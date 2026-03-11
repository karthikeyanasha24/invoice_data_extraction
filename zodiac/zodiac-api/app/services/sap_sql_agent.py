"""
Dynamic NL-to-SQL agent for SAP-style tables stored in the main Postgres DB.

This mirrors the INVOICE_BOT behaviour at a high level:
- LLM picks relevant tables based on the question and table descriptions.
- LLM produces a JSON SQL specification (tables, columns, joins, filters, order_by, limit).
- We convert that JSON spec into real SQL for Postgres and execute it via SQLAlchemy.
- Results are summarized back to the user via another LLM call.

It is intentionally generic and works over the following tables (if present in the DB):
VBRP, VBRK, VBAK, VBAP, VBEP, BSAD, BSEG, FAGLFLEXA, KNA1, KNVP, KNVV, MAKT, MARC, MARM, MEAN, MVKE, T016T.

The goal is to power questions like:
- "show me highest sales by product"
- "compare sales data with invoice data and identify major differences"
- "show me lowest sales by customer and country"
- "show me sales by country and industry"
- "which industry has highest revenues"
- "show me highest sales by customer and product and country"
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from pathlib import Path

from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from ..config.config import OPENAI_API_KEY

logger = logging.getLogger("zodiac-api.sap_sql_agent")

try:
    from openai import OpenAI

    _openai_available = True
except ImportError:  # pragma: no cover - runtime dependency
    OpenAI = None  # type: ignore
    _openai_available = False


# --- Schema config (extensible: edit schema_ai_config.json when adding tables) ---

def _load_schema_config() -> Dict[str, Any]:
    """Load schema_ai_config.json for extensible rules. Returns {} on failure."""
    try:
        root = Path(__file__).resolve().parent.parent
        path = root / "schema_ai_config.json"
        if path.exists():
            with path.open("r", encoding="utf-8") as f:
                cfg = json.load(f)
            return cfg if isinstance(cfg, dict) else {}
    except Exception as e:
        logger.warning("Could not load schema_ai_config.json: %s", e)
    return {}


_SCHEMA_CONFIG: Dict[str, Any] = {}
def _get_schema_config() -> Dict[str, Any]:
    global _SCHEMA_CONFIG
    if not _SCHEMA_CONFIG:
        _SCHEMA_CONFIG = _load_schema_config()
    return _SCHEMA_CONFIG


# --- Static metadata (fallback when mapping/config lack entries) ---------------------------------------------------------------------------

SAP_TABLE_DESCRIPTIONS: Dict[str, str] = {
    # Sales / Billing
    "VBRP": "Billing document item (sales by product, quantities, net values, currencies, customers). Use for: highest sales by product, revenue analysis.",
    "vbrp": "Same as VBRP – billing document item. Use for sales, revenue, product analysis.",
    "VBRK": "Billing document header (invoice-level amounts, dates, currencies, customers).",
    "VBAK": "Sales document header (orders, customers, dates, overall values).",
    "VBAP": "Sales document item (ordered products, quantities, values).",
    "VBEP": "Schedule lines for sales document items (delivery quantities and dates).",
    # Customer / Material Master
    "KNA1": "Customer master (names, addresses, countries, brsch=industry code). IMPORTANT: brsch is a code, use T016T for industry descriptions.",
    "T016T": "Industry text/descriptions (converts brsch codes to readable industry names). Use this for industry labels in charts.",
    "KNVV": "Customer sales data (sales area, pricing, related attributes).",
    "KNVP": "Customer partners (payer, ship-to, bill-to relationships).",
    "MAKT": "Material descriptions (product names).",
    "MARC": "Plant data for material (plant-level material attributes).",
    "MARM": "Units of measure for material (UOM conversion).",
    "MEAN": "International Article Numbers (EAN/UPC) for materials.",
    "MVKE": "Sales data for materials (sales org, distribution channel, pricing group).",
    # Finance / Accounting
    "BSAD": "Customer open and cleared items (AR line items, payments).",
    "BSEG": "Accounting document segment (line items for GL, customers, vendors).",
    "FAGLFLEXA": (
        "New G/L actual line items – GL cost/revenue postings with profit center, cost center, account. "
        "Key columns: prctr (profit center), racct (GL account), rbukrs (company code), "
        "hsl (amount in LOCAL currency – primary aggregation column), "
        "wsl (transaction currency amount), tsl (transaction currency alternative), "
        "ksl (controlling area currency), osl (object currency), "
        "ryear (fiscal year), gjahr (fiscal year alt), poper (posting period 01-12), "
        "drcrk (debit/credit: S=debit/expense, H=credit/revenue), budat (posting date), "
        "cost_elem (cost element), rcntr (cost center), rtcur (transaction currency – NOT waers), "
        "rwcur (second local currency), belnr (document number), segment (segment). "
        "IMPORTANT: currency is rtcur NOT waers. Amount in local currency is hsl. "
        "For 'total cost by profit center': SELECT prctr, SUM(hsl) FROM FAGLFLEXA GROUP BY prctr. "
        "Use for: GL balances, cost by profit center/cost center/account, P&L analysis."
    ),
    # Logistics – Outbound
    "LIKP": "Outbound delivery header (delivery documents, shipping dates, quantities, ship-to). Use for: deliveries, logistics.",
    "LIPS": "Outbound delivery item (products, quantities, reference to sales order). Use for: delivery line details.",
    # Vendor / Purchasing
    "LFA1": "Vendor master (vendor names, addresses, countries). Use for: supplier analysis, purchasing.",
    "LFB1": "Vendor company code (vendor accounting, payment terms).",
    "LFM1": "Vendor purchasing org (vendor–purchasing org data).",
    "EKKO": "Purchasing document header (PO header, vendor, dates, currency). Use for: purchase orders.",
    "EKPO": "Purchasing document item (PO line items, materials, quantities, values).",
    "EBAN": "Purchase requisition (requisition items, materials, quantities).",
    # Invoice Verification (Vendor Invoices)
    "RBKP": "Vendor invoice header (invoice document, vendor, amount, currency). Use for: vendor invoice analysis.",
    "RSEG": "Vendor invoice item (invoice line items, materials, quantities, amounts).",
    # Material Document / Reservations
    "MKPF": "Material document header (goods movement header, posting date).",
    "RESB": "Reservation/dependent requirements (material reservations, requirements).",
    "LSEG": "Document segment (document item data).",
    # Pricing / Conditions
    "KONV": (
        "Pricing conditions document – stores condition records for pricing (sales price, "
        "discounts, surcharges). "
        "Key columns: knumv (pricing doc number, join key to VBRK.KNUMV / VBAK.KNUMV), "
        "kschl (condition type, e.g. PR00=standard price, K007=customer discount, RA01=rebate), "
        "kbetr (condition amount/rate), waers (currency), kawrt (condition base value), "
        "kappl (application: V=sales, M=purchasing), kposn (condition item). "
        "Use for: sales price conditions, discount analysis, pricing by material/customer group."
    ),
    # Sales Document Flow
    "VBFA": (
        "Sales document flow – links predecessor and successor documents (order→delivery→billing). "
        "Key columns: vbelv (predecessor doc, e.g. sales order), vbeln (successor doc, e.g. delivery/billing), "
        "vbtyp_n (successor type: J=delivery, M=billing, C=order), posnv (predecessor item), "
        "posnn (successor item), matnr (material). "
        "Use for: tracing order-to-invoice flow, finding all deliveries for an order."
    ),
    # Controlling / Profitability
    "COEP": (
        "CO actual line items – cost postings by cost center, profit center, cost element. "
        "Key columns: kostl (cost center), prctr (profit center), kstar (cost element), "
        "wkgbtr (actual amount in controlling area currency), wtgbtr (amount in transaction currency), "
        "belnr (document number), gjahr (fiscal year), poper (posting period). "
        "Use for: actual cost analysis by cost center or profit center."
    ),
    "COSP": (
        "CO plan totals – planned costs by cost center and cost element. "
        "Key columns: kostl (cost center), kstar (cost element), gjahr (fiscal year), "
        "wkg001..wkg016 (planned amounts per period). "
        "Use for: budget vs actual comparisons, planned cost analysis."
    ),
    "CEPC": (
        "Profit center master data – profit center attributes. "
        "Key columns: prctr (profit center), datbi (valid-to date), kokrs (controlling area), "
        "ktext (short description), ltext (long description), verak (person responsible). "
        "Use for: profit center lookups and labels."
    ),
    "CSKS": (
        "Cost center master data – cost center attributes. "
        "Key columns: kostl (cost center), datbi (valid-to), kokrs (controlling area), "
        "ktext (short text), verak (person responsible). "
        "Use for: cost center lookups and labels."
    ),
    # Product Costing
    "CKIS": (
        "Costing items – detailed cost components for a cost estimate per material. "
        "Key columns: kalnr (costing number, join to KEKO.KALNR), "
        "posnr (item), wertn (total cost value – USE SUM(wertn) for standard cost), "
        "wrtfw (value in foreign currency), kstar (cost element), matnr (material), "
        "kostl (cost center), menge (quantity). "
        "Join pattern: KEKO.matnr → KEKO.kalnr = CKIS.kalnr → SUM(CKIS.wertn) "
        "Use for: material cost breakdown by cost element, standard cost components per material/plant."
    ),
    "CKMLCR": (
        "Material ledger cumulative values – actual (periodic) costs per material/plant. "
        "Key columns: kalnr (join to CKMLHD.kalnr for matnr), bdatj (fiscal year), "
        "poper (posting period), stprs (periodic unit price / standard price), "
        "salk3 (total stock value), waers (currency – this table uses waers), "
        "pvprs (preliminary price). "
        "IMPORTANT: CKMLCR has NO matnr column directly. "
        "To get material: JOIN CKMLHD on CKMLCR.kalnr = CKMLHD.kalnr → use CKMLHD.matnr. "
        "Full join: CKMLCR JOIN CKMLHD ON CKMLCR.kalnr = CKMLHD.kalnr "
        "           JOIN MAKT ON CKMLHD.matnr = MAKT.matnr "
        "Use for: actual cost by material/period, inventory valuation, standard price per period."
    ),
    "CKMLHD": (
        "Material ledger header – identifies the material ledger object (kalnr) per material/plant. "
        "Key columns: kalnr (costing number = join key to CKMLCR/KEKO), "
        "matnr (material number), bwkey (valuation area/plant). "
        "Use as bridge table: CKMLCR.kalnr = CKMLHD.kalnr → CKMLHD.matnr = MAKT.matnr."
    ),
    "KEKO": (
        "Cost estimate header – standard cost estimate per material/plant. "
        "Key columns: matnr (material), werks (plant), kalnr (costing number, join to CKIS.KALNR), "
        "kalka (costing type, '01'=standard cost), kadat (costing date), hwaer (currency – NOT waers), "
        "poper (period), bdatj (year). "
        "NOTE: KEKO itself does NOT have stprs. Standard price is in CKMLCR.stprs (actual) or CKIS.wertn (estimate). "
        "Join KEKO.KALNR = CKIS.KALNR for cost breakdown. "
        "Join KEKO.KALNR = CKMLCR.KALNR for periodic actual costs. "
        "Use for: standard cost lookup, cost estimate headers, material cost by plant."
    ),
    # Internal Orders / Production Orders
    "AUFK": (
        "Order master – internal orders and production orders. "
        "Key columns: aufnr (order number), auart (order type), ktext (description), "
        "kostl (responsible cost center), prctr (profit center), werks (plant). "
        "Use for: order analysis, production order lookups."
    ),
    # Bill of Materials
    "STKO": (
        "BOM header – bill of materials header. "
        "Key columns: stlty (BOM type: M=material), stlnr (BOM number, join to STPO.stlnr), "
        "stlal (alternative BOM), datuv (valid-from date), stktx (description). "
        "NOTE: STKO does NOT have matnr. To link to a material, the MAST table is needed "
        "(material-BOM link), but if MAST is unavailable, query STPO directly. "
        "Use for: BOM header information."
    ),
    "STPO": (
        "BOM items – components in a bill of materials. "
        "Key columns: stlnr (BOM number, join to STKO.stlnr), "
        "idnrk (component material number – join to MAKT.matnr for component description), "
        "menge (component quantity), meins (unit of measure), preis (price), waers (currency). "
        "IMPORTANT: idnrk = the component/child material number. "
        "Join STPO.idnrk = MAKT.matnr to get component descriptions. "
        "Use for: BOM component analysis, what materials go into a product."
    ),
    # AR – Accounts Receivable
    "BSAD": (
        "Customer cleared items (AR) – fully posted AR line items. "
        "Key columns: kunnr (customer, join to KNA1), bukrs (company code), "
        "dmbtr (amount in local currency), wrbtr (amount in transaction currency), "
        "waers (currency), budat (posting date), bldat (document date), "
        "gjahr (fiscal year), belnr (document number), shkzg (debit/credit: S=debit, H=credit). "
        "Use for: AR aging, customer payment analysis, outstanding receivables."
    ),
    # Purchasing Requisition
    "EBAN": (
        "Purchase requisition items – purchase request documents. "
        "Key columns: banfn (requisition number), bnfpo (item), matnr (material), "
        "menge (quantity), meins (UoM), preis (price), waers (currency), "
        "lifnr (preferred vendor), ekgrp (purchasing group), lfdat (delivery date), "
        "erdat (creation date), ebeln (assigned PO number if converted). "
        "Use for: open purchase requisitions, spend request analysis."
    ),
}


# High-level join hints between common SAP tables. This is injected into the LLM
# prompt so that the SQL JSON spec uses realistic join paths instead of guessing.
SAP_JOIN_HINTS = """
Typical business key joins you MUST prefer (do NOT invent other join columns):

