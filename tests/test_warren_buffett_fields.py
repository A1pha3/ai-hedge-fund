from types import SimpleNamespace

from src.agents.warren_buffett import (
    analyze_book_value_growth,
    analyze_consistency,
    analyze_fundamentals,
    analyze_moat,
    analyze_pricing_power,
    calculate_intrinsic_value,
    calculate_owner_earnings,
    estimate_maintenance_capex,
)
from src.agents.warren_buffett_helpers import _resolve_buffett_working_capital_change


def test_calculate_intrinsic_value_handles_missing_outstanding_shares_field():
    financial_line_items = [
        SimpleNamespace(net_income=100.0, depreciation_and_amortization=20.0, capital_expenditure=-10.0, revenue=500.0),
        SimpleNamespace(net_income=90.0, depreciation_and_amortization=18.0, capital_expenditure=-9.0, revenue=450.0, outstanding_shares=10.0),
        SimpleNamespace(net_income=80.0, depreciation_and_amortization=16.0, capital_expenditure=-8.0, revenue=400.0),
    ]

    result = calculate_intrinsic_value(financial_line_items, currency_symbol="$")

    assert result["intrinsic_value"] is not None
    assert result["intrinsic_value"] > 0


def test_calculate_intrinsic_value_returns_expected_payload_for_positive_owner_earnings():
    financial_line_items = [
        SimpleNamespace(net_income=100.0, depreciation_and_amortization=20.0, capital_expenditure=-10.0, revenue=500.0, outstanding_shares=10.0),
        SimpleNamespace(net_income=90.0, depreciation_and_amortization=18.0, capital_expenditure=-9.0, revenue=450.0, outstanding_shares=10.0),
        SimpleNamespace(net_income=80.0, depreciation_and_amortization=16.0, capital_expenditure=-8.0, revenue=400.0, outstanding_shares=10.0),
    ]

    result = calculate_intrinsic_value(financial_line_items, currency_symbol="$")

    assert result["intrinsic_value"] == 1684.916195598013
    assert result["raw_intrinsic_value"] == 1982.2543477623683
    assert result["owner_earnings"] == 110.0
    assert result["assumptions"] == {
        "stage1_growth": 0.08,
        "stage2_growth": 0.04,
        "terminal_growth": 0.025,
        "discount_rate": 0.1,
        "stage1_years": 5,
        "stage2_years": 5,
        "historical_growth": 0.08262379212492643,
    }
    assert result["details"] == [
        "Using three-stage DCF: Stage 1 (8.0%, 5y), Stage 2 (4.0%, 5y), Terminal (2.5%)",
        "Stage 1 PV: $521",
        "Stage 2 PV: $425",
        "Terminal PV: $1,036",
        "Total IV: $1,982",
        "Conservative IV (15% haircut): $1,685",
        "Owner earnings: $110",
        "Discount rate: 10.0%",
    ]


def test_calculate_intrinsic_value_keeps_negative_owner_earnings_as_negative_dcf_output():
    financial_line_items = [
        SimpleNamespace(net_income=-10.0, depreciation_and_amortization=5.0, capital_expenditure=-2.0, revenue=100.0, outstanding_shares=10.0),
        SimpleNamespace(net_income=-20.0, depreciation_and_amortization=5.0, capital_expenditure=-2.0, revenue=100.0, outstanding_shares=10.0),
        SimpleNamespace(net_income=-30.0, depreciation_and_amortization=5.0, capital_expenditure=-2.0, revenue=100.0, outstanding_shares=10.0),
    ]

    result = calculate_intrinsic_value(financial_line_items, currency_symbol="$")

    assert result["intrinsic_value"] == -80.61632563674831
    assert result["raw_intrinsic_value"] == -94.84273604323332
    assert result["owner_earnings"] == -7.0
    assert result["assumptions"] == {
        "stage1_growth": 0.03,
        "stage2_growth": 0.015,
        "terminal_growth": 0.025,
        "discount_rate": 0.1,
        "stage1_years": 5,
        "stage2_years": 5,
        "historical_growth": 0.03,
    }
    assert result["details"] == [
        "Using three-stage DCF: Stage 1 (3.0%, 5y), Stage 2 (1.5%, 5y), Terminal (2.5%)",
        "Stage 1 PV: $-29",
        "Stage 2 PV: $-20",
        "Terminal PV: $-46",
        "Total IV: $-95",
        "Conservative IV (15% haircut): $-81",
        "Owner earnings: $-7",
        "Discount rate: 10.0%",
    ]


