"""Envelope encryption for stored secrets (LLM provider API keys).

Framework-level, domain-agnostic. Mirrors the envelope pattern doc-vault uses
for file blobs, but scoped to short secret *strings* and with a minimal KMS
contract — only the two data-key operations, **no** digest signing (that is a
doc-vault audit concern, not a secret-storage one).

Envelope encryption means the secret is encrypted under a fresh random Data
Encryption Key (DEK), and only the *DEK* is wrapped by the KMS master key. The
plaintext DEK never leaves memory and is zeroed after use, so rotating the KMS
master key never requires re-encrypting every secret — only the wrapped DEKs.

The codec and provider calls are **synchronous**: each cloud KMS SDK here
(boto3, Azure Key Vault, google-cloud-kms) is itself synchronous, and
``DatabaseKeyStore`` calls encrypt/decrypt synchronously from within its async
methods. Key load/save is infrequent (not a hot path), so a brief blocking KMS
round-trip is acceptable and avoids a nested-event-loop hack.

Providers:
- ``LocalKMSProvider`` — dev default. Wraps the DEK with a Fernet master key
  (the same secret ``DatabaseKeyStore`` already holds), so no new key material
  is needed and legacy Fernet-encrypted rows keep working via the store's
  format-detecting decrypt path.
- ``AwsKMSProvider`` / ``AzureKMSProvider`` / ``GcpKMSProvider`` — production.
  Thin wrappers over each cloud's GenerateDataKey/Decrypt (SDKs imported
  lazily so the base install stays slim). Selected via ``SMART_LLM_KMS_*`` env.

Wire format of an envelope blob (a single ``str`` safe to store in the same
column as a legacy Fernet token — the prefix distinguishes them). Two versions,
both readable; new writes use **v2**, which records the wrapping **KEK key-id** so
rotation can tell which key wrapped a blob (targeted re-wrap) without
trial-decrypting:

    v1: "smllmenv1:" + b64url( 4-byte-BE len(edek) | edek | iv(12) | ct+tag )
    v2: "smllmenv2:" + b64url( 2-byte-BE len(kid) | kid | 4-byte-BE len(edek)
                               | edek | iv(12) | ct+tag )
"""

import base64
import hashlib
import os
import struct
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, cast

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

# Marks an envelope blob. A legacy Fernet token is urlsafe-base64 and starts
# with "gAAAAA", so these literal prefixes can never collide with one.
ENVELOPE_PREFIX = "smllmenv1:"  # v1 — no key-id (read-only compat)
ENVELOPE_PREFIX_V2 = "smllmenv2:"  # v2 — carries the wrapping KEK key-id


@dataclass(frozen=True)
class DataKeyPair:
    """A plaintext/encrypted data-key pair from a KMS."""

    plaintext: bytes  # raw AES-256 key — zeroed after use
    encrypted: bytes  # wrapped blob — safe to store


class SecretKMSProvider(ABC):
    """Minimal KMS contract for secret envelope encryption (DEK ops only)."""

    @property
    @abstractmethod
    def key_id(self) -> str:
        """A stable, non-secret identifier of the KEK this provider wraps DEKs
        with. Stored in a v2 envelope so rotation can tell which key wrapped a
        blob — targeted re-wrap, no trial-decrypt — and a reader can pick the
        right key during a two-KEK grace window."""

    @abstractmethod
    def generate_data_key(self) -> DataKeyPair:
        """Return a fresh AES-256 DEK as (plaintext, wrapped)."""

    @abstractmethod
    def wrap_data_key(self, plaintext_key: bytes) -> bytes:
        """Wrap an EXISTING plaintext DEK under the master key — the inverse of
        :meth:`decrypt_data_key`. Used by KEK rotation (:func:`rewrap_secret`) to
        re-wrap a data key under a new master key without re-encrypting, or even
        decrypting, the data it protects."""

    @abstractmethod
    def decrypt_data_key(self, encrypted_key: bytes) -> bytes:
        """Unwrap a previously-generated DEK, returning the plaintext key."""


