from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _load_json(path: str | Path) -> dict[str, Any]:
    resolved = Path(path).expanduser().resolve()
    return json.loads(resolved.read_text(encoding="utf-8"))


def _delta(left: dict[str, Any], right: dict[str, Any], key: str) -> float | None:
    left_value = left.get(key)
    right_value = right.get(key)
    if left_value is None or right_value is None:
        return None
    return round(float(left_value) - float(right_value), 4)


def render_case_based_short_trade_entry_pair_comparison_markdown(analysis: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# Case-Based Short Trade Entry Pair Comparison")
    lines.append("")
    lines.append("## Scope")
    lines.append(f"- left_report: {analysis['left_report']}")
    lines.append(f"- right_report: {analysis['right_report']}")
    lines.append(f"- left_ticker: {analysis['left_ticker']}")
    lines.append(f"- right_ticker: {analysis['right_ticker']}")
    lines.append("")
    lines.append("## Comparison")
    for key, value in analysis["comparison"].items():
        lines.append(f"- {key}: {value}")
    lines.append("")
    lines.append("## Recommendation")
    lines.append(f"- {analysis['recommendation']}")
    return "\n".join(lines) + "\n"


def analyze_case_based_short_trade_entry_pair_comparison(
    left_report: str | Path,
    right_report: str | Path,
) -> dict[str, Any]:
    left = _load_json(left_report)
    right = _load_json(right_report)
    left_ticker = str(left.get("ticker") or left.get("target_cases", [{}])[0].get("ticker") or "")
    right_ticker = str(right.get("ticker") or right.get("target_cases", [{}])[0].get("ticker") or "")

    comparison = {
        "adjustment_cost_delta": _delta(left, right, "adjustment_cost"),
        "target_case_count_delta": _delta(left, right, "target_case_count"),
        "next_high_return_mean_delta": _delta(left, right, "next_high_return_mean"),
        "next_close_return_mean_delta": _delta(left, right, "next_close_return_mean"),
        "next_close_positive_rate_delta": _delta(left, right, "next_close_positive_rate"),
    }

    left_cost = float(left.get("adjustment_cost") or 999.0)
    right_cost = float(right.get("adjustment_cost") or 999.0)
    left_close = float(left.get("next_close_return_mean") or -999.0)
    right_close = float(right.get("next_close_return_mean") or -999.0)
    left_positive = float(left.get("next_close_positive_rate") or -999.0)
    right_positive = float(right.get("next_close_positive_rate") or -999.0)
    left_cases = int(left.get("target_case_count") or 0)
    right_cases = int(right.get("target_case_count") or 0)

    if left_cost < right_cost and left_close > right_close and left_positive >= right_positive and left_cases >= right_cases:
        recommendation = (
            f"{left_ticker} 更适合作为下一轮的第一 case-based 入口：它需要更低的 adjustment_cost，"
            f"且 close continuation 和样本数都不弱于 {right_ticker}。"
        )
    elif left_close > right_close:
        recommendation = f"{left_ticker} 的 follow-through 更强，应优先继续推进。"
    else:
        recommendation = f"{left_ticker} 与 {right_ticker} 仍需继续观察，当前没有足够清晰的先后顺序。"

    return {
        "left_report": str(Path(left_report).expanduser().resolve()),
        "right_report": str(Path(right_report).expanduser().resolve()),
        "left_ticker": left_ticker,
        "right_ticker": right_ticker,
        "left_summary": left,
        "right_summary": right,
        "comparison": comparison,
        "recommendation": recommendation,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare two case-based short-trade release entries.")
    parser.add_argument("--left-report", required=True)
    parser.add_argument("--right-report", required=True)
    parser.add_argument("--output-json", default="")
    parser.add_argument("--output-md", default="")
    args = parser.parse_args()

    analysis = analyze_case_based_short_trade_entry_pair_comparison(args.left_report, args.right_report)
    if args.output_json:
        output_json = Path(args.output_json).expanduser().resolve()
        output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.output_md:
        output_md = Path(args.output_md).expanduser().resolve()
        output_md.write_text(render_case_based_short_trade_entry_pair_comparison_markdown(analysis), encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()