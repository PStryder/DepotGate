# DepotGate Security Punchlist
**Review Date:** January 7, 2026  
**Reviewer:** Kee (Lattice Architecture Review)  
**Context:** OSS v1 preparation + CorpoVellum hardening roadmap  
**Scope:** Security footguns, production readiness, artifact storage security

---

## Executive Summary

DepotGate has **two critical path traversal vulnerabilities** in its core storage and shipping logic. These are more severe than CogniGate's issues because DepotGate's entire purpose is file handling - compromise here means arbitrary filesystem access.

**Critical Issues:**
1. **Storage backend** allows writing artifacts anywhere via malicious tenant_id/root_task_id
2. **Shipping sink** allows reading from staging and writing shipped artifacts anywhere via malicious destination
3. **Docker runs as root** amplifying impact of above

**Additional Concerns:**
- No API authentication (anyone can stage/ship artifacts)
- Database credentials in environment (not properly secured)
- No rate limiting (resource exhaustion via artifact staging)

---

## BLOCKER Issues (Cannot Ship Without Fixes)

### BLOCK-001: Path Traversal in Storage Backend
**File:** `src/depotgate/storage/filesystem.py:26-29, 34-37`  
**Risk:** Write artifacts anywhere on filesystem

**Problem #1: tenant_id and root_task_id**
```python
def _get_artifact_path(self, tenant_id: str, root_task_id: str, artifact_id: UUID) -> Path:
    """Generate filesystem path for an artifact."""
    # Organize by tenant/root_task_id/artifact_id for easy cleanup
    return self.base_path / tenant_id / root_task_id / str(artifact_id)
```

**Attack:**
```python
tenant_id = "../../../../etc"
root_task_id = "passwd"
artifact_id = UUID("...")

# Results in: /app/data/staging/../../../../etc/passwd/{uuid}
# Writes to: /etc/passwd/{uuid}
```

**Problem #2: location strings**
```python
def _location_to_path(self, location: str) -> Path:
    """Convert location string to filesystem path."""
    if location.startswith("fs://"):
        relative_path = location[5:]
        return self.base_path / relative_path  # No validation!
    return Path(location)  # Even worse - absolute paths allowed!
```

**Attack:**
```python
location = "fs://../../../../../../etc/shadow"
# Results in: /app/data/staging/../../../../../../etc/shadow
# Reads from: /etc/shadow
```

**Fix Strategy:**
```python
import re
from pathlib import Path

def _sanitize_path_component(self, component: str) -> str:
    """Sanitize path component to prevent traversal."""
    # Remove any path separators and dangerous characters
    sanitized = re.sub(r'[/\\.]', '_', component)
    # Limit length
    return sanitized[:200]

def _get_artifact_path(self, tenant_id: str, root_task_id: str, artifact_id: UUID) -> Path:
    """Generate filesystem path for an artifact."""
    safe_tenant = self._sanitize_path_component(tenant_id)
    safe_task = self._sanitize_path_component(root_task_id)
    return self.base_path / safe_tenant / safe_task / str(artifact_id)

def _location_to_path(self, location: str) -> Path:
    """Convert location string to filesystem path."""
    if not location.startswith("fs://"):
        raise ValueError("Invalid location format, must start with fs://")
    
    relative_path = location[5:]
    path = (self.base_path / relative_path).resolve()
    
    # SECURITY: Verify resolved path is within base_path
    try:
        path.relative_to(self.base_path.resolve())
    except ValueError:
        raise ValueError(f"Path traversal attempt detected: {location}")
    
    return path
```

---

### BLOCK-002: Path Traversal in Shipping Sink
**File:** `src/depotgate/sinks/filesystem.py:38-54`  
**Risk:** Write shipped artifacts anywhere on filesystem

**Problem:**
```python
async def ship(self, artifacts, destination: str, manifest, artifact_content_getter):
    """Ship artifacts to filesystem destination."""
    # Parse destination - could be absolute or relative to base_path
    if destination.startswith("/"):
        dest_path = Path(destination)  # ABSOLUTE PATH - NO VALIDATION!
    else:
        dest_path = self.base_path / destination  # No sanitization!

    # Create destination directory structure
    shipment_dir = dest_path / str(manifest.manifest_id)
    shipment_dir.mkdir(parents=True, exist_ok=True)  # Creates anywhere!
```

**Attack:**
```python
destination = "/etc/cron.d"
# Results in: /etc/cron.d/{manifest_id}/
# Ships artifacts to cron directory, potential code execution
```

