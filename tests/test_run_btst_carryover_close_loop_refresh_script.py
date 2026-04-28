from __future__ import annotations

from pathlib import Path

import scripts.run_btst_carryover_close_loop_refresh as refresh_module

from scripts.run_btst_carryover_close_loop_refresh import refresh_btst_carryover_close_loop_bundle


def test_refresh_btst_carryover_close_loop_bundle_writes_carryover_artifacts(monkeypatch, tmp_path: Path) -> None:
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
    monkeypatch.setattr("scripts.run_btst_carryover_close_loop_refresh.analyze_btst_prepared_breakout_cohort", lambda reports_root: {"verdict": "stable_selected_relief_peer_found"})
    monkeypatch.setattr("scripts.run_btst_carryover_close_loop_refresh.render_btst_prepared_breakout_cohort_markdown", lambda payload: "# prepared breakout\n")
    monkeypatch.setattr(
        "scripts.run_btst_carryover_close_loop_refresh.analyze_btst_candidate_pool_recall_dossier",
        lambda tradeable_opportunity_pool_path, watchlist_recall_dossier_path=None, failure_dossier_path=None: {"dominant_stage": "candidate_pool"},
    )
    monkeypatch.setattr("scripts.run_btst_carryover_close_loop_refresh.render_btst_candidate_pool_recall_dossier_markdown", lambda payload: "# candidate pool\n")
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
    candidate_pool_calls: list[Path] = []

    monkeypatch.setattr(
        "scripts.run_btst_carryover_close_loop_refresh.analyze_btst_selected_outcome_refresh_board",
        lambda reports_root: {"entries": [], "report_dir": str(reports_root)},
    )
    monkeypatch.setattr("scripts.run_btst_carryover_close_loop_refresh.render_btst_selected_outcome_refresh_board_markdown", lambda payload: "# selected\n")
    monkeypatch.setattr("scripts.run_btst_carryover_close_loop_refresh.analyze_btst_prepared_breakout_cohort", lambda reports_root: {"verdict": "stable_selected_relief_peer_found"})
    monkeypatch.setattr("scripts.run_btst_carryover_close_loop_refresh.render_btst_prepared_breakout_cohort_markdown", lambda payload: "# prepared breakout\n")

    def _record_candidate_pool_call(
        tradeable_opportunity_pool_path: Path,
        watchlist_recall_dossier_path: Path | None = None,
        failure_dossier_path: Path | None = None,
    ) -> dict[str, str]:
        candidate_pool_calls.append(Path(tradeable_opportunity_pool_path))
        return {"dominant_stage": "candidate_pool"}

    monkeypatch.setattr("scripts.run_btst_carryover_close_loop_refresh.analyze_btst_candidate_pool_recall_dossier", _record_candidate_pool_call)
    monkeypatch.setattr("scripts.run_btst_carryover_close_loop_refresh.render_btst_candidate_pool_recall_dossier_markdown", lambda payload: "# candidate pool\n")
    monkeypatch.setattr(refresh_module, "DEFAULT_TRADEABLE_OPPORTUNITY_POOL_FILENAME", "btst_tradeable_opportunity_pool_april.json", raising=False)

    bundle = refresh_btst_carryover_close_loop_bundle(reports_root, output_dir=output_dir, refresh_control_tower=False)

    assert bundle["status"] == "no_formal_selected"
    assert bundle["selected_ticker"] is None
    assert "selected_outcome_refresh_json" in bundle["artifact_paths"]
    assert bundle["artifact_paths"]["prepared_breakout_cohort_json"] == str((output_dir / "btst_prepared_breakout_cohort_latest.json").resolve())
    assert bundle["artifact_paths"]["candidate_pool_recall_dossier_json"] == str((output_dir / "btst_candidate_pool_recall_dossier_latest.json").resolve())
    assert (output_dir / "btst_selected_outcome_refresh_board_latest.json").exists()
    assert (output_dir / "btst_prepared_breakout_cohort_latest.json").exists()
    assert (output_dir / "btst_candidate_pool_recall_dossier_latest.json").exists()
    assert candidate_pool_calls == [(reports_root / "btst_tradeable_opportunity_pool_april.json").resolve()]


