"""Persistent, explicitly manual SQL examples for the separate Basic Training mode."""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import Column, Integer, MetaData, String, Table, Text, select, insert, update, delete
from sqlalchemy.orm import Session

metadata = MetaData()
runs = Table("ai_basic_sql_training_runs", metadata,
    Column("id", String(64), primary_key=True), Column("user_id", Integer, nullable=False, index=True),
    Column("scope_digest", String(64), nullable=False), Column("source", String(32), nullable=False),
    Column("question", Text, nullable=False), Column("schema_json", Text, nullable=False),
    Column("sql", Text, nullable=False), Column("status", String(32), nullable=False),
    Column("columns_json", Text, nullable=False), Column("rows_json", Text, nullable=False),
    Column("created_at", String(40), nullable=False))
examples = Table("ai_basic_sql_training_examples", metadata,
    Column("id", String(64), primary_key=True), Column("user_id", Integer, nullable=False, index=True),
    Column("scope_digest", String(64), nullable=False), Column("source", String(32), nullable=False),
    Column("question", Text, nullable=False), Column("schema_json", Text, nullable=False),
    Column("sql", Text, nullable=False), Column("dialect", String(32), nullable=False),
    Column("revision", Integer, nullable=False), Column("history_json", Text, nullable=False),
    Column("validation_status", String(32), nullable=False), Column("updated_at", String(40), nullable=False))


def _digest(scope) -> str:
    from .analyst_drilldown import scope_digest
    return scope_digest(scope)


def ensure_tables(engine):
    metadata.create_all(engine, tables=[runs, examples])


def save_run(engine, scope, run_id: str, question: str) -> dict:
    ensure_tables(engine)
    with Session(engine) as session:
        row = session.execute(select(runs).where(runs.c.id == run_id,
            runs.c.user_id == scope.user_id, runs.c.scope_digest == _digest(scope),
            runs.c.status == "executed")).mappings().first()
        if not row:
            raise PermissionError("Select a successful SQL Training execution owned by your account")
        if question.strip() != row["question"].strip():
            raise ValueError("The saved question must match the question used for this execution")
        identity = hashlib.sha256((str(scope.user_id) + _digest(scope) + row["source"] + row["question"].casefold()).encode()).hexdigest()
        prior = session.execute(select(examples).where(examples.c.id == identity)).mappings().first()
        now = datetime.now(timezone.utc).isoformat()
        values = {"user_id": scope.user_id, "scope_digest": _digest(scope), "source": row["source"],
            "question": row["question"], "schema_json": row["schema_json"], "sql": row["sql"],
            "dialect": "postgres", "revision": 1, "history_json": "[]",
            "validation_status": "executed", "updated_at": now}
        if prior:
            history = json.loads(prior["history_json"] or "[]")
            history.append({"revision": prior["revision"], "sql": prior["sql"], "updated_at": prior["updated_at"]})
            values.update(revision=prior["revision"] + 1, history_json=json.dumps(history[-20:]))
            session.execute(update(examples).where(examples.c.id == identity).values(**values))
        else:
            session.execute(insert(examples).values(id=identity, **values))
        session.commit()
        return {"id": identity, "question": row["question"], "revision": values["revision"], "saved": True}


def list_examples(engine, scope, query=""):
    ensure_tables(engine)
    with Session(engine) as session:
        statement = select(examples).where(examples.c.user_id == scope.user_id,
            examples.c.scope_digest == _digest(scope)).order_by(examples.c.updated_at.desc()).limit(200)
        rows = session.execute(statement).mappings().all()
        needle = query.casefold().strip()
        output = []
        for row in rows:
            if needle and needle not in row["question"].casefold() and needle not in row["sql"].casefold():
                continue
            item = {**{key: row[key] for key in ("id", "source", "question", "sql", "dialect", "revision", "validation_status", "updated_at")},
                    "schema": json.loads(row["schema_json"]), "history": json.loads(row["history_json"] or "[]")}
            # Old examples can still have validation_status="executed" even
            # though they predate semantic checks. Recheck them when listing
            # so Basic's picker can disable stale SQL before the user runs it.
            item["answerability_issues"] = answerability_issues(item["question"], item["sql"], [])
            item["replayable"] = item["validation_status"] == "executed" and not item["answerability_issues"]
            output.append(item)
        return output


