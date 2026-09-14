import os
import uuid
from unittest.mock import patch

import pytest
import pytest_asyncio

from smart_llm.key_manager import KeyManager
from smart_llm.key_store import EnvKeyStore

# ---------------------------------------------------------------------------
# EnvKeyStore tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_env_store_loads_single_key():
    store = EnvKeyStore()
    with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test123"}):
        keys = await store.load_keys("openai")
    assert keys == ["sk-test123"]


@pytest.mark.asyncio
async def test_env_store_loads_multi_keys():
    store = EnvKeyStore()
    with patch.dict(os.environ, {"OPENAI_API_KEYS": "sk-a,sk-b,sk-c"}):
        keys = await store.load_keys("openai")
    assert keys == ["sk-a", "sk-b", "sk-c"]


@pytest.mark.asyncio
async def test_env_store_merges_single_and_multi():
    store = EnvKeyStore()
    with patch.dict(
        os.environ,
        {
            "OPENAI_API_KEYS": "sk-a,sk-b",
            "OPENAI_API_KEY": "sk-c",
        },
    ):
        keys = await store.load_keys("openai")
    assert keys == ["sk-a", "sk-b", "sk-c"]


@pytest.mark.asyncio
async def test_env_store_deduplicates():
    store = EnvKeyStore()
    with patch.dict(
        os.environ,
        {
            "OPENAI_API_KEYS": "sk-a",
            "OPENAI_API_KEY": "sk-a",
        },
    ):
        keys = await store.load_keys("openai")
    assert keys == ["sk-a"]


@pytest.mark.asyncio
async def test_env_store_returns_empty_for_missing():
    store = EnvKeyStore()
    with patch.dict(os.environ, {}, clear=True):
        keys = await store.load_keys("openai")
    assert keys == []


@pytest.mark.asyncio
async def test_env_store_list_providers():
    store = EnvKeyStore()
    with patch.dict(
        os.environ,
        {
            "OPENAI_API_KEY": "sk-test",
            "GEMINI_API_KEY": "gem-test",
        },
        clear=True,
    ):
        providers = await store.list_providers()
    assert set(providers) == {"openai", "gemini"}


@pytest.mark.asyncio
async def test_env_store_save_raises():
    store = EnvKeyStore()
    with pytest.raises(NotImplementedError):
        await store.save_key("openai", "key")


@pytest.mark.asyncio
async def test_env_store_delete_raises():
    store = EnvKeyStore()
    with pytest.raises(NotImplementedError):
        await store.delete_key("some-id")


# ---------------------------------------------------------------------------
# KeyManager + EnvKeyStore integration
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_key_manager_loads_from_env_store():
    store = EnvKeyStore()
    km = KeyManager(rotation_interval=5, key_store=store)
    with patch.dict(
        os.environ,
        {
            "OPENAI_API_KEY": "sk-test",
            "ANTHROPIC_API_KEY": "ant-test",
        },
        clear=True,
    ):
        await km.load_from_store()

    assert km.get_key("openai") == "sk-test"
    assert km.get_key("anthropic") == "ant-test"
    assert km.get_key("gemini") is None


@pytest.mark.asyncio
async def test_key_manager_no_store_raises():
    km = KeyManager()
    with pytest.raises(RuntimeError, match="No KeyStore configured"):
        await km.load_from_store()


# ---------------------------------------------------------------------------
# DatabaseKeyStore tests (requires smart-llm[db])
# ---------------------------------------------------------------------------

try:
    import cryptography  # noqa: F401
    import sqlalchemy  # noqa: F401

    HAS_DB_DEPS = True
except ImportError:
    HAS_DB_DEPS = False


@pytest.fixture
def encryption_key():
    from cryptography.fernet import Fernet

    return Fernet.generate_key().decode()


@pytest_asyncio.fixture
async def db_store(encryption_key):
    from sqlalchemy.ext.asyncio import create_async_engine

    from smart_llm.key_store import DatabaseKeyStore

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    store = DatabaseKeyStore(engine=engine, encryption_key=encryption_key)
    await store.create_tables()
    yield store
    await engine.dispose()


