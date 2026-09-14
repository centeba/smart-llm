"""KMS envelope encryption for stored secrets (HARDENING-PLAN A5).

Proves the envelope codec round-trips, is distinguishable from legacy Fernet
tokens, and rejects tampering (wrong master key / a truncated blob). Uses the
``local`` provider (Fernet-wrapped DEK) — no cloud SDKs needed.
"""

from __future__ import annotations

import pytest
from cryptography.fernet import Fernet

from smart_llm.secret_envelope import (
    ENVELOPE_PREFIX,
    ENVELOPE_PREFIX_V2,
    LocalKMSProvider,
    decrypt_secret,
    encrypt_secret,
    envelope_key_id,
    is_envelope,
    provider_from_env,
)

SECRET = "sk-proj-abcdef0123456789-a-real-looking-api-key"


@pytest.fixture
def provider() -> LocalKMSProvider:
    return LocalKMSProvider(Fernet.generate_key())


def test_round_trip(provider):
    blob = encrypt_secret(SECRET, provider)
    # New writes are v2 (they carry the KEK key-id); both versions are envelopes.
    assert is_envelope(blob) and blob.startswith(ENVELOPE_PREFIX_V2)
    assert decrypt_secret(blob, provider) == SECRET


def test_ciphertext_is_not_plaintext_and_is_randomized(provider):
    a = encrypt_secret(SECRET, provider)
    b = encrypt_secret(SECRET, provider)
    assert SECRET not in a  # secret never appears verbatim
    assert a != b  # fresh DEK + IV each time → non-deterministic


def test_envelope_is_distinguishable_from_legacy_fernet_token():
    # A legacy DatabaseKeyStore token is a bare Fernet token — must NOT be
    # mistaken for an envelope (that's what lets old + new rows coexist).
    legacy = Fernet(Fernet.generate_key()).encrypt(SECRET.encode()).decode()
    assert not is_envelope(legacy)
    assert is_envelope(encrypt_secret(SECRET, LocalKMSProvider(Fernet.generate_key())))


def test_wrong_master_key_cannot_decrypt(provider):
    # DEK is wrapped by the master key; a different provider can't unwrap it.
    blob = encrypt_secret(SECRET, provider)
    other = LocalKMSProvider(Fernet.generate_key())
    with pytest.raises(Exception):  # InvalidToken from Fernet unwrap
        decrypt_secret(blob, other)


def test_tampered_ciphertext_is_rejected(provider):
    blob = encrypt_secret(SECRET, provider)
    tampered = blob[:-4] + ("AAAA" if blob[-4:] != "AAAA" else "BBBB")
    with pytest.raises(Exception):
        decrypt_secret(tampered, provider)


def test_decrypt_secret_rejects_non_envelope(provider):
    with pytest.raises(ValueError):
        decrypt_secret("not-an-envelope", provider)


def test_provider_from_env_none_by_default(monkeypatch):
    monkeypatch.delenv("SMART_LLM_KMS_PROVIDER", raising=False)
    assert provider_from_env(local_master_key=Fernet.generate_key()) is None


def test_provider_from_env_local(monkeypatch):
    monkeypatch.setenv("SMART_LLM_KMS_PROVIDER", "local")
    p = provider_from_env(local_master_key=Fernet.generate_key())
    assert isinstance(p, LocalKMSProvider)
    # Usable end-to-end.
    assert decrypt_secret(encrypt_secret(SECRET, p), p) == SECRET


def test_provider_from_env_local_requires_master_key(monkeypatch):
    monkeypatch.setenv("SMART_LLM_KMS_PROVIDER", "local")
    with pytest.raises(ValueError):
        provider_from_env()


def test_provider_from_env_unknown_rejected(monkeypatch):
    monkeypatch.setenv("SMART_LLM_KMS_PROVIDER", "nonsense")
    with pytest.raises(ValueError):
        provider_from_env(local_master_key=Fernet.generate_key())


