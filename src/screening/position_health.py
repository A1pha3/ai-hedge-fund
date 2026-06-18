"""Position Health Check — P15-1.

Monitors stocks the user already holds and outputs a health assessment:
- Current composite score (has it deteriorated since recommendation?)
- Signal momentum (improving or declining?)
- Trend resonance (still aligned or breaking?)
- Volume confirmation (still supported?)
- Actionable recommendation: HOLD / WATCH / SELL

This fills the gap between "buy recommendation" and "sell signal."
All signal infrastructure is reused from existing modules.

CLI::

    python src/main.py --position-check 000001,300750,600519
    python src/main.py --position-check 000001 --sell-threshold=0.2
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.screening.composite_score import compute_composite_scores_for_recommendations
from src.screening.consecutive_recommendation import (
    load_auto_screening_history,
    resolve_report_dir,
)
from src.screening.signal_momentum import compute_signal_momentum
from src.screening.trend_resonance import compute_trend_resonance
from src.screening.volume_confirmation import compute_volume_confirmation
from src.utils.display import Fore, Style

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Composite score below this → SELL recommendation
_DEFAULT_SELL_THRESHOLD: float = 0.15

#: Composite score in "watch zone" → WATCH recommendation
_DEFAULT_WATCH_THRESHOLD: float = 0.30


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class PositionHealth:
    """Health assessment for a single held position."""

    ticker: str
    name: str = ""
    composite_score: float = 0.0
    score_b: float = 0.0
    momentum_bonus: float = 0.0
    sector_bonus: float = 0.0
    consistency_adj: float = 0.0
    volume_factor: float = 0.0
    trend_resonance_factor: float = 0.0
    momentum_label: str = "neutral"
    trend_label: str = "neutral"
    volume_label: str = "neutral"
    action: str = "HOLD"  # HOLD / WATCH / SELL
    reason: str = ""


@dataclass
class PositionHealthReport:
    """Position health report for all held tickers."""

    trade_date: str = ""
    items: list[PositionHealth] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "trade_date": self.trade_date,
            "items": [
                {
                    "ticker": item.ticker,
                    "name": item.name,
                    "composite_score": round(item.composite_score, 4),
                    "action": item.action,
                    "reason": item.reason,
                }
                for item in self.items
            ],
        }


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------


def _find_ticker_in_history(
    ticker: str,
    history: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Find the most recent recommendation for a ticker."""
    for report in history:
        recs = (report.get("payload", {}).get("recommendations")) or []
        for rec in recs:
            if str(rec.get("ticker", "")) == ticker:
                return rec
    return None


def _determine_action(
    composite: float,
    momentum: float,
    trend: float,
    sell_threshold: float,
    watch_threshold: float,
) -> tuple[str, str]:
    """Determine HOLD/WATCH/SELL action with reason."""
    if composite < sell_threshold:
        return "SELL", f"composite={composite:.3f} < sell_threshold={sell_threshold:.2f}"
    if composite < watch_threshold:
        return "WATCH", f"composite={composite:.3f} in watch zone [{sell_threshold:.2f}, {watch_threshold:.2f})"
    # Check for deteriorating signals
    if momentum < -0.05 and trend < -0.02:
        return "WATCH", "信号衰减+趋势共振冲突, 虽然综合分尚可但需警惕"
    return "HOLD", "综合信号健康"


