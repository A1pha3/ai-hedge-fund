import numpy as np
import pytest

from src.data.adapters.akshare_adapter import AKShareAdapter
from src.data.adapters.tushare_adapter import TushareAdapter
from src.data.cleaner import OutlierDetector, SmartDataCleaner
from src.data.validation_rules import (
    get_error_rules,
    get_rule_by_field,
    get_rules_for_data_type,
    get_warning_rules,
    PRICE_RULES,
    RULE_NO_FUTURE_DATE,
    RULE_NO_NEGATIVE_PRICE,
    RULE_OHLC_CONSISTENCY,
    RULE_PRICE_REASONABLE_RANGE,
    RULE_VOLUME_NON_NEGATIVE,
)
from src.data.validator_v2 import EnhancedDataValidator, validate_prices
from src.data.validator_v2_helpers import _is_invalid_value


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
        """GAMMA-017: 资产负债率 (D/A) 正确映射到 debt_to_assets，
        并推导出 debt_to_equity = D/A / (1 - D/A)。

        资产负债率=45% → debt_to_assets=0.45, debt_to_equity=0.45/0.55≈0.818
        之前错误地把 D/A 直接用作 D/E (0.45)，低估杠杆约 45%。
        """
        adapter = AKShareAdapter()
        raw_data = {"资产负债率": 45.0, "ticker": "600519"}
        result = adapter.adapt_financial_metrics(raw_data)

        # debt_to_assets 直接映射（正确）
        assert result["debt_to_assets"] == pytest.approx(0.45, rel=1e-3)
        # debt_to_equity 从 D/A 推导（D/A / (1-D/A)）
        assert result["debt_to_equity"] == pytest.approx(0.8182, rel=1e-3)

    def test_debt_to_equity_edge_cases(self):
        """GAMMA-017: debt_to_equity 推导的边界条件"""
        from src.data.adapters.akshare_adapter import (
            _derive_debt_to_equity_from_debt_to_assets,
        )

        # D/A = 0 → None (无负债)
        assert _derive_debt_to_equity_from_debt_to_assets(0.0) is None
        # D/A < 0 → None (异常数据)
        assert _derive_debt_to_equity_from_debt_to_assets(-0.1) is None
        # D/A = 1.0 → None (资不抵债临界点)
        assert _derive_debt_to_equity_from_debt_to_assets(1.0) is None
        # D/A > 1.0 → None (负权益)
        assert _derive_debt_to_equity_from_debt_to_assets(1.2) is None
        # D/A = 0.5 → D/E = 1.0 (负债 = 权益)
        assert _derive_debt_to_equity_from_debt_to_assets(0.5) == 1.0
        # D/E 恒 > D/A (对于 0 < D/A < 1)
        for da in (0.1, 0.3, 0.5, 0.7, 0.9):
            de = _derive_debt_to_equity_from_debt_to_assets(da)
            assert de is not None and de > da

    def test_direct_debt_to_equity_takes_priority(self):
        """GAMMA-017: 直接来源的 debt_to_equity 优先于推导"""
        adapter = AKShareAdapter()
        raw_data = {"debt_to_equity": 50.0, "资产负债率": 45.0, "ticker": "600519"}
        result = adapter.adapt_financial_metrics(raw_data)

        # 直接 debt_to_equity=50% → 0.5 (乘以 0.01)，不推导
        assert result["debt_to_equity"] == pytest.approx(0.5, rel=1e-3)
        assert result["debt_to_assets"] == pytest.approx(0.45, rel=1e-3)

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

    def test_nan_value_is_rejected_even_when_allow_null(self, validator):
        """NaN values must be rejected by validation.

        All FINANCIAL_METRICS_RULES have allow_null=True, so a NaN that is
        not technically None would silently pass min/max checks (every NaN
        comparison is False). This is a data-quality gate regression:
        corrupt upstream data would propagate to portfolio decisions
        without any signal.
        """
        metric = create_metric_dict(
            return_on_equity=float("nan"),
            gross_margin=0.30,
            net_margin=0.12,
        )

        is_valid, results = validator.validate_metric(metric)

        assert is_valid is False
        nan_failures = [r for r in results if r.field == "return_on_equity" and not r.is_valid]
        assert len(nan_failures) > 0, "NaN must trigger a validation failure"

    def test_inf_value_is_rejected_even_when_allow_null(self, validator):
        """Inf values must be rejected by validation, same rationale as NaN.

        Use a metric that would otherwise pass range checks (debt_to_assets
        ∈ [0, 1]) to make sure the rejection comes from the non-finite
        guard, not from range overflow. Because debt_to_assets is a
        warning-severity rule, the rejection is recorded as a warning,
        not an error — verify both the failure record and the warning
        classification.
        """
        metric = create_metric_dict(
            return_on_equity=0.15,
            gross_margin=0.30,
            net_margin=0.12,
            debt_to_assets=float("inf"),
        )

        _, results = validator.validate_metric(metric)
        inf_failures = [r for r in results if r.field == "debt_to_assets" and not r.is_valid]
        assert len(inf_failures) > 0, "Inf must trigger a validation failure"

    def test_inf_value_on_error_severity_rule_makes_metric_invalid(self, validator):
        """Inf on an error-severity rule (return_on_equity) must make the
        entire metric invalid — risk-budget data must be clean."""
        metric = create_metric_dict(
            return_on_equity=float("inf"),
            gross_margin=0.30,
            net_margin=0.12,
        )

        is_valid, results = validator.validate_metric(metric)

        assert is_valid is False
        inf_failures = [r for r in results if r.field == "return_on_equity" and not r.is_valid]
        assert len(inf_failures) > 0, "Inf on error-severity rule must fail the metric"

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


