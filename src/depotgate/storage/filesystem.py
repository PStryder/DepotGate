"""Filesystem storage backend implementation."""

import hashlib
import re
from pathlib import Path
from typing import AsyncIterator
from uuid import UUID

import aiofiles
import aiofiles.os

from depotgate.config import settings
from depotgate.storage.base import StorageBackend


class FilesystemStorageBackend(StorageBackend):
    """Filesystem-based artifact storage backend."""

    def __init__(self, base_path: Path | None = None):
        """Initialize filesystem storage.

        Args:
            base_path: Root directory for artifact storage. Defaults to config value.
        """
        self.base_path = base_path or settings.storage_base_path

    def _sanitize_path_component(self, component: str) -> str:
        """Sanitize path component to prevent directory traversal.
        
        Args:
            component: Path component to sanitize (tenant_id or root_task_id)
            
        Returns:
            Sanitized component with dangerous characters removed
        """
        # Remove path separators and dots to prevent traversal
        sanitized = re.sub(r'[/\\.]+', '_', component)
        # Limit length to prevent issues
        sanitized = sanitized[:200]
        # Ensure not empty
        if not sanitized:
            sanitized = "invalid"
        return sanitized

    def _get_artifact_path(self, tenant_id: str, root_task_id: str, artifact_id: UUID) -> Path:
        """Generate filesystem path for an artifact.
        
        SECURITY: Sanitizes tenant_id and root_task_id to prevent path traversal.
        """
        safe_tenant = self._sanitize_path_component(tenant_id)
        safe_task = self._sanitize_path_component(root_task_id)
        return self.base_path / safe_tenant / safe_task / str(artifact_id)

    def _location_to_path(self, location: str) -> Path:
        """Convert location string to filesystem path.
        
        SECURITY: Validates that resolved path stays within base_path.
        """
        if not location.startswith("fs://"):
            raise ValueError("Invalid location format, must start with fs://")
        
        relative_path = location[5:]
        path = (self.base_path / relative_path).resolve()
        
        # SECURITY: Verify resolved path is within base_path
        try:
            path.relative_to(self.base_path.resolve())
        except ValueError:
            raise ValueError(f"Path traversal attempt detected in location: {location}")
        
        return path

    def _path_to_location(self, path: Path) -> str:
        """Convert filesystem path to location string."""
        relative_path = path.relative_to(self.base_path)
        return f"fs://{relative_path}"

    async def store(
        self,
        artifact_id: UUID,
        tenant_id: str,
        root_task_id: str,
        content: bytes | AsyncIterator[bytes],
        mime_type: str,
    ) -> tuple[str, int, str]:
        """Store artifact content to filesystem."""
        path = self._get_artifact_path(tenant_id, root_task_id, artifact_id)

        # Ensure directory exists
        path.parent.mkdir(parents=True, exist_ok=True)

        hasher = hashlib.sha256()
        size = 0

        if isinstance(content, bytes):
            # Direct bytes
            hasher.update(content)
            size = len(content)

            # Check size limit
            max_size = settings.storage_max_artifact_bytes
            if max_size > 0 and size > max_size:
                raise ValueError(
                    f"Artifact size {size} bytes exceeds limit of {max_size} bytes"
                )

            async with aiofiles.open(path, "wb") as f:
                await f.write(content)
        else:
            # Streaming content
            max_size = settings.storage_max_artifact_bytes
            async with aiofiles.open(path, "wb") as f:
                async for chunk in content:
                    hasher.update(chunk)
                    size += len(chunk)

                    if max_size > 0 and size > max_size:
                        # Clean up partial file
                        await f.close()
                        await aiofiles.os.remove(path)
                        raise ValueError(
                            f"Artifact size exceeds limit of {max_size} bytes"
                        )

                    await f.write(chunk)

        content_hash = hasher.hexdigest()
        location = self._path_to_location(path)

        return location, size, content_hash

    async def retrieve(self, location: str) -> bytes:
        """Retrieve artifact content from filesystem."""
        path = self._location_to_path(location)

        if not path.exists():
            raise FileNotFoundError(f"Artifact not found at {location}")

        async with aiofiles.open(path, "rb") as f:
            return await f.read()

    async def retrieve_stream(self, location: str) -> AsyncIterator[bytes]:
        """Retrieve artifact content as a stream."""
        path = self._location_to_path(location)

        if not path.exists():
            raise FileNotFoundError(f"Artifact not found at {location}")

        chunk_size = 64 * 1024  # 64KB chunks
        async with aiofiles.open(path, "rb") as f:
            while True:
                chunk = await f.read(chunk_size)
                if not chunk:
                    break
                yield chunk

    async def delete(self, location: str) -> bool:
        """Delete artifact from filesystem."""
        path = self._location_to_path(location)

        if not path.exists():
            return False

        await aiofiles.os.remove(path)

        # Clean up empty parent directories
        try:
            parent = path.parent
            while parent != self.base_path:
                if not any(parent.iterdir()):
                    parent.rmdir()
                    parent = parent.parent
                else:
                    break
        except (OSError, ValueError):
            pass  # Directory not empty or permission issue

        return True

    async def exists(self, location: str) -> bool:
        """Check if artifact exists on filesystem."""
        path = self._location_to_path(location)
        return path.exists()

    async def get_size(self, location: str) -> int:
        """Get size of artifact on filesystem."""
        path = self._location_to_path(location)

        if not path.exists():
            raise FileNotFoundError(f"Artifact not found at {location}")

        stat = await aiofiles.os.stat(path)
        return stat.st_size
