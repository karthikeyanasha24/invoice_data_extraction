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


def _format_chart_data(rows: List[Dict[str, Any]], max_items: int = 50) -> List[Dict[str, Any]]:
    """Format and limit data for chart rendering."""
    if not rows:
        return []
    
    # Limit number of data points for readability
    limited_rows = rows[:max_items]
    
    # Clean up data: convert None to 0, format numbers
    formatted = []
    for row in limited_rows:
        clean_row = {}
        for key, value in row.items():
            if value is None:
                clean_row[key] = 0
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
    sql: str = ""
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
            return _auto_generate_basic_charts(rows, user_query, [], categorical_cols)
        except Exception as e:
            logger.error(f"❌ Table generation failed: {e}")
            return []
    
    # Use LLM to recommend chart types and structure
    try:
        client = _get_client()
        
        sample_rows = rows[:5]
        prompt = f"""
You are a data visualization expert. Analyze this query result and recommend the best chart(s).

User question: "{user_query}"

SQL query: {sql[:500] if sql else "N/A"}

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
"""
        
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
            
            charts.append(chart_spec)
            logger.info(f"✅ Created chart spec: {chart_spec.title} (type={chart_type}, data_points={len(chart_data)})")
        
        # If no charts were generated, try auto-generation
        if not charts:
            logger.info("📊 No charts from LLM, attempting auto-generation")
            charts = _auto_generate_basic_charts(rows, user_query, numeric_cols, categorical_cols)
        
        return charts
    
    except Exception as e:
        logger.error(f"❌ Chart generation failed: {e}", exc_info=True)
        # Try auto-generation as fallback
        try:
            numeric_cols = _detect_numeric_columns(rows)
            categorical_cols = _detect_categorical_columns(rows)
            return _auto_generate_basic_charts(rows, user_query, numeric_cols, categorical_cols)
        except:
            return []


def _auto_generate_basic_charts(
    rows: List[Dict[str, Any]],
    user_query: str,
    numeric_cols: List[str],
    categorical_cols: List[str]
) -> List[ChartSpec]:
    """
    Auto-generate basic charts when LLM doesn't provide recommendations.
    Creates sensible default visualizations based on data structure.
    """
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
                title=f"{y_key.replace('_', ' ').title()} by {x_key.replace('_', ' ').title()}",
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
                    title=f"{value_key.replace('_', ' ').title()} Distribution",
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
                title="Data Table",
                description="Detailed view of query results",
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
