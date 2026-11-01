"""Schema-bound item evidence for a named invoice, using the ordinary SQL guard."""
import re


def invoice_item_evidence_sql(question, schema):
    identifiers = re.findall(r"\binvoice(?:\s+(?:number|no\.?|id))?\s*[:#]?\s*['\"]?([A-Za-z0-9][A-Za-z0-9_-]{0,39})", question, re.I)
    identifiers = {value for value in identifiers if any(c.isdigit() for c in value)}
    if len(identifiers) != 1:
        return None
    tables = {table.upper(): table for table in schema}
    needed = {
        "VBRP": {"mandt", "vbeln", "posnr", "aubel", "aupos", "netwr"},
        "VBAP": {"mandt", "vbeln", "posnr", "netwr"},
        "VBRK": {"mandt", "vbeln", "netwr", "waerk"},
        "VBAK": {"mandt", "vbeln", "netwr", "waerk"},
    }
    columns = {table.upper(): {c["col"].lower(): c["col"] for c in fields} for table, fields in schema.items()}
    if any(table not in columns or not fields <= columns[table].keys() for table, fields in needed.items()):
        return None

    def quote(value):
        return '"' + value.replace('"', '""') + '"'

    def field(alias, table, column):
        return alias + "." + quote(columns[table][column])

    def amount(alias, table):
        return "CAST(NULLIF(TRIM(CAST(" + field(alias, table, "netwr") + " AS TEXT)), '') AS NUMERIC)"

    projections = []
    for alias, table, column, output in [
        ("p", "VBRP", "mandt", "client"), ("p", "VBRP", "vbeln", "invoice_id"),
        ("p", "VBRP", "posnr", "invoice_item"), ("p", "VBRP", "aubel", "linked_order_reference"),
        ("p", "VBRP", "aupos", "linked_order_item_reference"),
        ("o", "VBAP", "mandt", "order_item_client"), ("o", "VBAP", "vbeln", "order_item_document"),
        ("o", "VBAP", "posnr", "order_item"), ("h", "VBAK", "mandt", "order_client"),
        ("h", "VBAK", "vbeln", "order_id"), ("b", "VBRK", "waerk", "invoice_currency"),
        ("h", "VBAK", "waerk", "order_currency"),
        ("p", "VBRP", "fkimg", "billed_quantity"), ("p", "VBRP", "vrkme", "billing_unit"),
        ("o", "VBAP", "kwmeng", "order_quantity"), ("o", "VBAP", "vrkme", "order_unit"),
        ("o", "VBAP", "netpr", "order_net_price"), ("o", "VBAP", "kpein", "order_price_unit"),
        ("b", "VBRK", "fkdat", "invoice_date"), ("h", "VBAK", "audat", "order_date"),
    ]:
        if column in columns[table]:
            projections.append(field(alias, table, column) + " AS " + quote(output))
    for alias, table, output in [("p", "VBRP", "invoice_item_net"), ("o", "VBAP", "order_item_net"),
                                  ("b", "VBRK", "invoice_net_total"), ("h", "VBAK", "order_net_total")]:
        projections.append(amount(alias, table) + " AS " + quote(output))
    projections.append("CASE WHEN " + field("b", "VBRK", "waerk") + " = " + field("h", "VBAK", "waerk")
                       + " THEN " + amount("h", "VBAK") + " - " + amount("b", "VBRK") + ' END AS "order_minus_invoice"')
    projections.append("CASE WHEN " + field("o", "VBAP", "posnr")
                       + " IS NULL THEN 'Referenced order item is absent from the connected extract; its quantity, price and exact business cause cannot be established' "
                       + "ELSE 'Item evidence is present; a cause still requires matching quantities, units and pricing conditions' END AS observed_difference")
    invoice = next(iter(identifiers))
    predicates = [field("p", "VBRP", "vbeln") + " = '" + invoice.replace("'", "''") + "'"]
    orders = {value for value in re.findall(r"\border\s+([A-Za-z0-9][A-Za-z0-9_-]{0,39})", question, re.I)
              if any(c.isdigit() for c in value)}
    if len(orders) == 1:
        predicates.append(field("p", "VBRP", "aubel") + " = '" + next(iter(orders)).replace("'", "''") + "'")
    sql = "SELECT " + ", ".join(projections) + " FROM " + quote(tables["VBRP"]) + " p"
    for side, table, alias, pairs in [
        ("JOIN", "VBRK", "b", [("mandt", "mandt"), ("vbeln", "vbeln")]),
        ("LEFT JOIN", "VBAK", "h", [("mandt", "mandt"), ("vbeln", "aubel")]),
        ("LEFT JOIN", "VBAP", "o", [("mandt", "mandt"), ("vbeln", "aubel"), ("posnr", "aupos")]),
    ]:
        sql += " " + side + " " + quote(tables[table]) + " " + alias + " ON " + " AND ".join(
            field(alias, table, left) + " = " + field("p", "VBRP", right) for left, right in pairs)
    return sql + " WHERE " + " AND ".join(predicates) + " ORDER BY " + ", ".join(
        field("p", "VBRP", col) for col in ("mandt", "vbeln", "posnr")) + " LIMIT 201"