class TestStringNaNDefense:
    """validator_v2_helpers._is_invalid_value 字符串 NaN/Inf 防御 (R18 / GAMMA-012 补丁).

    Round 15 拦截了 float NaN/Inf，但 R16 审查发现仍有缺口:
    上游 CSV/JSON 偶尔会把 NaN/Inf 序列化为字符串 "nan"/"NaN"/"Infinity"/"-inf" 等,
    而 numpy 的 np.float64(nan) 在某些 numpy 版本上不再 isinstance(float).
    这些值如果只用 isinstance(value, float) + math.isnan 检查都会逃逸,
    最终带着 NaN 一路传到组合 / 评分层。
    """

    def test_string_nan_uppercase_is_rejected(self):
        """字符串 'NaN' 必须被拒绝。"""
        assert _is_invalid_value("NaN") is True

    def test_string_nan_lowercase_is_rejected(self):
        """字符串 'nan' (pandas 默认 NaN 序列化形式) 必须被拒绝。"""
        assert _is_invalid_value("nan") is True

    def test_string_infinity_is_rejected(self):
        """字符串 'Infinity' (JSON.stringify NaN 后的形式) 必须被拒绝。"""
        assert _is_invalid_value("Infinity") is True

    def test_string_negative_inf_is_rejected(self):
        """字符串 '-inf' 必须被拒绝。"""
        assert _is_invalid_value("-inf") is True

    def test_string_inf_short_form_is_rejected(self):
        """字符串 'inf' 必须被拒绝。"""
        assert _is_invalid_value("inf") is True

    def test_string_nan_with_whitespace_is_rejected(self):
        """字符串 '  NaN  ' (带空白) 必须被拒绝, strip 后匹配。"""
        assert _is_invalid_value("  NaN  ") is True

    def test_empty_string_is_not_rejected(self):
        """空字符串不属于 NaN, 由 allow_null / 上游清洗控制。"""
        assert _is_invalid_value("") is False

    def test_numeric_string_is_not_rejected(self):
        """合法数字字符串 '123' 不被本函数拒绝 (上游类型转换的职责)。"""
        assert _is_invalid_value("123") is False

    def test_arbitrary_string_is_not_rejected(self):
        """非 NaN 形式的普通字符串不应被拒绝。"""
        assert _is_invalid_value("hello") is False

    def test_numpy_nan_is_rejected(self):
        """np.nan (顶层 float) 必须被拒绝。"""
        assert _is_invalid_value(np.nan) is True

    def test_numpy_float64_nan_is_rejected(self):
        """np.float64(nan) 即使 numpy 版本不再 isinstance(float) 也必须被拒绝。"""
        assert _is_invalid_value(np.float64("nan")) is True

    def test_numpy_float64_inf_is_rejected(self):
        """np.float64(inf) 必须被拒绝。"""
        assert _is_invalid_value(np.float64("inf")) is True

    def test_numpy_float32_nan_is_rejected(self):
        """np.float32(nan) 也是 numpy 浮点子类, 必须被拒绝。"""
        assert _is_invalid_value(np.float32("nan")) is True

    def test_numpy_finite_value_is_not_rejected(self):
        """numpy 上的合法有限值不应被拒绝。"""
        assert _is_invalid_value(np.float64(0.15)) is False
        assert _is_invalid_value(np.int64(42)) is False

    def test_none_is_not_rejected_by_invalid_value(self):
        """None 由 allow_null 上游控制, 此函数不视为 invalid。"""
        assert _is_invalid_value(None) is False

    def test_bool_is_not_rejected(self):
        """bool 不是数值, 不应被本函数判定为 invalid。"""
        assert _is_invalid_value(True) is False
        assert _is_invalid_value(False) is False

    def test_int_is_not_rejected(self):
        """整数永远不可能是 NaN/Inf。"""
        assert _is_invalid_value(0) is False
        assert _is_invalid_value(42) is False
        assert _is_invalid_value(-1) is False

    def test_finite_float_is_not_rejected(self):
        """合法的有限 float 不应被拒绝。"""
        assert _is_invalid_value(0.0) is False
        assert _is_invalid_value(3.14) is False
        assert _is_invalid_value(-2.71) is False

    def test_native_float_nan_still_rejected(self):
        """回归检查: 原有的 float('nan') 拦截路径仍然工作。"""
        assert _is_invalid_value(float("nan")) is True

    def test_native_float_inf_still_rejected(self):
        """回归检查: 原有的 float('inf') / -inf 拦截路径仍然工作。"""
        assert _is_invalid_value(float("inf")) is True
        assert _is_invalid_value(float("-inf")) is True

    def test_string_nan_via_validator_is_rejected(self):
        """端到端: 字符串 'NaN' 通过 EnhancedDataValidator 时也会被拒绝。

        这是 GAMMA-012 R18 补丁的核心保证 — 哪怕上游适配器忘了类型转换,
        把 "NaN" 直接灌进 metric dict, 数据质量门也能拦住。
        """
        validator = EnhancedDataValidator()
        metric = create_metric_dict(
            return_on_equity="NaN",
            gross_margin=0.30,
            net_margin=0.12,
        )

        is_valid, results = validator.validate_metric(metric)

        assert is_valid is False
        nan_failures = [r for r in results if r.field == "return_on_equity" and not r.is_valid]
        assert len(nan_failures) > 0, "字符串 NaN 必须被验证器拦截"


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


