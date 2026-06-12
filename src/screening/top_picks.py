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
from src.screening.conditional_order_advisor import (
    DEFAULT_ATR_PERIOD,
    DEFAULT_LOOKBACK_SESSIONS,
    compute_conditional_advice,
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
from src.screening.signal_decay_detector import detect_signal_decay
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
# Market opportunity index
# ---------------------------------------------------------------------------


def _render_market_opportunity_index(
    picks: list[dict],
    market_regime: str,
) -> str:
    """Compute and render a one-line market opportunity traffic light.

    Combines market regime, pick quality, and verdict distribution into
    a single GO / CAUTION / WAIT signal that tells the user whether today
    is a good day to invest.

    Logic:
      - Crisis/risk_off regime → WAIT (unless all picks are high-quality)
      - <50% picks are BUY and no high-quality picks → WAIT
      - >=50% picks are BUY or >=1 high-quality pick in normal regime → GO
      - Everything else → CAUTION
    """
    if not picks:
        return f"  {Fore.YELLOW}⚡ 机会指数: 无候选 — CAUTION{Style.RESET_ALL}"

    verdicts = [build_front_door_verdict(p, market_regime=market_regime) for p in picks]
    buy_count = sum(1 for v in verdicts if v.get("action") == "BUY")
    total = len(picks)

    # High-quality: composite >= 0.5
    high_quality = sum(1 for p in picks if float(p.get("composite_score", 0.0) or 0.0) >= 0.5)

    # Scoring
    score = 0.0
    if buy_count > 0:
        score += buy_count / total  # BUY ratio
    if high_quality > 0:
        score += 0.3  # bonus for having high-quality picks
    if "crisis" in market_regime or "risk_off" in market_regime:
        score -= 0.5  # market risk penalty
    elif "cautious" in market_regime or "range" in market_regime:
        score -= 0.15  # mild penalty for choppy markets

    if score >= 0.5:
        label = f"{Fore.GREEN}{Style.BRIGHT}🟢 GO{Style.RESET_ALL}"
        hint = "市场条件有利，推荐标的质量较高"
    elif score >= 0.2:
        label = f"{Fore.YELLOW}{Style.BRIGHT}🟡 CAUTION{Style.RESET_ALL}"
        hint = "信号参差，建议轻仓或等待更明确信号"
    else:
        label = f"{Fore.RED}{Style.BRIGHT}🔴 WAIT{Style.RESET_ALL}"
        hint = "市场风险偏高或标的质量不足，建议观望"

    return f"  机会指数: {label}  BUY {buy_count}/{total}  HQ {high_quality}  | {hint}"

# ---------------------------------------------------------------------------
# R8: Stop-loss / take-profit from conditional order advisor
# ---------------------------------------------------------------------------


def _render_stop_loss_take_profit(
    ticker: str,
    name: str,
    *,
    trade_date: str,
) -> str:
    """R8: Compute and render ATR-based stop-loss/take-profit for a single ticker.

    Fetches price history via tushare, computes ATR, and returns a compact
    one-line summary.  Returns empty string on any failure (best-effort).
    """
    try:
        from datetime import datetime, timedelta

        from src.tools.tushare_api import get_ashare_prices_with_tushare

        end_dt = datetime.strptime(trade_date, "%Y%m%d") if len(trade_date) == 8 else datetime.now()
        start_dt = (end_dt - timedelta(days=90)).strftime("%Y%m%d")
        end_str = end_dt.strftime("%Y%m%d")

        prices = get_ashare_prices_with_tushare(ticker, start_dt, end_str)
        if not prices:
            return ""

        close_series = [float(p.close) for p in prices if p.close and p.close > 0]
        if not close_series:
            return ""

        current_price = close_series[-1]
        advice = compute_conditional_advice(
            ticker=ticker,
            current_price=current_price,
            price_history=close_series,
            name=name,
            atr_period=DEFAULT_ATR_PERIOD,
            lookback_sessions=DEFAULT_LOOKBACK_SESSIONS,
        )

        if advice.degraded or advice.current_price <= 0:
            return ""

        sl_pct = ((advice.suggested_stop_loss - advice.current_price) / advice.current_price) * 100
        tp_pct = ((advice.suggested_take_profit - advice.current_price) / advice.current_price) * 100
        sl_color = Fore.RED
        tp_color = Fore.GREEN
        rr_color = Fore.YELLOW if advice.risk_reward_ratio < 1.5 else Fore.GREEN

        return (
            f"     {Fore.WHITE}止损止盈:{Style.RESET_ALL} "
            f"买入={advice.suggested_buy_zone[0]:.2f}-{advice.suggested_buy_zone[1]:.2f}  "
            f"{sl_color}止损={advice.suggested_stop_loss:.2f}({sl_pct:+.1f}%){Style.RESET_ALL}  "
            f"{tp_color}止盈={advice.suggested_take_profit:.2f}({tp_pct:+.1f}%){Style.RESET_ALL}  "
            f"{rr_color}盈亏比={advice.risk_reward_ratio:.1f}{Style.RESET_ALL}"
        )
    except Exception:
        return ""  # Best-effort: failure is non-critical


# ---------------------------------------------------------------------------
# R9: Score trend from signal decay data
# ---------------------------------------------------------------------------


def _render_score_trend(
    ticker: str,
    *,
    report_dir: Path,
    lookback_days: int = 10,
) -> str:
    """R9: Render score trend direction for a consecutively-recommended ticker.

    Uses signal_decay_detector to compare current vs historical score_b.
    Returns a compact trend indicator: ↑↑ / → / ↓↓.
    Returns empty string if no decay data or first-time recommendation.
    """
    try:
        # Load the most recent report for current score
        latest_path = _find_latest_report(report_dir)
        if latest_path is None:
            return ""
        latest_data = json.loads(latest_path.read_text(encoding="utf-8"))
        current_recs = latest_data.get("recommendations") or []
        current_score = 0.0
        for rec in current_recs:
            if str(rec.get("ticker", "")) == ticker:
                current_score = float(rec.get("score_b", 0.0) or 0.0)
                break

        # Load previous reports to find historical score
        decay_map = detect_signal_decay(
            current_recommendations=[{"ticker": ticker, "score_b": current_score}],
            report_dir=report_dir,
            lookback_days=lookback_days,
        )
        decay_info = decay_map.get(ticker)
        if decay_info is None or decay_info.previous_score is None:
            return ""

        change_pct = float(decay_info.change_pct or 0.0)

        if change_pct > 5:
            return f" {Fore.GREEN}↑↑{Style.RESET_ALL}"
        elif change_pct > -5:
            return f" {Fore.WHITE}→{Style.RESET_ALL}"
        else:
            return f" {Fore.RED}↓↓{Style.RESET_ALL}"
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# R10: Multi-strategy confluence indicator
# ---------------------------------------------------------------------------


def _compute_confluence(item: dict) -> tuple[int, int]:
    """Count how many of the 4 strategies have direction=1 (bullish).

    Returns (bullish_count, total_strategies).
    """
    signals = item.get("strategy_signals") or {}
    if not signals:
        return 0, 0
    bullish = sum(1 for s in signals.values() if isinstance(s, dict) and s.get("direction") == 1)
    return bullish, len(signals)


def _render_confluence(bullish: int, total: int) -> str:
    """Render a compact confluence badge like '共振 4/4'."""
    if total == 0:
        return ""
    ratio = bullish / total
    if ratio >= 1.0:
        color = Fore.GREEN + Style.BRIGHT
    elif ratio >= 0.75:
        color = Fore.GREEN
    elif ratio >= 0.5:
        color = Fore.YELLOW
    else:
        color = Fore.WHITE
    return f"{color}共振 {bullish}/{total}{Style.RESET_ALL}"


# ---------------------------------------------------------------------------
# R11: Sector focus summary
# ---------------------------------------------------------------------------


def _render_sector_focus(picks: list[dict]) -> str:
    """Render a one-line sector distribution summary for the picks.

    Shows industries with count >= 2 first, then remaining as '其他'.
    """
    from collections import Counter

    industries = [str(p.get("industry_sw", "") or "未知").strip() for p in picks]
    industries = [i for i in industries if i and i != "未知"]
    if not industries:
        return ""

    counter = Counter(industries)
    parts = []
    for industry, count in counter.most_common():
        if count >= 2:
            parts.append(f"{Fore.CYAN}{industry}{Style.RESET_ALL}({count})")

    other = sum(c for _, c in counter.most_common() if c < 2)
    other_industries = [ind for ind, c in counter.most_common() if c < 2]
    if other_industries:
        other_names = "·".join(other_industries[:3])
        if len(other_industries) > 3:
            other_names += f"等{len(other_industries)}个"
        parts.append(f"{Fore.WHITE}{other_names}{Style.RESET_ALL}")

    if not parts:
        return ""

    return f"  🔥 行业聚焦: {' '.join(parts)}"


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
    trade_date = report_data.get("date", "")
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
    # Market opportunity traffic light
    opp = _render_market_opportunity_index(representative_picks, market_regime)
    print(opp)
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

        # R10: Multi-strategy confluence
        bullish, total = _compute_confluence(item)
        confluence_str = _render_confluence(bullish, total)

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
            f"{grade}{consec_str} {confluence_str}  "
            f"(base={base_score:.3f} {signal_str})"
        )
        print(f"     操作={verdict['action']}  T+30={t30_str}  T+30胜率={t30_wr_str}  样本={sample_count}  市场门控={verdict['market_regime']}")
        print(f"     失效条件: {verdict['invalidation_reason']}")

        # R8: Stop-loss/take-profit for BUY picks
        if verdict["action"] == "BUY":
            sl_tp = _render_stop_loss_take_profit(
                str(item.get("ticker", "")),
                str(item.get("name", "") or ""),
                trade_date=trade_date,
            )
            if sl_tp:
                print(sl_tp)

        # R9: Score trend for consecutive recommendations
        if consec_days >= 2:
            trend = _render_score_trend(
                str(item.get("ticker", "")),
                report_dir=search_dir,
            )
            if trend:
                print(f"     趋势:{trend}")

        if cluster_size > 1 and alternatives and bool(item.get("is_cluster_representative")):
            print(f"     {cluster_label} 代表票， 同簇备选: {', '.join(alternatives[:2])}")

    print(f"{Fore.WHITE}{'─' * 72}{Style.RESET_ALL}")

    # Verdict distribution summary
    dist = _render_verdict_distribution(representative_picks, market_regime)
    if dist:
        print(dist)

    # R11: Sector focus summary
    sector_focus = _render_sector_focus(representative_picks)
    if sector_focus:
        print(sector_focus)

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
