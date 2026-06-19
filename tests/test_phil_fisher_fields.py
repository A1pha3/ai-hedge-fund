from types import SimpleNamespace

import pytest

import src.agents.phil_fisher as phil_fisher


def test_analyze_margins_stability_scores_improving_strong_and_stable_margins():
    financial_line_items = [
        SimpleNamespace(operating_margin=0.22, gross_margin=0.55),
        SimpleNamespace(operating_margin=0.21, gross_margin=0.5),
        SimpleNamespace(operating_margin=0.20, gross_margin=0.48),
    ]

    result = phil_fisher.analyze_margins_stability(financial_line_items)

    assert result["score"] == 10
    assert "Operating margin stable or improving (20.0% -> 22.0%)" in result["details"]
    assert "Strong gross margin: 55.0%" in result["details"]
    assert "Operating margin extremely stable over multiple years" in result["details"]


def test_analyze_margins_stability_reports_decline_low_margin_and_high_volatility():
    financial_line_items = [
        SimpleNamespace(operating_margin=0.08, gross_margin=0.25),
        SimpleNamespace(operating_margin=0.20, gross_margin=0.35),
        SimpleNamespace(operating_margin=0.35, gross_margin=0.4),
    ]

    result = phil_fisher.analyze_margins_stability(financial_line_items)

    assert result["score"] == pytest.approx(10 / 6)
    assert "Operating margin positive but slightly declined" in result["details"]
    assert "Low gross margin: 25.0%" in result["details"]
    assert "Operating margin volatility is high" in result["details"]


def test_analyze_fisher_growth_quality_scores_strong_growth_and_healthy_rnd(monkeypatch):
    def _fake_cagr(financial_line_items, field):
        return {"revenue": 0.25, "earnings_per_share": 0.22}[field]

    monkeypatch.setattr(phil_fisher, "calculate_cagr_from_line_items", _fake_cagr)
    financial_line_items = [
        SimpleNamespace(revenue=100.0, research_and_development=10.0),
        SimpleNamespace(revenue=90.0, research_and_development=9.0),
    ]

    result = phil_fisher.analyze_fisher_growth_quality(financial_line_items)

    assert result["score"] == 10
    assert "Very strong annualized revenue growth: 25.0%" in result["details"]
    assert "Very strong annualized EPS growth: 22.0%" in result["details"]
    assert "R&D ratio 10.0% indicates significant investment in future growth" in result["details"]


def test_analyze_fisher_growth_quality_reports_muted_growth_and_missing_rnd(monkeypatch):
    def _fake_cagr(financial_line_items, field):
        return {"revenue": 0.01, "earnings_per_share": -0.02}[field]

    monkeypatch.setattr(phil_fisher, "calculate_cagr_from_line_items", _fake_cagr)
    financial_line_items = [
        SimpleNamespace(revenue=100.0, research_and_development=None),
        SimpleNamespace(revenue=98.0),
    ]

    result = phil_fisher.analyze_fisher_growth_quality(financial_line_items)

    assert result["score"] == 0
    assert "Minimal or negative annualized revenue growth: 1.0%" in result["details"]
    assert "Minimal or negative annualized EPS growth: -2.0%" in result["details"]
    assert "Insufficient R&D data to evaluate" in result["details"]


def test_analyze_management_efficiency_leverage_scores_high_roe_low_debt_and_positive_fcf():
    financial_line_items = [
        SimpleNamespace(net_income=30.0, shareholders_equity=100.0, debt_to_equity=0.2, free_cash_flow=10.0),
        SimpleNamespace(net_income=28.0, shareholders_equity=95.0, debt_to_equity=0.25, free_cash_flow=9.0),
        SimpleNamespace(net_income=25.0, shareholders_equity=90.0, debt_to_equity=0.3, free_cash_flow=8.0),
    ]

    result = phil_fisher.analyze_management_efficiency_leverage(financial_line_items)

    assert result["score"] == 10
    assert "High ROE: 30.0%" in result["details"]
    assert "Low debt-to-equity: 0.20" in result["details"]
    assert "Majority of periods have positive FCF (3/3)" in result["details"]


def test_analyze_management_efficiency_leverage_reports_negative_income_and_missing_fcf_with_debt_fallback():
    financial_line_items = [
        SimpleNamespace(net_income=-5.0, shareholders_equity=50.0, total_debt=80.0, free_cash_flow=None),
        SimpleNamespace(net_income=-4.0, shareholders_equity=40.0, total_debt=70.0),
    ]

    result = phil_fisher.analyze_management_efficiency_leverage(financial_line_items)

    assert result["score"] == 0
    assert "Recent net income is zero or negative, hurting ROE" in result["details"]
    assert "High debt-to-equity: 1.60" in result["details"]
    assert "Insufficient or no FCF data to check consistency" in result["details"]


