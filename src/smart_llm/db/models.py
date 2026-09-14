"""Consolidated AI agent / skill / link ORM + Pydantic models.

All agentic plumbing lives in smart-llm. Hosts wire the ORM tables into
their own SQLAlchemy ``Base`` via ``make_ai_models`` so that:

* Migrations stay with the host's Alembic configuration.
* Smart-llm has no global metadata of its own to manage.
* Pydantic schemas (which need no Base) are importable directly.

Migrating from the previous integration-hub-owned models (where these
classes lived in ``integration_hub_backend.api.models.ai_agent``):

>>> from smart_llm.db import make_ai_models
>>> from integration_hub_backend.api.core.db import Base
>>> _m = make_ai_models(Base)
>>> AISkill, AIAgentConfig, AIAgentSkillLink = (
...     _m["AISkill"], _m["AIAgentConfig"], _m["AIAgentSkillLink"]
... )

New columns on ``AISkill`` (added in the agentic refactor):

* ``kind``     — ``"prompt"`` (LLM-text skill stored as ``content``) or
  ``"python_tool"`` (concrete Python class registered in
  :mod:`smart_llm.registry`; ``content`` is then the registry name).
* ``modality`` — ``"document"`` | ``"image"`` | ``"video"`` |
  ``"audio"`` | ``"text"`` | ``"any"``. Drives palette grouping and
  filtered tool-picking by agents.
"""

import uuid
from datetime import datetime
from typing import Any, Final

from pydantic import BaseModel
from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

# ── Constants ─────────────────────────────────────────────────────────────────

SKILL_KIND_PROMPT = "prompt"
SKILL_KIND_PYTHON_TOOL = "python_tool"
SKILL_KINDS = (SKILL_KIND_PROMPT, SKILL_KIND_PYTHON_TOOL)

# ── Phase G — visibility scopes for cross-company AI agents ───────────────
SCOPE_COMPANY = "company"  # default — owning tenant only
SCOPE_PLATFORM = "platform"  # system_admin-owned; visible to every tenant
SCOPE_SHARED = "shared"  # owning tenant + grantees in ai_agent_grants
SCOPES = (SCOPE_COMPANY, SCOPE_PLATFORM, SCOPE_SHARED)

# Who pays for a ``scope='shared'`` agent's LLM call.
SHARED_PAYS_OWNER = "owner"
SHARED_PAYS_GRANTEE = "grantee"
SHARED_PAYS = (SHARED_PAYS_OWNER, SHARED_PAYS_GRANTEE)

# ── Autonomous-agent safety harness ───────────────────────────────────────
# Per-(agent, tool) approval policy, stored on AIAgentSkillLink.approval_mode.
APPROVAL_AUTO = "auto"  # risk-default: read→unattended, write/external→approval
APPROVAL_ALLOW = "allow"  # force unattended regardless of risk (admin opt-in)
APPROVAL_REQUIRE = "require_approval"  # always pause for human approval before dispatch
APPROVAL_DENY = "deny"  # never dispatch this tool for this agent
APPROVAL_MODES = (APPROVAL_AUTO, APPROVAL_ALLOW, APPROVAL_REQUIRE, APPROVAL_DENY)

# agent_runs.status lifecycle
RUN_RUNNING = "running"
RUN_AWAITING_APPROVAL = "awaiting_approval"
RUN_COMPLETED = "completed"
RUN_FAILED = "failed"
RUN_DENIED = "denied"
RUN_TIMEOUT = "timeout"
RUN_STATUSES = (
    RUN_RUNNING,
    RUN_AWAITING_APPROVAL,
    RUN_COMPLETED,
    RUN_FAILED,
    RUN_DENIED,
    RUN_TIMEOUT,
)

# agent_action_audit.decision — outcome of a tool-policy evaluation.
DECISION_ALLOW: Final = "allow"
DECISION_DENY: Final = "deny"
DECISION_APPROVAL_REQUIRED: Final = "approval_required"
DECISION_APPROVED = "approved"
DECISION_REJECTED = "rejected"

MODALITY_DOCUMENT = "document"
MODALITY_IMAGE = "image"
MODALITY_VIDEO = "video"
MODALITY_AUDIO = "audio"
MODALITY_TEXT = "text"
MODALITY_ANY = "any"
MODALITIES = (
    MODALITY_DOCUMENT,
    MODALITY_IMAGE,
    MODALITY_VIDEO,
    MODALITY_AUDIO,
    MODALITY_TEXT,
    MODALITY_ANY,
)


