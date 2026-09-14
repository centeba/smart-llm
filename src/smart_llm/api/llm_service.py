"""LLM service utilities — system prompt assembly, context building, and execution.

This module is part of smart-llm and has no imports from the host application.
The host provides the engine and encryption key at startup via get_key_store().
"""

import json
import logging
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Key store singleton — parameterised so the host injects engine + key
# ---------------------------------------------------------------------------

_key_store = None


def get_key_store(engine: Any = None, encryption_key: str | None = None) -> Any:
    """Return a DatabaseKeyStore backed by the provided async engine.

    On first call, engine and encryption_key must be supplied.
    Subsequent calls reuse the singleton and may omit the arguments.
    """
    global _key_store
    if _key_store is None:
        if engine is None or encryption_key is None:
            raise ValueError(
                "engine and encryption_key are required on the first call to get_key_store()"
            )
        from smart_llm.key_store import DatabaseKeyStore

        _key_store = DatabaseKeyStore(engine=engine, encryption_key=encryption_key)
    return _key_store


async def get_company_api_key(
    session: AsyncSession, company_id: uuid.UUID, provider: str
) -> str | None:
    """Retrieve a decrypted API key for a company + provider via smart-llm's store."""
    store = get_key_store()
    keys = await store.load_keys(provider, scope_id=company_id)
    if not keys:
        return None
    from smart_llm import KeyManager

    km = KeyManager(key_store=store)
    km.register_provider(provider, keys)
    return km.get_key(provider)


async def get_platform_api_key(session: AsyncSession, provider: str) -> str | None:
    """Phase G — retrieve the platform-level decrypted LLM key for
    ``provider``. Used when an agent's ``scope='platform'``. Reads
    from ``platform_llm_api_keys`` (created by migration 014).

    Returns ``None`` when no row exists; callers (typically
    ``resolve_agent_api_key``) surface that as a missing-key error
    so the operator sees a clean failure rather than a silent fallback.
    """
    # We can't import the host's ORM here without coupling; query the
    # table by raw SQL via the session. ``platform_llm_api_keys`` ships
    # with migration 014; if it doesn't exist this returns None.
    from sqlalchemy import text as _text

    try:
        row = (
            await session.execute(
                _text(
                    "SELECT key_encrypted FROM platform_llm_api_keys "
                    "WHERE provider = :p AND is_active = TRUE LIMIT 1"
                ),
                {"p": provider},
            )
        ).first()
    except Exception:  # noqa: BLE001 — table may not exist yet
        return None
    if row is None:
        return None

    # Re-use the singleton DatabaseKeyStore's Fernet so platform keys
    # are encrypted with the same secret as company-scoped ones.
    store = get_key_store()
    try:
        return cast("str | None", store._decrypt(row[0]))  # noqa: SLF001 — intentional reuse
    except Exception:  # noqa: BLE001
        logger.warning("platform key for %r failed to decrypt", provider)
        return None


async def resolve_agent_api_key(
    session: AsyncSession,
    agent: Any,
    triggering_company_id: uuid.UUID | str | None,
    *,
    AIAgentGrant: Any = None,
) -> str | None:
    """Phase G — paid-by routing for an agent's LLM key.

    - ``scope='company'`` → owner's company key.
    - ``scope='platform'`` → ``platform_llm_api_keys`` for the provider.
    - ``scope='shared'``  → consult ``ai_agent_grants`` for the
      ``(agent_id, triggering_company_id)`` pair; ``pays='owner'``
      bills the owner, ``pays='grantee'`` bills the triggering tenant.
      When no grant row exists we default to the owner (the same row
      that visible_agent_filter found via owner-match).

    Hosts that haven't run migrations 013/014 pass ``AIAgentGrant=None``
    and the function degrades to the legacy company-keyed path.
    """
    from smart_llm.api.scoping import resolve_paying_company_id
    from smart_llm.db.models import SCOPE_PLATFORM

    scope = getattr(agent, "scope", "company")
    if scope == SCOPE_PLATFORM:
        return await get_platform_api_key(session, agent.provider_type)

    grant_row = None
    if (
        scope == "shared"
        and AIAgentGrant is not None
        and triggering_company_id is not None
    ):
        from sqlalchemy import select as _select

        gstmt = _select(AIAgentGrant).where(
            AIAgentGrant.agent_id == agent.id,
            AIAgentGrant.grantee_company_id == triggering_company_id,
        )
        grant_row = (await session.execute(gstmt)).scalars().first()

    paying_company = resolve_paying_company_id(
        agent, triggering_company_id, grant_row=grant_row
    )
    if paying_company is None:
        return await get_platform_api_key(session, agent.provider_type)
    return await get_company_api_key(
        session, uuid.UUID(paying_company), agent.provider_type
    )


