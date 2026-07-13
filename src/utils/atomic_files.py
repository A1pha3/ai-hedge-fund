"""Durable atomic file publication helpers."""

from __future__ import annotations

import json
import math
import os
import secrets
import stat
import tempfile
from pathlib import Path
from typing import Any

import pandas as pd


def _sanitize_nonfinite(value: Any) -> Any:
    if isinstance(value, float):
        return None if not math.isfinite(value) else value
    if isinstance(value, dict):
        return {key: _sanitize_nonfinite(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_sanitize_nonfinite(item) for item in value]
    return value


def _fsync_directory(path: Path) -> None:
    """Persist a directory entry update on platforms that support it."""
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    directory_fd: int | None = None
    try:
        directory_fd = os.open(path, flags)
        os.fsync(directory_fd)
    except OSError:
        pass
    finally:
        if directory_fd is not None:
            try:
                os.close(directory_fd)
            except OSError:
                pass


def _ordinary_new_file_mode(parent: Path) -> int:
    """Observe the process umask without temporarily changing global state."""
    while True:
        probe = parent / f".mode-{secrets.token_hex(8)}.tmp"
        try:
            fd = os.open(probe, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o666)
        except FileExistsError:
            continue
        try:
            return stat.S_IMODE(os.fstat(fd).st_mode)
        finally:
            try:
                os.close(fd)
            finally:
                try:
                    probe.unlink()
                except OSError:
                    pass


def _prepare_temp(target: Path) -> tuple[int, str]:
    mode = stat.S_IMODE(target.stat().st_mode) if target.exists() else _ordinary_new_file_mode(target.parent)
    fd, temp_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    try:
        os.fchmod(fd, mode)
    except BaseException:
        try:
            os.close(fd)
        except BaseException:
            pass
        try:
            os.unlink(temp_name)
        except BaseException:
            pass
        raise
    return fd, temp_name


def _reject_symlink(target: Path) -> None:
    if target.is_symlink():
        raise ValueError(f"refusing atomic write to symlink target: {target}")


def _open_temp(fd: int, temp_name: str, *, newline: str | None = None):
    try:
        return os.fdopen(fd, "w", encoding="utf-8", newline=newline)
    except BaseException:
        try:
            os.close(fd)
        finally:
            try:
                os.unlink(temp_name)
            except OSError:
                pass
        raise


def atomic_write_json(path: Path | str, payload: Any) -> None:
    """Write strict UTF-8 JSON and atomically publish it at *path*."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    _reject_symlink(target)
    fd, temp_name = _prepare_temp(target)
    try:
        with _open_temp(fd, temp_name) as file:
            json.dump(
                _sanitize_nonfinite(payload),
                file,
                ensure_ascii=False,
                indent=2,
                default=str,
                allow_nan=False,
            )
            file.flush()
            os.fsync(file.fileno())
        _reject_symlink(target)
        os.replace(temp_name, target)
        _fsync_directory(target.parent)
    except BaseException:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def atomic_write_csv(path: Path | str, frame: pd.DataFrame) -> None:
    """Write a pandas frame and atomically publish it at *path*."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    _reject_symlink(target)
    fd, temp_name = _prepare_temp(target)
    try:
        with _open_temp(fd, temp_name, newline="") as file:
            frame.to_csv(file, index=False)
            file.flush()
            os.fsync(file.fileno())
        _reject_symlink(target)
        os.replace(temp_name, target)
        _fsync_directory(target.parent)
    except BaseException:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise
