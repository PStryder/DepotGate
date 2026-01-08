"""FastAPI routes for DepotGate API."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from depotgate.config import settings
from depotgate.core.deliverables import DeliverableManager
from depotgate.core.models import (
    ArtifactPointer,
    ArtifactRole,
    ClosureStatus,
    DeclareDeliverableRequest,
    Deliverable,
    DeliverableSpec,
    PurgePolicy,
    PurgeRequest,
    Receipt,
    ShipmentManifest,
    ShipRequest,
    StageArtifactRequest,
    HealthResponse,
)
from depotgate.core.receipts import ReceiptStore
from depotgate.core.shipping import ClosureNotMetError, ShippingError, ShippingService
from depotgate.core.staging import StagingArea
from depotgate.db.connection import metadata_session_dependency, receipts_session_dependency
from depotgate.auth import verify_api_key
from depotgate.middleware import get_rate_limiter

router = APIRouter(
    prefix="/api/v1", 
    tags=["depotgate"],
    dependencies=[Depends(verify_api_key), Depends(rate_limit_dependency)]
)


# Rate limiting dependency
async def rate_limit_dependency(request: Request) -> None:
    """Rate limiting dependency."""
    limiter = get_rate_limiter(
        calls_per_minute=settings.rate_limit_requests_per_minute,
        enabled=settings.rate_limit_enabled
    )
    await limiter.check_request(request)


# Dependency injection helpers
async def get_staging_area(
    metadata_session: Annotated[AsyncSession, Depends(metadata_session_dependency)],
    receipts_session: Annotated[AsyncSession, Depends(receipts_session_dependency)],
) -> StagingArea:
    return StagingArea(metadata_session, receipts_session)


async def get_deliverable_manager(
    metadata_session: Annotated[AsyncSession, Depends(metadata_session_dependency)],
    receipts_session: Annotated[AsyncSession, Depends(receipts_session_dependency)],
) -> DeliverableManager:
    return DeliverableManager(metadata_session, receipts_session)


async def get_shipping_service(
    metadata_session: Annotated[AsyncSession, Depends(metadata_session_dependency)],
    receipts_session: Annotated[AsyncSession, Depends(receipts_session_dependency)],
) -> ShippingService:
    return ShippingService(metadata_session, receipts_session)


async def get_receipt_store(
    receipts_session: Annotated[AsyncSession, Depends(receipts_session_dependency)],
) -> ReceiptStore:
    return ReceiptStore(receipts_session)


# ============================================================================
# Staging Endpoints
# ============================================================================


@router.post("/stage", response_model=ArtifactPointer)
async def stage_artifact(
    file: UploadFile = File(...),
    root_task_id: str = Form(...),
    artifact_role: ArtifactRole = Form(ArtifactRole.SUPPORTING),
    produced_by_receipt_id: str | None = Form(None),
    staging: StagingArea = Depends(get_staging_area),
):
    """
    Stage an artifact.

    Upload a file to the staging area. Returns an artifact pointer.
    """
    try:
        content = await file.read()
        mime_type = file.content_type or "application/octet-stream"

        pointer = await staging.stage_artifact(
            root_task_id=root_task_id,
            content=content,
            mime_type=mime_type,
            artifact_role=artifact_role,
            produced_by_receipt_id=produced_by_receipt_id,
        )
        return pointer
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/stage/bytes", response_model=ArtifactPointer, dependencies=[Depends(verify_api_key)])
async def stage_artifact_bytes(
    request: StageArtifactRequest,
    content: bytes = File(...),
    staging: StagingArea = Depends(get_staging_area),
):
    """
    Stage an artifact from raw bytes.

    Alternative endpoint for programmatic uploads.
    """
    try:
        pointer = await staging.stage_artifact(
            root_task_id=request.root_task_id,
            content=content,
            mime_type=request.mime_type,
            artifact_role=request.artifact_role,
            produced_by_receipt_id=request.produced_by_receipt_id,
            metadata=request.metadata,
        )
        return pointer
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/stage/list", response_model=list[ArtifactPointer], dependencies=[Depends(verify_api_key)])
async def list_staged_artifacts(
    root_task_id: str = Query(...),
    artifact_role: ArtifactRole | None = Query(None),
    staging: StagingArea = Depends(get_staging_area),
):
    """
    List artifacts staged for a task.
    """
    return await staging.list_artifacts(
        root_task_id=root_task_id,
        artifact_role=artifact_role,
    )


@router.get("/stage/{artifact_id}", response_model=ArtifactPointer, dependencies=[Depends(verify_api_key)])
async def get_artifact(
    artifact_id: UUID,
    staging: StagingArea = Depends(get_staging_area),
):
    """
    Get artifact metadata by ID.
    """
    pointer = await staging.get_artifact(artifact_id)
    if pointer is None:
        raise HTTPException(status_code=404, detail="Artifact not found")
    return pointer


@router.get("/stage/{artifact_id}/content", dependencies=[Depends(verify_api_key)])
async def get_artifact_content(
    artifact_id: UUID,
    staging: StagingArea = Depends(get_staging_area),
):
    """
    Download artifact content.
    """
    pointer = await staging.get_artifact(artifact_id)
    if pointer is None:
        raise HTTPException(status_code=404, detail="Artifact not found")

    async def content_stream():
        async for chunk in staging.retrieve_content_stream(artifact_id):
            yield chunk

    return StreamingResponse(
        content_stream(),
        media_type=pointer.mime_type,
        headers={
            "Content-Disposition": f'attachment; filename="{artifact_id}"',
            "Content-Length": str(pointer.size_bytes),
        },
    )


# ============================================================================
# Deliverable Endpoints
# ============================================================================


@router.post("/deliverables", response_model=Deliverable, dependencies=[Depends(verify_api_key)])
async def declare_deliverable(
    request: DeclareDeliverableRequest,
    manager: DeliverableManager = Depends(get_deliverable_manager),
):
    """
    Declare a deliverable contract.

    Registers a deliverable with its requirements and shipping destination.
    """
    return await manager.declare_deliverable(
        root_task_id=request.root_task_id,
        spec=request.spec,
    )


@router.get("/deliverables", response_model=list[Deliverable], dependencies=[Depends(verify_api_key)])
async def list_deliverables(
    root_task_id: str = Query(...),
    status: str | None = Query(None),
    manager: DeliverableManager = Depends(get_deliverable_manager),
):
    """
    List deliverables for a task.
    """
    return await manager.list_deliverables(
        root_task_id=root_task_id,
        status=status,
    )


@router.get("/deliverables/{deliverable_id}", response_model=Deliverable, dependencies=[Depends(verify_api_key)])
async def get_deliverable(
    deliverable_id: UUID,
    manager: DeliverableManager = Depends(get_deliverable_manager),
):
    """
    Get a deliverable by ID.
    """
    deliverable = await manager.get_deliverable(deliverable_id)
    if deliverable is None:
        raise HTTPException(status_code=404, detail="Deliverable not found")
    return deliverable


@router.get("/deliverables/{deliverable_id}/closure", response_model=ClosureStatus, dependencies=[Depends(verify_api_key)])
async def check_closure(
    deliverable_id: UUID,
    manager: DeliverableManager = Depends(get_deliverable_manager),
):
    """
    Check closure status for a deliverable.

    Returns which requirements are met/unmet.
    """
    try:
        return await manager.check_closure(deliverable_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ============================================================================
# Shipping Endpoints
# ============================================================================


@router.post("/ship", response_model=ShipmentManifest, dependencies=[Depends(verify_api_key)])
async def ship_deliverable(
    request: ShipRequest,
    shipping: ShippingService = Depends(get_shipping_service),
):
    """
    Ship a deliverable.

    Verifies closure and transfers artifacts to the destination.
    Returns a shipment manifest on success.
    """
    try:
        return await shipping.ship(
            root_task_id=request.root_task_id,
            deliverable_id=request.deliverable_id,
        )
    except ClosureNotMetError as e:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "closure_not_met",
                "deliverable_id": str(e.deliverable_id),
                "unmet_requirements": [
                    {
                        "type": r.requirement_type.value,
                        "value": r.value,
                        "description": r.description,
                    }
                    for r in e.unmet_requirements
                ],
            },
        )
    except ShippingError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/shipments", response_model=list[ShipmentManifest], dependencies=[Depends(verify_api_key)])
async def list_shipments(
    root_task_id: str = Query(...),
    shipping: ShippingService = Depends(get_shipping_service),
):
    """
    List shipments for a task.
    """
    return await shipping.list_shipments(root_task_id=root_task_id)


@router.get("/shipments/{manifest_id}", response_model=ShipmentManifest, dependencies=[Depends(verify_api_key)])
async def get_shipment(
    manifest_id: UUID,
    shipping: ShippingService = Depends(get_shipping_service),
):
    """
    Get a shipment manifest by ID.
    """
    manifest = await shipping.get_shipment(manifest_id)
    if manifest is None:
        raise HTTPException(status_code=404, detail="Shipment not found")
    return manifest


# ============================================================================
# Purge Endpoints
# ============================================================================


@router.post("/purge", response_model=list[str], dependencies=[Depends(verify_api_key)])
async def purge_artifacts(
    request: PurgeRequest,
    shipping: ShippingService = Depends(get_shipping_service),
):
    """
    Purge staged artifacts.

    Cleans up artifacts according to the specified policy.
    """
    purged_ids = await shipping.purge(
        root_task_id=request.root_task_id,
        policy=request.policy,
        artifact_ids=request.artifact_ids,
    )
    return [str(aid) for aid in purged_ids]


# ============================================================================
# Receipt Endpoints
# ============================================================================


@router.get("/receipts", response_model=list[Receipt], dependencies=[Depends(verify_api_key)])
async def list_receipts(
    root_task_id: str | None = Query(None),
    receipt_type: str | None = Query(None),
    limit: int = Query(100, le=1000),
    store: ReceiptStore = Depends(get_receipt_store),
):
    """
    List receipts with optional filters.
    """
    from depotgate.core.models import ReceiptType

    rt = None
    if receipt_type:
        try:
            rt = ReceiptType(receipt_type)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid receipt type: {receipt_type}")

    return await store.list_receipts(
        tenant_id=settings.tenant_id,
        root_task_id=root_task_id,
        receipt_type=rt,
        limit=limit,
    )


@router.get("/receipts/{receipt_id}", response_model=Receipt, dependencies=[Depends(verify_api_key)])
async def get_receipt(
    receipt_id: UUID,
    store: ReceiptStore = Depends(get_receipt_store),
):
    """
    Get a receipt by ID.
    """
    receipt = await store.get_receipt(receipt_id)
    if receipt is None:
        raise HTTPException(status_code=404, detail="Receipt not found")
    return receipt


# ============================================================================
# Health & Info Endpoints
# ============================================================================


@router.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint."""
    return HealthResponse(
        status="healthy",
        service="DepotGate",
        version="0.1.0",
        instance_id=settings.instance_id
    )


@router.get("/info")
async def service_info():
    """Service information."""
    from depotgate import __version__
    from depotgate.sinks.factory import list_sinks
    from depotgate.storage.factory import list_storage_backends

    return {
        "service": settings.service_name,
        "version": __version__,
        "tenant_id": settings.tenant_id,
        "storage_backend": settings.storage_backend,
        "available_storage_backends": list_storage_backends(),
        "enabled_sinks": settings.get_enabled_sinks(),
        "available_sinks": list_sinks(),
    }
