"""
AI-powered chart generation service.

Analyzes query results and generates appropriate visualizations (bar, line, pie, area charts)
with Recharts-compatible data structures.
"""
import json
import logging
import re
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional

from openai import OpenAI

from ..config.config import OPENAI_API_KEY

logger = logging.getLogger(__name__)


@dataclass
class ChartSpec:
    """Specification for a single chart visualization."""
    chart_type: str  # "bar", "line", "pie", "area", "table", "stacked_bar", "stacked_area", "timeline"
    title: str
    description: str
    data: List[Dict[str, Any]]
    x_key: Optional[str] = None  # Key for X-axis (bar, line, area)
    y_keys: Optional[List[str]] = None  # Keys for Y-axis values
    name_key: Optional[str] = None  # Key for pie chart labels
    value_key: Optional[str] = None  # Key for pie chart values
    colors: Optional[List[str]] = None  # Enhanced color scheme
    show_legend: bool = True
    show_grid: bool = True
    stacked: bool = False  # For stacked bar/area charts
    period_info: Optional[str] = None  # Period context (e.g., "Q1 2024", "2023-2024")


def _pretty_key_name(key: Optional[str]) -> str:
    if not key:
        return "Value"
    return str(key).replace("_", " ").strip().title()


def _normalize_chart_title(chart: ChartSpec) -> str:
    """
    Post-process LLM chart titles so they always match the actual x/y keys used by the chart data.
    This prevents misleading titles like "by month" when the x-axis is daily billing dates.
    """
    x = _pretty_key_name(chart.x_key)

    if chart.chart_type == "pie":
        val = _pretty_key_name(chart.value_key)
        return f"{val} Distribution"

    y0 = None
    if chart.y_keys and len(chart.y_keys) > 0:
        y0 = chart.y_keys[0]
    elif chart.value_key:
        y0 = chart.value_key

    if y0 and x:
        y = _pretty_key_name(y0)
        return f"{y} by {x}"

    return chart.title or "Visualization"


def _title_implies_month(title: str) -> bool:
    t = (title or "").lower()
    return bool(re.search(r"\bmonth|monthly|per month|by month\b", t))


def _x_key_is_month_bucket(x_key: Optional[str], data: List[Dict[str, Any]]) -> bool:
    if not x_key or not data:
        return False
    xk = str(x_key).lower()
    if any(k in xk for k in ("month", "yyyymm", "year_month", "period")):
        return True
    samples = [str((r or {}).get(x_key, "")).strip() for r in data[:15]]
    month_like = 0
    for s in samples:
        if re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", s) or re.fullmatch(r"\d{6}", s):
            month_like += 1
    return month_like >= 3


def mixed_currency_disclaimer(rows: List[Dict[str, Any]], sql: str = "") -> str:
    """
    If result rows include multiple WAERK/waers values, charts and copy should not imply a single currency.
    """
    if not rows:
        return ""
    waerk_vals: set[str] = set()
    for r in rows[:500]:
        if not isinstance(r, dict):
            continue
        for k in r.keys():
            lk = str(k).lower()
            if lk in ("waerk", "waers", "currency", "curr"):
                v = r.get(k)
                if v is not None and str(v).strip():
                    waerk_vals.add(str(v).strip())
    if len(waerk_vals) <= 1:
        return ""
    shown = ", ".join(sorted(waerk_vals)[:8])
    return (
        f"Mixed currencies in data ({shown}); numeric totals are not a single currency unless split by currency."
    )


def _apply_mixed_currency_note(charts: List[ChartSpec], rows: List[Dict[str, Any]], sql: str) -> None:
    note = mixed_currency_disclaimer(rows, sql)
    if note and charts:
        c0 = charts[0]
        c0.description = (c0.description + " " + note).strip()


def _extract_sql_filter_labels(sql: str) -> List[str]:
    s = sql or ""
    labels: List[str] = []

    years = sorted(set(re.findall(r"SUBSTRING\s*\(\s*TRIM\s*\([^)]*fkdat[^)]*\)\s*,\s*1\s*,\s*4\s*\)\s*=\s*'((?:19|20)\d{2})'", s, flags=re.IGNORECASE)))
    if years:
        labels.append("year=" + ",".join(years))

    m_cat = re.search(r"fktyp\"?\s*=\s*'([A-Za-z0-9]{1,10})'", s, flags=re.IGNORECASE)
    if m_cat:
        labels.append(f"billing_category={m_cat.group(1)}")

    m_type = re.search(r"fkart\"?\s*=\s*'([A-Za-z0-9]{1,10})'", s, flags=re.IGNORECASE)
    if m_type:
        labels.append(f"billing_type={m_type.group(1)}")

    m_curr = re.search(r"waerk\"?\s*=\s*'([A-Za-z]{3})'", s, flags=re.IGNORECASE)
    if m_curr:
        labels.append(f"currency={m_curr.group(1).upper()}")

    return labels


def _apply_sql_filter_context(charts: List[ChartSpec], sql: str) -> None:
    if not charts:
        return
    labels = _extract_sql_filter_labels(sql)
    if not labels:
        return
    suffix = " | Filters: " + ", ".join(labels)
    for c in charts:
        # Keep title compact and deterministic; dimensions still come from x/y keys.
        c.title = (c.title or "Visualization") + suffix


