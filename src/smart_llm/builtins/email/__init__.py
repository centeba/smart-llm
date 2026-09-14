"""Email-domain skills.

Registered on import — Phase D moves the email-extractor service's
bespoke prompt into :class:`ExtractEmailFieldsSkill` so it lives next
to the rest of the registry.
"""

from __future__ import annotations

from . import extract_email_fields  # noqa: F401
