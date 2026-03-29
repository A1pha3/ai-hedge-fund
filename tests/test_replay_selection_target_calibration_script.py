import json

from scripts.replay_selection_target_calibration import (
    analyze_selection_target_candidate_entry_metric_grid,
    analyze_selection_target_combination_grid,
    analyze_selection_target_penalty_grid,
    analyze_selection_target_penalty_threshold_grid,
    analyze_selection_target_replay_inputs,
    analyze_selection_target_structural_variants,
    analyze_selection_target_threshold_grid,
)
from src.execution.models import LayerCResult
from src.screening.models import StrategySignal
from src.targets.router import build_selection_targets


def _make_signal(direction: int, confidence: float, completeness: float = 1.0, sub_factors: dict | None = None) -> StrategySignal:
    return StrategySignal(
        direction=direction,
        confidence=confidence,
        completeness=completeness,
        sub_factors=sub_factors or {},
    )


def _write_replay_input(tmp_path):
    watch_item = LayerCResult(
        ticker="000001",
        score_b=0.71,
        score_c=0.66,
        score_final=0.69,
        quality_score=0.65,
        decision="avoid",
        strategy_signals={
            "trend": _make_signal(
                1,
                84.0,
                sub_factors={
                    "momentum": {"direction": 1, "confidence": 86.0, "completeness": 1.0},
                    "adx_strength": {"direction": 1, "confidence": 78.0, "completeness": 1.0},
                    "ema_alignment": {"direction": 1, "confidence": 74.0, "completeness": 1.0},
                    "volatility": {"direction": 1, "confidence": 66.0, "completeness": 1.0},
                    "long_trend_alignment": {"direction": 0, "confidence": 30.0, "completeness": 1.0},
                },
            ),
            "event_sentiment": _make_signal(
                1,
                76.0,
                sub_factors={
                    "event_freshness": {"direction": 1, "confidence": 90.0, "completeness": 1.0},
                    "news_sentiment": {"direction": 1, "confidence": 65.0, "completeness": 1.0},
                },
            ),
            "mean_reversion": _make_signal(-1, 18.0),
        },
        agent_contribution_summary={"cohort_contributions": {"analyst": 0.22, "investor": 0.11}},
    )
    selection_targets, summary = build_selection_targets(
        trade_date="20260322",
        watchlist=[watch_item],
        rejected_entries=[],
        supplemental_short_trade_entries=[],
        buy_order_tickers={"000001"},
        target_mode="dual_target",
    )
    assert selection_targets["000001"].short_trade is not None
    replay_input = {
        "artifact_version": "v1",
        "run_id": "test_run",
        "trade_date": "2026-03-22",
        "market": "CN",
        "target_mode": "dual_target",
        "pipeline_config_snapshot": {},
        "source_summary": {
            "watchlist_count": 1,
            "rejected_entry_count": 0,
            "supplemental_short_trade_entry_count": 0,
            "buy_order_ticker_count": 1,
        },
        "watchlist": [watch_item.model_dump(mode="json")],
        "rejected_entries": [],
        "supplemental_short_trade_entries": [],
        "buy_order_tickers": ["000001"],
        "selection_targets": {ticker: evaluation.model_dump(mode="json") for ticker, evaluation in selection_targets.items()},
        "target_summary": summary.model_dump(mode="json"),
    }
    replay_input_path = tmp_path / "selection_target_replay_input.json"
    replay_input_path.write_text(json.dumps(replay_input, ensure_ascii=False, indent=2), encoding="utf-8")
    return replay_input_path


