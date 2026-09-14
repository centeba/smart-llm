"""Phase-E4 REST endpoints — usage events + monthly budget editor.

Mounted by the host so the AI admin "Usage" tab can chart spend and
flip the company-level cap. Reads are admin-gated; the budget setter
is platform_admin-only by default — hosts that prefer to let
``company_admin`` adjust their own budget can pass a different
``budget_dep``.
"""

# NOTE: do NOT add ``from __future__ import annotations`` here — see the
# matching comment in ``agents.py``. Closure-typed dep params would
# silently demote to query params under PEP 563.

import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select


class _BudgetUpdate(BaseModel):
    monthly_ai_budget_usd: float
    # Platform-managed billing: the operator sets any tenant's cap by id. A
    # platform/system admin has no company_id of their own, so the target
    # company must be named explicitly.
    company_id: uuid.UUID


def create_usage_router(
    *,
    SessionDep: Any,
    CurrentUser: Any,
    CompanyAdminDep: Any,
    AIUsageEvent: Any,
    company_settings_loader: Any,
    company_settings_setter: Any,
    internal_gate_dep: Any = None,
    notification_log_model: Any = None,
    redis_factory: Any = None,
) -> APIRouter:
    """Build the usage router.

    ``company_settings_loader(session, company_id) -> float`` returns
    the company's current monthly cap (0.0 when unset).
    ``company_settings_setter(session, company_id, value) -> None``
    persists a new cap. Both callbacks live in the host because the
    ``company_settings`` model belongs to the host service.
    """
    router = APIRouter(prefix="/ai-usage", tags=["ai-usage"])

    @router.get("/")
    async def list_events(
        session: SessionDep,
        user: CurrentUser,
        days: int = 30,
        agent_id: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        """Return individual events + per-agent totals for the window."""
        if not getattr(user, "is_company_admin", False):
            raise HTTPException(403, "Admin only")
        company_id = getattr(user, "company_id", None)
        # system_admin / platform_admin accounts have no company_id.
        # Return a cross-tenant aggregate so the Usage tab shows platform-
        # wide spend instead of an empty state.
        if not company_id:
            cutoff = datetime.now(timezone.utc) - timedelta(days=days)
            events_q = (
                select(AIUsageEvent)
                .where(AIUsageEvent.created_at >= cutoff)
                .order_by(AIUsageEvent.created_at.desc())
                .limit(500)
            )
            if agent_id is not None:
                events_q = events_q.where(AIUsageEvent.agent_id == agent_id)
            events_rows = (await session.execute(events_q)).scalars().all()
            # Platform billing breakdown — aggregate by
            # (company_id, user_id, agent_id, skill_id) so the operator can
            # attribute spend per company AND per user AND per agent/skill.
            cross_agg: dict[tuple[Any, ...], dict[str, Any]] = {}
            for e in events_rows:
                key = (
                    str(e.company_id),
                    str(e.user_id) if e.user_id else None,
                    str(e.agent_id) if e.agent_id else None,
                    str(e.skill_id) if e.skill_id else None,
                )
                if key not in cross_agg:
                    cross_agg[key] = {
                        "company_id": key[0],
                        "user_id": key[1],
                        "agent_id": key[2],
                        "skill_id": key[3],
                        "usd_cost": 0.0,
                        "input_tokens": 0,
                        "output_tokens": 0,
                    }
                cross_agg[key]["usd_cost"] += float(e.usd_cost or 0)
                cross_agg[key]["input_tokens"] += int(e.input_tokens or 0)
                cross_agg[key]["output_tokens"] += int(e.output_tokens or 0)
            return {
                "scope": "platform",
                "events": [
                    {
                        "id": str(e.id),
                        "company_id": str(e.company_id),
                        "user_id": str(e.user_id) if e.user_id else None,
                        "agent_id": str(e.agent_id) if e.agent_id else None,
                        "skill_id": str(e.skill_id) if e.skill_id else None,
                        "provider": e.provider,
                        "model": e.model,
                        "input_tokens": e.input_tokens,
                        "output_tokens": e.output_tokens,
                        "usd_cost": e.usd_cost,
                        "created_at": e.created_at.isoformat(),
                    }
                    for e in events_rows
                ],
                "by_company_user_skill": list(cross_agg.values()),
                "monthly_budget_usd": 0.0,  # platform budget cap: Phase G
            }

        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        stmt = (
            select(AIUsageEvent)
            .where(
                AIUsageEvent.company_id == company_id,
                AIUsageEvent.created_at >= cutoff,
            )
            .order_by(AIUsageEvent.created_at.desc())
        )
        if agent_id is not None:
            stmt = stmt.where(AIUsageEvent.agent_id == agent_id)
        rows = (await session.execute(stmt.limit(500))).scalars().all()

        # Per-agent aggregates so the chart doesn't need to bucket
        # client-side over potentially thousands of events.
        agg_stmt = (
            select(
                AIUsageEvent.agent_id,
                func.sum(AIUsageEvent.usd_cost).label("cost"),
                func.sum(AIUsageEvent.input_tokens).label("in_tokens"),
                func.sum(AIUsageEvent.output_tokens).label("out_tokens"),
            )
            .where(
                AIUsageEvent.company_id == company_id,
                AIUsageEvent.created_at >= cutoff,
            )
            .group_by(AIUsageEvent.agent_id)
        )
        agg = (await session.execute(agg_stmt)).all()

        return {
            "scope": "company",
            "events": [
                {
                    "id": str(r.id),
                    "user_id": str(r.user_id) if r.user_id else None,
                    "agent_id": str(r.agent_id) if r.agent_id else None,
                    "skill_id": str(r.skill_id) if r.skill_id else None,
                    "provider": r.provider,
                    "model": r.model,
                    "input_tokens": r.input_tokens,
                    "output_tokens": r.output_tokens,
                    "usd_cost": r.usd_cost,
                    "created_at": r.created_at.isoformat(),
                }
                for r in rows
            ],
            "by_agent": [
                {
                    "agent_id": str(row.agent_id) if row.agent_id else None,
                    "usd_cost": float(row.cost or 0),
                    "input_tokens": int(row.in_tokens or 0),
                    "output_tokens": int(row.out_tokens or 0),
                }
                for row in agg
            ],
            "monthly_budget_usd": await company_settings_loader(
                session, str(company_id)
            ),
        }

    @router.get("/cost-dashboard")
    async def cost_dashboard(
        session: SessionDep,
        user: CurrentUser,
        days: int = 30,
    ) -> dict[str, Any]:
        """Per-tenant AI cost dashboard (SB-23) over the ``ai_usage_events`` ledger.

        Company admins see THEIR company's spend broken down by model, by user,
        and by agent, plus a daily cost trend and their budget utilisation.
        Platform/system admins (no company_id) get the PLATFORM view: spend
        broken down **by tenant** (``by_company``) — the operator's per-tenant
        cost report — plus by-model and the daily trend across all tenants.
        """
        if not getattr(user, "is_company_admin", False):
            raise HTTPException(403, "Admin only")
        company_id = getattr(user, "company_id", None)
        days = max(1, min(int(days), 365))
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)

        where = [AIUsageEvent.created_at >= cutoff]
        if company_id:
            where.append(AIUsageEvent.company_id == company_id)

        # ── Totals ──────────────────────────────────────────────────────────
        totals_row = (
            await session.execute(
                select(
                    func.coalesce(func.sum(AIUsageEvent.usd_cost), 0).label("cost"),
                    func.coalesce(func.sum(AIUsageEvent.input_tokens), 0).label(
                        "in_tok"
                    ),
                    func.coalesce(func.sum(AIUsageEvent.output_tokens), 0).label(
                        "out_tok"
                    ),
                    func.count().label("calls"),
                ).where(*where)
            )
        ).one()
        total_cost = float(totals_row.cost or 0)

        # ── Breakdown by model+provider (the cost drivers) ──────────────────
        by_model = [
            {
                "provider": row.provider,
                "model": row.model,
                "usd_cost": float(row.cost or 0),
                "calls": int(row.calls or 0),
            }
            for row in (
                await session.execute(
                    select(
                        AIUsageEvent.provider,
                        AIUsageEvent.model,
                        func.sum(AIUsageEvent.usd_cost).label("cost"),
                        func.count().label("calls"),
                    )
                    .where(*where)
                    .group_by(AIUsageEvent.provider, AIUsageEvent.model)
                    .order_by(func.sum(AIUsageEvent.usd_cost).desc())
                )
            ).all()
        ]

        # ── Company-scoped: by user + by agent. Platform-scoped: by tenant. ──
        by_user: list[dict[str, Any]] = []
        by_agent: list[dict[str, Any]] = []
        by_company: list[dict[str, Any]] = []
        if company_id:
            by_user = [
                {
                    "user_id": str(r.user_id) if r.user_id else None,
                    "usd_cost": float(r.cost or 0),
                }
                for r in (
                    await session.execute(
                        select(
                            AIUsageEvent.user_id,
                            func.sum(AIUsageEvent.usd_cost).label("cost"),
                        )
                        .where(*where)
                        .group_by(AIUsageEvent.user_id)
                        .order_by(func.sum(AIUsageEvent.usd_cost).desc())
                        .limit(50)
                    )
                ).all()
            ]
            by_agent = [
                {
                    "agent_id": str(r.agent_id) if r.agent_id else None,
                    "usd_cost": float(r.cost or 0),
                }
                for r in (
                    await session.execute(
                        select(
                            AIUsageEvent.agent_id,
                            func.sum(AIUsageEvent.usd_cost).label("cost"),
                        )
                        .where(*where)
                        .group_by(AIUsageEvent.agent_id)
                        .order_by(func.sum(AIUsageEvent.usd_cost).desc())
                    )
                ).all()
            ]
        else:
            by_company = [
                {
                    "company_id": str(r.company_id),
                    "usd_cost": float(r.cost or 0),
                    "calls": int(r.calls or 0),
                }
                for r in (
                    await session.execute(
                        select(
                            AIUsageEvent.company_id,
                            func.sum(AIUsageEvent.usd_cost).label("cost"),
                            func.count().label("calls"),
                        )
                        .where(*where)
                        .group_by(AIUsageEvent.company_id)
                        .order_by(func.sum(AIUsageEvent.usd_cost).desc())
                    )
                ).all()
            ]

        # ── Daily cost trend (bucketed in Python — portable across Postgres +
        # the sqlite test DB; the window bounds the row count). ──────────────
        daily: defaultdict[str, Decimal] = defaultdict(Decimal)
        for created_at, cost in (
            await session.execute(
                select(AIUsageEvent.created_at, AIUsageEvent.usd_cost).where(*where)
            )
        ).all():
            daily[created_at.date().isoformat()] += Decimal(str(cost or 0))
        daily_cost = [{"date": d, "usd_cost": float(daily[d])} for d in sorted(daily)]

        budget = (
            await company_settings_loader(session, str(company_id))
            if company_id
            else 0.0
        )
        return {
            "scope": "company" if company_id else "platform",
            "window_days": days,
            "total_usd_cost": total_cost,
            "total_input_tokens": int(totals_row.in_tok or 0),
            "total_output_tokens": int(totals_row.out_tok or 0),
            "total_calls": int(totals_row.calls or 0),
            "monthly_budget_usd": budget,
            "budget_used_pct": round(total_cost / budget * 100, 1) if budget else None,
            "by_model": by_model,
            "by_user": by_user,
            "by_agent": by_agent,
            "by_company": by_company,
            "daily_cost": daily_cost,
        }

    @router.patch("/budget")
    async def set_budget(
        body: _BudgetUpdate,
        session: SessionDep,
        user: CompanyAdminDep,
    ) -> dict[str, Any]:
        """Set a tenant's monthly AI budget cap.

        Platform-managed: budgets and billing are controlled centrally by the
        platform operator, not by each company. Only a platform/system admin
        may write a cap, and they name the target ``company_id`` in the body —
        a company admin can view its usage but not change its own cap.
        """
        if not getattr(user, "is_platform_admin", False):
            raise HTTPException(403, "Budgets are managed by the platform operator")
        if body.monthly_ai_budget_usd < 0:
            raise HTTPException(400, "Budget must be ≥ 0")
        await company_settings_setter(
            session, str(body.company_id), body.monthly_ai_budget_usd
        )
        await session.commit()
        return {
            "company_id": str(body.company_id),
            "monthly_ai_budget_usd": body.monthly_ai_budget_usd,
        }

    # ── Phase F — internal cross-service gate ────────────────────────────
    # External SentinelBuild services (pages-api, doc-vault, esign,
    # mit-stack) don't carry their own ``ai_usage_events`` table. When
    # they want to invoke an LLM they POST here with the internal
    # service secret; this endpoint runs the same gate that integration-
    # hub's own routes run inline. On first cap trip the bell-icon
    # alert + bus publish fire here so every blocked call across the
    # platform funnels through one set of side-effect plumbing.
    if internal_gate_dep is not None:
        from fastapi import status as _status

        from smart_llm.usage import (
            BudgetExceededError as _BudgetExceededError,
        )
        from smart_llm.usage import (
            assert_llm_allowed_for_tenant as _assert_llm_allowed_for_tenant,
        )

        class _AssertBody(BaseModel):
            company_id: uuid.UUID

        @router.post(
            "/assert-allowed",
            status_code=_status.HTTP_204_NO_CONTENT,
            include_in_schema=False,
        )
        async def assert_allowed(
            body: _AssertBody,
            session: SessionDep,
            _: internal_gate_dep,  # auth: INTERNAL_SERVICE_SECRET bearer
        ) -> None:
            cap = await company_settings_loader(session, str(body.company_id))
            redis = redis_factory() if redis_factory is not None else None
            try:
                await _assert_llm_allowed_for_tenant(
                    session,
                    company_id=str(body.company_id),
                    UsageModel=AIUsageEvent,
                    monthly_budget_usd=cap,
                    notification_log_model=notification_log_model,
                    redis=redis,
                )
                # commit the notification-log row that fired side-effects
                await session.commit()
            except _BudgetExceededError as exc:
                # The log row may have been added before raise; commit it
                # so the chassis bell sees the alert.
                await session.commit()
                raise HTTPException(
                    status_code=_status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="AI budget exhausted — contact your admin.",
                ) from exc

    return router
