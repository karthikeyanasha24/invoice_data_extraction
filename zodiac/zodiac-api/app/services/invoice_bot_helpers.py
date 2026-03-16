"""
Invoice-bot-style helpers for zodiac-api: spec post-processing, result shaping,
fallback SQL, document flow tracing, procurement-from-list, dynamic analysis, insights, COGS.
Uses list-of-dicts (no Streamlit/pandas required). Postgres SQL variants.
"""
from __future__ import annotations

import json
import logging
import os
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# --- Load TABLE_DESCRIPTIONS from app/sap_table_descriptions.json ---
_TABLE_DESCRIPTIONS_CACHE: Dict[str, str] = {}


def get_table_descriptions() -> Dict[str, str]:
    """Load full SAP table descriptions for adaptive selection (from sap_table_descriptions.json)."""
    global _TABLE_DESCRIPTIONS_CACHE
    if _TABLE_DESCRIPTIONS_CACHE:
        return _TABLE_DESCRIPTIONS_CACHE
    try:
        root = Path(__file__).resolve().parent.parent
        path = root / "sap_table_descriptions.json"
        if path.exists():
            with path.open("r", encoding="utf-8") as f:
                _TABLE_DESCRIPTIONS_CACHE = json.load(f)
            return _TABLE_DESCRIPTIONS_CACHE
    except Exception as e:
        logger.warning("Could not load sap_table_descriptions.json: %s", e)
    return {}


TABLE_DESCRIPTIONS = get_table_descriptions

# Constants (invoice-bot config parity)
REVENUE_BILLING_CATEGORIES = ("A", "B", "C", "D", "E", "I", "L", "W")
DATE_COLUMNS = {"FKDAT", "BUDAT", "BLDAT", "ZBDAT", "GSTRP"}
# Year/period columns: store 4-digit year (GJAHR, RYEAR) or period 01-12 (POPER). Do NOT convert to date range.
YEAR_PERIOD_COLUMNS = {"GJAHR", "RYEAR", "BDATJ", "POPER"}
INDUSTRY_SECTOR_LABELS = {
    "1": "Sector 1",
    "A": "Plant engineering and construction",
    "C": "Chemical",
    "E": "Electrical engineering",
    "F": "Food / FMCG",
    "M": "Mechanical engineering",
    "P": "Pharmaceutical",
    "R": "Retail",
    "S": "Services",
    "T": "Transport / Logistics",
    "V": "Vehicle manufacturing",
    "": "Not specified",
}
PROCUREMENT_TYPE_DISPLAY_LABELS = {
    "E": "E (In-house produced)",
    "F": "F (Externally procured)",
    "X": "X (Both)",
}
CUSTOMER_NUMBER_LENGTH = 10
DOCUMENT_NUMBER_LENGTH = 10

COGS_CALCULATION_EXPLANATION = """
**How SAP calculates Cost of Goods Sold (COGS)**

In SAP, COGS depends on **procurement type** (Make vs. Buy) and **valuation method** (Standard vs. Actual) configured for the material.

- **Manufactured internally:** Cost of Goods Manufactured (COGM) using BOM (STKO/STPO), routing (PLKO/PLPO), cost estimates (KEKO/KEPH).
- **Procured:** Moving Average (V) = MBEW.VERPR; Standard (S) = MBEW.STPRS. Price unit (PEINH) defines quantity per which price applies.
- The app reads valuation/cost data from MBEW, KEKO/KEPH, BKPF/BSEG or ACDOCA; it does not compute COGS itself.
- **Why no data:** Product name may not match MAKT.MAKTX; material may have no row in MBEW/KEKO; STPRS/VERPR may be 0 or null.
"""

# Tables that can join to MAKT for product-name filtering
_TABLES_THAT_JOIN_TO_MAKT = (
    "MARA", "VBRP", "VBAP", "LIPS", "MBEW", "KEKO", "EKPO", "CKIS", "STPO", "EBAN", "MSEG", "MAST"
)


def _extract_product_name_from_query(user_query: str) -> str:
    """Extract product name from query (e.g. 'show Harley products' -> 'Harley',
    'profit margin for Fire fighting vehicle' -> 'Fire fighting vehicle')."""
    if not user_query or not isinstance(user_query, str):
        return ""
    s = (user_query or "").strip()
    s_lower = s.lower()
    # "profit margin for X", "margin for X", "profitability for X" (adaptive to any product)
    for prefix in ("profit margin for", "margin for", "profitability for", "profit margin for the"):
        if prefix in s_lower:
            idx = s_lower.index(prefix) + len(prefix)
            name = s[idx:].strip().split(",")[0].split(".")[0].strip()
            if name and len(name) <= 80 and name.lower() not in ("all", "the", "a", "an"):
                return name
    # "show Harley products", "list Harley products"
    m = re.search(r"(?:show\s+me?\s+)?(.+?)\s+products\b", s_lower, re.IGNORECASE | re.DOTALL)
    if m:
        name = s[m.start(1) : m.end(1)].strip()
        if name.lower().startswith("all ") and len(name) > 4:
            name = name[4:].strip()
        if name and name.lower() not in ("all", "the", "my", "our"):
            if name.lower().startswith("analyse "):
                name = name[8:].strip()
            elif name.lower().startswith("analyze "):
                name = name[8:].strip()
            return name
    for pattern in ("products named ", "products called "):
        if pattern in s_lower:
            idx = s_lower.index(pattern) + len(pattern)
            name = s[idx:].strip().split(",")[0].split(".")[0].strip()
            if name:
                return name
    m = re.search(r"\b(?:analyse|analyze)\s+([A-Za-z0-9_\-]+)(?:\s|$|,|\.)", s_lower, re.IGNORECASE)
    if m:
        name = s[m.start(1) : m.end(1)].strip()
        if name and len(name) <= 40:
            return name
    return ""


def _extract_material_number_from_query(user_query: str) -> str:
    """Extract material/product number (e.g. 'cost of product number H10500' -> 'H10500')."""
    if not user_query or not isinstance(user_query, str):
        return ""
    s = (user_query or "").strip()
    s_lower = s.lower()
    for pattern in (
        r"product\s+number\s+([A-Za-z0-9_\-]+)",
        r"material\s+number\s+([A-Za-z0-9_\-]+)",
    ):
        m = re.search(pattern, s_lower, re.IGNORECASE)
        if m:
            val = s[m.start(1) : m.end(1)].strip()
            if val and len(val) <= 40 and val.lower() not in ("the", "a", "an", "cost", "price"):
                return val
    return ""


