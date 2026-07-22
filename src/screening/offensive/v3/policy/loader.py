"""Secure, environment-independent loading for one v3 policy JSON file."""

from __future__ import annotations

from collections.abc import Iterable
from contextlib import contextmanager, ExitStack
from decimal import Decimal
import json
import os
from pathlib import Path
import stat
from typing import Any, Iterator

from pydantic import ValidationError

from .models import PolicySnapshot

MAX_POLICY_FILE_BYTES = 1024 * 1024


class PolicyLoadError(ValueError):
    """The supplied policy file is not a secure, supported policy snapshot."""


def _reject_duplicate_keys(pairs: Iterable[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise PolicyLoadError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _required_descriptor_flag(name: str) -> int:
    value = getattr(os, name, None)
    if not isinstance(value, int) or value == 0:
        raise PolicyLoadError(f"required descriptor safety flag is unavailable: {name}")
    return value


@contextmanager
def _owned_descriptor(descriptor: int) -> Iterator[int]:
    """Close one descriptor without replacing an error already in flight."""

    try:
        yield descriptor
    except BaseException as primary_error:
        try:
            os.close(descriptor)
        except OSError as close_error:
            primary_error.add_note(
                f"also failed to close policy descriptor: {close_error}"
            )
        raise
    else:
        try:
            os.close(descriptor)
        except OSError as exc:
            raise PolicyLoadError("unable to close policy descriptor") from exc


def _read_regular_file(path: str | os.PathLike[str]) -> bytes:
    try:
        parsed_path = Path(os.fspath(path))
    except (OSError, TypeError, ValueError) as exc:
        raise PolicyLoadError(
            "policy path must name one non-symlink regular file"
        ) from exc

    path_parts = parsed_path.parts
    if parsed_path.is_absolute():
        directory_path = path_parts[0]
        components = path_parts[1:]
    else:
        directory_path = "."
        components = path_parts
    if not components:
        raise PolicyLoadError("policy path must name one non-symlink regular file")

    nofollow = _required_descriptor_flag("O_NOFOLLOW")
    directory = _required_descriptor_flag("O_DIRECTORY")
    cloexec = _required_descriptor_flag("O_CLOEXEC")
    nonblock = _required_descriptor_flag("O_NONBLOCK")
    directory_flags = os.O_RDONLY | cloexec | directory | nofollow
    file_flags = os.O_RDONLY | cloexec | nofollow | nonblock
    try:
        directory_descriptor = os.open(directory_path, directory_flags)
    except (OSError, TypeError, ValueError) as exc:
        raise PolicyLoadError("policy path must name one non-symlink regular file") from exc

    with ExitStack() as descriptors:
        directory_descriptor = descriptors.enter_context(
            _owned_descriptor(directory_descriptor)
        )
        try:
            for component in components[:-1]:
                next_descriptor = os.open(
                    component,
                    directory_flags,
                    dir_fd=directory_descriptor,
                )
                next_descriptor = descriptors.enter_context(
                    _owned_descriptor(next_descriptor)
                )
                if not stat.S_ISDIR(os.fstat(next_descriptor).st_mode):
                    raise PolicyLoadError(
                        "policy parent must be a non-symlink directory"
                    )
                directory_descriptor = next_descriptor
            descriptor = os.open(
                components[-1],
                file_flags,
                dir_fd=directory_descriptor,
            )
            descriptor = descriptors.enter_context(_owned_descriptor(descriptor))
        except PolicyLoadError:
            raise
        except (OSError, TypeError, ValueError) as exc:
            raise PolicyLoadError("policy path must contain no symlinks") from exc

        try:
            before = os.fstat(descriptor)
            if not stat.S_ISREG(before.st_mode):
                raise PolicyLoadError("policy path must name one regular file")
            if before.st_size > MAX_POLICY_FILE_BYTES:
                raise PolicyLoadError("policy file is too large")
            chunks: list[bytes] = []
            bytes_read = 0
            while chunk := os.read(descriptor, 64 * 1024):
                chunks.append(chunk)
                bytes_read += len(chunk)
                if bytes_read > MAX_POLICY_FILE_BYTES:
                    raise PolicyLoadError("policy file is too large")
            payload = b"".join(chunks)
            after = os.fstat(descriptor)
            unchanged_fields = (
                "st_dev",
                "st_ino",
                "st_size",
                "st_mtime_ns",
                "st_ctime_ns",
            )
            if (
                any(
                    getattr(before, field) != getattr(after, field)
                    for field in unchanged_fields
                )
                or len(payload) != before.st_size
            ):
                raise PolicyLoadError("policy file changed while it was being read")
            return payload
        except OSError as exc:
            raise PolicyLoadError("unable to read policy regular file") from exc


def load_policy_snapshot(path: str | os.PathLike[str] | Path) -> PolicySnapshot:
    """Load exactly one regular JSON file without consulting process environment."""

    payload = _read_regular_file(path)
    try:
        json.loads(
            payload,
            parse_float=Decimal,
            parse_int=int,
            object_pairs_hook=_reject_duplicate_keys,
        )
    except PolicyLoadError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise PolicyLoadError("policy file must contain one valid JSON value") from exc

    try:
        return PolicySnapshot.model_validate_json(payload, strict=True)
    except ValidationError as exc:
        raise PolicyLoadError(f"invalid policy snapshot: {exc}") from exc


__all__ = ["MAX_POLICY_FILE_BYTES", "PolicyLoadError", "load_policy_snapshot"]