def test_refresh_btst_carryover_close_loop_bundle_refreshes_selection_artifacts_before_retry(monkeypatch, tmp_path: Path) -> None:
    reports_root = tmp_path / "paper_trading_window_sample"
    output_dir = tmp_path / "outputs"
    reports_root.mkdir(parents=True, exist_ok=True)
    (reports_root / "daily_events.jsonl").write_text('{"event":"paper_trading_day"}\n', encoding="utf-8")

    selected_payload = {
        "report_dir": str(reports_root),
        "entries": [{"ticker": "002001", "current_cycle_status": "missing_next_day", "overall_contract_verdict": "pending_next_day"}],
    }
    anchor_payload = {"ticker": "002001", "probes": []}
    harvest_payload = {"focus_ticker": "300408", "focus_status": "next_day_watch", "priority_expansion_tickers": [], "harvest_entries": []}
    multiday_payload = {"selected_ticker": "002001", "policy_checks": {"selected_path_t2_bias_only": True}, "supportive_cohort_rows": []}
    expansion_payload = {"focus_ticker": "300408", "focus_status": "next_day_watch_priority", "priority_expansion_tickers": ["300408"], "watch_with_risk_tickers": []}
    proof_payload = {"focus_ticker": "301396", "focus_promotion_review_verdict": "ready_for_promotion_review", "ready_for_promotion_review_tickers": ["301396"]}
    gate_payload = {"focus_ticker": "301396", "focus_gate_verdict": "blocked_selected_contract_open", "ready_tickers": []}
    refresh_calls: list[Path] = []
    analyze_attempts = {"count": 0}

    def _selected_board_with_retry(reports_root: Path) -> dict[str, object]:
        analyze_attempts["count"] += 1
        if analyze_attempts["count"] == 1:
            raise ValueError("No BTST snapshot with formal selected entries found")
        return selected_payload

    monkeypatch.setattr("scripts.run_btst_carryover_close_loop_refresh.analyze_btst_selected_outcome_refresh_board", _selected_board_with_retry)
    monkeypatch.setattr("scripts.run_btst_carryover_close_loop_refresh.render_btst_selected_outcome_refresh_board_markdown", lambda payload: "# selected\n")
    monkeypatch.setattr(
        refresh_module,
        "refresh_selection_artifacts_for_report",
        lambda report_dir: refresh_calls.append(Path(report_dir).resolve()) or {"report_dir": str(report_dir), "results": []},
        raising=False,
    )
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
    monkeypatch.setattr("scripts.run_btst_carryover_close_loop_refresh.analyze_btst_prepared_breakout_cohort", lambda reports_root: {"verdict": "stable_selected_relief_peer_found"})
    monkeypatch.setattr("scripts.run_btst_carryover_close_loop_refresh.render_btst_prepared_breakout_cohort_markdown", lambda payload: "# prepared breakout\n")
    monkeypatch.setattr(
        "scripts.run_btst_carryover_close_loop_refresh.analyze_btst_candidate_pool_recall_dossier",
        lambda tradeable_opportunity_pool_path, watchlist_recall_dossier_path=None, failure_dossier_path=None: {"dominant_stage": "candidate_pool"},
    )
    monkeypatch.setattr("scripts.run_btst_carryover_close_loop_refresh.render_btst_candidate_pool_recall_dossier_markdown", lambda payload: "# candidate pool\n")

    bundle = refresh_btst_carryover_close_loop_bundle(reports_root, output_dir=output_dir, refresh_control_tower=False)

    assert bundle["selected_ticker"] == "002001"
    assert analyze_attempts["count"] == 2
    assert refresh_calls == [reports_root.resolve()]


