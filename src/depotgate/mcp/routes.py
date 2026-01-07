"""HTTP-based MCP (Model Context Protocol) interface for DepotGate.

This implements MCP over HTTP, allowing AI models/agents to interact with
DepotGate using the standard MCP tool-calling pattern.
"""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from depotgate.config import settings
from depotgate.core.deliverables import DeliverableManager
from depotgate.core.models import (
    ArtifactRole,
    DeliverableSpec,
    PurgePolicy,
)
from depotgate.core.shipping import ClosureNotMetError, ShippingError, ShippingService
from depotgate.core.staging import StagingArea
from depotgate.db.connection import metadata_session_dependency, receipts_session_dependency

router = APIRouter(prefix="/mcp", tags=["mcp"])


# MCP Request/Response Models


class MCPToolCall(BaseModel):
    """MCP tool call request."""

    tool: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class MCPToolResult(BaseModel):
    """MCP tool call result."""

    success: bool
    result: Any = None
    error: str | None = None


class MCPToolsListResponse(BaseModel):
    """Response listing available MCP tools."""

    tools: list[dict[str, Any]]


# Tool definitions for MCP
MCP_TOOLS = [
    {
        "name": "stage_artifact",
        "description": "Stage an artifact in DepotGate. Returns an artifact pointer.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "root_task_id": {
                    "type": "string",
                    "description": "Root task identifier",
                },
                "content_base64": {
                    "type": "string",
                    "description": "Base64-encoded artifact content",
                },
                "mime_type": {
                    "type": "string",
                    "description": "MIME type of the content",
                    "default": "application/octet-stream",
                },
                "artifact_role": {
                    "type": "string",
                    "enum": ["plan", "final_output", "supporting", "intermediate"],
                    "description": "Role classification for the artifact",
                    "default": "supporting",
                },
                "produced_by_receipt_id": {
                    "type": "string",
                    "description": "Receipt ID that produced this artifact (optional)",
                },
            },
            "required": ["root_task_id", "content_base64"],
        },
    },
    {
        "name": "list_staged_artifacts",
        "description": "List artifacts staged for a task.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "root_task_id": {
                    "type": "string",
                    "description": "Root task identifier",
                },
                "artifact_role": {
                    "type": "string",
                    "enum": ["plan", "final_output", "supporting", "intermediate"],
                    "description": "Filter by artifact role (optional)",
                },
            },
            "required": ["root_task_id"],
        },
    },
    {
        "name": "get_artifact",
        "description": "Get artifact metadata by ID.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "artifact_id": {
                    "type": "string",
                    "description": "Artifact UUID",
                },
            },
            "required": ["artifact_id"],
        },
    },
    {
        "name": "declare_deliverable",
        "description": "Declare a deliverable contract with requirements and shipping destination.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "root_task_id": {
                    "type": "string",
                    "description": "Root task identifier",
                },
                "artifact_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of artifact UUIDs to include",
                },
                "artifact_roles": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": ["plan", "final_output", "supporting", "intermediate"],
                    },
                    "description": "Artifact roles to include",
                },
                "shipping_destination": {
                    "type": "string",
                    "description": "Destination (e.g., 'filesystem://output' or 'http://...')",
                },
            },
            "required": ["root_task_id", "shipping_destination"],
        },
    },
    {
        "name": "check_closure",
        "description": "Check if closure requirements are met for a deliverable.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "deliverable_id": {
                    "type": "string",
                    "description": "Deliverable UUID",
                },
            },
            "required": ["deliverable_id"],
        },
    },
    {
        "name": "ship",
        "description": "Ship a deliverable. Verifies closure and transfers artifacts.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "root_task_id": {
                    "type": "string",
                    "description": "Root task identifier",
                },
                "deliverable_id": {
                    "type": "string",
                    "description": "Deliverable UUID",
                },
            },
            "required": ["root_task_id", "deliverable_id"],
        },
    },
    {
        "name": "purge",
        "description": "Purge staged artifacts.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "root_task_id": {
                    "type": "string",
                    "description": "Root task identifier",
                },
                "policy": {
                    "type": "string",
                    "enum": ["immediate", "retain_24h", "retain_7d", "manual"],
                    "description": "Purge policy",
                    "default": "immediate",
                },
                "artifact_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Specific artifact UUIDs to purge (optional, defaults to all)",
                },
            },
            "required": ["root_task_id"],
        },
    },
]


