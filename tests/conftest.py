"""Pytest configuration and fixtures for DepotGate tests."""

import asyncio
import os
import tempfile
from pathlib import Path
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Set test environment variables before importing app
os.environ["DEPOTGATE_STORAGE_BASE_PATH"] = tempfile.mkdtemp()
os.environ["DEPOTGATE_SINK_FILESYSTEM_BASE_PATH"] = tempfile.mkdtemp()
os.environ["DEPOTGATE_POSTGRES_HOST"] = "localhost"
os.environ["DEPOTGATE_POSTGRES_PORT"] = "5432"
os.environ["DEPOTGATE_POSTGRES_USER"] = "depotgate"
os.environ["DEPOTGATE_POSTGRES_PASSWORD"] = "depotgate"
os.environ["DEPOTGATE_POSTGRES_METADATA_DB"] = "depotgate_metadata_test"
os.environ["DEPOTGATE_POSTGRES_RECEIPTS_DB"] = "depotgate_receipts_test"

from depotgate.config import settings
from depotgate.db.models import MetadataBase, ReceiptsBase
from depotgate.main import app


@pytest.fixture(scope="session")
def event_loop():
    """Create event loop for async tests."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture
async def async_client() -> AsyncGenerator[AsyncClient, None]:
    """Create async HTTP client for testing."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.fixture
def temp_storage_path(tmp_path: Path) -> Path:
    """Create temporary storage directory."""
    storage_path = tmp_path / "staging"
    storage_path.mkdir(parents=True)
    return storage_path


@pytest.fixture
def temp_sink_path(tmp_path: Path) -> Path:
    """Create temporary sink directory."""
    sink_path = tmp_path / "shipped"
    sink_path.mkdir(parents=True)
    return sink_path


@pytest.fixture
def sample_artifact_content() -> bytes:
    """Sample artifact content for testing."""
    return b"Hello, DepotGate! This is test artifact content."


@pytest.fixture
def sample_json_content() -> bytes:
    """Sample JSON artifact content."""
    import json
    return json.dumps({"message": "test", "data": [1, 2, 3]}).encode()
