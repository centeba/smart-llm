"""`web_search` builtin (G5) — provider-pluggable, Tavily first.

Registered ONLY when a provider is configured (``TAVILY_API_KEY``), so an agent
that lists it does nothing surprising when no key is present — the tool is simply
absent from the registry. ``risk="external"`` (outbound call), so the policy gate
treats it as requiring approval unless an admin opts in.

Caching (SB-14): results are memoised in a short TTL cache so repeated identical
searches don't re-hit the provider. When ``SMART_LLM_WEB_SEARCH_REDIS_URL`` (or
``REDIS_URL``) is set the cache is **Redis-backed and shared across processes /
replicas** — a result one replica fetched is a hit for all of them; without a URL
it degrades to a per-process in-memory cache. On top of the cache a **single-flight**
guard collapses *concurrent* identical queries in a process to ONE upstream call
(the rest await the same result), so a thundering herd of agents can't fan out N
identical provider hits. Pair with the loop's per-tool call cap (G2 ``LoopGuards``).
"""

import asyncio
import hashlib
import json
import os
import time
from typing import Any, cast

import httpx
from pydantic import BaseModel, Field

from smart_llm.base import ActionTool
from smart_llm.db.models import MODALITY_TEXT
from smart_llm.registry import register_tool

_CACHE_TTL_SECONDS = 120
# Per-process fallback cache, used only when no Redis URL is configured (or Redis
# is unreachable). key -> (monotonic_ts, result).
_local_cache: dict[str, tuple[float, dict[str, Any]]] = {}
# Single-flight: one in-flight upstream call per key, shared by concurrent callers.
_inflight: dict[str, "asyncio.Future[dict[str, Any]]"] = {}

_redis_client: Any = None
_redis_resolved = False


def _get_redis() -> Any:
    """Lazily build a shared redis.asyncio client from the configured URL, or
    return None to fall back to the per-process cache. Cached after first call."""
    global _redis_client, _redis_resolved
    if _redis_resolved:
        return _redis_client
    _redis_resolved = True
    url = os.environ.get("SMART_LLM_WEB_SEARCH_REDIS_URL") or os.environ.get("REDIS_URL")
    if url:
        try:
            import redis.asyncio as aioredis

            _redis_client = aioredis.from_url(url, decode_responses=True)
        except Exception:  # noqa: BLE001 — no redis installed / bad URL → local cache
            _redis_client = None
    return _redis_client


def _redis_key(key: str) -> str:
    return "websearch:" + hashlib.sha256(key.encode("utf-8")).hexdigest()


async def _cache_get(key: str) -> dict[str, Any] | None:
    redis = _get_redis()
    if redis is not None:
        try:
            raw = await redis.get(_redis_key(key))
            if raw:
                loaded: dict[str, Any] = json.loads(raw)
                return loaded
            return None
        except Exception:  # noqa: BLE001 — Redis blip → fall through to local
            pass
    hit = _local_cache.get(key)
    if hit and (time.monotonic() - hit[0]) < _CACHE_TTL_SECONDS:
        return hit[1]
    return None


async def _cache_set(key: str, result: dict[str, Any]) -> None:
    redis = _get_redis()
    if redis is not None:
        try:
            await redis.set(_redis_key(key), json.dumps(result), ex=_CACHE_TTL_SECONDS)
            return
        except Exception:  # noqa: BLE001 — Redis blip → keep a local copy
            pass
    _local_cache[key] = (time.monotonic(), result)


class WebSearchArgs(BaseModel):
    query: str = Field(..., description="The search query.")
    max_results: int = Field(5, description="How many results to return (1–10).")


async def _tavily_search(query: str, max_results: int) -> dict[str, Any]:
    api_key = os.environ.get("TAVILY_API_KEY", "")
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.post(
            "https://api.tavily.com/search",
            json={
                "api_key": api_key,
                "query": query,
                "max_results": max(1, min(int(max_results or 5), 10)),
                "search_depth": "basic",
            },
        )
        resp.raise_for_status()
        data = resp.json()
    return {
        "answer": data.get("answer"),
        "results": [
            {"title": r.get("title"), "url": r.get("url"), "content": r.get("content")}
            for r in (data.get("results") or [])
        ],
    }


class WebSearchTool(ActionTool):
    args_model = WebSearchArgs
    read_only = True
    risk = "external"

    async def run_action(self, args: BaseModel, *, db_session: Any) -> dict[str, Any]:
        args = cast(WebSearchArgs, args)
        key = f"{args.query}::{args.max_results}"

        cached = await _cache_get(key)
        if cached is not None:
            return cached

        # Single-flight: if an identical query is already in flight in this
        # process, await its result instead of firing a second upstream call.
        existing = _inflight.get(key)
        if existing is not None:
            return await existing

        fut: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        _inflight[key] = fut
        try:
            # Re-check the cache now we hold the flight — another caller may have
            # populated it between our miss above and claiming the slot.
            cached = await _cache_get(key)
            if cached is not None:
                fut.set_result(cached)
                return cached
            try:
                result = await _tavily_search(args.query, args.max_results)
            except Exception as exc:  # noqa: BLE001
                # Don't cache failures (transient); concurrent callers share it.
                result = {"error": f"web_search failed: {exc}"}
            else:
                await _cache_set(key, result)
            fut.set_result(result)
            return result
        finally:
            _inflight.pop(key, None)


# Provider-gated registration: only expose the tool when a key is configured.
if os.environ.get("TAVILY_API_KEY"):
    register_tool(
        "web_search",
        WebSearchTool,
        label="Web Search",
        description="Search the web and return top results (title, url, snippet) "
        "plus a short answer when available.",
        modality=MODALITY_TEXT,
        risk="external",
    )
