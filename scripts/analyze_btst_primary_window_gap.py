from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


REPORTS_DIR = Path("data/reports")
DEFAULT_PRIMARY_ROLL_FORWARD_PATH = REPORTS_DIR / "p4_primary_roll_forward_validation_001309_20260330.json"
DEFAULT_MULTI_WINDOW_CANDIDATE_REPORT_PATH = REPORTS_DIR / "multi_window_short_trade_role_candidates_20260329.json"
DEFAULT_OUTPUT_JSON = REPORTS_DIR / "p6_primary_window_gap_001309_20260330.json"
DEFAULT_OUTPUT_MD = REPORTS_DIR / "p6_primary_window_gap_001309_20260330.md"


def _load_json(path: str | Path) -> dict[str, Any]:
    resolved = Path(path).expanduser().resolve()
    return json.loads(resolved.read_text(encoding="utf-8"))


def _find_candidate_row(candidate_report: dict[str, Any], ticker: str) -> dict[str, Any]:
    for row in list(candidate_report.get("candidates") or []):
        if str(row.get("ticker") or "") == ticker:
            return dict(row)
    return {}


def analyze_btst_primary_window_gap(
    primary_roll_forward_path: str | Path,
    *,
    candidate_report_path: str | Path,
    ticker: str = "001309",
) -> dict[str, Any]:
    normalized_ticker = str(ticker).strip()
    primary_roll = _load_json(primary_roll_forward_path)
    candidate_report = _load_json(candidate_report_path)
    candidate_row = _find_candidate_row(candidate_report, normalized_ticker)

    distinct_window_count = int(primary_roll.get("distinct_window_count") or 0)
    target_window_count = 2
    missing_window_count = max(0, target_window_count - distinct_window_count)
    window_keys = list(primary_roll.get("window_keys") or candidate_row.get("window_keys") or [])
    transition_locality = str(primary_roll.get("transition_locality") or candidate_row.get("transition_locality") or "unknown")

    missing_evidence = []
    if missing_window_count > 0:
        missing_evidence.append(f"至少还缺 {missing_window_count} 个新增独立窗口，才能进入默认升级评审。")
    if transition_locality != "multi_window_stable":
        missing_evidence.append("当前仍是 emergent_local_baseline，尚未形成跨窗口稳定 short-trade 角色。")

    candidate_window_sources = [
        {
            "source_type": "existing_local_window",
            "window_key": key,
            "status": "already_counted",
            "why": "当前窗口已贡献 primary follow-through 样本，不能重复计作独立窗口。",
        }
        for key in window_keys
    ]

    next_step_commands = [
        "围绕 001309 所在 ticker，优先在一个新增独立 paper_trading_window 报告中寻找 short_trade_boundary_near_miss 或 promotion 样本。",
        "新增窗口若仍满足 changed_non_target_case_count=0、next_close_return_mean>0、next_close_positive_rate>=0.75，才允许进入默认升级评审。",
        "若新增窗口里 001309 不再出现 short-trade 角色，应维持 primary_roll_forward_only，而不是强行补默认升级叙事。",
    ]

    recommendation = (
        f"{normalized_ticker} 当前并不缺主实验 guardrails，而是缺独立窗口证据。"
        f" 在 distinct_window_count={distinct_window_count} 仍小于 {target_window_count} 之前，"
        "后续工作应优先补窗口，而不是继续讨论默认升级。"
    )

    return {
        "generated_on": primary_roll.get("generated_on"),
        "primary_roll_forward": str(Path(primary_roll_forward_path).expanduser().resolve()),
        "candidate_report": str(Path(candidate_report_path).expanduser().resolve()),
        "ticker": normalized_ticker,
        "distinct_window_count": distinct_window_count,
        "target_window_count": target_window_count,
        "missing_window_count": missing_window_count,
        "window_keys": window_keys,
        "transition_locality": transition_locality,
        "missing_evidence": missing_evidence,
        "candidate_window_sources": candidate_window_sources,
        "next_step_commands": next_step_commands,
        "recommendation": recommendation,
    }


def render_btst_primary_window_gap_markdown(analysis: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# BTST Primary Window Gap")
    lines.append("")
    lines.append("## Overview")
    lines.append(f"- ticker: {analysis['ticker']}")
    lines.append(f"- distinct_window_count: {analysis['distinct_window_count']}")
    lines.append(f"- target_window_count: {analysis['target_window_count']}")
    lines.append(f"- missing_window_count: {analysis['missing_window_count']}")
    lines.append(f"- transition_locality: {analysis['transition_locality']}")
    lines.append("")
    lines.append("## Missing Evidence")
    for item in analysis["missing_evidence"]:
        lines.append(f"- {item}")
    if not analysis["missing_evidence"]:
        lines.append("- none")
    lines.append("")
    lines.append("## Next Steps")
    for item in analysis["next_step_commands"]:
        lines.append(f"- {item}")
    lines.append("")
    lines.append("## Recommendation")
    lines.append(f"- {analysis['recommendation']}")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Explain the remaining independent-window evidence gap for the BTST primary roll-forward lane.")
    parser.add_argument("--primary-roll-forward", default=str(DEFAULT_PRIMARY_ROLL_FORWARD_PATH))
    parser.add_argument("--candidate-report", default=str(DEFAULT_MULTI_WINDOW_CANDIDATE_REPORT_PATH))
    parser.add_argument("--ticker", default="001309")
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--output-md", default=str(DEFAULT_OUTPUT_MD))
    args = parser.parse_args()

    analysis = analyze_btst_primary_window_gap(
        args.primary_roll_forward,
        candidate_report_path=args.candidate_report,
        ticker=args.ticker,
    )
    output_json = Path(args.output_json).expanduser().resolve()
    output_md = Path(args.output_md).expanduser().resolve()
    output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_md.write_text(render_btst_primary_window_gap_markdown(analysis), encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()