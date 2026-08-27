"""Adaptive query must require JWT and must not execute analytical SQL without it."""
from __future__ import annotations

import inspect
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi import FastAPI, Depends
from fastapi.testclient import TestClient

from app.api.auth import create_access_token, get_current_user
from app.database import get_db
from app.models.user import ZodiacUser


def _fake_db():
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = None
    yield db


def _mini_app() -> FastAPI:
    app = FastAPI()
    sap_calls = {"n": 0}

    def _db():
        yield from _fake_db()

    @app.post("/api/query/adaptive")
    async def adaptive(user: ZodiacUser = Depends(get_current_user)):
        sap_calls["n"] += 1
        return {"ok": True, "user_id": int(user.id)}

    app.dependency_overrides[get_db] = _db
    app.state.sap_calls = sap_calls
    return app


def _post(client: TestClient, headers=None, body=None):
    return client.post("/api/query/adaptive", json=body or {"question": "Show inventory."}, headers=headers or {})


def _assert_unauthorized(resp, sap_calls=None):
    assert resp.status_code in (401, 403), resp.text
    body = resp.json()
    detail = str(body.get("detail") or body)
    leaked = ("sql" in body and body.get("sql")) or "traceback" in resp.text.lower() or "mbew" in resp.text.lower()
    assert not leaked, resp.text
    assert "password" not in resp.text.lower()
    assert "secret" not in detail.lower()
    if sap_calls is not None:
        assert sap_calls["n"] == 0


def test_adaptive_handler_requires_get_current_user_not_optional():
    from app.api.adaptive_query import post_query_adaptive, get_adaptive_chat_history

    post_src = inspect.getsource(post_query_adaptive)
    hist_src = inspect.getsource(get_adaptive_chat_history)
    assert "get_current_user_optional" not in post_src
    assert "get_current_user_optional" not in hist_src
    assert "Depends(get_current_user)" in post_src
    assert "Depends(get_current_user)" in hist_src


def test_adaptive_without_jwt():
    app = _mini_app()
    client = TestClient(app)
    _assert_unauthorized(_post(client), app.state.sap_calls)


def test_adaptive_missing_authorization_header():
    app = _mini_app()
    client = TestClient(app)
    _assert_unauthorized(client.post("/api/query/adaptive", json={"question": "Show inventory."}), app.state.sap_calls)


def test_adaptive_malformed_authorization_header():
    app = _mini_app()
    client = TestClient(app)
    _assert_unauthorized(_post(client, headers={"Authorization": "Token abc"}), app.state.sap_calls)


def test_adaptive_wrong_bearer_format():
    app = _mini_app()
    client = TestClient(app)
    _assert_unauthorized(_post(client, headers={"Authorization": "Bearer"}), app.state.sap_calls)


def test_adaptive_empty_bearer_token():
    app = _mini_app()
    client = TestClient(app)
    _assert_unauthorized(_post(client, headers={"Authorization": "Bearer "}), app.state.sap_calls)


def test_adaptive_invalid_jwt():
    app = _mini_app()
    client = TestClient(app)
    _assert_unauthorized(_post(client, headers={"Authorization": "Bearer not-a-real-token"}), app.state.sap_calls)


def test_adaptive_malformed_jwt():
    app = _mini_app()
    client = TestClient(app)
    _assert_unauthorized(_post(client, headers={"Authorization": "Bearer aaa.bbb.ccc"}), app.state.sap_calls)


def test_adaptive_expired_jwt():
    app = _mini_app()
    client = TestClient(app)
    token = create_access_token({"sub": "1"}, expires_delta=timedelta(seconds=-30))
    _assert_unauthorized(_post(client, headers={"Authorization": f"Bearer {token}"}), app.state.sap_calls)


def test_adaptive_valid_jwt():
    user = SimpleNamespace(id=42, email="qa@example.com", username="qa")

    def _db():
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = user
        yield db

    app = FastAPI()

    @app.post("/api/query/adaptive")
    async def adaptive(current: ZodiacUser = Depends(get_current_user)):
        return {"ok": True, "user_id": int(current.id)}

    app.dependency_overrides[get_db] = _db
    token = create_access_token({"sub": "42"}, expires_delta=timedelta(minutes=5))
    client = TestClient(app)
    resp = _post(client, headers={"Authorization": f"Bearer {token}"}, body={"question": "x"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["user_id"] == 42


def test_adaptive_real_endpoint_rejects_before_sap_sql():
    """Full app: unauthenticated POST must 401/403 and never call get_sap_session."""
    from app.server import app

    def override_db():
        yield from _fake_db()

    app.dependency_overrides[get_db] = override_db
    try:
        with patch("app.api.adaptive_query.get_sap_session") as mock_sap:
            client = TestClient(app)
            resp = client.post("/api/query/adaptive", json={"question": "Show inventory."})
            _assert_unauthorized(resp)
            mock_sap.assert_not_called()
            body = resp.json()
            assert not body.get("sql")
            assert not body.get("data")
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_adaptive_real_endpoint_valid_user_empty_question_does_not_run_sql():
    """Auth succeeds; validation 400 happens before analytical SQL."""
    from app.server import app
    from app.api.auth import get_current_user as real_get_current_user

    fake_user = SimpleNamespace(id=7, email="qa@example.com", username="qa")

    def override_db():
        yield from _fake_db()

    app.dependency_overrides[real_get_current_user] = lambda: fake_user
    app.dependency_overrides[get_db] = override_db
    try:
        with patch("app.api.adaptive_query.get_sap_session") as mock_sap:
            client = TestClient(app)
            resp = client.post("/api/query/adaptive", json={"question": "   "})
            assert resp.status_code == 400, resp.text
            mock_sap.assert_not_called()
    finally:
        app.dependency_overrides.pop(real_get_current_user, None)
        app.dependency_overrides.pop(get_db, None)
