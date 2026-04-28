from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from scripts.btst_latest_followup_utils import load_btst_followup_by_ticker_for_report
from scripts.analyze_btst_candidate_pool_recall_dossier import (
    DEFAULT_TRADEABLE_OPPORTUNITY_POOL_PATH,
    analyze_btst_candidate_pool_recall_dossier,
    render_btst_candidate_pool_recall_dossier_markdown,
)
from scripts.analyze_btst_no_candidate_entry_failure_dossier import analyze_btst_no_candidate_entry_failure_dossier, render_btst_no_candidate_entry_failure_dossier_markdown
from scripts.analyze_btst_tradeable_opportunity_pool import generate_btst_tradeable_opportunity_pool_artifacts
from scripts.analyze_btst_carryover_aligned_peer_harvest import analyze_btst_carryover_aligned_peer_harvest, render_btst_carryover_aligned_peer_harvest_markdown
from scripts.analyze_btst_carryover_aligned_peer_proof_board import analyze_btst_carryover_aligned_peer_proof_board, render_btst_carryover_aligned_peer_proof_board_markdown
from scripts.analyze_btst_carryover_anchor_probe import analyze_btst_carryover_anchor_probe, render_btst_carryover_anchor_probe_markdown
from scripts.analyze_btst_carryover_multiday_continuation_audit import analyze_btst_carryover_multiday_continuation_audit, render_btst_carryover_multiday_continuation_audit_markdown
from scripts.analyze_btst_carryover_peer_expansion import analyze_btst_carryover_peer_expansion, render_btst_carryover_peer_expansion_markdown
from scripts.analyze_btst_carryover_peer_promotion_gate import analyze_btst_carryover_peer_promotion_gate, render_btst_carryover_peer_promotion_gate_markdown
from scripts.analyze_btst_prepared_breakout_cohort import analyze_btst_prepared_breakout_cohort, render_btst_prepared_breakout_cohort_markdown
from scripts.analyze_btst_watchlist_recall_dossier import analyze_btst_watchlist_recall_dossier, render_btst_watchlist_recall_dossier_markdown
from scripts.analyze_btst_selected_outcome_refresh_board import analyze_btst_selected_outcome_refresh_board, render_btst_selected_outcome_refresh_board_markdown
from scripts.refresh_selection_artifacts_from_daily_events import refresh_selection_artifacts_for_report
from scripts.run_btst_nightly_control_tower import generate_btst_nightly_control_tower_artifacts
from src.paper_trading.btst_reporting import generate_and_register_btst_followup_artifacts


REPORTS_DIR = Path("data/reports")
DEFAULT_BUNDLE_JSON = REPORTS_DIR / "btst_carryover_close_loop_refresh_latest.json"
DEFAULT_BUNDLE_MD = REPORTS_DIR / "btst_carryover_close_loop_refresh_latest.md"
DEFAULT_TRADEABLE_OPPORTUNITY_POOL_FILENAME = DEFAULT_TRADEABLE_OPPORTUNITY_POOL_PATH.name


def _write_artifact(json_path: Path, markdown_path: Path, payload: dict[str, Any], markdown: str) -> None:
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    markdown_path.write_text(markdown, encoding="utf-8")


def _load_selected_board_with_refresh(reports_root: Path) -> dict[str, Any]:
    try:
        return analyze_btst_selected_outcome_refresh_board(reports_root)
    except ValueError as exc:
        if str(exc) != "No BTST snapshot with formal selected entries found":
            raise
        if not (reports_root / "daily_events.jsonl").exists():
            raise
        refresh_selection_artifacts_for_report(reports_root)
        return analyze_btst_selected_outcome_refresh_board(reports_root)


