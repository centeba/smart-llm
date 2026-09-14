"""Unit tests for the shared JWT revocation denylist (pre-launch Gate 3)."""

from __future__ import annotations

import pytest

from smart_llm import token_revocation
from smart_llm.token_revocation import (
    is_revoked,
    revoke_jti,
    revoke_user_tokens,
    token_is_revoked,
)


class _FakeRedis:
    """Minimal async Redis stand-in: SET with ex + GET, in-memory."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.store[key] = value

    async def get(self, key: str):
        return self.store.get(key)


class _BrokenRedis:
    async def get(self, key: str):
        raise ConnectionError("redis down")


@pytest.mark.asyncio
async def test_token_is_revoked_noop_without_shared_redis(monkeypatch):
    # No TOKEN_REVOCATION_REDIS_URL → the cross-service check is a no-op (a
    # service adopting it can't break auth before the env is wired).
    monkeypatch.delenv("TOKEN_REVOCATION_REDIS_URL", raising=False)
    token_revocation._reset_revocation_redis_for_tests()
    assert await token_is_revoked({"jti": "x", "sub": "u1", "iat": 1}) is False


@pytest.mark.asyncio
async def test_token_is_revoked_uses_shared_redis(monkeypatch):
    # With a client wired, token_is_revoked consults the denylist.
    fake = _FakeRedis()
    monkeypatch.setattr(token_revocation, "_rev_redis", fake)
    monkeypatch.setattr(token_revocation, "_rev_redis_init", True)
    payload = {"jti": "abc", "sub": "u1", "iat": 1}
    assert await token_is_revoked(payload) is False
    await revoke_jti(fake, "abc", 60)
    assert await token_is_revoked(payload) is True
    token_revocation._reset_revocation_redis_for_tests()


@pytest.mark.asyncio
async def test_jti_revocation():
    r = _FakeRedis()
    payload = {"jti": "abc", "sub": "u1", "iat": 1000}
    assert await is_revoked(r, payload) is False
    await revoke_jti(r, "abc", ttl_seconds=60)
    assert await is_revoked(r, payload) is True
    # A different token (different jti) for the same user is unaffected.
    assert await is_revoked(r, {"jti": "xyz", "sub": "u1", "iat": 1000}) is False


@pytest.mark.asyncio
async def test_revoke_jti_noops_on_missing_or_expired():
    r = _FakeRedis()
    await revoke_jti(r, "", ttl_seconds=60)  # no jti
    await revoke_jti(r, "abc", ttl_seconds=0)  # already expired
    assert r.store == {}


@pytest.mark.asyncio
async def test_user_cutoff_revokes_older_tokens_only():
    r = _FakeRedis()
    await revoke_user_tokens(r, "u1", cutoff_ts=5000, ttl_seconds=3600)
    # Issued before the cutoff → revoked.
    assert await is_revoked(r, {"jti": "a", "sub": "u1", "iat": 4999}) is True
    # Issued at/after the cutoff → still valid (a fresh post-reset login).
    assert await is_revoked(r, {"jti": "b", "sub": "u1", "iat": 5000}) is False
    assert await is_revoked(r, {"jti": "c", "sub": "u1", "iat": 6000}) is False
    # A different user is unaffected.
    assert await is_revoked(r, {"jti": "d", "sub": "u2", "iat": 1}) is False


@pytest.mark.asyncio
async def test_missing_iat_under_active_cutoff_is_revoked():
    r = _FakeRedis()
    await revoke_user_tokens(r, "u1", cutoff_ts=5000, ttl_seconds=3600)
    # A legacy token with no iat can't be proven fresh → treated as revoked.
    assert await is_revoked(r, {"jti": "a", "sub": "u1"}) is True


@pytest.mark.asyncio
async def test_fail_open_on_redis_error():
    # A Redis outage must not lock everyone out — is_revoked returns False.
    assert (
        await is_revoked(_BrokenRedis(), {"jti": "a", "sub": "u1", "iat": 1}) is False
    )