def test_calculate_owner_earnings_uses_historical_depreciation_and_working_capital_adjustment():
    financial_line_items = [
        SimpleNamespace(net_income=100.0, depreciation_and_amortization=None, capital_expenditure=-50.0, current_assets=200.0, current_liabilities=80.0),
        SimpleNamespace(net_income=90.0, depreciation_and_amortization=30.0, capital_expenditure=-40.0, revenue=400.0, current_assets=180.0, current_liabilities=70.0),
        SimpleNamespace(net_income=80.0, depreciation_and_amortization=25.0, capital_expenditure=-35.0, revenue=350.0),
    ]

    result = calculate_owner_earnings(financial_line_items, currency_symbol="$")

    assert result["owner_earnings"] == 77.5
    assert result["components"] == {
        "net_income": 100.0,
        "depreciation": 30.0,
        "maintenance_capex": 42.5,
        "working_capital_change": 10.0,
        "total_capex": 50.0,
    }
    assert result["details"] == [
        "Note: Using historical depreciation as fallback (¥30)",
        "Working capital change: $10",
        "Net income: $100",
        "Depreciation: $30",
        "Estimated maintenance capex: $42",
        "Owner earnings: $78",
    ]


def test_calculate_owner_earnings_estimates_depreciation_from_capex_when_history_is_missing():
    financial_line_items = [
        SimpleNamespace(net_income=100.0, depreciation_and_amortization=None, capital_expenditure=-20.0),
        SimpleNamespace(net_income=90.0, depreciation_and_amortization=None, capital_expenditure=-18.0, revenue=450.0),
    ]

    result = calculate_owner_earnings(financial_line_items, currency_symbol="$")

    assert result["owner_earnings"] == 95.0
    assert result["components"] == {
        "net_income": 100.0,
        "depreciation": 12.0,
        "maintenance_capex": 17.0,
        "working_capital_change": 0,
        "total_capex": 20.0,
    }
    assert result["details"] == [
        "Note: Estimated depreciation as 60% of capex (¥12)",
        "Net income: $100",
        "Depreciation: $12",
        "Estimated maintenance capex: $17",
        "Owner earnings: $95",
    ]


def test_calculate_owner_earnings_reports_missing_components_after_fallbacks():
    financial_line_items = [
        SimpleNamespace(net_income=None, depreciation_and_amortization=None, capital_expenditure=None),
        SimpleNamespace(net_income=90.0, depreciation_and_amortization=None, capital_expenditure=None),
    ]

    result = calculate_owner_earnings(financial_line_items, currency_symbol="$")

    assert result == {
        "owner_earnings": None,
        "details": ["Missing components: net income, depreciation, capital expenditure"],
    }


def test_estimate_maintenance_capex_uses_median_when_historical_capex_ratios_are_available():
    financial_line_items = [
        SimpleNamespace(capital_expenditure=-50.0, revenue=500.0, depreciation_and_amortization=30.0),
        SimpleNamespace(capital_expenditure=-40.0, revenue=400.0, depreciation_and_amortization=28.0),
        SimpleNamespace(capital_expenditure=-30.0, revenue=300.0, depreciation_and_amortization=26.0),
    ]

    result = estimate_maintenance_capex(financial_line_items)

    assert result == 42.5


