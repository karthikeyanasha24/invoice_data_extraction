"""Schema Explorer must still return tables when PK/FK reflection fails."""
from __future__ import annotations

from unittest.mock import MagicMock

import sqlalchemy


def test_basic_training_schema_returns_tables_when_pk_fk_reflection_fails(monkeypatch):
    from app.api import adaptive_query as aq

    schema = {
        "KNA1": [{"col": "mandt", "type": "text"}, {"col": "kunnr", "type": "text"}, {"col": "brsch", "type": "text"}],
        "T016T": [{"col": "brsch", "type": "text"}, {"col": "brtxt", "type": "text"}, {"col": "spras", "type": "text"}],
        "VBRK": [{"col": "mandt", "type": "text"}, {"col": "vbeln", "type": "text"}],
    }

    class FakeTools:
        def __init__(self, *args, **kwargs):
            pass

        def schema(self, source):
            assert source == "business"
            return schema, "live_database_metadata"

        def session(self, source):
            session = MagicMock()
            session.get_bind.return_value = MagicMock()
            return session

        def close(self):
            return None

    monkeypatch.setattr("app.services.analyst_agent.AnalystTools", FakeTools)
    monkeypatch.setattr(aq, "_basic_training_scope", lambda db, user: object())
    monkeypatch.setattr("app.services.adaptive_trusted_scope.reset_trusted_scope", lambda token: None)
    monkeypatch.setattr(aq, "USE_SAP_DB_FOR_AI", True)
    monkeypatch.setattr(aq, "_resolve_basic_training_source", lambda source: "business")
    monkeypatch.setattr(
        sqlalchemy,
        "inspect",
        lambda bind: MagicMock(
            get_multi_pk_constraint=MagicMock(side_effect=RuntimeError("catalog timeout")),
            get_multi_foreign_keys=MagicMock(side_effect=RuntimeError("catalog timeout")),
        ),
    )

    response = aq.basic_training_schema_endpoint(source="business", db=MagicMock(), current_user=MagicMock())
    tables = {item["table"]: item for item in response["tables"]}
    assert set(tables) >= {"KNA1", "T016T", "VBRK"}
    kna1_rels = tables["KNA1"]["relationships"]
    assert any(
        rel.get("references_table") == "T016T"
        and "brsch" in [str(c).lower() for c in (rel.get("columns") or [])]
        for rel in kna1_rels
    ), kna1_rels
