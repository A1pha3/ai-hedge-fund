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
from src.screening.consecutive_recommendation import (
    enrich_recommendations_with_history,
    resolve_report_dir,
)
from src.screening.data_quality_audit import _find_latest_report
from src.screening.expected_return import compute_expected_returns
from src.screening.investability import (
    build_front_door_verdict,
    rank_recommendations_by_investability,
    select_representative_candidates,
)
from src.screening.verify_recommendations import compute_verify_recommendations
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


# ---------------------------------------------------------------------------
# R4: Consecutive recommendation bonus
# ---------------------------------------------------------------------------

_CONSECUTIVE_BONUS: dict[int, float] = {
    3: 0.03,
    4: 0.04,
    5: 0.05,
}
_CONSECUTIVE_BONUS_DEFAULT = 0.08  # for 6+ days


def _consecutive_bonus(days: int) -> float:
    """Compute a small ranking bonus for consecutive recommendations."""
    if days < 3:
        return 0.0
    if days in _CONSECUTIVE_BONUS:
        return _CONSECUTIVE_BONUS[days]
    return _CONSECUTIVE_BONUS_DEFAULT


def _status_icon(status: str) -> str:
    """Map consecutive status to a compact icon."""
    if "reentry" in status:
        return "🔄"
    if "3plus" in status:
        return "🔁"
    if "2days" in status:
        return "🔁"
    if "broken" in status:
        return "⬇️"
    return "🆕"


# ---------------------------------------------------------------------------
# R5: Historical hit-rate summary
# ---------------------------------------------------------------------------


