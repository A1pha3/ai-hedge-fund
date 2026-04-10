from __future__ import annotations

from typing import Any, Callable


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

    if value is None or (isinstance(value, float) and is_nan(value)):
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