def is_raw_table_inspection_query(user_query: str) -> bool:
    """Row/list inspection — prefer table, not a generic KPI bar chart."""
    ql = (user_query or "").lower()
    if re.search(r"\b(compare|vs\.?|versus)\b", ql):
        return False
    return bool(
        re.search(r"\b(last|first|top)\s+\d+\s+rows?\b", ql)
        or re.search(r"\blist\s+(\d+\s+)?(the\s+)?rows?\b", ql)
        or re.search(r"\bshow\s+(me\s+)?(all\s+)?rows?\b", ql)
        or re.search(r"\b(raw\s+)?(data|rows?)\s+(please|only)?\b", ql)
    )


def plan_compare_year_bar_chart(
    merged_rows: List[Dict[str, Any]],
    user_query: str,
) -> Optional[List[ChartSpec]]:
    """
    Side-by-side / grouped bar: x = calendar_year, y = total_revenue (merged compare path).
    """
    if not merged_rows or len(merged_rows) < 2:
        return None
    data: List[Dict[str, Any]] = []
    for r in merged_rows:
        y = r.get("calendar_year")
        v = r.get("total_revenue")
        if y is None:
            continue
        data.append(
            {
                "calendar_year": str(y),
                "total_revenue": float(v) if isinstance(v, (int, float)) else v,
            }
        )
    if len(data) < 2:
        return None
    note = mixed_currency_disclaimer(data, "")
    desc = "Total billing revenue by calendar year (from year-scoped SQL)."
    if note:
        desc += " " + note
    y0, y1 = data[0]["calendar_year"], data[-1]["calendar_year"]
    return [
        ChartSpec(
            chart_type="bar",
            title=f"Revenue by year ({y0} vs {y1})",
            description=desc,
            data=data,
            x_key="calendar_year",
            y_keys=["total_revenue"],
            colors=["#3b82f6", "#6366f1", "#10b981", "#f59e0b"],
            show_legend=True,
            show_grid=True,
        )
    ]


