"""Shared numeric utility functions.

Replaces duplicated ``_safe_float`` / ``_safe_int`` / ``_coerce_score_b`` /
``_is_finite_number`` / ``_clip`` / ``clamp_unit_interval`` helpers scattered
across the codebase (30+ call sites in Round 7-14 modules alone).

All helpers are pure functions with no side effects and no IO.
"""

from __future__ import annotations

import math
from typing import Any

# ---------------------------------------------------------------------------
# Core coercion helpers
# ---------------------------------------------------------------------------


def safe_float(value: Any, default: float = 0.0) -> float:
    """Safely coerce *value* to a finite ``float``.

    - ``None``, ``bool``, NaN, Inf, and non-numeric types -> ``default``
    - Otherwise returns ``float(value)``

    Why ``bool`` is rejected: ``float(True) == 1.0`` is almost never the
    intended behaviour when ingesting JSON / LLM responses.
    """
    if value is None or isinstance(value, bool):
        return default
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(out):
        return default
    return out


def safe_int(value: Any, default: int = 0) -> int:
    """Safely coerce *value* to ``int`` (via ``float`` to handle ``"3.0"``).

    - ``None``, NaN, Inf, and non-numeric types -> ``default``
    - Truncates towards zero (same as ``int()``)
    """
    if value is None:
        return default
    try:
        fv = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(fv):
        return default
    return int(fv)


def is_finite_number(value: Any) -> bool:
    """Return ``True`` if *value* can be converted to a finite ``float``."""
    if value is None:
        return False
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def coerce_score_b(value: Any) -> float:
    """Coerce a ``score_b`` value to a finite ``float`` in ``[-1.0, 1.0]``.

    Convenience wrapper around :func:`safe_float` with clamping.
    Returns ``0.0`` for any invalid input.
    """
    fv = safe_float(value, 0.0)
    return max(-1.0, min(1.0, fv))


def optional_float(value: Any) -> float | None:
    """Safely coerce *value* to a finite float or None.

    Returns None for any invalid input (None, NaN, Inf, non-numeric).
    Use when the caller needs to distinguish "missing" from "zero".
    """
    if value is None:
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(out):
        return None
    return out


# ---------------------------------------------------------------------------
# Interval helpers (pre-existing)
# ---------------------------------------------------------------------------


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


def clamp_confidence(value: Any) -> float:
    """Clamp *value* to ``[0.0, 100.0]`` (confidence / 百分比 scale).

    Handles ``None`` and non-finite floats (NaN, Inf) by returning ``0.0``.

    R152: 防止 ``max(0.0, min(100.0, float(value or 0.0)))`` 把 NaN escalate 到
    100.0 满分 — ``float(NaN or 0.0)`` = NaN (NaN 是 truthy, ``or`` 不兜底), 再
    ``min(100.0, NaN)`` 在 CPython 返回 100.0, 最后 max→100.0。sub_factors 内层
    dict / getattr 读取的 confidence 不经 Pydantic 校验, NaN 可达; escalate 后会让
    垃圾置信度的 sub_factor 通过 gate (merge_approved_breakout_uplift / layer_c /
    catalyst_diagnostics 同族)。invalid confidence = 无置信度 → 0.0 正确 fail gate。
    """
    if value is None:
        return 0.0
    try:
        as_float = float(value)
    except (ValueError, TypeError):
        return 0.0
    if not math.isfinite(as_float):
        return 0.0
    return max(0.0, min(100.0, as_float))
