"""Unit tests for src/screening/candidate_pool_shadow_helpers.py

Pure functions + dependency injection covering shadow-pool share metrics,
release-stage classification, row selection/priority, lane payload building,
overflow classification, and summary assembly.
"""

from __future__ import annotations

from src.screening.candidate_pool_shadow_helpers import (
    ShadowRankRow,
    _build_source_layer_release_contract,
    _resolve_source_layer_release_stage,
    build_cooldown_review_shadow_payload,
    build_shadow_lane_payload,
    build_shadow_summary_payload,
    classify_overflow_candidate,
    compute_shadow_share_metrics,
    count_shadow_lanes,
    select_shadow_rows,
)
from src.screening.models import CandidateStock


def _cand(ticker: str, avg_volume: float = 500.0, market_cap: float = 3.0) -> CandidateStock:
    return CandidateStock(ticker=ticker, name=ticker, avg_volume_20d=avg_volume, market_cap=market_cap)


# ---------------------------------------------------------------------------
# compute_shadow_share_metrics
# ---------------------------------------------------------------------------


def test_compute_shadow_share_metrics_zero_volume() -> None:
    assert compute_shadow_share_metrics(avg_volume_20d=0.0, cutoff_reference=1000.0, min_avg_amount_20d=200.0) == (0.0, 0.0)


def test_compute_shadow_share_metrics_negative_volume() -> None:
    assert compute_shadow_share_metrics(avg_volume_20d=-5.0, cutoff_reference=1000.0, min_avg_amount_20d=200.0) == (0.0, 0.0)


def test_compute_shadow_share_metrics_normal() -> None:
    cutoff_share, min_gate_share = compute_shadow_share_metrics(
        avg_volume_20d=500.0, cutoff_reference=1000.0, min_avg_amount_20d=200.0
    )
    assert cutoff_share == 0.5
    assert min_gate_share == 2.5


def test_compute_shadow_share_metrics_rounds_to_4() -> None:
    cutoff_share, min_gate_share = compute_shadow_share_metrics(
        avg_volume_20d=333.0, cutoff_reference=1000.0, min_avg_amount_20d=7.0
    )
    assert cutoff_share == round(0.333, 4)
    assert min_gate_share == round(47.5714, 4)


# ---------------------------------------------------------------------------
# _resolve_source_layer_release_stage
# ---------------------------------------------------------------------------


def test_resolve_source_layer_strict_release_for_focus_in_non_cooldown() -> None:
    stage, reason = _resolve_source_layer_release_stage(lane="corridor", shadow_focus_selected=True)
    assert stage == "strict_release"
    assert reason == "shadow_focus_selected"


def test_resolve_source_layer_validation_only_when_cooldown_review() -> None:
    """cooldown_review lane is always validation_only even if focus selected."""
    stage, reason = _resolve_source_layer_release_stage(lane="cooldown_review", shadow_focus_selected=True)
    assert stage == "validation_only"
    assert reason == "shadow_validation_only"


def test_resolve_source_layer_validation_only_when_not_focus() -> None:
    stage, reason = _resolve_source_layer_release_stage(lane="corridor", shadow_focus_selected=False)
    assert stage == "validation_only"
    assert reason == "shadow_validation_only"


# ---------------------------------------------------------------------------
# _build_source_layer_release_contract
# ---------------------------------------------------------------------------


def test_build_source_layer_release_contract_groups_by_stage_and_lane() -> None:
    entries = [
        {"ticker": "000001", "source_layer_release_stage": "strict_release", "candidate_pool_lane": "corridor"},
        {"ticker": "000002", "source_layer_release_stage": "validation_only", "candidate_pool_lane": "rebucket"},
        {"ticker": "000003", "source_layer_release_stage": "strict_release", "candidate_pool_lane": "corridor"},
        {"ticker": "", "source_layer_release_stage": "strict_release", "candidate_pool_lane": "corridor"},  # dropped
    ]
    contract = _build_source_layer_release_contract(entries)
    assert contract["source_layer_strict_release_tickers"] == ["000001", "000003"]
    assert contract["source_layer_validation_only_tickers"] == ["000002"]
    lane_contracts = contract["source_layer_lane_release_contracts"]
    assert lane_contracts["corridor"]["strict_release_tickers"] == ["000001", "000003"]
    assert lane_contracts["rebucket"]["validation_only_tickers"] == ["000002"]


