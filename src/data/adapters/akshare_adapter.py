from typing import Any

from src.data.adapters.base import DataSourceAdapter


class AKShareAdapter(DataSourceAdapter):
    """AKShare 数据源适配器

    AKShare 返回的数据格式说明：
    - 比率类指标：百分比格式（如 15.5 表示 15.5%）
    - 金额类指标：万元为单位
    """

    def adapt_financial_metrics(self, raw_data: dict[str, Any]) -> dict[str, Any]:
        """将 AKShare 原始数据转换为标准格式

        字段映射关系：
        - 净资产收益率 → return_on_equity
        - 资产负债率 → debt_to_assets (并推导 debt_to_equity)
        - 营业收入 → revenue (万元转元)
        - 净利润 → net_income (万元转元)

        GAMMA-017 修正: AKShare 的「资产负债率」是 debt-to-**assets** (D/A)
        比率，不是 debt-to-equity (D/E)。之前错误地把 D/A 当作 D/E 使用，
        导致下游 agents (michael_burry, warren_buffett 等) 低估杠杆水平约 45%。
        现在仅映射到 debt_to_assets，并从 D/A 推导 D/E = D/A / (1 - D/A)。
        """
        rules = self.get_unit_conversion_rules()
        adapted: dict[str, Any] = {}

        ticker = raw_data.get("ticker", raw_data.get("股票代码", ""))
        adapted["ticker"] = str(ticker) if ticker else ""

        report_period = raw_data.get("report_period", raw_data.get("报告期", ""))
        adapted["report_period"] = str(report_period) if report_period else ""

        period = raw_data.get("period", "annual")
        adapted["period"] = period

        currency = raw_data.get("currency", "CNY")
        adapted["currency"] = currency

        field_mappings = {
            "return_on_equity": ["净资产收益率", "return_on_equity", "roe"],
            # GAMMA-017: 资产负债率 (D/A) 只映射到 debt_to_assets。
            # debt_to_equity 不再从 D/A 直接取值——它在下方后处理中推导。
            "debt_to_equity": ["debt_to_equity"],
            "debt_to_assets": ["资产负债率", "debt_to_assets"],
            "gross_margin": ["销售毛利率", "gross_margin"],
            "operating_margin": ["营业利润率", "operating_margin"],
            "net_margin": ["销售净利率", "net_margin"],
            "revenue_growth": ["营业收入同比增长率", "revenue_growth", "q_sales_yoy"],
            "current_ratio": ["流动比率", "current_ratio"],
            "quick_ratio": ["速动比率", "quick_ratio"],
        }

        for standard_field, source_fields in field_mappings.items():
            value = None
            for source_field in source_fields:
                if source_field in raw_data and raw_data[source_field] is not None:
                    value = self.safe_float(raw_data[source_field])
                    if value is not None:
                        break

            if value is not None:
                multiplier = rules.get(standard_field, 1.0)
                adapted[standard_field] = self.apply_unit_conversion(value, multiplier)

        revenue = raw_data.get("营业收入") or raw_data.get("revenue")
        if revenue is not None:
            adapted["revenue"] = self.safe_float(revenue, 0) * 10000

        net_income = raw_data.get("净利润") or raw_data.get("net_income")
        if net_income is not None:
            adapted["net_income"] = self.safe_float(net_income, 0) * 10000

        market_cap = raw_data.get("总市值") or raw_data.get("market_cap")
        if market_cap is not None:
            adapted["market_cap"] = self.safe_float(market_cap, 0) * 10000

        # GAMMA-017: 推导 debt_to_equity from debt_to_assets。
        # D/E = D/A / (1 - D/A) = total_liabilities / total_equity
        # 仅当 debt_to_equity 未从直接来源获取时才推导。
        if "debt_to_equity" not in adapted and "debt_to_assets" in adapted:
            adapted["debt_to_equity"] = _derive_debt_to_equity_from_debt_to_assets(adapted["debt_to_assets"])

        return adapted


def _derive_debt_to_equity_from_debt_to_assets(debt_to_assets: float | None) -> float | None:
    """从 debt-to-assets 比率推导 debt-to-equity。

    数学等价: D/E = D/A / (1 - D/A) = total_liabilities / total_equity

    边界处理:
    - D/A = None or <= 0 → None (无负债或数据缺失)
    - D/A >= 1.0 → None (资不抵债，D/E 趋于无穷，无意义)
    - 0 < D/A < 1.0 → D/E = D/A / (1 - D/A)
    """
    if debt_to_assets is None or debt_to_assets <= 0:
        return None
    equity_ratio = 1.0 - debt_to_assets
    if equity_ratio <= 0:
        return None  # 资不抵债
    return round(debt_to_assets / equity_ratio, 4)

