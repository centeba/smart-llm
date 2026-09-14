"""Tests for smart_llm.service_runtime (replica-aware pool sizing)."""

import importlib
from datetime import timedelta

import pytest

from smart_llm.service_runtime import (
    AUTH_ERROR_HEADER,
    AUTH_ERROR_TOKEN_EXPIRED,
    graceful_shutdown_timeout,
    resolve_pool_sizing,
)


@pytest.fixture(autouse=True)
def _clear_replica_env(monkeypatch):
    monkeypatch.delenv("REPLICA_COUNT", raising=False)
    yield


# ── graceful_shutdown_timeout (readiness gate 12) ────────────────────────────


def test_graceful_shutdown_timeout_default_30s(monkeypatch):
    monkeypatch.delenv("TEMPORAL_GRACEFUL_SHUTDOWN_SECONDS", raising=False)
    assert graceful_shutdown_timeout() == timedelta(seconds=30)


def test_graceful_shutdown_timeout_env_override(monkeypatch):
    monkeypatch.setenv("TEMPORAL_GRACEFUL_SHUTDOWN_SECONDS", "45")
    assert graceful_shutdown_timeout() == timedelta(seconds=45)


def test_graceful_shutdown_timeout_zero_allowed(monkeypatch):
    # 0 = old behavior (cancel immediately); explicit opt-out must be honored.
    monkeypatch.setenv("TEMPORAL_GRACEFUL_SHUTDOWN_SECONDS", "0")
    assert graceful_shutdown_timeout() == timedelta(seconds=0)


def test_graceful_shutdown_timeout_invalid_falls_back(monkeypatch):
    monkeypatch.setenv("TEMPORAL_GRACEFUL_SHUTDOWN_SECONDS", "not-a-number")
    assert graceful_shutdown_timeout() == timedelta(seconds=30)


def test_default_single_replica_unchanged(monkeypatch):
    monkeypatch.delenv("REPLICA_COUNT", raising=False)
    assert resolve_pool_sizing(20, 30) == (20, 30)


def test_scales_by_replica_count(monkeypatch):
    monkeypatch.setenv("REPLICA_COUNT", "3")
    # floor(20/3)=6, floor(30/3)=10
    assert resolve_pool_sizing(20, 30) == (6, 10)


def test_never_below_one_pool(monkeypatch):
    monkeypatch.setenv("REPLICA_COUNT", "50")
    pool, overflow = resolve_pool_sizing(5, 0)
    assert pool == 1  # floor(5/50)=0 -> clamped to 1
    assert overflow == 0


def test_invalid_replica_env_falls_back_to_one(monkeypatch):
    monkeypatch.setenv("REPLICA_COUNT", "not-a-number")
    assert resolve_pool_sizing(10, 20) == (10, 20)


def test_zero_or_negative_treated_as_one(monkeypatch):
    monkeypatch.setenv("REPLICA_COUNT", "0")
    assert resolve_pool_sizing(10, 20) == (10, 20)


def test_auth_error_constants():
    assert AUTH_ERROR_HEADER == "X-Auth-Error"
    assert AUTH_ERROR_TOKEN_EXPIRED == "token_expired"


def test_module_exports_helpers():
    mod = importlib.import_module("smart_llm.service_runtime")
    for name in (
        "add_readiness_route",
        "install_exception_handler",
        "db_check",
        "redis_check",
        "temporal_check",
        "current_request_id",
    ):
        assert hasattr(mod, name), name
