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
from src.screening.candidate_pool import (
    SHADOW_LIQUIDITY_CORRIDOR_FOCUS_LOW_GATE_MAX_CUTOFF_SHARE,
    SHADOW_LIQUIDITY_CORRIDOR_FOCUS_MIN_GATE_SHARE,
    SHADOW_LIQUIDITY_CORRIDOR_MIN_GATE_SHARE,
)

REPORTS_DIR = Path("data/reports")
DEFAULT_CANDIDATE_POOL_RECALL_DOSSIER_PATH = REPORTS_DIR / "btst_candidate_pool_recall_dossier_latest.json"
DEFAULT_OUTPUT_JSON = REPORTS_DIR / "btst_candidate_pool_corridor_narrow_probe_latest.json"
DEFAULT_OUTPUT_MD = REPORTS_DIR / "btst_candidate_pool_corridor_narrow_probe_latest.md"


def _load_optional_json(path: str | Path) -> dict[str, Any] | None:
    resolved = Path(path).expanduser().resolve()
    if not resolved.exists():
        return None
    return json.loads(resolved.read_text(encoding="utf-8"))


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _analyze_deepest_corridor_split(candidate_pool_recall_dossier: dict[str, Any], recall_dossier_path: str | Path) -> dict[str, Any] | None:
    corridor_rows: list[dict[str, Any]] = []
    for dossier in list(candidate_pool_recall_dossier.get("priority_ticker_dossiers") or []):
        normalized = dict(dossier or {})
        ticker = str(normalized.get("ticker") or "").strip()
        profile = dict(normalized.get("truncation_liquidity_profile") or {})
        if str(profile.get("priority_handoff") or "").strip() != "layer_a_liquidity_corridor":
            continue
        cutoff_share = _safe_float(profile.get("avg_amount_share_of_cutoff_mean"))
        min_gate_share = _safe_float(profile.get("avg_amount_share_of_min_gate_mean"))
        low_gate_focus = (
            min_gate_share is not None
            and SHADOW_LIQUIDITY_CORRIDOR_FOCUS_MIN_GATE_SHARE <= min_gate_share < SHADOW_LIQUIDITY_CORRIDOR_MIN_GATE_SHARE
        )
        keep_for_deepest_probe = low_gate_focus and cutoff_share is not None and cutoff_share <= SHADOW_LIQUIDITY_CORRIDOR_FOCUS_LOW_GATE_MAX_CUTOFF_SHARE
        corridor_rows.append(
            {
                "ticker": ticker,
                "avg_amount_share_of_cutoff_mean": cutoff_share,
                "avg_amount_share_of_min_gate_mean": min_gate_share,
                "keep_for_deepest_probe": keep_for_deepest_probe,
                "is_low_gate_focus": low_gate_focus,
            }
        )
    if not corridor_rows:
        return None

    ranked_rows = sorted(
        corridor_rows,
        key=lambda row: (
            0 if row.get("keep_for_deepest_probe") else 1,
            float(row.get("avg_amount_share_of_cutoff_mean") or 999.0),
            str(row.get("ticker") or ""),
        ),
    )
    retained_rows = [row for row in ranked_rows if row.get("keep_for_deepest_probe")]
    low_gate_excluded_rows = [row for row in ranked_rows if row.get("is_low_gate_focus") and not row.get("keep_for_deepest_probe")]
    standard_corridor_rows = [row for row in ranked_rows if not row.get("is_low_gate_focus")]
    verdict = "deepest_corridor_split_ready" if retained_rows else "no_retainable_deepest_corridor_focus"
    recommendation = (
        f"Keep only the deepest low-gate corridor names whose avg_amount/cutoff stays at or below "
        f"{SHADOW_LIQUIDITY_CORRIDOR_FOCUS_LOW_GATE_MAX_CUTOFF_SHARE}; route thicker low-gate tails back to "
        "upstream base-liquidity uplift instead of keeping them in the same shadow probe."
    )
    if low_gate_excluded_rows:
        recommendation += f" Current excluded low-gate tail: {[row['ticker'] for row in low_gate_excluded_rows]}."
    if standard_corridor_rows:
        recommendation += f" Standard corridor names {[row['ticker'] for row in standard_corridor_rows]} stay on the broader uplift lane."

    return {
        "focus_ticker": str((retained_rows or ranked_rows)[0].get("ticker") or ""),
        "verdict": verdict,
        "deepest_corridor_focus_tickers": [str(row.get("ticker") or "") for row in retained_rows],
        "excluded_low_gate_tail_tickers": [str(row.get("ticker") or "") for row in low_gate_excluded_rows],
        "standard_corridor_tickers": [str(row.get("ticker") or "") for row in standard_corridor_rows],
        "focus_min_gate_share": SHADOW_LIQUIDITY_CORRIDOR_FOCUS_MIN_GATE_SHARE,
        "standard_min_gate_share": SHADOW_LIQUIDITY_CORRIDOR_MIN_GATE_SHARE,
        "low_gate_focus_max_cutoff_share": SHADOW_LIQUIDITY_CORRIDOR_FOCUS_LOW_GATE_MAX_CUTOFF_SHARE,
        "retained_deepest_count": len(retained_rows),
        "low_gate_excluded_count": len(low_gate_excluded_rows),
        "threshold_override_gap_vs_anchor": None,
        "target_gap_to_selected": None,
        "recommendation": recommendation,
        "source_reports": {
            "candidate_pool_recall_dossier": str(Path(recall_dossier_path).expanduser().resolve()),
        },
    }


