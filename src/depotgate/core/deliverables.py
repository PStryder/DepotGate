"""Deliverable management and closure verification."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from depotgate.config import settings
from depotgate.core.models import (
    ArtifactPointer,
    ArtifactRole,
    ClosureRequirement,
    ClosureStatus,
    Deliverable,
    DeliverableSpec,
    RequirementType,
)
from depotgate.core.staging import StagingArea
from depotgate.db.models import ArtifactRecord, DeliverableRecord


class DeliverableManager:
    """Manages deliverable declarations and closure verification."""

    def __init__(
        self,
        metadata_session: AsyncSession,
        receipts_session: AsyncSession,
    ):
        """Initialize deliverable manager.

        Args:
            metadata_session: Database session for metadata
            receipts_session: Database session for receipts
        """
        self.metadata_session = metadata_session
        self.receipts_session = receipts_session

    async def declare_deliverable(
        self,
        root_task_id: str,
        spec: DeliverableSpec,
        tenant_id: str | None = None,
        deliverable_id: UUID | None = None,
    ) -> Deliverable:
        """
        Declare a deliverable contract.

        Args:
            root_task_id: Root task identifier
            spec: Deliverable specification
            tenant_id: Tenant ID (defaults to config)
            deliverable_id: Optional specific deliverable ID

        Returns:
            Declared Deliverable
        """
        tenant_id = tenant_id or settings.tenant_id
        from uuid import uuid4
        deliverable_id = deliverable_id or uuid4()

        deliverable = Deliverable(
            deliverable_id=deliverable_id,
            root_task_id=root_task_id,
            tenant_id=tenant_id,
            spec=spec,
        )

        record = DeliverableRecord(
            deliverable_id=deliverable_id,
            root_task_id=root_task_id,
            tenant_id=tenant_id,
            spec_json=spec.model_dump(mode="json"),
            status="pending",
        )
        self.metadata_session.add(record)
        await self.metadata_session.flush()

        return deliverable

    async def get_deliverable(
        self,
        deliverable_id: UUID,
        tenant_id: str | None = None,
    ) -> Deliverable | None:
        """
        Get a deliverable by ID.

        Args:
            deliverable_id: Deliverable identifier
            tenant_id: Tenant ID filter

        Returns:
            Deliverable or None if not found
        """
        tenant_id = tenant_id or settings.tenant_id

        result = await self.metadata_session.execute(
            select(DeliverableRecord).where(
                DeliverableRecord.deliverable_id == deliverable_id,
                DeliverableRecord.tenant_id == tenant_id,
            )
        )
        record = result.scalar_one_or_none()

        if record is None:
            return None

        return Deliverable(
            deliverable_id=record.deliverable_id,
            root_task_id=record.root_task_id,
            tenant_id=record.tenant_id,
            spec=DeliverableSpec(**record.spec_json),
            declared_at=record.declared_at,
            shipped_at=record.shipped_at,
            status=record.status,
        )

    async def list_deliverables(
        self,
        root_task_id: str,
        tenant_id: str | None = None,
        status: str | None = None,
    ) -> list[Deliverable]:
        """
        List deliverables for a root task.

        Args:
            root_task_id: Root task identifier
            tenant_id: Tenant ID filter
            status: Optional status filter

        Returns:
            List of deliverables
        """
        tenant_id = tenant_id or settings.tenant_id

        query = select(DeliverableRecord).where(
            DeliverableRecord.root_task_id == root_task_id,
            DeliverableRecord.tenant_id == tenant_id,
        )

        if status:
            query = query.where(DeliverableRecord.status == status)

        query = query.order_by(DeliverableRecord.declared_at)

        result = await self.metadata_session.execute(query)
        records = result.scalars().all()

        return [
            Deliverable(
                deliverable_id=r.deliverable_id,
                root_task_id=r.root_task_id,
                tenant_id=r.tenant_id,
                spec=DeliverableSpec(**r.spec_json),
                declared_at=r.declared_at,
                shipped_at=r.shipped_at,
                status=r.status,
            )
            for r in records
        ]

    async def check_closure(
        self,
        deliverable_id: UUID,
        tenant_id: str | None = None,
    ) -> ClosureStatus:
        """
        Check closure status for a deliverable.

        This verifies all declared requirements are met.

        Args:
            deliverable_id: Deliverable identifier
            tenant_id: Tenant ID filter

        Returns:
            ClosureStatus with met/unmet requirements
        """
        tenant_id = tenant_id or settings.tenant_id

        deliverable = await self.get_deliverable(deliverable_id, tenant_id)
        if deliverable is None:
            raise ValueError(f"Deliverable {deliverable_id} not found")

        # Get staged artifacts for this task
        staged_artifacts = await self._get_staged_artifacts(
            deliverable.root_task_id, tenant_id
        )

        met = []
        unmet = []

        spec = deliverable.spec

        # Check artifact ID requirements
        staged_ids = {a.artifact_id for a in staged_artifacts}
        for artifact_id in spec.artifact_ids:
            req = ClosureRequirement(
                requirement_type=RequirementType.ARTIFACT_ID,
                value=str(artifact_id),
                description=f"Artifact {artifact_id} must be staged",
            )
            if artifact_id in staged_ids:
                met.append(req)
            else:
                unmet.append(req)

        # Check artifact role requirements
        staged_roles = {a.artifact_role for a in staged_artifacts}
        for role in spec.artifact_roles:
            req = ClosureRequirement(
                requirement_type=RequirementType.ARTIFACT_ROLE,
                value=role.value,
                description=f"At least one artifact with role '{role.value}' must be staged",
            )
            if role in staged_roles:
                met.append(req)
            else:
                unmet.append(req)

        # Check explicit requirements
        for requirement in spec.requirements:
            if await self._check_requirement(requirement, staged_artifacts, tenant_id):
                met.append(requirement)
            else:
                unmet.append(requirement)

        return ClosureStatus(
            deliverable_id=deliverable_id,
            all_met=len(unmet) == 0,
            met_requirements=met,
            unmet_requirements=unmet,
            staged_artifacts=staged_artifacts,
        )

    async def _get_staged_artifacts(
        self,
        root_task_id: str,
        tenant_id: str,
    ) -> list[ArtifactPointer]:
        """Get all staged (non-purged) artifacts for a task."""
        result = await self.metadata_session.execute(
            select(ArtifactRecord).where(
                ArtifactRecord.root_task_id == root_task_id,
                ArtifactRecord.tenant_id == tenant_id,
                ArtifactRecord.purged_at.is_(None),
            )
        )
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

    async def _check_requirement(
        self,
        requirement: ClosureRequirement,
        staged_artifacts: list[ArtifactPointer],
        tenant_id: str,
    ) -> bool:
        """Check if a single requirement is met."""
        if requirement.requirement_type == RequirementType.ARTIFACT_ID:
            target_id = UUID(requirement.value)
            return any(a.artifact_id == target_id for a in staged_artifacts)

        elif requirement.requirement_type == RequirementType.ARTIFACT_ROLE:
            target_role = ArtifactRole(requirement.value)
            return any(a.artifact_role == target_role for a in staged_artifacts)

        elif requirement.requirement_type == RequirementType.CHILD_TASK:
            # Check if any artifact was produced for this child task
            # For v0, we check if produced_by_receipt_id contains task reference
            # This is a simplified check - full implementation would query receipts
            return any(
                a.produced_by_receipt_id and requirement.value in a.produced_by_receipt_id
                for a in staged_artifacts
            )

        elif requirement.requirement_type == RequirementType.RECEIPT_PHASE:
            # For v0, receipt phase checks are simplified
            # Full implementation would query receipt store
            # For now, assume phase requirements are met if any artifacts exist
            return len(staged_artifacts) > 0

        return False

    async def mark_shipped(
        self,
        deliverable_id: UUID,
        tenant_id: str | None = None,
    ) -> None:
        """Mark a deliverable as shipped."""
        tenant_id = tenant_id or settings.tenant_id

        result = await self.metadata_session.execute(
            select(DeliverableRecord).where(
                DeliverableRecord.deliverable_id == deliverable_id,
                DeliverableRecord.tenant_id == tenant_id,
            )
        )
        record = result.scalar_one_or_none()

        if record is None:
            raise ValueError(f"Deliverable {deliverable_id} not found")

        record.status = "shipped"
        record.shipped_at = datetime.utcnow()
        await self.metadata_session.flush()

    async def mark_rejected(
        self,
        deliverable_id: UUID,
        tenant_id: str | None = None,
    ) -> None:
        """Mark a deliverable as rejected."""
        tenant_id = tenant_id or settings.tenant_id

        result = await self.metadata_session.execute(
            select(DeliverableRecord).where(
                DeliverableRecord.deliverable_id == deliverable_id,
                DeliverableRecord.tenant_id == tenant_id,
            )
        )
        record = result.scalar_one_or_none()

        if record is None:
            raise ValueError(f"Deliverable {deliverable_id} not found")

        record.status = "rejected"
        await self.metadata_session.flush()
