"""Per-tenant cost dashboard endpoint (SB-23)."""

import uuid
from typing import Annotated, Any

import pytest
import pytest_asyncio
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from smart_llm.api.routers.usage import create_usage_router
from smart_llm.usage import UsageContext, make_usage_model, record_usage


class _Base(DeclarativeBase):
    pass


UsageEvent = make_usage_model(_Base)


class _FakeUser:
    def __init__(self, company_id: uuid.UUID | None) -> None:
        self.company_id = company_id
        self.is_company_admin = True


# Mutable holder so a test can pick who is "logged in".
_current: dict[str, _FakeUser] = {"user": _FakeUser(None)}


@pytest_asyncio.fixture
async def client():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(_Base.metadata.create_all)
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
    session = SessionLocal()

    async def _get_session():
        yield session

    def _get_user() -> _FakeUser:
        return _current["user"]

    async def _loader(_s: Any, _cid: str) -> float:
        return 100.0

    async def _setter(_s: Any, _cid: str, _v: float) -> None:
        return None

    session_dep = Annotated[AsyncSession, Depends(_get_session)]
    user_dep = Annotated[Any, Depends(_get_user)]
    router = create_usage_router(
        SessionDep=session_dep,
        CurrentUser=user_dep,
        CompanyAdminDep=user_dep,
        AIUsageEvent=UsageEvent,
        company_settings_loader=_loader,
        company_settings_setter=_setter,
    )
    app = FastAPI()
    app.include_router(router)

    # Seed spend for two tenants across two models.
    global COMPANY_A, COMPANY_B
    COMPANY_A, COMPANY_B = uuid.uuid4(), uuid.uuid4()
    for company, model, in_tok, out_tok in [
        (COMPANY_A, "claude-sonnet-4-6", 1_000_000, 500_000),
        (COMPANY_A, "gpt-5", 200_000, 100_000),
        (COMPANY_B, "claude-sonnet-4-6", 300_000, 100_000),
    ]:
        await record_usage(
            session,
            UsageEvent,
            UsageContext(
                company_id=str(company),
                agent_id=str(uuid.uuid4()),
                skill_id=None,
                provider="anthropic" if "claude" in model else "openai",
                model=model,
                user_id=str(uuid.uuid4()),
            ),
            input_tokens=in_tok,
            output_tokens=out_tok,
        )
    await session.commit()

    yield TestClient(app)
    await session.close()
    await engine.dispose()


def test_company_scoped_dashboard(client):
    _current["user"] = _FakeUser(COMPANY_A)
    r = client.get("/ai-usage/cost-dashboard?days=30")
    assert r.status_code == 200
    data = r.json()
    assert data["scope"] == "company"
    assert data["total_calls"] == 2  # only company A's two events
    assert data["total_usd_cost"] > 0
    assert data["monthly_budget_usd"] == 100.0
    assert data["budget_used_pct"] is not None
    # Company A used two distinct models → two rows, no cross-tenant leak.
    assert len(data["by_model"]) == 2
    assert data["by_user"] and not data["by_company"]
    assert data["daily_cost"] and data["daily_cost"][0]["usd_cost"] > 0


def test_platform_dashboard_breaks_down_by_tenant(client):
    _current["user"] = _FakeUser(None)  # platform admin, no company
    r = client.get("/ai-usage/cost-dashboard?days=30")
    assert r.status_code == 200
    data = r.json()
    assert data["scope"] == "platform"
    assert data["total_calls"] == 3  # all tenants
    # The operator's per-tenant cost report.
    companies = {row["company_id"] for row in data["by_company"]}
    assert companies == {str(COMPANY_A), str(COMPANY_B)}


def test_non_admin_forbidden(client):
    u = _FakeUser(COMPANY_A)
    u.is_company_admin = False
    _current["user"] = u
    assert client.get("/ai-usage/cost-dashboard").status_code == 403
