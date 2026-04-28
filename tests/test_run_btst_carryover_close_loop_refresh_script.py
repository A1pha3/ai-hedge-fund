from __future__ import annotations

from pathlib import Path

from scripts.run_btst_carryover_close_loop_refresh import refresh_btst_carryover_close_loop_bundle


def test_refresh_btst_carryover_close_loop_bundle_writes_all_artifacts(monkeypatch, tmp_path: Path) -> None:
    reports_root = tmp_path / "reports"
    output_dir = tmp_path / "outputs"
    reports_root.mkdir(parents=True, exist_ok=True)

    selected_payload = {
        "report_dir": str(reports_root / "sample_report"),
        "entries": [{"ticker": "002001", "current_cycle_status": "missing_next_day", "overall_contract_verdict": "pending_next_day"}],
    }
    anchor_payload = {"ticker": "002001", "probes": []}
    harvest_payload = {"focus_ticker": "300408", "focus_status": "next_day_watch", "priority_expansion_tickers": [], "harvest_entries": []}
    multiday_payload = {"selected_ticker": "002001", "policy_checks": {"selected_path_t2_bias_only": True}, "supportive_cohort_rows": []}
    expansion_payload = {
        "focus_ticker": "300408",
        "focus_status": "next_day_watch_priority",
        "priority_expansion_tickers": ["300408", "301396"],
        "watch_with_risk_tickers": ["688498"],
    }
    proof_payload = {
        "focus_ticker": "301396",
        "focus_promotion_review_verdict": "ready_for_promotion_review",
        "ready_for_promotion_review_tickers": ["301396"],
    }
    gate_payload = {
        "focus_ticker": "301396",
        "focus_gate_verdict": "blocked_selected_contract_open",
        "ready_tickers": [],
    }

    monkeypatch.setattr("scripts.run_btst_carryover_close_loop_refresh.analyze_btst_selected_outcome_refresh_board", lambda reports_root: selected_payload)
    monkeypatch.setattr("scripts.run_btst_carryover_close_loop_refresh.render_btst_selected_outcome_refresh_board_markdown", lambda payload: "# selected\n")
    monkeypatch.setattr(
        "scripts.run_btst_carryover_close_loop_refresh.analyze_btst_carryover_anchor_probe",
        lambda reports_root, ticker, report_dir=None: anchor_payload,
    )
    monkeypatch.setattr("scripts.run_btst_carryover_close_loop_refresh.render_btst_carryover_anchor_probe_markdown", lambda payload: "# anchor\n")
    monkeypatch.setattr("scripts.run_btst_carryover_close_loop_refresh.analyze_btst_carryover_aligned_peer_harvest", lambda path: harvest_payload)
    monkeypatch.setattr("scripts.run_btst_carryover_close_loop_refresh.render_btst_carryover_aligned_peer_harvest_markdown", lambda payload: "# harvest\n")
    monkeypatch.setattr("scripts.run_btst_carryover_close_loop_refresh.analyze_btst_carryover_multiday_continuation_audit", lambda reports_root: multiday_payload)
    monkeypatch.setattr("scripts.run_btst_carryover_close_loop_refresh.render_btst_carryover_multiday_continuation_audit_markdown", lambda payload: "# multiday\n")
    monkeypatch.setattr("scripts.run_btst_carryover_close_loop_refresh.analyze_btst_carryover_peer_expansion", lambda harvest_json, multiday_json: expansion_payload)
    monkeypatch.setattr("scripts.run_btst_carryover_close_loop_refresh.render_btst_carryover_peer_expansion_markdown", lambda payload: "# expansion\n")
    monkeypatch.setattr("scripts.run_btst_carryover_close_loop_refresh.analyze_btst_carryover_aligned_peer_proof_board", lambda harvest_json, expansion_json, selected_json: proof_payload)
    monkeypatch.setattr("scripts.run_btst_carryover_close_loop_refresh.render_btst_carryover_aligned_peer_proof_board_markdown", lambda payload: "# proof\n")
    monkeypatch.setattr("scripts.run_btst_carryover_close_loop_refresh.analyze_btst_carryover_peer_promotion_gate", lambda proof_json, selected_json: gate_payload)
    monkeypatch.setattr("scripts.run_btst_carryover_close_loop_refresh.render_btst_carryover_peer_promotion_gate_markdown", lambda payload: "# gate\n")
    monkeypatch.setattr(
        "scripts.run_btst_carryover_close_loop_refresh.generate_btst_nightly_control_tower_artifacts",
        lambda **kwargs: {"json_path": str(output_dir / "btst_nightly_control_tower_latest.json"), "markdown_path": str(output_dir / "btst_nightly_control_tower_latest.md")},
    )

    bundle = refresh_btst_carryover_close_loop_bundle(reports_root, output_dir=output_dir, refresh_control_tower=True)

    assert bundle["selected_ticker"] == "002001"
    assert bundle["peer_focus_ticker"] == "300408"
    assert bundle["peer_proof_focus_ticker"] == "301396"
    assert bundle["peer_promotion_gate_focus_ticker"] == "301396"
    assert bundle["ready_for_promotion_review_tickers"] == ["301396"]
    assert bundle["priority_expansion_tickers"] == ["300408", "301396"]
    assert bundle["watch_with_risk_tickers"] == ["688498"]
    assert (output_dir / "btst_selected_outcome_refresh_board_latest.json").exists()
    assert (output_dir / "btst_carryover_anchor_probe_latest.json").exists()
    assert (output_dir / "btst_carryover_aligned_peer_harvest_latest.json").exists()
    assert (output_dir / "btst_carryover_multiday_continuation_audit_latest.json").exists()
    assert (output_dir / "btst_carryover_peer_expansion_latest.json").exists()
    assert (output_dir / "btst_carryover_aligned_peer_proof_board_latest.json").exists()
    assert (output_dir / "btst_carryover_peer_promotion_gate_latest.json").exists()


