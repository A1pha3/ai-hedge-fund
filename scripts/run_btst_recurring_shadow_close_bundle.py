from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from scripts.analyze_recurring_frontier_release_pair_comparison import (
    analyze_recurring_frontier_release_pair_comparison,
    render_recurring_frontier_release_pair_comparison_markdown,
)
from scripts.analyze_recurring_frontier_ticker_release import (
    analyze_recurring_frontier_ticker_release,
    render_recurring_frontier_ticker_release_markdown,
)
from scripts.analyze_recurring_frontier_ticker_release_outcomes import (
    analyze_recurring_frontier_ticker_release_outcomes,
    render_recurring_frontier_ticker_release_outcomes_markdown,
)


REPORTS_DIR = Path("data/reports")
DEFAULT_REPORT_DIR = REPORTS_DIR / "paper_trading_window_20260323_20260326_btst_catalyst_floor_zero_refresh"
DEFAULT_RECURRING_FRONTIER_REPORT = REPORTS_DIR / "short_trade_boundary_recurring_frontier_cases_catalyst_floor_zero_refresh_20260401.json"
DEFAULT_OUTCOME_REPORT = REPORTS_DIR / "pre_layer_short_trade_outcomes_600821_300113_catalyst_floor_zero_refresh_20260401.json"
DEFAULT_CLOSE_CANDIDATE_TICKER = "300113"
DEFAULT_INTRADAY_CONTROL_TICKER = "600821"
DEFAULT_INTRADAY_CONTROL_OUTCOMES = REPORTS_DIR / "recurring_frontier_ticker_release_outcomes_600821_catalyst_floor_zero_refresh_20260401.json"
DEFAULT_CLOSE_RELEASE_JSON = REPORTS_DIR / "recurring_frontier_ticker_release_300113_catalyst_floor_zero_refresh_20260401.json"
DEFAULT_CLOSE_RELEASE_MD = REPORTS_DIR / "recurring_frontier_ticker_release_300113_catalyst_floor_zero_refresh_20260401.md"
DEFAULT_CLOSE_OUTCOMES_JSON = REPORTS_DIR / "recurring_frontier_ticker_release_outcomes_300113_catalyst_floor_zero_refresh_20260401.json"
DEFAULT_CLOSE_OUTCOMES_MD = REPORTS_DIR / "recurring_frontier_ticker_release_outcomes_300113_catalyst_floor_zero_refresh_20260401.md"
DEFAULT_PAIR_JSON = REPORTS_DIR / "recurring_frontier_release_pair_comparison_600821_vs_300113_catalyst_floor_zero_refresh_20260401.json"
DEFAULT_PAIR_MD = REPORTS_DIR / "recurring_frontier_release_pair_comparison_600821_vs_300113_catalyst_floor_zero_refresh_20260401.md"
DEFAULT_SUMMARY_JSON = REPORTS_DIR / "btst_recurring_shadow_close_bundle_300113_20260401.json"
DEFAULT_SUMMARY_MD = REPORTS_DIR / "btst_recurring_shadow_close_bundle_300113_20260401.md"


def _write_json(path: str | Path, payload: dict[str, Any]) -> str:
    resolved = Path(path).expanduser().resolve()
    resolved.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return str(resolved)


def _write_markdown(path: str | Path, content: str) -> str:
    resolved = Path(path).expanduser().resolve()
    resolved.write_text(content, encoding="utf-8")
    return str(resolved)


