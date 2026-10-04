import logging
from typing import Any, Dict, List

logger = logging.getLogger("zodiac-api.visualization_recommender")

class VisualizationRecommender:
    """
    Phase 5: Dynamic Visualization Engine
    Recommends chart grammar based on result dataset shape, cardinality, and types.
    """
    
    def recommend(self, rows: List[Dict[str, Any]], intent_context: Any = None) -> List[Dict[str, Any]]:
        """
        Analyze rows and return a list of recommended chart specs.
        """
        if not rows:
            return []
            
        columns = list(rows[0].keys())
        
        numeric_cols = []
        string_cols = []
        date_cols = []
        
        for col in columns:
            val = rows[0][col]
            if isinstance(val, (int, float)):
                numeric_cols.append(col)
            elif "date" in col.lower() or "time" in col.lower():
                date_cols.append(col)
            else:
                string_cols.append(col)
                
        recommendations = []
        
        # Trend / Time series
        if date_cols and numeric_cols:
            recommendations.append({
                "type": "line",
                "x_axis": date_cols[0],
                "y_axis": numeric_cols[0],
                "confidence": 0.9,
                "title": f"Trend of {numeric_cols[0]} over {date_cols[0]}"
            })
            
        # Bar chart for categorical distributions
        if string_cols and numeric_cols and len(rows) <= 50:
            recommendations.append({
                "type": "bar",
                "x_axis": string_cols[0],
                "y_axis": numeric_cols[0],
                "confidence": 0.85,
                "title": f"{numeric_cols[0]} by {string_cols[0]}"
            })
            
        # KPI Card for single numeric value or aggregated sum
        if numeric_cols and len(rows) == 1:
            recommendations.append({
                "type": "kpi",
                "value_field": numeric_cols[0],
                "confidence": 0.95,
                "title": f"Total {numeric_cols[0]}"
            })
            
        # Fallback table
        recommendations.append({
            "type": "table",
            "columns": columns,
            "confidence": 1.0,
            "title": "Data Table"
        })
        
        # Sort by confidence
        recommendations.sort(key=lambda x: x["confidence"], reverse=True)
        return recommendations

viz_recommender = VisualizationRecommender()
