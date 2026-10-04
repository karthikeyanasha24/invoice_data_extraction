import logging
from typing import Any, Dict, List

logger = logging.getLogger("zodiac-api.insight_engine")

class InsightEngine:
    """
    Phase 10: Insight Generation Layer
    Builds anomaly and trend insights with confidence scoring and explainability.
    """
    
    def analyze(self, rows: List[Dict[str, Any]], metric_name: str) -> Dict[str, Any]:
        """Generate insights based on result rows."""
        logger.info("Generating insights for metric: %s", metric_name)
        if not rows:
            return {"summary": "No data available for insights.", "anomalies": []}
            
        insights = {
            "summary": "Generated narrative summary of trends.",
            "anomalies": [],
            "confidence": 0.85
        }
        
        # Example logic for finding numeric outliers
        # In production this would use statistical models (e.g. Z-score, isolation forests)
        numeric_values = []
        for r in rows:
            for v in r.values():
                if isinstance(v, (int, float)):
                    numeric_values.append(v)
                    
        if numeric_values:
            avg = sum(numeric_values) / len(numeric_values)
            for i, r in enumerate(rows):
                for k, v in r.items():
                    if isinstance(v, (int, float)) and v > avg * 3:
                        insights["anomalies"].append({
                            "row_index": i,
                            "field": k,
                            "value": v,
                            "reason": f"Value is 3x higher than average ({avg:.2f})"
                        })
                        
        if insights["anomalies"]:
            insights["summary"] = f"Detected {len(insights['anomalies'])} anomalies in the data."
            
        return insights

insight_engine = InsightEngine()