def load_replay_example(engine, scope, identifier, revision, question, use_sap):
    """Resolve a picker selection from owned storage, never client-supplied SQL."""
    if scope is None or not getattr(scope, "user_id", None):
        raise PermissionError("Saved SQL Training replay requires an authenticated workspace")
    if (not isinstance(identifier, str) or not identifier or len(identifier) > 64
            or isinstance(revision, bool) or not isinstance(revision, int) or revision < 1):
        raise ValueError("Select a saved SQL Training query and its revision")
    ensure_tables(engine)
    with Session(engine) as session:
        row = session.execute(select(examples).where(
            examples.c.id == identifier, examples.c.user_id == scope.user_id,
            examples.c.scope_digest == _digest(scope))).mappings().first()
        if not row:
            raise PermissionError("This saved SQL Training query is not available in your workspace")
        if row["revision"] != revision or row["validation_status"] != "executed":
            raise ValueError("This saved query changed or needs validation. Refresh the list and run it in SQL Training first")
        if row["question"].strip() != question.strip():
            raise ValueError("The question must match the selected saved SQL Training query")
        if row["source"] not in ({"application", "business"} if use_sap else {"application"}):
            raise ValueError("The selected query's database source is not configured")
        issues = answerability_issues(row["question"], row["sql"], [])
        if issues:
            raise ValueError(
                "This saved SQL Training query needs review and cannot run in Basic: "
                + " ".join(issues)
            )
        return {"question": row["question"], "sql": row["sql"], "source": row["source"],
                "training_example": True, "training_example_id": row["id"],
                "training_revision": row["revision"]}


def edit_example(engine, scope, identifier, sql):
    if not isinstance(sql, str) or not sql.strip() or len(sql) > 24000:
        raise ValueError("Enter a SQL statement up to 24000 characters")
    ensure_tables(engine)
    with Session(engine) as session:
        row = session.execute(select(examples).where(examples.c.id == identifier,
            examples.c.user_id == scope.user_id, examples.c.scope_digest == _digest(scope))).mappings().first()
        if not row:
            raise PermissionError("Training example is not available in your workspace")
        history = json.loads(row["history_json"] or "[]")
        history.append({"revision": row["revision"], "sql": row["sql"], "updated_at": row["updated_at"]})
        session.execute(update(examples).where(examples.c.id == identifier).values(
            sql=sql.strip(), revision=row["revision"] + 1, history_json=json.dumps(history[-20:]),
            validation_status="needs_validation", updated_at=datetime.now(timezone.utc).isoformat()))
        session.commit()
    return {"saved": True, "revision": row["revision"] + 1, "validation_status": "needs_validation"}


def delete_example(engine, scope, identifier):
    ensure_tables(engine)
    with Session(engine) as session:
        result = session.execute(delete(examples).where(examples.c.id == identifier,
            examples.c.user_id == scope.user_id, examples.c.scope_digest == _digest(scope)))
        session.commit()
        return bool(result.rowcount)


def selected_schema(schema, selected):
    requested = selected if isinstance(selected, dict) else {}
    output = {}
    index = {str(table).lower(): (str(table), cols) for table, cols in (schema or {}).items()}
    for table_name, requested_cols in requested.items():
        found = index.get(str(table_name).lower())
        if not found or not isinstance(requested_cols, list):
            raise ValueError("Selected tables or columns are not in the accessible schema")
        original, cols = found
        by_name = {str(c.get("col", "")).lower(): c for c in cols if isinstance(c, dict)}
        selected_cols = []
        for name in requested_cols:
            col = by_name.get(str(name).lower())
            if not col:
                raise ValueError("Selected tables or columns are not in the accessible schema")
            selected_cols.append({"col": col.get("col"), "type": col.get("type", "unknown")})
        output[original] = selected_cols
    return output