def plan_adaptive_chart_specs(
    rows: List[Dict[str, Any]],
    user_query: str,
    sql: str,
    result_scope: Optional[Dict[str, Any]],
    action: str,
    *,
    query_profile: Optional[Dict[str, Any]] = None,
    result_shape: Optional[Dict[str, Any]] = None,
) -> Optional[List[ChartSpec]]:
    """
    Data-driven chart selection before the LLM chart recommender.
    Uses adaptive_ai_context profiles when provided (or builds them here).
    Returns None to fall through to LLM.
    """
    if not rows:
        return None
    q = (user_query or "").lower()

    try:
        from .adaptive_ai_context import (
            analyze_sql_result_shape,
            build_adaptive_query_profile,
            choose_dimension_column,
            wants_table_first,
        )

        profile = query_profile or build_adaptive_query_profile(user_query)
        shape = result_shape or analyze_sql_result_shape(rows, sql)
    except Exception:
        profile = {"kind": "general", "tags": [], "flags": {}}
        shape = {}

    if wants_table_first(profile, shape):
        fd = _format_chart_data(rows, max_items=100)
        return [
            ChartSpec(
                chart_type="table",
                title="Query results" + _scope_suffix(result_scope),
                description="Table-first view for row-level or wide result shape.",
                data=fd,
                show_legend=False,
                show_grid=False,
            )
        ]

    if is_raw_table_inspection_query(user_query):
        fd = _format_chart_data(rows, max_items=80)
        return [
            ChartSpec(
                chart_type="table",
                title="Query results" + _scope_suffix(result_scope),
                description="Row-level results as requested.",
                data=fd,
                show_legend=False,
                show_grid=False,
            )
        ]

    # Compare action with explicit year scope in result_scope
    if action == "compare" and isinstance(result_scope, dict) and result_scope.get("kind") == "compare":
        # Prefer LLM / merged path from orchestrator; no duplicate here
        return None

    time_keys: List[str] = list(shape.get("time_columns") or [])
    if not time_keys and rows and isinstance(rows[0], dict):
        for k in rows[0].keys():
            lk = str(k).lower()
            if lk in (
                "fkdat",
                "billing_date",
                "date",
                "month",
                "year_month",
                "period",
                "calmonth",
                "calendar_year",
                "billing_year",
                "year",
                "gjahr",
                "fiscal_year",
                "fisc_year",
            ):
                time_keys.append(k)

    numeric_cols = _detect_numeric_columns(rows)
    categorical_cols = _detect_categorical_columns(rows)
    dim_pick = choose_dimension_column(shape) if shape else None
    if not dim_pick and categorical_cols:
        dim_pick = categorical_cols[0]

    trendish = profile.get("kind") == "trend" or bool(
        re.search(r"\b(trend|over\s+time|monthly|each\s+month)\b", q)
    )
    use_line_for_time = time_keys and numeric_cols and len(rows) >= 3 and (
        trendish or len(rows) >= 5 or profile.get("kind") == "trend"
    )
    if use_line_for_time:
        tk = time_keys[0]
        measures = shape.get("measure_columns") if shape else None
        y_list = (
            [m for m in (measures or []) if m in numeric_cols][:3]
            if measures
            else [numeric_cols[0]]
        )
        if not y_list:
            y_list = [numeric_cols[0]]
        fd = _format_chart_data(rows, max_items=60)
        return [
            ChartSpec(
                chart_type="line",
                title=f"Measures over {tk.replace('_', ' ')}",
                description="Trend from query results (time axis from data).",
                data=fd,
                x_key=tk,
                y_keys=y_list,
                colors=["#3b82f6", "#10b981", "#f59e0b"],
                show_legend=len(y_list) > 1,
                show_grid=True,
            )
        ]

    # Ranking: top/bottom + category + measure
    if profile.get("kind") == "rank" or re.search(
        r"\b(top|bottom|rank|largest|smallest|highest|lowest)\b", q
    ):
        if dim_pick and numeric_cols and len(rows) <= 45:
            fd = _format_chart_data(rows, max_items=35)
            return [
                ChartSpec(
                    chart_type="bar",
                    title=f"{numeric_cols[0].replace('_', ' ').title()} by {dim_pick.replace('_', ' ').title()}",
                    description="Ranking from SQL result.",
                    data=fd,
                    x_key=dim_pick,
                    y_keys=[numeric_cols[0]],
                    colors=["#3b82f6", "#6366f1"],
                    show_legend=True,
                    show_grid=True,
                )
            ]

    # Single-row aggregate: table only (avoid fake single-bar chart)
    if len(rows) == 1:
        fd = _format_chart_data(rows, max_items=5)
        return [
            ChartSpec(
                chart_type="table",
                title="Summary" + _scope_suffix(result_scope),
                description="Single-row aggregate — values below.",
                data=fd,
                show_legend=False,
                show_grid=False,
            )
        ]

    # Distribution / share
    dist_q = profile.get("kind") == "distribution" or re.search(
        r"\b(share|distribution|proportion|breakdown|percent)\b", q
    )
    if dist_q and dim_pick and numeric_cols:
        fd = _format_chart_data(rows, max_items=min(len(rows), 40))
        if len(rows) <= 8:
            return [
                ChartSpec(
                    chart_type="pie",
                    title=f"{numeric_cols[0].replace('_', ' ').title()} distribution",
                    description="Share of categories in result set.",
                    data=fd,
                    name_key=dim_pick,
                    value_key=numeric_cols[0],
                    colors=["#3b82f6", "#6366f1", "#10b981", "#f59e0b", "#ef4444"],
                    show_legend=True,
                    show_grid=False,
                )
            ]
        return [
            ChartSpec(
                chart_type="bar",
                title=f"{numeric_cols[0].replace('_', ' ').title()} by {dim_pick.replace('_', ' ')}",
                description="Distribution — bar used because category count is large for a pie.",
                data=fd,
                x_key=dim_pick,
                y_keys=[numeric_cols[0]],
                colors=["#3b82f6", "#6366f1"],
                show_legend=True,
                show_grid=True,
            )
        ]

    smeasures = list(shape.get("measure_columns") or []) if shape else []
    smeasures = [m for m in smeasures if m in numeric_cols]
    if (
        len(smeasures) >= 2
        and dim_pick
        and profile.get("kind") in ("aggregate", "general")
        and not shape.get("time_columns")
        and len(rows) <= 40
    ):
        fd = _format_chart_data(rows, max_items=35)
        ys = smeasures[:3]
        return [
            ChartSpec(
                chart_type="bar",
                title="Multiple measures by category",
                description="Grouped measures from SQL (same category axis).",
                data=fd,
                x_key=dim_pick,
                y_keys=ys,
                colors=["#3b82f6", "#6366f1", "#10b981", "#f59e0b"],
                show_legend=True,
                show_grid=True,
            )
        ]

    # Year / period comparison already present in SQL result (e.g. GROUP BY calendar year)
    years_in_q = list(dict.fromkeys(re.findall(r"\b((?:19|20)\d{2})\b", user_query or "")))
    multi_year_question = len(set(years_in_q)) >= 2
    compare_like = bool(
        profile.get("kind") == "compare"
        or re.search(r"\b(compare|comparison|vs\.?|versus|between|against)\b", q)
        or re.search(r"\b(change|changed|difference)\b.*\bfrom\b.*\bto\b", q)
        or multi_year_question
    )
    year_dim_keys: List[str] = []
    if rows and isinstance(rows[0], dict):
        for k in rows[0].keys():
            lk = str(k).lower()
            if lk in ("calendar_year", "billing_year", "fisc_year", "fiscal_year", "year", "gjahr"):
                year_dim_keys.append(k)
    if compare_like and year_dim_keys and len(rows) >= 2 and numeric_cols:
        fd = _format_chart_data(rows, max_items=25)
        ycol = year_dim_keys[0]
        return [
            ChartSpec(
                chart_type="bar",
                title=f"{numeric_cols[0].replace('_', ' ').title()} by {ycol.replace('_', ' ')}"
                + _scope_suffix(result_scope),
                description="Period comparison from SQL result (x-axis matches grouped period column).",
                data=fd,
                x_key=ycol,
                y_keys=[numeric_cols[0]],
                colors=["#3b82f6", "#6366f1", "#10b981", "#f59e0b"],
                show_legend=True,
                show_grid=True,
            )
        ]

    return None


def _scope_suffix(result_scope: Optional[Dict[str, Any]]) -> str:
    if not result_scope:
        return ""
    if result_scope.get("kind") == "limited":
        lim = result_scope.get("limit")
        returned = result_scope.get("row_count_returned")
        if lim:
            return f" (limited to {returned} row(s), LIMIT {lim})"
        return f" (limited to {returned} row(s))"
    return ""