def test_build_source_layer_release_contract_dedupes_lane_tickers() -> None:
    entries = [
        {"ticker": "000001", "source_layer_release_stage": "strict_release", "candidate_pool_lane": "corridor"},
        {"ticker": "000001", "source_layer_release_stage": "strict_release", "candidate_pool_lane": "corridor"},
    ]
    contract = _build_source_layer_release_contract(entries)
    assert contract["source_layer_lane_release_contracts"]["corridor"]["strict_release_tickers"] == ["000001"]


def test_build_source_layer_release_contract_empty_entries() -> None:
    contract = _build_source_layer_release_contract([])
    assert contract["source_layer_strict_release_tickers"] == []
    assert contract["source_layer_validation_only_tickers"] == []
    assert contract["source_layer_lane_release_contracts"] == {}


def test_build_source_layer_release_contract_unknown_lane_defaults() -> None:
    entries = [{"ticker": "000001", "source_layer_release_stage": "validation_only"}]  # no lane
    contract = _build_source_layer_release_contract(entries)
    assert "unknown" in contract["source_layer_lane_release_contracts"]


# ---------------------------------------------------------------------------
# build_cooldown_review_shadow_payload
# ---------------------------------------------------------------------------


def test_build_cooldown_review_shadow_payload_sets_lane_and_reason() -> None:
    candidates = [_cand("000001"), _cand("000002")]
    shadow_candidates, entries = build_cooldown_review_shadow_payload(
        candidates=candidates,
        cutoff_reference=1000.0,
        min_avg_amount_20d=200.0,
        review_focus_tickers={"000001"},
        visibility_gap_tickers={"000002"},
    )
    assert len(shadow_candidates) == 2
    assert all(c.candidate_pool_lane == "cooldown_review" for c in shadow_candidates)
    assert all(c.candidate_pool_shadow_reason == "cooldown_review_shadow" for c in shadow_candidates)
    # focus flag
    assert shadow_candidates[0].shadow_focus_selected is True
    assert shadow_candidates[1].shadow_focus_selected is False
    # visibility gap flag
    assert shadow_candidates[0].shadow_visibility_gap_selected is False
    assert shadow_candidates[1].shadow_visibility_gap_selected is True
    # cooldown_review lane → always validation_only
    assert shadow_candidates[0].source_layer_release_stage == "validation_only"


def test_build_cooldown_review_shadow_payload_shares_computed() -> None:
    candidates = [_cand("000001", avg_volume=400.0)]
    _, entries = build_cooldown_review_shadow_payload(
        candidates=candidates,
        cutoff_reference=1000.0,
        min_avg_amount_20d=200.0,
        review_focus_tickers=set(),
        visibility_gap_tickers=set(),
    )
    assert entries[0]["avg_amount_share_of_cutoff"] == 0.4
    assert entries[0]["avg_amount_share_of_min_gate"] == 2.0
    assert entries[0]["cooldown_review"] is True


def test_build_cooldown_review_shadow_payload_empty() -> None:
    shadow_candidates, entries = build_cooldown_review_shadow_payload(
        candidates=[],
        cutoff_reference=1000.0,
        min_avg_amount_20d=200.0,
        review_focus_tickers=set(),
        visibility_gap_tickers=set(),
    )
    assert shadow_candidates == []
    assert entries == []


# ---------------------------------------------------------------------------
# select_shadow_rows
# ---------------------------------------------------------------------------


def _liquidity_key(c: CandidateStock) -> tuple[int, float, float, str]:
    return (0, float(c.avg_volume_20d), float(c.market_cap), c.ticker)


def test_select_shadow_rows_visibility_gap_first() -> None:
    rows: list[ShadowRankRow] = [
        (10.0, 1, _cand("000001"), False, False),  # neither
        (5.0, 2, _cand("000002"), False, True),    # visibility gap
    ]
    selected = select_shadow_rows(
        rows=rows, max_tickers=2, focus_tickers=set(), visibility_gap_tickers={"000002"}, liquidity_sort_key=_liquidity_key
    )
    tickers = [row[2].ticker for row in selected]
    assert tickers[0] == "000002"  # visibility gap prioritized


