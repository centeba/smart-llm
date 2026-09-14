"""Autonomous-agent tool-policy gate.

Sits in the agent loop's tool-dispatch path (:func:`smart_llm.agent_loop._dispatch_all`)
and decides, for each tool call an autonomous agent wants to make, whether to:

- **allow**  — dispatch it unattended;
- **deny**   — block it (tool not permitted for this agent);
- **approval_required** — pause for a human to approve before dispatch.

The decision combines the tool's *risk tier* (read / write / external — from
:meth:`smart_llm.base.ActionTool.effective_risk`) with the agent's per-tool
*approval mode* (``AIAgentSkillLink.approval_mode``), plus — for cross-company
actions — a deny-by-default authorization check (wired in P5).

The gate is OPTIONAL: when ``run_agent_loop`` is called without one
(``policy_gate=None``), behaviour is identical to before this module existed.
Only the durable autonomous run path constructs and passes a gate.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from smart_llm.db.models import (
    APPROVAL_ALLOW,
    APPROVAL_AUTO,
    APPROVAL_DENY,
    APPROVAL_REQUIRE,
    DECISION_ALLOW,
    DECISION_APPROVAL_REQUIRED,
    DECISION_DENY,
)

from .audit_chain import AuditChain

log = logging.getLogger(__name__)

Decision = Literal["allow", "deny", "approval_required"]


def resolve_tool_policy(approval_mode: str | None, tool_risk: str) -> Decision:
    """Pure decision: combine the per-tool ``approval_mode`` with the tool's
    risk tier into an allow / deny / approval_required outcome.

    Default-safe semantics:
    - ``deny``             → deny (always).
    - ``require_approval`` → approval_required (always).
    - ``allow``            → allow (admin force-opt-in, regardless of risk).
    - ``auto`` (default)   → risk-default: ``read`` runs unattended; ``write``
      and ``external`` require approval. So a high-risk tool can NEVER run
      unattended unless an admin explicitly set ``allow`` for it.
    - missing/unknown link → deny (tool not permitted for this agent).
    """
    if approval_mode is None:
        return DECISION_DENY  # not in the agent's allow-list
    if approval_mode == APPROVAL_DENY:
        return DECISION_DENY
    if approval_mode == APPROVAL_REQUIRE:
        return DECISION_APPROVAL_REQUIRED
    if approval_mode == APPROVAL_ALLOW:
        return DECISION_ALLOW
    # APPROVAL_AUTO (or any unrecognised value → treat as auto, the safe default)
    if approval_mode == APPROVAL_AUTO or True:
        return DECISION_ALLOW if tool_risk == "read" else DECISION_APPROVAL_REQUIRED


@dataclass
class ToolPolicyDecision:
    decision: Decision
    reason: str = ""
    target_company_id: str | None = None
    paying_company_id: str | None = None
    # Structured record for the agent_action_audit row.
    audit: dict[str, Any] = field(default_factory=dict)

    @property
    def allowed(self) -> bool:
        return self.decision == DECISION_ALLOW


@dataclass
class AgentRunContext:
    """Per-run context the gate evaluates against. Constructed by the caller
    (the autonomous run path) from the agent config + its skill links."""

    agent_id: str
    acting_company_id: str
    # Registry tool name → approval_mode. A tool absent from this map is NOT
    # in the agent's allow-list and is denied.
    tool_modes: dict[str, str] = field(default_factory=dict)
    agent_run_id: str | None = None
    # P5: async callable (agent_id, target_company_id, action) -> bool. When
    # set, a cross-company target triggers a deny-by-default authz check.
    authz_checker: Callable[[str, str, str], Awaitable[bool]] | None = None
    # Optional async sink to persist an agent_action_audit row:
    # (audit: dict) -> None.
    audit_sink: Callable[[dict[str, Any]], Awaitable[None]] | None = None
    # Optional async callable (agent_id, acting_company_id, tool_name) -> bool
    # (True = within limit). When set, an otherwise-allowed call that exceeds the
    # tenant+tool invocation rate is denied. An abuse control, distinct from the
    # loop's cost/budget caps. See smart_llm.security.rate_limit.
    rate_limiter: Callable[[str, str, str], Awaitable[bool]] | None = None
    # Optional tamper-evident hash chain. When set, each audit record is stamped
    # with prev_hash/record_hash before it reaches audit_sink, so the persisted
    # trail is verifiable (see smart_llm.security.audit_chain). One per run; seed
    # its head from the tenant's last persisted record_hash to chain across runs.
    audit_chain: AuditChain | None = None


def _args_digest(args: Any) -> str:
    try:
        if hasattr(args, "model_dump"):
            payload = args.model_dump()
        elif isinstance(args, dict):
            payload = args
        else:
            payload = {"repr": repr(args)}
        blob = json.dumps(payload, sort_keys=True, default=str)
    except Exception:  # noqa: BLE001
        blob = repr(args)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


class ToolPolicyGate:
    """Evaluates each tool call against the run context's policy."""

    def __init__(self, ctx: AgentRunContext):
        self.ctx = ctx

    async def evaluate(
        self,
        *,
        tool_name: str,
        tool_cls: type,
        validated_args: Any,
    ) -> ToolPolicyDecision:
        risk = (
            tool_cls.effective_risk()
            if hasattr(tool_cls, "effective_risk")
            else "write"
        )
        mode = self.ctx.tool_modes.get(tool_name)  # None → not allow-listed
        base = resolve_tool_policy(mode, risk)

        target_company = None
        # ── Cross-company target resolution (P5) ──────────────────────────
        # Only tools that explicitly declare ``cross_tenant_arg`` may target
        # another company; the target is read from the validated arg (never an
        # inferred/opaque id). Any cross-company effect is deny-by-default
        # unless an authz delegation check passes.
        cross_arg = getattr(tool_cls, "cross_tenant_arg", None)
        if cross_arg and validated_args is not None:
            raw_target = getattr(validated_args, cross_arg, None)
            if raw_target is not None and str(raw_target) != str(
                self.ctx.acting_company_id
            ):
                target_company = str(raw_target)
                if base != DECISION_DENY:
                    if self.ctx.authz_checker is None:
                        base = DECISION_DENY  # no delegation wiring → deny
                    else:
                        ok = await self.ctx.authz_checker(
                            self.ctx.agent_id, target_company, tool_name
                        )
                        if not ok:
                            base = DECISION_DENY

        # ── Invocation rate limit (abuse control) ─────────────────────────────
        # Only an otherwise-allowed call consumes rate budget — denied/approval
        # calls don't run, so they shouldn't count. Limiter failure fails OPEN
        # (availability): a limiter blip must not deny every legitimate call.
        rate_limited = False
        if base == DECISION_ALLOW and self.ctx.rate_limiter is not None:
            try:
                within = await self.ctx.rate_limiter(
                    self.ctx.agent_id, self.ctx.acting_company_id, tool_name
                )
            except Exception:  # noqa: BLE001 — limiter must never break a run
                log.warning(
                    "tool_policy: rate_limiter failed (allowing)", exc_info=True
                )
                within = True
            if not within:
                base = DECISION_DENY
                rate_limited = True

        if rate_limited:
            reason = "rate limit exceeded"
        else:
            reason = {
                DECISION_ALLOW: "allowed",
                DECISION_DENY: (
                    "tool not permitted for this agent"
                    if mode is None
                    else (
                        "cross-company action denied (no delegation grant)"
                        if target_company
                        else f"denied by policy ({mode})"
                    )
                ),
                DECISION_APPROVAL_REQUIRED: "requires human approval before dispatch",
            }[base]

        audit = {
            "agent_run_id": self.ctx.agent_run_id,
            "agent_id": self.ctx.agent_id,
            "tool_name": tool_name,
            "acting_company_id": self.ctx.acting_company_id,
            "target_company_id": target_company,
            "decision": base,
            "reason": reason,
            "args_digest": _args_digest(validated_args),
        }
        # Tamper-evident chaining: stamp prev_hash/record_hash so the persisted
        # audit trail is verifiable end to end. No-op when no chain is wired.
        if self.ctx.audit_chain is not None:
            audit = self.ctx.audit_chain.stamp(audit)
        decision = ToolPolicyDecision(
            decision=base,
            reason=reason,
            target_company_id=target_company,
            audit=audit,
        )
        if self.ctx.audit_sink is not None:
            try:
                await self.ctx.audit_sink(audit)
            except Exception:  # noqa: BLE001 — auditing must never break a run
                log.warning("tool_policy: audit sink failed", exc_info=True)
        return decision