def _get_client() -> OpenAI:
    """Get OpenAI client."""
    return OpenAI(api_key=OPENAI_API_KEY)


def _safe_json_extract(text: str) -> Dict[str, Any]:
    """Extract JSON from LLM response."""
    if not text:
        return {}
    try:
        return json.loads(text)
    except Exception:
        m = re.search(r"\{[\s\S]*\}", text)
        if not m:
            return {}
        try:
            return json.loads(m.group(0))
        except Exception:
            return {}


def _detect_numeric_columns(rows: List[Dict[str, Any]]) -> List[str]:
    """
    Detect numeric columns in result set.
    Uses both value inspection AND column name patterns.
    """
    if not rows:
        return []
    
    numeric_cols = []
    
    # Check first few rows (not just first row in case of NULL values)
    sample_size = min(5, len(rows))
    for key in rows[0].keys():
        is_numeric = False
        
        # Strategy 1: Check if column name suggests numeric data
        key_lower = key.lower()
        numeric_name_patterns = [
            "total", "sum", "count", "amount", "value", "revenue", "sales",
            "price", "cost", "quantity", "volume", "avg", "average", "max",
            "min", "balance", "payment", "invoice", "credit", "debit", "netwr"
        ]
        if any(pattern in key_lower for pattern in numeric_name_patterns):
            is_numeric = True
        
        # Strategy 2: Check actual values in sample rows
        if not is_numeric:
            for row in rows[:sample_size]:
                value = row.get(key)
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    is_numeric = True
                    break
        
        if is_numeric:
            numeric_cols.append(key)
    
    return numeric_cols


def _detect_categorical_columns(rows: List[Dict[str, Any]]) -> List[str]:
    """Detect categorical (text/label) columns in result set."""
    if not rows:
        return []
    
    categorical_cols = []
    first_row = rows[0]
    
    for key, value in first_row.items():
        if isinstance(value, str) or (value is None):
            categorical_cols.append(key)
    
    return categorical_cols


def _find_matching_key(target_key: str, available_keys: List[str]) -> Optional[str]:
    """Find a matching key using case-insensitive comparison and common variations."""
    if not target_key:
        return None
    
    target_lower = target_key.lower()
    
    # Exact match (case-insensitive)
    for key in available_keys:
        if key.lower() == target_lower:
            return key
    
    # Partial match
    for key in available_keys:
        if target_lower in key.lower() or key.lower() in target_lower:
            return key
    
    # Common variations (underscores, spaces, camelCase)
    normalized_target = target_lower.replace('_', '').replace(' ', '').replace('-', '')
    for key in available_keys:
        normalized_key = key.lower().replace('_', '').replace(' ', '').replace('-', '')
        if normalized_target == normalized_key:
            return key
    
    return None


def _format_sap_date(value: str) -> str:
    """
    Convert SAP-format date strings (YYYYMMDD) to readable ISO dates (YYYY-MM-DD).
    Also converts SAP period strings like YYYYPP (e.g. 202403 → "2024-03").
    Returns original string if not an SAP date.
    """
    s = str(value).strip()
    # SAP full date: exactly 8 digits, e.g. "19960308"
    if re.fullmatch(r"\d{8}", s):
        yyyy, mm, dd = s[:4], s[4:6], s[6:]
        # Basic sanity check (month 01-12, day 01-31)
        if "01" <= mm <= "12" and "01" <= dd <= "31":
            return f"{yyyy}-{mm}-{dd}"
    # SAP period: 6 digits where last 2 are 01-16 (fiscal periods 1-16), e.g. "202403"
    if re.fullmatch(r"\d{6}", s):
        yyyy, pp = s[:4], s[4:]
        if "01" <= pp <= "16":
            return f"{yyyy}-P{pp}"
    return s


def _format_chart_data(rows: List[Dict[str, Any]], max_items: int = 50) -> List[Dict[str, Any]]:
    """Format and limit data for chart rendering."""
    if not rows:
        return []

    # Limit number of data points for readability
    limited_rows = rows[:max_items]

    # Detect which columns look like SAP date columns by name
    if limited_rows:
        date_col_patterns = {
            "fkdat", "budat", "bldat", "bedat", "kadat", "kdatu", "augdt",
            "erdat", "laeda", "billing_date", "posting_date", "date",
            "period", "poper", "gjahr",
        }
        sample = limited_rows[0]
        date_cols = {
            k for k in sample.keys()
            if k.lower() in date_col_patterns
            or k.lower().endswith("_date")
            or k.lower().endswith("date")
        }
    else:
        date_cols = set()

    # Clean up data: convert None to 0, format numbers, convert SAP dates
    formatted = []
    for row in limited_rows:
        clean_row = {}
        for key, value in row.items():
            if value is None:
                clean_row[key] = 0
            elif key in date_cols and isinstance(value, str):
                clean_row[key] = _format_sap_date(value)
            elif isinstance(value, str) and re.fullmatch(r"\d{8}", value.strip()):
                # Even columns not named "date" but containing 8-digit SAP dates — convert them
                clean_row[key] = _format_sap_date(value.strip())
            elif isinstance(value, (int, float)):
                clean_row[key] = round(float(value), 2)
            else:
                clean_row[key] = str(value)
        formatted.append(clean_row)

    return formatted


