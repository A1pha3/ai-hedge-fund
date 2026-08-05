"""Content-addressed durable blob storage for one evidence namespace.

Plan 03 Task 1 scope: the payload becomes durable BEFORE its envelope is
committed, so an orphan blob is safe while an envelope without a durable
payload is impossible. Blobs are named by the sha256 of their content,
written temp-file + fsync + atomic rename, and read through the same
regular-file no-follow discipline as the trust registry.
"""

from __future__ import annotations

import hashlib
import os
import stat
import tempfile
from pathlib import Path


class BlobStoreError(RuntimeError):
    """Fail-closed blob store rejection."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


class BlobStore:
    """One content-addressed root directory; content hashes are keys."""

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)
        if self._root.is_symlink():
            raise BlobStoreError(
                "blob_root_symlink", "blob store root must be a real directory"
            )

    @property
    def root(self) -> Path:
        return self._root

    def blob_path(self, content_hash: str) -> Path:
        return (
            self._root / content_hash[:2] / content_hash[2:4] / content_hash
        )

    def put_durable(self, payload: bytes) -> str:
        """Persist one payload and return its sha256 content hash.

        Identical content converges; a hash collision with different
        content fails closed instead of overwriting.
        """

        digest = hashlib.sha256(payload).hexdigest()
        target = self.blob_path(digest)
        if target.exists():
            if self.get(digest) != payload:
                raise BlobStoreError(
                    "blob_hash_collision",
                    "content hash already stored with different bytes",
                )
            return digest
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(target.parent), prefix=".tmp-")
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, target)
        except BaseException:
            with contextlib_suppress():
                os.unlink(tmp)
            raise
        dir_fd = os.open(str(target.parent), os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
        return digest

    def get(self, content_hash: str) -> bytes:
        """Securely read one stored blob; missing blobs fail closed."""

        path = self.blob_path(content_hash)
        try:
            fd = os.open(str(path), os.O_RDONLY | os.O_NOFOLLOW)
        except FileNotFoundError as exc:
            raise BlobStoreError(
                "blob_not_found", "unknown content hash"
            ) from exc
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode):
                raise BlobStoreError(
                    "blob_not_regular", "blob path is not a regular file"
                )
            return os.read(fd, info.st_size)
        finally:
            os.close(fd)


class contextlib_suppress:
    """Minimal cleanup suppressor (no dependency churn)."""

    def __enter__(self) -> "contextlib_suppress":
        return self

    def __exit__(self, *exc_info: object) -> bool:
        return False


__all__ = ["BlobStore", "BlobStoreError"]
