"""
PR1 — Prevent duplicate ERP communication when adapter submit already wrote ERP.

No country branching in the updater: skip is driven by confirmation/metadata flags.
"""
from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.core.erp.hooks import (
    ERP_FULFILLED_IN_SUBMIT,
    WorkspaceErpUpdater,
)
from app.core.erp.models import CanonicalConfirmation, DocumentStatus, ErpPushResult


def _execution(*, flags=None, confirmation=None, metadata=None, ctx_meta=None):
    workspace = SimpleNamespace(
        customer_id="acme",
        flags=flags or {},
        erps=[
            SimpleNamespace(
                connection_key="primary",
                is_active=True,
                callback_url="https://erp.example/callback",
                base_url=None,
                auth_type="none",
                client_id_ref=None,
                client_secret_ref=None,
                extra_config={},
            )
        ],
        erp=None,
    )
    request = SimpleNamespace(db=None, metadata=dict(metadata or {}))
    adapter_ctx = SimpleNamespace(metadata=dict(ctx_meta or {}))
    return SimpleNamespace(
        workspace=workspace,
        request=request,
        customer_id="acme",
        correlation_id="corr-1",
        country_code="MX",
        adapter_ctx=adapter_ctx,
        _confirmation=confirmation,
    )


class TestErpSkipPolicy(unittest.TestCase):
    def test_skips_when_fulfilled_and_auto_mode(self):
        connector = MagicMock()
        updater = WorkspaceErpUpdater(connector=connector)
        execution = _execution(
            confirmation={
                "accepted": True,
                "document_number": "DOC-1",
                ERP_FULFILLED_IN_SUBMIT: True,
            }
        )
        with self.assertRaises(NotImplementedError) as ctx:
            updater.update(execution, execution._confirmation)
        self.assertIn("already fulfilled", str(ctx.exception).lower())
        connector.push_confirmation.assert_not_called()

    def test_always_mode_still_pushes(self):
        connector = MagicMock()
        connector.db = None
        connector.memory_store = None
        connector.push_confirmation.return_value = ErpPushResult(
            success=True,
            status=DocumentStatus.ERP_ACKNOWLEDGED,
            idempotency_key="k",
        )
        updater = WorkspaceErpUpdater(connector=connector)
        execution = _execution(
            flags={"erp_update_mode": "always"},
            confirmation={
                "accepted": True,
                "document_number": "DOC-1",
                ERP_FULFILLED_IN_SUBMIT: True,
            },
        )
        result = updater.update(execution, execution._confirmation)
        self.assertTrue(result.get("success"))
        connector.push_confirmation.assert_called_once()

    def test_never_mode_skips_even_without_flag(self):
        connector = MagicMock()
        updater = WorkspaceErpUpdater(connector=connector)
        execution = _execution(
            flags={"erp_update_mode": "never"},
            confirmation={"accepted": True, "document_number": "DOC-1"},
        )
        with self.assertRaises(NotImplementedError):
            updater.update(execution, execution._confirmation)
        connector.push_confirmation.assert_not_called()

    def test_government_first_without_flag_still_pushes(self):
        """Sample GST-style confirmation has no erp_fulfilled_in_submit."""
        connector = MagicMock()
        connector.db = None
        connector.memory_store = None
        connector.push_confirmation.return_value = ErpPushResult(
            success=True,
            status=DocumentStatus.ERP_ACKNOWLEDGED,
            idempotency_key="k",
        )
        updater = WorkspaceErpUpdater(connector=connector)
        execution = _execution(
            confirmation={"accepted": True, "ack_number": "SAMPLE-ACK-1"},
        )
        # Pretend country is something else — updater must not care.
        execution.country_code = "IN"
        result = updater.update(execution, execution._confirmation)
        self.assertTrue(result.get("success"))
        connector.push_confirmation.assert_called_once()

    def test_metadata_flag_on_adapter_ctx(self):
        connector = MagicMock()
        updater = WorkspaceErpUpdater(connector=connector)
        execution = _execution(
            confirmation={"accepted": True, "document_number": "DOC-1"},
            ctx_meta={ERP_FULFILLED_IN_SUBMIT: True},
        )
        with self.assertRaises(NotImplementedError):
            updater.update(execution, execution._confirmation)
        connector.push_confirmation.assert_not_called()


class TestMxConfirmationMarksFulfilled(unittest.TestCase):
    def test_receive_confirmation_sets_flag_on_success(self):
        from app.adapters.base import AdapterContext, AdapterStage
        from app.adapters.mx_cfdi.adapter import MxCfdiAdapter

        adapter = MxCfdiAdapter()
        ctx = AdapterContext(
            customer_id="acme",
            country_code="MX",
            payload={},
            correlation_id="c1",
            metadata={ERP_FULFILLED_IN_SUBMIT: True},
        )
        sap_response = {
            "success": True,
            "sap_status_code": 200,
            "sap_response": {"document_number": "5100000123"},
        }
        result = adapter.receive_confirmation(ctx, sap_response)
        self.assertTrue(result.success)
        conf = ctx.get_output(AdapterStage.CONFIRMATION)
        self.assertTrue(conf.get(ERP_FULFILLED_IN_SUBMIT))
        self.assertTrue(conf.get("extensions", {}).get(ERP_FULFILLED_IN_SUBMIT))


if __name__ == "__main__":
    unittest.main()
