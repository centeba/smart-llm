"""``parse_video_transcript`` skill — extract a transcript from a video.

Phase-E5 strategy chain:

1. Local Whisper on the video's audio track (Whisper's CLI handles
   most container formats directly).
2. Hosted transcription API (OpenAI ``whisper-1``).
3. Vision-LLM frame-sampling fallback (ffmpeg → frames every N
   seconds → vision-LLM describes each → stitched together) for the
   pathological case where the video has no usable audio.

Configurable via the AISkill's ``model_configuration`` — see
:mod:`fallback_chain` for the full key list.
"""

from __future__ import annotations

from typing import Any

from smart_llm.base import Tool
from smart_llm.db.models import MODALITY_VIDEO
from smart_llm.registry import register_tool

from .fallback_chain import (
    run_chain_mixed,
    transcription_api_strategy,
    video_vision_strategy,
    whisper_local_strategy,
)


class ParseVideoTranscriptSkill(Tool):
    def run(self, input_text: str, **kwargs: Any) -> str:
        cfg = dict(kwargs)
        result = run_chain_mixed(
            input_text,
            cfg,
            [
                ("whisper_local", whisper_local_strategy),
                ("transcription_api", transcription_api_strategy),
                ("video_vision", video_vision_strategy),
            ],
        )
        if cfg.get("include_strategy"):
            return f"[strategy={result.strategy}]\n{result.text}"
        return result.text


register_tool(
    "parse_video_transcript",
    ParseVideoTranscriptSkill,
    label="Transcribe Video",
    description=(
        "Transcribe a video using Whisper (local → API), with a "
        "vision-LLM frame-sampling fallback. Configure provider + "
        "frame interval via model_configuration."
    ),
    modality=MODALITY_VIDEO,
)