def analyze_visualization_needs(
    rows: List[Dict[str, Any]],
    user_query: str,
    action: str,
    sql: str = "",
    result_scope: Optional[Dict[str, Any]] = None,
    *,
    query_profile: Optional[Dict[str, Any]] = None,
    result_shape: Optional[Dict[str, Any]] = None,
) -> List[ChartSpec]:
    """
    Analyze query results and determine appropriate visualizations.
    
    Args:
        rows: Query result rows
        user_query: Original user question
        action: Action type from orchestrator (new, compare, reuse, etc.)
        sql: SQL query that was executed
    
    Returns:
        List of ChartSpec objects describing recommended visualizations
    """
    if not rows or len(rows) == 0:
        logger.info("❌ No rows to visualize (rows is empty or None)")
        return []

    adaptive = plan_adaptive_chart_specs(
        rows,
        user_query,
        sql,
        result_scope,
        action,
        query_profile=query_profile,
        result_shape=result_shape,
    )
    if adaptive:
        logger.info("📊 Adaptive chart plan: %s", [c.chart_type for c in adaptive])
        _apply_sql_filter_context(adaptive, sql)
        _apply_mixed_currency_note(adaptive, rows, sql)
        return adaptive

    logger.info(f"📊 Analyzing {len(rows)} rows for visualization")
    logger.info(f"📊 Sample row: {rows[0] if rows else 'None'}")
    
    # Check for all-NULL data (common issue with bad joins)
    if rows:
        non_null_count = sum(1 for row in rows[:5] for v in row.values() if v is not None)
        total_values = sum(len(row) for row in rows[:5])
        null_percentage = ((total_values - non_null_count) / total_values * 100) if total_values > 0 else 0
        
        if null_percentage > 80:
            logger.warning(f"⚠️ {null_percentage:.0f}% of values are NULL! This usually means:")
            logger.warning("   1. JOIN conditions are incorrect or don't match any data")
            logger.warning("   2. Data columns are empty in database")
            logger.warning("   3. Filters are too restrictive")
            logger.warning(f"   Sample row: {rows[0]}")
    
    # Quick analysis of data structure
    numeric_cols = _detect_numeric_columns(rows)
    categorical_cols = _detect_categorical_columns(rows)
    
    logger.info(f"📊 Found {len(numeric_cols)} numeric columns: {numeric_cols}")
    logger.info(f"📊 Found {len(categorical_cols)} categorical columns: {categorical_cols}")
    
    if not numeric_cols:
        logger.warning("⚠️ No numeric columns detected. Generating table view only.")
        # Generate at least a table view
        try:
            charts = _auto_generate_basic_charts(
                rows, user_query, [], categorical_cols, result_scope=result_scope, sql=sql
            )
            _apply_mixed_currency_note(charts, rows, sql)
            return charts
        except Exception as e:
            logger.error(f"❌ Table generation failed: {e}")
            return []
    
    # Use LLM to recommend chart types and structure
    try:
        client = _get_client()
        
        sample_rows = rows[:5]
        try:
            from .adaptive_ai_context import (
                analyze_sql_result_shape,
                build_adaptive_query_profile,
            )

            _prof = query_profile or build_adaptive_query_profile(user_query)
            _sh = result_shape or analyze_sql_result_shape(rows, sql)
            shape_blurb = (
                f"row_count={_sh.get('row_count')}; time_columns={_sh.get('time_columns')}; "
                f"measures={(_sh.get('measure_columns') or [])[:6]}; "
                f"dimensions={(_sh.get('dimension_columns') or [])[:6]}; "
                f"mixed_currency={_sh.get('mixed_currency')}"
            )
            profile_blurb = json.dumps(
                {"kind": _prof.get("kind"), "tags": _prof.get("tags"), "flags": _prof.get("flags")},
                default=str,
            )[:600]
        except Exception:
            shape_blurb = ""
            profile_blurb = ""

        prompt = f"""
You are a data visualization expert. Analyze this query result and recommend the best chart(s).

User question: "{user_query}"

SQL query: {sql[:500] if sql else "N/A"}

Intent profile (follow this; do not contradict): {profile_blurb or "N/A"}
Result shape: {shape_blurb or "N/A"}

Sample data (first 5 rows):
{json.dumps(sample_rows, default=str, indent=2)}

Available columns:
- Numeric: {', '.join(numeric_cols)}
- Categorical: {', '.join(categorical_cols)}

Total rows: {len(rows)}

Task:
Recommend 1-3 chart visualizations. Consider:
- Bar chart: Good for comparing categories (top customers, products, countries)
- Line chart: Good for trends over time
- Pie chart: Good for showing distribution/proportions (max 10 segments)
- Area chart: Good for cumulative trends over time
- Table: When data has many columns or is not numeric

Return STRICT JSON:
{{
  "charts": [
    {{
      "chart_type": "bar" | "line" | "pie" | "area" | "table",
      "title": "Clear chart title",
      "description": "Brief description of what this shows",
      "x_key": "column_name_for_x_axis",
      "y_keys": ["column1", "column2"],
      "name_key": "column_for_pie_labels",
      "value_key": "column_for_pie_values",
      "reason": "Why this chart type"
    }}
  ]
}}

Rules:
- For bar charts: x_key = categorical column, y_keys = numeric columns
- For pie charts: name_key = categorical column, value_key = numeric column
- For line/area charts: x_key = time/sequence column, y_keys = numeric columns
- Max 3 charts per query
- Only recommend charts that make sense for the data
- Chart title and x_key MUST match actual column names in the sample (never title "by year" unless a year column exists in the data).
- For compare / vs / two-period questions, prefer bar or grouped series only if the data includes a period or year column; otherwise use a table.
- Chart title MUST reflect the user question specifically:
  * If the query is "total sales by year", title = "Total Sales by Year" (NOT "Total Sales by Billing Date")
  * If the query is "top customers by revenue", title = "Top Customers by Revenue"
  * If the query is "cost by profit center", title = "Cost by Profit Center"
  * If the data has a date column grouped by year (fkdat→year), use "by Year" not "by Date"
  * If the date column has full YYYYMMDD values and there are many rows, prefer "by Year" in the title
  * Never use generic titles like "Total Sales" alone — always say "by <dimension>"
"""
        
        # Use smart_chat_completion so chart analysis benefits from the same
        # GPT-4o → Claude 3.5 Sonnet → Gemini 1.5 Pro → GPT-4o-mini fallback chain.
        try:
            from .multi_llm_client import smart_chat_completion as _smart_complete
            llm_response, _model_used = _smart_complete(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=800,
                require_premium=False,
            )
            llm_response = (llm_response or "").strip()
            logger.info(f"📊 Chart LLM model used: {_model_used}")
        except Exception as _sc_err:
            logger.warning(f"⚠️ smart_chat_completion failed for chart ({_sc_err}), falling back to gpt-4o-mini")
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=800,
            )
            llm_response = (response.choices[0].message.content or "").strip()
        logger.info(f"📊 LLM chart recommendation response: {llm_response[:200]}...")
        
        result = _safe_json_extract(llm_response)
        chart_recommendations = result.get("charts", [])
        
        if not chart_recommendations:
            logger.warning(f"❌ LLM returned no chart recommendations. Response: {llm_response[:500]}")
            return []
        
        logger.info(f"📊 LLM recommended {len(chart_recommendations)} chart(s)")
        
        # Generate ChartSpec objects
        charts = []
        for idx, rec in enumerate(chart_recommendations[:3], 1):  # Limit to 3 charts
            chart_type = rec.get("chart_type", "bar")
            logger.info(f"📊 Generating chart {idx}: type={chart_type}, config={rec}")
            
            # Generate chart data based on type
            chart_data = generate_chart_data(rows, chart_type, rec)
            
            if not chart_data:
                logger.warning(f"❌ Chart {idx} data generation returned empty for type={chart_type}")
                continue
            
            logger.info(f"✅ Chart {idx} data generated: {len(chart_data)} data points")
            
            # Color schemes (blue/indigo palette)
            color_schemes = {
                "bar": ["#3b82f6", "#6366f1", "#818cf8", "#a5b4fc"],  # Blue to indigo shades
                "line": ["#3b82f6", "#10b981", "#f59e0b", "#ef4444"],  # Blue, green, amber, red
                "pie": ["#3b82f6", "#6366f1", "#10b981", "#f59e0b", "#ef4444", "#8b5cf6", "#ec4899"],
                "area": ["#3b82f6", "#6366f1", "#10b981"],
            }
            
            # Use updated keys from config (may have been corrected in generate_chart_data)
            chart_spec = ChartSpec(
                chart_type=chart_type,
                title=rec.get("title", "Visualization"),
                description=rec.get("description", ""),
                data=chart_data,
                x_key=rec.get("x_key"),  # These were updated by generate_chart_data
                y_keys=rec.get("y_keys"),
                name_key=rec.get("name_key"),
                value_key=rec.get("value_key"),
                colors=color_schemes.get(chart_type, color_schemes.get("bar", ["#4F46E5"])),
                show_legend=True,
                show_grid=chart_type in ["bar", "line", "area", "stacked_bar", "stacked_area", "timeline"],
                stacked=rec.get("stacked", False),
                period_info=rec.get("period_info"),
            )
            
            # Normalize title to match actual x/y keys used by the generated chart data.
            chart_spec.title = _normalize_chart_title(chart_spec)
            # Guard: never claim "by month" unless x-axis is month-bucketed.
            if _title_implies_month(chart_spec.title) and not _x_key_is_month_bucket(chart_spec.x_key, chart_data):
                chart_spec.title = "Lowest line amounts (sample rows)"
                chart_spec.description = (
                    "Title adjusted because the data is line-level/date-level, not monthly aggregated."
                )
            if result_scope and result_scope.get("kind") == "limited":
                chart_spec.description = (
                    (chart_spec.description + " ").strip()
                    + f"Based on limited result scope: {result_scope.get('row_count_returned')} row(s)."
                ).strip()
            chart_spec.title = chart_spec.title + _scope_suffix(result_scope)
            
            charts.append(chart_spec)
            logger.info(f"✅ Created chart spec: {chart_spec.title} (type={chart_type}, data_points={len(chart_data)})")
        
        # If no charts were generated, try auto-generation
        if not charts:
            logger.info("📊 No charts from LLM, attempting auto-generation")
            charts = _auto_generate_basic_charts(
                rows,
                user_query,
                numeric_cols,
                categorical_cols,
                result_scope=result_scope,
                sql=sql,
            )
        _apply_sql_filter_context(charts, sql)
        _apply_mixed_currency_note(charts, rows, sql)
        return charts
    
    except Exception as e:
        logger.error(f"❌ Chart generation failed: {e}", exc_info=True)
        # Try auto-generation as fallback
        try:
            numeric_cols = _detect_numeric_columns(rows)
            categorical_cols = _detect_categorical_columns(rows)
            charts = _auto_generate_basic_charts(
                rows,
                user_query,
                numeric_cols,
                categorical_cols,
                result_scope=result_scope,
                sql=sql,
            )
            _apply_sql_filter_context(charts, sql)
            _apply_mixed_currency_note(charts, rows, sql)
            return charts
        except Exception:
            return []


