"""C2-BH2: _build_prior_period_keys robustness against malformed end_date.

Tushare ``fina_indicator`` may return a row with a null/missing/short
``end_date`` (observed for newly-listed companies or partial-year restatements).
``_build_prior_period_keys`` previously did ``int(end_date_str[:4])``
unconditionally — a 0-length or non-digit prefix raises ``ValueError``, which
propagates through TTM synthesis and is swallowed by the outer ``except`` in
``get_ashare_financial_metrics_with_tushare``, silently dropping ALL financial
metrics for the ticker. One bad row poisons the whole batch.
"""
from __future__ import annotations

import pytest

from src.tools.tushare_financial_metrics_helpers import (
    _build_prior_period_keys,
    _extend_ttm_synthesis_dates,
)


class TestBuildPriorPeriodKeysRobustness:
    def test_valid_quarterly_date(self) -> None:
        assert _build_prior_period_keys("20240331") == ("20231231", "20230331")

    def test_valid_annual_date(self) -> None:
        assert _build_prior_period_keys("20231231") == ("20221231", "20221231")

    @pytest.mark.parametrize(
        "bad",
        ["", "20", "abcd", "2024", None, "2024033"],
    )
    def test_malformed_does_not_raise(self, bad) -> None:
        """A malformed end_date must NOT raise — it returns a sentinel that
        downstream .get() misses, instead of poisoning the whole batch."""
        result = _build_prior_period_keys(bad)
        # Must return a tuple (not raise); sentinel keys that won't match real data
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_extend_synthesis_dates_skips_malformed(self) -> None:
        """A malformed end_date in period_dates must not crash synthesis-date
        extension; it is skipped so valid dates still synthesize."""
        dates = ["20240331", "", "20230630", "abc"]
        # Must not raise
        result = _extend_ttm_synthesis_dates(dates)
        # Valid dates still produce their prior-period keys
        assert "20240331" in result
        assert "20230630" in result
