from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from src.execution.daily_pipeline import FAST_AGENT_MAX_TICKERS, FAST_AGENT_SCORE_THRESHOLD
from src.screening.candidate_pool import _SNAPSHOT_DIR, build_candidate_pool
from src.screening.market_state import detect_market_state
from src.screening.signal_fusion import fuse_batch
from src.screening.strategy_scorer import score_batch


VARIANTS = {
    "baseline": {},
    "profitability_only": {
        "LAYER_B_ANALYSIS_PROFITABILITY_ZERO_PASS_MODE": "inactive",
    },
    "neutral_mean_reversion_only": {
        "LAYER_B_ANALYSIS_EXCLUDE_NEUTRAL_MEAN_REVERSION": "1",
    },
    "combined": {
        "LAYER_B_ANALYSIS_PROFITABILITY_ZERO_PASS_MODE": "inactive",
        "LAYER_B_ANALYSIS_EXCLUDE_NEUTRAL_MEAN_REVERSION": "1",
    },
}


@contextmanager
def _temporary_env(updates: dict[str, str]) -> Iterator[None]:
    original = {key: os.environ.get(key) for key in updates}
    try:
        for key, value in updates.items():
            os.environ[key] = value
        yield
    finally:
        for key, previous in original.items():
            if previous is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = previous


def _get_trade_dates(month_prefix: str) -> list[str]:
    dates = []
    for path in sorted(_SNAPSHOT_DIR.glob(f"candidate_pool_{month_prefix}*.json")):
        stem = path.stem
        dates.append(stem.rsplit("_", 1)[-1])
    return dates


def _profitability_metrics(record: dict) -> dict:
    profitability = (((record.get("strategy_signals") or {}).get("fundamental") or {}).get("sub_factors") or {}).get("profitability") or {}
    metrics = profitability.get("metrics") or {}
    return {
        "direction": profitability.get("direction", 0),
        "confidence": profitability.get("confidence", 0.0),
        "completeness": profitability.get("completeness", 0.0),
        "positive_count": metrics.get("positive_count", 0),
        "available_count": metrics.get("available_count", 0),
    }


def _strategy_summary(record: dict) -> dict:
    signals = record.get("strategy_signals") or {}
    summary = {}
    for name, signal in signals.items():
        summary[name] = {
            "direction": signal.get("direction", 0),
            "confidence": round(float(signal.get("confidence", 0.0)), 4),
            "completeness": round(float(signal.get("completeness", 0.0)), 4),
        }
    return summary


def _classify_added_sample(baseline_record: dict) -> list[str]:
    tags: list[str] = []
    profitability = _profitability_metrics(baseline_record)
    strategy = _strategy_summary(baseline_record)
    if profitability["direction"] == -1 and profitability["positive_count"] == 0:
        tags.append("profitability_hard_cliff")
    if strategy.get("mean_reversion", {}).get("direction") == 0 and strategy.get("mean_reversion", {}).get("completeness", 0.0) > 0:
        tags.append("neutral_mean_reversion_active")
    if strategy.get("trend", {}).get("direction") == 1 and strategy.get("fundamental", {}).get("direction") == 1:
        tags.append("trend_fundamental_dual_leg")
    if strategy.get("event_sentiment", {}).get("direction") == 0:
        tags.append("event_sentiment_missing")
    if not tags:
        tags.append("other")
    return tags


def _run_variant(trade_dates: list[str], env_updates: dict[str, str]) -> dict:
    by_date: dict[str, dict] = {}
    total_passes = 0

    with _temporary_env(env_updates):
        for trade_date in trade_dates:
            candidates = build_candidate_pool(trade_date, use_cache=True)
            market_state = detect_market_state(trade_date)
            scored = score_batch(candidates, trade_date)
            fused = fuse_batch(scored, market_state, trade_date)
            selected = sorted(
                [item for item in fused if item.score_b >= FAST_AGENT_SCORE_THRESHOLD],
                key=lambda item: item.score_b,
                reverse=True,
            )[:FAST_AGENT_MAX_TICKERS]
            candidate_map = {candidate.ticker: candidate for candidate in candidates}
            record_map: dict[str, dict] = {}
            selected_tickers = {item.ticker for item in selected}

            for item in fused:
                candidate = candidate_map.get(item.ticker)
                record_map[item.ticker] = {
                    "ticker": item.ticker,
                    "industry_sw": candidate.industry_sw if candidate else "",
                    "score_b": round(float(item.score_b), 4),
                    "decision": item.decision,
                    "selected": item.ticker in selected_tickers,
                    "arbitration_applied": list(item.arbitration_applied),
                    "strategy_signals": {name: signal.model_dump() for name, signal in item.strategy_signals.items()},
                }

            by_date[trade_date] = {
                "selected_tickers": [item.ticker for item in selected],
                "records": record_map,
                "layer_b_count": len(selected),
            }
            total_passes += len(selected)

    return {
        "trade_dates": trade_dates,
        "total_layer_b_passes": total_passes,
        "by_date": by_date,
    }