# ── ORM model factory ────────────────────────────────────────────────────────


def make_ai_models(Base: type) -> dict[str, type]:
    """Build ``AISkill``, ``AIAgentConfig``, ``AIAgentSkillLink`` ORM classes
    bound to the host's declarative ``Base``.

    Returns a dict so callers can pick what they need. The classes are
    fully usable: relationships are configured, primary keys are UUIDs,
    timestamps default server-side.
    """

    class AISkill(Base):  # type: ignore[misc]  # host-provided declarative Base is dynamic; mypy cannot check it
        __tablename__ = "ai_skills"

        id: Mapped[uuid.UUID] = mapped_column(
            UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
        )
        # Phase G — ``company_id`` is NULLable when ``scope='platform'``.
        # A CHECK constraint added by the migration ensures
        # ``(scope='platform') = (company_id IS NULL)`` so we don't
        # accidentally orphan a company/shared row.
        company_id: Mapped[uuid.UUID | None] = mapped_column(
            UUID(as_uuid=True), nullable=True, index=True
        )
        scope: Mapped[str] = mapped_column(
            String(32),
            nullable=False,
            server_default=SCOPE_COMPANY,
            index=True,
        )
        name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
        label: Mapped[str | None] = mapped_column(String(255), nullable=True)
        description: Mapped[str | None] = mapped_column(Text, nullable=True)
        icon: Mapped[str | None] = mapped_column(String(100), nullable=True)
        # Kind & modality drive registry resolution and palette grouping.
        # Kept indexed because the workflow palette filters on them when
        # listing tools per category / modality.
        kind: Mapped[str] = mapped_column(
            String(32),
            nullable=False,
            server_default=SKILL_KIND_PROMPT,
            index=True,
        )
        modality: Mapped[str] = mapped_column(
            String(32),
            nullable=False,
            server_default=MODALITY_ANY,
            index=True,
        )
        # For kind=prompt: free-text prompt fragment.
        # For kind=python_tool: the registry name (e.g. "parse_pdf").
        content: Mapped[str | None] = mapped_column(Text, nullable=True)
        # When set, this skill is provisioned by a vertical app (e.g.
        # "restoration") via the SDK's SkillBundle.register_with(). The UI
        # renders these read-only; PATCH/DELETE return 403. Edits happen by
        # changing the YAML in the vertical's repo and redeploying.
        source_app: Mapped[str | None] = mapped_column(
            String(100), nullable=True, index=True
        )
        is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
        # When true, this skill is only usable *inside* an agent's reasoning
        # loop (as an allow-listed tool) and is NOT offered as a directly
        # droppable node in the workflow builder. ``kind='prompt'`` skills are
        # implicitly agent-only (a prompt fragment is never directly callable);
        # this flag lets an author additionally mark a ``python_tool`` skill as
        # agent-only when it expects the agent's context to behave correctly.
        agent_only: Mapped[bool] = mapped_column(
            Boolean, nullable=False, server_default="false", default=False
        )
        created_by: Mapped[uuid.UUID] = mapped_column(
            UUID(as_uuid=True), nullable=False
        )
        created_at: Mapped[datetime] = mapped_column(
            DateTime(timezone=True), server_default=func.now(), nullable=False
        )
        updated_at: Mapped[datetime] = mapped_column(
            DateTime(timezone=True),
            server_default=func.now(),
            onupdate=func.now(),
            nullable=False,
        )

    class AIAgentConfig(Base):  # type: ignore[misc]  # host-provided declarative Base is dynamic; mypy cannot check it
        __tablename__ = "ai_agent_configs"

        id: Mapped[uuid.UUID] = mapped_column(
            UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
        )
        # Phase G — ``company_id`` is NULLable when ``scope='platform'``.
        company_id: Mapped[uuid.UUID | None] = mapped_column(
            UUID(as_uuid=True), nullable=True, index=True
        )
        scope: Mapped[str] = mapped_column(
            String(32),
            nullable=False,
            server_default=SCOPE_COMPANY,
            index=True,
        )
        name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
        label: Mapped[str | None] = mapped_column(String(255), nullable=True)
        description: Mapped[str | None] = mapped_column(Text, nullable=True)
        icon: Mapped[str | None] = mapped_column(String(100), nullable=True)
        system_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
        # "anthropic" | "openai" | "gemini" — stored as string so a host that
        # adds a new provider doesn't need a schema migration.
        provider_type: Mapped[str] = mapped_column(
            String(50), nullable=False, default="anthropic"
        )
        model_name: Mapped[str] = mapped_column(
            String(255), nullable=False, default="claude-3-5-sonnet-20240620"
        )
        # Optional JSON string for base_url, temperature, max_tokens, fallback
        # chains, etc. Kept as Text so callers can ship arbitrary structured
        # config without forcing a column for every dial.
        model_configuration: Mapped[str | None] = mapped_column(Text, nullable=True)
        # Optional: "json" | "text"
        response_format: Mapped[str | None] = mapped_column(String(50), nullable=True)
        # Optional role/persona reference (host-defined table; we don't FK here).
        role_id: Mapped[uuid.UUID | None] = mapped_column(
            UUID(as_uuid=True), nullable=True
        )
        # When set, this agent is provisioned by a vertical app (e.g.
        # "restoration") via the SDK's AgentBundle.register_with(). The
        # AI Admin UI renders these read-only; PATCH/DELETE return 403.
        source_app: Mapped[str | None] = mapped_column(
            String(100), nullable=True, index=True
        )
        # ── Autonomous-agent safety harness ───────────────────────────────
        # When ``True``, this agent may run as a reactive multi-step
        # autonomous run (the durable AgentRunWorkflow + tool-policy gate).
        # ``False`` (default) keeps the legacy single-shot behavior.
        autonomous: Mapped[bool] = mapped_column(
            Boolean, nullable=False, server_default="false"
        )
        # Per-run guardrails. NULL = use the loop default (10 steps) / no
        # extra cost ceiling beyond the company monthly cap.
        max_steps: Mapped[int | None] = mapped_column(Integer, nullable=True)
        max_cost_usd: Mapped[Any | None] = mapped_column(Numeric(12, 4), nullable=True)
        is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
        created_by: Mapped[uuid.UUID] = mapped_column(
            UUID(as_uuid=True), nullable=False
        )
        created_at: Mapped[datetime] = mapped_column(
            DateTime(timezone=True), server_default=func.now(), nullable=False
        )
        updated_at: Mapped[datetime] = mapped_column(
            DateTime(timezone=True),
            server_default=func.now(),
            onupdate=func.now(),
            nullable=False,
        )

        skill_links: Mapped[list[Any]] = relationship(
            "AIAgentSkillLink",
            back_populates="agent_config",
            cascade="all, delete-orphan",
        )

    class AIAgentSkillLink(Base):  # type: ignore[misc]  # host-provided declarative Base is dynamic; mypy cannot check it
        __tablename__ = "ai_agent_skill_links"

        agent_config_id: Mapped[uuid.UUID] = mapped_column(
            UUID(as_uuid=True),
            ForeignKey("ai_agent_configs.id", ondelete="CASCADE"),
            primary_key=True,
        )
        skill_id: Mapped[uuid.UUID] = mapped_column(
            UUID(as_uuid=True),
            ForeignKey("ai_skills.id", ondelete="CASCADE"),
            primary_key=True,
        )
        # Per-(agent, tool) approval policy for the autonomous tool-policy
        # gate. Default ``auto``; the gate upgrades high-risk tools to
        # ``require_approval`` unless an admin explicitly set ``auto`` here.
        approval_mode: Mapped[str] = mapped_column(
            String(16), nullable=False, server_default=APPROVAL_AUTO
        )

        agent_config: Mapped[Any] = relationship(
            "AIAgentConfig", back_populates="skill_links"
        )
        skill: Mapped[Any] = relationship("AISkill")

    # ── Phase G — grants tables for cross-tenant sharing ─────────────

    class AIAgentGrant(Base):  # type: ignore[misc]  # host-provided declarative Base is dynamic; mypy cannot check it
        """Grant of a ``scope='shared'`` agent to a non-owning tenant.

        ``pays`` decides which tenant's LLM key bills the call:
        ``'owner'`` = the agent's owner pays for everything;
        ``'grantee'`` = the grantee uses their own key.
        """

        __tablename__ = "ai_agent_grants"

        agent_id: Mapped[uuid.UUID] = mapped_column(
            UUID(as_uuid=True),
            ForeignKey("ai_agent_configs.id", ondelete="CASCADE"),
            primary_key=True,
        )
        grantee_company_id: Mapped[uuid.UUID] = mapped_column(
            UUID(as_uuid=True), primary_key=True, index=True
        )
        pays: Mapped[str] = mapped_column(
            String(16), nullable=False, server_default=SHARED_PAYS_OWNER
        )
        granted_by: Mapped[uuid.UUID] = mapped_column(
            UUID(as_uuid=True), nullable=False
        )
        granted_at: Mapped[datetime] = mapped_column(
            DateTime(timezone=True), server_default=func.now(), nullable=False
        )

    class AISkillGrant(Base):  # type: ignore[misc]  # host-provided declarative Base is dynamic; mypy cannot check it
        """Mirror of :class:`AIAgentGrant` for skills (shape only —
        skill grants ship now so the table is symmetric; UI consumers
        land later)."""

        __tablename__ = "ai_skill_grants"

        skill_id: Mapped[uuid.UUID] = mapped_column(
            UUID(as_uuid=True),
            ForeignKey("ai_skills.id", ondelete="CASCADE"),
            primary_key=True,
        )
        grantee_company_id: Mapped[uuid.UUID] = mapped_column(
            UUID(as_uuid=True), primary_key=True, index=True
        )
        pays: Mapped[str] = mapped_column(
            String(16), nullable=False, server_default=SHARED_PAYS_OWNER
        )
        granted_by: Mapped[uuid.UUID] = mapped_column(
            UUID(as_uuid=True), nullable=False
        )
        granted_at: Mapped[datetime] = mapped_column(
            DateTime(timezone=True), server_default=func.now(), nullable=False
        )

    # ── Autonomous-agent run ledger + per-action audit ──────────────────

    class AgentRun(Base):  # type: ignore[misc]  # host-provided declarative Base is dynamic; mypy cannot check it
        """One autonomous agent run — the queryable record of a reactive
        multi-step execution. The durable state lives in Temporal
        (``temporal_workflow_id``); this row is for listing/monitoring and
        enforcing run-level caps."""

        __tablename__ = "agent_runs"

        id: Mapped[uuid.UUID] = mapped_column(
            UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
        )
        agent_id: Mapped[uuid.UUID] = mapped_column(
            UUID(as_uuid=True),
            ForeignKey("ai_agent_configs.id", ondelete="CASCADE"),
            index=True,
            nullable=False,
        )
        acting_company_id: Mapped[uuid.UUID] = mapped_column(
            UUID(as_uuid=True), index=True, nullable=False
        )
        paying_company_id: Mapped[uuid.UUID | None] = mapped_column(
            UUID(as_uuid=True), nullable=True
        )
        trigger: Mapped[str | None] = mapped_column(String(64), nullable=True)
        status: Mapped[str] = mapped_column(
            String(32), nullable=False, server_default=RUN_RUNNING, index=True
        )
        step_count: Mapped[int] = mapped_column(
            Integer, nullable=False, server_default="0"
        )
        cost_usd: Mapped[Any] = mapped_column(
            Numeric(12, 4), nullable=False, server_default="0"
        )
        temporal_workflow_id: Mapped[str | None] = mapped_column(
            String(255), nullable=True
        )
        # JSON-encoded list of {token, tool, status} approval records.
        approvals: Mapped[str | None] = mapped_column(Text, nullable=True)
        started_at: Mapped[datetime] = mapped_column(
            DateTime(timezone=True), server_default=func.now(), nullable=False
        )
        ended_at: Mapped[datetime | None] = mapped_column(
            DateTime(timezone=True), nullable=True
        )

    class AgentActionAudit(Base):  # type: ignore[misc]  # host-provided declarative Base is dynamic; mypy cannot check it
        """Immutable, append-only record of every tool-policy decision the
        gate makes (allow / deny / approval) and its resolution. Complements
        the authz service's ``authz_audit`` (which records the delegation
        ``/check``) — this is the broader tool-dispatch record."""

        __tablename__ = "agent_action_audit"

        id: Mapped[uuid.UUID] = mapped_column(
            UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
        )
        agent_run_id: Mapped[uuid.UUID | None] = mapped_column(
            UUID(as_uuid=True), index=True, nullable=True
        )
        agent_id: Mapped[uuid.UUID] = mapped_column(
            UUID(as_uuid=True), index=True, nullable=False
        )
        tool_name: Mapped[str] = mapped_column(String(128), nullable=False)
        acting_company_id: Mapped[uuid.UUID] = mapped_column(
            UUID(as_uuid=True), index=True, nullable=False
        )
        target_company_id: Mapped[uuid.UUID | None] = mapped_column(
            UUID(as_uuid=True), nullable=True
        )
        paying_company_id: Mapped[uuid.UUID | None] = mapped_column(
            UUID(as_uuid=True), nullable=True
        )
        decision: Mapped[str] = mapped_column(String(32), nullable=False)
        reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
        # SHA-256 of the tool args (never the raw args — avoids storing PII).
        args_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
        created_at: Mapped[datetime] = mapped_column(
            DateTime(timezone=True), server_default=func.now(), nullable=False
        )

    return {
        "AISkill": AISkill,
        "AIAgentConfig": AIAgentConfig,
        "AIAgentSkillLink": AIAgentSkillLink,
        "AIAgentGrant": AIAgentGrant,
        "AISkillGrant": AISkillGrant,
        "AgentRun": AgentRun,
        "AgentActionAudit": AgentActionAudit,
    }