# Dependency helpers
async def get_staging_area(
    metadata_session: AsyncSession = Depends(metadata_session_dependency),
    receipts_session: AsyncSession = Depends(receipts_session_dependency),
) -> StagingArea:
    return StagingArea(metadata_session, receipts_session)


async def get_deliverable_manager(
    metadata_session: AsyncSession = Depends(metadata_session_dependency),
    receipts_session: AsyncSession = Depends(receipts_session_dependency),
) -> DeliverableManager:
    return DeliverableManager(metadata_session, receipts_session)


async def get_shipping_service(
    metadata_session: AsyncSession = Depends(metadata_session_dependency),
    receipts_session: AsyncSession = Depends(receipts_session_dependency),
) -> ShippingService:
    return ShippingService(metadata_session, receipts_session)


# MCP Endpoints


@router.get("/tools", response_model=MCPToolsListResponse)
async def list_tools():
    """List available MCP tools."""
    return MCPToolsListResponse(tools=MCP_TOOLS)


@router.post("/call", response_model=MCPToolResult)
async def call_tool(
    call: MCPToolCall,
    metadata_session: AsyncSession = Depends(metadata_session_dependency),
    receipts_session: AsyncSession = Depends(receipts_session_dependency),
):
    """
    Execute an MCP tool call.

    This is the main entry point for AI agents to interact with DepotGate.
    """
    staging = StagingArea(metadata_session, receipts_session)
    deliverables = DeliverableManager(metadata_session, receipts_session)
    shipping = ShippingService(metadata_session, receipts_session)

    try:
        if call.tool == "stage_artifact":
            return await _handle_stage_artifact(staging, call.arguments)

        elif call.tool == "list_staged_artifacts":
            return await _handle_list_staged(staging, call.arguments)

        elif call.tool == "get_artifact":
            return await _handle_get_artifact(staging, call.arguments)

        elif call.tool == "declare_deliverable":
            return await _handle_declare_deliverable(deliverables, call.arguments)

        elif call.tool == "check_closure":
            return await _handle_check_closure(deliverables, call.arguments)

        elif call.tool == "ship":
            return await _handle_ship(shipping, call.arguments)

        elif call.tool == "purge":
            return await _handle_purge(shipping, call.arguments)

        else:
            return MCPToolResult(
                success=False,
                error=f"Unknown tool: {call.tool}",
            )

    except Exception as e:
        return MCPToolResult(
            success=False,
            error=str(e),
        )


async def _handle_stage_artifact(
    staging: StagingArea,
    args: dict[str, Any],
) -> MCPToolResult:
    """Handle stage_artifact tool call."""
    import base64

    content = base64.b64decode(args["content_base64"])
    role = ArtifactRole(args.get("artifact_role", "supporting"))

    pointer = await staging.stage_artifact(
        root_task_id=args["root_task_id"],
        content=content,
        mime_type=args.get("mime_type", "application/octet-stream"),
        artifact_role=role,
        produced_by_receipt_id=args.get("produced_by_receipt_id"),
    )

    return MCPToolResult(
        success=True,
        result={
            "artifact_id": str(pointer.artifact_id),
            "location": pointer.location,
            "size_bytes": pointer.size_bytes,
            "content_hash": pointer.content_hash,
            "artifact_role": pointer.artifact_role.value,
        },
    )


async def _handle_list_staged(
    staging: StagingArea,
    args: dict[str, Any],
) -> MCPToolResult:
    """Handle list_staged_artifacts tool call."""
    role = None
    if "artifact_role" in args:
        role = ArtifactRole(args["artifact_role"])

    artifacts = await staging.list_artifacts(
        root_task_id=args["root_task_id"],
        artifact_role=role,
    )

    return MCPToolResult(
        success=True,
        result=[
            {
                "artifact_id": str(a.artifact_id),
                "size_bytes": a.size_bytes,
                "mime_type": a.mime_type,
                "artifact_role": a.artifact_role.value,
                "staged_at": a.staged_at.isoformat(),
            }
            for a in artifacts
        ],
    )


