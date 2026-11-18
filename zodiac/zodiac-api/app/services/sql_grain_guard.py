"""
Declare fact / join / aggregation grain for deep SQL.

Monetary queries must stay on billing_item (vbrp) and only attach N:1 dimensions.
MATNR bridges to purchase are never allowed to multiply NETWR/WAVWR.
Inventory snapshot tables (MBEW/MARD) must never join into VBRP before SUM(NETWR).
"""
from __future__ import annotations

import re
from typing import Any, Dict, List

SAFE_MONETARY_JOINS = {
    ("vbrp", "VBRK", "vbeln"),
    ("VBRK", "KNA1", "kunag/kunnr"),
    ("vbrp", "MAKT", "matnr"),
    ("vbrp", "MARA", "matnr"),
    ("KNA1", "T016T", "brsch"),
}

UNSAFE_MONETARY_JOINS = {
    "EKPO",
    "EKKO",
    "LFA1",
    "VBFA",
    "LIPS",
    "LIKP",
    "KONV",
    "BSEG",
    "FAGLFLEXA",
    "COEP",
}

_INV_JOIN_RE = re.compile(r'\bJOIN\s+"?(MBEW|MARD)"?', re.I)


def grain_contract(intent: str, dimensions: List[str]) -> Dict[str, Any]:
    dims = set(dimensions or [])
    if intent in {"suppliers_of_selection", "purchase_cost_by_product", "supplier_concentration"}:
        return {
            "fact_grain": "po_item",
            "join_grain": "EKPO⋈EKKO⋈LFA1",
            "aggregation_grain": "supplier" if intent == "supplier_concentration" else "supplier/product",
            "monetary_source": "EKPO.NETWR (purchase value, not invoice COGS)",
            "fanout_safe": True,
        }
    if intent in {"inventory_analysis"}:
        return {
            "fact_grain": "material_valuation",
            "join_grain": "MBEW GROUP BY MATNR[+BWKEY]",
            "aggregation_grain": "product / valuation_area",
            "monetary_source": "MBEW.SALK3 snapshot; qty = MBEW.LBKUM",
            "fanout_safe": True,
            "note": "Snapshot — not billing grain. Do not join into VBRP before aggregating.",
        }
    if intent in {"inventory_sales_comparison", "inventory_risk_analysis"}:
        grain = "product_group" if "product_group" in dims else "product"
        return {
            "fact_grain": "sales_agg ⋈ inventory_agg",
            "join_grain": f"independent GROUP BY {grain} then JOIN",
            "aggregation_grain": grain,
            "monetary_source": "VBRP.NETWR/WAVWR/FKIMG independently of MBEW.SALK3/LBKUM",
            "fanout_safe": True,
            "note": "Never FROM vbrp JOIN MARD/MBEW SUM(NETWR).",
        }
    if intent in {"inventory_by_plant"}:
        return {
            "fact_grain": "storage_location_stock",
            "join_grain": "MARD GROUP BY MATNR+WERKS (or WERKS)",
            "aggregation_grain": "plant_code",
            "monetary_source": "MARD.LABST unrestricted qty — plant codes, no T001W text",
            "fanout_safe": True,
            "note": "Inventory is not customer/region owned. Sales plant grain only via independent VBRP.WERKS agg.",
        }
    if any(d in dims for d in ("supplier",)):
        return {
            "fact_grain": "po_item",
            "join_grain": "material bridge",
            "aggregation_grain": ",".join(sorted(dims)),
            "monetary_source": "purchase NETWR only",
            "fanout_safe": True,
            "note": "Do not join suppliers into billing amount queries",
        }
    # Customer / industry / country sales totals should group billing documents
    # (or items) to that dimension — not rank individual billing lines.
    dimension_totals = bool(dims & {"customer", "industry", "country", "currency", "year"})
    item_dimensions = bool(dims & {"product", "material", "product_group"})
    if dimension_totals and not item_dimensions:
        return {
            "fact_grain": "billing_header",
            "join_grain": "VBRK (+ N:1 KNA1/T016T)",
            "aggregation_grain": ",".join(sorted(dims)) or "customer,currency",
            "monetary_source": "VBRK.NETWR grouped to the requested dimensions",
            "fanout_safe": True,
            "note": "Group all matching billing documents per dimension; do not return ranked individual billing items unless the question asks for lines/items.",
        }
    return {
        "fact_grain": "billing_item",
        "join_grain": "vbrp⋈VBRK (+ N:1 KNA1/MAKT/MARA)",
        "aggregation_grain": ",".join(sorted(dims)) or "product,currency",
        "monetary_source": "vbrp.NETWR / vbrp.WAVWR",
        "fanout_safe": True,
    }


