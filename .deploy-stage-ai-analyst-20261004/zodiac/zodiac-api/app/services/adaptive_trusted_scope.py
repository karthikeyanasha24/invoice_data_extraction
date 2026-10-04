"""Trusted execution scope for Adaptive AI Analyst SQL.

Isolation rules (application-enforced, independent of the LLM):

1. App Postgres tables that carry user_id are ALWAYS constrained to the
   authenticated user. LLM- or client-supplied user_id predicates are stripped
   and replaced with a bound trusted parameter.

2. SAP extract queries use the process-configured SAP_DATABASE_URL session.
   The LLM cannot select another DSN/tenant connection. No textual mandt
   injection is added (shared-extract deployments are one customer extract per
   deployment). Cross-customer SAP isolation is therefore connection/config
   binding, not prompt obedience.

3. Destructive / multi-statement SQL remains blocked by existing validators.
"""
from __future__ import annotations

import contextvars
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

USER_SCOPED_TABLES = frozenset(
    {
        "sat_documents",
        "sat_duplicate_checks",
        "sat_processing_logs",
        "invoice_v2_business_data",
        "v2_invoice_documents",
        "zodiac_invoice_failed_edi",
        "zodiac_invoice_success_edi",
        "ai_analysis_memory",
        "ai_chat_threads",
    }
)

_current_scope: contextvars.ContextVar[Optional["TrustedAiExecutionScope"]] = contextvars.ContextVar(
    "adaptive_trusted_scope", default=None
)

_FROM_JOIN_TABLE = re.compile(
    r'\b(?:FROM|JOIN)\s+"?([A-Za-z_][A-Za-z0-9_]*)"?',
    re.IGNORECASE,
)
_USER_ID_PRED = re.compile(
    r"""(?ix)
    (?:AND|WHERE)?\s*
    "?[A-Za-z_][A-Za-z0-9_]*"?\."?user_id"?\s*(?:=|<>|!=|IN)\s*
    (?:
        \d+
        |'[^']*'
        |:[A-Za-z_][A-Za-z0-9_]*
        |\([^)]*\)
    )
    """,
)
_BARE_USER_ID_PRED = re.compile(
    r"""(?ix)
    (?:AND|WHERE)?\s*
    "?user_id"?\s*(?:=|<>|!=|IN)\s*
    (?:
        \d+
        |'[^']*'
        |:[A-Za-z_][A-Za-z0-9_]*
        |\([^)]*\)
    )
    """,
)


@dataclass
class TrustedAiExecutionScope:
    """Trusted identity for adaptive SQL — never taken from model output."""

    user_id: int
    allowed_customer_ids: List[str] = field(default_factory=list)
    sap_connection_bound: bool = True

    def to_public_dict(self) -> Dict[str, Any]:
        return {
            "user_id": int(self.user_id),
            "allowed_customer_count": len(self.allowed_customer_ids),
            "sap_connection_bound": bool(self.sap_connection_bound),
            "user_scoped_tables": sorted(USER_SCOPED_TABLES),
        }


def set_trusted_scope(scope: Optional[TrustedAiExecutionScope]):
    return _current_scope.set(scope)


def reset_trusted_scope(token) -> None:
    _current_scope.reset(token)


def get_trusted_scope() -> Optional[TrustedAiExecutionScope]:
    return _current_scope.get()


def referenced_tables(sql: str) -> List[str]:
    return [m.group(1) for m in _FROM_JOIN_TABLE.finditer(sql or "")]


def touches_user_scoped_table(sql: str) -> bool:
    return any(t.lower() in USER_SCOPED_TABLES for t in referenced_tables(sql))


def _strip_user_id_predicates(sql: str) -> str:
    out = sql or ""
    out = _USER_ID_PRED.sub(" ", out)
    out = _BARE_USER_ID_PRED.sub(" ", out)
    out = re.sub(r"\bWHERE\s+(AND|OR)\b", "WHERE ", out, flags=re.I)
    out = re.sub(r"\b(AND|OR)\s+(AND|OR)\b", r"\1", out, flags=re.I)
    out = re.sub(r"\s+", " ", out).strip()
    return out


def enforce_trusted_user_scope(
    sql: str,
    scope: Optional[TrustedAiExecutionScope] = None,
) -> Tuple[str, Dict[str, Any]]:
    """Return (sql, bind_params) with trusted user_id for user-scoped app tables."""
    scope = scope if scope is not None else get_trusted_scope()
    params: Dict[str, Any] = {}
    raw = (sql or "").strip()
    if not raw:
        return raw, params
    if not touches_user_scoped_table(raw):
        return raw, params
    if scope is None or int(scope.user_id or 0) <= 0:
        raise PermissionError(
            "DENIED: user-scoped table query requires authenticated trusted scope"
        )

    cleaned = _strip_user_id_predicates(raw)
    alias = None
    for m in re.finditer(
        r'\b(?:FROM|JOIN)\s+"?([A-Za-z_][A-Za-z0-9_]*)"?\s+(?:AS\s+)?([A-Za-z_][A-Za-z0-9_]*)?',
        cleaned,
        flags=re.I,
    ):
        table, maybe_alias = m.group(1), m.group(2)
        if table.lower() in USER_SCOPED_TABLES:
            if maybe_alias and maybe_alias.upper() not in {
                "WHERE",
                "JOIN",
                "LEFT",
                "RIGHT",
                "INNER",
                "OUTER",
                "ON",
                "GROUP",
                "ORDER",
                "LIMIT",
                "UNION",
            }:
                alias = maybe_alias
            break

    col = f"{alias}.user_id" if alias else "user_id"
    pred = f"{col} = :_trusted_user_id"
    params["_trusted_user_id"] = int(scope.user_id)

    if re.search(r"\bWHERE\b", cleaned, flags=re.I):
        cleaned = re.sub(
            r"\bWHERE\b",
            f"WHERE {pred} AND ",
            cleaned,
            count=1,
            flags=re.I,
        )
    else:
        m = re.search(r"\b(GROUP\s+BY|ORDER\s+BY|LIMIT|OFFSET|FETCH)\b", cleaned, flags=re.I)
        if m:
            i = m.start()
            cleaned = cleaned[:i].rstrip() + f" WHERE {pred} " + cleaned[i:]
        else:
            cleaned = cleaned.rstrip(" ;") + f" WHERE {pred}"

    return cleaned, params


def classify_cross_user_attempt(sql: str, scope: TrustedAiExecutionScope) -> Optional[str]:
    if not touches_user_scoped_table(sql):
        return None
    m = re.search(r"\buser_id\b\s*=\s*(\d+|'[^']+')", sql or "", flags=re.I)
    if not m:
        if re.search(r"\buser_id\b\s*(?:<>|!=|NOT\s+IN|\bIN\b)", sql or "", flags=re.I):
            return "cross_user_predicate_rewritten"
        return None
    raw = m.group(1).strip("'")
    try:
        requested = int(raw)
    except ValueError:
        return "cross_user_predicate_rewritten"
    if requested != int(scope.user_id):
        return "cross_user_predicate_rewritten"
    return None
