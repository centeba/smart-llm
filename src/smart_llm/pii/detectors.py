"""PII detectors for the egress masking firewall.

A :class:`Detector` turns a block of outbound text into a list of
:class:`PiiMatch` spans. The firewall then tokenises each span (see
:mod:`smart_llm.pii.firewall`). Detectors are deliberately pure — plain
string in, spans out, no I/O — so they are trivially unit-testable and can
run on the hot egress path.

The default :class:`RegexDetector` ships a validated pack (Luhn for cards,
mod-97 for IBANs, octet-range for IPv4). A :class:`CompositeDetector` fans
out over several detectors and merges their spans, which is the seam a
heavier NER backend (Presidio / spaCy) plugs into later via the
``smart_llm.pii_detectors`` entry-point group — no firewall change and no
mandatory heavy dependency now.
"""

import logging
import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PiiMatch:
    """One detected PII span within a source string.

    ``value`` is the exact substring to tokenise; ``type`` is the category
    label (``"EMAIL"``, ``"SSN"``, …) that seeds the placeholder name.
    """

    start: int
    end: int
    value: str
    type: str


@runtime_checkable
class Detector(Protocol):
    """A PII detector: text in, non-overlapping matches out."""

    def detect(self, text: str) -> list[PiiMatch]: ...


# ── Validators ────────────────────────────────────────────────────────────────


def _luhn_ok(digits: str) -> bool:
    """Luhn (mod-10) checksum — rejects random 13–19 digit runs that merely
    look card-shaped, which is what keeps the card rule precise."""
    if not digits.isdigit() or not (13 <= len(digits) <= 19):
        return False
    total = 0
    # Double every second digit counting from the right; the rightmost (check)
    # digit is never doubled. From the left that means doubling indices whose
    # position matches ``len % 2``.
    parity = len(digits) % 2
    for i, ch in enumerate(digits):
        d = ord(ch) - 48
        if i % 2 == parity:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def _iban_ok(iban: str) -> bool:
    """ISO 13616 structure + mod-97 checksum."""
    s = iban.replace(" ", "").upper()
    if not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{11,30}", s):
        return False
    rearranged = s[4:] + s[:4]
    digits = "".join(str(ord(c) - 55) if c.isalpha() else c for c in rearranged)
    try:
        return int(digits) % 97 == 1
    except ValueError:
        return False


def _ipv4_ok(text: str) -> bool:
    parts = text.split(".")
    return len(parts) == 4 and all(p.isdigit() and 0 <= int(p) <= 255 for p in parts)


# ── Rule model ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class _Rule:
    """A single regex rule.

    ``value_group`` selects which capture group is the PII value (0 = whole
    match); the label ``MRN`` uses a labelled prefix but tokenises only the
    identifier group. ``validator`` receives the matched *value* string and
    returns whether to keep the match.
    """

    type: str
    regex: re.Pattern[str]
    validator: Callable[[str], bool] | None = None
    value_group: int = 0


