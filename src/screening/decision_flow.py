"""One-command decision flow -- P8-1.

Chains the entire CLI decision pipeline into a single command:
  auto screening → signal consistency → freshness check →
  conviction ranking → daily delta → daily brief

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
    4. Generate conviction ranking
    5. Compute daily delta
    6. Render daily brief

    Args:
        top_n: Number of top recommendations to process
        lookback_days: Lookback for tracking history
        reports_dir: Reports directory

    Returns:
        Complete decision flow report
    """
    start_time = time.time()
    search_dir = reports_dir or resolve_report_dir()
    flow_result: dict[str, Any] = {
        "generated_at": date.today().isoformat(),
        "top_n": top_n,
        "lookback_days": lookback_days,
    }

    # Step 1: Load latest screening report
    print(f"{Fore.CYAN}═══ Decision Flow ═══{Style.RESET_ALL}")
    print(f"\n{Fore.WHITE}Step 1/5: Loading latest screening results...{Style.RESET_ALL}")
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
    print(f"\n{Fore.WHITE}Step 2/5: Checking data freshness...{Style.RESET_ALL}")
    from src.screening.data_freshness_guard import check_data_freshness, _render_freshness_summary

    freshness = check_data_freshness(trade_date=trade_date, reports_dir=search_dir)
    print(f"  {_render_freshness_summary(freshness['fresh'], freshness['warnings'])}")
    flow_result["freshness"] = freshness

    # Step 3: Signal consistency
    print(f"\n{Fore.WHITE}Step 3/5: Cross-checking signal consistency...{Style.RESET_ALL}")
    from src.screening.signal_consistency import check_signal_consistency, render_consistency_report

    consistency = check_signal_consistency(recs)
    print(render_consistency_report(consistency))
    flow_result["consistency"] = consistency
    high_consistency_count = sum(1 for c in consistency if c.get("consistency_level") == "high")
    flow_result["high_consistency_count"] = high_consistency_count

    # Step 4: Dynamic threshold
    print(f"\n{Fore.WHITE}Step 4/5: Computing dynamic threshold...{Style.RESET_ALL}")
    from src.screening.dynamic_threshold import compute_dynamic_threshold, render_dynamic_threshold

    threshold_result = compute_dynamic_threshold(
        lookback_days=lookback_days,
        reports_dir=search_dir,
    )
    print(render_dynamic_threshold(threshold_result))
    flow_result["dynamic_threshold"] = threshold_result

    # Step 5: Daily delta
    print(f"\n{Fore.WHITE}Step 5/5: Comparing with yesterday's picks...{Style.RESET_ALL}")
    from src.screening.daily_delta import compute_daily_delta, render_daily_delta

    delta = compute_daily_delta(reports_dir=search_dir, top_n=top_n, lookback_days=5)
    print(render_daily_delta(delta))
    flow_result["daily_delta"] = delta

    # Summary
    elapsed = time.time() - start_time
    print(f"\n{Fore.CYAN}═══ Summary ═══{Style.RESET_ALL}")
    print(f"  Recommendations: {len(recs)} (top {top_n})")
    print(f"  Data freshness: {'✓ PASS' if freshness['fresh'] else '⚠ WARNING'}")
    print(f"  Signal consistency: {high_consistency_count}/{len(consistency)} high")
    print(f"  Dynamic threshold: {threshold_result['threshold']:.4f}")
    print(f"  Completed in {elapsed:.1f}s")

    return flow_result


def render_decision_flow_summary(flow: dict[str, Any]) -> str:
    """Render a compact summary suitable for daily brief."""
    lines = [
        f"Decision Flow — {flow.get('trade_date', '?')}",
        f"Recommendations: {flow.get('recommendation_count', 0)}",
        f"Freshness: {'PASS' if flow.get('freshness', {}).get('fresh') else 'WARNING'}",
        f"High consistency: {flow.get('high_consistency_count', 0)}/{flow.get('recommendation_count', 0)}",
    ]
    return "\n".join(lines)
