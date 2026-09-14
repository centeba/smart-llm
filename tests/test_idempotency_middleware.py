"""Tests for the uniform Idempotency-Key replay middleware (SB-03)."""

import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from smart_llm.api.middleware import IdempotencyMiddleware


class _FakeRedis:
    """Minimal async Redis stand-in: SET (with NX/EX), GET, DELETE."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def set(self, key, value, nx=False, ex=None):
        if nx and key in self.store:
            return None
        self.store[key] = value
        return True

    async def get(self, key):
        v = self.store.get(key)
        return v.encode("utf-8") if isinstance(v, str) else v

    async def delete(self, key):
        self.store.pop(key, None)
        return 1


def _make_app(redis, **kw):
    app = FastAPI()
    state = {"calls": 0}

    app.add_middleware(IdempotencyMiddleware, redis_getter=lambda: redis, **kw)

    @app.post("/things")
    async def create_thing():
        state["calls"] += 1
        return {"id": state["calls"]}

    @app.get("/things")
    async def list_things():
        state["calls"] += 1
        return {"count": state["calls"]}

    @app.post("/boom")
    async def boom():
        state["calls"] += 1
        from fastapi import HTTPException

        raise HTTPException(status_code=500, detail="kaboom")

    return app, state


def test_first_call_runs_and_marks_not_replayed():
    redis = _FakeRedis()
    app, state = _make_app(redis)
    client = TestClient(app, raise_server_exceptions=False)

    r = client.post("/things", headers={"Idempotency-Key": "k1"})
    assert r.status_code == 200
    assert r.json() == {"id": 1}
    assert r.headers["Idempotency-Replayed"] == "false"
    assert state["calls"] == 1


def test_duplicate_key_replays_without_rerunning():
    redis = _FakeRedis()
    app, state = _make_app(redis)
    client = TestClient(app, raise_server_exceptions=False)

    first = client.post("/things", headers={"Idempotency-Key": "k1"})
    second = client.post("/things", headers={"Idempotency-Key": "k1"})

    assert state["calls"] == 1  # handler ran only once
    assert second.status_code == first.status_code
    assert second.json() == first.json() == {"id": 1}
    assert second.headers["Idempotency-Replayed"] == "true"


def test_different_key_runs_again():
    redis = _FakeRedis()
    app, state = _make_app(redis)
    client = TestClient(app, raise_server_exceptions=False)

    client.post("/things", headers={"Idempotency-Key": "k1"})
    r = client.post("/things", headers={"Idempotency-Key": "k2"})
    assert state["calls"] == 2
    assert r.json() == {"id": 2}


def test_no_header_is_never_deduped():
    redis = _FakeRedis()
    app, state = _make_app(redis)
    client = TestClient(app, raise_server_exceptions=False)

    client.post("/things")
    client.post("/things")
    assert state["calls"] == 2


def test_non_mutating_method_ignored():
    redis = _FakeRedis()
    app, state = _make_app(redis)
    client = TestClient(app, raise_server_exceptions=False)

    client.get("/things", headers={"Idempotency-Key": "k1"})
    client.get("/things", headers={"Idempotency-Key": "k1"})
    assert state["calls"] == 2  # GET is not replayed


def test_same_key_different_credential_is_isolated():
    redis = _FakeRedis()
    app, state = _make_app(redis)
    client = TestClient(app, raise_server_exceptions=False)

    client.post(
        "/things", headers={"Idempotency-Key": "k1", "Authorization": "Bearer a"}
    )
    r = client.post(
        "/things", headers={"Idempotency-Key": "k1", "Authorization": "Bearer b"}
    )
    # Different credential → different storage key → not a replay.
    assert state["calls"] == 2
    assert r.headers["Idempotency-Replayed"] == "false"


def test_in_progress_returns_409():
    redis = _FakeRedis()
    app, state = _make_app(redis)
    client = TestClient(app, raise_server_exceptions=False)

    # Pre-seed a pending claim for the exact storage key the middleware computes.
    mw = IdempotencyMiddleware(app, redis_getter=lambda: redis)

    class _Req:
        method = "POST"
        url = type("U", (), {"path": "/things"})()
        headers = {"authorization": "Bearer x"}

        def __init__(self):
            self.headers = {"authorization": "Bearer x"}

    key = mw._storage_key(_Req(), "k1")
    redis.store[key] = json.dumps({"state": "pending"})

    r = client.post(
        "/things", headers={"Idempotency-Key": "k1", "Authorization": "Bearer x"}
    )
    assert r.status_code == 409
    assert state["calls"] == 0  # never ran; original still in flight


def test_5xx_not_cached_so_retry_reruns():
    redis = _FakeRedis()
    app, state = _make_app(redis)
    client = TestClient(app, raise_server_exceptions=False)

    r1 = client.post("/boom", headers={"Idempotency-Key": "k1"})
    r2 = client.post("/boom", headers={"Idempotency-Key": "k1"})
    assert r1.status_code == 500
    # 5xx released the claim → the retry re-runs rather than replaying the error.
    assert state["calls"] == 2


def test_no_redis_fails_open():
    app = FastAPI()
    state = {"calls": 0}
    app.add_middleware(IdempotencyMiddleware, redis_getter=None)

    @app.post("/things")
    async def create_thing():
        state["calls"] += 1
        return {"id": state["calls"]}

    client = TestClient(app, raise_server_exceptions=False)
    client.post("/things", headers={"Idempotency-Key": "k1"})
    client.post("/things", headers={"Idempotency-Key": "k1"})
    assert state["calls"] == 2  # no store → runs every time, never errors