# ── Pydantic schemas ──────────────────────────────────────────────────────────
#
# These are pure data shapes — no SQLAlchemy involvement — so they can be
# imported and used directly from the host without going through the factory.


class Message(BaseModel):
    message: str


# Skills -----------------------------------------------------------------------


class AISkillPublic(BaseModel):
    id: uuid.UUID
    company_id: uuid.UUID
    name: str
    label: str | None = None
    description: str | None = None
    icon: str | None = None
    kind: str = SKILL_KIND_PROMPT
    modality: str = MODALITY_ANY
    content: str | None = None
    source_app: str | None = None
    is_active: bool
    agent_only: bool = False
    created_at: datetime

    model_config = {"from_attributes": True}


class AISkillCreate(BaseModel):
    name: str
    label: str | None = None
    description: str | None = None
    icon: str | None = None
    kind: str = SKILL_KIND_PROMPT
    modality: str = MODALITY_ANY
    content: str | None = None
    is_active: bool = True
    agent_only: bool = False


class AISkillUpdate(BaseModel):
    # Notably absent: source_app. Once set by a SkillBundle sync, it's locked.
    name: str | None = None
    label: str | None = None
    description: str | None = None
    icon: str | None = None
    kind: str | None = None
    modality: str | None = None
    content: str | None = None
    is_active: bool | None = None
    agent_only: bool | None = None


