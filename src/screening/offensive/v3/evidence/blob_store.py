"""Content-addressed durable blob storage for one evidence namespace.

Plan 03 Task 1 scope: the payload becomes durable BEFORE its envelope is
committed, so an orphan blob is safe while an envelope without a durable
payload is impossible. Blobs are named by the sha256 of their content,
written temp-file + fsync + atomic rename, and read through the same
regular-file no-follow discipline as the trust registry.

Path guards (2026-08-21 adversarial review, autodev round 4): the blob
root is a cross-process cold-trust surface, so every directory component
from the anchor down is lstat-walked (symlink presets fail closed) and
content hashes must be exactly 64 lowercase hex before any path is
assembled — ``O_NOFOLLOW`` alone protects only the final component.
"""

from __future__ import annotations

import hashlib
import os
import re
import stat
import tempfile
from pathlib import Path

from src.screening.offensive.v3.orchestration.path_guards import walk_components

_HEX64 = re.compile(r"[0-9a-f]{64}")


class BlobStoreError(RuntimeError):
    """Fail-closed blob store rejection."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


def _blob_fail(code: str, message: str, **_details: object) -> Exception:
    """path_guards 守卫错误 → BlobStoreError (两参签名的族适配)。"""
    return BlobStoreError(code, message)


def _ensure_directory(path: Path, *, code: str = "blob_component_rejected") -> None:
    """逐段创建目录并逐段验证 — 绝不穿过 symlink 预置创建。

    ``Path.mkdir(parents=True, exist_ok=True)`` 会静默跟随路径上已有的
    symlink 在 root 之外创建目录 (对抗性审查 PoC-C: victim 落盘的元数据
    副作用)。本原语把创建拆成单段步进: 已存在的祖先段先全组件 walk,
    缺失段逐个 mkdir() (无 parents/exist_ok): 预置 symlink 触发拒绝,
    但**并发同伴竞态创建的真实目录收敛放行** — 与仓库的恰等重放幂等/
    并发收敛纪律一致 (services 并发 publish 收敛测试锁定)。
    """
    missing: list[str] = []
    probe = path
    while True:
        try:
            mode = probe.lstat().st_mode
        except FileNotFoundError:
            missing.append(probe.name)
            probe = probe.parent
            continue
        if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
            raise BlobStoreError(
                code,
                "blob store path must have no symlinked or non-directory "
                "component",
            )
        break
    walk_components(
        probe,
        fail=_blob_fail,
        missing_code=code,
        rejected_code=code,
    )
    for name in reversed(missing):
        probe = probe / name
        try:
            probe.mkdir()
        except FileExistsError:
            # 竞态同伴可能刚创建了真实目录 — 重验后收敛; 预置的
            # symlink/文件仍然拒绝。
            mode = probe.lstat().st_mode
            if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
                raise BlobStoreError(
                    code,
                    "blob store path component was preset to a "
                    "non-directory",
                ) from None
            continue
        mode = probe.lstat().st_mode
        if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
            raise BlobStoreError(
                code,
                "blob store path must have no symlinked or non-directory "
                "component",
            )


class BlobStore:
    """One content-addressed root directory; content hashes are keys."""

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root)
        if not self._root.is_absolute():
            raise BlobStoreError(
                "blob_root_not_canonical",
                "blob store root must be a canonical absolute path",
            )
        if self._root.is_symlink():
            raise BlobStoreError(
                "blob_root_symlink", "blob store root must be a real directory"
            )
        # 逐段创建 + 逐段验证 (2026-08-21 对抗性审查: mkdir(parents=True)
        # 会穿过父级 symlink 预置, 且此前只查 root 最终一段)。
        _ensure_directory(self._root, code="blob_root_rejected")

    @property
    def root(self) -> Path:
        return self._root

    def blob_path(self, content_hash: str) -> Path:
        # content_hash 是信封字段 (untrusted-ish): 拼任何路径前先过
        # 64-hex 形状校验 — 三段切片 (h[:2]/h[2:4]/h) 绝不接触穿越形状。
        if type(content_hash) is not str or _HEX64.fullmatch(content_hash) is None:
            raise BlobStoreError(
                "blob_hash_invalid",
                "content hash must be exactly 64 lowercase hex characters",
            )
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
        # 逐段创建 + 逐段验证 (2026-08-21 对抗性审查: mkdir(parents=True)
        # 的 exist_ok 会静默穿过预置 symlink, blob 随之写穿到 root 之外)。
        _ensure_directory(target.parent)
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
        # O_NOFOLLOW 只保护最终组件; 中间目录组件同样逐级 lstat
        # (2026-08-21 对抗性审查: 预置 symlink 可让 get 把 root 之外
        # 的字节当作该 hash 的原始 payload 返回)。
        walk_components(
            path.parent,
            fail=_blob_fail,
            missing_code="blob_not_found",
            rejected_code="blob_component_rejected",
        )
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