SALES / BILLING:
- VBRP (billing items) <-> VBRK (billing header)
  * VBRP.VBELN = VBRK.VBELN
- vbrp: same as VBRP, use vbrp.VBELN = VBRK.VBELN

- VBRK (billing header) <-> KNA1 (customer master)
  * VBRK.KUNAG = KNA1.KUNNR
  * VBRK.KUNRG = KNA1.KUNNR   (payer, if present)

- VBAK (sales order header) <-> VBAP (sales order items)
  * VBAK.VBELN = VBAP.VBELN

- VBAP (order items) / VBRP (billing items) <-> VBEP (schedule lines)
  * VBEP.VBELN = VBAP.VBELN AND VBEP.POSNR = VBAP.POSNR

- VBRP / VBAP / LIPS (items with product) <-> MAKT / MVKE / MARC (material master & descriptions)
  * VBRP.MATNR = MAKT.MATNR = MVKE.MATNR = MARC.MATNR
  * VBAP.MATNR = MAKT.MATNR
  * LIPS.MATNR = MAKT.MATNR

- BSAD / BSEG (AR items) <-> KNA1 (customer master)
  * BSAD.KUNNR = KNA1.KUNNR
  * BSEG.KUNNR = KNA1.KUNNR

TEXT / DESCRIPTION TABLES (IMPORTANT for readable labels):
- KNA1 (customer with brsch code) <-> T016T (industry descriptions)
  * KNA1.brsch = T016T.brsch
  * ALWAYS use T016T.brtxt for industry name (not KNA1.brsch which is just "HITE", "TRAD", "FOOD")

- Materials (MATNR code) <-> MAKT (material text)
  * VBRP.MATNR = MAKT.MATNR or VBAP.MATNR = MAKT.MATNR
  * Use MAKT.MAKTX for product names (not just MATNR codes)

LOGISTICS – OUTBOUND DELIVERY:
- LIKP (delivery header) <-> LIPS (delivery items)
  * LIKP.VBELN = LIPS.VBELN

- LIPS (delivery items) <-> VBAP (sales order items) – reference
  * LIPS.VGBEL = VBAP.VBELN AND LIPS.VGPOS = VBAP.POSNR

- LIKP (delivery) <-> KNA1 (ship-to customer)
  * LIKP.KUNNR = KNA1.KUNNR  (if present)

PURCHASING / VENDOR:
- EKKO (PO header) <-> EKPO (PO items)
  * EKKO.EBELN = EKPO.EBELN

- EKKO / EKPO <-> LFA1 (vendor master)
  * EKKO.LIFNR = LFA1.LIFNR
  * EKPO.LIFNR = LFA1.LIFNR  (if present)

- RBKP (vendor invoice header) <-> RSEG (vendor invoice items)
  * RBKP.BELNR = RSEG.BELNR AND RBKP.GJAHR = RSEG.GJAHR  (if GJAHR present)
  * or RBKP.BELNR = RSEG.BELNR

- RBKP <-> LFA1 (vendor)
  * RBKP.LIFNR = LFA1.LIFNR

- EBAN (purchase req) <-> EKPO (PO items) – optional, via EBAN–EKPO reference fields if present

PRICING CONDITIONS (KONV):
- KONV (pricing conditions) <-> VBRK (billing header)
  * VBRK.KNUMV = KONV.KNUMV
  * IMPORTANT: You MUST join via VBRK (not VBRP) because KNUMV is on VBRK header, not VBRP item.
  * Typical pattern: SELECT ... FROM vbrp JOIN VBRK ON vbrp.VBELN=VBRK.VBELN JOIN KONV ON VBRK.KNUMV=KONV.KNUMV

- Common KONV.KSCHL condition types (filter by these for specific analysis):
  * 'PR00' = Base price / list price
  * 'K007' = Customer discount (%)
  * 'K004' = Material discount
  * 'RA01' = Customer rebate
  * 'VPRS' = Cost-of-goods-sold (COGS) – use this for margin/profitability!
  * 'MWST'/'MWAS' = Tax
  * 'HD00' = Freight/handling

- For DISCOUNT analysis: filter KONV.KSCHL IN ('K007','K004','RA01') and use KONV.KBETR
- For PRICING: filter KONV.KSCHL = 'PR00' and use KONV.KBETR
- For COGS / COST: filter KONV.KSCHL = 'VPRS' and use KONV.KBETR

- KONV (pricing conditions) <-> VBAK (sales order header)
  * VBAK.KNUMV = KONV.KNUMV

SALES DOCUMENT FLOW (VBFA):
- VBFA.VBELV = predecessor document number (e.g. sales order VBELN)
  * VBFA.VBELN = successor document (delivery or billing)
  * Filter VBFA.VBTYP_N for type: 'J'=delivery, 'M'=billing document, 'C'=order

CONTROLLING / PROFITABILITY (COEP, CEPC, CSKS):
- COEP <-> CSKS (cost center master):  COEP.KOSTL = CSKS.KOSTL
- COEP <-> CEPC (profit center master): COEP.PRCTR = CEPC.PRCTR
- FAGLFLEXA <-> CEPC: FAGLFLEXA.PRCTR = CEPC.PRCTR

MATERIAL DOCUMENT:
- MKPF <-> MSEG (if MSEG exists): MKPF.MBLNR = MSEG.MBLNR, MKPF.MJAHR = MSEG.MJAHR
- NOTE: MSEG (material document items) is NOT in this database. Use MKPF for header-level goods movement queries only.

PRODUCT COSTING (STANDARD COST):
- KEKO (cost estimate header) <-> CKIS (costing items)
  * KEKO.KALNR = CKIS.KALNR
  * SUM(CKIS.WERTN) gives total standard cost per material

- KEKO (cost estimate) <-> MAKT (material description)
  * KEKO.MATNR = MAKT.MATNR

MATERIAL LEDGER (ACTUAL COST):
- CKMLCR has NO matnr column. Must join via CKMLHD:
  * CKMLCR.KALNR = CKMLHD.KALNR  (get the material)
  * CKMLHD.MATNR = MAKT.MATNR    (get description)
  * CKMLCR.STPRS = periodic standard price, CKMLCR.SALK3 = stock value
  * Filter by CKMLCR.BDATJ (year), CKMLCR.POPER (period 01-12)

- CKMLHD.BWKEY = plant/valuation area (can filter by plant)

BILL OF MATERIALS (BOM):
- STKO (BOM header) <-> STPO (BOM components)
  * STKO.STLNR = STPO.STLNR  (and STKO.STLTY = STPO.STLTY)

- STPO (component) <-> MAKT (component description)
  * STPO.IDNRK = MAKT.MATNR  (idnrk is the component/child material number)

- NOTE: STKO has NO matnr column. The parent material link requires MAST table which is NOT in DB.
  For "components of material X" queries, you cannot directly filter by parent matnr without MAST.
  Instead, use STPO directly to list components, or query CKIS for cost components.

AR / ACCOUNTS RECEIVABLE:
- BSAD (customer cleared items) <-> KNA1: BSAD.KUNNR = KNA1.KUNNR
- BSEG (accounting line items) <-> KNA1: BSEG.KUNNR = KNA1.KUNNR
- BSAD.DMBTR = amount in local currency, BSAD.SHKZG = S(debit)/H(credit)

PURCHASE REQUISITION:
- EBAN (requisition) <-> LFA1 (vendor): EBAN.LIFNR = LFA1.LIFNR
- EBAN (requisition) <-> EKPO (PO): EBAN.EBELN = EKPO.EBELN AND EBAN.EBELP = EKPO.EBELP

VERY IMPORTANT:
- VBRP / vbrp usually does NOT have KUNNR directly. To reach the customer, go:
  VBRP.VBELN -> VBRK.VBELN, then VBRK.KUNAG -> KNA1.KUNNR.

