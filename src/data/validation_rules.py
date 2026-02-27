from dataclasses import dataclass
from typing import Any, Callable


@dataclass
class ValidationRule:
    """验证规则定义"""

    field: str
    min_value: float | None = None
    max_value: float | None = None
    allow_null: bool = True
    custom_validator: Callable[[Any], bool] | None = None
    severity: str = "error"
    description: str = ""


FINANCIAL_METRICS_RULES: list[ValidationRule] = [
    ValidationRule(
        field="return_on_equity",
        min_value=-2.0,
        max_value=2.0,
        allow_null=True,
        severity="error",
        description="ROE 正常范围 -200% 到 +200%",
    ),
    ValidationRule(
        field="return_on_assets",
        min_value=-1.0,
        max_value=1.0,
        allow_null=True,
        severity="error",
        description="ROA 正常范围 -100% 到 +100%",
    ),
    ValidationRule(
        field="gross_margin",
        min_value=-0.5,
        max_value=1.0,
        allow_null=True,
        severity="error",
        description="毛利率正常范围 -50% 到 +100%",
    ),
    ValidationRule(
        field="operating_margin",
        min_value=-0.5,
        max_value=1.0,
        allow_null=True,
        severity="error",
        description="营业利润率正常范围 -50% 到 +100%",
    ),
    ValidationRule(
        field="net_margin",
        min_value=-0.5,
        max_value=1.0,
        allow_null=True,
        severity="error",
        description="净利率正常范围 -50% 到 +100%",
    ),
    ValidationRule(
        field="debt_to_equity",
        min_value=0.0,
        max_value=10.0,
        allow_null=True,
        severity="warning",
        description="资产负债率正常范围 0% 到 1000%",
    ),
    ValidationRule(
        field="debt_to_assets",
        min_value=0.0,
        max_value=1.0,
        allow_null=True,
        severity="warning",
        description="资产负债比正常范围 0 到 100%",
    ),
    ValidationRule(
        field="current_ratio",
        min_value=0.0,
        max_value=50.0,
        allow_null=True,
        severity="warning",
        description="流动比率正常范围 0 到 50",
    ),
    ValidationRule(
        field="quick_ratio",
        min_value=0.0,
        max_value=50.0,
        allow_null=True,
        severity="warning",
        description="速动比率正常范围 0 到 50",
    ),
    ValidationRule(
        field="cash_ratio",
        min_value=0.0,
        max_value=50.0,
        allow_null=True,
        severity="warning",
        description="现金比率正常范围 0 到 50",
    ),
    ValidationRule(
        field="revenue_growth",
        min_value=-1.0,
        max_value=10.0,
        allow_null=True,
        severity="warning",
        description="收入增长率正常范围 -100% 到 +1000%",
    ),
    ValidationRule(
        field="earnings_growth",
        min_value=-1.0,
        max_value=10.0,
        allow_null=True,
        severity="warning",
        description="盈利增长率正常范围 -100% 到 +1000%",
    ),
    ValidationRule(
        field="price_to_earnings_ratio",
        min_value=0.0,
        max_value=1000.0,
        allow_null=True,
        severity="warning",
        description="市盈率正常范围 0 到 1000",
    ),
    ValidationRule(
        field="price_to_book_ratio",
        min_value=0.0,
        max_value=100.0,
        allow_null=True,
        severity="warning",
        description="市净率正常范围 0 到 100",
    ),
    ValidationRule(
        field="price_to_sales_ratio",
        min_value=0.0,
        max_value=100.0,
        allow_null=True,
        severity="warning",
        description="市销率正常范围 0 到 100",
    ),
    ValidationRule(
        field="market_cap",
        min_value=0.0,
        max_value=None,
        allow_null=True,
        severity="warning",
        description="市值必须为非负数",
    ),
]


def get_rule_by_field(field_name: str) -> ValidationRule | None:
    """根据字段名获取验证规则

    Args:
        field_name: 字段名

    Returns:
        验证规则，如果不存在则返回 None
    """
    for rule in FINANCIAL_METRICS_RULES:
        if rule.field == field_name:
            return rule
    return None


def get_error_rules() -> list[ValidationRule]:
    """获取所有严重级别为 error 的规则"""
    return [r for r in FINANCIAL_METRICS_RULES if r.severity == "error"]


def get_warning_rules() -> list[ValidationRule]:
    """获取所有严重级别为 warning 的规则"""
    return [r for r in FINANCIAL_METRICS_RULES if r.severity == "warning"]
