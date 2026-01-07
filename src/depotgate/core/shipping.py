"""Shipping and purge operations for DepotGate."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from depotgate.config import settings
from depotgate.core.deliverables import DeliverableManager
from depotgate.core.models import (
    ArtifactPointer,
    PurgePolicy,
    PurgeRequest,
    ShipmentManifest,
)
from depotgate.core.receipts import ReceiptStore
from depotgate.core.staging import StagingArea
from depotgate.db.models import ArtifactRecord, ShipmentRecord
from depotgate.sinks.factory import get_sink_for_destination
from depotgate.storage.factory import get_storage_backend


class ShippingError(Exception):
    """Error during shipping operation."""
    pass


class ClosureNotMetError(ShippingError):
    """Closure requirements not met."""

    def __init__(self, deliverable_id: UUID, unmet_requirements: list):
        self.deliverable_id = deliverable_id
        self.unmet_requirements = unmet_requirements
        super().__init__(
            f"Closure requirements not met for deliverable {deliverable_id}"
        )


class ShippingService:
    """Handles shipping and purge operations."""

    def __init__(
        self,
        metadata_session: AsyncSession,
        receipts_session: AsyncSession,
    ):
        """Initialize shipping service.

        Args:
            metadata_session: Database session for metadata
            receipts_session: Database session for receipts
        """
        self.metadata_session = metadata_session
        self.receipts_session = receipts_session
        self.staging = StagingArea(metadata_session, receipts_session)
        self.deliverables = DeliverableManager(metadata_session, receipts_session)
        self.receipt_store = ReceiptStore(receipts_session)
        self.storage = get_storage_backend()

    async def ship(
        self,
        root_task_id: str,
        deliverable_id: UUID,
        tenant_id: str | None = None,
    ) -> ShipmentManifest:
        """
        Ship a deliverable if closure conditions are met.

        Args:
            root_task_id: Root task identifier
            deliverable_id: Deliverable to ship
            tenant_id: Tenant ID (defaults to config)

        Returns:
            ShipmentManifest on success

        Raises:
            ClosureNotMetError: If closure requirements not met
            ShippingError: For other shipping failures
        """
        tenant_id = tenant_id or settings.tenant_id

        # Get deliverable
        deliverable = await self.deliverables.get_deliverable(deliverable_id, tenant_id)
        if deliverable is None:
            raise ShippingError(f"Deliverable {deliverable_id} not found")

        if deliverable.root_task_id != root_task_id:
            raise ShippingError(
                f"Deliverable {deliverable_id} does not belong to task {root_task_id}"
            )

        if deliverable.status == "shipped":
            raise ShippingError(f"Deliverable {deliverable_id} already shipped")

        # Check closure
        closure_status = await self.deliverables.check_closure(deliverable_id, tenant_id)

        if not closure_status.all_met:
            # Emit rejection receipt
            await self.receipt_store.emit_shipment_rejected(
                tenant_id=tenant_id,
                root_task_id=root_task_id,
                deliverable_id=deliverable_id,
                unmet_requirements=closure_status.unmet_requirements,
                reason="Closure requirements not met",
            )
            await self.deliverables.mark_rejected(deliverable_id, tenant_id)
            raise ClosureNotMetError(deliverable_id, closure_status.unmet_requirements)

        # Determine which artifacts to ship
        artifacts_to_ship = self._select_artifacts_for_shipment(
            deliverable.spec, closure_status.staged_artifacts
        )

        if not artifacts_to_ship:
            raise ShippingError("No artifacts to ship")

        # Get sink and destination
        destination = deliverable.spec.shipping_destination
        sink, dest_path = get_sink_for_destination(destination)

        # Validate destination
        if not await sink.validate_destination(dest_path):
            raise ShippingError(f"Invalid destination: {destination}")

        # Create manifest
        manifest = ShipmentManifest(
            deliverable_id=deliverable_id,
            root_task_id=root_task_id,
            tenant_id=tenant_id,
            artifacts=artifacts_to_ship,
            destination=destination,
        )

        # Ship artifacts
        async def get_content(artifact_id: UUID) -> bytes:
            return await self.staging.retrieve_content(artifact_id)

        destination_refs = await sink.ship(
            artifacts=artifacts_to_ship,
            destination=dest_path,
            manifest=manifest,
            artifact_content_getter=get_content,
        )
        manifest.destination_refs = destination_refs

        # Record shipment
        record = ShipmentRecord(
            manifest_id=manifest.manifest_id,
            deliverable_id=deliverable_id,
            root_task_id=root_task_id,
            tenant_id=tenant_id,
            destination=destination,
            manifest_json=manifest.model_dump(mode="json"),
        )
        self.metadata_session.add(record)
        await self.metadata_session.flush()

        # Mark deliverable as shipped
        await self.deliverables.mark_shipped(deliverable_id, tenant_id)

        # Emit completion receipt
        await self.receipt_store.emit_shipment_complete(
            tenant_id=tenant_id,
            root_task_id=root_task_id,
            manifest=manifest,
        )

        return manifest

    def _select_artifacts_for_shipment(
        self,
        spec,
        staged_artifacts: list[ArtifactPointer],
    ) -> list[ArtifactPointer]:
        """Select which artifacts to include in shipment."""
        selected = []
        selected_ids = set()

        # Include explicitly listed artifact IDs
        for artifact_id in spec.artifact_ids:
            for artifact in staged_artifacts:
                if artifact.artifact_id == artifact_id:
                    if artifact.artifact_id not in selected_ids:
                        selected.append(artifact)
                        selected_ids.add(artifact.artifact_id)
                    break

        # Include artifacts matching required roles
        for role in spec.artifact_roles:
            for artifact in staged_artifacts:
                if artifact.artifact_role == role:
                    if artifact.artifact_id not in selected_ids:
                        selected.append(artifact)
                        selected_ids.add(artifact.artifact_id)

        # If no explicit selection, include all staged artifacts
        if not selected and not spec.artifact_ids and not spec.artifact_roles:
            selected = staged_artifacts

        return selected

    async def purge(
        self,
        root_task_id: str,
        policy: PurgePolicy = PurgePolicy.IMMEDIATE,
        artifact_ids: list[UUID] | None = None,
        tenant_id: str | None = None,
    ) -> list[UUID]:
        """
        Purge staged artifacts.

        Args:
            root_task_id: Root task identifier
            policy: Retention policy
            artifact_ids: Specific artifacts to purge (None = all for task)
            tenant_id: Tenant ID (defaults to config)

        Returns:
            List of purged artifact IDs
        """
        tenant_id = tenant_id or settings.tenant_id

        # Get artifacts to purge
        if artifact_ids:
            artifacts = []
            for aid in artifact_ids:
                artifact = await self.staging.get_artifact(aid, tenant_id)
                if artifact and artifact.root_task_id == root_task_id:
                    artifacts.append(artifact)
        else:
            artifacts = await self.staging.list_artifacts(root_task_id, tenant_id)

        if not artifacts:
            return []

        purged_ids = [a.artifact_id for a in artifacts]

        if policy == PurgePolicy.IMMEDIATE:
            # Delete content from storage
            await self.staging.delete_artifact_content(purged_ids, tenant_id)
            # Mark as purged in metadata
            await self.staging.mark_purged(purged_ids, tenant_id)

        elif policy in (PurgePolicy.RETAIN_24H, PurgePolicy.RETAIN_7D):
            # Just mark as purged (content cleanup would be done by scheduled job)
            await self.staging.mark_purged(purged_ids, tenant_id)

        elif policy == PurgePolicy.MANUAL:
            # Mark as purged but don't delete
            await self.staging.mark_purged(purged_ids, tenant_id)

        # Emit purge receipt
        await self.receipt_store.emit_purged(
            tenant_id=tenant_id,
            root_task_id=root_task_id,
            purged_artifact_ids=purged_ids,
            policy=policy,
        )

        return purged_ids

    async def get_shipment(
        self,
        manifest_id: UUID,
        tenant_id: str | None = None,
    ) -> ShipmentManifest | None:
        """Get a shipment manifest by ID."""
        tenant_id = tenant_id or settings.tenant_id

        result = await self.metadata_session.execute(
            select(ShipmentRecord).where(
                ShipmentRecord.manifest_id == manifest_id,
                ShipmentRecord.tenant_id == tenant_id,
            )
        )
        record = result.scalar_one_or_none()

        if record is None:
            return None

        return ShipmentManifest(**record.manifest_json)

    async def list_shipments(
        self,
        root_task_id: str,
        tenant_id: str | None = None,
    ) -> list[ShipmentManifest]:
        """List shipments for a root task."""
        tenant_id = tenant_id or settings.tenant_id

        result = await self.metadata_session.execute(
            select(ShipmentRecord).where(
                ShipmentRecord.root_task_id == root_task_id,
                ShipmentRecord.tenant_id == tenant_id,
            ).order_by(ShipmentRecord.shipped_at)
        )
        records = result.scalars().all()

        return [ShipmentManifest(**r.manifest_json) for r in records]
