"""StorageBackend — port for raw file persistence.

LocalStorageBackend writes to a directory on disk.
A future S3StorageBackend will return pre-signed URLs and delegate
writes/deletes to an S3-compatible API (AWS S3, MinIO, GCS).

Route contract:
  - get_url() returning None  → caller uses FileResponse(backend.resolve(key))
  - get_url() returning a str → caller issues RedirectResponse(url)
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable


@runtime_checkable
class StorageBackend(Protocol):
    def save(self, user_id: str, file_id: str, filename: str, data: bytes) -> str: ...
    def get_url(self, key: str) -> str | None: ...
    def resolve(self, key: str) -> Path | None: ...
    def delete(self, key: str) -> None: ...


class LocalStorageBackend:
    """Stores files under a root directory; serves via FileResponse."""

    def __init__(self, root: Path) -> None:
        self._root = root

    def save(self, user_id: str, file_id: str, filename: str, data: bytes) -> str:
        dest_dir = self._root / user_id
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / f"{file_id}_{filename}"
        dest.write_bytes(data)
        return str(Path(user_id) / f"{file_id}_{filename}")

    def get_url(self, key: str) -> None:  # type: ignore[override]
        return None

    def resolve(self, key: str) -> Path | None:
        path = self._root / key
        return path if path.exists() else None

    def delete(self, key: str) -> None:
        path = self._root / key
        if path.exists():
            path.unlink()