**Fix Strategy:**
```python
def _sanitize_destination(self, destination: str) -> Path:
    """Sanitize and validate destination path."""
    # Reject absolute paths
    if destination.startswith("/"):
        raise ValueError("Absolute destination paths not allowed")
    
    # Remove path traversal attempts
    safe_dest = destination.replace("..", "_")
    
    # Construct path
    dest_path = (self.base_path / safe_dest).resolve()
    
    # SECURITY: Verify resolved path is within base_path
    try:
        dest_path.relative_to(self.base_path.resolve())
    except ValueError:
        raise ValueError(f"Path traversal attempt in destination: {destination}")
    
    return dest_path

async def ship(self, artifacts, destination: str, manifest, artifact_content_getter):
    """Ship artifacts to filesystem destination."""
    dest_path = self._sanitize_destination(destination)
    
    # Create destination directory structure
    shipment_dir = dest_path / str(manifest.manifest_id)
    shipment_dir.mkdir(parents=True, exist_ok=True)
    # ... rest of shipping logic
```

---

### BLOCK-003: Docker Runs as Root
**File:** `Dockerfile`  
**Risk:** Container escape = host compromise

**Current State:**
```dockerfile
FROM python:3.11-slim
WORKDIR /app
# ... installs and setup ...
CMD ["python", "-m", "depotgate.main"]  # Runs as root!
```

**Fix:**
```dockerfile
# After creating data directories
RUN mkdir -p /app/data/staging /app/data/shipped

# Create non-root user
RUN groupadd -g 1000 depotgate && \
    useradd -m -u 1000 -g depotgate depotgate && \
    chown -R depotgate:depotgate /app

# Set environment variables
ENV DEPOTGATE_HOST=0.0.0.0
# ... other env vars ...

# Switch to non-root user before CMD
USER depotgate

# Run the service
CMD ["python", "-m", "depotgate.main"]
```

---

## HIGH Priority (Fix Before Production)

### HIGH-001: No API Authentication
**File:** `src/depotgate/api/routes.py`  
**Risk:** Anyone can stage/ship artifacts, read receipts, control system

**Problem:**
All endpoints from lines 66-404 have no authentication:
- `/api/v1/stage` - upload arbitrary files
- `/api/v1/ship` - ship artifacts anywhere
- `/api/v1/deliverables` - modify contracts
- `/api/v1/purge` - delete artifacts
- `/api/v1/receipts` - read all system activity

**Fix:**
```python
from fastapi import Security, HTTPException
from fastapi.security import APIKeyHeader

api_key_header = APIKeyHeader(name="X-DepotGate-Key", auto_error=False)

async def verify_api_key(key: str = Security(api_key_header)):
    """Verify API key from request header."""
    if not key or key != settings.api_key:
        raise HTTPException(403, "Invalid API key")
    return key

# Apply to all routes
@router.post("/stage", dependencies=[Depends(verify_api_key)])
async def stage_artifact(...):
    ...

@router.post("/ship", dependencies=[Depends(verify_api_key)])
async def ship_deliverable(...):
    ...

# Add to Settings
class Settings(BaseSettings):
    api_key: str = Field(description="API key for authentication")
    require_auth: bool = Field(default=True)
```

---

### HIGH-002: Input Validation Missing
**File:** `src/depotgate/api/routes.py:66-110`  
**Risk:** Malicious input causes system failures or exploitation

**Problem:**
```python
@router.post("/stage")
async def stage_artifact(
    file: UploadFile = File(...),
    root_task_id: str = Form(...),  # No validation!
    artifact_role: ArtifactRole = Form(ArtifactRole.SUPPORTING),
    produced_by_receipt_id: str | None = Form(None),  # No UUID validation!
):
```

Parameters accepted without validation:
- `root_task_id` - could be "../../../evil"
- `produced_by_receipt_id` - not validated as UUID
- `file` - no size limit check before reading

**Fix:**
```python
from pydantic import validator, Field

class StageArtifactForm(BaseModel):
    root_task_id: str = Field(max_length=256, pattern=r'^[a-zA-Z0-9_-]+$')
    artifact_role: ArtifactRole = ArtifactRole.SUPPORTING
    produced_by_receipt_id: str | None = None
    
    @validator('produced_by_receipt_id')
    def validate_receipt_id(cls, v):
        if v is not None:
            try:
                UUID(v)
            except ValueError:
                raise ValueError("Invalid receipt ID format")
        return v

@router.post("/stage")
async def stage_artifact(
    file: UploadFile = File(...),
    form: StageArtifactForm = Depends(),
    staging: StagingArea = Depends(get_staging_area),
):
    # Check file size before reading
    if file.size and file.size > settings.storage_max_artifact_bytes:
        raise HTTPException(413, "File too large")
    
    content = await file.read()
    # ... rest of logic
```

