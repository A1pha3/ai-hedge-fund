from abc import ABC, abstractmethod
from typing import Any

# Default unit conversion rules for A-share data sources.
# Both AKShare and Tushare return ratios in percentage format (e.g. 15.5 = 15.5%).
_ASHARE_UNIT_CONVERSION_RULES: dict[str, float] = {
    "return_on_equity": 0.01,
    "return_on_assets": 0.01,
    "debt_to_equity": 0.01,
    "debt_to_assets": 0.01,
    "gross_margin": 0.01,
    "operating_margin": 0.01,
    "net_margin": 0.01,
    "revenue_growth": 0.01,
    "earnings_growth": 0.01,
    "book_value_growth": 0.01,
    "earnings_per_share_growth": 0.01,
    "free_cash_flow_growth": 0.01,
    "operating_income_growth": 0.01,
    "ebitda_growth": 0.01,
    "current_ratio": 1.0,
    "quick_ratio": 1.0,
    "cash_ratio": 1.0,
    "interest_coverage": 1.0,
    "asset_turnover": 1.0,
    "inventory_turnover": 1.0,
    "receivables_turnover": 1.0,
    "payout_ratio": 0.01,
}


class DataSourceAdapter(ABC):
    """数据源适配器基类

    用于统一不同数据源的数据格式，确保输出一致性。
    所有比率类指标统一转换为小数格式（如 15.5% → 0.155）。
    """

    @abstractmethod
    def adapt_financial_metrics(self, raw_data: dict[str, Any]) -> dict[str, Any]:
        """将原始财务数据转换为标准格式

        Args:
            raw_data: 原始数据字典，字段名取决于数据源

        Returns:
            标准化后的数据字典，字段名与 FinancialMetrics 模型一致
        """

    def get_unit_conversion_rules(self) -> dict[str, float]:
        """返回单位转换规则

        Returns:
            {field: multiplier} 字段到乘数的映射
            例如: {"return_on_equity": 0.01} 表示值需要乘以 0.01
        """
        return dict(_ASHARE_UNIT_CONVERSION_RULES)

    def apply_unit_conversion(self, value: float | None, multiplier: float) -> float | None:
        """应用单位转换

        Args:
            value: 原始值
            multiplier: 乘数

        Returns:
            转换后的值，如果输入为 None 则返回 None
        """
        if value is None:
            return None
        return value * multiplier

    def safe_float(self, value: Any, default: float | None = None) -> float | None:
        """安全转换为浮点数

        Args:
            value: 任意类型的值
            default: 转换失败时的默认值

        Returns:
            转换后的浮点数或默认值
        """
        if value is None:
            return default
        try:
            result = float(value)
            return result if result != 0 else default
        except (ValueError, TypeError):
            return default
