"""``parse_docx`` skill — extract text from a .docx file."""

from pathlib import Path
from typing import Any

from smart_llm.base import Tool
from smart_llm.db.models import MODALITY_DOCUMENT
from smart_llm.registry import register_tool


class ParseDocxSkill(Tool):
    def run(self, input_text: str, **kwargs: Any) -> str:
        try:
            from docx import Document  # python-docx
        except ImportError as exc:
            raise RuntimeError(
                "ParseDocxSkill requires 'python-docx'. Install with `pip install python-docx`."
            ) from exc

        path = Path(input_text)
        if not path.exists():
            return input_text  # already text — no-op
        doc = Document(str(path))
        return "\n".join(p.text for p in doc.paragraphs).strip()


register_tool(
    "parse_docx",
    ParseDocxSkill,
    label="Parse DOCX",
    description="Extract text from a Word .docx file.",
    modality=MODALITY_DOCUMENT,
)