def _zero(buf: bytearray) -> None:
    for i in range(len(buf)):
        buf[i] = 0


# ---------------------------------------------------------------------------
# Providers
# ---------------------------------------------------------------------------


class LocalKMSProvider(SecretKMSProvider):
    """Dev provider: wraps the DEK with a Fernet master key.

    Accepts the same Fernet key ``DatabaseKeyStore`` is constructed with, so
    the ``local`` path introduces no new key material and stays a drop-in for
    the previous plain-Fernet scheme.
    """

    def __init__(self, master_key: str | bytes) -> None:
        from cryptography.fernet import Fernet

        key_bytes = master_key.encode() if isinstance(master_key, str) else master_key
        self._fernet = Fernet(key_bytes)
        # Non-secret, stable id derived from the master key: distinct keys get
        # distinct ids (a hash prefix reveals nothing about the key itself).
        self._key_id = "local:" + hashlib.sha256(key_bytes).hexdigest()[:16]

    @property
    def key_id(self) -> str:
        return self._key_id

    def generate_data_key(self) -> DataKeyPair:
        plaintext = os.urandom(32)  # AES-256
        return DataKeyPair(plaintext=plaintext, encrypted=self.wrap_data_key(plaintext))

    def wrap_data_key(self, plaintext_key: bytes) -> bytes:
        return self._fernet.encrypt(plaintext_key)

    def decrypt_data_key(self, encrypted_key: bytes) -> bytes:
        return self._fernet.decrypt(encrypted_key)


class AwsKMSProvider(SecretKMSProvider):
    """AWS KMS provider — GenerateDataKey / Decrypt against a CMK."""

    def __init__(self, key_id: str, region_name: str | None = None) -> None:
        self._key_id = key_id
        self._region = region_name

    @property
    def key_id(self) -> str:
        return self._key_id

    def _client(self) -> Any:  # lazy so boto3 isn't a base dependency
        import boto3

        return boto3.client("kms", region_name=self._region)

    def generate_data_key(self) -> DataKeyPair:
        resp = self._client().generate_data_key(KeyId=self._key_id, KeySpec="AES_256")
        return DataKeyPair(
            plaintext=resp["Plaintext"], encrypted=resp["CiphertextBlob"]
        )

    def wrap_data_key(self, plaintext_key: bytes) -> bytes:
        resp = self._client().encrypt(KeyId=self._key_id, Plaintext=plaintext_key)
        return cast(bytes, resp["CiphertextBlob"])

    def decrypt_data_key(self, encrypted_key: bytes) -> bytes:
        resp = self._client().decrypt(KeyId=self._key_id, CiphertextBlob=encrypted_key)
        return cast(bytes, resp["Plaintext"])


class AzureKMSProvider(SecretKMSProvider):
    """Azure Key Vault provider — wraps/unwraps the DEK with a Key Vault key."""

    def __init__(self, vault_url: str, key_name: str) -> None:
        self._vault_url = vault_url
        self._key_name = key_name

    @property
    def key_id(self) -> str:
        return self._key_name

    def _crypto_client(self) -> Any:
        from azure.identity import DefaultAzureCredential
        from azure.keyvault.keys import KeyClient
        from azure.keyvault.keys.crypto import CryptographyClient

        cred = DefaultAzureCredential()
        key = KeyClient(vault_url=self._vault_url, credential=cred).get_key(
            self._key_name
        )
        return CryptographyClient(key, credential=cred)

    def generate_data_key(self) -> DataKeyPair:
        plaintext = os.urandom(32)
        return DataKeyPair(plaintext=plaintext, encrypted=self.wrap_data_key(plaintext))

    def wrap_data_key(self, plaintext_key: bytes) -> bytes:
        from azure.keyvault.keys.crypto import KeyWrapAlgorithm

        wrapped = self._crypto_client().wrap_key(
            KeyWrapAlgorithm.rsa_oaep, plaintext_key
        )
        return cast(bytes, wrapped.encrypted_key)

    def decrypt_data_key(self, encrypted_key: bytes) -> bytes:
        from azure.keyvault.keys.crypto import KeyWrapAlgorithm

        result = self._crypto_client().unwrap_key(
            KeyWrapAlgorithm.rsa_oaep, encrypted_key
        )
        return cast(bytes, result.key)