@pytest.mark.skipif(not HAS_DB_DEPS, reason="db extras not installed")
@pytest.mark.asyncio
async def test_db_store_save_and_load(db_store):
    result = await db_store.save_key("openai", "sk-secret-123", label="prod")
    assert "id" in result
    assert result["provider"] == "openai"

    keys = await db_store.load_keys("openai")
    assert keys == ["sk-secret-123"]


@pytest.mark.skipif(not HAS_DB_DEPS, reason="db extras not installed")
@pytest.mark.asyncio
async def test_db_store_encryption_roundtrip(db_store):
    await db_store.save_key("anthropic", "ant-key-456")
    keys = await db_store.load_keys("anthropic")
    assert keys == ["ant-key-456"]


@pytest.mark.skipif(not HAS_DB_DEPS, reason="db extras not installed")
@pytest.mark.asyncio
async def test_db_store_delete(db_store):
    result = await db_store.save_key("openai", "sk-to-delete")
    key_id = result["id"]

    deleted = await db_store.delete_key(key_id)
    assert deleted is True

    keys = await db_store.load_keys("openai")
    assert keys == []


@pytest.mark.skipif(not HAS_DB_DEPS, reason="db extras not installed")
@pytest.mark.asyncio
async def test_db_store_delete_nonexistent(db_store):
    deleted = await db_store.delete_key(str(uuid.uuid4()))
    assert deleted is False


@pytest.mark.skipif(not HAS_DB_DEPS, reason="db extras not installed")
@pytest.mark.asyncio
async def test_db_store_scope_isolation(db_store):
    scope_a = uuid.uuid4()
    scope_b = uuid.uuid4()

    await db_store.save_key("openai", "key-a", scope_id=scope_a)
    await db_store.save_key("openai", "key-b", scope_id=scope_b)

    keys_a = await db_store.load_keys("openai", scope_id=scope_a)
    keys_b = await db_store.load_keys("openai", scope_id=scope_b)

    assert keys_a == ["key-a"]
    assert keys_b == ["key-b"]


@pytest.mark.skipif(not HAS_DB_DEPS, reason="db extras not installed")
@pytest.mark.asyncio
async def test_db_store_list_keys(db_store):
    scope = uuid.uuid4()
    await db_store.save_key("openai", "sk-1", label="key1", scope_id=scope)
    await db_store.save_key("anthropic", "ant-1", label="key2", scope_id=scope)

    all_keys = await db_store.list_keys(scope_id=scope)
    assert len(all_keys) == 2
    # Keys should not contain the actual secret
    for k in all_keys:
        assert "encrypted_key" not in k
        assert k["provider"] in ("openai", "anthropic")


@pytest.mark.skipif(not HAS_DB_DEPS, reason="db extras not installed")
@pytest.mark.asyncio
async def test_db_store_list_providers(db_store):
    scope = uuid.uuid4()
    await db_store.save_key("openai", "sk-1", scope_id=scope)
    await db_store.save_key("gemini", "gem-1", scope_id=scope)

    providers = await db_store.list_providers(scope_id=scope)
    assert set(providers) == {"openai", "gemini"}


@pytest.mark.skipif(not HAS_DB_DEPS, reason="db extras not installed")
@pytest.mark.asyncio
async def test_key_manager_with_db_store(db_store):
    scope = uuid.uuid4()
    km = KeyManager(rotation_interval=5, key_store=db_store)

    await km.save_to_store("openai", "sk-db-key", scope_id=scope)
    await km.load_from_store(scope_id=scope)

    assert km.get_key("openai") == "sk-db-key"