def test_refresh_btst_carryover_close_loop_bundle_short_circuits_without_formal_selected(monkeypatch, tmp_path: Path) -> None:
    reports_root = tmp_path / "reports"
    output_dir = tmp_path / "outputs"
    reports_root.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(
        "scripts.run_btst_carryover_close_loop_refresh.analyze_btst_selected_outcome_refresh_board",
        lambda reports_root: {"entries": [], "report_dir": str(reports_root)},
    )
    monkeypatch.setattr("scripts.run_btst_carryover_close_loop_refresh.render_btst_selected_outcome_refresh_board_markdown", lambda payload: "# selected\n")

    bundle = refresh_btst_carryover_close_loop_bundle(reports_root, output_dir=output_dir, refresh_control_tower=False)

    assert bundle["status"] == "no_formal_selected"
    assert bundle["selected_ticker"] is None
    assert "selected_outcome_refresh_json" in bundle["artifact_paths"]
    assert (output_dir / "btst_selected_outcome_refresh_board_latest.json").exists()


def test_refresh_btst_carryover_close_loop_bundle_threads_pending_peer_proof_contract(monkeypatch, tmp_path: Path) -> None:
    reports_root = tmp_path / "reports"
    output_dir = tmp_path / "outputs"
    reports_root.mkdir(parents=True, exist_ok=True)

    selected_payload = {
        "report_dir": str(reports_root / "sample_report"),
        "entries": [{"ticker": "300720", "current_cycle_status": "t_plus_4_closed", "overall_contract_verdict": "t_plus_2_observed_without_positive_expectation"}],
    }
    anchor_payload = {"ticker": "300720", "probes": []}
    harvest_payload = {"focus_ticker": "300620", "focus_status": "next_day_watch", "harvest_entries": []}
    multiday_payload = {"selected_ticker": "300720", "policy_checks": {"selected_path_t2_bias_only": True}, "supportive_cohort_rows": []}
    expansion_payload = {
        "focus_ticker": "300620",
        "focus_status": "next_day_watch_priority",
        "priority_expansion_tickers": ["300620", "603256"],
        "watch_with_risk_tickers": ["688498"],
    }
    proof_payload = {
        "focus_ticker": "300620",
        "focus_promotion_review_verdict": "await_t_plus_2_close",
        "ready_for_promotion_review_tickers": [],
    }
    gate_payload = {
        "focus_ticker": "300620",
        "focus_gate_verdict": "await_peer_t_plus_2_close",
        "default_expansion_status": "pending_peer_proof",
        "ready_tickers": [],
        "pending_t_plus_2_tickers": ["300620", "603256"],
        "pending_next_day_tickers": ["600989"],
    }

    monkeypatch.setattr("scripts.run_btst_carryover_close_loop_refresh.analyze_btst_selected_outcome_refresh_board", lambda reports_root: selected_payload)
    monkeypatch.setattr("scripts.run_btst_carryover_close_loop_refresh.render_btst_selected_outcome_refresh_board_markdown", lambda payload: "# selected\n")
    monkeypatch.setattr(
        "scripts.run_btst_carryover_close_loop_refresh.analyze_btst_carryover_anchor_probe",
        lambda reports_root, ticker, report_dir=None: anchor_payload,
    )
    monkeypatch.setattr("scripts.run_btst_carryover_close_loop_refresh.render_btst_carryover_anchor_probe_markdown", lambda payload: "# anchor\n")
    monkeypatch.setattr("scripts.run_btst_carryover_close_loop_refresh.analyze_btst_carryover_aligned_peer_harvest", lambda path: harvest_payload)
    monkeypatch.setattr("scripts.run_btst_carryover_close_loop_refresh.render_btst_carryover_aligned_peer_harvest_markdown", lambda payload: "# harvest\n")
    monkeypatch.setattr("scripts.run_btst_carryover_close_loop_refresh.analyze_btst_carryover_multiday_continuation_audit", lambda reports_root: multiday_payload)
    monkeypatch.setattr("scripts.run_btst_carryover_close_loop_refresh.render_btst_carryover_multiday_continuation_audit_markdown", lambda payload: "# multiday\n")
    monkeypatch.setattr("scripts.run_btst_carryover_close_loop_refresh.analyze_btst_carryover_peer_expansion", lambda harvest_json, multiday_json: expansion_payload)
    monkeypatch.setattr("scripts.run_btst_carryover_close_loop_refresh.render_btst_carryover_peer_expansion_markdown", lambda payload: "# expansion\n")
    monkeypatch.setattr("scripts.run_btst_carryover_close_loop_refresh.analyze_btst_carryover_aligned_peer_proof_board", lambda harvest_json, expansion_json, selected_json: proof_payload)
    monkeypatch.setattr("scripts.run_btst_carryover_close_loop_refresh.render_btst_carryover_aligned_peer_proof_board_markdown", lambda payload: "# proof\n")
    monkeypatch.setattr("scripts.run_btst_carryover_close_loop_refresh.analyze_btst_carryover_peer_promotion_gate", lambda proof_json, selected_json: gate_payload)
    monkeypatch.setattr("scripts.run_btst_carryover_close_loop_refresh.render_btst_carryover_peer_promotion_gate_markdown", lambda payload: "# gate\n")

    bundle = refresh_btst_carryover_close_loop_bundle(reports_root, output_dir=output_dir, refresh_control_tower=False)

    assert bundle["peer_promotion_gate_default_expansion_status"] == "pending_peer_proof"
    assert bundle["peer_promotion_gate_pending_t_plus_2_tickers"] == ["300620", "603256"]
    assert bundle["peer_promotion_gate_pending_next_day_tickers"] == ["600989"]