def test_refresh_btst_carryover_close_loop_bundle_backfills_followup_before_anchor_probe(monkeypatch, tmp_path: Path) -> None:
    reports_root = tmp_path / "paper_trading_window_sample"
    output_dir = tmp_path / "outputs"
    reports_root.mkdir(parents=True, exist_ok=True)
    (reports_root / "session_summary.json").write_text("{}", encoding="utf-8")

    selected_payload = {
        "report_dir": str(reports_root),
        "trade_date": "2026-04-22",
        "entries": [{"ticker": "688313", "current_cycle_status": "missing_next_day", "overall_contract_verdict": "pending_next_day"}],
    }
    followup_calls: list[tuple[Path, str]] = []

    monkeypatch.setattr("scripts.run_btst_carryover_close_loop_refresh.analyze_btst_selected_outcome_refresh_board", lambda reports_root: selected_payload)
    monkeypatch.setattr("scripts.run_btst_carryover_close_loop_refresh.render_btst_selected_outcome_refresh_board_markdown", lambda payload: "# selected\n")
    monkeypatch.setattr(
        refresh_module,
        "load_btst_followup_by_ticker_for_report",
        lambda report_dir: {},
        raising=False,
    )
    monkeypatch.setattr(
        refresh_module,
        "generate_and_register_btst_followup_artifacts",
        lambda report_dir, trade_date: followup_calls.append((Path(report_dir).resolve(), str(trade_date))),
        raising=False,
    )
    monkeypatch.setattr("scripts.run_btst_carryover_close_loop_refresh.analyze_btst_prepared_breakout_cohort", lambda reports_root: {"verdict": "stable_selected_relief_peer_found"})
    monkeypatch.setattr("scripts.run_btst_carryover_close_loop_refresh.render_btst_prepared_breakout_cohort_markdown", lambda payload: "# prepared breakout\n")

    def _stub_tradeable_pool_artifacts(reports_root: Path, **kwargs) -> dict[str, str]:
        output_json_path = (Path(reports_root) / "btst_tradeable_opportunity_pool_march.json").resolve()
        output_json_path.write_text('{"rows": [], "no_candidate_entry_summary": {}}', encoding="utf-8")
        return {"json_path": str(output_json_path)}

    monkeypatch.setattr(
        refresh_module,
        "generate_btst_tradeable_opportunity_pool_artifacts",
        _stub_tradeable_pool_artifacts,
        raising=False,
    )
    monkeypatch.setattr(refresh_module, "analyze_btst_watchlist_recall_dossier", lambda tradeable_opportunity_pool_path, failure_dossier_path=None, priority_limit=5: {"priority_ticker_dossiers": []}, raising=False)
    monkeypatch.setattr(refresh_module, "render_btst_watchlist_recall_dossier_markdown", lambda payload: "# watchlist\n", raising=False)
    monkeypatch.setattr(refresh_module, "analyze_btst_no_candidate_entry_failure_dossier", lambda tradeable_opportunity_pool_path, **kwargs: {"priority_ticker_dossiers": []}, raising=False)
    monkeypatch.setattr(refresh_module, "render_btst_no_candidate_entry_failure_dossier_markdown", lambda payload: "# failure\n", raising=False)
    monkeypatch.setattr("scripts.run_btst_carryover_close_loop_refresh.analyze_btst_candidate_pool_recall_dossier", lambda tradeable_opportunity_pool_path, watchlist_recall_dossier_path=None, failure_dossier_path=None: {"dominant_stage": "candidate_pool"})
    monkeypatch.setattr("scripts.run_btst_carryover_close_loop_refresh.render_btst_candidate_pool_recall_dossier_markdown", lambda payload: "# candidate pool\n")
    monkeypatch.setattr("scripts.run_btst_carryover_close_loop_refresh.analyze_btst_carryover_anchor_probe", lambda reports_root, ticker, report_dir=None: {"ticker": ticker, "probes": []})
    monkeypatch.setattr("scripts.run_btst_carryover_close_loop_refresh.render_btst_carryover_anchor_probe_markdown", lambda payload: "# anchor\n")
    monkeypatch.setattr("scripts.run_btst_carryover_close_loop_refresh.analyze_btst_carryover_aligned_peer_harvest", lambda path: {"focus_ticker": "688313", "focus_status": "watch", "priority_expansion_tickers": [], "harvest_entries": []})
    monkeypatch.setattr("scripts.run_btst_carryover_close_loop_refresh.render_btst_carryover_aligned_peer_harvest_markdown", lambda payload: "# harvest\n")
    monkeypatch.setattr("scripts.run_btst_carryover_close_loop_refresh.analyze_btst_carryover_multiday_continuation_audit", lambda reports_root: {"selected_ticker": "688313", "supportive_cohort_rows": []})
    monkeypatch.setattr("scripts.run_btst_carryover_close_loop_refresh.render_btst_carryover_multiday_continuation_audit_markdown", lambda payload: "# multiday\n")
    monkeypatch.setattr("scripts.run_btst_carryover_close_loop_refresh.analyze_btst_carryover_peer_expansion", lambda harvest_json, multiday_json: {"focus_ticker": "688313", "focus_status": "watch", "priority_expansion_tickers": [], "watch_with_risk_tickers": []})
    monkeypatch.setattr("scripts.run_btst_carryover_close_loop_refresh.render_btst_carryover_peer_expansion_markdown", lambda payload: "# expansion\n")
    monkeypatch.setattr("scripts.run_btst_carryover_close_loop_refresh.analyze_btst_carryover_aligned_peer_proof_board", lambda harvest_json, expansion_json, selected_json: {"focus_ticker": "688313", "focus_promotion_review_verdict": "watch", "ready_for_promotion_review_tickers": []})
    monkeypatch.setattr("scripts.run_btst_carryover_close_loop_refresh.render_btst_carryover_aligned_peer_proof_board_markdown", lambda payload: "# proof\n")
    monkeypatch.setattr("scripts.run_btst_carryover_close_loop_refresh.analyze_btst_carryover_peer_promotion_gate", lambda proof_json, selected_json: {"focus_ticker": "688313", "focus_gate_verdict": "watch", "ready_tickers": []})
    monkeypatch.setattr("scripts.run_btst_carryover_close_loop_refresh.render_btst_carryover_peer_promotion_gate_markdown", lambda payload: "# gate\n")

    bundle = refresh_btst_carryover_close_loop_bundle(reports_root, output_dir=output_dir, refresh_control_tower=False)

    assert bundle["selected_ticker"] == "688313"
    assert followup_calls == [(reports_root.resolve(), "2026-04-22")]