- When you need INDUSTRY of a customer:
  * NEVER use KNA1.brsch alone (it's just a code like "HITE", "TRAD", "FOOD")
  * ALWAYS join T016T to get the description: T016T.brtxt (readable industry name)
  * Join: KNA1.brsch = T016T.brsch
  * SELECT T016T.brtxt as industry_name (not KNA1.brsch)

- When you need COUNTRY of a customer:
  * PREFERRED: VBRK.LAND1 (country code directly on billing header — no extra join needed)
  * ALTERNATIVE: KNA1.LAND1 via join VBRK.KUNAG = KNA1.KUNNR (only if customer name also needed)

- For cost-related or COGS queries, use EKPO (purchase values), RBKP/RSEG (vendor invoice amounts), BSEG (accounting).

- MARGIN / PROFITABILITY queries:
  * Revenue = SUM(vbrp.NETWR) from billing items
  * COGS option 1 (KONV): JOIN VBRK ON vbrp.VBELN=VBRK.VBELN, JOIN KONV ON VBRK.KNUMV=KONV.KNUMV
    WHERE KONV.KSCHL='VPRS' → SUM(KONV.KBETR) = cost
  * COGS option 2 (purchase cost): JOIN EKPO ON vbrp.MATNR=EKPO.MATNR → SUM(EKPO.NETWR/EKPO.MENGE * vbrp.FKIMG)
  * Gross margin % = (revenue - cost) / revenue * 100
  * Simple margin: SELECT matnr, SUM(netwr) as revenue, ... GROUP BY matnr from vbrp/VBRK

- CURRENCY NOTE (very important):
  * VBRK currency column = WAERK (NOT waers)
  * FAGLFLEXA currency column = RTCUR (NOT waers)
  * KEKO currency column = HWAER (NOT waers)
  * EKKO, RBKP, RSEG, EKPO, KONV, CKMLCR → WAERS (the usual one)
  * Always match the actual currency column name to the table you are querying

- FISCAL YEAR / PERIOD filters:
  * For VBRK/VBRP: use VBRK.FKDAT (billing date, YYYYMMDD format) for date range filters
  * For FAGLFLEXA: use FAGLFLEXA.RYEAR (fiscal year as 4-digit string) and FAGLFLEXA.POPER (period 01-12)
  * For EKKO/RBKP: use BUDAT or BEDAT (YYYYMMDD)
  * For CKMLCR: use BDATJ (year) and POPER (period)
"""


@dataclass
class SqlAgentResult:
    sql: str
    rows: List[Dict[str, Any]]


_QUERY_TO_SQL_CACHE: Dict[str, str] = {}
_SQL_TO_ROWS_CACHE: Dict[str, List[Dict[str, Any]]] = {}


# --- Utility helpers --------------------------------------------------------------------------


def _get_openai_client() -> OpenAI | None:
    if not _openai_available:
        logger.warning("OpenAI package not available for sap_sql_agent")
        return None
    api_key = OPENAI_API_KEY
    if not api_key:
        logger.warning("OPEN_AI_KEY/OPENAI_API_KEY not set for sap_sql_agent")
        return None
    try:
        return OpenAI(api_key=api_key)
    except Exception as e:  # pragma: no cover - network/config
        logger.warning("Failed to create OpenAI client for sap_sql_agent: %s", e)
        return None


def _serialize_value(v: Any) -> Any:
    if isinstance(v, Decimal):
        return float(v)
    if hasattr(v, "isoformat"):
        try:
            return v.isoformat()
        except Exception:
            return str(v)
    if isinstance(v, (bytes, bytearray)):
        return v.decode("utf-8", errors="ignore")
    return v


def _introspect_columns(db: Session, table_names: List[str]) -> Dict[str, Dict[str, str]]:
    """
    Introspect the DB to get columns for each table and build semantic descriptions.

    Priority:
    1) If db_table_mapping.json (generated by test_db_connection.py) exists, use its
       per-column descriptions for any matching tables/columns.
    2) Otherwise, fall back to simple heuristic descriptions.
    """
    insp = inspect(db.bind)
    mapping: Dict[str, Dict[str, str]] = {}

    # Try to load pre-generated mapping file (optional)
    mapping_file: Dict[str, Any] = {}
    try:
        root = Path(__file__).resolve().parent.parent
        path = root / "db_table_mapping.json"
        if path.exists():
            import json as _json  # local import to avoid polluting module namespace

            with path.open("r", encoding="utf-8") as f:
                raw = _json.load(f)
            if isinstance(raw, dict):
                mapping_file = raw
    except Exception:
        # Non-fatal; we just fall back to heuristics
        mapping_file = {}

    # Build a case-insensitive lookup of actual DB tables once
    db_tables = {t.lower(): t for t in insp.get_table_names()}

    for tbl in table_names:
        # Find matching table in DB, case-insensitive
        actual_name = db_tables.get(tbl.lower())
        if not actual_name:
            # This is critical for debugging questions that reference tables
            # like KONV or FAGLFLEXA that might not actually exist in the DB.
            logger.warning("sap_sql_agent: selected table '%s' is not present in the database", tbl)
            continue

        cols: Dict[str, str] = {}
        file_entry = mapping_file.get(actual_name) or mapping_file.get(tbl) or {}
        file_cols = (file_entry.get("columns") or {}) if isinstance(file_entry, dict) else {}

        for col in insp.get_columns(actual_name):
            col_name = col["name"]
            if isinstance(file_cols, dict) and col_name in file_cols:
                # Use human-friendly description from mapping file when available
                cols[col_name] = str(file_cols[col_name])
            else:
                # Simple heuristic description; LLM will still see raw names
                cols[col_name] = f"{tbl}.{col_name} column"

        if cols:
            mapping[actual_name] = cols

    return mapping


def _get_table_descriptions(db: Session) -> Dict[str, str]:
    """
    Build table descriptions. Priority (mapping-first, adaptive for new tables):
    1) db_table_mapping.json meta.description
    2) schema_ai_config.json table_semantic_hints
    3) SAP_TABLE_DESCRIPTIONS (fallback)
    4) Generic fallback

    Skip tables from schema_ai_config skip_tables.
    """
    insp = inspect(db.bind)
    db_table_names = insp.get_table_names()
    cfg = _get_schema_config()
    skip_set = {s.lower() for s in (cfg.get("skip_tables") or [])}
    db_table_names = [t for t in db_table_names if t.lower() not in skip_set]

    mapping_file: Dict[str, Any] = {}
    try:
        root = Path(__file__).resolve().parent.parent
        path = root / "db_table_mapping.json"
        if path.exists():
            import json as _json
            with path.open("r", encoding="utf-8") as f:
                raw = _json.load(f)
            if isinstance(raw, dict):
                mapping_file = raw
    except Exception:
        pass

    table_hints = (cfg.get("table_semantic_hints") or {})
    out: Dict[str, str] = {}
    for actual_name in db_table_names:
        # 1) Mapping meta (from db_table_mapping.json - updated by refresh_schema_for_ai.py)
        entry = mapping_file.get(actual_name) or mapping_file.get(actual_name.upper())
        if isinstance(entry, dict) and entry.get("meta", {}).get("description"):
            desc = str(entry["meta"]["description"])
            if desc and desc != f"{actual_name} table":
                out[actual_name] = desc
                continue
        # 2) Config table_semantic_hints (extensible - add new tables here)
        desc = table_hints.get(actual_name) or table_hints.get(actual_name.upper())
        if desc:
            out[actual_name] = desc
            continue
        # 3) Hardcoded fallback
        desc = SAP_TABLE_DESCRIPTIONS.get(actual_name) or SAP_TABLE_DESCRIPTIONS.get(actual_name.upper())
        if desc:
            out[actual_name] = desc
            continue
        # 4) Generic
        out[actual_name] = f"{actual_name} table – check columns for available fields."
    return out


def _pick_tables(
    question: str,
    client: OpenAI,
    db: Session,
    knowledge_context: Optional[str] = None,
) -> List[str]:
    """
    Pick tables needed to answer the question. Uses dynamic table list from DB +
    mapping so new tables are auto-detected. User knowledge (e.g. "use these for costs")
    is injected when provided.
    """
    table_descriptions = _get_table_descriptions(db)
    if not table_descriptions:
        table_descriptions = SAP_TABLE_DESCRIPTIONS  # fallback

    # ── Helper: get numeric column names from schema config (no hardcoding) ──
    _cfg = _get_schema_config()
    _numeric_col_names = {c.upper() for c in (_cfg.get("numeric_columns") or [])}

    # ── Build a schema-based lookup: which tables have at least one numeric column ──
    # This lets us detect "dimension-only" tables without hardcoding table names.
    def _table_has_numeric_col(tbl_name: str) -> bool:
        """Return True if the table has any column that appears in numeric_columns config."""
        # We need column info from db_table_mapping.json (already in table_descriptions
        # as meta, or we can introspect quickly)
        try:
            from ..database import SessionLocal  # noqa: F401 – only used for quick check
        except Exception:
            pass
        # Use column_mappings from DB introspection cache if available; otherwise
        # check column names we know about from db_table_mapping / SAP_TABLE_DESCRIPTIONS.
        # This is best-effort; if we can't determine, assume the table has numeric columns.
        known_numeric_tables = {
            "VBRP", "VBRK", "EKPO", "EKKO", "RBKP", "RSEG",
            "FAGLFLEXA", "COEP", "KEKO", "CKIS", "BSAD", "BSEG",
            "LIKP", "LIPS", "VBAP", "VBAK",
        }
        return tbl_name.upper() in known_numeric_tables

    q_lower = (question or "").lower()
    db_tables_lower = {t.lower(): t for t in table_descriptions}

    # ── STEP 1: Detect if user explicitly named any tables in the question ──
    # e.g. "from FAGLFLEXA", "using KNA1 and T016T", "KONV pricing conditions"
    explicit_tables: List[str] = []
    for tbl_name in table_descriptions.keys():
        name_lower = tbl_name.lower()
        if name_lower and len(name_lower) >= 3 and name_lower in q_lower:
            explicit_tables.append(tbl_name)

    if explicit_tables:
        logger.info("sap_sql_agent: user explicitly named tables: %s", explicit_tables)

        # ── STEP 1a: Detect if this is a pure listing/filter query ────────────
        # Pure listing queries (e.g. "show all products containing 'jacket' from MAKT",
        # "list all customers in Germany") do NOT need fact/transaction tables.
        # Only add fact tables when the question asks for aggregation/amounts.
        _aggregation_signals = (
            "total", "sum", "revenue", "sales", "spend", "cost", "amount",
            "how much", "count", "how many", "average", "avg",
            "highest", "lowest", "top", "best", "worst", "most", "least",
            "maximum", "minimum", "by customer", "by product", "by country",
            "by vendor", "by material", "margin", "profit", "price",
            "ranking", "rank", "compare",
        )
        _is_aggregation_query = any(sig in q_lower for sig in _aggregation_signals)

        # ── STEP 1b: Schema-driven fact-table enrichment ──────────────────────
        # Only enrich with fact tables if the question clearly needs aggregation.
        # For pure listing/filter queries (containing, with word, list/show + single table),
        # the dimension table alone is sufficient — do NOT add VBRP/VBRK unnecessarily.
        has_fact_table = any(_table_has_numeric_col(t) for t in explicit_tables)
        if not has_fact_table and _is_aggregation_query:
            # Ask the LLM to identify missing fact tables given the question + named tables
            enrich_prompt = f"""
The user asked: "{question}"

They explicitly named these database tables: {explicit_tables}

These tables are dimension/lookup tables with no financial amounts.
Given the question, which FACT/TRANSACTION tables from the list below are needed
to actually compute the answer?

If the question is ONLY asking to LIST or FILTER records (e.g. "show all products containing X",
"list all customers with Y") and does NOT need totals/sums/counts, return:
{{"fact_tables": []}}

Otherwise return the needed fact tables:
{{"fact_tables": ["<exact_table_name>", ...]}}

