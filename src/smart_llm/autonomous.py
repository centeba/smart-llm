"""Helpers for the durable autonomous-agent run path (AgentRunWorkflow).

These are the smart-llm-side primitives the integration-hub ``/ai-invoke/agent-turn``
and ``/ai-invoke/agent-tool-dispatch`` endpoints use. They keep the
provider/tool/loop knowledge in smart-llm while the Temporal workflow holds only
opaque, provider-shaped ``messages`` state and orchestrates approvals.

Flow per run (one AgentRunWorkflow):
  1. workflow → agent_turn_activity(messages, tool_results) → ONE provider turn.
     Returns either a final text or a list of requested tool calls, each with the
     policy-gate decision (allow / deny / approval_required).
  2. workflow dispatches allowed/approved calls via agent_tool_dispatch_activity,
     pausing (wait_approval signal) for any approval_required call, then loops.
"""

from __future__ import annotations

import logging
from typing import Any

from .base import ActionTool
from .registry import get_tool_meta

logger = logging.getLogger(__name__)


async def resolve_action_tools(
    skill_names: list[str],
    db_session: Any,
    *,
    ai_skill_cls: Any = None,
) -> list[ActionTool]:
    """Resolve ``skill_names`` to instantiated :class:`ActionTool` objects.

    Mirrors the resolution order in :meth:`smart_llm.agent.Agent.run_with_skills`
    (registry first, then a DB ``AISkill`` row whose ``content`` is a registry
    name for ``kind='python_tool'``) but returns ONLY the ActionTools — prompt
    skills are not relevant to an autonomous tool-using run. Unknown names are
    skipped with a warning rather than raising, so one stale link can't abort a run.
    """
    tools: list[ActionTool] = []
    for name in skill_names:
        meta = get_tool_meta(name)
        if meta is None and db_session is not None and ai_skill_cls is not None:
            try:
                from sqlalchemy import select

                row = (
                    (
                        await db_session.execute(
                            select(ai_skill_cls).where(ai_skill_cls.name == name)
                        )
                    )
                    .scalars()
                    .first()
                )
                if row is not None and getattr(row, "kind", "") == "python_tool":
                    meta = get_tool_meta(getattr(row, "content", "") or "")
            except Exception:  # noqa: BLE001
                logger.warning("resolve_action_tools: DB lookup failed for %s", name)
        if meta is None:
            logger.warning("resolve_action_tools: unresolved skill %s", name)
            continue
        try:
            inst = meta.cls()
        except TypeError:
            logger.warning("resolve_action_tools: %s needs ctor args; skipping", name)
            continue
        if isinstance(inst, ActionTool):
            # Tag the instance with its registry name so _dispatch_all / the gate
            # index it by the same name the LLM uses.
            setattr(inst, "_registry_name", name)
            tools.append(inst)
    return tools


def synthetic_tool_result(
    tool_call_id: str, name: str, payload: dict[str, Any]
) -> dict[str, Any]:
    """Build the raw tool-result dict the turn activity later shapes into the
    provider message (used for deny/rejection results assembled by the workflow)."""
    import json

    return {"tool_call_id": tool_call_id, "name": name, "content": json.dumps(payload)}
