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
        - 资产负债率 → debt_to_equity
        - 营业收入 → revenue (万元转元)
        - 净利润 → net_income (万元转元)
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
            "debt_to_equity": ["资产负债率", "debt_to_equity", "debt_to_assets"],
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

        return adapted
