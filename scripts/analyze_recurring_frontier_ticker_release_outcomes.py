from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import mean
from typing import Any


def _load_json(path: str | Path) -> dict[str, Any]:
    resolved = Path(path).expanduser().resolve()
    return json.loads(resolved.read_text(encoding="utf-8"))


def render_recurring_frontier_ticker_release_outcomes_markdown(analysis: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# Recurring Frontier Ticker Release Outcome Review")
    lines.append("")
    lines.append("## Overview")
    lines.append(f"- release_report: {analysis['release_report']}")
    lines.append(f"- outcome_report: {analysis['outcome_report']}")
    lines.append(f"- ticker: {analysis['ticker']}")
    lines.append(f"- target_case_count: {analysis['target_case_count']}")
    lines.append(f"- promoted_target_case_count: {analysis['promoted_target_case_count']}")
    lines.append("")
    lines.append("## Outcome Summary")
    lines.append(f"- next_high_return_mean: {analysis['next_high_return_mean']}")
    lines.append(f"- next_close_return_mean: {analysis['next_close_return_mean']}")
    lines.append(f"- next_high_hit_rate_at_threshold: {analysis['next_high_hit_rate_at_threshold']}")
    lines.append(f"- next_close_positive_rate: {analysis['next_close_positive_rate']}")
    lines.append("")
    lines.append("## Target Cases")
    for row in analysis["target_cases"]:
        lines.append(
            f"- {row['trade_date']} {row['ticker']}: {row['before_decision']} -> {row['after_decision']}, next_high_return={row['next_high_return']}, next_close_return={row['next_close_return']}, release_verdict={row['release_verdict']}"
        )
    if not analysis["target_cases"]:
        lines.append("- none")
    lines.append("")
    lines.append("## Recommendation")
    lines.append(f"- {analysis['recommendation']}")
    return "\n".join(lines) + "\n"


def analyze_recurring_frontier_ticker_release_outcomes(
    release_report: str | Path,
    outcome_report: str | Path,
) -> dict[str, Any]:
    release_analysis = _load_json(release_report)
    outcome_analysis = _load_json(outcome_report)
    ticker = str(release_analysis.get("ticker") or "")
    rows_by_case = {
        f"{row.get('trade_date')}:{row.get('ticker')}": row
        for row in list(outcome_analysis.get("rows") or [])
    }
    next_high_hit_threshold = float(outcome_analysis.get("next_high_hit_threshold") or 0.02)

    target_cases: list[dict[str, Any]] = []
    next_high_returns: list[float] = []
    next_close_returns: list[float] = []
    next_high_hits = 0
    next_close_positive = 0

    for row in list(release_analysis.get("changed_cases") or []):
        case_key = f"{row.get('trade_date')}:{row.get('ticker')}"
        outcome = dict(rows_by_case.get(case_key) or {})
        next_high_return = outcome.get("next_high_return")
        next_close_return = outcome.get("next_close_return")
        if next_high_return is not None:
            next_high_returns.append(float(next_high_return))
            if float(next_high_return) >= next_high_hit_threshold:
                next_high_hits += 1
        if next_close_return is not None:
            next_close_returns.append(float(next_close_return))
            if float(next_close_return) > 0:
                next_close_positive += 1

        if next_close_return is not None and float(next_close_return) > 0:
            verdict = "promoted_with_positive_close"
        elif next_high_return is not None and float(next_high_return) >= next_high_hit_threshold:
            verdict = "promoted_with_intraday_upside"
        else:
            verdict = "promoted_but_outcome_mixed"

        target_cases.append(
            {
                **row,
                "next_trade_date": outcome.get("next_trade_date"),
                "next_open_return": outcome.get("next_open_return"),
                "next_high_return": next_high_return,
                "next_close_return": next_close_return,
                "release_verdict": verdict,
            }
        )

    promoted_target_case_count = int(release_analysis.get("promoted_target_case_count") or 0)
    if next_high_returns and next_close_returns and mean(next_close_returns) > 0:
        recommendation = f"{ticker} 的 recurring frontier release 不只提供上冲，也具备正向收盘延续，可继续推进更正式的局部变体。"
    elif next_high_returns and mean(next_high_returns) >= next_high_hit_threshold:
        recommendation = f"{ticker} 的 recurring frontier release 更像 intraday upside 实验，继续推进时应避免把它误当成 close continuation 规则。"
    else:
        recommendation = f"{ticker} 的 recurring frontier release 当前没有形成足够稳定的真实 outcome 支持。"

    return {
        "release_report": str(Path(release_report).expanduser().resolve()),
        "outcome_report": str(Path(outcome_report).expanduser().resolve()),
        "ticker": ticker,
        "target_case_count": len(target_cases),
        "promoted_target_case_count": promoted_target_case_count,
        "next_high_hit_threshold": round(next_high_hit_threshold, 4),
        "next_high_return_mean": round(mean(next_high_returns), 4) if next_high_returns else None,
        "next_close_return_mean": round(mean(next_close_returns), 4) if next_close_returns else None,
        "next_high_hit_rate_at_threshold": round(next_high_hits / len(next_high_returns), 4) if next_high_returns else None,
        "next_close_positive_rate": round(next_close_positive / len(next_close_returns), 4) if next_close_returns else None,
        "target_cases": target_cases,
        "recommendation": recommendation,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Join recurring frontier ticker release results with next-day outcomes.")
    parser.add_argument("--release-report", required=True)
    parser.add_argument("--outcome-report", required=True)
    parser.add_argument("--output-json", default="")
    parser.add_argument("--output-md", default="")
    args = parser.parse_args()

    analysis = analyze_recurring_frontier_ticker_release_outcomes(args.release_report, args.outcome_report)
    if args.output_json:
        output_json = Path(args.output_json).expanduser().resolve()
        output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.output_md:
        output_md = Path(args.output_md).expanduser().resolve()
        output_md.write_text(render_recurring_frontier_ticker_release_outcomes_markdown(analysis), encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()