# ---------------------------------------------------------------------------
# A5 — KMS envelope encryption (HARDENING-PLAN)
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def kms_store(encryption_key):
    """A DatabaseKeyStore wired to the ``local`` KMS provider — new keys are
    envelope-encrypted, legacy Fernet rows still decrypt."""
    from sqlalchemy.ext.asyncio import create_async_engine

    from smart_llm.key_store import DatabaseKeyStore
    from smart_llm.secret_envelope import LocalKMSProvider

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    store = DatabaseKeyStore(
        engine=engine,
        encryption_key=encryption_key,
        kms_provider=LocalKMSProvider(encryption_key),
    )
    await store.create_tables()
    yield store
    await engine.dispose()


async def _raw_encrypted_key(store, provider: str) -> str:
    """Read the raw stored ciphertext for a provider's active key."""
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession

    Model = store._get_table()  # noqa: SLF001 — test-only introspection
    async with AsyncSession(store._engine) as session:  # noqa: SLF001
        row = (
            (
                await session.execute(
                    select(Model).where(
                        Model.provider == provider, Model.is_active.is_(True)
                    )
                )
            )
            .scalars()
            .first()
        )
        return row.encrypted_key


@pytest.mark.skipif(not HAS_DB_DEPS, reason="db extras not installed")
@pytest.mark.asyncio
async def test_kms_store_stores_envelope_not_plaintext_or_fernet(kms_store):
    from smart_llm.secret_envelope import is_envelope

    await kms_store.save_key("openai", "sk-envelope-1")
    stored = await _raw_encrypted_key(kms_store, "openai")
    # Envelope-tagged, and the secret never appears in the ciphertext.
    assert is_envelope(stored)
    assert "sk-envelope-1" not in stored
    # Round-trips back to plaintext.
    assert await kms_store.load_keys("openai") == ["sk-envelope-1"]


@pytest.mark.skipif(not HAS_DB_DEPS, reason="db extras not installed")
@pytest.mark.asyncio
async def test_kms_store_reads_legacy_fernet_rows(encryption_key):
    """A store with KMS enabled must still decrypt rows written by the old
    plain-Fernet scheme (so enabling KMS doesn't strand existing keys)."""
    from sqlalchemy.ext.asyncio import create_async_engine

    from smart_llm.key_store import DatabaseKeyStore
    from smart_llm.secret_envelope import LocalKMSProvider

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    # 1) Write with a legacy (no-KMS) store.
    legacy = DatabaseKeyStore(engine=engine, encryption_key=encryption_key)
    await legacy.create_tables()
    await legacy.save_key("anthropic", "ant-legacy")
    # 2) Read with a KMS-enabled store over the same DB.
    kms = DatabaseKeyStore(
        engine=engine,
        encryption_key=encryption_key,
        kms_provider=LocalKMSProvider(encryption_key),
    )
    assert await kms.load_keys("anthropic") == ["ant-legacy"]
    await engine.dispose()


@pytest.mark.skipif(not HAS_DB_DEPS, reason="db extras not installed")
@pytest.mark.asyncio
async def test_reencrypt_all_migrates_legacy_rows(encryption_key):
    from sqlalchemy.ext.asyncio import create_async_engine

    from smart_llm.key_store import DatabaseKeyStore
    from smart_llm.secret_envelope import LocalKMSProvider, is_envelope

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    legacy = DatabaseKeyStore(engine=engine, encryption_key=encryption_key)
    await legacy.create_tables()
    await legacy.save_key("openai", "sk-legacy-a")
    await legacy.save_key("anthropic", "ant-legacy-b")

    kms = DatabaseKeyStore(
        engine=engine,
        encryption_key=encryption_key,
        kms_provider=LocalKMSProvider(encryption_key),
    )
    migrated = await kms.reencrypt_all()
    assert migrated == 2
    # Both rows are now envelope-format, and still decrypt to the same secrets.
    assert is_envelope(await _raw_encrypted_key(kms, "openai"))
    assert is_envelope(await _raw_encrypted_key(kms, "anthropic"))
    assert await kms.load_keys("openai") == ["sk-legacy-a"]
    assert await kms.load_keys("anthropic") == ["ant-legacy-b"]
    # Idempotent — a second run migrates nothing.
    assert await kms.reencrypt_all() == 0
    await engine.dispose()


