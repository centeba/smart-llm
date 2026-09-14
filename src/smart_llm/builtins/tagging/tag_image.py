"""``tag_image`` — composer that chains OCR → generate tags.

Mirrors :mod:`tag_document` but for image inputs: runs OCR via
:class:`ParseImageOcrSkill` then hands the recovered text to
:class:`GenerateTagsSkill` for the LLM to tag.
"""

from typing import Any

from smart_llm.base import Tool
from smart_llm.builtins.parsing.parse_image_ocr import ParseImageOcrSkill
from smart_llm.builtins.tagging.generate_tags import GenerateTagsSkill
from smart_llm.db.models import MODALITY_IMAGE
from smart_llm.registry import register_tool


class TagImageSkill(Tool):
    """Pipe-line: OCR the image → ask LLM for tags on the recovered text."""

    def run(self, input_text: str, **kwargs: Any) -> str:
        try:
            text = ParseImageOcrSkill().run(input_text)
        except Exception:
            # If OCR fails (e.g. no Tesseract), fall through with the raw
            # path — a vision-LLM agent can still describe the image.
            text = input_text
        return GenerateTagsSkill().run(text)


register_tool(
    "tag_image",
    TagImageSkill,
    label="Tag Image",
    description="OCR an image and generate tag suggestions in one step.",
    modality=MODALITY_IMAGE,
)
