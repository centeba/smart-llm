"""Phase-E2 multi-agent orchestration.

The platform's "agentic" story until now ran one ``AIAgentConfig`` per
node. Real workflows often need a *graph*: a classifier picks an
intent, then routes to one of N specialised follow-up agents.

This module ships:

- :class:`AgentGraphSpec` — typed description of a small DAG of
  ``AIAgentConfig`` invocations. Nodes are agents; edges carry the
  prior agent's response forward as input. A node may declare a
  ``branch`` predicate (Python expression evaluated against the
  upstream response) so the dispatcher can pick a single downstream
  branch instead of fanning out.
- :class:`OrchestratorSkill` — :class:`Tool` subclass registered as
  ``orchestrate_agents``. Hosts call it indirectly via the workflow
  builder's "Agent Graph" node; the executor passes a JSON spec.
- :func:`run_agent_graph` — async entry point used by the Mit Stack
  ``run_agent_graph_node`` Temporal activity (Phase E2 backend).

A depth cap prevents runaway cost: the spec's transitive depth must
not exceed :data:`MAX_DEPTH` (default 3). Cycles are rejected at
parse time.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from smart_llm.base import Tool
from smart_llm.db.models import MODALITY_ANY
from smart_llm.registry import register_tool

log = logging.getLogger(__name__)

MAX_DEPTH = 3


@dataclass
class AgentGraphNode:
    """One node in an agent graph.

    ``agent_id`` is the UUID of an :class:`AIAgentConfig`. ``next``
    lists downstream node ids; the dispatcher fans out (parallel) by
    default. If ``branch`` is set, only the matching branch runs.

    ``branch`` is a tiny dotted-key match: ``"intent==support"``
    fires when ``upstream.data['intent'] == 'support'``. The full
    Python eval surface is intentionally avoided — keeps the spec
    inspectable + safe to round-trip through workflow JSON.
    """

    id: str
    agent_id: str
    next: list[str] = field(default_factory=list)
    branch: str | None = None  # e.g. "intent==support"

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> AgentGraphNode:
        return cls(
            id=str(raw["id"]),
            agent_id=str(raw["agent_id"]),
            next=[str(x) for x in raw.get("next", [])],
            branch=raw.get("branch"),
        )


@dataclass
class AgentGraphSpec:
    """Top-level graph spec — one entry node, depth ≤ ``MAX_DEPTH``."""

    entry: str
    nodes: dict[str, AgentGraphNode]

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> AgentGraphSpec:
        nodes = {n["id"]: AgentGraphNode.from_dict(n) for n in raw.get("nodes", [])}
        spec = cls(entry=str(raw["entry"]), nodes=nodes)
        spec.validate()
        return spec

    # ── validation ──────────────────────────────────────────────────────────

    def validate(self) -> None:
        if self.entry not in self.nodes:
            raise ValueError(f"AgentGraphSpec.entry '{self.entry}' missing from nodes")
        # Detect cycles + measure depth via DFS.
        visiting: set[str] = set()

        def _walk(node_id: str, depth: int) -> int:
            if depth > MAX_DEPTH:
                raise ValueError(
                    f"AgentGraphSpec exceeds MAX_DEPTH={MAX_DEPTH} at node '{node_id}'"
                )
            if node_id in visiting:
                raise ValueError(f"AgentGraphSpec has a cycle through '{node_id}'")
            visiting.add(node_id)
            node = self.nodes.get(node_id)
            if node is None:
                raise ValueError(f"AgentGraphSpec references unknown node '{node_id}'")
            for nxt in node.next:
                _walk(nxt, depth + 1)
            visiting.discard(node_id)
            return depth

        _walk(self.entry, 1)


# ── runtime ────────────────────────────────────────────────────────────────

# A host-supplied callable that resolves + runs a single agent. Swapped
# in by the Mit Stack activity (which already knows how to look up
# ``AIAgentConfig`` + decrypt API keys). Decoupling like this keeps
# smart-llm's runtime free of host imports.
AgentRunner = Callable[[str, str], Awaitable[dict[str, Any]]]
# (agent_id, input) -> response_data


@dataclass
class HopContext:
    """Identity of one agent-to-agent hop, handed to a ``hop_authorizer`` so the
    host can decide whether node A (agent) may invoke node B (agent) — e.g. a
    per-tenant delegation / trust-boundary check across the graph."""

    from_node_id: str
    from_agent_id: str
    to_node_id: str
    to_agent_id: str


# Async callable (HopContext) -> bool. Optional; when supplied, every downstream
# hop must be authorized (a raise or False denies — fail-closed, like the
# tool-policy gate's authz_checker). When None, all hops run (unchanged).
HopAuthorizer = Callable[["HopContext"], Awaitable[bool]]


def _branch_matches(branch: str | None, upstream: dict[str, Any]) -> bool:
    """Tiny ``key==value`` predicate evaluator.

    Returns True if no branch is set (unconditional edge) or if
    ``upstream[key]`` equals the literal after ``==``. Anything more
    elaborate (regex, AND/OR) is deferred — keeping the predicate
    obvious avoids surprises in production graphs.
    """
    if not branch:
        return True
    if "==" not in branch:
        log.warning("orchestrator: ignoring malformed branch predicate %r", branch)
        return True
    key, _, value = branch.partition("==")
    return str(upstream.get(key.strip())) == value.strip()


async def run_agent_graph(
    spec: AgentGraphSpec,
    initial_input: str,
    *,
    runner: AgentRunner,
    guard: Any = None,
    hop_authorizer: HopAuthorizer | None = None,
) -> dict[str, Any]:
    """Run ``spec`` starting from ``spec.entry``.

    Returns ``{ "results": {node_id: response_data, ...} }`` so the
    caller can pick the leaf they care about. Fan-out levels run
    concurrently via :func:`asyncio.gather`.

    When ``guard`` (a :class:`~smart_llm.security.guard.SafetyGuard`) is
    supplied, each upstream response is screened before it is fed into a
    downstream node — so a poisoned/abusive node output cannot steer the rest
    of the graph. Per-node agents are normally already guarded by the Agent
    core; this is a belt-and-suspenders hop check for runners that bypass it.

    When ``hop_authorizer`` is supplied, every downstream hop A→B is authorized
    before B runs (identity in :class:`HopContext`). A ``False`` or a raise
    denies the hop — fail-closed — and B is not invoked; a denial marker is
    recorded in ``results`` for that node. The entry node runs unconditionally
    (the host authorizes starting the graph separately).
    """
    results: dict[str, dict[str, Any]] = {}

    async def _authorized(node: AgentGraphNode, nxt: AgentGraphNode) -> bool:
        if hop_authorizer is None:
            return True
        ctx = HopContext(
            from_node_id=node.id,
            from_agent_id=node.agent_id,
            to_node_id=nxt.id,
            to_agent_id=nxt.agent_id,
        )
        try:
            return bool(await hop_authorizer(ctx))
        except Exception:  # noqa: BLE001 — authz failure denies (fail-closed)
            log.warning(
                "orchestrator: hop_authorizer raised for %s -> %s; denying",
                node.id,
                nxt.id,
                exc_info=True,
            )
            return False

    async def _run_node(node_id: str, input_text: str) -> None:
        node = spec.nodes[node_id]
        log.debug("orchestrator: running %s (agent=%s)", node_id, node.agent_id)
        out = await runner(node.agent_id, input_text)
        results[node_id] = out

        # Each downstream may have a ``branch`` filter — gather only
        # those that match into a parallel batch.
        next_inputs: list[tuple[str, str]] = []
        for nxt_id in node.next:
            nxt = spec.nodes.get(nxt_id)
            if nxt is None:
                continue
            if not _branch_matches(nxt.branch, out):
                continue
            # Per-hop authorization (deny-by-default when a hop crosses a trust
            # boundary): an unauthorized hop is not invoked.
            if not await _authorized(node, nxt):
                results[nxt_id] = {
                    "error": "agent hop denied by authorization",
                    "denied": True,
                }
                log.warning("orchestrator: hop %s -> %s denied", node_id, nxt_id)
                continue
            # Pass the upstream response as JSON-ish text so the
            # next agent's first user turn sees the full payload.
            hop_text = _coerce_text(out)
            if guard is not None:
                # Screen the cross-hop text; a flagged hop aborts that
                # branch rather than propagating poisoned context.
                await guard.screen_tool_result(hop_text)
            next_inputs.append((nxt_id, hop_text))
        if next_inputs:
            await asyncio.gather(*(_run_node(nid, ntxt) for nid, ntxt in next_inputs))

    await _run_node(spec.entry, initial_input)
    return {"results": results}


def _coerce_text(data: dict[str, Any]) -> str:
    """Render an upstream response into something the next agent can read."""
    import json

    try:
        return json.dumps(data, ensure_ascii=False)
    except Exception:
        return str(data)


# ── registered skill ───────────────────────────────────────────────────────


class OrchestratorSkill(Tool):
    """Pre-LLM skill that flags the current run as orchestrated.

    The actual graph dispatch happens in the
    ``run_agent_graph_node`` activity, not here — this skill exists
    so workflow authors can attach an ``Agent Graph`` reference to a
    standard agent for diagnostic/logging purposes. In the common
    case the skill is a no-op pass-through.
    """

    def run(self, input_text: str, **kwargs: Any) -> str:
        # The activity reads its spec from kwargs/config; the prompt
        # input simply propagates unchanged.
        return input_text


register_tool(
    "orchestrate_agents",
    OrchestratorSkill,
    label="Orchestrate Agents",
    description=(
        "Marker skill for agent-graph nodes. Real dispatch is handled by "
        "smart_llm.orchestrator.run_agent_graph in the host activity."
    ),
    modality=MODALITY_ANY,
    params_schema={
        "type": "object",
        "properties": {
            "spec": {
                "type": "object",
                "description": "AgentGraphSpec JSON (entry + nodes). See orchestrator.AgentGraphSpec.",
            },
        },
        "required": ["spec"],
    },
)