def _ensure_candidate_pool_prerequisites(reports_root: Path) -> dict[str, Path]:
    tradeable_pool_json = reports_root / DEFAULT_TRADEABLE_OPPORTUNITY_POOL_FILENAME
    watchlist_recall_json = reports_root / "btst_watchlist_recall_dossier_latest.json"
    watchlist_recall_md = reports_root / "btst_watchlist_recall_dossier_latest.md"
    failure_dossier_json = reports_root / "btst_no_candidate_entry_failure_dossier_latest.json"
    failure_dossier_md = reports_root / "btst_no_candidate_entry_failure_dossier_latest.md"

    if not tradeable_pool_json.exists():
        generate_btst_tradeable_opportunity_pool_artifacts(
            reports_root,
            output_json=tradeable_pool_json,
            output_md=reports_root / "btst_tradeable_opportunity_pool_march.md",
            output_csv=reports_root / "btst_tradeable_opportunity_pool_march.csv",
            waterfall_output_json=reports_root / "btst_tradeable_opportunity_reason_waterfall_march.json",
            waterfall_output_md=reports_root / "btst_tradeable_opportunity_reason_waterfall_march.md",
        )

    if not watchlist_recall_json.exists():
        watchlist_recall = analyze_btst_watchlist_recall_dossier(tradeable_pool_json)
        _write_artifact(
            watchlist_recall_json,
            watchlist_recall_md,
            watchlist_recall,
            render_btst_watchlist_recall_dossier_markdown(watchlist_recall),
        )

    if not failure_dossier_json.exists():
        failure_dossier = analyze_btst_no_candidate_entry_failure_dossier(
            tradeable_pool_json,
            watchlist_recall_dossier_path=watchlist_recall_json if watchlist_recall_json.exists() else None,
        )
        _write_artifact(
            failure_dossier_json,
            failure_dossier_md,
            failure_dossier,
            render_btst_no_candidate_entry_failure_dossier_markdown(failure_dossier),
        )

    return {
        "tradeable_pool_json": tradeable_pool_json,
        "watchlist_recall_json": watchlist_recall_json,
        "failure_dossier_json": failure_dossier_json,
    }


def _ensure_followup_artifacts_for_focus_ticker(report_dir: Path, *, trade_date: str | None, ticker: str) -> None:
    rows_by_ticker = load_btst_followup_by_ticker_for_report(report_dir)
    if rows_by_ticker.get(ticker):
        return
    if trade_date and (report_dir / "session_summary.json").exists():
        generate_and_register_btst_followup_artifacts(report_dir=report_dir, trade_date=trade_date)


