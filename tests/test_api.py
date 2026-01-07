"""Tests for FastAPI routes.

Note: These tests require a running PostgreSQL database.
For CI/CD, use the docker-compose setup or mock the database.
"""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_check(async_client: AsyncClient):
    """Test health check endpoint."""
    response = await async_client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"


@pytest.mark.asyncio
async def test_service_info(async_client: AsyncClient):
    """Test service info endpoint."""
    response = await async_client.get("/api/v1/info")
    assert response.status_code == 200
    data = response.json()
    assert "version" in data
    assert "storage_backend" in data
    assert "available_sinks" in data


@pytest.mark.asyncio
async def test_root_endpoint(async_client: AsyncClient):
    """Test root endpoint."""
    response = await async_client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["service"] == "DepotGate"
    assert "docs" in data
    assert "api" in data
    assert "mcp" in data


# Note: The following tests would require database connectivity
# They are provided as examples but may need adjustment based on test infrastructure

@pytest.mark.asyncio
@pytest.mark.skip(reason="Requires database connection")
async def test_stage_artifact(async_client: AsyncClient, sample_artifact_content: bytes):
    """Test staging an artifact."""
    response = await async_client.post(
        "/api/v1/stage",
        files={"file": ("test.txt", sample_artifact_content, "text/plain")},
        data={
            "root_task_id": "test-task-123",
            "artifact_role": "supporting",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert "artifact_id" in data
    assert "location" in data
    assert data["size_bytes"] == len(sample_artifact_content)


@pytest.mark.asyncio
@pytest.mark.skip(reason="Requires database connection")
async def test_list_staged_artifacts(async_client: AsyncClient):
    """Test listing staged artifacts."""
    response = await async_client.get(
        "/api/v1/stage/list",
        params={"root_task_id": "test-task-123"},
    )
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)


@pytest.mark.asyncio
@pytest.mark.skip(reason="Requires database connection")
async def test_declare_deliverable(async_client: AsyncClient):
    """Test declaring a deliverable."""
    response = await async_client.post(
        "/api/v1/deliverables",
        json={
            "root_task_id": "test-task-123",
            "spec": {
                "artifact_roles": ["final_output"],
                "shipping_destination": "filesystem://output",
            },
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert "deliverable_id" in data
    assert data["status"] == "pending"


@pytest.mark.asyncio
@pytest.mark.skip(reason="Requires database connection")
async def test_check_closure(async_client: AsyncClient):
    """Test checking closure status."""
    # First create a deliverable
    create_response = await async_client.post(
        "/api/v1/deliverables",
        json={
            "root_task_id": "test-task-456",
            "spec": {
                "shipping_destination": "filesystem://output",
            },
        },
    )
    deliverable_id = create_response.json()["deliverable_id"]

    # Check closure
    response = await async_client.get(f"/api/v1/deliverables/{deliverable_id}/closure")
    assert response.status_code == 200
    data = response.json()
    assert "all_met" in data
    assert "unmet_requirements" in data
