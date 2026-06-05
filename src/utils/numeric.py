"""Shared numeric utility functions.

Replaces duplicated ``_clip`` and ``clamp_unit_interval`` helpers
scattered across the codebase.
"""

from __future__ import annotations

import math
from typing import Any


def clip(value: float, lower: float, upper: float) -> float:
    """Clamp *value* to the closed interval ``[lower, upper]``.

    Non-finite inputs (NaN, Inf) map to *lower*.
    """
    if not math.isfinite(value):
        return lower
    return max(lower, min(upper, value))


def clamp_unit_interval(value: Any) -> float:
    """Clamp *value* to ``[0.0, 1.0]``.

    Handles ``None`` and non-finite floats by returning ``0.0``.
    """
    if value is None:
        return 0.0
    try:
        as_float = float(value)
    except (ValueError, TypeError):
        return 0.0
    if not math.isfinite(as_float):
        return 0.0
    return max(0.0, min(1.0, as_float))
