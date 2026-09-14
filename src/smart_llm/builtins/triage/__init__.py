"""Triage / orchestration prompt-shaping skills.

These skills don't perform I/O — they augment an agent's prompt
with directives that frame how the LLM should approach a multi-step
task (e.g. classify document then route to the right sub-task).

Pure :class:`Tool` shape. The full agent-graph runtime (Phase E2)
that lets a parent agent actually *invoke* sub-agents is deferred;
in the meantime the orchestrator prompt drives the LLM through the
routing logic itself, calling the relevant per-modality skills
inline.
"""

from __future__ import annotations

from . import document_triage  # noqa: F401  — document_triage_orchestrator