Available tables:
{json.dumps(table_descriptions, indent=2)}
"""
            try:
                er = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[{"role": "user", "content": enrich_prompt}],
                    temperature=0,
                )
                ec = er.choices[0].message.content or ""
                try:
                    ed = json.loads(ec)
                except json.JSONDecodeError:
                    m2 = re.search(r"\{.*\}", ec, re.DOTALL)
                    ed = json.loads(m2.group(0)) if m2 else {}
                fact_tables = [
                    db_tables_lower.get((t or "").strip().lower())
                    for t in ed.get("fact_tables", [])
                    if isinstance(t, str) and db_tables_lower.get((t or "").strip().lower())
                ]
                for ft in fact_tables:
                    if ft and ft not in explicit_tables:
                        explicit_tables.insert(0, ft)
                logger.info(
                    "sap_sql_agent: added fact tables %s to explicit list", fact_tables
                )
            except Exception as enrich_err:
                logger.warning("sap_sql_agent: fact-table enrichment LLM call failed: %s", enrich_err)
        elif not has_fact_table and not _is_aggregation_query:
            logger.info(
                "sap_sql_agent: pure listing/filter query — using dimension table(s) %s as-is (no fact-table enrichment)",
                explicit_tables,
            )

        return explicit_tables

    # ── STEP 2: Full LLM-driven table selection ───────────────────────────────
    # No hardcoded signal words — the prompt is comprehensive enough to handle
    # ANY question type: revenue, cost, procurement, logistics, GL, etc.
    knowledge_block = ""
    if knowledge_context and knowledge_context.strip():
        knowledge_block = f"""
User preferences / stored knowledge (apply when relevant):
{knowledge_context.strip()}
"""

    prompt = f"""
User question: "{question}"
{knowledge_block}
You are selecting SAP-style database tables needed to answer this business question.

Available tables (use EXACT names):
{json.dumps(table_descriptions, indent=2)}

=== MANDATORY SELECTION RULES ===

1. FACT / TRANSACTION TABLES — always include the table(s) that actually hold the numbers:
   - Sales, billing, revenue, turnover, income → VBRP + VBRK (always both)
   - Purchase orders, procurement, ordered quantity → EKKO + EKPO
   - Vendor invoices, accounts payable → RBKP + RSEG
   - General ledger, profit center accounting, FI postings → FAGLFLEXA
   - Deliveries, shipments, logistics → LIKP + LIPS
   - CO actual costs by cost center → COEP + CSKS
   - Standard cost / unit cost estimates → KEKO (+ CKIS for detail breakdown)
   - Pricing conditions, discounts, surcharges → KONV + VBRK (join on KNUMV)

2. DIMENSION / LOOKUP TABLES — always add these alongside the fact tables:
   - Any question involving customers, buyers, sold-to parties → KNA1
   - Any question involving materials, products, items → MAKT
   - Any question involving vendors, suppliers → LFA1
   - Any question explicitly about "industry" or "sector" → T016T (ONLY with KNA1)
   - Do NOT include T016T unless the question explicitly mentions industry/sector —
     T016T only has brsch and brtxt columns, no financial data.

3. COST-OF-PRODUCT rule:
   - "What is the cost / price of [product]?" or "unit cost" or "standard cost" →
     use KEKO + MAKT (KEKO.stprs = standard price, join KEKO.MATNR = MAKT.MATNR)
   - Do NOT use EKPO for unit cost (EKPO = bulk purchase orders, not unit standard costs)

4. When the user explicitly names specific tables in the question (e.g. "using KONV",
   "from FAGLFLEXA"), include those tables AND any fact/dimension tables needed to
   produce a meaningful answer for the question.

5. Choose the MINIMUM set of tables. Do not include tables unrelated to the question.

Return STRICT JSON only — no explanation:
{{
  "selected_tables": [
    {{ "name": "<exact_table_name>", "reason": "<one line why>" }}
  ]
}}
"""
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
    )
    content = resp.choices[0].message.content or ""
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", content, re.DOTALL)
        data = json.loads(m.group(0)) if m else {}

    tables = [
        t.get("name") for t in data.get("selected_tables", [])
        if isinstance(t, dict) and t.get("name")
    ]

    # Normalize: keep only tables that actually exist in the DB
    normalized = []
    for t in tables:
        key = (t or "").strip()
        if not key:
            continue
        actual = db_tables_lower.get(key.lower())
        if actual and actual not in normalized:
            normalized.append(actual)
    tables = normalized

    # ── STEP 3: Structural safety rules (no semantics, just DB constraints) ──
    # These are schema-structural facts, not signal-word heuristics:

    # T016T has only brsch+brtxt — joining it without KNA1 makes no sense
    if any(t.upper() == "T016T" for t in tables) and not any(t.upper() == "KNA1" for t in tables):
        tables = [t for t in tables if t.upper() != "T016T"]
        logger.info("Removed T016T: it needs KNA1 as parent but KNA1 was not selected")

    # Last-resort fallback: if LLM returned nothing, start with VBRP
    if not tables:
        for cand in ["VBRP", "vbrp", "VBRK"]:
            actual = db_tables_lower.get(cand.lower())
            if actual:
                tables = [actual]
                break
        if not tables and table_descriptions:
            tables = [list(table_descriptions.keys())[0]]

    logger.info("sap_sql_agent: final selected tables: %s", tables)
    return tables


def _generate_sql_json(
    question: str,
    selected_tables: List[str],
    column_mappings: Dict[str, Dict[str, str]],
    client: OpenAI,
    time_scope: str = "current",
    few_shot_examples: Optional[List[Dict[str, str]]] = None,
    table_descriptions: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """
    Equivalent of INVOICE_BOT.generate_sql_json, but simplified and Postgres-focused.

    Supports:
    - simple SELECTs
    - aggregates (SUM/AVG/COUNT/MIN/MAX) via the optional "agg" field on columns
    - GROUP BY via a dedicated "group_by" list
    """
    # Determine date filter based on time_scope
    date_filter_instruction = ""
    if time_scope == "historical":
        date_filter_instruction = """
⏳ **TIME SCOPE: HISTORICAL DATA (1994-2010)**
- MUST add date filters to ONLY include data from 1994-01-01 to 2010-12-31
- Example: {{"lhs": "VBRK.FKDAT", "operator": ">=", "rhs": "'1994-01-01'"}}, {{"lhs": "VBRK.FKDAT", "operator": "<=", "rhs": "'2010-12-31'"}}
"""
    elif time_scope == "current":
        date_filter_instruction = """
⏳ **TIME SCOPE: CURRENT PERIOD**
- Include recent data only (no strict date filter unless user specifies)
"""
    elif time_scope == "both":
        date_filter_instruction = """
⏳ **TIME SCOPE: ALL PERIODS**
- Include ALL data from 1994 to present for comparison
"""

    few_shot_block = ""
    if few_shot_examples:
        # Keep prompt lean: only a few short examples
        cleaned_examples = []
        for ex in few_shot_examples[:5]:
            uq = str(ex.get("user_query") or "")[:500]
            sql_ex = str(ex.get("sql_query") or "")[:1500]
            if uq and sql_ex:
                cleaned_examples.append({"user_query": uq, "sql_query": sql_ex})
        if cleaned_examples:
            few_shot_block = (
                "\nRecent successful question→SQL examples (use as patterns, do NOT copy literally):\n"
                f"{json.dumps(cleaned_examples, indent=2)}\n"
            )

    # Table descriptions: config/mapping-first, fallback to SAP_TABLE_DESCRIPTIONS
    tbl_desc = table_descriptions or {}
    tables_block = {tbl: tbl_desc.get(tbl) or tbl_desc.get(tbl.upper()) or SAP_TABLE_DESCRIPTIONS.get(tbl, "") for tbl in selected_tables}

    # Also expose ALL available table descriptions as a reference catalogue.
    # This lets the LLM add a table (e.g. MAKT for a LIKE filter, KNA1 for a name lookup)
    # even if it wasn't in the pre-selected set — without a second round-trip.
    all_tables_catalogue = ""
    if tbl_desc:
        extra = {k: v for k, v in tbl_desc.items() if k not in tables_block}
        if extra:
            all_tables_catalogue = (
                "\nOther available tables you MAY add if the query requires them "
                "(include them in the 'tables' list and add the necessary join):\n"
                + json.dumps(extra, indent=2)
                + "\n"
            )

    # Config-driven: column_semantic_hints + join_rules (extensible when adding new tables)
    cfg = _get_schema_config()
    col_hints = cfg.get("column_semantic_hints") or {}
    join_rules = cfg.get("join_rules") or []
    col_hints_block = ""
    if col_hints:
        col_hints_block = (
            "\nColumn semantics (use when choosing columns – from schema_ai_config.json):\n"
            + "\n".join(f"- {k}: {v}" for k, v in list(col_hints.items())[:60])  # increased: was 25
            + "\n"
        )
    join_rules_block = ""
    if join_rules:
        join_rules_block = "\nConfigured join rules (schema_ai_config.json – use these when joining):\n" + "\n".join(
            f"- {r.get('left')} + {r.get('right')}: {r.get('on', '')}" for r in join_rules[:30]  # increased: was 20
        ) + "\n"
    
    prompt = f"""
User question: "{question}"

{date_filter_instruction}

{few_shot_block}

Tables selected as primary (with full column details below):
{json.dumps(tables_block, indent=2)}
{all_tables_catalogue}
Column mappings (table -> column -> short description):
{json.dumps(column_mappings, indent=2)}
{col_hints_block}
Known join patterns between these tables:
{SAP_JOIN_HINTS}
{join_rules_block}

Task:
- Choose relevant columns from these tables.
- Propose joins between tables using ONLY the business keys listed above (do NOT invent other join columns).
- **IMPORTANT – Customer queries**: VBRP/vbrp does NOT have KUNNR/KUNAG. To get customer data:
  * PREFERRED (works even without full KNA1 data): use VBRK.KUNAG directly as customer identifier.
    Group by VBRK.KUNAG for "by customer" aggregations if KNA1 has incomplete data.
  * For customer NAME: join VBRK.KUNAG = KNA1.KUNNR and use KNA1.NAME1. Use LEFT JOIN (not INNER).
  * Never add IS NOT NULL filter on KNA1 — that converts LEFT JOIN to INNER JOIN and kills results.
- **IMPORTANT – Country queries**: VBRK has its own LAND1 column (country). Prefer VBRK.LAND1 directly
  instead of joining to KNA1.LAND1 — this avoids empty results when KNA1 data is incomplete.
- **T016T (industry)**: ONLY include T016T when the question explicitly asks for "industry" or "by industry".
  * T016T has ONLY columns brsch and brtxt (no VBELN, no KUNNR).
  * Join: KNA1.brsch = T016T.brsch (NOT on VBELN).
  * SELECT T016T.brtxt for industry name (not KNA1.brsch which is just a code).
  * Do NOT add T016T for questions about products, customers, or sales alone.
