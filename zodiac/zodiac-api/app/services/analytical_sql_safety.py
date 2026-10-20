"""Protect fact grain and period identity using the governed SAP catalog."""
from __future__ import annotations

import os
from datetime import date
from itertools import combinations

from sqlglot import exp, parse_one
from sqlglot.errors import ParseError

from ..data_catalog.physical import column_names, resolve_table_name
from ..data_catalog.registry import get_table_entry
from .business_semantic_layer import ENTITIES


def _lookup_keys(table):
    entry = get_table_entry(table) or {}
    if "language" not in entry.get("grain", "").lower():
        return []
    columns = {c.lower(): c for c in column_names(table)}
    for entity in ENTITIES.values():
        if table.upper() in {t.upper() for t in entity.tables}:
            if all(key.lower() in columns for key in entity.business_keys):
                return [columns[key.lower()] for key in entity.business_keys]
    return []


def _terms(node):
    if isinstance(node, exp.And):
        yield from _terms(node.this)
        yield from _terms(node.expression)
    elif isinstance(node, exp.Paren):
        yield from _terms(node.this)
    elif node is not None:
        yield node


def _scope_predicates(select):
    where = select.args.get("where")
    if where:
        yield from _terms(where.this)
    for join in select.find_all(exp.Join):
        if join.find_ancestor(exp.Select) is select:
            yield from _terms(join.args.get("on"))


def _refs(node):
    return {(c.table.lower(), c.name.lower()) for c in node.find_all(exp.Column)}


def _identity_ref(node):
    while isinstance(node, (exp.Cast, exp.TryCast, exp.Trim, exp.Pad, exp.Paren)):
        node = node.this
    return (node.table.lower(), node.name.lower()) if isinstance(node, exp.Column) else None


def _date_restriction(predicate):
    """Known inclusive calendar intervals for mandatory date predicates."""
    from .sql_structure import _period_key

    if not isinstance(predicate, (exp.EQ, exp.In, exp.Between, exp.GTE, exp.GT, exp.LTE, exp.LT)):
        return None
    refs = _refs(predicate.this)
    if len(refs) != 1:
        return None
    is_year = _period_key(predicate.this)[0] == "year"
    node = predicate.this
    while isinstance(node, (exp.Cast, exp.TryCast, exp.Trim, exp.Nullif, exp.Paren)):
        node = node.this
    if not is_year and not isinstance(node, exp.Column):
        return None

    def bounds(value):
        if not isinstance(value, exp.Literal):
            return None
        raw = value.name.replace("-", "")
        try:
            if is_year and len(raw) == 4 and raw.isdigit():
                y = int(raw)
                return date(y, 1, 1).toordinal(), date(y, 12, 31).toordinal()
            if not is_year and len(raw) == 8 and raw.isdigit():
                day = date(int(raw[:4]), int(raw[4:6]), int(raw[6:])).toordinal()
                return day, day
        except ValueError:
            pass
        return None

    if isinstance(predicate, exp.In):
        intervals = [bounds(v) for v in predicate.expressions]
        if not intervals or any(v is None for v in intervals):
            return None
    elif isinstance(predicate, exp.Between):
        low, high = bounds(predicate.args["low"]), bounds(predicate.args["high"])
        if low is None or high is None:
            return None
        intervals = [(low[0], high[1])]
    else:
        interval = bounds(predicate.expression)
        if interval is None:
            return None
        low, high = interval
        if isinstance(predicate, exp.GTE):
            interval = (low, date.max.toordinal())
        elif isinstance(predicate, exp.GT):
            interval = (high + 1, date.max.toordinal())
        elif isinstance(predicate, exp.LTE):
            interval = (date.min.toordinal(), high)
        elif isinstance(predicate, exp.LT):
            interval = (date.min.toordinal(), low - 1)
        intervals = [interval]
    return next(iter(refs)), intervals


def _source_columns(tree, source):
    if isinstance(source, exp.Table):
        cte = next((c for c in tree.find_all(exp.CTE) if c.alias_or_name.lower() == source.name.lower()), None)
        if cte is None:
            return {c.lower() for c in column_names(source.name)}
        source = cte
    body = source.this if isinstance(source, (exp.CTE, exp.Subquery)) else None
    if isinstance(body, exp.Select) and not any(isinstance(e, exp.Star) or isinstance(e.this, exp.Star) for e in body.selects):
        return {e.alias_or_name.lower() for e in body.selects}
    return set()


