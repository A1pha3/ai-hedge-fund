from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from src.execution.daily_pipeline import FAST_AGENT_SCORE_THRESHOLD
from src.screening.candidate_pool import build_candidate_pool
from src.screening.market_state import detect_market_state
from src.screening.signal_fusion import fuse_batch
from src.screening.strategy_scorer import score_batch


THRESHOLDS = {
    "return_on_equity": 0.15,
    "net_margin": 0.20,
    "operating_margin": 0.15,
}


def analyze_trade_dates(trade_dates: list[str]) -> dict:
    metric_fail_blocked: Counter[str] = Counter()
    metric_fail_fund_nonpositive: Counter[str] = Counter()
    metric_fail_positive_count_0: Counter[str] = Counter()
    fail_combo_blocked: Counter[str] = Counter()
    fail_combo_fund_nonpositive: Counter[str] = Counter()
    fail_combo_positive_count_0: Counter[str] = Counter()
    near_threshold_fail_combo: Counter[str] = Counter()
    blocked_with_profitability_scored = 0
    fund_nonpositive_with_profitability_scored = 0
    positive_count_0_blocked = 0
    positive_count_0_fund_nonpositive = 0

    for trade_date in trade_dates:
        candidates = build_candidate_pool(trade_date, use_cache=True)
        market_state = detect_market_state(trade_date)
        scored = score_batch(candidates, trade_date)
        fused = fuse_batch(scored, market_state, trade_date)

        for item in fused:
            if float(item.score_b) >= FAST_AGENT_SCORE_THRESHOLD:
                continue

            signals = {name: signal.model_dump() for name, signal in item.strategy_signals.items()}
            fundamental = signals.get("fundamental") or {}
            fundamental_direction = int(fundamental.get("direction", 0) or 0)
            profitability = ((fundamental.get("sub_factors") or {}).get("profitability") or {})
            if float(profitability.get("completeness", 0) or 0.0) <= 0:
                continue

            blocked_with_profitability_scored += 1
            metrics = profitability.get("metrics") or {}
            failed_metrics: list[str] = []
            for metric_name, threshold in THRESHOLDS.items():
                value = metrics.get(metric_name)
                if value is not None and value < threshold:
                    metric_fail_blocked[metric_name] += 1
                    failed_metrics.append(metric_name)

            combo_key = "+".join(sorted(failed_metrics)) if failed_metrics else "none"
            fail_combo_blocked[combo_key] += 1

            if fundamental_direction <= 0:
                fund_nonpositive_with_profitability_scored += 1
                for metric_name in failed_metrics:
                    metric_fail_fund_nonpositive[metric_name] += 1
                fail_combo_fund_nonpositive[combo_key] += 1

            if metrics.get("positive_count") == 0:
                positive_count_0_blocked += 1
                for metric_name in failed_metrics:
                    metric_fail_positive_count_0[metric_name] += 1
                fail_combo_positive_count_0[combo_key] += 1
                if float(item.score_b) >= 0.30:
                    near_threshold_fail_combo[combo_key] += 1
                if fundamental_direction <= 0:
                    positive_count_0_fund_nonpositive += 1

    return {
        "trade_dates": trade_dates,
        "thresholds": THRESHOLDS,
        "blocked_with_profitability_scored": blocked_with_profitability_scored,
        "fund_nonpositive_with_profitability_scored": fund_nonpositive_with_profitability_scored,
        "positive_count_0_blocked": positive_count_0_blocked,
        "positive_count_0_fund_nonpositive": positive_count_0_fund_nonpositive,
        "metric_fail_blocked": dict(metric_fail_blocked.most_common()),
        "metric_fail_fund_nonpositive": dict(metric_fail_fund_nonpositive.most_common()),
        "metric_fail_positive_count_0": dict(metric_fail_positive_count_0.most_common()),
        "fail_combo_blocked": dict(fail_combo_blocked.most_common()),
        "fail_combo_fund_nonpositive": dict(fail_combo_fund_nonpositive.most_common()),
        "fail_combo_positive_count_0": dict(fail_combo_positive_count_0.most_common()),
        "near_threshold_fail_combo": dict(near_threshold_fail_combo.most_common()),
    }


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