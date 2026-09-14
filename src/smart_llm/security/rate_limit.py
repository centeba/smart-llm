"""Tool-invocation rate limiting — an abuse control for the tool-policy gate.

Distinct from the loop's cost controls (`LoopGuards.max_cost_usd`, the monthly
budget gate): those bound *spend*; this bounds *invocation frequency* per tenant
and tool, so a looping or abusive agent can't hammer a tool (or a downstream
vendor) across many runs.

Ships an in-memory token bucket (per-replica). A cluster-wide limiter (Redis) is
supplied by the host through the same callable seam
(:attr:`smart_llm.security.tool_policy.AgentRunContext.rate_limiter`), exactly as
`authz_checker` / `audit_sink` are injected — smart-llm keeps no Redis dependency.
"""

import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class RateLimit:
    """A token-bucket policy: ``capacity`` burst tokens, refilled at
    ``refill_per_sec`` sustained tokens/second."""

    capacity: float
    refill_per_sec: float


class TokenBucketRateLimiter:
    """In-memory (per-replica) token bucket keyed by an arbitrary string.

    Not thread-safe by design — the agent loop is single-threaded async; each
    ``check`` is a short non-awaiting critical section."""

    def __init__(self, limit: RateLimit):
        self._limit = limit
        self._buckets: dict[str, tuple[float, float]] = {}  # key -> (tokens, last_ts)

    def check(self, key: str, *, cost: float = 1.0) -> bool:
        """Consume ``cost`` tokens for ``key``; return whether they were available."""
        now = time.monotonic()
        tokens, last = self._buckets.get(key, (self._limit.capacity, now))
        tokens = min(
            self._limit.capacity, tokens + (now - last) * self._limit.refill_per_sec
        )
        if tokens >= cost:
            self._buckets[key] = (tokens - cost, now)
            return True
        self._buckets[key] = (tokens, now)
        return False


def make_tool_rate_limiter(
    default: RateLimit,
    *,
    per_tool: dict[str, RateLimit] | None = None,
) -> Callable[[str, str, str], Awaitable[bool]]:
    """Build a ``rate_limiter`` callable for ``AgentRunContext``.

    Bounds each ``(company_id, tool_name)`` pair. ``per_tool`` overrides the
    ``default`` policy for named tools. The returned async callable has the
    ``(agent_id, company_id, tool_name) -> bool`` shape the gate expects.
    """
    per_tool = per_tool or {}
    limiters: dict[str, TokenBucketRateLimiter] = {}

    def _limiter_for(tool_name: str) -> TokenBucketRateLimiter:
        return limiters.setdefault(
            tool_name, TokenBucketRateLimiter(per_tool.get(tool_name, default))
        )

    async def _check(agent_id: str, company_id: str, tool_name: str) -> bool:
        return _limiter_for(tool_name).check(f"{company_id}:{tool_name}")

    return _check
