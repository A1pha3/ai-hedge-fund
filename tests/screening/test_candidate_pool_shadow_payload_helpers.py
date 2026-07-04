"""Unit tests for src/screening/candidate_pool_shadow_payload_helpers.py

Covers the shadow candidate-pool payload assembly: selection/ranking context,
overflow classification routing, deep-corridor probe reservation, summary
wiring, and the no-overflow vs overflow branches of the main impl. All
collaborators are injected via stubs.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.screening.candidate_pool_shadow_payload_helpers import (
    _build_shadow_candidate_pool_payload_impl,
    _build_shadow_candidate_pool_summary,
    _build_shadow_lane_payloads,
    _classify_shadow_overflow_candidates,
    _prepare_shadow_selection_context,
    _reserve_default_deep_corridor_probe,
    _resolve_shadow_overflow_payload,
    build_shadow_candidate_pool_payload,
)
from src.screening.models import CandidateStock


def _cand(
    ticker: str,
    avg_volume: float = 500.0,
    share_of_cutoff: float | None = None,
    market_cap: float = 3.0,
) -> CandidateStock:
    return CandidateStock(
        ticker=ticker,
        name=ticker,
        avg_volume_20d=avg_volume,
        market_cap=market_cap,
        candidate_pool_avg_amount_share_of_cutoff=share_of_cutoff if share_of_cutoff is not None else 0.0,
    )


def _row(ticker: str, score: float, rank: int, share_of_cutoff: float | None = 0.5) -> tuple:
    """Build a ShadowRankRow tuple (score, rank, candidate, focus_band, vis_gap_band)."""
    return (score, rank, _cand(ticker, share_of_cutoff=share_of_cutoff), False, False)


def _liquidity_key(c: CandidateStock) -> tuple[int, float, float, str]:
    return (0, float(c.avg_volume_20d), float(c.market_cap), c.ticker)


# ---------------------------------------------------------------------------
# _reserve_default_deep_corridor_probe (pure — most branches)
# ---------------------------------------------------------------------------


def test_deep_probe_max_tickers_lt_2_returns_unchanged() -> None:
    rows = [_row("000001", 1.0, 1)]
    result = _reserve_default_deep_corridor_probe(rows=rows, selected_rows=[], max_tickers=1, cutoff_share_max=0.5)
    assert result == []


def test_deep_probe_selected_covers_all_rows_returns_unchanged() -> None:
    rows = [_row("000001", 1.0, 1), _row("000002", 0.8, 2)]
    selected = list(rows)
    result = _reserve_default_deep_corridor_probe(rows=rows, selected_rows=selected, max_tickers=3, cutoff_share_max=0.5)
    assert result == selected


def test_deep_probe_no_deep_rows_returns_unchanged() -> None:
    """Rows with share > cutoff_share_max (or <= 0) are not 'deep'."""
    rows = [_row("000001", 1.0, 1, share_of_cutoff=0.9)]  # 0.9 > 0.5 → not deep
    result = _reserve_default_deep_corridor_probe(rows=rows, selected_rows=[], max_tickers=3, cutoff_share_max=0.5)
    assert result == []


def test_deep_probe_adds_deepest_row() -> None:
    rows = [_row("000001", 1.0, 1, share_of_cutoff=0.1), _row("000002", 0.8, 2, share_of_cutoff=0.4)]
    # No selected rows, max_tickers=3 → should add the deepest (lowest share) row
    result = _reserve_default_deep_corridor_probe(rows=rows, selected_rows=[], max_tickers=3, cutoff_share_max=0.5)
    assert len(result) == 1
    assert result[0][2].ticker == "000001"  # lowest share (0.1)


def test_deep_probe_skips_when_deepest_already_selected() -> None:
    rows = [_row("000001", 1.0, 1, share_of_cutoff=0.1)]
    selected = list(rows)  # deepest already selected
    result = _reserve_default_deep_corridor_probe(rows=rows, selected_rows=selected, max_tickers=3, cutoff_share_max=0.5)
    assert result == selected


def test_deep_probe_retains_max_minus_1_plus_deepest() -> None:
    """With max_tickers=2 and 1 selected row, result = selected[:1] + deepest (if new)."""
    selected = [_row("000099", 2.0, 1, share_of_cutoff=0.9)]  # already selected, high share
    rows = selected + [_row("000001", 1.0, 2, share_of_cutoff=0.1)]  # deep candidate
    result = _reserve_default_deep_corridor_probe(rows=rows, selected_rows=selected, max_tickers=2, cutoff_share_max=0.5)
    # retained = selected[:1] = [000099], deepest = 000001 (not in retained) → [000099, 000001]
    assert len(result) == 2
    assert result[0][2].ticker == "000099"
    assert result[1][2].ticker == "000001"


def test_deep_probe_zero_share_excluded_from_deep_rows() -> None:
    """share_of_cutoff == 0.0 is excluded from deep_rows (0.0 < x is False)."""
    rows = [_row("000001", 1.0, 1, share_of_cutoff=0.0)]
    result = _reserve_default_deep_corridor_probe(rows=rows, selected_rows=[], max_tickers=3, cutoff_share_max=0.5)
    assert result == []


# ---------------------------------------------------------------------------
# _prepare_shadow_selection_context
# ---------------------------------------------------------------------------


def test_prepare_context_ranks_and_selects_top_n() -> None:
    candidates = [_cand("000001", avg_volume=300.0), _cand("000002", avg_volume=800.0), _cand("000003", avg_volume=500.0)]

    ranked, selected, cutoff_avg, cutoff_ref, shadow_cands, shadow_entries = _prepare_shadow_selection_context(
        candidates=candidates,
        pool_size=2,
        cooldown_review_candidates=None,
        candidate_liquidity_sort_key_fn=_liquidity_key,
        build_cooldown_review_shadow_payload_fn=lambda **k: ([], []),
        resolve_cooldown_shadow_review_tickers_fn=lambda: set(),
        shadow_visibility_gap_tickers=set(),
        min_avg_amount_20d=200.0,
    )
    # ranked descending by avg_volume: 000002 (800), 000003 (500), 000001 (300)
    assert [c.ticker for c in ranked] == ["000002", "000003", "000001"]
    # selected top 2 with ranks 1, 2
    assert [c.ticker for c in selected] == ["000002", "000003"]
    assert selected[0].candidate_pool_rank == 1
    assert selected[1].candidate_pool_rank == 2
    # cutoff_avg = last ranked (lowest) volume = 300
    assert cutoff_avg == 300.0
    # cutoff_ref = max(last selected volume, 1.0) = max(500, 1) = 500
    assert cutoff_ref == 500.0
    assert shadow_cands == []
    assert shadow_entries == []


def test_prepare_context_empty_candidates_safe_defaults() -> None:
    ranked, selected, cutoff_avg, cutoff_ref, _, _ = _prepare_shadow_selection_context(
        candidates=[],
        pool_size=5,
        cooldown_review_candidates=None,
        candidate_liquidity_sort_key_fn=_liquidity_key,
        build_cooldown_review_shadow_payload_fn=lambda **k: ([], []),
        resolve_cooldown_shadow_review_tickers_fn=lambda: set(),
        shadow_visibility_gap_tickers=set(),
        min_avg_amount_20d=200.0,
    )
    assert ranked == []
    assert selected == []
    assert cutoff_avg == 0.0
    assert cutoff_ref == 1.0


def test_prepare_context_builds_cooldown_shadow_when_present() -> None:
    cooldown_cands = [_cand("000099")]
    cooldown_shadow = ([_cand("000099")], [{"ticker": "000099"}])
    calls: list[dict] = []

    def _build_cooldown(**k):
        calls.append(k)
        return cooldown_shadow

    _, _, _, _, shadow_cands, shadow_entries = _prepare_shadow_selection_context(
        candidates=[_cand("000001", avg_volume=800.0)],
        pool_size=5,
        cooldown_review_candidates=cooldown_cands,
        candidate_liquidity_sort_key_fn=_liquidity_key,
        build_cooldown_review_shadow_payload_fn=_build_cooldown,
        resolve_cooldown_shadow_review_tickers_fn=lambda: {"000099"},
        shadow_visibility_gap_tickers=set(),
        min_avg_amount_20d=200.0,
    )
    assert len(shadow_cands) == 1
    assert len(shadow_entries) == 1
    # cooldown builder received review_focus_tickers + visibility_gap_tickers
    assert calls[0]["review_focus_tickers"] == {"000099"}
    assert calls[0]["visibility_gap_tickers"] == set()


# ---------------------------------------------------------------------------
# _classify_shadow_overflow_candidates
# ---------------------------------------------------------------------------


def _classify_kwargs(ranked, pool_size, classify_fn, **overrides) -> dict:
    base: dict[str, Any] = dict(
        ranked_candidates=ranked,
        pool_size=pool_size,
        min_avg_amount_20d=200.0,
        resolve_shadow_focus_tickers_fn=lambda **k: set(),
        resolve_shadow_visibility_gap_tickers_fn=lambda **k: set(),
        classify_overflow_candidate_fn=classify_fn,
        shadow_liquidity_corridor_min_gate_share=1.0,
        shadow_liquidity_corridor_max_cutoff_share=0.5,
        shadow_liquidity_corridor_focus_min_gate_share=0.8,
        shadow_liquidity_corridor_focus_max_cutoff_share=0.6,
        shadow_liquidity_corridor_focus_low_gate_max_cutoff_share=0.55,
        shadow_liquidity_corridor_visibility_gap_max_cutoff_share=0.7,
        shadow_rebucket_min_gate_share=0.8,
        shadow_rebucket_min_cutoff_share=0.3,
        shadow_rebucket_max_cutoff_share=0.5,
        shadow_rebucket_focus_min_cutoff_share=0.25,
        shadow_rebucket_visibility_gap_min_cutoff_share=0.2,
    )
    base.update(overrides)
    return base


def test_classify_overflow_routes_to_corridor() -> None:
    ranked = [_cand("000001", avg_volume=800.0), _cand("000002", avg_volume=400.0), _cand("000003", avg_volume=300.0)]

    def _classify(**k):
        if k["candidate"].ticker == "000003":
            return "layer_a_liquidity_corridor", (k["min_gate_share"], k["rank"], k["candidate"], False, False)
        return None

    overflow, cutoff_avg, corridor, rebucket = _classify_shadow_overflow_candidates(**_classify_kwargs(ranked, pool_size=2, classify_fn=_classify))
    # overflow = ranked[2:] = [000003]
    assert [c.ticker for c in overflow] == ["000003"]
    assert len(corridor) == 1
    assert len(rebucket) == 0
    assert corridor[0][2].ticker == "000003"


def test_classify_overflow_routes_to_rebucket() -> None:
    ranked = [_cand("000001", avg_volume=800.0), _cand("000002", avg_volume=400.0), _cand("000003", avg_volume=300.0)]

    def _classify(**k):
        if k["candidate"].ticker == "000003":
            return "post_gate_liquidity_competition", (k["cutoff_share"], k["rank"], k["candidate"], False, False)
        return None

    _, _, corridor, rebucket = _classify_shadow_overflow_candidates(**_classify_kwargs(ranked, pool_size=2, classify_fn=_classify))
    assert len(corridor) == 0
    assert len(rebucket) == 1


def test_classify_overflow_drops_unclassified() -> None:
    ranked = [_cand("000001", avg_volume=800.0), _cand("000002", avg_volume=400.0), _cand("000003", avg_volume=300.0)]

    def _classify(**k):
        return None  # nothing classifies

    _, _, corridor, rebucket = _classify_shadow_overflow_candidates(**_classify_kwargs(ranked, pool_size=2, classify_fn=_classify))
    assert corridor == []
    assert rebucket == []


def test_classify_overflow_cutoff_avg_floored_at_1() -> None:
    ranked = [_cand("000001", avg_volume=800.0), _cand("000002", avg_volume=0.0)]  # pool_size-1 volume = 0

    def _classify(**k):
        return None

    _, cutoff_avg, _, _ = _classify_shadow_overflow_candidates(**_classify_kwargs(ranked, pool_size=2, classify_fn=_classify))
    assert cutoff_avg == 1.0  # max(0.0, 1.0)


# ---------------------------------------------------------------------------
# _build_shadow_candidate_pool_summary
# ---------------------------------------------------------------------------


def test_build_summary_delegates_with_correct_counts() -> None:
    calls: list[dict] = []

    def _build(**k):
        calls.append(k)
        return {"computed": True}

    summary = _build_shadow_candidate_pool_summary(
        pool_size=10,
        selected_candidates=[_cand("000001"), _cand("000002")],
        overflow_count=3,
        selected_cutoff_avg_volume_20d=555.6789,
        shadow_candidates=[_cand("000003")],
        shadow_entries=[{"ticker": "000003"}],
        shadow_focus_signature_fn=lambda: "sig",
        focus_filter_diagnostics=[{"d": 1}],
        build_shadow_summary_payload_fn=_build,
    )
    assert summary == {"computed": True}
    k = calls[0]
    assert k["pool_size"] == 10
    assert k["selected_count"] == 2
    assert k["overflow_count"] == 3
    assert k["selected_cutoff_avg_volume_20d"] == 555.6789  # rounded to 4
    assert k["focus_signature"] == "sig"
    assert k["focus_filter_diagnostics"] == [{"d": 1}]


# ---------------------------------------------------------------------------
# _build_shadow_lane_payloads
# ---------------------------------------------------------------------------


def test_build_lane_payloads_invokes_select_and_build_for_both_lanes() -> None:
    corridor_rows = [_row("000001", 1.0, 3)]
    rebucket_rows = [_row("000002", 0.5, 4)]
    select_calls: list[str] = []
    build_calls: list[str] = []

    def _select(**k):
        select_calls.append(k.get("rows"))
        return k["rows"]

    def _build_lane(**k):
        build_calls.append(k["lane"])
        return ([_cand(k["lane"])], [{"lane": k["lane"]}])

    shadow_cands, shadow_entries = _build_shadow_lane_payloads(
        corridor_candidates=corridor_rows,
        rebucket_candidates=rebucket_rows,
        cutoff_avg_volume=800.0,
        min_avg_amount_20d=200.0,
        candidate_liquidity_sort_key_fn=_liquidity_key,
        resolve_shadow_focus_tickers_fn=lambda **k: set(),
        resolve_shadow_visibility_gap_tickers_fn=lambda **k: set(),
        select_shadow_rows_fn=_select,
        build_shadow_lane_payload_fn=_build_lane,
        shadow_liquidity_corridor_max_tickers=3,
        shadow_liquidity_corridor_focus_low_gate_max_cutoff_share=0.5,
        shadow_rebucket_max_tickers=2,
    )
    assert len(shadow_cands) == 2
    assert len(shadow_entries) == 2
    assert select_calls[0] is corridor_rows
    assert select_calls[1] is rebucket_rows
    assert "layer_a_liquidity_corridor" in build_calls
    assert "post_gate_liquidity_competition" in build_calls


def test_build_lane_payloads_deep_probe_applied_for_corridor_without_focus() -> None:
    """When corridor lane has no focus/visibility tickers, deep probe is applied."""
    corridor_rows = [_row("000001", 1.0, 3, share_of_cutoff=0.1)]
    select_calls: list = []

    def _select(**k):
        select_calls.append(k["rows"])
        return []  # select returns nothing → deep probe should add a row

    def _build_lane(**k):
        return ([], [])

    _build_shadow_lane_payloads(
        corridor_candidates=corridor_rows,
        rebucket_candidates=[],
        cutoff_avg_volume=800.0,
        min_avg_amount_20d=200.0,
        candidate_liquidity_sort_key_fn=_liquidity_key,
        resolve_shadow_focus_tickers_fn=lambda **k: set(),
        resolve_shadow_visibility_gap_tickers_fn=lambda **k: set(),
        select_shadow_rows_fn=_select,
        build_shadow_lane_payload_fn=_build_lane,
        shadow_liquidity_corridor_max_tickers=3,
        shadow_liquidity_corridor_focus_low_gate_max_cutoff_share=0.5,
        shadow_rebucket_max_tickers=2,
    )
    # corridor lane invoked select; deep probe path was taken (no focus/visibility)
    assert len(select_calls) >= 1


# ---------------------------------------------------------------------------
# _build_shadow_candidate_pool_payload_impl — branch coverage
# ---------------------------------------------------------------------------


def _impl_kwargs(**overrides: Any) -> dict:
    """Build minimal DI stubs; defaults make overflow candidates classify as None."""
    base: dict[str, Any] = dict(
        pool_size=10,
        cooldown_review_candidates=None,
        focus_filter_diagnostics=None,
        candidate_liquidity_sort_key_fn=_liquidity_key,
        build_cooldown_review_shadow_payload_fn=lambda **k: ([], []),
        build_shadow_summary_payload_fn=lambda **k: {"summary": True, **{kk: vv for kk, vv in k.items() if kk in ("pool_size", "overflow_count")}},
        shadow_focus_signature_fn=lambda: "",
        resolve_cooldown_shadow_review_tickers_fn=lambda: set(),
        resolve_shadow_focus_tickers_fn=lambda **k: set(),
        resolve_shadow_visibility_gap_tickers_fn=lambda **k: set(),
        classify_overflow_candidate_fn=lambda **k: None,
        select_shadow_rows_fn=lambda **k: [],
        build_shadow_lane_payload_fn=lambda **k: ([], []),
        min_avg_amount_20d=200.0,
        shadow_visibility_gap_tickers=set(),
        shadow_liquidity_corridor_min_gate_share=1.0,
        shadow_liquidity_corridor_max_cutoff_share=0.5,
        shadow_liquidity_corridor_focus_min_gate_share=0.8,
        shadow_liquidity_corridor_focus_max_cutoff_share=0.6,
        shadow_liquidity_corridor_focus_low_gate_max_cutoff_share=0.55,
        shadow_liquidity_corridor_visibility_gap_max_cutoff_share=0.7,
        shadow_rebucket_min_gate_share=0.8,
        shadow_rebucket_min_cutoff_share=0.3,
        shadow_rebucket_max_cutoff_share=0.5,
        shadow_rebucket_focus_min_cutoff_share=0.25,
        shadow_rebucket_visibility_gap_min_cutoff_share=0.2,
        shadow_liquidity_corridor_max_tickers=3,
        shadow_rebucket_max_tickers=2,
    )
    base.update(overrides)
    return base


def test_impl_no_overflow_when_candidates_le_pool_size() -> None:
    candidates = [_cand("000001", avg_volume=800.0), _cand("000002", avg_volume=500.0)]
    selected, shadow, summary = _build_shadow_candidate_pool_payload_impl(candidates, **_impl_kwargs(pool_size=10))
    assert len(selected) == 2
    assert selected[0].candidate_pool_rank == 1  # higher volume first
    assert shadow == []
    assert summary["overflow_count"] == 0


def test_impl_with_overflow_extends_shadow() -> None:
    candidates = [_cand(f"{i:06d}", avg_volume=float(1000 - i * 100)) for i in range(1, 6)]  # 5 candidates

    def _classify(**k):
        # classify all overflow as corridor
        return "layer_a_liquidity_corridor", (k["min_gate_share"], k["rank"], k["candidate"], False, False)

    def _select(**k):
        return k["rows"]

    def _build_lane(**k):
        return ([_cand("shadow_x")], [{"ticker": "shadow_x"}])

    selected, shadow, summary = _build_shadow_candidate_pool_payload_impl(
        candidates,
        **_impl_kwargs(
            pool_size=2,
            classify_overflow_candidate_fn=_classify,
            select_shadow_rows_fn=_select,
            build_shadow_lane_payload_fn=_build_lane,
        ),
    )
    assert len(selected) == 2  # pool_size
    assert len(shadow) >= 1  # overflow shadow added
    assert summary["overflow_count"] == 3  # 5 - 2


def test_impl_cooldown_shadow_included_in_no_overflow_summary() -> None:
    candidates = [_cand("000001", avg_volume=800.0)]
    cooldown_shadow = ([_cand("000099")], [{"ticker": "000099"}])

    selected, shadow, summary = _build_shadow_candidate_pool_payload_impl(
        candidates,
        **_impl_kwargs(
            pool_size=10,
            cooldown_review_candidates=[_cand("000099")],
            build_cooldown_review_shadow_payload_fn=lambda **k: cooldown_shadow,
            resolve_cooldown_shadow_review_tickers_fn=lambda: {"000099"},
        ),
    )
    assert len(selected) == 1
    assert len(shadow) == 1  # cooldown shadow candidate
    assert shadow[0].ticker == "000099"
    assert summary["overflow_count"] == 0


# ---------------------------------------------------------------------------
# build_shadow_candidate_pool_payload — entry delegation
# ---------------------------------------------------------------------------


def test_entry_delegates_to_impl() -> None:
    candidates = [_cand("000001", avg_volume=800.0)]
    result = build_shadow_candidate_pool_payload(candidates, **_impl_kwargs(pool_size=10))
    selected, shadow, summary = result
    assert len(selected) == 1
    assert summary["summary"] is True