def _auto_generate_basic_charts(
    rows: List[Dict[str, Any]],
    user_query: str,
    numeric_cols: List[str],
    categorical_cols: List[str],
    result_scope: Optional[Dict[str, Any]] = None,
    sql: str = "",
) -> List[ChartSpec]:
    """
    Auto-generate basic charts when LLM doesn't provide recommendations.
    Creates sensible default visualizations based on data structure.
    """
    _ = sql  # reserved for future title/context hints from executed SQL
    charts = []
    
    if not numeric_cols or not rows:
        logger.info("📊 Auto-gen: No numeric columns or rows, skipping")
        return []
    
    logger.info(f"📊 Auto-generating charts with {len(numeric_cols)} numeric, {len(categorical_cols)} categorical cols")
    
    formatted_data = _format_chart_data(rows, max_items=30)
    
    # Color scheme
    colors = ["#3b82f6", "#6366f1", "#10b981", "#f59e0b", "#ef4444"]
    
    try:
        # Strategy 1: If we have categorical + numeric, create bar chart
        if len(categorical_cols) >= 1 and len(numeric_cols) >= 1:
            x_key = categorical_cols[0]
            y_key = numeric_cols[0]
            
            charts.append(ChartSpec(
                chart_type="bar",
                title=f"{y_key.replace('_', ' ').title()} by {x_key.replace('_', ' ').title()}" + _scope_suffix(result_scope),
                description="Auto-generated visualization",
                data=formatted_data,
                x_key=x_key,
                y_keys=[y_key],
                colors=colors,
                show_legend=True,
                show_grid=True,
            ))
            logger.info(f"✅ Auto-generated bar chart: {x_key} vs {y_key}")
        
        # Strategy 2: If we have 2+ numeric cols and few rows, try pie chart
        if len(categorical_cols) >= 1 and len(numeric_cols) >= 1 and len(rows) <= 15:
            name_key = categorical_cols[0]
            value_key = numeric_cols[0]
            
            pie_data = []
            for row in formatted_data[:10]:
                if name_key in row and value_key in row:
                    pie_data.append({
                        "name": str(row[name_key]),
                        "value": float(row[value_key]) if isinstance(row[value_key], (int, float)) else 0
                    })
            
            if pie_data:
                charts.append(ChartSpec(
                    chart_type="pie",
                    title=f"{value_key.replace('_', ' ').title()} Distribution" + _scope_suffix(result_scope),
                    description="Auto-generated pie chart",
                    data=pie_data,
                    name_key="name",
                    value_key="value",
                    colors=colors,
                    show_legend=True,
                    show_grid=False,
                ))
                logger.info(f"✅ Auto-generated pie chart: {name_key} distribution")
        
        # Strategy 3: Always add table view for reference
        # Even if no numeric columns, show table
        if len(formatted_data) > 0:
            charts.append(ChartSpec(
                chart_type="table",
                title="Data Table" + _scope_suffix(result_scope),
                description=(
                    "Detailed view of query results"
                    if not result_scope or result_scope.get("kind") != "limited"
                    else f"Detailed view of limited query results ({result_scope.get('row_count_returned')} row(s))."
                ),
                data=formatted_data[:20],  # Limit to 20 rows for display
                show_legend=False,
                show_grid=False,
            ))
            logger.info(f"✅ Auto-generated table with {len(formatted_data[:20])} rows")
    
    except Exception as e:
        logger.error(f"❌ Auto-chart generation failed: {e}")
    
    return charts