def _build_comparison(variant_name: str, baseline: dict, variant: dict) -> dict:
    baseline_selected = {
        (trade_date, ticker)
        for trade_date, payload in baseline["by_date"].items()
        for ticker in payload["selected_tickers"]
    }
    variant_selected = {
        (trade_date, ticker)
        for trade_date, payload in variant["by_date"].items()
        for ticker in payload["selected_tickers"]
    }
    added_pairs = sorted(variant_selected - baseline_selected)
    removed_pairs = sorted(baseline_selected - variant_selected)

    added_samples = []
    industry_counts: Counter[str] = Counter()
    tag_counts: Counter[str] = Counter()
    daily_added_counts: Counter[str] = Counter()

    for trade_date, ticker in added_pairs:
        baseline_record = baseline["by_date"][trade_date]["records"][ticker]
        variant_record = variant["by_date"][trade_date]["records"][ticker]
        tags = _classify_added_sample(baseline_record)
        industry = variant_record.get("industry_sw") or "unknown"
        industry_counts[industry] += 1
        daily_added_counts[trade_date] += 1
        tag_counts.update(tags)
        added_samples.append(
            {
                "trade_date": trade_date,
                "ticker": ticker,
                "industry_sw": industry,
                "baseline_score_b": baseline_record["score_b"],
                "variant_score_b": variant_record["score_b"],
                "score_delta": round(variant_record["score_b"] - baseline_record["score_b"], 4),
                "baseline_arbitration": baseline_record["arbitration_applied"],
                "variant_arbitration": variant_record["arbitration_applied"],
                "tags": tags,
                "strategy_summary": _strategy_summary(baseline_record),
                "profitability": _profitability_metrics(baseline_record),
            }
        )

    return {
        "variant": variant_name,
        "baseline_total_layer_b_passes": baseline["total_layer_b_passes"],
        "variant_total_layer_b_passes": variant["total_layer_b_passes"],
        "layer_b_pass_delta": variant["total_layer_b_passes"] - baseline["total_layer_b_passes"],
        "added_sample_count": len(added_samples),
        "removed_sample_count": len(removed_pairs),
        "added_samples": added_samples,
        "removed_samples": [{"trade_date": trade_date, "ticker": ticker} for trade_date, ticker in removed_pairs],
        "added_industry_counts": dict(industry_counts.most_common()),
        "added_tag_counts": dict(tag_counts.most_common()),
        "daily_added_counts": dict(sorted(daily_added_counts.items())),
        "daily_layer_b_counts": {
            trade_date: {
                "baseline": baseline["by_date"][trade_date]["layer_b_count"],
                "variant": variant["by_date"][trade_date]["layer_b_count"],
            }
            for trade_date in baseline["trade_dates"]
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Replay Layer B rule variants on cached candidate-pool windows.")
    parser.add_argument("--month-prefix", default="202602", help="candidate_pool_YYYYMM*.json prefix, default: 202602")
    parser.add_argument("--output", default="", help="optional json output path")
    args = parser.parse_args()

    trade_dates = _get_trade_dates(args.month_prefix)
    if not trade_dates:
        raise SystemExit(f"No candidate pool snapshots found for prefix {args.month_prefix}")

    variant_results = {
        name: _run_variant(trade_dates, env_updates)
        for name, env_updates in VARIANTS.items()
    }
    baseline = variant_results["baseline"]
    comparisons = {
        name: _build_comparison(name, baseline, result)
        for name, result in variant_results.items()
        if name != "baseline"
    }

    payload = {
        "trade_dates": trade_dates,
        "window": {"start": trade_dates[0], "end": trade_dates[-1], "days": len(trade_dates)},
        "thresholds": {
            "fast_agent_score_threshold": FAST_AGENT_SCORE_THRESHOLD,
            "fast_agent_max_tickers": FAST_AGENT_MAX_TICKERS,
        },
        "baseline_total_layer_b_passes": baseline["total_layer_b_passes"],
        "comparisons": comparisons,
    }

    output_text = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(output_text, encoding="utf-8")
    print(output_text)


if __name__ == "__main__":
    main()
