"""Tests for MCP interface."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_mcp_tools_list(async_client: AsyncClient):
    """Test listing MCP tools."""
    response = await async_client.get("/mcp/tools")
    assert response.status_code == 200
    data = response.json()
    assert "tools" in data
    tools = data["tools"]

    # Verify expected tools exist
    tool_names = [t["name"] for t in tools]
    assert "stage_artifact" in tool_names
    assert "list_staged_artifacts" in tool_names
    assert "declare_deliverable" in tool_names
    assert "check_closure" in tool_names
    assert "ship" in tool_names
    assert "purge" in tool_names


@pytest.mark.asyncio
async def test_mcp_tool_schemas(async_client: AsyncClient):
    """Test that MCP tools have valid input schemas."""
    response = await async_client.get("/mcp/tools")
    data = response.json()

    for tool in data["tools"]:
        assert "name" in tool
        assert "description" in tool
        assert "inputSchema" in tool
        schema = tool["inputSchema"]
        assert schema["type"] == "object"
        assert "properties" in schema


@pytest.mark.asyncio
async def test_mcp_unknown_tool(async_client: AsyncClient):
    """Test calling unknown MCP tool."""
    response = await async_client.post(
        "/mcp/call",
        json={
            "tool": "unknown_tool",
            "arguments": {},
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is False
    assert "Unknown tool" in data["error"]


# Note: These tests require database connectivity
@pytest.mark.asyncio
@pytest.mark.skip(reason="Requires database connection")
async def test_mcp_stage_artifact(async_client: AsyncClient):
    """Test staging artifact via MCP."""
    import base64

    content = base64.b64encode(b"Test content").decode()

    response = await async_client.post(
        "/mcp/call",
        json={
            "tool": "stage_artifact",
            "arguments": {
                "root_task_id": "mcp-test-task",
                "content_base64": content,
                "mime_type": "text/plain",
                "artifact_role": "supporting",
            },
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert "artifact_id" in data["result"]


@pytest.mark.asyncio
@pytest.mark.skip(reason="Requires database connection")
async def test_mcp_workflow(async_client: AsyncClient):
    """Test complete MCP workflow: stage -> declare -> ship."""
    import base64

    # 1. Stage artifact
    content = base64.b64encode(b'{"result": "test output"}').decode()
    stage_response = await async_client.post(
        "/mcp/call",
        json={
            "tool": "stage_artifact",
            "arguments": {
                "root_task_id": "workflow-test",
                "content_base64": content,
                "mime_type": "application/json",
                "artifact_role": "final_output",
            },
        },
    )
    assert stage_response.json()["success"] is True
    artifact_id = stage_response.json()["result"]["artifact_id"]

    # 2. Declare deliverable
    declare_response = await async_client.post(
        "/mcp/call",
        json={
            "tool": "declare_deliverable",
            "arguments": {
                "root_task_id": "workflow-test",
                "artifact_ids": [artifact_id],
                "shipping_destination": "filesystem://test-output",
            },
        },
    )
    assert declare_response.json()["success"] is True
    deliverable_id = declare_response.json()["result"]["deliverable_id"]

    # 3. Check closure
    closure_response = await async_client.post(
        "/mcp/call",
        json={
            "tool": "check_closure",
            "arguments": {
                "deliverable_id": deliverable_id,
            },
        },
    )
    assert closure_response.json()["success"] is True
    assert closure_response.json()["result"]["all_met"] is True

    # 4. Ship
    ship_response = await async_client.post(
        "/mcp/call",
        json={
            "tool": "ship",
            "arguments": {
                "root_task_id": "workflow-test",
                "deliverable_id": deliverable_id,
            },
        },
    )
    assert ship_response.json()["success"] is True
    assert "manifest_id" in ship_response.json()["result"]
