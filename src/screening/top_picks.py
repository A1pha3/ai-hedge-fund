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
    _max_short_horizon_metric,
    _safe_metric,
    build_front_door_verdict,
    rank_recommendations_by_investability,
    select_representative_candidates,
)
from src.screening.signal_decay_detector import detect_signal_decay
from src.screening.verify_recommendations import compute_verify_recommendations
from src.utils.numeric import safe_float as _safe_float_value
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

    # MarketState 的字段是 regime_gate_level (src/screening/models.py:76), 不是 regime。
    # 此前引用 getattr(state, "regime") 永远返回空 → market_regime 全程为 "unknown"
    # → 依赖 market_regime 的 verdict/前端门/R-5.A 全部失效。修为正确字段名。
    regime = str(getattr(state, "regime_gate_level", "") or "")
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

    Used by the per-pick table row (:func:`_build_top_table_row`) to render the
    long-horizon *invalidation* view (T+30 edge<0 → "T+30 edge 转负" reason in
    ``build_front_door_verdict``). T+30 is intentionally NOT the BUY-gate
    decision horizon (see C220 commit 4184dd7e + C222 horizon 一致性) — it is
    the long-term衰退 signal retained alongside the short-horizon decision.

    For BUY-gate decision-horizon (T+5/T+10) extraction use
    :func:`_extract_decision_horizon_metrics` instead.

    Returns ``(edge, winrate)`` where each value is the raw float when the
    field is present and numeric, otherwise ``None``.
    """
    t30 = (item.get("expected_returns") or {}).get("t30")
    t30_wr = (item.get("win_rates") or {}).get("t30")
    edge = float(t30) if isinstance(t30, (int, float)) else None
    winrate = float(t30_wr) if isinstance(t30_wr, (int, float)) else None
    return edge, winrate


def _extract_decision_horizon_metrics(item: dict) -> tuple[float | None, float | None]:
    """Extract the BUY-gate decision-horizon (max of T+5/T+10) edge and win-rate.

    C222 (2026-06-28 horizon 一致性): BUY gate decision horizon is T+5 OR T+10
    (see ``_meets_quality_bar`` C220 commit 4184dd7e, per-horizon bootstrap CI
    in C219: T+5 winrate=60.2% [59.0%, 61.3%], T+10 winrate=60.5% [59.4%, 61.6%],
    but T+30 winrate=45.4% [44.2%, 46.5%] << 50%). Position sizing
    (:func:`_suggest_position_pct`) and portfolio P&L aggregation
    (:func:`_render_portfolio_expected_return`) must use the SAME horizon as
    the BUY verdict — using T+30 here would mis-state the expected return of
    a BUY portfolio (a BUY stock was admitted on T+5/T+10 strength, so its
    expected return should be quoted on T+5/T+10, not on T+30 where the
    same population has <50% winrate).

    Returns ``(edge, winrate)`` where each is ``max(t5, t10)`` when at least
    one short-horizon entry is numeric; ``None`` when no short-horizon data
    is present. Uses :func:`investability._max_short_horizon_metric` to stay
    in sync with the ranking sort key tie-breaker.
    """
    edge = _max_short_horizon_metric(item.get("expected_returns"))
    winrate = _max_short_horizon_metric(item.get("win_rates"))
    return edge, winrate


def _format_sample_count(item: dict) -> str:
    """O-2/R35: format the bucket sample count with a mature-T+30 suffix.

    The displayed T+30 winrate is computed over ALL bucket records
    (``bucket_sample_count``), but only *mature* records
    (R35 ``bucket_t30_mature_count``) have full 30-day outcomes — and the BUY
    gate requires mature >= 20. When fewer records are mature than the total,
    show ``样本=N(熟M)`` so the user can calibrate confidence: a 62% winrate
    on 50 samples of which only 20 are mature is weaker evidence than the bare
    "样本=50" implies. Serves the "更高确信" goal via honest sample disclosure.
    """
    total = int(item.get("bucket_sample_count", 0) or 0)
    mature_raw = item.get("bucket_t30_mature_count")
    if mature_raw is None:
        return f"{total}"
    try:
        mature = int(mature_raw)
    except (TypeError, ValueError):
        return f"{total}"
    if 0 <= mature < total:
        return f"{total}(熟{mature})"
    return f"{total}"


def _classify_return_rhythm(expected_returns: dict | None) -> str:
    """O-3: classify the T+30 gain pattern as 早 / 匀 / 晚 from the 5-horizon
    cumulative return shape. Serves the product goal's explicit "持续时间综合最优"
    dimension (10天涨50% vs 5天涨20% are different winners — the user must
    distinguish a fast-mover that fades from a slow-grind that holds).

    Display-only: does NOT enter ranking (avoids a new sort-dimension bloat).
    Thresholds (tunable): 早 = ≥60% of T+30 gain realized by T+5; 晚 = ≥40% of
    T+30 gain realized after T+20; else 匀. Returns "—" when the edge is
    non-positive or the anchor horizons (t5/t20/t30) are missing/non-numeric.
    """
    if not expected_returns:
        return "—"
    t5 = expected_returns.get("t5")
    t20 = expected_returns.get("t20")
    t30 = expected_returns.get("t30")
    if not all(isinstance(x, (int, float)) for x in (t5, t20, t30)):
        return "—"
    if t30 <= 0:
        return "—"
    early_share = t5 / t30
    late_share = (t30 - t20) / t30
    if early_share >= 0.60:
        return "早"
    if late_share >= 0.40:
        return "晚"
    return "匀"


#: A-1 per-pick position diversification cap (single-name ceiling).
_MAX_POSITION_PCT: float = 15.0


def _suggest_position_pct(
    *,
    decision_edge: float | None,
    decision_winrate: float | None,
    market_regime: str,
    max_per_pick: float = _MAX_POSITION_PCT,
) -> float:
    """A-1: transparent per-pick position suggestion for BUY picks (educational
    decision-support). Simple risk-budget, NOT portfolio optimization (no
    correlation / risk-parity / mean-variance) — reuses the R71-R77 disclaimer.

    C222 (2026-06-28 horizon 一致性): ``decision_edge`` / ``decision_winrate``
    are the BUY-gate decision-horizon metrics (max of T+5/T+10), NOT T+30.
    Previously named ``t30_edge`` / ``t30_winrate`` which misrepresented the
    computation: a BUY pick is admitted on T+5/T+10 strength (see
    ``_meets_quality_bar`` C220 commit 4184dd7e), so sizing it by T+30 edge
    would under-allocate when T+5/T+10 edge > T+30 edge (the typical case
    for low-bucket short-term rebound tickets per C219). Callers should
    source these via :func:`_extract_decision_horizon_metrics`.

    Formula (tunable): base = |edge| × confidence × 100, where confidence normalizes
    winrate above the 0.50 coin-flip (0.50→0, 0.70→1.0, 1.0→2.5). Regime downgrade:
    crisis/risk_off/halt → 0 (stand aside); cautious/range → ×0.5. Capped at
    ``max_per_pick`` (15% single-name ceiling for diversification). Returns 0.0 for
    non-positive edge, missing inputs, or risk-off regimes — bridging "买哪只 → 买多少"
    without over-stepping into investment directive.
    """
    if decision_edge is None or decision_winrate is None or decision_edge <= 0:
        return 0.0
    regime_lower = str(market_regime).lower()
    if "crisis" in regime_lower or "risk_off" in regime_lower or "halt" in regime_lower:
        return 0.0
    confidence = max(0.0, (decision_winrate - 0.50) / 0.20)
    # C260 (2026-06-30): decision_edge is in PERCENT (the BUY-gate decision-horizon
    # expected return, max of T+5/T+10; see _extract_decision_horizon_metrics which
    # reads expected_returns percent values rendered as f"{decision_edge:+.2f}%").
    # The prior `* 100.0` was a unit-conversion leftover from when edge was a fraction
    # (0.08) — it saturated max_per_pick for ~all BUY picks (edge 4.66 * conf 0.485
    # * 100 = 225 -> capped 15), making the per-pick suggestion a constant 15% and
    # destroying the conviction-based differentiation the feature exists to provide.
    # With percent input, base = edge% * confidence is already in percent.
    base = abs(decision_edge) * confidence
    if "cautious" in regime_lower or "range" in regime_lower:
        base *= 0.5
    return round(min(base, max_per_pick), 1)


def _render_portfolio_expected_return(picks: list[dict], market_regime: str) -> str:
    """R33: Render a one-line equal-weighted decision-horizon (T+5/T+10) expected
    return for all BUY picks.

    C222 (2026-06-28 horizon 一致性): previously aggregated T+30 edge/winrate,
    but BUY gate decision horizon is T+5 OR T+10 (see ``_meets_quality_bar``
    C220 commit 4184dd7e). Quoting a BUY portfolio's expected return on T+30
    mis-states the population's actual edge — the same picks have T+30 winrate
    ~45% (per C219 bootstrap CI n=7201), so an "T+30 avg edge=+0.5%" header
    on a BUY portfolio would falsely imply 30-day hold alpha when the alpha is
    actually a 5-10 day rebound. Now uses ``_extract_decision_horizon_metrics``
    (max of T+5/T+10) so the quoted edge/winrate matches the horizon on which
    the BUY verdict was issued.

    Reuses the per-pick ``expected_returns.t5`` / ``t10`` and ``win_rates.t5`` /
    ``t10`` already attached by :func:`rank_recommendations_by_investability`.

    The aggregate is equal-weighted. A previous per-pick ``sample_count < 20``
    halving scheme was removed because it was unreachable:
    :func:`build_front_door_verdict` requires a sufficient backing sample (raw
    ``bucket_sample_count >= 20``, or — when the R35 field is present —
    ``bucket_t30_mature_count >= 20``) for any BUY classification, so a
    low-sample pick can never enter this BUY-only aggregate. Equal weighting
    matches the spec's documented alternative ("等权或 composite_score 归一化");
    see ``test_low_sample_pick_can_never_be_buy`` for the guard that pins this.

    Returns empty string when fewer than 2 BUY picks or no decision-horizon
    (T+5/T+10) data.
    """
    buy_picks: list[dict] = []
    for item in picks:
        verdict = build_front_door_verdict(item, market_regime=market_regime)
        if verdict.get("action") == "BUY":
            buy_picks.append(item)

    if len(buy_picks) < _PORTFOLIO_SUMMARY_MIN_BUYS:
        return ""

    # Equal weighting across BUY picks that carry a decision-horizon edge.
    # Uses max(t5, t10) per pick (the same horizon that justified its BUY
    # verdict), NOT t30 — see C222 horizon 一致性 comment above.
    edges: list[float] = []
    winrates: list[float] = []
    for item in buy_picks:
        edge, winrate = _extract_decision_horizon_metrics(item)
        if edge is not None:
            edges.append(edge)
        # Win-rate may be absent on some picks even when the edge is present
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
    # and the BUY verdict gate which requires t5/t10 win_rate >= 0.55). The
    # previous 0.45 yellow band was an inconsistent outlier: a BUY portfolio
    # (every pick >= 0.55) could never reach it, yet a future verdict-gate
    # change would silently surface a "good enough" yellow on picks that fail
    # the BUY bar elsewhere. Align to 0.50. See BH-003.
    wr_color = Fore.GREEN if avg_winrate >= 0.55 else Fore.YELLOW if avg_winrate >= 0.50 else Fore.RED

    return (
        f"  {Fore.WHITE}组合 T+5/T+10 决策预期:{Style.RESET_ALL} "
        f"{edge_color}{avg_edge:+.2f}% (等权){Style.RESET_ALL} | "
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
                # NS-13 family drain: NaN score_b 经 `float(x or 0.0)` 仍 truthy 不兜底,
                # 进入 detect_signal_decay 污染 change_pct 计算. 用 safe_float 源头拒绝.
                current_score = _safe_float_value(rec.get("score_b", 0.0), 0.0)
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


def _render_exit_timing_line(
    ticker: str, rhythm: str, current_score_b: float, report_dir: Path
) -> str:
    """Q-1: per-pick 卖时机建议 (综合 R144 节奏 + R9 衰减).

    服务"持续时间"可行动化 — 系统说 BUY 但不说何时 SELL。节奏=早→止盈窗口,
    匀→持有到期, 晚→耐心; 叠加信号衰减→提前关注。无节奏/无前值 → 空串不渲染。
    ``current_score_b`` 必须是真实当日分 (传 0.0 会让 change_pct 全为 -100%)。
    """
    from src.screening.exit_timing import compute_exit_timing, render_exit_timing
    from src.screening.signal_decay_detector import detect_signal_decay

    decay_map = detect_signal_decay(
        current_recommendations=[{"ticker": ticker, "score_b": current_score_b}],
        report_dir=report_dir,
    )
    decay_info = decay_map.get(ticker)
    change_pct = float(decay_info.change_pct) if decay_info and decay_info.change_pct is not None else None
    days_peak = int(decay_info.days_since_peak) if decay_info else 0

    advice = compute_exit_timing(
        rhythm=rhythm, decay_change_pct=change_pct, days_since_peak=days_peak
    )
    return render_exit_timing(advice)


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
        # NS-13 family drain: NaN bonus/score 经 `float(x or 0.0)` 仍 truthy 不兜底,
        # 导致 `max(-1.0, min(1.0, NaN+bonus))` 在 CPython 返回 1.0, corrupt 标的静默
        # 顶到推荐列表顶部 (BH-012 escalate-to-top 同型). 用 safe_float 源头拒绝 NaN.
        bonus = _safe_float_value(recommendation.get("consecutive_bonus", 0.0), 0.0)
        original_score = _safe_float_value(recommendation.get("composite_score", 0.0), 0.0)
        # NS-11 (autodev c232): 存 pre-bonus `composite_score_gated` 让下游
        # build_front_door_verdict 用 pre-bonus score 判 BUY gate (>=0.5), bonus
        # 仅用于排序. 总是存 (即使 bonus=0) 让下游总能读到 pre-bonus score,
        # 行为一致. 缺省时 build_front_door_verdict 回退 composite_score (向后兼容).
        # Re-clamp to the documented [-1.0, 1.0] domain (composite_score.py:16).
        recommendation["composite_score_gated"] = round(max(-1.0, min(1.0, original_score)), 4)
        if not bonus:
            continue
        # Re-clamp to the documented [-1.0, 1.0] domain (composite_score.py:16).
        # compute_composite_scores already clamps, but the bonus is added after,
        # so a high-base pick (0.98) + 6+day bonus (0.08) would otherwise reach 1.06.
        recommendation["composite_score"] = round(max(-1.0, min(1.0, original_score + bonus)), 4)
    # BH-011 family (sibling: composite_score.py:312, investability.py:309): composite_score
    # is rounded to 4 decimals above, so ties are common at the Top-N membership boundary.
    # R143/O-1: restore the risk-aware 6-tuple tie-break from rank_recommendations_by_investability
    # that this bonus re-sort was discarding — a pure 2-tuple (-composite, ticker) left two
    # BUY picks with equal composite sorting alphabetically, hiding the stronger-evidence
    # pick. composite_score (with bonus folded in) stays the primary key so R4
    # consecutive-boost still bubbles picks up; the risk-aware keys only break ties.
    # Absent keys default equally so ticker remains the deterministic final fallback
    # (preserves BH-011 determinism when risk keys are missing).
    # NS-13: sort key 的 composite_score / score_b 也用 safe_float 防止 NaN 进 sort key
    # 导致同 score 的标的间排序不确定 (NaN 比较均 False, 破坏 Timsort 稳定性).
    # C222 (2026-06-28 horizon 一致性): mirror of investability.rank_recommendations_by_investability
    # — tie-breakers 2/3 changed from t30_edge/t30_winrate to
    # ``_max_short_horizon_metric`` (max of t5/t10) to align with BUY gate horizon
    # (T+5 OR T+10 pass, see ``_meets_quality_bar`` C220 commit 4184dd7e). The two
    # sort sites must stay in sync: rank_recommendations_by_investability produces
    # the initial ranking, this function re-sorts after applying consecutive_bonus;
    # diverging tie-breakers would invert the order of bonus-equal picks. T+30
    # retained only as long-term invalidation signal (not a ranking tie-breaker).
    ranked.sort(
        key=lambda recommendation: (
            -_safe_float_value(recommendation.get("composite_score", 0.0), 0.0),
            -_safe_metric(_max_short_horizon_metric(recommendation.get("expected_returns")), float("-inf")),
            -_safe_metric(_max_short_horizon_metric(recommendation.get("win_rates")), float("-inf")),
            -_safe_metric(recommendation.get("bucket_sample_count"), 0.0),
            -_safe_float_value(recommendation.get("score_b", 0.0), 0.0),
            str(recommendation.get("ticker") or ""),
        ),
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
    # R111 / R39-R44-R71-R77 trust-calibration family: 当 composite_score 来自 R39 fallback
    # 路径（missing-composite, 0.9 折扣的 score_b, composite_verified=False）时, 在分数后
    # 追加 (估) 标记, 让用户区分"完整维度调整的 composite"与"保守估计分数", 校准对推荐
    # 的信任度。composite_verified 缺省（旧报告）按 verified 处理, 行为保持。
    composite_verified = item.get("composite_verified")
    estimate_marker = "" if composite_verified else ("估" if composite_verified is False else "")
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
    # C222: BUY gate decision-horizon metrics (max of T+5/T+10). Used for
    # position sizing and the decision-horizon display row. T+30 above is
    # retained only as the long-term invalidation view.
    decision_edge, decision_winrate = _extract_decision_horizon_metrics(item)

    t30_str = f"{t30:+.2f}%" if t30 is not None else "—"
    t30_wr_str = f"{t30_wr:.0%}" if t30_wr is not None else "—"
    # C222: render decision-horizon edge/winrate so the user can see the
    # BUY verdict's actual basis (max of T+5/T+10). When signal_horizon is
    # set (BUY/HOLD-with-short-signal), this row disambiguates "T+30=+0.3%"
    # (weak long-term) from "决策=+1.2% 胜率=62%" (the short-term rebound
    # that actually drove the BUY).
    decision_edge_str = f"{decision_edge:+.2f}%" if decision_edge is not None else "—"
    decision_wr_str = f"{decision_winrate:.0%}" if decision_winrate is not None else "—"
    rhythm = _classify_return_rhythm(item.get("expected_returns"))
    # O-4: per-bucket T+30 typical downside (赔率). Pairs with win rate so the
    # user can size by tail risk: 60% win @ -4% typical loss ≠ 60% @ -30%.
    downside = item.get("bucket_t30_avg_negative_return")
    downside_str = f"{downside:+.1f}%" if isinstance(downside, (int, float)) else "—"
    # A-1: per-pick position suggestion (BUY only, regime-aware, capped). Bridges
    # "买哪只 → 买多少" with a simple transparent risk-budget; covered by the R71
    # disclaimer (not an investment directive). C222: sized by decision-horizon
    # (T+5/T+10) edge/winrate, NOT T+30 — matches BUY verdict horizon.
    pos_str = ""
    if verdict["action"] == "BUY":
        pos_pct = _suggest_position_pct(
            decision_edge=decision_edge,
            decision_winrate=decision_winrate,
            market_regime=context.market_regime,
        )
        if pos_pct > 0:
            pos_str = f"  建议仓位(参考)={pos_pct:.1f}%"
    base_score = float(item.get("base_score", item.get("score_b", 0.0)) or 0.0)
    score_color = _score_color(composite_score)

    print(
        f"  {Fore.WHITE}{idx}.{Style.RESET_ALL} "
        f"{Fore.CYAN}{str(item.get('ticker', '')):<8}{Style.RESET_ALL} "
        f"{name:<14}{new_badge} "
        f"{score_color}{composite_score:>+.3f}{Style.RESET_ALL}{estimate_marker} "
        f"{grade}{consec_str} {confluence_str}  "
        f"(base={base_score:.3f} {signal_str}{factor_attr})"
    )
    # C221: 展示短期反弹信号来源 horizon (T+5 / T+10 / T+5+T+10),
    # 让用户区分 BUY 信号是 T+5 反弹还是 T+10 反弹, 避免把 T+5 票当 T+10 持有.
    # signal_horizon 为空 (HOLD/AVOID 无短期信号) 时不展示, 保持输出简洁.
    signal_horizon_str = ""
    if verdict.get("signal_horizon"):
        signal_horizon_str = f"  信号={verdict['signal_horizon']}"
    # C222: per-pick 行展示分两层 — 决策 horizon (max T+5/T+10, BUY verdict 依据)
    # + 长期 horizon (T+30, invalidation 维度). 让用户看到 BUY 票的短期反弹强度
    # (决策=+1.2% 胜率=62%) 与长期走势 (T+30=+0.3% 胜率=48%) 的差异, 避免把
    # T+5/T+10 反弹票当 30 天持有 (C219 n=7201 证明 low bucket T+30 winrate=45%).
    print(
        f"     操作={verdict['action']}{signal_horizon_str}  "
        f"决策={decision_edge_str} 胜率={decision_wr_str}  "
        f"T+30={t30_str} T+30胜率={t30_wr_str}  "
        f"样本={_format_sample_count(item)}  节奏={rhythm}  "
        f"赔率(下行)={downside_str}{pos_str}  "
        f"市场门控={verdict['market_regime']}"
    )
    print(f"     失效条件: {verdict['invalidation_reason']}")

    # Q-1: per-pick 卖时机建议 (BUY 才显示 — HOLD/AVOID 无卖出问题)
    if verdict["action"] == "BUY":
        exit_line = _render_exit_timing_line(
            ticker=str(item.get("ticker", "")),
            rhythm=rhythm,
            current_score_b=base_score,
            report_dir=context.report_dir,
        )
        if exit_line:
            print(f"     {exit_line}")

    # R-1: 多周期冲突 (short vs long horizon sign disagreement) — any pick
    from src.screening.horizon_conflict import detect_horizon_conflict, render_horizon_conflict as _render_hc

    hc = detect_horizon_conflict(item.get("expected_returns"))
    hc_line = _render_hc(hc)
    if hc_line:
        print(f"     {hc_line}")

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
    print(f"  Date: {trade_date}  |  默认前门: composite confidence + T+5/T+10 决策 horizon posterior edge + 代表票去重 + 连续推荐加权")
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
    _print_stability_block(report_dir)
    _print_data_quality_block(report_dir)
    _print_concentration_block(representative_picks)
    _print_correlation_block(representative_picks)
    _print_portfolio_risk_block(representative_picks)
    _print_regime_winrate_block(market_regime)
    _print_monotonicity_block(report_dir)
    _print_north_star_block(report_dir)
    _print_factor_attribution_block(report_dir)
    _print_factor_attribution_by_state_block(report_dir)  # NS-6: 因子 × state_type 倒挂
    _print_model_version_comparison_block(report_dir)  # NS-7: 新旧 model_version 效果对比
    _print_decision_flow_hint()
    _print_disclaimer()


def _print_correlation_block(picks: list[dict]) -> None:
    """Q-4: 相关性仓位折减 — when BUY picks overlap (same industry + close score),
    their combined position over-concentrates risk. Surface ⚠ + per-pick discount
    factor so R145 position suggestions can be scaled. Independent picks → silent.
    """
    try:
        from src.screening.correlation_discount import (
            compute_correlation_discount,
            render_correlation_note,
        )

        report = compute_correlation_discount(picks)
    except Exception:  # noqa: BLE001 — best-effort display; never break the front door
        return
    line = render_correlation_note(report)
    if line:
        print(line)


def _print_portfolio_risk_block(picks: list[dict]) -> None:
    """R-3: 组合风险预算总览 — synthesize P-4 concentration + Q-4 correlation into a
    single read-only ``🎯 组合风险: X%/100% 预算`` line.

    P-4 (集中度) / Q-4 (相关性) / R145 (仓位) 各自独立, 此前无组合层"总风险 vs
    预算"数。R-3 复用既有 compute_industry_concentration + compute_correlation_discount
    合成 0-100% 预算占用。纯展示不进排序, 数据不足/<2 picks 静默 (同 R-1/R-2/R-5).
    """
    try:
        from src.screening.portfolio_risk_budget import (
            render_portfolio_risk_line,
            summarize_portfolio_risk,
        )

        summary = summarize_portfolio_risk(picks)
    except Exception:  # noqa: BLE001 — best-effort display; never break the front door
        return
    line = render_portfolio_risk_line(summary)
    if line:
        print(line)


def _print_regime_winrate_block(market_regime: str) -> None:
    """R-5.A: 按 current regime 展示真实历史 T+30 胜率 + 多周期 median 速览。

    真实回测 (2026-06-24, 91 只) 揭示: crisis regime (结构性行情) 真实胜率 73%
    +8%, normal regime (震荡市) 24% -9%。这让用户看到当前 regime 的真实期望,
    自己决定是否信任推荐。是赚钱工具的诚实基础 (不碰 gate/仓位)。

    2026-06-25 多周期扩展: 加一行各 horizon (T+15/T+20/T+25/T+30) median,
    让用户看到中长周期是否比 T+30 更优 (如 crisis T+20/T+25 正 median).
    """
    try:
        from src.screening.regime_winrate import render_regime_winrate_line, render_regime_multihorizon_line

        line = render_regime_winrate_line(market_regime)
        if line:
            print(line)
        mh_line = render_regime_multihorizon_line(market_regime)
        if mh_line:
            print(mh_line)
    except Exception:  # noqa: BLE001 — best-effort display; never break the front door
        return


def _print_monotonicity_block(report_dir: Path) -> None:
    """NS-4: 排序单调性健康度 — score rank → T+30 胜率是否单调.

    真实数据 (493 条 tracking_history) 揭示模型整体排序倒挂: low-score 胜率
    50.5% → high-score 39.5% (高分票胜率反而最低). 本块在 ``--top-picks`` footer
    把"高分是否 → 高胜率"量化展示: 倒挂时 ⚠ 红字提示 (模型把输家排前面),
    单调时 ✓ 绿字, 非单调时 ⚠ 黄字, 样本不足静默.

    纯诊断不改 gate/factor/仓位 (越界 = 过拟合, Phase 0 STOP 裁决). 镜像
    regime_winrate / portfolio_concentration 的 best-effort footer-block 模式.
    """
    try:
        from src.screening.rank_monotonicity import (
            compute_high_vs_low_significance_from_loaded,
            compute_horizon_monotonicity_from_loaded,
            compute_period_breakdown_from_loaded,
            compute_rank_monotonicity,
            render_horizon_breakdown_line,
            render_monotonicity_line,
            render_period_breakdown_line,
            render_significance_line,
        )
        from src.screening.consecutive_recommendation import (
            load_tracking_history,
        )

        report = compute_rank_monotonicity(reports_dir=report_dir)
    except Exception:  # noqa: BLE001 — best-effort display; never break the front door
        return
    line = render_monotonicity_line(report)
    if line:
        print(line)
    records = None
    # M7: 显著性 — 倒挂是真的还是小样本噪声? (防 owner over-react; 紧接 overall 解释)
    try:
        records = load_tracking_history(report_dir)
        sig = compute_high_vs_low_significance_from_loaded(records, min_n=20)
        sig_line = render_significance_line(sig)
        if sig_line:
            print(sig_line)
    except Exception as exc:  # noqa: BLE001 — best-effort; significance 永不破坏前门  (c267: was silent pass → observable)
        logger.warning("[top_picks] significance footer block failed (best-effort, skipped): %s", exc)
    # M8: 样本充足性 — 不显著是因为样本太小吗? (需累积多少才能下结论)
    if records:
        try:
            from src.screening.rank_monotonicity import (
                compute_power_analysis_from_loaded as _compute_power,
                render_power_line as _render_power,
            )
            power = _compute_power(records, min_n=20)
            power_line = _render_power(power)
            if power_line:
                print(power_line)
        except Exception as exc:  # noqa: BLE001 — best-effort; power 永不破坏前门  (c267: was silent pass → observable)
            logger.warning("[top_picks] power footer block failed (best-effort, skipped): %s", exc)
    # M5: 时段分段单调性 (design packet 推荐区分 H1 因子 bug vs H2 regime)
    try:
        records = load_tracking_history(report_dir)
        periods = compute_period_breakdown_from_loaded(records, n_periods=2, min_n=15)
        period_line = render_period_breakdown_line(periods)
        if period_line:
            print(period_line)
    except Exception as exc:  # noqa: BLE001 — best-effort; period breakdown 永不破坏前门  (c267: was silent pass → observable)
        logger.warning("[top_picks] period_breakdown footer block failed (best-effort, skipped): %s", exc)
    # M6: 多 horizon 单调性 (回答 design packet H5: 倒挂是 T+30 特定还是全 horizon? 排除 MR 短期反转)
    if records:
        try:
            horizons = compute_horizon_monotonicity_from_loaded(
                records,
                ["next_5day_return", "next_10day_return", "next_20day_return", "next_30day_return"],
                min_n=15,
            )
            horizon_line = render_horizon_breakdown_line(horizons)
            if horizon_line:
                print(horizon_line)
        except Exception as exc:  # noqa: BLE001 — best-effort; horizon breakdown 永不破坏前门  (c267: was silent pass → observable)
            logger.warning("[top_picks] horizon_breakdown footer block failed (best-effort, skipped): %s", exc)


def _print_factor_attribution_block(report_dir: Path) -> None:
    """M1: 因子层归因 — per-strategy T/MR/F/E 贡献 × T+5 胜率 (BUY gate 决策 horizon).

    owner 授权 C (decomposition). 定位**哪个因子**让高分票输 (倒挂根因).
    horizon 对齐 C229/C230 (2026-06-28): 默认 ``next_5day_return``;
    T+30 保留为长期 invalidation 诊断 (可显式传 ``horizon_field``).
    当前旧 records 无 score_decomposition → insufficient 静默.
    owner 跑 --auto (新代码注入 decomposition) 累积新 records 后激活.
    """
    try:
        from src.screening.factor_attribution import (
            compute_factor_attribution_from_loaded,
            render_factor_attribution_line,
        )
        from src.screening.consecutive_recommendation import load_tracking_history

        records = load_tracking_history(report_dir)
        report = compute_factor_attribution_from_loaded(records, min_n=15)
    except Exception:  # noqa: BLE001 — best-effort; never break the front door
        return
    line = render_factor_attribution_line(report)
    if line:
        print(line)


def _print_factor_attribution_by_state_block(report_dir: Path) -> None:
    """NS-6: 因子归因 × state_type — 哪个因子在哪个市场帮倒忙 (历史回测).

    用户方法论 (2026-06-29): 历史回测先行 — 不等 score_decomposition 持久化成熟.
    JOIN tracking_history (realized T+5/T+10 return) + 历史报告 recommendations
    (score_decomposition + market_state.state_type) on (ticker, date) → ~7500 条.
    对每 state_type × 每 factor 算贡献高/低组胜率倒挂.

    历史 n=7500 诊断 (2024-03~2026-05): event_sentiment 系统性倒挂 (trend T+5
    高贡献胜率 27% vs 低 69%, +42% inversion), fundamental/mean_reversion 在
    trend 倒挂. 供 owner 因子调优 (最大 P&L 杠杆). 纯诊断不改因子/gate/仓位.
    """
    try:
        from src.screening.factor_attribution_by_state import (
            compute_factor_attribution_by_state,
            compute_factor_attribution_score_controlled,
            render_factor_attribution_by_state_line,
            render_score_controlled_factor_line,
        )
        report = compute_factor_attribution_by_state(reports_dir=report_dir, min_n=15)
        sc_report = compute_factor_attribution_score_controlled(reports_dir=report_dir, min_n=15)
    except Exception:  # noqa: BLE001 — best-effort; never break the front door
        return
    line = render_factor_attribution_by_state_line(report)
    if line:
        print(line)
    sc_line = render_score_controlled_factor_line(sc_report)
    if sc_line:
        print(sc_line)


def _print_model_version_comparison_block(report_dir: Path) -> None:
    """NS-7: 新旧 model_version 效果对比 — owner 每次调参是否改善实现胜率/收益.

    按 NS-2 ``model_version`` (git short sha) 分组 tracking_history, 取两个最近活跃
    版本做 candidate-vs-baseline 对比 (winrate + median return delta). 服务 owner
    因子调优反馈闭环 (P&L 最大杠杆): 让 owner 看到 commits ab96aae0..e5406887 每次
    调参后实现 winrate 是升是降, 而非只在全量聚合上盲调.

    纯诊断, 不改 gate/factor/仓位/score (越界=过拟合). best-effort: 数据不足
    (新版本 < min_samples mature 记录) 诚实标 insufficient, 不强行下结论; 任何
    异常静默 return, 永不破坏前门.
    """
    try:
        from src.screening.consecutive_recommendation import load_tracking_history
        from src.screening.model_version_comparison import (
            compare_model_versions,
            render_model_version_comparison_line,
        )

        records = load_tracking_history(report_dir)
        comparison = compare_model_versions(records)
    except Exception:  # noqa: BLE001 — best-effort; never break the front door
        return
    line = render_model_version_comparison_line(comparison)
    if line:
        print(line)


def _print_north_star_block(report_dir: Path) -> None:
    """NS-3: 北极星 P&L 趋势仪表 — 按推荐日等权累积真实 T+30 P&L.

    北极星目标: 用户按推荐操作 30 天真实 P&L>0. 本块在 ``--top-picks`` footer
    量化该目标当前状态 (累积等权 mean + 整体 winrate + median 三维度). 真实数据
    (493 条) 显示 divergent: 累积 mean +190% 但 winrate 46% + median -2%
    (少数大赢家拉高 mean, 典型票微亏). 三维度避免 R-6/R-7 mean 异常值污染误导.

    verdict: divergent⚠ (mean 正但典型票不赚) / positive✓ (全正趋近 >0) /
    negative⚠ (亏) / insufficient 静默. 纯诊断不改 gate/factor/仓位.
    """
    try:
        from src.screening.north_star_pnl import (
            compute_holding_period_curve_from_loaded,
            compute_north_star_pnl,
            compute_payoff_analysis_from_loaded,
            render_holding_period_line,
            render_north_star_line,
            render_payoff_line,
        )
        from src.screening.consecutive_recommendation import load_tracking_history

        report = compute_north_star_pnl(reports_dir=report_dir)
    except Exception:  # noqa: BLE001 — best-effort display; never break the front door
        return
    line = render_north_star_line(report)
    if line:
        print(line)
    # M9: 持有期收益曲线 (全样本, 不受 high bucket n=38 限制; 最优卖出点 + 稳健画像)
    try:
        records = load_tracking_history(report_dir)
        curve = compute_holding_period_curve_from_loaded(
            records,
            ["next_5day_return", "next_10day_return", "next_20day_return", "next_30day_return"],
            min_n=20,
        )
        hp_line = render_holding_period_line(curve)
        if hp_line:
            print(hp_line)
    except Exception as exc:  # noqa: BLE001 — best-effort; holding period 永不破坏前门  (c267: was silent pass → observable)
        logger.warning("[top_picks] holding_period footer block failed (best-effort, skipped): %s", exc)
    # M10: 盈亏比 + 输家画像 (全样本, 服务 winrate>50%+高盈亏比; 哪 bucket 拖累 winrate?)
    if records:
        try:
            payoff = compute_payoff_analysis_from_loaded(records, min_n=20)
            payoff_line = render_payoff_line(payoff)
            if payoff_line:
                print(payoff_line)
        except Exception as exc:  # noqa: BLE001 — best-effort; payoff 永不破坏前门  (c267: was silent pass → observable)
            logger.warning("[top_picks] payoff footer block failed (best-effort, skipped): %s", exc)
        # M11: 砍输家池策略模拟 (量化"砍哪个 bucket"提 winrate 的效果; owner 门控决策依据)
        try:
            from src.screening.north_star_pnl import (
                compute_pruning_strategy_from_loaded as _compute_pruning,
                render_pruning_line as _render_pruning,
            )
            pruning = _compute_pruning(records, min_n=20)
            pruning_line = _render_pruning(pruning)
            if pruning_line:
                print(pruning_line)
        except Exception as exc:  # noqa: BLE001 — best-effort  (c267: was silent pass → observable)
            logger.warning("[top_picks] pruning footer block failed (best-effort, skipped): %s", exc)
        # M12: winrate bootstrap CI (给 owner 门控决策提供稳健不确定性估计;
        # low bucket 50% (n=105) 的 bootstrap 95% CI 是 [42%, 58%] — 比
        # 正态近似更稳健, 服务 winrate>50% 门控翻转决策)
        try:
            from src.screening.north_star_pnl import (
                compute_bootstrap_ci_from_loaded as _compute_bootstrap,
                render_bootstrap_ci_line as _render_bootstrap,
            )
            ci_results = _compute_bootstrap(records, min_n=20, n_bootstrap=10000, seed=42)
            ci_line = _render_bootstrap(ci_results)
            if ci_line:
                print(ci_line)
        except Exception as exc:  # noqa: BLE001 — best-effort  (c267: was silent pass → observable)
            logger.warning("[top_picks] bootstrap_ci footer block failed (best-effort, skipped): %s", exc)


def _print_concentration_block(picks: list[dict]) -> None:
    """P-4: 组合级行业集中度 — Top 行业占比 + 超阈值 ⚠ 风险提示。

    R145 给 per-pick 仓位, 但组合层级"你 40% 在科技"集中度视角此前缺失。
    count-based (每只推荐 = 1 单位), 过滤未知行业, 纯展示不改门控。数据不足
    (无合法 industry_sw) 时静默不渲染。
    """
    try:
        from src.screening.portfolio_concentration import (
            compute_industry_concentration,
            render_concentration_line,
        )

        report = compute_industry_concentration(picks, threshold=0.3)
    except Exception:  # noqa: BLE001 — best-effort display; never break the front door
        return
    line = render_concentration_line(report)
    if line:
        print(line)


def _print_stability_block(report_dir: Path) -> None:
    """P-1: 推荐稳定性度量 — 近 N 日 Top-3 相邻日 Jaccard 重叠率。

    产品目标核心形容词"稳定"此前无任何度量。一只昨 BUY 今 AVOID 明又 BUY 的票
    完全合法却违背"稳定"。复用 auto_screening 历史，零新数据源，纯展示不进排序。
    数据不足（<2 份报告）时静默不渲染（不污染首次运行的前门）。
    """
    try:
        from src.screening.recommendation_stability import (
            compute_recommendation_stability,
            render_stability_line,
        )

        report = compute_recommendation_stability(
            reports_dir=report_dir, lookback_days=5, top_n=3
        )
    except Exception:  # noqa: BLE001 — best-effort display; never break the front door
        return
    line = render_stability_line(report)
    if line:
        print(line)


def _print_data_quality_block(report_dir: Path) -> None:
    """R-2: 数据完整度门控 — run-level 数据完整度单行摘要。

    用户无法一眼判断今日推荐基于完整还是部分数据 (某策略源缺失会让对应 signal
    静默为中性, composite 仍照常排序)。复用 ``data_quality_audit`` 既有审计:
    读最新 auto_screening 报告 → 审计 Top N → 聚合为单行「📊 数据完整度: N%
    (M/4 策略就绪) ⚠ K 只基于部分数据」。纯展示不进排序, 数据不足/缺报告时静默
    不渲染 (与 P-1/P-4/Q-4 同 best-effort 模式, 永不中断前门)。
    """
    try:
        from src.screening.data_quality_audit import (
            audit_recommendations,
            load_latest_recommendations,
            render_data_quality_summary,
            summarize_data_quality,
        )

        _date_str, recs = load_latest_recommendations(report_dir=report_dir)
        audits = audit_recommendations(recs)
        summary = summarize_data_quality(audits)
    except Exception:  # noqa: BLE001 — best-effort display; never break the front door
        return
    line = render_data_quality_summary(summary)
    if line:
        print(line)


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
