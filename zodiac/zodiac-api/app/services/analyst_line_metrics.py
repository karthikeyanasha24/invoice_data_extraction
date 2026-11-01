"""Keep a requested individual billing-line extreme distinct from group totals."""
import re


def billing_line_extreme(question):
    q = question or ""
    if (not re.search(r"\b(?:billing|invoice)\b", q, re.I)
            or not re.search(r"\b(?:lines?|items?)\b", q, re.I)
            or re.search(r"\b(?:sum|totals?|aggregated?)\b", q, re.I)):
        return None
    if re.search(r"\b(?:lowest|smallest|minimum)\b", q, re.I):
        return "MIN"
    if re.search(r"\b(?:highest|largest|maximum)\b", q, re.I):
        return "MAX"
    return None


def billing_line_metric_issues(question, sql):
    wanted = billing_line_extreme(question)
    if not wanted or not sql:
        return []
    from sqlglot import exp, parse_one
    from sqlglot.optimizer.scope import Scope, build_scope
    from .agent_query_contract import output_lineage
    root = build_scope(parse_one(sql, read="postgres"))

    def operations(scope, value, aggregate=None):
        if isinstance(value, exp.AggFunc):
            aggregate = aggregate or type(value).__name__.upper()
        if isinstance(value, exp.Column):
            source = scope.sources.get(value.table)
            if source is None and not value.table and len(scope.selected_sources) == 1:
                source = next(iter(scope.selected_sources.values()))[1]
            if isinstance(source, exp.Table):
                return {aggregate or "RAW"} if source.name.upper() == "VBRP" and value.name.lower() == "netwr" else set()
            if isinstance(source, Scope):
                projected = next((p for p in source.expression.selects if p.alias_or_name.lower() == value.name.lower()), None)
                if projected is not None:
                    return operations(source, projected.this if isinstance(projected, exp.Alias) else projected, aggregate)
            return set()
        return set().union(*(operations(scope, child, aggregate) for child in value.iter_expressions()))

    ops = set().union(*(operations(root, p) for p in root.expression.selects))
    lineage = output_lineage(sql)
    origins = {(t.upper(), c.lower()) for values in lineage.values() for t, c in values}
    identified_lines = {("VBRP", c) for c in ("mandt", "vbeln", "posnr")} <= origins
    if wanted in ops or ("RAW" in ops and identified_lines):
        return []
    return [f"The request asks for individual billing-line extremes. Use {wanted}(VBRP.NETWR) at the requested industry/client/currency grain, or return ranked lines with client, document and item IDs. SUM of industry line amounts answers a different metric."]