def convert_date_to_yyyymmdd(date_str: str) -> str:
    """Normalize date string to YYYYMMDD."""
    s = (date_str or "").strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%Y%m%d"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y%m%d")
        except Exception:
            pass
    if re.match(r"^\d{4}$", s):
        return f"{s}0101"
    if re.match(r"^\d{8}$", s):
        return s
    return s


def fix_date_filters(json_spec: dict) -> dict:
    """Normalize date filters: single year -> >= YYYY0101 and <= YYYY1231 for date columns;
    for GJAHR/RYEAR/BDATJ keep as = 'YYYY'; for POPER keep as = 'MM'. Year range -> full dates."""
    if not json_spec or "filters" not in json_spec:
        return json_spec
    new_filters = []
    for filt in json_spec["filters"]:
        lhs = filt.get("lhs", "")
        op = (filt.get("operator") or "=").strip()
        rhs_raw = (str(filt.get("rhs") or "").strip()).strip("'\"")
        col = lhs.split(".")[-1].strip() if "." in lhs else lhs
        col_upper = col.upper()
        # Year columns (GJAHR, RYEAR, BDATJ): store 4-digit year, use = 'YYYY' not date range
        if col_upper in {"GJAHR", "RYEAR", "BDATJ"}:
            if not rhs_raw or rhs_raw.upper() in ("NULL", "NONE", "''"):
                continue
            if re.match(r"^\d{4}$", rhs_raw):
                new_filters.append({"lhs": lhs, "operator": "=", "rhs": f"'{rhs_raw}'"})
                continue
        # Period column (POPER): 01-12, normalize single digit (5 -> 05)
        if col_upper == "POPER":
            if rhs_raw:
                m = re.match(r"^(\d{1,2})$", rhs_raw)
                if m:
                    p_val = int(m.group(1))
                    if 1 <= p_val <= 12:
                        new_filters.append({"lhs": lhs, "operator": "=", "rhs": f"'{p_val:02d}'"})
                        continue
        # Date columns: convert 4-digit year to date range
        if col_upper in DATE_COLUMNS:
            if not rhs_raw or rhs_raw.upper() in ("NULL", "NONE", "''"):
                continue
            if re.match(r"^\d{4}$", rhs_raw):
                year = rhs_raw
                if op == ">=":
                    new_filters.append({"lhs": lhs, "operator": ">=", "rhs": f"'{year}0101'"})
                    continue
                if op == "<=":
                    new_filters.append({"lhs": lhs, "operator": "<=", "rhs": f"'{year}1231'"})
                    continue
                new_filters.append({"lhs": lhs, "operator": ">=", "rhs": f"'{year}0101'"})
                new_filters.append({"lhs": lhs, "operator": "<=", "rhs": f"'{year}1231'"})
                continue
            new_rhs = convert_date_to_yyyymmdd(rhs_raw)
            if new_rhs:
                filt = dict(filt)
                filt["rhs"] = f"'{new_rhs}'"
        new_filters.append(filt)
    json_spec["filters"] = new_filters
    return json_spec


def inject_product_name_filter_if_needed(user_query: str, json_spec: dict) -> dict:
    """Add MAKT.MAKTX filter when user asks for a product by name; add MAKT + SPRAS='E' if needed."""
    if not user_query or not json_spec:
        return json_spec
    product_name = _extract_product_name_from_query(user_query)
    if not product_name:
        return json_spec
    columns = json_spec.get("columns", [])
    tables = {c.get("table") for c in columns if c.get("table")}
    for j in json_spec.get("joins", []):
        tables.add(j.get("left"))
        tables.add(j.get("right"))
    for t in json_spec.get("tables", []):
        if isinstance(t, dict) and t.get("name"):
            tables.add(t.get("name"))
    if "MAKT" not in tables:
        partner = next((t for t in _TABLES_THAT_JOIN_TO_MAKT if t in tables), None)
        if partner is not None:
            json_spec.setdefault("columns", [])
            if not any(c.get("table") == "MAKT" and c.get("name") == "MAKTX" for c in json_spec["columns"]):
                json_spec["columns"].append({"table": "MAKT", "name": "MAKTX", "description": "material_description"})
            json_spec.setdefault("joins", [])
            if not any(j.get("right") == "MAKT" for j in json_spec["joins"]):
                json_spec["joins"].append({"left": partner, "right": "MAKT", "on": f"{partner}.MATNR = MAKT.MATNR", "type": "inner"})
            tables.add("MAKT")
    if "MAKT" not in tables:
        return json_spec
    has_maktx = any(
        "MAKTX" in str(f.get("lhs", "")).upper() or "MATERIAL_DESCRIPTION" in str(f.get("lhs", "")).upper()
        for f in json_spec.get("filters", [])
    )
    if has_maktx:
        return json_spec
    json_spec.setdefault("filters", [])
    json_spec["filters"].append({"lhs": "MAKT.MAKTX", "operator": "=", "rhs": product_name})
    inject_makt_single_language_if_needed(json_spec)
    return json_spec


def inject_material_number_filter_if_needed(user_query: str, json_spec: dict) -> dict:
    """When user asks for cost of a specific product/material number, add MATNR filter."""
    if not user_query or not json_spec:
        return json_spec
    matnr = _extract_material_number_from_query(user_query)
    if not matnr:
        return json_spec
    tables = set()
    for c in json_spec.get("columns", []):
        if c.get("table"):
            tables.add(c.get("table"))
    for j in json_spec.get("joins", []):
        tables.add(j.get("left"))
        tables.add(j.get("right"))
    for t in json_spec.get("tables", []):
        if isinstance(t, dict) and t.get("name"):
            tables.add(t.get("name"))
    matnr_tables = [t for t in ("MBEW", "MARA", "MAKT", "KEKO", "CKIS", "VBRP", "VBAP", "LIPS") if t in tables]
    if not matnr_tables:
        return json_spec
    lhs = f"{matnr_tables[0]}.MATNR"
    for f in json_spec.get("filters", []):
        if "MATNR" in str(f.get("lhs", "")).upper() and str(f.get("rhs", "")).strip().upper() == matnr.upper():
            return json_spec
    json_spec.setdefault("filters", [])
    json_spec["filters"].append({"lhs": lhs, "operator": "=", "rhs": matnr})
    return json_spec