def test_refresh_btst_carryover_close_loop_bundle_skips_followup_generation_without_session_summary(monkeypatch, tmp_path: Path) -> None:
    reports_root = tmp_path / "paper_trading_window_sample"
    output_dir = tmp_path / "outputs"
    reports_root.mkdir(parents=True, exist_ok=True)

    selected_payload = {
        "report_dir": str(reports_root),
        "trade_date": "2026-04-22",
        "entries": [{"ticker": "688313", "current_cycle_status": "missing_next_day", "overall_contract_verdict": "pending_next_day"}],
    }
    followup_calls: list[tuple[Path, str]] = []

    monkeypatch.setattr("scripts.run_btst_carryover_close_loop_refresh.analyze_btst_selected_outcome_refresh_board", lambda reports_root: selected_payload)
    monkeypatch.setattr("scripts.run_btst_carryover_close_loop_refresh.render_btst_selected_outcome_refresh_board_markdown", lambda payload: "# selected\n")
    monkeypatch.setattr(refresh_module, "load_btst_followup_by_ticker_for_report", lambda report_dir: {}, raising=False)
    monkeypatch.setattr(
        refresh_module,
        "generate_and_register_btst_followup_artifacts",
        lambda report_dir, trade_date: followup_calls.append((Path(report_dir).resolve(), str(trade_date))),
        raising=False,
    )
    monkeypatch.setattr("scripts.run_btst_carryover_close_loop_refresh.analyze_btst_prepared_breakout_cohort", lambda reports_root: {"verdict": "stable_selected_relief_peer_found"})
    monkeypatch.setattr("scripts.run_btst_carryover_close_loop_refresh.render_btst_prepared_breakout_cohort_markdown", lambda payload: "# prepared breakout\n")

    def _stub_tradeable_pool_artifacts(reports_root: Path, **kwargs) -> dict[str, str]:
        output_json_path = (Path(reports_root) / "btst_tradeable_opportunity_pool_march.json").resolve()
        output_json_path.write_text('{"rows": [], "no_candidate_entry_summary": {}}', encoding="utf-8")
        return {"json_path": str(output_json_path)}

    monkeypatch.setattr(refresh_module, "generate_btst_tradeable_opportunity_pool_artifacts", _stub_tradeable_pool_artifacts, raising=False)
    monkeypatch.setattr(refresh_module, "analyze_btst_watchlist_recall_dossier", lambda tradeable_opportunity_pool_path, failure_dossier_path=None, priority_limit=5: {"priority_ticker_dossiers": []}, raising=False)
    monkeypatch.setattr(refresh_module, "render_btst_watchlist_recall_dossier_markdown", lambda payload: "# watchlist\n", raising=False)
    monkeypatch.setattr(refresh_module, "analyze_btst_no_candidate_entry_failure_dossier", lambda tradeable_opportunity_pool_path, **kwargs: {"priority_ticker_dossiers": []}, raising=False)
    monkeypatch.setattr(refresh_module, "render_btst_no_candidate_entry_failure_dossier_markdown", lambda payload: "# failure\n", raising=False)
    monkeypatch.setattr("scripts.run_btst_carryover_close_loop_refresh.analyze_btst_candidate_pool_recall_dossier", lambda tradeable_opportunity_pool_path, watchlist_recall_dossier_path=None, failure_dossier_path=None: {"dominant_stage": "candidate_pool"})
    monkeypatch.setattr("scripts.run_btst_carryover_close_loop_refresh.render_btst_candidate_pool_recall_dossier_markdown", lambda payload: "# candidate pool\n")
    monkeypatch.setattr("scripts.run_btst_carryover_close_loop_refresh.analyze_btst_carryover_anchor_probe", lambda reports_root, ticker, report_dir=None: {"ticker": ticker, "probes": []})
    monkeypatch.setattr("scripts.run_btst_carryover_close_loop_refresh.render_btst_carryover_anchor_probe_markdown", lambda payload: "# anchor\n")
    monkeypatch.setattr("scripts.run_btst_carryover_close_loop_refresh.analyze_btst_carryover_aligned_peer_harvest", lambda path: {"focus_ticker": "688313", "focus_status": "watch", "priority_expansion_tickers": [], "harvest_entries": []})
    monkeypatch.setattr("scripts.run_btst_carryover_close_loop_refresh.render_btst_carryover_aligned_peer_harvest_markdown", lambda payload: "# harvest\n")
    monkeypatch.setattr("scripts.run_btst_carryover_close_loop_refresh.analyze_btst_carryover_multiday_continuation_audit", lambda reports_root: {"selected_ticker": "688313", "supportive_cohort_rows": []})
    monkeypatch.setattr("scripts.run_btst_carryover_close_loop_refresh.render_btst_carryover_multiday_continuation_audit_markdown", lambda payload: "# multiday\n")
    monkeypatch.setattr("scripts.run_btst_carryover_close_loop_refresh.analyze_btst_carryover_peer_expansion", lambda harvest_json, multiday_json: {"focus_ticker": "688313", "focus_status": "watch", "priority_expansion_tickers": [], "watch_with_risk_tickers": []})
    monkeypatch.setattr("scripts.run_btst_carryover_close_loop_refresh.render_btst_carryover_peer_expansion_markdown", lambda payload: "# expansion\n")
    monkeypatch.setattr("scripts.run_btst_carryover_close_loop_refresh.analyze_btst_carryover_aligned_peer_proof_board", lambda harvest_json, expansion_json, selected_json: {"focus_ticker": "688313", "focus_promotion_review_verdict": "watch", "ready_for_promotion_review_tickers": []})
    monkeypatch.setattr("scripts.run_btst_carryover_close_loop_refresh.render_btst_carryover_aligned_peer_proof_board_markdown", lambda payload: "# proof\n")
    monkeypatch.setattr("scripts.run_btst_carryover_close_loop_refresh.analyze_btst_carryover_peer_promotion_gate", lambda proof_json, selected_json: {"focus_ticker": "688313", "focus_gate_verdict": "watch", "ready_tickers": []})
    monkeypatch.setattr("scripts.run_btst_carryover_close_loop_refresh.render_btst_carryover_peer_promotion_gate_markdown", lambda payload: "# gate\n")

    bundle = refresh_btst_carryover_close_loop_bundle(reports_root, output_dir=output_dir, refresh_control_tower=False)

    assert bundle["selected_ticker"] == "688313"
    assert followup_calls == []


