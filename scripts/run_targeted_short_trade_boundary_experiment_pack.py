from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from scripts.analyze_targeted_release_outcomes import analyze_targeted_release_outcomes, render_targeted_release_outcomes_markdown
from scripts.analyze_targeted_short_trade_boundary_release import (
    analyze_targeted_short_trade_boundary_release,
    render_targeted_short_trade_boundary_release_markdown,
)


def _load_json(path: str | Path) -> dict[str, Any]:
    resolved = Path(path).expanduser().resolve()
    return json.loads(resolved.read_text(encoding="utf-8"))


def _write_json(path: str | Path, payload: dict[str, Any]) -> str:
    resolved = Path(path).expanduser().resolve()
    resolved.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return str(resolved)


def _write_markdown(path: str | Path, content: str) -> str:
    resolved = Path(path).expanduser().resolve()
    resolved.write_text(content, encoding="utf-8")
    return str(resolved)


def _compact_date(value: str) -> str:
    return str(value or "").replace("-", "")


def _find_frontier_case(frontier_analysis: dict[str, Any], *, ticker: str, trade_date: str | None = None) -> dict[str, Any]:
    rows = list(frontier_analysis.get("minimal_near_miss_rows") or [])
    matches = [
        row
        for row in rows
        if str(row.get("ticker") or "") == ticker and (trade_date is None or str(row.get("trade_date") or "") == trade_date)
    ]
    if trade_date and not matches:
        raise ValueError(f"No frontier row found for {trade_date}:{ticker}")
    if not trade_date and not matches:
        raise ValueError(f"No frontier row found for ticker {ticker}")
    if trade_date is None and len(matches) > 1:
        raise ValueError(f"Multiple frontier rows found for ticker {ticker}; provide --trade-date to disambiguate")
    return dict(matches[0])


def _default_artifact_stem(*, output_dir: Path, ticker: str, trade_date: str) -> Path:
    return output_dir / f"{ticker}_{_compact_date(trade_date)}"


def render_targeted_short_trade_boundary_experiment_pack_markdown(pack: dict[str, Any]) -> str:
    frontier_case = dict(pack.get("frontier_case") or {})
    release = dict(pack.get("release_analysis") or {})
    outcomes = dict(pack.get("outcome_analysis") or {})
    lines: list[str] = []
    lines.append("# Targeted Short Trade Boundary Experiment Pack")
    lines.append("")
    lines.append("## Scope")
    lines.append(f"- ticker: {pack['ticker']}")
    lines.append(f"- trade_date: {pack['trade_date']}")
    lines.append(f"- source_frontier_report: {pack['source_frontier_report']}")
    lines.append(f"- source_report_dir: {pack['source_report_dir']}")
    lines.append("")
    lines.append("## Frontier Recommendation")
    lines.append(f"- baseline_score_target: {frontier_case.get('baseline_score_target')}")
    lines.append(f"- replayed_score_target: {frontier_case.get('replayed_score_target')}")
    lines.append(f"- near_miss_threshold: {frontier_case.get('near_miss_threshold')}")
    lines.append(f"- stale_weight: {frontier_case.get('stale_weight')}")
    lines.append(f"- extension_weight: {frontier_case.get('extension_weight')}")
    lines.append(f"- adjustment_cost: {frontier_case.get('adjustment_cost')}")
    lines.append("")
    lines.append("## Release Result")
    lines.append(f"- changed_case_count: {release.get('changed_case_count')}")
    lines.append(f"- changed_non_target_case_count: {release.get('changed_non_target_case_count')}")
    lines.append(f"- decision_transition_counts: {release.get('decision_transition_counts')}")
    lines.append(f"- recommendation: {release.get('recommendation')}")
    lines.append("")
    lines.append("## Outcome Result")
    lines.append(f"- target_case_count: {outcomes.get('target_case_count')}")
    lines.append(f"- promoted_target_case_count: {outcomes.get('promoted_target_case_count')}")
    lines.append(f"- next_high_return_mean: {outcomes.get('next_high_return_mean')}")
    lines.append(f"- next_close_return_mean: {outcomes.get('next_close_return_mean')}")
    lines.append(f"- next_close_positive_rate: {outcomes.get('next_close_positive_rate')}")
    lines.append(f"- recommendation: {outcomes.get('recommendation')}")
    lines.append("")
    lines.append("## Artifacts")
    for key, value in dict(pack.get("artifacts") or {}).items():
        lines.append(f"- {key}: {value}")
    lines.append("")
    lines.append("## Pack Recommendation")
    lines.append(f"- {pack['recommendation']}")
    return "\n".join(lines) + "\n"


