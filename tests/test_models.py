"""Tests for data models."""

import pytest
from uuid import uuid4

from depotgate.core.models import (
    ArtifactPointer,
    ArtifactRole,
    ClosureRequirement,
    Deliverable,
    DeliverableSpec,
    PurgePolicy,
    Receipt,
    ReceiptType,
    RequirementType,
    ShipmentManifest,
)


class TestArtifactPointer:
    """Tests for ArtifactPointer model."""

    def test_create_artifact_pointer(self):
        """Test creating an artifact pointer."""
        pointer = ArtifactPointer(
            location="fs://test/artifact",
            size_bytes=1024,
            mime_type="application/json",
            content_hash="abc123def456",
            artifact_role=ArtifactRole.FINAL_OUTPUT,
            tenant_id="tenant-1",
            root_task_id="task-123",
        )

        assert pointer.artifact_id is not None
        assert pointer.location == "fs://test/artifact"
        assert pointer.size_bytes == 1024
        assert pointer.artifact_role == ArtifactRole.FINAL_OUTPUT

    def test_artifact_pointer_defaults(self):
        """Test artifact pointer default values."""
        pointer = ArtifactPointer(
            location="fs://test",
            size_bytes=100,
            mime_type="text/plain",
            tenant_id="default",
            root_task_id="task",
        )

        assert pointer.artifact_role == ArtifactRole.SUPPORTING
        assert pointer.content_hash is None
        assert pointer.produced_by_receipt_id is None


class TestDeliverableSpec:
    """Tests for DeliverableSpec model."""

    def test_create_spec_with_artifacts(self):
        """Test creating spec with artifact IDs."""
        artifact_id = uuid4()
        spec = DeliverableSpec(
            artifact_ids=[artifact_id],
            shipping_destination="filesystem://output",
        )

        assert artifact_id in spec.artifact_ids
        assert spec.shipping_destination == "filesystem://output"

    def test_create_spec_with_roles(self):
        """Test creating spec with artifact roles."""
        spec = DeliverableSpec(
            artifact_roles=[ArtifactRole.FINAL_OUTPUT, ArtifactRole.PLAN],
            shipping_destination="http://webhook.example.com",
        )

        assert ArtifactRole.FINAL_OUTPUT in spec.artifact_roles
        assert ArtifactRole.PLAN in spec.artifact_roles

    def test_create_spec_with_requirements(self):
        """Test creating spec with closure requirements."""
        req = ClosureRequirement(
            requirement_type=RequirementType.CHILD_TASK,
            value="child-task-123",
            description="Child task must complete",
        )
        spec = DeliverableSpec(
            requirements=[req],
            shipping_destination="filesystem://output",
        )

        assert len(spec.requirements) == 1
        assert spec.requirements[0].requirement_type == RequirementType.CHILD_TASK


class TestShipmentManifest:
    """Tests for ShipmentManifest model."""

    def test_create_manifest(self):
        """Test creating a shipment manifest."""
        artifact = ArtifactPointer(
            location="fs://test",
            size_bytes=100,
            mime_type="text/plain",
            tenant_id="test",
            root_task_id="task",
        )

        manifest = ShipmentManifest(
            deliverable_id=uuid4(),
            root_task_id="task-123",
            tenant_id="tenant-1",
            artifacts=[artifact],
            destination="filesystem://output",
        )

        assert manifest.manifest_id is not None
        assert len(manifest.artifacts) == 1
        assert manifest.shipped_at is not None


class TestReceipt:
    """Tests for Receipt model."""

    def test_create_receipt(self):
        """Test creating a receipt."""
        receipt = Receipt(
            receipt_type=ReceiptType.ARTIFACT_STAGED,
            tenant_id="tenant-1",
            root_task_id="task-123",
            payload={"artifact_id": "abc123"},
        )

        assert receipt.receipt_id is not None
        assert receipt.receipt_type == ReceiptType.ARTIFACT_STAGED
        assert receipt.timestamp is not None

    def test_receipt_causality(self):
        """Test receipt causality linkage."""
        parent_id = str(uuid4())
        receipt = Receipt(
            receipt_type=ReceiptType.SHIPMENT_COMPLETE,
            tenant_id="tenant",
            root_task_id="task",
            caused_by_receipt_id=parent_id,
        )

        assert receipt.caused_by_receipt_id == parent_id


class TestClosureRequirement:
    """Tests for ClosureRequirement model."""

    def test_requirement_types(self):
        """Test different requirement types."""
        child_req = ClosureRequirement(
            requirement_type=RequirementType.CHILD_TASK,
            value="child-123",
        )
        assert child_req.requirement_type == RequirementType.CHILD_TASK

        role_req = ClosureRequirement(
            requirement_type=RequirementType.ARTIFACT_ROLE,
            value="final_output",
        )
        assert role_req.requirement_type == RequirementType.ARTIFACT_ROLE

        artifact_req = ClosureRequirement(
            requirement_type=RequirementType.ARTIFACT_ID,
            value=str(uuid4()),
        )
        assert artifact_req.requirement_type == RequirementType.ARTIFACT_ID


class TestPurgePolicy:
    """Tests for PurgePolicy enum."""

    def test_purge_policies(self):
        """Test purge policy values."""
        assert PurgePolicy.IMMEDIATE.value == "immediate"
        assert PurgePolicy.RETAIN_24H.value == "retain_24h"
        assert PurgePolicy.RETAIN_7D.value == "retain_7d"
        assert PurgePolicy.MANUAL.value == "manual"
