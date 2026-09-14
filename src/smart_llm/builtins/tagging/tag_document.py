"""``tag_document`` — composer that chains parse → generate → auto-create.

For most callers this is the only tagging skill needed: pass a PDF/DOCX
path in, get tags suggested + persisted in one shot.
"""

from typing import Any

from smart_llm.base import Tool
from smart_llm.builtins.parsing.parse_docx import ParseDocxSkill

# Importing the parsing + generate skills triggers their registration.
from smart_llm.builtins.parsing.parse_pdf import ParsePdfSkill
from smart_llm.builtins.tagging.generate_tags import GenerateTagsSkill
from smart_llm.db.models import MODALITY_DOCUMENT
from smart_llm.registry import register_tool


class TagDocumentSkill(Tool):
    """Pipe-line: detect filetype → extract text → ask LLM for tags."""

    def run(self, input_text: str, **kwargs: Any) -> str:
        # Heuristic: file extension drives the parser choice. Anything we
        # can't classify is passed through unchanged on the assumption
        # that the caller already extracted the text.
        lower = input_text.lower()
        if lower.endswith(".pdf"):
            text = ParsePdfSkill().run(input_text)
        elif lower.endswith(".docx"):
            text = ParseDocxSkill().run(input_text)
        else:
            text = input_text
        return GenerateTagsSkill().run(text)


register_tool(
    "tag_document",
    TagDocumentSkill,
    label="Tag Document",
    description="Parse a document and generate tag suggestions in one step.",
    modality=MODALITY_DOCUMENT,
)
