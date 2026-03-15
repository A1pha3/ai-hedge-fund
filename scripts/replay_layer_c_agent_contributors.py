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


def _write_payload(output_path: Path, payload: dict) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _build_payload(model_name: str, model_provider: str, completed_dates: list[str], comparison_rows: list[dict], partial: bool) -> dict:
    return {
        "model": {"model_name": model_name, "model_provider": model_provider},
        "dates": completed_dates,
        "comparisons": comparison_rows,
        "partial": partial,
    }


def _load_existing_output(output_path: Path) -> tuple[list[str], list[dict]]:
    if not output_path.exists():
        return [], []
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    completed_dates = [str(item) for item in (payload.get("dates") or [])]
    comparisons = [item for item in (payload.get("comparisons") or []) if isinstance(item, dict)]
    return completed_dates, comparisons


def _comparison_key(row: dict) -> tuple[str, str, str]:
    return (str(row.get("variant") or ""), str(row.get("trade_date") or ""), str(row.get("ticker") or ""))


def _chunked(items: list[str], batch_size: int) -> list[list[str]]:
    if batch_size <= 0:
        return [items]
    return [items[index : index + batch_size] for index in range(0, len(items), batch_size)]


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


def _filter_targets_by_tickers(targets: list[dict], selected_tickers: set[str] | None) -> list[dict]:
    if not selected_tickers:
        return targets
    return [target for target in targets if target["ticker"] in selected_tickers]


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
    parser.add_argument("--resume", action="store_true", help="Resume from an existing --output file by skipping completed dates")
    parser.add_argument("--ticker-batch-size", type=int, default=0, help="Optional ticker batch size for more granular persistence; 0 means process all tickers for a date together")
    parser.add_argument("--ticker", action="append", dest="tickers", default=[], help="Optional ticker filter; can be passed multiple times")
    args = parser.parse_args()

    if not args.variants:
        raise ValueError("至少需要提供一个 --variant")

    selected_dates = {item.strip() for item in args.dates.split(",") if item.strip()}
    selected_tickers = {item.strip() for item in args.tickers if str(item).strip()} or None
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
        all_targets.extend(_filter_targets_by_tickers(_build_focus_targets(baseline_rows, variant_rows, selected_dates, variant_path.stem), selected_tickers))

    grouped_by_date = _group_targets_by_date(all_targets)
    output_path = Path(args.output).resolve() if args.output else None
    completed_dates: list[str] = []
    comparison_rows: list[dict] = []
    if args.resume and output_path is not None:
        completed_dates, comparison_rows = _load_existing_output(output_path)
    completed_keys = {_comparison_key(row) for row in comparison_rows}

    for trade_date, targets in sorted(grouped_by_date.items()):
        if trade_date in completed_dates:
            print(f"skip_completed_date: {trade_date}")
            continue
        pending_targets = [target for target in targets if (target["variant"], target["trade_date"], target["ticker"]) not in completed_keys]
        if not pending_targets:
            completed_dates.append(trade_date)
            continue
        for ticker_batch in _chunked(sorted({target["ticker"] for target in pending_targets}), args.ticker_batch_size):
            batch_targets = [target for target in pending_targets if target["ticker"] in set(ticker_batch)]
            analyst_signals = agent_runner(ticker_batch, trade_date, "fast") if ticker_batch else {}
            for _, variant_targets in sorted(_group_targets_by_variant(batch_targets).items()):
                replay_results = aggregate_layer_c_results(_build_fused_scores(variant_targets), analyst_signals)
                new_rows = _compare(variant_targets, replay_results)
                comparison_rows.extend(new_rows)
                completed_keys.update(_comparison_key(row) for row in new_rows)
            if output_path is not None:
                _write_payload(
                    output_path,
                    _build_payload(
                        resolved_model_name,
                        resolved_model_provider,
                        sorted(completed_dates),
                        comparison_rows,
                        partial=True,
                    ),
                )
                print(f"saved_partial_json: {output_path} completed_keys={len(completed_keys)}")
        completed_dates.append(trade_date)
        if output_path is not None:
            _write_payload(
                output_path,
                _build_payload(
                    resolved_model_name,
                    resolved_model_provider,
                    sorted(completed_dates),
                    comparison_rows,
                    partial=True,
                ),
            )
            print(f"saved_partial_json: {output_path} completed_dates={sorted(completed_dates)}")

    payload = _build_payload(
        resolved_model_name,
        resolved_model_provider,
        sorted(completed_dates),
        comparison_rows,
        partial=False,
    )

    for row in comparison_rows:
        replay = row["replay"]
        print(
            f"{row['trade_date']} {row['variant']} {row['ticker']} "
            f"logged_score_c={row['logged']['score_c']:.4f} replay_score_c={replay['score_c']:.4f} "
            f"logged_conflict={row['logged']['bc_conflict']} replay_conflict={replay['bc_conflict']}"
        )
        print(f"  top_negative_agents={replay['agent_contribution_summary']['top_negative_agents']}")

    if output_path is not None:
        _write_payload(output_path, payload)
        print(f"saved_json: {output_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())