"""SQLAlchemy models for DepotGate database tables."""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import JSON, DateTime, Enum, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from depotgate.core.models import ArtifactRole, PurgePolicy, ReceiptType


class MetadataBase(DeclarativeBase):
    """Base class for metadata database models."""

    pass


class ReceiptsBase(DeclarativeBase):
    """Base class for receipts database models."""

    pass


# Metadata Database Models


class ArtifactRecord(MetadataBase):
    """Database record for staged artifacts."""

    __tablename__ = "artifacts"

    artifact_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    location: Mapped[str] = mapped_column(String(1024), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    mime_type: Mapped[str] = mapped_column(String(256), nullable=False)
    content_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    artifact_role: Mapped[str] = mapped_column(
        Enum(ArtifactRole), nullable=False, default=ArtifactRole.SUPPORTING
    )
    tenant_id: Mapped[str] = mapped_column(String(256), nullable=False, index=True)
    root_task_id: Mapped[str] = mapped_column(String(256), nullable=False, index=True)
    produced_by_receipt_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    staged_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    purged_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class DeliverableRecord(MetadataBase):
    """Database record for declared deliverables."""

    __tablename__ = "deliverables"

    deliverable_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    root_task_id: Mapped[str] = mapped_column(String(256), nullable=False, index=True)
    tenant_id: Mapped[str] = mapped_column(String(256), nullable=False, index=True)
    spec_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    declared_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    shipped_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(64), default="pending")


class ShipmentRecord(MetadataBase):
    """Database record for completed shipments."""

    __tablename__ = "shipments"

    manifest_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    deliverable_id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    root_task_id: Mapped[str] = mapped_column(String(256), nullable=False, index=True)
    tenant_id: Mapped[str] = mapped_column(String(256), nullable=False, index=True)
    destination: Mapped[str] = mapped_column(String(1024), nullable=False)
    shipped_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    manifest_json: Mapped[dict] = mapped_column(JSON, nullable=False)


# Receipts Database Models


class ReceiptRecord(ReceiptsBase):
    """Database record for receipts."""

    __tablename__ = "receipts"

    receipt_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    receipt_type: Mapped[str] = mapped_column(Enum(ReceiptType), nullable=False, index=True)
    tenant_id: Mapped[str] = mapped_column(String(256), nullable=False, index=True)
    root_task_id: Mapped[str] = mapped_column(String(256), nullable=False, index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    caused_by_receipt_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    payload_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
