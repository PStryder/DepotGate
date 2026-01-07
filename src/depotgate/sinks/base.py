"""Abstract base class for outbound sinks."""

from abc import ABC, abstractmethod
from typing import Any

from depotgate.core.models import ArtifactPointer, ShipmentManifest


class OutboundSink(ABC):
    """Abstract interface for outbound shipping sinks."""

    @property
    @abstractmethod
    def sink_type(self) -> str:
        """Return the sink type identifier."""
        pass

    @abstractmethod
    async def ship(
        self,
        artifacts: list[ArtifactPointer],
        destination: str,
        manifest: ShipmentManifest,
        artifact_content_getter: Any,  # Callable to get content by artifact_id
    ) -> dict[str, str]:
        """
        Ship artifacts to destination.

        Args:
            artifacts: List of artifact pointers to ship
            destination: Destination specification (sink-specific)
            manifest: Shipment manifest for reference
            artifact_content_getter: Async callable(artifact_id) -> bytes

        Returns:
            Dict mapping artifact_id -> destination reference
        """
        pass

    @abstractmethod
    async def validate_destination(self, destination: str) -> bool:
        """
        Validate that a destination specification is valid.

        Args:
            destination: Destination specification

        Returns:
            True if valid, False otherwise
        """
        pass

    def parse_destination(self, full_destination: str) -> tuple[str, str]:
        """
        Parse a full destination into sink type and destination path.

        Format: "sink_type://destination_path"
        Example: "filesystem:///output/deliverables"
                 "http://webhook.example.com/receive"

        Args:
            full_destination: Full destination string

        Returns:
            Tuple of (sink_type, destination_path)
        """
        if "://" in full_destination:
            parts = full_destination.split("://", 1)
            return parts[0], parts[1]
        return self.sink_type, full_destination