def compute_position_health(
    *,
    tickers: list[str],
    sell_threshold: float = _DEFAULT_SELL_THRESHOLD,
    watch_threshold: float = _DEFAULT_WATCH_THRESHOLD,
    reports_dir: Path | None = None,
) -> PositionHealthReport:
    """Compute health assessment for held positions.

    Args:
        tickers: List of ticker codes the user holds
        sell_threshold: Composite score below this → SELL
        watch_threshold: Composite score below this → WATCH
        reports_dir: Reports directory

    Returns:
        :class:`PositionHealthReport`
    """
    search_dir = reports_dir or resolve_report_dir()
    history = load_auto_screening_history(
        lookback_days=30,
        report_dir=search_dir,
    )

    if not history:
        return PositionHealthReport()

    latest = history[0]
    trade_date = latest.get("date", "")

    # Filter recommendations for the held tickers
    held_recs: list[dict[str, Any]] = []
    for ticker in tickers:
        rec = _find_ticker_in_history(ticker, history)
        if rec is not None:
            held_recs.append(rec)
        else:
            # Ticker not in recent recommendations — create a minimal rec
            held_recs.append({"ticker": ticker, "name": ticker, "score_b": 0.0})

    if not held_recs:
        return PositionHealthReport(trade_date=trade_date)

    # Compute composite scores (reuses all 6 signal factors)
    try:
        composite_report = compute_composite_scores_for_recommendations(
            recommendations=held_recs,
            trade_date=trade_date,
            lookback_days=30,
            reports_dir=search_dir,
        )
        composite_map = {item.ticker: item for item in composite_report.items}
    except Exception:
        composite_map = {}

    # Compute momentum
    try:
        momentum_report = compute_signal_momentum(
            top_n=len(held_recs),
            lookback_days=10,
            reports_dir=search_dir,
        )
        momentum_map = {item.ticker: item for item in momentum_report.items}
    except Exception:
        momentum_map = {}

    # Compute trend resonance
    try:
        trend_report = compute_trend_resonance(
            top_n=len(held_recs),
            reports_dir=search_dir,
        )
        trend_map = {item.ticker: item for item in trend_report.items}
    except Exception:
        trend_map = {}

    # Compute volume confirmation
    try:
        volume_report = compute_volume_confirmation(
            top_n=len(held_recs),
            lookback_days=5,
            reports_dir=search_dir,
        )
        volume_map = {item.ticker: item for item in volume_report.items}
    except Exception:
        volume_map = {}

    # Build health entries
    items: list[PositionHealth] = []
    for rec in held_recs:
        ticker = str(rec.get("ticker", ""))
        name = str(rec.get("name", "") or ticker)

        comp = composite_map.get(ticker)
        mom = momentum_map.get(ticker)
        trend = trend_map.get(ticker)
        vol = volume_map.get(ticker)

        composite_score = comp.composite_score if comp else 0.0
        score_b = comp.base_score if comp else float(rec.get("score_b", 0.0) or 0.0)
        mom_bonus = comp.momentum_bonus if comp else 0.0
        sec_bonus = comp.sector_bonus if comp else 0.0
        con_adj = comp.consistency_adj if comp else 0.0
        vol_factor = comp.volume_factor if comp else 0.0
        trf = comp.trend_resonance_factor if comp else 0.0

        mom_label = mom.momentum_label if mom else "unknown"
        trend_label = trend.resonance_label if trend else "unknown"
        vol_label = vol.confirmation if vol else "unknown"

        action, reason = _determine_action(
            composite_score, mom_bonus, trf,
            sell_threshold, watch_threshold,
        )

        items.append(
            PositionHealth(
                ticker=ticker,
                name=name,
                composite_score=composite_score,
                score_b=score_b,
                momentum_bonus=mom_bonus,
                sector_bonus=sec_bonus,
                consistency_adj=con_adj,
                volume_factor=vol_factor,
                trend_resonance_factor=trf,
                momentum_label=mom_label,
                trend_label=trend_label,
                volume_label=vol_label,
                action=action,
                reason=reason,
            )
        )

    # Sort: SELL first, then WATCH, then HOLD; within each by composite ascending
    action_order = {"SELL": 0, "WATCH": 1, "HOLD": 2}
    items.sort(key=lambda x: (action_order.get(x.action, 3), x.composite_score))

    return PositionHealthReport(trade_date=trade_date, items=items)


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _action_colored(action: str) -> str:
    if action == "SELL":
        return f"{Fore.RED}{Style.BRIGHT}✗ SELL{Style.RESET_ALL}"
    if action == "WATCH":
        return f"{Fore.YELLOW}⚠ WATCH{Style.RESET_ALL}"
    return f"{Fore.GREEN}✓ HOLD{Style.RESET_ALL}"


