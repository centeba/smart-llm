"""``tag_video`` — composer that chains transcription → generate tags."""

from typing import Any

from smart_llm.base import Tool
from smart_llm.builtins.parsing.parse_video import ParseVideoTranscriptSkill
from smart_llm.builtins.tagging.generate_tags import GenerateTagsSkill
from smart_llm.db.models import MODALITY_VIDEO
from smart_llm.registry import register_tool


class TagVideoSkill(Tool):
    """Pipe-line: transcribe the video → ask LLM for tags on the transcript."""

    def run(self, input_text: str, **kwargs: Any) -> str:
        try:
            text = ParseVideoTranscriptSkill().run(input_text)
        except NotImplementedError:
            # Phase E5 wires real Whisper/vision-LLM fallbacks. Until then,
            # let the LLM see the path/identifier and do its best.
            text = input_text
        return GenerateTagsSkill().run(text)


register_tool(
    "tag_video",
    TagVideoSkill,
    label="Tag Video",
    description="Transcribe a video and generate tag suggestions in one step.",
    modality=MODALITY_VIDEO,
)
