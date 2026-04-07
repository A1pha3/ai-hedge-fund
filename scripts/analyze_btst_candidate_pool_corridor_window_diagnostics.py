from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

REPORTS_DIR = Path("data/reports")
DEFAULT_CANDIDATE_DOSSIER_PATH = REPORTS_DIR / "btst_tplus2_candidate_dossier_300720_latest.json"
DEFAULT_COMMAND_BOARD_PATH = REPORTS_DIR / "btst_candidate_pool_corridor_window_command_board_latest.json"
DEFAULT_OUTPUT_JSON = REPORTS_DIR / "btst_candidate_pool_corridor_window_diagnostics_latest.json"
DEFAULT_OUTPUT_MD = REPORTS_DIR / "btst_candidate_pool_corridor_window_diagnostics_latest.md"


def _load_json(path: str | Path) -> dict[str, Any]:
    resolved = Path(path).expanduser().resolve()
    return json.loads(resolved.read_text(encoding="utf-8"))


def _normalize_trade_date(value: Any) -> str:
    text = str(value or "").strip()
    digits = "".join(ch for ch in text if ch.isdigit())
    if len(digits) >= 8:
        return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}"
    return text


def _load_short_trade_target(report_dir: str | Path, trade_date: str, ticker: str) -> dict[str, Any]:
    artifact_path = Path(report_dir).expanduser().resolve() / "selection_artifacts" / trade_date / "selection_target_replay_input.json"
    payload = _load_json(artifact_path)
    return dict(dict(payload.get("selection_targets") or {}).get(ticker) or {}).get("short_trade") or {}


def _choose_anchor_window(candidate_dossier: dict[str, Any], trade_date: str) -> dict[str, Any]:
    per_window_summaries = [dict(row or {}) for row in list(candidate_dossier.get("per_window_summaries") or [])]
    same_trade_date_rows = [row for row in per_window_summaries if _normalize_trade_date(row.get("report_label")) == trade_date]
    if same_trade_date_rows:
        selected_rows = [row for row in same_trade_date_rows if str(row.get("decision") or "").strip() == "selected"]
        ranked_rows = selected_rows or same_trade_date_rows
        return max(
            ranked_rows,
            key=lambda row: (
                1 if str(row.get("decision") or "").strip() == "selected" else 0,
                float(row.get("score_target") or -999.0),
                str(row.get("report_dir") or ""),
            ),
        )
    recent_windows = {
        _normalize_trade_date(row.get("report_label")): dict(row or {})
        for row in list(candidate_dossier.get("recent_window_summaries") or [])
        if _normalize_trade_date(row.get("report_label"))
    }
    return dict(recent_windows.get(trade_date) or {})


def _extract_metric_subset(row: dict[str, Any]) -> dict[str, Any]:
    metrics = dict(row.get("metrics_payload") or {})
    thresholds = dict(metrics.get("thresholds") or {})
    return {
        "breakout_stage": metrics.get("breakout_stage"),
        "breakout_freshness": metrics.get("breakout_freshness"),
        "trend_acceleration": metrics.get("trend_acceleration"),
        "volume_expansion_quality": metrics.get("volume_expansion_quality"),
        "close_strength": metrics.get("close_strength"),
        "sector_resonance": metrics.get("sector_resonance"),
        "catalyst_freshness": metrics.get("catalyst_freshness"),
        "effective_catalyst_freshness": metrics.get("effective_catalyst_freshness"),
        "upstream_shadow_catalyst_relief_applied": metrics.get("upstream_shadow_catalyst_relief_applied"),
        "selected_breakout_gate_pass": metrics.get("selected_breakout_gate_pass"),
        "near_miss_breakout_gate_pass": metrics.get("near_miss_breakout_gate_pass"),
        "effective_select_threshold": thresholds.get("effective_select_threshold"),
        "base_select_threshold": thresholds.get("select_threshold"),
        "effective_near_miss_threshold": thresholds.get("near_miss_threshold"),
    }


def _delta(left: float | None, right: float | None) -> float | None:
    if left is None or right is None:
        return None
    return round(float(left) - float(right), 4)