def test_estimate_maintenance_capex_falls_back_to_higher_of_capex_and_depreciation_methods():
    financial_line_items = [
        SimpleNamespace(capital_expenditure=-20.0, revenue=200.0, depreciation_and_amortization=12.0),
        SimpleNamespace(capital_expenditure=None, revenue=150.0, depreciation_and_amortization=None),
    ]

    result = estimate_maintenance_capex(financial_line_items)

    assert result == 17.0


def test_estimate_maintenance_capex_returns_zero_for_empty_inputs():
    assert estimate_maintenance_capex([]) == 0


def test_analyze_fundamentals_preserves_high_quality_and_missing_metric_paths():
    strong_metrics = [
        SimpleNamespace(
            return_on_equity=0.18,
            debt_to_equity=0.3,
            operating_margin=0.2,
            current_ratio=1.8,
            model_dump=lambda: {"return_on_equity": 0.18, "debt_to_equity": 0.3, "operating_margin": 0.2, "current_ratio": 1.8},
        )
    ]
    missing_metrics = [
        SimpleNamespace(
            return_on_equity=None,
            debt_to_equity=None,
            operating_margin=None,
            current_ratio=None,
            model_dump=lambda: {"return_on_equity": None, "debt_to_equity": None, "operating_margin": None, "current_ratio": None},
        )
    ]

    assert analyze_fundamentals(strong_metrics) == {
        "score": 7,
        "details": "Strong ROE of 18.0%; Conservative debt levels; Strong operating margins; Good liquidity position",
        "metrics": {"return_on_equity": 0.18, "debt_to_equity": 0.3, "operating_margin": 0.2, "current_ratio": 1.8},
    }
    assert analyze_fundamentals(missing_metrics) == {
        "score": 0,
        "details": "ROE data not available; Debt to equity data not available; Operating margin data not available; Current ratio data not available",
        "metrics": {"return_on_equity": None, "debt_to_equity": None, "operating_margin": None, "current_ratio": None},
    }


def test_analyze_consistency_preserves_growth_and_insufficient_earnings_paths():
    consistent_financials = [
        SimpleNamespace(net_income=130.0),
        SimpleNamespace(net_income=110.0),
        SimpleNamespace(net_income=90.0),
        SimpleNamespace(net_income=70.0),
    ]
    sparse_financials = [
        SimpleNamespace(net_income=130.0),
        SimpleNamespace(net_income=None),
        SimpleNamespace(net_income=90.0),
        SimpleNamespace(net_income=None),
    ]

    assert analyze_consistency(consistent_financials) == {
        "score": 3,
        "details": "Consistent earnings growth over past periods",
    }
    assert analyze_consistency(sparse_financials) == {
        "score": 0,
        "details": "Insufficient earnings data for trend analysis",
    }


def test_analyze_book_value_growth_skips_items_without_share_count():
    financial_line_items = [
        SimpleNamespace(shareholders_equity=300.0),
        SimpleNamespace(shareholders_equity=240.0, outstanding_shares=10.0),
        SimpleNamespace(shareholders_equity=200.0, outstanding_shares=10.0),
        SimpleNamespace(shareholders_equity=150.0, outstanding_shares=10.0),
    ]

    result = analyze_book_value_growth(financial_line_items)

    assert result["score"] >= 0
    assert "Insufficient" not in result["details"]


