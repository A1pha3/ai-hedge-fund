from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import mean, median

from src.execution.daily_pipeline import FAST_AGENT_SCORE_THRESHOLD, WATCHLIST_SCORE_THRESHOLD
from src.screening.signal_fusion import _get_neutral_mean_reversion_mode, _quality_first_guard_enabled
from src.screening.strategy_scorer import (
    EVENT_SENTIMENT_MAX_CANDIDATES,
    FUNDAMENTAL_SCORE_MAX_CANDIDATES,
    HEAVY_SCORE_MIN_PROVISIONAL_SCORE,
    TECHNICAL_SCORE_MAX_CANDIDATES,
)


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    return rows


def _build_day_summary(row: dict) -> dict:
    plan = row.get("current_plan", {})
    risk_metrics = plan.get("risk_metrics", {})
    counts = risk_metrics.get("counts", {})
    funnel = risk_metrics.get("funnel_diagnostics", {})
    layer_b = funnel.get("filters", {}).get("layer_b", {})
    watchlist_filter = funnel.get("filters", {}).get("watchlist", {})
    buy_orders_filter = funnel.get("filters", {}).get("buy_orders", {})

    filtered = layer_b.get("tickers", [])
    selected = layer_b.get("selected_tickers", [])
    score_values = [float(item.get("score_b", 0.0) or 0.0) for item in filtered if item.get("score_b") is not None]
    watch_band = [item for item in filtered if 0.35 <= float(item.get("score_b", 0.0) or 0.0) < FAST_AGENT_SCORE_THRESHOLD]
    near_threshold = [item for item in filtered if 0.30 <= float(item.get("score_b", 0.0) or 0.0) < FAST_AGENT_SCORE_THRESHOLD]
    zero_count = sum(1 for item in filtered if float(item.get("score_b", 0.0) or 0.0) == 0.0)
    negative_count = sum(1 for item in filtered if float(item.get("score_b", 0.0) or 0.0) < 0.0)

    return {
        "trade_date": row.get("trade_date"),
        "counts": {
            "layer_a_count": int(counts.get("layer_a_count", 0) or 0),
            "layer_b_count": int(counts.get("layer_b_count", 0) or 0),
            "layer_c_count": int(counts.get("layer_c_count", 0) or 0),
            "watchlist_count": int(counts.get("watchlist_count", 0) or 0),
            "buy_order_count": int(counts.get("buy_order_count", 0) or 0),
            "sell_order_count": int(counts.get("sell_order_count", 0) or 0),
        },
        "selected_layer_b_tickers": selected,
        "layer_b_filter_summary": {
            "filtered_count": int(layer_b.get("filtered_count", len(filtered)) or 0),
            "max_filtered_score_b": max(score_values) if score_values else None,
            "median_filtered_score_b": median(score_values) if score_values else None,
            "mean_filtered_score_b": mean(score_values) if score_values else None,
            "watch_band_count_035_to_gate": len(watch_band),
            "near_threshold_count_030_to_gate": len(near_threshold),
            "zero_count": zero_count,
            "negative_count": negative_count,
            "top_filtered_candidates": filtered[:10],
        },
        "watchlist_filter_summary": {
            "filtered_count": int(watchlist_filter.get("filtered_count", 0) or 0),
            "reason_counts": watchlist_filter.get("reason_counts", {}),
            "selected_tickers": watchlist_filter.get("selected_tickers", []),
        },
        "buy_order_filter_summary": {
            "filtered_count": int(buy_orders_filter.get("filtered_count", 0) or 0),
            "reason_counts": buy_orders_filter.get("reason_counts", {}),
            "selected_tickers": buy_orders_filter.get("selected_tickers", []),
        },
        "logic_scores": plan.get("logic_scores", {}),
        "buy_orders": plan.get("buy_orders", []),
        "executed_trades": row.get("executed_trades", {}),
    }


def analyze_report(report_dir: Path) -> dict:
    session_summary = _read_json(report_dir / "session_summary.json")
    daily_rows = _read_jsonl(report_dir / "daily_events.jsonl")
    day_summaries = [_build_day_summary(row) for row in daily_rows]

    layer_b_counts = [item["counts"]["layer_b_count"] for item in day_summaries]
    watchlist_counts = [item["counts"]["watchlist_count"] for item in day_summaries]
    buy_counts = [item["counts"]["buy_order_count"] for item in day_summaries]

    return {
        "report_dir": str(report_dir),
        "session_overview": {
            "mode": session_summary.get("mode"),
            "start_date": session_summary.get("start_date"),
            "end_date": session_summary.get("end_date"),
            "model_provider": session_summary.get("model_provider"),
            "model_name": session_summary.get("model_name"),
            "daily_event_stats": session_summary.get("daily_event_stats", {}),
            "final_positions": {
                ticker: int(position.get("long", 0) or 0)
                for ticker, position in session_summary.get("final_portfolio_snapshot", {}).get("positions", {}).items()
            },
        },
        "current_code_defaults": {
            "fast_agent_score_threshold": FAST_AGENT_SCORE_THRESHOLD,
            "watchlist_score_threshold": WATCHLIST_SCORE_THRESHOLD,
            "technical_score_max_candidates": TECHNICAL_SCORE_MAX_CANDIDATES,
            "fundamental_score_max_candidates": FUNDAMENTAL_SCORE_MAX_CANDIDATES,
            "event_sentiment_max_candidates": EVENT_SENTIMENT_MAX_CANDIDATES,
            "heavy_score_min_provisional_score": HEAVY_SCORE_MIN_PROVISIONAL_SCORE,
            "neutral_mean_reversion_mode": _get_neutral_mean_reversion_mode(),
            "quality_first_guard_enabled": _quality_first_guard_enabled(),
        },
        "aggregate_diagnostics": {
            "trade_date_count": len(day_summaries),
            "avg_layer_b_count": mean(layer_b_counts) if layer_b_counts else 0.0,
            "avg_watchlist_count": mean(watchlist_counts) if watchlist_counts else 0.0,
            "avg_buy_order_count": mean(buy_counts) if buy_counts else 0.0,
            "nonzero_layer_b_days": sum(1 for value in layer_b_counts if value > 0),
            "single_or_two_name_layer_b_days": sum(1 for value in layer_b_counts if value in {1, 2}),
        },
        "daily_diagnostics": day_summaries,
    }


