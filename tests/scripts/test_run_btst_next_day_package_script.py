"""P0D (2026-06-04) tests for the unified next-day package entrypoint.

Key invariants from the plan:
  1. Wrapper early-exit still writes a ``failed`` summary.
  2. Same params run twice → no duplicate bridge append (idempotent).
  3. ``--reuse-existing`` does not invoke expensive refresh steps.
  4. ONE-PAGER does not contain fields unavailable at the current phase.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.run_btst_next_day_package import (
    _render_one_pager,
    run_btst_next_day_package,
)


def _minimal_summary() -> dict:
    return {
        "schema_version": 1,
        "summary_status": "complete",
        "generated_at": "2026-06-04T01:00:00+08:00",
        "decision_id": "btst-20260602-post-close-plan-v1",
        "decision_phase": "post_close_plan",
        "signal_date": "20260602",
        "next_trade_date": "2026-06-03",
        "decision_as_of": "2026-06-02T23:59:59+08:00",
        "data_as_of": "2026-06-02T15:00:00+08:00",
        "market": {
            "regime_gate_level": "crisis",
            "market_gate": "halt",
            "gate_enforced": True,
            "buy_orders_cleared": False,
        },
        "execution": {
            "report_mode": "confirmation_review_only",
            "formal_selected_tickers": ["002463"],
            "orderable_tickers": [],
            "confirmation_only_tickers": ["002463"],
            "first_invalidate_if": "开盘后无法形成延续确认",
        },
        "early_runner": {
            "board_date_alignment_status": "exact",
            "artifact_freshness_status": "fresh",
            "point_in_time_status": "safe",
            "source_gate_action": "research_only",
            "actionability_status": "research_only",
            "intersection_count": 0,
            "only_early_runner_count": 0,
            "second_entry_count": 0,
        },
        "incremental_evidence": {
            "status": "insufficient",
            "sample_count": 0,
        },
        "profile_compare": {
            "comparison_scope": "doc_bundle_rendering",
            "effective_decision_diff": False,
        },
        "artifacts": {
            "required": [],
            "optional": [],
            "missing_required": [],
            "missing_optional": [],
        },
    }


class TestOnePager:
    def test_one_pager_renders_from_summary(self) -> None:
        md = _render_one_pager(_minimal_summary())
        assert "# BTST ONE-PAGER" in md
        assert "20260602" in md
        assert "halt" in md
        assert "002463" in md
        assert "evidence insufficient" in md.lower() or "证据不足" in md

    def test_one_pager_post_close_omits_t1_fields(self) -> None:
        """ONE-PAGER at post_close_plan must not include T+1 fields."""
        md = _render_one_pager(_minimal_summary())
        assert "post_close_plan" in md
        # Must include phase restriction warning.
        assert "阶段限制" in md
        assert "不包含 T+1" in md
        # Must NOT contain realized outcome terms.
        assert "filled" not in md.lower()
        assert "realized" not in md.lower()

    def test_one_pager_includes_phase_restriction_warning(self) -> None:
        summary = _minimal_summary()
        summary["decision_phase"] = "post_close_plan"
        md = _render_one_pager(summary)
        assert "阶段限制" in md

    def test_one_pager_shows_evidence_insufficient(self) -> None:
        summary = _minimal_summary()
        summary["incremental_evidence"]["status"] = "insufficient"
        md = _render_one_pager(summary)
        assert "证据不足" in md


class TestOnePagerHonestyDisclosure:
    """Loop 91 (autodev): surface computed-but-never-read honesty fields.

    The operator_summary.json schema captures summary_status, manual_intervention,
    source_conflicts, artifacts.missing_required, bridge.failure_reasons,
    optimization_resolution.fallback_reason, and failed run_steps — but the
    ONE-PAGER renderer dropped them all. Operator reading the markdown had no
    visibility into degraded status, conflicts, missing required artifacts,
    bridge failures, optimization fallbacks, or failed steps.
    """

    def test_one_pager_renders_summary_status_complete(self) -> None:
        """summary_status must be visible at the top of the one-pager."""
        summary = _minimal_summary()
        summary["summary_status"] = "complete"
        md = _render_one_pager(summary)
        assert "complete" in md.lower()

    def test_one_pager_renders_summary_status_degraded(self) -> None:
        """When summary_status=degraded, surface it prominently."""
        summary = _minimal_summary()
        summary["summary_status"] = "degraded"
        md = _render_one_pager(summary)
        assert "degraded" in md.lower()

    def test_one_pager_renders_manual_intervention_when_required(self) -> None:
        """When manual_intervention.required=True, surface reasons."""
        summary = _minimal_summary()
        summary["manual_intervention"] = {
            "required": True,
            "reasons": ["doc bundle failed: RuntimeError('boom')"],
        }
        md = _render_one_pager(summary)
        assert "manual_intervention" in md.lower() or "人工介入" in md
        assert "doc bundle failed" in md

    def test_one_pager_omits_manual_intervention_when_not_required(self) -> None:
        """When manual_intervention.required=False, do not render the section."""
        summary = _minimal_summary()
        summary["manual_intervention"] = {"required": False, "reasons": []}
        md = _render_one_pager(summary)
        assert "人工介入" not in md
        assert "manual_intervention" not in md.lower()

    def test_one_pager_renders_source_conflicts_when_present(self) -> None:
        """When source_conflicts has entries, surface them."""
        summary = _minimal_summary()
        summary["source_conflicts"] = [
            {
                "field": "formal_selected_tickers",
                "artifact_a": "doc_bundle",
                "value_a": ["002463"],
                "artifact_b": "early_runner",
                "value_b": ["002463", "600519"],
                "resolution": "unresolved",
            }
        ]
        md = _render_one_pager(summary)
        assert "source_conflict" in md.lower() or "源冲突" in md
        assert "formal_selected_tickers" in md
        assert "doc_bundle" in md
        assert "early_runner" in md

    def test_one_pager_omits_source_conflicts_when_empty(self) -> None:
        """When source_conflicts is empty, do not render the section."""
        summary = _minimal_summary()
        summary["source_conflicts"] = []
        md = _render_one_pager(summary)
        assert "源冲突" not in md
        assert "source_conflict" not in md.lower()

    def test_one_pager_renders_missing_required_artifacts(self) -> None:
        """When artifacts.missing_required is non-empty, surface it."""
        summary = _minimal_summary()
        summary["artifacts"] = {
            "required": ["doc_bundle", "early_runner"],
            "optional": [],
            "missing_required": ["early_runner"],
            "missing_optional": [],
        }
        md = _render_one_pager(summary)
        assert "missing_required" in md.lower() or "缺失必要产物" in md
        assert "early_runner" in md

    def test_one_pager_renders_bridge_failure_reasons(self) -> None:
        """When bridge.failure_reasons is non-empty, surface it."""
        summary = _minimal_summary()
        summary["bridge"] = {
            "updated_files": [],
            "unchanged_files": [],
            "missing_targets": ["reports/daily.md"],
            "failure_reasons": ["target file is read-only"],
        }
        md = _render_one_pager(summary)
        assert "bridge" in md.lower() or "桥接" in md
        assert "target file is read-only" in md

    def test_one_pager_renders_failed_run_steps(self) -> None:
        """When run_steps has failed entries, surface them."""
        summary = _minimal_summary()
        summary["run_steps"] = [
            {
                "step_name": "generate_doc_bundle",
                "status": "failed",
                "failure_reason": "RuntimeError: boom",
                "duration_seconds": 1.2,
            },
            {
                "step_name": "render_one_pager",
                "status": "success",
                "duration_seconds": 0.1,
            },
        ]
        md = _render_one_pager(summary)
        assert "generate_doc_bundle" in md
        assert "failed" in md.lower()
        assert "RuntimeError: boom" in md

    def test_one_pager_omits_run_steps_when_all_succeeded(self) -> None:
        """When all run_steps succeeded, do not render the section (noise reduction)."""
        summary = _minimal_summary()
        summary["run_steps"] = [
            {"step_name": "step_a", "status": "success"},
            {"step_name": "step_b", "status": "success"},
        ]
        md = _render_one_pager(summary)
        # All-success run_steps should not clutter the one-pager.
        assert "step_a" not in md

    def test_one_pager_renders_optimization_fallback_reason(self) -> None:
        """When optimization_resolution.fallback_reason is set, surface it."""
        summary = _minimal_summary()
        summary["optimization_resolution"] = {
            "status": "fallback",
            "manifest_ref": None,
            "fallback_reason": "optimizer timeout after 30s",
        }
        md = _render_one_pager(summary)
        assert "optimizer timeout" in md

    def test_one_pager_omits_optimization_section_when_unoptimized(self) -> None:
        """When optimization_resolution.status=unoptimized (default), do not render."""
        summary = _minimal_summary()
        summary["optimization_resolution"] = {
            "status": "unoptimized",
            "manifest_ref": None,
            "fallback_reason": None,
        }
        md = _render_one_pager(summary)
        assert "optimization" not in md.lower()
        assert "优化" not in md


class TestWrapperFailedSummary:
    def test_early_exit_writes_failed_summary(self, tmp_path: Path) -> None:
        """When generate_btst_doc_bundle raises, a failed summary is still written."""
        with patch("scripts.generate_btst_doc_bundle.generate_btst_doc_bundle", side_effect=RuntimeError("boom")):
            result = run_btst_next_day_package(
                signal_date="20260602",
                reports_root=str(tmp_path / "reports"),
                output_dir=str(tmp_path / "output"),
                reuse_existing=False,
            )

        assert result["status"] == "failed"
        summary = result["summary"]
        assert summary["summary_status"] == "failed"
        # Verify operator_summary.json was written.
        summary_path = tmp_path / "output" / "operator_summary.json"
        assert summary_path.exists()
        written = json.loads(summary_path.read_text(encoding="utf-8"))
        assert written["summary_status"] == "failed"
        assert written["manual_intervention"]["required"] is True


class TestDryRun:
    def test_dry_run_does_not_write_files(self, tmp_path: Path) -> None:
        with patch("scripts.generate_btst_doc_bundle.generate_btst_doc_bundle") as mock_gen:
            mock_gen.return_value = {
                "status": "generated",
                "signal_date": "20260602",
                "output_dir": str(tmp_path / "output"),
                "written_files": [],
                "early_runner_status": "unavailable",
                "control_tower": {"gate": "normal_trade", "enforced": False, "buy_orders_cleared": False},
                "report_mode": "formal_execution",
                "semantic_selected_labels": [],
            }
            result = run_btst_next_day_package(
                signal_date="20260602",
                reports_root=str(tmp_path / "reports"),
                output_dir=str(tmp_path / "output"),
                dry_run=True,
            )

        assert result["dry_run"] is True
        # No files should be written.
        output_dir = tmp_path / "output"
        if output_dir.exists():
            assert not list(output_dir.iterdir())


class TestReuseExisting:
    def test_reuse_existing_does_not_call_expensive_steps(self, tmp_path: Path) -> None:
        with patch("scripts.generate_btst_doc_bundle.generate_btst_doc_bundle") as mock_gen:
            mock_gen.return_value = {
                "status": "generated",
                "signal_date": "20260602",
                "output_dir": str(tmp_path / "output"),
                "written_files": [],
                "early_runner_status": "unavailable",
                "control_tower": {"gate": "normal_trade", "enforced": False, "buy_orders_cleared": False},
                "report_mode": "formal_execution",
                "semantic_selected_labels": [],
            }
            result = run_btst_next_day_package(
                signal_date="20260602",
                reports_root=str(tmp_path / "reports"),
                output_dir=str(tmp_path / "output"),
                reuse_existing=True,
                refresh_early_runner=False,
                with_profile_compare=False,
            )

        # generate_btst_doc_bundle was called once (doc bundle is the core step).
        assert mock_gen.call_count == 1
        # No profile compare step was run.
        step_names = [s["step_name"] for s in result["steps"]]
        assert "profile_compare" not in step_names


class TestIdempotency:
    def test_same_params_produce_same_decision_id(self, tmp_path: Path) -> None:
        mock_result = {
            "status": "generated",
            "signal_date": "20260602",
            "output_dir": str(tmp_path / "output"),
            "written_files": [],
            "early_runner_status": "unavailable",
            "control_tower": {"gate": "normal_trade", "enforced": False, "buy_orders_cleared": False},
            "report_mode": "formal_execution",
            "semantic_selected_labels": [],
        }
        with patch("scripts.generate_btst_doc_bundle.generate_btst_doc_bundle", return_value=mock_result):
            result_a = run_btst_next_day_package(
                signal_date="20260602",
                reports_root=str(tmp_path / "reports"),
                output_dir=str(tmp_path / "output_a"),
            )
        with patch("scripts.generate_btst_doc_bundle.generate_btst_doc_bundle", return_value=mock_result):
            result_b = run_btst_next_day_package(
                signal_date="20260602",
                reports_root=str(tmp_path / "reports"),
                output_dir=str(tmp_path / "output_b"),
            )
        assert result_a["summary"]["decision_id"] == result_b["summary"]["decision_id"]


class TestRefreshOnceInvariant:
    def test_profile_compare_does_not_refresh_early_runner_twice(self, tmp_path: Path) -> None:
        """P0D (2026-06-04): profile compare must never refresh early-runner a second time.

        Plan invariant: "保证 early-runner 整次运行最多刷新一次" — even when both
        --refresh-early-runner and --with-profile-compare are set, the profile compare
        step must pass refresh_early_runner=False to the inner generate_btst_doc_bundle.
        """
        refresh_call_args: list[dict] = []

        def _fake_generate(signal_date, **kwargs):
            refresh_call_args.append(kwargs.get("refresh_early_runner"))
            profile_output_dir = Path(kwargs["output_dir"])
            profile_output_dir.mkdir(parents=True, exist_ok=True)
            (profile_output_dir / f"BTST-{signal_date}.md").write_text("# BTST\n", encoding="utf-8")
            (profile_output_dir / f"BTST-LLM-{signal_date}.md").write_text("# BTST-LLM\n", encoding="utf-8")
            return {
                "status": "generated",
                "signal_date": signal_date,
                "output_dir": str(profile_output_dir),
                "written_files": [
                    str(profile_output_dir / f"BTST-{signal_date}.md"),
                    str(profile_output_dir / f"BTST-LLM-{signal_date}.md"),
                ],
                "early_runner_status": "exact",
                "early_runner_intersection_count": 0,
                "early_runner_only_count": 0,
                "early_runner_second_entry_count": 0,
                "control_tower": {
                    "gate": "normal_trade",
                    "enforced": False,
                    "buy_orders_cleared": False,
                },
                "report_mode": "formal_execution",
                "semantic_selected_labels": [],
            }

        with patch("scripts.generate_btst_doc_bundle.generate_btst_doc_bundle", side_effect=_fake_generate):
            run_btst_next_day_package(
                signal_date="20260602",
                reports_root=str(tmp_path / "reports"),
                output_dir=str(tmp_path / "output"),
                refresh_early_runner=True,  # First call SHOULD refresh.
                with_profile_compare=True,  # Then profile compare runs.
            )

        # The first call (initial doc bundle) and the second call (profile compare)
        # are the only generate_btst_doc_bundle invocations.
        assert len(refresh_call_args) >= 2
        # First call respects the user's refresh flag.
        assert refresh_call_args[0] is True
        # Subsequent calls (profile compare) MUST NOT refresh.
        for arg in refresh_call_args[1:]:
            assert arg is False, f"Profile compare must not refresh; got {arg}"
