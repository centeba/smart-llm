"""Phase G — visibility-scope filter + paid-by routing tests.

Pure unit tests against an in-memory aiosqlite DB. Verifies that
``visible_agent_filter`` returns the right rows for each
combination of caller-scope × row-scope × grant-state, and that
``resolve_paying_company_id`` selects the right paying tenant.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy import (
    DateTime,
    ForeignKey,
    String,
    select,
)
from sqlalchemy.dialects.postgresql import UUID  # works against sqlite too
from sqlalchemy.ext.asyncio import (
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from smart_llm.api.scoping import (
    resolve_paying_company_id,
    visible_agent_filter,
)
from smart_llm.db.models import (
    SCOPE_COMPANY,
    SCOPE_PLATFORM,
    SCOPE_SHARED,
    SHARED_PAYS_GRANTEE,
    SHARED_PAYS_OWNER,
)

# ── In-memory schema — only the columns the filter needs ────────────────────


class _Base(DeclarativeBase):
    pass


class _Agent(_Base):
    __tablename__ = "_agents"
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    scope: Mapped[str] = mapped_column(
        String(32), nullable=False, default=SCOPE_COMPANY
    )
    name: Mapped[str] = mapped_column(String(255))
    provider_type: Mapped[str] = mapped_column(String(50), default="anthropic")


class _Grant(_Base):
    __tablename__ = "_grants"
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("_agents.id"),
        primary_key=True,
    )
    grantee_company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True
    )
    pays: Mapped[str] = mapped_column(String(16), default=SHARED_PAYS_OWNER)
    granted_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(_Base.metadata.create_all)
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
    async with SessionLocal() as session:
        yield session
    await engine.dispose()


# ── Test fixtures — three companies + one agent per scope ───────────────────


@pytest_asyncio.fixture
async def seeded(db):
    company_a = uuid.uuid4()
    company_b = uuid.uuid4()
    company_c = uuid.uuid4()
    admin = uuid.uuid4()

    a_company = _Agent(company_id=company_a, scope=SCOPE_COMPANY, name="A-only")
    a_platform = _Agent(
        company_id=None, scope=SCOPE_PLATFORM, name="platform-summarizer"
    )
    a_shared = _Agent(company_id=company_a, scope=SCOPE_SHARED, name="A-shared")
    db.add_all([a_company, a_platform, a_shared])
    await db.flush()

    # Grant the shared agent to company_b — pays=owner.
    db.add(
        _Grant(
            agent_id=a_shared.id,
            grantee_company_id=company_b,
            pays=SHARED_PAYS_OWNER,
            granted_by=admin,
        )
    )
    await db.commit()

    return {
        "company_a": company_a,
        "company_b": company_b,
        "company_c": company_c,
        "agent_company": a_company,
        "agent_platform": a_platform,
        "agent_shared": a_shared,
    }


# ── visible_agent_filter ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_company_a_sees_own_agents_plus_platform(db, seeded):
    flt = visible_agent_filter(_Agent, _Grant, seeded["company_a"])
    rows = (await db.execute(select(_Agent).where(flt))).scalars().all()
    names = {r.name for r in rows}
    # A's own company agent + the platform agent + its own shared agent.
    assert names == {"A-only", "platform-summarizer", "A-shared"}


@pytest.mark.asyncio
async def test_company_b_sees_platform_and_granted_shared(db, seeded):
    flt = visible_agent_filter(_Agent, _Grant, seeded["company_b"])
    rows = (await db.execute(select(_Agent).where(flt))).scalars().all()
    names = {r.name for r in rows}
    # No A-only (it's company scope to A); platform agent is visible
    # everywhere; the shared agent is visible via the grant row.
    assert names == {"platform-summarizer", "A-shared"}


@pytest.mark.asyncio
async def test_company_c_sees_platform_only(db, seeded):
    """Company C has no grants — only the platform agent is visible."""
    flt = visible_agent_filter(_Agent, _Grant, seeded["company_c"])
    rows = (await db.execute(select(_Agent).where(flt))).scalars().all()
    names = {r.name for r in rows}
    assert names == {"platform-summarizer"}


@pytest.mark.asyncio
async def test_platform_admin_sees_everything(db, seeded):
    """``current_company_id=None`` means platform-level admin."""
    flt = visible_agent_filter(_Agent, _Grant, None)
    rows = (await db.execute(select(_Agent).where(flt))).scalars().all()
    names = {r.name for r in rows}
    assert names == {"A-only", "platform-summarizer", "A-shared"}


# ── resolve_paying_company_id ───────────────────────────────────────────────


def test_paying_company_scope_company():
    """``scope='company'`` always bills the owner."""
    owner = uuid.uuid4()
    agent = _Agent(
        company_id=owner, scope=SCOPE_COMPANY, name="x", provider_type="anthropic"
    )
    paying = resolve_paying_company_id(agent, triggering_company_id=uuid.uuid4())
    assert paying == str(owner)


def test_paying_company_scope_platform():
    """``scope='platform'`` returns None → platform key path."""
    agent = _Agent(company_id=None, scope=SCOPE_PLATFORM, name="x")
    paying = resolve_paying_company_id(agent, triggering_company_id=uuid.uuid4())
    assert paying is None


def test_paying_company_scope_shared_owner_pays():
    owner = uuid.uuid4()
    grantee = uuid.uuid4()
    agent = _Agent(company_id=owner, scope=SCOPE_SHARED, name="x")
    grant = _Grant(
        agent_id=agent.id or uuid.uuid4(),
        grantee_company_id=grantee,
        pays=SHARED_PAYS_OWNER,
        granted_by=uuid.uuid4(),
    )
    paying = resolve_paying_company_id(
        agent, triggering_company_id=grantee, grant_row=grant
    )
    assert paying == str(owner)


def test_paying_company_scope_shared_grantee_pays():
    owner = uuid.uuid4()
    grantee = uuid.uuid4()
    agent = _Agent(company_id=owner, scope=SCOPE_SHARED, name="x")
    grant = _Grant(
        agent_id=agent.id or uuid.uuid4(),
        grantee_company_id=grantee,
        pays=SHARED_PAYS_GRANTEE,
        granted_by=uuid.uuid4(),
    )
    paying = resolve_paying_company_id(
        agent, triggering_company_id=grantee, grant_row=grant
    )
    assert paying == str(grantee)


def test_paying_company_scope_shared_no_grant_defaults_to_owner():
    """No grant row + scope=shared = the caller is the owner (the
    visible_agent_filter found the row via owner-match). Owner pays."""
    owner = uuid.uuid4()
    agent = _Agent(company_id=owner, scope=SCOPE_SHARED, name="x")
    paying = resolve_paying_company_id(
        agent, triggering_company_id=owner, grant_row=None
    )
    assert paying == str(owner)
