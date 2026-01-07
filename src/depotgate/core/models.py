"""Pydantic models for DepotGate domain objects."""

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class ArtifactRole(str, Enum):
    """Role classification for artifacts."""

    PLAN = "plan"
    FINAL_OUTPUT = "final_output"
    SUPPORTING = "supporting"
    INTERMEDIATE = "intermediate"


class ArtifactPointer(BaseModel):
    """Content-opaque reference to a staged artifact."""

    artifact_id: UUID = Field(default_factory=uuid4)
    location: str  # Storage-agnostic location reference
    size_bytes: int
    mime_type: str
    content_hash: str | None = None  # SHA-256 recommended
    artifact_role: ArtifactRole = ArtifactRole.SUPPORTING
    tenant_id: str
    root_task_id: str
    produced_by_receipt_id: str | None = None
    staged_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        from_attributes = True


class RequirementType(str, Enum):
    """Types of closure requirements."""

    CHILD_TASK = "child_task"
    ARTIFACT_ROLE = "artifact_role"
    ARTIFACT_ID = "artifact_id"
    RECEIPT_PHASE = "receipt_phase"


class ClosureRequirement(BaseModel):
    """A single closure requirement for a deliverable."""

    requirement_type: RequirementType
    value: str  # Task ID, artifact role, artifact ID, or phase name
    description: str | None = None


class DeliverableSpec(BaseModel):
    """Specification for a deliverable contract."""

    artifact_ids: list[UUID] = Field(default_factory=list)
    artifact_roles: list[ArtifactRole] = Field(default_factory=list)
    requirements: list[ClosureRequirement] = Field(default_factory=list)
    shipping_destination: str  # Sink identifier + destination
    metadata: dict[str, Any] = Field(default_factory=dict)


class Deliverable(BaseModel):
    """A declared deliverable with its contract."""

    deliverable_id: UUID = Field(default_factory=uuid4)
    root_task_id: str
    tenant_id: str
    spec: DeliverableSpec
    declared_at: datetime = Field(default_factory=datetime.utcnow)
    shipped_at: datetime | None = None
    status: str = "pending"  # pending, shipped, rejected

    class Config:
        from_attributes = True


class ShipmentManifest(BaseModel):
    """Manifest for a completed shipment."""

    manifest_id: UUID = Field(default_factory=uuid4)
    deliverable_id: UUID
    root_task_id: str
    tenant_id: str
    artifacts: list[ArtifactPointer]
    destination: str
    shipped_at: datetime = Field(default_factory=datetime.utcnow)
    destination_refs: dict[str, str] = Field(default_factory=dict)  # artifact_id -> dest location


class PurgePolicy(str, Enum):
    """Retention/purge policy options."""

    IMMEDIATE = "immediate"  # Delete immediately after shipment
    RETAIN_24H = "retain_24h"  # Keep for 24 hours
    RETAIN_7D = "retain_7d"  # Keep for 7 days
    MANUAL = "manual"  # Never auto-delete


class PurgeRequest(BaseModel):
    """Request to purge staged artifacts."""

    root_task_id: str
    policy: PurgePolicy = PurgePolicy.IMMEDIATE
    artifact_ids: list[UUID] | None = None  # None = all for this root_task_id


# Receipt Types

class ReceiptType(str, Enum):
    """Types of receipts emitted by DepotGate."""

    ARTIFACT_STAGED = "artifact_staged"
    SHIPMENT_REJECTED = "shipment_rejected"
    SHIPMENT_COMPLETE = "shipment_complete"
    PURGED = "purged"


class Receipt(BaseModel):
    """Base receipt model for DepotGate events."""

    receipt_id: UUID = Field(default_factory=uuid4)
    receipt_type: ReceiptType
    tenant_id: str
    root_task_id: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    caused_by_receipt_id: str | None = None  # Causality linkage
    payload: dict[str, Any] = Field(default_factory=dict)

    class Config:
        from_attributes = True


class ArtifactStagedReceipt(Receipt):
    """Receipt for artifact staging."""

    receipt_type: ReceiptType = ReceiptType.ARTIFACT_STAGED
    artifact_pointer: ArtifactPointer | None = None


class ShipmentRejectedReceipt(Receipt):
    """Receipt for rejected shipment."""

    receipt_type: ReceiptType = ReceiptType.SHIPMENT_REJECTED
    deliverable_id: UUID | None = None
    unmet_requirements: list[ClosureRequirement] = Field(default_factory=list)
    reason: str = ""


class ShipmentCompleteReceipt(Receipt):
    """Receipt for completed shipment."""

    receipt_type: ReceiptType = ReceiptType.SHIPMENT_COMPLETE
    manifest: ShipmentManifest | None = None


class PurgedReceipt(Receipt):
    """Receipt for purge operation."""

    receipt_type: ReceiptType = ReceiptType.PURGED
    purged_artifact_ids: list[UUID] = Field(default_factory=list)
    policy: PurgePolicy = PurgePolicy.IMMEDIATE


# API Request/Response Models

class StageArtifactRequest(BaseModel):
    """Request to stage an artifact."""

    root_task_id: str
    mime_type: str = "application/octet-stream"
    artifact_role: ArtifactRole = ArtifactRole.SUPPORTING
    produced_by_receipt_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class DeclareDeliverableRequest(BaseModel):
    """Request to declare a deliverable."""

    root_task_id: str
    spec: DeliverableSpec


class ShipRequest(BaseModel):
    """Request to ship a deliverable."""

    root_task_id: str
    deliverable_id: UUID


class ClosureStatus(BaseModel):
    """Status of closure requirements for a deliverable."""

    deliverable_id: UUID
    all_met: bool
    met_requirements: list[ClosureRequirement] = Field(default_factory=list)
    unmet_requirements: list[ClosureRequirement] = Field(default_factory=list)
    staged_artifacts: list[ArtifactPointer] = Field(default_factory=list)
