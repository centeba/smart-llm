"""Phase-E5 — strategy chain helper for parsing skills.

The vision/audio parsers all follow the same shape: try a fast local
backend (Tesseract / Whisper) first, then fall back to a vision-LLM
or provider-hosted transcription API. This module factors the
boring iterate-and-catch into one place so each skill just declares
its strategy list.

A "strategy" is a callable ``(path: str, **cfg) -> Optional[str]``.
Returning ``None`` (or raising) signals "not configured / not
confident enough" and the chain advances. Returning a non-empty
string halts the chain and reports the producing strategy via the
returned ``ParseResult``.

Configuration flows in via the standard ``model_configuration``
JSON on the host's ``AISkill`` row. Keys consumed today:

- ``ocr_min_confidence`` — int (default 60). Tesseract output below
  this is treated as failure so the LLM fallback fires.
- ``vision_provider`` — ``anthropic`` | ``openai`` | ``gemini`` |
  ``""`` (disabled).
- ``vision_model`` — model name override.
- ``vision_api_key`` — explicit key (otherwise read from env per
  provider). Required when no host KeyManager is wired through.
- ``transcription_provider`` — ``openai`` (Whisper API) | ``""``.
- ``whisper_bin`` — explicit path to a local whisper.cpp / openai-
  whisper executable; if unset we try ``$WHISPER_BIN`` then
  ``shutil.which("whisper")``.
- ``video_frame_interval_seconds`` — int (default 30). Vision-LLM
  fallback for video samples one frame per N seconds.
"""

import asyncio
import logging
import os
import shutil
import subprocess
import tempfile
from collections.abc import Awaitable, Callable, Coroutine
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

logger = logging.getLogger(__name__)


@dataclass
class ParseResult:
    text: str
    strategy: str  # which strategy produced the text


Strategy = Callable[[str, dict[str, Any]], str | None]
AsyncStrategy = Callable[[str, dict[str, Any]], Awaitable[str | None]]


def run_chain(
    path: str,
    cfg: dict[str, Any],
    strategies: list[tuple[str, Strategy]],
) -> ParseResult:
    """Iterate ``strategies`` until one returns non-empty text.

    Each tuple is ``(name, callable)``. Exceptions are caught and
    logged; chain advances. Final failure raises ``RuntimeError``
    listing every attempt's failure mode so the workflow log shows
    what to fix.
    """
    failures: list[str] = []
    for name, fn in strategies:
        try:
            out = fn(path, cfg)
            if out:
                return ParseResult(text=out, strategy=name)
            failures.append(f"{name}: returned empty")
        except Exception as e:  # noqa: BLE001
            failures.append(f"{name}: {type(e).__name__}: {e}")
    raise RuntimeError(
        f"All parse strategies failed for {path!r}:\n  - " + "\n  - ".join(failures)
    )


def run_chain_mixed(
    path: str,
    cfg: dict[str, Any],
    sync_then_async: list[tuple[str, Any]],
) -> ParseResult:
    """Bridge for sync ``Tool.run`` callers.

    Each strategy is either a plain ``Strategy`` callable or an
    ``AsyncStrategy`` coroutine function; we run async ones via a
    fresh event loop in the current thread (or a worker thread when
    one is already running, e.g. inside an async activity bridge).
    """
    failures: list[str] = []
    for name, fn in sync_then_async:
        try:
            if asyncio.iscoroutinefunction(fn):
                out = _run_coro(fn(path, cfg))
            else:
                out = fn(path, cfg)
            if out:
                return ParseResult(text=out, strategy=name)
            failures.append(f"{name}: returned empty")
        except Exception as e:  # noqa: BLE001
            failures.append(f"{name}: {type(e).__name__}: {e}")
    raise RuntimeError(
        f"All parse strategies failed for {path!r}:\n  - " + "\n  - ".join(failures)
    )