def scope_master_joins_to_client(sql: str) -> str:
    """Add the client key to master-data joins that omit it.

    Customer, vendor and material numbers repeat across SAP clients, so a join
    on the number alone attaches every client's record to each fact row.
    """
    from ..data_catalog.registry import MASTER_DATA_TABLES

    try:
        tree = parse_one(sql, read="postgres")
    except ParseError:
        return sql
    master = {t.upper() for t in MASTER_DATA_TABLES}
    cte_names = {c.alias_or_name.lower() for c in tree.find_all(exp.CTE)}
    changed = False
    for select in list(tree.find_all(exp.Select)):
        from_ = select.args.get("from") or select.args.get("from_")
        joins = select.args.get("joins") or []
        sources = {node.alias_or_name.lower(): node for node in ([from_.this] if from_ else []) + [j.this for j in joins]}
        for join in joins:
            target, on = join.this, join.args.get("on")
            # Language-keyed texts are reduced to one row per key by
            # canonicalize_text_joins, so only other master data needs this.
            if (on is None or not isinstance(target, exp.Table) or target.name.lower() in cte_names
                    or target.name.upper() not in master or _lookup_keys(target.name)
                    or "mandt" not in {c.lower() for c in column_names(target.name)}):
                continue
            alias = target.alias_or_name
            if (alias.lower(), "mandt") in _refs(on):
                continue
            partner = None
            for term in _terms(on):
                if not isinstance(term, exp.EQ):
                    continue
                for side, other in ((term.this, term.expression), (term.expression, term.this)):
                    others = {t for t, _ in _refs(other)}
                    if {t for t, _ in _refs(side)} == {alias.lower()} and len(others) == 1 and alias.lower() not in others:
                        candidate = next(iter(others))
                        if candidate in sources and "mandt" in _source_columns(tree, sources[candidate]):
                            partner = sources[candidate].alias_or_name
                            break
                if partner:
                    break
            if not partner:
                continue
            join.set("on", exp.and_(on, exp.EQ(this=exp.column("mandt", table=alias, quoted=True),
                                               expression=exp.column("mandt", table=partner, quoted=True))))
            changed = True
    return tree.sql(dialect="postgres") if changed else sql


def canonicalize_text_joins(sql: str) -> str:
    """Choose one deterministic label row per joined key before facts join it.

    Explicit text filters are applied before selection. Projected language is
    retained as a facet. Duplicate labels within a language cannot multiply
    a fact or consume a ranking slot. Language preference is configurable.
    """
    try:
        tree = parse_one(sql, read="postgres")
    except ParseError:
        return sql
    changed = False
    preferred = [s.strip().upper() for s in os.getenv("AI_TEXT_LANGUAGES", "E,EN").split(",") if s.strip()]
    for select in list(tree.find_all(exp.Select)):
        predicates = list(_scope_predicates(select))
        for join in list(select.find_all(exp.Join)):
            if join.find_ancestor(exp.Select) is not select or not isinstance(join.this, exp.Table):
                continue
            table = join.this
            keys = _lookup_keys(table.name)
            if not keys:
                continue
            columns = column_names(table.name)
            alias = table.alias_or_name
            partition = []
            for key in keys:
                ref = (alias.lower(), key.lower())
                matched = None
                for predicate in predicates:
                    if isinstance(predicate, exp.EQ):
                        for side, other in ((predicate.this, predicate.expression), (predicate.expression, predicate.this)):
                            if _identity_ref(side) == ref and _refs(other) and all(t != alias.lower() for t, _ in _refs(other)):
                                matched = side.copy()
                                break
                if matched is None:
                    break
                partition.append(matched)
            if len(partition) != len(keys):
                continue  # Cannot prove the lookup's complete key is joined.
            language = next((c for c in columns if c.lower() == "spras"), None)
            if language and any(
                (alias.lower(), language.lower()) in _refs(projection)
                for projection in select.expressions
            ):
                partition.append(exp.column(language, table=alias, quoted=True))
            client = next((c for c in columns if c.lower() == "mandt"), None)
            if client and any(
                isinstance(p, exp.EQ) and (alias.lower(), client.lower()) in _refs(p)
                and len({t for t, _ in _refs(p)}) > 1 for p in predicates
            ):
                partition.append(exp.column(client, table=alias, quoted=True))

            def localize(node):
                node = node.copy()
                for c in node.find_all(exp.Column):
                    if c.table.lower() == alias.lower():
                        c.set("table", exp.to_identifier("label_source", quoted=True))
                return node

            text_filters = [localize(p) for p in predicates if _refs(p) and all(t == alias.lower() for t, _ in _refs(p))]
            order = []
            if language:
                lang = exp.column(language, table="label_source", quoted=True)
                normalized = exp.Upper(this=exp.Trim(this=exp.Cast(this=lang.copy(), to=exp.DataType.build("TEXT"))))
                preference = exp.Case(ifs=[exp.If(
                    this=exp.EQ(this=normalized.copy(), expression=exp.Literal.string(value)),
                    true=exp.Literal.number(i),
                ) for i, value in enumerate(preferred)], default=exp.Literal.number(len(preferred)))
                order.extend([exp.Ordered(this=preference), exp.Ordered(this=lang)])
            order.extend(exp.Ordered(this=exp.column(c, table="label_source", quoted=True)) for c in sorted(columns))
            rank_name = "_lookup_row"
            while rank_name.lower() in {c.lower() for c in columns}:
                rank_name += "_"
            rank = exp.Window(this=exp.RowNumber(), partition_by=[localize(p) for p in partition], order=exp.Order(expressions=order))
            inner = exp.select("label_source.*", exp.alias_(rank, rank_name, quoted=True)).from_(
                exp.Table(this=exp.to_identifier(resolve_table_name(table.name) or table.name, quoted=True),
                          alias=exp.TableAlias(this=exp.to_identifier("label_source", quoted=True)))
            )
            if text_filters:
                inner = inner.where(exp.and_(*text_filters))
            lookup = exp.select(*[exp.column(c, table="label_rows", quoted=True) for c in columns]).from_(
                inner.subquery("label_rows")
            ).where(exp.EQ(this=exp.column(rank_name, table="label_rows", quoted=True), expression=exp.Literal.number(1)))
            join.set("this", exp.Subquery(this=lookup, alias=exp.TableAlias(this=exp.to_identifier(alias, quoted=True))))
            changed = True
    return tree.sql(dialect="postgres") if changed else sql


