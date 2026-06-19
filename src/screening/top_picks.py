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
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from src.screening.composite_score import (
    _composite_grade,
    compute_composite_scores,
)
from src.screening.conditional_order_advisor import (
    compute_conditional_advice,
    DEFAULT_ATR_PERIOD,
    DEFAULT_LOOKBACK_SESSIONS,
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

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# P16-1: Market gate warning
# ---------------------------------------------------------------------------


def _print_market_gate_regime_advice(regime: str) -> None:
    """Print the regime-specific MARKET GATE guidance block.

    Extracted from :func:`_render_market_gate`: three regime branches
    (crisis/risk_off, cautious/range, normal) each print a header line
    plus an action hint. Kept together so the tone and copy stay
    consistent across branches.
    """
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
    _print_market_gate_regime_advice(regime)

    return regime.lower() or "unknown"


# ---------------------------------------------------------------------------
# R4: Consecutive recommendation bonus
# ---------------------------------------------------------------------------

_CONSECUTIVE_BONUS: dict[int, float] = {
    3: 0.03,
    4: 0.04,
    5: 0.05,
}
_CONSECUTIVE_BONUS_DEFAULT = 0.08  # for 6+ days

# ---------------------------------------------------------------------------
# R32: Risk label thresholds (ATR / price ratio → 低/中/高)
# ---------------------------------------------------------------------------

#: ATR/price < this → 低风险
_RISK_LOW_THRESHOLD: float = 0.03
#: ATR/price < this (and >= LOW) → 中风险; >= this → 高风险
_RISK_HIGH_THRESHOLD: float = 0.05


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

    # Excess return vs the picks' own recommended-basket average (a same-day
    # reference point, NOT a market index — see verify_recommendations BETA-009).
    # H1 (Stage 3): the recommended-basket "benchmark" is computed from the SAME
    # picks as the basket mean, so excess_return is structurally ≈ 0.0 (it is a
    # mathematical identity: mean(picks) - mean(picks) = 0). Rendering a line that
    # is always ~0.00% adds noise and erodes trust in the conviction panel.
    # Suppress the line when the excess is within rounding of zero; a future real
    # benchmark (e.g. CSI300 via get_index_daily) would naturally render here.
    _EXCESS_RETURN_RENDER_EPSILON = 0.01
    excess = getattr(verify_summary, "excess_return", None)
    if excess is not None and abs(excess) > _EXCESS_RETURN_RENDER_EPSILON:
        color = Fore.GREEN if excess > 0 else Fore.RED
        lines.append(f"  超额收益(vs 推荐均值): {color}{excess:+.2f}%{Style.RESET_ALL}")

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
# R33: Portfolio expected return summary
# ---------------------------------------------------------------------------

#: Minimum BUY count to show portfolio summary (single BUY has no portfolio meaning)
_PORTFOLIO_SUMMARY_MIN_BUYS: int = 2


def _extract_t30_metrics(item: dict) -> tuple[float | None, float | None]:
    """Extract the T+30 expected-return edge and win-rate from a pick dict.

    Shared by the per-pick table row (:func:`_build_top_table_row`) and the R33
    portfolio summary (:func:`_render_portfolio_expected_return`) so the two
    rendering paths never diverge on the defensive-extraction logic.

    Returns ``(edge, winrate)`` where each value is the raw float when the
    field is present and numeric, otherwise ``None``.
    """
    t30 = (item.get("expected_returns") or {}).get("t30")
    t30_wr = (item.get("win_rates") or {}).get("t30")
    edge = float(t30) if isinstance(t30, (int, float)) else None
    winrate = float(t30_wr) if isinstance(t30_wr, (int, float)) else None
    return edge, winrate


def _render_portfolio_expected_return(picks: list[dict], market_regime: str) -> str:
    """R33: Render a one-line equal-weighted T+30 expected return for all BUY picks.

    Reuses the per-pick ``expected_returns.t30`` and ``win_rates.t30`` already
    attached by :func:`rank_recommendations_by_investability`.

    The aggregate is equal-weighted. A previous per-pick ``sample_count < 20``
    halving scheme was removed because it was unreachable:
    :func:`build_front_door_verdict` requires a sufficient backing sample (raw
    ``bucket_sample_count >= 20``, or — when the R35 field is present —
    ``bucket_t30_mature_count >= 20``) for any BUY classification, so a
    low-sample pick can never enter this BUY-only aggregate. Equal weighting
    matches the spec's documented alternative ("等权或 composite_score 归一化");
    see ``test_low_sample_pick_can_never_be_buy`` for the guard that pins this.

    Returns empty string when fewer than 2 BUY picks or no T+30 data.
    """
    buy_picks: list[dict] = []
    for item in picks:
        verdict = build_front_door_verdict(item, market_regime=market_regime)
        if verdict.get("action") == "BUY":
            buy_picks.append(item)

    if len(buy_picks) < _PORTFOLIO_SUMMARY_MIN_BUYS:
        return ""

    # Equal weighting across BUY picks that carry a T+30 edge.
    edges: list[float] = []
    winrates: list[float] = []
    for item in buy_picks:
        edge, winrate = _extract_t30_metrics(item)
        if edge is not None:
            edges.append(edge)
        # Win-rate may be absent on some picks even when the T+30 edge is present
        # (different calibration fields).  Track its own denominator so the average
        # is not diluted by picks that have no win-rate data.
        if winrate is not None:
            winrates.append(winrate)

    if not edges:
        return ""

    avg_edge = sum(edges) / len(edges)
    avg_winrate = sum(winrates) / len(winrates) if winrates else 0.0
    edge_color = Fore.GREEN if avg_edge > 0 else Fore.RED if avg_edge < 0 else Fore.WHITE
    # Win-rate color thresholds must match the canonical thresholds used
    # everywhere else in the front door (e.g. _render_hit_rate_summary line ~183
    # and the BUY verdict gate which requires t30_win_rate >= 0.55). The
    # previous 0.45 yellow band was an inconsistent outlier: a BUY portfolio
    # (every pick >= 0.55) could never reach it, yet a future verdict-gate
    # change would silently surface a "good enough" yellow on picks that fail
    # the BUY bar elsewhere. Align to 0.50. See BH-003.
    wr_color = Fore.GREEN if avg_winrate >= 0.55 else Fore.YELLOW if avg_winrate >= 0.50 else Fore.RED

    return (
        f"  {Fore.WHITE}组合 T+30 预期:{Style.RESET_ALL} "
        f"{edge_color}{avg_edge:+.2f}% (加权){Style.RESET_ALL} | "
        f"{Fore.WHITE}平均胜率:{Style.RESET_ALL} {wr_color}{avg_winrate:.0%}{Style.RESET_ALL} | "
        f"{Fore.WHITE}BUY 数:{Style.RESET_ALL} {len(buy_picks)}"
    )


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


def _format_stop_loss_take_profit(advice) -> str:
    """R8: Format a :class:`ConditionalOrderAdvice` as a stop-loss/take-profit line."""
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


def _compute_pick_risk_advice(
    ticker: str,
    name: str,
    *,
    trade_date: str,
):
    """R32: Fetch price history and compute conditional advice (shared by R8 + R32).

    Returns the :class:`ConditionalOrderAdvice` or ``None`` on any failure
    (best-effort — the front door must never crash on data-fetch errors).
    """
    try:
        from src.tools.tushare_api import get_ashare_prices_with_tushare

        end_dt = datetime.strptime(trade_date, "%Y%m%d") if len(trade_date) == 8 else datetime.now()
        start_dt = (end_dt - timedelta(days=90)).strftime("%Y%m%d")
        end_str = end_dt.strftime("%Y%m%d")

        prices = get_ashare_prices_with_tushare(ticker, start_dt, end_str)
        if not prices:
            return None

        close_series = [float(p.close) for p in prices if p.close and p.close > 0]
        if not close_series:
            return None

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
            return None
        return advice
    except Exception:
        return None  # Best-effort: failure is non-critical


def _risk_label_from_advice(advice) -> tuple[str, float]:
    """R32: Map ATR/price ratio to a (label, ratio) risk level.

    Returns ``("低"/"中"/"高", atr_price_ratio)``.  When ATR or price is
    unavailable, returns ``("—", 0.0)``.
    """
    if advice is None or advice.current_price <= 0 or advice.atr <= 0:
        return ("—", 0.0)
    ratio = advice.atr / advice.current_price
    if ratio < _RISK_LOW_THRESHOLD:
        return ("低", ratio)
    if ratio < _RISK_HIGH_THRESHOLD:
        return ("中", ratio)
    return ("高", ratio)


def _render_reason_and_risk(item: dict, advice) -> str:
    """R32: Render a one-line reason + risk summary for a pick.

    Combines R15 factor attribution (top-2 factors) with an ATR-based risk
    label, so the user sees "why buy" and "how risky" in a single glance.
    Returns empty string when neither reason nor risk is available.
    """
    reason = _compute_factor_reason(item)

    risk_label, risk_ratio = _risk_label_from_advice(advice)
    risk_color = Fore.GREEN if risk_label == "低" else Fore.YELLOW if risk_label == "中" else Fore.RED if risk_label == "高" else Fore.WHITE

    if not reason and risk_label == "—":
        return ""
    reason_part = f"理由: {reason}" if reason else "理由: 数据不足"
    risk_part = f"风险: {risk_color}{risk_label}({risk_ratio:.1%}){Style.RESET_ALL}" if risk_label != "—" else "风险: 数据不足"
    return f"     {Fore.WHITE}{reason_part} | {risk_part}{Style.RESET_ALL}"


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
        # change_pct is None when previous_score == 0.0 (a prior day's score
        # coerced from None/NaN → 0.0 by ALPHA-002 makes the percentage
        # undefined). The old guard above only checked ``previous_score is
        # None``, so a 0.0 prior slipped through and rendered a flat "→"
        # instead of being suppressed as "no valid prior". Suppress here too.
        # See CAMPAIGN2-BH-6.
        if decay_info.change_pct is None:
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

    other_industries = [ind for ind, c in counter.most_common() if c < 2]
    if other_industries:
        other_names = "·".join(other_industries[:3])
        if len(other_industries) > 3:
            other_names += f"等{len(other_industries)}个"
        parts.append(f"{Fore.WHITE}{other_names}{Style.RESET_ALL}")

    if not parts:
        return ""

    return f"  🔥 行业聚焦: {' '.join(parts)}"


def _build_industry_momentum_map(rotation_signals: object) -> dict[str, float]:
    """Normalize the report rotation payload into an industry -> momentum map."""
    if not isinstance(rotation_signals, list):
        return {}

    momentum_map: dict[str, float] = {}
    for signal in rotation_signals:
        if not isinstance(signal, dict):
            continue
        name = str(signal.get("industry_name", "")).strip()
        score = float(signal.get("momentum_score", 0.0) or 0.0)
        if name:
            momentum_map[name] = score
    return momentum_map


def _collect_pick_industries(picks: list[dict]) -> list[str]:
    """Collect valid industries from the current representative picks."""
    industries = [str(p.get("industry_sw", "") or "未知").strip() for p in picks]
    return [industry for industry in industries if industry and industry != "未知"]


def _momentum_arrow(score: float) -> str:
    """Map a momentum score to the display arrow used by R14."""
    if score > 20:
        return f"{Fore.GREEN}↗{Style.RESET_ALL}"
    if score < -20:
        return f"{Fore.RED}↘{Style.RESET_ALL}"
    return f"{Fore.WHITE}→{Style.RESET_ALL}"


def _render_sector_rotation(report_data: dict, picks: list[dict]) -> str:
    """R14: Render sector rotation direction from industry_rotation data.

    Shows direction arrows for each industry in the current picks,
    using momentum_score from the report's industry_rotation payload.
    """
    momentum_map = _build_industry_momentum_map(report_data.get("industry_rotation") or [])
    if not momentum_map:
        return ""

    from collections import Counter

    industries = _collect_pick_industries(picks)
    if not industries:
        return ""

    counter = Counter(industries)
    parts = []
    for industry, count in counter.most_common():
        mom = momentum_map.get(industry)
        if mom is None:
            continue
        parts.append(f"{industry}{_momentum_arrow(mom)}")

    if not parts:
        return ""

    return f"  🔄 行业轮动: {' '.join(parts)}"


def _render_factor_attribution(item: dict) -> str:
    """R15: Render top-2 contributing factors for a recommendation.

    Shows which factors contribute most to the score, making the
    recommendation explainable. Uses existing strategy_signals data.
    """
    reason = _compute_factor_reason(item)
    if not reason:
        return ""
    return f" {Fore.WHITE}主因:{Style.RESET_ALL} {reason}"


#: Map strategy key → Chinese label (shared by R15 + R32)
_FACTOR_LABEL_MAP: dict[str, str] = {
    "trend": "趋势",
    "mean_reversion": "反转",
    "fundamental": "基本面",
    "event_sentiment": "情绪",
}


def _compute_factor_reason(item: dict) -> str:
    """Compute a plain-text top-2 factor reason string (no color/prefix).

    Shared by R15 (:func:`_render_factor_attribution`) and R32
    (:func:`_render_reason_and_risk`).  Returns ``""`` when no factors qualify.
    """
    signals = item.get("strategy_signals") or {}
    if not signals:
        return ""

    # Collect (factor_name, direction * confidence) pairs
    contributions: list[tuple[str, float]] = []
    for key, signal in signals.items():
        if not isinstance(signal, dict):
            continue
        direction = float(signal.get("direction", 0) or 0)
        confidence = float(signal.get("confidence", 0) or 0)
        strength = abs(direction * confidence)
        label = _FACTOR_LABEL_MAP.get(key, key)
        if direction > 0:
            contributions.append((f"{label}↑", strength))
        elif direction < 0:
            contributions.append((f"{label}↓", strength))

    if not contributions:
        return ""

    # Sort by strength, take top 2
    contributions.sort(key=lambda x: x[1], reverse=True)
    top = [c[0] for c in contributions[:2]]
    return " + ".join(top)


# ---------------------------------------------------------------------------
# R12: Data freshness guard
# ---------------------------------------------------------------------------


def _check_report_freshness(report_date: str, now: datetime | None = None) -> str:
    """Return a warning string if the report is stale (>1 *trading* day old).

    BH-015 / R45 same-class drain: prefers the real A-share ``trade_cal`` so
    that a pre-CNY report read mid-holiday does not trigger a false stale
    warning (no real trading days elapsed during closure). Falls back to the
    weekday approximation when no tushare token / network failure (R36
    behaviour preserved).

    A report is considered stale once >= 2 trading days have elapsed since its
    date — i.e. one full trading day has passed without a newer report, which
    means the user has not re-run ``--auto`` and may be trading on stale data.
    """
    if not report_date or len(report_date) != 8 or not report_date.isdigit():
        return ""
    try:
        report_dt = datetime.strptime(report_date, "%Y%m%d")
    except ValueError:
        return ""
    today = now or datetime.now()
    elapsed_trading_days = _trading_days_elapsed(report_dt, today)
    if elapsed_trading_days >= 2:
        formatted = report_dt.strftime("%Y-%m-%d")
        return (
            f"  {Fore.YELLOW}{Style.BRIGHT}⚠ 报告日期: {formatted}（非最新，请先运行 --auto 更新）{Style.RESET_ALL}"
        )
    return ""


def _trading_days_between(start: datetime, end: datetime) -> int:
    """Count A-share trading days strictly between *start* and *end* (exclusive).

    Prefers the real ``trade_cal`` open dates (BH-015 / R45 same-class drain)
    so that long holidays (Spring Festival, National Day) are correctly
    recognised as zero-trading-day gaps. Falls back to the Mon-Fri weekday
    approximation when ``trade_cal`` is unavailable (R36 behaviour preserved).

    ``start`` (the report's own trading day) and ``end`` (the review moment) are
    both excluded: the report's own day is already captured, and *end*'s trading
    day has not finished yet so its data may not exist. This makes a Friday
    report read on Monday count as 0 elapsed days (Mon's data is not ready).
    """
    if end.date() <= start.date():
        return 0
    real_count = _real_trading_days_between(start, end)
    if real_count is not None:
        return real_count
    # Fallback: Mon-Fri weekday approximation.
    count = 0
    current = start.date() + timedelta(days=1)
    last = end.date() - timedelta(days=1)
    while current <= last:
        if current.weekday() < 5:  # 0=Mon .. 4=Fri
            count += 1
        current += timedelta(days=1)
    return count


def _real_trading_days_between(start: datetime, end: datetime) -> int | None:
    """BH-015 / R45 same-class: count real A-share open trading days strictly
    between ``start`` and ``end`` using ``trade_cal``.

    Returns ``None`` (signaling fallback) when no tushare token / network
    failure / empty result. Excludes both endpoints to match
    ``_trading_days_between`` semantics.
    """
    try:
        from src.tools.tushare_api import get_open_trade_dates  # local import: keep startup light
    except Exception:  # pragma: no cover — defensive
        return None
    start_compact = start.strftime("%Y%m%d")
    end_compact = end.strftime("%Y%m%d")
    try:
        open_dates = get_open_trade_dates(start_compact, end_compact)
    except Exception:  # pragma: no cover — never block freshness on calendar fetch
        return None
    if not open_dates:
        logger.debug(
            "[TopPicks] get_open_trade_dates(%s, %s) returned empty — falling "
            "back to weekday approximation (R36). Freshness guard accuracy "
            "during long holidays (CNY/National Day) will be degraded.",
            start_compact,
            end_compact,
        )
        return None
    # Strictly between: exclude both endpoints.
    return sum(1 for d in open_dates if start_compact < d < end_compact)


def _trading_days_elapsed(report_dt: datetime, now: datetime) -> int:
    """Trading days that passed between the report and the latest expected day.

    The "latest expected trading day" rolls *now* back to the most recent
    weekday (a Saturday/Sunday review is really a review of Friday's data), so
    reading a Friday report on Saturday/Sunday/Monday all count as 0 elapsed
    trading days — Monday's data may not exist yet at the time of review.
    """
    latest = now
    while latest.weekday() >= 5:  # roll weekends back to Friday
        latest -= timedelta(days=1)
    return _trading_days_between(report_dt, latest)


# ---------------------------------------------------------------------------
# R13: New / dropped pick detection
# ---------------------------------------------------------------------------


def _find_previous_report(current_path: Path) -> Path | None:
    """Find the report file immediately before *current_path* in the same dir.

    Files are named ``auto_screening_YYYYMMDD.json``. We sort by name
    (lexicographic = chronological) and return the entry just before the
    one matching *current_path*.
    """
    candidates = sorted(current_path.parent.glob("auto_screening_*.json"))
    if len(candidates) < 2:
        return None
    try:
        idx = candidates.index(current_path)
    except ValueError:
        return None
    if idx == 0:
        return None
    return candidates[idx - 1]


def _compute_pick_changes(
    current_tickers: set[str],
    prev_path: Path,
) -> tuple[set[str], set[str]]:
    """Return (new_tickers, dropped_tickers) compared to previous report."""
    try:
        prev_data = json.loads(prev_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set(), set()
    prev_recs = prev_data.get("recommendations") or []
    prev_tickers = {str(r.get("ticker", "")) for r in prev_recs if str(r.get("ticker", ""))}
    new = current_tickers - prev_tickers
    dropped = prev_tickers - current_tickers
    return new, dropped


def _render_pick_changes(new: set[str], dropped: set[str], current_items: list[dict]) -> str:
    """Render a one-line summary of new/dropped picks."""
    parts = []
    if new:
        # Get names for new tickers
        name_map = {str(it.get("ticker", "")): str(it.get("name", "") or it.get("ticker", "")) for it in current_items}
        new_labels = [f"{Fore.GREEN}🆕 {name_map.get(t, t)}{Style.RESET_ALL}" for t in sorted(new)[:3]]
        extra = f" +{len(new) - 3}个" if len(new) > 3 else ""
        parts.append("新入选: " + ", ".join(new_labels) + extra)
    if dropped:
        drop_labels = [f"{Fore.RED}❌ {t}{Style.RESET_ALL}" for t in sorted(dropped)[:3]]
        extra = f" +{len(dropped) - 3}个" if len(dropped) > 3 else ""
        parts.append("退出: " + ", ".join(drop_labels) + extra)
    if not parts:
        return ""
    return "  📊 " + " | ".join(parts)


def _enrich_with_consecutive_bonus(recommendations: list[dict], report_dir: Path) -> list[dict]:
    """Best-effort enrichment for consecutive recommendation metadata."""
    try:
        enriched = enrich_recommendations_with_history(
            recommendations=list(recommendations),
            lookback_days=10,
            report_dir=report_dir,
        )
    except Exception:
        return recommendations

    for recommendation in enriched:
        days = int(recommendation.get("consecutive_days", 0) or 0)
        recommendation["consecutive_bonus"] = _consecutive_bonus(days)
    return enriched


def _apply_consecutive_bonus_and_resort(ranked: list[dict]) -> list[dict]:
    """Fold the consecutive-recommendation bonus into composite_score and re-sort.

    Extracted from :func:`_build_ranked_candidates`. The ranker produces an
    initial ordering; consecutive-day bonus (R4) is then added on top of each
    item's composite_score and the list re-sorted descending so bonus-boosted
    picks bubble up. Mutates ``ranked`` in place and returns it.
    """
    for recommendation in ranked:
        bonus = float(recommendation.get("consecutive_bonus", 0.0) or 0.0)
        if not bonus:
            continue
        original_score = float(recommendation.get("composite_score", 0.0) or 0.0)
        # Re-clamp to the documented [-1.0, 1.0] domain (composite_score.py:16).
        # compute_composite_scores already clamps, but the bonus is added after,
        # so a high-base pick (0.98) + 6+day bonus (0.08) would otherwise reach 1.06.
        recommendation["composite_score"] = round(max(-1.0, min(1.0, original_score + bonus)), 4)
    ranked.sort(
        key=lambda recommendation: float(recommendation.get("composite_score", 0.0) or 0.0),
        reverse=True,
    )
    return ranked


def _build_ranked_candidates(
    recommendations: list[dict],
    report_dir: Path,
    lookback_days: int,
) -> list[dict]:
    """Compute ranked candidates with expected returns and consecutive bonus."""
    composite = compute_composite_scores(
        top_n=len(recommendations),
        lookback_days=lookback_days,
        reports_dir=report_dir,
    )
    expected = compute_expected_returns(
        recommendations=recommendations,
        lookback_days=max(60, lookback_days),
        reports_dir=report_dir,
    )
    if not composite.items:
        return []

    ranked = rank_recommendations_by_investability(
        _enrich_with_consecutive_bonus(recommendations, report_dir),
        composite,
        expected,
    )
    return _apply_consecutive_bonus_and_resort(ranked)


def _load_recommendation_context(
    report_dir: Path,
    count: int,
) -> tuple[Path, dict, list[dict], str] | None:
    """Load the latest screening report and its candidate recommendations."""
    report_path = _find_latest_report(report_dir)
    if report_path is None:
        return None

    try:
        report_data = json.loads(report_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        # R106 (R88/BH-017 family): reports/ 目录混入 corrupt
        # auto_screening_*.json (运行中断 / 部分写入 / 磁盘错误留下的半截文件)
        # 时, 前门此前抛 raw JSONDecodeError traceback 中断整个默认前门。
        # 与 missing-report 一致语义 (返回 None) + 用户可见 warning 提示
        # "重新运行 --auto 生成", 让用户看到可操作提示而非 raw traceback。
        print(
            f"{Fore.RED}[TopPicks] 读取报告失败 ({report_path.name}, 可能是运行中断/"
            f"部分写入留下的损坏文件): {exc}{Style.RESET_ALL}"
        )
        print(
            f"{Fore.YELLOW}[TopPicks] 请重新运行 --auto 生成新的 auto_screening 报告。{Style.RESET_ALL}"
        )
        return None
    recommendations = (report_data.get("recommendations") or [])[:count * 3]
    trade_date = str(report_data.get("date", "") or "")
    return report_path, report_data, recommendations, trade_date


def _detect_pick_changes(report_path: Path, ranked: list[dict]) -> tuple[set[str], set[str]]:
    """Compare the current ranked candidates against the previous report."""
    all_current_tickers = {str(item.get("ticker", "")) for item in ranked if str(item.get("ticker", ""))}
    prev_report = _find_previous_report(report_path)
    if prev_report is None:
        return set(), set()
    return _compute_pick_changes(all_current_tickers, prev_report)


def _build_signal_breakdown(item: dict) -> str:
    """Render the compact signal breakdown shown next to the base score."""
    signal_specs = (
        ("momentum_bonus", f"{Fore.GREEN}动量↑{Style.RESET_ALL}", f"{Fore.RED}动量↓{Style.RESET_ALL}", 0.0),
        ("sector_bonus", f"{Fore.GREEN}行业强{Style.RESET_ALL}", f"{Fore.RED}行业弱{Style.RESET_ALL}", 0.0),
        ("consistency_adj", f"{Fore.GREEN}一致{Style.RESET_ALL}", f"{Fore.RED}分歧{Style.RESET_ALL}", 0.0),
        ("volume_factor", f"{Fore.GREEN}放量{Style.RESET_ALL}", f"{Fore.RED}缩量{Style.RESET_ALL}", 0.0),
        ("trend_resonance_factor", f"{Fore.GREEN}共振↑{Style.RESET_ALL}", f"{Fore.RED}冲突{Style.RESET_ALL}", 0.02),
    )
    parts: list[str] = []
    for key, positive_label, negative_label, threshold in signal_specs:
        value = float(item.get(key, 0.0) or 0.0)
        if value > threshold:
            parts.append(positive_label)
        elif value < -threshold:
            parts.append(negative_label)
    bonus_val = float(item.get("consecutive_bonus", 0.0) or 0.0)
    if bonus_val > 0:
        parts.append(f"{Fore.GREEN}连续+{bonus_val:.2f}{Style.RESET_ALL}")
    return " ".join(parts) if parts else f"{Fore.WHITE}中性{Style.RESET_ALL}"


def _score_color(composite_score: float) -> str:
    """Choose the color used for the composite score display."""
    if composite_score >= 0.5:
        return Fore.GREEN + Style.BRIGHT
    if composite_score >= 0.3:
        return Fore.YELLOW
    return Fore.RED


@dataclass(frozen=True)
class TopPicksRenderContext:
    market_regime: str
    new_tickers: set[str]
    report_dir: Path
    trade_date: str


def _print_pick_entry_details(
    *,
    item: dict,
    verdict: dict,
    consec_days: int,
    context: TopPicksRenderContext,
) -> None:
    """Render the optional detail lines below a representative pick.

    Extracted from :func:`_print_pick_entry`: BUY stop-loss/take-profit,
    consecutive-day score trend, and cluster-representative alternatives.
    Each line is independent and only prints when its data is present.
    """
    ticker = str(item.get("ticker", ""))
    name = str(item.get("name", "") or "")

    # R32: compute risk advice once, share between R8 (stop-loss) and R32 (reason+risk)
    advice = None
    if verdict["action"] == "BUY":
        advice = _compute_pick_risk_advice(ticker, name, trade_date=context.trade_date)
        if advice is not None:
            sl_tp = _format_stop_loss_take_profit(advice)
            if sl_tp:
                print(sl_tp)

    # R32: one-line reason + risk (shown for all picks, not just BUY)
    reason_risk = _render_reason_and_risk(item, advice)
    if reason_risk:
        print(reason_risk)

    if consec_days >= 2:
        trend = _render_score_trend(
            ticker,
            report_dir=context.report_dir,
        )
        if trend:
            print(f"     趋势:{trend}")

    cluster_size = int(item.get("cluster_size", 1) or 1)
    alternatives = [str(ticker_alt) for ticker_alt in (item.get("cluster_alternatives") or []) if str(ticker_alt)]
    if cluster_size > 1 and alternatives and bool(item.get("is_cluster_representative")):
        cluster_label = str(item.get("cluster_label", "") or "")
        print(f"     {cluster_label} 代表票， 同簇备选: {', '.join(alternatives[:2])}")


def _print_pick_entry(
    idx: int,
    item: dict,
    context: TopPicksRenderContext,
) -> None:
    """Render a single representative pick and its optional detail lines."""
    composite_score = float(item.get("composite_score", item.get("score_b", 0.0)) or 0.0)
    grade = _composite_grade(composite_score)
    name = str(item.get("name", "") or item.get("ticker", ""))[:14]
    verdict = build_front_door_verdict(item, market_regime=context.market_regime)

    is_new = str(item.get("ticker", "")) in context.new_tickers
    new_badge = f" {Fore.GREEN}🆕{Style.RESET_ALL}" if is_new else ""

    consec_days = int(item.get("consecutive_days", 0) or 0)
    consec_status = str(item.get("consecutive_status", "") or "")
    consec_icon = _status_icon(consec_status) if consec_days > 0 else ""
    consec_str = f" {consec_icon}{consec_days}d" if consec_days > 0 else ""

    factor_attr = _render_factor_attribution(item)
    signal_str = _build_signal_breakdown(item)
    bullish, total = _compute_confluence(item)
    confluence_str = _render_confluence(bullish, total)

    t30, t30_wr = _extract_t30_metrics(item)
    sample_count = int(item.get("bucket_sample_count", 0) or 0)

    t30_str = f"{t30:+.2f}%" if t30 is not None else "—"
    t30_wr_str = f"{t30_wr:.0%}" if t30_wr is not None else "—"
    base_score = float(item.get("base_score", item.get("score_b", 0.0)) or 0.0)
    score_color = _score_color(composite_score)

    print(
        f"  {Fore.WHITE}{idx}.{Style.RESET_ALL} "
        f"{Fore.CYAN}{str(item.get('ticker', '')):<8}{Style.RESET_ALL} "
        f"{name:<14}{new_badge} "
        f"{score_color}{composite_score:>+.3f}{Style.RESET_ALL} "
        f"{grade}{consec_str} {confluence_str}  "
        f"(base={base_score:.3f} {signal_str}{factor_attr})"
    )
    print(f"     操作={verdict['action']}  T+30={t30_str}  T+30胜率={t30_wr_str}  样本={sample_count}  市场门控={verdict['market_regime']}")
    print(f"     失效条件: {verdict['invalidation_reason']}")

    _print_pick_entry_details(
        item=item,
        verdict=verdict,
        consec_days=consec_days,
        context=context,
    )


def _print_top_picks_header(
    trade_date: str,
    freshness_warning: str,
    representative_picks: list[dict],
    market_regime: str,
) -> None:
    """Render the static header block above the representative picks."""
    print(f"\n{Fore.CYAN}{Style.BRIGHT}🎯 Today's Top Picks{Style.RESET_ALL}")
    print(f"  Date: {trade_date}  |  默认前门: composite confidence + T+30 posterior edge + 代表票去重 + 连续推荐加权")
    if freshness_warning:
        print(freshness_warning)
    print(_render_market_opportunity_index(representative_picks, market_regime))
    print(f"{Fore.WHITE}{'─' * 72}{Style.RESET_ALL}")


def _print_high_confidence_summary(representative_picks: list[dict]) -> None:
    """Render the quick high-confidence summary line."""
    strong_picks = [item for item in representative_picks if float(item.get("composite_score", 0.0) or 0.0) >= 0.5]
    if strong_picks:
        tickers = ", ".join(f"{Fore.CYAN}{str(pick.get('ticker', ''))}{Style.RESET_ALL}" for pick in strong_picks[:3])
        print(f"  💡 High confidence picks: {tickers}")
        return
    print("  ⚠ No high-confidence picks today. Consider waiting for better signals.")


def _print_hit_rate_block(report_dir: Path) -> None:
    """Render the historical hit-rate summary when verification data is available."""
    try:
        verify = compute_verify_recommendations(
            lookback_days=30,
            reports_dir=report_dir,
        )
        summary = _render_hit_rate_summary(verify)
        if summary:
            print(summary)
    except Exception as exc:
        # BH-021 / R48 BH-017 同族: 前门命中率摘要 (R5) 静默失败时用户看不到任何信号。
        # 行为零变更 (仍 best-effort 跳过)，但发降级诊断让 verify pipeline 失败可观测。
        logger.debug("hit-rate summary degraded to skip: %s", exc)


def _print_top_picks_footer(
    report_data: dict,
    representative_picks: list[dict],
    market_regime: str,
    new_tickers: set[str],
    dropped_tickers: set[str],
    ranked: list[dict],
    report_dir: Path,
) -> None:
    """Render the footer summaries below the representative pick list."""
    print(f"{Fore.WHITE}{'─' * 72}{Style.RESET_ALL}")

    dist = _render_verdict_distribution(representative_picks, market_regime)
    if dist:
        print(dist)

    portfolio_edge = _render_portfolio_expected_return(representative_picks, market_regime)
    if portfolio_edge:
        print(portfolio_edge)

    sector_focus = _render_sector_focus(representative_picks)
    if sector_focus:
        print(sector_focus)

    sector_rotation = _render_sector_rotation(report_data, representative_picks)
    if sector_rotation:
        print(sector_rotation)

    if new_tickers or dropped_tickers:
        changes = _render_pick_changes(new_tickers, dropped_tickers, ranked)
        if changes:
            print(changes)

    _print_high_confidence_summary(representative_picks)
    _print_hit_rate_block(report_dir)
    _print_decision_flow_hint()
    _print_disclaimer()


def _print_disclaimer() -> None:
    """C65 (gamma trust calibration): research-only disclaimer on the default front door.

    The front door emits concrete BUY/HOLD/AVOID verdicts, T+30 edges, and
    stop-loss price levels. Without an inline boundary disclosure (which the
    PDF exporter at pdf_exporter.py:344 and the backtest CLI at
    backtesting/cli.py:128 already carry), a user can over-read the model
    output as a guaranteed investment directive. Echoing the project-level
    disclaimer serves the product goal "更高确信" (feature-proposals.md:29):
    conviction includes honestly naming the limits of model output, not just
    showing confident numbers.
    """
    print(
        f"  {Fore.WHITE}⚠ 以上推荐由 AI 模型自动生成, 仅供研究 / 学习用途, 不构成任何投资建议。"
        f"实际投资需结合个人风险承受能力与最新市场情况。{Style.RESET_ALL}"
    )


def _print_decision_flow_hint() -> None:
    """Round 9 quality slice: one-line pointer to the deep-analysis command.

    The front door (``--top-picks``) already covers fresh data, verdicts,
    T+30 edge, factor attribution, and stop-loss advice for most users.
    Pointing power users at ``--decision-flow`` (rather than leaving them to
    discover it) serves the "避免前门分裂" product goal: users get a single
    default entry and a clear escalation path, instead of running both
    commands. Follows the Round 6 research recommendation
    (round6-product-analysis.md:15).
    """
    print(
        f"  {Fore.CYAN}💡 深度分析（阈值/一致性/逐因子明细）请运行 --decision-flow{Style.RESET_ALL}"
    )


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

    context = _load_recommendation_context(search_dir, count)
    if context is None:
        print(f"{Fore.RED}No auto_screening report found. Run --auto first.{Style.RESET_ALL}")
        return 1

    report_path, report_data, recs, trade_date = context
    market_regime = _render_market_gate(trade_date)

    # R12: Data freshness guard
    freshness_warning = _check_report_freshness(trade_date)

    if not recs:
        print(f"{Fore.YELLOW}No recommendations in latest report.{Style.RESET_ALL}")
        return 0

    ranked = _build_ranked_candidates(
        recs,
        search_dir,
        lookback_days,
    )
    if not ranked:
        print(f"{Fore.YELLOW}Unable to compute composite scores.{Style.RESET_ALL}")
        return 0

    representative_picks = select_representative_candidates(ranked, count=count)

    # R13: Detect new/dropped picks vs previous report
    new_tickers, dropped_tickers = _detect_pick_changes(report_path, ranked)

    _print_top_picks_header(
        trade_date,
        freshness_warning,
        representative_picks,
        market_regime,
    )

    render_context = TopPicksRenderContext(
        market_regime=market_regime,
        new_tickers=new_tickers,
        report_dir=search_dir,
        trade_date=trade_date,
    )
    for idx, item in enumerate(representative_picks, 1):
        _print_pick_entry(idx, item, render_context)

    _print_top_picks_footer(
        report_data,
        representative_picks,
        market_regime,
        new_tickers,
        dropped_tickers,
        ranked,
        search_dir,
    )

    print()
    return 0
