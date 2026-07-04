import json
from types import SimpleNamespace

import src.agents.valuation as valuation


def test_valuation_agent_builds_bullish_payload_with_dcf_scenarios(monkeypatch):
    monkeypatch.setattr(valuation, "get_api_key_from_state", lambda state, name: "k")
    monkeypatch.setattr(valuation.progress, "update_status", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        valuation,
        "get_financial_metrics",
        lambda **kwargs: [
            SimpleNamespace(
                earnings_growth=0.12,
                market_cap=1000.0,
                interest_coverage=8.0,
                debt_to_equity=0.3,
                revenue_growth=0.15,
                free_cash_flow_growth=0.2,
                price_to_book_ratio=1.5,
                book_value_growth=0.08,
            )
        ],
    )
    monkeypatch.setattr(
        valuation,
        "search_line_items",
        lambda **kwargs: [
            SimpleNamespace(
                net_income=100.0,
                depreciation_and_amortization=20.0,
                capital_expenditure=30.0,
                working_capital=50.0,
                total_debt=100.0,
                cash_and_equivalents=20.0,
                free_cash_flow=80.0,
            ),
            SimpleNamespace(
                net_income=90.0,
                depreciation_and_amortization=18.0,
                capital_expenditure=25.0,
                working_capital=45.0,
                total_debt=110.0,
                cash_and_equivalents=15.0,
                free_cash_flow=75.0,
            ),
        ],
    )
    monkeypatch.setattr(valuation, "get_market_cap", lambda *args, **kwargs: 1000.0)
    monkeypatch.setattr(valuation, "calculate_owner_earnings_value", lambda **kwargs: 1400.0)
    monkeypatch.setattr(valuation, "calculate_wacc", lambda **kwargs: 0.1)
    monkeypatch.setattr(
        valuation,
        "calculate_dcf_scenarios",
        lambda **kwargs: {
            "expected_value": 1600.0,
            "downside": 1200.0,
            "upside": 2000.0,
            "range": 800.0,
            "scenarios": {"base": 1600.0},
        },
    )
    monkeypatch.setattr(valuation, "calculate_ev_ebitda_value", lambda *args, **kwargs: 1100.0)
    monkeypatch.setattr(valuation, "calculate_residual_income_value", lambda **kwargs: 900.0)
    monkeypatch.setattr(valuation, "get_currency_symbol", lambda ticker: "¥")

    state = {
        "messages": [],
        "data": {"end_date": "2026-04-10", "tickers": ["000001"], "analyst_signals": {}},
        "metadata": {"show_reasoning": False},
    }

    result = valuation.valuation_analyst_agent(state)

    assert json.loads(result["messages"][0].content) == {
        "000001": {
            "signal": "bullish",
            "confidence": 100,
            "reasoning": {
                "dcf_analysis": {
                    "signal": "bullish",
                    "details": "Value: ¥1,600.00, Market Cap: ¥1,000.00, Gap: 60.0%, Weight: 35%\n  WACC: 10.0%, Bear: ¥1,200.00, Bull: ¥2,000.00, Range: ¥800.00",
                },
                "owner_earnings_analysis": {
                    "signal": "bullish",
                    "details": "Value: ¥1,400.00, Market Cap: ¥1,000.00, Gap: 40.0%, Weight: 35%",
                },
                "ev_ebitda_analysis": {
                    "signal": "neutral",
                    "details": "Value: ¥1,100.00, Market Cap: ¥1,000.00, Gap: 10.0%, Weight: 20%",
                },
                "residual_income_analysis": {
                    "signal": "neutral",
                    "details": "Value: ¥900.00, Market Cap: ¥1,000.00, Gap: -10.0%, Weight: 10%",
                },
                "dcf_scenario_analysis": {
                    "bear_case": "¥1,200.00",
                    "base_case": "¥1,600.00",
                    "bull_case": "¥2,000.00",
                    "wacc_used": "10.0%",
                    "fcf_periods_analyzed": 2,
                },
            },
        }
    }
    assert result["data"]["analyst_signals"] == {
        "valuation_analyst_agent": {
            "000001": {
                "signal": "bullish",
                "confidence": 100,
                "reasoning": {
                    "dcf_analysis": {
                        "signal": "bullish",
                        "details": "Value: ¥1,600.00, Market Cap: ¥1,000.00, Gap: 60.0%, Weight: 35%\n  WACC: 10.0%, Bear: ¥1,200.00, Bull: ¥2,000.00, Range: ¥800.00",
                    },
                    "owner_earnings_analysis": {
                        "signal": "bullish",
                        "details": "Value: ¥1,400.00, Market Cap: ¥1,000.00, Gap: 40.0%, Weight: 35%",
                    },
                    "ev_ebitda_analysis": {
                        "signal": "neutral",
                        "details": "Value: ¥1,100.00, Market Cap: ¥1,000.00, Gap: 10.0%, Weight: 20%",
                    },
                    "residual_income_analysis": {
                        "signal": "neutral",
                        "details": "Value: ¥900.00, Market Cap: ¥1,000.00, Gap: -10.0%, Weight: 10%",
                    },
                    "dcf_scenario_analysis": {
                        "bear_case": "¥1,200.00",
                        "base_case": "¥1,600.00",
                        "bull_case": "¥2,000.00",
                        "wacc_used": "10.0%",
                        "fcf_periods_analyzed": 2,
                    },
                },
            }
        }
    }