def generate_chart_data(
    rows: List[Dict[str, Any]],
    chart_type: str,
    config: Dict[str, Any]
) -> List[Dict[str, Any]]:
    """
    Generate chart-specific data format.
    
    Args:
        rows: Query result rows
        chart_type: Type of chart to generate
        config: Chart configuration from LLM
    
    Returns:
        Formatted data for the specific chart type
    """
    if not rows:
        logger.warning("❌ generate_chart_data: No rows provided")
        return []
    
    try:
        if chart_type == "bar" or chart_type == "line" or chart_type == "area":
            # Format: [{ x_key: "label", y_key1: value1, y_key2: value2 }]
            x_key = config.get("x_key")
            y_keys = config.get("y_keys", [])
            
            logger.info(f"📊 {chart_type} chart config: x_key={x_key}, y_keys={y_keys}")
            
            if not x_key or not y_keys:
                logger.warning(f"❌ Missing x_key or y_keys for {chart_type} chart")
                return []
            
            formatted_data = _format_chart_data(rows, max_items=30)
            
            # Check if keys exist in data
            if not formatted_data:
                logger.warning(f"❌ No formatted data for {chart_type} chart")
                return []
            
            available_keys = list(formatted_data[0].keys())
            logger.info(f"📊 Available keys in data: {available_keys}")
            
            # Case-insensitive key matching
            actual_x_key = _find_matching_key(x_key, available_keys)
            if not actual_x_key:
                logger.warning(f"❌ x_key '{x_key}' not found in data. Available: {available_keys}")
                # Try to use first categorical column as fallback
                categorical_cols = _detect_categorical_columns(formatted_data)
                if categorical_cols:
                    actual_x_key = categorical_cols[0]
                    logger.info(f"📊 Using fallback x_key: {actual_x_key}")
                else:
                    return []
            
            # Verify y_keys exist
            actual_y_keys = []
            for y_key in y_keys:
                actual_y = _find_matching_key(y_key, available_keys)
                if actual_y:
                    actual_y_keys.append(actual_y)
                else:
                    logger.warning(f"❌ y_key '{y_key}' not found in data")
            
            if not actual_y_keys:
                logger.warning(f"❌ No valid y_keys found for {chart_type} chart")
                return []
            
            logger.info(f"✅ Using x_key={actual_x_key}, y_keys={actual_y_keys}")
            
            # Update config with actual keys
            config["x_key"] = actual_x_key
            config["y_keys"] = actual_y_keys

            # Ensure y-axis values are numeric even if the backend sent
            # currency-prefixed strings like "DEM 15.03".
            def _try_float_from_any(v: Any) -> Any:
                if isinstance(v, (int, float)):
                    return float(v)
                if isinstance(v, str):
                    m = re.search(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", v)
                    if m:
                        try:
                            return float(m.group(0))
                        except Exception:
                            return v
                return v

            for row in formatted_data:
                for yk in actual_y_keys:
                    if yk in row:
                        row[yk] = _try_float_from_any(row.get(yk))

            # Line/area charts should be ordered chronologically when the x-axis
            # looks like a date/period. Otherwise the UI "trend" can be misleading.
            if chart_type in {"line", "area"}:
                def _parse_sort_key(x: Any):
                    if x is None:
                        return (0, 0, 0)
                    s = str(x).strip()
                    # YYYY-MM-DD
                    m1 = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", s)
                    if m1:
                        return (1, int(m1.group(1)), int(m1.group(2)) * 100 + int(m1.group(3)))
                    # YYYY-Pxx (SAP period)
                    m2 = re.fullmatch(r"(\d{4})-P(\d{1,2})", s)
                    if m2:
                        return (2, int(m2.group(1)), int(m2.group(2)))
                    # Plain year (e.g. 1999)
                    m3 = re.fullmatch(r"(\d{4})", s)
                    if m3:
                        return (3, int(m3.group(1)), 0)
                    return (99, 0, 0)

                # Only sort if a meaningful fraction of points look date/period-like.
                x_samples = [row.get(actual_x_key) for row in formatted_data[:min(30, len(formatted_data))]]
                date_like = sum(1 for xv in x_samples if isinstance(xv, str) and re.match(r"^\d{4}-", xv)) >= 5
                if date_like:
                    formatted_data = sorted(formatted_data, key=lambda r: _parse_sort_key(r.get(actual_x_key)))

            return formatted_data
        
        elif chart_type == "pie":
            # Format: [{ name: "label", value: number }]
            name_key = config.get("name_key")
            value_key = config.get("value_key")
            
            logger.info(f"📊 Pie chart config: name_key={name_key}, value_key={value_key}")
            
            if not name_key or not value_key:
                logger.warning(f"❌ Missing name_key or value_key for pie chart")
                return []
            
            # Limit pie chart to top 10 segments
            limited_rows = rows[:10]
            
            if not limited_rows:
                logger.warning(f"❌ No rows for pie chart")
                return []
            
            available_keys = list(limited_rows[0].keys())
            logger.info(f"📊 Available keys for pie: {available_keys}")
            
            # Find matching keys
            actual_name_key = _find_matching_key(name_key, available_keys)
            actual_value_key = _find_matching_key(value_key, available_keys)
            
            if not actual_name_key or not actual_value_key:
                logger.warning(f"❌ Could not match pie keys. name_key='{name_key}' -> {actual_name_key}, value_key='{value_key}' -> {actual_value_key}")
                return []
            
            logger.info(f"✅ Using name_key={actual_name_key}, value_key={actual_value_key}")
            
            # Build pie data - ALWAYS uses "name" and "value" keys
            pie_data = []
            for row in limited_rows:
                if actual_name_key in row and actual_value_key in row:
                    pie_data.append({
                        "name": str(row[actual_name_key]),
                        "value": float(row[actual_value_key]) if row[actual_value_key] is not None else 0
                    })
            
            # CRITICAL: Update config to reflect the ACTUAL keys in pie_data
            # Since we transform to {"name": ..., "value": ...}, these are the keys
            config["name_key"] = "name"
            config["value_key"] = "value"
            
            logger.info(f"✅ Generated {len(pie_data)} pie chart segments")
            return pie_data
        
        elif chart_type == "table":
            # Return formatted rows as-is
            return _format_chart_data(rows, max_items=100)
        
        return []
    
    except Exception as e:
        logger.error(f"Failed to generate {chart_type} chart data: {e}")
        return []


def chart_specs_to_json(charts: List[ChartSpec]) -> List[Dict[str, Any]]:
    """Convert ChartSpec objects to JSON-serializable dictionaries."""
    return [asdict(chart) for chart in charts]
