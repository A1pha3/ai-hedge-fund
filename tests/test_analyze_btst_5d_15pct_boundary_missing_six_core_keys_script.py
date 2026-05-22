from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from src.execution.models import ExecutionPlan, LayerCResult
from src.research.artifacts import FileSelectionArtifactWriter
from src.targets.models import DualTargetEvaluation, DualTargetSummary, TargetEvaluationResult


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "analyze_btst_5d_15pct_boundary_missing_six_core_keys.py"
MISSING_SIX_CORE_KEYS = [
    "breakout_freshness",
    "trend_acceleration",
    "volume_expansion_quality",
    "close_strength",
    "trend_continuation",
    "short_term_reversal",
]


def _load_script_module():
    assert SCRIPT_PATH.exists(), f"Expected script to exist: {SCRIPT_PATH}"
    spec = importlib.util.spec_from_file_location("boundary_missing_six_core_keys_script", SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _nested_only_attachment_row() -> dict[str, object]:
    nested_metrics = {
        "breakout_freshness": 0.91,
        "trend_acceleration": 0.82,
        "volume_expansion_quality": 0.73,
        "close_strength": 0.64,
        "trend_continuation": 0.55,
        "short_term_reversal": 0.18,
    }
    return {
        "candidate_source": "short_trade_boundary",
        "ticker": "001309",
        "trade_date": "20260324",
        "source_payload": {
            "ticker": "001309",
            "candidate_source": "short_trade_boundary",
            "t0_tail_strength": 0.61,
        },
        "attached_target": {
            "candidate_source": "short_trade_boundary",
            "t0_tail_strength": 0.61,
            "short_trade": {
                "decision": "near_miss",
                "t0_tail_strength": 0.61,
                "explainability_payload": {},
                "metrics_payload": nested_metrics,
            },
        },
        "snapshot_target": {
            "candidate_source": "short_trade_boundary",
            "t0_tail_strength": 0.61,
            "short_trade": {
                "decision": "near_miss",
                "t0_tail_strength": 0.61,
                "explainability_payload": {},
                "metrics_payload": nested_metrics,
            },
        },
    }


def _nested_source_metrics_row() -> dict[str, object]:
    source_nested_metrics = {
        "breakout_freshness": 0.91,
        "trend_acceleration": 0.82,
        "volume_expansion_quality": 0.73,
        "close_strength": 0.64,
        "trend_continuation": 0.55,
        "short_term_reversal": 0.18,
    }
    return {
        "candidate_source": "short_trade_boundary",
        "ticker": "001309",
        "trade_date": "20260324",
        "source_payload": {
            "ticker": "001309",
            "candidate_source": "short_trade_boundary",
            "t0_tail_strength": 0.61,
            "short_trade_boundary_metrics": source_nested_metrics,
        },
        "attached_target": {
            "candidate_source": "short_trade_boundary",
            "t0_tail_strength": 0.61,
            "short_trade": {
                "decision": "near_miss",
                "t0_tail_strength": 0.61,
                "explainability_payload": {},
                "metrics_payload": {},
            },
        },
        "snapshot_target": {
            "candidate_source": "short_trade_boundary",
            "t0_tail_strength": 0.61,
            "short_trade": {
                "decision": "near_miss",
                "t0_tail_strength": 0.61,
                "explainability_payload": {},
                "metrics_payload": {},
            },
        },
    }


def _missing_everywhere_row() -> dict[str, object]:
    return {
        "candidate_source": "layer_b_boundary",
        "ticker": "300111",
        "trade_date": "20260324",
        "source_payload": {
            "ticker": "300111",
            "candidate_source": "layer_b_boundary",
            "t0_tail_strength": 0.44,
        },
        "attached_target": {
            "candidate_source": "layer_b_boundary",
            "t0_tail_strength": 0.44,
            "short_trade": {
                "decision": "rejected",
                "t0_tail_strength": 0.44,
                "explainability_payload": {},
                "metrics_payload": {},
            },
        },
        "snapshot_target": {
            "candidate_source": "layer_b_boundary",
            "t0_tail_strength": 0.44,
            "short_trade": {
                "decision": "rejected",
                "t0_tail_strength": 0.44,
                "explainability_payload": {},
                "metrics_payload": {},
            },
        },
    }


def _mixed_nested_only_and_missing_everywhere_row() -> dict[str, object]:
    nested_only_keys = {
        "breakout_freshness": 0.91,
        "trend_acceleration": 0.82,
        "volume_expansion_quality": 0.73,
    }
    return {
        "candidate_source": "mixed_boundary_source",
        "ticker": "300222",
        "trade_date": "20260324",
        "source_payload": {
            "ticker": "300222",
            "candidate_source": "mixed_boundary_source",
            "t0_tail_strength": 0.51,
            **nested_only_keys,
        },
        "attached_target": {
            "candidate_source": "mixed_boundary_source",
            "t0_tail_strength": 0.51,
            "short_trade": {
                "decision": "mixed",
                "t0_tail_strength": 0.51,
                "explainability_payload": {},
                "metrics_payload": nested_only_keys,
            },
        },
        "snapshot_target": {
            "candidate_source": "mixed_boundary_source",
            "t0_tail_strength": 0.51,
            "short_trade": {
                "decision": "mixed",
                "t0_tail_strength": 0.51,
                "explainability_payload": {},
                "metrics_payload": nested_only_keys,
            },
        },
    }


def _lost_after_source_row() -> dict[str, object]:
    source_payload = {
        "ticker": "300333",
        "candidate_source": "lost_after_source_boundary",
        "t0_tail_strength": 0.38,
        "breakout_freshness": 0.84,
        "trend_acceleration": 0.76,
        "volume_expansion_quality": 0.69,
        "close_strength": 0.58,
        "trend_continuation": 0.47,
        "short_term_reversal": 0.31,
    }
    return {
        "candidate_source": "lost_after_source_boundary",
        "ticker": "300333",
        "trade_date": "20260324",
        "source_payload": source_payload,
        "attached_target": {
            "candidate_source": "lost_after_source_boundary",
            "t0_tail_strength": 0.38,
            "short_trade": {
                "decision": "lost",
                "t0_tail_strength": 0.38,
                "explainability_payload": {},
                "metrics_payload": {},
            },
        },
        "snapshot_target": {
            "candidate_source": "lost_after_source_boundary",
            "t0_tail_strength": 0.38,
            "short_trade": {
                "decision": "lost",
                "t0_tail_strength": 0.38,
                "explainability_payload": {},
                "metrics_payload": {},
            },
        },
    }


def _hold_boundary_until_more_context_row_with_surface_visible_missing_six_keys() -> dict[str, object]:
    surface_visible_keys = {
        "breakout_freshness": 0.97,
        "trend_acceleration": 0.86,
        "volume_expansion_quality": 0.78,
        "close_strength": 0.69,
        "trend_continuation": 0.57,
        "short_term_reversal": 0.22,
    }
    return {
        "candidate_source": "hold_boundary_until_more_context_source",
        "ticker": "002555",
        "trade_date": "20260324",
        "source_payload": {
            "ticker": "002555",
            "candidate_source": "hold_boundary_until_more_context_source",
            "t0_tail_strength": 0.49,
        },
        "attached_target": {
            "candidate_source": "hold_boundary_until_more_context_source",
            "t0_tail_strength": 0.49,
            "short_trade": {
                "decision": "hold",
                "t0_tail_strength": 0.49,
                "explainability_payload": surface_visible_keys,
                "metrics_payload": {},
            },
        },
        "snapshot_target": {
            "candidate_source": "hold_boundary_until_more_context_source",
            "t0_tail_strength": 0.49,
            "short_trade": {
                "decision": "hold",
                "t0_tail_strength": 0.49,
                "explainability_payload": surface_visible_keys,
                "metrics_payload": {},
            },
        },
    }


def test_analyze_btst_5d_15pct_boundary_missing_six_core_keys_from_rows_returns_required_deterministic_boards() -> None:
    script = _load_script_module()

    analysis = script.analyze_btst_5d_15pct_boundary_missing_six_core_keys_from_rows(
        [_nested_source_metrics_row(), _missing_everywhere_row()]
    )

    trace_by_ticker = {row["ticker"]: row for row in analysis["trace_status_board"]}
    assert analysis["boundary_row_count"] == 2
    assert trace_by_ticker["001309"]["surface_trace_status_counts"] == {
        "dropped_before_snapshot": 6,
        "present_end_to_end": 1,
    }
    assert trace_by_ticker["001309"]["surface_trace_statuses"] == {
        "breakout_freshness": "dropped_before_snapshot",
        "trend_acceleration": "dropped_before_snapshot",
        "volume_expansion_quality": "dropped_before_snapshot",
        "close_strength": "dropped_before_snapshot",
        "trend_continuation": "dropped_before_snapshot",
        "short_term_reversal": "dropped_before_snapshot",
        "t0_tail_strength": "present_end_to_end",
    }
    assert trace_by_ticker["001309"]["nested_only_missing_six_keys"] == []
    assert trace_by_ticker["001309"]["missing_everywhere_missing_six_keys"] == []
    assert trace_by_ticker["001309"]["governance_action"] == "fix_snapshot_attachment_contract"
    assert trace_by_ticker["300111"]["missing_everywhere_missing_six_keys"] == MISSING_SIX_CORE_KEYS

    assert analysis["key_trace_summary_board"] == [
        {
            "row_count": 2,
            "surface_trace_status_counts": {
                "dropped_before_snapshot": 6,
                "missing_at_source": 6,
                "present_end_to_end": 2,
            },
            "missing_six_key_diagnosis_counts": {
                "nested_only": 0,
                "missing_everywhere": 6,
                "surface_visible": 0,
                "lost_after_source": 6,
                "inconclusive": 0,
            },
        }
    ]
    assert analysis["boundary_source_trace_board"] == [
        {
            "candidate_source": "layer_b_boundary",
            "row_count": 1,
            "nested_only_missing_six_key_count": 0,
            "missing_everywhere_missing_six_key_count": 6,
            "surface_visible_missing_six_key_count": 0,
            "lost_after_source_missing_six_key_count": 0,
            "inconclusive_missing_six_key_count": 0,
            "governance_action": "fix_boundary_source_contract",
        },
        {
            "candidate_source": "short_trade_boundary",
            "row_count": 1,
            "nested_only_missing_six_key_count": 0,
            "missing_everywhere_missing_six_key_count": 0,
            "surface_visible_missing_six_key_count": 0,
            "lost_after_source_missing_six_key_count": 6,
            "inconclusive_missing_six_key_count": 0,
            "governance_action": "fix_snapshot_attachment_contract",
        },
    ]
    assert {row["key"]: row for row in analysis["survivor_key_contrast_board"]} == {
        "breakout_freshness": {
            "key": "breakout_freshness",
            "source_payload_count": 1,
            "attached_metrics_payload_count": 0,
            "attached_surface_payload_count": 0,
            "snapshot_metrics_payload_count": 0,
            "snapshot_surface_payload_count": 0,
        },
        "trend_acceleration": {
            "key": "trend_acceleration",
            "source_payload_count": 1,
            "attached_metrics_payload_count": 0,
            "attached_surface_payload_count": 0,
            "snapshot_metrics_payload_count": 0,
            "snapshot_surface_payload_count": 0,
        },
        "volume_expansion_quality": {
            "key": "volume_expansion_quality",
            "source_payload_count": 1,
            "attached_metrics_payload_count": 0,
            "attached_surface_payload_count": 0,
            "snapshot_metrics_payload_count": 0,
            "snapshot_surface_payload_count": 0,
        },
        "close_strength": {
            "key": "close_strength",
            "source_payload_count": 1,
            "attached_metrics_payload_count": 0,
            "attached_surface_payload_count": 0,
            "snapshot_metrics_payload_count": 0,
            "snapshot_surface_payload_count": 0,
        },
        "trend_continuation": {
            "key": "trend_continuation",
            "source_payload_count": 1,
            "attached_metrics_payload_count": 0,
            "attached_surface_payload_count": 0,
            "snapshot_metrics_payload_count": 0,
            "snapshot_surface_payload_count": 0,
        },
        "short_term_reversal": {
            "key": "short_term_reversal",
            "source_payload_count": 1,
            "attached_metrics_payload_count": 0,
            "attached_surface_payload_count": 0,
            "snapshot_metrics_payload_count": 0,
            "snapshot_surface_payload_count": 0,
        },
        "t0_tail_strength": {
            "key": "t0_tail_strength",
            "source_payload_count": 2,
            "attached_metrics_payload_count": 0,
            "attached_surface_payload_count": 2,
            "snapshot_metrics_payload_count": 0,
            "snapshot_surface_payload_count": 2,
        },
    }
    assert analysis["governance_diagnosis_board"] == [
        {
            "action": "fix_boundary_source_contract",
            "row_count": 1,
            "tickers": ["300111"],
            "affected_keys": MISSING_SIX_CORE_KEYS,
        },
        {
            "action": "fix_snapshot_attachment_contract",
            "row_count": 1,
            "tickers": ["001309"],
            "affected_keys": MISSING_SIX_CORE_KEYS,
        }
    ]


def test_extract_source_payload_includes_short_trade_boundary_metrics_container() -> None:
    script = _load_script_module()

    payload = script._extract_source_payload(
        {
            "source_entry": {
                "ticker": "001309",
                "candidate_source": "short_trade_boundary",
                "t0_tail_strength": 0.61,
                "short_trade_boundary_metrics": {
                    "breakout_freshness": 0.91,
                    "trend_acceleration": 0.82,
                    "volume_expansion_quality": 0.73,
                    "close_strength": 0.64,
                    "trend_continuation": 0.55,
                    "short_term_reversal": 0.18,
                },
            }
        }
    )

    assert payload == {
        "breakout_freshness": 0.91,
        "trend_acceleration": 0.82,
        "volume_expansion_quality": 0.73,
        "close_strength": 0.64,
        "trend_continuation": 0.55,
        "short_term_reversal": 0.18,
        "t0_tail_strength": 0.61,
    }


def test_source_contract_repair_stops_marking_tail_two_keys_missing_everywhere() -> None:
    script = _load_script_module()

    analysis = script.analyze_btst_5d_15pct_boundary_missing_six_core_keys_from_rows([_nested_source_metrics_row()])

    assert analysis["trace_status_board"][0]["missing_everywhere_missing_six_keys"] == []
    assert analysis["trace_status_board"][0]["governance_action"] == "fix_snapshot_attachment_contract"
    assert analysis["governance_diagnosis_board"] == [
        {
            "action": "fix_snapshot_attachment_contract",
            "row_count": 1,
            "tickers": ["001309"],
            "affected_keys": MISSING_SIX_CORE_KEYS,
        }
    ]


def test_nested_only_six_core_keys_drive_snapshot_attachment_contract_diagnosis() -> None:
    script = _load_script_module()

    analysis = script.analyze_btst_5d_15pct_boundary_missing_six_core_keys_from_rows([_nested_only_attachment_row()])

    assert analysis["governance_diagnosis_board"] == [
        {
            "action": "fix_snapshot_attachment_contract",
            "row_count": 1,
            "tickers": ["001309"],
            "affected_keys": MISSING_SIX_CORE_KEYS,
        }
    ]
    assert analysis["trace_status_board"][0]["nested_only_missing_six_keys"] == MISSING_SIX_CORE_KEYS
    assert analysis["trace_status_board"][0]["missing_everywhere_missing_six_keys"] == []


def test_mixed_nested_only_and_missing_everywhere_six_core_keys_escalate_to_boundary_source_contract() -> None:
    script = _load_script_module()

    analysis = script.analyze_btst_5d_15pct_boundary_missing_six_core_keys_from_rows(
        [_mixed_nested_only_and_missing_everywhere_row()]
    )

    assert analysis["trace_status_board"][0]["nested_only_missing_six_keys"] == [
        "breakout_freshness",
        "trend_acceleration",
        "volume_expansion_quality",
    ]
    assert analysis["trace_status_board"][0]["missing_everywhere_missing_six_keys"] == [
        "close_strength",
        "trend_continuation",
        "short_term_reversal",
    ]
    assert analysis["trace_status_board"][0]["governance_action"] == "fix_boundary_source_contract"
    assert analysis["governance_diagnosis_board"] == [
        {
            "action": "fix_boundary_source_contract",
            "row_count": 1,
            "tickers": ["300222"],
            "affected_keys": [
                "close_strength",
                "trend_continuation",
                "short_term_reversal",
            ],
        }
    ]


def test_missing_everywhere_six_core_keys_drive_boundary_source_contract_diagnosis() -> None:
    script = _load_script_module()

    analysis = script.analyze_btst_5d_15pct_boundary_missing_six_core_keys_from_rows([_missing_everywhere_row()])

    assert analysis["governance_diagnosis_board"] == [
        {
            "action": "fix_boundary_source_contract",
            "row_count": 1,
            "tickers": ["300111"],
            "affected_keys": MISSING_SIX_CORE_KEYS,
        }
    ]
    assert analysis["trace_status_board"][0]["nested_only_missing_six_keys"] == []
    assert analysis["trace_status_board"][0]["missing_everywhere_missing_six_keys"] == MISSING_SIX_CORE_KEYS


def test_lost_after_source_six_core_keys_route_to_snapshot_attachment_contract() -> None:
    script = _load_script_module()

    analysis = script.analyze_btst_5d_15pct_boundary_missing_six_core_keys_from_rows([_lost_after_source_row()])

    assert analysis["trace_status_board"][0]["governance_action"] == "fix_snapshot_attachment_contract"
    assert analysis["trace_status_board"][0]["nested_only_missing_six_keys"] == []
    assert analysis["trace_status_board"][0]["missing_everywhere_missing_six_keys"] == []
    assert analysis["governance_diagnosis_board"] == [
        {
            "action": "fix_snapshot_attachment_contract",
            "row_count": 1,
            "tickers": ["300333"],
            "affected_keys": MISSING_SIX_CORE_KEYS,
        }
    ]


def test_hold_boundary_until_more_context_surface_visible_missing_six_keys_are_not_marked_affected() -> None:
    script = _load_script_module()

    analysis = script.analyze_btst_5d_15pct_boundary_missing_six_core_keys_from_rows(
        [_hold_boundary_until_more_context_row_with_surface_visible_missing_six_keys()]
    )

    assert analysis["trace_status_board"][0]["governance_action"] == "hold_boundary_until_more_context"
    assert analysis["trace_status_board"][0]["nested_only_missing_six_keys"] == []
    assert analysis["trace_status_board"][0]["missing_everywhere_missing_six_keys"] == []
    assert analysis["governance_diagnosis_board"] == [
        {
            "action": "hold_boundary_until_more_context",
            "row_count": 1,
            "tickers": ["002555"],
            "affected_keys": [],
        }
    ]


def test_survivor_key_contrast_board_shows_t0_tail_strength_as_surface_survivor() -> None:
    script = _load_script_module()

    analysis = script.analyze_btst_5d_15pct_boundary_missing_six_core_keys_from_rows([_nested_only_attachment_row()])

    contrast_by_key = {
        row["key"]: row for row in analysis["survivor_key_contrast_board"]
    }

    assert contrast_by_key["t0_tail_strength"] == {
        "key": "t0_tail_strength",
        "source_payload_count": 1,
        "attached_metrics_payload_count": 0,
        "attached_surface_payload_count": 1,
        "snapshot_metrics_payload_count": 0,
        "snapshot_surface_payload_count": 1,
    }
    assert contrast_by_key["breakout_freshness"] == {
        "key": "breakout_freshness",
        "source_payload_count": 0,
        "attached_metrics_payload_count": 1,
        "attached_surface_payload_count": 0,
        "snapshot_metrics_payload_count": 1,
        "snapshot_surface_payload_count": 0,
    }


def _write_live_boundary_artifacts(reports_root: Path) -> dict[str, object]:
    report_dir = reports_root / "paper_trading_window_20260324_boundary_missing_six"
    trade_dir = report_dir / "selection_artifacts" / "2026-03-24"
    trade_dir.mkdir(parents=True, exist_ok=True)

    nested_metrics = {
        "breakout_freshness": 0.91,
        "trend_acceleration": 0.82,
        "volume_expansion_quality": 0.73,
        "close_strength": 0.64,
        "trend_continuation": 0.55,
        "short_term_reversal": 0.18,
    }
    snapshot_target = {
        "candidate_source": "short_trade_boundary",
        "t0_tail_strength": 0.61,
        "short_trade": {
            "decision": "near_miss",
            "t0_tail_strength": 0.61,
            "explainability_payload": {},
            "metrics_payload": nested_metrics,
        },
    }
    replay_input = {
        "trade_date": "20260324",
        "watchlist": [],
        "rejected_entries": [],
        "upstream_shadow_observation_entries": [],
        "supplemental_catalyst_theme_entries": [],
        "supplemental_short_trade_entries": [
            {
                "ticker": "001309",
                "candidate_source": "different_source",
                "breakout_freshness": 0.15,
                "trend_acceleration": 0.15,
                "volume_expansion_quality": 0.15,
                "close_strength": 0.15,
                "trend_continuation": 0.15,
                "short_term_reversal": 0.15,
                "t0_tail_strength": 0.15,
            },
            {
                "ticker": "001309",
                "candidate_source": "short_trade_boundary",
                "t0_tail_strength": 0.61,
                "short_trade_boundary_metrics": nested_metrics,
            },
        ],
        "selection_targets": {
            "001309": snapshot_target,
        },
    }
    snapshot = {
        "trade_date": "20260324",
        "selection_targets": {
            "001309": snapshot_target,
        },
    }
    trade_dir.joinpath("selection_target_replay_input.json").write_text(
        json.dumps(replay_input, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    trade_dir.joinpath("selection_snapshot.json").write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return {
        "report_dir_name": report_dir.name,
        "trade_date": "20260324",
        "ticker": "001309",
        "candidate_source": "short_trade_boundary",
    }


def test_analyze_btst_5d_15pct_boundary_missing_six_core_keys_reconstructs_live_rows_from_artifacts(tmp_path: Path, monkeypatch) -> None:
    script = _load_script_module()
    reports_root = tmp_path / "data" / "reports"
    boundary_row = _write_live_boundary_artifacts(reports_root)

    monkeypatch.setattr(
        script,
        "analyze_btst_5d_15pct_boundary_contract_inspection",
        lambda reports_root: {
            "generated_at": "2026-03-25T00:00:00Z",
            "reports_root": str(Path(reports_root).resolve()),
            "boundary_row_count": 1,
            "boundary_rows": [boundary_row],
        },
    )

    analysis = script.analyze_btst_5d_15pct_boundary_missing_six_core_keys(reports_root)

    assert analysis["generated_at"]
    assert analysis["reports_root"] == str(reports_root.resolve())
    assert analysis["boundary_row_count"] == 1
    assert analysis["trace_status_board"] == [
        {
            "candidate_source": "short_trade_boundary",
            "ticker": "001309",
            "trade_date": "20260324",
            "surface_trace_status_counts": {
                "dropped_before_snapshot": 6,
                "present_end_to_end": 1,
            },
            "surface_trace_statuses": {
                "breakout_freshness": "dropped_before_snapshot",
                "trend_acceleration": "dropped_before_snapshot",
                "volume_expansion_quality": "dropped_before_snapshot",
                "close_strength": "dropped_before_snapshot",
                "trend_continuation": "dropped_before_snapshot",
                "short_term_reversal": "dropped_before_snapshot",
                "t0_tail_strength": "present_end_to_end",
            },
            "nested_only_missing_six_keys": MISSING_SIX_CORE_KEYS,
            "missing_everywhere_missing_six_keys": [],
            "surface_visible_keys": ["t0_tail_strength"],
            "governance_action": "fix_snapshot_attachment_contract",
        }
    ]


def _write_surface_repaired_boundary_artifacts(reports_root: Path) -> dict[str, object]:
    report_dir = reports_root / "paper_trading_window_20260324_boundary_surface_repaired"
    writer = FileSelectionArtifactWriter(
        artifact_root=report_dir / "selection_artifacts",
        run_id="session_surface_repaired",
    )
    evaluation = DualTargetEvaluation(
        ticker="001309",
        trade_date="20260324",
        candidate_source="short_trade_boundary",
        short_trade=TargetEvaluationResult(
            target_type="short_trade",
            decision="near_miss",
            candidate_source="short_trade_boundary",
            explainability_payload={"t0_tail_strength": 0.61},
            metrics_payload={
                "breakout_freshness": 0.81,
                "trend_acceleration": 0.67,
                "volume_expansion_quality": 0.74,
                "close_strength": 0.64,
                "trend_continuation": 0.55,
                "short_term_reversal": 0.18,
            },
        ),
    )
    plan = ExecutionPlan(
        date="20260324",
        portfolio_snapshot={"cash": 100000.0, "positions": {}},
        risk_metrics={
            "funnel_diagnostics": {
                "filters": {
                    "short_trade_candidates": {
                        "tickers": [
                            {
                                "ticker": "001309",
                                "candidate_source": "short_trade_boundary",
                                "t0_tail_strength": 0.61,
                                "short_trade_boundary_metrics": {
                                    "breakout_freshness": 0.81,
                                    "trend_acceleration": 0.67,
                                    "volume_expansion_quality": 0.74,
                                    "close_strength": 0.64,
                                    "trend_continuation": 0.55,
                                    "short_term_reversal": 0.18,
                                },
                            }
                        ]
                    }
                }
            }
        },
        watchlist=[
            LayerCResult(
                ticker="001309",
                score_b=0.8,
                score_c=0.71,
                score_final=0.76,
                quality_score=0.65,
                decision="watch",
            )
        ],
        selection_targets={"001309": evaluation},
        target_mode="short_trade_only",
        dual_target_summary=DualTargetSummary(target_mode="short_trade_only", selection_target_count=1),
        buy_orders=[],
    )
    writer.write_for_plan(plan=plan, trade_date="20260324", pipeline=None, selected_analysts=None)
    return {
        "report_dir_name": report_dir.name,
        "trade_date": "20260324",
        "ticker": "001309",
        "candidate_source": "short_trade_boundary",
    }


def test_analyze_btst_5d_15pct_boundary_missing_six_core_keys_reconstructs_surface_repaired_rows(tmp_path: Path, monkeypatch) -> None:
    script = _load_script_module()
    reports_root = tmp_path / "data" / "reports"
    boundary_row = _write_surface_repaired_boundary_artifacts(reports_root)

    monkeypatch.setattr(
        script,
        "analyze_btst_5d_15pct_boundary_contract_inspection",
        lambda reports_root: {
            "generated_at": "2026-03-25T00:00:00Z",
            "reports_root": str(Path(reports_root).resolve()),
            "boundary_row_count": 1,
            "boundary_rows": [boundary_row],
        },
    )

    analysis = script.analyze_btst_5d_15pct_boundary_missing_six_core_keys(reports_root)

    trace_row = analysis["trace_status_board"][0]
    assert trace_row["nested_only_missing_six_keys"] == ["trend_continuation", "short_term_reversal"], f"nested_only should be only tail-two, got {trace_row['nested_only_missing_six_keys']}"
    assert trace_row["missing_everywhere_missing_six_keys"] == [], f"all keys present somewhere, got {trace_row['missing_everywhere_missing_six_keys']}"
    assert trace_row["surface_visible_keys"] == ["breakout_freshness", "trend_acceleration", "volume_expansion_quality", "close_strength", "t0_tail_strength"], f"four attachment keys + t0_tail_strength should be surface visible, got {trace_row['surface_visible_keys']}"
    assert analysis["governance_diagnosis_board"] == [
        {
            "action": "fix_snapshot_attachment_contract",
            "row_count": 1,
            "tickers": ["001309"],
            "affected_keys": ["trend_continuation", "short_term_reversal"],
        }
    ], f"governance board mismatch: {analysis['governance_diagnosis_board']}"


def test_locate_replay_input_source_entry_does_not_attribute_mismatched_single_ticker_entry() -> None:
    script = _load_script_module()
    replay_input = {
        "supplemental_short_trade_entries": [
            {
                "ticker": "001309",
                "candidate_source": "different_source",
                "upstream_candidate_source": "another_source",
                "t0_tail_strength": 0.15,
            }
        ]
    }

    source_bucket, source_entry = script._locate_replay_input_source_entry(
        replay_input,
        ticker="001309",
        candidate_source="short_trade_boundary",
    )

    assert source_bucket is None
    assert source_entry == {}


def test_render_btst_5d_15pct_boundary_missing_six_core_keys_markdown_summarizes_required_boards() -> None:
    script = _load_script_module()
    analysis = {
        "generated_at": "2026-03-25T00:00:00Z",
        "reports_root": "/repo/data/reports",
        **script.analyze_btst_5d_15pct_boundary_missing_six_core_keys_from_rows([_nested_only_attachment_row()]),
    }

    markdown = script.render_btst_5d_15pct_boundary_missing_six_core_keys_markdown(analysis)

    assert "# BTST 5D / +15% Boundary Missing Six Core Keys" in markdown
    assert "- boundary_row_count: 1" in markdown
    assert "## key_trace_summary_board" in markdown
    assert "## boundary_source_trace_board" in markdown
    assert "## survivor_key_contrast_board" in markdown
    assert "## governance_diagnosis_board" in markdown


def test_main_writes_json_and_markdown_and_prints_compact_summary(tmp_path: Path, monkeypatch, capsys) -> None:
    script = _load_script_module()
    reports_root = tmp_path / "data" / "reports"
    boundary_row = _write_live_boundary_artifacts(reports_root)
    output_json = tmp_path / "outputs" / "boundary_missing_six.json"
    output_md = tmp_path / "outputs" / "boundary_missing_six.md"

    monkeypatch.setattr(
        script,
        "analyze_btst_5d_15pct_boundary_contract_inspection",
        lambda reports_root: {
            "generated_at": "2026-03-25T00:00:00Z",
            "reports_root": str(Path(reports_root).resolve()),
            "boundary_row_count": 1,
            "boundary_rows": [boundary_row],
        },
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "analyze_btst_5d_15pct_boundary_missing_six_core_keys.py",
            "--reports-root",
            str(reports_root),
            "--output-json",
            str(output_json),
            "--output-md",
            str(output_md),
        ],
    )

    script.main()

    written_json = json.loads(output_json.read_text(encoding="utf-8"))
    written_md = output_md.read_text(encoding="utf-8")
    stdout = capsys.readouterr().out.strip()

    assert written_json["reports_root"] == str(reports_root.resolve())
    assert written_json["boundary_row_count"] == 1
    assert "## governance_diagnosis_board" in written_md
    assert stdout.startswith("boundary_missing_six_core_keys:")
    assert "boundary_row_count=1" in stdout
    assert str(output_json.resolve()) in stdout
    assert not stdout.startswith("{")
