# StorageBackend port for raw file persistence; LocalStorageBackend as default

**Status:** Accepted

## Decision

`core/storage.StorageBackend` is a Protocol:

- `save(user_id, file_id, filename, data) → key`
- `get_url(key) → str | None`
- `resolve(key) → Path | None`
- `delete(key) → None`

`LocalStorageBackend(root: Path)` is the reference implementation. It writes to `{root}/{user_id}/{file_id}_{filename}` and returns relative path keys. `get_url()` always returns `None`.

Route contract:

| `get_url(key)` returns | Route serves with                |
|------------------------|----------------------------------|
| `None`                 | `FileResponse(backend.resolve(key))` |
| `str` (URL)            | `RedirectResponse(url)`          |

## Rationale

Two deployment shapes need different serve paths: local development (file on disk, served by the FastAPI process) and cloud (pre-signed URL, served directly by S3/GCS/MinIO, no bytes through the backend). Proxying bytes through the backend for both cases is operationally expensive at cloud scale and complicates streaming.

`get_url() → None` is a deliberate sentinel rather than two methods (`get_url`, `serve_local`) because it composes cleanly with the FastAPI route: one branch on the return value, the same route handler for both cases.

The port lives in agno-plus core (not the application) because two assistants already need it (`agentic-aide` and `personal-aide-minimal`). The agentic-aide team initially placed `StorageBackend` in their `adapters/storage.py` (their ADR-0006) on the grounds that the second consumer didn't exist yet. The second consumer now exists; promoting the port to agno-plus avoids duplication.

## Alternatives considered

**Always proxy bytes through the backend.** One serve path, no branching. Adds backend load for large cloud files and an unnecessary serialization step for local files. Rejected.

**Cloud-only abstraction with local mode as "use a mock S3."** Forces every dev environment to run MinIO or equivalent. Sufficient for some teams; over-engineered for a quick-start example.

**Application-layer abstraction.** Keep the port in each app. Worked when only one app existed; duplication now.

## Consequences

- Adding an S3 backend is one file (`S3StorageBackend(boto3_client, bucket)`) implementing the four methods. Pre-signed URLs go in `get_url()`.
- Deletion is the consumer's responsibility — the library does not GC `LocalStorageBackend` files automatically. Apps tie file lifetime to their `ingested_files` table (see agentic-aide ADR-0006).
- `key` is opaque to the route. `LocalStorageBackend` happens to use relative paths; an S3 backend would use bucket-relative keys. Callers must not parse the key.
- Existing application code that already has its own `StoragePort` can migrate by changing imports — the protocol shape matches the agentic-aide implementation 1:1.
