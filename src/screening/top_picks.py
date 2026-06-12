"""One-Command Top Picks — P12-2.

The simplest way to get actionable buy recommendations.
Runs the full decision pipeline and outputs a compact ranked list
with composite confidence scores.

This is the "what should I buy today?" command.

CLI::

    python src/main.py --top-picks [--count=5]
    python src/main.py --top-picks --count=3 --lookback=30

Design principle:
    One command → one answer. No analysis paralysis.
    The user sees: ticker, name, composite score, grade, and why.
"""
from __future__ import annotations

import json
from pathlib import Path

from src.screening.composite_score import (
    compute_composite_scores,
    _composite_grade,
)
from src.screening.consecutive_recommendation import resolve_report_dir
from src.screening.data_quality_audit import _find_latest_report
from src.screening.expected_return import compute_expected_returns
from src.screening.investability import (
    build_front_door_verdict,
    rank_recommendations_by_investability,
    select_representative_candidates,
)
from src.utils.display import Fore, Style


# ---------------------------------------------------------------------------
# P16-1: Market gate warning
# ---------------------------------------------------------------------------


def _render_market_gate(trade_date: str) -> str:
    """Render market-gate guidance and return the normalized regime label."""

    if not trade_date or len(trade_date) != 8 or not trade_date.isdigit():
        return "unknown"

    from src.screening.market_state import detect_market_state

    try:
        state = detect_market_state(trade_date)
    except Exception as exc:
        print(
            f"\n{Fore.YELLOW}⚠ MARKET GATE unavailable: {exc}{Style.RESET_ALL}"
        )
        print(
            f"  {Fore.YELLOW}已跳过市场门控增强，继续输出默认前门结果。{Style.RESET_ALL}\n"
        )
        return "unknown"

    regime = str(getattr(state, "regime", "") or "")
    regime_lower = regime.lower()

    if "crisis" in regime_lower or "risk_off" in regime_lower:
        print(
            f"\n{Fore.RED}{Style.BRIGHT}⚠ MARKET GATE: {regime}{Style.RESET_ALL}"
        )
        print(
            f"  {Fore.RED}当前市场处于高风险状态, 默认前门只给 HOLD / AVOID 级别建议。{Style.RESET_ALL}"
        )
        print(
            f"  {Fore.YELLOW}建议: 降低仓位或等待市场企稳后再操作。{Style.RESET_ALL}\n"
        )
    elif "cautious" in regime_lower or "range" in regime_lower:
        print(
            f"\n{Fore.YELLOW}⚡ MARKET GATE: {regime}{Style.RESET_ALL}"
        )
        print(
            f"  {Fore.YELLOW}市场处于震荡/谨慎状态, 建议轻仓参与, 严格止损。{Style.RESET_ALL}\n"
        )
    else:
        print(
            f"\n{Fore.GREEN}✓ MARKET GATE: {regime or 'normal'}{Style.RESET_ALL}"
        )
        print(
            f"  {Fore.GREEN}市场门控允许正常筛选, 重点关注 BUY / HOLD 级别代表票。{Style.RESET_ALL}\n"
        )

    return regime_lower or "unknown"


