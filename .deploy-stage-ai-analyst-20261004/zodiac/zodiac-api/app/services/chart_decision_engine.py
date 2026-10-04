"""
chart_decision_engine.py

Python port of the reference project's:
  - services/data-shape-analyzer.js   (tagColumnsByValues, detectResultShape)
  - services/analytics-chart-policy.js (coefficientOfVariation, chartForBreakdown)
  - services/chart-decision-engine.js  (decideChart)

Key principle: look at ACTUAL DATA VALUES, not column names.
Column names are a secondary tiebreaker only.

Tags:  'money' | 'count' | 'date' | 'text' | 'id' | 'ratio' | 'unknown'
Shapes: 'kpi' | 'trend' | 'comparison' | 'ranking' | 'distribution' | 'table' | 'empty'
Charts: 'bar' | 'line' | 'pie' | 'kpi_card' | 'table' | 'bar_horizontal' | 'line_large'
"""
import re
import math
import logging
from datetime import datetime, date
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# MODULE-LEVEL CONSTANTS (compiled once, not inside loops)
# ---------------------------------------------------------------------------

_MAX_PIE_SLICES = 8
_CV_PIE_AVOID = 2.2
_LINE_LARGE_THRESHOLD = 400
_SAMPLING_CAP = 500

# SAP key/document columns — always IDs, never metrics
_SAP_ID_COLS = frozenset({
    "mandt", "vbeln", "kunnr", "kunag", "kunnr", "lifnr", "matnr", "werks", "bukrs",
    "vkorg", "vtweg", "spart", "aubel", "vgbel", "fknum", "belnr",
    "buzei", "posnr", "aupos", "ebelp", "ebeln", "knumv",
    "vbelv", "posnn", "rnumb", "bolnr", "zterm", "kkber",
    "gjahr",  # fiscal year — dimensional, not a metric
    "fkart", "fktyp", "waerk", "waers", "pernr",
})

# Helper/sort columns that look numeric but are positional
_HELPER_PAT = re.compile(
    r"^(sortorder|sort_order|roworder|row_order|sortkey|sort_key|"
    r"displayorder|display_order|rn|rownum|rankno|seqno|sno|orderno|"
    r"lineorder|itemorder)$",
    re.I,
)

# English-style ID column name pattern
_ID_NAME_PAT = re.compile(
    r"(?:^|_)(id|no|num|code|ref|key|seq|recno|rowno|sno)(?:_|$)|"
    r"^(id|no|branchid|itemid|customerid|vendorid)$",
    re.I,
)

_RATIO_PAT  = re.compile(r"pct$|percent|ratio|rate$|share$|margin|growth|discount", re.I)
_MONEY_PAT  = re.compile(
    r"amount|value|sales|revenue|net|gross|total|cost|price|profit|"
    r"earning|purchase|turnover|avg|aov|average|salary|wages|netwr|kwmeng",
    re.I,
)
_COUNT_PAT  = re.compile(
    r"count$|qty$|quantity$|units?$|bills?$|invoices?$|orders?$|"
    r"customers?$|items?$|pieces?$|txn|transactions?$|footfall",
    re.I,
)
_PERIOD_COL_PAT = re.compile(
    r"^(period|label|range|timerange|periodlabel|periodname|comparelabel)$", re.I
)

COLORS = ["#3b82f6", "#6366f1", "#10b981", "#f59e0b", "#ef4444", "#8b5cf6", "#ec4899"]


# ---------------------------------------------------------------------------
# DATE HELPERS
# ---------------------------------------------------------------------------

