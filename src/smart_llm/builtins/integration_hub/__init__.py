"""Integration-hub adapter package.

Wraps every operation defined in
``services/integration-hub/.../mcp/tools.TOOL_DEFINITIONS`` as a
smart-llm :class:`ActionTool` so the same tools the MCP server exposes
become first-class skills inside the registry, the AI admin UI, and
the workflow builder TOOLS palette.

Import is **guarded**: hosts that ship smart-llm without
integration-hub (e.g. a hypothetical doc-vault-only service) will hit
``ModuleNotFoundError`` on the first ``integration_hub_backend.*``
import; we swallow it and skip registration silently. Hosts that *do*
bundle integration-hub (currently integration-hub-api itself, plus
mit-stack workers via the shared site-packages) get all 16 tools
registered at startup.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

try:
    # Import order matches mcp/tools.TOOL_DEFINITIONS for easy auditing.
    from . import (
        drive,  # noqa: F401          — 1 tool
        gmail,  # noqa: F401          — 4 tools
        notifications,  # noqa: F401  — 3 rule-builder tools
        observability,  # noqa: F401  — 2 tools
        outlook,  # noqa: F401        — 4 tools
        postgres,  # noqa: F401      — 3 tools
        stripe,  # noqa: F401         — 2 tools
    )
except ModuleNotFoundError as e:  # pragma: no cover — host-shape dependent
    if e.name and (
        e.name.startswith("integration_hub_backend")
        or e.name == "integration_hub_backend"
    ):
        logger.info(
            "smart_llm.builtins.integration_hub: integration_hub_backend not "
            "installed in this host; skipping action-tool registration."
        )
    else:
        # Different missing module — re-raise so we don't mask real bugs.
        raise