def _render_summary_markdown(summary: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# BTST Recurring Shadow Close Bundle")
    lines.append("")
    lines.append("## Overview")
    lines.append(f"- close_candidate_ticker: {summary['close_candidate_ticker']}")
    lines.append(f"- intraday_control_ticker: {summary['intraday_control_ticker']}")
    lines.append(f"- recommendation: {summary['recommendation']}")
    lines.append("")
    lines.append("## Close Candidate Release")
    lines.append(f"- release_report: {summary['close_candidate_release_report']}")
    lines.append(f"- target_case_count: {summary['close_candidate_release'].get('target_case_count')}")
    lines.append(f"- promoted_target_case_count: {summary['close_candidate_release'].get('promoted_target_case_count')}")
    lines.append("")
    lines.append("## Close Candidate Outcomes")
    lines.append(f"- outcome_report: {summary['close_candidate_outcomes_report']}")
    lines.append(f"- next_high_return_mean: {summary['close_candidate_outcomes'].get('next_high_return_mean')}")
    lines.append(f"- next_close_return_mean: {summary['close_candidate_outcomes'].get('next_close_return_mean')}")
    lines.append(f"- next_close_positive_rate: {summary['close_candidate_outcomes'].get('next_close_positive_rate')}")
    lines.append("")
    lines.append("## Pair Comparison")
    lines.append(f"- pair_report: {summary['pair_comparison_report']}")
    lines.append(f"- pair_recommendation: {summary['pair_comparison'].get('recommendation')}")
    lines.append("")
    lines.append("## Next Step")
    lines.append(f"- {summary['next_step']}")
    return "\n".join(lines) + "\n"


def run_btst_recurring_shadow_close_bundle(
    *,
    report_dir: str | Path,
    recurring_frontier_report: str | Path,
    outcome_report: str | Path,
    close_candidate_ticker: str,
    intraday_control_ticker: str,
    intraday_control_outcomes_report: str | Path,
    close_release_json: str | Path,
    close_release_md: str | Path,
    close_outcomes_json: str | Path,
    close_outcomes_md: str | Path,
    pair_json: str | Path,
    pair_md: str | Path,
) -> dict[str, Any]:
    close_release = analyze_recurring_frontier_ticker_release(
        report_dir,
        recurring_frontier_report=recurring_frontier_report,
        ticker=close_candidate_ticker,
    )
    close_release_report = _write_json(close_release_json, close_release)
    _write_markdown(close_release_md, render_recurring_frontier_ticker_release_markdown(close_release))

    close_outcomes = analyze_recurring_frontier_ticker_release_outcomes(close_release_report, outcome_report)
    close_candidate_outcomes_report = _write_json(close_outcomes_json, close_outcomes)
    _write_markdown(close_outcomes_md, render_recurring_frontier_ticker_release_outcomes_markdown(close_outcomes))

    pair_comparison = analyze_recurring_frontier_release_pair_comparison(
        intraday_control_outcomes_report,
        close_candidate_outcomes_report,
    )
    pair_comparison_report = _write_json(pair_json, pair_comparison)
    _write_markdown(pair_md, render_recurring_frontier_release_pair_comparison_markdown(pair_comparison))

    summary = {
        "report_dir": str(Path(report_dir).expanduser().resolve()),
        "recurring_frontier_report": str(Path(recurring_frontier_report).expanduser().resolve()),
        "outcome_report": str(Path(outcome_report).expanduser().resolve()),
        "close_candidate_ticker": close_candidate_ticker,
        "intraday_control_ticker": intraday_control_ticker,
        "close_candidate_release_report": close_release_report,
        "close_candidate_outcomes_report": close_candidate_outcomes_report,
        "pair_comparison_report": pair_comparison_report,
        "close_candidate_release": close_release,
        "close_candidate_outcomes": close_outcomes,
        "pair_comparison": pair_comparison,
        "recommendation": (
            f"{close_candidate_ticker} 已被整理成可直接执行的 recurring shadow close bundle。"
            f" 若下一轮继续推进 close-candidate shadow replay，应直接复用该 bundle，并与 {intraday_control_ticker} 的 intraday control 结果成对比较。"
        ),
        "next_step": f"复跑 {close_candidate_ticker} close-candidate shadow replay，并把结果与 {intraday_control_ticker} intraday control 一起回接到 rollout governance。",
    }
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a runnable bundle for the recurring shadow close-candidate lane.")
    parser.add_argument("--report-dir", default=str(DEFAULT_REPORT_DIR))
    parser.add_argument("--recurring-frontier-report", default=str(DEFAULT_RECURRING_FRONTIER_REPORT))
    parser.add_argument("--outcome-report", default=str(DEFAULT_OUTCOME_REPORT))
    parser.add_argument("--close-candidate-ticker", default=DEFAULT_CLOSE_CANDIDATE_TICKER)
    parser.add_argument("--intraday-control-ticker", default=DEFAULT_INTRADAY_CONTROL_TICKER)
    parser.add_argument("--intraday-control-outcomes-report", default=str(DEFAULT_INTRADAY_CONTROL_OUTCOMES))
    parser.add_argument("--close-release-json", default=str(DEFAULT_CLOSE_RELEASE_JSON))
    parser.add_argument("--close-release-md", default=str(DEFAULT_CLOSE_RELEASE_MD))
    parser.add_argument("--close-outcomes-json", default=str(DEFAULT_CLOSE_OUTCOMES_JSON))
    parser.add_argument("--close-outcomes-md", default=str(DEFAULT_CLOSE_OUTCOMES_MD))
    parser.add_argument("--pair-json", default=str(DEFAULT_PAIR_JSON))
    parser.add_argument("--pair-md", default=str(DEFAULT_PAIR_MD))
    parser.add_argument("--summary-json", default=str(DEFAULT_SUMMARY_JSON))
    parser.add_argument("--summary-md", default=str(DEFAULT_SUMMARY_MD))
    args = parser.parse_args()

    summary = run_btst_recurring_shadow_close_bundle(
        report_dir=args.report_dir,
        recurring_frontier_report=args.recurring_frontier_report,
        outcome_report=args.outcome_report,
        close_candidate_ticker=args.close_candidate_ticker,
        intraday_control_ticker=args.intraday_control_ticker,
        intraday_control_outcomes_report=args.intraday_control_outcomes_report,
        close_release_json=args.close_release_json,
        close_release_md=args.close_release_md,
        close_outcomes_json=args.close_outcomes_json,
        close_outcomes_md=args.close_outcomes_md,
        pair_json=args.pair_json,
        pair_md=args.pair_md,
    )
    _write_json(args.summary_json, summary)
    _write_markdown(args.summary_md, _render_summary_markdown(summary))
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