def analyze_btst_candidate_pool_corridor_narrow_probe(
    *,
    candidate_pool_recall_dossier_path: str | Path = DEFAULT_CANDIDATE_POOL_RECALL_DOSSIER_PATH,
    candidate_dossier_path: str | Path = DEFAULT_CANDIDATE_DOSSIER_PATH,
    command_board_path: str | Path = DEFAULT_COMMAND_BOARD_PATH,
) -> dict[str, Any]:
    legacy_mode_requested = (
        Path(candidate_dossier_path).expanduser().resolve() != DEFAULT_CANDIDATE_DOSSIER_PATH.expanduser().resolve()
        or Path(command_board_path).expanduser().resolve() != DEFAULT_COMMAND_BOARD_PATH.expanduser().resolve()
    )
    if not legacy_mode_requested:
        recall_dossier = _load_optional_json(candidate_pool_recall_dossier_path)
        if recall_dossier:
            deepest_corridor_analysis = _analyze_deepest_corridor_split(recall_dossier, candidate_pool_recall_dossier_path)
            if deepest_corridor_analysis:
                return deepest_corridor_analysis

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
        f"- deepest_corridor_focus_tickers: {analysis.get('deepest_corridor_focus_tickers')}",
        f"- excluded_low_gate_tail_tickers: {analysis.get('excluded_low_gate_tail_tickers')}",
        f"- standard_corridor_tickers: {analysis.get('standard_corridor_tickers')}",
        f"- low_gate_focus_max_cutoff_share: {analysis.get('low_gate_focus_max_cutoff_share')}",
        f"- verdict: {analysis.get('verdict')}",
        f"- recommendation: {analysis.get('recommendation')}",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Isolate the deepest BTST liquidity corridor focus subset before keeping any corridor shadow probe.")
    parser.add_argument("--candidate-pool-recall-dossier-path", default=str(DEFAULT_CANDIDATE_POOL_RECALL_DOSSIER_PATH))
    parser.add_argument("--candidate-dossier-path", default=str(DEFAULT_CANDIDATE_DOSSIER_PATH))
    parser.add_argument("--command-board-path", default=str(DEFAULT_COMMAND_BOARD_PATH))
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--output-md", default=str(DEFAULT_OUTPUT_MD))
    args = parser.parse_args()

    analysis = analyze_btst_candidate_pool_corridor_narrow_probe(
        candidate_pool_recall_dossier_path=args.candidate_pool_recall_dossier_path,
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