def _independent_measure_scopes(sql: str) -> bool:
    """Prove separate fact aggregates cannot multiply each other's measures.

    Physical monetary tables are aggregated in independent SELECT scopes. A
    later scope can join those aggregates only on all their grouping keys and
    cannot SUM/AVG the joined amounts again. EXISTS filters do not expand rows.
    Names of CTEs and output aliases have no role in this proof.
    """
    try:
        from sqlglot import exp, parse_one
        from sqlglot.optimizer.scope import Scope, traverse_scope

        scopes = list(traverse_scope(parse_one(sql, read="postgres")))
        facts = {"VBAK", "VBAP", "VBRK", "VBRP", "EKPO", "MBEW", "MARD"}
        aggregate_scopes = {}
        for scope in scopes:
            select = scope.expression
            if not isinstance(select, exp.Select):
                continue
            sources = scope.selected_sources
            physical = {alias: src.name.upper() for alias, (_, src) in sources.items()
                        if isinstance(src, exp.Table)}
            aggregates = [n for n in select.find_all(exp.AggFunc)
                          if n.find_ancestor(exp.Select) is select and not n.find_ancestor(exp.Window)]
            monetary = [n for n in aggregates if any(
                c.name.upper() in {"NETWR", "WAVWR", "SALK3", "DMBTR", "WRBTR"}
                for c in n.find_all(exp.Column))]
            if monetary:
                if len(physical) != 1 or len([t for t in physical.values() if t in facts]) != 1:
                    return False
                # Raw flow/schedule/inventory joins can duplicate a physical
                # amount even when they contribute no money to SELECT.
                if any(t in set(UNSAFE_MONETARY_JOINS) | {"VBEP"} for t in physical.values()):
                    return False
                # A derived row source is unproven here; require EXISTS rather
                # than an ordinary join to a possibly repeating link table.
                if any(isinstance(src, Scope) for _, src in sources.values()):
                    return False
                group = select.args.get("group")
                group_keys = set()
                for key in (group.expressions if group else []):
                    projected = next((p for p in select.expressions
                                      if (p.this if isinstance(p, exp.Alias) else p) == key), None)
                    if projected is None or not projected.alias_or_name:
                        return False
                    group_keys.add(projected.alias_or_name.lower())
                aggregate_scopes[id(scope)] = group_keys

        if len(aggregate_scopes) < 2:
            return False
        combined = False
        for scope in scopes:
            select = scope.expression
            if not isinstance(select, exp.Select):
                continue
            derived = {alias: aggregate_scopes[id(src)] for alias, (_, src) in scope.selected_sources.items()
                       if isinstance(src, Scope) and id(src) in aggregate_scopes}
            if len(derived) < 2:
                continue
            combined = True
            if any(n.find_ancestor(exp.Select) is select for n in select.find_all(exp.AggFunc)):
                return False
            if len(derived) != len(scope.selected_sources):
                return False
            covered = {alias: set() for alias in derived}
            for join in select.args.get("joins") or []:
                on = join.args.get("on")
                if on is None:
                    # Scalar independent aggregates have exactly one row.
                    if all(not keys for keys in derived.values()):
                        continue
                    return False
                # OR conditions do not prove a unique equality join.
                if on.find(exp.Or):
                    return False
                for equality in on.walk():
                    if not isinstance(equality, (exp.EQ, exp.NullSafeEQ)):
                        continue
                    left, right = equality.this, equality.expression
                    if (isinstance(left, exp.Column) and isinstance(right, exp.Column)
                            and left.table in derived and right.table in derived
                            and left.table != right.table):
                        covered[left.table].add(left.name.lower())
                        covered[right.table].add(right.name.lower())
            if any(not keys <= covered[alias] for alias, keys in derived.items()):
                return False
        return combined
    except Exception:
        return False