def refresh_btst_carryover_close_loop_bundle(
    reports_root: str | Path,
    *,
    output_dir: str | Path | None = None,
    refresh_control_tower: bool = True,
) -> dict[str, Any]:
    resolved_reports_root = Path(reports_root).expanduser().resolve()
    resolved_output_dir = Path(output_dir).expanduser().resolve() if output_dir else resolved_reports_root
    resolved_output_dir.mkdir(parents=True, exist_ok=True)
    artifact_paths = _resolve_close_loop_artifact_paths(resolved_output_dir)

    selected_board = _load_selected_board_with_refresh(resolved_reports_root)
    _write_artifact(
        artifact_paths["selected_output_json"],
        artifact_paths["selected_output_md"],
        selected_board,
        render_btst_selected_outcome_refresh_board_markdown(selected_board),
    )

    prepared_breakout_cohort = analyze_btst_prepared_breakout_cohort(resolved_reports_root)
    _write_artifact(
        artifact_paths["prepared_breakout_output_json"],
        artifact_paths["prepared_breakout_output_md"],
        prepared_breakout_cohort,
        render_btst_prepared_breakout_cohort_markdown(prepared_breakout_cohort),
    )

    candidate_pool_prerequisites = _ensure_candidate_pool_prerequisites(resolved_reports_root)
    candidate_pool_recall = analyze_btst_candidate_pool_recall_dossier(
        candidate_pool_prerequisites["tradeable_pool_json"],
        watchlist_recall_dossier_path=candidate_pool_prerequisites["watchlist_recall_json"],
        failure_dossier_path=candidate_pool_prerequisites["failure_dossier_json"],
    )
    _write_artifact(
        artifact_paths["candidate_pool_recall_output_json"],
        artifact_paths["candidate_pool_recall_output_md"],
        candidate_pool_recall,
        render_btst_candidate_pool_recall_dossier_markdown(candidate_pool_recall),
    )

    focus_entry = dict((selected_board.get("entries") or [None])[0] or {})
    focus_ticker = str(focus_entry.get("ticker") or "")
    if not focus_ticker:
        bundle = {
            "reports_root": str(resolved_reports_root),
            "selected_ticker": None,
            "status": "no_formal_selected",
            "recommendation": "当前没有 formal selected，close-loop refresh bundle 仅刷新了 selected outcome board。",
            "artifact_paths": {
                "selected_outcome_refresh_json": str(artifact_paths["selected_output_json"]),
                "selected_outcome_refresh_markdown": str(artifact_paths["selected_output_md"]),
                "prepared_breakout_cohort_json": str(artifact_paths["prepared_breakout_output_json"]),
                "prepared_breakout_cohort_markdown": str(artifact_paths["prepared_breakout_output_md"]),
                "candidate_pool_recall_dossier_json": str(artifact_paths["candidate_pool_recall_output_json"]),
                "candidate_pool_recall_dossier_markdown": str(artifact_paths["candidate_pool_recall_output_md"]),
            },
        }
        return bundle

    _ensure_followup_artifacts_for_focus_ticker(
        Path(selected_board.get("report_dir") or resolved_reports_root),
        trade_date=str(selected_board.get("trade_date") or focus_entry.get("trade_date") or ""),
        ticker=focus_ticker,
    )
    anchor_probe = analyze_btst_carryover_anchor_probe(resolved_reports_root, ticker=focus_ticker, report_dir=selected_board.get("report_dir"))
    _write_artifact(artifact_paths["anchor_output_json"], artifact_paths["anchor_output_md"], anchor_probe, render_btst_carryover_anchor_probe_markdown(anchor_probe))

    harvest = analyze_btst_carryover_aligned_peer_harvest(artifact_paths["anchor_output_json"])
    _write_artifact(artifact_paths["harvest_output_json"], artifact_paths["harvest_output_md"], harvest, render_btst_carryover_aligned_peer_harvest_markdown(harvest))

    multiday_audit = analyze_btst_carryover_multiday_continuation_audit(resolved_reports_root)
    _write_artifact(artifact_paths["multiday_output_json"], artifact_paths["multiday_output_md"], multiday_audit, render_btst_carryover_multiday_continuation_audit_markdown(multiday_audit))

    peer_expansion = analyze_btst_carryover_peer_expansion(artifact_paths["harvest_output_json"], artifact_paths["multiday_output_json"])
    _write_artifact(artifact_paths["expansion_output_json"], artifact_paths["expansion_output_md"], peer_expansion, render_btst_carryover_peer_expansion_markdown(peer_expansion))

    peer_proof_board = analyze_btst_carryover_aligned_peer_proof_board(
        artifact_paths["harvest_output_json"],
        artifact_paths["expansion_output_json"],
        artifact_paths["selected_output_json"],
    )
    _write_artifact(artifact_paths["proof_board_output_json"], artifact_paths["proof_board_output_md"], peer_proof_board, render_btst_carryover_aligned_peer_proof_board_markdown(peer_proof_board))

    peer_promotion_gate = analyze_btst_carryover_peer_promotion_gate(artifact_paths["proof_board_output_json"], artifact_paths["selected_output_json"])
    _write_artifact(
        artifact_paths["promotion_gate_output_json"],
        artifact_paths["promotion_gate_output_md"],
        peer_promotion_gate,
        render_btst_carryover_peer_promotion_gate_markdown(peer_promotion_gate),
    )

    control_tower_result: dict[str, Any] = {}
    if refresh_control_tower:
        control_tower_result = generate_btst_nightly_control_tower_artifacts(
            reports_root=resolved_reports_root,
            output_json=resolved_output_dir / "btst_nightly_control_tower_latest.json",
            output_md=resolved_output_dir / "btst_nightly_control_tower_latest.md",
            delta_output_json=resolved_output_dir / "btst_open_ready_delta_latest.json",
            delta_output_md=resolved_output_dir / "btst_open_ready_delta_latest.md",
            close_validation_output_json=resolved_output_dir / "btst_latest_close_validation_latest.json",
            close_validation_output_md=resolved_output_dir / "btst_latest_close_validation_latest.md",
            history_dir=resolved_output_dir / "archive" / "btst_nightly_control_tower_history",
        )

    bundle = _build_close_loop_bundle(
        resolved_reports_root=resolved_reports_root,
        focus_ticker=focus_ticker,
        focus_entry=focus_entry,
        peer_expansion=peer_expansion,
        peer_proof_board=peer_proof_board,
        peer_promotion_gate=peer_promotion_gate,
        refresh_control_tower=refresh_control_tower,
        artifact_paths=artifact_paths,
        control_tower_result=control_tower_result,
    )
    return bundle