_FILTER_OPERATORS = {"include_value", "include_range", "exclude_value", "exclude_range", "greater_than", "less_than"}
_SAP_DATE_FIELDS = {
    "fkdat", "erdat", "aedat", "budat", "bldat", "ftrms", "gltrp", "gstrp", "gltrs", "gstrs",
    "gstri", "getri", "gltri", "ftrmi", "ftrmp", "pdatv", "sdatv", "trmdt", "valdt",
    "kdatb", "kdate", "bedat", "cpudt", "audat", "eindt", "lfdat", "prsdt", "zfbdt",
    "datuv", "ersda", "laeda", "vdatu", "prdat", "fkdat_rl",
}
_SAP_AMOUNT_FIELDS = {
    "netwr", "mwsbk", "rmwwr", "wavwr", "fkwrt", "wrbtr", "dmbtr", "salk3", "stprs", "verpr",
    "peinh", "netpr", "mwsbp", "kwmeng", "fkimg", "lfimg", "menge", "gamng", "bmenge", "vfmng",
    "lmeng", "brgew", "ntgew", "kzwi1", "kzwi2", "kzwi3", "kzwi4", "kzwi5", "kzwi6",
}


def _is_date_field(column_info: dict) -> bool:
    name = str(column_info.get("col") or "").lower()
    field_type = str(column_info.get("type") or "").lower()
    return ("date" in field_type or "time" in field_type or name in _SAP_DATE_FIELDS
            or name.endswith(("_date", "_date_time", "_dt", "dat", "date"))
            or name.endswith(("startd", "endd")))


