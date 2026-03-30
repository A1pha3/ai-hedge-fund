from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from scripts.analyze_short_trade_ticker_role_history import discover_report_dirs
from scripts.replay_selection_target_calibration import STRUCTURAL_VARIANTS, analyze_selection_target_structural_variants


REPORTS_DIR = Path("data/reports")
DEFAULT_OUTPUT_JSON = REPORTS_DIR / "btst_candidate_entry_window_scan_20260330.json"
DEFAULT_OUTPUT_MD = REPORTS_DIR / "btst_candidate_entry_window_scan_20260330.md"
WINDOW_KEY_PATTERN = re.compile(r"paper_trading_window_(\d{8})_(\d{8})")


def _extract_window_key(report_name: str) -> str:
    matched = WINDOW_KEY_PATTERN.search(str(report_name))
    if not matched:
        return str(report_name)
    return f"{matched.group(1)}_{matched.group(2)}"


def _parse_csv_list(raw: str | None) -> list[str]:
    if raw is None or not str(raw).strip():
        return []
    return [token.strip() for token in str(raw).split(",") if token.strip()]


def _build_window_status(*, filtered_count: int, focus_filtered_tickers: list[str], preserve_filtered_tickers: list[str], blocked_to_none_count: int) -> str:
    if preserve_filtered_tickers:
        return "misfilters_preserve_tickers"
    if focus_filtered_tickers:
        return "filters_focus_tickers"
    if filtered_count > 0 and blocked_to_none_count > 0:
        return "filters_entries_without_focus_signal"
    if filtered_count > 0:
        return "filters_entries_without_decision_release"
    return "no_filtered_entries"


