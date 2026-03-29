from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _index_rows(rows: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    return {
        (str(row.get("trade_date") or ""), str(row.get("ticker") or "")): row
        for row in rows
        if str(row.get("trade_date") or "").strip() and str(row.get("ticker") or "").strip()
    }


def render_short_trade_boundary_expansion_cases_markdown(analysis: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# Short Trade Boundary Expansion Case Review")
    lines.append("")
    lines.append("## Overview")
    lines.append(f"- targeted_variant_report: {analysis['targeted_variant_report']}")
    lines.append(f"- filtered_candidate_report: {analysis['filtered_candidate_report']}")
    lines.append(f"- selected_variant_name: {analysis['selected_variant_name']}")
    lines.append(f"- selected_variant_thresholds: {analysis['selected_variant_thresholds']}")
    lines.append(f"- added_case_count: {analysis['added_case_count']}")
    lines.append("")
    lines.append("## Added Cases")
    for row in analysis["added_cases"]:
        lines.append(
            f"- {row['trade_date']} {row['ticker']}: trigger={row['release_trigger']}, score_b={row['score_b']}, candidate_score={row['candidate_score']}, next_high_return={row['next_high_return']}, next_close_return={row['next_close_return']}, failed_thresholds_before={row['failed_thresholds_before']}"
        )
    lines.append("")
    lines.append("## Recommendation")
    lines.append(f"- {analysis['recommendation']}")
    return "\n".join(lines) + "\n"


def analyze_short_trade_boundary_expansion_cases(
    targeted_variant_report: str | Path,
    filtered_candidate_report: str | Path,
    *,
    variant_name: str | None = None,
) -> dict[str, Any]:
    targeted_payload = _load_json(Path(targeted_variant_report).expanduser().resolve())
    filtered_payload = _load_json(Path(filtered_candidate_report).expanduser().resolve())

    variants = list(targeted_payload.get("variants") or [])
    selected_variant = None
    if variant_name:
        selected_variant = next((variant for variant in variants if str(variant.get("variant_name") or "") == variant_name), None)
    if selected_variant is None:
        selected_variant = dict(targeted_payload.get("recommended_variant") or {})

    filtered_index = _index_rows(list(filtered_payload.get("rows") or []))
    added_cases: list[dict[str, Any]] = []
    for row in list(selected_variant.get("top_selected_rows") or []):
        key = (str(row.get("trade_date") or ""), str(row.get("ticker") or ""))
        baseline_row = filtered_index.get(key, {})
        before_failed_thresholds = dict(baseline_row.get("failed_thresholds") or {})
        release_trigger = "newly_admitted"
        if before_failed_thresholds:
            if set(before_failed_thresholds) == {"catalyst_freshness"}:
                release_trigger = "catalyst_floor_only"
            elif "catalyst_freshness" in before_failed_thresholds and len(before_failed_thresholds) > 1:
                release_trigger = "catalyst_plus_other_floors"
            else:
                release_trigger = "non_catalyst_floor_change"
        added_cases.append(
            {
                "trade_date": row.get("trade_date"),
                "ticker": row.get("ticker"),
                "score_b": row.get("score_b"),
                "candidate_score": row.get("candidate_score"),
                "next_high_return": row.get("next_high_return"),
                "next_close_return": row.get("next_close_return"),
                "failed_thresholds_before": before_failed_thresholds,
                "failed_threshold_count_before": baseline_row.get("failed_threshold_count"),
                "primary_reason_before": baseline_row.get("primary_reason"),
                "release_trigger": release_trigger,
            }
        )

    if added_cases:
        catalyst_only_count = sum(1 for row in added_cases if row["release_trigger"] == "catalyst_floor_only")
        recommendation = (
            f"当前推荐变体新增 {len(added_cases)} 个样本，其中 {catalyst_only_count} 个属于纯 catalyst floor 放行；"
            f"这说明该变体主要释放的是本来结构已够强、只差事件新鲜度门槛的样本。"
        )
    else:
        recommendation = "当前选定变体没有新增样本。"

    return {
        "targeted_variant_report": str(Path(targeted_variant_report).expanduser().resolve()),
        "filtered_candidate_report": str(Path(filtered_candidate_report).expanduser().resolve()),
        "selected_variant_name": selected_variant.get("variant_name"),
        "selected_variant_thresholds": dict(selected_variant.get("thresholds") or {}),
        "added_case_count": len(added_cases),
        "added_cases": added_cases,
        "recommendation": recommendation,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Review which edge candidates are newly admitted by a targeted short-trade boundary expansion variant.")
    parser.add_argument("--targeted-variant-report", required=True)
    parser.add_argument("--filtered-candidate-report", required=True)
    parser.add_argument("--variant-name", default="")
    parser.add_argument("--output-json", default="")
    parser.add_argument("--output-md", default="")
    args = parser.parse_args()

    analysis = analyze_short_trade_boundary_expansion_cases(
        args.targeted_variant_report,
        args.filtered_candidate_report,
        variant_name=args.variant_name or None,
    )
    if args.output_json:
        output_json = Path(args.output_json).expanduser().resolve()
        output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.output_md:
        output_md = Path(args.output_md).expanduser().resolve()
        output_md.write_text(render_short_trade_boundary_expansion_cases_markdown(analysis), encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()