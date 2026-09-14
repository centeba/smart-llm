"""AI Agent Config and Company LLM API Key router factory.

Call create_agents_router() with the host app's dependency types and ORM models
to get a fully-wired FastAPI APIRouter that can be mounted at any prefix.
Auth, DB session, and company scoping stay in the host app — this module only
contains the business logic.
"""

# NOTE: do NOT add ``from __future__ import annotations`` here. The route
# functions reference factory-kwargs (``SessionDep``, ``CompanyAdminDep``)
# as type annotations, which only resolve through this function's closure
# at definition time. PEP 563 stringification breaks FastAPI's
# ``get_type_hints`` lookup (closure names aren't in ``__globals__``),
# silently demoting Depends parameters to query params and producing 422s.

import uuid
from typing import Any, cast

from fastapi import APIRouter, HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.orm import selectinload

# Phase M — index-on-write hook for AI Admin search.
from .. import ai_search_index as _search_index


def create_agents_router(
    *,
    SessionDep: Any,
    CurrentUser: Any,
    CompanyAdminDep: Any,
    # Authoring (create/update/delete an agent config, add/remove an LLM key) is
    # restricted to a platform/system admin — tenants are consumers, not authors,
    # so a company admin can no longer stand up an arbitrary agent (prompt +
    # tool bindings + approval modes) or upload provider keys. Domain agents
    # arrive via the M2M ``/sync`` endpoint (deploy-time, code-reviewed). Falls
    # back to CompanyAdminDep when a host doesn't wire it (older embedders/tests).
    PlatformAdminDep: Any = None,
    # Per-deployment domain isolation: the single domain this deployment serves
    # (e.g. "restoration"). When set, ``/sync`` rejects any batch whose
    # ``source_app`` differs. None → no enforcement (dev/back-compat).
    expected_source_app: Any = None,
    AIAgentConfig: Any,
    AISkill: Any,
    AISkillPublic: Any,
    AIAgentSkillLink: Any,
    AIAgentConfigPublic: Any,
    AIAgentConfigCreate: Any,
    AIAgentConfigUpdate: Any,
    AIAgentConfigsPublic: Any,
    CompanyLLMApiKeyPublic: Any,
    CompanyLLMApiKeyCreate: Any,
    CompanyLLMApiKeysPublic: Any,
    Message: Any,
    log_audit: Any,
    get_key_store: Any,
    InternalServiceDep: Any = None,
    AIAgentSyncRequest: Any = None,
    AIAgentSyncResponse: Any = None,
    AIAgentSyncResultItem: Any = None,
    # Phase G — when supplied, list/get lookups widen via
    # ``visible_agent_filter`` so platform + granted-shared agents
    # resolve. Hosts that haven't run migrations 013/014 simply
    # don't pass this and the router keeps the legacy
    # ``company_id == current`` shape.
    AIAgentGrant: Any = None,
) -> APIRouter:
    """Return a router for AI agent config and LLM key management.

    Parameters are injected by the host application so that this module has
    zero imports from the host package (no circular dependencies).

    The sync-related parameters mirror the skills router. When all four are
    provided, ``POST /ai-agents/sync`` is registered for vertical-app
    upserts. The route is placed *before* ``/{config_id}`` to avoid path
    collision (FastAPI matches routes in registration order; ``/sync`` would
    otherwise be parsed as a UUID config_id and 422).
    """
    # Back-compat: hosts that don't wire a platform-admin dep keep the old
    # behaviour (company admin can author). The production host wires it.
    PlatformAdminDep = PlatformAdminDep or CompanyAdminDep

    router = APIRouter(prefix="/ai-agents", tags=["ai-agents"])
    _sync_enabled = (
        InternalServiceDep is not None
        and AIAgentSyncRequest is not None
        and AIAgentSyncResponse is not None
        and AIAgentSyncResultItem is not None
    )

    def _require_company(user: Any) -> uuid.UUID:
        if not user.company_id:
            raise HTTPException(status_code=400, detail="User has no company")
        return cast(uuid.UUID, user.company_id)

    def _is_platform_admin(user: Any) -> bool:
        """Platform/system admins see (and operate on) every tenant's rows.

        Roles ``platform_admin`` (legacy) and ``system_admin`` (current
        canonical name after user-master ``normalize_role``) both grant
        cross-tenant access. Other roles fall through to the per-company
        scope. Hosts whose user model lacks a ``role`` attribute behave
        as if no user is platform admin (safe default).
        """
        role = getattr(user, "role", None)
        return role in ("platform_admin", "system_admin")

    def _scope_filter(
        user: Any, requested: uuid.UUID | None
    ) -> tuple[uuid.UUID | None, bool]:
        """Return (filter_company_id, allow_cross_tenant).

        Non-admins are always pinned to their own company. Platform
        admins may pass an explicit ``?company_id=`` to scope; without
        it they see everything.
        """
        if _is_platform_admin(user):
            return requested, requested is None
        # Regular users — explicit ``?company_id=`` is ignored to avoid
        # accidentally leaking another tenant's row count via 200/0.
        return _require_company(user), False

    def _config_to_public(config: Any) -> Any:
        skills = [
            AISkillPublic.model_validate(link.skill)
            for link in (config.skill_links or [])
            if link.skill
        ]
        d = {c.key: getattr(config, c.key) for c in config.__table__.columns}
        d["skills"] = skills
        d["skill_modes"] = {  # G7 — surface per-tool approval modes to the UI
            str(link.skill_id): link.approval_mode
            for link in (config.skill_links or [])
            if getattr(link, "approval_mode", None)
        }
        return AIAgentConfigPublic(**d)

    def _reject_if_managed(config: Any) -> None:
        """Refuse PATCH/DELETE on agents provisioned by a vertical app.
        Mirrors the equivalent guard on AISkill rows."""
        source_app = getattr(config, "source_app", None)
        if source_app:
            raise HTTPException(
                status_code=403,
                detail={
                    "error": "managed_agent",
                    "message": (
                        f"This agent is provisioned by app {source_app!r}. "
                        "Edit the YAML in that app's repo and redeploy to change it."
                    ),
                    "source_app": source_app,
                },
            )

    # -------------------------------------------------------------------------
    # Sync endpoint (M2M-only) — registered FIRST so /sync wins over /{config_id}
    # -------------------------------------------------------------------------

    if _sync_enabled:
        # Sentinel "system" UUID for created_by on synced agents — same convention
        # as the synced-skills path.
        _SYSTEM_USER_ID = uuid.UUID("00000000-0000-0000-0000-0000000000ff")

        @router.post("/sync", response_model=AIAgentSyncResponse)
        async def sync_agents(
            session: SessionDep,
            _: InternalServiceDep,
            data: AIAgentSyncRequest,
        ) -> Any:
            """Batch upsert vertical-app agents into the platform DB.

            For each agent:

            1. Lookup by qualified name ``<source_app>:<bare_name>``.
            2. If exists with a different ``source_app`` → 409 (cross-app conflict).
            3. Else insert/update the AIAgentConfig row.
            4. Resolve attached ``skill_names`` to skill IDs:
               - Bare name (no ":") → ``<source_app>:<name>``
               - Already-qualified name → used as-is (e.g. ``smart_llm:summarize``)
               - Skills not found are reported in ``unresolved_skills`` per agent
                 but don't fail the whole sync (admin can fix the skill order
                 and re-run; idempotent).
            5. Replace ``ai_agent_skill_links`` to match the resolved set.

            Auth: ``Authorization: Bearer <INTERNAL_SERVICE_SECRET>``.
            """
            if not data.source_app:
                raise HTTPException(status_code=400, detail="source_app is required")
            # Per-deployment domain isolation — reject artifacts for any other
            # domain (see the matching guard in skills.py::sync_skills).
            if expected_source_app and data.source_app != expected_source_app:
                raise HTTPException(
                    status_code=403,
                    detail={
                        "error": "wrong_deployment",
                        "message": (
                            f"This deployment serves app {expected_source_app!r}; "
                            f"it will not ingest agents for {data.source_app!r}."
                        ),
                        "expected_source_app": expected_source_app,
                    },
                )
            if not data.agents:
                return AIAgentSyncResponse(
                    source_app=data.source_app, created=[], updated=[], unchanged=[]
                )

            qualified_names = [f"{data.source_app}:{item.name}" for item in data.agents]

            # Single round-trip lookup, including existing skill_links so we can
            # diff without re-querying per row.
            existing_rows = (
                (
                    await session.execute(
                        select(AIAgentConfig)
                        .where(
                            AIAgentConfig.company_id == data.company_id,
                            AIAgentConfig.name.in_(qualified_names),
                        )
                        .options(selectinload(AIAgentConfig.skill_links))
                    )
                )
                .scalars()
                .all()
            )
            by_name = {row.name: row for row in existing_rows}

            # Cross-app conflict — refuse to clobber another app's agent
            for row in existing_rows:
                if row.source_app and row.source_app != data.source_app:
                    raise HTTPException(
                        status_code=409,
                        detail={
                            "error": "source_app_conflict",
                            "message": (
                                f"Agent {row.name!r} is owned by app "
                                f"{row.source_app!r}; cannot be synced by "
                                f"{data.source_app!r}."
                            ),
                            "agent_id": str(row.id),
                            "owning_app": row.source_app,
                        },
                    )

            # Pre-resolve every skill name needed across the whole batch in one query.
            all_skill_names: set[str] = set()
            for item in data.agents:
                for sn in item.skill_names:
                    qualified = sn if ":" in sn else f"{data.source_app}:{sn}"
                    all_skill_names.add(qualified)
                for t in item.tools or []:  # G7 — tool attachments resolve too
                    tn = t.get("name") if isinstance(t, dict) else None
                    if tn:
                        all_skill_names.add(
                            tn if ":" in tn else f"{data.source_app}:{tn}"
                        )

            skill_id_by_name: dict[str, uuid.UUID] = {}
            if all_skill_names:
                skill_rows = (
                    (
                        await session.execute(
                            select(AISkill).where(
                                AISkill.company_id == data.company_id,
                                AISkill.name.in_(all_skill_names),
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                skill_id_by_name = {row.name: row.id for row in skill_rows}

            created: list[Any] = []
            updated: list[Any] = []
            unchanged: list[Any] = []

            for item in data.agents:
                qualified_name = f"{data.source_app}:{item.name}"

                # Resolve referenced skills (per-agent so unresolved is reported)
                resolved_ids: list[uuid.UUID] = []
                unresolved: list[str] = []
                for sn in item.skill_names:
                    qualified = sn if ":" in sn else f"{data.source_app}:{sn}"
                    if qualified in skill_id_by_name:
                        resolved_ids.append(skill_id_by_name[qualified])
                    else:
                        unresolved.append(qualified)

                # G7 — resolve tool attachments + their per-tool approval modes.
                mode_by_id: dict[uuid.UUID, str] = {}
                for t in item.tools or []:
                    if not isinstance(t, dict) or not t.get("name"):
                        continue
                    tn = t["name"]
                    qualified = tn if ":" in tn else f"{data.source_app}:{tn}"
                    sid = skill_id_by_name.get(qualified)
                    if sid is None:
                        unresolved.append(qualified)
                        continue
                    if sid not in resolved_ids:
                        resolved_ids.append(sid)
                    mode_by_id[sid] = str(t.get("approval_mode", "auto"))

                existing = by_name.get(qualified_name)

                if existing is None:
                    new_id = uuid.uuid4()
                    config = AIAgentConfig(
                        id=new_id,
                        company_id=data.company_id,
                        name=qualified_name,
                        label=item.label,
                        description=item.description,
                        icon=item.icon,
                        system_prompt=item.system_prompt,
                        provider_type=item.provider_type,
                        model_name=item.model_name,
                        model_configuration=item.model_configuration,
                        response_format=item.response_format,
                        source_app=data.source_app,
                        is_active=True,
                        created_by=_SYSTEM_USER_ID,
                    )
                    session.add(config)
                    for sid in resolved_ids:
                        link_kwargs: dict[str, Any] = {
                            "agent_config_id": new_id,
                            "skill_id": sid,
                        }
                        if sid in mode_by_id:  # G7 — per-tool approval mode
                            link_kwargs["approval_mode"] = mode_by_id[sid]
                        session.add(AIAgentSkillLink(**link_kwargs))
                    created.append(
                        AIAgentSyncResultItem(
                            name=qualified_name,
                            agent_id=new_id,
                            status="created",
                            unresolved_skills=unresolved,
                        )
                    )
                    continue

                # Diff fields
                changed = False
                for field in (
                    "label",
                    "description",
                    "icon",
                    "system_prompt",
                    "provider_type",
                    "model_name",
                    "model_configuration",
                    "response_format",
                ):
                    new_val = getattr(item, field)
                    if getattr(existing, field) != new_val:
                        setattr(existing, field, new_val)
                        changed = True
                if existing.source_app != data.source_app:
                    existing.source_app = data.source_app
                    changed = True

                # Diff skill links — replace if the set OR any per-tool approval
                # mode differs (G7).
                current_modes = {
                    link.skill_id: getattr(link, "approval_mode", None)
                    for link in existing.skill_links
                }
                set_changed = set(current_modes) != set(resolved_ids)
                mode_changed = any(
                    sid in mode_by_id and current_modes.get(sid) != mode_by_id[sid]
                    for sid in resolved_ids
                )
                if set_changed or mode_changed:
                    for link in list(existing.skill_links):
                        await session.delete(link)
                    await session.flush()
                    for sid in resolved_ids:
                        link_kwargs = {
                            "agent_config_id": existing.id,
                            "skill_id": sid,
                        }
                        if sid in mode_by_id:
                            link_kwargs["approval_mode"] = mode_by_id[sid]
                        session.add(AIAgentSkillLink(**link_kwargs))
                    changed = True

                bucket = updated if changed else unchanged
                bucket.append(
                    AIAgentSyncResultItem(
                        name=qualified_name,
                        agent_id=existing.id,
                        status="updated" if changed else "unchanged",
                        unresolved_skills=unresolved,
                    )
                )

            await log_audit(
                session,
                user_id=_SYSTEM_USER_ID,
                company_id=data.company_id,
                action="ai_agent_config.synced",
                target_type="ai_agent_bundle",
                target_id=data.source_app,
                details={
                    "source_app": data.source_app,
                    "created": len(created),
                    "updated": len(updated),
                    "unchanged": len(unchanged),
                },
            )
            await session.commit()
            return AIAgentSyncResponse(
                source_app=data.source_app,
                created=created,
                updated=updated,
                unchanged=unchanged,
            )

    # -------------------------------------------------------------------------
    # Agent Config CRUD
    # -------------------------------------------------------------------------

    @router.get("/", response_model=AIAgentConfigsPublic)
    async def list_agent_configs(
        session: SessionDep,
        current_user: CompanyAdminDep,
        skip: int = 0,
        limit: int = 100,
        search: str | None = None,
        company_id: uuid.UUID | None = None,
        all_companies: bool = False,
    ) -> Any:
        # Scoping (platform admins):
        #   ?company_id=<id>   → drill into that one tenant (cross-tenant).
        #   ?all_companies=true → the full cross-tenant list (every tenant's
        #                          per-company seeded agents — noisy; opt-in).
        #   default             → own company + platform-scoped rows only, so
        #                          the admin isn't drowned in ~N copies of the
        #                          same per-company default agent.
        # Non-admins are always pinned to their own company.
        filters: list[Any] = []
        if _is_platform_admin(current_user):
            if company_id is not None:
                filters.append(AIAgentConfig.company_id == company_id)
            elif not all_companies:
                own = getattr(current_user, "company_id", None)
                scope = [AIAgentConfig.company_id.is_(None)]  # platform-scoped
                if own is not None:
                    scope.append(AIAgentConfig.company_id == own)
                filters.append(or_(*scope))
            # else all_companies → no company filter (full cross-tenant)
        else:
            own = _require_company(current_user)
            if AIAgentGrant is not None:
                from ..scoping import visible_agent_filter

                filters.append(visible_agent_filter(AIAgentConfig, AIAgentGrant, own))
            else:
                filters.append(AIAgentConfig.company_id == own)
        if search:
            filters.append(AIAgentConfig.name.ilike(f"%{search}%"))

        stmt = (
            select(AIAgentConfig)
            .where(*filters)
            .options(
                selectinload(AIAgentConfig.skill_links).selectinload(
                    AIAgentSkillLink.skill
                )
            )
        )
        count_stmt = select(func.count()).select_from(
            select(AIAgentConfig.id).where(*filters).subquery()
        )
        count = (await session.execute(count_stmt)).scalar_one()
        result = await session.execute(
            stmt.order_by(AIAgentConfig.created_at.desc()).offset(skip).limit(limit)
        )
        configs = result.scalars().all()
        return AIAgentConfigsPublic(
            data=[_config_to_public(c) for c in configs], count=count
        )

    @router.get("/{config_id}", response_model=AIAgentConfigPublic)
    async def get_agent_config(
        session: SessionDep,
        current_user: CompanyAdminDep,
        config_id: uuid.UUID,
    ) -> Any:
        filters = [AIAgentConfig.id == config_id]
        if not _is_platform_admin(current_user):
            cid = _require_company(current_user)
            if AIAgentGrant is not None:
                from ..scoping import visible_agent_filter

                filters.append(visible_agent_filter(AIAgentConfig, AIAgentGrant, cid))
            else:
                filters.append(AIAgentConfig.company_id == cid)
        result = await session.execute(
            select(AIAgentConfig)
            .where(*filters)
            .options(
                selectinload(AIAgentConfig.skill_links).selectinload(
                    AIAgentSkillLink.skill
                )
            )
        )
        config = result.scalars().first()
        if config is None and not _is_platform_admin(current_user):
            # Phase 2d dual-read: the legacy SQL filter missed it — widen via
            # authz (a cross-company grant the user holds in OpenFGA).
            from ..authz_probe import authz_can_view

            if await authz_can_view(current_user.id, "agent", config_id):
                config = (
                    (
                        await session.execute(
                            select(AIAgentConfig)
                            .where(AIAgentConfig.id == config_id)
                            .options(
                                selectinload(AIAgentConfig.skill_links).selectinload(
                                    AIAgentSkillLink.skill
                                )
                            )
                        )
                    )
                    .scalars()
                    .first()
                )
        if not config:
            raise HTTPException(status_code=404, detail="Agent config not found")
        return _config_to_public(config)

    @router.post("/", response_model=AIAgentConfigPublic)
    async def create_agent_config(
        session: SessionDep,
        current_user: PlatformAdminDep,
        data: AIAgentConfigCreate,
    ) -> Any:
        # Phase G — scope rules:
        # - scope='platform' requires system_admin / platform_admin AND
        #   forces company_id=None.
        # - scope='company' / 'shared' require a company_id; pinned to
        #   the caller's tenant for non-platform-admin users.
        from smart_llm.db.models import (
            SCOPE_COMPANY,
            SCOPE_PLATFORM,
            SCOPES,
        )

        scope = getattr(data, "scope", SCOPE_COMPANY) or SCOPE_COMPANY
        if scope not in SCOPES:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid scope {scope!r}; must be one of {SCOPES}",
            )

        if scope == SCOPE_PLATFORM:
            if not _is_platform_admin(current_user):
                raise HTTPException(
                    status_code=403,
                    detail="Only platform admins can create scope='platform' agents.",
                )
            company_id = None
        else:
            company_id = _require_company(current_user)

        config = AIAgentConfig(
            company_id=company_id,
            scope=scope,
            name=data.name,
            label=data.label,
            description=data.description,
            icon=data.icon,
            system_prompt=data.system_prompt,
            provider_type=data.provider_type,
            model_name=data.model_name,
            model_configuration=data.model_configuration,
            response_format=data.response_format,
            role_id=data.role_id,
            is_active=data.is_active,
            created_by=current_user.id,
        )
        session.add(config)
        await session.flush()

        for skill_id in data.skill_ids:
            link_kwargs: dict[str, Any] = {
                "agent_config_id": config.id,
                "skill_id": skill_id,
            }
            mode = data.skill_modes.get(str(skill_id))  # G7
            if mode:
                link_kwargs["approval_mode"] = mode
            session.add(AIAgentSkillLink(**link_kwargs))

        await log_audit(
            session,
            user_id=current_user.id,
            company_id=company_id,
            action="ai_agent_config.created",
            target_type="ai_agent_config",
            target_id=str(config.id),
            details={"name": data.name, "provider": data.provider_type},
        )
        await session.commit()
        await session.refresh(config)

        result = await session.execute(
            select(AIAgentConfig)
            .where(AIAgentConfig.id == config.id)
            .options(
                selectinload(AIAgentConfig.skill_links).selectinload(
                    AIAgentSkillLink.skill
                )
            )
        )
        config = result.scalars().one()
        # Phase M — fire-and-forget index. Errors log only.
        await _search_index.index_doc(
            "agent", str(config.id), _search_index.agent_to_doc(config)
        )
        return _config_to_public(config)

    @router.patch("/{config_id}", response_model=AIAgentConfigPublic)
    async def update_agent_config(
        session: SessionDep,
        current_user: PlatformAdminDep,
        config_id: uuid.UUID,
        data: AIAgentConfigUpdate,
    ) -> Any:
        company_id = _require_company(current_user)
        result = await session.execute(
            select(AIAgentConfig).where(
                AIAgentConfig.id == config_id, AIAgentConfig.company_id == company_id
            )
        )
        config = result.scalars().first()
        if not config:
            raise HTTPException(status_code=404, detail="Agent config not found")

        _reject_if_managed(config)

        update_data = data.model_dump(exclude_unset=True)
        skill_ids = update_data.pop("skill_ids", None)
        skill_modes = update_data.pop("skill_modes", {}) or {}  # G7

        for field, value in update_data.items():
            setattr(config, field, value)

        if skill_ids is not None:
            for link in list(config.skill_links):
                await session.delete(link)
            await session.flush()
            for sid in skill_ids:
                link_kwargs: dict[str, Any] = {
                    "agent_config_id": config.id,
                    "skill_id": sid,
                }
                mode = skill_modes.get(str(sid))
                if mode:
                    link_kwargs["approval_mode"] = mode
                session.add(AIAgentSkillLink(**link_kwargs))

        await log_audit(
            session,
            user_id=current_user.id,
            company_id=company_id,
            action="ai_agent_config.updated",
            target_type="ai_agent_config",
            target_id=str(config_id),
            details=data.model_dump(exclude_unset=True),
        )
        await session.commit()

        result = await session.execute(
            select(AIAgentConfig)
            .where(AIAgentConfig.id == config.id)
            .options(
                selectinload(AIAgentConfig.skill_links).selectinload(
                    AIAgentSkillLink.skill
                )
            )
        )
        config = result.scalars().one()
        # Phase M — reindex with the patched fields.
        await _search_index.index_doc(
            "agent", str(config.id), _search_index.agent_to_doc(config)
        )
        return _config_to_public(config)

    @router.delete("/{config_id}", response_model=Message)
    async def delete_agent_config(
        session: SessionDep,
        current_user: PlatformAdminDep,
        config_id: uuid.UUID,
    ) -> Any:
        company_id = _require_company(current_user)
        result = await session.execute(
            select(AIAgentConfig).where(
                AIAgentConfig.id == config_id, AIAgentConfig.company_id == company_id
            )
        )
        config = result.scalars().first()
        if not config:
            raise HTTPException(status_code=404, detail="Agent config not found")

        _reject_if_managed(config)

        await log_audit(
            session,
            user_id=current_user.id,
            company_id=company_id,
            action="ai_agent_config.deleted",
            target_type="ai_agent_config",
            target_id=str(config_id),
            details={"name": config.name},
        )
        deleted_id = str(config.id)
        await session.delete(config)
        await session.commit()
        # Phase M — best-effort search index cleanup.
        await _search_index.delete_doc("agent", deleted_id)
        return Message(message="Agent config deleted")

    # -------------------------------------------------------------------------
    # Company LLM API Keys — delegated to smart-llm's DatabaseKeyStore
    # -------------------------------------------------------------------------

    @router.get("/llm-keys/", response_model=CompanyLLMApiKeysPublic)
    async def list_llm_keys(
        session: SessionDep,
        current_user: CompanyAdminDep,
    ) -> Any:
        company_id = _require_company(current_user)
        store = get_key_store()
        keys = await store.list_keys(scope_id=company_id)
        data = [
            CompanyLLMApiKeyPublic(
                id=uuid.UUID(k["id"]),
                company_id=company_id,
                provider=k["provider"],
                is_active=k["is_active"],
                created_at=k.get("created_at"),
            )
            for k in keys
        ]
        return CompanyLLMApiKeysPublic(data=data, count=len(data))

    @router.post("/llm-keys/", response_model=CompanyLLMApiKeyPublic)
    async def create_llm_key(
        session: SessionDep,
        current_user: PlatformAdminDep,
        data: CompanyLLMApiKeyCreate,
    ) -> Any:
        company_id = _require_company(current_user)
        store = get_key_store()
        result = await store.save_key(
            data.provider,
            data.api_key,
            label=f"{data.provider} key",
            scope_id=company_id,
        )
        await log_audit(
            session,
            user_id=current_user.id,
            company_id=company_id,
            action="llm_key.created",
            target_type="llm_api_key",
            target_id=result["id"],
            details={"provider": data.provider},
        )
        await session.commit()
        return CompanyLLMApiKeyPublic(
            id=uuid.UUID(result["id"]),
            company_id=company_id,
            provider=result["provider"],
            is_active=result["is_active"],
            created_at=result.get("created_at"),
        )

    @router.delete("/llm-keys/{key_id}", response_model=Message)
    async def delete_llm_key(
        session: SessionDep,
        current_user: PlatformAdminDep,
        key_id: uuid.UUID,
    ) -> Any:
        company_id = _require_company(current_user)
        store = get_key_store()
        keys = await store.list_keys(scope_id=company_id)
        matching = [k for k in keys if k["id"] == str(key_id)]
        if not matching:
            raise HTTPException(status_code=404, detail="LLM key not found")

        await store.delete_key(str(key_id))
        await log_audit(
            session,
            user_id=current_user.id,
            company_id=company_id,
            action="llm_key.deleted",
            target_type="llm_api_key",
            target_id=str(key_id),
            details={"provider": matching[0]["provider"]},
        )
        await session.commit()
        return Message(message="LLM key deleted")

    return router
