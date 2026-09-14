"""Detector precision/recall for the PII masking firewall."""

from smart_llm.pii.detectors import (
    CompositeDetector,
    PiiMatch,
    RegexDetector,
    _iban_ok,
    _luhn_ok,
)


def _types(text: str, **kw) -> set[str]:
    return {m.type for m in RegexDetector(**kw).detect(text)}


def _values(text: str, **kw) -> set[str]:
    return {m.value for m in RegexDetector(**kw).detect(text)}


# ── Recall — real PII is caught ────────────────────────────────────────────────


def test_email_detected():
    assert "EMAIL" in _types("reach me at jane.doe+tag@example.co.uk please")
    assert "jane.doe+tag@example.co.uk" in _values("jane.doe+tag@example.co.uk")


def test_ssn_dashed_detected():
    assert _values("SSN 123-45-6789 on file") == {"123-45-6789"}


def test_valid_visa_detected_via_luhn():
    # 4111 1111 1111 1111 is the canonical Luhn-valid test Visa.
    assert "CREDIT_CARD" in _types("card 4111 1111 1111 1111 expires soon")


def test_iban_detected():
    assert "IBAN" in _types("wire to GB82 WEST 1234 5698 7654 32 today")


def test_ipv4_detected():
    assert "IPV4" in _types("client ip 192.168.1.254 connected")


def test_phone_detected():
    assert "PHONE" in _types("call +1 415-555-0132 after noon")


def test_mrn_labelled_detected():
    matches = RegexDetector().detect("patient MRN: A1234567 admitted")
    mrn = [m for m in matches if m.type == "MRN"]
    assert mrn and mrn[0].value == "A1234567"


def test_dob_formats_detected():
    assert "DOB" in _types("dob 1990-05-01")
    assert "DOB" in _types("born 05/01/1990")


# ── Precision — look-alikes are NOT masked ─────────────────────────────────────


def test_luhn_invalid_card_ignored():
    # One digit changed from the valid test card → Luhn fails → not a card.
    assert "CREDIT_CARD" not in _types("ref 4111 1111 1111 1112")


def test_luhn_helper():
    assert _luhn_ok("4111111111111111")
    assert not _luhn_ok("4111111111111112")
    assert not _luhn_ok("123")  # too short


def test_iban_checksum_rejects_corrupted():
    assert _iban_ok("GB82WEST12345698765432")
    assert not _iban_ok("GB82WEST12345698765433")  # bad check digits


def test_ipv4_octet_out_of_range_ignored():
    assert "IPV4" not in _types("version 999.1.1.1 build")


def test_bare_ten_digits_not_phone():
    # No separators / country code → not treated as a phone number.
    assert "PHONE" not in _types("order 1234567890 shipped")


def test_plain_long_number_not_card():
    assert "CREDIT_CARD" not in _types("quantity 1234567890123456789")


# ── Structure — spans don't overlap, categories filter ─────────────────────────


def test_spans_non_overlapping_and_sorted():
    text = "email a@b.co and ssn 123-45-6789 and ip 10.0.0.1"
    matches = RegexDetector().detect(text)
    starts = [m.start for m in matches]
    assert starts == sorted(starts)
    for a, b in zip(matches, matches[1:]):
        assert a.end <= b.start


def test_categories_allowlist_restricts_rules():
    text = "a@b.co and 123-45-6789"
    only_email = _types(text, categories=["EMAIL"])
    assert only_email == {"EMAIL"}


def test_empty_text_returns_no_matches():
    assert RegexDetector().detect("") == []


def test_composite_detector_merges_without_overlap():
    class _Fixed:
        def detect(self, text):
            return [PiiMatch(0, 4, "0000", "CUSTOM")]

    comp = CompositeDetector([RegexDetector(), _Fixed()])
    # RegexDetector claims nothing at 0-4 here, so the custom span survives.
    out = comp.detect("0000 plain text")
    assert any(m.type == "CUSTOM" for m in out)