def test_select_shadow_rows_caps_at_max() -> None:
    rows = [(float(i), i, _cand(f"{i:06d}"), False, False) for i in range(1, 6)]
    selected = select_shadow_rows(
        rows=rows, max_tickers=3, focus_tickers=set(), visibility_gap_tickers=set(), liquidity_sort_key=_liquidity_key
    )
    assert len(selected) == 3


def test_select_shadow_rows_focus_before_all() -> None:
    rows = [
        (10.0, 1, _cand("000001"), False, False),
        (8.0, 2, _cand("000002"), True, False),  # focus
    ]
    selected = select_shadow_rows(
        rows=rows, max_tickers=2, focus_tickers={"000002"}, visibility_gap_tickers=set(), liquidity_sort_key=_liquidity_key
    )
    tickers = [row[2].ticker for row in selected]
    assert tickers[0] == "000002"  # focus before plain


def test_select_shadow_rows_dedupes_ticker() -> None:
    rows = [
        (10.0, 1, _cand("000001"), False, True),
        (5.0, 2, _cand("000001"), True, False),  # same ticker, duplicate
    ]
    selected = select_shadow_rows(
        rows=rows, max_tickers=5, focus_tickers={"000001"}, visibility_gap_tickers={"000001"}, liquidity_sort_key=_liquidity_key
    )
    assert len(selected) == 1  # deduped


def test_select_shadow_rows_empty_rows() -> None:
    selected = select_shadow_rows(
        rows=[], max_tickers=5, focus_tickers=set(), visibility_gap_tickers=set(), liquidity_sort_key=_liquidity_key
    )
    assert selected == []


# ---------------------------------------------------------------------------
# build_shadow_lane_payload
# ---------------------------------------------------------------------------


def test_build_shadow_lane_payload_basic() -> None:
    rows: list[ShadowRankRow] = [
        (0.5, 3, _cand("000001", avg_volume=500.0), True, False),
    ]
    candidates, entries = build_shadow_lane_payload(
        selected_rows=rows,
        cutoff_reference=1000.0,
        min_avg_amount_20d=200.0,
        lane="corridor",
        reason="below_cutoff",
        rank_key="cutoff_share",
        focus_tickers={"000001"},
        visibility_gap_tickers=set(),
    )
    assert len(candidates) == 1
    c = candidates[0]
    assert c.candidate_pool_lane == "corridor"
    assert c.candidate_pool_rank == 3
    assert c.shadow_focus_selected is True
    assert c.source_layer_release_stage == "strict_release"  # focus + non-cooldown
    assert entries[0]["cutoff_share"] == 0.5
    assert entries[0]["avg_amount_share_of_min_gate"] == 2.5


def test_build_shadow_lane_payload_visibility_gap_reason_suffix() -> None:
    rows: list[ShadowRankRow] = [
        (0.3, 1, _cand("000001"), False, True),  # visibility_gap_relaxed_band=True
    ]
    candidates, entries = build_shadow_lane_payload(
        selected_rows=rows,
        cutoff_reference=1000.0,
        min_avg_amount_20d=200.0,
        lane="rebucket",
        reason="post_gate",
        rank_key="cutoff_share",
        focus_tickers=set(),
        visibility_gap_tickers={"000001"},
    )
    assert candidates[0].candidate_pool_shadow_reason == "post_gate_visibility_gap_relaxed_band"


def test_build_shadow_lane_payload_focus_reason_suffix() -> None:
    rows: list[ShadowRankRow] = [
        (0.3, 1, _cand("000001"), True, False),  # focus_relaxed_band=True (no visibility gap)
    ]
    candidates, _ = build_shadow_lane_payload(
        selected_rows=rows,
        cutoff_reference=1000.0,
        min_avg_amount_20d=200.0,
        lane="rebucket",
        reason="post_gate",
        rank_key="cutoff_share",
        focus_tickers={"000001"},
        visibility_gap_tickers=set(),
    )
    assert candidates[0].candidate_pool_shadow_reason == "post_gate_focus_relaxed_band"


def test_build_shadow_lane_payload_empty() -> None:
    candidates, entries = build_shadow_lane_payload(
        selected_rows=[],
        cutoff_reference=1000.0,
        min_avg_amount_20d=200.0,
        lane="corridor",
        reason="below_cutoff",
        rank_key="cutoff_share",
        focus_tickers=set(),
        visibility_gap_tickers=set(),
    )
    assert candidates == []
    assert entries == []