- **SIMILAR RULE**: For materials, use MAKT.MAKTX (description) not MATNR (code)
- **Margin/profitability**: margin = (revenue - cost) / revenue. Revenue from VBRP.NETWR. Cost from EKPO.NETWR or CKIS.wertn joined on material. For "average margin on low products" use AVG of margin per product, filter to low-margin products, group by product. If EKPO/CKIS not available, use revenue-only analysis and note that true margin needs cost data.
- **Cost of a specific product (e.g. a jacket)**: when the question is "cost of X" or "price of X":
  * PREFERRED: use KEKO + CKIS + MAKT for the STANDARD COST.
    - Filter: MAKT.MAKTX ILIKE '%jacket%'  (or whatever product)
    - Join: KEKO.MATNR = MAKT.MATNR, KEKO.KALNR = CKIS.KALNR
    - Select: MAKT.MAKTX, KEKO.matnr, SUM(CKIS.wertn) as standard_cost
    - Note: KEKO does NOT have stprs column; standard cost total is SUM(CKIS.WERTN).
    - Alternative for unit price: use CKMLCR.stprs joined via CKMLCR.kalnr = CKMLHD.kalnr, CKMLHD.matnr = MAKT.matnr
  * ALTERNATIVE (if KEKO not available or returns nothing): use EKPO + MAKT.
    - MAKT.MAKTX ILIKE '%jacket%', join EKPO.MATNR = MAKT.MATNR, SUM(EKPO.NETWR) / NULLIF(SUM(EKPO.MENGE), 0) as unit_cost.
  * LAST RESORT: use VBRP + MAKT to show the SALES PRICE as a proxy (note: this is selling price, not cost).
    - Group by MAKT.MAKTX, compute SUM(VBRP.NETWR) / NULLIF(SUM(VBRP.FKIMG), 0) as avg_sales_price.
- Add filters only if clearly needed from the question (for dates, customers, countries, industries, products, etc.).
- Return STRICT JSON with this structure:
{{
  "tables": [{{ "name": "VBRP", "description": "..." }}],
  "columns": [
    {{ "table": "T016T", "name": "brtxt", "description": "industry_name", "agg": null }},
    {{ "table": "VBRP", "name": "NETWR", "description": "total_sales", "agg": "SUM" }}
  ],
  "joins": [
    {{ "left": "VBRP", "right": "VBRK", "on": "VBRP.VBELN = VBRK.VBELN" }},
    {{ "left": "VBRK", "right": "KNA1", "on": "VBRK.KUNAG = KNA1.KUNNR" }},
    {{ "left": "KNA1", "right": "T016T", "on": "KNA1.brsch = T016T.brsch" }}
  ],
  "filters": [{{ "lhs": "VBRK.FKDAT", "operator": ">=", "rhs": "'2024-01-01'" }}],
  "group_by": [
    {{ "table": "T016T", "column": "brtxt" }}
  ],
  "having": [
    {{ "lhs": "total_sales", "operator": ">", "rhs": "0" }}
  ],
  "order_by": [
    "total_sales DESC"
  ],
  "limit": 200
}}

Rules:
- Use table and column names that actually exist in the column mappings.
- If a column entry has "agg": "SUM" | "AVG" | "COUNT" | "MIN" | "MAX",
  you are defining an aggregated metric over that column.
- CRITICAL: For "order_by", you MUST reference a column by its "description" field from the "columns" array.
  Example: If you have {{"table": "VBRP", "name": "NETWR", "description": "total_sales", "agg": "SUM"}},
  then order_by should be ["total_sales DESC"], NOT ["NETWR DESC"] or ["billing_item_net_value DESC"].
- For questions like:
    * "which industry has highest revenues"
    * "top customers by sales"
    * "highest sales by customer and product"
  you MUST:
    * pick an appropriate numeric metric column (e.g., VBRP.NETWR, BSAD.DMBTR, INVOICE_V2_BUSINESS_DATA.TOTAL_AMOUNT)
    * set "agg": "SUM" (or another relevant aggregate) on that metric column
    * give it a clear "description" like "total_sales" or "total_revenue"
    * add the dimension columns (industry, customer, product, country, etc.) to "group_by"
    * filter out NULL dimension values where it makes sense (e.g., industry IS NOT NULL)
    * order by the metric's description (e.g., "total_sales DESC") and use a small limit (e.g. 50 or 100).
- If the question is about "lowest", sort ASC instead of DESC.
- **CRITICAL for lowest/highest/top/bottom by dimension**: Exclude zero/empty aggregates.
  When grouping by customer, country, product, industry, etc. and showing SUM of sales/amounts,
  add "having": [{{ "lhs": "<metric_description>", "operator": ">", "rhs": "0" }}]
  so we only show entities that have actual activity. E.g. for "lowest sales by customer and country",
  add having on total_sales > 0 — otherwise we get customers with $0 (no sales), which is wrong.

- **MANDATORY: ALWAYS include currency** – whenever any monetary/amount column is selected
  (NETWR, WRBTR, DMBTR, HSL, WSL, KSL, KBETR, STPRS, WERTN, RMWWR, BRTWR, KBETR, etc.),
  you MUST also select the currency column. Rules by table (IMPORTANT – these are exact column names!):
  * VBRP or VBRK queries → add VBRK.WAERK (alias: "currency")   ← WAERK not WAERS for VBRK!
  * EKKO or EKPO queries → add EKKO.WAERS (alias: "currency")
  * RBKP or RSEG queries → add RBKP.WAERS (alias: "currency")
  * FAGLFLEXA queries → add FAGLFLEXA.RTCUR (alias: "currency") ← RTCUR not WAERS for FAGLFLEXA!
  * KEKO queries → add KEKO.HWAER (alias: "currency")            ← HWAER not WAERS for KEKO!
  * KONV queries → add KONV.WAERS (alias: "currency")
  * CKMLCR queries → add CKMLCR.WAERS (alias: "currency")
  Also add the currency column to group_by if group_by is non-empty.
  A number without a currency code is useless to the business user.

- **MANDATORY: ALWAYS include a date or period column** unless the question explicitly asks for
  a single grand-total number (e.g. "what is the total sales overall?"):
  * VBRK/VBRP queries → add VBRK.FKDAT (billing date, alias: "billing_date") to SELECT and group_by
  * RBKP queries → add RBKP.BUDAT (posting date, alias: "posting_date") to SELECT and group_by
  * EKKO queries → add EKKO.BEDAT (PO date, alias: "po_date") to SELECT and group_by
  * FAGLFLEXA queries → add FAGLFLEXA.POPER (posting period 01-12, alias: "period") AND
    FAGLFLEXA.RYEAR (fiscal year, alias: "fiscal_year") to SELECT and group_by
  This allows the user to see WHICH period the data belongs to.

- **MANDATORY: ALWAYS show MATERIAL NAME alongside material number** – raw codes are not useful:
  * Whenever MATNR appears in any table (VBRP, EKPO, KEKO, CKIS, VBAP, MARC, etc.),
    you MUST join MAKT and SELECT MAKT.MAKTX (description) with alias "material_name".
  * Add MAKT to tables list, join: <source_table>.MATNR = MAKT.MATNR
  * Add MAKT.MAKTX to group_by if group_by is non-empty.
  * If MAKT is already in the query, just make sure MAKTX is in the columns list.
  * Exception: if the question explicitly says "show material number" or "list MATNR codes".

- **TEXT SEARCH / FILTER by name or word**: When the question asks to filter by a word or name
  (e.g. "containing 'jacket'", "with word 'pump'", "products that include 'motor'",
  "customers named 'Smith'", "vendors containing 'GmbH'"), you MUST add an ILIKE filter:
  * For product/material names: filter on MAKT.MAKTX ILIKE '%<word>%'
    (always join MAKT if not already included)
  * For customer names: filter on KNA1.NAME1 ILIKE '%<word>%'
  * For vendor names: filter on LFA1.NAME1 ILIKE '%<word>%'
  * Do NOT skip this filter — returning all rows instead of the matching subset is wrong.
  * Example for "list all products containing 'jacket'":
    tables: [VBRP, VBRK, MAKT], join VBRP.MATNR = MAKT.MATNR,
    filter: MAKT.MAKTX ILIKE '%jacket%', SELECT MAKT.MAKTX, SUM(VBRP.FKIMG), SUM(VBRP.NETWR)

- **MANDATORY: NEVER add date column to GROUP BY on aggregated queries** (queries with SUM/AVG):
  For aggregated queries like "top N customers by total revenue", "sales by country", etc.,
  NEVER put FKDAT, BUDAT, or any date in group_by — that would fragment the total into
  per-day rows and give wrong results (e.g. revenue per customer per day instead of total).
  Instead, for aggregated queries, add date as MIN/MAX aggregates for time-range context:
  * {{"table": "VBRK", "name": "FKDAT", "description": "earliest_billing_date", "agg": "MIN"}}
  * {{"table": "VBRK", "name": "FKDAT", "description": "latest_billing_date", "agg": "MAX"}}
  Only add raw date to group_by for detail (non-aggregated) row-level queries.