def test_analyze_moat_scores_high_roe_margin_efficiency_and_stability():
    metrics = [
        SimpleNamespace(return_on_equity=0.22, return_on_invested_capital=0.18, operating_margin=0.24, asset_turnover=1.2),
        SimpleNamespace(return_on_equity=0.21, return_on_invested_capital=0.17, operating_margin=0.23, asset_turnover=1.1),
        SimpleNamespace(return_on_equity=0.20, return_on_invested_capital=0.16, operating_margin=0.22, asset_turnover=1.05),
        SimpleNamespace(return_on_equity=0.19, return_on_invested_capital=0.15, operating_margin=0.22, asset_turnover=1.0),
        SimpleNamespace(return_on_equity=0.18, return_on_invested_capital=0.14, operating_margin=0.21, asset_turnover=0.95),
    ]

    result = analyze_moat(metrics)

    assert result["score"] == 5
    assert result["max_score"] == 5
    assert "Excellent ROE consistency: 5/5 periods >15% (avg: 20.0%) - indicates durable competitive advantage" in result["details"]
    assert "Strong and stable operating margins (avg: 22.4%) indicate pricing power moat" in result["details"]
    assert "Efficient asset utilization suggests operational moat" in result["details"]
    assert "High performance stability (94.2%) suggests strong competitive moat" in result["details"]


def test_analyze_moat_keeps_stability_credit_even_when_roe_and_margins_are_weak():
    metrics = [
        SimpleNamespace(return_on_equity=0.12, return_on_invested_capital=0.08, operating_margin=0.10, asset_turnover=0.7),
        SimpleNamespace(return_on_equity=0.11, return_on_invested_capital=0.07, operating_margin=0.11, asset_turnover=0.8),
        SimpleNamespace(return_on_equity=0.10, return_on_invested_capital=0.06, operating_margin=0.09, asset_turnover=0.75),
        SimpleNamespace(return_on_equity=0.09, return_on_invested_capital=0.05, operating_margin=0.10, asset_turnover=0.72),
        SimpleNamespace(return_on_equity=0.08, return_on_invested_capital=0.04, operating_margin=0.08, asset_turnover=0.68),
    ]

    result = analyze_moat(metrics)

    assert result["score"] == 1
    assert result["max_score"] == 5
    assert "Inconsistent ROE: only 0/5 periods >15%" in result["details"]
    assert "Low operating margins (avg: 9.6%) suggest limited pricing power" in result["details"]
    assert "High performance stability (87.6%) suggests strong competitive moat" in result["details"]


def test_analyze_pricing_power_scores_expanding_and_high_gross_margins():
    financial_line_items = [
        SimpleNamespace(gross_margin=0.55),
        SimpleNamespace(gross_margin=0.52),
        SimpleNamespace(gross_margin=0.50),
    ]
    metrics = [
        SimpleNamespace(operating_margin=0.24),
        SimpleNamespace(operating_margin=0.23),
        SimpleNamespace(operating_margin=0.22),
    ]

    result = analyze_pricing_power(financial_line_items, metrics)

    assert result["score"] == 5
    assert result["details"] == "Expanding gross margins indicate strong pricing power; Consistently high gross margins (52.3%) indicate strong pricing power"


def test_analyze_pricing_power_reports_declining_gross_margins_without_extra_credit():
    financial_line_items = [
        SimpleNamespace(gross_margin=0.20),
        SimpleNamespace(gross_margin=0.22),
        SimpleNamespace(gross_margin=0.25),
    ]
    metrics = [
        SimpleNamespace(operating_margin=0.08),
        SimpleNamespace(operating_margin=0.09),
        SimpleNamespace(operating_margin=0.10),
    ]

    result = analyze_pricing_power(financial_line_items, metrics)

    assert result["score"] == 0
    assert result["details"] == "Declining gross margins may indicate pricing pressure"


# ---------------------------------------------------------------------------
# Falsy-zero residue guards (R68/R69/R96/R100 family on agents path)
# A legitimate 0.0 balance-sheet value (zero current liabilities / zero net
# assets) must NOT be silently skipped by a truthiness presence-check.
# ---------------------------------------------------------------------------


