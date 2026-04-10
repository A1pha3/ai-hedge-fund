from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from src.project_env import load_project_dotenv
from src.execution.daily_pipeline import FAST_AGENT_SCORE_THRESHOLD
from src.screening.candidate_pool import build_candidate_pool
from src.screening.market_state import detect_market_state
from src.screening.signal_fusion import fuse_batch
from src.screening.strategy_scorer import score_batch


load_project_dotenv()


THRESHOLDS = {
    "return_on_equity": 0.15,
    "net_margin": 0.20,
    "operating_margin": 0.15,
}


def _build_profitability_breakdown_accumulator() -> dict:
    return {
        "metric_fail_blocked": Counter(),
        "metric_fail_fund_nonpositive": Counter(),
        "metric_fail_positive_count_0": Counter(),
        "fail_combo_blocked": Counter(),
        "fail_combo_fund_nonpositive": Counter(),
        "fail_combo_positive_count_0": Counter(),
        "near_threshold_fail_combo": Counter(),
        "triple_fail_industry_blocked": Counter(),
        "triple_fail_industry_fund_nonpositive": Counter(),
        "triple_fail_market_cap_bucket_blocked": Counter(),
        "triple_fail_market_cap_bucket_fund_nonpositive": Counter(),
        "blocked_with_profitability_scored": 0,
        "fund_nonpositive_with_profitability_scored": 0,
        "positive_count_0_blocked": 0,
        "positive_count_0_fund_nonpositive": 0,
        "triple_fail_examples": [],
    }


def _process_trade_date_profitability_breakdown(trade_date: str, stats: dict) -> None:
    candidates = build_candidate_pool(trade_date, use_cache=True)
    market_state = detect_market_state(trade_date)
    scored = score_batch(candidates, trade_date)
    fused = fuse_batch(scored, market_state, trade_date)
    candidate_map = {candidate.ticker: candidate for candidate in candidates}
    for item in fused:
        _process_profitability_item(item, candidate_map=candidate_map, trade_date=trade_date, stats=stats)


def _process_profitability_item(item: object, *, candidate_map: dict[str, object], trade_date: str, stats: dict) -> None:
    if float(item.score_b) >= FAST_AGENT_SCORE_THRESHOLD:
        return
    signals = {name: signal.model_dump() for name, signal in item.strategy_signals.items()}
    fundamental = signals.get("fundamental") or {}
    fundamental_direction = int(fundamental.get("direction", 0) or 0)
    profitability = ((fundamental.get("sub_factors") or {}).get("profitability") or {})
    if float(profitability.get("completeness", 0) or 0.0) <= 0:
        return
    stats["blocked_with_profitability_scored"] += 1
    metrics = profitability.get("metrics") or {}
    failed_metrics = _record_failed_metrics(metrics, stats["metric_fail_blocked"])
    combo_key = "+".join(sorted(failed_metrics)) if failed_metrics else "none"
    stats["fail_combo_blocked"][combo_key] += 1
    if fundamental_direction <= 0:
        _record_nonpositive_fundamental_failures(failed_metrics, combo_key, stats)
    if metrics.get("positive_count") == 0:
        _record_positive_count_zero_failures(item, failed_metrics, combo_key, stats, fundamental_direction)
    if combo_key == "net_margin+operating_margin+return_on_equity":
        _record_triple_fail_example(item, candidate_map=candidate_map, trade_date=trade_date, stats=stats, fundamental_direction=fundamental_direction)


def _record_failed_metrics(metrics: dict, counter: Counter[str]) -> list[str]:
    failed_metrics: list[str] = []
    for metric_name, threshold in THRESHOLDS.items():
        value = metrics.get(metric_name)
        if value is not None and value < threshold:
            counter[metric_name] += 1
            failed_metrics.append(metric_name)
    return failed_metrics


def _record_nonpositive_fundamental_failures(failed_metrics: list[str], combo_key: str, stats: dict) -> None:
    stats["fund_nonpositive_with_profitability_scored"] += 1
    for metric_name in failed_metrics:
        stats["metric_fail_fund_nonpositive"][metric_name] += 1
    stats["fail_combo_fund_nonpositive"][combo_key] += 1