# Country / nationality → ISO 2-letter code (for LAND1 filter). Extend as needed.
COUNTRY_NAME_TO_ISO: Dict[str, str] = {
    "korean": "KR", "korea": "KR", "south korea": "KR",
    "indian": "IN", "india": "IN",
    "german": "DE", "germany": "DE",
    "french": "FR", "france": "FR",
    "american": "US", "usa": "US", "united states": "US", "us": "US",
    "japanese": "JP", "japan": "JP",
    "chinese": "CN", "china": "CN",
    "british": "GB", "uk": "GB", "united kingdom": "GB", "britain": "GB",
    "australian": "AU", "australia": "AU",
    "canadian": "CA", "canada": "CA",
    "italian": "IT", "italy": "IT",
    "spanish": "ES", "spain": "ES",
    "dutch": "NL", "netherlands": "NL",
    "swiss": "CH", "switzerland": "CH",
    "brazilian": "BR", "brazil": "BR",
    "russian": "RU", "russia": "RU",
    "mexican": "MX", "mexico": "MX",
    "austrian": "AT", "austria": "AT",
    "belgian": "BE", "belgium": "BE",
    "irish": "IE", "ireland": "IE",
    "thai": "TH", "thailand": "TH",
    "indonesian": "ID", "indonesia": "ID",
    "malaysian": "MY", "malaysia": "MY",
    "singaporean": "SG", "singapore": "SG",
    "vietnamese": "VN", "vietnam": "VN",
    "philippine": "PH", "philippines": "PH",
    "south african": "ZA", "south africa": "ZA",
    "emirati": "AE", "uae": "AE", "emirates": "AE",
    "saudi": "SA", "saudi arabia": "SA",
    "israeli": "IL", "israel": "IL",
    "egyptian": "EG", "egypt": "EG",
    "nigerian": "NG", "nigeria": "NG",
    "polish": "PL", "poland": "PL",
    "czech": "CZ", "czech republic": "CZ",
    "hungarian": "HU", "hungary": "HU",
    "romanian": "RO", "romania": "RO",
    "portuguese": "PT", "portugal": "PT",
    "greek": "GR", "greece": "GR",
    "turkish": "TR", "turkey": "TR",
    "swedish": "SE", "sweden": "SE",
    "norwegian": "NO", "norway": "NO",
    "danish": "DK", "denmark": "DK",
    "finnish": "FI", "finland": "FI",
}


def _extract_country_iso_from_query(user_query: str) -> Optional[str]:
    """If the query mentions a country or nationality, return 2-letter ISO code; else None."""
    if not user_query or not isinstance(user_query, str):
        return None
    q = (user_query or "").strip().lower()
    # Prefer longer phrases first (e.g. "south korea" before "korea")
    for phrase, code in sorted(COUNTRY_NAME_TO_ISO.items(), key=lambda x: -len(x[0])):
        if re.search(r"\b" + re.escape(phrase) + r"\b", q):
            return code
    return None


def inject_country_filter_if_needed(user_query: str, json_spec: dict) -> dict:
    """
    When the user asks for sales/revenue by a specific country (e.g. Korean customers, revenue from India),
    add a filter LAND1 = '<ISO code>'. Uses KNA1.LAND1 or VBRK.LAND1 depending on tables in spec.
    """
    if not user_query or not json_spec:
        return json_spec
    iso = _extract_country_iso_from_query(user_query)
    if not iso:
        return json_spec
    tables = set()
    for c in json_spec.get("columns", []):
        if c.get("table"):
            tables.add(str(c.get("table")).upper())
    for j in json_spec.get("joins", []):
        for side in ("left", "right"):
            t = j.get(side)
            if t:
                tables.add(str(t).upper())
    for t in json_spec.get("tables", []):
        if isinstance(t, dict) and t.get("name"):
            tables.add(str(t.get("name")).upper())
    # Prefer VBRK.LAND1 (billing country) if VBRK present; else KNA1.LAND1 (customer country)
    land1_lhs = None
    if "VBRK" in tables:
        land1_lhs = "VBRK.LAND1"
    elif "KNA1" in tables:
        land1_lhs = "KNA1.LAND1"
    if not land1_lhs:
        return json_spec
    filters = json_spec.get("filters", [])
    for f in filters:
        lhs = (f.get("lhs") or "").upper()
        if "LAND1" in lhs:
            return json_spec  # already has country filter
    json_spec.setdefault("filters", [])
    json_spec["filters"].append({"lhs": land1_lhs, "operator": "=", "rhs": f"'{iso}'"})
    return json_spec


def inject_makt_single_language_if_needed(json_spec: dict, language: str = "E") -> dict:
    """Add MAKT.SPRAS = language when MAKT is in spec and no SPRAS filter exists."""
    if not json_spec:
        return json_spec
    tables = set()
    for c in json_spec.get("columns", []):
        if c.get("table"):
            tables.add(c.get("table"))
    for j in json_spec.get("joins", []):
        tables.add(j.get("left"))
        tables.add(j.get("right"))
    for t in json_spec.get("tables", []):
        if isinstance(t, dict) and t.get("name"):
            tables.add(t.get("name"))
    if "MAKT" not in tables:
        return json_spec
    has_spras = any("SPRAS" in str(f.get("lhs", "")).upper() for f in json_spec.get("filters", []))
    if has_spras:
        return json_spec
    json_spec.setdefault("filters", [])
    json_spec["filters"].append({"lhs": "MAKT.SPRAS", "operator": "=", "rhs": language})
    return json_spec


