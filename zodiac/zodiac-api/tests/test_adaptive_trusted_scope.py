"""Trusted adaptive SQL scope — user-scoped tables cannot cross users."""
from __future__ import annotations

import pytest

from app.services.adaptive_trusted_scope import (
    TrustedAiExecutionScope,
    classify_cross_user_attempt,
    enforce_trusted_user_scope,
    reset_trusted_scope,
    set_trusted_scope,
    touches_user_scoped_table,
)


def test_sap_sql_unchanged_by_user_scope():
    sql = 'SELECT SUM(CAST(NULLIF(TRIM(CAST("VBRK"."netwr" AS TEXT)), \'\') AS NUMERIC)) AS total FROM "VBRK"'
    scope = TrustedAiExecutionScope(user_id=42)
    out, params = enforce_trusted_user_scope(sql, scope)
    assert out == sql
    assert params == {}
    assert not touches_user_scoped_table(sql)


def test_sat_documents_injects_trusted_user_id_and_strips_foreign():
    sql = (
        "SELECT id, user_id, supplier_name, total FROM sat_documents "
        "WHERE user_id <> 0 ORDER BY id DESC LIMIT 5"
    )
    scope = TrustedAiExecutionScope(user_id=42)
    out, params = enforce_trusted_user_scope(sql, scope)
    assert params["_trusted_user_id"] == 42
    assert "user_id = :_trusted_user_id" in out.replace(" ", " ")
    assert "user_id <> 0" not in out
    assert classify_cross_user_attempt(sql, scope) == "cross_user_predicate_rewritten"


def test_user_scoped_without_scope_is_denied():
    sql = "SELECT id FROM sat_documents LIMIT 5"
    with pytest.raises(PermissionError):
        enforce_trusted_user_scope(sql, None)


def test_contextvar_scope_used_by_default():
    sql = "SELECT id FROM sat_documents LIMIT 1"
    token = set_trusted_scope(TrustedAiExecutionScope(user_id=7))
    try:
        out, params = enforce_trusted_user_scope(sql)
        assert params["_trusted_user_id"] == 7
        assert "user_id = :_trusted_user_id" in out
    finally:
        reset_trusted_scope(token)


def test_destructive_still_not_select_only_here():
    # Scope module does not authorize writes; SELECT-only is enforced elsewhere.
    sql = "SELECT id FROM sat_documents"
    out, params = enforce_trusted_user_scope(sql, TrustedAiExecutionScope(user_id=1))
    assert params["_trusted_user_id"] == 1
    assert "WHERE" in out.upper()