class GcpKMSProvider(SecretKMSProvider):
    """GCP Cloud KMS provider — encrypt/decrypt the DEK under a KMS key."""

    def __init__(self, key_name: str) -> None:
        # Fully-qualified: projects/*/locations/*/keyRings/*/cryptoKeys/*
        self._key_name = key_name

    @property
    def key_id(self) -> str:
        return self._key_name

    def _client(self) -> Any:
        from google.cloud import kms

        return kms.KeyManagementServiceClient()

    def generate_data_key(self) -> DataKeyPair:
        plaintext = os.urandom(32)
        return DataKeyPair(plaintext=plaintext, encrypted=self.wrap_data_key(plaintext))

    def wrap_data_key(self, plaintext_key: bytes) -> bytes:
        resp = self._client().encrypt(
            request={"name": self._key_name, "plaintext": plaintext_key}
        )
        return cast(bytes, resp.ciphertext)

    def decrypt_data_key(self, encrypted_key: bytes) -> bytes:
        resp = self._client().decrypt(
            request={"name": self._key_name, "ciphertext": encrypted_key}
        )
        return cast(bytes, resp.plaintext)


# ---------------------------------------------------------------------------
# Factory + envelope codec
# ---------------------------------------------------------------------------


def provider_from_env(
    *, local_master_key: str | bytes | None = None
) -> SecretKMSProvider | None:
    """Build a KMS provider from ``SMART_LLM_KMS_PROVIDER`` (``local``/``aws``/
    ``azure``/``gcp``). Returns ``None`` when unset — callers then keep the
    legacy plain-Fernet path, so nothing changes without explicit opt-in.

    ``local`` requires ``local_master_key`` (typically the store's Fernet key).
    """
    kind = os.getenv("SMART_LLM_KMS_PROVIDER", "").strip().lower()
    if not kind:
        return None
    if kind == "local":
        if not local_master_key:
            raise ValueError(
                "SMART_LLM_KMS_PROVIDER=local requires a master key "
                "(pass local_master_key / the store's encryption_key)"
            )
        return LocalKMSProvider(local_master_key)
    if kind == "aws":
        key_id = os.environ["SMART_LLM_KMS_AWS_KEY_ID"]
        return AwsKMSProvider(key_id, region_name=os.getenv("AWS_REGION") or None)
    if kind == "azure":
        return AzureKMSProvider(
            os.environ["SMART_LLM_KMS_AZURE_VAULT_URL"],
            os.environ["SMART_LLM_KMS_AZURE_KEY_NAME"],
        )
    if kind == "gcp":
        return GcpKMSProvider(os.environ["SMART_LLM_KMS_GCP_KEY_NAME"])
    raise ValueError(f"Unknown SMART_LLM_KMS_PROVIDER: {kind!r}")


def _pack_v2(key_id: str, edek: bytes, iv_ct: bytes) -> str:
    """Assemble a v2 envelope blob (``iv_ct`` = iv(12) + ct+tag)."""
    kid = key_id.encode()
    payload = (
        struct.pack(">H", len(kid)) + kid + struct.pack(">I", len(edek)) + edek + iv_ct
    )
    return ENVELOPE_PREFIX_V2 + base64.urlsafe_b64encode(payload).decode()


