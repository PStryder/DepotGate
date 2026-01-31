"""ReceiptGate MCP client for DepotGate receipt emission."""

from __future__ import annotations

from typing import Any

import httpx

from depotgate.config import settings


def _normalize_endpoint(endpoint: str) -> str:
    endpoint = (endpoint or "").rstrip("/")
    if endpoint and not endpoint.endswith("/mcp"):
        endpoint = f"{endpoint}/mcp"
    return endpoint


async def emit_receipt(payload: dict[str, Any]) -> bool:
    """Emit a receipt to ReceiptGate via MCP."""
    if not settings.receiptgate_emit_receipts:
        return False
    if not settings.receiptgate_endpoint:
        return False

    endpoint = _normalize_endpoint(settings.receiptgate_endpoint)
    headers = {"Content-Type": "application/json"}
    token = settings.receiptgate_auth_token.get_secret_value()
    if token:
        headers["Authorization"] = f"Bearer {token}"

    request_payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "receiptgate.submit_receipt",
            "arguments": {"receipt": payload},
        },
    }

    try:
        async with httpx.AsyncClient(timeout=settings.receiptgate_timeout_seconds) as client:
            response = await client.post(endpoint, json=request_payload, headers=headers)
            response.raise_for_status()
            data = response.json()
            return "error" not in data
    except Exception:
        return False
