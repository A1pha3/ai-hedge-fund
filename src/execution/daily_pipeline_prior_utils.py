"""Shared historical-prior field accessors.

Tiny helper functions used across daily_pipeline sub-modules
to safely extract typed values from historical prior dicts.
"""

from __future__ import annotations

from typing import Any


def historical_prior_float(prior: dict[str, Any], key: str) -> float | None:
    """Extract a float from a prior dict, returning None on missing/invalid."""
    value = prior.get(key)
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def historical_prior_int(prior: dict[str, Any], key: str) -> int | None:
    """Extract an int from a prior dict, returning None on missing/invalid."""
    value = prior.get(key)
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
