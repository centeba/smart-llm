"""Service-instantiation helper shared by every integration-hub adapter.

Lifted directly from ``services/integration-hub/.../mcp/server.py`` lines
56-75 so the MCP transport and the smart-llm registry route to the
*same* service objects with the *same* construction rules. When a new
tool is added to ``mcp/tools.TOOL_DEFINITIONS`` only the adapter
subclass needs to be added here — the dispatch table is read at call
time.

This module is imported lazily from each adapter's ``run_action`` so
adapter subclass *definition* doesn't pull integration-hub into the
import graph; only invocation does. Hosts that don't bundle
integration-hub silently skip registration via the parent package's
``try/except ImportError`` guard.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession


async def dispatch(
    name: str,
    args: Any,
    *,
    db_session: AsyncSession,
) -> Any:
    """Resolve ``name`` against ``TOOL_DEFINITIONS`` and call the right
    service method with the validated args.

    Returns whatever the service method returns (typically a list/dict).
    Callers that need a guaranteed-dict shape should wrap.
    """
    # Imported here, not at module top, so that the adapter package's
    # ``try/except ImportError`` guard keeps the smart-llm registry
    # importable on hosts without integration-hub installed.
    from integration_hub_backend.api.services.email_service import EmailService
    from integration_hub_backend.api.services.google_drive_service import (
        GoogleDriveService,
    )
    from integration_hub_backend.api.services.observability_service import (
        ObservabilityService,
    )
    from integration_hub_backend.api.services.postgres_service import (
        PostgresService,
    )
    from integration_hub_backend.api.services.rule_service import RuleService
    from integration_hub_backend.api.services.stripe_service import StripeService
    from integration_hub_backend.mcp.tools import TOOL_DEFINITIONS

    info = TOOL_DEFINITIONS[name]
    service_kind = info["service"]

    if service_kind == "email_service":
        service: Any = EmailService(db_session)
    elif service_kind == "google_drive_service":
        service = GoogleDriveService(ObservabilityService(db_session))
    elif service_kind == "stripe_service":
        service = StripeService(ObservabilityService(db_session))
    elif service_kind == "observability_service":
        service = ObservabilityService(db_session)
    elif service_kind == "postgres_service":
        service = PostgresService(db_session)
    elif service_kind == "rule_service":
        service = RuleService(db_session)
    else:
        raise ValueError(f"Unknown service kind '{service_kind}' for tool '{name}'")

    method = getattr(service, info["method"])
    payload = args.model_dump() if hasattr(args, "model_dump") else dict(args)
    return await method(**payload)
