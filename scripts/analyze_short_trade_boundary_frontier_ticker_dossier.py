from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _load_json(path: str | Path) -> dict[str, Any]:
    resolved = Path(path).expanduser().resolve()
    return json.loads(resolved.read_text(encoding="utf-8"))


def render_short_trade_boundary_frontier_ticker_dossier_markdown(analysis: dict[str, Any]) -> str:
    dossier = analysis["dossier"]
    lines: list[str] = []
    lines.append(f"# Short Trade Boundary Frontier Ticker Dossier: {dossier['ticker']}")
    lines.append("")
    lines.append("## Overview")
    lines.append(f"- source_report: {analysis['source_report']}")
    lines.append(f"- priority_rank: {dossier['priority_rank']}")
    lines.append(f"- occurrence_count: {dossier['occurrence_count']}")
    lines.append(f"- trade_dates: {dossier['trade_dates']}")
    lines.append("")
    lines.append("## Frontier Profile")
    lines.append(f"- minimal_adjustment_cost: {dossier['minimal_adjustment_cost']}")
    lines.append(f"- max_adjustment_cost: {dossier['max_adjustment_cost']}")
    lines.append(f"- gap_to_near_miss_mean: {dossier['gap_to_near_miss_mean']}")
    lines.append(f"- dominant_pattern: {dossier['dominant_pattern']}")
    lines.append("")
    lines.append("## Outcome Profile")
    lines.append(f"- next_open_return_mean: {dossier['next_open_return_mean']}")
    lines.append(f"- next_high_return_mean: {dossier['next_high_return_mean']}")
    lines.append(f"- next_close_return_mean: {dossier['next_close_return_mean']}")
    lines.append(f"- next_high_hit_rate_at_threshold: {dossier['next_high_hit_rate_at_threshold']}")
    lines.append(f"- next_close_positive_rate: {dossier['next_close_positive_rate']}")
    lines.append(f"- pattern_label: {dossier['pattern_label']}")
    lines.append("")
    lines.append("## Representative Cases")
    lines.append(f"- top_outcome_case: {dossier['top_outcome_case']}")
    lines.append(f"- worst_close_case: {dossier['worst_close_case']}")
    lines.append("")
    lines.append("## Recommendation")
    lines.append(f"- {analysis['recommendation']}")
    return "\n".join(lines) + "\n"


def analyze_short_trade_boundary_frontier_ticker_dossier(
    dossier_report: str | Path,
    *,
    ticker: str,
) -> dict[str, Any]:
    analysis = _load_json(dossier_report)
    normalized_ticker = str(ticker).strip()
    dossiers = list(analysis.get("dossiers") or [])
    matching = [row for row in dossiers if str(row.get("ticker") or "") == normalized_ticker]
    if not matching:
        raise ValueError(f"Ticker not found in dossier report: {normalized_ticker}")
    dossier = dict(matching[0])

    next_high_return_mean = float(dossier.get("next_high_return_mean") or 0.0)
    next_close_positive_rate = float(dossier.get("next_close_positive_rate") or 0.0)

    if dossier.get("pattern_label") == "recurring frontier with intraday upside" and next_close_positive_rate >= 0.6:
        recommendation = (
            f"{normalized_ticker} 应优先作为 close continuation 对照样本观察。"
            f"它仍属于 intraday frontier，但收盘延续稳定性高于同簇样本。"
        )
    elif dossier.get("pattern_label") == "recurring frontier with intraday upside" and next_high_return_mean >= 0.04:
        recommendation = (
            f"{normalized_ticker} 应继续作为 intraday frontier 主样本观察，"
            f"不要直接当成默认 close continuation release 候选。"
        )
    elif dossier.get("pattern_label") == "recurring frontier with intraday upside":
        recommendation = (
            f"{normalized_ticker} 应继续作为 intraday frontier dossier 观察，"
            f"同时保留为较弱上冲样本的对照。"
        )
    elif dossier.get("pattern_label") == "recurring frontier with close continuation":
        recommendation = (
            f"{normalized_ticker} 具备更稳定的 close continuation 特征，"
            f"可作为 recurring frontier 中更偏收盘延续的一类样本继续审查。"
        )
    else:
        recommendation = f"{normalized_ticker} 当前更适合作为观察样本，而不是优先 release 候选。"

    return {
        "source_report": str(Path(dossier_report).expanduser().resolve()),
        "dossier": dossier,
        "recommendation": recommendation,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract a single recurring frontier ticker dossier from the aggregated dossier report.")
    parser.add_argument("--dossier-report", required=True)
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--output-json", default="")
    parser.add_argument("--output-md", default="")
    args = parser.parse_args()

    analysis = analyze_short_trade_boundary_frontier_ticker_dossier(args.dossier_report, ticker=args.ticker)
    if args.output_json:
        output_json = Path(args.output_json).expanduser().resolve()
        output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.output_md:
        output_md = Path(args.output_md).expanduser().resolve()
        output_md.write_text(render_short_trade_boundary_frontier_ticker_dossier_markdown(analysis), encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()