class AISkillsPublic(BaseModel):
    data: list[AISkillPublic]
    count: int


# ── Sync schemas (M2M endpoint POST /ai-skills/sync) ─────────────────────────
#
# Vertical apps (restoration, future wealth-mgmt, etc.) call /sync at startup
# to upsert their YAML-defined skills into the platform DB so they appear in
# the AI Admin UI. The vertical's app_id namespaces the skill names — e.g.
# the restoration "photo_tagger" YAML becomes "restoration:photo_tagger" in DB.


class AISkillSyncItem(BaseModel):
    """A single skill in a sync batch — bare name; namespacing applied server-side."""

    name: str  # bare name, e.g. "photo_tagger" — qualified to "<app>:<name>" on insert
    label: str | None = None
    description: str | None = None
    icon: str | None = None
    kind: str = SKILL_KIND_PROMPT
    modality: str = MODALITY_ANY
    content: str | None = None


class AISkillSyncRequest(BaseModel):
    source_app: str
    company_id: uuid.UUID
    skills: list[AISkillSyncItem]


class AISkillSyncResultItem(BaseModel):
    name: str  # qualified name, e.g. "restoration:photo_tagger"
    skill_id: uuid.UUID
    status: str  # "created" | "updated" | "unchanged"


class AISkillSyncResponse(BaseModel):
    source_app: str
    created: list[AISkillSyncResultItem]
    updated: list[AISkillSyncResultItem]
    unchanged: list[AISkillSyncResultItem]