def _independently_aggregated_row_ctes(sql: str) -> bool:
    """Prove row CTEs keep each monetary fact separate until aggregation.

    Generated SQL often stages document identity, header attributes, and
    verified links in row CTEs before summing order and invoice facts. Trace
    those CTEs to their SAP document families, then require one family per
    aggregate and every aggregate grouping key on the comparison join.
    """
    try:
        from sqlglot import exp, parse_one
        from sqlglot.optimizer.scope import Scope, traverse_scope

        scopes = list(traverse_scope(parse_one(sql, read="postgres")))
        order_tables = {"VBAK", "VBAP"}
        invoice_tables = {"VBRK", "VBRP"}
        document_tables = order_tables | invoice_tables
        families: dict[int, set[str]] = {}
        row_safe: dict[int, bool] = {}
        aggregates: dict[int, tuple[str, set[str]]] = {}

        def unique_output_keys(source) -> set[str]:
            if not isinstance(source, Scope) or not isinstance(source.expression, exp.Select):
                return set()
            select = source.expression
            group = select.args.get("group")
            if group:
                result = set()
                for key in group.expressions:
                    projection = next((p for p in select.expressions
                                       if (p.this if isinstance(p, exp.Alias) else p) == key), None)
                    if projection is None or not projection.alias_or_name:
                        return set()
                    result.add(projection.alias_or_name.lower())
                return result
            if select.args.get("distinct"):
                return {p.alias_or_name.lower() for p in select.expressions if p.alias_or_name}
            return set()

        # traverse_scope is bottom-up, so each CTE's source lineage is ready
        # when its consuming scope is visited.
        for scope in scopes:
            select = scope.expression
            if not isinstance(select, exp.Select):
                continue
            sources = scope.selected_sources
            source_families: dict[str, set[str]] = {}
            for alias, (_, source) in sources.items():
                if isinstance(source, exp.Table):
                    name = source.name.upper()
                    if name in order_tables:
                        source_families[alias] = {"order"}
                    elif name in invoice_tables:
                        source_families[alias] = {"invoice"}
                    else:
                        source_families[alias] = set()
                elif isinstance(source, Scope):
                    source_families[alias] = set(families.get(id(source), set()))

            lineage = set().union(*source_families.values()) if source_families else set()
            families[id(scope)] = lineage

            # Row CTE joins are allowed only when each added side is proven
            # unique on the equality keys. EXISTS/subqueries are separate
            # scopes and cannot multiply the enclosing row set.
            safe_rows = True
            if select.args.get("joins"):
                for join in select.args["joins"]:
                    target_alias = join.this.alias_or_name
                    target = sources.get(target_alias, (None, None))[1]
                    unique_keys = unique_output_keys(target)
                    on = join.args.get("on")
                    covered = set()
                    if on is not None and not on.find(exp.Or):
                        for equality in [*on.find_all(exp.EQ), *on.find_all(exp.NullSafeEQ)]:
                            left, right = equality.this, equality.expression
                            # A unique target key remains cardinality-safe when
                            # the source side normalizes its key (for example,
                            # LPAD(TRIM(source.kunnr), 10, '0')). The proof only
                            # needs the target's complete unique key in equality.
                            if isinstance(left, exp.Column) and left.table == target_alias:
                                covered.add(left.name.lower())
                            if isinstance(right, exp.Column) and right.table == target_alias:
                                covered.add(right.name.lower())
                    if not unique_keys or not unique_keys <= covered:
                        safe_rows = False
                        break
            row_safe[id(scope)] = safe_rows

            agg_nodes = [n for n in select.find_all(exp.AggFunc)
                         if n.find_ancestor(exp.Select) is select
                         and not n.find_ancestor(exp.Window)]
            monetary_families = {
                family
                for agg in agg_nodes
                for column in agg.find_all(exp.Column)
                for family in (
                    source_families.get(column.table, set())
                    if column.table else
                    (next(iter(source_families.values())) if len(source_families) == 1 else set())
                )
            }
            if not monetary_families:
                continue
            # This proof is deliberately limited to a single staged row CTE;
            # direct fact aggregation and richer safe shapes are handled by
            # the existing proofs above.
            if (len(monetary_families) != 1 or len(sources) != 1
                    or not row_safe.get(id(next(iter(sources.values()))[1]), False)):
                continue
            group = select.args.get("group")
            if not group:
                continue
            keys: set[str] = set()
            for key in group.expressions:
                projection = next((p for p in select.expressions
                                   if (p.this if isinstance(p, exp.Alias) else p) == key), None)
                if projection is None or not projection.alias_or_name:
                    keys.clear()
                    break
                keys.add(projection.alias_or_name.lower())
            if keys:
                aggregates[id(scope)] = (next(iter(monetary_families)), keys)

        for scope in scopes:
            select = scope.expression
            if not isinstance(select, exp.Select):
                continue
            sources = scope.selected_sources
            derived = {alias: aggregates[id(source)]
                       for alias, (_, source) in sources.items()
                       if isinstance(source, Scope) and id(source) in aggregates}
            if len(derived) < 2 or len({family for family, _ in derived.values()}) < 2:
                continue
            if len(derived) != len(sources) or any(
                n.find_ancestor(exp.Select) is select for n in select.find_all(exp.AggFunc)
            ):
                continue
            covered = {alias: set() for alias in derived}
            valid = True
            for join in select.args.get("joins") or []:
                on = join.args.get("on")
                if on is None or on.find(exp.Or):
                    valid = False
                    break
                for equality in on.walk():
                    if not isinstance(equality, (exp.EQ, exp.NullSafeEQ)):
                        continue
                    left, right = equality.this, equality.expression
                    if (isinstance(left, exp.Column) and isinstance(right, exp.Column)
                            and left.table in derived and right.table in derived
                            and left.table != right.table):
                        covered[left.table].add(left.name.lower())
                        covered[right.table].add(right.name.lower())
            if valid and all(keys <= covered[alias]
                             for alias, (_, keys) in derived.items()):
                return True
        return False
    except Exception:
        return False


