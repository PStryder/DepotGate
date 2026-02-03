"""Tests for LegiVellum receipt builders."""

from uuid import uuid4

from depotgate.core.models import (
    ArtifactPointer,
    ArtifactRole,
    ClosureRequirement,
    PurgePolicy,
    RequirementType,
    ShipmentManifest,
)
from depotgate.legivellum_receipts import (
    build_artifact_staged_receipt,
    build_purge_receipt,
    build_shipment_complete_receipt,
    build_shipment_rejected_receipt,
)


def _sample_pointer(root_task_id: str) -> ArtifactPointer:
    return ArtifactPointer(
        location="fs://staging/sample",
        size_bytes=256,
        mime_type="text/plain",
        content_hash="abc123",
        artifact_role=ArtifactRole.FINAL_OUTPUT,
        tenant_id="default",
        root_task_id=root_task_id,
        produced_by_receipt_id="rec-123",
    )


def test_build_artifact_staged_receipt_includes_body_and_refs():
    pointer = _sample_pointer("task-1")
    payload = build_artifact_staged_receipt(
        tenant_id="default",
        root_task_id="task-1",
        artifact_pointer=pointer,
        caused_by="rec-123",
        metadata={"principal_ai": "user-1"},
    )

    assert payload["phase"] == "complete"
    assert payload["status"] == "success"
    assert payload["outcome_kind"] == "artifact_pointer"
    assert payload["body"]["event"] == "artifact_staged"
    assert payload["artifact_refs"]
    assert payload["artifact_refs"][0]["artifact_id"] == str(pointer.artifact_id)


def test_build_shipment_complete_receipt_includes_refs():
    pointer = _sample_pointer("task-2")
    manifest = ShipmentManifest(
        deliverable_id=uuid4(),
        root_task_id="task-2",
        tenant_id="default",
        artifacts=[pointer],
        destination="filesystem://output",
    )

    payload = build_shipment_complete_receipt(
        tenant_id="default",
        root_task_id="task-2",
        manifest=manifest,
        caused_by="rec-456",
        metadata={"principal_ai": "user-2"},
    )

    assert payload["phase"] == "complete"
    assert payload["status"] == "success"
    assert payload["body"]["event"] == "shipment_complete"
    assert len(payload["artifact_refs"]) == 1
    assert payload["artifact_refs"][0]["artifact_id"] == str(pointer.artifact_id)


def test_build_shipment_rejected_receipt_includes_unmet_requirements():
    requirement = ClosureRequirement(
        requirement_type=RequirementType.CHILD_TASK,
        value="child-task-1",
        description="Child task must complete",
    )

    payload = build_shipment_rejected_receipt(
        tenant_id="default",
        root_task_id="task-3",
        deliverable_id=uuid4(),
        unmet_requirements=[requirement],
        reason="Missing child task",
        caused_by="rec-789",
        metadata={"principal_ai": "user-3"},
    )

    assert payload["status"] == "failure"
    assert payload["body"]["event"] == "shipment_rejected"
    assert payload["body"]["unmet_requirements"]


def test_build_purge_receipt_includes_refs():
    artifact_ids = [uuid4(), uuid4()]
    payload = build_purge_receipt(
        tenant_id="default",
        root_task_id="task-4",
        purged_artifact_ids=artifact_ids,
        policy=PurgePolicy.IMMEDIATE,
        caused_by="rec-012",
        metadata={"principal_ai": "user-4"},
    )

    assert payload["body"]["event"] == "purged"
    assert len(payload["artifact_refs"]) == 2
