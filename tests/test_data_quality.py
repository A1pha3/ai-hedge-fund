import pytest

from src.data.adapters.akshare_adapter import AKShareAdapter
from src.data.adapters.base import DataSourceAdapter
from src.data.adapters.tushare_adapter import TushareAdapter
from src.data.cleaner import OutlierDetector, SmartDataCleaner
from src.data.validation_rules import (
    FINANCIAL_METRICS_RULES,
    get_error_rules,
    get_rule_by_field,
    get_warning_rules,
)
from src.data.validator_v2 import EnhancedDataValidator


def create_metric_dict(**kwargs):
    """创建测试用的指标字典"""
    default = {
        "ticker": "600519",
        "report_period": "2024Q1",
        "period": "quarter",
        "currency": "CNY",
        "market_cap": None,
        "enterprise_value": None,
        "price_to_earnings_ratio": None,
        "price_to_book_ratio": None,
        "price_to_sales_ratio": None,
        "enterprise_value_to_ebitda_ratio": None,
        "enterprise_value_to_revenue_ratio": None,
        "free_cash_flow_yield": None,
        "peg_ratio": None,
        "gross_margin": None,
        "operating_margin": None,
        "net_margin": None,
        "return_on_equity": None,
        "return_on_assets": None,
        "return_on_invested_capital": None,
        "asset_turnover": None,
        "inventory_turnover": None,
        "receivables_turnover": None,
        "days_sales_outstanding": None,
        "operating_cycle": None,
        "working_capital_turnover": None,
        "current_ratio": None,
        "quick_ratio": None,
        "cash_ratio": None,
        "operating_cash_flow_ratio": None,
        "debt_to_equity": None,
        "debt_to_assets": None,
        "interest_coverage": None,
        "revenue_growth": None,
        "earnings_growth": None,
        "book_value_growth": None,
        "earnings_per_share_growth": None,
        "free_cash_flow_growth": None,
        "operating_income_growth": None,
        "ebitda_growth": None,
        "payout_ratio": None,
        "earnings_per_share": None,
        "book_value_per_share": None,
        "free_cash_flow_per_share": None,
    }
    default.update(kwargs)
    return default


class TestAKShareAdapter:
    """AKShare 适配器测试"""

    def test_roe_unit_conversion(self):
        """测试 ROE 单位转换：15.5% → 0.155"""
        adapter = AKShareAdapter()
        raw_data = {"净资产收益率": 15.5, "ticker": "600519"}
        result = adapter.adapt_financial_metrics(raw_data)

        assert result["return_on_equity"] == pytest.approx(0.155, rel=1e-3)

    def test_debt_to_equity_conversion(self):
        """测试资产负债率转换：45% → 0.45"""
        adapter = AKShareAdapter()
        raw_data = {"资产负债率": 45.0, "ticker": "600519"}
        result = adapter.adapt_financial_metrics(raw_data)

        assert result["debt_to_equity"] == pytest.approx(0.45, rel=1e-3)

    def test_revenue_conversion_wan_to_yuan(self):
        """测试收入单位转换：万元 → 元"""
        adapter = AKShareAdapter()
        raw_data = {"营业收入": 1000.0, "ticker": "600519"}
        result = adapter.adapt_financial_metrics(raw_data)

        assert result["revenue"] == 10000000.0

    def test_none_value_handling(self):
        """测试 None 值处理"""
        adapter = AKShareAdapter()
        raw_data = {"ticker": "600519", "净资产收益率": None}
        result = adapter.adapt_financial_metrics(raw_data)

        assert "return_on_equity" not in result or result.get("return_on_equity") is None

    def test_unit_conversion_rules(self):
        """测试单位转换规则完整性"""
        adapter = AKShareAdapter()
        rules = adapter.get_unit_conversion_rules()

        assert "return_on_equity" in rules
        assert rules["return_on_equity"] == 0.01
        assert rules["gross_margin"] == 0.01
        assert rules["current_ratio"] == 1.0


class TestTushareAdapter:
    """Tushare 适配器测试"""

    def test_roe_unit_conversion(self):
        """测试 ROE 单位转换：15.5% → 0.155"""
        adapter = TushareAdapter()
        raw_data = {"roe": 15.5, "ts_code": "600519.SH"}
        result = adapter.adapt_financial_metrics(raw_data)

        assert result["return_on_equity"] == pytest.approx(0.155, rel=1e-3)

    def test_ts_code_parsing(self):
        """测试 ts_code 解析"""
        adapter = TushareAdapter()
        raw_data = {"ts_code": "600519.SH", "roe": 10.0}
        result = adapter.adapt_financial_metrics(raw_data)

        assert result["ticker"] == "600519"

    def test_market_cap_conversion(self):
        """测试市值转换：万元 → 元"""
        adapter = TushareAdapter()
        raw_data = {"total_mv": 100000.0, "ts_code": "600519.SH"}
        result = adapter.adapt_financial_metrics(raw_data)

        assert result["market_cap"] == 1000000000.0


class TestValidationRules:
    """验证规则测试"""

    def test_get_rule_by_field(self):
        """测试根据字段名获取规则"""
        rule = get_rule_by_field("return_on_equity")

        assert rule is not None
        assert rule.field == "return_on_equity"
        assert rule.min_value == -2.0
        assert rule.max_value == 2.0

    def test_get_error_rules(self):
        """测试获取 error 级别规则"""
        rules = get_error_rules()

        assert len(rules) > 0
        for rule in rules:
            assert rule.severity == "error"

    def test_get_warning_rules(self):
        """测试获取 warning 级别规则"""
        rules = get_warning_rules()

        assert len(rules) > 0
        for rule in rules:
            assert rule.severity == "warning"

    def test_rules_completeness(self):
        """测试规则完整性"""
        required_fields = [
            "return_on_equity",
            "gross_margin",
            "net_margin",
            "debt_to_equity",
        ]

        for field in required_fields:
            rule = get_rule_by_field(field)
            assert rule is not None, f"缺少字段 {field} 的验证规则"