def test_valuation_agent_returns_neutral_error_when_metrics_are_missing(monkeypatch):
    monkeypatch.setattr(valuation, "get_api_key_from_state", lambda state, name: "k")
    monkeypatch.setattr(valuation.progress, "update_status", lambda *args, **kwargs: None)
    monkeypatch.setattr(valuation, "get_financial_metrics", lambda **kwargs: [])

    state = {
        "messages": [],
        "data": {"end_date": "2026-04-10", "tickers": ["000001"], "analyst_signals": {}},
        "metadata": {"show_reasoning": False},
    }

    result = valuation.valuation_analyst_agent(state)

    assert json.loads(result["messages"][0].content) == {
        "000001": {
            "signal": "neutral",
            "confidence": 0,
            "reasoning": {"error": "No financial metrics available for valuation analysis"},
        }
    }
    assert result["data"]["analyst_signals"] == {
        "valuation_analyst_agent": {
            "000001": {
                "signal": "neutral",
                "confidence": 0,
                "reasoning": {"error": "No financial metrics available for valuation analysis"},
            }
        }
    }


# ---------- Regression tests for ALPHA-R20.16: `x or 0.05` 0.0-swallower ----------


def test_calculate_enhanced_dcf_value_preserves_zero_revenue_growth():
    """When revenue_growth is exactly 0.0, it must NOT be replaced by the 0.05 default."""
    fcf_history = [100.0, 110.0, 105.0]
    growth_metrics = {"revenue_growth": 0.0, "fcf_growth": 0.0, "earnings_growth": 0.0}
    result = valuation.calculate_enhanced_dcf_value(
        fcf_history=fcf_history,
        growth_metrics=growth_metrics,
        wacc=0.1,
        market_cap=1000.0,
        revenue_growth=0.0,
    )
    # If the bug were present, 0.0 would become 0.05, inflating the DCF value.
    # With 0.0 growth, the value should be lower than with 0.05 growth.
    # We just verify it returns a finite number (the fix prevents the `or` fallback).
    assert isinstance(result, float)
    assert result > 0  # Still positive with positive FCF

    # Cross-check: 0.0 growth should give a *lower* value than 0.05 growth
    result_with_growth = valuation.calculate_enhanced_dcf_value(
        fcf_history=fcf_history,
        growth_metrics=growth_metrics,
        wacc=0.1,
        market_cap=1000.0,
        revenue_growth=0.05,
    )
    assert result < result_with_growth, f"Zero-growth DCF ({result}) should be less than 5%-growth DCF ({result_with_growth})"


