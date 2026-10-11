"""Query-scope checks and expression rewrites using the PostgreSQL syntax tree."""
from __future__ import annotations

from sqlglot import exp, parse_one
from sqlglot.errors import ParseError


def _tree(sql: str):
    return parse_one(sql, read="postgres")


def _key(node):
    """Compare schema identifiers case-insensitively without changing literals."""
    return node.copy().transform(
        lambda n: exp.Identifier(this=n.name.lower(), quoted=False)
        if isinstance(n, exp.Identifier) else n
    ).sql(dialect="postgres")


def _period_key(node):
    """Recognize equivalent year transforms without equating month buckets."""
    while isinstance(node, (exp.Cast, exp.TryCast, exp.Nullif, exp.Paren)):
        node = node.this
    is_year = (
        isinstance(node, exp.Substring)
        and node.args.get("start") is not None and node.args["start"].name == "1"
        and node.args.get("length") is not None and node.args["length"].name == "4"
        or isinstance(node, exp.Extract) and node.this.name.upper() == "YEAR"
    )
    columns = list(node.find_all(exp.Column))
    if is_year and len(columns) == 1:
        return ("year", _key(columns[0]))
    return ("expression", _key(node))


def has_group_aggregate(expression: str) -> bool:
    try:
        tree = _tree(expression)
    except ParseError:
        return False
    return any(
        isinstance(n, exp.AggFunc) and not _window_aggregate(n)
        and not any(isinstance(a, exp.Select) for a in _ancestors(n))
        for n in tree.walk()
    )


def expressions_equivalent(left: str, right: str) -> bool:
    try:
        return _period_key(_tree(left)) == _period_key(_tree(right))
    except ParseError:
        return False


def has_date_year_predicate(sql: str, column: str, year: str) -> bool:
    try:
        tree = _tree(sql)
    except ParseError:
        return False
    for where in tree.find_all(exp.Where):
        for predicate in where.find_all(exp.EQ, exp.GTE, exp.GT, exp.LTE, exp.LT, exp.In, exp.Between, exp.Like, exp.ILike):
            if not any(c.name.lower() == column.lower() for c in predicate.this.find_all(exp.Column)):
                continue
            if isinstance(predicate, exp.In):
                operands = predicate.expressions
            elif isinstance(predicate, exp.Between):
                operands = [predicate.args.get("low"), predicate.args.get("high")]
            else:
                operands = [predicate.expression]
            if isinstance(predicate, (exp.Like, exp.ILike)):
                if any(isinstance(v, exp.Literal) and v.name == year + '%' for v in operands):
                    return True
                continue
            if any(isinstance(v, exp.Literal) and v.name.replace("-", "")[:4] == year for v in operands):
                return True
    return False


def _ancestors(node):
    while node.parent is not None:
        node = node.parent
        yield node


def _window_aggregate(node):
    for ancestor in _ancestors(node):
        if isinstance(ancestor, exp.Window):
            return True
        if isinstance(ancestor, (exp.AggFunc, exp.Select)):
            return False
    return False


def has_ranking_bound(sql: str, limit: int, *, partition_dimension: str | None = None) -> bool:
    """Recognize a top-N row-number filter in a reachable query scope.

    Partitioned cohorts use a rank predicate instead of a global LIMIT. The
    predicate must refer to an ordered ROW_NUMBER projection in its source,
    not an arbitrary numeric field or an unused CTE.
    """
    from sqlglot.optimizer.scope import Scope, build_scope

    try:
        root = build_scope(_tree(sql))
        if root is None:
            return False
        pending, seen = [root], set()
        while pending:
            scope = pending.pop()
            if id(scope) in seen:
                continue
            seen.add(id(scope))
            sources = {name.lower(): source for name, (_, source) in scope.selected_sources.items()}
            pending.extend(source for source in sources.values() if isinstance(source, Scope))
            pending.extend(scope.union_scopes)
            where = scope.expression.args.get('where')
            if where is None:
                continue

            def conjuncts(node):
                if isinstance(node, exp.And):
                    yield from conjuncts(node.this)
                    yield from conjuncts(node.expression)
                elif isinstance(node, exp.Paren):
                    yield from conjuncts(node.this)
                else:
                    yield node

            for predicate in conjuncts(where.this):
                if not isinstance(predicate, (exp.LTE, exp.LT)):
                    continue
                column, value = predicate.this, predicate.expression
                if not isinstance(column, exp.Column) or not isinstance(value, exp.Literal) or value.is_string:
                    continue
                boundary = limit if isinstance(predicate, exp.LTE) else limit + 1
                if value.name != str(boundary):
                    continue
                source = sources.get(column.table.lower()) if column.table else (
                    next(iter(sources.values())) if len(sources) == 1 else None
                )
                if not isinstance(source, Scope) or not isinstance(source.expression, exp.Select):
                    continue
                for projection in source.expression.expressions:
                    if not isinstance(projection, exp.Alias) or projection.alias.lower() != column.name.lower():
                        continue
                    window = projection.this
                    if (isinstance(window, exp.Window) and isinstance(window.this, exp.RowNumber)
                            and window.args.get('order') is not None):
                        if partition_dimension:
                            from .semantic_requirements import result_has_dimension
                            columns = [c.name for part in window.args.get('partition_by') or [] for c in part.find_all(exp.Column)]
                            if not result_has_dimension(columns, partition_dimension):
                                continue
                        return True
    except (ParseError, ValueError):
        return False
    return False


