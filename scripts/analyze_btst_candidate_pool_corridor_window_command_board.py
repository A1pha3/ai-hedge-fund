from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from scripts.analyze_short_trade_ticker_role_history import (
    analyze_short_trade_ticker_role_history,
)
from scripts.btst_report_utils import discover_nested_report_dirs

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


def _load_broad_scope_shadow_fallback(reports_root: Path, focus_ticker: str) -> dict[str, Any]:
    report_dirs = discover_nested_report_dirs([reports_root], report_name_contains="paper_trading")
    role_history = analyze_short_trade_ticker_role_history(report_dirs, tickers=[focus_ticker])
    ticker_summary = dict(list(role_history.get("ticker_summaries") or [{}])[0] or {})
    observations = [dict(row or {}) for row in list(ticker_summary.get("observations") or [])]
    shadow_rows = [
        row
        for row in observations
        if "_shadow_" in str(row.get("role") or "") and str(row.get("role") or "").endswith(("_selected", "_near_miss"))
    ]
    best_rows_by_trade_date: dict[str, dict[str, Any]] = {}
    for row in shadow_rows:
        trade_date = _normalize_trade_date(row.get("trade_date"))
        if not trade_date:
            continue
        previous = best_rows_by_trade_date.get(trade_date)
        candidate = {
            "trade_date": trade_date,
            "decision": row.get("target_decision"),
            "candidate_source": row.get("candidate_source"),
            "score_target": row.get("score_target"),
            "report_dir": row.get("report_dir"),
            "report_label": row.get("report_label"),
            "downstream_bottleneck": "broad_scope_shadow_role_history",
            "action_tier": "upgrade_near_miss_window" if str(row.get("target_decision") or "") == "near_miss" else "review_support_window",
        }
        if previous is None or (
            (1 if str(candidate.get("decision") or "") == "selected" else 0),
            float(candidate.get("score_target") or -999.0),
            str(candidate.get("report_dir") or ""),
        ) > (
            (1 if str(previous.get("decision") or "") == "selected" else 0),
            float(previous.get("score_target") or -999.0),
            str(previous.get("report_dir") or ""),
        ):
            best_rows_by_trade_date[trade_date] = candidate

    action_rows = [best_rows_by_trade_date[key] for key in sorted(best_rows_by_trade_date)]
    confirmed_selected_trade_dates = [
        str(row.get("trade_date") or "")
        for row in action_rows
        if str(row.get("trade_date") or "") and str(row.get("decision") or "") == "selected"
    ]
    exploratory_trade_dates = [str(row.get("trade_date") or "") for row in action_rows if str(row.get("trade_date") or "")]
    return {
        "confirmed_selected_trade_dates": confirmed_selected_trade_dates,
        "exploratory_trade_dates": exploratory_trade_dates,
        "action_rows": action_rows,
        "broad_scope_distinct_window_count": len({str(row.get("report_label") or "") for row in shadow_rows if row.get("report_label")}),
    }


