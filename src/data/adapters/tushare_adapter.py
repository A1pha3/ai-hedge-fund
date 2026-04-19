from typing import Any

from src.data.adapters.base import DataSourceAdapter


class TushareAdapter(DataSourceAdapter):
    """Tushare 数据源适配器

    Tushare fina_indicator 接口返回格式说明：
    - 比率类指标：百分比格式（如 15.5 表示 15.5%）
    - 市值：万元为单位
    """

    def adapt_financial_metrics(self, raw_data: dict[str, Any]) -> dict[str, Any]:
        """将 Tushare 原始数据转换为标准格式

        字段映射关系（Tushare fina_indicator 接口）：
        - roe → return_on_equity
        - debt_to_assets → debt_to_equity
        - q_sales_yoy → revenue_growth
        - total_mv → market_cap (万元转元)
        """
        rules = self.get_unit_conversion_rules()
        adapted: dict[str, Any] = {}

        ts_code = raw_data.get("ts_code", raw_data.get("ticker", ""))
        if "." in str(ts_code):
            ticker = str(ts_code).split(".")[0]
        else:
            ticker = str(ts_code) if ts_code else ""
        adapted["ticker"] = ticker

        ann_date = raw_data.get("ann_date", raw_data.get("end_date", ""))
        adapted["report_period"] = str(ann_date) if ann_date else ""

        period = raw_data.get("period", "annual")
        adapted["period"] = period

        currency = raw_data.get("currency", "CNY")
        adapted["currency"] = currency

        field_mappings = {
            "return_on_equity": ["roe", "return_on_equity"],
            "return_on_assets": ["roa", "return_on_assets"],
            "debt_to_equity": ["debt_to_eqt", "debt_to_equity"],
            "debt_to_assets": ["debt_to_assets"],
            "gross_margin": ["grossprofit_margin", "gross_margin"],
            "operating_margin": ["op_of_gr", "operating_margin"],
            "net_margin": ["netprofit_margin", "net_margin"],
            "revenue_growth": ["q_sales_yoy", "revenue_growth"],
            "earnings_growth": ["q_profit_yoy", "earnings_growth"],
            "current_ratio": ["current_ratio"],
            "quick_ratio": ["quick_ratio"],
            "interest_coverage": ["interestcover", "interest_coverage"],
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

        total_mv = raw_data.get("total_mv") or raw_data.get("market_cap")
        if total_mv is not None:
            adapted["market_cap"] = self.safe_float(total_mv, 0) * 10000

        total_revenue = raw_data.get("total_revenue") or raw_data.get("revenue")
        if total_revenue is not None:
            adapted["revenue"] = self.safe_float(total_revenue, 0) * 10000

        net_profit = raw_data.get("net_profit") or raw_data.get("net_income")
        if net_profit is not None:
            adapted["net_income"] = self.safe_float(net_profit, 0) * 10000

        return adapted