def test_rnd_intensity_treats_zero_revenue_as_undefined_not_huge_ratio():
    """revenue == 0 makes the R&D/revenue ratio undefined, not astronomically high.

    A pre-revenue company (revenue=0, spending on R&D) previously hit the
    ``revenues[0] if revenues[0] else 1e-9`` epsilon fallback: rnd/1e-9 exploded
    to ~1e10, mapping to "R&D ratio ... is very high" (score 2) — a false
    positive R&D-investment signal for a company with no revenue. The ratio is
    mathematically undefined at zero revenue; it must read as undefined (neutral
    score), not an inflated high score. Falsy-zero epsilon family (R122/R123).
    """
    from src.agents.phil_fisher_helpers import _score_fisher_rnd_intensity

    financial_line_items = [
        SimpleNamespace(revenue=0.0, research_and_development=10.0),
        SimpleNamespace(revenue=0.0, research_and_development=8.0),
    ]

    score, detail = _score_fisher_rnd_intensity(financial_line_items)

    # Zero revenue -> ratio undefined -> NOT a high-R&D-investment score
    assert score == 0
    assert "very high" not in detail.lower()


def test_roe_treats_zero_equity_as_undefined_not_huge_roe():
    """shareholders_equity == 0 makes ROE undefined, not astronomically high.

    A zero-equity company (distressed: liabilities == assets) with positive net
    income previously hit the ``eq_values[0] if eq_values[0] else 1e-9`` epsilon
    fallback: ni/1e-9 exploded to ~1e10, mapping to "High ROE" (score 3) — a
    false-positive quality signal for a balance sheet with no equity. ROE is
    undefined at zero equity; it must read as undefined (neutral score), not an
    inflated high score. Falsy-zero epsilon family (R122/R123).
    """
    from src.agents.phil_fisher_helpers import _score_fisher_roe

    # Paired (ni, equity) tuples (R127 caller contract); latest period has zero equity + positive NI
    score, detail = _score_fisher_roe([(30.0, 0.0), (28.0, 100.0)])

    # Zero equity -> ROE undefined -> NOT "High ROE"
    assert score == 0
    assert "High ROE" not in detail


def test_rnd_intensity_pairs_rd_with_revenue_across_complementary_missing_periods():
    """len(A)==len(B) guard cannot detect complementary-missing data.

    item0 has revenue but no R&D; item1 has R&D but no revenue. Both filtered
    lists end up length 1, so ``len(rnd_values) == len(revenues)`` passes — but
    rnd_values[0] (=item1.R&D=10) pairs with revenues[0] (=item0.revenue=100),
    a cross-period mismatch giving 0.10 -> score 1 ("somewhat low but positive").
    Same-period pairing yields no period with BOTH fields -> "Insufficient".
    Positional-mismatch family (R125), complementary-missing edge.
    """
    from src.agents.phil_fisher_helpers import _score_fisher_rnd_intensity

    financial_line_items = [
        SimpleNamespace(revenue=100.0, research_and_development=None),
        SimpleNamespace(revenue=None, research_and_development=10.0),
    ]

    score, detail = _score_fisher_rnd_intensity(financial_line_items)

    # No period has BOTH R&D and revenue -> Insufficient, not a mismatched 0.10 ratio
    assert score == 0
    assert "Insufficient" in detail


def test_management_efficiency_roe_pairs_ni_with_equity_across_complementary_missing():
    """ROE divides caller-filtered ni_values/eq_values; complementary-missing
    (item0 has NI no equity, item1 has equity no NI) defeats the len== guard.
    Previously ni_values[0] (=item0.NI=30) / eq_values[0] (=item1.equity=100)
    -> 0.30 -> "High ROE" score 3, a cross-period false positive for a company
    where no single period has both NI and equity. Same-period pairing yields
    no NI+equity pair -> "Insufficient data for ROE calculation" score 0.
    Positional-mismatch family (R125/R126), caller-side fix.
    """
    financial_line_items = [
        SimpleNamespace(net_income=30.0, shareholders_equity=None, debt_to_equity=None, free_cash_flow=10.0),
        SimpleNamespace(net_income=None, shareholders_equity=100.0, debt_to_equity=None, free_cash_flow=10.0),
    ]

    result = phil_fisher.analyze_management_efficiency_leverage(financial_line_items)

    # No period has BOTH NI and equity -> ROE must read Insufficient, NOT "High ROE"
    assert "High ROE" not in result["details"]
    assert "Insufficient data for ROE" in result["details"]


def test_management_efficiency_debt_to_equity_pairs_across_complementary_missing():
    """_score_fisher_debt_to_equity fallback filters debt_values independently
    and pairs with caller-passed eq_values via len==; complementary-missing
    (item0 has debt no equity, item1 has equity no debt) defeats the guard.
    Previously debt_values[0] (=item0.debt=80) / eq_values[0] (=item1.equity=50)
    -> 1.60 -> "High debt-to-equity" score 0 (correct direction, fabricated
    value). Same-period pairing yields no debt+equity pair -> "No debt/equity
    data available" score 0. Positional-mismatch family (R125/R126).
    """
    financial_line_items = [
        SimpleNamespace(total_debt=80.0, shareholders_equity=None, debt_to_equity=None, net_income=10.0, free_cash_flow=10.0),
        SimpleNamespace(total_debt=None, shareholders_equity=50.0, debt_to_equity=None, net_income=10.0, free_cash_flow=10.0),
    ]

    result = phil_fisher.analyze_management_efficiency_leverage(financial_line_items)

    # No period has BOTH debt and equity -> "No debt/equity data", NOT fabricated 1.60
    assert "No debt/equity data" in result["details"]
    assert "1.60" not in result["details"]
