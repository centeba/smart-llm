"""Blocking SDK and subprocess calls run in a worker thread, not on the event
loop: Gemini's complete() and the video parser's ffmpeg."""

import threading
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from smart_llm.builtins.parsing import fallback_chain
from smart_llm.providers.gemini import GeminiProvider


@pytest.mark.asyncio
async def test_gemini_complete_calls_the_sdk_off_the_event_loop() -> None:
    seen: list[int] = []

    def generate_content(**_: Any) -> SimpleNamespace:
        seen.append(threading.get_ident())
        return SimpleNamespace(
            text='{"ok": true}',
            usage_metadata=SimpleNamespace(
                prompt_token_count=3, candidates_token_count=4
            ),
        )

    provider = GeminiProvider(api_key="test-key")
    provider.client = MagicMock()
    provider.client.models.generate_content.side_effect = generate_content

    assert await provider.complete("system", "user") == {"ok": True}
    assert seen and seen[0] != threading.get_ident()
    assert provider.last_usage == {"input_tokens": 3, "output_tokens": 4}


@pytest.mark.asyncio
async def test_video_ffmpeg_runs_off_the_event_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[int] = []

    def fake_run(*_: Any, **__: Any) -> SimpleNamespace:
        seen.append(threading.get_ident())
        return SimpleNamespace(returncode=1)  # ffmpeg failed -> strategy returns None

    monkeypatch.setattr(fallback_chain.shutil, "which", lambda _: "/usr/bin/ffmpeg")
    monkeypatch.setattr(fallback_chain.subprocess, "run", fake_run)

    result = await fallback_chain.video_vision_strategy(
        "clip.mp4", {"vision_provider": "openai"}
    )
    assert result is None
    assert seen and seen[0] != threading.get_ident()
