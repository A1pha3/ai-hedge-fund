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


def render_recurring_frontier_release_pair_comparison_markdown(analysis: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# Recurring Frontier Release Pair Comparison")
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


def analyze_recurring_frontier_release_pair_comparison(
    left_report: str | Path,
    right_report: str | Path,
) -> dict[str, Any]:
    left = _load_json(left_report)
    right = _load_json(right_report)
    left_ticker = str(left.get("ticker") or "")
    right_ticker = str(right.get("ticker") or "")

    comparison = {
        "promoted_target_case_count_delta": _delta(left, right, "promoted_target_case_count"),
        "next_high_return_mean_delta": _delta(left, right, "next_high_return_mean"),
        "next_close_return_mean_delta": _delta(left, right, "next_close_return_mean"),
        "next_high_hit_rate_at_threshold_delta": _delta(left, right, "next_high_hit_rate_at_threshold"),
        "next_close_positive_rate_delta": _delta(left, right, "next_close_positive_rate"),
    }

    if float(left.get("next_high_return_mean") or -999.0) > float(right.get("next_high_return_mean") or -999.0) and float(left.get("next_close_positive_rate") or -999.0) < float(right.get("next_close_positive_rate") or -999.0):
        recommendation = (
            f"{left_ticker} 更适合作为 recurring release 的 intraday 主样本，"
            f"{right_ticker} 更适合作为 close-continuation 对照样本。"
        )
    elif float(left.get("next_close_return_mean") or -999.0) > float(right.get("next_close_return_mean") or -999.0):
        recommendation = f"{left_ticker} 在 release 后整体 follow-through 更强，应继续优先推进。"
    else:
        recommendation = f"{left_ticker} 与 {right_ticker} 的 release 表现仍需继续观察，当前没有足够清晰的分工。"

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
    parser = argparse.ArgumentParser(description="Compare two recurring frontier release outcome reports.")
    parser.add_argument("--left-report", required=True)
    parser.add_argument("--right-report", required=True)
    parser.add_argument("--output-json", default="")
    parser.add_argument("--output-md", default="")
    args = parser.parse_args()

    analysis = analyze_recurring_frontier_release_pair_comparison(args.left_report, args.right_report)
    if args.output_json:
        output_json = Path(args.output_json).expanduser().resolve()
        output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.output_md:
        output_md = Path(args.output_md).expanduser().resolve()
        output_md.write_text(render_recurring_frontier_release_pair_comparison_markdown(analysis), encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()