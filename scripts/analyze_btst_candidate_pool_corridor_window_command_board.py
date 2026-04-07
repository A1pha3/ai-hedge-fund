from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

REPORTS_DIR = Path("data/reports")
DEFAULT_MANIFEST_PATH = REPORTS_DIR / "report_manifest_latest.json"
DEFAULT_PERSISTENCE_DOSSIER_PATH = REPORTS_DIR / "btst_candidate_pool_corridor_persistence_dossier_latest.json"
DEFAULT_OUTPUT_JSON = REPORTS_DIR / "btst_candidate_pool_corridor_window_command_board_latest.json"
DEFAULT_OUTPUT_MD = REPORTS_DIR / "btst_candidate_pool_corridor_window_command_board_latest.md"


def _load_json(path: str | Path) -> dict[str, Any]:
    resolved = Path(path).expanduser().resolve()
    return json.loads(resolved.read_text(encoding="utf-8"))


def _normalize_trade_date(value: Any) -> str:
    text = str(value or "").strip()
    digits = "".join(ch for ch in text if ch.isdigit())
    if len(digits) >= 8:
        return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}"
    return text


def analyze_btst_candidate_pool_corridor_window_command_board(
    manifest_path: str | Path = DEFAULT_MANIFEST_PATH,
    *,
    persistence_dossier_path: str | Path = DEFAULT_PERSISTENCE_DOSSIER_PATH,
) -> dict[str, Any]:
    manifest = _load_json(manifest_path)
    persistence = _load_json(persistence_dossier_path)
    continuation_summary = dict(manifest.get("continuation_promotion_ready_summary") or {})
    focus_ticker = str(
        persistence.get("focus_ticker")
        or continuation_summary.get("focus_ticker")
        or ""
    ).strip()
    if not focus_ticker:
        raise ValueError("No focus_ticker found for corridor window command board.")
    candidate_dossier = _load_json(REPORTS_DIR / f"btst_tplus2_candidate_dossier_{focus_ticker}_latest.json")

    confirmed_selected_trade_dates = list(continuation_summary.get("combined_merge_ready_evidence_trade_dates") or [])
    exploratory_trade_dates = list(continuation_summary.get("combined_evidence_trade_dates") or [])
    current_plan_visible_trade_dates = list(continuation_summary.get("candidate_dossier_current_plan_visible_trade_dates") or [])
    visibility_gap_trade_dates = list(continuation_summary.get("candidate_dossier_current_plan_visibility_gap_trade_dates") or [])

    action_rows: list[dict[str, Any]] = []
    for window in list(candidate_dossier.get("recent_window_summaries") or []):
        row = dict(window or {})
        trade_date = _normalize_trade_date(row.get("report_label"))
        if trade_date in confirmed_selected_trade_dates:
            continue
        decision = str(row.get("decision") or "").strip()
        if decision == "near_miss":
            action_tier = "upgrade_near_miss_window"
        elif trade_date in visibility_gap_trade_dates:
            action_tier = "recover_visibility_gap_window"
        else:
            action_tier = "review_support_window"
        action_rows.append(
            {
                "trade_date": trade_date or None,
                "decision": decision or None,
                "candidate_source": row.get("candidate_source"),
                "score_target": row.get("score_target"),
                "report_dir": row.get("report_dir"),
                "downstream_bottleneck": row.get("downstream_bottleneck"),
                "action_tier": action_tier,
            }
        )
    for trade_date in visibility_gap_trade_dates:
        if any(str(row.get("trade_date") or "") == trade_date for row in action_rows):
            continue
        action_rows.append(
            {
                "trade_date": trade_date,
                "decision": None,
                "candidate_source": None,
                "score_target": None,
                "report_dir": None,
                "downstream_bottleneck": "current_plan_visibility_gap",
                "action_tier": "recover_visibility_gap_window",
            }
        )

    tier_rank = {
        "upgrade_near_miss_window": 0,
        "recover_visibility_gap_window": 1,
        "review_support_window": 2,
    }
    action_rows.sort(key=lambda row: (tier_rank.get(str(row.get("action_tier") or ""), 9), str(row.get("trade_date") or "")))
    next_target_trade_dates = [str(row.get("trade_date") or "") for row in action_rows if str(row.get("trade_date") or "")][:3]

    recommendation = (
        f"Prioritize the next independent selected window for {focus_ticker}. "
        f"Confirmed selected dates={confirmed_selected_trade_dates}; next targets={next_target_trade_dates}."
    )

    return {
        "focus_ticker": focus_ticker,
        "verdict": "collect_one_more_selected_window",
        "confirmed_selected_trade_dates": confirmed_selected_trade_dates,
        "exploratory_trade_dates": exploratory_trade_dates,
        "current_plan_visible_trade_dates": current_plan_visible_trade_dates,
        "visibility_gap_trade_dates": visibility_gap_trade_dates,
        "missing_independent_sample_count": dict(persistence.get("continuation_readiness") or {}).get("missing_independent_sample_count"),
        "next_target_trade_dates": next_target_trade_dates,
        "action_rows": action_rows[:6],
        "recommendation": recommendation,
        "source_reports": {
            "manifest": str(Path(manifest_path).expanduser().resolve()),
            "persistence_dossier": str(Path(persistence_dossier_path).expanduser().resolve()),
            "candidate_dossier": str((REPORTS_DIR / f"btst_tplus2_candidate_dossier_{focus_ticker}_latest.json").expanduser().resolve()),
        },
    }


def render_btst_candidate_pool_corridor_window_command_board_markdown(analysis: dict[str, Any]) -> str:
    lines = [
        "# BTST Candidate Pool Corridor Window Command Board",
        "",
        "## Overview",
        f"- focus_ticker: {analysis.get('focus_ticker')}",
        f"- verdict: {analysis.get('verdict')}",
        f"- confirmed_selected_trade_dates: {analysis.get('confirmed_selected_trade_dates')}",
        f"- exploratory_trade_dates: {analysis.get('exploratory_trade_dates')}",
        f"- current_plan_visible_trade_dates: {analysis.get('current_plan_visible_trade_dates')}",
        f"- visibility_gap_trade_dates: {analysis.get('visibility_gap_trade_dates')}",
        f"- missing_independent_sample_count: {analysis.get('missing_independent_sample_count')}",
        f"- next_target_trade_dates: {analysis.get('next_target_trade_dates')}",
        "",
        "## Action Rows",
        f"- action_rows: {analysis.get('action_rows')}",
        "",
        "## Recommendation",
        f"- {analysis.get('recommendation')}",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="List the next exact windows to pursue for the corridor leader's second independent selected sample.")
    parser.add_argument("--manifest-path", default=str(DEFAULT_MANIFEST_PATH))
    parser.add_argument("--persistence-dossier-path", default=str(DEFAULT_PERSISTENCE_DOSSIER_PATH))
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--output-md", default=str(DEFAULT_OUTPUT_MD))
    args = parser.parse_args()

    analysis = analyze_btst_candidate_pool_corridor_window_command_board(
        manifest_path=args.manifest_path,
        persistence_dossier_path=args.persistence_dossier_path,
    )
    output_json = Path(args.output_json).expanduser().resolve()
    output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_md = Path(args.output_md).expanduser().resolve()
    output_md.write_text(render_btst_candidate_pool_corridor_window_command_board_markdown(analysis), encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
