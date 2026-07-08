from __future__ import annotations


def test_resolve_industry_day_pct_uses_real_industry_cache():
    from scripts.backtest_paper_loop import _resolve_industry_day_pct

    result = _resolve_industry_day_pct(
        "000001",
        "20260708",
        ticker_to_industry={"000001": "农林牧渔"},
        industry_day_pct={("农林牧渔", "20260708"): 1.2},
    )

    assert result == 1.2


def test_resolve_industry_day_pct_missing_mapping_is_zero_not_stock_pct():
    from scripts.backtest_paper_loop import _resolve_industry_day_pct

    result = _resolve_industry_day_pct(
        "000001",
        "20260708",
        ticker_to_industry={},
        industry_day_pct={},
    )

    assert result == 0.0
