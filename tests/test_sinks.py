"""Tests for outbound sinks."""

import json
import pytest
from pathlib import Path
from uuid import uuid4

from depotgate.core.models import ArtifactPointer, ArtifactRole, ShipmentManifest
from depotgate.sinks.filesystem import FilesystemSink
from depotgate.sinks.factory import get_sink, get_sink_for_destination, list_sinks


class TestFilesystemSink:
    """Tests for filesystem sink."""

    @pytest.fixture
    def sink(self, tmp_path: Path) -> FilesystemSink:
        """Create sink with temp directory."""
        return FilesystemSink(base_path=tmp_path)

    @pytest.fixture
    def sample_artifacts(self) -> list[ArtifactPointer]:
        """Create sample artifacts for testing."""
        return [
            ArtifactPointer(
                artifact_id=uuid4(),
                location="fs://test/artifact1",
                size_bytes=100,
                mime_type="application/json",
                content_hash="abc123",
                artifact_role=ArtifactRole.FINAL_OUTPUT,
                tenant_id="test",
                root_task_id="task-1",
            ),
            ArtifactPointer(
                artifact_id=uuid4(),
                location="fs://test/artifact2",
                size_bytes=200,
                mime_type="text/plain",
                content_hash="def456",
                artifact_role=ArtifactRole.SUPPORTING,
                tenant_id="test",
                root_task_id="task-1",
            ),
        ]

    @pytest.fixture
    def sample_manifest(self, sample_artifacts: list[ArtifactPointer]) -> ShipmentManifest:
        """Create sample shipment manifest."""
        return ShipmentManifest(
            deliverable_id=uuid4(),
            root_task_id="task-1",
            tenant_id="test",
            artifacts=sample_artifacts,
            destination="filesystem://output",
        )

    @pytest.mark.asyncio
    async def test_ship_artifacts(
        self,
        sink: FilesystemSink,
        sample_artifacts: list[ArtifactPointer],
        sample_manifest: ShipmentManifest,
        tmp_path: Path,
    ):
        """Test shipping artifacts to filesystem."""
        content_map = {
            sample_artifacts[0].artifact_id: b'{"test": "data"}',
            sample_artifacts[1].artifact_id: b"Plain text content",
        }

        async def get_content(artifact_id):
            return content_map[artifact_id]

        dest_refs = await sink.ship(
            artifacts=sample_artifacts,
            destination="output",
            manifest=sample_manifest,
            artifact_content_getter=get_content,
        )

        # Verify destination refs returned
        assert len(dest_refs) == 2
        for artifact in sample_artifacts:
            assert str(artifact.artifact_id) in dest_refs

        # Verify files exist
        shipment_dir = tmp_path / "output" / str(sample_manifest.manifest_id)
        assert shipment_dir.exists()

        # Verify manifest was written
        manifest_file = shipment_dir / "manifest.json"
        assert manifest_file.exists()
        manifest_data = json.loads(manifest_file.read_text())
        assert manifest_data["deliverable_id"] == str(sample_manifest.deliverable_id)

    @pytest.mark.asyncio
    async def test_validate_destination(self, sink: FilesystemSink, tmp_path: Path):
        """Test destination validation."""
        assert await sink.validate_destination("output") is True
        assert await sink.validate_destination(str(tmp_path / "new_dir")) is True


class TestSinkFactory:
    """Tests for sink factory."""

    def test_list_sinks(self):
        """Test listing available sinks."""
        sinks = list_sinks()
        assert "filesystem" in sinks
        assert "http" in sinks

    def test_get_sink(self):
        """Test getting sink by type."""
        fs_sink = get_sink("filesystem")
        assert fs_sink.sink_type == "filesystem"

        http_sink = get_sink("http")
        assert http_sink.sink_type == "http"

    def test_get_sink_unknown(self):
        """Test getting unknown sink type."""
        with pytest.raises(ValueError, match="Unknown sink type"):
            get_sink("unknown")

    def test_get_sink_for_destination(self):
        """Test parsing destination strings."""
        sink, path = get_sink_for_destination("filesystem://output/path")
        assert sink.sink_type == "filesystem"
        assert path == "output/path"

        sink, path = get_sink_for_destination("http://example.com/webhook")
        assert sink.sink_type == "http"
        assert path == "example.com/webhook"

        # Default to filesystem for unqualified paths
        sink, path = get_sink_for_destination("output/path")
        assert sink.sink_type == "filesystem"
        assert path == "output/path"