def _is_date_value(v: Any) -> bool:
    """True when v looks like a calendar date (not a document/ID number)."""
    if isinstance(v, (datetime, date)):
        return True
    s = str(v).strip()
    # ISO date: YYYY-MM-DD
    if re.match(r"^\d{4}-\d{2}-\d{2}", s):
        return True
    # DD/MM/YYYY or DD-MM-YYYY
    if re.match(r"^\d{2}[/\-]\d{2}[/\-]\d{4}", s):
        return True
    # SAP 8-digit YYYYMMDD — require plausible year (1900-2100) and valid month
    m8 = re.fullmatch(r"(\d{4})(\d{2})(\d{2})", s)
    if m8:
        y, mo, dy = m8.group(1), m8.group(2), m8.group(3)
        if "1900" <= y <= "2100" and "01" <= mo <= "12" and "01" <= dy <= "31":
            return True
    # SAP 6-digit period YYYYPP — require plausible year and period 01-16
    m6 = re.fullmatch(r"(\d{4})(\d{2})", s)
    if m6:
        y, pp = m6.group(1), m6.group(2)
        if "1990" <= y <= "2100" and "01" <= pp <= "16":
            return True
    # Month name prefix
    if re.match(r"^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s", s, re.I):
        return True
    return False


def _coerce_date(val: Any) -> Optional[datetime]:
    """Parse a value to datetime, or return None."""
    if isinstance(val, datetime):
        return val
    if isinstance(val, date):
        return datetime(val.year, val.month, val.day)
    s = str(val or "").strip()
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    m2 = re.fullmatch(r"(\d{2})[./\-](\d{2})[./\-](\d{4})", s)
    if m2:
        try:
            return datetime(int(m2.group(3)), int(m2.group(2)), int(m2.group(1)))
        except ValueError:
            return None
    m3 = re.fullmatch(r"(\d{4})(\d{2})(\d{2})", s)
    if m3:
        try:
            return datetime(int(m3.group(1)), int(m3.group(2)), int(m3.group(3)))
        except ValueError:
            return None
    return None


def _label_looks_like_dates(rows: List[Dict], col: str, threshold: float = 0.55) -> bool:
    sample = rows[:min(len(rows), 50)]
    ok = empty = 0
    for r in sample:
        s = str(r.get(col) or "").strip()
        if not s:
            empty += 1
            continue
        if _coerce_date(s) or s.lower() in ("today", "yesterday"):
            ok += 1
    denom = len(sample) - empty
    return denom > 0 and (ok / denom) >= threshold


def _dates_non_decreasing(rows: List[Dict], col: str, min_parsable: int = 2) -> bool:
    dates = [d for r in rows if (d := _coerce_date(r.get(col)))]
    if len(dates) < min_parsable:
        return False
    return all(dates[i] >= dates[i - 1] for i in range(1, len(dates)))