def _resolve_close_loop_artifact_paths(resolved_output_dir: Path) -> dict[str, Path]:
    return {
        "selected_output_json": resolved_output_dir / "btst_selected_outcome_refresh_board_latest.json",
        "selected_output_md": resolved_output_dir / "btst_selected_outcome_refresh_board_latest.md",
        "anchor_output_json": resolved_output_dir / "btst_carryover_anchor_probe_latest.json",
        "anchor_output_md": resolved_output_dir / "btst_carryover_anchor_probe_latest.md",
        "harvest_output_json": resolved_output_dir / "btst_carryover_aligned_peer_harvest_latest.json",
        "harvest_output_md": resolved_output_dir / "btst_carryover_aligned_peer_harvest_latest.md",
        "multiday_output_json": resolved_output_dir / "btst_carryover_multiday_continuation_audit_latest.json",
        "multiday_output_md": resolved_output_dir / "btst_carryover_multiday_continuation_audit_latest.md",
        "expansion_output_json": resolved_output_dir / "btst_carryover_peer_expansion_latest.json",
        "expansion_output_md": resolved_output_dir / "btst_carryover_peer_expansion_latest.md",
        "proof_board_output_json": resolved_output_dir / "btst_carryover_aligned_peer_proof_board_latest.json",
        "proof_board_output_md": resolved_output_dir / "btst_carryover_aligned_peer_proof_board_latest.md",
        "promotion_gate_output_json": resolved_output_dir / "btst_carryover_peer_promotion_gate_latest.json",
        "promotion_gate_output_md": resolved_output_dir / "btst_carryover_peer_promotion_gate_latest.md",
        "prepared_breakout_output_json": resolved_output_dir / "btst_prepared_breakout_cohort_latest.json",
        "prepared_breakout_output_md": resolved_output_dir / "btst_prepared_breakout_cohort_latest.md",
        "candidate_pool_recall_output_json": resolved_output_dir / "btst_candidate_pool_recall_dossier_latest.json",
        "candidate_pool_recall_output_md": resolved_output_dir / "btst_candidate_pool_recall_dossier_latest.md",
    }