def _scan_visibility_gap_report_dir(report_dir: str | Path, ticker: str) -> dict[str, Any]:
    resolved = Path(report_dir).expanduser().resolve()
    day_payload = json.loads((resolved / "daily_events.jsonl").read_text(encoding="utf-8").splitlines()[0])
    current_plan = dict(day_payload.get("current_plan") or {})
    semantic_sections = (
        "selection_targets",
        "watchlist",
        "buy_orders",
        "pending_buy_queue",
        "candidate_pool_shadow_candidates",
        "upstream_shadow_observations",
        "upstream_shadow_released",
        "watchlist_shadow_released",
        "decisions",
    )
    current_plan_paths: list[str] = []
    for section_name in semantic_sections:
        section_value = current_plan.get(section_name)
        if ticker in json.dumps(section_value, ensure_ascii=False):
            current_plan_paths.append(section_name)

    replay_input_hits: list[str] = []
    for file_path in resolved.glob("selection_artifacts/**/selection_target_replay_input.json"):
        if ticker in file_path.read_text(encoding="utf-8"):
            replay_input_hits.append(str(file_path))

    snapshot_hits: list[str] = []
    for file_path in resolved.glob("selection_artifacts/**/selection_snapshot.json"):
        if ticker in file_path.read_text(encoding="utf-8"):
            snapshot_hits.append(str(file_path))

    return {
        "report_dir": str(resolved),
        "semantic_current_plan_has_ticker": bool(current_plan_paths),
        "semantic_current_plan_paths": current_plan_paths,
        "replay_input_has_ticker": bool(replay_input_hits),
        "replay_input_paths": replay_input_hits[:2],
        "selection_snapshot_has_ticker": bool(snapshot_hits),
        "selection_snapshot_paths": snapshot_hits[:2],
    }


def analyze_btst_candidate_pool_corridor_window_diagnostics(
    *,
    candidate_dossier_path: str | Path = DEFAULT_CANDIDATE_DOSSIER_PATH,
    command_board_path: str | Path = DEFAULT_COMMAND_BOARD_PATH,
) -> dict[str, Any]:
    candidate_dossier = _load_json(candidate_dossier_path)
    command_board = _load_json(command_board_path)
    focus_ticker = str(command_board.get("focus_ticker") or candidate_dossier.get("candidate_ticker") or "").strip()
    if not focus_ticker:
        raise ValueError("No focus_ticker found for corridor window diagnostics.")

    selected_trade_date = str(list(command_board.get("confirmed_selected_trade_dates") or [None])[0] or "")
    near_miss_trade_date = str(list(command_board.get("next_target_trade_dates") or [None])[0] or "")

    selected_window = _choose_anchor_window(candidate_dossier, selected_trade_date)
    near_miss_window = _choose_anchor_window(candidate_dossier, near_miss_trade_date)
    selected_target = _load_short_trade_target(selected_window.get("report_dir"), selected_trade_date, focus_ticker) if selected_window else {}
    near_miss_target = _load_short_trade_target(near_miss_window.get("report_dir"), near_miss_trade_date, focus_ticker) if near_miss_window else {}
    selected_metrics = _extract_metric_subset(selected_target)
    near_miss_metrics = _extract_metric_subset(near_miss_target)

    near_miss_delta_vs_selected = {
        "score_target_delta": _delta(near_miss_target.get("score_target"), selected_target.get("score_target")),
        "trend_acceleration_delta": _delta(near_miss_metrics.get("trend_acceleration"), selected_metrics.get("trend_acceleration")),
        "close_strength_delta": _delta(near_miss_metrics.get("close_strength"), selected_metrics.get("close_strength")),
        "volume_expansion_quality_delta": _delta(near_miss_metrics.get("volume_expansion_quality"), selected_metrics.get("volume_expansion_quality")),
        "effective_select_threshold_delta": _delta(near_miss_metrics.get("effective_select_threshold"), selected_metrics.get("effective_select_threshold")),
        "same_breakout_stage": near_miss_metrics.get("breakout_stage") == selected_metrics.get("breakout_stage"),
        "same_upstream_shadow_catalyst_relief_state": near_miss_metrics.get("upstream_shadow_catalyst_relief_applied")
        == selected_metrics.get("upstream_shadow_catalyst_relief_applied"),
    }

    if (
        near_miss_delta_vs_selected.get("score_target_delta") is not None
        and abs(float(near_miss_delta_vs_selected["score_target_delta"])) <= 0.01
        and near_miss_delta_vs_selected.get("same_breakout_stage")
        and near_miss_delta_vs_selected.get("same_upstream_shadow_catalyst_relief_state")
    ):
        near_miss_verdict = "narrow_selected_gap_candidate"
    else:
        near_miss_verdict = "broad_gap_candidate"

    visibility_gap_trade_dates = list(command_board.get("visibility_gap_trade_dates") or [])
    visibility_gap_report_dirs = list(dict(candidate_dossier.get("current_plan_visibility_summary") or {}).get("current_plan_visibility_gap_report_dirs") or [])
    visibility_gap_scan_rows = [_scan_visibility_gap_report_dir(report_dir, focus_ticker) for report_dir in visibility_gap_report_dirs]
    recoverable_count = sum(
        1
        for row in visibility_gap_scan_rows
        if (not row.get("semantic_current_plan_has_ticker")) and row.get("replay_input_has_ticker") and row.get("selection_snapshot_has_ticker")
    )
    visibility_gap_verdict = (
        "recoverable_current_plan_visibility_gap"
        if recoverable_count > 0
        else "non_actionable_visibility_gap"
    )

    recommendation = (
        f"Prioritize {near_miss_trade_date} as a narrow upgrade probe for {focus_ticker}; "
        f"use {visibility_gap_trade_dates[:1]} as a visibility-audit lane, not as a global uplift trigger."
    )

    return {
        "focus_ticker": focus_ticker,
        "selected_anchor_window": {
            "trade_date": selected_trade_date or None,
            "report_dir": selected_window.get("report_dir"),
            "decision": selected_target.get("decision"),
            "score_target": selected_target.get("score_target"),
            "candidate_source": selected_window.get("candidate_source") or selected_target.get("candidate_source"),
            "downstream_bottleneck": selected_window.get("downstream_bottleneck"),
            "metrics": selected_metrics,
        },
        "near_miss_upgrade_window": {
            "trade_date": near_miss_trade_date or None,
            "report_dir": near_miss_window.get("report_dir"),
            "decision": near_miss_target.get("decision"),
            "score_target": near_miss_target.get("score_target"),
            "candidate_source": near_miss_window.get("candidate_source") or near_miss_target.get("candidate_source"),
            "downstream_bottleneck": near_miss_window.get("downstream_bottleneck"),
            "metrics": near_miss_metrics,
            "verdict": near_miss_verdict,
            "delta_vs_selected": near_miss_delta_vs_selected,
        },
        "visibility_gap_window": {
            "trade_dates": visibility_gap_trade_dates,
            "report_dir_count": len(visibility_gap_report_dirs),
            "recoverable_report_dir_count": recoverable_count,
            "verdict": visibility_gap_verdict,
            "scan_rows": visibility_gap_scan_rows[:5],
        },
        "recommendation": recommendation,
        "source_reports": {
            "candidate_dossier": str(Path(candidate_dossier_path).expanduser().resolve()),
            "command_board": str(Path(command_board_path).expanduser().resolve()),
        },
    }