def _write_selection_snapshot(tmp_path):
    watch_item = LayerCResult(
        ticker="000001",
        score_b=0.71,
        score_c=0.66,
        score_final=0.69,
        quality_score=0.65,
        decision="avoid",
        strategy_signals={
            "trend": _make_signal(
                1,
                84.0,
                sub_factors={
                    "momentum": {"direction": 1, "confidence": 86.0, "completeness": 1.0},
                    "adx_strength": {"direction": 1, "confidence": 78.0, "completeness": 1.0},
                    "ema_alignment": {"direction": 1, "confidence": 74.0, "completeness": 1.0},
                    "volatility": {"direction": 1, "confidence": 66.0, "completeness": 1.0},
                    "long_trend_alignment": {"direction": 0, "confidence": 30.0, "completeness": 1.0},
                },
            ),
            "event_sentiment": _make_signal(
                1,
                76.0,
                sub_factors={
                    "event_freshness": {"direction": 1, "confidence": 90.0, "completeness": 1.0},
                    "news_sentiment": {"direction": 1, "confidence": 65.0, "completeness": 1.0},
                },
            ),
            "mean_reversion": _make_signal(-1, 18.0),
        },
        agent_contribution_summary={"cohort_contributions": {"analyst": 0.22, "investor": 0.11}},
    )
    selection_targets, summary = build_selection_targets(
        trade_date="20260322",
        watchlist=[watch_item],
        rejected_entries=[],
        supplemental_short_trade_entries=[],
        buy_order_tickers={"000001"},
        target_mode="dual_target",
    )
    snapshot_payload = {
        "artifact_version": "v1",
        "run_id": "test_snapshot_run",
        "trade_date": "2026-03-22",
        "market": "CN",
        "target_mode": "dual_target",
        "pipeline_config_snapshot": {},
        "universe_summary": {
            "watchlist_count": 1,
            "buy_order_count": 1,
        },
        "selection_targets": {ticker: evaluation.model_dump(mode="json") for ticker, evaluation in selection_targets.items()},
        "target_summary": summary.model_dump(mode="json"),
        "buy_orders": [{"ticker": "000001", "shares": 100, "amount": 1000.0}],
        "funnel_diagnostics": {
            "filters": {
                "watchlist": {
                    "filtered_count": 0,
                    "reason_counts": {},
                    "tickers": [],
                    "selected_tickers": ["000001"],
                    "selected_entries": [watch_item.model_dump(mode="json")],
                },
                "short_trade_candidates": {
                    "candidate_count": 0,
                    "reason_counts": {},
                    "selected_tickers": [],
                    "tickers": [],
                },
            }
        },
    }
    snapshot_path = tmp_path / "selection_snapshot.json"
    snapshot_path.write_text(json.dumps(snapshot_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return snapshot_path


def test_replay_selection_target_calibration_reproduces_stored_decisions(tmp_path):
    replay_input_path = _write_replay_input(tmp_path)

    analysis = analyze_selection_target_replay_inputs(replay_input_path)

    assert analysis["replay_input_count"] == 1
    assert analysis["trade_date_count"] == 1
    assert analysis["decision_mismatch_count"] == 0
    assert analysis["decision_transition_counts"] == {"selected->selected": 1}
    assert analysis["signal_availability"] == {"has_any": 1}
    assert analysis["available_strategy_signal_counts"] == {"trend": 1, "event_sentiment": 1, "mean_reversion": 1}


def test_replay_selection_target_calibration_accepts_selection_snapshot_input(tmp_path):
    snapshot_path = _write_selection_snapshot(tmp_path)

    analysis = analyze_selection_target_replay_inputs(snapshot_path)

    assert analysis["replay_input_count"] == 1
    assert analysis["trade_date_count"] == 1
    assert analysis["decision_mismatch_count"] == 0
    assert analysis["decision_transition_counts"] == {"selected->selected": 1}
    assert analysis["signal_availability"] == {"has_any": 1}
    assert analysis["available_strategy_signal_counts"] == {"trend": 1, "event_sentiment": 1, "mean_reversion": 1}


def test_replay_selection_target_calibration_detects_threshold_drift(tmp_path):
    replay_input_path = _write_replay_input(tmp_path)

    analysis = analyze_selection_target_replay_inputs(replay_input_path, select_threshold=0.99)

    assert analysis["decision_mismatch_count"] == 1
    assert analysis["mismatch_examples"][0]["ticker"] == "000001"
    assert analysis["mismatch_examples"][0]["stored_decision"] == "selected"
    assert analysis["mismatch_examples"][0]["replayed_decision"] != "selected"
    assert analysis["mismatch_examples"][0]["replayed_score_target"] is not None
    assert analysis["mismatch_examples"][0]["replayed_gap_to_selected"] > 0
    assert analysis["mismatch_examples"][0]["replayed_top_reasons"]
    assert analysis["mismatch_examples"][0]["replayed_metrics_payload"]["weighted_positive_contributions"]
    assert analysis["mismatch_examples"][0]["replayed_metrics_payload"]["weighted_negative_contributions"]


def test_replay_selection_target_calibration_emits_focused_score_diagnostics(tmp_path):
    replay_input_path = _write_replay_input(tmp_path)

    analysis = analyze_selection_target_replay_inputs(replay_input_path, focus_tickers=["000001"])

    assert analysis["focus_tickers"] == ["000001"]
    assert len(analysis["focused_score_diagnostics"]) == 1
    diagnostic = analysis["focused_score_diagnostics"][0]
    assert diagnostic["ticker"] == "000001"
    assert diagnostic["candidate_source"] == "layer_c_watchlist"
    assert diagnostic["candidate_reason_codes"] == []
    assert diagnostic["replayed_metrics_payload"]["weighted_positive_contributions"]
    assert diagnostic["replayed_metrics_payload"]["thresholds"]["select_threshold"] == 0.58
    assert diagnostic["replayed_total_positive_contribution"] is not None
    assert diagnostic["replayed_total_negative_contribution"] is not None
    assert diagnostic["replayed_gap_to_near_miss"] <= 0


def test_replay_selection_target_threshold_grid_finds_first_promotions(tmp_path):
    replay_input_path = _write_replay_input(tmp_path)

    grid = analyze_selection_target_threshold_grid(
        replay_input_path,
        select_thresholds=[0.99, 0.58],
        near_miss_thresholds=[0.80, 0.46],
    )

    assert grid["grid_row_count"] == 3
    assert grid["first_row_with_selected"]["select_threshold"] == 0.58
    assert grid["first_row_with_selected"]["near_miss_threshold"] == 0.46
    assert grid["first_row_with_selected"]["promoted_to_selected"] == []
    assert grid["first_row_with_near_miss"]["select_threshold"] == 0.99
    assert grid["first_row_with_near_miss"]["near_miss_threshold"] == 0.46
    assert grid["first_row_with_near_miss"]["promoted_to_near_miss"] == []
    assert grid["first_row_with_near_miss"]["demoted_from_selected"] == ["000001"]


def test_replay_selection_target_structural_variant_releases_bearish_conflict_block(tmp_path):
    watch_item = LayerCResult(
        ticker="300394",
        score_b=0.62,
        score_c=0.18,
        score_final=0.44,
        quality_score=0.88,
        decision="watch",
        bc_conflict="b_positive_c_strong_bearish",
        strategy_signals={
            "trend": _make_signal(
                1,
                86.0,
                sub_factors={
                    "momentum": {"direction": 1, "confidence": 90.0, "completeness": 1.0},
                    "adx_strength": {"direction": 1, "confidence": 80.0, "completeness": 1.0},
                    "ema_alignment": {"direction": 1, "confidence": 82.0, "completeness": 1.0},
                    "volatility": {"direction": 1, "confidence": 60.0, "completeness": 1.0},
                    "long_trend_alignment": {"direction": 0, "confidence": 22.0, "completeness": 1.0},
                },
            ),
            "event_sentiment": _make_signal(
                1,
                74.0,
                sub_factors={
                    "event_freshness": {"direction": 1, "confidence": 88.0, "completeness": 1.0},
                    "news_sentiment": {"direction": 1, "confidence": 68.0, "completeness": 1.0},
                },
            ),
            "mean_reversion": _make_signal(0, 20.0),
        },
        agent_contribution_summary={"cohort_contributions": {"analyst": 0.16, "investor": 0.08}},
    )
    selection_targets, summary = build_selection_targets(
        trade_date="20260322",
        watchlist=[watch_item],
        rejected_entries=[],
        supplemental_short_trade_entries=[],
        buy_order_tickers=set(),
        target_mode="dual_target",
    )
    assert selection_targets["300394"].short_trade is not None
    assert selection_targets["300394"].short_trade.decision == "blocked"
    replay_input = {
        "artifact_version": "v1",
        "run_id": "test_structural_variant",
        "trade_date": "2026-03-22",
        "market": "CN",
        "target_mode": "dual_target",
        "pipeline_config_snapshot": {},
        "source_summary": {
            "watchlist_count": 1,
            "rejected_entry_count": 0,
            "supplemental_short_trade_entry_count": 0,
            "buy_order_ticker_count": 0,
        },
        "watchlist": [watch_item.model_dump(mode="json")],
        "rejected_entries": [],
        "supplemental_short_trade_entries": [],
        "buy_order_tickers": [],
        "selection_targets": {ticker: evaluation.model_dump(mode="json") for ticker, evaluation in selection_targets.items()},
        "target_summary": summary.model_dump(mode="json"),
    }
    replay_input_path = tmp_path / "selection_target_replay_input.json"
    replay_input_path.write_text(json.dumps(replay_input, ensure_ascii=False, indent=2), encoding="utf-8")

    analysis = analyze_selection_target_structural_variants(
        replay_input_path,
        structural_variants=["baseline", "no_bearish_conflict_block"],
        select_threshold=0.58,
        near_miss_threshold=0.46,
    )

    assert analysis["variant_row_count"] == 2
    assert analysis["first_row_releasing_blocked"]["structural_variant"] == "no_bearish_conflict_block"
    assert analysis["first_row_releasing_blocked"]["released_from_blocked"] == ["300394"]
    baseline_row = analysis["rows"][0]
    variant_row = analysis["rows"][1]
    assert baseline_row["replayed_short_trade_decision_counts"] == {"blocked": 1}
    assert variant_row["replayed_short_trade_decision_counts"] in ({"rejected": 1}, {"near_miss": 1}, {"selected": 1})


def test_replay_selection_target_softer_penalty_weights_raise_score(tmp_path):
    watch_item = LayerCResult(
        ticker="300394",
        score_b=0.62,
        score_c=0.18,
        score_final=0.44,
        quality_score=0.88,
        decision="watch",
        bc_conflict="b_positive_c_strong_bearish",
        strategy_signals={
            "trend": _make_signal(
                1,
                86.0,
                sub_factors={
                    "momentum": {"direction": 1, "confidence": 90.0, "completeness": 1.0},
                    "adx_strength": {"direction": 1, "confidence": 80.0, "completeness": 1.0},
                    "ema_alignment": {"direction": 1, "confidence": 82.0, "completeness": 1.0},
                    "volatility": {"direction": 1, "confidence": 60.0, "completeness": 1.0},
                    "long_trend_alignment": {"direction": 0, "confidence": 22.0, "completeness": 1.0},
                },
            ),
            "event_sentiment": _make_signal(
                1,
                74.0,
                sub_factors={
                    "event_freshness": {"direction": 1, "confidence": 88.0, "completeness": 1.0},
                    "news_sentiment": {"direction": 1, "confidence": 68.0, "completeness": 1.0},
                },
            ),
            "mean_reversion": _make_signal(0, 20.0),
        },
        agent_contribution_summary={"cohort_contributions": {"analyst": 0.16, "investor": 0.08}},
    )
    selection_targets, summary = build_selection_targets(
        trade_date="20260322",
        watchlist=[watch_item],
        rejected_entries=[],
        supplemental_short_trade_entries=[],
        buy_order_tickers=set(),
        target_mode="dual_target",
    )
    replay_input = {
        "artifact_version": "v1",
        "run_id": "test_softer_penalty_weights",
        "trade_date": "2026-03-22",
        "market": "CN",
        "target_mode": "dual_target",
        "pipeline_config_snapshot": {},
        "source_summary": {
            "watchlist_count": 1,
            "rejected_entry_count": 0,
            "supplemental_short_trade_entry_count": 0,
            "buy_order_ticker_count": 0,
        },
        "watchlist": [watch_item.model_dump(mode="json")],
        "rejected_entries": [],
        "supplemental_short_trade_entries": [],
        "buy_order_tickers": [],
        "selection_targets": {ticker: evaluation.model_dump(mode="json") for ticker, evaluation in selection_targets.items()},
        "target_summary": summary.model_dump(mode="json"),
    }
    replay_input_path = tmp_path / "selection_target_replay_input.json"
    replay_input_path.write_text(json.dumps(replay_input, ensure_ascii=False, indent=2), encoding="utf-8")

    base_analysis = analyze_selection_target_replay_inputs(
        replay_input_path,
        structural_variant="no_bearish_conflict_block",
        focus_tickers=["300394"],
    )
    softer_analysis = analyze_selection_target_replay_inputs(
        replay_input_path,
        structural_variant="no_bearish_conflict_softer_penalty_weights",
        focus_tickers=["300394"],
    )

    base_diag = base_analysis["focused_score_diagnostics"][0]
    softer_diag = softer_analysis["focused_score_diagnostics"][0]
    assert softer_diag["replayed_score_target"] >= base_diag["replayed_score_target"]
    assert softer_diag["replayed_metrics_payload"]["thresholds"]["stale_score_penalty_weight"] == 0.06
    assert softer_diag["replayed_metrics_payload"]["thresholds"]["extension_score_penalty_weight"] == 0.04


def test_replay_selection_target_split_penalty_variants_raise_expected_components(tmp_path):
    watch_item = LayerCResult(
        ticker="300394",
        score_b=0.62,
        score_c=0.18,
        score_final=0.44,
        quality_score=0.88,
        decision="avoid",
        bc_conflict="b_positive_c_strong_bearish",
        strategy_signals={
            "trend": _make_signal(
                1,
                86.0,
                sub_factors={
                    "momentum": {"direction": 1, "confidence": 90.0, "completeness": 1.0},
                    "adx_strength": {"direction": 1, "confidence": 80.0, "completeness": 1.0},
                    "ema_alignment": {"direction": 1, "confidence": 82.0, "completeness": 1.0},
                    "volatility": {"direction": 1, "confidence": 60.0, "completeness": 1.0},
                    "long_trend_alignment": {"direction": 0, "confidence": 22.0, "completeness": 1.0},
                },
            ),
            "event_sentiment": _make_signal(
                1,
                74.0,
                sub_factors={
                    "event_freshness": {"direction": 1, "confidence": 88.0, "completeness": 1.0},
                    "news_sentiment": {"direction": 1, "confidence": 68.0, "completeness": 1.0},
                },
            ),
            "mean_reversion": _make_signal(0, 20.0),
        },
        agent_contribution_summary={"cohort_contributions": {"analyst": 0.16, "investor": 0.08}},
    )
    selection_targets, summary = build_selection_targets(
        trade_date="20260322",
        watchlist=[watch_item],
        rejected_entries=[],
        supplemental_short_trade_entries=[],
        buy_order_tickers=set(),
        target_mode="dual_target",
    )
    replay_input = {
        "artifact_version": "v1",
        "run_id": "test_split_penalty_variants",
        "trade_date": "2026-03-22",
        "market": "CN",
        "target_mode": "dual_target",
        "pipeline_config_snapshot": {},
        "source_summary": {
            "watchlist_count": 1,
            "rejected_entry_count": 0,
            "supplemental_short_trade_entry_count": 0,
            "buy_order_ticker_count": 0,
        },
        "watchlist": [watch_item.model_dump(mode="json")],
        "rejected_entries": [],
        "supplemental_short_trade_entries": [],
        "buy_order_tickers": [],
        "selection_targets": {ticker: evaluation.model_dump(mode="json") for ticker, evaluation in selection_targets.items()},
        "target_summary": summary.model_dump(mode="json"),
    }
    replay_input_path = tmp_path / "selection_target_replay_input.json"
    replay_input_path.write_text(json.dumps(replay_input, ensure_ascii=False, indent=2), encoding="utf-8")

    base_analysis = analyze_selection_target_replay_inputs(
        replay_input_path,
        structural_variant="no_bearish_conflict_block",
        focus_tickers=["300394"],
    )
    avoid_analysis = analyze_selection_target_replay_inputs(
        replay_input_path,
        structural_variant="no_bearish_conflict_lower_avoid_penalty",
        focus_tickers=["300394"],
    )
    stale_analysis = analyze_selection_target_replay_inputs(
        replay_input_path,
        structural_variant="no_bearish_conflict_lower_stale_penalty_weight",
        focus_tickers=["300394"],
    )
    extension_analysis = analyze_selection_target_replay_inputs(
        replay_input_path,
        structural_variant="no_bearish_conflict_lower_extension_penalty_weight",
        focus_tickers=["300394"],
    )

    base_score = base_analysis["focused_score_diagnostics"][0]["replayed_score_target"]
    avoid_score = avoid_analysis["focused_score_diagnostics"][0]["replayed_score_target"]
    stale_score = stale_analysis["focused_score_diagnostics"][0]["replayed_score_target"]
    extension_score = extension_analysis["focused_score_diagnostics"][0]["replayed_score_target"]

    assert avoid_score > base_score
    assert stale_score >= base_score
    assert extension_score >= base_score
    assert avoid_analysis["focused_score_diagnostics"][0]["replayed_metrics_payload"]["thresholds"]["stale_score_penalty_weight"] == 0.12
    assert stale_analysis["focused_score_diagnostics"][0]["replayed_metrics_payload"]["thresholds"]["stale_score_penalty_weight"] == 0.06
    assert extension_analysis["focused_score_diagnostics"][0]["replayed_metrics_payload"]["thresholds"]["extension_score_penalty_weight"] == 0.04


def test_replay_selection_target_candidate_entry_filter_excludes_watchlist_avoid_boundary_entries(tmp_path):
    rejected_entry = {
        "ticker": "300502",
        "score_b": 0.3829,
        "score_c": -0.1194,
        "score_final": 0.1568,
        "quality_score": 0.9375,
        "decision": "avoid",
        "bc_conflict": "b_positive_c_strong_bearish",
        "candidate_source": "watchlist_filter_diagnostics",
        "candidate_reason_codes": ["decision_avoid", "score_final_below_watchlist_threshold"],
        "reason": "decision_avoid",
        "strategy_signals": {
            "trend": _make_signal(
                1,
                70.0,
                sub_factors={
                    "momentum": {"direction": 0, "confidence": 0.0, "completeness": 1.0},
                    "adx_strength": {"direction": 1, "confidence": 50.0, "completeness": 1.0},
                    "ema_alignment": {"direction": 1, "confidence": 100.0, "completeness": 1.0},
                    "volatility": {"direction": 0, "confidence": 0.0, "completeness": 1.0},
                    "long_trend_alignment": {"direction": 1, "confidence": 100.0, "completeness": 1.0},
                },
            ),
            "event_sentiment": _make_signal(
                0,
                0.0,
                sub_factors={
                    "event_freshness": {"direction": 0, "confidence": 0.0, "completeness": 1.0},
                    "news_sentiment": {"direction": 0, "confidence": 0.0, "completeness": 1.0},
                },
            ),
            "mean_reversion": _make_signal(0, 0.0),
        },
        "agent_contribution_summary": {"cohort_contributions": {"analyst": -0.0646, "investor": -0.0548}},
    }
    rejected_entry_json = {
        **rejected_entry,
        "strategy_signals": {name: signal.model_dump(mode="json") for name, signal in rejected_entry["strategy_signals"].items()},
    }
    selection_targets, summary = build_selection_targets(
        trade_date="20260322",
        watchlist=[],
        rejected_entries=[rejected_entry],
        supplemental_short_trade_entries=[],
        buy_order_tickers=set(),
        target_mode="dual_target",
    )
    replay_input = {
        "artifact_version": "v1",
        "run_id": "test_candidate_entry_filter",
        "trade_date": "2026-03-22",
        "market": "CN",
        "target_mode": "dual_target",
        "pipeline_config_snapshot": {},
        "source_summary": {
            "watchlist_count": 0,
            "rejected_entry_count": 1,
            "supplemental_short_trade_entry_count": 0,
            "buy_order_ticker_count": 0,
        },
        "watchlist": [],
        "rejected_entries": [rejected_entry_json],
        "supplemental_short_trade_entries": [],
        "buy_order_tickers": [],
        "selection_targets": {ticker: evaluation.model_dump(mode="json") for ticker, evaluation in selection_targets.items()},
        "target_summary": summary.model_dump(mode="json"),
    }
    replay_input_path = tmp_path / "selection_target_replay_input.json"
    replay_input_path.write_text(json.dumps(replay_input, ensure_ascii=False, indent=2), encoding="utf-8")

    baseline_analysis = analyze_selection_target_replay_inputs(
        replay_input_path,
        structural_variant="baseline",
        focus_tickers=["300502"],
    )
    filtered_analysis = analyze_selection_target_replay_inputs(
        replay_input_path,
        structural_variant="exclude_watchlist_avoid_boundary_entries",
        focus_tickers=["300502"],
    )

    assert baseline_analysis["focused_score_diagnostics"][0]["replayed_present"] is True
    assert baseline_analysis["focused_score_diagnostics"][0]["filtered_candidate_entry"] is False
    assert filtered_analysis["filtered_candidate_entry_counts"] == {"watchlist_avoid_boundary_entry": 1}
    assert filtered_analysis["decision_mismatch_count"] == 1
    assert filtered_analysis["focused_score_diagnostics"][0]["candidate_source"] == "watchlist_filter_diagnostics"
    assert filtered_analysis["focused_score_diagnostics"][0]["filtered_candidate_entry"] is True
    assert filtered_analysis["focused_score_diagnostics"][0]["filtered_candidate_entry_rule"] == "watchlist_avoid_boundary_entry"
    assert filtered_analysis["focused_score_diagnostics"][0]["replayed_present"] is False
    assert filtered_analysis["focused_score_diagnostics"][0]["replayed_decision"] is None
    assert filtered_analysis["focused_score_diagnostics"][0]["replayed_score_target"] is None


def test_replay_selection_target_weak_structure_filter_only_excludes_weak_boundary_sample(tmp_path):
    retained_entry = {
        "ticker": "300394",
        "score_b": 0.4199,
        "score_c": -0.0961,
        "score_final": 0.1877,
        "quality_score": 0.975,
        "decision": "avoid",
        "bc_conflict": "b_positive_c_strong_bearish",
        "candidate_source": "watchlist_filter_diagnostics",
        "candidate_reason_codes": ["decision_avoid", "score_final_below_watchlist_threshold"],
        "reason": "decision_avoid",
        "strategy_signals": {
            "trend": _make_signal(
                1,
                100.0,
                sub_factors={
                    "momentum": {"direction": 1, "confidence": 100.0, "completeness": 1.0},
                    "adx_strength": {"direction": 1, "confidence": 49.24, "completeness": 1.0},
                    "ema_alignment": {"direction": 1, "confidence": 100.0, "completeness": 1.0},
                    "volatility": {"direction": 0, "confidence": 0.0, "completeness": 1.0},
                    "long_trend_alignment": {"direction": 1, "confidence": 100.0, "completeness": 1.0},
                },
            ),
            "event_sentiment": _make_signal(
                0,
                0.0,
                sub_factors={
                    "event_freshness": {"direction": 0, "confidence": 0.0, "completeness": 1.0},
                    "news_sentiment": {"direction": 0, "confidence": 0.0, "completeness": 1.0},
                },
            ),
            "mean_reversion": _make_signal(0, 0.0),
        },
        "agent_contribution_summary": {"cohort_contributions": {"analyst": -0.0305, "investor": -0.0656}},
    }
    weak_entry = {
        "ticker": "300502",
        "score_b": 0.3829,
        "score_c": -0.1194,
        "score_final": 0.1568,
        "quality_score": 0.9375,
        "decision": "avoid",
        "bc_conflict": "b_positive_c_strong_bearish",
        "candidate_source": "watchlist_filter_diagnostics",
        "candidate_reason_codes": ["decision_avoid", "score_final_below_watchlist_threshold"],
        "reason": "decision_avoid",
        "strategy_signals": {
            "trend": _make_signal(
                1,
                70.0,
                sub_factors={
                    "momentum": {"direction": 0, "confidence": 0.0, "completeness": 1.0},
                    "adx_strength": {"direction": 1, "confidence": 50.0, "completeness": 1.0},
                    "ema_alignment": {"direction": 1, "confidence": 100.0, "completeness": 1.0},
                    "volatility": {"direction": 0, "confidence": 0.0, "completeness": 1.0},
                    "long_trend_alignment": {"direction": 1, "confidence": 100.0, "completeness": 1.0},
                },
            ),
            "event_sentiment": _make_signal(
                0,
                0.0,
                sub_factors={
                    "event_freshness": {"direction": 0, "confidence": 0.0, "completeness": 1.0},
                    "news_sentiment": {"direction": 0, "confidence": 0.0, "completeness": 1.0},
                },
            ),
            "mean_reversion": _make_signal(0, 0.0),
        },
        "agent_contribution_summary": {"cohort_contributions": {"analyst": -0.0646, "investor": -0.0548}},
    }
    replay_entries = [retained_entry, weak_entry]
    replay_entries_json = [
        {
            **entry,
            "strategy_signals": {name: signal.model_dump(mode="json") for name, signal in entry["strategy_signals"].items()},
        }
        for entry in replay_entries
    ]
    selection_targets, summary = build_selection_targets(
        trade_date="20260322",
        watchlist=[],
        rejected_entries=replay_entries,
        supplemental_short_trade_entries=[],
        buy_order_tickers=set(),
        target_mode="dual_target",
    )
    replay_input = {
        "artifact_version": "v1",
        "run_id": "test_candidate_entry_weak_structure_filter",
        "trade_date": "2026-03-22",
        "market": "CN",
        "target_mode": "dual_target",
        "pipeline_config_snapshot": {},
        "source_summary": {
            "watchlist_count": 0,
            "rejected_entry_count": 2,
            "supplemental_short_trade_entry_count": 0,
            "buy_order_ticker_count": 0,
        },
        "watchlist": [],
        "rejected_entries": replay_entries_json,
        "supplemental_short_trade_entries": [],
        "buy_order_tickers": [],
        "selection_targets": {ticker: evaluation.model_dump(mode="json") for ticker, evaluation in selection_targets.items()},
        "target_summary": summary.model_dump(mode="json"),
    }
    replay_input_path = tmp_path / "selection_target_replay_input.json"
    replay_input_path.write_text(json.dumps(replay_input, ensure_ascii=False, indent=2), encoding="utf-8")

    filtered_analysis = analyze_selection_target_replay_inputs(
        replay_input_path,
        structural_variant="exclude_watchlist_avoid_weak_structure_entries",
        focus_tickers=["300394", "300502"],
    )

    diagnostics_by_ticker = {row["ticker"]: row for row in filtered_analysis["focused_score_diagnostics"]}
    assert filtered_analysis["filtered_candidate_entry_counts"] == {"watchlist_avoid_boundary_weak_structure_entry": 1}
    assert filtered_analysis["decision_transition_counts"]["blocked->none"] == 1
    assert diagnostics_by_ticker["300394"]["filtered_candidate_entry"] is False
    assert diagnostics_by_ticker["300394"]["replayed_present"] is True
    assert diagnostics_by_ticker["300502"]["filtered_candidate_entry"] is True
    assert diagnostics_by_ticker["300502"]["filtered_candidate_entry_rule"] == "watchlist_avoid_boundary_weak_structure_entry"
    assert diagnostics_by_ticker["300502"]["filtered_candidate_entry_metrics"] == {
        "breakout_freshness": 0.0,
        "catalyst_freshness": 0.0,
        "volume_expansion_quality": 0.0,
    }
    assert diagnostics_by_ticker["300502"]["replayed_present"] is False


def test_replay_selection_target_candidate_entry_metric_grid_finds_selective_threshold_row(tmp_path):
    retained_entry = {
        "ticker": "300394",
        "score_b": 0.4199,
        "score_c": -0.0961,
        "score_final": 0.1877,
        "quality_score": 0.975,
        "decision": "avoid",
        "bc_conflict": "b_positive_c_strong_bearish",
        "candidate_source": "watchlist_filter_diagnostics",
        "candidate_reason_codes": ["decision_avoid", "score_final_below_watchlist_threshold"],
        "reason": "decision_avoid",
        "strategy_signals": {
            "trend": _make_signal(
                1,
                100.0,
                sub_factors={
                    "momentum": {"direction": 1, "confidence": 100.0, "completeness": 1.0},
                    "adx_strength": {"direction": 1, "confidence": 49.24, "completeness": 1.0},
                    "ema_alignment": {"direction": 1, "confidence": 100.0, "completeness": 1.0},
                    "volatility": {"direction": 0, "confidence": 0.0, "completeness": 1.0},
                    "long_trend_alignment": {"direction": 1, "confidence": 100.0, "completeness": 1.0},
                },
            ),
            "event_sentiment": _make_signal(
                0,
                0.0,
                sub_factors={
                    "event_freshness": {"direction": 0, "confidence": 0.0, "completeness": 1.0},
                    "news_sentiment": {"direction": 0, "confidence": 0.0, "completeness": 1.0},
                },
            ),
            "mean_reversion": _make_signal(0, 0.0),
        },
        "agent_contribution_summary": {"cohort_contributions": {"analyst": -0.0305, "investor": -0.0656}},
    }
    weak_entry = {
        "ticker": "300502",
        "score_b": 0.3829,
        "score_c": -0.1194,
        "score_final": 0.1568,
        "quality_score": 0.9375,
        "decision": "avoid",
        "bc_conflict": "b_positive_c_strong_bearish",
        "candidate_source": "watchlist_filter_diagnostics",
        "candidate_reason_codes": ["decision_avoid", "score_final_below_watchlist_threshold"],
        "reason": "decision_avoid",
        "strategy_signals": {
            "trend": _make_signal(
                1,
                70.0,
                sub_factors={
                    "momentum": {"direction": 0, "confidence": 0.0, "completeness": 1.0},
                    "adx_strength": {"direction": 1, "confidence": 50.0, "completeness": 1.0},
                    "ema_alignment": {"direction": 1, "confidence": 100.0, "completeness": 1.0},
                    "volatility": {"direction": 0, "confidence": 0.0, "completeness": 1.0},
                    "long_trend_alignment": {"direction": 1, "confidence": 100.0, "completeness": 1.0},
                },
            ),
            "event_sentiment": _make_signal(
                0,
                0.0,
                sub_factors={
                    "event_freshness": {"direction": 0, "confidence": 0.0, "completeness": 1.0},
                    "news_sentiment": {"direction": 0, "confidence": 0.0, "completeness": 1.0},
                },
            ),
            "mean_reversion": _make_signal(0, 0.0),
        },
        "agent_contribution_summary": {"cohort_contributions": {"analyst": -0.0646, "investor": -0.0548}},
    }
    replay_entries_json = [
        {
            **entry,
            "strategy_signals": {name: signal.model_dump(mode="json") for name, signal in entry["strategy_signals"].items()},
        }
        for entry in [retained_entry, weak_entry]
    ]
    selection_targets, summary = build_selection_targets(
        trade_date="20260322",
        watchlist=[],
        rejected_entries=[retained_entry, weak_entry],
        supplemental_short_trade_entries=[],
        buy_order_tickers=set(),
        target_mode="dual_target",
    )
    replay_input = {
        "artifact_version": "v1",
        "run_id": "test_candidate_entry_metric_grid",
        "trade_date": "2026-03-22",
        "market": "CN",
        "target_mode": "dual_target",
        "pipeline_config_snapshot": {},
        "source_summary": {
            "watchlist_count": 0,
            "rejected_entry_count": 2,
            "supplemental_short_trade_entry_count": 0,
            "buy_order_ticker_count": 0,
        },
        "watchlist": [],
        "rejected_entries": replay_entries_json,
        "supplemental_short_trade_entries": [],
        "buy_order_tickers": [],
        "selection_targets": {ticker: evaluation.model_dump(mode="json") for ticker, evaluation in selection_targets.items()},
        "target_summary": summary.model_dump(mode="json"),
    }
    replay_input_path = tmp_path / "selection_target_replay_input.json"
    replay_input_path.write_text(json.dumps(replay_input, ensure_ascii=False, indent=2), encoding="utf-8")

    analysis = analyze_selection_target_candidate_entry_metric_grid(
        replay_input_path,
        breakout_freshness_max_values=[0.0, 0.05],
        volume_expansion_quality_max_values=[0.0, 0.05],
        catalyst_freshness_max_values=[0.0, 0.05],
        base_structural_variants=["baseline"],
        focus_tickers=["300394", "300502"],
    )

    assert analysis["grid_row_count"] == 8
    first_row = analysis["first_row_filtering_any"]
    assert first_row is not None
    assert first_row["structural_variant"] == "baseline"
    assert first_row["filtered_candidate_entry_counts"] == {"watchlist_avoid_boundary_weak_structure_entry": 1}
    selective_row = next(
        row
        for row in analysis["rows"]
        if row["breakout_freshness_max"] == 0.05 and row["volume_expansion_quality_max"] == 0.05 and row["catalyst_freshness_max"] == 0.05
    )
    assert selective_row["candidate_entry_filter_observability"] == {
        "watchlist_avoid_boundary_weak_structure_entry": {
            "precondition_match_count": 2,
            "metric_data_pass_count": 2,
            "metric_threshold_match_count": 1,
        }
    }
    diagnostics_by_ticker = {row["ticker"]: row for row in selective_row["analysis"]["focused_score_diagnostics"]}
    assert diagnostics_by_ticker["300394"]["filtered_candidate_entry"] is False
    assert diagnostics_by_ticker["300502"]["filtered_candidate_entry"] is True


def test_replay_selection_target_candidate_entry_metric_grid_surfaces_focus_preserve_semantic_row(tmp_path):
    retained_entry = {
        "ticker": "300394",
        "score_b": 0.4199,
        "score_c": -0.0961,
        "score_final": 0.1877,
        "quality_score": 0.975,
        "decision": "avoid",
        "bc_conflict": "b_positive_c_strong_bearish",
        "candidate_source": "watchlist_filter_diagnostics",
        "candidate_reason_codes": ["decision_avoid", "score_final_below_watchlist_threshold"],
        "reason": "decision_avoid",
        "strategy_signals": {
            "trend": _make_signal(
                1,
                100.0,
                sub_factors={
                    "momentum": {"direction": 1, "confidence": 100.0, "completeness": 1.0},
                    "adx_strength": {"direction": 1, "confidence": 49.24, "completeness": 1.0},
                    "ema_alignment": {"direction": 1, "confidence": 100.0, "completeness": 1.0},
                    "volatility": {"direction": 0, "confidence": 0.0, "completeness": 1.0},
                    "long_trend_alignment": {"direction": 1, "confidence": 100.0, "completeness": 1.0},
                },
            ),
            "event_sentiment": _make_signal(
                0,
                0.0,
                sub_factors={
                    "event_freshness": {"direction": 0, "confidence": 0.0, "completeness": 1.0},
                    "news_sentiment": {"direction": 0, "confidence": 0.0, "completeness": 1.0},
                },
            ),
            "mean_reversion": _make_signal(0, 0.0),
        },
        "agent_contribution_summary": {"cohort_contributions": {"analyst": -0.0305, "investor": -0.0656}},
    }
    weak_entry = {
        "ticker": "300502",
        "score_b": 0.3829,
        "score_c": -0.1194,
        "score_final": 0.1568,
        "quality_score": 0.9375,
        "decision": "avoid",
        "bc_conflict": "b_positive_c_strong_bearish",
        "candidate_source": "watchlist_filter_diagnostics",
        "candidate_reason_codes": ["decision_avoid", "score_final_below_watchlist_threshold"],
        "reason": "decision_avoid",
        "strategy_signals": {
            "trend": _make_signal(
                1,
                70.0,
                sub_factors={
                    "momentum": {"direction": 0, "confidence": 0.0, "completeness": 1.0},
                    "adx_strength": {"direction": 1, "confidence": 50.0, "completeness": 1.0},
                    "ema_alignment": {"direction": 1, "confidence": 100.0, "completeness": 1.0},
                    "volatility": {"direction": 0, "confidence": 0.0, "completeness": 1.0},
                    "long_trend_alignment": {"direction": 1, "confidence": 100.0, "completeness": 1.0},
                },
            ),
            "event_sentiment": _make_signal(
                0,
                0.0,
                sub_factors={
                    "event_freshness": {"direction": 0, "confidence": 0.0, "completeness": 1.0},
                    "news_sentiment": {"direction": 0, "confidence": 0.0, "completeness": 1.0},
                },
            ),
            "mean_reversion": _make_signal(0, 0.0),
        },
        "agent_contribution_summary": {"cohort_contributions": {"analyst": -0.0646, "investor": -0.0548}},
    }
    replay_entries_json = [
        {
            **entry,
            "strategy_signals": {name: signal.model_dump(mode="json") for name, signal in entry["strategy_signals"].items()},
        }
        for entry in [retained_entry, weak_entry]
    ]
    selection_targets, summary = build_selection_targets(
        trade_date="20260322",
        watchlist=[],
        rejected_entries=[retained_entry, weak_entry],
        supplemental_short_trade_entries=[],
        buy_order_tickers=set(),
        target_mode="dual_target",
    )
    replay_input = {
        "artifact_version": "v1",
        "run_id": "test_candidate_entry_semantic_frontier",
        "trade_date": "2026-03-22",
        "market": "CN",
        "target_mode": "dual_target",
        "pipeline_config_snapshot": {},
        "source_summary": {
            "watchlist_count": 0,
            "rejected_entry_count": 2,
            "supplemental_short_trade_entry_count": 0,
            "buy_order_ticker_count": 0,
        },
        "watchlist": [],
        "rejected_entries": replay_entries_json,
        "supplemental_short_trade_entries": [],
        "buy_order_tickers": [],
        "selection_targets": {ticker: evaluation.model_dump(mode="json") for ticker, evaluation in selection_targets.items()},
        "target_summary": summary.model_dump(mode="json"),
    }
    replay_input_path = tmp_path / "selection_target_replay_input.json"
    replay_input_path.write_text(json.dumps(replay_input, ensure_ascii=False, indent=2), encoding="utf-8")

    analysis = analyze_selection_target_candidate_entry_metric_grid(
        replay_input_path,
        breakout_freshness_max_values=[],
        trend_acceleration_max_values=[0.42, 0.43],
        volume_expansion_quality_max_values=[],
        close_strength_max_values=[0.68, 0.69],
        catalyst_freshness_max_values=[],
        base_structural_variants=["baseline"],
        focus_tickers=["300502"],
        preserve_tickers=["300394"],
    )

    assert analysis["grid_row_count"] == 4
    assert analysis["trend_acceleration_max_grid"] == [0.42, 0.43]
    assert analysis["close_strength_max_grid"] == [0.68, 0.69]
    first_focus_row = analysis["first_focus_filtered_preserving_rows"]["300502"]
    assert first_focus_row["trend_acceleration_max"] == 0.43
    assert first_focus_row["close_strength_max"] == 0.69
    assert first_focus_row["focus_filtered"] == {"300502": True}
    assert first_focus_row["preserve_filtered"] == {"300394": False}
    diagnostics_by_ticker = {row["ticker"]: row for row in first_focus_row["analysis"]["focused_score_diagnostics"]}
    assert diagnostics_by_ticker["300502"]["filtered_candidate_entry"] is True
    assert diagnostics_by_ticker["300502"]["filtered_candidate_entry_metrics"] == {
        "close_strength": 0.6883,
        "trend_acceleration": 0.425,
    }
    assert diagnostics_by_ticker["300394"]["filtered_candidate_entry"] is False


def test_replay_selection_target_candidate_entry_metric_grid_supports_omitted_dimensions_in_subset_search(tmp_path):
    retained_entry = {
        "ticker": "300394",
        "score_b": 0.4199,
        "score_c": -0.0961,
        "score_final": 0.1877,
        "quality_score": 0.975,
        "decision": "avoid",
        "bc_conflict": "b_positive_c_strong_bearish",
        "candidate_source": "watchlist_filter_diagnostics",
        "candidate_reason_codes": ["decision_avoid", "score_final_below_watchlist_threshold"],
        "reason": "decision_avoid",
        "strategy_signals": {
            "trend": _make_signal(
                1,
                100.0,
                sub_factors={
                    "momentum": {"direction": 1, "confidence": 100.0, "completeness": 1.0},
                    "adx_strength": {"direction": 1, "confidence": 49.24, "completeness": 1.0},
                    "ema_alignment": {"direction": 1, "confidence": 100.0, "completeness": 1.0},
                    "volatility": {"direction": 0, "confidence": 0.0, "completeness": 1.0},
                    "long_trend_alignment": {"direction": 1, "confidence": 100.0, "completeness": 1.0},
                },
            ),
            "event_sentiment": _make_signal(
                0,
                0.0,
                sub_factors={
                    "event_freshness": {"direction": 0, "confidence": 0.0, "completeness": 1.0},
                    "news_sentiment": {"direction": 0, "confidence": 0.0, "completeness": 1.0},
                },
            ),
            "mean_reversion": _make_signal(0, 0.0),
        },
        "agent_contribution_summary": {"cohort_contributions": {"analyst": -0.0305, "investor": -0.0656}},
    }
    weak_entry = {
        "ticker": "300502",
        "score_b": 0.3829,
        "score_c": -0.1194,
        "score_final": 0.1568,
        "quality_score": 0.9375,
        "decision": "avoid",
        "bc_conflict": "b_positive_c_strong_bearish",
        "candidate_source": "watchlist_filter_diagnostics",
        "candidate_reason_codes": ["decision_avoid", "score_final_below_watchlist_threshold"],
        "reason": "decision_avoid",
        "strategy_signals": {
            "trend": _make_signal(
                1,
                70.0,
                sub_factors={
                    "momentum": {"direction": 0, "confidence": 0.0, "completeness": 1.0},
                    "adx_strength": {"direction": 1, "confidence": 50.0, "completeness": 1.0},
                    "ema_alignment": {"direction": 1, "confidence": 100.0, "completeness": 1.0},
                    "volatility": {"direction": 0, "confidence": 0.0, "completeness": 1.0},
                    "long_trend_alignment": {"direction": 1, "confidence": 100.0, "completeness": 1.0},
                },
            ),
            "event_sentiment": _make_signal(
                0,
                0.0,
                sub_factors={
                    "event_freshness": {"direction": 0, "confidence": 0.0, "completeness": 1.0},
                    "news_sentiment": {"direction": 0, "confidence": 0.0, "completeness": 1.0},
                },
            ),
            "mean_reversion": _make_signal(0, 0.0),
        },
        "agent_contribution_summary": {"cohort_contributions": {"analyst": -0.0646, "investor": -0.0548}},
    }
    replay_entries_json = [
        {
            **entry,
            "strategy_signals": {name: signal.model_dump(mode="json") for name, signal in entry["strategy_signals"].items()},
        }
        for entry in [retained_entry, weak_entry]
    ]
    selection_targets, summary = build_selection_targets(
        trade_date="20260322",
        watchlist=[],
        rejected_entries=[retained_entry, weak_entry],
        supplemental_short_trade_entries=[],
        buy_order_tickers=set(),
        target_mode="dual_target",
    )
    replay_input = {
        "artifact_version": "v1",
        "run_id": "test_candidate_entry_subset_search",
        "trade_date": "2026-03-22",
        "market": "CN",
        "target_mode": "dual_target",
        "pipeline_config_snapshot": {},
        "source_summary": {
            "watchlist_count": 0,
            "rejected_entry_count": 2,
            "supplemental_short_trade_entry_count": 0,
            "buy_order_ticker_count": 0,
        },
        "watchlist": [],
        "rejected_entries": replay_entries_json,
        "supplemental_short_trade_entries": [],
        "buy_order_tickers": [],
        "selection_targets": {ticker: evaluation.model_dump(mode="json") for ticker, evaluation in selection_targets.items()},
        "target_summary": summary.model_dump(mode="json"),
    }
    replay_input_path = tmp_path / "selection_target_replay_input.json"
    replay_input_path.write_text(json.dumps(replay_input, ensure_ascii=False, indent=2), encoding="utf-8")

    analysis = analyze_selection_target_candidate_entry_metric_grid(
        replay_input_path,
        breakout_freshness_max_values=[None, 0.0],
        trend_acceleration_max_values=[None, 0.43],
        volume_expansion_quality_max_values=[None],
        close_strength_max_values=[None, 0.69],
        catalyst_freshness_max_values=[None],
        base_structural_variants=["baseline"],
        focus_tickers=["300502"],
        preserve_tickers=["300394"],
    )

    first_focus_row = analysis["first_focus_filtered_preserving_rows"]["300502"]
    assert first_focus_row["breakout_freshness_max"] == 0.0
    assert first_focus_row["trend_acceleration_max"] is None
    assert first_focus_row["close_strength_max"] is None
    assert first_focus_row["volume_expansion_quality_max"] is None
    assert first_focus_row["catalyst_freshness_max"] is None
    assert first_focus_row["threshold_adjustment_cost"] == 0.0


def test_replay_selection_target_weak_structure_filter_skips_entries_with_missing_signals(tmp_path):
    missing_signal_entry = {
        "ticker": "601899",
        "score_b": 0.41,
        "score_c": -0.10,
        "score_final": 0.18,
        "quality_score": 0.90,
        "decision": "avoid",
        "bc_conflict": "b_positive_c_strong_bearish",
        "candidate_source": "watchlist_filter_diagnostics",
        "candidate_reason_codes": ["decision_avoid", "score_final_below_watchlist_threshold"],
        "reason": "decision_avoid",
        "strategy_signals": {},
        "agent_contribution_summary": {"cohort_contributions": {"analyst": 0.0, "investor": 0.0}},
    }
    selection_targets, summary = build_selection_targets(
        trade_date="20260322",
        watchlist=[],
        rejected_entries=[missing_signal_entry],
        supplemental_short_trade_entries=[],
        buy_order_tickers=set(),
        target_mode="dual_target",
    )
    replay_input = {
        "artifact_version": "v1",
        "run_id": "test_missing_signal_metric_filter_guard",
        "trade_date": "2026-03-22",
        "market": "CN",
        "target_mode": "dual_target",
        "pipeline_config_snapshot": {},
        "source_summary": {
            "watchlist_count": 0,
            "rejected_entry_count": 1,
            "supplemental_short_trade_entry_count": 0,
            "buy_order_ticker_count": 0,
        },
        "watchlist": [],
        "rejected_entries": [missing_signal_entry],
        "supplemental_short_trade_entries": [],
        "buy_order_tickers": [],
        "selection_targets": {ticker: evaluation.model_dump(mode="json") for ticker, evaluation in selection_targets.items()},
        "target_summary": summary.model_dump(mode="json"),
    }
    replay_input_path = tmp_path / "selection_target_replay_input.json"
    replay_input_path.write_text(json.dumps(replay_input, ensure_ascii=False, indent=2), encoding="utf-8")

    analysis = analyze_selection_target_replay_inputs(
        replay_input_path,
        structural_variant="baseline",
        structural_overrides={
            "exclude_candidate_entries": [
                {
                    "name": "watchlist_avoid_boundary_weak_structure_entry",
                    "candidate_sources": ["watchlist_filter_diagnostics"],
                    "all_reason_codes": ["decision_avoid", "score_final_below_watchlist_threshold"],
                    "metric_max_thresholds": {
                        "breakout_freshness": 0.05,
                        "volume_expansion_quality": 0.05,
                        "catalyst_freshness": 0.05,
                    },
                }
            ]
        },
        focus_tickers=["601899"],
    )

    assert analysis["filtered_candidate_entry_counts"] == {}
    assert analysis["candidate_entry_filter_observability"] == {
        "watchlist_avoid_boundary_weak_structure_entry": {
            "precondition_match_count": 1,
            "metric_data_fail_count": 1,
        }
    }
    assert analysis["focused_score_diagnostics"][0]["filtered_candidate_entry"] is False


def test_replay_selection_target_penalty_grid_surfaces_best_and_first_near_miss_row(tmp_path):
    retained_entry = {
        "ticker": "300394",
        "score_b": 0.4199,
        "score_c": -0.0961,
        "score_final": 0.1877,
        "quality_score": 0.975,
        "decision": "avoid",
        "bc_conflict": "b_positive_c_strong_bearish",
        "candidate_source": "watchlist_filter_diagnostics",
        "candidate_reason_codes": ["decision_avoid", "score_final_below_watchlist_threshold"],
        "reason": "decision_avoid",
        "strategy_signals": {
            "trend": _make_signal(
                1,
                100.0,
                sub_factors={
                    "momentum": {"direction": 1, "confidence": 100.0, "completeness": 1.0},
                    "adx_strength": {"direction": 1, "confidence": 49.24, "completeness": 1.0},
                    "ema_alignment": {"direction": 1, "confidence": 100.0, "completeness": 1.0},
                    "volatility": {"direction": 0, "confidence": 0.0, "completeness": 1.0},
                    "long_trend_alignment": {"direction": 1, "confidence": 100.0, "completeness": 1.0},
                },
            ),
            "event_sentiment": _make_signal(
                0,
                0.0,
                sub_factors={
                    "event_freshness": {"direction": 0, "confidence": 0.0, "completeness": 1.0},
                    "news_sentiment": {"direction": 0, "confidence": 0.0, "completeness": 1.0},
                },
            ),
            "mean_reversion": _make_signal(0, 0.0),
        },
        "agent_contribution_summary": {"cohort_contributions": {"analyst": -0.0305, "investor": -0.0656}},
    }
    replay_input = {
        "artifact_version": "v1",
        "run_id": "test_penalty_grid",
        "trade_date": "2026-03-22",
        "market": "CN",
        "target_mode": "dual_target",
        "pipeline_config_snapshot": {},
        "source_summary": {
            "watchlist_count": 0,
            "rejected_entry_count": 1,
            "supplemental_short_trade_entry_count": 0,
            "buy_order_ticker_count": 0,
        },
        "watchlist": [],
        "rejected_entries": [
            {
                **retained_entry,
                "strategy_signals": {name: signal.model_dump(mode="json") for name, signal in retained_entry["strategy_signals"].items()},
            }
        ],
        "supplemental_short_trade_entries": [],
        "buy_order_tickers": [],
    }
    selection_targets, summary = build_selection_targets(
        trade_date="20260322",
        watchlist=[],
        rejected_entries=[retained_entry],
        supplemental_short_trade_entries=[],
        buy_order_tickers=set(),
        target_mode="dual_target",
    )
    replay_input["selection_targets"] = {ticker: evaluation.model_dump(mode="json") for ticker, evaluation in selection_targets.items()}
    replay_input["target_summary"] = summary.model_dump(mode="json")
    replay_input_path = tmp_path / "selection_target_replay_input.json"
    replay_input_path.write_text(json.dumps(replay_input, ensure_ascii=False, indent=2), encoding="utf-8")

    analysis = analyze_selection_target_penalty_grid(
        replay_input_path,
        avoid_penalty_values=[0.12, 0.06],
        stale_score_penalty_weight_values=[0.12, 0.06],
        extension_score_penalty_weight_values=[0.08, 0.04],
        base_structural_variants=["no_bearish_conflict_block"],
        near_miss_threshold=0.3,
        focus_tickers=["300394"],
    )

    assert analysis["grid_row_count"] == 8
    best_row = analysis["best_focus_rows"]["300394"]
    assert best_row["focus_scores"]["300394"] is not None
    assert best_row["focus_scores"]["300394"] > 0.2133
    assert best_row["layer_c_avoid_penalty"] == 0.06
    first_near_miss_row = analysis["first_focus_near_miss_rows"]["300394"]
    assert first_near_miss_row["focus_decisions"]["300394"] in {"near_miss", "selected"}
    assert first_near_miss_row["focus_scores"]["300394"] >= 0.3


def test_replay_selection_target_penalty_threshold_grid_finds_minimal_rescue_row(tmp_path):
    retained_entry = {
        "ticker": "300394",
        "score_b": 0.4199,
        "score_c": -0.0961,
        "score_final": 0.1877,
        "quality_score": 0.975,
        "decision": "avoid",
        "bc_conflict": "b_positive_c_strong_bearish",
        "candidate_source": "watchlist_filter_diagnostics",
        "candidate_reason_codes": ["decision_avoid", "score_final_below_watchlist_threshold"],
        "reason": "decision_avoid",
        "strategy_signals": {
            "trend": _make_signal(
                1,
                100.0,
                sub_factors={
                    "momentum": {"direction": 1, "confidence": 100.0, "completeness": 1.0},
                    "adx_strength": {"direction": 1, "confidence": 49.24, "completeness": 1.0},
                    "ema_alignment": {"direction": 1, "confidence": 100.0, "completeness": 1.0},
                    "volatility": {"direction": 0, "confidence": 0.0, "completeness": 1.0},
                    "long_trend_alignment": {"direction": 1, "confidence": 100.0, "completeness": 1.0},
                },
            ),
            "event_sentiment": _make_signal(
                0,
                0.0,
                sub_factors={
                    "event_freshness": {"direction": 0, "confidence": 0.0, "completeness": 1.0},
                    "news_sentiment": {"direction": 0, "confidence": 0.0, "completeness": 1.0},
                },
            ),
            "mean_reversion": _make_signal(0, 0.0),
        },
        "agent_contribution_summary": {"cohort_contributions": {"analyst": -0.0305, "investor": -0.0656}},
    }
    replay_input = {
        "artifact_version": "v1",
        "run_id": "test_penalty_threshold_grid",
        "trade_date": "2026-03-22",
        "market": "CN",
        "target_mode": "dual_target",
        "pipeline_config_snapshot": {},
        "source_summary": {
            "watchlist_count": 0,
            "rejected_entry_count": 1,
            "supplemental_short_trade_entry_count": 0,
            "buy_order_ticker_count": 0,
        },
        "watchlist": [],
        "rejected_entries": [
            {
                **retained_entry,
                "strategy_signals": {name: signal.model_dump(mode="json") for name, signal in retained_entry["strategy_signals"].items()},
            }
        ],
        "supplemental_short_trade_entries": [],
        "buy_order_tickers": [],
    }
    selection_targets, summary = build_selection_targets(
        trade_date="20260322",
        watchlist=[],
        rejected_entries=[retained_entry],
        supplemental_short_trade_entries=[],
        buy_order_tickers=set(),
        target_mode="dual_target",
    )
    replay_input["selection_targets"] = {ticker: evaluation.model_dump(mode="json") for ticker, evaluation in selection_targets.items()}
    replay_input["target_summary"] = summary.model_dump(mode="json")
    replay_input_path = tmp_path / "selection_target_replay_input.json"
    replay_input_path.write_text(json.dumps(replay_input, ensure_ascii=False, indent=2), encoding="utf-8")

    analysis = analyze_selection_target_penalty_threshold_grid(
        replay_input_path,
        avoid_penalty_values=[0.12, 0.06],
        stale_score_penalty_weight_values=[0.12, 0.06],
        extension_score_penalty_weight_values=[0.08, 0.04],
        select_thresholds=[0.58, 0.3],
        near_miss_thresholds=[0.46, 0.3],
        base_structural_variants=["no_bearish_conflict_block"],
        focus_tickers=["300394"],
    )

    first_near_miss_row = analysis["first_focus_near_miss_rows"]["300394"]
    assert first_near_miss_row["focus_decisions"]["300394"] in {"near_miss", "selected"}
    assert first_near_miss_row["near_miss_threshold"] == 0.3
    first_selected_row = analysis["first_focus_selected_rows"]["300394"]
    assert first_selected_row["focus_decisions"]["300394"] == "selected"
    assert first_selected_row["select_threshold"] == 0.3


def test_replay_selection_target_combination_grid_surfaces_blocked_to_selected_release(tmp_path):
    watch_item = LayerCResult(
        ticker="000001",
        score_b=0.71,
        score_c=0.66,
        score_final=0.69,
        quality_score=0.65,
        decision="watch",
        bc_conflict="b_positive_c_strong_bearish",
        strategy_signals={
            "trend": _make_signal(
                1,
                84.0,
                sub_factors={
                    "momentum": {"direction": 1, "confidence": 86.0, "completeness": 1.0},
                    "adx_strength": {"direction": 1, "confidence": 78.0, "completeness": 1.0},
                    "ema_alignment": {"direction": 1, "confidence": 74.0, "completeness": 1.0},
                    "volatility": {"direction": 1, "confidence": 66.0, "completeness": 1.0},
                    "long_trend_alignment": {"direction": 0, "confidence": 30.0, "completeness": 1.0},
                },
            ),
            "event_sentiment": _make_signal(
                1,
                76.0,
                sub_factors={
                    "event_freshness": {"direction": 1, "confidence": 90.0, "completeness": 1.0},
                    "news_sentiment": {"direction": 1, "confidence": 65.0, "completeness": 1.0},
                },
            ),
            "mean_reversion": _make_signal(-1, 18.0),
        },
        agent_contribution_summary={"cohort_contributions": {"analyst": 0.22, "investor": 0.11}},
    )
    selection_targets, summary = build_selection_targets(
        trade_date="20260322",
        watchlist=[watch_item],
        rejected_entries=[],
        supplemental_short_trade_entries=[],
        buy_order_tickers={"000001"},
        target_mode="dual_target",
    )
    assert selection_targets["000001"].short_trade is not None
    assert selection_targets["000001"].short_trade.decision == "blocked"
    replay_input = {
        "artifact_version": "v1",
        "run_id": "test_combination_grid",
        "trade_date": "2026-03-22",
        "market": "CN",
        "target_mode": "dual_target",
        "pipeline_config_snapshot": {},
        "source_summary": {
            "watchlist_count": 1,
            "rejected_entry_count": 0,
            "supplemental_short_trade_entry_count": 0,
            "buy_order_ticker_count": 1,
        },
        "watchlist": [watch_item.model_dump(mode="json")],
        "rejected_entries": [],
        "supplemental_short_trade_entries": [],
        "buy_order_tickers": ["000001"],
        "selection_targets": {ticker: evaluation.model_dump(mode="json") for ticker, evaluation in selection_targets.items()},
        "target_summary": summary.model_dump(mode="json"),
    }
    replay_input_path = tmp_path / "selection_target_replay_input.json"
    replay_input_path.write_text(json.dumps(replay_input, ensure_ascii=False, indent=2), encoding="utf-8")

    analysis = analyze_selection_target_combination_grid(
        replay_input_path,
        structural_variants=["baseline", "no_bearish_conflict_block"],
        select_thresholds=[0.58],
        near_miss_thresholds=[0.46],
    )

    assert analysis["grid_row_count"] == 2
    assert analysis["first_row_releasing_blocked"]["structural_variant"] == "no_bearish_conflict_block"
    assert analysis["first_row_blocked_to_selected"]["structural_variant"] == "no_bearish_conflict_block"
    assert analysis["first_row_blocked_to_selected"]["blocked_to_selected"] == ["000001"]
    baseline_row = analysis["rows"][0]
    variant_row = analysis["rows"][1]
    assert baseline_row["structural_variant"] == "baseline"
    assert baseline_row["replayed_short_trade_decision_counts"] == {"blocked": 1}
    assert variant_row["structural_variant"] == "no_bearish_conflict_block"
    assert variant_row["replayed_short_trade_decision_counts"] == {"selected": 1}