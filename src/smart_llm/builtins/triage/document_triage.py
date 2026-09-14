"""``document_triage_orchestrator`` — top-level routing directive.

Prompt skill consumed by the seeded ``document_triage_template``
agent. It tells the LLM how to route an inbound document through
the four downstream skills (``classify_intent``, ``extract_entities``,
``summarize``, ``generate_tags``) and what JSON shape to return.

Doesn't perform multi-agent dispatch by itself — that's Phase E2,
where a real ``OrchestratorSkill`` (smart-llm/orchestrator.py)
will fan-out to sub-agents in parallel. Until then the parent agent
runs all four steps inline against the same input + LLM call.
"""

from typing import Any

from smart_llm.base import Tool
from smart_llm.db.models import MODALITY_DOCUMENT
from smart_llm.registry import register_tool
from smart_llm.security.envelope import untrusted_envelope

_DIRECTIVE = (
    "You are a document triage router. Given the input document text:\n"
    "\n"
    "  1. CLASSIFY the document's intent into ONE of: "
    "``contract`` | ``invoice`` | ``correspondence`` | ``identity`` | "
    "``policy`` | ``other``.\n"
    "  2. ROUTE based on intent:\n"
    "       - contract / policy → run ``summarize`` AND ``extract_entities``.\n"
    "       - invoice / identity → run ``extract_entities`` AND ``generate_tags``.\n"
    "       - correspondence    → run ``classify_intent`` (sender_role)\n"
    "                              AND ``summarize``.\n"
    "       - other             → run ``generate_tags`` only.\n"
    "  3. RETURN a single JSON object with this shape:\n"
    "       {\n"
    '         "intent": <one of the 6 above>,\n'
    '         "entities": [...]            // present iff extracted\n'
    '         "summary": "..."             // present iff summarized\n'
    '         "tags": [...]                // present iff tagged\n'
    '         "tag_confidence": {...}      // matches tags 1:1\n'
    '         "action": "file" | "approve" | "escalate"\n'
    "       }\n"
    "\n"
    "Do not include keys for steps you skipped. Return only valid JSON — "
    "no markdown fences, no commentary."
)


class DocumentTriageOrchestratorSkill(Tool):
    def run(self, input_text: str, **kwargs: Any) -> str:
        return (
            f"{_DIRECTIVE}\n\n{untrusted_envelope(input_text, label='DOCUMENT TEXT')}"
        )


register_tool(
    "document_triage_orchestrator",
    DocumentTriageOrchestratorSkill,
    label="Document Triage Orchestrator",
    description=(
        "Top-level routing prompt for the Document Triage agent. Classifies "
        "intent then routes through summarize / extract_entities / "
        "generate_tags / classify_intent based on the result."
    ),
    modality=MODALITY_DOCUMENT,
)