# Ordered most-specific / longest first so a card is never mis-claimed as a
# phone number, an email local-part is never split, etc. The first rule to
# claim a span wins; later overlapping matches are dropped.
_DEFAULT_RULES: tuple[_Rule, ...] = (
    _Rule(
        "EMAIL",
        re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"),
    ),
    _Rule(
        "IPV6",
        re.compile(r"\b(?:[A-Fa-f0-9]{1,4}:){2,7}[A-Fa-f0-9]{1,4}\b"),
    ),
    _Rule("IPV4", re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"), _ipv4_ok),
    _Rule("IBAN", re.compile(r"\b[A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]){11,30}\b"), _iban_ok),
    # Credit card: 13–19 digits, optionally grouped by spaces or dashes. Luhn
    # validated so plain long numbers (order ids, quantities) are not masked.
    _Rule(
        "CREDIT_CARD",
        re.compile(r"\b(?:\d[ -]?){13,19}\b"),
        lambda v: _luhn_ok(re.sub(r"[ -]", "", v)),
    ),
    _Rule("SSN", re.compile(r"\b\d{3}[- ]\d{2}[- ]\d{4}\b")),
    # MRN — no universal format, so gate on a nearby "MRN" label and tokenise
    # only the identifier. Keeps the rule from masking every short code.
    _Rule("MRN", re.compile(r"\bMRN[:#]?\s*([A-Za-z0-9]{5,12})\b"), value_group=1),
    # North-American / E.164 phone. Requires a separator or country code so it
    # doesn't swallow arbitrary 10-digit integers.
    _Rule(
        "PHONE",
        re.compile(
            r"(?<!\d)(?:\+?\d{1,3}[ .\-])?\(?\d{3}\)?[ .\-]\d{3}[ .\-]\d{4}(?!\d)"
        ),
    ),
    # Date of birth — common machine formats only (mm/dd/yyyy, yyyy-mm-dd).
    _Rule(
        "DOB",
        re.compile(r"\b(?:\d{1,2}[/]\d{1,2}[/]\d{4}|\d{4}-\d{2}-\d{2})\b"),
    ),
)


class RegexDetector:
    """Validated regex detector pack.

    ``categories`` optionally restricts the active rule types (the per-company
    ``pii_categories`` allowlist); ``None`` means every rule is active.
    """

    def __init__(
        self,
        rules: Sequence[_Rule] | None = None,
        categories: Iterable[str] | None = None,
    ):
        self._rules: tuple[_Rule, ...] = (
            tuple(rules) if rules is not None else _DEFAULT_RULES
        )
        self._categories: set[str] | None = (
            {c.upper() for c in categories} if categories is not None else None
        )

    def detect(self, text: str) -> list[PiiMatch]:
        if not text:
            return []
        claimed: list[tuple[int, int]] = []
        out: list[PiiMatch] = []
        for rule in self._rules:
            if self._categories is not None and rule.type not in self._categories:
                continue
            for m in rule.regex.finditer(text):
                value = m.group(rule.value_group)
                if not value:
                    continue
                if rule.validator is not None and not rule.validator(value):
                    continue
                start, end = m.span(rule.value_group)
                if any(not (end <= cs or start >= ce) for cs, ce in claimed):
                    continue  # overlaps an already-claimed span
                claimed.append((start, end))
                out.append(PiiMatch(start, end, value, rule.type))
        out.sort(key=lambda x: x.start)
        return out


class CompositeDetector:
    """Runs several detectors in order and merges their spans.

    Earlier detectors win overlaps, so put the precise regex pack first and a
    fuzzier NER detector after — the NER backend only contributes spans the
    regex pack didn't already claim.
    """

    def __init__(self, detectors: Sequence[Detector]):
        self._detectors: list[Detector] = list(detectors)

    def detect(self, text: str) -> list[PiiMatch]:
        if not text:
            return []
        claimed: list[tuple[int, int]] = []
        out: list[PiiMatch] = []
        for det in self._detectors:
            for m in det.detect(text):
                if any(not (m.end <= cs or m.start >= ce) for cs, ce in claimed):
                    continue
                claimed.append((m.start, m.end))
                out.append(m)
        out.sort(key=lambda x: x.start)
        return out


class NerDetector:
    """Documented plug-point for a named-entity PII backend (Presidio / spaCy).

    Ships as an inert stub so the firewall's interface is stable: installing
    ``smart-llm[pii-ner]`` and registering a real detector under the
    ``smart_llm.pii_detectors`` entry-point group upgrades detection with no
    firewall change. The stub itself detects nothing.
    """

    def detect(self, text: str) -> list[PiiMatch]:
        return []


def load_entry_point_detectors() -> list[Detector]:
    """Discover extra detectors registered under ``smart_llm.pii_detectors``.

    Best-effort: a bad plugin is logged and skipped rather than breaking the
    firewall. Returns an empty list when nothing is registered (the default).
    """
    try:
        from importlib.metadata import entry_points
    except Exception:  # pragma: no cover - importlib.metadata always present on 3.9+
        return []
    try:
        eps = entry_points()
        group = (
            eps.select(group="smart_llm.pii_detectors")
            if hasattr(eps, "select")
            else eps.get("smart_llm.pii_detectors", [])  # type: ignore[arg-type]  # importlib.metadata pre-3.10 dict-style API
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("pii: entry-point detector discovery failed: %s", e)
        return []
    detectors: list[Detector] = []
    for ep in group:
        try:
            factory = ep.load()
            detectors.append(factory())
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "pii: failed to load detector %r: %s", getattr(ep, "name", ep), e
            )
    return detectors