class TestPriceValidatorRules:
    """R20 价格类 validator 规则测试.

    R19 审查发现 16 条 metrics 规则全部针对财务指标, 价格类 (OHLC / volume /
    日期) 没有任何 validator 兜底; 低质量价格直通到技术指标 → 信号 → 组合。
    R20 新增 5 条价格规则做硬门槛, 这里覆盖每条规则的正反例 + 注册表完整性。
    """

    @pytest.fixture
    def price_validator(self):
        return EnhancedDataValidator(data_type="prices")

    @staticmethod
    def _make_price(**overrides):
        """构造一条合法价格行作为测试基线, 调用方按需 override 个别字段."""
        base = {
            "ticker": "600519",
            "open": 100.0,
            "high": 105.0,
            "low": 98.0,
            "close": 102.0,
            "volume": 1_000_000,
            "time": "2026-05-30",
        }
        base.update(overrides)
        return base

    # ------- 规则注册表完整性 --------------------------------------------

    def test_price_rules_registry_contains_all_five(self):
        """PRICE_RULES 应当注册 5 条规则, 与 R20 设计对齐."""
        assert len(PRICE_RULES) == 5
        names = {r.field for r in PRICE_RULES}
        assert names == {
            RULE_OHLC_CONSISTENCY,
            RULE_NO_NEGATIVE_PRICE,
            RULE_NO_FUTURE_DATE,
            RULE_VOLUME_NON_NEGATIVE,
            RULE_PRICE_REASONABLE_RANGE,
        }

    def test_get_rules_for_data_type_prices(self):
        """get_rules_for_data_type('prices') 应当返回 PRICE_RULES 全集."""
        rules = get_rules_for_data_type("prices")
        assert len(rules) == 5
        assert {r.field for r in rules} == {r.field for r in PRICE_RULES}

    def test_get_rule_by_field_finds_price_rule(self):
        """price 规则可通过 get_rule_by_field 查询."""
        rule = get_rule_by_field(RULE_OHLC_CONSISTENCY)
        assert rule is not None
        assert rule.severity == "error"

    def test_get_error_rules_includes_price_errors(self):
        """get_error_rules 应当同时包含财务 error 规则与价格 error 规则."""
        error_fields = {r.field for r in get_error_rules()}
        # 4 条 error 级价格规则 (OHLC / 负价格 / 未来日期 / 负成交量) 都在
        assert RULE_OHLC_CONSISTENCY in error_fields
        assert RULE_NO_NEGATIVE_PRICE in error_fields
        assert RULE_NO_FUTURE_DATE in error_fields
        assert RULE_VOLUME_NON_NEGATIVE in error_fields

    def test_get_warning_rules_includes_reasonable_range(self):
        """合理价格区间属 warning 级 (允许极端但不离谱的边界)."""
        warning_fields = {r.field for r in get_warning_rules()}
        assert RULE_PRICE_REASONABLE_RANGE in warning_fields

    # ------- 单条规则验证: 失败用例 --------------------------------------

    def test_ohlc_inconsistency_high_below_open_fails(self, price_validator):
        """OHLC 一致性: high < open → 校验失败."""
        bad_row = self._make_price(open=100.0, high=99.0, low=95.0, close=98.0)
        is_valid, results = price_validator.validate_metric(bad_row)
        assert is_valid is False
        assert any(r.field == RULE_OHLC_CONSISTENCY and not r.is_valid for r in results)

    def test_ohlc_inconsistency_low_above_close_fails(self, price_validator):
        """OHLC 一致性: low > close → 校验失败."""
        bad_row = self._make_price(open=100.0, high=105.0, low=103.0, close=101.0)
        is_valid, results = price_validator.validate_metric(bad_row)
        assert is_valid is False
        assert any(r.field == RULE_OHLC_CONSISTENCY and not r.is_valid for r in results)

    def test_negative_price_fails(self, price_validator):
        """所有价格必须 > 0: close 为负 → 失败."""
        bad_row = self._make_price(close=-1.0, low=-2.0)
        is_valid, results = price_validator.validate_metric(bad_row)
        assert is_valid is False
        assert any(r.field == RULE_NO_NEGATIVE_PRICE and not r.is_valid for r in results)

    def test_zero_price_fails(self, price_validator):
        """价格 == 0 也属非法 (停牌应当无 row, 不是 0 价)."""
        bad_row = self._make_price(open=0.0)
        is_valid, results = price_validator.validate_metric(bad_row)
        assert is_valid is False
        assert any(r.field == RULE_NO_NEGATIVE_PRICE and not r.is_valid for r in results)

    def test_future_date_fails(self, price_validator):
        """未来日期 → 校验失败 (10 年后)."""
        bad_row = self._make_price(time="2036-01-01")
        is_valid, results = price_validator.validate_metric(bad_row)
        assert is_valid is False
        assert any(r.field == RULE_NO_FUTURE_DATE and not r.is_valid for r in results)

    def test_negative_volume_fails(self, price_validator):
        """负成交量 → 校验失败."""
        bad_row = self._make_price(volume=-100)
        is_valid, results = price_validator.validate_metric(bad_row)
        assert is_valid is False
        assert any(r.field == RULE_VOLUME_NON_NEGATIVE and not r.is_valid for r in results)

    def test_close_below_reasonable_range_warns(self, price_validator):
        """close=0.001 低于合理区间下界 0.01 → 出现 warning 级失败 (不影响 is_valid)."""
        edge_row = self._make_price(close=0.001, low=0.001, open=0.001, high=0.002)
        # 负价格规则要求 > 0, 0.001 满足; 仅触发合理区间 warning。
        is_valid, results = price_validator.validate_metric(edge_row)
        # warning 级规则不让 is_valid 翻为 False
        assert is_valid is True
        assert any(r.field == RULE_PRICE_REASONABLE_RANGE and not r.is_valid for r in results)

    def test_close_above_reasonable_range_warns(self, price_validator):
        """close=99999 超出合理区间上界 10000 → warning 级失败."""
        edge_row = self._make_price(close=99999.0, low=98000.0, open=98500.0, high=99999.0)
        is_valid, results = price_validator.validate_metric(edge_row)
        assert is_valid is True
        assert any(r.field == RULE_PRICE_REASONABLE_RANGE and not r.is_valid for r in results)

    # ------- 合法用例: 必须放行 ------------------------------------------

    def test_valid_price_row_passes(self, price_validator):
        """合法价格行 → 全部规则通过."""
        good_row = self._make_price()
        is_valid, results = price_validator.validate_metric(good_row)
        assert is_valid is True
        # 也不应触发任何 warning 级失败
        assert not any(not r.is_valid for r in results)

    def test_today_date_passes(self, price_validator):
        """今天日期 → 不算未来日期, 必须通过."""
        from datetime import datetime, timezone

        today = datetime.now(timezone.utc).date().isoformat()
        good_row = self._make_price(time=today)
        is_valid, results = price_validator.validate_metric(good_row)
        assert is_valid is True

    # ------- 批量入口 ----------------------------------------------------

    def test_validate_prices_helper_filters_invalid(self):
        """validate_prices 便捷函数: 过滤掉非法行, 保留合法行."""
        rows = [
            self._make_price(close=102.0),  # ok
            self._make_price(close=-5.0, low=-10.0),  # 负价格 → 失败
            self._make_price(time="2099-12-31"),  # 未来日期 → 失败
        ]
        valid, report = validate_prices(rows, min_pass_rate=0.0)
        assert report.total == 3
        assert len(valid) == 1
        assert valid[0]["close"] == 102.0

    def test_validate_prices_batch_report_records_errors(self):
        """批量验证: 错误条目落到 report.errors, warning 落到 warnings_list."""
        rows = [
            self._make_price(close=-1.0, low=-2.0),  # error: 负价格
            self._make_price(close=99999.0, low=98000.0, open=98500.0, high=99999.0),  # warning: 超区间
        ]
        _, report = validate_prices(rows, min_pass_rate=0.0)
        # 至少一条 error (负价格), 至少一条 warning (合理区间)
        assert len(report.errors) >= 1
        assert any(e["field"] == RULE_NO_NEGATIVE_PRICE for e in report.errors)
        assert len(report.warnings_list) >= 1
        assert any(w["field"] == RULE_PRICE_REASONABLE_RANGE for w in report.warnings_list)

    def test_default_validator_does_not_apply_price_rules(self):
        """回归保护: 默认 (metrics) validator 不应误用价格规则, 否则普通 metric
        dict 会因为缺 OHLC 字段被误判失败。"""
        validator = EnhancedDataValidator()
        metric = create_metric_dict(return_on_equity=0.15, gross_margin=0.30, net_margin=0.12)
        is_valid, results = validator.validate_metric(metric)
        assert is_valid is True
        # 结果里不应含任何价格规则的 field
        price_rule_names = {r.field for r in PRICE_RULES}
        assert not any(r.field in price_rule_names for r in results)