@pytest.mark.skipif(not HAS_DB_DEPS, reason="db extras not installed")
@pytest.mark.asyncio
async def test_reencrypt_all_requires_kms_provider(db_store):
    with pytest.raises(ValueError):
        await db_store.reencrypt_all()  # no KMS provider → nothing to migrate to


@pytest.mark.skipif(not HAS_DB_DEPS, reason="db extras not installed")
@pytest.mark.asyncio
async def test_legacy_store_cannot_decrypt_envelope_rows(kms_store, encryption_key):
    """Negative: a store with NO KMS provider must refuse an envelope row rather
    than silently returning garbage."""
    from smart_llm.key_store import DatabaseKeyStore

    await kms_store.save_key("openai", "sk-env-only")
    # A legacy store sharing the same engine but no KMS provider.
    legacy = DatabaseKeyStore(
        engine=kms_store._engine,
        encryption_key=encryption_key,  # noqa: SLF001
    )
    with pytest.raises(ValueError):
        await legacy.load_keys("openai")


@pytest.mark.skipif(not HAS_DB_DEPS, reason="db extras not installed")
@pytest.mark.asyncio
async def test_rewrap_all_rotates_kek(encryption_key):
    """rewrap_all re-wraps every envelope DEK from the old KEK to the store's
    current (new) KEK: the new store reads all keys, the old KEK can no longer,
    and a second sweep is a resumable no-op."""
    from cryptography.fernet import Fernet, InvalidToken
    from sqlalchemy.ext.asyncio import create_async_engine

    from smart_llm.key_store import DatabaseKeyStore
    from smart_llm.secret_envelope import LocalKMSProvider

    old_provider = LocalKMSProvider(encryption_key)
    new_key = Fernet.generate_key().decode()
    new_provider = LocalKMSProvider(new_key)

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    old_store = DatabaseKeyStore(
        engine=engine, encryption_key=encryption_key, kms_provider=old_provider
    )
    await old_store.create_tables()
    await old_store.save_key("openai", "sk-a")
    await old_store.save_key("anthropic", "ant-b")

    new_store = DatabaseKeyStore(
        engine=engine, encryption_key=new_key, kms_provider=new_provider
    )
    assert await new_store.rewrap_all(old_provider) == 2

    # Data ciphertext preserved → same plaintext, now readable under the new KEK.
    assert await new_store.load_keys("openai") == ["sk-a"]
    assert await new_store.load_keys("anthropic") == ["ant-b"]
    # The old KEK can no longer unwrap the rotated DEKs.
    with pytest.raises(InvalidToken):
        await old_store.load_keys("openai")
    # Resumable: a second sweep re-wraps nothing (all rows already on the new KEK).
    assert await new_store.rewrap_all(old_provider) == 0
    assert await new_store.load_keys("openai") == ["sk-a"]

    await engine.dispose()


@pytest.mark.skipif(not HAS_DB_DEPS, reason="db extras not installed")
@pytest.mark.asyncio
async def test_rewrap_all_skips_legacy_rows(encryption_key):
    """A legacy (non-envelope) Fernet row is left untouched by rewrap_all —
    reencrypt_all is the path to bring it into the envelope scheme first."""
    from cryptography.fernet import Fernet
    from sqlalchemy.ext.asyncio import create_async_engine

    from smart_llm.key_store import DatabaseKeyStore
    from smart_llm.secret_envelope import LocalKMSProvider, is_envelope

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    legacy = DatabaseKeyStore(engine=engine, encryption_key=encryption_key)
    await legacy.create_tables()
    await legacy.save_key("openai", "sk-legacy")

    new_provider = LocalKMSProvider(Fernet.generate_key())
    kms = DatabaseKeyStore(
        engine=engine, encryption_key=encryption_key, kms_provider=new_provider
    )
    assert await kms.rewrap_all(LocalKMSProvider(encryption_key)) == 0
    stored = await _raw_encrypted_key(kms, "openai")
    assert not is_envelope(stored)  # legacy row untouched

    await engine.dispose()