# Agent Configs ----------------------------------------------------------------


class AIAgentConfigPublic(BaseModel):
    id: uuid.UUID
    # Phase G — nullable for ``scope='platform'`` rows.
    company_id: uuid.UUID | None = None
    scope: str = SCOPE_COMPANY
    name: str
    label: str | None = None
    description: str | None = None
    icon: str | None = None
    system_prompt: str | None = None
    provider_type: str
    model_name: str
    model_configuration: str | None = None
    response_format: str | None = None
    role_id: uuid.UUID | None = None
    source_app: str | None = None
    is_active: bool
    created_at: datetime
    skills: list[AISkillPublic] = []
    # G7 — per-tool approval policy: {skill_id (str): approval_mode}. Only links
    # with a non-default mode appear; the UI renders a selector per attached tool.
    skill_modes: dict[str, str] = {}

    model_config = {"from_attributes": True}


class AIAgentConfigCreate(BaseModel):
    name: str
    label: str | None = None
    description: str | None = None
    icon: str | None = None
    system_prompt: str | None = None
    provider_type: str = "anthropic"
    model_name: str = "claude-3-5-sonnet-20240620"
    model_configuration: str | None = None
    response_format: str | None = None
    role_id: uuid.UUID | None = None
    is_active: bool = True
    skill_ids: list[uuid.UUID] = []
    # G7 — optional per-tool approval mode: {skill_id (str): approval_mode}.
    skill_modes: dict[str, str] = {}
    # Phase G — visibility scope. Defaults to per-tenant. The router
    # rejects ``scope='platform'`` from non-platform-admins.
    scope: str = SCOPE_COMPANY


