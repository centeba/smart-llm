"""Fail-open auth edges: token-revocation strict mode + API-key required mode."""

import pytest

import smart_llm.token_revocation as tr
from smart_llm.api.middleware import require_api_key
from smart_llm.token_revocation import is_revoked, token_is_revoked


class _BoomRedis:
    async def get(self, key):
        raise RuntimeError("revocation store down")


class _MapRedis:
    def __init__(self, data):
        self._data = data

    async def get(self, key):
        return self._data.get(key)


# ── token revocation ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_is_revoked_fail_open_default():
    # Redis error, default posture → not revoked (fail-open).
    assert await is_revoked(_BoomRedis(), {"jti": "x", "sub": "u"}) is False


@pytest.mark.asyncio
async def test_is_revoked_fail_closed_strict():
    # Redis error, strict → revoked (fail-closed / deny).
    assert await is_revoked(_BoomRedis(), {"jti": "x", "sub": "u"}, strict=True) is True


@pytest.mark.asyncio
async def test_is_revoked_hits_jti_denylist():
    r = _MapRedis({"sb:revoked:jti:abc": "1"})
    assert await is_revoked(r, {"jti": "abc"}) is True


@pytest.mark.asyncio
async def test_is_revoked_clean_token():
    r = _MapRedis({})
    assert await is_revoked(r, {"jti": "fresh", "sub": "u", "iat": 100}) is False


@pytest.mark.asyncio
async def test_token_is_revoked_strict_env_fails_closed(monkeypatch):
    monkeypatch.setattr(tr, "_revocation_redis", lambda: _BoomRedis())
    monkeypatch.setenv("TOKEN_REVOCATION_STRICT", "true")
    assert await token_is_revoked({"jti": "x", "sub": "u"}) is True


@pytest.mark.asyncio
async def test_token_is_revoked_default_fails_open(monkeypatch):
    monkeypatch.setattr(tr, "_revocation_redis", lambda: _BoomRedis())
    monkeypatch.delenv("TOKEN_REVOCATION_STRICT", raising=False)
    assert await token_is_revoked({"jti": "x", "sub": "u"}) is False


@pytest.mark.asyncio
async def test_token_is_revoked_not_configured_ignores_strict(monkeypatch):
    # Revocation not enforced here (no Redis) → never denies, even under strict.
    monkeypatch.setattr(tr, "_revocation_redis", lambda: None)
    monkeypatch.setenv("TOKEN_REVOCATION_STRICT", "true")
    assert await token_is_revoked({"jti": "x"}) is False


# ── API key required mode ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_api_key_anonymous_when_unconfigured_dev(monkeypatch):
    monkeypatch.delenv("SMART_LLM_API_KEYS", raising=False)
    monkeypatch.delenv("SMART_LLM_REQUIRE_API_KEY", raising=False)
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    assert await require_api_key(api_key=None) == "anonymous"


@pytest.mark.asyncio
async def test_api_key_required_flag_fails_closed(monkeypatch):
    from fastapi import HTTPException

    monkeypatch.delenv("SMART_LLM_API_KEYS", raising=False)
    monkeypatch.setenv("SMART_LLM_REQUIRE_API_KEY", "true")
    with pytest.raises(HTTPException) as ei:
        await require_api_key(api_key=None)
    assert ei.value.status_code == 500


@pytest.mark.asyncio
async def test_api_key_production_fails_closed(monkeypatch):
    from fastapi import HTTPException

    monkeypatch.delenv("SMART_LLM_API_KEYS", raising=False)
    monkeypatch.delenv("SMART_LLM_REQUIRE_API_KEY", raising=False)
    monkeypatch.setenv("ENVIRONMENT", "production")
    with pytest.raises(HTTPException) as ei:
        await require_api_key(api_key=None)
    assert ei.value.status_code == 500


@pytest.mark.asyncio
async def test_api_key_valid_and_invalid(monkeypatch):
    from fastapi import HTTPException

    monkeypatch.setenv("SMART_LLM_API_KEYS", "good1, good2")
    assert await require_api_key(api_key="good2") == "good2"
    with pytest.raises(HTTPException) as ei:
        await require_api_key(api_key="bad")
    assert ei.value.status_code == 401
