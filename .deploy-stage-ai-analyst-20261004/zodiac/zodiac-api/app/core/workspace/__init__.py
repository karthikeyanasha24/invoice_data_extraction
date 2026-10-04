"""Workspace context and access guards."""
from .context import (
    WorkspaceContext,
    apply_customer_id_filter,
    apply_customer_ids_filter,
    assert_ai_workspace_scope,
    is_valid_secret_ref,
    list_assigned_customer_ids,
    require_workspace_access,
    resolve_workspace,
    user_can_access_customer,
    validate_secret_ref_or_raise,
)

__all__ = [
    "WorkspaceContext",
    "apply_customer_id_filter",
    "apply_customer_ids_filter",
    "assert_ai_workspace_scope",
    "is_valid_secret_ref",
    "list_assigned_customer_ids",
    "require_workspace_access",
    "resolve_workspace",
    "user_can_access_customer",
    "validate_secret_ref_or_raise",
]