# ---------------------------------------------------------------------------
# count_shadow_lanes
# ---------------------------------------------------------------------------


def test_count_shadow_lanes_groups_by_lane() -> None:
    entries = [
        {"candidate_pool_lane": "corridor"},
        {"candidate_pool_lane": "corridor"},
        {"candidate_pool_lane": "rebucket"},
        {"candidate_pool_lane": "cooldown_review"},
    ]
    assert count_shadow_lanes(entries) == {"corridor": 2, "rebucket": 1, "cooldown_review": 1}


def test_count_shadow_lanes_missing_lane_defaults_unknown() -> None:
    entries = [{"ticker": "000001"}, {"candidate_pool_lane": None}]
    counts = count_shadow_lanes(entries)
    assert counts == {"unknown": 2}


def test_count_shadow_lanes_empty() -> None:
    assert count_shadow_lanes([]) == {}


# ---------------------------------------------------------------------------
# classify_overflow_candidate
# ---------------------------------------------------------------------------


def _classify_kwargs(**overrides):
    base = dict(
        candidate=_cand("000001"),
        rank=5,
        cutoff_share=0.4,
        min_gate_share=1.5,
        corridor_focus_tickers=set(),
        rebucket_focus_tickers=set(),
        corridor_visibility_gap_tickers=set(),
        rebucket_visibility_gap_tickers=set(),
        corridor_min_gate_share=1.0,
        corridor_max_cutoff_share=0.5,
        corridor_focus_min_gate_share=0.8,
        corridor_focus_max_cutoff_share=0.6,
        corridor_focus_low_gate_max_cutoff_share=0.55,
        corridor_visibility_gap_max_cutoff_share=0.7,
        rebucket_min_gate_share=0.8,
        rebucket_min_cutoff_share=0.3,
        rebucket_max_cutoff_share=0.5,
        rebucket_focus_min_cutoff_share=0.25,
        rebucket_visibility_gap_min_cutoff_share=0.2,
    )
    base.update(overrides)
    return base


def test_classify_overflow_corridor_basic() -> None:
    result = classify_overflow_candidate(**_classify_kwargs(min_gate_share=1.5, cutoff_share=0.4))
    assert result is not None
    lane, row = result
    assert lane == "layer_a_liquidity_corridor"
    assert row[0] == 1.5  # score = min_gate_share
    assert row[1] == 5    # rank


def test_classify_overflow_corridor_visibility_gap() -> None:
    result = classify_overflow_candidate(
        **_classify_kwargs(
            min_gate_share=1.2,
            cutoff_share=0.65,
            corridor_visibility_gap_tickers={"000001"},
        )
    )
    assert result is not None
    assert result[0] == "layer_a_liquidity_corridor"
    assert result[1][4] is True  # visibility_gap_relaxed_band


def test_classify_overflow_corridor_focus() -> None:
    result = classify_overflow_candidate(
        **_classify_kwargs(
            min_gate_share=1.2,
            cutoff_share=0.55,
            corridor_focus_tickers={"000001"},
        )
    )
    assert result is not None
    assert result[0] == "layer_a_liquidity_corridor"
    assert result[1][3] is True  # focus_relaxed_band


def test_classify_overflow_rebucket_basic() -> None:
    result = classify_overflow_candidate(
        **_classify_kwargs(
            min_gate_share=0.9,
            cutoff_share=0.35,
            # Make corridor fail: cutoff too high for corridor (0.4 > 0.5 fails? use 0.35 < 0.5 ok → corridor)
            corridor_max_cutoff_share=0.3,  # force corridor to fail (0.35 > 0.3)
        )
    )
    assert result is not None
    assert result[0] == "post_gate_liquidity_competition"
    assert result[1][0] == 0.35  # score = cutoff_share for rebucket


def test_classify_overflow_rebucket_visibility_gap() -> None:
    # min_gate 0.9 < corridor_min 1.0 → all corridor checks fail.
    # rebucket_min_cutoff=0.5 (basic needs cutoff>=0.5) fails for cutoff=0.35,
    # but visibility_gap variant (min_cutoff=0.3) passes.
    result = classify_overflow_candidate(
        **_classify_kwargs(
            min_gate_share=0.9,
            cutoff_share=0.35,
            rebucket_min_cutoff_share=0.5,
            rebucket_visibility_gap_min_cutoff_share=0.3,
            rebucket_visibility_gap_tickers={"000001"},
        )
    )
    assert result is not None
    assert result[0] == "post_gate_liquidity_competition"
    assert result[1][4] is True