def analyze_btst_candidate_entry_window_scan(
    report_dirs: list[str | Path],
    *,
    structural_variant: str = "exclude_watchlist_avoid_weak_structure_entries",
    profile_name: str = "default",
    select_threshold: float | None = None,
    near_miss_threshold: float | None = None,
    focus_tickers: list[str] | None = None,
    preserve_tickers: list[str] | None = None,
) -> dict[str, Any]:
    if structural_variant not in STRUCTURAL_VARIANTS:
        available = ", ".join(sorted(STRUCTURAL_VARIANTS))
        raise ValueError(f"Unknown structural variant: {structural_variant}. Available: {available}")

    resolved_report_dirs = [Path(path).expanduser().resolve() for path in report_dirs]
    focus_ticker_list = [ticker for ticker in list(focus_tickers or []) if str(ticker or "").strip()]
    preserve_ticker_list = [ticker for ticker in list(preserve_tickers or []) if str(ticker or "").strip()]
    focus_union = sorted(set(focus_ticker_list) | set(preserve_ticker_list))

    rows: list[dict[str, Any]] = []
    filtered_ticker_counts: Counter[str] = Counter()
    status_counts: Counter[str] = Counter()
    filtered_report_window_keys: set[str] = set()

    for report_dir in resolved_report_dirs:
        variant_analysis = analyze_selection_target_structural_variants(
            report_dir,
            profile_name=profile_name,
            structural_variants=["baseline", structural_variant],
            select_threshold=select_threshold,
            near_miss_threshold=near_miss_threshold,
            focus_tickers=focus_union,
        )
        baseline_row = next(row for row in list(variant_analysis.get("rows") or []) if row.get("structural_variant") == "baseline")
        structural_row = next(row for row in list(variant_analysis.get("rows") or []) if row.get("structural_variant") == structural_variant)
        structural_analysis = dict(structural_row.get("analysis") or {})

        filtered_entries: list[dict[str, Any]] = []
        filtered_trade_dates: set[str] = set()
        for day_row in list(structural_analysis.get("by_trade_date") or []):
            trade_date = str(day_row.get("trade_date") or "")
            day_filtered_entries = [dict(entry or {}) for entry in list(day_row.get("filtered_candidate_entries") or [])]
            if day_filtered_entries:
                filtered_trade_dates.add(trade_date)
            for entry in day_filtered_entries:
                filtered_entries.append({"trade_date": trade_date, **entry})

        filtered_tickers = sorted({str(entry.get("ticker") or "") for entry in filtered_entries if str(entry.get("ticker") or "").strip()})
        focus_filtered_tickers = sorted(set(filtered_tickers) & set(focus_ticker_list))
        preserve_filtered_tickers = sorted(set(filtered_tickers) & set(preserve_ticker_list))
        blocked_to_none_count = int(dict(structural_analysis.get("decision_transition_counts") or {}).get("blocked->none", 0))
        window_status = _build_window_status(
            filtered_count=len(filtered_entries),
            focus_filtered_tickers=focus_filtered_tickers,
            preserve_filtered_tickers=preserve_filtered_tickers,
            blocked_to_none_count=blocked_to_none_count,
        )

        status_counts[window_status] += 1
        if filtered_entries:
            filtered_report_window_keys.add(_extract_window_key(report_dir.name))
        filtered_ticker_counts.update(filtered_tickers)

        rows.append(
            {
                "report_dir": report_dir.as_posix(),
                "report_name": report_dir.name,
                "window_key": _extract_window_key(report_dir.name),
                "trade_dates": sorted({str(day_row.get("trade_date") or "") for day_row in list(structural_analysis.get("by_trade_date") or []) if str(day_row.get("trade_date") or "").strip()}),
                "baseline_decision_counts": dict(baseline_row.get("replayed_short_trade_decision_counts") or {}),
                "variant_decision_counts": dict(structural_row.get("replayed_short_trade_decision_counts") or {}),
                "decision_mismatch_count": int(structural_row.get("decision_mismatch_count") or 0),
                "released_from_blocked": list(structural_row.get("released_from_blocked") or []),
                "blocked_to_near_miss": list(structural_row.get("blocked_to_near_miss") or []),
                "blocked_to_selected": list(structural_row.get("blocked_to_selected") or []),
                "filtered_candidate_entry_count": len(filtered_entries),
                "filtered_tickers": filtered_tickers,
                "filtered_trade_dates": sorted(filtered_trade_dates),
                "focus_filtered_tickers": focus_filtered_tickers,
                "preserve_filtered_tickers": preserve_filtered_tickers,
                "candidate_entry_filter_observability": dict(structural_analysis.get("candidate_entry_filter_observability") or {}),
                "filtered_candidate_entry_counts": dict(structural_analysis.get("filtered_candidate_entry_counts") or {}),
                "window_status": window_status,
                "focused_score_diagnostics": list(structural_analysis.get("focused_score_diagnostics") or []),
            }
        )

    rows.sort(
        key=lambda row: (
            0 if row["focus_filtered_tickers"] else 1,
            0 if not row["preserve_filtered_tickers"] else 1,
            -int(row["filtered_candidate_entry_count"]),
            row["window_key"],
            row["report_name"],
        )
    )

    filtered_report_count = sum(1 for row in rows if int(row["filtered_candidate_entry_count"]) > 0)
    focus_hit_report_count = sum(1 for row in rows if row["focus_filtered_tickers"])
    preserve_misfire_report_count = sum(1 for row in rows if row["preserve_filtered_tickers"])
    distinct_window_count_with_filtered_entries = len(filtered_report_window_keys)

    if preserve_misfire_report_count > 0:
        rollout_readiness = "research_only_preserve_misfire"
        recommendation = "弱结构 candidate-entry 规则已出现 preserve 误伤，当前只能保留为 research-only 语义，不能进入 shadow rollout。"
    elif filtered_report_count == 0:
        rollout_readiness = "no_window_signal"
        recommendation = "当前可用窗口里没有任何弱结构 candidate-entry hit，不能从现有证据推进 rollout。"
    elif distinct_window_count_with_filtered_entries < 2:
        rollout_readiness = "shadow_only_until_second_window"
        recommendation = "弱结构 candidate-entry 规则当前只在单一独立窗口里形成过滤信号，但没有 preserve 误伤；可保留为 shadow candidate-entry 旁路，不得升级默认。"
    else:
        rollout_readiness = "shadow_rollout_review_ready"
        recommendation = "弱结构 candidate-entry 规则已在多个独立窗口里形成过滤信号，且未出现 preserve 误伤；下一步应进入 shadow rollout review，而不是直接升级默认。"

    return {
        "report_dirs": [path.as_posix() for path in resolved_report_dirs],
        "structural_variant": structural_variant,
        "profile_name": profile_name,
        "select_threshold": select_threshold,
        "near_miss_threshold": near_miss_threshold,
        "focus_tickers": focus_ticker_list,
        "preserve_tickers": preserve_ticker_list,
        "report_count": len(rows),
        "filtered_report_count": filtered_report_count,
        "focus_hit_report_count": focus_hit_report_count,
        "preserve_misfire_report_count": preserve_misfire_report_count,
        "distinct_window_count_with_filtered_entries": distinct_window_count_with_filtered_entries,
        "filtered_ticker_counts": dict(filtered_ticker_counts.most_common()),
        "window_status_counts": dict(status_counts.most_common()),
        "rows": rows,
        "rollout_readiness": rollout_readiness,
        "recommendation": recommendation,
    }