def test_rewrap_rotates_kek_and_preserves_data_ciphertext():
    """``rewrap_secret`` re-wraps the DEK under a new KEK, leaving the iv +
    data ciphertext byte-identical — so the rotated blob decrypts under the new
    provider and the old KEK can no longer read it, and it's re-tagged v2 with the
    new key-id."""
    from cryptography.fernet import InvalidToken

    from smart_llm.secret_envelope import _parse, rewrap_secret

    old = LocalKMSProvider(Fernet.generate_key())
    new = LocalKMSProvider(Fernet.generate_key())
    blob = encrypt_secret(SECRET, old)

    rotated = rewrap_secret(blob, old_provider=old, new_provider=new)

    assert is_envelope(rotated)
    assert decrypt_secret(rotated, new) == SECRET  # readable under the new KEK
    with pytest.raises(InvalidToken):
        decrypt_secret(rotated, old)  # old KEK can no longer unwrap the DEK
    assert envelope_key_id(rotated) == new.key_id  # re-tagged with the new key-id
    # Only the wrapped DEK (+ key-id) changed; the iv + data ciphertext is verbatim.
    assert _parse(blob)[2] == _parse(rotated)[2]


def test_rewrap_rejects_non_envelope():
    from smart_llm.secret_envelope import rewrap_secret

    p = LocalKMSProvider(Fernet.generate_key())
    with pytest.raises(ValueError):
        rewrap_secret("gAAAAA-legacy-fernet", old_provider=p, new_provider=p)


def test_rewrap_fails_when_old_provider_is_wrong():
    from cryptography.fernet import InvalidToken

    from smart_llm.secret_envelope import rewrap_secret

    blob = encrypt_secret(SECRET, LocalKMSProvider(Fernet.generate_key()))
    with pytest.raises(InvalidToken):
        rewrap_secret(
            blob,
            old_provider=LocalKMSProvider(Fernet.generate_key()),  # wrong KEK
            new_provider=LocalKMSProvider(Fernet.generate_key()),
        )


def _v1_blob(provider, secret: str = SECRET) -> str:
    """Craft a legacy v1 envelope (no key-id) for back-compat tests."""
    import base64
    import os
    import struct

    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    pair = provider.generate_data_key()
    iv = os.urandom(12)
    ct = AESGCM(pair.plaintext).encrypt(iv, secret.encode(), None)
    payload = struct.pack(">I", len(pair.encrypted)) + pair.encrypted + iv + ct
    return ENVELOPE_PREFIX + base64.urlsafe_b64encode(payload).decode()


def test_v1_blob_still_decrypts_and_has_no_key_id(provider):
    v1 = _v1_blob(provider)
    assert v1.startswith(ENVELOPE_PREFIX) and is_envelope(v1)
    assert envelope_key_id(v1) is None  # v1 predates the marker
    assert decrypt_secret(v1, provider) == SECRET


def test_v2_records_provider_key_id(provider):
    blob = encrypt_secret(SECRET, provider)
    assert blob.startswith(ENVELOPE_PREFIX_V2)
    assert envelope_key_id(blob) == provider.key_id


def test_rewrap_upgrades_v1_to_v2_and_tags_new_key_id():
    from smart_llm.secret_envelope import rewrap_secret

    old = LocalKMSProvider(Fernet.generate_key())
    new = LocalKMSProvider(Fernet.generate_key())
    v1 = _v1_blob(old)

    rotated = rewrap_secret(v1, old_provider=old, new_provider=new)

    assert rotated.startswith(ENVELOPE_PREFIX_V2)
    assert envelope_key_id(rotated) == new.key_id
    assert decrypt_secret(rotated, new) == SECRET


def test_local_key_id_is_stable_and_distinct():
    key = Fernet.generate_key()
    assert LocalKMSProvider(key).key_id == LocalKMSProvider(key).key_id  # stable
    assert (
        LocalKMSProvider(key).key_id != LocalKMSProvider(Fernet.generate_key()).key_id
    )
