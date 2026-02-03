"""Tests for MCP JSON-RPC surface."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_tool(async_client: AsyncClient):
    """Health tool should return service info via MCP."""
    response = await async_client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "depotgate.health", "arguments": {}},
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert "result" in payload
    data = payload["result"]
    assert data["status"] == "healthy"
    assert data["service"] == "DepotGate"
    assert "version" in data


# Note: The following tests would require database connectivity
# They are provided as examples but may need adjustment based on test infrastructure

@pytest.mark.asyncio
@pytest.mark.skip(reason="Requires database connection")
async def test_stage_artifact(async_client: AsyncClient, sample_artifact_content: bytes):
    """Test staging an artifact via MCP."""
    import base64

    response = await async_client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 10,
            "method": "tools/call",
            "params": {
                "name": "stage_artifact",
                "arguments": {
                    "root_task_id": "test-task-123",
                    "content_base64": base64.b64encode(sample_artifact_content).decode(),
                    "mime_type": "text/plain",
                    "artifact_role": "supporting",
                },
            },
        },
    )
    assert response.status_code == 200
    data = response.json()["result"]
    assert "artifact_id" in data
    assert "location" in data
    assert data["size_bytes"] == len(sample_artifact_content)


@pytest.mark.asyncio
@pytest.mark.skip(reason="Requires database connection")
async def test_list_staged_artifacts(async_client: AsyncClient):
    """Test listing staged artifacts via MCP."""
    response = await async_client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 11,
            "method": "tools/call",
            "params": {
                "name": "list_staged_artifacts",
                "arguments": {"root_task_id": "test-task-123"},
            },
        },
    )
    assert response.status_code == 200
    data = response.json()["result"]
    assert isinstance(data, list)


@pytest.mark.asyncio
@pytest.mark.skip(reason="Requires database connection")
async def test_declare_deliverable(async_client: AsyncClient):
    """Test declaring a deliverable via MCP."""
    response = await async_client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 12,
            "method": "tools/call",
            "params": {
                "name": "declare_deliverable",
                "arguments": {
                    "root_task_id": "test-task-123",
                    "artifact_roles": ["final_output"],
                    "shipping_destination": "filesystem://output",
                },
            },
        },
    )
    assert response.status_code == 200
    data = response.json()["result"]
    assert "deliverable_id" in data
    assert data["status"] == "pending"


@pytest.mark.asyncio
@pytest.mark.skip(reason="Requires database connection")
async def test_check_closure(async_client: AsyncClient):
    """Test checking closure status via MCP."""
    # First create a deliverable
    create_response = await async_client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 13,
            "method": "tools/call",
            "params": {
                "name": "declare_deliverable",
                "arguments": {
                    "root_task_id": "test-task-456",
                    "shipping_destination": "filesystem://output",
                },
            },
        },
    )
    deliverable_id = create_response.json()["result"]["deliverable_id"]

    # Check closure
    response = await async_client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 14,
            "method": "tools/call",
            "params": {
                "name": "check_closure",
                "arguments": {"deliverable_id": deliverable_id},
            },
        },
    )
    assert response.status_code == 200
    data = response.json()["result"]
    assert "all_met" in data
    assert "unmet_requirements" in data