def test_resolve_buffett_working_capital_change_keeps_zero_current_liabilities():
    """A period with current_liabilities=0.0 (debt-free shell) must be kept.

    Previously `if all([current_assets, current_liabilities, ...])` skipped
    any period whose current_liabilities legitimately equals 0.0, silently
    dropping real working-capital data and returning 0 with no detail.
    Falsy-zero family (R68/R69/R96/R100) residue on the agents path.
    """
    financial_line_items = [
        # Latest period: zero current liabilities (real balance sheet value)
        SimpleNamespace(current_assets=200.0, current_liabilities=0.0),
        # Previous period: nonzero, so wc_change should be nonzero
        SimpleNamespace(current_assets=150.0, current_liabilities=50.0),
    ]

    working_capital_change, detail = _resolve_buffett_working_capital_change(
        financial_line_items, currency_symbol="$"
    )

    # wc_current = 200 - 0 = 200; wc_previous = 150 - 50 = 100; change = 100
    assert working_capital_change == 100.0
    # Detail string must be populated (not None) -> period was NOT skipped
    assert detail is not None
    assert "100" in detail


def test_analyze_book_value_growth_keeps_zero_shareholders_equity():
    """A period with shareholders_equity=0.0 (zero net assets) must be kept
    when shares_outstanding is nonzero.

    Previously `if shareholders_equity and shares_outstanding:` skipped any
    period with shareholders_equity == 0, potentially dropping book_values
    below the 3-period minimum -> "Insufficient book value data".
    Falsy-zero family residue; the div-by-zero guard belongs on
    shares_outstanding only, not shareholders_equity.
    """
    financial_line_items = [
        SimpleNamespace(shareholders_equity=300.0, outstanding_shares=10.0),
        SimpleNamespace(shareholders_equity=200.0, outstanding_shares=10.0),
        # Latest period: zero net assets, but 10 shares -> book value 0.0 is real
        SimpleNamespace(shareholders_equity=0.0, outstanding_shares=10.0),
    ]

    result = analyze_book_value_growth(financial_line_items)

    # Period with shareholders_equity=0 must NOT cause "Insufficient data"
    assert "Insufficient" not in result["details"]
    assert result["score"] >= 0


def test_collect_buffett_capex_ratio_inputs_includes_legitimate_zero_capex():
    """capital_expenditure == 0 is a legitimate value, not missing data.

    tushare ``c_pay_acq_const_fiolta`` (购建固定资产无形资产支付现金) can be 0.0
    for a period where the company spent nothing on fixed/intangible assets
    (service companies, holding companies between investment cycles). The
    capex/revenue ratio filter must distinguish 0.0 from None — a zero-capex
    period contributes ratio 0.0 (the most capital-light reading) and must
    NOT be silently dropped.

    Previously ``if ... and item.capital_expenditure and item.revenue`` used
    truthiness, dropping zero-capex periods. With fewer ratios the avg capex
    ratio is biased upward -> method_3 (avg_ratio * revenue) inflates the
    maintenance capex estimate (or, if it drops below 3 ratios, method_3 is
    skipped entirely) -> ``owner_earnings = net_income + depreciation -
    maintenance_capex - working_capital_change`` is deflated. The
    charlie_munger sibling (_score_munger_capital_intensity) already uses
    ``is not None`` correctly; this aligns buffett with it.
    Falsy-zero family residue (R107/R108/R110).
    """
    from src.agents.warren_buffett_helpers import _collect_buffett_capex_ratio_inputs

    financial_line_items = [
        SimpleNamespace(capital_expenditure=-10.0, revenue=100.0),
        SimpleNamespace(capital_expenditure=-10.0, revenue=100.0),
        # Legitimate zero-capex period (genuinely spent nothing this quarter)
        SimpleNamespace(capital_expenditure=0.0, revenue=100.0),
        SimpleNamespace(capital_expenditure=-8.0, revenue=100.0),
        # Missing capex (None) -> still correctly excluded
        SimpleNamespace(capital_expenditure=None, revenue=100.0),
    ]

    result = _collect_buffett_capex_ratio_inputs(financial_line_items)

    # All 4 periods with a non-None capex must contribute (incl. the 0.0 one);
    # only the None period is dropped.
    assert len(result) == 4
    assert 0.0 in result  # zero-capex period contributes ratio 0.0, not dropped
