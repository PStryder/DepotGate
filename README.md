# DepotGate v0

**Artifact Staging, Closure Verification, and Outbound Logistics**

DepotGate is an infrastructure primitive for managing artifact delivery in asynchronous and multi-agent systems. It enforces declared closure requirements before releasing deliverables, preventing both premature delivery and permanent limbo.

## Quick Start

### Using Docker Compose

```bash
# Start PostgreSQL and DepotGate
docker-compose up -d

# Service available at http://localhost:8000
# API docs at http://localhost:8000/docs
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

## API Endpoints

### Staging (`/api/v1/stage`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/stage` | Stage an artifact (multipart upload) |
| GET | `/stage/list` | List staged artifacts for a task |
| GET | `/stage/{artifact_id}` | Get artifact metadata |
| GET | `/stage/{artifact_id}/content` | Download artifact content |

### Deliverables (`/api/v1/deliverables`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/deliverables` | Declare a deliverable contract |
| GET | `/deliverables` | List deliverables for a task |
| GET | `/deliverables/{id}` | Get deliverable details |
| GET | `/deliverables/{id}/closure` | Check closure status |

### Shipping (`/api/v1`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/ship` | Ship a deliverable (if closure met) |
| GET | `/shipments` | List shipments for a task |
| GET | `/shipments/{id}` | Get shipment manifest |
| POST | `/purge` | Purge staged artifacts |

### MCP Interface (`/mcp`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/mcp` | JSON-RPC endpoint (`tools/list`, `tools/call`) |
| GET | `/mcp/tools` | Legacy: list available MCP tools |
| POST | `/mcp/call` | Legacy: execute an MCP tool call |

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

### 1. Stage an Artifact

```bash
curl -X POST http://localhost:8000/api/v1/stage \
  -F "file=@output.json" \
  -F "root_task_id=task-123" \
  -F "artifact_role=final_output"
```

### 2. Declare a Deliverable

```bash
curl -X POST http://localhost:8000/api/v1/deliverables \
  -H "Content-Type: application/json" \
  -d '{
    "root_task_id": "task-123",
    "spec": {
      "artifact_roles": ["final_output"],
      "shipping_destination": "filesystem://output"
    }
  }'
```

### 3. Check Closure and Ship

```bash
# Check closure status
curl http://localhost:8000/api/v1/deliverables/{deliverable_id}/closure

# Ship if ready
curl -X POST http://localhost:8000/api/v1/ship \
  -H "Content-Type: application/json" \
  -d '{
    "root_task_id": "task-123",
    "deliverable_id": "..."
  }'
```

### MCP Usage (for AI Agents)

```python
import httpx
import base64

# List available tools (legacy)
tools = httpx.get("http://localhost:8000/mcp/tools").json()

# Stage an artifact (legacy)
response = httpx.post("http://localhost:8000/mcp/call", json={
    "tool": "stage_artifact",
    "arguments": {
        "root_task_id": "agent-task-1",
        "content_base64": base64.b64encode(b"result data").decode(),
        "mime_type": "application/json",
        "artifact_role": "final_output"
    }
})

# JSON-RPC equivalent
rpc_response = httpx.post("http://localhost:8000/mcp", json={
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {
        "name": "stage_artifact",
        "arguments": {
            "root_task_id": "agent-task-1",
            "content_base64": base64.b64encode(b\"result data\").decode(),
            "mime_type": "application/json",
            "artifact_role": "final_output"
        }
    }
})
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
│  ├── /api/v1/* - REST endpoints                            │
│  └── /mcp/*    - MCP interface                             │
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
