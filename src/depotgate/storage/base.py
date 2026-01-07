"""Abstract base class for storage backends."""

from abc import ABC, abstractmethod
from typing import AsyncIterator
from uuid import UUID

from depotgate.core.models import ArtifactPointer


class StorageBackend(ABC):
    """Abstract interface for artifact storage backends."""

    @abstractmethod
    async def store(
        self,
        artifact_id: UUID,
        tenant_id: str,
        root_task_id: str,
        content: bytes | AsyncIterator[bytes],
        mime_type: str,
    ) -> tuple[str, int, str]:
        """
        Store artifact content and return location info.

        Args:
            artifact_id: Unique artifact identifier
            tenant_id: Tenant identifier
            root_task_id: Root task identifier for organization
            content: Artifact content (bytes or async iterator for streaming)
            mime_type: MIME type of the content

        Returns:
            Tuple of (location, size_bytes, content_hash)
        """
        pass

    @abstractmethod
    async def retrieve(self, location: str) -> bytes:
        """
        Retrieve artifact content by location.

        Args:
            location: Storage location reference

        Returns:
            Artifact content as bytes
        """
        pass

    @abstractmethod
    async def retrieve_stream(self, location: str) -> AsyncIterator[bytes]:
        """
        Retrieve artifact content as a stream.

        Args:
            location: Storage location reference

        Yields:
            Chunks of artifact content
        """
        pass

    @abstractmethod
    async def delete(self, location: str) -> bool:
        """
        Delete artifact from storage.

        Args:
            location: Storage location reference

        Returns:
            True if deleted, False if not found
        """
        pass

    @abstractmethod
    async def exists(self, location: str) -> bool:
        """
        Check if artifact exists at location.

        Args:
            location: Storage location reference

        Returns:
            True if exists, False otherwise
        """
        pass

    @abstractmethod
    async def get_size(self, location: str) -> int:
        """
        Get size of artifact at location.

        Args:
            location: Storage location reference

        Returns:
            Size in bytes
        """
        pass
