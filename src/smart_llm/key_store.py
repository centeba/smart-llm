"""Pluggable key persistence backends for smart-llm.

Provides an abstract KeyStore interface with two implementations:
- EnvKeyStore: loads keys from environment variables (default, zero-config)
- DatabaseKeyStore: encrypted key storage via SQLAlchemy (opt-in, requires `smart-llm[db]`)
"""

from __future__ import annotations

import logging
import os
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from smart_llm.models import LLMApiKey
    from smart_llm.secret_envelope import SecretKMSProvider

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Provider name mapping for env vars
# ---------------------------------------------------------------------------

_ENV_KEY_MAP = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
}

_ENV_KEYS_MAP = {
    "openai": "OPENAI_API_KEYS",
    "anthropic": "ANTHROPIC_API_KEYS",
    "gemini": "GEMINI_API_KEYS",
    "openrouter": "OPENROUTER_API_KEYS",
}


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------


class KeyStore(ABC):
    """Abstract interface for API key persistence."""

    @abstractmethod
    async def load_keys(
        self, provider: str, *, scope_id: uuid.UUID | None = None
    ) -> list[str]:
        """Return all active plaintext keys for a provider."""

    @abstractmethod
    async def save_key(
        self,
        provider: str,
        key: str,
        *,
        label: str | None = None,
        scope_id: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        """Persist a new key. Returns metadata dict with at least 'id'."""

    @abstractmethod
    async def delete_key(self, key_id: str) -> bool:
        """Remove a key by its ID. Returns True if deleted."""

    @abstractmethod
    async def list_keys(
        self, *, scope_id: uuid.UUID | None = None
    ) -> list[dict[str, Any]]:
        """List key metadata (id, provider, is_active, label) without exposing secrets."""

    @abstractmethod
    async def list_providers(self, *, scope_id: uuid.UUID | None = None) -> list[str]:
        """Return distinct provider names that have at least one active key."""


# ---------------------------------------------------------------------------
# Environment variable backend
# ---------------------------------------------------------------------------


class EnvKeyStore(KeyStore):
    """Loads keys from environment variables.

    Supports both single-key (``OPENAI_API_KEY``) and multi-key
    (``OPENAI_API_KEYS`` — comma-separated) formats.

    This store is **read-only**; ``save_key`` and ``delete_key`` raise
    ``NotImplementedError``.
    """

    async def load_keys(
        self, provider: str, *, scope_id: uuid.UUID | None = None
    ) -> list[str]:
        name = provider.lower()
        keys: list[str] = []

        # Check multi-key env var first (comma-separated)
        multi_env = _ENV_KEYS_MAP.get(name)
        if multi_env:
            val = os.getenv(multi_env, "").strip()
            if val:
                keys.extend(k.strip() for k in val.split(",") if k.strip())

        # Fall back / also check single-key env var
        single_env = _ENV_KEY_MAP.get(name)
        if single_env:
            val = os.getenv(single_env, "").strip()
            if val and val not in keys:
                keys.append(val)

        return keys

    async def save_key(self, provider: str, key: str, **kwargs: Any) -> dict[str, Any]:
        raise NotImplementedError(
            "EnvKeyStore is read-only. Set keys via environment variables."
        )

    async def delete_key(self, key_id: str) -> bool:
        raise NotImplementedError(
            "EnvKeyStore is read-only. Remove keys from environment variables."
        )

    async def list_keys(
        self, *, scope_id: uuid.UUID | None = None
    ) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for provider in _ENV_KEY_MAP:
            keys = await self.load_keys(provider)
            for i, _ in enumerate(keys):
                result.append(
                    {
                        "id": f"env-{provider}-{i}",
                        "provider": provider,
                        "is_active": True,
                        "label": f"env ({provider})",
                    }
                )
        return result

    async def list_providers(self, *, scope_id: uuid.UUID | None = None) -> list[str]:
        providers: list[str] = []
        for provider in _ENV_KEY_MAP:
            if await self.load_keys(provider):
                providers.append(provider)
        return providers


# ---------------------------------------------------------------------------
# Database backend (requires smart-llm[db] extras)
# ---------------------------------------------------------------------------


class DatabaseKeyStore(KeyStore):
    """Encrypted key storage backed by a SQL database via SQLAlchemy async.

    Requires the ``db`` extras: ``pip install smart-llm[db]``

    Encryption is **KMS-envelope by default when configured**, with a
    legacy-compatible fallback:

    - If a ``kms_provider`` is supplied (or ``SMART_LLM_KMS_PROVIDER`` is set),
      new keys are envelope-encrypted — a random DEK encrypts the key and only
      the DEK is wrapped by the KMS master key. This retires the host-disk
      Fernet key from the storage path in production (KMS holds the master).
    - Otherwise keys are encrypted with the ``encryption_key`` Fernet directly,
      exactly as before.

    Reads auto-detect the format (see :func:`smart_llm.secret_envelope.is_envelope`),
    so a store can decrypt legacy rows and envelope rows side by side — enabling
    a lazy, non-blocking migration (or the explicit :meth:`reencrypt_all`).

    Parameters
    ----------
    engine : AsyncEngine
        SQLAlchemy async engine connected to the target database.
    encryption_key : str
        A Fernet-compatible key. Used to decrypt legacy rows, and — for the
        ``local`` KMS provider — to wrap DEKs, so no new key material is needed
        for dev/test.
    table_name : str
        Name of the database table (default ``"llm_api_keys"``).
    kms_provider : SecretKMSProvider | None
        Explicit provider. When ``None``, one is built from the environment via
        ``provider_from_env`` (which returns ``None`` unless
        ``SMART_LLM_KMS_PROVIDER`` is set — preserving legacy behavior).
    """

    def __init__(
        self,
        engine: Any,
        encryption_key: str,
        table_name: str = "llm_api_keys",
        kms_provider: "SecretKMSProvider | None" = None,
    ) -> None:
        try:
            from cryptography.fernet import Fernet
            from sqlalchemy.ext.asyncio import (
                AsyncSession,  # noqa: F401 — availability probe for the `db` extra
            )
        except ImportError as exc:
            raise ImportError(
                "DatabaseKeyStore requires the 'db' extras. "
                "Install with: pip install smart-llm[db]"
            ) from exc

        from smart_llm.secret_envelope import provider_from_env

        self._engine = engine
        self._table_name = table_name
        self._fernet = Fernet(
            encryption_key.encode()
            if isinstance(encryption_key, str)
            else encryption_key
        )
        # Explicit provider wins; else derive from env (None => legacy Fernet,
        # so nothing changes unless an operator opts in). The local provider
        # reuses this store's Fernet key so dev needs no extra config.
        self._kms = (
            kms_provider
            if kms_provider is not None
            else provider_from_env(local_master_key=encryption_key)
        )

    def _encrypt(self, plaintext: str) -> str:
        # With a KMS provider, new keys are envelope-encrypted; otherwise fall
        # back to the legacy plain-Fernet scheme (unchanged behavior).
        if self._kms is None:
            return self._fernet.encrypt(plaintext.encode()).decode()
        from smart_llm.secret_envelope import encrypt_secret

        return encrypt_secret(plaintext, self._kms)

    def _decrypt(self, ciphertext: str) -> str:
        # Auto-detect the stored format so legacy and envelope rows coexist.
        from smart_llm.secret_envelope import decrypt_secret, is_envelope

        if not is_envelope(ciphertext):
            return self._fernet.decrypt(ciphertext.encode()).decode()
        if self._kms is None:
            raise ValueError(
                "envelope-encrypted key found but no KMS provider is configured"
            )
        return decrypt_secret(ciphertext, self._kms)

    def _get_table(self) -> type[LLMApiKey]:
        """Return the LLMApiKey model class."""
        from smart_llm.models import LLMApiKey

        return LLMApiKey

    async def load_keys(
        self, provider: str, *, scope_id: uuid.UUID | None = None
    ) -> list[str]:
        from sqlalchemy import select
        from sqlalchemy.ext.asyncio import AsyncSession

        Model = self._get_table()
        async with AsyncSession(self._engine) as session:
            stmt = select(Model).where(
                Model.provider == provider.lower(),
                Model.is_active.is_(True),
            )
            if scope_id is not None:
                stmt = stmt.where(Model.scope_id == scope_id)
            result = await session.execute(stmt)
            rows = result.scalars().all()
            return [self._decrypt(row.encrypted_key) for row in rows]

    async def save_key(
        self,
        provider: str,
        key: str,
        *,
        label: str | None = None,
        scope_id: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        from sqlalchemy import update
        from sqlalchemy.ext.asyncio import AsyncSession

        Model = self._get_table()
        row_id = uuid.uuid4()
        now = datetime.now(timezone.utc)
        row = Model(
            id=row_id,
            provider=provider.lower(),
            encrypted_key=self._encrypt(key),
            is_active=True,
            label=label,
            scope_id=scope_id,
            created_at=now,
        )
        async with AsyncSession(self._engine) as session:
            # Rotation, not accumulation: at most one active key per
            # (scope, provider) — enforced by a matching partial unique
            # index on the table, but deactivate explicitly here too so a
            # rapid retry/duplicate submission (e.g. a client-side retry
            # loop) finds no existing active row to collide with instead
            # of raising an IntegrityError.
            await session.execute(
                update(Model)
                .where(
                    Model.provider == provider.lower(),
                    Model.scope_id == scope_id,
                    Model.is_active.is_(True),
                )
                .values(is_active=False)
            )
            session.add(row)
            await session.commit()
        # Return metadata captured before commit to avoid expired-attribute access
        return {
            "id": str(row_id),
            "provider": provider.lower(),
            "is_active": True,
            "label": label,
            "scope_id": str(scope_id) if scope_id else None,
            "created_at": now.isoformat(),
        }

    async def delete_key(self, key_id: str) -> bool:
        from sqlalchemy import select
        from sqlalchemy.ext.asyncio import AsyncSession

        Model = self._get_table()
        async with AsyncSession(self._engine) as session:
            stmt = select(Model).where(Model.id == uuid.UUID(key_id))
            result = await session.execute(stmt)
            row = result.scalars().first()
            if row is None:
                return False
            await session.delete(row)
            await session.commit()
            return True

    async def list_keys(
        self, *, scope_id: uuid.UUID | None = None
    ) -> list[dict[str, Any]]:
        from sqlalchemy import select
        from sqlalchemy.ext.asyncio import AsyncSession

        Model = self._get_table()
        async with AsyncSession(self._engine) as session:
            stmt = select(Model)
            if scope_id is not None:
                stmt = stmt.where(Model.scope_id == scope_id)
            stmt = stmt.order_by(Model.created_at.desc())
            result = await session.execute(stmt)
            rows = result.scalars().all()
            return [
                {
                    "id": str(r.id),
                    "provider": r.provider,
                    "is_active": r.is_active,
                    "label": r.label,
                    "scope_id": str(r.scope_id) if r.scope_id else None,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                }
                for r in rows
            ]

    async def list_providers(self, *, scope_id: uuid.UUID | None = None) -> list[str]:
        from sqlalchemy import distinct, select
        from sqlalchemy.ext.asyncio import AsyncSession

        Model = self._get_table()
        async with AsyncSession(self._engine) as session:
            stmt = select(distinct(Model.provider)).where(Model.is_active.is_(True))
            if scope_id is not None:
                stmt = stmt.where(Model.scope_id == scope_id)
            result = await session.execute(stmt)
            return [row[0] for row in result.all()]

    async def create_tables(self) -> None:
        """Create the key storage table if it doesn't exist."""
        from smart_llm.models import Base

        async with self._engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def reencrypt_all(self) -> int:
        """One-time migration: re-encrypt every legacy Fernet-encrypted row under
        the configured KMS envelope. Idempotent — rows already in envelope form
        are skipped. Returns the number of rows rewritten.

        Requires a KMS provider (``SMART_LLM_KMS_PROVIDER`` / ``kms_provider``);
        raises otherwise, since there'd be nothing to migrate *to*. Safe to run
        online: reads decrypt via the format-detecting path, and each row is
        rewritten in place, so concurrent readers see either the old or the new
        ciphertext — both decrypt to the same key.
        """
        from sqlalchemy import select
        from sqlalchemy.ext.asyncio import AsyncSession

        from smart_llm.secret_envelope import is_envelope

        if self._kms is None:
            raise ValueError(
                "reencrypt_all requires a KMS provider "
                "(set SMART_LLM_KMS_PROVIDER or pass kms_provider)"
            )

        Model = self._get_table()
        migrated = 0
        async with AsyncSession(self._engine) as session:
            rows = (await session.execute(select(Model))).scalars().all()
            for row in rows:
                if is_envelope(row.encrypted_key):
                    continue  # already migrated
                plaintext = self._decrypt(row.encrypted_key)  # legacy Fernet path
                row.encrypted_key = self._encrypt(plaintext)  # -> envelope
                migrated += 1
            if migrated:
                await session.commit()
        return migrated

    async def rewrap_all(self, old_provider: SecretKMSProvider) -> int:
        """Rotate the envelope KEK: re-wrap every envelope row's DEK from
        ``old_provider``'s master key onto the store's CURRENT provider (the new
        KEK), leaving the data ciphertext untouched — only the wrapped DEK
        changes. Returns the number of rows re-wrapped.

        Legacy (non-envelope) rows are skipped — run :meth:`reencrypt_all` first
        to bring them into the envelope scheme.

        Targeted + resumable: a v2 row already tagged with the new KEK's key-id is
        skipped up front (no decrypt), so re-running the sweep is cheap. As a
        belt-and-braces fallback for v1 rows (no key-id) and partial reruns, a row
        whose DEK no longer unwraps under ``old_provider`` is verified to decrypt
        under the new provider and skipped rather than failing the sweep. A row
        that unwraps under NEITHER key is genuine corruption and raises.
        """
        from sqlalchemy import select
        from sqlalchemy.ext.asyncio import AsyncSession

        from smart_llm.secret_envelope import (
            decrypt_secret,
            envelope_key_id,
            is_envelope,
            rewrap_secret,
        )

        if self._kms is None:
            raise ValueError(
                "rewrap_all requires the store's KMS provider (the new KEK) — "
                "set SMART_LLM_KMS_PROVIDER or pass kms_provider"
            )

        new_key_id = self._kms.key_id
        Model = self._get_table()
        rewrapped = 0
        async with AsyncSession(self._engine) as session:
            rows = (await session.execute(select(Model))).scalars().all()
            for row in rows:
                if not is_envelope(row.encrypted_key):
                    continue  # legacy Fernet — run reencrypt_all first
                if envelope_key_id(row.encrypted_key) == new_key_id:
                    continue  # already on the new KEK (targeted skip, no decrypt)
                try:
                    row.encrypted_key = rewrap_secret(
                        row.encrypted_key,
                        old_provider=old_provider,
                        new_provider=self._kms,
                    )
                    rewrapped += 1
                except Exception:  # noqa: BLE001 — trial-decrypt fallback
                    # DEK won't unwrap under the old KEK. Most likely already
                    # re-wrapped under the new KEK by a prior run — verify and skip.
                    try:
                        decrypt_secret(row.encrypted_key, self._kms)
                    except Exception as verify_exc:  # noqa: BLE001
                        raise ValueError(
                            f"row {row.id}: DEK unwraps under neither the old nor "
                            f"the new KEK — refusing to rotate (possible corruption)"
                        ) from verify_exc
                    # else: already on the new KEK, leave as-is
            if rewrapped:
                await session.commit()
        return rewrapped