# ---------------------------------------------------------------------------
# System prompt assembly
# ---------------------------------------------------------------------------


def build_system_prompt(agent_config: Any, skills: list[Any]) -> str:
    parts: list[str] = []
    if agent_config.system_prompt:
        parts.append(agent_config.system_prompt)
    for skill in skills:
        if skill.is_active and skill.content:
            parts.append(f"\n\n--- Skill: {skill.name} ---\n{skill.content}")
    return "\n".join(parts) if parts else "You are a helpful assistant."


# ---------------------------------------------------------------------------
# Conversation context
# ---------------------------------------------------------------------------


async def build_conversation_context(
    session: AsyncSession,
    thread_id: uuid.UUID,
    max_messages: int = 20,
    AgentChatMessage: Any = None,
) -> str:
    """Build a text representation of the recent conversation history.

    AgentChatMessage ORM class must be passed by the host application.
    """
    result = await session.execute(
        select(AgentChatMessage)
        .where(AgentChatMessage.thread_id == thread_id)
        .options(selectinload(AgentChatMessage.parts))
        .order_by(AgentChatMessage.created_at.desc())
        .limit(max_messages)
    )
    messages = list(reversed(result.scalars().all()))
    lines: list[str] = []
    for msg in messages:
        role_label = "User" if msg.role == "user" else "Assistant"
        text_parts = [
            p.text_content
            for p in msg.parts
            if p.part_type == "text" and p.text_content
        ]
        if text_parts:
            lines.append(f"{role_label}: {' '.join(text_parts)}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Agent skills loader
# ---------------------------------------------------------------------------


async def load_agent_skills(
    session: AsyncSession,
    agent_config_id: uuid.UUID,
    AISkill: Any = None,
    AIAgentSkillLink: Any = None,
) -> list[Any]:
    """Load skills linked to an agent config. ORM classes injected by host."""
    result = await session.execute(
        select(AISkill)
        .join(AIAgentSkillLink, AIAgentSkillLink.skill_id == AISkill.id)
        .where(AIAgentSkillLink.agent_config_id == agent_config_id)
    )
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# Non-streaming execution via smart-llm
# ---------------------------------------------------------------------------


def _resolve_pii(company_pii_policy: str | None, model_configuration: Any) -> tuple[str, bool]:
    """Resolve the effective PII policy + vision escape hatch for one agent call.

    Combines the company policy (or the ``SMART_LLM_PII_DEFAULT_POLICY`` env
    default when ``None``) with the agent's per-agent override read from its
    ``model_configuration`` JSON — masking is on out-of-the-box and an agent may
    only tighten it. Returns ``(effective_policy, allow_vision_pii)``.
    """
    from smart_llm.pii import resolve_pii_policy

    cfg: dict[str, Any] = {}
    if model_configuration:
        try:
            cfg = json.loads(model_configuration) or {}
        except (json.JSONDecodeError, TypeError):
            cfg = {}
    policy = resolve_pii_policy(company_pii_policy, cfg)
    allow_vision = bool(cfg.get("allow_vision_pii", False))
    return policy, allow_vision


async def run_agent_non_streaming(
    agent_config: Any,
    skills: list[Any],
    api_key: str,
    user_input: str,
    context: str | None = None,
    *,
    company_pii_policy: str | None = None,
) -> dict[str, Any]:
    from smart_llm import Agent
    from smart_llm.tool import ContextPruningTool

    system_prompt = build_system_prompt(agent_config, skills)

    model_name = agent_config.model_name
    base_url = None
    if agent_config.model_configuration:
        try:
            cfg = json.loads(agent_config.model_configuration)
            base_url = cfg.get("base_url")
        except (json.JSONDecodeError, TypeError):
            pass

    # Apply the per-tenant provider policy: an ``openrouter`` config is
    # downgraded to a direct vendor when the agent (or its company) forbids
    # routing through the gateway. Non-gateway configs pass through unchanged.
    from smart_llm.provider_policy import resolve_agent_provider

    provider_type, model_name = resolve_agent_provider(
        agent_config.provider_type, model_name, agent_config.model_configuration
    )

    pii_policy, pii_allow_vision = _resolve_pii(
        company_pii_policy, agent_config.model_configuration
    )

    agent = Agent(
        name=agent_config.name,
        provider_type=provider_type,
        system_prompt=system_prompt,
        api_key=api_key,
        tools=[ContextPruningTool(max_chars=15000)],
        model_name=model_name,
        base_url=base_url,
        pii_policy=pii_policy,
        pii_allow_vision=pii_allow_vision,
    )

    response = await agent.analyze(user_input, context=context)
    return {
        "data": response.data,
        "provider": response.provider,
        "metadata": response.metadata,
    }


# ---------------------------------------------------------------------------
# Streaming execution — routed through Agent for budget + usage + safety
# ---------------------------------------------------------------------------


@dataclass
class ModelOverride:
    """Per-turn provider/model selection for :func:`run_agent_streaming`.

    Overrides the bound ``AIAgentConfig`` for this call only (the DB config is
    never mutated). ``model_configuration`` falls back to the agent config's
    when ``None``.
    """

    provider_type: str
    model_name: str
    model_configuration: str | None = None


@dataclass
class UsageRecording:
    """Handles the host injects so a streamed turn is budget-gated and billed.

    Mirrors smart-llm's opt-in usage pattern: when ``usage_session`` +
    ``usage_model`` are set, the turn runs the budget check before the stream
    opens and records one ``ai_usage_events`` row under the effective model
    after it drains. Omit for an unmetered stream.
    """

    usage_session: Any = None
    usage_model: Any = None
    company_id: Any = None
    monthly_budget_usd: float = 0.0
    agent_id: Any = None
    user_id: Any = None


async def run_agent_streaming(
    agent_config: Any,
    skills: list[Any],
    api_key: str,
    user_input: str,
    context: str | None = None,
    *,
    model_override: ModelOverride | None = None,
    usage_ctx: UsageRecording | None = None,
    company_pii_policy: str | None = None,
    pii_hints: Any = None,
) -> AsyncIterator[str]:
    """Stream an assistant reply as SSE lines: ``data: {"type":"text",...}``.

    Runs through :class:`smart_llm.Agent` (not raw provider SDKs) so every turn
    — for every provider, including a per-turn ``model_override`` — gets the
    budget gate, content-safety input screen, and ``ai_usage_events`` recording
    built into ``Agent.analyze_stream``. ``model_override`` selects the
    provider/model for this call; ``usage_ctx`` wires budget + billing. Both are
    optional and backward-compatible.
    """
    from smart_llm import Agent
    from smart_llm.provider_policy import resolve_agent_provider
    from smart_llm.tool import ContextPruningTool

    system_prompt = build_system_prompt(agent_config, skills)

    provider_type = (
        model_override.provider_type if model_override else agent_config.provider_type
    )
    model_name = (
        model_override.model_name if model_override else agent_config.model_name
    )
    model_configuration = (
        model_override.model_configuration
        if model_override and model_override.model_configuration is not None
        else agent_config.model_configuration
    )

    # Parity with run_agent_non_streaming: honour the tenant/agent privacy
    # policy that may downgrade an openrouter selection to a direct vendor.
    provider_type, model_name = resolve_agent_provider(
        provider_type, model_name, model_configuration
    )

    base_url = None
    if model_configuration:
        try:
            base_url = json.loads(model_configuration).get("base_url")
        except (json.JSONDecodeError, TypeError):
            pass

    pii_policy, pii_allow_vision = _resolve_pii(company_pii_policy, model_configuration)

    uc = usage_ctx or UsageRecording()
    agent = Agent(
        name=getattr(agent_config, "name", None) or "chat",
        provider_type=provider_type,
        system_prompt=system_prompt,
        api_key=api_key,
        tools=[ContextPruningTool(max_chars=15000)],
        model_name=model_name,
        base_url=base_url,
        usage_session=uc.usage_session,
        usage_model=uc.usage_model,
        company_id=uc.company_id,
        monthly_budget_usd=uc.monthly_budget_usd,
        agent_id=uc.agent_id,
        user_id=uc.user_id,
        pii_policy=pii_policy,
        pii_allow_vision=pii_allow_vision,
        pii_hints=pii_hints,
    )

    try:
        async for chunk in agent.analyze_stream(user_input, context=context):
            yield f"data: {json.dumps({'type': 'text', 'content': chunk})}\n\n"
    except Exception as exc:
        logger.exception("Streaming error for provider %s", provider_type)
        yield f"data: {json.dumps({'type': 'error', 'content': str(exc)})}\n\n"

    yield f"data: {json.dumps({'type': 'done'})}\n\n"
