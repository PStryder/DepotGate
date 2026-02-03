"""Tests for MCP interface."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_mcp_tools_list(async_client: AsyncClient):
    """Test listing MCP tools via JSON-RPC."""
    response = await async_client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "result" in data
    tools = data["result"]["tools"]

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
    response = await async_client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
    )
    data = response.json()

    for tool in data["result"]["tools"]:
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
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "unknown_tool", "arguments": {}},
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert "error" in data
    assert "Unknown tool" in data["error"]["message"]


# Note: These tests require database connectivity
@pytest.mark.asyncio
@pytest.mark.skip(reason="Requires database connection")
async def test_mcp_stage_artifact(async_client: AsyncClient):
    """Test staging artifact via MCP."""
    import base64

    content = base64.b64encode(b"Test content").decode()

    response = await async_client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "stage_artifact",
                "arguments": {
                    "root_task_id": "mcp-test-task",
                    "content_base64": content,
                    "mime_type": "text/plain",
                    "artifact_role": "supporting",
                },
            },
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert "result" in data
    assert "artifact_id" in data["result"]


@pytest.mark.asyncio
@pytest.mark.skip(reason="Requires database connection")
async def test_mcp_workflow(async_client: AsyncClient):
    """Test complete MCP workflow: stage -> declare -> ship."""
    import base64

    # 1. Stage artifact
    content = base64.b64encode(b'{"result": "test output"}').decode()
    stage_response = await async_client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "stage_artifact",
                "arguments": {
                    "root_task_id": "workflow-test",
                    "content_base64": content,
                    "mime_type": "application/json",
                    "artifact_role": "final_output",
                },
            },
        },
    )
    assert "result" in stage_response.json()
    artifact_id = stage_response.json()["result"]["artifact_id"]

    # 2. Declare deliverable
    declare_response = await async_client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "declare_deliverable",
                "arguments": {
                    "root_task_id": "workflow-test",
                    "artifact_ids": [artifact_id],
                    "shipping_destination": "filesystem://test-output",
                },
            },
        },
    )
    assert "result" in declare_response.json()
    deliverable_id = declare_response.json()["result"]["deliverable_id"]

    # 3. Check closure
    closure_response = await async_client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "check_closure",
                "arguments": {"deliverable_id": deliverable_id},
            },
        },
    )
    assert "result" in closure_response.json()
    assert closure_response.json()["result"]["all_met"] is True

    # 4. Ship
    ship_response = await async_client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {
                "name": "ship",
                "arguments": {
                    "root_task_id": "workflow-test",
                    "deliverable_id": deliverable_id,
                },
            },
        },
    )
    assert "result" in ship_response.json()
    assert "manifest_id" in ship_response.json()["result"]
