"""
Platform service hooks for the orchestrator (Phase 4).

Every collaborator the pipeline needs is a Protocol with a safe default, so any
of them can be swapped by dependency injection — in tests, per deployment, or
by a later phase (Core ERP connector in Phase 6, monitoring in Phase 8, AI in
Phase 9) — without editing the orchestrator.

None of these know about a country.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Protocol, Tuple, runtime_checkable

logger = logging.getLogger("zodiac-api.pipeline.hooks")


# --------------------------------------------------------------- protocols


@runtime_checkable
class AuthenticationProvider(Protocol):
    """Confirms the caller identity attached to a request."""

    def authenticate(self, request: Any) -> Any: ...


@runtime_checkable
class WorkspaceResolver(Protocol):
    """Loads the customer workspace (Phase 2) for a request."""

    def resolve(self, request: Any, principal: Any) -> Any: ...


@runtime_checkable
class AdapterResolver(Protocol):
    """Chooses the country adapter for a workspace. Returns (code, adapter, config)."""

    def resolve(self, request: Any, workspace: Any) -> Tuple[str, Any, Any]: ...


@runtime_checkable
class ErpUpdater(Protocol):
    """Writes the confirmation back to the customer ERP (Phase 6 owns this)."""

    def update(self, execution: Any, confirmation: Any) -> Dict[str, Any]: ...


@runtime_checkable
class MonitoringSink(Protocol):
    """Receives pipeline events (Phase 8 owns persistence)."""

    def emit(self, event: Dict[str, Any]) -> None: ...


@runtime_checkable
class AiEventSink(Protocol):
    """Receives run summaries for workspace-scoped AI (Phase 9 owns this)."""

    def emit(self, event: Dict[str, Any]) -> None: ...


@runtime_checkable
class AuditSink(Protocol):
    """Receives one entry per stage transition."""

    def record(self, entry: Dict[str, Any]) -> None: ...


# ---------------------------------------------------------------- defaults


class PrincipalAuthenticator:
    """
    Default authentication stage.

    HTTP authentication already happened upstream (`get_current_user`). This
    asserts a principal is present and active, so a programmatic caller cannot
    run the pipeline anonymously.
    """

    def authenticate(self, request: Any) -> Any:
        user = getattr(request, "user", None)
        if user is None:
            raise PermissionError("No authenticated principal on the request")
        if getattr(user, "is_active", True) is False:
            raise PermissionError("Authenticated principal is inactive")
        return user


class WorkspaceContextResolver:
    """Delegates to the Phase 2 workspace resolver, which enforces tenancy."""

    def resolve(self, request: Any, principal: Any) -> Any:
        from ..workspace.context import resolve_workspace

        return resolve_workspace(
            request.db, principal, request.customer_id, require_access=True
        )


class RegistryAdapterResolver:
    """
    Resolves `workspace + country_code → adapter` through the Adapter Registry.

    The country code is data read from the request or the workspace's adapter
    configuration; it is never compared against a literal.
    """

    def resolve(self, request: Any, workspace: Any) -> Tuple[str, Any, Any]:
        from ...adapters import ensure_builtin_adapters, registry

        ensure_builtin_adapters()

        configs = {c.country_code: c for c in getattr(workspace, "adapters", []) if c.enabled}
        requested = request.country_code

        if requested is None:
            if not configs:
                raise LookupError(
                    f"Workspace '{workspace.customer_id}' has no enabled country adapter"
                )
            if len(configs) > 1:
                raise LookupError(
                    "Workspace has multiple enabled adapters "
                    f"({', '.join(sorted(configs))}); country_code is required"
                )
            requested = next(iter(configs))

        config = configs.get(requested)
        if config is None:
            # Case-insensitive second pass: stored codes are free-form text.
            config = next(
                (c for code, c in configs.items() if code.lower() == str(requested).lower()),
                None,
            )
        if config is None:
            raise PermissionError(
                f"Country '{requested}' is not enabled for workspace '{workspace.customer_id}'"
            )

        adapter = registry.resolve(requested, db=request.db, config=config)
        return requested, adapter, config


class NullErpUpdater:
    """Legacy no-op updater; stage reports itself as skipped."""

    def update(self, execution: Any, confirmation: Any) -> Dict[str, Any]:
        raise NotImplementedError("No ERP connector configured")


def _default_erp_updater() -> "ErpUpdater":
    """Phase 6 default: workspace-aware HTTP connector (skips if unconfigured)."""
    from ..erp.hooks import WorkspaceErpUpdater

    return WorkspaceErpUpdater()


class LoggingMonitoringSink:
    def emit(self, event: Dict[str, Any]) -> None:
        logger.info(
            "[monitoring] %s %s stage=%s status=%s",
            event.get("correlation_id"),
            event.get("customer_id"),
            event.get("stage"),
            event.get("status"),
        )


class LoggingAiEventSink:
    def emit(self, event: Dict[str, Any]) -> None:
        logger.info(
            "[ai] %s %s status=%s stages=%s",
            event.get("correlation_id"),
            event.get("customer_id"),
            event.get("status"),
            len(event.get("stages", [])),
        )


class LoggingAuditSink:
    def record(self, entry: Dict[str, Any]) -> None:
        logger.info(
            "[audit] %s %s stage=%s status=%s attempts=%s",
            entry.get("correlation_id"),
            entry.get("customer_id"),
            entry.get("stage"),
            entry.get("status"),
            entry.get("attempts"),
        )


class CollectingSink:
    """In-memory sink for tests and dry runs."""

    def __init__(self) -> None:
        self.events: list = []

    def emit(self, event: Dict[str, Any]) -> None:
        self.events.append(event)

    def record(self, entry: Dict[str, Any]) -> None:
        self.events.append(entry)


@dataclass
class PlatformServices:
    """
    Dependency-injection container.

    Construct with overrides to replace any collaborator:
        PlatformServices(monitoring=MyDatadogSink())

    When both monitoring and audit are left unset, Phase 8 shared stores are
    wired so stage audit and finalize write to the same timeline.
    """

    authenticator: AuthenticationProvider = field(default_factory=PrincipalAuthenticator)
    workspace_resolver: WorkspaceResolver = field(default_factory=WorkspaceContextResolver)
    adapter_resolver: AdapterResolver = field(default_factory=RegistryAdapterResolver)
    erp_updater: Optional[ErpUpdater] = field(default_factory=_default_erp_updater)
    monitoring: Optional[MonitoringSink] = None
    ai_events: AiEventSink = field(default_factory=LoggingAiEventSink)
    audit: Optional[AuditSink] = None

    def __post_init__(self) -> None:
        if self.monitoring is None and self.audit is None:
            from ..monitoring.sinks import build_default_monitoring_bundle

            bundle = build_default_monitoring_bundle()
            self.monitoring = bundle["monitoring"]
            self.audit = bundle["audit"]
            return
        if self.monitoring is None:
            from ..monitoring.sinks import PersistingMonitoringSink

            self.monitoring = PersistingMonitoringSink()
        if self.audit is None:
            from ..monitoring.sinks import PersistingAuditSink

            self.audit = PersistingAuditSink()