def render_btst_candidate_pool_corridor_window_diagnostics_markdown(analysis: dict[str, Any]) -> str:
    lines = [
        "# BTST Candidate Pool Corridor Window Diagnostics",
        "",
        "## Focus",
        f"- focus_ticker: {analysis.get('focus_ticker')}",
        "",
        "## Selected Anchor Window",
        f"- selected_anchor_window: {analysis.get('selected_anchor_window')}",
        "",
        "## Near-Miss Upgrade Window",
        f"- near_miss_upgrade_window: {analysis.get('near_miss_upgrade_window')}",
        "",
        "## Visibility Gap Window",
        f"- visibility_gap_window: {analysis.get('visibility_gap_window')}",
        "",
        "## Recommendation",
        f"- {analysis.get('recommendation')}",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Diagnose the next two corridor windows for the 300720 selected-persistence lane.")
    parser.add_argument("--candidate-dossier-path", default=str(DEFAULT_CANDIDATE_DOSSIER_PATH))
    parser.add_argument("--command-board-path", default=str(DEFAULT_COMMAND_BOARD_PATH))
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--output-md", default=str(DEFAULT_OUTPUT_MD))
    args = parser.parse_args()

    analysis = analyze_btst_candidate_pool_corridor_window_diagnostics(
        candidate_dossier_path=args.candidate_dossier_path,
        command_board_path=args.command_board_path,
    )
    output_json = Path(args.output_json).expanduser().resolve()
    output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_md = Path(args.output_md).expanduser().resolve()
    output_md.write_text(render_btst_candidate_pool_corridor_window_diagnostics_markdown(analysis), encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