def render_btst_candidate_entry_window_scan_markdown(analysis: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# BTST Candidate Entry Window Scan")
    lines.append("")
    lines.append("## Overview")
    lines.append(f"- structural_variant: {analysis['structural_variant']}")
    lines.append(f"- report_count: {analysis['report_count']}")
    lines.append(f"- filtered_report_count: {analysis['filtered_report_count']}")
    lines.append(f"- focus_hit_report_count: {analysis['focus_hit_report_count']}")
    lines.append(f"- preserve_misfire_report_count: {analysis['preserve_misfire_report_count']}")
    lines.append(f"- distinct_window_count_with_filtered_entries: {analysis['distinct_window_count_with_filtered_entries']}")
    lines.append(f"- rollout_readiness: {analysis['rollout_readiness']}")
    lines.append(f"- recommendation: {analysis['recommendation']}")
    lines.append("")
    lines.append("## Window Rows")
    for row in list(analysis.get("rows") or []):
        lines.append(
            f"- report={row['report_name']} window_key={row['window_key']} status={row['window_status']} filtered_count={row['filtered_candidate_entry_count']} released_from_blocked={row['released_from_blocked']} focus_filtered={row['focus_filtered_tickers']} preserve_filtered={row['preserve_filtered_tickers']}"
        )
    if not analysis.get("rows"):
        lines.append("- none")
    lines.append("")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Scan BTST report windows for candidate-entry weak-structure rule selectivity and rollout readiness.")
    parser.add_argument("--report-dirs", default="", help="Comma-separated report directories.")
    parser.add_argument("--report-root-dirs", default="", help="Comma-separated root directories to recursively discover report directories.")
    parser.add_argument("--report-name-contains", default="paper_trading_window", help="Optional substring filter used during report discovery.")
    parser.add_argument("--structural-variant", default="exclude_watchlist_avoid_weak_structure_entries")
    parser.add_argument("--profile-name", default="default")
    parser.add_argument("--select-threshold", type=float, default=None)
    parser.add_argument("--near-miss-threshold", type=float, default=None)
    parser.add_argument("--focus-tickers", default="", help="Comma-separated tickers expected to be filtered if the rule is useful.")
    parser.add_argument("--preserve-tickers", default="", help="Comma-separated tickers that should remain unfiltered.")
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--output-md", default=str(DEFAULT_OUTPUT_MD))
    args = parser.parse_args()

    report_dirs = _parse_csv_list(args.report_dirs)
    if args.report_root_dirs:
        report_dirs.extend(
            str(path)
            for path in discover_report_dirs(
                _parse_csv_list(args.report_root_dirs),
                report_name_contains=str(args.report_name_contains or ""),
            )
        )
    if not report_dirs:
        raise SystemExit("No report directories were provided or discovered.")

    analysis = analyze_btst_candidate_entry_window_scan(
        report_dirs,
        structural_variant=str(args.structural_variant or "exclude_watchlist_avoid_weak_structure_entries"),
        profile_name=str(args.profile_name or "default"),
        select_threshold=args.select_threshold,
        near_miss_threshold=args.near_miss_threshold,
        focus_tickers=_parse_csv_list(args.focus_tickers),
        preserve_tickers=_parse_csv_list(args.preserve_tickers),
    )

    output_json = Path(args.output_json).expanduser().resolve()
    output_md = Path(args.output_md).expanduser().resolve()
    output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_md.write_text(render_btst_candidate_entry_window_scan_markdown(analysis), encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()