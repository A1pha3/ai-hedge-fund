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
    total_steps = 10
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

    # R104 (R88/BH-017 family): a corrupt/truncated report (partial write /
    # interrupted run) must not crash the whole --decision-flow CLI. Degrade
    # to "no report" + user-visible warning so the operator re-runs --auto
    # rather than debugging a JSONDecodeError.
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        print(
            f"  {Fore.RED}✗ 最新报告 {report_path.name} 损坏或不可读 ({exc}); "
            f"请重新运行 --auto 生成.{Style.RESET_ALL}"
        )
        return {**flow_result, "error": "corrupt_report"}
    recs = (report.get("recommendations") or [])[:top_n]
    trade_date = report.get("date", date.today().strftime("%Y%m%d"))
    print(f"  {Fore.GREEN}✓{Style.RESET_ALL} Loaded {len(recs)} recommendations (date: {trade_date})")
    flow_result["trade_date"] = trade_date
    flow_result["recommendation_count"] = len(recs)

    # Step 2: Data freshness
    print(f"\n{Fore.WHITE}Step 2/{total_steps}: Checking data freshness...{Style.RESET_ALL}")
    from src.screening.data_freshness_guard import (
        _render_freshness_summary,
        check_data_freshness,
    )

    freshness = check_data_freshness(trade_date=trade_date, reports_dir=search_dir)
    print(f"  {_render_freshness_summary(freshness['fresh'], freshness['warnings'])}")
    flow_result["freshness"] = freshness

    # Step 3: Signal consistency
    print(f"\n{Fore.WHITE}Step 3/{total_steps}: Cross-checking signal consistency...{Style.RESET_ALL}")
    from src.screening.signal_consistency import (
        check_signal_consistency,
        render_consistency_report,
    )

    consistency = check_signal_consistency(recs)
    print(render_consistency_report(consistency))
    flow_result["consistency"] = consistency
    high_consistency_count = sum(1 for c in consistency if c.get("consistency_level") == "high")
    flow_result["high_consistency_count"] = high_consistency_count

    # Step 4: Dynamic threshold
    print(f"\n{Fore.WHITE}Step 4/{total_steps}: Computing dynamic threshold...{Style.RESET_ALL}")
    from src.screening.dynamic_threshold import (
        compute_dynamic_threshold,
        render_dynamic_threshold,
    )

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
    from src.screening.investability import rank_recommendations_by_investability

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

    # Step 8: Signal momentum (P10-1)
    print(f"\n{Fore.WHITE}Step 8/{total_steps}: Analyzing signal momentum...{Style.RESET_ALL}")
    from src.screening.signal_momentum import (
        compute_signal_momentum,
        render_signal_momentum,
    )

    momentum = compute_signal_momentum(top_n=top_n, lookback_days=lookback_days, reports_dir=search_dir)
    print(render_signal_momentum(momentum))
    flow_result["signal_momentum"] = momentum.to_dict()
    improving_count = sum(1 for i in momentum.items if i.momentum_bonus > 0)
    declining_count = sum(1 for i in momentum.items if i.momentum_bonus < 0)

    # Step 9: Sector strength (P10-2)
    print(f"\n{Fore.WHITE}Step 9/{total_steps}: Evaluating sector strength...{Style.RESET_ALL}")
    from src.screening.sector_strength import (
        compute_sector_strength,
        render_sector_strength,
    )

    sector = compute_sector_strength(top_n=top_n, lookback_days=lookback_days, reports_dir=search_dir)
    print(render_sector_strength(sector))
    flow_result["sector_strength"] = sector.to_dict()

    # Step 10: Composite confidence score (P11-1)
    print(f"\n{Fore.WHITE}Step 10/{total_steps}: Computing composite confidence scores...{Style.RESET_ALL}")
    from src.screening.composite_score import (
        compute_composite_scores,
        render_composite_scores,
    )

    composite = compute_composite_scores(top_n=top_n, lookback_days=lookback_days, reports_dir=search_dir)
    print(render_composite_scores(composite))
    flow_result["composite_scores"] = composite.to_dict()
    investability = rank_recommendations_by_investability(recs, composite, expected)
    flow_result["investability_ranking"] = investability

    # Summary
    elapsed = time.time() - start_time
    print(f"\n{Fore.CYAN}═══ Decision Summary ═══{Style.RESET_ALL}")
    print(f"  Date: {trade_date}")
    print(f"  Recommendations: {len(recs)} (top {top_n})")
    print(f"  Data freshness: {'✓ PASS' if freshness['fresh'] else '⚠ WARNING'}")
    print(f"  Signal consistency: {high_consistency_count}/{len(consistency)} high")
    print(f"  Dynamic threshold: {threshold_result['threshold']:.4f}")
    print(f"  Outliers: {outlier_count}")
    print(f"  Momentum: {Fore.GREEN}{improving_count} improving{Style.RESET_ALL} / {Fore.RED}{declining_count} declining{Style.RESET_ALL}")
    if investability:
        best = investability[0]
        t30 = (best.get("expected_returns") or {}).get("t30")
        t30_str = f"{float(t30):+.2f}%" if isinstance(t30, (int, float)) else "—"
        t30_wr = (best.get("win_rates") or {}).get("t30")
        t30_wr_str = f"{float(t30_wr):.0%}" if isinstance(t30_wr, (int, float)) else "—"
        # BH-002 drain: attribute the T+30 stat to its matured-sample denominator,
        # not the all-records ``bucket_sample_count``. A freshly-recommended
        # batch inflates the all-records count without contributing to the T+30
        # estimate, so the displayed backing sample was misleading.
        sample_all = int(best.get("bucket_sample_count", 0) or 0)
        sample_t30_mature = int(best.get("bucket_t30_mature_count", 0) or 0)
        sample_str = f"样本={sample_all}(T30熟={sample_t30_mature})"
        print(
            f"  Top investable: {best.get('ticker', '?')} (composite={float(best.get('composite_score', 0.0)):+.3f}, T+30={t30_str}, 胜率={t30_wr_str}, {sample_str})"
        )
    print(f"  Completed in {elapsed:.1f}s")

    # R77 (R71/R72/R73/R75/R76 trust-calibration family): this surface emits a
    # concrete Top-investable ticker with composite score, T+30 edge and win
    # rate. Carry the same non-advice disclaimer as the other six user-facing
    # decision surfaces (--top-picks / --daily-brief / --position-check /
    # --explain / --why-not / PDF / backtest) so users do not read
    # "Top investable: 000001 (T+30=+3.2%, 胜率=58%)" as a deterministic
    # instruction (serves product goal "更高确信" = confidence includes honest
    # boundary disclosure).
    _print_decision_flow_disclaimer()

    return flow_result


def _print_decision_flow_disclaimer() -> None:
    """R77: research-only disclaimer at the end of the --decision-flow summary.

    Mirrors the R71 ``--top-picks`` disclaimer wording so all user-facing
    decision surfaces stay consistent.
    """
    print(
        f"\n  {Fore.WHITE}⚠ 以上决策流摘要由 AI 模型自动生成, 仅供研究 / 学习用途, 不构成任何投资建议。"
        f"实际投资需结合个人风险承受能力与最新市场情况。{Style.RESET_ALL}"
    )


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
