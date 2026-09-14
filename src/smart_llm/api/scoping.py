"""Phase G — visibility-scope SQLAlchemy filters.

Every per-tenant query against ``ai_agent_configs`` / ``ai_skills``
should run through :func:`visible_agent_filter` /
:func:`visible_skill_filter` instead of hand-rolling
``WHERE company_id = current``. Both functions yield a single
``ColumnElement`` that resolves to ``True`` for:

- ``scope='platform'`` rows (visible everywhere).
- ``scope='company'`` rows whose ``company_id`` matches.
- ``scope='shared'`` rows where:
  - the caller is the owner, OR
  - a grant row exists for the caller's company.

``current_company_id=None`` means a platform-level caller
(``system_admin``/``platform_admin``); they see everything.

Centralised so the agents router, skills router, the Temporal
``run_agent_node`` activity, and the streaming router all share one
implementation. Drift between them was the original Phase G risk;
this module removes that surface.
"""

from typing import Any
from uuid import UUID

from sqlalchemy import ColumnElement, and_, or_, select

from smart_llm.db.models import (
    SCOPE_COMPANY,
    SCOPE_PLATFORM,
    SCOPE_SHARED,
)


def visible_agent_filter(
    AIAgentConfig: Any,
    AIAgentGrant: Any,
    current_company_id: UUID | str | None,
) -> ColumnElement[bool]:
    """Return a SQLAlchemy filter expression for ``AIAgentConfig``.

    Compose with other ``WHERE`` clauses via :func:`sqlalchemy.and_`
    or by passing it as an additional positional to ``.where(...)``.
    """
    if current_company_id is None:
        # Platform-level admin sees every row.
        return _true_expr()

    # Pass through whatever the caller gave us — SQLAlchemy's UUID
    # type adapter handles both ``uuid.UUID`` and string forms against
    # Postgres, but SQLite-backed unit tests need the native UUID
    # object. Coerce strings to UUID for safety.
    cid = current_company_id
    if isinstance(cid, str):
        try:
            cid = UUID(cid)
        except (ValueError, TypeError):
            pass
    return or_(
        AIAgentConfig.scope == SCOPE_PLATFORM,
        and_(
            AIAgentConfig.scope == SCOPE_COMPANY,
            AIAgentConfig.company_id == cid,
        ),
        and_(
            AIAgentConfig.scope == SCOPE_SHARED,
            or_(
                AIAgentConfig.company_id == cid,
                AIAgentConfig.id.in_(
                    select(AIAgentGrant.agent_id).where(
                        AIAgentGrant.grantee_company_id == cid
                    )
                ),
            ),
        ),
    )


def visible_skill_filter(
    AISkill: Any,
    AISkillGrant: Any,
    current_company_id: UUID | str | None,
) -> ColumnElement[bool]:
    """Symmetric helper for ``AISkill``. Same predicate shape as
    :func:`visible_agent_filter`; lets the skills router widen its
    lookups without duplicating the OR-tree."""
    if current_company_id is None:
        return _true_expr()

    cid = current_company_id
    if isinstance(cid, str):
        try:
            cid = UUID(cid)
        except (ValueError, TypeError):
            pass
    return or_(
        AISkill.scope == SCOPE_PLATFORM,
        and_(
            AISkill.scope == SCOPE_COMPANY,
            AISkill.company_id == cid,
        ),
        and_(
            AISkill.scope == SCOPE_SHARED,
            or_(
                AISkill.company_id == cid,
                AISkill.id.in_(
                    select(AISkillGrant.skill_id).where(
                        AISkillGrant.grantee_company_id == cid
                    )
                ),
            ),
        ),
    )


def _true_expr() -> ColumnElement[bool]:
    """Always-true expression usable inside ``where(...)`` so callers
    can compose without branching on ``None``."""
    from sqlalchemy import literal

    return literal(True)


def resolve_paying_company_id(
    agent: Any,
    triggering_company_id: UUID | str | None,
    *,
    grant_row: Any | None = None,
) -> str | None:
    """Phase G — who pays the LLM key bill for this call?

    - ``scope='company'`` → the agent's owner (its own ``company_id``).
    - ``scope='platform'`` → ``None`` (platform-level key resolver).
    - ``scope='shared'``  → consult the grant row's ``pays`` field;
      ``'owner'`` returns the agent's owner, ``'grantee'`` returns
      the triggering tenant. If no grant row is supplied we fall back
      to the owner (safer default — owner sees the spend; grantee
      can't accidentally bill themselves for an agent they don't yet
      have a grant for).
    """
    scope = getattr(agent, "scope", SCOPE_COMPANY)
    if scope == SCOPE_PLATFORM:
        return None
    if scope == SCOPE_SHARED and grant_row is not None:
        pays = getattr(grant_row, "pays", "owner")
        if pays == "grantee" and triggering_company_id is not None:
            return str(triggering_company_id)
    owner = getattr(agent, "company_id", None)
    return str(owner) if owner else None
