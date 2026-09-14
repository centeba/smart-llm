"""Vision/image content moderation on the way into a vision model."""

import pytest

from smart_llm.security.guard import SafetyConfig, SafetyGuard
from smart_llm.security.moderation import (
    ModerationError,
    ModerationResult,
    ModerationUnavailableError,
)

_IMG = b"\x89PNG\r\n\x1a\n fake bytes"


class _FakeImageModerator:
    def __init__(self, flagged, categories=None, boom=False):
        self._flagged = flagged
        self._categories = categories or []
        self._boom = boom
        self.calls = 0

    async def moderate_image(self, data_uri):
        self.calls += 1
        if self._boom:
            raise RuntimeError("backend down")
        return ModerationResult(
            flagged=self._flagged, categories=self._categories, backend="fake-image"
        )


def _guard(config, image_moderator=None):
    # key_getter set so the guard builds an image moderator, then swap in a fake.
    g = SafetyGuard(key_getter=lambda: "k", config=config)
    if image_moderator is not None:
        g._image_moderator = image_moderator
    return g


@pytest.mark.asyncio
async def test_flagged_image_blocks():
    fake = _FakeImageModerator(flagged=True, categories=["sexual"])
    g = _guard(SafetyConfig(image_moderation="auto"), fake)
    with pytest.raises(ModerationError):
        await g.screen_image(_IMG, "image/png")
    assert fake.calls == 1


@pytest.mark.asyncio
async def test_clean_image_passes():
    fake = _FakeImageModerator(flagged=False)
    g = _guard(SafetyConfig(image_moderation="auto"), fake)
    await g.screen_image(_IMG, "image/png")  # no raise


@pytest.mark.asyncio
async def test_off_skips_entirely():
    fake = _FakeImageModerator(flagged=True)
    g = _guard(SafetyConfig(image_moderation="off"), fake)
    await g.screen_image(_IMG, "image/png")  # no raise
    assert fake.calls == 0


@pytest.mark.asyncio
async def test_shadow_does_not_raise_on_flag():
    fake = _FakeImageModerator(flagged=True)
    g = _guard(SafetyConfig(image_moderation="auto", shadow=True), fake)
    await g.screen_image(_IMG, "image/png")  # logged, not raised


@pytest.mark.asyncio
async def test_no_backend_auto_allows():
    # key_getter=None → no image moderator; 'auto' allows.
    g = SafetyGuard(key_getter=None, config=SafetyConfig(image_moderation="auto"))
    assert g._image_moderator is None
    await g.screen_image(_IMG, "image/png")  # no raise


@pytest.mark.asyncio
async def test_no_backend_required_blocks():
    g = SafetyGuard(key_getter=None, config=SafetyConfig(image_moderation="required"))
    with pytest.raises(ModerationUnavailableError):
        await g.screen_image(_IMG, "image/png")


@pytest.mark.asyncio
async def test_backend_outage_auto_allows():
    fake = _FakeImageModerator(flagged=False, boom=True)
    g = _guard(SafetyConfig(image_moderation="auto"), fake)
    await g.screen_image(_IMG, "image/png")  # backend error under 'auto' → allow


@pytest.mark.asyncio
async def test_backend_outage_required_blocks():
    fake = _FakeImageModerator(flagged=False, boom=True)
    g = _guard(SafetyConfig(image_moderation="required"), fake)
    with pytest.raises(ModerationUnavailableError):
        await g.screen_image(_IMG, "image/png")


@pytest.mark.asyncio
async def test_agent_analyze_image_screens_image(monkeypatch):
    # Full path: Agent.analyze_image calls screen_image, which blocks a flagged image.
    from unittest.mock import AsyncMock, MagicMock, patch

    from smart_llm.agent import Agent

    mock_cls = MagicMock()
    inst = mock_cls.return_value
    inst.complete_with_image = AsyncMock(return_value=[{"ok": True}])
    inst.last_usage = {"input_tokens": 1, "output_tokens": 1}

    # Guard that only exercises image moderation: no text backend (fail_open so
    # the text-prompt screen is a no-op), a flagged fake image moderator.
    guard = SafetyGuard(
        key_getter=lambda: "k",
        config=SafetyConfig(
            moderation_enabled=True, fail_open=True, image_moderation="auto"
        ),
    )
    guard._moderator = None  # no network text moderation in the test
    guard._image_moderator = _FakeImageModerator(flagged=True, categories=["violence"])

    with patch("smart_llm.agent.AnthropicProvider", mock_cls):
        agent = Agent(
            name="v",
            provider_type="anthropic",
            system_prompt="s",
            api_key="k",
            safety_enabled=True,
            safety_guard=guard,
        )
        with pytest.raises(ModerationError):
            await agent.analyze_image(_IMG, "image/png")
        # The provider was never called — the image was blocked pre-egress.
        inst.complete_with_image.assert_not_called()
