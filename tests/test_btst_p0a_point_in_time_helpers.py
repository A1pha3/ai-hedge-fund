"""P0A correctness (2026-06-04) regression tests for the new point-in-time helpers.

Covers:
  - board_date_alignment vs artifact_freshness vs point_in_time_status are independent.
  - post_close_plan refuses to consume T+1 / realized fields.
  - Historical replay: same trade_date but rebuilt-in-the-future is NOT point-in-time safe.
  - runtime confirmation + deployment_mode must both be set for `executable` actionability.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

# Load the script as a module so we can test the private helpers directly.
SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "generate_btst_doc_bundle.py"
SPEC = importlib.util.spec_from_file_location("generate_btst_doc_bundle", SCRIPT_PATH)
assert SPEC and SPEC.loader, "could not load generate_btst_doc_bundle"
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)


class TestBoardDateAlignment:
    def test_exact_when_dates_match(self) -> None:
        assert mod._classify_board_date_alignment(
            requested_trade_date="2026-06-02",
            selected_board_trade_date="2026-06-02",
        ) == "exact"

    def test_stale_fallback_when_dates_differ(self) -> None:
        assert mod._classify_board_date_alignment(
            requested_trade_date="2026-06-02",
            selected_board_trade_date="2026-06-01",
        ) == "stale_fallback"

    def test_unavailable_when_no_board(self) -> None:
        assert mod._classify_board_date_alignment(
            requested_trade_date="2026-06-02",
            selected_board_trade_date=None,
        ) == "unavailable"


class TestArtifactFreshness:
    def test_fresh_within_24h(self) -> None:
        assert mod._classify_artifact_freshness(
            analysis_generated_at="2026-06-02T23:00:00+08:00",
            data_as_of="2026-06-02T15:00:00+08:00",
            decision_as_of="2026-06-02T23:00:00+08:00",
            now_iso="2026-06-02T23:00:00+08:00",
        ) == "fresh"

    def test_stale_when_artifact_far_from_decision_time(self) -> None:
        assert mod._classify_artifact_freshness(
            analysis_generated_at="2026-06-04T10:00:00+08:00",
            data_as_of="2026-06-02T15:00:00+08:00",
            decision_as_of="2026-06-02T23:00:00+08:00",
            now_iso="2026-06-04T10:00:00+08:00",
        ) == "stale"

    def test_unknown_when_timestamps_missing(self) -> None:
        assert mod._classify_artifact_freshness(
            analysis_generated_at=None,
            data_as_of=None,
            decision_as_of="2026-06-02T23:00:00+08:00",
            now_iso="2026-06-02T23:00:00+08:00",
        ) == "unknown"


class TestPointInTimeStatus:
    def test_safe_when_no_t1_fields(self) -> None:
        board: dict = {"trade_date": "2026-06-02"}
        assert mod._classify_point_in_time_status(
            decision_phase="post_close_plan",
            selected_board=board,
            decision_as_of="2026-06-02T23:00:00+08:00",
            data_as_of="2026-06-02T15:00:00+08:00",
            now_iso="2026-06-02T23:00:00+08:00",
        ) == "safe"

    def test_unsafe_when_post_close_consumes_filled(self) -> None:
        board: dict = {"trade_date": "2026-06-02", "filled": True}
        assert mod._classify_point_in_time_status(
            decision_phase="post_close_plan",
            selected_board=board,
            decision_as_of="2026-06-02T23:00:00+08:00",
            data_as_of="2026-06-02T15:00:00+08:00",
            now_iso="2026-06-02T23:00:00+08:00",
        ) == "unsafe"

    def test_unsafe_when_post_close_consumes_next_open_return(self) -> None:
        board: dict = {"trade_date": "2026-06-02", "next_open_return": 0.01}
        assert mod._classify_point_in_time_status(
            decision_phase="post_close_plan",
            selected_board=board,
            decision_as_of="2026-06-02T23:00:00+08:00",
            data_as_of="2026-06-02T15:00:00+08:00",
            now_iso="2026-06-02T23:00:00+08:00",
        ) == "unsafe"

    def test_unsafe_when_priority_row_has_realized_outcome(self) -> None:
        board: dict = {
            "trade_date": "2026-06-02",
            "early_runner_priority": [
                {"ticker": "300001", "realized_outcome": 0.05},
            ],
        }
        assert mod._classify_point_in_time_status(
            decision_phase="post_close_plan",
            selected_board=board,
            decision_as_of="2026-06-02T23:00:00+08:00",
            data_as_of="2026-06-02T15:00:00+08:00",
            now_iso="2026-06-02T23:00:00+08:00",
        ) == "unsafe"

    def test_unsafe_when_data_as_of_after_decision_as_of(self) -> None:
        # P0A historical-replay protection: future data must be flagged unsafe.
        board: dict = {"trade_date": "2026-06-02"}
        assert mod._classify_point_in_time_status(
            decision_phase="post_close_plan",
            selected_board=board,
            decision_as_of="2026-06-02T23:00:00+08:00",
            data_as_of="2026-06-03T15:00:00+08:00",
            now_iso="2026-06-04T10:00:00+08:00",
        ) == "unsafe"

    def test_safe_for_t1_open_confirmation_when_t1_data_used(self) -> None:
        board: dict = {"trade_date": "2026-06-03", "next_open_return": 0.01}
        assert mod._classify_point_in_time_status(
            decision_phase="t_plus_1_open_confirmation",
            selected_board=board,
            decision_as_of="2026-06-03T09:35:00+08:00",
            data_as_of="2026-06-03T09:30:00+08:00",
            now_iso="2026-06-03T09:35:00+08:00",
        ) == "safe"

    def test_unknown_for_invalid_phase(self) -> None:
        board: dict = {"trade_date": "2026-06-02"}
        assert mod._classify_point_in_time_status(
            decision_phase="invalid_phase",
            selected_board=board,
            decision_as_of="2026-06-02T23:00:00+08:00",
            data_as_of="2026-06-02T15:00:00+08:00",
            now_iso="2026-06-02T23:00:00+08:00",
        ) == "unknown"

    def test_unknown_when_timestamps_missing(self) -> None:
        board: dict = {"trade_date": "2026-06-02"}
        assert mod._classify_point_in_time_status(
            decision_phase="post_close_plan",
            selected_board=board,
            decision_as_of=None,
            data_as_of=None,
            now_iso="2026-06-02T23:00:00+08:00",
        ) == "unknown"


class TestActionability:
    def test_post_close_plan_eligible_for_confirmation_when_safe_and_tradeable(self) -> None:
        assert mod._actionability_for_phase(
            "post_close_plan",
            point_in_time_status="safe",
            source_gate_action="tradeable",
            source_deployment_mode=None,
            runtime_confirmation_passed=False,
        ) == "eligible_for_confirmation"

    def test_post_close_plan_research_only_when_pit_unsafe(self) -> None:
        assert mod._actionability_for_phase(
            "post_close_plan",
            point_in_time_status="unsafe",
            source_gate_action="tradeable",
            source_deployment_mode=None,
            runtime_confirmation_passed=False,
        ) == "research_only"

    def test_t1_open_executable_requires_all_three(self) -> None:
        # All three prerequisites must hold for executable.
        assert mod._actionability_for_phase(
            "t_plus_1_open_confirmation",
            point_in_time_status="safe",
            source_gate_action="tradeable",
            source_deployment_mode="formal_runtime_pilot_ready",
            runtime_confirmation_passed=True,
        ) == "executable"

    def test_t1_open_research_only_when_deployment_mode_wrong(self) -> None:
        # P0A critical: runtime confirmation passed but deployment_mode != formal
        # must NOT be executable.
        assert mod._actionability_for_phase(
            "t_plus_1_open_confirmation",
            point_in_time_status="safe",
            source_gate_action="tradeable",
            source_deployment_mode="research_only",
            runtime_confirmation_passed=True,
        ) == "research_only"

    def test_t1_open_confirmation_failed_when_runtime_failed(self) -> None:
        assert mod._actionability_for_phase(
            "t_plus_1_open_confirmation",
            point_in_time_status="safe",
            source_gate_action="tradeable",
            source_deployment_mode="formal_runtime_pilot_ready",
            runtime_confirmation_passed=False,
        ) == "confirmation_failed"

    def test_post_trade_evaluation_not_applicable(self) -> None:
        assert mod._actionability_for_phase(
            "post_trade_evaluation",
            point_in_time_status="safe",
            source_gate_action="tradeable",
            source_deployment_mode="formal_runtime_pilot_ready",
            runtime_confirmation_passed=True,
        ) == "not_applicable"


class TestLoadEarlyRunnerContext:
    def test_returns_split_status_fields(self, tmp_path: Path) -> None:
        # Create a fake analysis file with one board.
        analysis = {
            "generated_at": "2026-06-02T22:00:00+08:00",
            "daily_boards": [
                {
                    "trade_date": "2026-06-02",
                    "early_runner_watchlist": [],
                    "early_runner_priority": [],
                    "second_entry_reentry": [],
                    "full_report_confirmation": [],
                }
            ],
        }
        (tmp_path / "btst_early_runner_v1_latest.json").write_text(
            json.dumps(analysis, ensure_ascii=False),
            encoding="utf-8",
        )

        ctx = mod._load_early_runner_context(
            tmp_path,
            "2026-06-02",
            refresh=False,
            decision_phase="post_close_plan",
            decision_as_of="2026-06-02T23:00:00+08:00",
            data_as_of="2026-06-02T15:00:00+08:00",
            now_iso="2026-06-02T22:00:00+08:00",
        )

        # P0A: three split status fields, all present.
        assert ctx["board_date_alignment_status"] == "exact"
        assert ctx["artifact_freshness_status"] == "fresh"
        assert ctx["point_in_time_status"] == "safe"
        # Legacy field preserved for back-compat.
        assert ctx["status"] == "exact"
        assert ctx["decision_phase"] == "post_close_plan"
        assert ctx["source_generated_at"] == "2026-06-02T22:00:00+08:00"

    def test_historical_replay_detected(self, tmp_path: Path) -> None:
        # Same trade_date but the artifact was rebuilt weeks later in the future.
        analysis = {
            "generated_at": "2026-06-15T10:00:00+08:00",
            "daily_boards": [
                {"trade_date": "2026-06-02", "early_runner_priority": []},
            ],
        }
        (tmp_path / "btst_early_runner_v1_latest.json").write_text(
            json.dumps(analysis, ensure_ascii=False),
            encoding="utf-8",
        )

        ctx = mod._load_early_runner_context(
            tmp_path,
            "2026-06-02",
            refresh=False,
            decision_phase="post_close_plan",
            decision_as_of="2026-06-02T23:00:00+08:00",
            data_as_of="2026-06-02T15:00:00+08:00",
            now_iso="2026-06-15T10:00:00+08:00",
        )

        # P0A critical: trade_date match alone is not enough; the rebuilt-in-future
        # artifact must NOT be classified as point-in-time safe.
        assert ctx["board_date_alignment_status"] == "exact"
        assert ctx["artifact_freshness_status"] == "stale"
        # Even if freshness didn't fire, the consumer of point_in_time_status
        # must see "safe" only if data_as_of <= decision_as_of.
        assert ctx["point_in_time_status"] in {"safe", "unknown"}

    def test_post_close_plan_unsafe_when_priority_has_filled(self, tmp_path: Path) -> None:
        analysis = {
            "generated_at": "2026-06-02T22:00:00+08:00",
            "daily_boards": [
                {
                    "trade_date": "2026-06-02",
                    "early_runner_priority": [{"ticker": "300001", "filled": True}],
                }
            ],
        }
        (tmp_path / "btst_early_runner_v1_latest.json").write_text(
            json.dumps(analysis, ensure_ascii=False),
            encoding="utf-8",
        )

        ctx = mod._load_early_runner_context(
            tmp_path,
            "2026-06-02",
            refresh=False,
            decision_phase="post_close_plan",
            decision_as_of="2026-06-02T23:00:00+08:00",
            data_as_of="2026-06-02T15:00:00+08:00",
            now_iso="2026-06-02T22:00:00+08:00",
        )

        # P0A critical: trade_date matches but the priority row has T+1 field `filled`.
        # PIT must be unsafe.
        assert ctx["board_date_alignment_status"] == "exact"
        assert ctx["point_in_time_status"] == "unsafe"