def _record_positive_count_zero_failures(item: object, failed_metrics: list[str], combo_key: str, stats: dict, fundamental_direction: int) -> None:
    stats["positive_count_0_blocked"] += 1
    for metric_name in failed_metrics:
        stats["metric_fail_positive_count_0"][metric_name] += 1
    stats["fail_combo_positive_count_0"][combo_key] += 1
    if float(item.score_b) >= 0.30:
        stats["near_threshold_fail_combo"][combo_key] += 1
    if fundamental_direction <= 0:
        stats["positive_count_0_fund_nonpositive"] += 1


def _resolve_market_cap_bucket(candidate: object | None) -> str:
    market_cap = float(candidate.market_cap) if candidate else 0.0
    if market_cap < 100:
        return "lt_100b"
    if market_cap < 300:
        return "100b_to_300b"
    if market_cap < 1000:
        return "300b_to_1000b"
    return "ge_1000b"


def _record_triple_fail_example(item: object, *, candidate_map: dict[str, object], trade_date: str, stats: dict, fundamental_direction: int) -> None:
    candidate = candidate_map.get(item.ticker)
    industry = candidate.industry_sw if candidate and candidate.industry_sw else "unknown"
    market_cap = float(candidate.market_cap) if candidate else 0.0
    market_cap_bucket = _resolve_market_cap_bucket(candidate)
    stats["triple_fail_industry_blocked"][industry] += 1
    stats["triple_fail_market_cap_bucket_blocked"][market_cap_bucket] += 1
    if fundamental_direction <= 0:
        stats["triple_fail_industry_fund_nonpositive"][industry] += 1
        stats["triple_fail_market_cap_bucket_fund_nonpositive"][market_cap_bucket] += 1
    if len(stats["triple_fail_examples"]) < 12:
        stats["triple_fail_examples"].append(
            {
                "trade_date": trade_date,
                "ticker": item.ticker,
                "industry_sw": industry,
                "market_cap": round(market_cap, 2),
                "score_b": round(float(item.score_b), 4),
                "fundamental_direction": fundamental_direction,
            }
        )


def _build_profitability_breakdown_summary(trade_dates: list[str], stats: dict) -> dict:
    return {
        "trade_dates": trade_dates,
        "thresholds": THRESHOLDS,
        "blocked_with_profitability_scored": stats["blocked_with_profitability_scored"],
        "fund_nonpositive_with_profitability_scored": stats["fund_nonpositive_with_profitability_scored"],
        "positive_count_0_blocked": stats["positive_count_0_blocked"],
        "positive_count_0_fund_nonpositive": stats["positive_count_0_fund_nonpositive"],
        "metric_fail_blocked": dict(stats["metric_fail_blocked"].most_common()),
        "metric_fail_fund_nonpositive": dict(stats["metric_fail_fund_nonpositive"].most_common()),
        "metric_fail_positive_count_0": dict(stats["metric_fail_positive_count_0"].most_common()),
        "fail_combo_blocked": dict(stats["fail_combo_blocked"].most_common()),
        "fail_combo_fund_nonpositive": dict(stats["fail_combo_fund_nonpositive"].most_common()),
        "fail_combo_positive_count_0": dict(stats["fail_combo_positive_count_0"].most_common()),
        "near_threshold_fail_combo": dict(stats["near_threshold_fail_combo"].most_common()),
        "triple_fail_industry_blocked": dict(stats["triple_fail_industry_blocked"].most_common()),
        "triple_fail_industry_fund_nonpositive": dict(stats["triple_fail_industry_fund_nonpositive"].most_common()),
        "triple_fail_market_cap_bucket_blocked": dict(stats["triple_fail_market_cap_bucket_blocked"].most_common()),
        "triple_fail_market_cap_bucket_fund_nonpositive": dict(stats["triple_fail_market_cap_bucket_fund_nonpositive"].most_common()),
        "triple_fail_examples": stats["triple_fail_examples"],
    }


def analyze_trade_dates(trade_dates: list[str]) -> dict:
    stats = _build_profitability_breakdown_accumulator()
    for trade_date in trade_dates:
        _process_trade_date_profitability_breakdown(trade_date, stats)
    return _build_profitability_breakdown_summary(trade_dates, stats)


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze profitability subfactor metric failures for cached candidate-pool windows.")
    parser.add_argument("--trade-dates", required=True, help="Comma-separated trade dates like 20260323,20260324")
    parser.add_argument("--output", default="", help="Optional output JSON path")
    args = parser.parse_args()

    trade_dates = [item.strip() for item in args.trade_dates.split(",") if item.strip()]
    analysis = analyze_trade_dates(trade_dates)

    if args.output:
        output_path = Path(args.output).expanduser().resolve()
        output_path.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