def _likely_daily_grain(rows: List[Dict], col: str) -> bool:
    n = min(len(rows), 31)
    deltas, prev, c = [], None, 0
    for r in rows:
        if c >= n:
            break
        d = _coerce_date(r.get(col))
        if d is None:
            continue
        if prev is not None:
            deltas.append(abs((d - prev).days))
        prev = d
        c += 1
    if not deltas:
        return False
    med = sorted(deltas)[len(deltas) // 2]
    return 0.9 <= med <= 1.2


# ---------------------------------------------------------------------------
# ANALYTICS POLICY
# ---------------------------------------------------------------------------

def coefficient_of_variation(values: List[float]) -> float:
    v = [x for x in (values or []) if math.isfinite(x) and x >= 0]
    if len(v) < 2:
        return 0.0
    mean = sum(v) / len(v)
    if abs(mean) < 1e-12:
        return 0.0
    variance = sum((x - mean) ** 2 for x in v) / max(len(v) - 1, 1)
    return math.sqrt(max(variance, 0)) / mean


def chart_for_breakdown(row_count: int, labels: List[str], metric_values: List[float]) -> str:
    n = row_count or 0
    if n <= 0:
        return "table"
    cv = coefficient_of_variation(metric_values)
    max_lab = max((len(str(s or "")) for s in labels), default=0)
    if n <= 8:
        return "bar" if cv >= _CV_PIE_AVOID else "pie"
    if n <= 24:
        return "bar_horizontal" if max_lab > 22 else "bar"
    return "bar_horizontal"


def progressive_hint(row_count: int, max_points: int = _SAMPLING_CAP) -> Dict[str, Any]:
    if row_count <= max_points:
        return {"mode": "full", "sampleSize": row_count, "maxPoints": max_points}
    step = math.ceil(row_count / max_points)
    return {"mode": "sampled", "sampleSize": math.ceil(row_count / step), "stride": step, "maxPoints": max_points}


# ---------------------------------------------------------------------------
# COLUMN TAGGER — value-first, name-as-tiebreaker
# ---------------------------------------------------------------------------

def tag_columns_by_values(rows: List[Dict[str, Any]]) -> Dict[str, str]:
    """
    Tag each column by examining actual values (not just names).
    Column names used only as tiebreakers.

    Returns: {col_name: 'money'|'count'|'date'|'text'|'id'|'ratio'|'unknown'}
    """
    if not rows:
        return {}

    cols = list(rows[0].keys())
    sample = rows[:min(len(rows), 30)]
    tags: Dict[str, str] = {}

    for col in cols:
        col_lower = col.lower()

        # ── PRE-CHECK: known SAP ID / key columns → always 'id' ───────────
        if col_lower in _SAP_ID_COLS:
            tags[col] = "id"
            continue

        # ── PRE-CHECK: helper / sort-order columns → 'id' ─────────────────
        if _HELPER_PAT.match(col_lower):
            tags[col] = "id"
            continue

        all_vals = [r.get(col) for r in sample]
        values = [v for v in all_vals if v is not None and v != ""]

        if not values:
            tags[col] = "unknown"
            continue

        # ── 1. DATE: check value format first ─────────────────────────────
        date_count = sum(1 for v in values if _is_date_value(v))
        if date_count / len(values) >= 0.6:
            tags[col] = "date"
            continue

        # ── 2. NUMERIC ratio ───────────────────────────────────────────────
        def _is_num(v: Any) -> bool:
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                return True
            try:
                float(str(v).replace(",", "").replace(" ", ""))
                return True
            except (ValueError, TypeError):
                return False

        numeric_vals = [v for v in values if _is_num(v)]
        num_ratio = len(numeric_vals) / len(values)

        if num_ratio < 0.7:
            tags[col] = "text"
            continue

        # All-numeric path
        def _f(v: Any) -> float:
            return float(v) if isinstance(v, (int, float)) else float(str(v).replace(",", "").replace(" ", ""))

        nums = [_f(v) for v in numeric_vals]
        max_val = max(nums)
        min_val = min(nums)
        avg_val = sum(nums) / len(nums)
        all_ints = all(n == int(n) for n in nums)
        has_decimal = any(abs(n % 1) > 0.001 for n in nums)
        unique_ratio = len(set(nums)) / len(nums)

        # ── 3. English-style ID by name + uniqueness ──────────────────────
        if _ID_NAME_PAT.search(col_lower) and all_ints and unique_ratio > 0.8 and max_val < 1e8:
            tags[col] = "id"
            continue

        # ── 3b. High-uniqueness integers are surrogate keys ───────────────
        # Guard: if the name looks like a metric column, never tag as id
        _is_metric_name = bool(_MONEY_PAT.search(col_lower) or _COUNT_PAT.search(col_lower))
        if not _is_metric_name and all_ints and unique_ratio > 0.95 and len(nums) >= 5:
            # Additional guard: IDs are typically < 10 digits (< 10 billion)
            # Large values (e.g. revenue in SAP scale 1000s) shouldn't be IDs
            if max_val < 1e10:
                tags[col] = "id"
                continue

        # ── 4. RATIO / PERCENTAGE ─────────────────────────────────────────
        if _RATIO_PAT.search(col_lower) and max_val <= 100 and min_val >= -100:
            tags[col] = "ratio"
            continue
        if not _ID_NAME_PAT.search(col_lower) and not _RATIO_PAT.search(col_lower):
            if max_val <= 100 and min_val >= 0 and has_decimal and avg_val < 50:
                tags[col] = "ratio"
                continue

        # ── 5. MONEY vs COUNT ─────────────────────────────────────────────
        is_money_name = bool(_MONEY_PAT.search(col_lower))
        is_count_name = bool(_COUNT_PAT.search(col_lower))

        if is_count_name and not is_money_name:
            tags[col] = "count"
            continue
        if is_money_name:
            tags[col] = "money"
            continue

        # Value-based fallback
        if has_decimal or avg_val > 1000:
            tags[col] = "money"
        elif all_ints and avg_val <= 10000 and max_val < 1e7:
            tags[col] = "count"
        else:
            tags[col] = "money" if avg_val > 500 else "count"

    return tags


# ---------------------------------------------------------------------------
# MAIN DECISION FUNCTION
# ---------------------------------------------------------------------------

def decide_chart(
    rows: List[Dict[str, Any]],
    col_tags: Optional[Dict[str, str]] = None,
    options: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Map dataset shape → visualization recommendation.

    Returns dict:
        shape, vizKind, chartType, labelCol, valueCols, title, rationale, renderHints
    """
    opts = {
        "maxPieSlices": _MAX_PIE_SLICES,
        "cvSkewForPieAvoid": _CV_PIE_AVOID,
        "lineLargeThreshold": _LINE_LARGE_THRESHOLD,
        "samplingCap": _SAMPLING_CAP,
    }
    if options:
        opts.update(options)

    def _empty(reason: str = "empty dataset"):
        return {
            "shape": "empty", "vizKind": "none", "chartType": None,
            "labelCol": None, "valueCols": [], "title": "", "rationale": [reason],
            "renderHints": {"progressive": progressive_hint(0, opts["samplingCap"]), "binning": None},
        }

    if not rows:
        return _empty()

    tags = col_tags if col_tags else tag_columns_by_values(rows)
    cols = list(rows[0].keys())
    if not cols:
        return _empty("no columns")

    date_cols   = [c for c in cols if tags.get(c) == "date"]
    money_cols  = [c for c in cols if tags.get(c) == "money"]
    count_cols  = [c for c in cols if tags.get(c) == "count"]
    text_cols   = [c for c in cols if tags.get(c) == "text"]
    id_cols     = [c for c in cols if tags.get(c) == "id"]
    ratio_cols  = [c for c in cols if tags.get(c) == "ratio"]
    numeric_cols = money_cols + count_cols + ratio_cols
    rationale: List[str] = []
    binning = None

    def _hints():
        return {"progressive": progressive_hint(len(rows), opts["samplingCap"]), "binning": binning}

    # Prefer the most distinctive non-ID text column (avoid pie/bar of all-US country).
    def _nunique(col: str) -> int:
        return len({str(r.get(col) or "") for r in rows})

    label_candidates = [c for c in text_cols if c not in id_cols]
    if len(label_candidates) > 1:
        label_candidates.sort(key=_nunique, reverse=True)
        distinctive = [c for c in label_candidates if _nunique(c) > 1]
        text_label_col = (distinctive or label_candidates)[0]
    else:
        text_label_col = label_candidates[0] if label_candidates else None

    # ── Rule 1: KPI (single aggregate row) ────────────────────────────────
    if len(rows) == 1 and len(numeric_cols) >= 1:
        rationale.append("single-row aggregate ⇒ KPI tile")
        return {
            "shape": "kpi", "vizKind": "kpi", "chartType": "kpi_card",
            "labelCol": None, "valueCols": numeric_cols, "title": "Summary",
            "rationale": rationale, "renderHints": _hints(),
        }

    # ── Rule 2: Named period compare (Period-style label + few rows) ───────
    period_col = next((c for c in text_cols if _PERIOD_COL_PAT.match(c)), None)
    if (period_col and len(rows) <= 12 and len(numeric_cols) >= 1
            and all(0 < len(str(r.get(period_col) or "")) < 40 for r in rows[:6])):
        rationale.append("few rows + Period-style label ⇒ category comparison bar")
        return {
            "shape": "comparison", "vizKind": "category_comparison", "chartType": "bar",
            "labelCol": period_col, "valueCols": numeric_cols,
            "title": "Comparison: " + " vs ".join(numeric_cols),
            "rationale": rationale, "renderHints": _hints(),
        }

    # ── Rule 3: Time series (date column present) ──────────────────────────
    if date_cols and len(numeric_cols) >= 1 and len(rows) >= 2:
        time_col = date_cols[0]
        rationale.append("date-typed axis + numeric measures ⇒ line chart")
        chart_type = "line"
        if len(rows) > opts["lineLargeThreshold"]:
            chart_type = "line_large"
            rationale.append(f"{len(rows)} points > {opts['lineLargeThreshold']} ⇒ line_large + sampling")
            binning = {"unit": "week" if _likely_daily_grain(rows, time_col) else "month",
                       "reason": "dense series — consider bucketing"}
        return {
            "shape": "trend", "vizKind": "time_series", "chartType": chart_type,
            "labelCol": time_col, "valueCols": numeric_cols,
            "title": "Trend: " + ", ".join(numeric_cols),
            "rationale": rationale, "renderHints": _hints(),
        }

    # ── Rule 3b: Date-like text label (heuristic) ─────────────────────────
    if len(numeric_cols) == 1 and len(rows) >= 3:
        label_guess = (
            next((c for c in text_cols if c not in id_cols), None)
            or next((c for c in cols if c not in numeric_cols and tags.get(c) == "unknown"), None)
        )
        if label_guess and (
            re.search(r"period|month|date|day|sale|dt|invoice|time|year|yyyymm", label_guess, re.I)
            or _label_looks_like_dates(rows, label_guess, 0.55)
        ) and _dates_non_decreasing(rows, label_guess, min(len(rows), 2)):
            rationale.append(f'label "{label_guess}" date-like ⇒ line')
            chart_type = "line"
            if len(rows) > opts["lineLargeThreshold"]:
                chart_type = "line_large"
            return {
                "shape": "trend", "vizKind": "time_series", "chartType": chart_type,
                "labelCol": label_guess, "valueCols": numeric_cols,
                "title": f"Trend: {numeric_cols[0]}",
                "rationale": rationale, "renderHints": _hints(),
            }

    # ── Rule 4: Pie — part-to-whole with moderate skew ─────────────────────
    pie_val_col = next((c for c in money_cols), None) or next((c for c in count_cols), None) or (numeric_cols[0] if numeric_cols else None)
    pie_eligible = (
        bool(text_label_col)
        and len(money_cols) == 1
        and not count_cols
        and not ratio_cols
        and len(rows) > 1
        and _nunique(text_label_col) > 1
    )
    if pie_eligible and pie_val_col:
        pie_vals = []
        for r in rows:
            try:
                x = float(r.get(pie_val_col) or 0)
                if math.isfinite(x) and x >= 0:
                    pie_vals.append(x)
            except (ValueError, TypeError):
                pass
        cv = coefficient_of_variation(pie_vals)
        if len(rows) <= opts["maxPieSlices"] and cv < opts["cvSkewForPieAvoid"] and len(numeric_cols) == 1:
            rationale.append(f"{len(rows)} slices, CV={cv:.2f} ⇒ pie")
            return {
                "shape": "distribution", "vizKind": "contribution", "chartType": "pie",
                "labelCol": text_label_col, "valueCols": [pie_val_col],
                "title": f"Distribution: {pie_val_col}",
                "rationale": rationale, "renderHints": _hints(),
            }

    # ── Rule 5: Category × measure → bar / bar_horizontal ─────────────────
    if text_label_col and len(numeric_cols) >= 1:
        clean = []
        if len(numeric_cols) == 1:
            for r in rows:
                try:
                    x = float(r.get(numeric_cols[0]) or 0)
                    if math.isfinite(x) and x >= 0:
                        clean.append(x)
                except (ValueError, TypeError):
                    pass
        chart_sub = chart_for_breakdown(len(rows), [str(r.get(text_label_col) or "") for r in rows], clean)
        viz_kind = "contribution" if chart_sub == "pie" else "category_comparison"
        rationale.append(f"categorical label + {len(numeric_cols)} measure(s) ⇒ {chart_sub}")
        return {
            "shape": "distribution" if chart_sub == "pie" else "ranking",
            "vizKind": viz_kind, "chartType": chart_sub,
            "labelCol": text_label_col, "valueCols": numeric_cols,
            "title": " & ".join(numeric_cols) + " by " + text_label_col,
            "rationale": rationale, "renderHints": _hints(),
        }

    # ── Fallback: table ────────────────────────────────────────────────────
    rationale.append("no clear axis — fallback table")
    return {
        "shape": "table", "vizKind": "ambiguous", "chartType": "table",
        "labelCol": cols[0] if cols else None,
        "valueCols": numeric_cols if numeric_cols else cols[1:],
        "title": "Results", "rationale": rationale, "renderHints": _hints(),
    }


# ---------------------------------------------------------------------------
# RESULT SHAPE DETECTOR
# ---------------------------------------------------------------------------

def detect_result_shape(rows: List[Dict[str, Any]], col_tags: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    if not rows:
        return {"shape": "empty", "chartType": None, "labelCol": None, "valueCols": [], "title": "", "engine": None}
    tags = col_tags or tag_columns_by_values(rows)
    d = decide_chart(rows, tags, {})
    return {
        "shape": d["shape"], "chartType": d["chartType"],
        "labelCol": d["labelCol"], "valueCols": d["valueCols"],
        "title": d["title"],
        "engine": {"vizKind": d["vizKind"], "rationale": d["rationale"], "renderHints": d["renderHints"]},
    }


# ---------------------------------------------------------------------------
# CHART DATA FORMATTER
# ---------------------------------------------------------------------------

def _fmt_sap_date(v: Any) -> Any:
    if not isinstance(v, str):
        return v
    s = v.strip()
    m8 = re.fullmatch(r"(\d{4})(\d{2})(\d{2})", s)
    if m8:
        y, mo, dy = m8.group(1), m8.group(2), m8.group(3)
        if "1900" <= y <= "2100" and "01" <= mo <= "12" and "01" <= dy <= "31":
            return f"{y}-{mo}-{dy}"
    m6 = re.fullmatch(r"(\d{4})(\d{2})", s)
    if m6:
        y, pp = m6.group(1), m6.group(2)
        if "1990" <= y <= "2100" and "01" <= pp <= "16":
            return f"{y}-P{pp}"
    return s


def _format_data(rows: List[Dict[str, Any]], max_items: int = 60) -> List[Dict[str, Any]]:
    result = []
    for row in rows[:max_items]:
        clean: Dict[str, Any] = {}
        for k, v in row.items():
            if v is None:
                clean[k] = 0
            elif isinstance(v, str):
                clean[k] = _fmt_sap_date(v)
            elif isinstance(v, float) and math.isfinite(v):
                clean[k] = round(v, 4)
            else:
                clean[k] = v
        result.append(clean)
    return result


# ---------------------------------------------------------------------------
# CHART SPEC BUILDER
# ---------------------------------------------------------------------------

def build_chart_spec(
    rows: List[Dict[str, Any]],
    user_query: str = "",
    sql: str = "",
    col_tags: Optional[Dict[str, str]] = None,
) -> Optional[Dict[str, Any]]:
    """
    Produce a single ChartSpec-compatible dict from rows.
    Returns None when rows is empty.
    """
    if not rows:
        return None

    tags = col_tags or tag_columns_by_values(rows)
    decision = decide_chart(rows, tags, {})

    chart_type = decision["chartType"] or "table"
    # Normalise extended types for frontend
    # line_large → line (frontend handles large datasets natively)
    if chart_type == "line_large":
        chart_type = "line"
    # bar_horizontal is kept — the frontend renders it as a horizontal bar chart
    # (do NOT collapse to "bar" here; long labels read better horizontally)

    label_col  = decision["labelCol"]
    value_cols = decision["valueCols"] or []
    title = decision["title"] or "Results"

    # Prefer a short user-query-derived title when available
    if user_query:
        q = user_query.strip().rstrip("?")
        if len(q) <= 100:
            title = q

    data = _format_data(rows)

    if chart_type == "kpi_card":
        return {
            "chart_type": "kpi_card", "title": title,
            "description": " | ".join(decision["rationale"][:2]),
            "data": data[:1], "x_key": None, "y_keys": value_cols,
            "name_key": None, "value_key": value_cols[0] if value_cols else None,
            "colors": COLORS, "show_legend": False, "show_grid": False,
            "stacked": False, "period_info": None,
        }

    if chart_type == "pie":
        pie_data = []
        for r in data[:_MAX_PIE_SLICES]:
            name_v = r.get(label_col, "")
            num_v  = r.get(value_cols[0], 0) if value_cols else 0
            try:
                num_v = float(num_v) if num_v is not None else 0.0
            except (ValueError, TypeError):
                num_v = 0.0
            pie_data.append({"name": str(name_v), "value": num_v})
        return {
            "chart_type": "pie", "title": title,
            "description": " | ".join(decision["rationale"][:2]),
            "data": pie_data, "x_key": None, "y_keys": None,
            "name_key": "name", "value_key": "value",
            "colors": COLORS, "show_legend": True, "show_grid": False,
            "stacked": False, "period_info": None,
        }

    if chart_type == "table":
        return {
            "chart_type": "table", "title": title,
            "description": " | ".join(decision["rationale"][:2]),
            "data": data[:100], "x_key": None, "y_keys": None,
            "name_key": None, "value_key": None,
            "colors": COLORS, "show_legend": False, "show_grid": False,
            "stacked": False, "period_info": None,
        }

    # bar / line / area
    return {
        "chart_type": chart_type, "title": title,
        "description": " | ".join(decision["rationale"][:2]),
        "data": data, "x_key": label_col, "y_keys": value_cols[:4],
        "name_key": None, "value_key": None,
        "colors": COLORS, "show_legend": len(value_cols) > 1, "show_grid": True,
        "stacked": False, "period_info": None,
    }


def build_chart_specs_for_rows(
    rows: List[Dict[str, Any]],
    user_query: str = "",
    sql: str = "",
) -> List[Dict[str, Any]]:
    """
    Produce 1-2 chart specs.
    Primary: value-based decision.
    Secondary: table view (always appended unless primary is already table/kpi).
    """
    if not rows:
        return []

    tags = tag_columns_by_values(rows)
    specs: List[Dict[str, Any]] = []

    primary = build_chart_spec(rows, user_query, sql, col_tags=tags)
    if primary:
        specs.append(primary)


    if primary and primary["chart_type"] not in ("table", "kpi_card"):
        table_data = _format_data(rows, max_items=100)
        specs.append({
            "chart_type": "table", "title": "Data Table",
            "description": f"{len(rows)} row(s) returned",
            "data": table_data, "x_key": None, "y_keys": None,
            "name_key": None, "value_key": None,
            "colors": COLORS, "show_legend": False, "show_grid": False,
            "stacked": False, "period_info": None,
        })

    return specs
