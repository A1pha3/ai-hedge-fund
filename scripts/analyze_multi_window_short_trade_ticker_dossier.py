from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _load_json(path: str | Path) -> dict[str, Any]:
    resolved = Path(path).expanduser().resolve()
    return json.loads(resolved.read_text(encoding="utf-8"))


def render_multi_window_short_trade_ticker_dossier_markdown(analysis: dict[str, Any]) -> str:
    dossier = analysis["dossier"]
    lines: list[str] = []
    lines.append(f"# Multi-Window Short Trade Ticker Dossier: {dossier['ticker']}")
    lines.append("")
    lines.append("## Overview")
    lines.append(f"- source_report: {analysis['source_report']}")
    lines.append(f"- outcome_report: {analysis['outcome_report']}")
    lines.append(f"- transition_locality: {dossier['transition_locality']}")
    lines.append(f"- short_trade_trade_date_count: {dossier['short_trade_trade_date_count']}")
    lines.append(f"- distinct_window_count: {dossier['distinct_window_count']}")
    lines.append(f"- distinct_report_count: {dossier['distinct_report_count']}")
    lines.append(f"- role_counts: {dossier['role_counts']}")
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


def analyze_multi_window_short_trade_ticker_dossier(
    candidate_report: str | Path,
    outcome_report: str | Path,
    *,
    ticker: str,
) -> dict[str, Any]:
    candidates = _load_json(candidate_report)
    outcomes = _load_json(outcome_report)
    normalized_ticker = str(ticker).strip()

    candidate_rows = [row for row in list(candidates.get("candidates") or []) if str(row.get("ticker") or "") == normalized_ticker]
    if not candidate_rows:
        raise ValueError(f"Ticker not found in candidate report: {normalized_ticker}")
    outcome_rows = [row for row in list(outcomes.get("rows") or []) if str(row.get("ticker") or "") == normalized_ticker and str(row.get("data_status") or "") == "ok"]

    next_open_values = [float(row.get("next_open_return") or 0.0) for row in outcome_rows if row.get("next_open_return") is not None]
    next_high_values = [float(row.get("next_high_return") or 0.0) for row in outcome_rows if row.get("next_high_return") is not None]
    next_close_values = [float(row.get("next_close_return") or 0.0) for row in outcome_rows if row.get("next_close_return") is not None]
    next_high_hit_threshold = float(outcomes.get("next_high_hit_threshold") or 0.02)
    next_high_hit_rate = None if not next_high_values else round(sum(1 for value in next_high_values if value >= next_high_hit_threshold) / len(next_high_values), 4)
    next_close_positive_rate = None if not next_close_values else round(sum(1 for value in next_close_values if value > 0) / len(next_close_values), 4)

    candidate = dict(candidate_rows[0])
    dominant_role_counts = dict(candidate.get("role_counts") or {})
    if "short_trade_boundary_near_miss" in dominant_role_counts and (next_close_positive_rate or 0.0) >= 0.6:
        pattern_label = "emergent near-miss with close continuation"
        recommendation = f"{normalized_ticker} 更适合作为 near-miss close-continuation baseline 继续观察，优先级高于纯 intraday 对照样本。"
    elif "short_trade_boundary_near_miss" in dominant_role_counts and (next_high_values and sum(next_high_values) / len(next_high_values) >= next_high_hit_threshold):
        pattern_label = "emergent near-miss with intraday upside"
        recommendation = f"{normalized_ticker} 更适合作为 near-miss intraday baseline 观察，暂不应直接上升为默认 release profile。"
    elif "short_trade_boundary_rejected" in dominant_role_counts:
        pattern_label = "emergent rejected frontier"
        recommendation = f"{normalized_ticker} 当前仍更适合作为 rejected recurring frontier baseline，而不是 near-miss baseline。"
    else:
        pattern_label = "emergent short-trade observation"
        recommendation = f"{normalized_ticker} 当前仍属于窗口内观察样本，需要更多窗口证据。"

    dossier = {
        **candidate,
        "next_open_return_mean": round(sum(next_open_values) / len(next_open_values), 4) if next_open_values else None,
        "next_high_return_mean": round(sum(next_high_values) / len(next_high_values), 4) if next_high_values else None,
        "next_close_return_mean": round(sum(next_close_values) / len(next_close_values), 4) if next_close_values else None,
        "next_high_hit_rate_at_threshold": next_high_hit_rate,
        "next_close_positive_rate": next_close_positive_rate,
        "pattern_label": pattern_label,
        "top_outcome_case": max(outcome_rows, key=lambda row: float(row.get("next_high_return") or -999.0), default=None),
        "worst_close_case": min(outcome_rows, key=lambda row: float(row.get("next_close_return") or 999.0), default=None),
    }

    return {
        "source_report": str(Path(candidate_report).expanduser().resolve()),
        "outcome_report": str(Path(outcome_report).expanduser().resolve()),
        "dossier": dossier,
        "recommendation": recommendation,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract a single ticker dossier from the multi-window short-trade candidate scan.")
    parser.add_argument("--candidate-report", required=True)
    parser.add_argument("--outcome-report", required=True)
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--output-json", default="")
    parser.add_argument("--output-md", default="")
    args = parser.parse_args()

    analysis = analyze_multi_window_short_trade_ticker_dossier(
        args.candidate_report,
        args.outcome_report,
        ticker=args.ticker,
    )
    if args.output_json:
        output_json = Path(args.output_json).expanduser().resolve()
        output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.output_md:
        output_md = Path(args.output_md).expanduser().resolve()
        output_md.write_text(render_multi_window_short_trade_ticker_dossier_markdown(analysis), encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()