def test_refresh_btst_carryover_close_loop_bundle_builds_candidate_pool_prerequisites(monkeypatch, tmp_path: Path) -> None:
    reports_root = tmp_path / "paper_trading_window_sample"
    output_dir = tmp_path / "outputs"
    reports_root.mkdir(parents=True, exist_ok=True)

    selected_payload = {
        "report_dir": str(reports_root),
        "entries": [{"ticker": "002001", "current_cycle_status": "missing_next_day", "overall_contract_verdict": "pending_next_day"}],
    }
    anchor_payload = {"ticker": "002001", "probes": []}
    harvest_payload = {"focus_ticker": "300408", "focus_status": "next_day_watch", "priority_expansion_tickers": [], "harvest_entries": []}
    multiday_payload = {"selected_ticker": "002001", "policy_checks": {"selected_path_t2_bias_only": True}, "supportive_cohort_rows": []}
    expansion_payload = {"focus_ticker": "300408", "focus_status": "next_day_watch_priority", "priority_expansion_tickers": ["300408"], "watch_with_risk_tickers": []}
    proof_payload = {"focus_ticker": "301396", "focus_promotion_review_verdict": "ready_for_promotion_review", "ready_for_promotion_review_tickers": ["301396"]}
    gate_payload = {"focus_ticker": "301396", "focus_gate_verdict": "blocked_selected_contract_open", "ready_tickers": []}
    prereq_calls: list[str] = []
    candidate_pool_calls: list[tuple[Path, Path | None, Path | None]] = []

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
    monkeypatch.setattr("scripts.run_btst_carryover_close_loop_refresh.analyze_btst_prepared_breakout_cohort", lambda reports_root: {"verdict": "stable_selected_relief_peer_found"})
    monkeypatch.setattr("scripts.run_btst_carryover_close_loop_refresh.render_btst_prepared_breakout_cohort_markdown", lambda payload: "# prepared breakout\n")

    def _build_tradeable_pool(
        reports_root: Path,
        *,
        output_json: str | Path | None = None,
        output_md: str | Path | None = None,
        output_csv: str | Path | None = None,
        waterfall_output_json: str | Path | None = None,
        waterfall_output_md: str | Path | None = None,
        trade_dates: set[str] | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> dict[str, str]:
        prereq_calls.append("tradeable")
        output_json_path = Path(output_json or reports_root / "btst_tradeable_opportunity_pool_march.json").resolve()
        output_json_path.write_text('{"rows": [], "no_candidate_entry_summary": {}}', encoding="utf-8")
        return {"json_path": str(output_json_path)}

    monkeypatch.setattr(refresh_module, "generate_btst_tradeable_opportunity_pool_artifacts", _build_tradeable_pool, raising=False)
    monkeypatch.setattr(refresh_module, "analyze_btst_watchlist_recall_dossier", lambda tradeable_opportunity_pool_path, failure_dossier_path=None, priority_limit=5: prereq_calls.append("watchlist") or {"priority_ticker_dossiers": []}, raising=False)
    monkeypatch.setattr(refresh_module, "render_btst_watchlist_recall_dossier_markdown", lambda payload: "# watchlist\n", raising=False)
    monkeypatch.setattr(
        refresh_module,
        "analyze_btst_no_candidate_entry_failure_dossier",
        lambda tradeable_opportunity_pool_path, action_board_path=None, replay_bundle_path=None, watchlist_recall_dossier_path=None, corridor_shadow_pack_path=None, priority_limit=5, hotspot_limit=3: prereq_calls.append("failure") or {"priority_ticker_dossiers": []},
        raising=False,
    )
    monkeypatch.setattr(refresh_module, "render_btst_no_candidate_entry_failure_dossier_markdown", lambda payload: "# failure\n", raising=False)

    def _record_candidate_pool_call(
        tradeable_opportunity_pool_path: Path,
        watchlist_recall_dossier_path: Path | None = None,
        failure_dossier_path: Path | None = None,
    ) -> dict[str, str]:
        candidate_pool_calls.append(
            (
                Path(tradeable_opportunity_pool_path).resolve(),
                Path(watchlist_recall_dossier_path).resolve() if watchlist_recall_dossier_path else None,
                Path(failure_dossier_path).resolve() if failure_dossier_path else None,
            )
        )
        return {"dominant_stage": "candidate_pool"}

    monkeypatch.setattr("scripts.run_btst_carryover_close_loop_refresh.analyze_btst_candidate_pool_recall_dossier", _record_candidate_pool_call)
    monkeypatch.setattr("scripts.run_btst_carryover_close_loop_refresh.render_btst_candidate_pool_recall_dossier_markdown", lambda payload: "# candidate pool\n")

    bundle = refresh_btst_carryover_close_loop_bundle(reports_root, output_dir=output_dir, refresh_control_tower=False)

    assert bundle["selected_ticker"] == "002001"
    assert prereq_calls == ["tradeable", "watchlist", "failure"]
    assert (reports_root / "btst_tradeable_opportunity_pool_march.json").exists()
    assert (reports_root / "btst_watchlist_recall_dossier_latest.json").exists()
    assert (reports_root / "btst_no_candidate_entry_failure_dossier_latest.json").exists()
    assert candidate_pool_calls == [
        (
            (reports_root / "btst_tradeable_opportunity_pool_march.json").resolve(),
            (reports_root / "btst_watchlist_recall_dossier_latest.json").resolve(),
            (reports_root / "btst_no_candidate_entry_failure_dossier_latest.json").resolve(),
        )
    ]


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
    monkeypatch.setattr("scripts.run_btst_carryover_close_loop_refresh.analyze_btst_prepared_breakout_cohort", lambda reports_root: {"verdict": "stable_selected_relief_peer_found"})
    monkeypatch.setattr("scripts.run_btst_carryover_close_loop_refresh.render_btst_prepared_breakout_cohort_markdown", lambda payload: "# prepared breakout\n")
    monkeypatch.setattr(
        "scripts.run_btst_carryover_close_loop_refresh.analyze_btst_candidate_pool_recall_dossier",
        lambda tradeable_opportunity_pool_path, watchlist_recall_dossier_path=None, failure_dossier_path=None: {"dominant_stage": "candidate_pool"},
    )
    monkeypatch.setattr("scripts.run_btst_carryover_close_loop_refresh.render_btst_candidate_pool_recall_dossier_markdown", lambda payload: "# candidate pool\n")

    bundle = refresh_btst_carryover_close_loop_bundle(reports_root, output_dir=output_dir, refresh_control_tower=False)

    assert bundle["peer_promotion_gate_default_expansion_status"] == "pending_peer_proof"
    assert bundle["peer_promotion_gate_pending_t_plus_2_tickers"] == ["300620", "603256"]
    assert bundle["peer_promotion_gate_pending_next_day_tickers"] == ["600989"]


def test_refresh_btst_carryover_close_loop_bundle_writes_prepared_breakout_and_candidate_pool_artifacts(monkeypatch, tmp_path: Path) -> None:
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
    expansion_payload = {"focus_ticker": "300408", "focus_status": "next_day_watch_priority", "priority_expansion_tickers": ["300408"], "watch_with_risk_tickers": []}
    proof_payload = {"focus_ticker": "301396", "focus_promotion_review_verdict": "ready_for_promotion_review", "ready_for_promotion_review_tickers": ["301396"]}
    gate_payload = {"focus_ticker": "301396", "focus_gate_verdict": "blocked_selected_contract_open", "ready_tickers": []}
    prepared_breakout_payload = {"verdict": "stable_selected_relief_peer_found", "candidates": [{"ticker": "300505"}]}
    candidate_pool_payload = {"dominant_stage": "candidate_pool", "focus_tickers": ["300408"], "recommendation": "keep tracking"}

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
    monkeypatch.setattr("scripts.run_btst_carryover_close_loop_refresh.analyze_btst_prepared_breakout_cohort", lambda reports_root: prepared_breakout_payload)
    monkeypatch.setattr("scripts.run_btst_carryover_close_loop_refresh.render_btst_prepared_breakout_cohort_markdown", lambda payload: "# prepared breakout\n")
    monkeypatch.setattr(
        "scripts.run_btst_carryover_close_loop_refresh.analyze_btst_candidate_pool_recall_dossier",
        lambda tradeable_opportunity_pool_path, watchlist_recall_dossier_path=None, failure_dossier_path=None: candidate_pool_payload,
    )
    monkeypatch.setattr("scripts.run_btst_carryover_close_loop_refresh.render_btst_candidate_pool_recall_dossier_markdown", lambda payload: "# candidate pool\n")

    bundle = refresh_btst_carryover_close_loop_bundle(reports_root, output_dir=output_dir, refresh_control_tower=False)

    assert (output_dir / "btst_prepared_breakout_cohort_latest.json").exists()
    assert (output_dir / "btst_prepared_breakout_cohort_latest.md").exists()
    assert (output_dir / "btst_candidate_pool_recall_dossier_latest.json").exists()
    assert (output_dir / "btst_candidate_pool_recall_dossier_latest.md").exists()
    assert bundle["artifact_paths"]["prepared_breakout_cohort_json"] == str((output_dir / "btst_prepared_breakout_cohort_latest.json").resolve())
    assert bundle["artifact_paths"]["prepared_breakout_cohort_markdown"] == str((output_dir / "btst_prepared_breakout_cohort_latest.md").resolve())
    assert bundle["artifact_paths"]["candidate_pool_recall_dossier_json"] == str((output_dir / "btst_candidate_pool_recall_dossier_latest.json").resolve())
    assert bundle["artifact_paths"]["candidate_pool_recall_dossier_markdown"] == str((output_dir / "btst_candidate_pool_recall_dossier_latest.md").resolve())