def _build_close_loop_bundle(
    *,
    resolved_reports_root: Path,
    focus_ticker: str,
    focus_entry: dict[str, Any],
    peer_expansion: dict[str, Any],
    peer_proof_board: dict[str, Any],
    peer_promotion_gate: dict[str, Any],
    refresh_control_tower: bool,
    artifact_paths: dict[str, Path],
    control_tower_result: dict[str, Any],
) -> dict[str, Any]:
    return {
        "reports_root": str(resolved_reports_root),
        "selected_ticker": focus_ticker,
        "selected_cycle_status": focus_entry.get("current_cycle_status"),
        "selected_contract_verdict": focus_entry.get("overall_contract_verdict"),
        "peer_focus_ticker": peer_expansion.get("focus_ticker"),
        "peer_focus_status": peer_expansion.get("focus_status"),
        "peer_proof_focus_ticker": peer_proof_board.get("focus_ticker"),
        "peer_proof_focus_verdict": peer_proof_board.get("focus_promotion_review_verdict"),
        "peer_promotion_gate_focus_ticker": peer_promotion_gate.get("focus_ticker"),
        "peer_promotion_gate_focus_verdict": peer_promotion_gate.get("focus_gate_verdict"),
        "peer_promotion_gate_default_expansion_status": peer_promotion_gate.get("default_expansion_status"),
        "priority_expansion_tickers": list(peer_expansion.get("priority_expansion_tickers") or []),
        "watch_with_risk_tickers": list(peer_expansion.get("watch_with_risk_tickers") or []),
        "ready_for_promotion_review_tickers": list(peer_proof_board.get("ready_for_promotion_review_tickers") or []),
        "promotion_gate_ready_tickers": list(peer_promotion_gate.get("ready_tickers") or []),
        "peer_promotion_gate_pending_t_plus_2_tickers": list(peer_promotion_gate.get("pending_t_plus_2_tickers") or []),
        "peer_promotion_gate_pending_next_day_tickers": list(peer_promotion_gate.get("pending_next_day_tickers") or []),
        "refresh_control_tower": refresh_control_tower,
        "artifact_paths": {
            "selected_outcome_refresh_json": str(artifact_paths["selected_output_json"]),
            "selected_outcome_refresh_markdown": str(artifact_paths["selected_output_md"]),
            "carryover_anchor_probe_json": str(artifact_paths["anchor_output_json"]),
            "carryover_anchor_probe_markdown": str(artifact_paths["anchor_output_md"]),
            "carryover_aligned_peer_harvest_json": str(artifact_paths["harvest_output_json"]),
            "carryover_aligned_peer_harvest_markdown": str(artifact_paths["harvest_output_md"]),
            "carryover_multiday_continuation_audit_json": str(artifact_paths["multiday_output_json"]),
            "carryover_multiday_continuation_audit_markdown": str(artifact_paths["multiday_output_md"]),
            "carryover_peer_expansion_json": str(artifact_paths["expansion_output_json"]),
            "carryover_peer_expansion_markdown": str(artifact_paths["expansion_output_md"]),
            "carryover_aligned_peer_proof_board_json": str(artifact_paths["proof_board_output_json"]),
            "carryover_aligned_peer_proof_board_markdown": str(artifact_paths["proof_board_output_md"]),
            "carryover_peer_promotion_gate_json": str(artifact_paths["promotion_gate_output_json"]),
            "carryover_peer_promotion_gate_markdown": str(artifact_paths["promotion_gate_output_md"]),
            "prepared_breakout_cohort_json": str(artifact_paths["prepared_breakout_output_json"]),
            "prepared_breakout_cohort_markdown": str(artifact_paths["prepared_breakout_output_md"]),
            "candidate_pool_recall_dossier_json": str(artifact_paths["candidate_pool_recall_output_json"]),
            "candidate_pool_recall_dossier_markdown": str(artifact_paths["candidate_pool_recall_output_md"]),
            "nightly_control_tower_json": control_tower_result.get("json_path"),
            "nightly_control_tower_markdown": control_tower_result.get("markdown_path"),
        },
        "recommendation": (
            f"已刷新 {focus_ticker} 的 selected contract 与 peer close-loop 队列；"
            f" 当前 peer focus={peer_expansion.get('focus_ticker')} ({peer_expansion.get('focus_status')})，"
             f" proof_focus={peer_proof_board.get('focus_ticker')} ({peer_proof_board.get('focus_promotion_review_verdict')})，"
             f" promotion_gate_focus={peer_promotion_gate.get('focus_ticker')} ({peer_promotion_gate.get('focus_gate_verdict')})，"
             f" default_expansion_status={peer_promotion_gate.get('default_expansion_status')}，"
             f" priority_expansion={peer_expansion.get('priority_expansion_tickers')}，"
             f" ready_for_promotion_review={peer_proof_board.get('ready_for_promotion_review_tickers')}，"
             f" promotion_gate_ready={peer_promotion_gate.get('ready_tickers')}，"
             f" pending_t_plus_2={peer_promotion_gate.get('pending_t_plus_2_tickers')}，"
             f" pending_next_day={peer_promotion_gate.get('pending_next_day_tickers')}，"
                f" watch_with_risk={peer_expansion.get('watch_with_risk_tickers')}。"
        ),
    }