---

### HIGH-003: Database Credentials Exposure
**File:** `src/depotgate/config.py:31-35`  
**Risk:** Credentials leaked via logs, error messages, config dumps

**Problem:**
```python
postgres_user: str = "depotgate"
postgres_password: str = "depotgate"  # Default password!
```

Credentials:
- Have insecure defaults
- Appear in logs when database_url property is accessed
- No secrets management

**Fix:**
```python
from pydantic import SecretStr

class Settings(BaseSettings):
    postgres_user: str = Field(description="PostgreSQL username")
    postgres_password: SecretStr = Field(description="PostgreSQL password")
    
    @property
    def metadata_database_url(self) -> str:
        """Connection string for metadata database."""
        pwd = self.postgres_password.get_secret_value()
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{pwd}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_metadata_db}"
        )
    
    model_config = SettingsConfigDict(
        env_prefix="DEPOTGATE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        # SECURITY: Never log secrets
        str_strip_whitespace=True,
    )

# In .env.example, remove defaults:
# DEPOTGATE_POSTGRES_USER=depotgate
# DEPOTGATE_POSTGRES_PASSWORD=changeme
```

**Also add validation:**
```python
@field_validator('postgres_password')
def validate_password(cls, v):
    pwd = v.get_secret_value() if isinstance(v, SecretStr) else v
    if pwd in ['depotgate', 'password', 'changeme', '']:
        raise ValueError("Insecure default password detected")
    return v
```

---

## MEDIUM Priority (Pre-Launch)

### MED-001: No Rate Limiting
**File:** `src/depotgate/api/routes.py` - all endpoints  
**Risk:** Resource exhaustion via artifact spam

**Problem:**
`/api/v1/stage` can be called unlimited times, filling disk with artifacts.

**Fix:**
```python
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

limiter = Limiter(key_func=get_remote_address)

@router.post("/stage")
@limiter.limit("100/minute")  # Configurable limit
async def stage_artifact(request: Request, ...):
    ...
```

---

### MED-002: Artifact Size Bomb Prevention
**File:** `src/depotgate/storage/filesystem.py:70-93`  
**Risk:** Disk exhaustion via large uploads

**Current Logic:**
```python
if max_size > 0 and size > max_size:
    # Clean up partial file
    await f.close()
    await aiofiles.os.remove(path)
    raise ValueError(...)
```

Issue: File is written first, THEN checked. For streaming uploads, this partially writes before failing.

**Better Approach:**
```python
# Check size BEFORE accepting upload
if isinstance(content, bytes):
    if max_size > 0 and len(content) > max_size:
        raise ValueError(f"Artifact size {len(content)} exceeds limit")
    # Proceed with write
else:
    # For streams, track size as we write
    async with aiofiles.open(path, "wb") as f:
        async for chunk in content:
            if max_size > 0 and size + len(chunk) > max_size:
                # Close and remove BEFORE exceeding limit
                await f.close()
                await aiofiles.os.remove(path)
                raise ValueError(f"Artifact size exceeds limit")
            size += len(chunk)
            await f.write(chunk)
```

---

### MED-003: Receipt Ledger Can Leak Sensitive Data
**File:** `src/depotgate/core/receipts.py` (if exists)  
**Risk:** Receipts contain artifact metadata that might include sensitive info

Similar to CogniGate HIGH-004, receipts should not contain:
- Full file paths
- User-provided metadata without sanitization
- System internals

**Recommendation:**
Add receipt sanitization before storage:
```python
def sanitize_receipt_metadata(metadata: dict) -> dict:
    """Remove sensitive patterns from receipt metadata."""
    sanitized = {}
    for k, v in metadata.items():
        if isinstance(v, str):
            # Redact paths
            v = re.sub(r'/[a-z0-9_/-]+', '[PATH]', v)
            # Redact potential secrets
            v = re.sub(r'[a-zA-Z0-9]{32,}', '[REDACTED]', v)
        sanitized[k] = v
    return sanitized
```

---

## OSS vs CorpoVellum Split

### Ship in OSS v1
- Fix all 3 BLOCKERs (path traversal + Docker user)
- Add basic API auth (API key)
- Add input validation on root_task_id
- Document remaining risks

### Hold for CorpoVellum
- Advanced auth (JWT, RBAC, multi-tenant)
- Secrets management (HashiCorp Vault integration)
- Audit logging to external system
- Artifact encryption at rest
- Artifact virus scanning
- Advanced rate limiting per tenant
- Compliance features (GDPR, HIPAA)

---

## Testing Requirements

**Critical:** Add these test cases before v1

