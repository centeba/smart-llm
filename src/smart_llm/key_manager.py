import logging
import uuid
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from .key_store import KeyStore

logger = logging.getLogger(__name__)


class KeyManager:
    """
    Manages API keys for multiple LLM providers with rotation support.

    Optionally backed by a :class:`KeyStore` for persistent storage.
    When no store is provided the manager operates purely in-memory
    (backward-compatible with the original behaviour).
    """

    def __init__(
        self,
        rotation_interval: int = 10,
        key_store: Optional["KeyStore"] = None,
    ):
        self.keys: dict[str, list[str]] = {}
        self.indices: dict[str, int] = {}
        self.usage_counts: dict[str, int] = {}
        self.rotation_interval = rotation_interval
        self._store = key_store

    # ------------------------------------------------------------------
    # In-memory operations (unchanged, sync, backward-compatible)
    # ------------------------------------------------------------------

    def register_provider(self, name: str, keys: list[str]) -> None:
        """Register a provider and its list of keys."""
        self.keys[name.lower()] = keys
        self.indices[name.lower()] = 0
        self.usage_counts[name.lower()] = 0

    def get_key(self, provider: str) -> str | None:
        """Get the current active key for a provider, rotating if interval reached."""
        name = provider.lower()
        provider_keys = self.keys.get(name, [])
        if not provider_keys:
            return None

        current_index = self.indices[name]

        if self.usage_counts[name] >= self.rotation_interval:
            self.indices[name] = (current_index + 1) % len(provider_keys)
            self.usage_counts[name] = 0
            logger.info(f"Rotating key for {name} to index {self.indices[name]}")

        self.usage_counts[name] += 1
        return provider_keys[self.indices[name]]

    def rotate_on_failure(self, provider: str) -> None:
        """Force immediate rotation for a provider due to failure."""
        name = provider.lower()
        provider_keys = self.keys.get(name, [])
        if provider_keys:
            self.indices[name] = (self.indices[name] + 1) % len(provider_keys)
            self.usage_counts[name] = 0
            logger.warning(f"Forced rotation for {name} due to failure.")

    # ------------------------------------------------------------------
    # Store-backed operations (async)
    # ------------------------------------------------------------------

    async def load_from_store(
        self,
        provider: str | None = None,
        *,
        scope_id: uuid.UUID | None = None,
    ) -> None:
        """Load keys from the configured store into in-memory rotation.

        If *provider* is ``None`` all providers with active keys are loaded.
        """
        if self._store is None:
            raise RuntimeError("No KeyStore configured on this KeyManager")

        if provider:
            keys = await self._store.load_keys(provider, scope_id=scope_id)
            if keys:
                self.register_provider(provider, keys)
        else:
            providers = await self._store.list_providers(scope_id=scope_id)
            for p in providers:
                keys = await self._store.load_keys(p, scope_id=scope_id)
                if keys:
                    self.register_provider(p, keys)

    async def save_to_store(
        self,
        provider: str,
        key: str,
        *,
        label: str | None = None,
        scope_id: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        """Persist a key via the store and register it for in-memory rotation."""
        if self._store is None:
            raise RuntimeError("No KeyStore configured on this KeyManager")

        result = await self._store.save_key(
            provider, key, label=label, scope_id=scope_id
        )
        # Also add to in-memory rotation
        name = provider.lower()
        if name not in self.keys:
            self.register_provider(name, [key])
        else:
            self.keys[name].append(key)
        return result

    async def delete_from_store(self, key_id: str) -> bool:
        """Remove a key from the store. Does NOT remove from in-memory rotation
        (call ``load_from_store`` to refresh)."""
        if self._store is None:
            raise RuntimeError("No KeyStore configured on this KeyManager")
        return await self._store.delete_key(key_id)


# Default instance for convenience (no store, pure in-memory)
key_manager = KeyManager()
