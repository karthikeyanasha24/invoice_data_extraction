"""Rule-based recommendations from operational analytics (Phase 9)."""
from __future__ import annotations

from typing import Any, Dict, List


class RecommendationEngine:
    """
    Generates advisory recommendations from analytics facts.

    Never mutates pipeline state; recommendations are read-only guidance.
    """

    def generate(self, analytics: Dict[str, Any]) -> List[Dict[str, Any]]:
        recs: List[Dict[str, Any]] = []
        counts = analytics.get("summary_counts") or {}
        failed = int(counts.get("failed") or 0)
        completed = int(counts.get("completed") or 0)
        retry = analytics.get("retry_statistics") or {}
        success = analytics.get("success_rate_percent")
        avg = analytics.get("average_processing_time_ms")
        failures_today = analytics.get("failures_today") or []
        gov = analytics.get("government_outages") or []
        erp = (analytics.get("erp_delays") or {}).get("failed_transactions") or []
        erp_alerts = (analytics.get("erp_delays") or {}).get("alerts") or []
        validation = analytics.get("top_validation_failures") or []
        high_latency = analytics.get("high_latency_alerts") or []

        if failures_today:
            recs.append(
                {
                    "priority": "high",
                    "code": "REVIEW_FAILURES_TODAY",
                    "title": "Investigate today's pipeline failures",
                    "detail": f"{len(failures_today)} failed transaction(s) recorded today.",
                    "actions": [
                        "Open workspace Monitoring → Latest transactions",
                        "Inspect failed_stage and failure_reason on each correlation_id",
                    ],
                }
            )

        if gov:
            recs.append(
                {
                    "priority": "critical",
                    "code": "GOVERNMENT_HEALTH",
                    "title": "Government connector instability detected",
                    "detail": f"{len(gov)} government_unavailable alert(s) in recent history.",
                    "actions": [
                        "Check Government Connector health for this workspace",
                        "Verify endpoint_url_ref and auth configuration",
                        "Pause non-critical submissions if outage is confirmed",
                    ],
                }
            )

        if erp or erp_alerts:
            recs.append(
                {
                    "priority": "high",
                    "code": "ERP_LATENCY_OR_FAILURE",
                    "title": "ERP update delays or failures",
                    "detail": (
                        f"{len(erp)} ERP-related failed transaction(s); "
                        f"{len(erp_alerts)} ERP alert(s)."
                    ),
                    "actions": [
                        "Verify workspace ERP connection and callback URL",
                        "Inspect erp_push_outbox for stuck pushes",
                        "Confirm ERP credentials refs resolve in the runtime environment",
                    ],
                }
            )

        if int(retry.get("total_retries") or 0) >= 5 or int(
            retry.get("transactions_with_retries") or 0
        ) >= 3:
            recs.append(
                {
                    "priority": "medium",
                    "code": "ELEVATED_RETRIES",
                    "title": "Elevated retry activity",
                    "detail": (
                        f"total_retries={retry.get('total_retries')}, "
                        f"transactions_with_retries={retry.get('transactions_with_retries')}."
                    ),
                    "actions": [
                        "Review transport retry alerts",
                        "Correlate retries with government/ERP unavailable windows",
                    ],
                }
            )

        if success is not None and success < 90.0 and (completed + failed) >= 5:
            recs.append(
                {
                    "priority": "high",
                    "code": "LOW_SUCCESS_RATE",
                    "title": "Success rate below 90%",
                    "detail": f"Current success rate is {success:.1f}%.",
                    "actions": [
                        "Triage top_errors in monitoring summary",
                        "Validate country adapter rules version for this workspace",
                    ],
                }
            )

        if avg is not None and avg >= 60_000:
            recs.append(
                {
                    "priority": "medium",
                    "code": "HIGH_AVERAGE_LATENCY",
                    "title": "Average processing time is high",
                    "detail": f"Average latency ≈ {avg:.0f} ms.",
                    "actions": [
                        "Inspect high_latency alerts",
                        "Check government/ERP response times via monitoring",
                    ],
                }
            )
        elif high_latency:
            recs.append(
                {
                    "priority": "medium",
                    "code": "HIGH_LATENCY_ALERTS",
                    "title": "High latency alerts present",
                    "detail": f"{len(high_latency)} high_latency alert(s).",
                    "actions": ["Review correlation_ids on high_latency alerts"],
                }
            )

        if validation:
            top = validation[0]
            recs.append(
                {
                    "priority": "medium",
                    "code": "VALIDATION_HOTSPOT",
                    "title": "Validation failures concentrated",
                    "detail": f"Top validation issue: {top.get('key')} ({top.get('count')}).",
                    "actions": [
                        "Review inbound document quality for this workspace",
                        "Confirm mapping/rules_version on workspace adapter config",
                    ],
                }
            )

        if not recs:
            recs.append(
                {
                    "priority": "info",
                    "code": "HEALTHY",
                    "title": "No critical operational issues detected",
                    "detail": "Recent monitoring facts look stable for this workspace.",
                    "actions": ["Continue monitoring success rate and latency trends"],
                }
            )

        return recs
