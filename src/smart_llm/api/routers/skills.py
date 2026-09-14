"""AI Skill router factory.

Call create_skills_router() with the host app's dependency types and ORM models
to get a fully-wired FastAPI APIRouter.
"""

# NOTE: do NOT add ``from __future__ import annotations`` here — see the
# matching comment in ``agents.py``. Closure-typed dep params would
# silently demote to query params under PEP 563.

import uuid
from typing import Any, cast

from fastapi import APIRouter, HTTPException
from sqlalchemy import func, or_, select

# Phase M — index-on-write hook for AI Admin search.
from .. import ai_search_index as _search_index


def create_skills_router(
    *,
    SessionDep: Any,
    CurrentUser: Any,
    CompanyAdminDep: Any,
    # Authoring (create/update/delete a skill) is restricted to a platform/
    # system admin — tenants are consumers, not authors, so a company admin
    # can no longer inject an arbitrary skill/prompt. Domain skills arrive via
    # the M2M ``/sync`` endpoint (deploy-time, code-reviewed). When the host
    # doesn't wire this (older embedders/tests), it falls back to
    # CompanyAdminDep so behaviour is unchanged for them.
    PlatformAdminDep: Any = None,
    # Per-deployment domain isolation: the single domain this deployment serves
    # (e.g. "restoration"). When set, ``/sync`` rejects any batch whose
    # ``source_app`` differs — so a wealth deployment physically cannot ingest
    # restoration skills, and vice-versa. None → no enforcement (dev/back-compat).
    expected_source_app: Any = None,
    AISkill: Any,
    AISkillPublic: Any,
    AISkillCreate: Any,
    AISkillUpdate: Any,
    AISkillsPublic: Any,
    Message: Any,
    log_audit: Any,
    InternalServiceDep: Any = None,
    AISkillSyncRequest: Any = None,
    AISkillSyncResponse: Any = None,
    AISkillSyncResultItem: Any = None,
    # Phase G — see agents.py for shape.
    AISkillGrant: Any = None,
) -> APIRouter:
    """Return a router for AI skill management.

    Parameters are injected by the host application so that this module has
    zero imports from the host package (no circular dependencies).

    The sync-related parameters (``InternalServiceDep``, ``AISkillSyncRequest``,
    ``AISkillSyncResponse``, ``AISkillSyncResultItem``) are optional; if all
    four are provided, the router exposes ``POST /ai-skills/sync`` which
    vertical apps call from their backend at startup to upsert their YAML
    skills. The endpoint is guarded by ``InternalServiceDep`` (M2M-only).
    """
    # Back-compat: hosts that don't wire a platform-admin dep keep the old
    # behaviour (company admin can author). The production host wires it.
    PlatformAdminDep = PlatformAdminDep or CompanyAdminDep

    router = APIRouter(prefix="/ai-skills", tags=["ai-skills"])
    _sync_enabled = (
        InternalServiceDep is not None
        and AISkillSyncRequest is not None
        and AISkillSyncResponse is not None
        and AISkillSyncResultItem is not None
    )

    def _require_company(user: Any) -> uuid.UUID:
        if not user.company_id:
            raise HTTPException(status_code=400, detail="User has no company")
        return cast(uuid.UUID, user.company_id)

    def _is_platform_admin(user: Any) -> bool:
        """Platform/system admins see every tenant's rows. Mirrors the
        same predicate in :mod:`smart_llm.api.routers.agents`."""
        role = getattr(user, "role", None)
        return role in ("platform_admin", "system_admin")

    @router.get("/registry")
    async def list_registry_tools() -> Any:
        """Return every Python tool registered in :mod:`smart_llm.registry`.

        Used by the admin UI when creating an ``AISkill`` with
        ``kind="python_tool"`` so the user can pick a stable registry name
        from a dropdown instead of typing a free-form string.
        Admin-only — same gate as the rest of the router.
        """
        from smart_llm.registry import list_tools

        return [m.to_dict() for m in list_tools()]

    @router.get("/registry/{name}")
    async def get_registry_tool(name: str) -> Any:
        """Return a single registered tool's metadata, including its
        ``params_schema``. The workflow builder fetches this when a
        ``tool_node`` is selected so it can auto-render typed config
        fields from the schema (Phase E1)."""
        from smart_llm.registry import get_tool_meta

        meta = get_tool_meta(name)
        if meta is None:
            raise HTTPException(status_code=404, detail=f"Tool '{name}' not registered")
        return meta.to_dict()

    @router.get("/", response_model=AISkillsPublic)
    async def list_skills(
        session: SessionDep,
        current_user: CompanyAdminDep,
        skip: int = 0,
        limit: int = 100,
        search: str | None = None,
        active: bool | None = None,
        company_id: uuid.UUID | None = None,
        all_companies: bool = False,
    ) -> Any:
        # Scoping (platform admins):
        #   ?company_id=<id>    → drill into that one tenant.
        #   ?all_companies=true → full cross-tenant list (every tenant's
        #                          per-company seeded skills — noisy; opt-in).
        #   default             → own company + platform-scoped rows only.
        # Other roles are always pinned to their own company.
        filters: list[Any] = []
        if _is_platform_admin(current_user):
            if company_id is not None:
                scope_company = company_id
                if AISkillGrant is not None:
                    from ..scoping import visible_skill_filter

                    filters.append(
                        visible_skill_filter(AISkill, AISkillGrant, scope_company)
                    )
                else:
                    filters.append(AISkill.company_id == scope_company)
            elif not all_companies:
                own = getattr(current_user, "company_id", None)
                scope = [AISkill.company_id.is_(None)]  # platform-scoped
                if own is not None:
                    scope.append(AISkill.company_id == own)
                filters.append(or_(*scope))
            # else all_companies → no company filter (full cross-tenant)
        else:
            scope_company = _require_company(current_user)
            if AISkillGrant is not None:
                from ..scoping import visible_skill_filter

                filters.append(
                    visible_skill_filter(AISkill, AISkillGrant, scope_company)
                )
            else:
                filters.append(AISkill.company_id == scope_company)
        if search:
            filters.append(AISkill.name.ilike(f"%{search}%"))
        if active is not None:
            filters.append(AISkill.is_active.is_(active))
        base = select(AISkill).where(*filters)
        count_base = select(func.count()).select_from(
            select(AISkill.id).where(*filters).subquery()
        )
        count = (await session.execute(count_base)).scalar_one()
        result = await session.execute(
            base.order_by(AISkill.created_at.desc()).offset(skip).limit(limit)
        )
        skills = result.scalars().all()
        return AISkillsPublic(
            data=[AISkillPublic.model_validate(s) for s in skills], count=count
        )

    @router.get("/{skill_id}", response_model=AISkillPublic)
    async def get_skill(
        session: SessionDep,
        current_user: CompanyAdminDep,
        skill_id: uuid.UUID,
    ) -> Any:
        filters = [AISkill.id == skill_id]
        if not _is_platform_admin(current_user):
            cid = _require_company(current_user)
            if AISkillGrant is not None:
                from ..scoping import visible_skill_filter

                filters.append(visible_skill_filter(AISkill, AISkillGrant, cid))
            else:
                filters.append(AISkill.company_id == cid)
        result = await session.execute(select(AISkill).where(*filters))
        skill = result.scalars().first()
        if skill is None and not _is_platform_admin(current_user):
            # Phase 2d dual-read: widen via authz for a cross-company grant.
            from ..authz_probe import authz_can_view

            if await authz_can_view(current_user.id, "skill", skill_id):
                skill = (
                    (
                        await session.execute(
                            select(AISkill).where(AISkill.id == skill_id)
                        )
                    )
                    .scalars()
                    .first()
                )
        if not skill:
            raise HTTPException(status_code=404, detail="Skill not found")
        return AISkillPublic.model_validate(skill)

    @router.post("/", response_model=AISkillPublic)
    async def create_skill(
        session: SessionDep,
        current_user: PlatformAdminDep,
        data: AISkillCreate,
    ) -> Any:
        company_id = _require_company(current_user)
        skill = AISkill(
            company_id=company_id,
            name=data.name,
            label=data.label,
            description=data.description,
            icon=data.icon,
            kind=data.kind,
            modality=data.modality,
            content=data.content,
            is_active=data.is_active,
            agent_only=data.agent_only,
            created_by=current_user.id,
        )
        session.add(skill)
        await log_audit(
            session,
            user_id=current_user.id,
            company_id=company_id,
            action="ai_skill.created",
            target_type="ai_skill",
            target_id=str(skill.id),
            details={"name": data.name},
        )
        await session.commit()
        await session.refresh(skill)
        # Phase M — fire-and-forget index.
        await _search_index.index_doc(
            "skill", str(skill.id), _search_index.skill_to_doc(skill)
        )
        return AISkillPublic.model_validate(skill)

    def _reject_if_managed(skill: Any) -> None:
        """If the skill has a source_app set, it's provisioned by a vertical
        app and is read-only in the UI / API. Editing/deleting it through
        the user-facing endpoints returns 403 with a clear message.
        Hot-attribute check tolerates older rows where source_app is missing
        on the model (defensive — should not happen post-migration)."""
        source_app = getattr(skill, "source_app", None)
        if source_app:
            raise HTTPException(
                status_code=403,
                detail={
                    "error": "managed_skill",
                    "message": (
                        f"This skill is provisioned by app {source_app!r}. "
                        "Edit the YAML in that app's repo and redeploy to change it."
                    ),
                    "source_app": source_app,
                },
            )

    @router.patch("/{skill_id}", response_model=AISkillPublic)
    async def update_skill(
        session: SessionDep,
        current_user: PlatformAdminDep,
        skill_id: uuid.UUID,
        data: AISkillUpdate,
    ) -> Any:
        company_id = _require_company(current_user)
        result = await session.execute(
            select(AISkill).where(
                AISkill.id == skill_id, AISkill.company_id == company_id
            )
        )
        skill = result.scalars().first()
        if not skill:
            raise HTTPException(status_code=404, detail="Skill not found")

        _reject_if_managed(skill)

        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(skill, field, value)

        await log_audit(
            session,
            user_id=current_user.id,
            company_id=company_id,
            action="ai_skill.updated",
            target_type="ai_skill",
            target_id=str(skill_id),
            details=data.model_dump(exclude_unset=True),
        )
        await session.commit()
        await session.refresh(skill)
        # Phase M — reindex with the patched fields.
        await _search_index.index_doc(
            "skill", str(skill.id), _search_index.skill_to_doc(skill)
        )
        return AISkillPublic.model_validate(skill)

    @router.delete("/{skill_id}", response_model=Message)
    async def delete_skill(
        session: SessionDep,
        current_user: PlatformAdminDep,
        skill_id: uuid.UUID,
    ) -> Any:
        company_id = _require_company(current_user)
        result = await session.execute(
            select(AISkill).where(
                AISkill.id == skill_id, AISkill.company_id == company_id
            )
        )
        skill = result.scalars().first()
        if not skill:
            raise HTTPException(status_code=404, detail="Skill not found")

        _reject_if_managed(skill)

        await log_audit(
            session,
            user_id=current_user.id,
            company_id=company_id,
            action="ai_skill.deleted",
            target_type="ai_skill",
            target_id=str(skill_id),
            details={"name": skill.name},
        )
        deleted_id = str(skill.id)
        await session.delete(skill)
        await session.commit()
        # Phase M — best-effort search index cleanup.
        await _search_index.delete_doc("skill", deleted_id)
        return Message(message="Skill deleted")

    # ── Sync endpoint (M2M-only) ─────────────────────────────────────────────
    #
    # Vertical apps call this from their backend at startup to upsert their
    # YAML-defined skills. The skill name is namespaced server-side by
    # prefixing the source_app, so e.g. restoration's "photo_tagger" YAML
    # becomes "restoration:photo_tagger" in DB and is unambiguously owned.
    #
    # Idempotent: re-running the same sync returns everything in `unchanged`.
    # Atomic: a 409 (cross-app conflict) aborts the whole batch.

    if _sync_enabled:
        # System UUID used as `created_by` for synced skills — they're not
        # owned by any individual user. Distinct from the all-zero UUID so
        # platform admins can identify "system-provisioned" rows at a glance.
        _SYSTEM_USER_ID = uuid.UUID("00000000-0000-0000-0000-0000000000ff")

        @router.post("/sync", response_model=AISkillSyncResponse)
        async def sync_skills(
            session: SessionDep,
            _: InternalServiceDep,
            data: AISkillSyncRequest,
        ) -> Any:
            """Batch upsert skills owned by a vertical app.

            Auth: ``Authorization: Bearer <INTERNAL_SERVICE_SECRET>``. Never
            exposed through the external nginx ingress.
            """
            if not data.source_app:
                raise HTTPException(status_code=400, detail="source_app is required")
            # Per-deployment domain isolation: this deployment only accepts its
            # own domain's artifacts. Blocks cross-domain contamination even if
            # a vertical is misconfigured or two domains are co-located.
            if expected_source_app and data.source_app != expected_source_app:
                raise HTTPException(
                    status_code=403,
                    detail={
                        "error": "wrong_deployment",
                        "message": (
                            f"This deployment serves app {expected_source_app!r}; "
                            f"it will not ingest skills for {data.source_app!r}."
                        ),
                        "expected_source_app": expected_source_app,
                    },
                )
            if not data.skills:
                # Empty batch is a valid no-op
                return AISkillSyncResponse(
                    source_app=data.source_app, created=[], updated=[], unchanged=[]
                )

            qualified_names = [f"{data.source_app}:{item.name}" for item in data.skills]

            # Single round-trip lookup of all existing rows in the batch
            existing_rows = (
                (
                    await session.execute(
                        select(AISkill).where(
                            AISkill.company_id == data.company_id,
                            AISkill.name.in_(qualified_names),
                        )
                    )
                )
                .scalars()
                .all()
            )
            by_name = {row.name: row for row in existing_rows}

            # Cross-app conflict detection — refuse to clobber a skill owned
            # by a different app, even if names happen to match
            for row in existing_rows:
                if row.source_app and row.source_app != data.source_app:
                    raise HTTPException(
                        status_code=409,
                        detail={
                            "error": "source_app_conflict",
                            "message": (
                                f"Skill {row.name!r} is owned by app "
                                f"{row.source_app!r}; cannot be synced by "
                                f"{data.source_app!r}."
                            ),
                            "skill_id": str(row.id),
                            "owning_app": row.source_app,
                        },
                    )

            created: list[Any] = []
            updated: list[Any] = []
            unchanged: list[Any] = []

            for item in data.skills:
                qualified_name = f"{data.source_app}:{item.name}"
                existing = by_name.get(qualified_name)

                if existing is None:
                    # Pre-generate the id so we can include it in the response
                    # without needing a session.refresh() round-trip per row.
                    new_id = uuid.uuid4()
                    skill = AISkill(
                        id=new_id,
                        company_id=data.company_id,
                        name=qualified_name,
                        label=item.label,
                        description=item.description,
                        icon=item.icon,
                        kind=item.kind,
                        modality=item.modality,
                        content=item.content,
                        source_app=data.source_app,
                        is_active=True,
                        created_by=_SYSTEM_USER_ID,
                    )
                    session.add(skill)
                    created.append(
                        AISkillSyncResultItem(
                            name=qualified_name,
                            skill_id=new_id,
                            status="created",
                        )
                    )
                    continue

                # Detect changes; only mark updated when content actually shifted
                changed = False
                for field in (
                    "label",
                    "description",
                    "icon",
                    "kind",
                    "modality",
                    "content",
                ):
                    new_val = getattr(item, field)
                    if getattr(existing, field) != new_val:
                        setattr(existing, field, new_val)
                        changed = True
                # Backfill source_app on rows that pre-existed sync
                if existing.source_app != data.source_app:
                    existing.source_app = data.source_app
                    changed = True

                if changed:
                    updated.append(
                        AISkillSyncResultItem(
                            name=qualified_name,
                            skill_id=existing.id,
                            status="updated",
                        )
                    )
                else:
                    unchanged.append(
                        AISkillSyncResultItem(
                            name=qualified_name,
                            skill_id=existing.id,
                            status="unchanged",
                        )
                    )

            # One audit row per sync batch — finer-grained per-skill audit
            # would balloon the audit log without much extra signal
            await log_audit(
                session,
                user_id=_SYSTEM_USER_ID,
                company_id=data.company_id,
                action="ai_skill.synced",
                target_type="ai_skill_bundle",
                target_id=data.source_app,
                details={
                    "source_app": data.source_app,
                    "created": len(created),
                    "updated": len(updated),
                    "unchanged": len(unchanged),
                },
            )
            await session.commit()
            return AISkillSyncResponse(
                source_app=data.source_app,
                created=created,
                updated=updated,
                unchanged=unchanged,
            )

    return router
