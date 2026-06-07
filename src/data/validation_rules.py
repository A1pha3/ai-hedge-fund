from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any
from collections.abc import Callable


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
        min_value=-50.0,
        max_value=10.0,
        allow_null=True,
        severity="warning",
        description="资产负债率正常范围 -5000% 到 +1000%（负值表示负权益）",
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


# ---------------------------------------------------------------------------
# 价格类规则 (R20 新增 — R19 审查发现 16 条 metrics 规则全部针对财务指标,
# OHLC / volume / 日期 等价格类字段没有任何 validator 兜底。低质量价格会
# 直通技术指标 → 信号 → 组合，因此先加 5 条基础规则做硬门槛。)
# ---------------------------------------------------------------------------

# 价格类规则名（导出常量，供外部精确匹配 / 报告分类用）
RULE_OHLC_CONSISTENCY = "price_ohlc_consistency"  # high >= max(open,close), low <= min(open,close)
RULE_NO_NEGATIVE_PRICE = "price_no_negative"  # 所有价格 > 0
RULE_NO_FUTURE_DATE = "price_no_future_date"  # 日期 <= today
RULE_VOLUME_NON_NEGATIVE = "price_volume_non_negative"  # volume >= 0
RULE_PRICE_REASONABLE_RANGE = "price_reasonable_range"  # 0.01 <= close <= 10000


def _row_get(obj: Any, key: str) -> float | str | None:
    """Unified row field accessor — supports both dict and object attribute access.

    Extracted from 5 price-rule validators that each defined an identical local ``_get``
    (R20.1 DRY refactor).  Returns ``None`` when the key is missing rather than raising,
    so validators can safely skip absent fields.
    """
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)


def _ohlc_consistent(row: Any) -> bool:
    """OHLC 一致性: high >= max(open, close), low <= min(open, close).

    row 支持对象属性或 dict。任一字段缺失/非数值 → 默认通过 (由 RULE_NO_NEGATIVE_PRICE
    或 schema 校验拦截缺失场景), 避免把 schema 问题误判成 OHLC 不一致。
    """

    o, h, lo, c = _row_get(row, "open"), _row_get(row, "high"), _row_get(row, "low"), _row_get(row, "close")
    try:
        o_f, h_f, lo_f, c_f = float(o), float(h), float(lo), float(c)
    except (TypeError, ValueError):
        return True
    return h_f >= max(o_f, c_f) and lo_f <= min(o_f, c_f)


def _all_prices_positive(row: Any) -> bool:
    """所有价格字段 (open/high/low/close) > 0。缺失 → 默认通过, 由 schema 兜底。"""

    for key in ("open", "high", "low", "close"):
        v = _row_get(row, key)
        if v is None:
            continue
        try:
            if float(v) <= 0:
                return False
        except (TypeError, ValueError):
            return False
    return True


def _date_not_in_future(row: Any) -> bool:
    """日期 <= 今天 (UTC date)。

    row 必须有 `time` 字段 (Price 模型契约), 接受 ISO date / ISO datetime / date /
    datetime 几种形式。无法解析 → 默认通过 (schema 层会拒绝非法格式)。
    """

    t = _row_get(row, "time")
    if t is None:
        return True
    today = datetime.now(timezone.utc).date()
    if isinstance(t, datetime):
        return t.date() <= today
    if isinstance(t, date):
        return t <= today
    if isinstance(t, str):
        # 接受 "YYYY-MM-DD" 或 ISO datetime 前缀。
        try:
            parsed_date = date.fromisoformat(t[:10])
        except ValueError:
            return True
        return parsed_date <= today
    return True


def _volume_non_negative(row: Any) -> bool:
    """volume >= 0。缺失 → 默认通过。"""

    v = _row_get(row, "volume")
    if v is None:
        return True
    try:
        return float(v) >= 0
    except (TypeError, ValueError):
        return False


def _close_in_reasonable_range(row: Any) -> bool:
    """0.01 <= close <= 10000。

    A 股价格区间历史最大约 3000+ (贵州茅台), 港股仙股低至 ~0.01; 边界放宽到
    10000 / 0.01 兼容极端但不离谱的值, 真正异常 (浮点垃圾或单位错误) 会触发。
    """

    c = _row_get(row, "close")
    if c is None:
        return True
    try:
        c_f = float(c)
    except (TypeError, ValueError):
        return False
    return 0.01 <= c_f <= 10000.0


# 注意: 这些规则的 `field` 与 `custom_validator` 协同工作。当 `field` 是
# 行级别检查 (如 OHLC 一致性), validator 会把整个 row 传给 custom_validator;
# field 名仅作为报告里展示用的虚拟字段名, 避免与 FINANCIAL_METRICS_RULES
# 的字段冲突 (财务规则按 field 取值, 价格规则按 row 行验证)。
PRICE_RULES: list[ValidationRule] = [
    ValidationRule(
        field=RULE_OHLC_CONSISTENCY,
        custom_validator=_ohlc_consistent,
        severity="error",
        description="OHLC 一致性: high >= max(open,close), low <= min(open,close)",
    ),
    ValidationRule(
        field=RULE_NO_NEGATIVE_PRICE,
        custom_validator=_all_prices_positive,
        severity="error",
        description="所有价格 (open/high/low/close) 必须 > 0",
    ),
    ValidationRule(
        field=RULE_NO_FUTURE_DATE,
        custom_validator=_date_not_in_future,
        severity="error",
        description="价格日期不能晚于今天",
    ),
    ValidationRule(
        field=RULE_VOLUME_NON_NEGATIVE,
        custom_validator=_volume_non_negative,
        severity="error",
        description="成交量必须 >= 0",
    ),
    ValidationRule(
        field=RULE_PRICE_REASONABLE_RANGE,
        custom_validator=_close_in_reasonable_range,
        severity="warning",
        description="收盘价合理区间 0.01 <= close <= 10000",
    ),
]


def get_rule_by_field(field_name: str) -> ValidationRule | None:
    """根据字段名获取验证规则 (含财务指标与价格规则)

    Args:
        field_name: 字段名 / 规则名

    Returns:
        验证规则，如果不存在则返回 None
    """
    for rule in FINANCIAL_METRICS_RULES:
        if rule.field == field_name:
            return rule
    for rule in PRICE_RULES:
        if rule.field == field_name:
            return rule
    return None


def get_error_rules() -> list[ValidationRule]:
    """获取所有严重级别为 error 的规则 (含财务指标与价格规则)"""
    return [r for r in FINANCIAL_METRICS_RULES + PRICE_RULES if r.severity == "error"]


def get_warning_rules() -> list[ValidationRule]:
    """获取所有严重级别为 warning 的规则 (含财务指标与价格规则)"""
    return [r for r in FINANCIAL_METRICS_RULES + PRICE_RULES if r.severity == "warning"]


def get_rules_for_data_type(data_type: str) -> list[ValidationRule]:
    """按 data_type 取对应规则集.

    Args:
        data_type: "metrics" / "prices"

    Returns:
        规则列表 (未知 data_type 返回空列表 — 调用方应自行决定是否报错)
    """
    if data_type == "metrics":
        return list(FINANCIAL_METRICS_RULES)
    if data_type == "prices":
        return list(PRICE_RULES)
    return []
