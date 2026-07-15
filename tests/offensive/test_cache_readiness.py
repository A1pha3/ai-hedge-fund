"""Tests for per-ticker cache refresh outcome model and conservation."""

from datetime import date
from unittest.mock import Mock

import pandas as pd
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


def test_suspension_failure_is_unavailable_not_empty():
    from src.screening.offensive import cache_refresh

    load_suspension_evidence = getattr(cache_refresh, "load_suspension_evidence", None)
    assert load_suspension_evidence is not None

    evidence = load_suspension_evidence(
        "20260713",
        fetch_fn=Mock(side_effect=RuntimeError("down")),
    )
    assert evidence.status is SuspensionEvidenceStatus.UNAVAILABLE


@pytest.mark.parametrize(
    "payload",
    (
        None,
        [],
        {},
        pd.DataFrame(),
        pd.DataFrame({"other": []}),
        pd.DataFrame({"ts_code": ["bad"]}),
        pd.DataFrame({"ts_code": [123]}),
    ),
)
def test_malformed_suspension_payload_is_unavailable(payload):
    from src.screening.offensive.cache_refresh import load_suspension_evidence

    evidence = load_suspension_evidence(
        "20260713",
        fetch_fn=Mock(return_value=payload),
    )

    assert evidence.status is SuspensionEvidenceStatus.UNAVAILABLE
    assert evidence.tickers == frozenset()
    assert evidence.source_fingerprint is None


def test_empty_suspension_dataframe_with_schema_is_authoritative_empty():
    from src.screening.offensive.cache_refresh import load_suspension_evidence

    evidence = load_suspension_evidence(
        "20260713",
        fetch_fn=Mock(return_value=pd.DataFrame({"ts_code": pd.Series(dtype=str)})),
    )

    assert evidence.status is SuspensionEvidenceStatus.AVAILABLE_EMPTY
    assert evidence.source_fingerprint is not None


def test_refresh_result_freezes_nested_mappings():
    tickers = ("000001", "000002")
    outcomes = {
        ticker: TickerRefreshOutcome(
            ticker=ticker,
            price_status=PriceStatus.CURRENT,
            price_history_rows=1,
            fund_flow_status=FundFlowStatus.CURRENT,
            fund_flow_history_rows=1,
            evidence_fingerprints={"price": f"sha256:{ticker}"},
        )
        for ticker in tickers
    }
    result = DailyActionRefreshResult(
        trade_date=date(2026, 7, 13),
        universe_tickers=tickers,
        universe_fingerprint=universe_fingerprint(tickers),
        daily_batch_fingerprint=None,
        suspension_evidence=SuspensionEvidence.available(date(2026, 7, 13), set()),
        outcomes=outcomes,
        stats=derive_stats_from_outcomes(outcomes),
    )

    with pytest.raises(TypeError):
        result.outcomes["000002"] = result.outcomes["000001"]
    with pytest.raises(TypeError):
        result.outcomes["000001"].evidence_fingerprints["price"] = "forged"


def test_refresh_result_copies_universe_suspensions_and_nested_counters():
    universe = ["000001"]
    suspended = {"000001"}
    counters = {"nested": {"values": [1], "labels": {"captured"}}}
    evidence = SuspensionEvidence(
        trade_date=date(2026, 7, 13),
        status=SuspensionEvidenceStatus.AVAILABLE_NONEMPTY,
        tickers=suspended,
        source_fingerprint="sha256:" + "a" * 64,
    )
    outcomes = {
        "000001": _outcome(
            "000001",
            price=PriceStatus.SUSPENDED,
            flow=FundFlowStatus.SUSPENDED,
        )
    }

    result = DailyActionRefreshResult(
        trade_date=date(2026, 7, 13),
        universe_tickers=universe,
        universe_fingerprint=universe_fingerprint(tuple(universe)),
        daily_batch_fingerprint=None,
        suspension_evidence=evidence,
        outcomes=outcomes,
        stats=derive_stats_from_outcomes(outcomes),
        _refresh_counters=counters,
    )
    universe.append("000002")
    suspended.add("000002")
    counters["nested"]["values"].append(2)
    counters["nested"]["labels"].add("forged")

    assert result.universe_tickers == ("000001",)
    assert result.suspension_evidence.tickers == frozenset({"000001"})
    assert result.nested["values"] == (1,)
    assert result.nested["labels"] == frozenset({"captured"})
    with pytest.raises(TypeError):
        result.nested["forged"] = True


class TestSuspensionEvidence:
    def test_available_with_tickers(self):
        ev = SuspensionEvidence.available(date(2026, 7, 13), {"000001", "000002"})
        assert ev.status is SuspensionEvidenceStatus.AVAILABLE_NONEMPTY
        assert ev.tickers == frozenset({"000001", "000002"})

    def test_unavailable_has_empty_tickers(self):
        ev = SuspensionEvidence.unavailable(date(2026, 7, 13))
        assert ev.status is SuspensionEvidenceStatus.UNAVAILABLE
        assert ev.tickers == frozenset()

    def test_available_empty_list_means_no_suspensions(self):
        """Empty list = authority confirms no suspensions (distinct from unavailable)."""
        ev = SuspensionEvidence.available(date(2026, 7, 13), set())
        assert ev.status is SuspensionEvidenceStatus.AVAILABLE_EMPTY
        assert len(ev.tickers) == 0

    @pytest.mark.parametrize(
        ("status", "tickers", "source_fingerprint"),
        (
            (SuspensionEvidenceStatus.AVAILABLE_EMPTY, {"000001"}, None),
            (SuspensionEvidenceStatus.AVAILABLE_NONEMPTY, set(), None),
            (SuspensionEvidenceStatus.UNAVAILABLE, {"000001"}, None),
            (
                SuspensionEvidenceStatus.UNAVAILABLE,
                set(),
                "sha256:" + "a" * 64,
            ),
            (SuspensionEvidenceStatus.AVAILABLE_NONEMPTY, {"bad"}, None),
            (SuspensionEvidenceStatus.AVAILABLE_EMPTY, set(), ""),
            (SuspensionEvidenceStatus.AVAILABLE_EMPTY, None, None),
        ),
    )
    def test_rejects_inconsistent_state(self, status, tickers, source_fingerprint):
        with pytest.raises(ValueError):
            SuspensionEvidence(
                trade_date=date(2026, 7, 13),
                status=status,
                tickers=tickers,
                source_fingerprint=source_fingerprint,
            )


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

    def test_result_post_init_requires_exact_outcome_keys(self):
        tickers = ("000001", "000002")
        outcomes = {
            "000001": _outcome("000001"),
            "000003": _outcome("000003"),
        }
        with pytest.raises(ValueError, match="exactly cover"):
            DailyActionRefreshResult(
                trade_date=date(2026, 7, 13),
                universe_tickers=tickers,
                universe_fingerprint=universe_fingerprint(tickers),
                daily_batch_fingerprint=None,
                suspension_evidence=SuspensionEvidence.available(date(2026, 7, 13), set()),
                outcomes=outcomes,
                stats=derive_stats_from_outcomes(outcomes),
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
