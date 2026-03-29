from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _load_json(path: str | Path) -> dict[str, Any]:
    resolved = Path(path).expanduser().resolve()
    return json.loads(resolved.read_text(encoding="utf-8"))


def _metric_delta(left: dict[str, Any], right: dict[str, Any], key: str) -> float | None:
    left_value = left.get(key)
    right_value = right.get(key)
    if left_value is None or right_value is None:
        return None
    return round(float(left_value) - float(right_value), 4)


def render_short_trade_boundary_frontier_pair_comparison_markdown(analysis: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# Short Trade Boundary Frontier Pair Comparison")
    lines.append("")
    lines.append("## Scope")
    lines.append(f"- source_report: {analysis['source_report']}")
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


def analyze_short_trade_boundary_frontier_pair_comparison(
    dossier_report: str | Path,
    *,
    left_ticker: str,
    right_ticker: str,
) -> dict[str, Any]:
    analysis = _load_json(dossier_report)
    dossiers = {str(row.get("ticker") or ""): row for row in list(analysis.get("dossiers") or [])}
    left = dict(dossiers.get(str(left_ticker).strip()) or {})
    right = dict(dossiers.get(str(right_ticker).strip()) or {})
    if not left:
        raise ValueError(f"Ticker not found in dossier report: {left_ticker}")
    if not right:
        raise ValueError(f"Ticker not found in dossier report: {right_ticker}")

    comparison = {
        "priority_rank_delta": _metric_delta(right, left, "priority_rank"),
        "minimal_adjustment_cost_delta": _metric_delta(left, right, "minimal_adjustment_cost"),
        "next_high_return_mean_delta": _metric_delta(left, right, "next_high_return_mean"),
        "next_close_return_mean_delta": _metric_delta(left, right, "next_close_return_mean"),
        "next_close_positive_rate_delta": _metric_delta(left, right, "next_close_positive_rate"),
        "pattern_label_pair": [left.get("pattern_label"), right.get("pattern_label")],
    }

    if float(left.get("minimal_adjustment_cost") or 999.0) < float(right.get("minimal_adjustment_cost") or 999.0) and float(left.get("next_high_return_mean") or -999.0) > float(right.get("next_high_return_mean") or -999.0):
        recommendation = (
            f"{left_ticker} 仍应排在 {right_ticker} 之前，因为它同时具备更低 rescue cost 和更高 intraday upside。"
        )
    elif float(left.get("next_close_positive_rate") or -999.0) < float(right.get("next_close_positive_rate") or -999.0):
        recommendation = (
            f"{right_ticker} 更适合作为 close continuation 对照样本，而 {left_ticker} 更像 intraday frontier。"
        )
    else:
        recommendation = f"{left_ticker} 与 {right_ticker} 仍需继续观察，当前没有单一维度足够覆盖两者差异。"

    return {
        "source_report": str(Path(dossier_report).expanduser().resolve()),
        "left_ticker": str(left_ticker).strip(),
        "right_ticker": str(right_ticker).strip(),
        "left_dossier": left,
        "right_dossier": right,
        "comparison": comparison,
        "recommendation": recommendation,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare two recurring frontier ticker dossiers.")
    parser.add_argument("--dossier-report", required=True)
    parser.add_argument("--left-ticker", required=True)
    parser.add_argument("--right-ticker", required=True)
    parser.add_argument("--output-json", default="")
    parser.add_argument("--output-md", default="")
    args = parser.parse_args()

    analysis = analyze_short_trade_boundary_frontier_pair_comparison(
        args.dossier_report,
        left_ticker=args.left_ticker,
        right_ticker=args.right_ticker,
    )
    if args.output_json:
        output_json = Path(args.output_json).expanduser().resolve()
        output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.output_md:
        output_md = Path(args.output_md).expanduser().resolve()
        output_md.write_text(render_short_trade_boundary_frontier_pair_comparison_markdown(analysis), encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()