def text_join_errors(tree) -> list[str]:
    errors = []
    for join in tree.find_all(exp.Join):
        if isinstance(join.this, exp.Table) and _lookup_keys(join.this.name):
            errors.append(f"Text lookup {join.this.name} must return one row per joined entity key before joining facts")
    return list(dict.fromkeys(errors))


def identity_period_errors(tree) -> list[str]:
    """Reject comparison of the same dated document with itself in other years."""
    from .sql_structure import _period_key

    errors = []
    for select in tree.find_all(exp.Select):
        aliases = {t.alias_or_name.lower(): t.name for t in select.find_all(exp.Table)
                   if t.find_ancestor(exp.Select) is select}
        parents = {}
        def root(node):
            parents.setdefault(node, node)
            if parents[node] != node:
                parents[node] = root(parents[node])
            return parents[node]
        periods = {}
        for predicate in _scope_predicates(select):
            if isinstance(predicate, exp.EQ):
                left, right = _identity_ref(predicate.this), _identity_ref(predicate.expression)
                if left and right:
                    parents[root(left)] = root(right)
            restriction = _date_restriction(predicate)
            if restriction:
                ref, intervals = restriction
                previous = periods.get(ref, [(date.min.toordinal(), date.max.toordinal())])
                periods[ref] = [
                    (max(a, c), min(b, d)) for a, b in previous for c, d in intervals
                    if max(a, c) <= min(b, d)
                ]
        grouped_refs = set()
        group = select.args.get("group")
        aliases_to_projection = {p.alias: p.this for p in select.expressions if isinstance(p, exp.Alias)}
        for field in group.expressions if group else []:
            if isinstance(field, exp.Column) and not field.table and field.name in aliases_to_projection:
                field = aliases_to_projection[field.name]
            elif isinstance(field, exp.Literal) and not field.is_string and field.name.isdigit():
                index = int(field.name) - 1
                if 0 <= index < len(select.expressions):
                    field = select.expressions[index]
            grouped_refs.update(_refs(field))
        compared_years = {}
        for aggregate in select.find_all(exp.AggFunc):
            if aggregate.find_ancestor(exp.Select) is not select:
                continue
            for predicate in aggregate.find_all(exp.EQ):
                restriction = _date_restriction(predicate)
                if restriction and _period_key(predicate.this)[0] == "year":
                    ref, intervals = restriction
                    compared_years.setdefault(ref, set()).update(intervals)
        for entity in ENTITIES.values():
            for physical in entity.tables:
                grain = (get_table_entry(physical) or {}).get("grain", "").lower()
                if "item" in grain and len(entity.business_keys) == 1:
                    continue  # Catalog describes header identity, not an item key.
                matching = [alias for alias, table in aliases.items() if table.upper() == physical.upper()]
                for alias in matching:
                    if all(any(root((alias, key.lower())) == root(ref) for ref in grouped_refs) for key in entity.business_keys):
                        if any(len(compared_years.get((alias, field.lower()), set())) > 1 for field in entity.date_fields):
                            errors.append(f"Invalid period comparison: grouping by unique dated {physical} document identity cannot align different periods; use an entity grain or an explicit cohort")
                for a, b in combinations(matching, 2):
                    if not all(root((a, k.lower())) == root((b, k.lower())) for k in entity.business_keys):
                        continue
                    for date_field in entity.date_fields:
                        first, second = periods.get((a, date_field.lower())), periods.get((b, date_field.lower()))
                        if first is not None and second is not None and not any(max(lo_a, lo_b) <= min(hi_a, hi_b) for lo_a, hi_a in first for lo_b, hi_b in second):
                            errors.append(f"Invalid period comparison: {physical} aliases share document identity but require disjoint years on {date_field}")
    return list(dict.fromkeys(errors))
