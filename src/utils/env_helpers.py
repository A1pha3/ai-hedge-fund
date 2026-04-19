"""Centralized environment variable parsing utilities.

Replaces duplicated `_get_env_float` / `_get_env_int` / etc. helpers
that were previously defined inline in 7+ modules.
"""

from __future__ import annotations

import os


def get_env_float(name: str, default: float) -> float:
    """Parse a float from an environment variable, falling back to *default*."""
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    try:
        return float(raw_value)
    except ValueError:
        return default


def get_env_int(name: str, default: int) -> int:
    """Parse an int from an environment variable, falling back to *default*."""
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    try:
        return int(raw_value)
    except ValueError:
        return default


def get_env_csv_set(name: str, default: str) -> set[str]:
    """Parse a comma-separated env var into a ``set[str]``."""
    raw_value = os.getenv(name, default)
    return {item.strip() for item in str(raw_value or "").split(",") if item.strip()}


def get_env_csv_list(name: str, default: str) -> list[str]:
    """Parse a comma-separated env var into a ``list[str]``."""
    raw_value = os.getenv(name, default)
    return [item.strip() for item in str(raw_value or "").split(",") if item.strip()]


def get_env_flag(name: str, default: bool = False) -> bool:
    """Parse a boolean flag from an environment variable.

    Truthy values: ``1``, ``true``, ``yes``, ``on`` (case-insensitive).
    """
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


def get_env_mode(name: str, default: str) -> str:
    """Parse a string mode from an environment variable, falling back to *default*."""
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    value = raw_value.strip().lower()
    return value or default
