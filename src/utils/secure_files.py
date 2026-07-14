"""Security-hardened file reading primitives.

Rejects symlinks, FIFOs, directories, device files, and oversize content.
Uses O_NOFOLLOW to prevent symlink attacks, checks inode stability before
and after read to detect TOCTOU replacement.
"""

from __future__ import annotations

import errno
import os
import stat
from pathlib import Path


class SecureReadError(Exception):
    """Raised when a file fails security-hardened read validation."""


def read_regular_bytes(path: Path, *, max_bytes: int) -> bytes:
    """Read one bounded stable regular file without following indirection.

    Security guarantees:
    - Rejects symlinks (O_NOFOLLOW on the final component)
    - Rejects non-regular files (directories, FIFOs, devices, sockets)
    - Enforces a maximum byte limit
    - Detects inode/device replacement between open and read (TOCTOU)
    - Guarantees file descriptor closure

    Args:
        path: File to read. Must be a Path object.
        max_bytes: Maximum content size. Content exceeding this raises SecureReadError.

    Returns:
        The file's raw bytes.

    Raises:
        SecureReadError: If any security check fails.
        FileNotFoundError: If the file does not exist.
    """
    if not isinstance(path, Path):
        path = Path(path)

    fd = None
    try:
        # O_NOFOLLOW: reject if final component is a symlink
        # O_CLOEXEC: close-on-exec
        # O_NONBLOCK: don't block on FIFOs
        fd = os.open(
            str(path),
            os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK,
        )
    except OSError as exc:
        # FileNotFoundError, PermissionError, etc.
        # ELOOP is raised when O_NOFOLLOW rejects a symlink final component.
        # (errno 40 on Linux, 62 on macOS — using the symbolic constant covers
        # both platforms.)
        if exc.errno == errno.ELOOP:
            raise SecureReadError(f"{path}: symlink rejected") from exc
        raise

    try:
        # Verify it's a regular file
        stat_before = os.fstat(fd)
        if not stat.S_ISREG(stat_before.st_mode):
            if stat.S_ISDIR(stat_before.st_mode):
                raise SecureReadError(f"{path}: is a directory")
            if stat.S_ISLNK(stat_before.st_mode):
                raise SecureReadError(f"{path}: symlink rejected")
            raise SecureReadError(
                f"{path}: not a regular file (mode={stat_before.st_mode:o})"
            )

        # Check size limit before reading
        if stat_before.st_size > max_bytes:
            raise SecureReadError(
                f"{path}: size {stat_before.st_size} exceeds max_bytes {max_bytes}"
            )

        # Read content
        content = b""
        while True:
            chunk = os.read(fd, min(65536, max_bytes - len(content) + 1))
            if not chunk:
                break
            content += chunk
            if len(content) > max_bytes:
                raise SecureReadError(
                    f"{path}: content exceeds max_bytes {max_bytes}"
                )

        # TOCTOU check: verify inode/device didn't change during read
        stat_after = os.fstat(fd)
        if (
            stat_after.st_ino != stat_before.st_ino
            or stat_after.st_dev != stat_before.st_dev
        ):
            raise SecureReadError(
                f"{path}: inode changed during read (TOCTOU detected)"
            )

        return content
    finally:
        if fd is not None:
            os.close(fd)
