"""Security-hardened file reading primitives.

Rejects symlinks (final component AND every ancestor), FIFOs, directories,
device files, and oversize content. Each path component is opened relative to a
trusted directory descriptor with ``O_NOFOLLOW`` (and ``O_DIRECTORY`` for
intermediate components), so a symlinked parent directory cannot redirect the
read. After reading, the opened file identity is compared against a fresh
``lstat`` to detect TOCTOU replacement.
"""

from __future__ import annotations

import errno
import os
import stat
from pathlib import Path


class SecureReadError(Exception):
    """Raised when a file fails security-hardened read validation."""


def _read_all(fd: int, max_bytes: int) -> bytes:
    """Read the whole descriptor, failing closed above ``max_bytes``."""

    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = os.read(fd, 65536)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise SecureReadError(f"content exceeds max_bytes {max_bytes}")
        chunks.append(chunk)
    return b"".join(chunks)


def read_regular_bytes(path: Path, *, max_bytes: int) -> bytes:
    """Read one bounded stable regular file without following any indirection.

    Security guarantees:
    - Rejects a symlink final component (``O_NOFOLLOW``)
    - Rejects a symlink in ANY ancestor component (``O_NOFOLLOW`` per component)
    - Rejects non-regular files (directories, FIFOs, devices, sockets)
    - Enforces a maximum byte limit before and during read
    - Detects inode/device/size/mtime replacement across the read (TOCTOU)
    - Guarantees every opened descriptor is closed

    Args:
        path: File to read.
        max_bytes: Maximum content size. Larger content raises SecureReadError.

    Returns:
        The file's raw bytes.

    Raises:
        SecureReadError: If any security check fails.
        FileNotFoundError: If the file does not exist.
    """

    if not isinstance(path, Path):
        path = Path(path)

    anchor = path.anchor
    if anchor:
        components = path.parts[1:]
        base_fd = os.open(anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    else:
        components = path.parts
        base_fd = os.open(".", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)

    if not components:
        os.close(base_fd)
        raise SecureReadError(f"{path}: no final path component")

    open_dirs = [base_fd]
    parent_fd = base_fd
    try:
        # Walk every intermediate directory component with O_NOFOLLOW so a
        # symlinked ancestor cannot redirect the read outside the trusted tree.
        for name in components[:-1]:
            try:
                child = os.open(
                    name,
                    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                    dir_fd=parent_fd,
                )
            except OSError as exc:
                if exc.errno in (errno.ELOOP, errno.ENOTDIR):
                    raise SecureReadError(
                        f"{path}: symlinked or non-directory ancestor {name!r}"
                    ) from exc
                raise
            open_dirs.append(child)
            parent_fd = child

        final_name = components[-1]
        try:
            fd = os.open(
                final_name,
                os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK,
                dir_fd=parent_fd,
            )
        except OSError as exc:
            # ELOOP: O_NOFOLLOW rejected a symlink final component.
            if exc.errno == errno.ELOOP:
                raise SecureReadError(f"{path}: symlink rejected") from exc
            raise  # FileNotFoundError / PermissionError propagate unchanged

        try:
            stat_before = os.fstat(fd)
            if not stat.S_ISREG(stat_before.st_mode):
                if stat.S_ISDIR(stat_before.st_mode):
                    raise SecureReadError(f"{path}: is a directory")
                if stat.S_ISLNK(stat_before.st_mode):
                    raise SecureReadError(f"{path}: symlink rejected")
                raise SecureReadError(
                    f"{path}: not a regular file (mode={stat_before.st_mode:o})"
                )
            if stat_before.st_size > max_bytes:
                raise SecureReadError(
                    f"{path}: size {stat_before.st_size} exceeds max_bytes {max_bytes}"
                )

            content = _read_all(fd, max_bytes)

            # TOCTOU: the opened descriptor's identity must still match a fresh
            # lstat of the same name under the trusted parent directory.
            current = os.stat(final_name, dir_fd=parent_fd, follow_symlinks=False)
            if (
                stat_before.st_dev,
                stat_before.st_ino,
                stat_before.st_size,
                stat_before.st_mtime_ns,
            ) != (
                current.st_dev,
                current.st_ino,
                current.st_size,
                current.st_mtime_ns,
            ):
                raise SecureReadError(f"{path}: changed while reading")

            return content
        finally:
            os.close(fd)
    finally:
        for opened in reversed(open_dirs):
            os.close(opened)


def read_secure_csv_frame(path: Path, *, max_bytes: int):
    """Securely read a CSV into a string-typed pandas frame, or None if absent.

    单一实现 (2026-08-23 对抗审查 Item 4): 授权侧 (cache_refresh 构建 readiness
    manifest) 与验证侧 (daily_action_snapshot 复算 PIT 指纹) 必须走同一条读取
    路径 — 各自实现会产生解析器分歧 (浮点往返/列投影/dtype), 让"授权指纹"与
    "验证指纹"对同一文件算出不同值. 本函数是唯一的 secure CSV frame 入口.
    """
    import io

    import pandas as pd

    if not isinstance(path, Path):
        path = Path(path)
    if not path.exists():
        return None
    raw = read_regular_bytes(path, max_bytes=max_bytes)
    if not raw.strip():
        return pd.DataFrame()
    return pd.read_csv(io.BytesIO(raw), dtype=str)
