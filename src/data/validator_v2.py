import logging
from dataclasses import dataclass
from typing import Any, Union

from src.data.models import FinancialMetrics, Price
from src.data.validation_rules import (
    FINANCIAL_METRICS_RULES,
    get_rules_for_data_type,
    PRICE_RULES,
    ValidationRule,
)
from src.data.validator_v2_helpers import evaluate_metric_rule

logger = logging.getLogger(__name__)

# Type aliases — validator accepts Pydantic models or raw dicts for both
# metrics and prices.  Keeping `Any` in the union for forward compat.
MetricRow = Union[FinancialMetrics, dict[str, Any]]
PriceRow = Union[Price, dict[str, Any]]


@dataclass
class ValidationResult:
    """单个字段的验证结果"""

    is_valid: bool
    field: str
    value: float | str | None
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

    R20 起新增 ``data_type`` 维度: ``"metrics"`` 走字段级 min/max 检查,
    ``"prices"`` 走行级 custom_validator (OHLC 一致性, 价格 / 成交量正负,
    未来日期等)。两种规则集互不重叠, 调用方按 data_type 切换。
    """

    def __init__(self, rules: list[ValidationRule] | None = None, data_type: str = "metrics"):
        """初始化验证器

        Args:
            rules: 验证规则列表; 不提供时按 ``data_type`` 取默认规则集。
            data_type: ``"metrics"`` (默认) 走财务指标字段级规则, ``"prices"``
                走价格行级规则。仅在 ``rules`` 未显式提供时生效。
        """
        if rules is None:
            rules = get_rules_for_data_type(data_type) or FINANCIAL_METRICS_RULES
        self.rules = {rule.field: rule for rule in rules}
        self.data_type = data_type

    def validate_metric(self, metric: MetricRow) -> tuple[bool, list[ValidationResult]]:
        """验证单个指标对象

        Args:
            metric: 指标对象（支持对象属性或字典）

        Returns:
            (是否通过所有 error 级别验证, 验证结果列表)
        """
        results: list[ValidationResult] = []
        has_error = False

        for field_name, rule in self.rules.items():
            # 价格规则: custom_validator 接收整行 row, field 名仅是虚拟标签。
            # 跳过 _get_field_value 否则会在 metric 上找不到 "price_ohlc_consistency"
            # 这种虚拟字段 → 全部返回 None → 误判通过。
            if self._is_row_level_rule(rule):
                field_results, field_has_error = self._evaluate_row_level_rule(
                    field_name=field_name,
                    rule=rule,
                    row=metric,
                )
                results.extend(field_results)
                has_error = has_error or field_has_error
                continue

            value = self._get_field_value(metric, field_name)
            field_results, field_has_error = evaluate_metric_rule(
                field_name=field_name,
                rule=rule,
                value=value,
                result_factory=ValidationResult,
                is_nan=self._is_nan,
            )
            results.extend(field_results)
            has_error = has_error or field_has_error

        return not has_error, results

    def validate_batch(self, metrics: list[MetricRow]) -> ValidationReport:
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

    def filter_valid_metrics(self, metrics: list[MetricRow], min_pass_rate: float = 0.8) -> tuple[list[MetricRow], ValidationReport]:
        """过滤出有效的指标

        Args:
            metrics: 指标列表
            min_pass_rate: 最低通过率阈值

        Returns:
            (有效指标列表, 验证报告)
        """
        # validate_batch already calls validate_metric for every metric and
        # records is_valid in the report.  We can reuse that result instead of
        # re-running N validations (N+1 problem).  Since the report doesn't
        # store per-metric validity, we pass through once more — but only to
        # collect the valid ones, not to re-validate.
        report = self.validate_batch(metrics)

        if report.pass_rate < min_pass_rate:
            logger.warning(f"数据质量过低: 通过率 {report.pass_rate:.2%}, " f"错误数 {len(report.errors)}, " f"警告数 {len(report.warnings_list)}")

        # Use the report's error set to identify invalid metric indices.
        # Errors are keyed by (index, field) — collect unique failing indices.
        failing_indices: set[int] = {e.get("index", -1) for e in report.errors}
        valid_metrics: list[MetricRow] = [metric for i, metric in enumerate(metrics) if i not in failing_indices]

        return valid_metrics, report

    def _get_field_value(self, metric: MetricRow, field_name: str) -> float | str | None:
        """获取字段值，支持对象属性和字典"""
        if hasattr(metric, field_name):
            return getattr(metric, field_name)
        if isinstance(metric, dict):
            return metric.get(field_name)
        return None

    @staticmethod
    def _is_row_level_rule(rule: ValidationRule) -> bool:
        """判断规则是否走行级路径 (custom_validator 接收整行 row 而非字段值).

        判定: 同时满足 (a) 无 min/max 范围 (b) 有 custom_validator (c) 注册在
        PRICE_RULES 里。这样既兼容 R20 新增的价格规则, 又不影响 R3-R19 财务规则
        的旧行为 (财务规则全部走 evaluate_metric_rule 字段级路径)。
        """
        if rule.min_value is not None or rule.max_value is not None:
            return False
        if rule.custom_validator is None:
            return False
        return any(r.field == rule.field for r in PRICE_RULES)

    @staticmethod
    def _evaluate_row_level_rule(
        *,
        field_name: str,
        rule: ValidationRule,
        row: MetricRow,
    ) -> tuple[list[ValidationResult], bool]:
        """行级规则评估: 整行 row 喂给 custom_validator, 失败时记一条结果。"""
        try:
            ok = bool(rule.custom_validator(row)) if rule.custom_validator else True
        except Exception as exc:  # custom validator 自身崩了等同于校验失败
            ok = False
            message = f"{field_name} 行级校验抛错: {exc}"
        else:
            message = "" if ok else f"{field_name} 行级校验未通过: {rule.description}"

        if ok:
            return [], False
        result = ValidationResult(
            is_valid=False,
            field=field_name,
            value=None,
            rule=rule,
            message=message,
        )
        return [result], rule.severity == "error"

    def _is_nan(self, value: float) -> bool:
        """检查值是否为 NaN"""
        import math

        return math.isnan(value)


def validate_financial_metrics(metrics: list[MetricRow], min_pass_rate: float = 0.8) -> tuple[list[MetricRow], ValidationReport]:
    """验证财务指标的便捷函数

    Args:
        metrics: 财务指标列表
        min_pass_rate: 最低通过率阈值

    Returns:
        (有效指标列表, 验证报告)
    """
    validator = EnhancedDataValidator()
    return validator.filter_valid_metrics(metrics, min_pass_rate)


def validate_prices(prices: list[PriceRow], min_pass_rate: float = 0.8) -> tuple[list[PriceRow], ValidationReport]:
    """验证价格行的便捷函数 (R20 新增).

    应用 PRICE_RULES 5 条价格类规则 (OHLC 一致性 / 价格正负 / 未来日期 /
    成交量非负 / 收盘价合理区间)。返回过滤后的有效价格行 + 验证报告。

    Args:
        prices: 价格行列表 (Price 对象或 dict, 需含 open/high/low/close/volume/time)
        min_pass_rate: 最低通过率阈值, 低于该阈值会打 warning

    Returns:
        (有效价格行列表, 验证报告)
    """
    validator = EnhancedDataValidator(data_type="prices")
    return validator.filter_valid_metrics(prices, min_pass_rate)
