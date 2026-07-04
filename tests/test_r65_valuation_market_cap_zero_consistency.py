"""R65 family drain (Stage 2 Refactor Batch): defensive consistency for
``market_cap is None`` → ``not market_cap`` in the remaining valuation agents.

R65 fixed ``cathie_wood.py`` and ``bill_ackman.py`` to guard with ``not market_cap``
(catches both ``None`` and ``0``). The current call sites of these agents only
receive ``market_cap`` from ``get_market_cap`` which normalizes ``0 → None`` (so
``market_cap == 0`` is currently unreachable), making these *latent* — but the
inconsistency is a verifiable drift from the canonical R65 guard. If a future
caller passes ``0`` directly (e.g. a snapshot hydrated from JSON, a new data
source), ``pfcf = market_cap / recent_fcf = 0`` would be scored as "Reasonable
P/FCF" (max points) for a worthless/unknown-cap stock — silent miscompute.

These tests prove the guard now treats ``market_cap == 0`` like ``None``
(insufficient data, score 0) rather than letting it flow into division.
"""

from types import SimpleNamespace

from src.agents.peter_lynch import analyze_lynch_valuation
from src.agents.phil_fisher import analyze_fisher_valuation
from src.agents.stanley_druckenmiller import analyze_druckenmiller_valuation


def test_fisher_valuation_market_cap_zero_returns_insufficient_data():
    """R65 drain: market_cap=0 应与 None 一样返回 insufficient data (score 0),
    而非让 pfcf=0/positive=0 被评分成 "Reasonable P/FCF" 满分。
    """
    financial_line_items = [
        SimpleNamespace(
            net_income=100.0,
            free_cash_flow=80.0,
            earnings_per_share=5.0,
            total_debt=20.0,
            cash_and_equivalents=30.0,
        )
    ]
    # market_cap=0 (e.g. corrupt snapshot / unknown-cap stock)
    result = analyze_fisher_valuation(financial_line_items, 0)
    assert result["score"] == 0, f"market_cap=0 应与 None 一样返回 score=0 (insufficient data); got score={result['score']} " f"details={result['details']!r} — 这意味着 0 市值票被当合法标的评分 (R65 latent bug)"


def test_druckenmiller_valuation_market_cap_zero_returns_insufficient_data():
    """R65 drain: 同上 — druckenmiller valuation 也应把 market_cap=0 当 insufficient data。"""
    financial_line_items = [
        SimpleNamespace(
            net_income=100.0,
            free_cash_flow=80.0,
            ebit=120.0,
            ebitda=150.0,
            total_debt=200.0,
            cash_and_equivalents=50.0,
        )
    ]
    result = analyze_druckenmiller_valuation(financial_line_items, 0)
    assert result["score"] == 0, f"market_cap=0 应与 None 一样返回 score=0; got score={result['score']} " f"details={result['details']!r}"


def test_lynch_valuation_market_cap_zero_returns_insufficient_data():
    """R65 drain: 同上 — peter_lynch valuation 也应把 market_cap=0 当 insufficient data。"""
    financial_line_items = [
        SimpleNamespace(
            net_income=100.0,
            earnings_per_share=5.0,
            revenue=1000.0,
        )
    ]
    result = analyze_lynch_valuation(financial_line_items, 0)
    assert result["score"] == 0, f"market_cap=0 应与 None 一样返回 score=0; got score={result['score']} " f"details={result['details']!r}"