def _parse(blob: str) -> tuple[str | None, bytes, bytes]:
    """Split a v1 or v2 envelope into ``(key_id, edek, iv_ct)``. ``key_id`` is
    ``None`` for a v1 blob (which predates the marker)."""
    if blob.startswith(ENVELOPE_PREFIX_V2):
        payload = base64.urlsafe_b64decode(blob[len(ENVELOPE_PREFIX_V2) :].encode())
        (kid_len,) = struct.unpack(">H", payload[:2])
        off = 2
        key_id = payload[off : off + kid_len].decode()
        off += kid_len
        (edek_len,) = struct.unpack(">I", payload[off : off + 4])
        off += 4
        edek = payload[off : off + edek_len]
        return key_id, edek, payload[off + edek_len :]
    if blob.startswith(ENVELOPE_PREFIX):
        payload = base64.urlsafe_b64decode(blob[len(ENVELOPE_PREFIX) :].encode())
        (edek_len,) = struct.unpack(">I", payload[:4])
        edek = payload[4 : 4 + edek_len]
        return None, edek, payload[4 + edek_len :]
    raise ValueError("not an envelope-encrypted secret")


def encrypt_secret(plaintext: str, provider: SecretKMSProvider) -> str:
    """Envelope-encrypt a secret string into a v2 blob (carrying the provider's
    key-id), safe to store in the same column as a legacy Fernet token."""
    pair = provider.generate_data_key()
    dek = bytearray(pair.plaintext)
    try:
        iv = os.urandom(12)
        ct = AESGCM(bytes(dek)).encrypt(iv, plaintext.encode(), None)
        return _pack_v2(provider.key_id, pair.encrypted, iv + ct)
    finally:
        _zero(dek)
        _zero(bytearray(pair.plaintext))


def is_envelope(blob: str) -> bool:
    """True if ``blob`` is an envelope (v1 or v2) produced by this module."""
    return blob.startswith(ENVELOPE_PREFIX) or blob.startswith(ENVELOPE_PREFIX_V2)


def envelope_key_id(blob: str) -> str | None:
    """The wrapping KEK's key-id recorded in a v2 envelope, or ``None`` for a v1
    envelope (which predates the marker). Lets rotation skip rows already on the
    new KEK without trial-decrypting. Raises if ``blob`` isn't an envelope."""
    return _parse(blob)[0]


def decrypt_secret(blob: str, provider: SecretKMSProvider) -> str:
    """Inverse of :func:`encrypt_secret`; reads both v1 and v2. Raises if ``blob``
    isn't an envelope."""
    _key_id, edek, iv_ct = _parse(blob)
    iv, ct = iv_ct[:12], iv_ct[12:]
    dek = bytearray(provider.decrypt_data_key(edek))
    try:
        return AESGCM(bytes(dek)).decrypt(iv, ct, None).decode()
    finally:
        _zero(dek)


def rewrap_secret(
    blob: str,
    *,
    old_provider: SecretKMSProvider,
    new_provider: SecretKMSProvider,
) -> str:
    """Re-wrap an envelope's DEK from one KEK to another — KEK rotation.

    Unwraps the data key with ``old_provider`` and re-wraps it with
    ``new_provider``, re-packing the SAME iv + ciphertext into a v2 blob tagged
    with ``new_provider.key_id``. The protected data is never decrypted and its
    ciphertext bytes are unchanged; only the wrapped DEK (``edek``) and the
    recorded key-id differ. This is what makes envelope encryption cheap to
    rotate — rotating the master key touches only the wrapped DEKs, not the data.
    Reads both v1 and v2 input.

    Raises if ``blob`` isn't an envelope or its DEK won't unwrap under
    ``old_provider`` (e.g. the row was already re-wrapped under the new KEK; the
    caller can check :func:`envelope_key_id` first to skip those)."""
    _old_kid, edek, iv_ct = _parse(blob)  # iv(12) + ct+tag — preserved verbatim
    dek = bytearray(old_provider.decrypt_data_key(edek))
    try:
        new_edek = new_provider.wrap_data_key(bytes(dek))
    finally:
        _zero(dek)
    return _pack_v2(new_provider.key_id, new_edek, iv_ct)