def _render_markdown(analysis: dict) -> str:
    overview = analysis["session_overview"]
    defaults = analysis["current_code_defaults"]
    aggregate = analysis["aggregate_diagnostics"]
    lines = [
        "# Layer B 冷分布诊断报告",
        "",
        f"- report_dir: {analysis['report_dir']}",
        f"- mode: {overview['mode']}",
        f"- window: {overview['start_date']} -> {overview['end_date']}",
        f"- model: {overview['model_provider']} / {overview['model_name']}",
        "",
        "## 当前代码默认参数",
        f"- fast_agent_score_threshold: {defaults['fast_agent_score_threshold']}",
        f"- watchlist_score_threshold: {defaults['watchlist_score_threshold']}",
        f"- technical_score_max_candidates: {defaults['technical_score_max_candidates']}",
        f"- fundamental_score_max_candidates: {defaults['fundamental_score_max_candidates']}",
        f"- event_sentiment_max_candidates: {defaults['event_sentiment_max_candidates']}",
        f"- heavy_score_min_provisional_score: {defaults['heavy_score_min_provisional_score']}",
        f"- neutral_mean_reversion_mode: {defaults['neutral_mean_reversion_mode']}",
        f"- quality_first_guard_enabled: {defaults['quality_first_guard_enabled']}",
        "",
        "## 窗口级结论",
        f"- trade_date_count: {aggregate['trade_date_count']}",
        f"- avg_layer_b_count: {aggregate['avg_layer_b_count']:.4f}",
        f"- avg_watchlist_count: {aggregate['avg_watchlist_count']:.4f}",
        f"- avg_buy_order_count: {aggregate['avg_buy_order_count']:.4f}",
        f"- nonzero_layer_b_days: {aggregate['nonzero_layer_b_days']}",
        f"- single_or_two_name_layer_b_days: {aggregate['single_or_two_name_layer_b_days']}",
        f"- final_positions: {overview['final_positions']}",
        "",
        "## 逐日明细",
    ]

    for item in analysis["daily_diagnostics"]:
        counts = item["counts"]
        layer_b = item["layer_b_filter_summary"]
        watchlist = item["watchlist_filter_summary"]
        buy_order = item["buy_order_filter_summary"]
        lines.extend(
            [
                "",
                f"### {item['trade_date']}",
                f"- counts: {counts}",
                f"- selected_layer_b_tickers: {item['selected_layer_b_tickers']}",
                f"- max_filtered_score_b: {layer_b['max_filtered_score_b']}",
                f"- median_filtered_score_b: {layer_b['median_filtered_score_b']}",
                f"- mean_filtered_score_b: {layer_b['mean_filtered_score_b']}",
                f"- watch_band_count_035_to_gate: {layer_b['watch_band_count_035_to_gate']}",
                f"- near_threshold_count_030_to_gate: {layer_b['near_threshold_count_030_to_gate']}",
                f"- zero_count: {layer_b['zero_count']}",
                f"- negative_count: {layer_b['negative_count']}",
                f"- watchlist_filter_reason_counts: {watchlist['reason_counts']}",
                f"- buy_order_filter_reason_counts: {buy_order['reason_counts']}",
                f"- executed_trades: {item['executed_trades']}",
                f"- logic_scores: {item['logic_scores']}",
                "- top_filtered_candidates:",
            ]
        )
        for candidate in layer_b["top_filtered_candidates"]:
            lines.append(f"  - {candidate}")

    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze Layer B cold-distribution diagnostics from a clean report directory.")
    parser.add_argument("--report-dir", required=True, help="Path to a report directory that contains session_summary.json and daily_events.jsonl")
    parser.add_argument("--output-json", help="Optional output JSON path")
    parser.add_argument("--output-md", help="Optional output Markdown path")
    args = parser.parse_args()

    report_dir = Path(args.report_dir).expanduser().resolve()
    analysis = analyze_report(report_dir)

    if args.output_json:
        output_json = Path(args.output_json).expanduser().resolve()
        output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    markdown = _render_markdown(analysis)
    if args.output_md:
        output_md = Path(args.output_md).expanduser().resolve()
        output_md.write_text(markdown, encoding="utf-8")

    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()