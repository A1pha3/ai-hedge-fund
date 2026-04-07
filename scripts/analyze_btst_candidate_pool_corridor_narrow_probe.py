from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from scripts.analyze_btst_candidate_pool_corridor_window_diagnostics import (
    DEFAULT_CANDIDATE_DOSSIER_PATH,
    DEFAULT_COMMAND_BOARD_PATH,
    analyze_btst_candidate_pool_corridor_window_diagnostics,
)

REPORTS_DIR = Path("data/reports")
DEFAULT_OUTPUT_JSON = REPORTS_DIR / "btst_candidate_pool_corridor_narrow_probe_latest.json"
DEFAULT_OUTPUT_MD = REPORTS_DIR / "btst_candidate_pool_corridor_narrow_probe_latest.md"


def analyze_btst_candidate_pool_corridor_narrow_probe(
    *,
    candidate_dossier_path: str | Path = DEFAULT_CANDIDATE_DOSSIER_PATH,
    command_board_path: str | Path = DEFAULT_COMMAND_BOARD_PATH,
) -> dict[str, Any]:
    diagnostics = analyze_btst_candidate_pool_corridor_window_diagnostics(
        candidate_dossier_path=candidate_dossier_path,
        command_board_path=command_board_path,
    )
    selected_anchor = dict(diagnostics.get("selected_anchor_window") or {})
    near_miss_window = dict(diagnostics.get("near_miss_upgrade_window") or {})
    selected_metrics = dict(selected_anchor.get("metrics") or {})
    near_miss_metrics = dict(near_miss_window.get("metrics") or {})
    selected_score = float(selected_anchor.get("score_target") or 0.0)
    near_miss_score = float(near_miss_window.get("score_target") or 0.0)
    selected_threshold = float(selected_metrics.get("effective_select_threshold") or 0.0)
    near_miss_threshold = float(near_miss_metrics.get("effective_select_threshold") or 0.0)
    threshold_override_gap = round(near_miss_threshold - selected_threshold, 4)
    threshold_gap_to_selected = round(max(near_miss_threshold - near_miss_score, 0.0), 4)
    anchor_threshold_gap = round(max(selected_threshold - selected_score, 0.0), 4)

    if threshold_override_gap > 0 and threshold_gap_to_selected > 0:
        verdict = "lane_specific_select_threshold_override_gap"
    else:
        verdict = "score_weight_gap_requires_deeper_probe"

    recommendation = (
        "Prioritize lane-specific override parity inspection before adding any new score uplift; "
        "2026-04-06 already matches the anchor on breakout stage and relief state."
    )
    return {
        "focus_ticker": diagnostics.get("focus_ticker"),
        "anchor_trade_date": selected_anchor.get("trade_date"),
        "target_trade_date": near_miss_window.get("trade_date"),
        "anchor_decision": selected_anchor.get("decision"),
        "target_decision": near_miss_window.get("decision"),
        "anchor_score_target": selected_anchor.get("score_target"),
        "target_score_target": near_miss_window.get("score_target"),
        "score_target_delta_vs_anchor": round(near_miss_score - selected_score, 4),
        "anchor_effective_select_threshold": selected_metrics.get("effective_select_threshold"),
        "target_effective_select_threshold": near_miss_metrics.get("effective_select_threshold"),
        "threshold_override_gap_vs_anchor": threshold_override_gap,
        "target_gap_to_selected": threshold_gap_to_selected,
        "anchor_gap_to_selected": anchor_threshold_gap,
        "same_breakout_stage": near_miss_metrics.get("breakout_stage") == selected_metrics.get("breakout_stage"),
        "same_upstream_shadow_catalyst_relief_state": near_miss_metrics.get("upstream_shadow_catalyst_relief_applied")
        == selected_metrics.get("upstream_shadow_catalyst_relief_applied"),
        "verdict": verdict,
        "recommendation": recommendation,
        "source_reports": dict(diagnostics.get("source_reports") or {}),
    }


def render_btst_candidate_pool_corridor_narrow_probe_markdown(analysis: dict[str, Any]) -> str:
    lines = [
        "# BTST Candidate Pool Corridor Narrow Probe",
        "",
        f"- focus_ticker: {analysis.get('focus_ticker')}",
        f"- anchor_trade_date: {analysis.get('anchor_trade_date')}",
        f"- target_trade_date: {analysis.get('target_trade_date')}",
        f"- anchor_decision: {analysis.get('anchor_decision')}",
        f"- target_decision: {analysis.get('target_decision')}",
        f"- anchor_effective_select_threshold: {analysis.get('anchor_effective_select_threshold')}",
        f"- target_effective_select_threshold: {analysis.get('target_effective_select_threshold')}",
        f"- threshold_override_gap_vs_anchor: {analysis.get('threshold_override_gap_vs_anchor')}",
        f"- target_gap_to_selected: {analysis.get('target_gap_to_selected')}",
        f"- verdict: {analysis.get('verdict')}",
        f"- recommendation: {analysis.get('recommendation')}",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Quantify the smallest lane-specific gap between the 300720 selected anchor and near-miss target window.")
    parser.add_argument("--candidate-dossier-path", default=str(DEFAULT_CANDIDATE_DOSSIER_PATH))
    parser.add_argument("--command-board-path", default=str(DEFAULT_COMMAND_BOARD_PATH))
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--output-md", default=str(DEFAULT_OUTPUT_MD))
    args = parser.parse_args()

    analysis = analyze_btst_candidate_pool_corridor_narrow_probe(
        candidate_dossier_path=args.candidate_dossier_path,
        command_board_path=args.command_board_path,
    )
    output_json = Path(args.output_json).expanduser().resolve()
    output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_md = Path(args.output_md).expanduser().resolve()
    output_md.write_text(render_btst_candidate_pool_corridor_narrow_probe_markdown(analysis), encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
