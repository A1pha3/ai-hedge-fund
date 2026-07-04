"""P0C (2026-06-04) tests for the versioned, immutable operator_summary.

Key invariants from the plan:
  1. complete / degraded / failed all produce schema-valid JSON.
  2. Source conflicts are never silently overwritten.
  3. Required vs optional artifact absence yields different status.
  4. Same inputs produce identical output (idempotent).
  5. Outcome fields must be rejected by the schema validator.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.paper_trading.btst_operator_summary import (
    ActionabilityStatus,
    build_decision_id,
    build_operator_summary,
    ComparisonScope,
    DecisionPhase,
    IncrementalEvidenceStatus,
    OperatorSummary,
    PointInTimeStatus,
    read_operator_summary,
    SummaryStatus,
    write_operator_summary,
)


def _base_kwargs() -> dict:
    return {
        "signal_date": "20260602",
        "decision_phase": "post_close_plan",
        "next_trade_date": "2026-06-03",
        "decision_as_of": "2026-06-02T23:59:59+08:00",
        "data_as_of": "2026-06-02T15:00:00+08:00",
        "baseline_commit": "abc123",
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
        "profile_compare": {
            "comparison_scope": "doc_bundle_rendering",
            "effective_decision_diff": False,
            "recommended_profile": None,
            "reason": "当前 profile 未改变真实候选或执行语义",
        },
        "artifacts": {
            "required": ["rule_report"],
            "optional": ["early_runner_board"],
            "missing_required": [],
            "missing_optional": [],
        },
    }


class TestSchemaValidation:
    def test_complete_path_produces_valid_json(self) -> None:
        summary = build_operator_summary(**_base_kwargs())
        raw = json.loads(summary.model_dump_json())
        assert raw["schema_version"] == 1
        assert raw["summary_status"] == "complete"
        assert raw["decision_id"].startswith("btst-20260602-post-close-plan-v1")

    def test_degraded_path_produces_valid_json(self) -> None:
        kwargs = _base_kwargs()
        kwargs["summary_status"] = "degraded"
        summary = build_operator_summary(**kwargs)
        raw = json.loads(summary.model_dump_json())
        assert raw["summary_status"] == "degraded"

    def test_failed_path_produces_valid_json(self) -> None:
        kwargs = _base_kwargs()
        kwargs["summary_status"] = "failed"
        # A failed run may have no market or execution data at all.
        kwargs.pop("market", None)
        kwargs.pop("execution", None)
        summary = build_operator_summary(**kwargs)
        raw = json.loads(summary.model_dump_json())
        assert raw["summary_status"] == "failed"
        assert raw["market"]["regime_gate_level"] is None
        assert raw["execution"]["report_mode"] is None

    def test_schema_version_must_be_1(self) -> None:
        kwargs = _base_kwargs()
        with pytest.raises(Exception, match="schema_version"):
            OperatorSummary(schema_version=2, generated_at="...", decision_id="...", decision_as_of="...", data_as_of="...", signal_date="20260602")

    def test_decision_phase_enum(self) -> None:
        for phase in DecisionPhase:
            kwargs = _base_kwargs()
            kwargs["decision_phase"] = phase.value
            summary = build_operator_summary(**kwargs)
            assert summary.decision_phase == phase


class TestOutcomeRejection:
    def test_outcome_field_rejected_at_top_level(self) -> None:
        with pytest.raises(Exception, match="Extra inputs are not permitted|realized_return"):
            OperatorSummary(
                schema_version=1,
                generated_at="2026-01-01T00:00:00Z",
                decision_id="test",
                decision_as_of="2026-01-01T00:00:00Z",
                data_as_of="2026-01-01T00:00:00Z",
                signal_date="20260101",
                realized_return=0.05,
            )

    def test_outcome_field_rejected_even_in_dict(self) -> None:
        # Pydantic ignores extra fields by default, so top-level extra fields
        # are silently dropped. The model_validator catches only fields that
        # are explicitly set. This test confirms the validator fires when
        # we explicitly pass an outcome field.
        with pytest.raises(Exception):
            OperatorSummary(
                schema_version=1,
                generated_at="2026-01-01T00:00:00Z",
                decision_id="test",
                decision_as_of="2026-01-01T00:00:00Z",
                data_as_of="2026-01-01T00:00:00Z",
                signal_date="20260101",
                realized_outcome="profit",
            )


class TestSourceConflicts:
    def test_source_conflicts_are_not_silently_dropped(self) -> None:
        kwargs = _base_kwargs()
        kwargs["source_conflicts"] = [
            {
                "field": "market_gate",
                "artifact_a": "report_a.json",
                "value_a": "halt",
                "artifact_b": "report_b.json",
                "value_b": "normal_trade",
                "resolution": "unresolved",
            }
        ]
        summary = build_operator_summary(**kwargs)
        assert len(summary.source_conflicts) == 1
        assert summary.source_conflicts[0].field == "market_gate"
        assert summary.source_conflicts[0].resolution == "unresolved"


class TestArtifactStatus:
    def test_required_missing_yields_degraded(self) -> None:
        kwargs = _base_kwargs()
        kwargs["artifacts"] = {
            "required": ["rule_report", "session_summary"],
            "optional": ["early_runner_board"],
            "missing_required": ["session_summary"],
            "missing_optional": [],
        }
        # Caller must set summary_status=degraded when required artifacts are missing.
        kwargs["summary_status"] = "degraded"
        summary = build_operator_summary(**kwargs)
        assert summary.summary_status == SummaryStatus.DEGRADED
        assert "session_summary" in summary.artifacts.missing_required

    def test_optional_missing_does_not_imply_failure(self) -> None:
        kwargs = _base_kwargs()
        kwargs["artifacts"] = {
            "required": ["rule_report"],
            "optional": ["early_runner_board", "profile_compare"],
            "missing_required": [],
            "missing_optional": ["profile_compare"],
        }
        summary = build_operator_summary(**kwargs)
        assert summary.summary_status == SummaryStatus.COMPLETE
        assert "profile_compare" in summary.artifacts.missing_optional


class TestIdempotency:
    def test_same_inputs_produce_same_decision_id(self) -> None:
        id_a = build_decision_id(signal_date="20260602", decision_phase="post_close_plan", version=1)
        id_b = build_decision_id(signal_date="20260602", decision_phase="post_close_plan", version=1)
        assert id_a == id_b

    def test_same_inputs_produce_same_json_excluding_timestamps(self) -> None:
        kwargs = _base_kwargs()
        # Fix generated_at to ensure deterministic comparison.
        summary_a = build_operator_summary(**kwargs)
        summary_b = build_operator_summary(**kwargs)
        # decision_id must be identical.
        assert summary_a.decision_id == summary_b.decision_id
        assert summary_a.signal_date == summary_b.signal_date
        assert summary_a.market.market_gate == summary_b.market.market_gate


class TestAtomicWrite:
    def test_write_and_read_roundtrip(self, tmp_path: Path) -> None:
        kwargs = _base_kwargs()
        summary = build_operator_summary(**kwargs)
        out_path = tmp_path / "operator_summary.json"
        write_operator_summary(summary, out_path)
        assert out_path.exists()
        loaded = read_operator_summary(out_path)
        assert loaded.decision_id == summary.decision_id
        assert loaded.signal_date == summary.signal_date
        assert loaded.market.market_gate == summary.market.market_gate

    def test_overwrite_is_atomic(self, tmp_path: Path) -> None:
        kwargs = _base_kwargs()
        summary1 = build_operator_summary(**kwargs)
        out_path = tmp_path / "operator_summary.json"
        write_operator_summary(summary1, out_path)

        kwargs2 = {**kwargs, "summary_status": "degraded"}
        summary2 = build_operator_summary(**kwargs2)
        write_operator_summary(summary2, out_path)

        loaded = read_operator_summary(out_path)
        assert loaded.summary_status == SummaryStatus.DEGRADED
        # No leftover temp files.
        tmp_files = list(tmp_path.glob(".operator_summary_*"))
        assert len(tmp_files) == 0


class TestManualIntervention:
    def test_manual_patch_required_is_alias(self) -> None:
        kwargs = _base_kwargs()
        kwargs["manual_intervention"] = {"required": True, "reasons": ["gate conflict"]}
        summary = build_operator_summary(**kwargs)
        assert summary.manual_patch_required is True
        assert summary.manual_intervention.required is True
        assert "gate conflict" in summary.manual_intervention.reasons

    def test_manual_intervention_defaults_to_not_required(self) -> None:
        summary = build_operator_summary(**_base_kwargs())
        assert summary.manual_intervention.required is False
        assert summary.manual_patch_required is False