def _document_measure_lineage(sql: str) -> bool:
    """Follow document identities through row CTEs and pre-aggregation.

    A billing item may attach its unique header before aggregation. Later
    document comparisons may list each aggregate group, but cannot re-sum
    amounts across that join. Every join must prove its target identity or,
    for a final row listing, expose the complete aggregate identity.
    """
    try:
        from sqlglot import exp, parse_one
        from sqlglot.optimizer.scope import Scope, build_scope

        primary = {"VBAK": {"MANDT", "VBELN"}, "VBRK": {"MANDT", "VBELN"},
                   "VBAP": {"MANDT", "VBELN", "POSNR"}, "VBRP": {"MANDT", "VBELN", "POSNR"}}
        money = {"NETWR", "WAVWR"}
        root = build_scope(parse_one(sql, read="postgres"))

        def describe(scope):
            select = scope.expression
            if not isinstance(select, exp.Select) or select.find(exp.Window):
                raise ValueError("unproven scope")
            sources = scope.selected_sources
            infos = {}
            for alias, (_, source) in sources.items():
                if isinstance(source, Scope):
                    infos[alias] = describe(source)
                elif isinstance(source, exp.Table) and source.name.upper() in primary:
                    infos[alias] = (primary[source.name.upper()], money, False)
                else:
                    raise ValueError("unproven source")
            if not infos:
                raise ValueError("no source")
            projections = {p.alias_or_name.upper(): p.this if isinstance(p, exp.Alias) else p
                           for p in select.expressions}
            # Keys survive only an explicit, unchanged column projection.
            projected = {a: {} for a in infos}
            measure_outputs = set()
            aggregate_nodes = [n for n in select.find_all(exp.AggFunc)
                               if n.find_ancestor(exp.Select) is select]
            measure_sources = set()
            for name, value in projections.items():
                if isinstance(value, exp.Column) and value.table in infos:
                    projected[value.table][value.name.upper()] = name
                refs = [c for c in value.find_all(exp.Column)
                        if c.table in infos and c.name.upper() in infos[c.table][1]]
                if refs:
                    measure_outputs.add(name)
                    measure_sources.update(c.table for c in refs)
                    if aggregate_nodes and any(infos[c.table][2] for c in refs):
                        raise ValueError("reaggregated monetary fact")
            base = next(iter(infos))
            equivalent = set()
            for join in select.args.get('joins') or []:
                target = join.this.alias_or_name
                on = join.args.get('on')
                if target not in infos or on is None or on.find(exp.Or):
                    raise ValueError("unproven join")
                covered = {a: set() for a in infos}
                def conjuncts(node):
                    if isinstance(node, exp.Paren):
                        return conjuncts(node.this)
                    if isinstance(node, exp.And):
                        return conjuncts(node.this) + conjuncts(node.expression)
                    return [node]
                for atom in conjuncts(on):
                    if isinstance(atom, (exp.EQ, exp.NullSafeEQ)) and isinstance(atom.this, exp.Column) and isinstance(atom.expression, exp.Column):
                        a, b = atom.this, atom.expression
                        if a.table in infos and b.table in infos and a.table != b.table:
                            covered[a.table].add(a.name.upper())
                            covered[b.table].add(b.name.upper())
                            equivalent.add(frozenset({(a.table, a.name.upper()), (b.table, b.name.upper())}))
                if join.args.get('side') in {'RIGHT', 'FULL'} and (
                        not infos[target][0] <= covered[target] or not infos[base][0] <= covered[base]):
                    raise ValueError("outer join must preserve both unique grains")
                if not infos[target][0] <= covered[target]:
                    # An order can have several currency groups. Only a final,
                    # non-aggregate listing exposing every group may show them.
                    if (scope is not root or aggregate_nodes or not infos[target][2] or infos[base][2]
                            or not infos[base][0] <= covered[base]
                            or not infos[target][0] <= set(projected[target]) | covered[target]):
                        raise ValueError("multiplying monetary join")
                if aggregate_nodes and any(a != base for a in measure_sources):
                    raise ValueError("measure not on base fact")
                if isinstance(sources[target][1], exp.Table) and target in measure_sources:
                    # A header attached to items repeats its value on every
                    # item, even if SUM happens only in a later CTE.
                    raise ValueError("header measure copied to repeating rows")
            if aggregate_nodes or select.args.get('group'):
                group = select.args.get('group')
                groups = list(group.expressions) if group else []
                keys = set()
                for expression in groups:
                    name = next((n for n, p in projections.items() if p == expression), None)
                    if name is None:
                        raise ValueError("hidden grouping key")
                    keys.add(name)
                return keys, measure_outputs, bool(measure_outputs)
            keys = infos[base][0]
            for name, value in projections.items():
                if isinstance(value, exp.Coalesce):
                    columns = list(value.find_all(exp.Column))
                    if len(columns) == 2 and frozenset((c.table, c.name.upper()) for c in columns) in equivalent:
                        for column in columns:
                            projected[column.table][column.name.upper()] = name
            if not keys <= set(projected[base]):
                raise ValueError("hidden document identity")
            return {projected[base][k] for k in keys}, measure_outputs, infos[base][2]

        info = describe(root)
        return bool(info[1])
    except Exception:
        return False