def run_targeted_short_trade_boundary_experiment_pack(
    *,
    frontier_report: str | Path,
    output_dir: str | Path,
    ticker: str,
    trade_date: str | None = None,
    next_high_hit_threshold: float = 0.02,
) -> dict[str, Any]:
    frontier_analysis = _load_json(frontier_report)
    frontier_case = _find_frontier_case(frontier_analysis, ticker=ticker, trade_date=trade_date)
    resolved_trade_date = str(frontier_case.get("trade_date") or "")
    resolved_ticker = str(frontier_case.get("ticker") or ticker)
    report_dir = str(frontier_analysis.get("report_dir") or "")
    if not report_dir:
        raise ValueError("Frontier report does not contain report_dir")

    output_root = Path(output_dir).expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    stem = _default_artifact_stem(output_dir=output_root, ticker=resolved_ticker, trade_date=resolved_trade_date)

    release_analysis = analyze_targeted_short_trade_boundary_release(
        report_dir,
        targets={(resolved_trade_date, resolved_ticker)},
        near_miss_threshold=float(frontier_case["near_miss_threshold"]),
        stale_weight=float(frontier_case["stale_weight"]),
        extension_weight=float(frontier_case["extension_weight"]),
    )
    release_json_path = _write_json(output_root / f"targeted_short_trade_boundary_release_{stem.name}.json", release_analysis)
    release_md_path = _write_markdown(
        output_root / f"targeted_short_trade_boundary_release_{stem.name}.md",
        render_targeted_short_trade_boundary_release_markdown(release_analysis),
    )

    outcome_analysis = analyze_targeted_release_outcomes(release_json_path, next_high_hit_threshold=next_high_hit_threshold)
    outcome_json_path = _write_json(output_root / f"targeted_short_trade_boundary_release_outcomes_{stem.name}.json", outcome_analysis)
    outcome_md_path = _write_markdown(
        output_root / f"targeted_short_trade_boundary_release_outcomes_{stem.name}.md",
        render_targeted_release_outcomes_markdown(outcome_analysis),
    )

    if release_analysis.get("changed_non_target_case_count"):
        recommendation = "当前实验包检测到非目标样本变化，暂不适合作为严格低污染的定向 rescue 依据。"
    elif int(outcome_analysis.get("promoted_target_case_count") or 0) <= 0:
        recommendation = "当前实验包没有形成目标样本迁移，暂不建议把该 rescue 视为可执行放行规则。"
    else:
        recommendation = str(outcome_analysis.get("recommendation") or release_analysis.get("recommendation") or "")

    pack = {
        "ticker": resolved_ticker,
        "trade_date": resolved_trade_date,
        "source_frontier_report": str(Path(frontier_report).expanduser().resolve()),
        "source_report_dir": report_dir,
        "frontier_case": frontier_case,
        "release_analysis": release_analysis,
        "outcome_analysis": outcome_analysis,
        "artifacts": {
            "release_json": release_json_path,
            "release_md": release_md_path,
            "outcome_json": outcome_json_path,
            "outcome_md": outcome_md_path,
        },
        "recommendation": recommendation,
    }
    pack_json_path = _write_json(output_root / f"targeted_short_trade_boundary_experiment_pack_{stem.name}.json", pack)
    pack_md_path = _write_markdown(
        output_root / f"targeted_short_trade_boundary_experiment_pack_{stem.name}.md",
        render_targeted_short_trade_boundary_experiment_pack_markdown(pack),
    )
    pack["artifacts"].update({
        "pack_json": pack_json_path,
        "pack_md": pack_md_path,
    })
    _write_json(Path(pack_json_path), pack)
    _write_markdown(Path(pack_md_path), render_targeted_short_trade_boundary_experiment_pack_markdown(pack))
    return pack


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a runnable targeted short-trade boundary rescue experiment pack from frontier recommendations.")
    parser.add_argument("--frontier-report", default="data/reports/short_trade_boundary_score_failures_frontier_latest.json")
    parser.add_argument("--output-dir", default="data/reports")
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--trade-date", default=None)
    parser.add_argument("--next-high-hit-threshold", type=float, default=0.02)
    args = parser.parse_args()

    pack = run_targeted_short_trade_boundary_experiment_pack(
        frontier_report=args.frontier_report,
        output_dir=args.output_dir,
        ticker=args.ticker,
        trade_date=args.trade_date,
        next_high_hit_threshold=float(args.next_high_hit_threshold),
    )
    print(json.dumps(pack, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()