def ensure_delivery_chain_in_spec(json_spec: dict) -> dict:
    """When VBRP and LIKP are in spec, ensure VBFA (VBRP->VBFA->LIKP), LIKP-LIPS, and LIKP.VBELN in columns."""
    if not json_spec:
        return json_spec
    columns = json_spec.get("columns", [])
    joins = json_spec.get("joins", [])
    tables_info = json_spec.get("tables", [])
    tables_from_cols = {c.get("table") for c in columns if c.get("table")}
    tables_from_joins = set()
    for j in joins:
        tables_from_joins.add(j.get("left"))
        tables_from_joins.add(j.get("right"))
    tables_from_info = {t.get("name") for t in tables_info if isinstance(t, dict) and t.get("name")}
    all_tables = tables_from_cols | tables_from_joins | tables_from_info
    if "VBRP" not in all_tables or "LIKP" not in all_tables:
        return json_spec
    join_pairs = {(j.get("left"), j.get("right")) for j in joins}
    added_joins = []
    if ("VBRP", "VBFA") not in join_pairs and ("VBFA", "VBRP") not in join_pairs:
        added_joins.append({"left": "VBRP", "right": "VBFA", "on": "VBRP.VBELN = VBFA.VBELN AND VBRP.POSNR = VBFA.POSNN", "type": "left"})
    if ("VBFA", "LIKP") not in join_pairs and ("LIKP", "VBFA") not in join_pairs:
        added_joins.append({"left": "VBFA", "right": "LIKP", "on": "VBFA.VBELV = LIKP.VBELN", "type": "left"})
    if ("LIKP", "LIPS") not in join_pairs and ("LIPS", "LIKP") not in join_pairs:
        added_joins.append({"left": "LIKP", "right": "LIPS", "on": "LIKP.VBELN = LIPS.VBELN", "type": "left"})
    if added_joins:
        json_spec.setdefault("joins", [])
        json_spec["joins"].extend(added_joins)
    has_likp_vbeln = any(c.get("table") == "LIKP" and c.get("name") == "VBELN" for c in columns)
    if not has_likp_vbeln and "LIKP" in all_tables:
        json_spec.setdefault("columns", [])
        json_spec["columns"].append({"table": "LIKP", "name": "VBELN", "description": "delivery_number"})
    return json_spec


def load_column_mappings(selected_tables: List[str], base_path: Optional[Path] = None) -> Dict[str, Dict[str, str]]:
    """Load column mappings from app/table_mapping/{table}.json. Returns {table_name: {col: description}}."""
    mappings = {}
    if base_path is None:
        base_path = Path(__file__).resolve().parent.parent
    folder = base_path / "table_mapping"
    if not folder.exists():
        return mappings
    for tbl in selected_tables:
        path = folder / f"{tbl}.json"
        if path.exists():
            try:
                with path.open("r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    mappings[tbl] = data
            except json.JSONDecodeError as e:
                logger.warning("JSON decode error in %s: %s", path, e)
    return mappings


# --- Result shaping (list of dicts in/out) ---

def _get_material_number_column(cols: List[str]) -> str:
    for c in cols:
        if not c:
            continue
        cu = (c or "").upper().replace(" ", "_")
        if cu in ("MATNR", "MATERIAL_NUMBER", "IDNRK") or "MATERIAL_NUMBER" in cu:
            return c
    return ""


def _get_product_display_column(cols: List[str]) -> str:
    for c in cols:
        if not c:
            continue
        cu = (c or "").upper().replace(" ", "_")
        if cu in ("MAKTX", "MATERIAL_NAME", "PRODUCT_NAME") or "MATERIAL_DESCRIPTION" in cu or (cu != "MATNR" and "DESCRIPTION" in cu and "MATERIAL" in cu):
            return c
    return ""


def _get_customer_name_column(cols: List[str]) -> str:
    for c in cols:
        if not c:
            continue
        cu = (c or "").upper().replace(" ", "_")
        if cu in ("NAME1", "CUSTOMER_NAME") or (cu != "KUNNR" and "CUSTOMER" in cu and "NAME" in cu):
            return c
    return ""


def _find_numeric_value_column(cols: List[str], rows: List[Dict[str, Any]]) -> str:
    for c in cols:
        if not c:
            continue
        cu = (c or "").upper()
        if "NETWR" in cu or "NET_VALUE" in cu or "VALUE" in cu or "REVENUE" in cu:
            return c
    if rows:
        for key in rows[0].keys():
            try:
                v = rows[0].get(key)
                if v is not None and isinstance(v, (int, float)):
                    return key
            except Exception:
                pass
    return ""


def deduplicate_material_price_rows(rows: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], bool]:
    """One row per material when result has material + price/description. Returns (rows, was_deduped)."""
    if not rows:
        return rows, False
    cols = list(rows[0].keys())
    matnr_col = _get_material_number_column(cols)
    if not matnr_col:
        return rows, False
    seen = set()
    out = []
    for r in rows:
        key = str(r.get(matnr_col, "")).strip()
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return (out, len(out) < len(rows))


def deduplicate_supplier_per_part_rows(rows: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], bool]:
    """One row per (material, vendor). Returns (rows, was_deduped)."""
    if not rows:
        return rows, False
    cols = list(rows[0].keys())
    vendor_col = None
    for c in cols:
        cu = (c or "").upper().replace(" ", "_")
        if cu in ("LIFNR", "VENDOR_NUMBER") or "VENDOR_NAME" in cu:
            vendor_col = c
            break
    if not vendor_col:
        return rows, False
    mat_col = _get_material_number_column(cols) or _get_product_display_column(cols)
    if not mat_col:
        return rows, False
    seen = set()
    out = []
    for r in rows:
        key = (str(r.get(mat_col, "")).strip(), str(r.get(vendor_col, "")).strip())
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return (out, len(out) < len(rows))


