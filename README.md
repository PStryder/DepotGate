# DepotGate v0

**Artifact Staging, Closure Verification, and Outbound Logistics**

DepotGate is an infrastructure primitive for managing artifact delivery in asynchronous and multi-agent systems. It enforces declared closure requirements before releasing deliverables, preventing both premature delivery and permanent limbo.

## Quick Start

### Using Docker Compose

```bash
# Start PostgreSQL and DepotGate
docker-compose up -d

# Service available at http://localhost:8000/mcp (MCP JSON-RPC)
```

### Local Development

```bash
# Install dependencies
pip install -e ".[dev]"

# Set up PostgreSQL (requires running instance)
# Copy and edit environment config
cp .env.example .env

# Run the service
python -m depotgate.main
```

## MCP Interface

DepotGate exposes MCP over HTTP at `/mcp` with JSON-RPC methods:
- `tools/list`
- `tools/call`

**Available MCP Tools:**
- `stage_artifact` - Stage an artifact in DepotGate
- `list_staged_artifacts` - List artifacts staged for a task
- `get_artifact` - Get artifact metadata by ID
- `declare_deliverable` - Declare a deliverable contract
- `check_closure` - Check if closure requirements are met
- `ship` - Ship a deliverable (verifies closure first)
- `purge` - Purge staged artifacts
- `depotgate.health` - Health check / service info
- `depotgate.get_deliverable` - Fetch a deliverable by ID

## Example Usage

### MCP JSON-RPC

```python
import httpx
import base64

# Stage an artifact
payload = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {
        "name": "stage_artifact",
        "arguments": {
            "root_task_id": "task-123",
            "content_base64": base64.b64encode(b"result data").decode(),
            "mime_type": "application/json",
            "artifact_role": "final_output",
        },
    },
}

response = httpx.post("http://localhost:8000/mcp", json=payload).json()
artifact_id = response["result"]["artifact_id"]

# Declare a deliverable
declare_payload = {
    "jsonrpc": "2.0",
    "id": 2,
    "method": "tools/call",
    "params": {
        "name": "declare_deliverable",
        "arguments": {
            "root_task_id": "task-123",
            "artifact_ids": [artifact_id],
            "shipping_destination": "filesystem://output",
        },
    },
}

deliverable = httpx.post("http://localhost:8000/mcp", json=declare_payload).json()
```

## Configuration

Environment variables (prefix: `DEPOTGATE_`):

| Variable | Default | Description |
|----------|---------|-------------|
| `HOST` | 0.0.0.0 | Service bind address |
| `PORT` | 8000 | Service port |
| `DEBUG` | false | Enable debug mode |
| `TENANT_ID` | default | Single tenant identifier |
| `SERVICE_PRINCIPAL_ID` | svc:depotgate | Service principal identifier |
| `DEFAULT_RECIPIENT_AI` | svc:depotgate | Default recipient AI for emitted receipts |
| `POSTGRES_HOST` | localhost | PostgreSQL host |
| `POSTGRES_PORT` | 5432 | PostgreSQL port |
| `POSTGRES_USER` | depotgate | Database user |
| `POSTGRES_PASSWORD` | depotgate_local | Database password |
| `POSTGRES_METADATA_DB` | depotgate_metadata | Metadata database |
| `POSTGRES_RECEIPTS_DB` | depotgate_receipts | Receipts database |
| `STORAGE_BACKEND` | filesystem | Storage backend type |
| `STORAGE_BASE_PATH` | ./data/staging | Staging directory |
| `STORAGE_MAX_ARTIFACT_SIZE_MB` | 100 | Max artifact size (0=unlimited) |
| `ENABLED_SINKS` | filesystem | Comma-separated sink list |
| `SINK_FILESYSTEM_BASE_PATH` | ./data/shipped | Shipped artifacts directory |
| `RECEIPTGATE_ENDPOINT` |  | ReceiptGate MCP endpoint |
| `RECEIPTGATE_AUTH_TOKEN` |  | ReceiptGate auth token |
| `RECEIPTGATE_EMIT_RECEIPTS` | true | Emit LegiVellum receipts to ReceiptGate |
| `RECEIPTGATE_TIMEOUT_SECONDS` | 10 | ReceiptGate request timeout |

ReceiptGate integration emits LegiVellum receipts for artifact staging,
shipment completion/rejection, and purge operations when enabled.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        DepotGate                            │
├─────────────────────────────────────────────────────────────┤
│  API Layer (FastAPI)                                        │
│  ├── /mcp      - MCP JSON-RPC                            │
│  └── (tools/list, tools/call)                             │
├─────────────────────────────────────────────────────────────┤
│  Core Services                                              │
│  ├── StagingArea      - Artifact storage management        │
│  ├── DeliverableManager - Declarations & closure checking  │
│  ├── ShippingService  - Ship & purge operations            │
│  └── ReceiptStore     - Event logging                      │
├─────────────────────────────────────────────────────────────┤
│  Storage Layer                                              │
│  ├── StorageBackend   - Pluggable artifact storage         │
│  │   └── FilesystemStorageBackend                          │
│  └── OutboundSink     - Pluggable shipping destinations    │
│      ├── FilesystemSink                                    │
│      └── HttpSink                                          │
├─────────────────────────────────────────────────────────────┤
│  Persistence                                                │
│  ├── PostgreSQL (metadata) - Artifacts, deliverables       │
│  └── PostgreSQL (receipts) - Event receipts                │
└─────────────────────────────────────────────────────────────┘
```

## Core Concepts

- **Artifact**: Opaque payload produced by work. DepotGate never inspects content.
- **Artifact Pointer**: Content-opaque reference with metadata only.
- **Staging Area**: Namespace where artifacts accumulate before shipment.
- **Deliverable**: Declared outbound unit with requirements and destination.
- **Closure**: Explicit verification that all declared requirements are met.
- **Receipt**: Immutable event record for auditability.

## Non-Goals (Hard Boundaries)

DepotGate **MUST NOT**:
- Inspect artifact contents
- Transform or modify artifacts
- Schedule work or spawn tasks
- Retry or repair failures
- Infer intent or completeness

## Testing

```bash
# Run tests
pytest

# With coverage
pytest --cov=depotgate

# Run only unit tests (no DB required)
pytest tests/test_models.py tests/test_storage.py tests/test_sinks.py
```

## License

MIT
