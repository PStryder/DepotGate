"""Emit LegiVellum receipts for DepotGate events."""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from depotgate.config import settings
from depotgate.core.models import ArtifactPointer, ClosureRequirement, PurgePolicy, ShipmentManifest
from depotgate.legivellum_receipts import (
    build_artifact_staged_receipt,
    build_purge_receipt,
    build_shipment_complete_receipt,
    build_shipment_rejected_receipt,
)
from depotgate.receiptgate_client import emit_receipt


logger = logging.getLogger(__name__)


async def emit_artifact_staged_receipt(
    *,
    tenant_id: str,
    root_task_id: str,
    artifact_pointer: ArtifactPointer,
    caused_by: str | None,
    metadata: dict[str, Any] | None,
) -> None:
    payload = build_artifact_staged_receipt(
        tenant_id=tenant_id,
        root_task_id=root_task_id,
        artifact_pointer=artifact_pointer,
        caused_by=caused_by,
        metadata=metadata,
    )
    await _emit(payload, event="artifact_staged", task_id=root_task_id)


async def emit_shipment_complete_receipt(
    *,
    tenant_id: str,
    root_task_id: str,
    manifest: ShipmentManifest,
    caused_by: str | None,
    metadata: dict[str, Any] | None,
) -> None:
    payload = build_shipment_complete_receipt(
        tenant_id=tenant_id,
        root_task_id=root_task_id,
        manifest=manifest,
        caused_by=caused_by,
        metadata=metadata,
    )
    await _emit(payload, event="shipment_complete", task_id=root_task_id)


async def emit_shipment_rejected_receipt(
    *,
    tenant_id: str,
    root_task_id: str,
    deliverable_id: UUID,
    unmet_requirements: list[ClosureRequirement],
    reason: str,
    caused_by: str | None,
    metadata: dict[str, Any] | None,
) -> None:
    payload = build_shipment_rejected_receipt(
        tenant_id=tenant_id,
        root_task_id=root_task_id,
        deliverable_id=deliverable_id,
        unmet_requirements=unmet_requirements,
        reason=reason,
        caused_by=caused_by,
        metadata=metadata,
    )
    await _emit(payload, event="shipment_rejected", task_id=root_task_id)


async def emit_purge_receipt(
    *,
    tenant_id: str,
    root_task_id: str,
    purged_artifact_ids: list[UUID],
    policy: PurgePolicy,
    caused_by: str | None,
    metadata: dict[str, Any] | None,
) -> None:
    payload = build_purge_receipt(
        tenant_id=tenant_id,
        root_task_id=root_task_id,
        purged_artifact_ids=purged_artifact_ids,
        policy=policy,
        caused_by=caused_by,
        metadata=metadata,
    )
    await _emit(payload, event="purged", task_id=root_task_id)


async def _emit(payload: dict[str, Any], *, event: str, task_id: str) -> None:
    if not settings.receiptgate_emit_receipts or not settings.receiptgate_endpoint:
        return
    receipt_id = payload.get("receipt_id")
    success = await emit_receipt(payload)
    if success:
        logger.info(
            "receiptgate_emit_success event=%s receipt_id=%s task_id=%s",
            event,
            receipt_id,
            task_id,
        )
    else:
        logger.warning(
            "receiptgate_emit_failed event=%s receipt_id=%s task_id=%s",
            event,
            receipt_id,
            task_id,
        )
