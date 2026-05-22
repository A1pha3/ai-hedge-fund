from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from statistics import mean
from typing import Any


REPORTS_DIR = Path("data/reports")
DEFAULT_INPUT_JSON = REPORTS_DIR / "btst_5d_15pct_objective_monitor_latest.json"
DEFAULT_OUTPUT_JSON = REPORTS_DIR / "btst_5d_15pct_false_negative_dossier_latest.json"
DEFAULT_OUTPUT_MD = REPORTS_DIR / "btst_5d_15pct_false_negative_dossier_latest.md"


def _load_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _summarize(values: list[float]) -> dict[str, float | int | None]:
    if not values:
        return {"count": 0, "min": None, "max": None, "mean": None}
    return {
        "count": len(values),
        "min": round(min(values), 4),
        "max": round(max(values), 4),
        "mean": round(mean(values), 4),
    }


def analyze_btst_5d_15pct_false_negative_dossier(input_json: str | Path) -> dict[str, Any]:
    payload = _load_json(input_json)
    rows = [dict(row) for row in list(payload.get("false_negative_strict_goal_rows") or [])]
    rows.sort(
        key=lambda row: (
            float(row.get("max_future_high_return_2_5d") or -999.0),
            float(row.get("score_target") or -999.0),
            str(row.get("trade_date") or ""),
            str(row.get("ticker") or ""),
        ),
        reverse=True,
    )

    decision_counts = Counter(str(row.get("decision") or "unknown") for row in rows)
    candidate_source_counts = Counter(str(row.get("candidate_source") or "unknown") for row in rows)
    ticker_counts = Counter(str(row.get("ticker") or "unknown") for row in rows)
    repeating_tickers = sorted([ticker for ticker, count in ticker_counts.items() if ticker and ticker != "unknown" and count >= 2])
    max_future_high_returns = [float(row["max_future_high_return_2_5d"]) for row in rows if row.get("max_future_high_return_2_5d") is not None]
    time_to_hit_values = [float(row["time_to_hit_15pct"]) for row in rows if row.get("time_to_hit_15pct") is not None]
    score_target_values = [float(row["score_target"]) for row in rows if row.get("score_target") is not None]

    if not rows:
        recommendation = "当前 5D/+15% false negative 列表为空。"
    elif repeating_tickers:
        lead_ticker = repeating_tickers[0]
        lead_source = next((str(row.get("candidate_source") or "unknown") for row in rows if str(row.get("ticker") or "") == lead_ticker), "unknown")
        recommendation = f"优先复盘重复出现的 false negative：{lead_ticker}，并从 {lead_source} 这条候选来源切入做针对性因子/门控诊断。"
    else:
        lead_source = candidate_source_counts.most_common(1)[0][0] if candidate_source_counts else "unknown"
        recommendation = f"当前 false negative 主要集中在 {lead_source}，应先围绕这条候选来源做结构化诊断。"

    return {
        "input_json": str(Path(input_json).expanduser().resolve()),
        "false_negative_count": len(rows),
        "decision_counts": dict(decision_counts),
        "candidate_source_counts": dict(candidate_source_counts),
        "ticker_counts": dict(ticker_counts),
        "repeating_tickers": repeating_tickers,
        "max_future_high_return_2_5d_summary": _summarize(max_future_high_returns),
        "time_to_hit_15pct_summary": _summarize(time_to_hit_values),
        "score_target_summary": _summarize(score_target_values),
        "rows": rows,
        "recommendation": recommendation,
    }


def render_btst_5d_15pct_false_negative_dossier_markdown(analysis: dict[str, Any]) -> str:
    lines = [
        "# BTST 5D / +15% False Negative Dossier",
        "",
        "## Overview",
        f"- false_negative_count: {analysis.get('false_negative_count')}",
        f"- decision_counts: {analysis.get('decision_counts')}",
        f"- candidate_source_counts: {analysis.get('candidate_source_counts')}",
        f"- ticker_counts: {analysis.get('ticker_counts')}",
        f"- repeating_tickers: {analysis.get('repeating_tickers')}",
        "",
        "## Metric Summary",
        f"- max_future_high_return_2_5d_summary: {analysis.get('max_future_high_return_2_5d_summary')}",
        f"- time_to_hit_15pct_summary: {analysis.get('time_to_hit_15pct_summary')}",
        f"- score_target_summary: {analysis.get('score_target_summary')}",
        "",
        "## Rows",
    ]
    rows = list(analysis.get("rows") or [])
    for row in rows:
        lines.append(
            f"- {row.get('trade_date')} {row.get('ticker')}: decision={row.get('decision')}, candidate_source={row.get('candidate_source')}, score_target={row.get('score_target')}, max_future_high_return_2_5d={row.get('max_future_high_return_2_5d')}, time_to_hit_15pct={row.get('time_to_hit_15pct')}"
        )
    if not rows:
        lines.append("- none")
    lines.extend(["", "## Recommendation", f"- {analysis.get('recommendation')}", ""])
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarize repeating 5D/+15% BTST false-negative patterns from the objective monitor output.")
    parser.add_argument("--input-json", default=str(DEFAULT_INPUT_JSON))
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--output-md", default=str(DEFAULT_OUTPUT_MD))
    args = parser.parse_args()

    analysis = analyze_btst_5d_15pct_false_negative_dossier(args.input_json)
    output_json = Path(args.output_json).expanduser().resolve()
    output_md = Path(args.output_md).expanduser().resolve()
    output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_md.write_text(render_btst_5d_15pct_false_negative_dossier_markdown(analysis), encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