"""
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
    )
    content = resp.choices[0].message.content or ""
    try:
        spec = json.loads(content)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", content, re.DOTALL)
        spec = json.loads(m.group(0)) if m else {}
    return spec or {}


def _ensure_having_for_aggregates(spec: Dict[str, Any], question: str) -> None:
    """
    When question asks for lowest/highest/top/bottom by dimension with aggregates,
    auto-inject HAVING metric > 0 so we exclude entities with $0 (wrong for rankings).
    Modifies spec in place.
    """
    q_lower = (question or "").lower()
    if not any(kw in q_lower for kw in ("lowest", "highest", "top", "bottom", "minimum", "maximum", "best", "worst")):
        return
    if spec.get("having"):
        return
    group_bys = spec.get("group_by") or []
    if not group_bys:
        return
    columns = spec.get("columns") or []
    sum_col = None
    for col in columns:
        if str(col.get("agg") or "").upper() in ("SUM", "AVG"):
            sum_col = col
            break
    if not sum_col:
        return
    human = sum_col.get("description") or f"{sum_col.get('table', '')}_{sum_col.get('name', '')}"
    human_safe = re.sub(r"[^\w]", "_", str(human))[:60] or "total"
    spec["having"] = [{"lhs": human_safe, "operator": ">", "rhs": "0"}]
    logger.info("Auto-injected HAVING %s > 0 for ranking query", human_safe)


def _auto_enrich_spec(spec: Dict[str, Any], question: str) -> None:
    """
    Post-process LLM-generated SQL spec to enforce three mandatory context columns:
      1. Currency (WAERS) whenever monetary amounts are present
      2. Date/period column so user knows WHEN the data is from
      3. MAKT.MAKTX alongside any MATNR column (human-readable material name)

    IMPORTANT date rule: date/period is added to SELECT for context, but NEVER to GROUP BY
    on aggregated queries (queries with SUM/AVG columns). Adding a date to GROUP BY on an
    aggregated query changes "top 20 customers by total revenue" into
    "revenue per customer per day" — completely wrong semantics.
    Instead, for aggregated queries we add MIN/MAX of the date so the user can see
    the time range covered without fragmenting the aggregation.

    Modifies spec in-place.  This is a safety net — the LLM prompt already asks for these,
    but we enforce them here in case the model skips one.
    """
    if not spec:
        return

    q_lower = (question or "").lower()

    # Resolve sets of tables and column names currently in the spec
    tables_in_spec = {(t.get("name") or "").upper() for t in spec.get("tables", [])}
    col_names_upper = {(c.get("name") or "").upper() for c in spec.get("columns", [])}

    # Build a map from UPPERCASE table name → actual name as used in spec (preserving LLM case)
    # This is used when adding enrichment columns so the table name in the added column matches
    # exactly what the LLM put in spec["tables"], avoiding validate_sql_spec case mismatches.
    _spec_table_actual_name: Dict[str, str] = {
        (t.get("name") or "").upper(): (t.get("name") or "")
        for t in spec.get("tables", []) if t.get("name")
    }
    def _spec_tbl(uppercase_key: str) -> str:
        """Return the table name as it appears in spec (preserving LLM case) or fallback to uppercase_key."""
        return _spec_table_actual_name.get(uppercase_key, uppercase_key)

    # Use schema_ai_config.json numeric_columns — no hardcoded list needed.
    # Adding a new numeric column to the config automatically flows through here.
    _cfg = _get_schema_config()
    AMOUNT_COLS = {c.upper() for c in (_cfg.get("numeric_columns") or [])}
    # Fallback in case config is empty (should not happen after our edits)
    if not AMOUNT_COLS:
        AMOUNT_COLS = {"NETWR", "WRBTR", "DMBTR", "HSL", "WSL", "KSL", "KBETR", "STPRS"}
    CURRENCY_COLS = {"WAERS", "WAERK", "RCUR", "RTCUR", "RWCUR", "HWAER", "FWAER_KPF"}
    DATE_PERIOD_COLS = {"FKDAT", "BUDAT", "BEDAT", "POPER", "GJAHR", "RYEAR", "BLDAT", "AUGDT"}

    has_amounts = bool(col_names_upper & AMOUNT_COLS)
    has_currency = bool(col_names_upper & CURRENCY_COLS)
    has_date_period = bool(col_names_upper & DATE_PERIOD_COLS)
    has_matnr = "MATNR" in col_names_upper
    has_maktx = "MAKTX" in col_names_upper
    has_group_by = bool(spec.get("group_by"))

    # Is there any aggregate column (SUM/AVG/COUNT/MIN/MAX)?  Critical for date rule.
    has_aggregate = any(
        str(c.get("agg") or "").upper() in {"SUM", "AVG", "COUNT", "MIN", "MAX"}
        for c in spec.get("columns", [])
    )

    # Is this a pure single-number grand-total query? Skip date enrichment for those.
    is_grand_total = any(
        phrase in q_lower for phrase in
        ("grand total", "overall total", "total overall", "all time total", "in total",
         "total amount", "how much total", "sum total")
    ) and not has_group_by

    # ─── 1. Currency enrichment ───────────────────────────────────────────────
    if has_amounts and not has_currency:
        CURRENCY_SOURCE = [
            # trigger_tbl, src_tbl, src_col (actual DB column name!), alias
            ("VBRK",       "VBRK",       "WAERK",  "currency"),   # VBRK uses WAERK not WAERS
            ("EKKO",       "EKKO",       "WAERS",  "currency"),
            ("RBKP",       "RBKP",       "WAERS",  "currency"),
            ("FAGLFLEXA",  "FAGLFLEXA",  "RTCUR",  "currency"),   # FAGLFLEXA uses RTCUR not WAERS
            ("KEKO",       "KEKO",       "HWAER",  "currency"),   # KEKO uses HWAER not WAERS
            ("VBRP",       "VBRK",       "WAERK",  "currency"),   # VBRP pulls currency from VBRK.WAERK
            ("RSEG",       "RBKP",       "WAERS",  "currency"),
            ("EKPO",       "EKKO",       "WAERS",  "currency"),
            ("KONV",       "KONV",       "WAERS",  "currency"),   # KONV has WAERS
            ("CKMLCR",     "CKMLCR",     "WAERS",  "currency"),   # CKMLCR has WAERS
        ]
        for trigger_tbl, src_tbl, src_col, alias in CURRENCY_SOURCE:
            if trigger_tbl in tables_in_spec and src_tbl in tables_in_spec:
                # Use the exact table name casing from spec (not hardcoded uppercase)
                # to avoid validate_sql_spec false-positive case-mismatch errors.
                actual_src_tbl = _spec_tbl(src_tbl)
                spec.setdefault("columns", []).append(
                    {"table": actual_src_tbl, "name": src_col, "description": alias, "agg": None}
                )
                # Currency is safe to GROUP BY — same value for all rows in a billing doc
                if has_group_by:
                    spec.setdefault("group_by", []).append({"table": actual_src_tbl, "column": src_col})
                logger.info("Auto-enriched spec: added %s.%s (currency)", actual_src_tbl, src_col)
                break

    # ─── 2. Date / period enrichment ─────────────────────────────────────────
    # RULE: For aggregated queries (has SUM/AVG), add MIN/MAX of the date as range markers
    # — never add a raw date to GROUP BY, which would fragment the aggregation.
    # For non-aggregated (detail) queries, add date normally (and to GROUP BY if needed).
    if not has_date_period and not is_grand_total:
        DATE_SOURCE = [
            ("VBRK",      "VBRK",      "FKDAT",  "billing_date"),
            ("RBKP",      "RBKP",      "BUDAT",  "posting_date"),
            ("EKKO",      "EKKO",      "BEDAT",  "po_date"),
            ("FAGLFLEXA", "FAGLFLEXA", "POPER",  "period"),
        ]
        for trigger_tbl, src_tbl, src_col, alias in DATE_SOURCE:
            if trigger_tbl in tables_in_spec and src_tbl in tables_in_spec:
                # Use the exact table name casing from spec
                actual_src_tbl = _spec_tbl(src_tbl)
                if has_aggregate:
                    # Aggregated query: add MIN/MAX as range markers (no GROUP BY change)
                    spec.setdefault("columns", []).append(
                        {"table": actual_src_tbl, "name": src_col,
                         "description": f"earliest_{alias}", "agg": "MIN"}
                    )
                    spec.setdefault("columns", []).append(
                        {"table": actual_src_tbl, "name": src_col,
                         "description": f"latest_{alias}", "agg": "MAX"}
                    )
                    logger.info(
                        "Auto-enriched spec: added MIN/MAX(%s.%s) date range for aggregated query",
                        actual_src_tbl, src_col
                    )
                else:
                    # Detail (non-aggregated) query: add date as plain column
                    spec.setdefault("columns", []).append(
                        {"table": actual_src_tbl, "name": src_col, "description": alias, "agg": None}
                    )
                    if has_group_by:
                        spec.setdefault("group_by", []).append({"table": actual_src_tbl, "column": src_col})
                    # FAGLFLEXA: also add RYEAR
                    if src_col == "POPER":
                        actual_faglflexa = _spec_tbl("FAGLFLEXA")
                        spec["columns"].append(
                            {"table": actual_faglflexa, "name": "RYEAR",
                             "description": "fiscal_year", "agg": None}
                        )
                        if has_group_by:
                            spec["group_by"].append({"table": actual_faglflexa, "column": "RYEAR"})
                    logger.info(
                        "Auto-enriched spec: added %s.%s (date/period, non-aggregated)",
                        actual_src_tbl, src_col
                    )
                break

    # ─── 3. Material name (MAKTX) enrichment ────────────────────────────────
    if has_matnr and not has_maktx:
        matnr_source_tables = [
            (c.get("table") or "").upper()
            for c in spec.get("columns", [])
            if (c.get("name") or "").upper() == "MATNR"
        ]
        source_tbl = matnr_source_tables[0] if matnr_source_tables else None

        if "MAKT" not in tables_in_spec and source_tbl:
            spec.setdefault("tables", []).append(
                {"name": "MAKT", "description": "Material descriptions (MAKTX)"}
            )
            spec.setdefault("joins", []).append({
                "left": source_tbl,
                "right": "MAKT",
                "on": f"{source_tbl}.MATNR = MAKT.MATNR"
            })

        spec.setdefault("columns", []).append(
            {"table": "MAKT", "name": "MAKTX", "description": "material_name", "agg": None}
        )
        if has_group_by:
            spec.setdefault("group_by", []).append({"table": "MAKT", "column": "MAKTX"})
        logger.info("Auto-enriched spec: added MAKT.MAKTX (material name) for table %s", source_tbl)


def _json_to_sql_postgres(json_spec: Dict[str, Any], column_mappings: Dict[str, Dict[str, str]]) -> str:
    """
    Convert JSON spec into a Postgres SQL query.

    We mirror the INVOICE_BOT approach:
    - Build SELECT list for chosen columns.
    - Start from a base table, then add JOINs from the spec.
    - If some tables are missing join conditions, join them via common keys if possible (e.g., VBELN, KUNNR, MATNR).
    """
    columns = json_spec.get("columns", []) or []
    joins = json_spec.get("joins", []) or []
    tables_info = json_spec.get("tables", []) or []
    limit = int(json_spec.get("limit", 100) or 100)

    all_tables: List[str] = []
    for j in joins:
        all_tables.append(j.get("left"))
        all_tables.append(j.get("right"))
    for c in columns:
        all_tables.append(c.get("table"))
    for t in tables_info:
        all_tables.append(t.get("name"))
    all_tables = [t for t in {t for t in all_tables if t}]  # unique, remove None

    if not all_tables:
        raise ValueError("sap_sql_agent: JSON spec contains no tables")

    # Map spec table names to actual DB table names (case differences already handled by column_mappings keys)
    table_aliases: Dict[str, str] = {}
    used_aliases: set[str] = set()

    def _fmt_alias(tbl: str) -> str:
        base = tbl[0].lower()
        alias = base
        i = 1
        while alias in used_aliases:
            alias = f"{base}{i}"
            i += 1
        used_aliases.add(alias)
        return alias

    # The mapping keys in column_mappings are the actual DB table names.
    # Build a map from logical name (any case) -> actual DB table name.
    #
    # IMPORTANT: We build from ALL tables in column_mappings (not just SAP_TABLE_DESCRIPTIONS)
    # so that any table in the DB (e.g. KONV, VBFA, AUFK, CKIS) is resolvable even if it
    # wasn't hardcoded in SAP_TABLE_DESCRIPTIONS.
    logical_to_actual: Dict[str, str] = {}

    # First pass: explicit SAP_TABLE_DESCRIPTIONS keys (backward compat, prefer these for aliases)
    for logical in SAP_TABLE_DESCRIPTIONS.keys():
        for actual in column_mappings.keys():
            if actual.lower() == logical.lower():
                logical_to_actual[logical] = actual
                logical_to_actual[logical.lower()] = actual
                logical_to_actual[logical.upper()] = actual

    # Second pass: every table that exists in column_mappings but wasn't mapped above.
    # This handles tables like KONV, VBFA, CEPC, COEP, CKIS etc. that are in the DB but
    # not in the hardcoded SAP_TABLE_DESCRIPTIONS dict.
    for actual in column_mappings.keys():
        if actual not in logical_to_actual:
            logical_to_actual[actual] = actual
        if actual.lower() not in logical_to_actual:
            logical_to_actual[actual.lower()] = actual
        if actual.upper() not in logical_to_actual:
            logical_to_actual[actual.upper()] = actual

    def _actual_table_name(logical: str) -> str:
        key = logical
        if key not in logical_to_actual:
            key = logical.lower()
        if key not in logical_to_actual:
            key = logical.upper()
        return logical_to_actual.get(key, logical)

    # Build a case-insensitive column name map per table so we can always
    # use the real DB column identifiers even if the JSON spec uses upper-case.
    column_name_map: Dict[str, Dict[str, str]] = {}
    for actual_tbl, cols in column_mappings.items():
        column_name_map[actual_tbl] = {c_name.lower(): c_name for c_name in cols.keys()}

    def _actual_column_name(actual_tbl: str, logical_col: str) -> str:
        if not logical_col:
            return logical_col
        table_cols = column_name_map.get(actual_tbl, {})
        return table_cols.get(str(logical_col).lower(), logical_col)

    for tbl in all_tables:
        actual = _actual_table_name(tbl)
        table_aliases[actual] = _fmt_alias(actual)

    # SELECT (also build alias -> aggregate expression for HAVING; PostgreSQL does not allow SELECT aliases in HAVING)
    select_parts: List[str] = []
    used_col_aliases: set[str] = set()
    alias_to_agg_expr: Dict[str, str] = {}

    for col in columns:
        logical_tbl = col.get("table")
        col_name_raw = col.get("name")
        if not logical_tbl or not col_name_raw:
            continue
        actual_tbl = _actual_table_name(logical_tbl)
        if actual_tbl not in table_aliases:
            continue
        alias = table_aliases[actual_tbl]
        col_name = _actual_column_name(actual_tbl, col_name_raw)
        agg = str(col.get("agg") or "").upper()

        # Config-driven casting: schema_ai_config.json defines numeric_columns and trim_numeric_tables.
        # Add new tables/columns there when schema changes; no code changes needed.
        cfg = _get_schema_config()
        numeric_cols = {c.upper() for c in (cfg.get("numeric_columns") or [])}
        trim_tables = {t.upper() for t in (cfg.get("trim_numeric_tables") or [])}
        actual_upper = actual_tbl.upper()
        col_upper = str(col_name).upper()
        needs_numeric_cast = col_upper in numeric_cols
        use_trim_pattern = actual_upper in trim_tables and needs_numeric_cast

        if agg in {"SUM", "AVG", "COUNT", "MIN", "MAX"}:
            if needs_numeric_cast and agg != "COUNT":
                if use_trim_pattern:
                    expr = f"{agg}(NULLIF(TRIM({alias}.\"{col_name}\"::text), '')::numeric)"
                else:
                    expr = f"{agg}(NULLIF({alias}.\"{col_name}\",'')::numeric)"
            else:
                expr = f"{agg}({alias}.\"{col_name}\")"
        else:
            expr = f'{alias}."{col_name}"'
        human = col.get("description") or f"{actual_tbl}_{col_name}"
        human_safe = re.sub(r"[^\w]", "_", human)[:60] or f"{alias}_{col_name}"
        if human_safe in used_col_aliases:
            suffix = 1
            while f"{human_safe}_{suffix}" in used_col_aliases:
                suffix += 1
            human_safe = f"{human_safe}_{suffix}"
        used_col_aliases.add(human_safe)
        if agg in {"SUM", "AVG", "COUNT", "MIN", "MAX"}:
            alias_to_agg_expr[human_safe] = expr
        select_parts.append(f'    {expr} AS "{human_safe}"')

    if not select_parts:
        # Fallback: SELECT * from first table
        base_logical = all_tables[0]
        base_actual = _actual_table_name(base_logical)
        alias = table_aliases[base_actual]
        select_parts.append(f"    {alias}.*")

    sql_lines: List[str] = [f"SELECT {', '.join(select_parts)}",]

    # Base table: first in joins, else first in tables_info, else first in list
    base_logical = (
        (joins[0].get("left") if joins else None)
        or (tables_info[0].get("name") if tables_info else None)
        or all_tables[0]
    )
    base_actual = _actual_table_name(base_logical)
    base_alias = table_aliases[base_actual]
    sql_lines.append(f'FROM "{base_actual}" AS {base_alias}')

    added_actuals = {base_actual}

    # Helper to rewrite "VBRP.VBELN" → "v.\"vbeln\"" using aliases and actual DB column names.
    # Postgres identifiers are case-sensitive when quoted; DB usually has lowercase columns.
    def _rewrite_expr(expr: str) -> str:
        out = expr
        # Replace Table.Column with alias."actual_column" (uses real DB column casing)
        def _repl(m: re.Match) -> str:
            tbl_part = m.group(1)
            col_part = m.group(2)
            actual_tbl = _actual_table_name(tbl_part)
            alias = table_aliases.get(actual_tbl)
            if not alias:
                return m.group(0)
            actual_col = _actual_column_name(actual_tbl, col_part)
            return f'{alias}."{actual_col}"'
        out = re.sub(r'\b(\w+)\.(\w+)\b', _repl, out)
        return out

    # Add joins from spec
    for j in joins:
        left_logical = j.get("left")
        right_logical = j.get("right")
        on_expr = j.get("on") or ""
        if not right_logical:
            continue
        right_actual = _actual_table_name(right_logical)
        if right_actual in added_actuals:
            continue
        right_alias = table_aliases[right_actual]
        sql_lines.append(f'\nLEFT JOIN "{right_actual}" AS {right_alias}')
        if on_expr:
            sql_lines.append(f"    ON {_rewrite_expr(on_expr)}")
        added_actuals.add(right_actual)

    # Add any missing tables with heuristic joins on common keys (skip if no common key; else invalid SQL)
    COMMON_KEYS = ["VBELN", "KUNNR", "KUNAG", "MATNR", "EBELN", "LIFNR", "BELNR", "BRSCH"]
    for logical_tbl in all_tables:
        actual_tbl = _actual_table_name(logical_tbl)
        if actual_tbl in added_actuals:
            continue
        alias = table_aliases[actual_tbl]
        # Try to join on a shared key with an already-added table
        join_cond = None
        for key in COMMON_KEYS:
            other_col = _actual_column_name(actual_tbl, key)
            if not other_col:
                continue
            for added in added_actuals:
                base_col = _actual_column_name(added, key)
                if base_col:
                    add_alias = table_aliases.get(added)
                    if add_alias:
                        join_cond = f'{add_alias}."{base_col}" = {alias}."{other_col}"'
                        break
            if join_cond:
                break
        if join_cond:
            sql_lines.append(f'\nLEFT JOIN "{actual_tbl}" AS {alias}')
            sql_lines.append(f"    ON {join_cond}")
            added_actuals.add(actual_tbl)

    # WHERE (must come BEFORE GROUP BY)
    conds: List[str] = []
    for f in json_spec.get("filters", []) or []:
        lhs = _rewrite_expr(str(f.get("lhs", "")))
        op = str(f.get("operator", "")).strip().upper()
        rhs_raw = f.get("rhs")
        
        if not lhs or not op:
            continue
        
        # Handle NULL operators (don't need RHS)
        if op in {"IS NULL", "IS NOT NULL"}:
            conds.append(f"{lhs} {op}")
        else:
            # Need RHS for all other operators
            rhs = str(rhs_raw).strip() if rhs_raw is not None else ""
            if rhs and rhs.lower() != "none":
                conds.append(f"{lhs} {op} {rhs}")

    # NOTE: Do NOT auto-add IS NOT NULL conditions here.
    # The auto-IS-NOT-NULL for KNA1 was converting LEFT JOINs to INNER JOINs,
    # causing 0 rows whenever KNA1 data is incomplete (e.g. partial test datasets).
    # The LLM prompt instructs explicit NULL filtering when needed for a specific query.

    if conds:
        sql_lines.append("\nWHERE " + " AND ".join(conds))

    # GROUP BY (must come AFTER WHERE)
    group_bys = json_spec.get("group_by", []) or []
    gb_parts: List[str] = []
    for gb in group_bys:
        if not isinstance(gb, dict):
            continue
        t_logical = gb.get("table")
        col_raw = gb.get("column")
        if not t_logical or not col_raw:
            continue
        t_actual = _actual_table_name(t_logical)
        alias = table_aliases.get(t_actual)
        if not alias:
            continue
        col = _actual_column_name(t_actual, col_raw)
        gb_parts.append(f'{alias}."{col}"')
    if gb_parts:
        sql_lines.append("\nGROUP BY " + ", ".join(gb_parts))

    # HAVING (after GROUP BY, before ORDER BY)
    # PostgreSQL does NOT allow SELECT aliases in HAVING; use the full aggregate expression instead.
    having_parts: List[str] = []
    for h in json_spec.get("having", []) or []:
        if not isinstance(h, dict):
            continue
        lhs = str(h.get("lhs", "")).strip()
        op = str(h.get("operator", "")).strip().upper()
        rhs_raw = h.get("rhs")
        if not lhs or not op:
            continue
        # Match alias by name (case-insensitive)
        lhs_lower = lhs.lower()
        matched = lhs if lhs in used_col_aliases else None
        if not matched:
            for a in used_col_aliases:
                if a.lower() == lhs_lower or lhs_lower in a.lower():
                    matched = a
                    break
        # Use aggregate expression if available; otherwise fall back to alias (may fail in PG)
        lhs_expr = alias_to_agg_expr.get(matched) if matched else None
        if not lhs_expr and matched:
            lhs_expr = f'"{matched}"'
        elif not lhs_expr:
            lhs_expr = lhs
        # Ensure any raw table.column inside HAVING is rewritten to the correct alias/column
        lhs_expr = _rewrite_expr(lhs_expr)
        if op in {"IS NULL", "IS NOT NULL"}:
            having_parts.append(f"{lhs_expr} {op}")
        else:
            rhs = str(rhs_raw).strip() if rhs_raw is not None else ""
            if rhs and rhs.lower() != "none":
                having_parts.append(f"{lhs_expr} {op} {rhs}")
    if having_parts:
        sql_lines.append("\nHAVING " + " AND ".join(having_parts))

    # ORDER BY
    order_by_parts: List[str] = []
    for ob in json_spec.get("order_by", []) or []:
        if isinstance(ob, str):
            # Check if it's a SELECT alias first
            ob_clean = ob.strip().split()[0]  # Remove DESC/ASC
            if ob_clean in used_col_aliases:
                order_by_parts.append(ob)
            else:
                order_by_parts.append(_rewrite_expr(ob))
        else:
            t_logical = ob.get("table")
            col_raw = ob.get("column")
            direction = ob.get("direction", "DESC").upper()
            
            # Try to match against SELECT aliases first (case-insensitive)
            col_lower = str(col_raw).lower().strip() if col_raw else ""
            matched_alias = None
            for used_alias in used_col_aliases:
                if col_lower in used_alias.lower() or used_alias.lower() in col_lower:
                    matched_alias = used_alias
                    break
            
            if matched_alias:
                # Use the SELECT alias directly
                order_by_parts.append(f'"{matched_alias}" {direction}')
            elif t_logical and col_raw:
                # Fall back to table.column format
                t_actual = _actual_table_name(t_logical)
                alias = table_aliases.get(t_actual)
                if alias and t_actual:
                    col = _actual_column_name(t_actual, col_raw)
                    order_by_parts.append(f'{alias}."{col}" {direction}')
    
    if order_by_parts:
        sql_lines.append("\nORDER BY " + ", ".join(order_by_parts))

    sql_lines.append(f"\nLIMIT {limit}")
    return "\n".join(sql_lines) + ";"


def _run_sql(db: Session, sql: str) -> List[Dict[str, Any]]:
    """Execute SQL and return rows. Raises exception on failure so the retry loop
    receives the REAL Postgres error (e.g. 'column X does not exist') instead of
    a misleading 'no rows' message that causes the LLM to generate a wrong refinement."""
    if not sql or not sql.strip():
        return []
    # Intentionally NOT catching exceptions here.  Callers (run_sap_sql_agent) have a
    # try/except that captures the real error message and passes it to refine_query_on_error.
    result = db.execute(text(sql))
    rows = result.fetchall()
    keys = result.keys()
    out: List[Dict[str, Any]] = []
    for row in rows:
        row_dict = {k: _serialize_value(v) for k, v in zip(keys, row)}
        out.append(row_dict)
    return out


def _summarize_results(question: str, sql: str, rows: List[Dict[str, Any]], client: OpenAI) -> str:
    """
    Ask the LLM to summarize the tabular result in natural language.
    """
    if not rows:
        return ""

    # Truncate to keep prompt reasonable
    sample_rows = rows[:100]
    data_json = json.dumps(sample_rows, default=_serialize_value)

    prompt = f"""
