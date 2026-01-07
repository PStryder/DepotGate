"""Filesystem outbound sink implementation."""

import shutil
from pathlib import Path
from typing import Any, Callable, Coroutine
from uuid import UUID

import aiofiles
import aiofiles.os

from depotgate.config import settings
from depotgate.core.models import ArtifactPointer, ShipmentManifest
from depotgate.sinks.base import OutboundSink


class FilesystemSink(OutboundSink):
    """Filesystem-based outbound sink."""

    def __init__(self, base_path: Path | None = None):
        """Initialize filesystem sink.

        Args:
            base_path: Base directory for shipped artifacts. Defaults to config.
        """
        self.base_path = base_path or settings.sink_filesystem_base_path

    @property
    def sink_type(self) -> str:
        return "filesystem"

    async def ship(
        self,
        artifacts: list[ArtifactPointer],
        destination: str,
        manifest: ShipmentManifest,
        artifact_content_getter: Callable[[UUID], Coroutine[Any, Any, bytes]],
    ) -> dict[str, str]:
        """Ship artifacts to filesystem destination."""
        # Parse destination - could be absolute or relative to base_path
        if destination.startswith("/"):
            dest_path = Path(destination)
        else:
            dest_path = self.base_path / destination

        # Create destination directory structure
        # Organize by manifest_id for traceability
        shipment_dir = dest_path / str(manifest.manifest_id)
        shipment_dir.mkdir(parents=True, exist_ok=True)

        destination_refs: dict[str, str] = {}

        for artifact in artifacts:
            # Determine filename - use artifact_id with extension based on mime_type
            extension = self._get_extension(artifact.mime_type)
            filename = f"{artifact.artifact_id}{extension}"
            file_path = shipment_dir / filename

            # Get and write content
            content = await artifact_content_getter(artifact.artifact_id)
            async with aiofiles.open(file_path, "wb") as f:
                await f.write(content)

            destination_refs[str(artifact.artifact_id)] = str(file_path)

        # Write manifest as JSON for reference
        manifest_path = shipment_dir / "manifest.json"
        async with aiofiles.open(manifest_path, "w") as f:
            await f.write(manifest.model_dump_json(indent=2))

        return destination_refs

    async def validate_destination(self, destination: str) -> bool:
        """Validate filesystem destination."""
        try:
            if destination.startswith("/"):
                dest_path = Path(destination)
            else:
                dest_path = self.base_path / destination

            # Check if we can create the directory (or it exists)
            dest_path.mkdir(parents=True, exist_ok=True)
            return True
        except (OSError, PermissionError):
            return False

    def _get_extension(self, mime_type: str) -> str:
        """Get file extension for a MIME type."""
        mime_map = {
            "application/json": ".json",
            "application/xml": ".xml",
            "application/pdf": ".pdf",
            "application/octet-stream": ".bin",
            "text/plain": ".txt",
            "text/html": ".html",
            "text/css": ".css",
            "text/javascript": ".js",
            "text/markdown": ".md",
            "image/png": ".png",
            "image/jpeg": ".jpg",
            "image/gif": ".gif",
            "image/svg+xml": ".svg",
        }
        return mime_map.get(mime_type, ".bin")
