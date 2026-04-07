from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import scripts.btst_analysis_utils as btst_utils
from scripts.analyze_btst_candidate_pool_lane_objective_support import _build_occurrence_rows
from scripts.analyze_btst_tplus1_tplus2_objective_monitor import _deduplicate_rows
from scripts.btst_report_utils import discover_nested_report_dirs as discover_report_dirs


REPORTS_DIR = Path("data/reports")
DEFAULT_DEFAULT_MERGE_REVIEW_PATH = REPORTS_DIR / "btst_default_merge_review_latest.json"
DEFAULT_CANDIDATE_POOL_RECALL_DOSSIER_PATH = REPORTS_DIR / "btst_candidate_pool_recall_dossier_latest.json"
DEFAULT_OUTPUT_JSON = REPORTS_DIR / "btst_default_merge_strict_counterfactual_latest.json"
DEFAULT_OUTPUT_MD = REPORTS_DIR / "btst_default_merge_strict_counterfactual_latest.md"


def _load_optional_json(path: str | Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    resolved = Path(path).expanduser().resolve()
    if not resolved.exists():
        return {}
    return json.loads(resolved.read_text(encoding="utf-8"))


def _collect_default_tradeable_rows(reports_root: Path) -> list[dict[str, Any]]:
    report_dirs = discover_report_dirs([reports_root], report_name_contains="paper_trading_window")
    price_cache: dict[tuple[str, str], Any] = {}
    rows: list[dict[str, Any]] = []
    for report_dir in report_dirs:
        for snapshot in btst_utils.iter_selection_snapshots(report_dir) or []:
            trade_date = btst_utils.normalize_trade_date(snapshot.get("trade_date"))
            for ticker, evaluation in dict(snapshot.get("selection_targets") or {}).items():
                short_trade = dict((evaluation or {}).get("short_trade") or {})
                if not short_trade or str(short_trade.get("decision") or "") not in {"selected", "near_miss"}:
                    continue
                price_outcome = btst_utils.extract_btst_price_outcome(str(ticker), trade_date, price_cache)
                rows.append(
                    {
                        "trade_date": trade_date,
                        "ticker": str(ticker),
                        "decision": str(short_trade.get("decision") or ""),
                        "candidate_source": str((evaluation or {}).get("candidate_source") or dict(short_trade.get("explainability_payload") or {}).get("candidate_source") or "unknown"),
                        **price_outcome,
                    }
                )
    deduped_rows, _ = _deduplicate_rows(rows)
    return deduped_rows


def _collect_focus_occurrence_rows(candidate_pool_recall_dossier: dict[str, Any], focus_ticker: str) -> list[dict[str, Any]]:
    return _build_occurrence_rows(candidate_pool_recall_dossier, tickers=[focus_ticker])


def _merge_key(row: dict[str, Any]) -> tuple[str, str]:
    return (str(row.get("trade_date") or ""), str(row.get("ticker") or ""))


def _build_surface(rows: list[dict[str, Any]]) -> dict[str, Any]:
    summary = btst_utils.build_surface_summary(rows, next_high_hit_threshold=0.02)
    return {
        "closed_cycle_count": summary.get("closed_cycle_count"),
        "t_plus_2_positive_rate": summary.get("t_plus_2_close_positive_rate"),
        "mean_t_plus_2_return": dict(summary.get("t_plus_2_close_return_distribution") or {}).get("mean"),
    }


def generate_btst_default_merge_strict_counterfactual(
    *,
    reports_root: str | Path = REPORTS_DIR,
    default_merge_review_path: str | Path = DEFAULT_DEFAULT_MERGE_REVIEW_PATH,
    candidate_pool_recall_dossier_path: str | Path = DEFAULT_CANDIDATE_POOL_RECALL_DOSSIER_PATH,
) -> dict[str, Any]:
    resolved_reports_root = Path(reports_root).expanduser().resolve()
    default_merge_review = _load_optional_json(default_merge_review_path)
    candidate_pool_recall_dossier = _load_optional_json(candidate_pool_recall_dossier_path)
    focus_ticker = str(default_merge_review.get("focus_ticker") or "").strip()

    default_tradeable_rows = _collect_default_tradeable_rows(resolved_reports_root)
    focus_rows = _collect_focus_occurrence_rows(candidate_pool_recall_dossier, focus_ticker) if focus_ticker else []
    default_keys = {_merge_key(row) for row in default_tradeable_rows}
    focus_keys = {_merge_key(row) for row in focus_rows}
    overlap_keys = sorted(default_keys & focus_keys)
    focus_only_rows = [row for row in focus_rows if _merge_key(row) not in default_keys]
    default_trade_dates = sorted({str(row.get("trade_date") or "") for row in default_tradeable_rows if str(row.get("trade_date") or "").strip()})
    focus_trade_dates = sorted({str(row.get("trade_date") or "") for row in focus_rows if str(row.get("trade_date") or "").strip()})
    focus_only_trade_dates = sorted({str(row.get("trade_date") or "") for row in focus_only_rows if str(row.get("trade_date") or "").strip()})
    overlap_trade_dates = sorted({trade_date for trade_date, _ in overlap_keys if str(trade_date or "").strip()})
    merged_rows = [*default_tradeable_rows, *focus_only_rows]

    default_surface = _build_surface(default_tradeable_rows)
    focus_surface = _build_surface(focus_rows)
    merged_surface = _build_surface(merged_rows)
    positive_rate_uplift = (
        round(float(merged_surface.get("t_plus_2_positive_rate")) - float(default_surface.get("t_plus_2_positive_rate")), 4)
        if merged_surface.get("t_plus_2_positive_rate") is not None and default_surface.get("t_plus_2_positive_rate") is not None
        else None
    )
    mean_return_uplift = (
        round(float(merged_surface.get("mean_t_plus_2_return")) - float(default_surface.get("mean_t_plus_2_return")), 4)
        if merged_surface.get("mean_t_plus_2_return") is not None and default_surface.get("mean_t_plus_2_return") is not None
        else None
    )
    if positive_rate_uplift is None or mean_return_uplift is None:
        strict_counterfactual_verdict = "insufficient_strict_counterfactual_data"
    elif positive_rate_uplift > 0 and mean_return_uplift > 0:
        strict_counterfactual_verdict = "strict_merge_uplift_positive"
    else:
        strict_counterfactual_verdict = "strict_merge_uplift_mixed"

    recommendation = (
        f"严格去重后，{focus_ticker} 的 merge uplift verdict={strict_counterfactual_verdict}，"
        f" overlap_case_count={len(overlap_keys)}， strict_positive_rate_uplift={positive_rate_uplift}，"
        f" strict_mean_return_uplift={mean_return_uplift}。"
        if focus_ticker
        else "当前没有 focus_ticker，无法构建严格去重 merge counterfactual。"
    )
    return {
        "focus_ticker": focus_ticker or None,
        "merge_review_verdict": default_merge_review.get("merge_review_verdict"),
        "strict_counterfactual_verdict": strict_counterfactual_verdict,
        "default_tradeable_surface": default_surface,
        "focus_candidate_surface": focus_surface,
        "strict_merged_surface": merged_surface,
        "strict_uplift_vs_default_btst": {
            "t_plus_2_positive_rate_uplift": positive_rate_uplift,
            "mean_t_plus_2_return_uplift": mean_return_uplift,
        },
        "overlap_diagnostics": {
            "default_tradeable_case_count": len(default_tradeable_rows),
            "focus_case_count": len(focus_rows),
            "focus_only_case_count": len(focus_only_rows),
            "overlap_case_count": len(overlap_keys),
            "default_trade_date_count": len(default_trade_dates),
            "focus_trade_date_count": len(focus_trade_dates),
            "focus_only_trade_date_count": len(focus_only_trade_dates),
            "overlap_trade_date_count": len(overlap_trade_dates),
            "overlap_case_ratio_vs_focus_cases": round(len(overlap_keys) / len(focus_rows), 4) if focus_rows else 0.0,
            "focus_only_trade_dates": focus_only_trade_dates[:10],
            "overlap_trade_dates": overlap_trade_dates[:10],
            "overlap_trade_date_tickers": [{"trade_date": trade_date, "ticker": ticker} for trade_date, ticker in overlap_keys[:10]],
        },
        "assumption_note": "Strict merge counterfactual de-duplicates by (trade_date, ticker) between default tradeable rows and focus continuation rows before recomputing the merged surface.",
        "recommendation": recommendation,
        "source_reports": {
            "default_merge_review": str(Path(default_merge_review_path).expanduser().resolve()),
            "candidate_pool_recall_dossier": str(Path(candidate_pool_recall_dossier_path).expanduser().resolve()),
            "reports_root": str(resolved_reports_root),
        },
    }


def render_btst_default_merge_strict_counterfactual_markdown(analysis: dict[str, Any]) -> str:
    lines = [
        "# BTST Default Merge Strict Counterfactual",
        "",
        "## Overview",
        f"- focus_ticker: {analysis.get('focus_ticker')}",
        f"- strict_counterfactual_verdict: {analysis.get('strict_counterfactual_verdict')}",
        f"- merge_review_verdict: {analysis.get('merge_review_verdict')}",
        f"- default_tradeable_surface: {analysis.get('default_tradeable_surface')}",
        f"- focus_candidate_surface: {analysis.get('focus_candidate_surface')}",
        f"- strict_merged_surface: {analysis.get('strict_merged_surface')}",
        f"- strict_uplift_vs_default_btst: {analysis.get('strict_uplift_vs_default_btst')}",
        f"- overlap_diagnostics: {analysis.get('overlap_diagnostics')}",
        f"- assumption_note: {analysis.get('assumption_note')}",
        "",
        "## Recommendation",
        f"- {analysis.get('recommendation')}",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a strict, de-duplicated default BTST merge counterfactual for the current continuation focus ticker.")
    parser.add_argument("--reports-root", default=str(REPORTS_DIR))
    parser.add_argument("--default-merge-review-path", default=str(DEFAULT_DEFAULT_MERGE_REVIEW_PATH))
    parser.add_argument("--candidate-pool-recall-dossier-path", default=str(DEFAULT_CANDIDATE_POOL_RECALL_DOSSIER_PATH))
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--output-md", default=str(DEFAULT_OUTPUT_MD))
    args = parser.parse_args()

    analysis = generate_btst_default_merge_strict_counterfactual(
        reports_root=args.reports_root,
        default_merge_review_path=args.default_merge_review_path,
        candidate_pool_recall_dossier_path=args.candidate_pool_recall_dossier_path,
    )
    output_json = Path(args.output_json).expanduser().resolve()
    output_md = Path(args.output_md).expanduser().resolve()
    output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_md.write_text(render_btst_default_merge_strict_counterfactual_markdown(analysis), encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