You are an expert SAP sales and finance analyst.

The user asked:
\"\"\"{question}\"\"\"

You executed the following SQL on a Postgres database that contains SAP-style tables:
```sql
{sql}
```

Here is a sample of the result rows as JSON:
{data_json}

Task:
- Explain the answer using ONLY the exact numbers and values from the JSON above.
- Do NOT invent, approximate, or reuse numbers from memory or prior context.
- Include specific numbers (totals, top items, customers, countries, industries) from the data.
- **Always state the currency** of any monetary amounts (e.g. "USD", "EUR"). If a "currency",
  "WAERS", or "WAERK" column is present in the data, use it. If not, note the currency is unknown.
- **Always state the time period** the data covers. If "billing_date", "FKDAT", "posting_date",
  "BUDAT", "period", "POPER", "fiscal_year", or "RYEAR" columns are present, mention the date range
  or period. If no date column is present, note the time scope (e.g. "all available periods").
- For material numbers (MATNR), always use the material name (MAKTX) instead of the raw code
  if a "material_name" or "MAKTX" column is present in the data.
- Be concise (3–8 sentences).
- If the JSON is empty, say clearly that no data was returned for this query.
"""
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.4,
        max_tokens=600,
    )
    return (resp.choices[0].message.content or "").strip()


def validate_sql_spec(spec: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """
    Validate SQL specification before execution.
    
    Args:
        spec: JSON SQL specification
    
    Returns:
        Tuple of (is_valid, list_of_errors)
    """
    errors = []
    
    # Check basic structure
    if not spec:
        errors.append("Empty specification")
        return False, errors
    
    tables = spec.get("tables", [])
    columns = spec.get("columns", [])
    
    if not tables:
        errors.append("No tables specified")
    
    if not columns:
        errors.append("No columns specified")
    
    # Validate columns reference existing tables (case-insensitive: LLM may mix VBRK/vbrk)
    table_names = {t.get("name") for t in tables if isinstance(t, dict) and t.get("name")}
    table_names_lower = {(n or "").lower() for n in table_names}
    for col in columns:
        if isinstance(col, dict):
            col_table = col.get("table")
            if col_table and (col_table not in table_names) and (col_table.lower() not in table_names_lower):
                errors.append(f"Column references unknown table: {col_table}")

    # Validate joins reference existing tables (case-insensitive)
    joins = spec.get("joins", [])
    for j in joins:
        if isinstance(j, dict):
            left = j.get("left")
            right = j.get("right")
            if left and (left not in table_names) and (left.lower() not in table_names_lower):
                errors.append(f"Join references unknown left table: {left}")
            if right and (right not in table_names) and (right.lower() not in table_names_lower):
                errors.append(f"Join references unknown right table: {right}")
    
    is_valid = len(errors) == 0
    return is_valid, errors


def refine_query_on_error(
    client: OpenAI,
    original_question: str,
    sql_error: str,
    previous_spec: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Use LLM to refine the query specification after an SQL error.
    
    Args:
        client: OpenAI client
        original_question: User's original question
        sql_error: Error message from SQL execution
        previous_spec: Previous JSON SQL specification that failed
    
    Returns:
        Refined JSON SQL specification
    """
    try:
        prompt = f"""
An SQL query failed with an error. Please fix the JSON SQL specification.

Original question: "{original_question}"

Previous specification that failed:
{json.dumps(previous_spec, indent=2)}

Error message:
{sql_error}

Common issues:
- Missing join conditions
- Invalid column names (use exact DB column names; Postgres columns are usually lowercase)
- Incorrect table references
- Missing GROUP BY for aggregated columns
- T016T has only brsch/brtxt columns — NEVER join T016T on VBELN; only join KNA1.brsch = T016T.brsch when question asks about industry
- Do NOT include T016T unless the question asks about industry
- Query returned no rows: remove date filters, use all periods, simplify to fewer joins
- Results include $0 / zero aggregates: add "having": [{{ "lhs": "<metric_alias>", "operator": ">", "rhs": "0" }}]

Return a CORRECTED JSON specification with the same structure.
"""
        
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=1000,
        )
        
        content = (response.choices[0].message.content or "").strip()
        try:
            refined_spec = json.loads(content)
        except json.JSONDecodeError:
            m = re.search(r"\{.*\}", content, re.DOTALL)
            refined_spec = json.loads(m.group(0)) if m else previous_spec
        
        return refined_spec or previous_spec
    
    except Exception as e:
        logger.error(f"Query refinement failed: {e}")
        return previous_spec