def _dedupe_trade_dates(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        normalized = str(value or "").strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        ordered.append(normalized)
    return ordered


def _should_apply_broad_scope_fallback(
    *,
    candidate_dossier: dict[str, Any],
    confirmed_selected_trade_dates: list[str],
    exploratory_trade_dates: list[str],
    action_rows: list[dict[str, Any]],
) -> bool:
    if not candidate_dossier:
        return False
    if confirmed_selected_trade_dates or exploratory_trade_dates:
        return False
    if not action_rows:
        return True
    return all(
        not str(row.get("report_dir") or "").strip() and not str(row.get("decision") or "").strip()
        for row in action_rows
    )


def _merge_action_rows(
    existing_rows: list[dict[str, Any]],
    fallback_rows: list[dict[str, Any]],
    *,
    tier_rank: dict[str, int],
) -> list[dict[str, Any]]:
    merged_by_trade_date: dict[str, dict[str, Any]] = {}

    def _row_rank(row: dict[str, Any]) -> tuple[int, int, int, float]:
        return (
            -tier_rank.get(str(row.get("action_tier") or ""), 9),
            1 if str(row.get("report_dir") or "").strip() else 0,
            1 if str(row.get("decision") or "") == "selected" else 0,
            float(row.get("score_target") or -999.0),
        )

    for row in [dict(item or {}) for item in [*existing_rows, *fallback_rows]]:
        trade_date = str(row.get("trade_date") or "").strip()
        if not trade_date:
            continue
        previous = merged_by_trade_date.get(trade_date)
        if previous is None or _row_rank(row) > _row_rank(previous):
            merged_by_trade_date[trade_date] = row

    return list(merged_by_trade_date.values())


def _action_sort_key(row: dict[str, Any], tier_rank: dict[str, int]) -> tuple[int, float, str]:
    action_tier = str(row.get("action_tier") or "")
    if action_tier == "upgrade_near_miss_window":
        return (
            tier_rank.get(action_tier, 9),
            -float(row.get("score_target") or -999.0),
            str(row.get("trade_date") or ""),
        )
    return (
        tier_rank.get(action_tier, 9),
        0.0,
        str(row.get("trade_date") or ""),
    )


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
    reports_root = Path(manifest_path).expanduser().resolve().parent
    candidate_dossier_path = (reports_root / f"btst_tplus2_candidate_dossier_{focus_ticker}_latest.json").expanduser().resolve()
    candidate_dossier = _load_json(candidate_dossier_path) if candidate_dossier_path.exists() else {}
    summary_focus_ticker = str(continuation_summary.get("focus_ticker") or "").strip()

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
    broad_scope_fallback = {}
    if not candidate_dossier and summary_focus_ticker != focus_ticker:
        broad_scope_fallback = _load_broad_scope_shadow_fallback(reports_root, focus_ticker)
        confirmed_selected_trade_dates = list(broad_scope_fallback.get("confirmed_selected_trade_dates") or [])
        exploratory_trade_dates = list(broad_scope_fallback.get("exploratory_trade_dates") or [])
        current_plan_visible_trade_dates = []
        visibility_gap_trade_dates = []
        action_rows = [dict(row or {}) for row in list(broad_scope_fallback.get("action_rows") or [])]
    elif _should_apply_broad_scope_fallback(
        candidate_dossier=candidate_dossier,
        confirmed_selected_trade_dates=confirmed_selected_trade_dates,
        exploratory_trade_dates=exploratory_trade_dates,
        action_rows=action_rows,
    ):
        broad_scope_fallback = _load_broad_scope_shadow_fallback(reports_root, focus_ticker)
        confirmed_selected_trade_dates = _dedupe_trade_dates(
            [*confirmed_selected_trade_dates, *list(broad_scope_fallback.get("confirmed_selected_trade_dates") or [])]
        )
        exploratory_trade_dates = _dedupe_trade_dates(
            [*exploratory_trade_dates, *list(broad_scope_fallback.get("exploratory_trade_dates") or [])]
        )
        action_rows = _merge_action_rows(
            action_rows,
            [dict(row or {}) for row in list(broad_scope_fallback.get("action_rows") or [])],
            tier_rank=tier_rank,
        )

    action_rows.sort(key=lambda row: _action_sort_key(row, tier_rank))
    next_target_trade_dates = [str(row.get("trade_date") or "") for row in action_rows if str(row.get("trade_date") or "") and str(row.get("decision") or "") != "selected"][:3]

    if candidate_dossier:
        verdict = "collect_one_more_selected_window"
        recommendation = (
            f"Prioritize the next independent selected window for {focus_ticker}. "
            f"Confirmed selected dates={confirmed_selected_trade_dates}; next targets={next_target_trade_dates}."
        )
    else:
        verdict = "missing_candidate_dossier"
        if broad_scope_fallback:
            recommendation = (
                f"{focus_ticker} is still missing btst_tplus2_candidate_dossier_latest evidence, "
                f"but broad-scope shadow history already shows {broad_scope_fallback.get('broad_scope_distinct_window_count')} independent window(s). "
                f"Formalize trade dates {next_target_trade_dates} into the dossier before corridor governance is re-run."
            )
        else:
            recommendation = (
                f"{focus_ticker} is missing btst_tplus2_candidate_dossier_latest evidence. "
                f"Use visibility-gap windows {next_target_trade_dates} to rebuild the dossier before merge-review probing."
            )

    return {
        "focus_ticker": focus_ticker,
        "verdict": verdict,
        "confirmed_selected_trade_dates": confirmed_selected_trade_dates,
        "exploratory_trade_dates": exploratory_trade_dates,
        "current_plan_visible_trade_dates": current_plan_visible_trade_dates,
        "visibility_gap_trade_dates": visibility_gap_trade_dates,
        "missing_independent_sample_count": dict(persistence.get("continuation_readiness") or {}).get("missing_independent_sample_count"),
        "next_target_trade_dates": next_target_trade_dates,
        "action_rows": action_rows[:6],
        "broad_scope_distinct_window_count": broad_scope_fallback.get("broad_scope_distinct_window_count"),
        "recommendation": recommendation,
        "source_reports": {
            "manifest": str(Path(manifest_path).expanduser().resolve()),
            "persistence_dossier": str(Path(persistence_dossier_path).expanduser().resolve()),
            "candidate_dossier": str(candidate_dossier_path),
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