async def _handle_get_artifact(
    staging: StagingArea,
    args: dict[str, Any],
) -> MCPToolResult:
    """Handle get_artifact tool call."""
    artifact = await staging.get_artifact(UUID(args["artifact_id"]))

    if artifact is None:
        return MCPToolResult(
            success=False,
            error="Artifact not found",
        )

    return MCPToolResult(
        success=True,
        result={
            "artifact_id": str(artifact.artifact_id),
            "location": artifact.location,
            "size_bytes": artifact.size_bytes,
            "mime_type": artifact.mime_type,
            "content_hash": artifact.content_hash,
            "artifact_role": artifact.artifact_role.value,
            "root_task_id": artifact.root_task_id,
            "staged_at": artifact.staged_at.isoformat(),
        },
    )


async def _handle_declare_deliverable(
    manager: DeliverableManager,
    args: dict[str, Any],
) -> MCPToolResult:
    """Handle declare_deliverable tool call."""
    artifact_ids = [UUID(aid) for aid in args.get("artifact_ids", [])]
    artifact_roles = [ArtifactRole(r) for r in args.get("artifact_roles", [])]

    spec = DeliverableSpec(
        artifact_ids=artifact_ids,
        artifact_roles=artifact_roles,
        shipping_destination=args["shipping_destination"],
    )

    deliverable = await manager.declare_deliverable(
        root_task_id=args["root_task_id"],
        spec=spec,
    )

    return MCPToolResult(
        success=True,
        result={
            "deliverable_id": str(deliverable.deliverable_id),
            "root_task_id": deliverable.root_task_id,
            "status": deliverable.status,
            "declared_at": deliverable.declared_at.isoformat(),
        },
    )


async def _handle_check_closure(
    manager: DeliverableManager,
    args: dict[str, Any],
) -> MCPToolResult:
    """Handle check_closure tool call."""
    status = await manager.check_closure(UUID(args["deliverable_id"]))

    return MCPToolResult(
        success=True,
        result={
            "deliverable_id": str(status.deliverable_id),
            "all_met": status.all_met,
            "met_count": len(status.met_requirements),
            "unmet_count": len(status.unmet_requirements),
            "unmet_requirements": [
                {
                    "type": r.requirement_type.value,
                    "value": r.value,
                    "description": r.description,
                }
                for r in status.unmet_requirements
            ],
            "staged_artifact_count": len(status.staged_artifacts),
        },
    )


async def _handle_ship(
    service: ShippingService,
    args: dict[str, Any],
) -> MCPToolResult:
    """Handle ship tool call."""
    try:
        manifest = await service.ship(
            root_task_id=args["root_task_id"],
            deliverable_id=UUID(args["deliverable_id"]),
        )

        return MCPToolResult(
            success=True,
            result={
                "manifest_id": str(manifest.manifest_id),
                "deliverable_id": str(manifest.deliverable_id),
                "destination": manifest.destination,
                "artifact_count": len(manifest.artifacts),
                "shipped_at": manifest.shipped_at.isoformat(),
                "destination_refs": manifest.destination_refs,
            },
        )

    except ClosureNotMetError as e:
        return MCPToolResult(
            success=False,
            error="Closure requirements not met",
            result={
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
        return MCPToolResult(
            success=False,
            error=str(e),
        )


async def _handle_purge(
    service: ShippingService,
    args: dict[str, Any],
) -> MCPToolResult:
    """Handle purge tool call."""
    artifact_ids = None
    if "artifact_ids" in args:
        artifact_ids = [UUID(aid) for aid in args["artifact_ids"]]

    policy = PurgePolicy(args.get("policy", "immediate"))

    purged = await service.purge(
        root_task_id=args["root_task_id"],
        policy=policy,
        artifact_ids=artifact_ids,
    )

    return MCPToolResult(
        success=True,
        result={
            "purged_count": len(purged),
            "purged_artifact_ids": [str(aid) for aid in purged],
            "policy": policy.value,
        },
    )