def run_sap_sql_agent(
    question: str,
    db: Session,
    knowledge_context: Optional[str] = None,
    max_retries: int = 2,
    time_scope: str = "current",
    few_shot_examples: Optional[List[Dict[str, str]]] = None,
) -> SqlAgentResult | None:
    """
    Main entry point used by the dashboard AI endpoint.

    It:
    - Uses LLM to pick tables (dynamically from DB + mapping; supports new tables)
    - Introspects columns from Postgres
    - Uses LLM to build a JSON SQL spec
    - Translates to Postgres SQL and executes
    - Caches SQL per question

    Args:
        knowledge_context: Optional user preferences (e.g. "For cost queries use EKPO, RBKP, RSEG").
        time_scope: 'current' (recent data), 'historical' (1994-2010), or 'both' (all periods)
    """
    client = _get_openai_client()
    if not client:
        return None

    attempt = 0
    last_error = None
    spec = None
    
    try:
        selected_tables = _pick_tables(question, client, db, knowledge_context)
        logger.info("sap_sql_agent: question='%s' | selected_tables=%s", question, selected_tables)

        column_mappings = _introspect_columns(db, selected_tables)
        if not column_mappings:
            logger.warning("sap_sql_agent: no column mappings found for selected tables %s", selected_tables)
            return None

        logger.info(
            "sap_sql_agent: usable_tables_after_introspection=%s",
            list(column_mappings.keys()),
        )

        table_descriptions = _get_table_descriptions(db)
        spec = _generate_sql_json(
            question,
            selected_tables,
            column_mappings,
            client,
            time_scope=time_scope,
            few_shot_examples=few_shot_examples,
            table_descriptions=table_descriptions,
        )
        if not spec:
            logger.warning("sap_sql_agent: empty JSON spec for question %s", question)
            return None

        _ensure_having_for_aggregates(spec, question)
        _auto_enrich_spec(spec, question)  # enforce: currency, date/period, material name

        # Validate specification
        is_valid, validation_errors = validate_sql_spec(spec)
        if not is_valid:
            logger.warning(f"Invalid SQL spec: {validation_errors}")
            # Try to auto-fix common issues
            if validation_errors and len(validation_errors) < 5:
                logger.info("Attempting to refine specification...")
                spec = refine_query_on_error(client, question, ", ".join(validation_errors), spec)
                is_valid, validation_errors = validate_sql_spec(spec)
        
        # Retry loop for SQL execution
        rows: List[Dict[str, Any]] = []
        sql = ""
        while attempt <= max_retries:
            try:
                sql = _json_to_sql_postgres(spec, column_mappings)
                logger.info(f"📝 Generated SQL:\n{sql}")
                rows = _run_sql(db, sql)

                if rows:
                    logger.info(f"✅ SQL returned {len(rows)} rows")
                    return SqlAgentResult(sql=sql, rows=rows)

                # Query returned no rows — retry with simpler query
                logger.warning(f"⚠️ SQL returned no rows for question: {question}")
                logger.warning(f"📊 SQL query:\n{sql}")
                if attempt < max_retries:
                    try:
                        db.rollback()
                    except Exception:
                        pass
                    logger.warning("Query returned 0 rows — refining SQL...")
                    spec = refine_query_on_error(
                        client,
                        question,
                        "Query returned no rows. The database may have historical data (1994-2010) but little recent data. "
                        "Remove date filters, use ALL periods, simplify joins to only essential tables.",
                        spec,
                    )
                    attempt += 1
                    continue
                break

            except Exception as sql_err:
                last_error = str(sql_err)
                logger.warning(f"SQL execution failed (attempt {attempt + 1}/{max_retries + 1}): {last_error}")
                
                if attempt < max_retries:
                    try:
                        db.rollback()
                    except Exception:
                        pass
                    logger.info("Refining query specification...")
                    spec = refine_query_on_error(client, question, last_error, spec)
                    attempt += 1
                else:
                    # Max retries reached
                    logger.error(f"Max retries reached for question: {question}")
                    return None

        # ADAPTIVE: If 0 rows and we used "current" (recent) scope, retry once with ALL periods.
        # Works for any question — sales, costs, compare — no hardcoding.
        if not rows and time_scope == "current":
            try:
                db.rollback()
            except Exception:
                pass
            logger.info("Retrying with time_scope='both' (all periods) — adaptive fallback")
            retry_result = run_sap_sql_agent(
                question,
                db,
                knowledge_context=knowledge_context,
                max_retries=1,
                time_scope="both",
                few_shot_examples=few_shot_examples,
            )
            if retry_result and retry_result.rows:
                return retry_result

        return None

    except Exception as e:
        logger.warning("sap_sql_agent failed for question '%s': %s", question, e)
        return None


def answer_with_sap_sql_agent(question: str, db: Session) -> str:
    """
    Convenience wrapper: run the SAP SQL agent and turn its result into a natural language answer.
    """
    client = _get_openai_client()
    if not client:
        return ""

    result = run_sap_sql_agent(question, db)
    if not result or not result.rows:
        return ""

    try:
        summary = _summarize_results(question, result.sql, result.rows, client)
    except Exception as e:
        logger.warning("sap_sql_agent summarization failed: %s", e)
        return ""

    return summary
