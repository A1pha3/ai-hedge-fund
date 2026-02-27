import logging
from dataclasses import dataclass
from typing import Any

from src.data.validation_rules import FINANCIAL_METRICS_RULES, ValidationRule

logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    """单个字段的验证结果"""

    is_valid: bool
    field: str
    value: Any
    rule: ValidationRule
    message: str


@dataclass
class ValidationReport:
    """批量验证报告"""

    total: int
    passed: int
    failed: int
    warnings: int
    pass_rate: float
    errors: list[dict[str, Any]]
    warnings_list: list[dict[str, Any]]


class EnhancedDataValidator:
    """增强型数据验证器

    提供多层验证机制：
    1. 范围验证：检查值是否在合理范围内
    2. 空值验证：检查必需字段是否为空
    3. 自定义验证：支持自定义验证函数
    """

    def __init__(self, rules: list[ValidationRule] | None = None):
        """初始化验证器

        Args:
            rules: 验证规则列表，默认使用财务指标规则
        """
        self.rules = {rule.field: rule for rule in (rules or FINANCIAL_METRICS_RULES)}

    def validate_metric(self, metric: Any) -> tuple[bool, list[ValidationResult]]:
        """验证单个指标对象

        Args:
            metric: 指标对象（支持对象属性或字典）

        Returns:
            (是否通过所有 error 级别验证, 验证结果列表)
        """
        results: list[ValidationResult] = []
        has_error = False

        for field_name, rule in self.rules.items():
            value = self._get_field_value(metric, field_name)

            if value is None or (isinstance(value, float) and self._is_nan(value)):
                if not rule.allow_null:
                    result = ValidationResult(
                        is_valid=False,
                        field=field_name,
                        value=value,
                        rule=rule,
                        message=f"{field_name} 不能为空",
                    )
                    results.append(result)
                    if rule.severity == "error":
                        has_error = True
                continue

            if rule.min_value is not None and value < rule.min_value:
                result = ValidationResult(
                    is_valid=False,
                    field=field_name,
                    value=value,
                    rule=rule,
                    message=f"{field_name}={value} 小于最小值 {rule.min_value}",
                )
                results.append(result)
                if rule.severity == "error":
                    has_error = True

            if rule.max_value is not None and value > rule.max_value:
                result = ValidationResult(
                    is_valid=False,
                    field=field_name,
                    value=value,
                    rule=rule,
                    message=f"{field_name}={value} 大于最大值 {rule.max_value}",
                )
                results.append(result)
                if rule.severity == "error":
                    has_error = True

            if rule.custom_validator and not rule.custom_validator(value):
                result = ValidationResult(
                    is_valid=False,
                    field=field_name,
                    value=value,
                    rule=rule,
                    message=f"{field_name}={value} 未通过自定义验证",
                )
                results.append(result)
                if rule.severity == "error":
                    has_error = True

        return not has_error, results

    def validate_batch(self, metrics: list[Any]) -> ValidationReport:
        """批量验证并生成报告

        Args:
            metrics: 指标列表

        Returns:
            验证报告
        """
        total = len(metrics)
        passed = 0
        failed = 0
        warnings = 0
        errors: list[dict[str, Any]] = []
        warnings_list: list[dict[str, Any]] = []

        for i, metric in enumerate(metrics):
            is_valid, results = self.validate_metric(metric)

            if is_valid:
                passed += 1
            else:
                failed += 1

            for result in results:
                if not result.is_valid:
                    item = {
                        "index": i,
                        "field": result.field,
                        "value": result.value,
                        "message": result.message,
                        "severity": result.rule.severity,
                    }
                    if result.rule.severity == "error":
                        errors.append(item)
                    else:
                        warnings_list.append(item)
                        warnings += 1

        return ValidationReport(
            total=total,
            passed=passed,
            failed=failed,
            warnings=warnings,
            pass_rate=passed / total if total > 0 else 0.0,
            errors=errors[:50],
            warnings_list=warnings_list[:50],
        )

    def filter_valid_metrics(self, metrics: list[Any], min_pass_rate: float = 0.8) -> tuple[list[Any], ValidationReport]:
        """过滤出有效的指标

        Args:
            metrics: 指标列表
            min_pass_rate: 最低通过率阈值

        Returns:
            (有效指标列表, 验证报告)
        """
        report = self.validate_batch(metrics)

        if report.pass_rate < min_pass_rate:
            logger.warning(f"数据质量过低: 通过率 {report.pass_rate:.2%}, " f"错误数 {len(report.errors)}, " f"警告数 {len(report.warnings_list)}")

        valid_metrics: list[Any] = []
        for metric in metrics:
            is_valid, _ = self.validate_metric(metric)
            if is_valid:
                valid_metrics.append(metric)

        return valid_metrics, report

    def _get_field_value(self, metric: Any, field_name: str) -> Any:
        """获取字段值，支持对象属性和字典"""
        if hasattr(metric, field_name):
            return getattr(metric, field_name)
        elif isinstance(metric, dict):
            return metric.get(field_name)
        return None

    def _is_nan(self, value: float) -> bool:
        """检查值是否为 NaN"""
        import math

        return math.isnan(value)


def validate_financial_metrics(metrics: list[Any], min_pass_rate: float = 0.8) -> tuple[list[Any], ValidationReport]:
    """验证财务指标的便捷函数

    Args:
        metrics: 财务指标列表
        min_pass_rate: 最低通过率阈值

    Returns:
        (有效指标列表, 验证报告)
    """
    validator = EnhancedDataValidator()
    return validator.filter_valid_metrics(metrics, min_pass_rate)