def _render_hit_rate_summary(verify_summary: object) -> str:
    """Render a compact historical hit-rate summary for the front door."""
    lines = [f"\n  {Fore.CYAN}📊 历史命中率速览{Style.RESET_ALL}"]

    total = getattr(verify_summary, "total_recommendations", 0)
    days = getattr(verify_summary, "total_days", 0)
    if not total or not days:
        return ""

    unique = getattr(verify_summary, "unique_tickers", 0)
    lookback = getattr(verify_summary, "lookback_days", 30)
    lines.append(
        f"  近 {lookback} 天: {days} 个交易日, "
        f"{total} 次推荐 ({unique} 只不重复标的)"
    )

    # Win rates
    wr_parts: list[str] = []
    for horizon, label in [("t5", "T+5"), ("t10", "T+10"), ("t30", "T+30")]:
        wr = getattr(verify_summary, f"overall_{horizon}_win_rate", None)
        if wr is not None:
            color = Fore.GREEN if wr >= 0.55 else Fore.YELLOW if wr >= 0.50 else Fore.RED
            wr_parts.append(f"{label} 胜率={color}{wr:.0%}{Style.RESET_ALL}")
    if wr_parts:
        lines.append("  " + " | ".join(wr_parts))

    # Average returns
    ret_parts: list[str] = []
    for horizon, label in [("t5", "T+5"), ("t30", "T+30")]:
        ret = getattr(verify_summary, f"avg_{horizon}_return", None)
        if ret is not None:
            color = Fore.GREEN if ret > 0 else Fore.RED
            ret_parts.append(f"{label} 均收={color}{ret:+.2f}%{Style.RESET_ALL}")
    if ret_parts:
        lines.append("  " + " | ".join(ret_parts))

    # Excess return
    excess = getattr(verify_summary, "excess_return", None)
    if excess is not None:
        color = Fore.GREEN if excess > 0 else Fore.RED
        lines.append(f"  超额收益(vs 沪深300): {color}{excess:+.2f}%{Style.RESET_ALL}")

    lines.append(f"  {Fore.WHITE}💡 历史表现不代表未来收益{Style.RESET_ALL}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Verdict distribution summary
# ---------------------------------------------------------------------------


def _render_verdict_distribution(picks: list[dict], market_regime: str) -> str:
    """Render BUY/HOLD/AVOID distribution for the representative picks."""
    counts = {"BUY": 0, "HOLD": 0, "AVOID": 0}
    for item in picks:
        verdict = build_front_door_verdict(item, market_regime=market_regime)
        action = verdict.get("action", "AVOID")
        counts[action] = counts.get(action, 0) + 1

    parts = []
    if counts["BUY"]:
        parts.append(f"{Fore.GREEN}BUY={counts['BUY']}{Style.RESET_ALL}")
    if counts["HOLD"]:
        parts.append(f"{Fore.YELLOW}HOLD={counts['HOLD']}{Style.RESET_ALL}")
    if counts["AVOID"]:
        parts.append(f"{Fore.RED}AVOID={counts['AVOID']}{Style.RESET_ALL}")

    return "  分布: " + " | ".join(parts) if parts else ""


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


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

    # R4: Enrich with consecutive recommendation data
    try:
        enriched = enrich_recommendations_with_history(
            recommendations=list(recs),
            lookback_days=10,
            report_dir=search_dir,
        )
        # Apply consecutive bonus to composite scores
        for rec in enriched:
            days = int(rec.get("consecutive_days", 0) or 0)
            rec["consecutive_bonus"] = _consecutive_bonus(days)
    except Exception:
        enriched = recs

    ranked = rank_recommendations_by_investability(enriched, composite, expected)

    # Apply consecutive bonus to ranking (re-sort with bonus)
    for rec in ranked:
        bonus = float(rec.get("consecutive_bonus", 0.0) or 0.0)
        if bonus:
            original_score = float(rec.get("composite_score", 0.0) or 0.0)
            rec["composite_score"] = round(original_score + bonus, 4)

    ranked.sort(
        key=lambda r: float(r.get("composite_score", 0.0) or 0.0),
        reverse=True,
    )

    representative_picks = select_representative_candidates(ranked, count=count)

    # Step 3: Render compact output
    print(f"\n{Fore.CYAN}{Style.BRIGHT}🎯 Today's Top Picks{Style.RESET_ALL}")
    print(f"  Date: {trade_date}  |  默认前门: composite confidence + T+30 posterior edge + 代表票去重 + 连续推荐加权")
    print(f"{Fore.WHITE}{'─' * 72}{Style.RESET_ALL}")

    for idx, item in enumerate(representative_picks, 1):
        composite_score = float(item.get("composite_score", item.get("score_b", 0.0)) or 0.0)
        grade = _composite_grade(composite_score)
        name = str(item.get("name", "") or item.get("ticker", ""))[:14]
        verdict = build_front_door_verdict(item, market_regime=market_regime)

        # R4: Consecutive recommendation display
        consec_days = int(item.get("consecutive_days", 0) or 0)
        consec_status = str(item.get("consecutive_status", "") or "")
        consec_icon = _status_icon(consec_status) if consec_days > 0 else ""
        consec_str = f" {consec_icon}{consec_days}d" if consec_days > 0 else ""

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
        bonus_val = float(item.get("consecutive_bonus", 0.0) or 0.0)
        if bonus_val > 0:
            parts.append(f"{Fore.GREEN}连续+{bonus_val:.2f}{Style.RESET_ALL}")

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
            f"{grade}{consec_str}  "
            f"(base={base_score:.3f} {signal_str})"
        )
        print(f"     操作={verdict['action']}  T+30={t30_str}  T+30胜率={t30_wr_str}  样本={sample_count}  市场门控={verdict['market_regime']}")
        print(f"     失效条件: {verdict['invalidation_reason']}")
        if cluster_size > 1 and alternatives and bool(item.get("is_cluster_representative")):
            print(f"     {cluster_label} 代表票， 同簇备选: {', '.join(alternatives[:2])}")

    print(f"{Fore.WHITE}{'─' * 72}{Style.RESET_ALL}")

    # Verdict distribution summary
    dist = _render_verdict_distribution(representative_picks, market_regime)
    if dist:
        print(dist)

    # Quick tips
    strong_picks = [i for i in representative_picks if float(i.get("composite_score", 0.0) or 0.0) >= 0.5]
    if strong_picks:
        tickers = ", ".join(f"{Fore.CYAN}{str(p.get('ticker', ''))}{Style.RESET_ALL}" for p in strong_picks[:3])
        print(f"  💡 High confidence picks: {tickers}")
    else:
        print("  ⚠ No high-confidence picks today. Consider waiting for better signals.")

    # R5: Historical hit-rate summary
    try:
        verify = compute_verify_recommendations(
            lookback_days=30,
            reports_dir=search_dir,
        )
        summary = _render_hit_rate_summary(verify)
        if summary:
            print(summary)
    except Exception:
        pass  # Non-critical: hit-rate summary is best-effort

    print()
    return 0