class TestEnhancedDataValidator:
    """增强验证器测试"""

    @pytest.fixture
    def validator(self):
        return EnhancedDataValidator()

    def test_valid_metric(self, validator):
        """测试有效指标验证"""
        metric = create_metric_dict(
            return_on_equity=0.15,
            gross_margin=0.30,
            net_margin=0.12,
        )

        is_valid, results = validator.validate_metric(metric)
        assert is_valid is True

    def test_invalid_roe_too_high(self, validator):
        """测试 ROE 过高验证失败"""
        metric = create_metric_dict(return_on_equity=5.19)

        is_valid, results = validator.validate_metric(metric)
        assert is_valid is False

        roe_errors = [r for r in results if r.field == "return_on_equity"]
        assert len(roe_errors) > 0

    def test_invalid_margin_too_high(self, validator):
        """测试利润率过高验证失败"""
        metric = create_metric_dict(net_margin=12.81)

        is_valid, results = validator.validate_metric(metric)
        assert is_valid is False

    def test_batch_validation(self, validator):
        """测试批量验证"""
        metrics = [
            create_metric_dict(return_on_equity=0.15),
            create_metric_dict(return_on_equity=5.19),
        ]

        report = validator.validate_batch(metrics)

        assert report.total == 2
        assert report.passed == 1
        assert report.failed == 1
        assert report.pass_rate == 0.5

    def test_filter_valid_metrics(self, validator):
        """测试过滤有效指标"""
        metrics = [
            create_metric_dict(return_on_equity=0.15),
            create_metric_dict(return_on_equity=5.19),
        ]

        valid_metrics, report = validator.filter_valid_metrics(metrics)

        assert len(valid_metrics) == 1
        assert valid_metrics[0]["return_on_equity"] == 0.15


class TestOutlierDetector:
    """异常值检测器测试"""

    def test_iqr_method(self):
        """测试 IQR 方法"""
        values = [1.0, 2.0, 3.0, 4.0, 5.0, 100.0]
        outliers = OutlierDetector.iqr_method(values)

        assert 5 in outliers

    def test_zscore_method(self):
        """测试 Z-Score 方法"""
        values = [1.0, 2.0, 3.0, 4.0, 5.0, 100.0]
        outliers = OutlierDetector.zscore_method(values, threshold=2.0)

        assert len(outliers) > 0

    def test_no_outliers(self):
        """测试无异常值情况"""
        values = [1.0, 2.0, 3.0, 4.0, 5.0]
        outliers = OutlierDetector.iqr_method(values)

        assert len(outliers) == 0


class TestSmartDataCleaner:
    """智能清洗器测试"""

    @pytest.fixture
    def cleaner(self):
        return SmartDataCleaner()

    def test_fix_unit_error_roe(self, cleaner):
        """测试 ROE 单位错误修正"""
        metrics = [create_metric_dict(return_on_equity=519.0)]

        fixed = cleaner.clean_dict_metrics(metrics, "600519")

        assert fixed[0]["return_on_equity"] == 5.19

    def test_fix_unit_error_margin(self, cleaner):
        """测试利润率单位错误修正"""
        metrics = [create_metric_dict(net_margin=12.81)]

        fixed = cleaner.clean_dict_metrics(metrics, "600519")

        assert fixed[0]["net_margin"] == 0.1281

    def test_no_fix_needed(self, cleaner):
        """测试无需修正情况"""
        metrics = [create_metric_dict(return_on_equity=0.15)]

        fixed = cleaner.clean_dict_metrics(metrics, "600519")

        assert fixed[0]["return_on_equity"] == 0.15


class TestIntegration:
    """集成测试"""

    def test_end_to_end_flow(self):
        """测试端到端数据流"""
        adapter = AKShareAdapter()
        validator = EnhancedDataValidator()
        cleaner = SmartDataCleaner()

        raw_data = {
            "ticker": "600519",
            "净资产收益率": 15.5,
            "销售净利率": 12.8,
        }

        adapted = adapter.adapt_financial_metrics(raw_data)

        assert adapted["return_on_equity"] == 0.155
        assert adapted["net_margin"] == 0.128

        metric = create_metric_dict(
            return_on_equity=adapted.get("return_on_equity"),
            net_margin=adapted.get("net_margin"),
        )

        is_valid, _ = validator.validate_metric(metric)
        assert is_valid is True

    def test_unit_error_detection_and_fix(self):
        """测试单位错误检测和修正"""
        adapter = AKShareAdapter()
        validator = EnhancedDataValidator()
        cleaner = SmartDataCleaner()

        raw_data = {"ticker": "600519", "净资产收益率": 1550.0}

        adapted = adapter.adapt_financial_metrics(raw_data)

        assert adapted["return_on_equity"] == 15.5

        metric = create_metric_dict(return_on_equity=15.5)

        is_valid, results = validator.validate_metric(metric)
        assert is_valid is False

        fixed = cleaner.clean_dict_metrics([metric], "600519")
        assert fixed[0]["return_on_equity"] == 0.155

        is_valid, _ = validator.validate_metric(fixed[0])
        assert is_valid is True