def apply_training_filters(sql: str, filters, selection: dict) -> str:
    """Add user-authored selection-screen filters to one selected-schema SELECT."""
    if not filters:
        return sql
    if not isinstance(filters, list) or len(filters) > 30:
        raise ValueError("Add no more than 30 filter conditions")

    from sqlglot import exp, parse_one
    from sqlglot.errors import SqlglotError
    try:
        tree = parse_one(sql, read="postgres")
    except SqlglotError as error:
        raise ValueError("SQL syntax could not be parsed before applying filters") from error
    if not isinstance(tree, exp.Select) or len(list(tree.find_all(exp.Select))) != 1:
        raise ValueError("Training filters can be applied to one SELECT without nested queries")

    grouped = {}
    for item in filters:
        if not isinstance(item, dict):
            raise ValueError("Each filter must select a schema field and an operation")
        table_name = str(item.get("table") or "")
        column_name = str(item.get("column") or "")
        operator = str(item.get("operator") or "")
        if operator not in _FILTER_OPERATORS:
            raise ValueError("Choose an available include, exclude, or comparison filter")
        columns = next((cols for table, cols in selection.items() if table.lower() == table_name.lower()), None)
        column_info = next((col for col in columns or [] if str(col.get("col", "")).lower() == column_name.lower()), None)
        if not column_info:
            raise ValueError("Every filter field must be selected in the accessible schema")
        matching_tables = [node for node in tree.find_all(exp.Table) if node.name.lower() == table_name.lower()]
        if len(matching_tables) != 1:
            raise ValueError(f"Filter table {table_name} must appear exactly once in the SQL query")
        table_node = matching_tables[0]
        alias = table_node.alias or table_node.name
        field = exp.Column(this=exp.Identifier(this=column_info["col"], quoted=True),
                           table=exp.Identifier(this=alias, quoted=True))
        field_type = str(column_info.get("type") or "").lower()
        numeric_field = any(kind in field_type for kind in ("numeric", "decimal", "integer", "float", "double")) \
            or column_info["col"].lower() in _SAP_AMOUNT_FIELDS
        date_field = _is_date_field(column_info)
        comparable_field = exp.Cast(this=field.copy(), to=exp.DataType.build("DECIMAL")) if numeric_field else field
        if date_field and any(kind in field_type for kind in ("timestamp", "datetime")):
            comparable_field = exp.Cast(this=field.copy(), to=exp.DataType.build("DATE"))

        def literal(raw):
            value = str(raw or "").strip()
            if not value or len(value) > 256:
                raise ValueError("Enter a filter value up to 256 characters")
            if date_field:
                date_value = value
                for date_format in ("%Y-%m-%d", "%d.%m.%Y", "%Y%m%d"):
                    try:
                        parsed_date = datetime.strptime(date_value, date_format)
                        break
                    except ValueError:
                        parsed_date = None
                if parsed_date is None:
                    raise ValueError(f"Enter a valid date for {column_info['col']} (YYYY-MM-DD)")
                value = parsed_date.strftime("%Y-%m-%d") if any(kind in field_type for kind in ("date", "time")) else parsed_date.strftime("%Y%m%d")
            if numeric_field:
                value = value.replace(" ", "")
                if value.endswith("-"):
                    value = "-" + value[:-1]
                if "," in value and "." in value:
                    value = value.replace(".", "").replace(",", ".") if value.rfind(",") > value.rfind(".") else value.replace(",", "")
                elif "," in value:
                    value = value.replace(",", ".")
                if not re.fullmatch(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)", value):
                    raise ValueError(f"Enter a valid numeric value for {column_info['col']}")
                return exp.Literal.number(value)
            return exp.Literal.string(value)

        value = item.get("value")
        upper = item.get("upper")
        if operator.endswith("range") or operator == "include_range":
            lower_literal, upper_literal = literal(value), literal(upper)
            if numeric_field and Decimal(lower_literal.this) > Decimal(upper_literal.this):
                raise ValueError(f"The lower limit must not exceed the upper limit for {column_info['col']}")
            if date_field and str(lower_literal.this) > str(upper_literal.this):
                raise ValueError(f"The lower date must not exceed the upper date for {column_info['col']}")
            condition = exp.Between(this=comparable_field.copy(), low=lower_literal, high=upper_literal)
            if operator == "exclude_range":
                condition = exp.Not(this=condition)
            positive = operator == "include_range"
        else:
            val = literal(value)
            if operator == "include_value":
                condition, positive = exp.EQ(this=comparable_field.copy(), expression=val), True
            elif operator == "exclude_value":
                condition, positive = exp.NEQ(this=comparable_field.copy(), expression=val), False
            elif operator == "greater_than":
                condition, positive = exp.GT(this=comparable_field.copy(), expression=val), True
            else:
                condition, positive = exp.LT(this=comparable_field.copy(), expression=val), True
        key = (table_name.lower(), column_name.lower())
        group = grouped.setdefault(key, {"positive": [], "negative": [], "comparisons": []})
        if operator in {"greater_than", "less_than"}:
            group["comparisons"].append(condition)
        else:
            group["positive" if positive else "negative"].append(condition)

    conditions = []
    for group in grouped.values():
        if group["positive"]:
            conditions.append(exp.or_(*group["positive"]))
        conditions.extend(group["negative"])
        # Bound comparisons on the same field are conjunctive (e.g. > lower
        # AND < upper), unlike multiple SAP include choices, which are ORed.
        conditions.extend(group["comparisons"])
    filter_expression = exp.and_(*conditions)
    prior_where = tree.args.get("where")
    tree.set("where", exp.Where(this=exp.and_(prior_where.this, filter_expression) if prior_where else filter_expression))
    return tree.sql(dialect="postgres")


def check_query_scope(sql: str, selection: dict):
    # Reuse the same SQLGlot boundary as model-generated SQL. It enforces one
    # read-only SELECT/WITH, validates every physical table/column, expands safe
    # stars, and correctly handles CTEs and aliases against the selected subset.
    from .analyst_agent_sql import validate_agent_sql
    from sqlglot.errors import SqlglotError
    try:
        safe_sql, _tables = validate_agent_sql(sql, selection)
        return safe_sql
    except SqlglotError as error:
        # SQLGlot's parse diagnostic points to the syntax/position that needs
        # attention. Keep it short so the training UI can show an actionable
        # error instead of making every parser rejection look identical.
        diagnostic = re.sub(r"\s+", " ", str(error)).strip()
        if len(diagnostic) > 240:
            diagnostic = diagnostic[:237] + "..."
        detail = f" ({diagnostic})" if diagnostic else ""
        raise ValueError(
            "SQL syntax could not be parsed" + detail
            + "; check PostgreSQL syntax and selected table/column names"
        ) from error


def needs_specific_years(question: str) -> bool:
    return not re.search(r"\b(?:19|20)\d{2}\b", question or "") and bool(re.search(
        r"\b(?:between|for|in)\s+(?:the\s+)?specific\s+years\b", question or "", re.I))


