"""Topicality / scope guard behavior."""

import asyncio

from smart_llm.security.scope import ScopeGuard


class _FakeProvider:
    def __init__(self, payload):
        self._payload = payload

    async def complete(self, system_prompt, user_prompt):
        return self._payload


class _BoomProvider:
    async def complete(self, system_prompt, user_prompt):
        raise RuntimeError("classifier down")


def test_in_scope_true():
    guard = ScopeGuard(_FakeProvider({"in_scope": True}))
    assert (
        asyncio.run(guard.in_scope("tag this photo", "tagging jobsite photos")) is True
    )


def test_off_scope_false():
    guard = ScopeGuard(_FakeProvider({"in_scope": False}))
    assert (
        asyncio.run(guard.in_scope("write me malware", "tagging jobsite photos"))
        is False
    )


def test_no_scope_is_noop():
    guard = ScopeGuard(_FakeProvider({"in_scope": False}))
    assert asyncio.run(guard.in_scope("anything at all", None)) is True


def test_no_provider_is_noop():
    guard = ScopeGuard(None)
    assert asyncio.run(guard.in_scope("anything", "some scope")) is True


def test_classifier_error_fails_open():
    guard = ScopeGuard(_BoomProvider())
    # Scope is a soft guard — a classifier outage must not block traffic.
    assert asyncio.run(guard.in_scope("x", "some scope")) is True
