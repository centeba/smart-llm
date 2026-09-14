"""Phase-E3: WebSocket streaming proxy for agent responses.

The frontend (workflow run-history viewer + agent admin "Run" panel)
opens a WS to ``/ws/ai-agents/{agent_id}/stream`` with an
``Authorization`` header (or token in the first JSON message). The
host wires :func:`create_streaming_router` with its own session +
auth deps; this module owns the agent-resolve + provider-stream
plumbing.

Auth note: WebSocket clients can't always set headers (browsers
don't allow custom headers on `new WebSocket()`), so we accept the
JWT in the first message of the connection: ``{"token": "...",
"input": "..."}``. Hosts that prefer header auth can wrap
``stream_agent`` themselves.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select
from sqlalchemy.orm import selectinload

logger = logging.getLogger(__name__)


# Resolver signatures kept loose so the host owns ORM/auth wiring.
TokenResolver = Callable[[str], Awaitable[Any]]
# (jwt_token) -> user-or-None

KeyResolver = Callable[[Any, str], Awaitable[str | None]]
# (agent_config, company_id) -> decrypted_api_key


def create_streaming_router(
    *,
    SessionFactory: Any,
    AIAgentConfig: Any,
    AIAgentSkillLink: Any,
    resolve_token: TokenResolver,
    resolve_key: KeyResolver,
) -> APIRouter:
    """Build the streaming router.

    ``SessionFactory`` is a callable returning an *async* SQLAlchemy
    session (e.g. ``async_sessionmaker``). ``resolve_token`` decodes
    the JWT and returns the host's ``User`` (or ``None``).
    ``resolve_key`` returns the plaintext API key for the agent's
    company — typically a thin wrapper around the host's
    ``KeyManager``/``DatabaseKeyStore``.
    """
    router = APIRouter(tags=["ai-agents-stream"])

    @router.websocket("/ws/ai-agents/{agent_id}/stream")
    async def stream_agent(websocket: WebSocket, agent_id: uuid.UUID) -> None:
        await websocket.accept()
        try:
            init = await websocket.receive_json()
        except (WebSocketDisconnect, json.JSONDecodeError):
            await websocket.close(code=1003)
            return

        token = init.get("token")
        input_text = init.get("input", "")
        # Phase F2 streaming follow-up — when ``mode == "tools"`` the
        # router uses ``run_agent_loop_stream`` (provider-native
        # streaming-with-tools + agent-loop dispatch) and forwards each
        # discriminated-union event as a WS frame. Default ``"text"``
        # preserves the Phase-E3 behaviour (plain text deltas) so
        # existing consumers (Try-It dialog) keep working unchanged.
        mode = (init.get("mode") or "text").lower()
        if not token:
            await websocket.send_json({"error": "missing token"})
            await websocket.close(code=4401)
            return

        user = await resolve_token(token)
        if user is None:
            await websocket.send_json({"error": "invalid token"})
            await websocket.close(code=4401)
            return

        # Only admins may stream (matches REST CompanyAdminDep). Hosts
        # may expose ``is_company_admin`` for a clean check; otherwise
        # we fall back to the role-name allow-list used across the
        # platform.
        is_admin = getattr(user, "is_company_admin", None)
        if is_admin is None:
            role = getattr(user, "role", None)
            is_admin = role in (
                "system_admin",
                "company_admin",
                "platform_admin",
            )
        if not is_admin:
            await websocket.send_json({"error": "forbidden"})
            await websocket.close(code=4403)
            return

        async with SessionFactory() as session:
            stmt = (
                select(AIAgentConfig)
                .where(AIAgentConfig.id == agent_id)
                .options(
                    selectinload(AIAgentConfig.skill_links).selectinload(
                        AIAgentSkillLink.skill
                    )
                )
            )
            res = await session.execute(stmt)
            config = res.scalars().first()
            user_role = getattr(user, "role", None)
            is_super = user_role in ("system_admin", "platform_admin")
            if config is None or (
                not is_super
                and str(config.company_id) != str(getattr(user, "company_id", ""))
            ):
                await websocket.send_json({"error": "agent not found"})
                await websocket.close(code=4404)
                return

            try:
                api_key = await resolve_key(config, str(config.company_id))
            except Exception as e:  # noqa: BLE001
                await websocket.send_json({"error": f"key resolution failed: {e}"})
                await websocket.close(code=1011)
                return

            from smart_llm.agent import Agent

            agent = Agent(
                name=config.name,
                provider_type=config.provider_type,
                system_prompt=config.system_prompt or "",
                api_key=api_key or "",
                model_name=config.model_name,
            )

            if mode == "tools":
                # Resolve attached skills into ActionTool instances and
                # delegate to the agent-loop streaming driver.
                action_tools = _resolve_action_tools(config)
                # ── Safety harness (S1) ──────────────────────────────────────
                # The streaming tools path must run the SAME safety harness as
                # the durable path: the content-safety guard (indirect-injection
                # screening) and a ToolPolicyGate (risk-tier × per-tool
                # approval_mode), so streamed write/external tools are never
                # dispatched unattended. Built from the agent's own skill links;
                # a tool absent from the map is denied by the gate.
                from smart_llm.security.tool_policy import (
                    AgentRunContext,
                    ToolPolicyGate,
                )

                tool_modes = {
                    link.skill.name: link.approval_mode
                    for link in (config.skill_links or [])
                    if link.skill is not None and getattr(link.skill, "is_active", True)
                }
                policy_gate = ToolPolicyGate(
                    AgentRunContext(
                        agent_id=str(config.id),
                        acting_company_id=str(config.company_id),
                        tool_modes=tool_modes,
                    )
                )
                try:
                    from smart_llm.agent_loop import run_agent_loop_stream

                    async for event in run_agent_loop_stream(
                        agent._provider,  # noqa: SLF001 — intentional
                        agent.system_prompt,
                        input_text,
                        action_tools,
                        session,
                        guard=agent._safety_guard,  # noqa: SLF001
                        policy_gate=policy_gate,
                    ):
                        await websocket.send_json(event)
                    # Synthetic done frame so the consumer has a stable
                    # close signal (last event might be turn_complete or
                    # error; both terminate the stream).
                    await websocket.send_json({"type": "done"})
                except WebSocketDisconnect:
                    return
                except NotImplementedError as e:
                    await websocket.send_json({"type": "error", "message": str(e)})
                except Exception as e:  # noqa: BLE001
                    logger.exception("tool-streaming failed for agent %s", agent_id)
                    await websocket.send_json({"type": "error", "message": str(e)})
                finally:
                    try:
                        await websocket.close()
                    except Exception:  # noqa: BLE001
                        pass
                return

            try:
                async for delta in agent.analyze_stream(input_text):
                    await websocket.send_json({"delta": delta})
                await websocket.send_json({"done": True})
            except WebSocketDisconnect:
                return
            except NotImplementedError as e:
                await websocket.send_json({"error": str(e)})
            except Exception as e:  # noqa: BLE001
                logger.exception("streaming failed for agent %s", agent_id)
                await websocket.send_json({"error": str(e)})
            finally:
                try:
                    await websocket.close()
                except Exception:  # noqa: BLE001
                    pass

    return router


# ── Skill → ActionTool resolution ───────────────────────────────────────────


def _resolve_action_tools(config: Any) -> list[Any]:
    """Walk the agent's attached skills and instantiate every one
    that resolves to an :class:`~smart_llm.base.ActionTool` in the
    registry. ``kind="prompt"`` rows are ignored — they augment the
    system prompt and don't take part in the tool-use loop. Unknown
    registry names are skipped silently (logged) rather than aborting
    the stream."""
    from smart_llm.base import ActionTool
    from smart_llm.registry import get_tool_meta

    tools: list[Any] = []
    for link in getattr(config, "skill_links", []) or []:
        skill = getattr(link, "skill", None)
        if skill is None or not getattr(skill, "is_active", True):
            continue
        if getattr(skill, "kind", "prompt") != "python_tool":
            continue
        # The skill row's ``content`` holds the registry name when
        # kind=python_tool (per Phase C seed migration convention).
        registry_name = getattr(skill, "content", None) or skill.name
        meta = get_tool_meta(registry_name)
        if meta is None:
            logger.warning(
                "streaming: skill %r not in registry — skipping",
                registry_name,
            )
            continue
        try:
            instance = meta.cls()
        except TypeError:
            logger.warning(
                "streaming: skill %r could not be instantiated; skipping",
                registry_name,
            )
            continue
        if not isinstance(instance, ActionTool):
            # Prompt-shaping Tool subclasses aren't usable in
            # stream_with_tools; ignore.
            continue
        tools.append(instance)
    return tools