def _single_fact_with_existence_filter(sql: str) -> bool:
    """Allow a single monetary fact to be filtered by correlated EXISTS.

    A NOT EXISTS anti-join against billing items is a common way to list
    unbilled order items. It does not bring billing-item rows into the result
    grain, so it must not be confused with joining two monetary facts.
    Require exactly one measured SAP fact family and require every occurrence
    of the other monetary family to be under EXISTS/NOT EXISTS.
    """
    try:
        from sqlglot import exp, parse_one
        from sqlglot.optimizer.scope import traverse_scope

        tree = parse_one(sql, read="postgres")
        families = {"VBAK": "order", "VBAP": "order", "VBRK": "invoice", "VBRP": "invoice"}
        measured: set[str] = set()
        for scope in traverse_scope(tree):
            select = scope.expression
            if not isinstance(select, exp.Select):
                continue
            local_tables = {
                alias: source.name.upper()
                for alias, (_, source) in scope.selected_sources.items()
                if isinstance(source, exp.Table)
            }
            for column in select.find_all(exp.Column):
                if column.name.upper() not in {"NETWR", "WAVWR"}:
                    continue
                table_name = local_tables.get(column.table)
                family = families.get(table_name or "")
                if family:
                    measured.add(family)
        if len(measured) != 1:
            return False
        measured_family = next(iter(measured))
        for table in tree.find_all(exp.Table):
            if table.name.upper() in set(UNSAFE_MONETARY_JOINS) | {"MBEW", "MARD", "VBEP"}:
                if not table.find_ancestor(exp.Exists):
                    return False
            family = families.get(table.name.upper())
            if family and family != measured_family:
                if not table.find_ancestor(exp.Exists):
                    return False
        return True
    except Exception:
        return False