def test_classify_overflow_rebucket_focus() -> None:
    # rebucket_min_cutoff=0.5 (basic fails for 0.35), focus variant (min_cutoff=0.3) passes.
    result = classify_overflow_candidate(
        **_classify_kwargs(
            min_gate_share=0.9,
            cutoff_share=0.35,
            rebucket_min_cutoff_share=0.5,
            rebucket_focus_min_cutoff_share=0.3,
            rebucket_focus_tickers={"000001"},
        )
    )
    assert result is not None
    assert result[0] == "post_gate_liquidity_competition"
    assert result[1][3] is True


def test_classify_overflow_returns_none_when_no_match() -> None:
    result = classify_overflow_candidate(
        **_classify_kwargs(
            min_gate_share=0.1,  # too low for any gate
            cutoff_share=0.9,    # too high for corridor
            corridor_max_cutoff_share=0.5,
            corridor_min_gate_share=1.0,
            rebucket_min_gate_share=0.8,
            rebucket_max_cutoff_share=0.5,
        )
    )
    assert result is None


def test_classify_overflow_annotates_candidate_shares() -> None:
    result = classify_overflow_candidate(**_classify_kwargs(cutoff_share=0.42, min_gate_share=1.3))
    assert result is not None
    annotated = result[1][2]
    assert annotated.candidate_pool_avg_amount_share_of_cutoff == 0.42
    assert annotated.candidate_pool_avg_amount_share_of_min_gate == 1.3


# ---------------------------------------------------------------------------
# build_shadow_summary_payload
# ---------------------------------------------------------------------------


def test_build_shadow_summary_payload_structure() -> None:
    shadow_candidates = [_cand("000001"), _cand("000002")]
    shadow_entries = [
        {"ticker": "000001", "candidate_pool_lane": "corridor", "shadow_focus_selected": True, "source_layer_release_stage": "strict_release"},
        {"ticker": "000002", "candidate_pool_lane": "rebucket", "shadow_focus_selected": False, "source_layer_release_stage": "validation_only"},
    ]
    summary = build_shadow_summary_payload(
        pool_size=10,
        selected_count=10,
        overflow_count=2,
        selected_cutoff_avg_volume_20d=800.0,
        shadow_candidates=shadow_candidates,
        shadow_entries=shadow_entries,
        focus_signature="sig123",
    )
    assert summary["pool_size"] == 10
    assert summary["selected_count"] == 10
    assert summary["overflow_count"] == 2
    assert summary["selected_cutoff_avg_volume_20d"] == 800.0
    assert summary["lane_counts"] == {"corridor": 1, "rebucket": 1}
    assert summary["selected_tickers"] == ["000001", "000002"]
    assert summary["focus_tickers"] == ["000001"]
    assert summary["visibility_gap_tickers"] == []
    assert summary["focus_signature"] == "sig123"
    assert summary["shadow_recall_complete"] is True
    assert summary["shadow_recall_status"] == "computed"
    assert summary["tickers"] == shadow_entries
    assert summary["focus_filter_diagnostics"] == []
    # source layer contract keys present
    assert "source_layer_strict_release_tickers" in summary
    assert summary["source_layer_strict_release_tickers"] == ["000001"]


def test_build_shadow_summary_payload_focus_filter_diagnostics_passed_through() -> None:
    diagnostics = [{"ticker": "000001", "reason": "filtered"}]
    summary = build_shadow_summary_payload(
        pool_size=5,
        selected_count=5,
        overflow_count=0,
        selected_cutoff_avg_volume_20d=0.0,
        shadow_candidates=[],
        shadow_entries=[],
        focus_signature="",
        focus_filter_diagnostics=diagnostics,
    )
    assert summary["focus_filter_diagnostics"] == diagnostics


def test_build_shadow_summary_payload_empty_entries() -> None:
    summary = build_shadow_summary_payload(
        pool_size=10,
        selected_count=0,
        overflow_count=0,
        selected_cutoff_avg_volume_20d=0.0,
        shadow_candidates=[],
        shadow_entries=[],
        focus_signature="",
    )
    assert summary["lane_counts"] == {}
    assert summary["selected_tickers"] == []
    assert summary["focus_tickers"] == []
