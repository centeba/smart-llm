"""Tiny authz /check probe for smart_llm AI routers (Phase 2d dual-read).

Direct httpx (not the SDK) to avoid an import cycle — ``sentinelbuild_sdk``
depends on ``smart_llm``. Best-effort, fail-closed: returns False when authz is
unreachable, so the legacy SQL visibility filter remains the primary path and
authz only *widens* access for cross-company grants it can confirm.
"""

from __future__ import annotations

import os
import uuid

import httpx
import structlog

log = structlog.get_logger(__name__)


async def authz_can_view(
    user_id: uuid.UUID | str, resource: str, obj_id: uuid.UUID | str
) -> bool:
    """Does ``user:<id>`` have ``viewer`` on ``<resource>:<obj_id>`` per authz?"""
    base = os.environ.get("AUTHZ_URL", "http://authz:8000").rstrip("/")
    key = os.environ.get("INTERNAL_API_KEY", "")
    try:
        async with httpx.AsyncClient(timeout=5.0) as c:
            r = await c.post(
                f"{base}/api/v1/check",
                json={
                    "user": f"user:{user_id}",
                    "relation": "viewer",
                    "object": f"{resource}:{obj_id}",
                },
                headers={"X-Internal-Key": key},
            )
        if r.status_code == 200:
            return bool(r.json().get("allowed"))
        log.warning("authz_probe_status", status=r.status_code)
    except Exception:  # noqa: BLE001
        log.warning("authz_probe_error", exc_info=True)
    return False
