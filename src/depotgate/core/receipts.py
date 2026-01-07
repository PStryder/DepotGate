"""Receipt store for DepotGate events."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from depotgate.core.models import (
    ArtifactPointer,
    ArtifactStagedReceipt,
    ClosureRequirement,
    PurgePolicy,
    PurgedReceipt,
    Receipt,
    ReceiptType,
    ShipmentCompleteReceipt,
    ShipmentManifest,
    ShipmentRejectedReceipt,
)
from depotgate.db.models import ReceiptRecord


class ReceiptStore:
    """Store and retrieve receipts from PostgreSQL."""

    def __init__(self, session: AsyncSession):
        """Initialize with database session."""
        self.session = session

    async def store_receipt(self, receipt: Receipt) -> Receipt:
        """Store a receipt and return it with updated fields."""
        record = ReceiptRecord(
            receipt_id=receipt.receipt_id,
            receipt_type=receipt.receipt_type,
            tenant_id=receipt.tenant_id,
            root_task_id=receipt.root_task_id,
            timestamp=receipt.timestamp,
            caused_by_receipt_id=receipt.caused_by_receipt_id,
            payload_json=receipt.payload,
        )
        self.session.add(record)
        await self.session.flush()
        return receipt

    async def get_receipt(self, receipt_id: UUID) -> Receipt | None:
        """Retrieve a receipt by ID."""
        result = await self.session.execute(
            select(ReceiptRecord).where(ReceiptRecord.receipt_id == receipt_id)
        )
        record = result.scalar_one_or_none()

        if record is None:
            return None

        return Receipt(
            receipt_id=record.receipt_id,
            receipt_type=ReceiptType(record.receipt_type),
            tenant_id=record.tenant_id,
            root_task_id=record.root_task_id,
            timestamp=record.timestamp,
            caused_by_receipt_id=record.caused_by_receipt_id,
            payload=record.payload_json,
        )

    async def list_receipts(
        self,
        tenant_id: str | None = None,
        root_task_id: str | None = None,
        receipt_type: ReceiptType | None = None,
        since: datetime | None = None,
        limit: int = 100,
    ) -> list[Receipt]:
        """List receipts with optional filters."""
        query = select(ReceiptRecord)

        if tenant_id:
            query = query.where(ReceiptRecord.tenant_id == tenant_id)
        if root_task_id:
            query = query.where(ReceiptRecord.root_task_id == root_task_id)
        if receipt_type:
            query = query.where(ReceiptRecord.receipt_type == receipt_type)
        if since:
            query = query.where(ReceiptRecord.timestamp >= since)

        query = query.order_by(ReceiptRecord.timestamp.desc()).limit(limit)

        result = await self.session.execute(query)
        records = result.scalars().all()

        return [
            Receipt(
                receipt_id=r.receipt_id,
                receipt_type=ReceiptType(r.receipt_type),
                tenant_id=r.tenant_id,
                root_task_id=r.root_task_id,
                timestamp=r.timestamp,
                caused_by_receipt_id=r.caused_by_receipt_id,
                payload=r.payload_json,
            )
            for r in records
        ]

    # Convenience methods for specific receipt types

    async def emit_artifact_staged(
        self,
        tenant_id: str,
        root_task_id: str,
        artifact_pointer: ArtifactPointer,
        caused_by: str | None = None,
    ) -> ArtifactStagedReceipt:
        """Emit an artifact_staged receipt."""
        receipt = ArtifactStagedReceipt(
            tenant_id=tenant_id,
            root_task_id=root_task_id,
            caused_by_receipt_id=caused_by,
            artifact_pointer=artifact_pointer,
            payload={
                "artifact_id": str(artifact_pointer.artifact_id),
                "location": artifact_pointer.location,
                "size_bytes": artifact_pointer.size_bytes,
                "mime_type": artifact_pointer.mime_type,
                "content_hash": artifact_pointer.content_hash,
                "artifact_role": artifact_pointer.artifact_role.value,
            },
        )
        await self.store_receipt(receipt)
        return receipt

    async def emit_shipment_rejected(
        self,
        tenant_id: str,
        root_task_id: str,
        deliverable_id: UUID,
        unmet_requirements: list[ClosureRequirement],
        reason: str,
        caused_by: str | None = None,
    ) -> ShipmentRejectedReceipt:
        """Emit a shipment_rejected receipt."""
        receipt = ShipmentRejectedReceipt(
            tenant_id=tenant_id,
            root_task_id=root_task_id,
            caused_by_receipt_id=caused_by,
            deliverable_id=deliverable_id,
            unmet_requirements=unmet_requirements,
            reason=reason,
            payload={
                "deliverable_id": str(deliverable_id),
                "reason": reason,
                "unmet_requirements": [
                    {
                        "type": r.requirement_type.value,
                        "value": r.value,
                        "description": r.description,
                    }
                    for r in unmet_requirements
                ],
            },
        )
        await self.store_receipt(receipt)
        return receipt

    async def emit_shipment_complete(
        self,
        tenant_id: str,
        root_task_id: str,
        manifest: ShipmentManifest,
        caused_by: str | None = None,
    ) -> ShipmentCompleteReceipt:
        """Emit a shipment_complete receipt."""
        receipt = ShipmentCompleteReceipt(
            tenant_id=tenant_id,
            root_task_id=root_task_id,
            caused_by_receipt_id=caused_by,
            manifest=manifest,
            payload={
                "manifest_id": str(manifest.manifest_id),
                "deliverable_id": str(manifest.deliverable_id),
                "destination": manifest.destination,
                "artifact_count": len(manifest.artifacts),
                "artifact_ids": [str(a.artifact_id) for a in manifest.artifacts],
                "destination_refs": manifest.destination_refs,
            },
        )
        await self.store_receipt(receipt)
        return receipt

    async def emit_purged(
        self,
        tenant_id: str,
        root_task_id: str,
        purged_artifact_ids: list[UUID],
        policy: PurgePolicy,
        caused_by: str | None = None,
    ) -> PurgedReceipt:
        """Emit a purged receipt."""
        receipt = PurgedReceipt(
            tenant_id=tenant_id,
            root_task_id=root_task_id,
            caused_by_receipt_id=caused_by,
            purged_artifact_ids=purged_artifact_ids,
            policy=policy,
            payload={
                "purged_artifact_ids": [str(aid) for aid in purged_artifact_ids],
                "policy": policy.value,
                "count": len(purged_artifact_ids),
            },
        )
        await self.store_receipt(receipt)
        return receipt
