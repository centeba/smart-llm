"""Phase M — `GET /ai-search/` endpoint.

Cross-tenant for ``system_admin``/``platform_admin`` (matches Phase F
``_scope_filter`` shape — they see all companies' agents/skills/tools);
per-tenant otherwise. Tools are always visible (global).

Falls back to an empty result list when ES is unreachable so the UI
degrades cleanly to its in-memory client-side filter.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, Query

from .. import ai_search_index


def create_ai_search_router(*, CurrentUser: Any) -> APIRouter:
    """Build the router. ``CurrentUser`` is the host's auth
    dependency (e.g. ``CurrentUserDep`` from integration-hub)."""
    router = APIRouter(prefix="/ai-search", tags=["ai-search"])

    @router.get("/")
    async def search(
        q: str = Query("", description="Search query"),
        type: Literal["agent", "skill", "tool"] | None = Query(None),
        limit: int = Query(25, ge=1, le=100),
        current_user: Any = Depends(CurrentUser),
    ) -> dict[str, Any]:
        """Search across agents + skills + tools."""
        # Cross-tenant for platform-level roles; per-tenant otherwise.
        role = getattr(current_user, "role", None)
        company_id: str | None
        if role in ("system_admin", "platform_admin"):
            company_id = None
        else:
            cid = getattr(current_user, "company_id", None)
            company_id = str(cid) if cid else None

        rows = await ai_search_index.search(
            q,
            company_id=company_id,
            type_filter=type,
            limit=limit,
        )
        return {"results": rows, "count": len(rows)}

    return router
