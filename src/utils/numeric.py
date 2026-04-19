"""Shared numeric utility functions.

Replaces duplicated ``_clip`` and ``clamp_unit_interval`` helpers
scattered across the codebase.
"""

from __future__ import annotations


def clip(value: float, lower: float, upper: float) -> float:
    """Clamp *value* to the closed interval ``[lower, upper]``."""
    return max(lower, min(upper, value))


def clamp_unit_interval(value: float) -> float:
    """Clamp *value* to ``[0.0, 1.0]``."""
    return max(0.0, min(1.0, float(value or 0.0)))