def render_btst_carryover_close_loop_refresh_markdown(bundle: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# BTST Carryover Close-Loop Refresh")
    lines.append("")
    lines.append("## Overview")
    lines.append(f"- reports_root: {bundle.get('reports_root')}")
    lines.append(f"- selected_ticker: {bundle.get('selected_ticker')}")
    lines.append(f"- selected_cycle_status: {bundle.get('selected_cycle_status')}")
    lines.append(f"- selected_contract_verdict: {bundle.get('selected_contract_verdict')}")
    lines.append(f"- peer_focus_ticker: {bundle.get('peer_focus_ticker')}")
    lines.append(f"- peer_focus_status: {bundle.get('peer_focus_status')}")
    lines.append(f"- peer_proof_focus_ticker: {bundle.get('peer_proof_focus_ticker')}")
    lines.append(f"- peer_proof_focus_verdict: {bundle.get('peer_proof_focus_verdict')}")
    lines.append(f"- peer_promotion_gate_focus_ticker: {bundle.get('peer_promotion_gate_focus_ticker')}")
    lines.append(f"- peer_promotion_gate_focus_verdict: {bundle.get('peer_promotion_gate_focus_verdict')}")
    lines.append(f"- peer_promotion_gate_default_expansion_status: {bundle.get('peer_promotion_gate_default_expansion_status')}")
    lines.append(f"- priority_expansion_tickers: {bundle.get('priority_expansion_tickers')}")
    lines.append(f"- ready_for_promotion_review_tickers: {bundle.get('ready_for_promotion_review_tickers')}")
    lines.append(f"- promotion_gate_ready_tickers: {bundle.get('promotion_gate_ready_tickers')}")
    lines.append(f"- peer_promotion_gate_pending_t_plus_2_tickers: {bundle.get('peer_promotion_gate_pending_t_plus_2_tickers')}")
    lines.append(f"- peer_promotion_gate_pending_next_day_tickers: {bundle.get('peer_promotion_gate_pending_next_day_tickers')}")
    lines.append(f"- watch_with_risk_tickers: {bundle.get('watch_with_risk_tickers')}")
    lines.append(f"- refresh_control_tower: {bundle.get('refresh_control_tower')}")
    lines.append("")
    lines.append("## Artifact Paths")
    for label, artifact_path in dict(bundle.get("artifact_paths") or {}).items():
        lines.append(f"- {label}: {artifact_path}")
    lines.append("")
    lines.append("## Recommendation")
    lines.append(f"- {bundle.get('recommendation')}")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Refresh the full BTST carryover close-loop chain so selected contract and peer expansion surfaces move together.")
    parser.add_argument("--reports-root", default=str(REPORTS_DIR))
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--output-json", default=str(DEFAULT_BUNDLE_JSON))
    parser.add_argument("--output-md", default=str(DEFAULT_BUNDLE_MD))
    parser.add_argument("--skip-control-tower", action="store_true")
    args = parser.parse_args()

    bundle = refresh_btst_carryover_close_loop_bundle(
        args.reports_root,
        output_dir=args.output_dir,
        refresh_control_tower=not args.skip_control_tower,
    )
    output_json = Path(args.output_json).expanduser().resolve()
    output_md = Path(args.output_md).expanduser().resolve()
    _write_artifact(output_json, output_md, bundle, render_btst_carryover_close_loop_refresh_markdown(bundle))
    print(json.dumps(bundle, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
