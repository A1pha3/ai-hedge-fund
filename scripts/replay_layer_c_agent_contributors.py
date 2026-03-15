from __future__ import annotations

import argparse
import json
from pathlib import Path

from dotenv import load_dotenv

from scripts.analyze_layer_b_backtest_variants import _resolve_model_selection
from src.backtesting.rule_variant_compare import make_pipeline_agent_runner
from src.execution.layer_c_aggregator import aggregate_layer_c_results
from src.screening.models import FusedScore
from src.utils.analysts import ANALYST_ORDER


load_dotenv(override=True)


def _load_pipeline_rows(path: Path) -> dict[str, dict]:
    rows: dict[str, dict] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        if payload.get("event") == "pipeline_day_timing":
            rows[str(payload["trade_date"])] = payload
    return rows


def _filters(row: dict) -> dict:
    return ((row.get("current_plan") or {}).get("funnel_diagnostics") or {}).get("filters", {})


def _selected_tickers(filter_payload: dict) -> list[str]:
    return [str(item) for item in (filter_payload.get("selected_tickers") or [])]


def _ticker_map(filter_payload: dict) -> dict[str, dict]:
    entries = filter_payload.get("tickers") or []
    return {str(item.get("ticker")): item for item in entries if isinstance(item, dict) and item.get("ticker")}


def _classify_score_b(score_b: float) -> str:
    if score_b > 0.50:
        return "strong_buy"
    if score_b >= 0.35:
        return "watch"
    if score_b >= -0.20:
        return "neutral"
    if score_b >= -0.50:
        return "sell"
    return "strong_sell"


def _build_focus_targets(baseline_rows: dict[str, dict], variant_rows: dict[str, dict], selected_dates: set[str] | None, variant_name: str) -> list[dict]:
    targets: list[dict] = []
    common_dates = sorted(set(baseline_rows) & set(variant_rows))
    for trade_date in common_dates:
        if selected_dates and trade_date not in selected_dates:
            continue
        baseline_layer_b = set(_selected_tickers(_filters(baseline_rows[trade_date]).get("layer_b", {})))
        variant_filters = _filters(variant_rows[trade_date])
        variant_layer_b = _selected_tickers(variant_filters.get("layer_b", {}))
        watchlist_map = _ticker_map(variant_filters.get("watchlist", {}))

        for ticker in variant_layer_b:
            if ticker in baseline_layer_b:
                continue
            logged = watchlist_map.get(ticker)
            if not logged:
                continue
            targets.append(
                {
                    "variant": variant_name,
                    "trade_date": trade_date,
                    "ticker": ticker,
                    "logged": {
                        "score_b": float(logged.get("score_b", 0.0) or 0.0),
                        "score_c": float(logged.get("score_c", 0.0) or 0.0),
                        "score_final": float(logged.get("score_final", 0.0) or 0.0),
                        "decision": str(logged.get("decision") or ""),
                        "bc_conflict": logged.get("bc_conflict"),
                        "reasons": [str(item) for item in (logged.get("reasons") or [])],
                    },
                }
            )
    return targets


