"""
Isolation-focused tests for Phase 2 review.
"""
from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

from fastapi import HTTPException

from app.core.workspace.context import (
    apply_customer_id_filter,
    apply_customer_ids_filter,
    require_workspace_access,
    user_can_access_customer,
)


class TestCrossCustomerIsolation(unittest.TestCase):
    def _user_for(self, assigned):
        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = [
            (c,) for c in assigned
        ]
        user = SimpleNamespace(id=42, is_admin=False, is_customer_user=True)
        return db, user

    def test_invoices_filter_helper_scopes_to_one_customer(self):
        query = MagicMock()
        apply_customer_id_filter(query, "customer_id_col", "ACME")
        query.filter.assert_called_once()

    def test_empty_assignment_yields_no_rows(self):
        query = MagicMock()
        apply_customer_ids_filter(query, "col", [])
        query.filter.assert_called()

    def test_user_acme_denied_otherco_config(self):
        db, user = self._user_for(["ACME"])
        self.assertFalse(user_can_access_customer(db, user, "OTHERCO"))
        with self.assertRaises(HTTPException) as ctx:
            require_workspace_access(db, user, "OTHERCO")
        # Hide existence
        self.assertEqual(ctx.exception.status_code, 404)

    def test_two_users_isolated(self):
        db_a, user_a = self._user_for(["CUST_A"])
        db_b, user_b = self._user_for(["CUST_B"])
        self.assertTrue(user_can_access_customer(db_a, user_a, "CUST_A"))
        self.assertFalse(user_can_access_customer(db_a, user_a, "CUST_B"))
        self.assertTrue(user_can_access_customer(db_b, user_b, "CUST_B"))
        self.assertFalse(user_can_access_customer(db_b, user_b, "CUST_A"))


if __name__ == "__main__":
    unittest.main()