def _identified_document_values(sql: str) -> bool:
    """Document-pair listings can display values without summing repeated facts.

    Both physical document identities must be projected, no row-expanding link
    source or aggregate is permitted, and money must be a single-source value.
    Approved relationship validation is still required separately.
    """
    try:
        from sqlglot import exp, parse_one
        from sqlglot.optimizer.scope import traverse_scope

        root = parse_one(sql, read="postgres")
        scope = next(s for s in traverse_scope(root) if s.expression is root)
        if not isinstance(root, exp.Select) or root.find(exp.AggFunc) or root.find(exp.Window):
            return False
        keys = {"VBAK": {"VBELN"}, "VBRK": {"VBELN"},
                "VBAP": {"VBELN", "POSNR"}, "VBRP": {"VBELN", "POSNR"}}
        sources = scope.selected_sources
        if len(sources) != 2 or any(not isinstance(src, exp.Table) or src.name.upper() not in keys
                                    for _, src in sources.values()):
            return False
        projected = {alias: set() for alias in sources}
        for projection in root.expressions:
            value = projection.this if isinstance(projection, exp.Alias) else projection
            if isinstance(value, exp.Column) and value.table in projected:
                projected[value.table].add(value.name.upper())
            money = [c for c in value.find_all(exp.Column) if c.name.upper() in {"NETWR", "WAVWR"}]
            if money and (len(money) != 1 or any(isinstance(n, (exp.Binary, exp.Subquery)) for n in value.walk())):
                return False
        return all(keys[src.name.upper()] <= projected[alias] for alias, (_, src) in sources.items())
    except Exception:
        return False


def sql_has_unsafe_monetary_fanout(sql: str) -> bool:
    s = (sql or "").upper()
    raw = sql or ""
    if "NETWR" not in s and "WAVWR" not in s:
        return False
    if _independent_measure_scopes(sql):
        return False
    if _independently_aggregated_row_ctes(sql):
        return False
    if _identified_document_values(sql):
        return False
    if _document_measure_lineage(sql):
        return False
    if _single_fact_with_existence_filter(sql):
        return False
    has_billing = "VBRP" in s or "VBRK" in s
    # See below: this specific template proves VBFA/VBRP relationships first,
    # then aggregates linked orders back to one row per billing document.
    linked_order_invoice_grain = (
        re.search(r"\binvoice_cohort\s+AS\s*\(", raw, re.I)
        and re.search(r"\border_periods\s+AS\s*\(", raw, re.I)
        and re.search(
            r'GROUP\s+BY\s+l\."billing_document"\s*,\s*i\."currency"', raw, re.I
        )
        and re.search(
            r'LEFT\s+JOIN\s+"?order_periods"?\s+p\s+ON\s+p\."billing_document"\s*=\s*i\."billing_document"',
            raw,
            re.I,
        )
        and not re.search(r"\b(?:SUM|AVG)\s*\(\s*p\.\"order_amount_", raw, re.I)
    )
    if has_billing:
        for t in UNSAFE_MONETARY_JOINS:
            if t in s and not (linked_order_invoice_grain and t == "VBFA"):
                return True
        if _INV_JOIN_RE.search(raw):
            return True
    # Purchase NETWR joined to inventory snapshot before aggregation.
    if "EKPO" in s and _INV_JOIN_RE.search(raw):
        return True
    # The linked-order comparison template keeps monetary sources separate:
    # invoice_cohort has one row per billing document, order_periods aggregates
    # linked order amounts back to that same billing-document grain, and the
    # final projection joins the two one-to-one without aggregating either
    # amount across the other source. This is safe despite naming both SAP
    # money-bearing tables in separate CTEs.
    if linked_order_invoice_grain:
        return False
    # Sales-order monetary grain must not mix with billing or schedule-line fan-out.
    has_order = "VBAK" in s or "VBAP" in s
    if has_order and has_billing:
        return True
    if "VBEP" in s and "VBAP" in s and "NETWR" in s:
        return True
    return False