def _run_coro(coro: Coroutine[Any, Any, str | None]) -> str | None:
    """Run a coroutine to completion regardless of caller context."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop is None:
        return asyncio.run(coro)
    # We're inside a running loop (e.g. an async activity calling a
    # sync Tool.run). Drop to a worker thread so we don't deadlock.
    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


async def run_chain_async(
    path: str,
    cfg: dict[str, Any],
    strategies: list[tuple[str, AsyncStrategy]],
) -> ParseResult:
    """Async variant for strategies that hit network APIs."""
    failures: list[str] = []
    for name, fn in strategies:
        try:
            out = await fn(path, cfg)
            if out:
                return ParseResult(text=out, strategy=name)
            failures.append(f"{name}: returned empty")
        except Exception as e:  # noqa: BLE001
            failures.append(f"{name}: {type(e).__name__}: {e}")
    raise RuntimeError(
        f"All parse strategies failed for {path!r}:\n  - " + "\n  - ".join(failures)
    )


# ── Tesseract OCR ───────────────────────────────────────────────────────────


def tesseract_strategy(path: str, cfg: dict[str, Any]) -> str | None:
    """Run Tesseract; return None if unavailable or low-confidence."""
    try:
        import pytesseract
        from PIL import Image
    except ImportError:
        return None
    img = Image.open(path)
    # ``image_to_data`` exposes per-token confidence; we take the mean
    # over non-empty tokens. Whole-image ``image_to_string`` doesn't.
    try:
        data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)
        confs = [
            int(c)
            for c in data.get("conf", [])
            if str(c).lstrip("-").isdigit() and int(c) >= 0
        ]
        if confs:
            mean_conf = sum(confs) / len(confs)
            min_conf = int(cfg.get("ocr_min_confidence", 60))
            if mean_conf < min_conf:
                logger.info(
                    "tesseract: mean confidence %.1f < %d threshold; falling back",
                    mean_conf,
                    min_conf,
                )
                return None
    except Exception:  # noqa: BLE001 — confidence check is best-effort
        pass
    text = pytesseract.image_to_string(img).strip()
    return text or None


# ── Vision-LLM OCR / image description ──────────────────────────────────────


async def vision_llm_strategy(path: str, cfg: dict[str, Any]) -> str | None:
    """Send the image to a vision-capable model and ask for text.

    Provider chosen via ``cfg["vision_provider"]``. Empty string
    (default) disables this strategy so the chain raises rather than
    silently calling out to an external API the host didn't opt into.
    """
    provider = (cfg.get("vision_provider") or "").lower()
    if not provider:
        return None
    api_key = cfg.get("vision_api_key") or _env_key(provider)
    if not api_key:
        logger.warning("vision_llm: no api key for provider %s", provider)
        return None
    image_b64 = _read_b64(path)
    prompt = (
        "Extract every visible character from this image as plain "
        "text. Preserve line breaks. Return only the extracted text."
    )
    if provider == "anthropic":
        return await _anthropic_vision(api_key, cfg, image_b64, prompt)
    if provider == "openai":
        return await _openai_vision(api_key, cfg, image_b64, prompt)
    if provider == "gemini":
        return await _gemini_vision(api_key, cfg, image_b64, prompt)
    logger.warning("vision_llm: unknown provider %r", provider)
    return None


async def _anthropic_vision(
    api_key: str, cfg: dict[str, Any], image_b64: str, prompt: str
) -> str | None:
    from anthropic import AsyncAnthropic
    from anthropic.types import MessageParam, TextBlock

    client = AsyncAnthropic(api_key=api_key)
    resp = await client.messages.create(
        model=cfg.get("vision_model") or "claude-sonnet-4-6",
        max_tokens=4096,
        messages=cast(
            list[MessageParam],
            [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": _guess_media_type(image_b64),
                                "data": image_b64,
                            },
                        },
                        {"type": "text", "text": prompt},
                    ],
                }
            ],
        ),
    )
    return cast(TextBlock, resp.content[0]).text.strip() if resp.content else None


async def _openai_vision(
    api_key: str, cfg: dict[str, Any], image_b64: str, prompt: str
) -> str | None:
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=api_key)
    resp = await client.chat.completions.create(
        model=cfg.get("vision_model") or "gpt-4o",
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{image_b64}"},
                    },
                ],
            }
        ],
    )
    return (resp.choices[0].message.content or "").strip() or None


async def _gemini_vision(
    api_key: str, cfg: dict[str, Any], image_b64: str, prompt: str
) -> str | None:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)

    def _call() -> types.GenerateContentResponse:
        return client.models.generate_content(
            model=cfg.get("vision_model") or "gemini-2.5-flash",
            contents=cast(
                Any,
                [
                    types.Part.from_bytes(
                        data=__import__("base64").b64decode(image_b64),
                        mime_type=_guess_media_type(image_b64),
                    ),
                    prompt,
                ],
            ),
        )

    loop = asyncio.get_running_loop()
    resp = await loop.run_in_executor(None, _call)
    text = getattr(resp, "text", None)
    return text.strip() if text else None


# ── Whisper (local + API) ───────────────────────────────────────────────────


def whisper_local_strategy(path: str, cfg: dict[str, Any]) -> str | None:
    """Invoke a local whisper binary if configured.

    Looks for, in order: ``cfg["whisper_bin"]``, ``$WHISPER_BIN``,
    ``shutil.which("whisper")``. Falls through (returns None) if no
    binary is found — keeps the chain working on hosts without
    Whisper installed.
    """
    binary = (
        cfg.get("whisper_bin") or os.getenv("WHISPER_BIN") or shutil.which("whisper")
    )
    if not binary:
        return None
    with tempfile.TemporaryDirectory() as tmp:
        out_dir = Path(tmp)
        # Whisper-CLI writes to ``<basename>.txt`` in --output_dir
        proc = subprocess.run(
            [binary, path, "--output_format", "txt", "--output_dir", str(out_dir)],
            capture_output=True,
            text=True,
            timeout=600,
        )
        if proc.returncode != 0:
            logger.warning(
                "whisper: exit=%d stderr=%s", proc.returncode, proc.stderr[-200:]
            )
            return None
        for txt in out_dir.glob("*.txt"):
            content = txt.read_text(encoding="utf-8", errors="replace").strip()
            if content:
                return content
    return None


async def transcription_api_strategy(path: str, cfg: dict[str, Any]) -> str | None:
    """Fallback to a hosted transcription API (OpenAI Whisper)."""
    provider = (cfg.get("transcription_provider") or "").lower()
    if not provider:
        return None
    if provider != "openai":
        logger.warning("transcription_api: unsupported provider %r", provider)
        return None
    api_key = cfg.get("transcription_api_key") or os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=api_key)
    with open(path, "rb") as f:
        resp = await client.audio.transcriptions.create(
            model=cfg.get("transcription_model") or "whisper-1",
            file=f,
        )
    return (resp.text or "").strip() or None


# ── Video frame sampling → vision-LLM ───────────────────────────────────────


async def video_vision_strategy(path: str, cfg: dict[str, Any]) -> str | None:
    """Sample frames every N seconds; describe each via vision-LLM.

    Requires ``ffmpeg`` on PATH for frame extraction. Returns
    a stitched transcript-like string; if vision-LLM is disabled or
    ffmpeg is missing, returns None.
    """
    if not (cfg.get("vision_provider") or ""):
        return None
    if shutil.which("ffmpeg") is None:
        logger.warning("video_vision: ffmpeg not on PATH")
        return None

    interval = int(cfg.get("video_frame_interval_seconds", 30))
    with tempfile.TemporaryDirectory() as tmp:
        pattern = str(Path(tmp) / "frame-%04d.jpg")
        proc = subprocess.run(
            [
                "ffmpeg",
                "-loglevel",
                "error",
                "-i",
                path,
                "-vf",
                f"fps=1/{interval}",
                pattern,
            ],
            capture_output=True,
            timeout=600,
        )
        if proc.returncode != 0:
            return None
        chunks: list[str] = []
        for frame in sorted(Path(tmp).glob("frame-*.jpg")):
            text = await vision_llm_strategy(str(frame), cfg)
            if text:
                chunks.append(text)
        return "\n\n".join(chunks) if chunks else None


# ── helpers ─────────────────────────────────────────────────────────────────


def _env_key(provider: str) -> str | None:
    return {
        "anthropic": os.getenv("ANTHROPIC_API_KEY"),
        "openai": os.getenv("OPENAI_API_KEY"),
        "gemini": os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"),
    }.get(provider)


def _read_b64(path: str) -> str:
    import base64

    return base64.b64encode(Path(path).read_bytes()).decode("ascii")


def _guess_media_type(image_b64: str) -> str:
    # Cheap detection from the first few bytes — covers PNG/JPEG.
    import base64

    head = base64.b64decode(image_b64[:32] + "==")[:8]
    if head.startswith(b"\x89PNG"):
        return "image/png"
    return "image/jpeg"
