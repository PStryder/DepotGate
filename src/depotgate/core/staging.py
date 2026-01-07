"""Staging area management for artifacts."""

from datetime import datetime
from typing import AsyncIterator
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from depotgate.config import settings
from depotgate.core.models import ArtifactPointer, ArtifactRole
from depotgate.core.receipts import ReceiptStore
from depotgate.db.models import ArtifactRecord
from depotgate.storage.base import StorageBackend
from depotgate.storage.factory import get_storage_backend


class StagingArea:
    """Manages artifact staging operations."""

    def __init__(
        self,
        metadata_session: AsyncSession,
        receipts_session: AsyncSession,
        storage: StorageBackend | None = None,
    ):
        """Initialize staging area.

        Args:
            metadata_session: Database session for metadata
            receipts_session: Database session for receipts
            storage: Storage backend (defaults to configured backend)
        """
        self.metadata_session = metadata_session
        self.receipts_session = receipts_session
        self.storage = storage or get_storage_backend()
        self.receipt_store = ReceiptStore(receipts_session)

    async def stage_artifact(
        self,
        root_task_id: str,
        content: bytes | AsyncIterator[bytes],
        mime_type: str = "application/octet-stream",
        artifact_role: ArtifactRole = ArtifactRole.SUPPORTING,
        produced_by_receipt_id: str | None = None,
        tenant_id: str | None = None,
        artifact_id: UUID | None = None,
        metadata: dict | None = None,
    ) -> ArtifactPointer:
        """
        Stage an artifact and return its pointer.

        Args:
            root_task_id: Root task identifier
            content: Artifact content
            mime_type: MIME type
            artifact_role: Role classification
            produced_by_receipt_id: Receipt ID that produced this artifact
            tenant_id: Tenant ID (defaults to config)
            artifact_id: Optional specific artifact ID
            metadata: Optional metadata dict

        Returns:
            ArtifactPointer for the staged artifact
        """
        tenant_id = tenant_id or settings.tenant_id
        artifact_id = artifact_id or UUID(int=0).int  # Will be generated
        from uuid import uuid4
        artifact_id = artifact_id if isinstance(artifact_id, UUID) else uuid4()

        # Store in storage backend
        location, size_bytes, content_hash = await self.storage.store(
            artifact_id=artifact_id,
            tenant_id=tenant_id,
            root_task_id=root_task_id,
            content=content,
            mime_type=mime_type,
        )

        # Create pointer
        pointer = ArtifactPointer(
            artifact_id=artifact_id,
            location=location,
            size_bytes=size_bytes,
            mime_type=mime_type,
            content_hash=content_hash,
            artifact_role=artifact_role,
            tenant_id=tenant_id,
            root_task_id=root_task_id,
            produced_by_receipt_id=produced_by_receipt_id,
        )

        # Store in metadata database
        record = ArtifactRecord(
            artifact_id=artifact_id,
            location=location,
            size_bytes=size_bytes,
            mime_type=mime_type,
            content_hash=content_hash,
            artifact_role=artifact_role,
            tenant_id=tenant_id,
            root_task_id=root_task_id,
            produced_by_receipt_id=produced_by_receipt_id,
            metadata_json=metadata,
        )
        self.metadata_session.add(record)
        await self.metadata_session.flush()

        # Emit receipt
        await self.receipt_store.emit_artifact_staged(
            tenant_id=tenant_id,
            root_task_id=root_task_id,
            artifact_pointer=pointer,
            caused_by=produced_by_receipt_id,
        )

        return pointer

    async def list_artifacts(
        self,
        root_task_id: str,
        tenant_id: str | None = None,
        artifact_role: ArtifactRole | None = None,
        include_purged: bool = False,
    ) -> list[ArtifactPointer]:
        """
        List artifacts staged for a task.

        Args:
            root_task_id: Root task identifier
            tenant_id: Tenant ID filter
            artifact_role: Optional role filter
            include_purged: Include purged artifacts

        Returns:
            List of artifact pointers
        """
        tenant_id = tenant_id or settings.tenant_id

        query = select(ArtifactRecord).where(
            ArtifactRecord.root_task_id == root_task_id,
            ArtifactRecord.tenant_id == tenant_id,
        )

        if artifact_role:
            query = query.where(ArtifactRecord.artifact_role == artifact_role)

        if not include_purged:
            query = query.where(ArtifactRecord.purged_at.is_(None))

        query = query.order_by(ArtifactRecord.staged_at)

        result = await self.metadata_session.execute(query)
        records = result.scalars().all()

        return [
            ArtifactPointer(
                artifact_id=r.artifact_id,
                location=r.location,
                size_bytes=r.size_bytes,
                mime_type=r.mime_type,
                content_hash=r.content_hash,
                artifact_role=ArtifactRole(r.artifact_role),
                tenant_id=r.tenant_id,
                root_task_id=r.root_task_id,
                produced_by_receipt_id=r.produced_by_receipt_id,
                staged_at=r.staged_at,
            )
            for r in records
        ]

    async def get_artifact(
        self,
        artifact_id: UUID,
        tenant_id: str | None = None,
    ) -> ArtifactPointer | None:
        """
        Get a specific artifact by ID.

        Args:
            artifact_id: Artifact identifier
            tenant_id: Tenant ID filter

        Returns:
            ArtifactPointer or None if not found
        """
        tenant_id = tenant_id or settings.tenant_id

        query = select(ArtifactRecord).where(
            ArtifactRecord.artifact_id == artifact_id,
            ArtifactRecord.tenant_id == tenant_id,
            ArtifactRecord.purged_at.is_(None),
        )

        result = await self.metadata_session.execute(query)
        record = result.scalar_one_or_none()

        if record is None:
            return None

        return ArtifactPointer(
            artifact_id=record.artifact_id,
            location=record.location,
            size_bytes=record.size_bytes,
            mime_type=record.mime_type,
            content_hash=record.content_hash,
            artifact_role=ArtifactRole(record.artifact_role),
            tenant_id=record.tenant_id,
            root_task_id=record.root_task_id,
            produced_by_receipt_id=record.produced_by_receipt_id,
            staged_at=record.staged_at,
        )

    async def retrieve_content(self, artifact_id: UUID) -> bytes:
        """
        Retrieve artifact content by ID.

        Args:
            artifact_id: Artifact identifier

        Returns:
            Artifact content as bytes
        """
        pointer = await self.get_artifact(artifact_id)
        if pointer is None:
            raise ValueError(f"Artifact {artifact_id} not found")

        return await self.storage.retrieve(pointer.location)

    async def retrieve_content_stream(
        self, artifact_id: UUID
    ) -> AsyncIterator[bytes]:
        """
        Retrieve artifact content as stream.

        Args:
            artifact_id: Artifact identifier

        Yields:
            Chunks of artifact content
        """
        pointer = await self.get_artifact(artifact_id)
        if pointer is None:
            raise ValueError(f"Artifact {artifact_id} not found")

        async for chunk in self.storage.retrieve_stream(pointer.location):
            yield chunk

    async def mark_purged(
        self,
        artifact_ids: list[UUID],
        tenant_id: str | None = None,
    ) -> int:
        """
        Mark artifacts as purged (soft delete in metadata).

        Args:
            artifact_ids: List of artifact IDs to purge
            tenant_id: Tenant ID filter

        Returns:
            Number of artifacts marked
        """
        tenant_id = tenant_id or settings.tenant_id
        now = datetime.utcnow()
        count = 0

        for artifact_id in artifact_ids:
            result = await self.metadata_session.execute(
                select(ArtifactRecord).where(
                    ArtifactRecord.artifact_id == artifact_id,
                    ArtifactRecord.tenant_id == tenant_id,
                    ArtifactRecord.purged_at.is_(None),
                )
            )
            record = result.scalar_one_or_none()
            if record:
                record.purged_at = now
                count += 1

        await self.metadata_session.flush()
        return count

    async def delete_artifact_content(
        self,
        artifact_ids: list[UUID],
        tenant_id: str | None = None,
    ) -> int:
        """
        Delete artifact content from storage.

        Args:
            artifact_ids: List of artifact IDs to delete
            tenant_id: Tenant ID filter

        Returns:
            Number of artifacts deleted
        """
        tenant_id = tenant_id or settings.tenant_id
        count = 0

        for artifact_id in artifact_ids:
            pointer = await self.get_artifact(artifact_id, tenant_id)
            if pointer:
                deleted = await self.storage.delete(pointer.location)
                if deleted:
                    count += 1

        return count
