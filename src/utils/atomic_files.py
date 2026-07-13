"""Durable, descriptor-relative atomic publication helpers."""

from __future__ import annotations

import errno
import json
import math
import os
import secrets
import stat
import sys
from pathlib import Path
from typing import Any, Callable

import pandas as pd


def _sanitize_nonfinite(value: Any) -> Any:
    if isinstance(value, float):
        return None if not math.isfinite(value) else value
    if isinstance(value, dict):
        return {key: _sanitize_nonfinite(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_sanitize_nonfinite(item) for item in value]
    return value


def _open_parent(target: Path) -> int:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(target.parent, flags)
    if not stat.S_ISDIR(os.fstat(fd).st_mode):
        os.close(fd)
        raise ValueError(f"atomic write parent is not a directory: {target.parent}")
    return fd


def _target_mode(parent_fd: int, name: str) -> int:
    try:
        held = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        # O_CREAT applies the process umask atomically; fstat observes the result.
        return 0o666
    if stat.S_ISLNK(held.st_mode):
        raise ValueError(f"refusing atomic write to symlink target: {name}")
    if not stat.S_ISREG(held.st_mode):
        raise ValueError(f"refusing atomic write to non-regular target: {name}")
    return stat.S_IMODE(held.st_mode)


def _create_temp(parent_fd: int, target_name: str, requested_mode: int) -> tuple[int, str]:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    while True:
        name = f".{target_name}.{secrets.token_hex(12)}.tmp"
        try:
            fd = os.open(name, flags, requested_mode, dir_fd=parent_fd)
            break
        except FileExistsError:
            continue
    try:
        # Existing targets require exact mode preservation. New files retain umask result.
        if requested_mode != 0o666:
            os.fchmod(fd, requested_mode)
        return fd, name
    except BaseException:
        try:
            os.close(fd)
        except BaseException:
            pass
        try:
            os.unlink(name, dir_fd=parent_fd)
        except BaseException:
            pass
        raise


def _atomic_write(path: Path | str, writer: Callable[[Any], None], *, newline: str | None = None) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    parent_fd = _open_parent(target)
    temp_name: str | None = None
    published = False
    try:
        mode = _target_mode(parent_fd, target.name)
        raw_fd, temp_name = _create_temp(parent_fd, target.name, mode)
        try:
            file = os.fdopen(raw_fd, "w", encoding="utf-8", newline=newline)
        except BaseException:
            try:
                os.close(raw_fd)
            except BaseException:
                pass
            try:
                os.unlink(temp_name, dir_fd=parent_fd)
            except BaseException:
                pass
            temp_name = None
            raise
        with file:
            writer(file)
            file.flush()
            os.fsync(file.fileno())
        # Revalidate while holding the same parent directory identity.
        _target_mode(parent_fd, target.name)
        os.replace(temp_name, target.name, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
        published = True
        temp_name = None
        try:
            os.fsync(parent_fd)
        except OSError as exc:
            # Some filesystems/platforms explicitly report directory fsync unsupported.
            if exc.errno not in {errno.EINVAL, errno.ENOTSUP, getattr(errno, "EOPNOTSUPP", errno.ENOTSUP)}:
                raise
    finally:
        active_error = sys.exc_info()[0] is not None
        if temp_name is not None and not published:
            try:
                os.unlink(temp_name, dir_fd=parent_fd)
            except BaseException:
                pass
        try:
            os.close(parent_fd)
        except BaseException:
            if not active_error:
                raise


def atomic_write_json(path: Path | str, payload: Any) -> None:
    def write(file: Any) -> None:
        json.dump(_sanitize_nonfinite(payload), file, ensure_ascii=False, indent=2,
                  default=str, allow_nan=False)
    _atomic_write(path, write)


def atomic_write_csv(path: Path | str, frame: pd.DataFrame) -> None:
    _atomic_write(path, lambda file: frame.to_csv(file, index=False), newline="")
