from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scripts.btst_analysis_utils import (
    extract_btst_price_outcome as _extract_btst_price_outcome,
    iter_selection_snapshots as _iter_selection_snapshots,
    normalize_trade_date as _normalize_trade_date,
    round_or_none as _round_or_none,
)
from scripts.btst_report_utils import discover_nested_report_dirs as discover_report_dirs
from scripts.btst_round1_factor_mining_helpers import build_round1_research_row


REPORTS_DIR = Path("data/reports")
DEFAULT_REPORTS_ROOT = REPORTS_DIR
DEFAULT_OUTPUT_JSON = REPORTS_DIR / "btst_5d_15pct_factor_research_round1_latest.json"
DEFAULT_OUTPUT_MD = REPORTS_DIR / "btst_5d_15pct_factor_research_round1_latest.md"


def _group_summary(rows: list[dict[str, Any]], *, min_closed_cycle_count: int) -> dict[str, Any]:
    closed_rows = [row for row in rows if row.get("gamma_closed_cycle")]
    hit_rows = [row for row in closed_rows if row.get("future_high_hit_15pct_2_5d") is True]
    mean_max_return = _round_or_none(sum(float(row.get("max_future_high_return_2_5d") or 0.0) for row in closed_rows) / len(closed_rows)) if closed_rows else None
    beta_tradeable_rate = _round_or_none(sum(1 for row in rows if row.get("beta_tradeable")) / len(rows)) if rows else None
    unique_report_dirs = len({str(row.get("report_dir_name") or "") for row in closed_rows})
    hit_rate = _round_or_none(len(hit_rows) / len(closed_rows)) if closed_rows else None
    alpha_pass = len(closed_rows) >= min_closed_cycle_count and float(hit_rate or 0.0) >= 0.55 and float(mean_max_return or 0.0) >= 0.15
    beta_pass = beta_tradeable_rate is not None and beta_tradeable_rate >= 0.70
    gamma_pass = unique_report_dirs >= 2 or min_closed_cycle_count == 1
    return {
        "row_count": len(rows),
        "closed_cycle_count": len(closed_rows),
        "hit_rate_15pct": hit_rate,
        "mean_max_future_high_return_2_5d": mean_max_return,
        "beta_tradeable_rate": beta_tradeable_rate,
        "unique_report_dir_count": unique_report_dirs,
        "alpha_pass": alpha_pass,
        "beta_pass": beta_pass,
        "gamma_pass": gamma_pass,
    }


def _sorted_group_rows(groups: dict[str, list[dict[str, Any]]], *, group_type: str, min_closed_cycle_count: int) -> list[dict[str, Any]]:
    rows = [{"group_type": group_type, "group_label": label, **_group_summary(group_rows, min_closed_cycle_count=min_closed_cycle_count)} for label, group_rows in groups.items()]
    rows.sort(
        key=lambda row: (
            float(row.get("hit_rate_15pct") or -999.0),
            float(row.get("mean_max_future_high_return_2_5d") or -999.0),
            float(row.get("beta_tradeable_rate") or -999.0),
            int(row.get("closed_cycle_count") or 0),
            str(row.get("group_label") or ""),
        ),
        reverse=True,
    )
    return rows


def _collect_shortlist(analysis: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for key in ("factor_family_leaderboard", "interaction_leaderboard"):
        for row in list(analysis.get(key) or []):
            if row.get("alpha_pass") and row.get("beta_pass") and row.get("gamma_pass"):
                candidates.append(dict(row))
    candidates.sort(
        key=lambda row: (
            float(row.get("hit_rate_15pct") or -999.0),
            float(row.get("mean_max_future_high_return_2_5d") or -999.0),
            float(row.get("beta_tradeable_rate") or -999.0),
        ),
        reverse=True,
    )
    return candidates


def analyze_btst_5d_15pct_factor_research_round1(reports_root: str | Path, *, min_closed_cycle_count: int = 3) -> dict[str, Any]:
    resolved_root = Path(reports_root).expanduser().resolve()
    report_dirs = discover_report_dirs([resolved_root], report_name_contains="paper_trading_window")
    price_cache: dict[tuple[str, str], Any] = {}
    rows: list[dict[str, Any]] = []
    for report_dir in report_dirs:
        for snapshot in _iter_selection_snapshots(report_dir) or []:
            trade_date = _normalize_trade_date(snapshot.get("trade_date"))
            for ticker, evaluation in dict(snapshot.get("selection_targets") or {}).items():
                short_trade = dict((evaluation or {}).get("short_trade") or {})
                if not short_trade:
                    continue
                rows.append(
                    build_round1_research_row(
                        ticker=str(ticker),
                        trade_date=trade_date,
                        report_dir_name=report_dir.name,
                        evaluation=dict(evaluation or {}),
                        price_outcome=_extract_btst_price_outcome(str(ticker), trade_date, price_cache),
                    )
                )

    prototype_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    family_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    interaction_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        prototype_groups[str(row.get("event_prototype") or "unclassified")].append(row)
        for family_name in ("trend_family", "breakout_family", "volume_quality_family"):
            if row.get(family_name) is not None:
                family_groups[family_name].append(row)
        for interaction_name in ("trend_x_close_strength", "breakout_x_volume_quality"):
            if row.get(interaction_name) is not None:
                interaction_groups[interaction_name].append(row)

    analysis = {
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "reports_root": str(resolved_root),
        "row_count": len(rows),
        "event_prototype_leaderboard": _sorted_group_rows(prototype_groups, group_type="event_prototype", min_closed_cycle_count=min_closed_cycle_count),
        "factor_family_leaderboard": _sorted_group_rows(family_groups, group_type="factor_family", min_closed_cycle_count=min_closed_cycle_count),
        "interaction_leaderboard": _sorted_group_rows(interaction_groups, group_type="interaction", min_closed_cycle_count=min_closed_cycle_count),
    }
    analysis["alpha_beta_gamma_shortlist"] = _collect_shortlist(analysis)
    return analysis


def render_btst_5d_15pct_factor_research_round1_markdown(analysis: dict[str, Any]) -> str:
    lines = ["# BTST 5D / 15% Factor Research Round 1", ""]
    lines.append(f"- row_count: {analysis.get('row_count')}")
    lines.append("")
    for section in ("event_prototype_leaderboard", "factor_family_leaderboard", "interaction_leaderboard", "alpha_beta_gamma_shortlist"):
        lines.append(f"## {section}")
        rows = list(analysis.get(section) or [])
        if not rows:
            lines.append("- none")
        for row in rows:
            lines.append(
                f"- {row.get('group_label')}: hit_rate_15pct={row.get('hit_rate_15pct')}, mean_max_return={row.get('mean_max_future_high_return_2_5d')}, beta_tradeable_rate={row.get('beta_tradeable_rate')}, gates=({row.get('alpha_pass')}, {row.get('beta_pass')}, {row.get('gamma_pass')})"
            )
        lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the BTST 5D/+15% round-1 factor research leaderboard.")
    parser.add_argument("--reports-root", default=str(DEFAULT_REPORTS_ROOT))
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--output-md", default=str(DEFAULT_OUTPUT_MD))
    parser.add_argument("--min-closed-cycle-count", type=int, default=3)
    args = parser.parse_args()

    analysis = analyze_btst_5d_15pct_factor_research_round1(args.reports_root, min_closed_cycle_count=args.min_closed_cycle_count)
    output_json = Path(args.output_json).expanduser().resolve()
    output_md = Path(args.output_md).expanduser().resolve()
    output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_md.write_text(render_btst_5d_15pct_factor_research_round1_markdown(analysis), encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
