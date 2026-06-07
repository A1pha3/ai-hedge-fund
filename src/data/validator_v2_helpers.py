from __future__ import annotations

import math
from typing import Any
from collections.abc import Callable

try:  # numpy is a hard dependency of the project (see pyproject.toml),
    # but we still guard the import so this helper degrades gracefully
    # in any minimal/test environment without it.
    import numpy as _np  # type: ignore

    _HAS_NUMPY = True
except Exception:  # pragma: no cover - numpy is always installed in this repo
    _np = None  # type: ignore[assignment]
    _HAS_NUMPY = False


# String forms of NaN / Inf that occasionally leak in from upstream feeds
# (pandas.to_csv with default na_rep="", JSON-encoded numeric columns from
# akshare / tushare scrapes that serialize NaN as the literal string "nan",
# etc.). These pass every min/max comparison silently and corrupt the
# data-quality gate, so they must be rejected the same way float NaN is.
_STRING_NAN_VALUES = frozenset(
    {
        "nan",
        "NaN",
        "NAN",
        "inf",
        "Inf",
        "INF",
        "+inf",
        "+Inf",
        "+INF",
        "-inf",
        "-Inf",
        "-INF",
        "infinity",
        "Infinity",
        "INFINITY",
        "+infinity",
        "+Infinity",
        "+INFINITY",
        "-infinity",
        "-Infinity",
        "-INFINITY",
    }
)


def _is_invalid_value(value: Any) -> bool:
    """Return True if ``value`` must be rejected by the validator.

    Catches all of: ``float('nan')``, ``float('inf')``, numpy NaN / Inf
    (regardless of numpy version), and string forms ``"NaN"`` / ``"nan"``
    / ``"Infinity"`` / ``"-inf"`` etc. that occasionally leak in from
    upstream CSV / JSON serialization. ``None``, ``bool``, ``int``, and
    legitimate numeric strings are NOT considered invalid — None is
    handled by ``allow_null`` upstream, and string casting is the
    caller's responsibility.
    """
    if value is None:
        return False  # None is handled by allow_null upstream
    if isinstance(value, bool):
        return False  # bool is not a numeric value here
    if isinstance(value, float):
        return math.isnan(value) or math.isinf(value)
    if isinstance(value, int):
        return False  # int cannot be NaN/Inf
    if _HAS_NUMPY:
        # Use duck typing via numpy scalars: np.float64(nan) is *not*
        # always isinstance(float) on every numpy version, so check the
        # numpy hierarchy explicitly. np.bool_ inherits from np.generic
        # but must be excluded the same way Python bool is.
        if isinstance(value, _np.bool_):  # type: ignore[union-attr]
            return False
        if isinstance(value, _np.floating):  # type: ignore[union-attr]
            return bool(_np.isnan(value)) or bool(_np.isinf(value))  # type: ignore[union-attr]
        if isinstance(value, _np.integer):  # type: ignore[union-attr]
            return False
    if isinstance(value, str):
        stripped = value.strip()
        if stripped in _STRING_NAN_VALUES:
            return True
        return False
    return False


def evaluate_metric_rule(
    *,
    field_name: str,
    rule,
    value: Any,
    result_factory: Callable[..., Any],
    is_nan: Callable[[float], bool],
) -> tuple[list[Any], bool]:
    results: list[Any] = []
    has_error = False

    if value is None:
        if not rule.allow_null:
            results.append(
                result_factory(
                    is_valid=False,
                    field=field_name,
                    value=value,
                    rule=rule,
                    message=f"{field_name} 不能为空",
                )
            )
            has_error = rule.severity == "error"
        return results, has_error

    if _is_invalid_value(value):
        # NaN / Inf (in any form: native float, numpy scalar, or string
        # "NaN" / "Infinity" / "-inf" etc.) are NOT the same as null —
        # they are corrupt data that silently passes every min/max
        # comparison (NaN comparisons are always False). Reject as an
        # error regardless of allow_null, so the data-quality gate
        # stops bad numbers from reaching the portfolio / scoring layer.
        results.append(
            result_factory(
                is_valid=False,
                field=field_name,
                value=value,
                rule=rule,
                message=f"{field_name} 为非有限值 (NaN/Inf), 拒绝接受",
            )
        )
        has_error = has_error or rule.severity == "error"
        return results, has_error

    if rule.min_value is not None and value < rule.min_value:
        results.append(
            result_factory(
                is_valid=False,
                field=field_name,
                value=value,
                rule=rule,
                message=f"{field_name}={value} 小于最小值 {rule.min_value}",
            )
        )
        has_error = has_error or rule.severity == "error"

    if rule.max_value is not None and value > rule.max_value:
        results.append(
            result_factory(
                is_valid=False,
                field=field_name,
                value=value,
                rule=rule,
                message=f"{field_name}={value} 大于最大值 {rule.max_value}",
            )
        )
        has_error = has_error or rule.severity == "error"

    if rule.custom_validator and not rule.custom_validator(value):
        results.append(
            result_factory(
                is_valid=False,
                field=field_name,
                value=value,
                rule=rule,
                message=f"{field_name}={value} 未通过自定义验证",
            )
        )
        has_error = has_error or rule.severity == "error"

    return results, has_error
