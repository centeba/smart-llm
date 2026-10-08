"""Placeholder-secret guard shared by every service's Settings.

Each service used to check a single literal (``"changethis"``) and only when
``ENVIRONMENT == "production"`` exactly — so the repo's own ``.env.example``
values (``changeme_…``) passed, and a staging / preview environment could run
on template secrets indefinitely. This module recognises the *family* of
template values and applies one policy everywhere:

* ``test``  — no check (unit tests run on fixed throwaway values);
* ``local`` — ``warnings.warn`` (a developer's compose stack keeps booting);
* anything else (``production``, ``staging``, ``development``, previews…) —
  ``ValueError``, so the service refuses to start.

Only *set* values are judged. An empty value means "unset", which each
service already handles on its own terms (required → its own error; optional
→ feature off).
"""

from __future__ import annotations

import warnings

_PLACEHOLDER_PREFIXES: tuple[str, ...] = (
    "changethis",
    "changeme",
    "change-me",
    "change_me",
    "replaceme",
    "replace-me",
    "replace_me",
    "placeholder",
    "your-",
    "your_",
    "<",
)
_PLACEHOLDER_VALUES: frozenset[str] = frozenset(
    {"secret", "password", "example", "dummy", "todo", "xxx", "admin", "test", "123456"}
)
LENIENT_ENVIRONMENTS: frozenset[str] = frozenset({"local", "test"})


def is_placeholder_secret(value: str | None) -> bool:
    """True when ``value`` is a set-but-template secret (``changeme_…``,
    ``<your-key>``, ``password`` …). Empty / None is *not* a placeholder."""
    v = (value or "").strip().lower()
    if not v:
        return False
    return v in _PLACEHOLDER_VALUES or v.startswith(_PLACEHOLDER_PREFIXES)


def enforce_no_placeholder_secrets(environment: str, **secrets: str | None) -> None:
    """Refuse (or, in ``local``, warn about) template values among ``secrets``.

    ``secrets`` maps the *environment variable name* to its configured value,
    so the message tells the operator exactly what to set. Call it from a
    Settings ``model_validator`` in every environment; the policy lives here.
    """
    env = (environment or "").strip().lower()
    if env == "test":
        return
    offenders = [
        name for name, value in secrets.items() if is_placeholder_secret(value)
    ]
    if not offenders:
        return
    message = (
        "Placeholder secret(s) are set — generate real values (e.g. "
        "`openssl rand -hex 32`) for: " + ", ".join(offenders)
    )
    if env == "local":
        warnings.warn(message, stacklevel=2)
        return
    raise ValueError(f"{message} (ENVIRONMENT={environment!r})")
