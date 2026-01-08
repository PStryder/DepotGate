"""HTTP outbound sink implementation."""

import base64
from typing import Any, Callable, Coroutine
from urllib.parse import urlparse
from uuid import UUID

import httpx

from depotgate.config import settings
from depotgate.core.models import ArtifactPointer, ShipmentManifest
from depotgate.sinks.base import OutboundSink


class HttpSink(OutboundSink):
    """HTTP-based outbound sink for webhooks and REST endpoints."""

    def __init__(self, timeout: int | None = None):
        """Initialize HTTP sink.

        Args:
            timeout: Request timeout in seconds. Defaults to config.
        """
        self.timeout = timeout or settings.sink_http_timeout_seconds

    @property
    def sink_type(self) -> str:
        return "http"

    async def ship(
        self,
        artifacts: list[ArtifactPointer],
        destination: str,
        manifest: ShipmentManifest,
        artifact_content_getter: Callable[[UUID], Coroutine[Any, Any, bytes]],
    ) -> dict[str, str]:
        """Ship artifacts via HTTP POST to destination URL."""
        destination_refs: dict[str, str] = {}

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            # Build payload with manifest and artifacts
            artifact_payloads = []

            for artifact in artifacts:
                content = await artifact_content_getter(artifact.artifact_id)
                artifact_payloads.append({
                    "artifact_id": str(artifact.artifact_id),
                    "mime_type": artifact.mime_type,
                    "size_bytes": artifact.size_bytes,
                    "content_hash": artifact.content_hash,
                    "artifact_role": artifact.artifact_role.value,
                    "content_base64": base64.b64encode(content).decode("ascii"),
                })

            payload = {
                "manifest": {
                    "manifest_id": str(manifest.manifest_id),
                    "deliverable_id": str(manifest.deliverable_id),
                    "root_task_id": manifest.root_task_id,
                    "tenant_id": manifest.tenant_id,
                    "shipped_at": manifest.shipped_at.isoformat(),
                },
                "artifacts": artifact_payloads,
            }

            # POST to destination
            response = await client.post(
                destination,
                json=payload,
                headers={"Content-Type": "application/json"},
            )
            response.raise_for_status()

            # Parse response for destination refs if provided
            try:
                resp_data = response.json()
                if isinstance(resp_data, dict) and "artifact_refs" in resp_data:
                    destination_refs = resp_data["artifact_refs"]
                else:
                    # Default: use destination URL + artifact_id
                    for artifact in artifacts:
                        destination_refs[str(artifact.artifact_id)] = (
                            f"{destination}#{artifact.artifact_id}"
                        )
            except Exception:
                # Default refs on parse failure
                for artifact in artifacts:
                    destination_refs[str(artifact.artifact_id)] = (
                        f"{destination}#{artifact.artifact_id}"
                    )

        return destination_refs

    def _is_allowed_host(self, hostname: str | None) -> bool:
        """Check if hostname is allowed for HTTP sink destinations."""
        if not hostname:
            return False
        allowed_hosts = [h.lower() for h in settings.sink_http_allowed_hosts]
        if not allowed_hosts:
            return False
        if "*" in allowed_hosts:
            return True
        return hostname.lower() in allowed_hosts

    async def validate_destination(self, destination: str) -> bool:
        """Validate HTTP destination URL."""
        try:
            parsed = urlparse(destination)
            if parsed.scheme not in settings.sink_http_allowed_schemes:
                return False
            if not parsed.netloc:
                return False
            return self._is_allowed_host(parsed.hostname)
        except Exception:
            return False
