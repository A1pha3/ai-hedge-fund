from copy import deepcopy
from types import SimpleNamespace

import pytest

from src.screening.composite_score import CompositeEntry, CompositeReport
from src.screening.expected_return import ExpectedReturn, ExpectedReturnReport
from src.screening.investability import compute_full_pool_shadow_ranking


def _reports(recommendations: list[dict], *, winner: str):
    composite_items = []
    expected_items = []
    for index, recommendation in enumerate(recommendations):
        ticker = recommendation["ticker"]
        score = 0.99 if ticker == winner else 0.80 - index / 1000
        composite_items.append(
            CompositeEntry(
                ticker=ticker,
                base_score=score,
                momentum_bonus=0.01,
                sector_bonus=0.01,
                consistency_adj=0.01,
                volume_factor=0.01,
                trend_resonance_factor=0.01,
                composite_score=score,
            )
        )
        expected_items.append(
            ExpectedReturn(
                ticker=ticker,
                score_b=recommendation["score_b"],
                bucket_label="high",
                bucket_sample_count=100,
                expected_returns={"t5": 1.0, "t10": 2.0},
                win_rates={"t5": 0.60, "t10": 0.61},
            )
        )
    return (
        CompositeReport(trade_date="20260713", items=composite_items),
        ExpectedReturnReport(
            trade_date="20260713",
            lookback_days=60,
            total_samples=100,
            items=expected_items,
        ),
    )


def test_candidate_35_wins_full_pool_shadow_without_changing_canonical_order():
    candidates = [
        {"ticker": f"{index:06d}", "score_b": 1.0 - index / 100}
        for index in range(40)
    ]
    canonical = deepcopy(candidates[:30])
    winner = candidates[35]["ticker"]
    composite, expected = _reports(candidates, winner=winner)

    shadow = compute_full_pool_shadow_ranking(candidates, composite, expected)

    assert shadow["shadow_rank_status"] == "complete"
    assert shadow["shadow_rank"][0]["ticker"] == winner
    assert shadow["shadow_rank"][0]["rank"] == 1
    assert candidates[:30] == canonical


def test_shadow_rank_is_deterministic_for_complete_ties():
    candidates = [
        {"ticker": ticker, "score_b": 0.5}
        for ticker in ("000003", "000001", "000002")
    ]
    composite, expected = _reports(candidates, winner="absent")
    for item in composite.items:
        item.base_score = item.composite_score = 0.5

    first = compute_full_pool_shadow_ranking(candidates, composite, expected)
    second = compute_full_pool_shadow_ranking(
        list(reversed(candidates)), composite, expected
    )

    assert [row["ticker"] for row in first["shadow_rank"]] == [
        "000001",
        "000002",
        "000003",
    ]
    assert first == second


def test_missing_explicit_dimension_marks_shadow_insufficient():
    candidates = [{"ticker": "000001", "score_b": 0.5}, {"ticker": "000002", "score_b": 0.4}]
    composite, expected = _reports(candidates, winner="000001")
    composite.items.pop()

    shadow = compute_full_pool_shadow_ranking(candidates, composite, expected)

    assert shadow == {"shadow_rank_status": "insufficient", "shadow_rank": []}


@pytest.mark.parametrize("score_b", [float("nan"), float("inf"), float("-inf"), "0.5", True])
def test_nonfinite_or_nonnumeric_original_score_b_marks_shadow_insufficient(score_b):
    candidates = [{"ticker": "000001", "score_b": score_b}]
    composite, expected = _reports(candidates, winner="000001")

    shadow = compute_full_pool_shadow_ranking(candidates, composite, expected)

    assert shadow == {"shadow_rank_status": "insufficient", "shadow_rank": []}


@pytest.mark.parametrize("bad_metric", ["0.5", True])
def test_nonnumeric_explicit_composite_dimension_is_insufficient(bad_metric):
    candidates = [{"ticker": "000001", "score_b": 0.5}]
    composite, expected = _reports(candidates, winner="000001")
    composite.items[0].momentum_bonus = bad_metric

    assert compute_full_pool_shadow_ranking(candidates, composite, expected) == {
        "shadow_rank_status": "insufficient",
        "shadow_rank": [],
    }


@pytest.mark.parametrize("bad_metric", ["0.6", True])
def test_nonnumeric_explicit_expected_evidence_is_insufficient(bad_metric):
    candidates = [{"ticker": "000001", "score_b": 0.5}]
    composite, expected = _reports(candidates, winner="000001")
    expected.items[0].win_rates["t5"] = bad_metric

    assert compute_full_pool_shadow_ranking(candidates, composite, expected) == {
        "shadow_rank_status": "insufficient",
        "shadow_rank": [],
    }


def test_shadow_output_has_no_execution_or_weight_fields():
    candidates = [{"ticker": "000001", "score_b": 0.5}]
    composite, expected = _reports(candidates, winner="000001")
    shadow = compute_full_pool_shadow_ranking(candidates, composite, expected)

    forbidden = {"target_weight", "planned_weight", "trade_id", "execution_label"}
    assert forbidden.isdisjoint(shadow["shadow_rank"][0])


def test_auto_payload_emits_shadow_research_fields_without_execution_fields():
    from src.main import _build_auto_screening_payload

    payload = _build_auto_screening_payload(
        trade_date="20260713",
        top_n=10,
        market_state=SimpleNamespace(model_dump=lambda: {}),
        candidates=[],
        fused=[],
        top_results_serializable=[{"ticker": "000001"}],
        sector_warnings=[],
        consecutive_highlight=0,
        decay_summary={},
        industry_rotation_payload=[],
        batch_fetcher_use_batch=False,
        batch_fetcher_stats={},
        shadow_rank_status="complete",
        shadow_rank=[{"rank": 1, "ticker": "000035"}],
    )

    assert payload["recommendations"] == [{"ticker": "000001"}]
    assert payload["shadow_rank_status"] == "complete"
    assert payload["shadow_rank"] == [{"rank": 1, "ticker": "000035"}]
    assert "buy_orders" not in payload["shadow_rank"][0]