class AIAgentConfigUpdate(BaseModel):
    name: str | None = None
    label: str | None = None
    description: str | None = None
    icon: str | None = None
    system_prompt: str | None = None
    provider_type: str | None = None
    model_name: str | None = None
    model_configuration: str | None = None
    response_format: str | None = None
    role_id: uuid.UUID | None = None
    is_active: bool | None = None
    skill_ids: list[uuid.UUID] | None = None
    skill_modes: dict[str, str] = {}  # G7 — per-tool approval mode by skill_id
    scope: str | None = None


class AIAgentConfigsPublic(BaseModel):
    data: list[AIAgentConfigPublic]
    count: int


# ── Agent sync schemas (M2M endpoint POST /ai-agents/sync) ───────────────────
#
# Vertical apps call /ai-agents/sync at startup to upsert the agent
# definitions they ship as YAML. The `skill_names` list references **bare**
# skill names — the sync endpoint qualifies them with the source_app prefix
# (e.g. "photo_tagger" → "restoration:photo_tagger") and resolves to skill
# IDs to populate ai_agent_skill_links. Cross-app skill references (e.g.
# attaching a built-in or another app's skill) are allowed if the qualifier
# is explicit ("smart_llm:summarize", "cooling-tower:detect_unit").


class AIAgentSyncItem(BaseModel):
    """A single agent in a sync batch — bare name; namespacing applied server-side."""

    name: str  # bare name, e.g. "photo_triage" — qualified to "<app>:<name>" on insert
    label: str | None = None
    description: str | None = None
    icon: str | None = None
    system_prompt: str | None = None
    provider_type: str = "anthropic"
    model_name: str = "claude-3-5-sonnet-20240620"
    model_configuration: str | None = None
    response_format: str | None = None
    # Skill names attached to this agent. Bare names (e.g. "photo_tagger")
    # resolve to the vertical app's own namespace ("<source_app>:photo_tagger").
    # Names with an explicit ":" are looked up as-is — lets verticals attach
    # built-in skills or another app's skill ("smart_llm:summarize").
    skill_names: list[str] = []
    # G7 — tool-backed attachments with a per-tool approval policy. Each entry:
    # {"name": <tool/skill name>, "approval_mode": auto|allow|require_approval|
    # deny}. Resolved + namespaced like skill_names; the resolved link carries
    # the approval_mode the agent loop's ToolPolicyGate enforces.
    tools: list[dict[str, Any]] = []


class AIAgentSyncRequest(BaseModel):
    source_app: str
    company_id: uuid.UUID
    agents: list[AIAgentSyncItem]


class AIAgentSyncResultItem(BaseModel):
    name: str  # qualified, e.g. "restoration:photo_triage"
    agent_id: uuid.UUID
    status: str  # "created" | "updated" | "unchanged"
    unresolved_skills: list[
        str
    ] = []  # populated when a referenced skill name doesn't exist


class AIAgentSyncResponse(BaseModel):
    source_app: str
    created: list[AIAgentSyncResultItem]
    updated: list[AIAgentSyncResultItem]
    unchanged: list[AIAgentSyncResultItem]


# LLM API Keys (managed by smart-llm DatabaseKeyStore) -------------------------


class CompanyLLMApiKeyPublic(BaseModel):
    id: uuid.UUID
    company_id: uuid.UUID
    provider: str
    is_active: bool
    created_at: datetime | None = None


class CompanyLLMApiKeyCreate(BaseModel):
    provider: str
    api_key: str


class CompanyLLMApiKeysPublic(BaseModel):
    data: list[CompanyLLMApiKeyPublic]
    count: int
