"""Tests for storage backend."""

import pytest
from pathlib import Path
from uuid import uuid4

from depotgate.storage.filesystem import FilesystemStorageBackend


class TestFilesystemStorageBackend:
    """Tests for filesystem storage backend."""

    @pytest.fixture
    def storage(self, tmp_path: Path) -> FilesystemStorageBackend:
        """Create storage backend with temp directory."""
        return FilesystemStorageBackend(base_path=tmp_path)

    @pytest.mark.asyncio
    async def test_store_and_retrieve(
        self,
        storage: FilesystemStorageBackend,
        sample_artifact_content: bytes,
    ):
        """Test storing and retrieving an artifact."""
        artifact_id = uuid4()
        tenant_id = "test-tenant"
        root_task_id = "test-task-123"

        # Store
        location, size, content_hash = await storage.store(
            artifact_id=artifact_id,
            tenant_id=tenant_id,
            root_task_id=root_task_id,
            content=sample_artifact_content,
            mime_type="text/plain",
        )

        assert location.startswith("fs://")
        assert size == len(sample_artifact_content)
        assert content_hash is not None
        assert len(content_hash) == 64  # SHA-256 hex

        # Retrieve
        retrieved = await storage.retrieve(location)
        assert retrieved == sample_artifact_content

    @pytest.mark.asyncio
    async def test_exists(
        self,
        storage: FilesystemStorageBackend,
        sample_artifact_content: bytes,
    ):
        """Test checking artifact existence."""
        artifact_id = uuid4()

        location, _, _ = await storage.store(
            artifact_id=artifact_id,
            tenant_id="test",
            root_task_id="task",
            content=sample_artifact_content,
            mime_type="application/octet-stream",
        )

        assert await storage.exists(location) is True
        assert await storage.exists("fs://nonexistent") is False

    @pytest.mark.asyncio
    async def test_delete(
        self,
        storage: FilesystemStorageBackend,
        sample_artifact_content: bytes,
    ):
        """Test deleting an artifact."""
        artifact_id = uuid4()

        location, _, _ = await storage.store(
            artifact_id=artifact_id,
            tenant_id="test",
            root_task_id="task",
            content=sample_artifact_content,
            mime_type="application/octet-stream",
        )

        assert await storage.exists(location) is True
        assert await storage.delete(location) is True
        assert await storage.exists(location) is False
        assert await storage.delete(location) is False  # Already deleted

    @pytest.mark.asyncio
    async def test_get_size(
        self,
        storage: FilesystemStorageBackend,
        sample_artifact_content: bytes,
    ):
        """Test getting artifact size."""
        artifact_id = uuid4()

        location, _, _ = await storage.store(
            artifact_id=artifact_id,
            tenant_id="test",
            root_task_id="task",
            content=sample_artifact_content,
            mime_type="application/octet-stream",
        )

        size = await storage.get_size(location)
        assert size == len(sample_artifact_content)

    @pytest.mark.asyncio
    async def test_retrieve_stream(
        self,
        storage: FilesystemStorageBackend,
        sample_artifact_content: bytes,
    ):
        """Test streaming retrieval."""
        artifact_id = uuid4()

        location, _, _ = await storage.store(
            artifact_id=artifact_id,
            tenant_id="test",
            root_task_id="task",
            content=sample_artifact_content,
            mime_type="application/octet-stream",
        )

        chunks = []
        async for chunk in storage.retrieve_stream(location):
            chunks.append(chunk)

        assert b"".join(chunks) == sample_artifact_content