def run_top_picks(
    *,
    count: int = 5,
    lookback_days: int = 5,
    reports_dir: Path | None = None,
) -> int:
    """Run full decision pipeline and output top picks.

    Args:
        count: Number of picks to show (default 5)
        lookback_days: Lookback for momentum/sector analysis
        reports_dir: Reports directory

    Returns:
        Exit code
    """
    search_dir = reports_dir or resolve_report_dir()

    # Step 1: Load latest report
    report_path = _find_latest_report(search_dir)
    if report_path is None:
        print(f"{Fore.RED}No auto_screening report found. Run --auto first.{Style.RESET_ALL}")
        return 1

    report_data = json.loads(report_path.read_text(encoding="utf-8"))
    recs = (report_data.get("recommendations") or [])[:count * 3]  # Load more for filtering
    trade_date = report_data.get("trade_date", "")
    market_regime = _render_market_gate(trade_date)

    if not recs:
        print(f"{Fore.YELLOW}No recommendations in latest report.{Style.RESET_ALL}")
        return 0

    # Step 2: Compute composite scores
    composite = compute_composite_scores(
        top_n=count * 3,
        lookback_days=lookback_days,
        reports_dir=search_dir,
    )
    expected = compute_expected_returns(
        recommendations=recs,
        lookback_days=max(60, lookback_days),
        reports_dir=search_dir,
    )

    if not composite.items:
        print(f"{Fore.YELLOW}Unable to compute composite scores.{Style.RESET_ALL}")
        return 0

    ranked = rank_recommendations_by_investability(recs, composite, expected)
    representative_picks = select_representative_candidates(ranked, count=count)

    # Step 3: Render compact output
    print(f"\n{Fore.CYAN}{Style.BRIGHT}🎯 Today's Top Picks{Style.RESET_ALL}")
    print(f"  Date: {trade_date}  |  默认前门: composite confidence + T+30 posterior edge + 代表票去重")
    print(f"{Fore.WHITE}{'─' * 72}{Style.RESET_ALL}")

    for idx, item in enumerate(representative_picks, 1):
        composite_score = float(item.get("composite_score", item.get("score_b", 0.0)) or 0.0)
        grade = _composite_grade(composite_score)
        name = str(item.get("name", "") or item.get("ticker", ""))[:14]
        verdict = build_front_door_verdict(item, market_regime=market_regime)

        # Signal breakdown
        parts = []
        if float(item.get("momentum_bonus", 0.0) or 0.0) > 0:
            parts.append(f"{Fore.GREEN}动量↑{Style.RESET_ALL}")
        elif float(item.get("momentum_bonus", 0.0) or 0.0) < 0:
            parts.append(f"{Fore.RED}动量↓{Style.RESET_ALL}")
        if float(item.get("sector_bonus", 0.0) or 0.0) > 0:
            parts.append(f"{Fore.GREEN}行业强{Style.RESET_ALL}")
        elif float(item.get("sector_bonus", 0.0) or 0.0) < 0:
            parts.append(f"{Fore.RED}行业弱{Style.RESET_ALL}")
        if float(item.get("consistency_adj", 0.0) or 0.0) > 0:
            parts.append(f"{Fore.GREEN}一致{Style.RESET_ALL}")
        elif float(item.get("consistency_adj", 0.0) or 0.0) < 0:
            parts.append(f"{Fore.RED}分歧{Style.RESET_ALL}")
        if float(item.get("volume_factor", 0.0) or 0.0) > 0:
            parts.append(f"{Fore.GREEN}放量{Style.RESET_ALL}")
        elif float(item.get("volume_factor", 0.0) or 0.0) < 0:
            parts.append(f"{Fore.RED}缩量{Style.RESET_ALL}")
        if float(item.get("trend_resonance_factor", 0.0) or 0.0) > 0.02:
            parts.append(f"{Fore.GREEN}共振↑{Style.RESET_ALL}")
        elif float(item.get("trend_resonance_factor", 0.0) or 0.0) < -0.02:
            parts.append(f"{Fore.RED}冲突{Style.RESET_ALL}")

        signal_str = " ".join(parts) if parts else f"{Fore.WHITE}中性{Style.RESET_ALL}"
        t30 = (item.get("expected_returns") or {}).get("t30")
        t30_wr = (item.get("win_rates") or {}).get("t30")
        sample_count = int(item.get("bucket_sample_count", 0) or 0)
        cluster_label = str(item.get("cluster_label", "") or "")
        cluster_size = int(item.get("cluster_size", 1) or 1)
        alternatives = [str(ticker) for ticker in (item.get("cluster_alternatives") or []) if str(ticker)]

        # Color by composite score
        if composite_score >= 0.5:
            score_color = Fore.GREEN + Style.BRIGHT
        elif composite_score >= 0.3:
            score_color = Fore.YELLOW
        else:
            score_color = Fore.RED

        t30_str = f"{t30:+.2f}%" if isinstance(t30, (int, float)) else "—"
        t30_wr_str = f"{t30_wr:.0%}" if isinstance(t30_wr, (int, float)) else "—"
        base_score = float(item.get("base_score", item.get("score_b", 0.0)) or 0.0)

        print(
            f"  {Fore.WHITE}{idx}.{Style.RESET_ALL} "
            f"{Fore.CYAN}{str(item.get('ticker', '')):<8}{Style.RESET_ALL} "
            f"{name:<14} "
            f"{score_color}{composite_score:>+.3f}{Style.RESET_ALL} "
            f"{grade}  "
            f"(base={base_score:.3f} {signal_str})"
        )
        print(f"     操作={verdict['action']}  T+30={t30_str}  T+30胜率={t30_wr_str}  样本={sample_count}  市场门控={verdict['market_regime']}")
        print(f"     失效条件: {verdict['invalidation_reason']}")
        if cluster_size > 1 and alternatives and bool(item.get("is_cluster_representative")):
            print(f"     {cluster_label} 代表票， 同簇备选: {', '.join(alternatives[:2])}")

    print(f"{Fore.WHITE}{'─' * 72}{Style.RESET_ALL}")

    # Quick tips
    strong_picks = [i for i in representative_picks if float(i.get("composite_score", 0.0) or 0.0) >= 0.5]
    if strong_picks:
        tickers = ", ".join(f"{Fore.CYAN}{str(p.get('ticker', ''))}{Style.RESET_ALL}" for p in strong_picks[:3])
        print(f"  💡 High confidence picks: {tickers}")
    else:
        print("  ⚠ No high-confidence picks today. Consider waiting for better signals.")

    print()
    return 0