def render_position_health(report: PositionHealthReport) -> str:
    """Render position health as a readable table."""
    if not report.items:
        return f"\n{Fore.CYAN}📋 Position Health Check (持仓健康检查){Style.RESET_ALL}\n  无持仓数据\n"

    lines = [
        f"\n{Fore.CYAN}📋 Position Health Check (持仓健康检查){Style.RESET_ALL}",
        f"  Date: {report.trade_date}",
        "",
        f"  {'标的':<8} {'名称':<10} {'综合':>7} {'动量':>6} {'趋势':>6} {'量价':>6}  {'操作':>16}",
        f"  {'─' * 8} {'─' * 10} {'─' * 7} {'─' * 6} {'─' * 6} {'─' * 6}  {'─' * 16}",
    ]

    sell_count = 0
    watch_count = 0
    hold_count = 0

    for item in report.items:
        action_str = _action_colored(item.action)

        def _fmt(val: float) -> str:
            if val > 0:
                return f"{Fore.GREEN}+{val:.2f}{Style.RESET_ALL}"
            if val < 0:
                return f"{Fore.RED}{val:.2f}{Style.RESET_ALL}"
            return "  0.00"

        lines.append(
            f"  {item.ticker:<8} {item.name[:10]:<10} "
            f"{item.composite_score:>+7.3f} "
            f"{_fmt(item.momentum_bonus):>14} "
            f"{_fmt(item.trend_resonance_factor):>14} "
            f"{_fmt(item.volume_factor):>14}  "
            f"{action_str:>28}"
        )
        if item.reason:
            lines.append(f"    {'':>28} {Fore.WHITE}{item.reason}{Style.RESET_ALL}")

        if item.action == "SELL":
            sell_count += 1
        elif item.action == "WATCH":
            watch_count += 1
        else:
            hold_count += 1

    lines.append("")
    lines.append(
        f"  {Fore.GREEN}✓ HOLD: {hold_count}{Style.RESET_ALL}  "
        f"{Fore.YELLOW}⚠ WATCH: {watch_count}{Style.RESET_ALL}  "
        f"{Fore.RED}✗ SELL: {sell_count}{Style.RESET_ALL}  "
        f"总计: {len(report.items)}"
    )

    if sell_count > 0:
        sell_tickers = [i.ticker for i in report.items if i.action == "SELL"]
        lines.append(
            f"  {Fore.RED}⚠ 建议立即关注: {', '.join(sell_tickers)}{Style.RESET_ALL}"
        )

    # Trust-calibration disclaimer: this surface emits explicit SELL/WATCH/HOLD
    # actions. Carry the same non-advice boundary as --top-picks / --daily-brief
    # / PDF / backtest so users do not read model output as a deterministic
    # instruction (serves product goal "更高确信" = confidence includes honest
    # boundary disclosure).
    lines.append("")
    lines.append(
        f"  {Fore.WHITE}⚠ 以上持仓健康检查由 AI 模型自动生成, 仅供研究 / 学习用途, 不构成任何投资建议。"
        f"实际投资需结合个人风险承受能力与最新市场情况。{Style.RESET_ALL}"
    )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI entry
# ---------------------------------------------------------------------------


def run_position_check(argv: list[str] | None = None) -> int:
    """CLI entry point for --position-check."""
    tickers: list[str] = []
    sell_threshold = _DEFAULT_SELL_THRESHOLD
    watch_threshold = _DEFAULT_WATCH_THRESHOLD

    if argv:
        for arg in argv:
            if arg.startswith("--tickers="):
                tickers = [t.strip() for t in arg.split("=")[1].split(",") if t.strip()]
            elif arg.startswith("--sell-threshold="):
                try:
                    sell_threshold = float(arg.split("=")[1])
                except ValueError:
                    pass
            elif arg.startswith("--watch-threshold="):
                try:
                    watch_threshold = float(arg.split("=")[1])
                except ValueError:
                    pass

    if not tickers:
        print(f"{Fore.RED}Usage: --position-check --tickers=000001,300750{Style.RESET_ALL}")
        return 1

    reports_dir = resolve_report_dir()
    report = compute_position_health(
        tickers=tickers,
        sell_threshold=sell_threshold,
        watch_threshold=watch_threshold,
        reports_dir=reports_dir,
    )
    print(render_position_health(report))
    return 0