def aggregate_by_customer_sales(rows: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], bool]:
    """One row per customer with summed value. Returns (rows, was_aggregated)."""
    if not rows:
        return rows, False
    cols = list(rows[0].keys())
    customer_num_col = None
    for c in cols:
        cu = (c or "").upper().replace(" ", "_")
        if cu in ("KUNNR", "CUSTOMER_NUMBER"):
            customer_num_col = c
            break
    customer_name_col = _get_customer_name_column(cols)
    group_col = customer_num_col if customer_num_col else customer_name_col
    value_col = _find_numeric_value_column(cols, rows)
    if not group_col or not value_col:
        return rows, False
    agg = defaultdict(lambda: {"_sum": 0})
    for r in rows:
        g = str(r.get(group_col, "")).strip()
        try:
            v = float(r.get(value_col) or 0)
        except (TypeError, ValueError):
            v = 0
        agg[g]["_sum"] += v
        if g not in agg or "_row" not in agg[g]:
            agg[g]["_row"] = dict(r)
    out = []
    for g, data in agg.items():
        row = dict(data["_row"])
        row[value_col] = data["_sum"]
        out.append(row)
    out.sort(key=lambda r: (r.get(value_col) or 0), reverse=True)
    return (out, len(out) < len(rows))


def filter_dataframe_by_product_name_if_requested(
    user_query: str, rows: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Keep only rows whose material description contains the product name from the query."""
    if not user_query or not rows:
        return rows
    product_name = _extract_product_name_from_query(user_query)
    if not product_name:
        return rows
    cols = list(rows[0].keys())
    desc_col = _get_product_display_column(cols)
    if not desc_col:
        return rows
    pn_upper = product_name.upper()
    out = []
    for r in rows:
        val = str(r.get(desc_col, "") or "")
        if pn_upper in val.upper():
            out.append(r)
    return out if out else rows


def apply_procurement_type_display(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Replace BESKZ/procurement_type values with 'E (In-house produced)', etc."""
    if not rows:
        return rows
    cols = list(rows[0].keys())
    col = None
    for c in cols:
        cu = (c or "").upper().replace(" ", "_")
        if cu in ("BESKZ", "PROCUREMENT_TYPE") or "PROCUREMENT_TYPE" in cu:
            col = c
            break
    if not col:
        return rows
    out = []
    for r in rows:
        r = dict(r)
        val = (r.get(col) or "")
        r[col] = PROCUREMENT_TYPE_DISPLAY_LABELS.get(str(val).strip().upper(), val)
        out.append(r)
    return out


def apply_industry_display(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Replace industry codes (BRSCH, etc.) with full sector names."""
    if not rows:
        return rows
    cols = list(rows[0].keys())
    industry_col = None
    for c in cols:
        cu = (c or "").upper().replace(" ", "_")
        if cu in ("BRSCH", "MBRSH", "INDUSTRY_KEY") or "INDUSTRY" in cu:
            industry_col = c
            break
    if not industry_col:
        return rows
    out = []
    for r in rows:
        r = dict(r)
        code = str(r.get(industry_col, "") or "").strip()
        r[industry_col] = INDUSTRY_SECTOR_LABELS.get(code, INDUSTRY_SECTOR_LABELS.get(code.upper(), code or "Not specified"))
        out.append(r)
    return out


# --- Fallback SQL (Postgres) ---

def strip_where_from_sql(sql: str) -> str:
    """Remove WHERE clause for sample/no-filter run."""
    if not sql or "WHERE" not in sql.upper():
        return sql
    upper = sql.upper()
    idx = upper.find("\nWHERE ")
    if idx == -1:
        idx = upper.find(" WHERE ")
    if idx == -1:
        return sql
    before = sql[:idx]
    after = sql[idx + 7 :]
    order_pos = after.upper().find("\nORDER BY")
    if order_pos != -1:
        after = after[order_pos:]
    else:
        semi = after.find(";")
        after = after[semi:] if semi != -1 else ";"
    return before + after


def get_core_billing_sql(limit: int = 100) -> str:
    """Minimal Postgres SQL: VBRK, VBRP, VBAK, KNA1, VBFA, LIKP (process flow)."""
    return f'''SELECT
    v1."VBELN" AS "Billing_document_number",
    v2."AUBEL" AS "Sales_order_number",
    likp."VBELN" AS "Delivery_number",
    v."BSTNK" AS "Customer_purchase_order_number",
    v1."NETWR" AS "Net_value",
    v1."FKDAT" AS "Billing_date",
    k."KUNNR" AS "Customer_number",
    k."NAME1" AS "Customer_name"
FROM "VBRK" AS v1
JOIN "VBRP" AS v2 ON v1."VBELN" = v2."VBELN"
JOIN "VBAK" AS v ON v2."AUBEL" = v."VBELN"
LEFT JOIN "VBFA" AS vbfa ON v2."VBELN" = vbfa."VBELN" AND v2."POSNR" = vbfa."POSNN"
LEFT JOIN "LIKP" AS likp ON vbfa."VBELV" = likp."VBELN"
JOIN "KNA1" AS k ON v1."KUNAG" = k."KUNNR"
ORDER BY v1."NETWR" DESC
LIMIT {limit};'''


def _is_product_performance_query(user_query: str) -> bool:
    if not user_query or not isinstance(user_query, str):
        return False
    q = user_query.lower().strip()
    if "product" not in q and "products" not in q:
        return False
    return any(
        p in q for p in (
            "product analysis", "product performance", "best product", "top product",
            "product data performance", "comparative market", "similar product"
        )
    )


def get_product_performance_fallback_sql(
    user_query: str, with_date_filter: bool = True
) -> Optional[str]:
    """Postgres SQL for product performance (VBRK, VBRP, MAKT) with optional year filter."""
    if not _is_product_performance_query(user_query):
        return None
    q = (user_query or "").strip()
    start_year = end_year = None
    if with_date_filter:
        range_m = re.search(r"(?:year\s+)?(\d{4})\s+to\s+(\d{4})", q, re.IGNORECASE)
        if range_m:
            start_year, end_year = range_m.group(1), range_m.group(2)
        else:
            single_m = re.search(r"year\s+(\d{4})\b", q, re.IGNORECASE)
            if single_m:
                start_year = end_year = single_m.group(1)
    fktyp_in = ", ".join(f"'{c}'" for c in REVENUE_BILLING_CATEGORIES)
    where_parts = [f'vbrk."FKTYP" IN ({fktyp_in})']
    if with_date_filter and start_year and end_year:
        where_parts.append(f"vbrk.\"FKDAT\" >= '{start_year}0101'")
        where_parts.append(f"vbrk.\"FKDAT\" <= '{end_year}1231'")
    where_sql = " AND ".join(where_parts)
    sql = f'''SELECT
  vbrp."MATNR" AS material_number,
  makt."MAKTX" AS material_description,
  vbrp."NETWR" AS net_value
FROM "VBRK" AS vbrk
JOIN "VBRP" AS vbrp ON vbrk."VBELN" = vbrp."VBELN"
JOIN "MAKT" AS makt ON makt."MATNR" = vbrp."MATNR" AND makt."SPRAS" = 'E'
WHERE {where_sql}
ORDER BY vbrp."NETWR" DESC
LIMIT 100'''
    return sql


# --- Procurement / sales-by-customer ---

def is_procurement_only_query(user_query: str) -> bool:
    q = (user_query or "").strip().lower()
    has_procurement = any(
        x in q for x in (
            "procured internally", "procured externally", "internally and externally",
            "procurement type", "which are internal", "which are external", "which products are procured"
        )
    )
    list_ref = any(
        x in q for x in (
            "from the list below", "from the list above", "from these products",
            "which of these", "which products listed", "from the previous", "from the prior"
        )
    )
    return bool(has_procurement and (list_ref or "which products" in q or "which are" in q))


def is_from_list_below_procurement_query(user_query: str) -> bool:
    q = (user_query or "").strip().lower()
    list_ref = any(
        x in q for x in (
            "from the list below", "from the list above", "from these products",
            "which of these", "which products listed", "from the previous", "from the prior"
        )
    )
    procurement = any(
        x in q for x in (
            "procured internally", "procured externally", "procurement type",
            "which are internal", "which are external", "which products are procured"
        )
    )
    return bool(list_ref and procurement)


def is_sales_by_customer_query(user_query: str) -> bool:
    if not (user_query or "").strip():
        return False
    q = (user_query or "").lower().strip()
    if "product" in q and ("by industry" in q or "per industry" in q):
        return False
    if "best selling" in q and "industry" in q:
        return False
    return any(
        x in q for x in (
            "by customer", "sales by customer", "revenue by customer",
            "highest sales", "best sales", "sales totals per customer",
            "totals per customer", "top customers", "customer sales", "customer revenue"
        )
    )


def get_material_numbers_from_dataframe(rows: List[Dict[str, Any]]) -> List[str]:
    """Extract unique material numbers from result rows."""
    if not rows:
        return []
    cols = list(rows[0].keys())
    mat_cols = []
    for c in cols:
        lower = (c or "").lower()
        if lower in ("material_number", "matnr", "main_material_number", "component_material", "component_material_number", "idnrk"):
            mat_cols.append(c)
    if not mat_cols:
        for c in cols:
            if "material" in (c or "").lower() and "number" in (c or "").lower():
                mat_cols.append(c)
                break
    out = []
    for c in mat_cols:
        for r in rows:
            v = r.get(c)
            if v is not None and str(v).strip():
                out.append(str(v).strip())
    return list(dict.fromkeys(out))


def query_procurement_type_for_materials(
    run_sql_fn: Callable[[str], List[Dict[str, Any]]],
    matnr_list: List[str],
) -> Tuple[List[Dict[str, Any]], str]:
    """Run MARA+MAKT+MARC for given material numbers; return (rows, sql_used)."""
    if not matnr_list:
        return [], ""
    matnr_list = list(matnr_list)[:500]
    safe = [f"'{str(m).strip().replace(chr(39), chr(39)+chr(39))}'" for m in matnr_list if str(m).strip()]
    if not safe:
        return [], ""
    in_clause = ", ".join(safe)
    sql = f'''
SELECT
    m1."MATNR" AS material_number,
    m."MAKTX" AS material_description,
    m2."BESKZ" AS procurement_type,
    m2."WERKS" AS plant
FROM "MARA" AS m1
JOIN "MAKT" AS m ON m1."MATNR" = m."MATNR" AND m."SPRAS" = 'E'
JOIN "MARC" AS m2 ON m1."MATNR" = m2."MATNR"
WHERE m1."MATNR" IN ({in_clause})
ORDER BY m."MAKTX", m1."MATNR"
LIMIT 1000
'''
    try:
        rows = run_sql_fn(sql)
        return rows, sql.strip()
    except Exception as e:
        logger.warning("query_procurement_type_for_materials failed: %s", e)
        return [], sql.strip()


# --- Document flow tracing ---

def trace_document_number(
    value: str,
    run_sql_fn: Callable[[str], List[Dict[str, Any]]],
) -> Tuple[Optional[str], Dict[str, Optional[List[Dict[str, Any]]]]]:
    """Trace where document number appears across VBRK, VBRP, LIKP, LIPS, VBAK, VBAP, VBFA, BSAD, BSID. Returns (normalized_value, results_dict)."""
    raw = (value or "").strip()
    if not raw:
        return None, {}
    normalized = raw.zfill(DOCUMENT_NUMBER_LENGTH) if raw.isdigit() else raw
    safe = normalized.replace("'", "''")
    results = {}
    queries = [
        ("VBRK.VBELN", f'SELECT "VBELN", "KUNAG", "FKDAT", "NETWR" FROM "VBRK" WHERE "VBELN" = \'{safe}\' LIMIT 50'),
        ("VBRP.VBELN", f'SELECT "VBELN", "AUBEL", "AUPOS", "MATNR", "NETWR" FROM "VBRP" WHERE "VBELN" = \'{safe}\' LIMIT 50'),
        ("VBRP.AUBEL", f'SELECT "VBELN", "AUBEL", "AUPOS", "MATNR", "NETWR" FROM "VBRP" WHERE "AUBEL" = \'{safe}\' LIMIT 50'),
        ("VBAK.VBELN", f'SELECT "VBELN", "BSTNK", "KUNNR", "AUDAT", "NETWR" FROM "VBAK" WHERE "VBELN" = \'{safe}\' LIMIT 50'),
        ("LIKP.VBELN", f'SELECT "VBELN", "KUNNR", "LFDAT" FROM "LIKP" WHERE "VBELN" = \'{safe}\' LIMIT 50'),
        ("LIPS.VBELN", f'SELECT "VBELN", "POSNR", "VGBEL", "VGPOS", "MATNR", "NETWR" FROM "LIPS" WHERE "VBELN" = \'{safe}\' LIMIT 50'),
        ("BSAD.VBELN", f'SELECT "VBELN", "BELNR", "BUKRS", "GJAHR", "AUGDT", "KUNNR" FROM "BSAD" WHERE "VBELN" = \'{safe}\' LIMIT 50'),
    ]
    for key, q in queries:
        try:
            results[key] = run_sql_fn(q)
        except Exception:
            results[key] = None
    return normalized, results


def get_document_flow_for_order(
    normalized_order: str,
    run_sql_fn: Callable[[str], List[Dict[str, Any]]],
) -> Optional[Dict[str, Any]]:
    """Order -> delivery -> invoice -> accounting doc flow for a sales order number."""
    if not (normalized_order or isinstance(normalized_order, str)):
        return None
    safe = str(normalized_order).strip().replace("'", "''")
    out = {"order": normalized_order, "deliveries": [], "billings": [], "accounting_docs": [], "flow_chain": [("Order", normalized_order)]}
    try:
        q_del = f'SELECT DISTINCT "VBELN" AS delivery FROM "VBFA" WHERE "VBELV" = \'{safe}\' LIMIT 100'
        rows = run_sql_fn(q_del)
        if rows and "delivery" in rows[0]:
            out["deliveries"] = list({str(r["delivery"]).strip() for r in rows})
            for d in out["deliveries"]:
                out["flow_chain"].append(("Delivery", d))
        q_bill = f'SELECT DISTINCT "VBELN" AS billing FROM "VBRP" WHERE "AUBEL" = \'{safe}\' LIMIT 100'
        rows = run_sql_fn(q_bill)
        if rows and "billing" in rows[0]:
            out["billings"] = list({str(r["billing"]).strip() for r in rows})
            for b in out["billings"]:
                out["flow_chain"].append(("Invoice", b))
    except Exception as e:
        logger.warning("get_document_flow_for_order failed: %s", e)
    return out if (out["deliveries"] or out["billings"]) else None


# --- Dynamic analysis plan & perform (return dict for API) ---

def get_dynamic_analysis_plan(
    user_query: str,
    rows: List[Dict[str, Any]],
    openai_client: Any,
) -> Dict[str, Any]:
    """LLM suggests calculations, visualizations, data_notes from columns. Returns {calculations, visualizations, data_notes}."""
    if not rows:
        return {}
    cols = list(rows[0].keys())
    col_str = " ".join(str(c).upper() for c in cols)
    procurement_only = is_procurement_only_query(user_query or "")
    has_procurement_col = "PROCUREMENT_TYPE" in col_str or "BESKZ" in col_str
    procurement_instruction = ""
    if procurement_only and has_procurement_col:
        procurement_instruction = """
**IMPORTANT — Procurement-only:** Suggest ONLY visualizations by procurement_type (bar/pie: x/labels = procurement_type, agg = count). One short data_note: "Procurement Type (MARC.BESKZ): E = In-house, F = External, X = Both."
"""
    prompt = f"""
User query: "{user_query}"

Available columns: {json.dumps(cols, indent=2)}
{procurement_instruction}

Task: Suggest calculations, charts (bar, pie, line), and optional data_notes. Use exact column names. Return JSON only:
{{ "calculations": ["sum of <col>", ...], "visualizations": [{{ "type": "bar", "x": "<col>", "y": "<col>", "agg": "sum" }}, ...], "data_notes": ["..."] }}
"""
    try:
        resp = openai_client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
        )
        content = (resp.choices[0].message.content or "").strip()
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            m = re.search(r"\{.*\}", content, re.DOTALL)
            return json.loads(m.group(0)) if m else {}
    except Exception as e:
        logger.warning("get_dynamic_analysis_plan failed: %s", e)
        return {}


def perform_analysis_from_plan(
    rows: List[Dict[str, Any]],
    plan: Dict[str, Any],
    user_query: str,
) -> Dict[str, Any]:
    """Compute calculations and build chart-ready data from plan. Returns {calculations: [...], visualizations: [...], data_notes: [...]}."""
    if not rows or not plan:
        return plan or {}
    cols = list(rows[0].keys())
    calculations_out = []
    for calc in plan.get("calculations") or []:
        low = (calc or "").lower()
        if "sum of" in low:
            rest = (calc.split("sum of")[-1] or "").strip().split(" grouped by ")[0].split(" group by ")[0].strip()
            for c in cols:
                if rest in c or c in rest:
                    total = sum(float(r.get(c) or 0) for r in rows)
                    calculations_out.append({"description": calc, "value": total})
                    break
    vis_out = []
    for v in plan.get("visualizations") or []:
        x = v.get("x") or v.get("labels")
        y = v.get("y") or v.get("values")
        agg = v.get("agg", "sum")
        if not x or not y:
            continue
        if x not in cols:
            x = next((c for c in cols if (x or "").lower() in (c or "").lower()), x)
        if y not in cols:
            y = next((c for c in cols if (y or "").lower() in (c or "").lower()), y)
        if x not in cols or y not in cols:
            continue
        groups = defaultdict(list)
        for r in rows:
            k = str(r.get(x, "")).strip()
            groups[k].append(r.get(y))
        if agg == "sum":
            data = [{"name": k, "value": sum(float(v or 0) for v in vals)} for k, vals in groups.items()]
        else:
            data = [{"name": k, "value": len(vals)} for k, vals in groups.items()]
        vis_out.append({"type": v.get("type", "bar"), "x_key": x, "y_key": y, "data": data})
    return {
        "calculations": calculations_out,
        "visualizations": vis_out,
        "data_notes": plan.get("data_notes") or [],
    }


# --- Insights (multi-provider) & COGS ---

def get_insights_from_provider(
    provider: str,
    user_query: str,
    rows: List[Dict[str, Any]],
    openai_client: Any,
    pdf_text: str = "",
    sql_query: str = "",
) -> str:
    """Single provider insight. provider in ('chatgpt', 'claude', 'gemini', 'perplexity')."""
    if not rows:
        return "No data available to analyze."
    data_summary = f"Columns: {list(rows[0].keys())}\n\nSample:\n{json.dumps(rows[:50], default=str)}"
    prompt = f"""You are an expert analyst. Provide concise insights from the data (industry trends, customer revenue, products, market context). Use ONLY the numbers from the data.

User question: {user_query}
Data summary:
{data_summary}
"""
    if sql_query:
        prompt += f"\nSQL that produced this data:\n```\n{sql_query[:4000]}\n```\n"
    if pdf_text:
        prompt += f"\nAdditional context from PDF:\n{pdf_text[:15000]}\n"
    provider = (provider or "chatgpt").strip().lower()
    try:
        if provider == "chatgpt" and openai_client:
            r = openai_client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
            )
            return (r.choices[0].message.content or "").strip()
        # Optional: add claude, gemini, perplexity via env keys
        return "Provider not configured."
    except Exception as e:
        return f"Error from {provider}: {e}"


def get_insights_from_all_providers(
    user_query: str,
    rows: List[Dict[str, Any]],
    openai_client: Any,
    pdf_text: str = "",
    sql_query: str = "",
) -> List[Tuple[str, str]]:
    """Run ChatGPT (and optionally others); return [(provider_display_name, text), ...]."""
    results = []
    text = get_insights_from_provider("chatgpt", user_query, rows, openai_client, pdf_text=pdf_text, sql_query=sql_query)
    if text and "not configured" not in text.lower():
        results.append(("ChatGPT (OpenAI)", text))
    if not results:
        results.append(("No result", "No provider returned a valid analysis."))
    return results


def pick_best_analysis(user_query: str, responses: List[Tuple[str, str]], openai_client: Any) -> Tuple[str, str, List[Tuple[str, str]]]:
    """Given [(provider_name, text), ...], return (best_provider, best_text, alternatives)."""
    if not responses:
        return "", "", []
    if len(responses) == 1:
        return responses[0][0], responses[0][1], []
    analyses_text = "\n\n".join(f"[PROVIDER: {name}]\n{text[:4000]}" for name, text in responses)
    judge_prompt = f"""Rank the following analyses by quality (insights, clarity, actionability). Reply with provider names in order, best first, comma-separated.

User question: {user_query}

{analyses_text}
"""
    try:
        r = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": judge_prompt}],
            temperature=0,
        )
        order_str = (r.choices[0].message.content or "").strip()
        order = [n.strip() for n in order_str.split(",") if n.strip()]
        name_to_response = {name: (name, text) for name, text in responses}
        best_name = None
        for n in order:
            for rname in name_to_response:
                if n.lower() in rname.lower() or rname.lower() in n.lower():
                    best_name = rname
                    break
            if best_name:
                break
        if not best_name and responses:
            best_name = responses[0][0]
        if best_name:
            best = name_to_response[best_name]
            others = [(nm, tx) for nm, tx in responses if nm != best_name]
            return best[0], best[1], others
    except Exception:
        pass
    return responses[0][0], responses[0][1], responses[1:]


def get_cogs_calculation_answer_if_asked(user_query: str, rows: List[Dict[str, Any]]) -> Optional[str]:
    """If user asks how cost of goods is calculated, return explanation + note when all cost values are zero."""
    if not user_query or not isinstance(user_query, str) or not rows:
        return None
    q = user_query.strip().lower()
    if not (
        ("cost of goods" in q or "cogs" in q or "cost of the product" in q)
        and ("calculat" in q or "how" in q or "what" in q or "explain" in q)
    ):
        return None
    cost_cols = []
    for c in rows[0].keys():
        cu = (c or "").upper().replace(" ", "_")
        if any(x in cu for x in ("STANDARD_PRICE", "STPRS", "MOVING_AVERAGE", "VERPR", "COST_COMPONENT", "KST001", "KST002", "KST003")):
            cost_cols.append(c)
    note = ""
    if cost_cols:
        all_zero = True
        for r in rows:
            for c in cost_cols:
                try:
                    v = float(r.get(c) or 0)
                    if v != 0:
                        all_zero = False
                        break
                except (TypeError, ValueError):
                    pass
        if all_zero:
            note = "\n\n---\n\n**About the table above:** All cost values are 0 or empty (prices not released or missing in SAP)."
    return (COGS_CALCULATION_EXPLANATION + note).strip() or None


def get_single_material_cost_summary(user_query: str, rows: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """When result has one material (one row or same MATNR), return detailed cost summary dict for API."""
    if not rows or len(rows) == 0:
        return None
    cols = list(rows[0].keys())
    matnr_col = _get_material_number_column(cols)
    if not matnr_col:
        return None
    unique_matnr = list({str(r.get(matnr_col, "")).strip() for r in rows})
    if len(unique_matnr) != 1:
        return None
    matnr_val = unique_matnr[0]
    row = rows[0]
    cost_keywords = ("standard_price", "stprs", "moving_average", "verpr", "price_unit", "peinh", "price_control", "vprsv", "valuation_area", "bwkey", "cost_component", "kst001", "kst002", "kst003")
    display_labels = {
        "material_number": "Material number", "MATERIAL_NUMBER": "Material number", "matnr": "Material number", "MATNR": "Material number",
        "standard_price": "Standard price", "STANDARD_PRICE": "Standard price", "stprs": "Standard price", "STPRS": "Standard price",
        "moving_average_price": "Moving average price", "MOVING_AVERAGE_PRICE": "Moving average price", "verpr": "Moving average price", "VERPR": "Moving average price",
        "price_unit": "Price unit", "PRICE_UNIT": "Price unit", "peinh": "Price unit", "PEINH": "Price unit",
    }
    desc_col = _get_product_display_column(cols)
    out = {"material_number": matnr_val, "fields": []}
    if desc_col:
        out["description"] = row.get(desc_col, "")
    for c in cols:
        if c in (matnr_col, desc_col):
            continue
        cu = (c or "").upper().replace(" ", "_")
        if any(kw in cu for kw in cost_keywords):
            label = display_labels.get(cu, display_labels.get(c, c))
            val = row.get(c)
            out["fields"].append({"label": label, "value": val})
    if len(out["fields"]) < 1:
        return None
    requested = _extract_material_number_from_query(user_query)
    if requested and requested.upper() != matnr_val.upper():
        out["note"] = f"Query was for product number **{requested}**; result shows material **{matnr_val}** (exact match from SAP)."
    return out
