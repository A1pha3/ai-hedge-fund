"""One-command decision flow -- P8-1 + P9-2.

Chains the entire CLI decision pipeline into a single command:
  auto screening → data freshness → signal consistency →
  dynamic threshold → outlier detection → expected returns →
  daily delta → summary

This is the primary entry point for daily stock selection.

CLI:
    python src/main.py --decision-flow
    python src/main.py --decision-flow --top-n=10 --lookback=30
"""

from __future__ import annotations

import json
import time
from datetime import date
from pathlib import Path
from typing import Any

from src.screening.consecutive_recommendation import resolve_report_dir
from src.utils.display import Fore, Style


# ---------------------------------------------------------------------------
# Core decision flow
# ---------------------------------------------------------------------------


def run_decision_flow(
    *,
    top_n: int = 10,
    lookback_days: int = 30,
    reports_dir: Path | None = None,
) -> dict[str, Any]:
    """Execute the full decision flow pipeline.

    Steps:
    1. Load latest auto screening results
    2. Check data freshness
    3. Check signal consistency
    4. Compute dynamic threshold
    5. Detect outliers
    6. Estimate expected returns
    7. Compute daily delta
    8. Render summary

    Args:
        top_n: Number of top recommendations to process
        lookback_days: Lookback for tracking history
        reports_dir: Reports directory

    Returns:
        Complete decision flow report
    """
    start_time = time.time()
    search_dir = reports_dir or resolve_report_dir()
    total_steps = 7
    flow_result: dict[str, Any] = {
        "generated_at": date.today().isoformat(),
        "top_n": top_n,
        "lookback_days": lookback_days,
    }

    # Step 1: Load latest screening report
    print(f"{Fore.CYAN}═══ Decision Flow ═══{Style.RESET_ALL}")
    print(f"\n{Fore.WHITE}Step 1/{total_steps}: Loading latest screening results...{Style.RESET_ALL}")
    from src.screening.data_quality_audit import _find_latest_report

    report_path = _find_latest_report(search_dir)
    if report_path is None:
        print(f"  {Fore.RED}✗ No auto_screening report found. Run --auto first.{Style.RESET_ALL}")
        return {**flow_result, "error": "no_report"}

    report = json.loads(report_path.read_text(encoding="utf-8"))
    recs = (report.get("recommendations") or [])[:top_n]
    trade_date = report.get("trade_date", date.today().strftime("%Y%m%d"))
    print(f"  {Fore.GREEN}✓{Style.RESET_ALL} Loaded {len(recs)} recommendations (date: {trade_date})")
    flow_result["trade_date"] = trade_date
    flow_result["recommendation_count"] = len(recs)

    # Step 2: Data freshness
    print(f"\n{Fore.WHITE}Step 2/{total_steps}: Checking data freshness...{Style.RESET_ALL}")
    from src.screening.data_freshness_guard import check_data_freshness, _render_freshness_summary

    freshness = check_data_freshness(trade_date=trade_date, reports_dir=search_dir)
    print(f"  {_render_freshness_summary(freshness['fresh'], freshness['warnings'])}")
    flow_result["freshness"] = freshness

    # Step 3: Signal consistency
    print(f"\n{Fore.WHITE}Step 3/{total_steps}: Cross-checking signal consistency...{Style.RESET_ALL}")
    from src.screening.signal_consistency import check_signal_consistency, render_consistency_report

    consistency = check_signal_consistency(recs)
    print(render_consistency_report(consistency))
    flow_result["consistency"] = consistency
    high_consistency_count = sum(1 for c in consistency if c.get("consistency_level") == "high")
    flow_result["high_consistency_count"] = high_consistency_count

    # Step 4: Dynamic threshold
    print(f"\n{Fore.WHITE}Step 4/{total_steps}: Computing dynamic threshold...{Style.RESET_ALL}")
    from src.screening.dynamic_threshold import compute_dynamic_threshold, render_dynamic_threshold

    threshold_result = compute_dynamic_threshold(
        lookback_days=lookback_days,
        reports_dir=search_dir,
    )
    print(render_dynamic_threshold(threshold_result))
    flow_result["dynamic_threshold"] = threshold_result

    # Step 5: Outlier detection
    print(f"\n{Fore.WHITE}Step 5/{total_steps}: Detecting recommendation outliers...{Style.RESET_ALL}")
    from src.screening.outlier_detect import detect_outliers, render_outliers

    outliers_result = detect_outliers(top_n=top_n, reports_dir=search_dir)
    print(render_outliers(outliers_result))
    flow_result["outliers"] = outliers_result
    outlier_count = len(outliers_result.get("outliers", []))
    flow_result["outlier_count"] = outlier_count

    # Step 6: Expected returns
    print(f"\n{Fore.WHITE}Step 6/{total_steps}: Estimating expected returns...{Style.RESET_ALL}")
    from src.screening.expected_return import (
        compute_expected_returns,
        render_expected_returns_compact,
    )

    expected = compute_expected_returns(
        recommendations=recs,
        lookback_days=lookback_days,
        reports_dir=search_dir,
    )
    print(render_expected_returns_compact(expected))
    flow_result["expected_returns"] = expected.to_dict()

    # Step 7: Daily delta
    print(f"\n{Fore.WHITE}Step 7/{total_steps}: Comparing with yesterday's picks...{Style.RESET_ALL}")
    from src.screening.daily_delta import compute_daily_delta, render_daily_delta

    delta = compute_daily_delta(reports_dir=search_dir, top_n=top_n, lookback_days=5)
    print(render_daily_delta(delta))
    flow_result["daily_delta"] = delta

    # Summary
    elapsed = time.time() - start_time
    print(f"\n{Fore.CYAN}═══ Decision Summary ═══{Style.RESET_ALL}")
    print(f"  Date: {trade_date}")
    print(f"  Recommendations: {len(recs)} (top {top_n})")
    print(f"  Data freshness: {'✓ PASS' if freshness['fresh'] else '⚠ WARNING'}")
    print(f"  Signal consistency: {high_consistency_count}/{len(consistency)} high")
    print(f"  Dynamic threshold: {threshold_result['threshold']:.4f}")
    print(f"  Outliers: {outlier_count}")
    if expected.items:
        best = max(expected.items, key=lambda x: x.score_b)
        er = best.expected_returns
        t5_str = f"{er.get('t5', 0.0) or 0.0:+.2f}%" if er.get("t5") is not None else "—"
        print(f"  Top pick: {best.ticker} (score={best.score_b:.3f}, T+5 exp={t5_str})")
    print(f"  Completed in {elapsed:.1f}s")

    return flow_result


def render_decision_flow_summary(flow: dict[str, Any]) -> str:
    """Render a compact summary suitable for daily brief."""
    lines = [
        f"Decision Flow — {flow.get('trade_date', '?')}",
        f"Recommendations: {flow.get('recommendation_count', 0)}",
        f"Freshness: {'PASS' if flow.get('freshness', {}).get('fresh') else 'WARNING'}",
        f"High consistency: {flow.get('high_consistency_count', 0)}/{flow.get('recommendation_count', 0)}",
        f"Outliers: {flow.get('outlier_count', 0)}",
    ]
    return "\n".join(lines)
