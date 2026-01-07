"""Factory for creating storage backends."""

from depotgate.config import settings
from depotgate.storage.base import StorageBackend
from depotgate.storage.filesystem import FilesystemStorageBackend

# Registry of available storage backends
_BACKENDS: dict[str, type[StorageBackend]] = {
    "filesystem": FilesystemStorageBackend,
}


def get_storage_backend(backend_type: str | None = None) -> StorageBackend:
    """
    Get a storage backend instance.

    Args:
        backend_type: Type of backend to create. Defaults to config value.

    Returns:
        StorageBackend instance

    Raises:
        ValueError: If backend type is not registered
    """
    backend_type = backend_type or settings.storage_backend

    if backend_type not in _BACKENDS:
        raise ValueError(
            f"Unknown storage backend: {backend_type}. "
            f"Available: {list(_BACKENDS.keys())}"
        )

    return _BACKENDS[backend_type]()


def register_storage_backend(name: str, backend_class: type[StorageBackend]) -> None:
    """
    Register a new storage backend type.

    Args:
        name: Name for the backend type
        backend_class: Backend class to register
    """
    _BACKENDS[name] = backend_class


def list_storage_backends() -> list[str]:
    """List available storage backend types."""
    return list(_BACKENDS.keys())
