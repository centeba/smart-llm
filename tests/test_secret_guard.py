"""Placeholder-secret policy shared by every service's Settings."""

from __future__ import annotations

import pytest

from smart_llm.secret_guard import enforce_no_placeholder_secrets, is_placeholder_secret


@pytest.mark.parametrize(
    "value",
    [
        "changethis",
        "changeme_at_least_32_chars_long_secret",
        "CHANGE-ME",
        "replace_me_now",
        "<your-api-key>",
        "your-secret-here",
        "placeholder",
        "password",
        "  secret  ",
    ],
)
def test_template_values_are_placeholders(value: str) -> None:
    assert is_placeholder_secret(value)


@pytest.mark.parametrize(
    "value", ["", None, "   ", "SbDev-87239d50f5ad", "a3f9c1e2b4d6"]
)
def test_empty_and_real_values_are_not_placeholders(value: str | None) -> None:
    assert not is_placeholder_secret(value)


def test_production_refuses_placeholder() -> None:
    with pytest.raises(ValueError, match="SECRET_KEY") as exc:
        enforce_no_placeholder_secrets(
            "production", SECRET_KEY="changeme_x", INTERNAL_API_KEY="real-value"
        )
    assert "INTERNAL_API_KEY" not in str(exc.value)


@pytest.mark.parametrize(
    "environment", ["staging", "development", "preview", "Production"]
)
def test_every_non_lenient_environment_refuses(environment: str) -> None:
    with pytest.raises(ValueError):
        enforce_no_placeholder_secrets(environment, SECRET_KEY="changethis")


def test_local_only_warns() -> None:
    with pytest.warns(UserWarning, match="SECRET_KEY"):
        enforce_no_placeholder_secrets("local", SECRET_KEY="changethis")


def test_test_environment_is_silent() -> None:
    enforce_no_placeholder_secrets("test", SECRET_KEY="changethis")


def test_unset_values_are_ignored() -> None:
    enforce_no_placeholder_secrets("production", SECRET_KEY="", WEBHOOK_SECRET=None)
