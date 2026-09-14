"""Shared cross-replica one-shot guard (HARDENING-PLAN A6a).

`run_once` claims a Redis SET-NX key so exactly one replica per boot window
runs a shared startup task. On a Redis error it fails CLOSED by default (skip
the task) and only runs anyway when the caller opts into `fail_open=True`.
"""

from __future__ import annotations

import asyncio

from smart_llm.service_runtime import run_once


class _FakeRedis:
    """Minimal SET-NX-EX semantics."""

    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    async def set(self, key, value, nx=False, ex=None):
        if nx and key in self._store:
            return None
        self._store[key] = value
        return True


class _BoomRedis:
    async def set(self, *a, **k):
        raise RuntimeError("redis down")


def test_only_first_caller_acquires():
    r = _FakeRedis()
    assert asyncio.run(run_once(r, "task")) is True
    assert asyncio.run(run_once(r, "task")) is False  # already claimed this window


def test_distinct_names_independent():
    r = _FakeRedis()
    assert asyncio.run(run_once(r, "a")) is True
    assert asyncio.run(run_once(r, "b")) is True


def test_fail_closed_by_default_on_redis_error():
    # Default: a Redis outage must NOT run the task on every replica.
    assert asyncio.run(run_once(_BoomRedis(), "task")) is False


def test_fail_open_opt_in_on_redis_error():
    # Opt-in: idempotent DDL still runs when Redis is down.
    assert asyncio.run(run_once(_BoomRedis(), "task", fail_open=True)) is True
