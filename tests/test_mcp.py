"""Tests for MCP interface."""

import os

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

    # Every advertised tool must be namespaced: docs/canonical/mcp.naming.md
    # requires <service>.<verb>, and an unprefixed name in tools/list is what
    # a compatible client would copy.
    tool_names = [t["name"] for t in tools]
    assert "depotgate.stage_artifact" in tool_names
    assert "depotgate.list_staged_artifacts" in tool_names
    assert "depotgate.declare_deliverable" in tool_names
    assert "depotgate.check_closure" in tool_names
    assert "depotgate.ship" in tool_names
    assert "depotgate.purge" in tool_names
    assert all(name.startswith("depotgate.") for name in tool_names), tool_names


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


@pytest.mark.asyncio
async def test_legacy_unprefixed_tool_names_still_dispatch(async_client: AsyncClient):
    """Renaming the advertised tools must not break existing callers.

    InterView and the demo scripts still call the bare names; they are accepted
    but no longer advertised, so new clients learn the canonical form.
    """
    response = await async_client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "list_staged_artifacts", "arguments": {"root_task_id": "no-such-task"}},
        },
    )
    assert response.status_code == 200
    body = response.json()
    # Reaches the handler rather than falling through to "Unknown tool".
    assert "Unknown tool" not in str(body)


@pytest.mark.asyncio
async def test_unknown_tool_is_still_rejected(async_client: AsyncClient):
    response = await async_client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "definitely_not_a_tool", "arguments": {}},
        },
    )
    assert "Unknown tool" in str(response.json())


@pytest.mark.asyncio
@pytest.mark.skipif(
    not os.environ.get("DEPOTGATE_TEST_DATABASE"),
    reason="Set DEPOTGATE_TEST_DATABASE=1 with a provisioned database to run",
)
async def test_list_staged_artifacts_carries_location_and_hash(async_client: AsyncClient):
    """A listing that drops pointer and hash cannot support the artifact claim.

    stage_artifact returned location and content_hash while the listing did
    not, so InterView's artifact inventory showed nulls for both and could
    neither locate nor verify what it listed.
    """
    import base64

    staged = await async_client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {
                "name": "depotgate.stage_artifact",
                "arguments": {
                    "root_task_id": "list-fields-task",
                    "content_base64": base64.b64encode(b"hello").decode(),
                    "mime_type": "text/plain",
                    "artifact_role": "final_output",
                },
            },
        },
    )
    staged_result = staged.json()["result"]

    listed = await async_client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {
                "name": "depotgate.list_staged_artifacts",
                "arguments": {"root_task_id": "list-fields-task"},
            },
        },
    )
    entries = listed.json()["result"]
    assert entries, "expected the staged artifact to be listed"
    entry = entries[0]

    # The listing must agree with what staging reported.
    assert entry["location"] == staged_result["location"]
    assert entry["content_hash"] == staged_result["content_hash"]
    assert entry["content_hash"], "content_hash must not be empty"
    assert entry["size_bytes"] == staged_result["size_bytes"]
