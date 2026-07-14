"""Tests for per-ticker cache refresh outcome model and conservation."""

from datetime import date

import pytest

from src.screening.offensive.cache_readiness import (
    DailyActionRefreshResult,
    FundFlowStatus,
    PriceStatus,
    SuspensionEvidence,
    SuspensionEvidenceStatus,
    TickerRefreshOutcome,
    derive_stats_from_outcomes,
    universe_fingerprint,
)


def _outcome(
    ticker: str,
    price: PriceStatus = PriceStatus.CURRENT,
    flow: FundFlowStatus = FundFlowStatus.CURRENT,
    price_rows: int = 100,
    flow_rows: int = 100,
) -> TickerRefreshOutcome:
    return TickerRefreshOutcome(
        ticker=ticker,
        price_status=price,
        price_history_rows=price_rows,
        fund_flow_status=flow,
        fund_flow_history_rows=flow_rows,
    )


class TestSuspensionEvidence:
    def test_available_with_tickers(self):
        ev = SuspensionEvidence.available(date(2026, 7, 13), {"000001", "000002"})
        assert ev.status is SuspensionEvidenceStatus.AVAILABLE
        assert ev.tickers == frozenset({"000001", "000002"})

    def test_unavailable_has_empty_tickers(self):
        ev = SuspensionEvidence.unavailable(date(2026, 7, 13))
        assert ev.status is SuspensionEvidenceStatus.UNAVAILABLE
        assert ev.tickers == frozenset()

    def test_available_empty_list_means_no_suspensions(self):
        """Empty list = authority confirms no suspensions (distinct from unavailable)."""
        ev = SuspensionEvidence.available(date(2026, 7, 13), set())
        assert ev.status is SuspensionEvidenceStatus.AVAILABLE
        assert len(ev.tickers) == 0


class TestConservation:
    def test_price_status_counts_sum_to_universe(self):
        outcomes = {
            "000001": _outcome("000001"),
            "000002": _outcome("000002", price=PriceStatus.SUSPENDED),
            "000003": _outcome("000003"),
        }
        stats = derive_stats_from_outcomes(outcomes)
        assert sum(stats.price_status_counts.values()) == 3
        assert stats.price_status_counts["current"] == 2
        assert stats.price_status_counts["suspended"] == 1

    def test_fund_flow_status_counts_sum_to_universe(self):
        outcomes = {
            "000001": _outcome("000001"),
            "000002": _outcome("000002", flow=FundFlowStatus.SUSPENDED),
            "000003": _outcome("000003", flow=FundFlowStatus.UNSUPPORTED),
            "000004": _outcome("000004"),
        }
        stats = derive_stats_from_outcomes(outcomes)
        assert sum(stats.fund_flow_status_counts.values()) == 4
        assert stats.fund_flow_status_counts["current"] == 2

    def test_result_post_init_rejects_duplicate_universe(self):
        with pytest.raises(ValueError, match="duplicates"):
            DailyActionRefreshResult(
                trade_date=date(2026, 7, 13),
                universe_tickers=("000001", "000001"),
                universe_fingerprint="sha256:x",
                daily_batch_fingerprint=None,
                suspension_evidence=SuspensionEvidence.available(date(2026, 7, 13), set()),
                outcomes={},
                stats=derive_stats_from_outcomes({}),
            )

    def test_result_post_init_rejects_conservation_violation(self):
        """If outcomes don't cover all universe tickers, conservation fails."""
        tickers = ("000001", "000002")
        outcomes = {"000001": _outcome("000001")}  # missing 000002
        stats = derive_stats_from_outcomes(outcomes)
        with pytest.raises(ValueError, match="price status counts"):
            DailyActionRefreshResult(
                trade_date=date(2026, 7, 13),
                universe_tickers=tickers,
                universe_fingerprint=universe_fingerprint(tickers),
                daily_batch_fingerprint=None,
                suspension_evidence=SuspensionEvidence.available(date(2026, 7, 13), set()),
                outcomes=outcomes,
                stats=stats,
            )

    def test_valid_result_passes_post_init(self):
        tickers = ("000001", "000002")
        outcomes = {
            "000001": _outcome("000001"),
            "000002": _outcome(
                "000002",
                price=PriceStatus.SUSPENDED,
                flow=FundFlowStatus.SUSPENDED,
            ),
        }
        stats = derive_stats_from_outcomes(outcomes)
        result = DailyActionRefreshResult(
            trade_date=date(2026, 7, 13),
            universe_tickers=tickers,
            universe_fingerprint=universe_fingerprint(tickers),
            daily_batch_fingerprint=None,
            suspension_evidence=SuspensionEvidence.available(date(2026, 7, 13), {"000002"}),
            outcomes=outcomes,
            stats=stats,
        )
        assert len(result.outcomes) == 2

    def test_not_attempted_preserves_ticker_in_counts(self):
        """Quota-exceeded tickers must be NOT_ATTEMPTED, not disappear from denominator."""
        outcomes = {
            "000001": _outcome("000001"),
            "000002": _outcome("000002"),
            "000003": TickerRefreshOutcome(
                ticker="000003",
                price_status=PriceStatus.NOT_ATTEMPTED,
                price_history_rows=0,
                fund_flow_status=FundFlowStatus.NOT_ATTEMPTED,
                fund_flow_history_rows=0,
            ),
        }
        stats = derive_stats_from_outcomes(outcomes)
        assert stats.price_status_counts["not_attempted"] == 1
        assert sum(stats.price_status_counts.values()) == 3