def widen_year_predicate(expression: str, year_expression: str, years: list[str]) -> str:
    """Replace restrictions on the compared year, preserving other predicates.

    Only the exact year expression is eligible. Another date's restriction,
    month selection, customer predicate, and nested query scopes are retained.
    """
    tree = _tree(expression)
    year = _period_key(_tree(year_expression))

    def rewrite(node):
        if isinstance(node, (exp.EQ, exp.In, exp.Between)) and _period_key(node.this) == year:
            return exp.In(
                this=node.this.copy(),
                expressions=[exp.Literal.string(value) for value in years],
            )
        return node

    # A nested SELECT has its own cohort and must not be widened here.
    if tree.find(exp.Select):
        raise ValueError("Structured filter contains a nested query; regenerate a scoped SQL plan")
    return tree.transform(rewrite).sql(dialect="postgres")


def qualify_expression(expression: str, tables: list[str]) -> str:
    """Quote verified physical references; leave aliases and literals untouched."""
    from ..data_catalog.physical import column_names, resolve_table_name

    try:
        tree = _tree(expression)
    except ParseError:
        return expression
    if tree.find(exp.Select):
        return expression  # Separate validation rejects undeclared query scopes.
    allowed = {t.lower() for t in tables}
    changed = False
    for column in tree.find_all(exp.Column):
        if column.table.lower() not in allowed:
            continue
        table = resolve_table_name(column.table)
        name = next((c for c in column_names(table) if c.lower() == column.name.lower()), None) if table else None
        if not name:
            continue
        if column.table != table or column.name != name or not all(
            column.args.get(k) is not None and column.args[k].args.get("quoted") for k in ("table", "this")
        ):
            column.set("table", exp.Identifier(this=table, quoted=True))
            column.set("this", exp.Identifier(this=name, quoted=True))
            changed = True
    return tree.sql(dialect="postgres") if changed else expression


def sql_structure_errors(sql: str, question: str = "") -> list[str]:
    """Reject ungrouped projections and contradictory CASE comparison scopes."""
    try:
        tree = _tree(sql)
    except ParseError as exc:
        return [f"Invalid PostgreSQL SQL syntax: {str(exc).splitlines()[0]}"]
    from .analytical_sql_safety import identity_period_errors, text_join_errors

    errors = text_join_errors(tree)
    from sqlglot.optimizer.scope import traverse_scope
    try:
        for scope in traverse_scope(tree):
            visible = set()
            ancestor = scope
            while ancestor is not None:
                visible.update(str(alias).lower() for alias in ancestor.selected_sources)
                ancestor = ancestor.parent
            for column in scope.columns:
                if column.table and column.table.lower() not in visible:
                    errors.append(f"Table qualifier is not bound in this SELECT scope: {column.table}")
    except Exception:
        errors.append("SQL table qualifiers could not be verified")
    if question:
        from .semantic_requirements import required_semantics

        if required_semantics(question).get("period_compare"):
            errors.extend(identity_period_errors(tree))
    for select in tree.find_all(exp.Select):
        projections = [p.this if isinstance(p, exp.Alias) else p for p in select.expressions]
        aggregates = [
            n for p in projections for n in p.find_all(exp.AggFunc)
            if n.find_ancestor(exp.Select) is select
            and not _window_aggregate(n)
        ]
        group = select.args.get("group")
        if aggregates or group:
            aliases = {p.alias: p.this for p in select.expressions if isinstance(p, exp.Alias)}
            groups = []
            for g in group.expressions if group else []:
                if isinstance(g, exp.Literal) and not g.is_string and g.name.isdigit():
                    pos = int(g.name) - 1
                    g = projections[pos] if 0 <= pos < len(projections) else g
                elif isinstance(g, exp.Column) and not g.table and g.name in aliases:
                    g = aliases[g.name]
                groups.append(_key(g))

            def check(node):
                if _key(node) in groups or isinstance(node, (exp.Subquery, exp.Select)):
                    return
                if isinstance(node, exp.AggFunc) and not _window_aggregate(node):
                    return
                if (isinstance(node, exp.Filter) and isinstance(node.this, exp.AggFunc)
                        and not _window_aggregate(node.this)):
                    # FILTER predicates belong to the aggregate input rows,
                    # not the grouped result projection.
                    return
                if isinstance(node, exp.Column):
                    errors.append(f"Ungrouped column in aggregate projection: {node.sql(dialect='postgres')}")
                    return
                if isinstance(node, exp.Star):
                    errors.append("Ungrouped wildcard in aggregate projection")
                    return
                for child in node.iter_expressions():
                    check(child)

            for projection in projections:
                check(projection)

        where = select.args.get("where")
        if not where:
            continue
        # Compare CASE period predicates with mandatory conjuncts in this scope.
        periods = {}
        for aggregate in aggregates:
            for equality in aggregate.find_all(exp.EQ):
                if isinstance(equality.expression, exp.Literal):
                    value = equality.expression.name
                    if len(value) == 4 and value.isdigit() and equality.this.find(exp.Column):
                        periods.setdefault(_period_key(equality.this), set()).add(value)

        def conjuncts(node):
            if isinstance(node, exp.And):
                yield from conjuncts(node.this)
                yield from conjuncts(node.expression)
            elif isinstance(node, exp.Paren):
                yield from conjuncts(node.this)
            else:
                yield node

        for predicate in conjuncts(where.this):
            required = periods.get(_period_key(predicate.this)) if isinstance(predicate, (exp.EQ, exp.In)) else None
            if not required or len(required) < 2:
                continue
            literals = [predicate.expression] if isinstance(predicate, exp.EQ) else predicate.expressions
            if all(isinstance(v, exp.Literal) for v in literals):
                allowed = {v.name for v in literals}
                if not required <= allowed:
                    errors.append("WHERE excludes a period required by this scope's comparison aggregates")
    return list(dict.fromkeys(errors))
