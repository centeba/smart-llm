"""``summarize_video`` — produce a concise narrative summary of an mp4
or other video file.

Pipeline:

1. :class:`ParseVideoTranscriptSkill` (Whisper local → API → vision-
   frame fallback). Whatever strategy succeeds, we get a transcript
   *or* a frame-by-frame description string.
2. Wrap the recovered text in a directive that asks the agent to
   summarise the video in 3-5 sentences plus surface
   ``key_moments`` (timestamp-tagged when the transcript carries
   them).

The result is a directive string ready to be sent to a downstream
LLM via :meth:`smart_llm.Agent.analyze` — it does not call an LLM
itself. That keeps the skill cheap to chain inside ``run_with_skills``
where the agent's own provider/model is the one that produces the
summary, honouring the company's KeyManager and budget guard.
"""

from __future__ import annotations

from typing import Any

from smart_llm.base import Tool
from smart_llm.db.models import MODALITY_VIDEO
from smart_llm.registry import register_tool
from smart_llm.security.envelope import untrusted_envelope

from .parse_video import ParseVideoTranscriptSkill

_DIRECTIVE = (
    "You are summarising a video. The text below is either a "
    "verbatim transcript of the audio track or, if the video had no "
    "usable audio, a frame-by-frame description sampled every N "
    "seconds. Reply with a strict JSON object — no markdown, no "
    "prose — with these fields:\n"
    "  summary: 3-5 sentence narrative of what happens in the video\n"
    "  key_moments: array of {timestamp_seconds:int, description:str} "
    "objects (omit timestamps when the input has none)\n"
    "  dominant_topics: array of 1-5 short topic phrases\n"
    "  has_speech: boolean — true if the input looks like a transcript "
    "(speakers / sentences) rather than a frame description\n"
)


class SummarizeVideoSkill(Tool):
    """Transcribe-then-summarise composer for videos.

    The transcribe step is configurable through the same kwargs as
    :class:`ParseVideoTranscriptSkill` (``whisper_bin``,
    ``transcription_provider``, ``vision_provider``,
    ``video_frame_interval_seconds``). Pass ``include_strategy=True``
    in kwargs to surface which transcript strategy fired (helpful in
    the run-history viewer).
    """

    def run(self, input_text: str, **kwargs: Any) -> str:
        try:
            transcript = ParseVideoTranscriptSkill().run(input_text, **kwargs)
        except Exception as exc:  # noqa: BLE001
            return (
                f"{_DIRECTIVE}\n\n"
                f"[transcription failed: {exc}; the video may be unreadable]"
            )
        if not transcript or not transcript.strip():
            return f"{_DIRECTIVE}\n\n[transcription returned empty text]"
        return f"{_DIRECTIVE}\n\n{untrusted_envelope(transcript, label='TRANSCRIPT')}"


register_tool(
    "summarize_video",
    SummarizeVideoSkill,
    label="Summarize Video",
    description=(
        "Transcribe a video then ask the LLM for a JSON summary "
        "(narrative + key_moments + topics). Inherits transcription "
        "config from parse_video_transcript."
    ),
    modality=MODALITY_VIDEO,
    params_schema={
        "type": "object",
        "properties": {
            "video_frame_interval_seconds": {
                "type": "integer",
                "minimum": 5,
                "maximum": 300,
                "default": 30,
            },
            "transcription_provider": {
                "type": "string",
                "enum": ["openai", ""],
                "default": "",
            },
            "vision_provider": {
                "type": "string",
                "enum": ["anthropic", "openai", "gemini", ""],
                "default": "",
            },
        },
    },
)
