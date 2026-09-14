"""web_search cache + single-flight (SB-14)."""

import asyncio
import json

import pytest

from smart_llm.builtins import web_search
from smart_llm.builtins.web_search import WebSearchArgs, WebSearchTool


@pytest.fixture(autouse=True)
def _reset_state():
    """Each test starts with an empty cache, no in-flight, no Redis."""
    web_search._local_cache.clear()
    web_search._inflight.clear()
    web_search._redis_resolved = False
    web_search._redis_client = None
    yield
    web_search._local_cache.clear()
    web_search._inflight.clear()
    web_search._redis_resolved = False
    web_search._redis_client = None


def _tool() -> WebSearchTool:
    return WebSearchTool()


@pytest.mark.asyncio
async def test_cache_hit_avoids_second_provider_call(monkeypatch):
    calls = {"n": 0}

    async def fake(query, max_results):
        calls["n"] += 1
        return {"answer": query, "results": []}

    monkeypatch.setattr(web_search, "_tavily_search", fake)
    tool = _tool()
    r1 = await tool.run_action(WebSearchArgs(query="q"), db_session=None)
    r2 = await tool.run_action(WebSearchArgs(query="q"), db_session=None)
    assert r1 == r2 == {"answer": "q", "results": []}
    assert calls["n"] == 1  # second call served from cache


@pytest.mark.asyncio
async def test_single_flight_collapses_concurrent_calls(monkeypatch):
    calls = {"n": 0}
    release = asyncio.Event()

    async def fake(query, max_results):
        calls["n"] += 1
        await release.wait()  # hold all callers in one in-flight request
        return {"answer": query, "results": []}

    monkeypatch.setattr(web_search, "_tavily_search", fake)
    tool = _tool()
    tasks = [
        asyncio.create_task(tool.run_action(WebSearchArgs(query="same"), db_session=None))
        for _ in range(6)
    ]
    await asyncio.sleep(0.02)  # let the leader claim the flight + enter the provider
    release.set()
    results = await asyncio.gather(*tasks)
    assert calls["n"] == 1  # 6 concurrent identical queries → ONE upstream call
    assert all(r == {"answer": "same", "results": []} for r in results)


@pytest.mark.asyncio
async def test_errors_are_not_cached(monkeypatch):
    calls = {"n": 0}

    async def fake(query, max_results):
        calls["n"] += 1
        raise RuntimeError("boom")

    monkeypatch.setattr(web_search, "_tavily_search", fake)
    tool = _tool()
    r1 = await tool.run_action(WebSearchArgs(query="q"), db_session=None)
    r2 = await tool.run_action(WebSearchArgs(query="q"), db_session=None)
    assert "error" in r1 and "error" in r2
    assert calls["n"] == 2  # a failure is retried, not cached


@pytest.mark.asyncio
async def test_redis_backed_cache_shared(monkeypatch):
    class _FakeRedis:
        def __init__(self):
            self.store = {}

        async def get(self, key):
            return self.store.get(key)

        async def set(self, key, value, ex=None):
            self.store[key] = value
            return True

    redis = _FakeRedis()
    web_search._redis_resolved = True
    web_search._redis_client = redis

    calls = {"n": 0}

    async def fake(query, max_results):
        calls["n"] += 1
        return {"answer": query, "results": []}

    monkeypatch.setattr(web_search, "_tavily_search", fake)

    # A fresh tool instance (simulating another process/replica) still hits the
    # shared Redis entry the first call wrote — no second provider call.
    await _tool().run_action(WebSearchArgs(query="q"), db_session=None)
    assert any(k.startswith("websearch:") for k in redis.store)  # went to Redis
    stored = json.loads(next(iter(redis.store.values())))
    assert stored == {"answer": "q", "results": []}

    await _tool().run_action(WebSearchArgs(query="q"), db_session=None)
    assert calls["n"] == 1  # second instance served from shared Redis