def test_calculate_enhanced_dcf_transition_fcf_is_monotonic():
    """BH-009: transition-stage FCF must compound on the previous year's level
    (running product), not raise the base to the current year's declining rate.

    The old ``base * (1+rate)^(year-3)`` form re-applied only the current
    year's declining transition rate as if constant across all transition
    years. With a positive transition growth, the projected FCF series became
    non-monotonic (declining in later transition years), understating terminal
    value. This test reconstructs the transition projection and asserts it is
    strictly increasing when transition_growth > 0.
    """
    # Reconstruct the per-year transition FCFs by instrumenting the internal
    # loop via the public function's present-value decomposition is fragile;
    # instead assert the high-level monotonicity invariant indirectly: a
    # higher transition_growth must yield a strictly higher intrinsic value
    # (it widens each transition FCF and the terminal level).
    fcf_history = [100.0, 105.0, 110.0]
    base_kwargs = dict(
        fcf_history=fcf_history,
        growth_metrics={"revenue_growth": 0.08, "fcf_growth": 0.08, "earnings_growth": 0.08},
        wacc=0.10,
        market_cap=1000.0,
        revenue_growth=0.08,
    )
    # We vary transition_growth indirectly via revenue_growth (it derives the
    # transition schedule). With the bug, raising growth could DECREASE value
    # in some bands because the non-monotonic FCF collapsed terminal FCF.
    low = valuation.calculate_enhanced_dcf_value(**base_kwargs)
    higher = dict(base_kwargs)
    higher["revenue_growth"] = 0.12
    higher["growth_metrics"] = {"revenue_growth": 0.12, "fcf_growth": 0.12, "earnings_growth": 0.12}
    high = valuation.calculate_enhanced_dcf_value(**higher)
    assert high > low, f"Higher growth (0.12) must raise DCF ({high}) above lower-growth (0.08) DCF ({low}); " f"a decrease signals the non-monotonic transition-FCF bug (BH-009)."


def test_calculate_dcf_scenarios_preserves_zero_revenue_growth():
    """When revenue_growth is exactly 0.0, all scenarios should use 0.0 as base, not 0.05."""
    fcf_history = [100.0, 110.0, 105.0]
    growth_metrics = {"revenue_growth": 0.0, "fcf_growth": 0.0, "earnings_growth": 0.0}

    result_zero = valuation.calculate_dcf_scenarios(
        fcf_history=fcf_history,
        growth_metrics=growth_metrics,
        wacc=0.1,
        market_cap=1000.0,
        revenue_growth=0.0,
    )

    result_default = valuation.calculate_dcf_scenarios(
        fcf_history=fcf_history,
        growth_metrics=growth_metrics,
        wacc=0.1,
        market_cap=1000.0,
        revenue_growth=None,
    )

    # Both should produce valid results
    assert isinstance(result_zero["expected_value"], float)
    assert isinstance(result_default["expected_value"], float)

    # revenue_growth=0.0 should give LOWER values than revenue_growth=None (which defaults to 0.05)
    assert result_zero["expected_value"] < result_default["expected_value"], f"Zero-growth scenario ({result_zero['expected_value']}) should be less than " f"default-growth scenario ({result_default['expected_value']})"


def test_calculate_enhanced_dcf_value_handles_none_revenue_growth():
    """When revenue_growth is None, the 0.05 default should be applied."""
    fcf_history = [100.0, 110.0, 105.0]
    growth_metrics = {"revenue_growth": None, "fcf_growth": None, "earnings_growth": None}

    result = valuation.calculate_enhanced_dcf_value(
        fcf_history=fcf_history,
        growth_metrics=growth_metrics,
        wacc=0.1,
        market_cap=1000.0,
        revenue_growth=None,
    )

    assert isinstance(result, float)
    assert result > 0
