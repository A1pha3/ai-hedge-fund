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
