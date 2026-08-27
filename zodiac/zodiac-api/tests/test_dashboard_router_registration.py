"""Dashboard router must import and register /api/v1/dashboard/* paths."""
from __future__ import annotations

from pathlib import Path


DASHBOARD_FILE = Path(__file__).resolve().parents[1] / "app" / "api" / "dashboard.py"

EXPECTED_SUFFIXES = [
    "/statistics",
    "/v2/inbound",
    "/v2/inbound/recent",
    "/v2/outbound",
    "/v2/business",
    "/v2/customer-comparison",
    "/v2/failed-invoices-analysis",
    "/ai-analysis/chat",
    "/ai-analysis/schema",
]


def test_dashboard_does_not_import_sap_sql_agent_at_module_level():
    src = DASHBOARD_FILE.read_text(encoding="utf-8")
    head = "\n".join(src.splitlines()[:45])
    assert "from ..services.sap_sql_agent import" not in head
    assert "answer_with_sap_sql_agent" not in src


def test_dashboard_module_imports_and_exposes_v2_routes():
    from app.api import dashboard

    assert dashboard.router is not None
    paths = []
    for route in dashboard.router.routes:
        path = getattr(route, "path", "") or ""
        paths.append(path)
    joined = " ".join(paths)
    for suffix in EXPECTED_SUFFIXES:
        assert suffix in joined, f"missing dashboard route suffix {suffix} in {sorted(paths)}"


def test_server_registers_dashboard_in_openapi():
    from app.server import ROUTER_STATUS, app

    assert ROUTER_STATUS.get("dashboard", {}).get("loaded") is True, ROUTER_STATUS.get("dashboard")
    spec = app.openapi()
    paths = spec.get("paths") or {}
    dash = [p for p in paths if p.startswith("/api/v1/dashboard")]
    assert dash, "OpenAPI has no /api/v1/dashboard/* paths"
    assert "/api/v1/dashboard/v2/inbound" in paths
    assert "/api/v1/dashboard/v2/inbound/recent" in paths
    assert "/api/v1/dashboard/v2/outbound" in paths
    assert "/api/v1/dashboard/v2/business" in paths


def test_health_routers_endpoint_exists():
    from fastapi.testclient import TestClient
    from app.server import app

    client = TestClient(app)
    resp = client.get("/health/routers")
    assert resp.status_code == 200
    body = resp.json()
    assert "routers" in body
    assert body["routers"]["dashboard"]["loaded"] is True
    assert "password" not in resp.text.lower()
    assert "secret_key" not in resp.text.lower()


def test_dashboard_inbound_requires_auth():
    from unittest.mock import MagicMock
    from fastapi.testclient import TestClient
    from app.database import get_db
    from app.server import app

    def override_db():
        yield MagicMock()

    app.dependency_overrides[get_db] = override_db
    try:
        client = TestClient(app)
        resp = client.get("/api/v1/dashboard/v2/inbound?days=0")
        assert resp.status_code in (401, 403), resp.text
        assert "sql" not in resp.text.lower()
    finally:
        app.dependency_overrides.pop(get_db, None)