def _group_targets_by_date(targets: list[dict]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for target in targets:
        grouped.setdefault(target["trade_date"], []).append(target)
    return grouped


def _group_targets_by_variant(targets: list[dict]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for target in targets:
        grouped.setdefault(target["variant"], []).append(target)
    return grouped


def _build_fused_scores(targets: list[dict]) -> list[FusedScore]:
    fused_scores: list[FusedScore] = []
    for target in targets:
        score_b = float(target["logged"]["score_b"])
        fused_scores.append(
            FusedScore(
                ticker=target["ticker"],
                score_b=score_b,
                strategy_signals={},
                arbitration_applied=[],
                market_state=None,
                weights_used={},
                decision=_classify_score_b(score_b),
            )
        )
    return fused_scores


def _compare(targets: list[dict], replay_results: list) -> list[dict]:
    replay_by_ticker = {item.ticker: item for item in replay_results}
    comparisons: list[dict] = []
    for target in targets:
        replay = replay_by_ticker.get(target["ticker"])
        if replay is None:
            continue
        comparisons.append(
            {
                "variant": target["variant"],
                "trade_date": target["trade_date"],
                "ticker": target["ticker"],
                "logged": target["logged"],
                "replay": {
                    "score_b": round(replay.score_b, 4),
                    "score_c": round(replay.score_c, 4),
                    "score_final": round(replay.score_final, 4),
                    "decision": replay.decision,
                    "bc_conflict": replay.bc_conflict,
                    "agent_contribution_summary": replay.agent_contribution_summary,
                },
                "delta": {
                    "score_c": round(replay.score_c - target["logged"]["score_c"], 4),
                    "score_final": round(replay.score_final - target["logged"]["score_final"], 4),
                },
            }
        )
    return comparisons


def main() -> int:
    parser = argparse.ArgumentParser(description="Replay Layer C agent contributors for extra tickers already identified in timing logs")
    parser.add_argument("--baseline", required=True, help="Baseline timing JSONL path")
    parser.add_argument("--variant", action="append", dest="variants", default=[], help="Variant timing JSONL path; can be passed multiple times")
    parser.add_argument("--dates", default="20260202,20260203,20260224,20260226", help="Comma-separated trade dates in YYYYMMDD format")
    parser.add_argument("--model-name", required=False, help="Model name override")
    parser.add_argument("--model-provider", required=False, help="Model provider override")
    parser.add_argument("--output", required=False, help="Optional JSON output path")
    args = parser.parse_args()

    if not args.variants:
        raise ValueError("至少需要提供一个 --variant")

    selected_dates = {item.strip() for item in args.dates.split(",") if item.strip()}
    baseline_rows = _load_pipeline_rows(Path(args.baseline).resolve())
    resolved_model_name, resolved_model_provider = _resolve_model_selection(args.model_name, args.model_provider)
    selected_analysts = [value for _, value in ANALYST_ORDER]
    agent_runner = make_pipeline_agent_runner(
        model_name=resolved_model_name,
        model_provider=resolved_model_provider,
        selected_analysts=selected_analysts,
    )

    all_targets: list[dict] = []
    for variant_arg in args.variants:
        variant_path = Path(variant_arg).resolve()
        variant_rows = _load_pipeline_rows(variant_path)
        all_targets.extend(_build_focus_targets(baseline_rows, variant_rows, selected_dates, variant_path.stem))

    grouped_by_date = _group_targets_by_date(all_targets)
    comparison_rows: list[dict] = []
    for trade_date, targets in sorted(grouped_by_date.items()):
        unique_tickers = sorted({target["ticker"] for target in targets})
        analyst_signals = agent_runner(unique_tickers, trade_date, "fast") if unique_tickers else {}
        for _, variant_targets in sorted(_group_targets_by_variant(targets).items()):
            replay_results = aggregate_layer_c_results(_build_fused_scores(variant_targets), analyst_signals)
            comparison_rows.extend(_compare(variant_targets, replay_results))

    payload = {
        "model": {"model_name": resolved_model_name, "model_provider": resolved_model_provider},
        "dates": sorted(grouped_by_date.keys()),
        "comparisons": comparison_rows,
    }

    for row in comparison_rows:
        replay = row["replay"]
        print(
            f"{row['trade_date']} {row['variant']} {row['ticker']} "
            f"logged_score_c={row['logged']['score_c']:.4f} replay_score_c={replay['score_c']:.4f} "
            f"logged_conflict={row['logged']['bc_conflict']} replay_conflict={replay['bc_conflict']}"
        )
        print(f"  top_negative_agents={replay['agent_contribution_summary']['top_negative_agents']}")

    if args.output:
        output_path = Path(args.output).resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"saved_json: {output_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())