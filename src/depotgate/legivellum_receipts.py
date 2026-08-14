"""Helpers for building LegiVellum receipt payloads for DepotGate events."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys
from typing import Any
from uuid import UUID, uuid4

from depotgate.config import settings
from depotgate.core.models import ArtifactPointer, ClosureRequirement, PurgePolicy, ShipmentManifest

try:
    from legivellum.models import Receipt as CanonicalReceipt
    from legivellum.models import generate_receipt_id
except ImportError:
    CanonicalReceipt = None
    generate_receipt_id = None
    # Walk every real ancestor rather than indexing fixed depths: in a container
    # the module sits too shallow for parents[4] and blind indexing raises
    # IndexError at import time, taking the whole service down.
    for parent in Path(__file__).resolve().parents:
        shared_root = parent / "LegiVellum" / "shared"
        if shared_root.exists():
            sys.path.append(str(shared_root))
            try:
                from legivellum.models import Receipt as CanonicalReceipt
                from legivellum.models import generate_receipt_id
            except ImportError:
                CanonicalReceipt = None
                generate_receipt_id = None
            break


def _new_receipt_id() -> str:
    if generate_receipt_id:
        return generate_receipt_id()
    return str(uuid4())


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc).isoformat()
    return dt.isoformat()


def _resolve_principal(metadata: dict[str, Any] | None) -> str:
    if isinstance(metadata, dict):
        for key in ("principal_ai", "principal", "owner", "recipient_ai", "from_principal"):
            value = metadata.get(key)
            if value:
                return str(value)
    return settings.default_recipient_ai or settings.service_principal_id


def _artifact_ref(pointer: ArtifactPointer) -> dict[str, Any]:
    return {
        "artifact_id": str(pointer.artifact_id),
        "uri": pointer.location,
        "size_bytes": pointer.size_bytes,
        "mime": pointer.mime_type,
        "checksum": pointer.content_hash or "NA",
        "role": pointer.artifact_role.value,
        "tenant_id": pointer.tenant_id,
        "root_task_id": pointer.root_task_id,
        "produced_by_receipt_id": pointer.produced_by_receipt_id,
    }


def _serialize_requirements(requirements: list[ClosureRequirement]) -> list[dict[str, Any]]:
    return [
        {
            "type": r.requirement_type.value,
            "value": r.value,
            "description": r.description,
        }
        for r in requirements
    ]


def _build_receipt(
    *,
    tenant_id: str,
    task_id: str,
    principal_ai: str,
    phase: str,
    status: str,
    task_type: str,
    task_summary: str,
    task_body: str,
    inputs: dict[str, Any],
    expected_outcome_kind: str,
    expected_artifact_mime: str,
    outcome_kind: str,
    outcome_text: str,
    artifact_location: str,
    artifact_pointer: str,
    artifact_checksum: str,
    artifact_size_bytes: int,
    artifact_mime: str,
    caused_by_receipt_id: str | None,
    dedupe_key: str,
    metadata: dict[str, Any],
    body: dict[str, Any],
    artifact_refs: list[dict[str, Any]],
    completed_at: datetime | None,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    payload = {
        "schema_version": "1.0",
        "tenant_id": tenant_id,
        "receipt_id": _new_receipt_id(),
        "task_id": task_id,
        "parent_task_id": "NA",
        "caused_by_receipt_id": caused_by_receipt_id or "NA",
        "dedupe_key": dedupe_key,
        "attempt": 0,
        "from_principal": principal_ai,
        "for_principal": principal_ai,
        "source_system": "depotgate",
        "recipient_ai": principal_ai,
        "trust_domain": "default",
        "phase": phase,
        "status": status,
        "realtime": False,
        "task_type": task_type,
        "task_summary": task_summary,
        "task_body": task_body,
        "inputs": inputs,
        "expected_outcome_kind": expected_outcome_kind,
        "expected_artifact_mime": expected_artifact_mime,
        "outcome_kind": outcome_kind,
        "outcome_text": outcome_text,
        "artifact_location": artifact_location,
        "artifact_pointer": artifact_pointer,
        "artifact_checksum": artifact_checksum,
        "artifact_size_bytes": artifact_size_bytes,
        "artifact_mime": artifact_mime,
        "escalation_class": "NA",
        "escalation_reason": "NA",
        "escalation_to": "NA",
        "retry_requested": False,
        "body": body,
        "artifact_refs": artifact_refs,
        "created_at": _iso(now),
        "stored_at": None,
        "started_at": None,
        "completed_at": _iso(completed_at),
        "read_at": None,
        "archived_at": None,
        "metadata": metadata,
    }

    if CanonicalReceipt is None:
        return payload

    return CanonicalReceipt.model_validate(payload).model_dump(mode="json")


def build_artifact_staged_receipt(
    *,
    tenant_id: str,
    root_task_id: str,
    artifact_pointer: ArtifactPointer,
    caused_by: str | None,
    metadata: dict[str, Any] | None,
) -> dict[str, Any]:
    principal_ai = _resolve_principal(metadata)
    inputs = {
        "root_task_id": root_task_id,
        "artifact_id": str(artifact_pointer.artifact_id),
        "artifact_role": artifact_pointer.artifact_role.value,
    }
    if artifact_pointer.produced_by_receipt_id:
        inputs["produced_by_receipt_id"] = artifact_pointer.produced_by_receipt_id

    receipt_metadata = {
        "artifact_id": str(artifact_pointer.artifact_id),
        "artifact_role": artifact_pointer.artifact_role.value,
        "root_task_id": root_task_id,
    }
    if metadata:
        receipt_metadata["client_metadata"] = metadata

    return _build_receipt(
        tenant_id=tenant_id,
        task_id=root_task_id,
        principal_ai=principal_ai,
        phase="complete",
        status="success",
        task_type="artifact_staging",
        task_summary=f"Artifact staged ({artifact_pointer.artifact_role.value})",
        task_body=f"Artifact {artifact_pointer.artifact_id} staged for task {root_task_id}",
        inputs=inputs,
        expected_outcome_kind="artifact_pointer",
        expected_artifact_mime=artifact_pointer.mime_type,
        outcome_kind="artifact_pointer",
        outcome_text="Artifact staged",
        artifact_location=settings.storage_backend,
        artifact_pointer=artifact_pointer.location,
        artifact_checksum=artifact_pointer.content_hash or "NA",
        artifact_size_bytes=artifact_pointer.size_bytes,
        artifact_mime=artifact_pointer.mime_type,
        caused_by_receipt_id=caused_by,
        dedupe_key=f"artifact:{artifact_pointer.artifact_id}",
        metadata=receipt_metadata,
        body={
            "event": "artifact_staged",
            "root_task_id": root_task_id,
            "artifact": _artifact_ref(artifact_pointer),
            "produced_by_receipt_id": artifact_pointer.produced_by_receipt_id,
            "metadata": metadata or {},
        },
        artifact_refs=[_artifact_ref(artifact_pointer)],
        completed_at=datetime.now(timezone.utc),
    )


def build_shipment_complete_receipt(
    *,
    tenant_id: str,
    root_task_id: str,
    manifest: ShipmentManifest,
    caused_by: str | None,
    metadata: dict[str, Any] | None,
) -> dict[str, Any]:
    principal_ai = _resolve_principal(metadata)
    artifact_ids = [str(a.artifact_id) for a in manifest.artifacts]
    truncated = len(artifact_ids) > 25
    receipt_metadata = {
        "deliverable_id": str(manifest.deliverable_id),
        "manifest_id": str(manifest.manifest_id),
        "destination": manifest.destination,
        "artifact_count": len(artifact_ids),
        "artifact_ids": artifact_ids[:25],
        "artifact_ids_truncated": truncated,
    }
    if metadata:
        receipt_metadata["client_metadata"] = metadata

    artifact_refs = [_artifact_ref(pointer) for pointer in manifest.artifacts]

    return _build_receipt(
        tenant_id=tenant_id,
        task_id=root_task_id,
        principal_ai=principal_ai,
        phase="complete",
        status="success",
        task_type="artifact_shipment",
        task_summary=f"Shipment complete ({len(artifact_ids)} artifacts)",
        task_body=(
            f"Deliverable {manifest.deliverable_id} shipped to {manifest.destination} "
            f"for task {root_task_id}"
        ),
        inputs={
            "deliverable_id": str(manifest.deliverable_id),
            "manifest_id": str(manifest.manifest_id),
            "destination": manifest.destination,
        },
        expected_outcome_kind="response_text",
        expected_artifact_mime="NA",
        outcome_kind="response_text",
        outcome_text="Shipment complete",
        artifact_location="NA",
        artifact_pointer="NA",
        artifact_checksum="NA",
        artifact_size_bytes=0,
        artifact_mime="NA",
        caused_by_receipt_id=caused_by,
        dedupe_key=f"shipment:{manifest.manifest_id}",
        metadata=receipt_metadata,
        body={
            "event": "shipment_complete",
            "root_task_id": root_task_id,
            "deliverable_id": str(manifest.deliverable_id),
            "manifest_id": str(manifest.manifest_id),
            "destination": manifest.destination,
            "artifact_count": len(manifest.artifacts),
            "destination_refs": manifest.destination_refs,
            "metadata": metadata or {},
        },
        artifact_refs=artifact_refs,
        completed_at=datetime.now(timezone.utc),
    )


def build_shipment_rejected_receipt(
    *,
    tenant_id: str,
    root_task_id: str,
    deliverable_id: UUID,
    unmet_requirements: list[ClosureRequirement],
    reason: str,
    caused_by: str | None,
    metadata: dict[str, Any] | None,
) -> dict[str, Any]:
    principal_ai = _resolve_principal(metadata)
    receipt_metadata = {
        "deliverable_id": str(deliverable_id),
        "unmet_requirements": _serialize_requirements(unmet_requirements),
    }
    if metadata:
        receipt_metadata["client_metadata"] = metadata

    return _build_receipt(
        tenant_id=tenant_id,
        task_id=root_task_id,
        principal_ai=principal_ai,
        phase="complete",
        status="failure",
        task_type="artifact_shipment",
        task_summary="Shipment rejected",
        task_body=f"Deliverable {deliverable_id} rejected for task {root_task_id}",
        inputs={
            "deliverable_id": str(deliverable_id),
            "root_task_id": root_task_id,
        },
        expected_outcome_kind="response_text",
        expected_artifact_mime="NA",
        outcome_kind="response_text",
        outcome_text=reason or "Shipment rejected",
        artifact_location="NA",
        artifact_pointer="NA",
        artifact_checksum="NA",
        artifact_size_bytes=0,
        artifact_mime="NA",
        caused_by_receipt_id=caused_by,
        dedupe_key=f"shipment_rejected:{deliverable_id}",
        metadata=receipt_metadata,
        body={
            "event": "shipment_rejected",
            "root_task_id": root_task_id,
            "deliverable_id": str(deliverable_id),
            "reason": reason or "Shipment rejected",
            "unmet_requirements": _serialize_requirements(unmet_requirements),
            "metadata": metadata or {},
        },
        artifact_refs=[],
        completed_at=datetime.now(timezone.utc),
    )


def build_purge_receipt(
    *,
    tenant_id: str,
    root_task_id: str,
    purged_artifact_ids: list[UUID],
    policy: PurgePolicy,
    caused_by: str | None,
    metadata: dict[str, Any] | None,
) -> dict[str, Any]:
    principal_ai = _resolve_principal(metadata)
    artifact_ids = [str(aid) for aid in purged_artifact_ids]
    truncated = len(artifact_ids) > 25
    receipt_metadata = {
        "purge_policy": policy.value,
        "purged_count": len(artifact_ids),
        "purged_artifact_ids": artifact_ids[:25],
        "artifact_ids_truncated": truncated,
    }
    if metadata:
        receipt_metadata["client_metadata"] = metadata

    return _build_receipt(
        tenant_id=tenant_id,
        task_id=root_task_id,
        principal_ai=principal_ai,
        phase="complete",
        status="success",
        task_type="artifact_purge",
        task_summary=f"Purged {len(artifact_ids)} artifacts",
        task_body=f"Artifacts purged for task {root_task_id}",
        inputs={
            "root_task_id": root_task_id,
            "purged_count": len(artifact_ids),
            "policy": policy.value,
        },
        expected_outcome_kind="response_text",
        expected_artifact_mime="NA",
        outcome_kind="response_text",
        outcome_text=f"Purged {len(artifact_ids)} artifacts",
        artifact_location="NA",
        artifact_pointer="NA",
        artifact_checksum="NA",
        artifact_size_bytes=0,
        artifact_mime="NA",
        caused_by_receipt_id=caused_by,
        dedupe_key=f"purge:{root_task_id}:{policy.value}:{len(artifact_ids)}",
        metadata=receipt_metadata,
        body={
            "event": "purged",
            "root_task_id": root_task_id,
            "purged_artifact_ids": artifact_ids,
            "purge_policy": policy.value,
            "metadata": metadata or {},
        },
        artifact_refs=[{"artifact_id": aid} for aid in artifact_ids],
        completed_at=datetime.now(timezone.utc),
    )
