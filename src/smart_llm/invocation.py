"""Tool invocation context (G1).

A generic, domain-pure carrier the agent loop threads to tools that need to act
on behalf of the caller — read their identity, call an upstream service with a
short-lived token, and share a per-invocation cache across tools. It carries
primitives only (ids, roles, a token, a trace id, a cache handle); it never
holds domain content.

Back-compat: the loop passes the context to ``run_action`` **only when the tool
opts in** by declaring a ``ctx`` parameter. Tools written as
``run_action(self, args, *, db_session)`` are unaffected (``ctx`` defaults to
``None`` and is simply not passed).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass
class InvocationContext:
    """Per-invocation context for tools. All fields optional / generic."""

    user_id: str | None = None
    company_id: str | None = None
    roles: list[str] = field(default_factory=list)
    # A short-lived auth token / M2M key the tool can use to call back into the
    # platform on behalf of the caller. Never logged.
    auth_token: str | None = None
    trace_id: str | None = None
    # Request-scoped memo shared across every tool in one invocation, so two
    # tools that need the same upstream fetch only pay for it once.
    cache: dict[str, Any] = field(default_factory=dict)

    async def cached(self, key: str, factory: Callable[[], Awaitable[Any]]) -> Any:
        """Return ``cache[key]``, computing it via ``factory`` once if absent."""
        if key not in self.cache:
            self.cache[key] = await factory()
        return self.cache[key]