```python
# tests/test_security.py

async def test_path_traversal_in_storage_blocked():
    """Verify storage backend rejects path traversal in tenant_id."""
    backend = FilesystemStorageBackend()
    with pytest.raises(ValueError, match="traversal"):
        await backend.store(
            artifact_id=uuid4(),
            tenant_id="../../etc",
            root_task_id="passwd",
            content=b"malicious",
            mime_type="text/plain"
        )

async def test_path_traversal_in_location_blocked():
    """Verify location strings are validated."""
    backend = FilesystemStorageBackend()
    with pytest.raises(ValueError, match="traversal"):
        await backend.retrieve("fs://../../../../etc/shadow")

async def test_destination_path_traversal_blocked():
    """Verify filesystem sink rejects traversal in destination."""
    sink = FilesystemSink()
    with pytest.raises(ValueError, match="traversal"):
        await sink.ship(
            artifacts=[],
            destination="../../../etc/cron.d",
            manifest=mock_manifest,
            artifact_content_getter=mock_getter
        )

async def test_absolute_destination_rejected():
    """Verify absolute paths in destination are rejected."""
    sink = FilesystemSink()
    with pytest.raises(ValueError, match="Absolute"):
        await sink.ship(
            artifacts=[],
            destination="/etc/evil",
            manifest=mock_manifest,
            artifact_content_getter=mock_getter
        )

async def test_oversized_artifact_rejected():
    """Verify size limits are enforced."""
    staging = StagingArea(...)
    huge_content = b"x" * (200 * 1024 * 1024)  # 200MB
    with pytest.raises(ValueError, match="exceeds limit"):
        await staging.stage_artifact(
            root_task_id="test",
            content=huge_content,
            mime_type="application/octet-stream"
        )
```

---

## Deployment Checklist

Before production:

**Configuration:**
- [ ] Set strong API_KEY (32+ random chars)
- [ ] Change all database passwords from defaults
- [ ] Set storage_max_artifact_size_mb to reasonable limit
- [ ] Verify DEPOTGATE_STORAGE_BASE_PATH is correct
- [ ] Verify DEPOTGATE_SINK_FILESYSTEM_BASE_PATH is correct

**Docker:**
- [ ] Image runs as non-root user (depotgate:1000)
- [ ] Data directories have correct permissions (700)
- [ ] Storage volumes mounted correctly
- [ ] Resource limits set (memory, CPU, disk)
- [ ] Health check working

**Database:**
- [ ] PostgreSQL credentials secured
- [ ] Databases initialized (init-db.sql run)
- [ ] Connection pooling configured
- [ ] Backup strategy in place

**Network:**
- [ ] API behind firewall or reverse proxy with TLS
- [ ] Rate limiting active
- [ ] Only necessary ports exposed
- [ ] Database not publicly accessible

**Monitoring:**
- [ ] Health endpoint monitored
- [ ] Disk usage alerting (staging + shipped dirs)
- [ ] Database connection monitoring
- [ ] Error rate alerting

---

## Mesh Integration Concerns

When integrating with other LegiVellum gates:

### AsyncGate → DepotGate
- AsyncGate must sanitize task IDs before passing to DepotGate
- DepotGate should NOT trust task_id/tenant_id from AsyncGate
- Implement validation layers at boundary

### CogniGate → DepotGate
- CogniGate's artifact_write tool calls DepotGate
- DepotGate must validate ALL inputs from CogniGate
- Don't assume CogniGate's sanitization is sufficient

### MetaGate Bootstrap
- MetaGate should set DepotGate paths securely
- Validate paths don't escape intended boundaries
- Set proper directory permissions (700)

---

## Final Recommendations

**For OSS v1 Launch:**
1. Fix BLOCKER-001, 002, 003 immediately (paths + Docker)
2. Add HIGH-001 (API auth) as required
3. Add HIGH-002 (input validation)
4. Document security model in README
5. Run security test suite

**For CorpoVellum:**
1. Complete all BLOCKER + HIGH + MEDIUM fixes
2. Add encryption at rest for artifacts
3. Implement audit logging
4. Get external security review
5. Consider artifact scanning (virus, malware)

**Timeline Estimate:**
- OSS v1 BLOCKER fixes: 1-2 days
- Full OSS v1 ready: 3-4 days
- CorpoVellum hardening: 2-3 weeks
- Compliance features: 2-3 months

---

**DepotGate is more critical than CogniGate** because its entire purpose is artifact handling. A compromise here means complete filesystem access and potential data exfiltration of all artifacts ever staged or shipped.

Priority: **HIGH**  
Urgency: **IMMEDIATE**

---

*Review by Kee - Lattice Architecture Analysis*  
*Next: Fix BLOCKERs, test thoroughly, ship safely*