def answerability_issues(question: str, sql: str, rows: list[dict]) -> list[str]:
    """Catch clear gaps between a training question and its executed result.

    This is a small deterministic check, not a claim that every other query
    fully answers its question. It keeps obviously incomplete runs out of
    checked Basic replay while showing the rows and repair guidance.
    """
    from sqlglot import exp, parse_one

    try:
        tree = parse_one(sql, read="postgres")
    except Exception:
        return []  # Syntax errors have already been handled by validation.
    if not isinstance(tree, exp.Select):
        return []
    issues = []
    wording = question.lower()
    tables = {table.name.lower() for table in tree.find_all(exp.Table)}
    output = {str(key).lower() for row in rows[:1] for key in row}
    output.update(str(selection.alias_or_name).lower() for selection in tree.selects)

    if re.search(r"\bcountr(?:y|ies)\b", wording) and not any(
        "country" in name or name in {"land1", "landx"} for name in output
    ):
        issues.append("The question asks for countries, but the result has no country column. Select a country field such as KNA1.LAND1 and join it to the customer.")
    if ("vbak" in tables and not tables.intersection({"vbrk", "vbrp"})
            and re.search(r"\binvoices?\b", wording)
            and re.search(r"\b(?:difference|differences|compare|comparison)\b", wording)):
        issues.append("The question compares order and invoice values, but the SQL reads no invoice table. Join the sales order to billing data and calculate both values and their difference.")

    years = list(dict.fromkeys(re.findall(r"\b(?:19|20)\d{2}\b", wording)))
    if needs_specific_years(question):
        issues.append(
            "The saved question asks for specific years but names no years. "
            "Specify the actual year or range in both the question and SQL, then rerun and save it. "
            "If every year is intended, state 'all years' in the question."
        )
    range_wording = len(years) == 2 and bool(re.search(
        r"\bbetween\b|\b(?:19|20)\d{2}\s*(?:to|through|until|[-–—])\s*(?:19|20)\d{2}\b",
        wording,
    ))
    if years:
        date_fields = {"fkdat", "audat", "budat", "bldat", "erdat", "billing_date", "order_date",
                       "invoice_date", "billing_year", "invoice_year", "order_year",
                       "sales_year", "salesyear", "year", "fiscal_year"}
        required_years = ([str(year) for year in range(min(map(int, years)), max(map(int, years)) + 1)]
                          if range_wording else years)
        from .analyst_filters import _calendar_years_proven

        def conjuncts(node):
            if isinstance(node, exp.Paren):
                return conjuncts(node.this)
            if isinstance(node, exp.And):
                return conjuncts(node.this) + conjuncts(node.expression)
            return [] if isinstance(node, exp.Or) else [node]

        year_filters = []
        constrained_dates = set()
        for where in tree.find_all(exp.Where):
            predicates = [term for term in conjuncts(where.this)
                          if {column.name.lower() for column in term.find_all(exp.Column)} & date_fields]
            if _calendar_years_proven(predicates, required_years):
                year_filters.append(where)
                constrained_dates.update(column.name.lower() for term in predicates
                                         for column in term.find_all(exp.Column)
                                         if column.name.lower() in date_fields)
        if not year_filters:
            constrained_dates = date_fields
            requested = years[0] if len(years) == 1 else f"{years[0]}–{years[-1]}"
            issues.append(
                f"The question specifies {requested}, but the SQL has no matching date filter. "
                "Add a filter on the relevant SAP date field and rerun before saving this example."
            )
        observed_years = set()
        from .agent_query_contract import output_lineage
        lineage = output_lineage(sql)
        for row in rows:
            for key, value in row.items():
                origins = lineage.get(key, set())
                # A filtered order-date cohort may legitimately contain later
                # invoice dates. Check the output dates constrained by SQL.
                if not ({column.lower() for _, column in origins} & constrained_dates
                        or str(key).lower() in constrained_dates):
                    continue
                match = re.search(r"((?:19|20)\d{2})", str(value or ""))
                if match:
                    observed_years.add(match.group(1))
        if observed_years - set(required_years):
            actual = ", ".join(sorted(observed_years - set(required_years)))
            issues.append(
                f"The requested year(s) are {', '.join(years)}, but the returned dates are from {actual}. "
                "Check the date field and filter before saving this example."
            )

    if range_wording:
        limit_node = tree.args.get("limit")
        try:
            limit = int(limit_node.expression.this) if limit_node else 0
        except (TypeError, ValueError, AttributeError):
            limit = 0
        if limit >= 10 and len(rows) >= limit:
            observed = set()
            for row in rows:
                for key, value in row.items():
                    if re.search(r"year|date|fkdat|audat|budat|bldat", str(key), re.I):
                        match = re.match(r"((?:19|20)\d{2})", str(value or ""))
                        if match:
                            observed.add(int(match.group(1)))
            first, last = sorted(map(int, years))
            if not observed or min(observed) > first or max(observed) < last:
                shown = ", ".join(str(year) for year in sorted(observed)) or "no visible year"
                issues.append(
                    f"The query reached LIMIT {limit} for {first}–{last}, but returned rows show {shown}. "
                    "This sample cannot establish the full period. Group by year and requested dimensions, "
                    "or revise the limit and rerun."
                )
    # Old saved examples can predate composite-key validation. Flag an
    # obviously missing SAP client join in the picker, before execution, using
    # the same mandatory client boundary as the live relationship catalog.
    from sqlglot.optimizer.scope import Scope, traverse_scope
    from .agent_query_contract import output_lineage
    client_tables = {"VBAK", "VBAP", "VBRK", "VBRP", "KNA1", "VBFA", "VBKD", "LIKP", "LIPS", "EKKO", "EKPO"}
    for scope in traverse_scope(tree):
        physical = {alias: source.name.upper() for alias, (_, source) in scope.selected_sources.items()
                    if isinstance(source, exp.Table) and source.name.upper() in client_tables}
        seen = set()
        source = scope.expression.args.get("from_") or scope.expression.args.get("from")
        if source:
            seen.add(source.this.alias_or_name)
        def client_column(column):
            if not isinstance(column, exp.Column):
                return False
            source_scope = scope.sources.get(column.table)
            if isinstance(source_scope, exp.Table):
                return column.name.lower() == "mandt"
            if isinstance(source_scope, Scope):
                origins = output_lineage(source_scope.expression.sql(dialect="postgres")).get(column.name, set())
                return bool(origins) and all(name.lower() == "mandt" for _, name in origins)
            return False
        for join in scope.expression.args.get("joins") or []:
            target = join.this.alias_or_name
            if target in physical and seen:
                def and_terms(node):
                    if isinstance(node, exp.Paren):
                        return and_terms(node.this)
                    if isinstance(node, exp.And):
                        return and_terms(node.this) + and_terms(node.expression)
                    return [node]
                matched = any(
                    isinstance(term, (exp.EQ, exp.NullSafeEQ))
                    and isinstance(term.this, exp.Column) and isinstance(term.expression, exp.Column)
                    and client_column(term.this) and client_column(term.expression)
                    and target in {term.this.table, term.expression.table}
                    and bool(({term.this.table, term.expression.table} - {target}) & seen)
                    for term in and_terms(join.args.get("on"))
                )
                if not matched:
                    issues.append(f"The SAP join to {physical[target]} omits MANDT. Retain the client key as well as the document or customer keys, then rerun SQL Training.")
            seen.add(target)
    return issues


def record_run(engine, scope, source, question, schema, sql, result, answer_issues=None):
    ensure_tables(engine)
    identifier = uuid.uuid4().hex
    now = datetime.now(timezone.utc).isoformat()
    rows = result.get("rows") or []
    with Session(engine) as session:
        session.execute(insert(runs).values(id=identifier, user_id=scope.user_id, scope_digest=_digest(scope),
            source=source, question=question, schema_json=json.dumps(schema), sql=result.get("sql") or sql,
            status="needs_review" if answer_issues else "executed" if result.get("ok") else "failed",
            columns_json=json.dumps(list(rows[0].keys()) if rows else []), rows_json=json.dumps(rows[:500], default=str), created_at=now))
        session.commit()
    return identifier
