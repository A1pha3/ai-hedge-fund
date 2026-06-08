"""P2-8 组合绩效周报/月报 — 自动生成定期绩效汇总。

从逐日持仓快照、交易记录、推荐记录和 P1-3 追踪数据中聚合指定
周期 (周/月) 的绩效指标, 输出 ``PerformanceReport`` dataclass
以及人类可读的 ASCII 报告。

设计原则:
  - **纯函数**: 不读写文件, 不依赖外部状态, 便于单测
  - **数值安全**: NaN / Inf 输入一律兜底为 0, 杜绝告警污染
  - **优雅降级**: 空输入 → 零值报告 (不抛异常)
  - **行宽 420 字符**

主入口:
  - :func:`generate_performance_report` — 聚合生成 PerformanceReport
  - :func:`render_performance_report` — 渲染 ASCII 周报/月报

数据源约定:
  - ``positions_history``: 逐日持仓快照, 每条 = {date, portfolio_value, positions: [{ticker, strategy, daily_pnl, return_pct, ...}]}
  - ``trades``: 交易记录, 每条 = {date, ticker, action, pnl, return_pct, strategy, ...}
  - ``recommendations``: 推荐记录 (P1-3 格式), 每条 = {ticker, recommended_date, next_day_return, ...}
  - ``tracking_history``: P1-3 tracking_history records (可选, 用于推荐命中率)
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import Any, Mapping, Sequence


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: 年化交易日 (中国大陆 A 股)
ANNUAL_TRADING_DAYS: int = 244

#: 无风险利率 (年化, 用于 Sharpe / Sortino)
DEFAULT_RISK_FREE_RATE: float = 0.015

#: 已知策略名 -> 中文显示名
STRATEGY_DISPLAY_NAMES: dict[str, str] = {
    "trend": "趋势",
    "mean_reversion": "均值回归",
    "fundamental": "基本面",
    "event_sentiment": "事件情绪",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _safe_float(value: Any, default: float = 0.0) -> float:
    """非数值 / NaN / Inf -> ``default``。"""
    if value is None:
        return default
    try:
        fv = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(fv):
        return default
    return fv


def _safe_int(value: Any, default: int = 0) -> int:
    """非整数 -> ``default``。"""
    if value is None:
        return default
    try:
        fv = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(fv):
        return default
    return int(fv)


def _parse_date(date_str: str) -> datetime | None:
    """YYYYMMDD / YYYY-MM-DD -> ``datetime``。"""
    if not date_str:
        return None
    cleaned = str(date_str).replace("-", "").strip()
    if len(cleaned) != 8 or not cleaned.isdigit():
        return None
    try:
        return datetime.strptime(cleaned, "%Y%m%d")
    except ValueError:
        return None


def _format_date_display(date_str: str) -> str:
    """YYYYMMDD -> ``YYYY-MM-DD`` (显示用)。"""
    cleaned = str(date_str).replace("-", "").strip()
    if len(cleaned) == 8:
        return f"{cleaned[:4]}-{cleaned[4:6]}-{cleaned[6:]}"
    return date_str


# ---------------------------------------------------------------------------
# Core calculation helpers
# ---------------------------------------------------------------------------


def _compute_total_return(positions_history: Sequence[Mapping[str, Any]], start_date: str, end_date: str) -> float:
    """计算区间总收益率 (小数, 如 0.032 = 3.2%)。"""
    if not positions_history:
        return 0.0
    first_value = _find_portfolio_value(positions_history, start_date, prefer_end=False)
    last_value = _find_portfolio_value(positions_history, end_date, prefer_end=True)
    if first_value <= 0:
        return 0.0
    return (last_value - first_value) / first_value


def _find_portfolio_value(history: Sequence[Mapping[str, Any]], target_date: str, prefer_end: bool = True) -> float:
    """从历史快照中查找最接近 target_date 的组合市值。"""
    target_dt = _parse_date(target_date)
    if target_dt is None or not history:
        return 0.0
    best_value = 0.0
    best_diff = timedelta(days=9999)
    for snap in history:
        snap_date = str(snap.get("date", ""))
        snap_dt = _parse_date(snap_date)
        if snap_dt is None:
            continue
        diff = abs(snap_dt - target_dt)
        if prefer_end:
            if snap_dt <= target_dt and diff < best_diff:
                best_diff = diff
                best_value = _safe_float(snap.get("portfolio_value", 0))
        else:
            if snap_dt >= target_dt and diff < best_diff:
                best_diff = diff
                best_value = _safe_float(snap.get("portfolio_value", 0))
    return best_value


def _compute_max_drawdown(positions_history: Sequence[Mapping[str, Any]]) -> float:
    """计算区间最大回撤 (正数小数, 如 0.045 = 4.5%)。"""
    if not positions_history:
        return 0.0
    equity: list[float] = []
    for snap in sorted(positions_history, key=lambda s: str(s.get("date", ""))):
        pv = _safe_float(snap.get("portfolio_value", 0))
        if pv > 0:
            equity.append(pv)
    if len(equity) < 2:
        return 0.0
    peak = equity[0]
    max_dd = 0.0
    for v in equity:
        if v > peak:
            peak = v
        if peak > 0:
            dd = (peak - v) / peak
            if dd > max_dd:
                max_dd = dd
    return max_dd


def _compute_daily_returns(positions_history: Sequence[Mapping[str, Any]]) -> list[float]:
    """从 positions_history 中提取逐日收益率序列。"""
    if not positions_history:
        return []
    sorted_history = sorted(positions_history, key=lambda s: str(s.get("date", "")))
    values: list[float] = [_safe_float(s.get("portfolio_value", 0)) for s in sorted_history]
    values = [v for v in values if v > 0]
    if len(values) < 2:
        return []
    returns: list[float] = []
    for i in range(1, len(values)):
        if values[i - 1] > 0:
            returns.append((values[i] - values[i - 1]) / values[i - 1])
    return returns


def _compute_sharpe(daily_returns: Sequence[float], risk_free_rate: float = DEFAULT_RISK_FREE_RATE) -> float:
    """计算年化 Sharpe Ratio。"""
    if not daily_returns:
        return 0.0
    cleaned = [_safe_float(r) for r in daily_returns]
    n = len(cleaned)
    if n < 2:
        return 0.0
    mean_ret = sum(cleaned) / n
    daily_rf = risk_free_rate / ANNUAL_TRADING_DAYS
    excess_mean = mean_ret - daily_rf
    variance = sum((r - mean_ret) ** 2 for r in cleaned) / (n - 1)
    if variance < 1e-15:
        return 0.0
    std = math.sqrt(variance)
    if std < 1e-15:
        return 0.0
    sharpe = (excess_mean / std) * math.sqrt(ANNUAL_TRADING_DAYS)
    if not math.isfinite(sharpe):
        return 0.0
    return sharpe


def _compute_sortino(daily_returns: Sequence[float], risk_free_rate: float = DEFAULT_RISK_FREE_RATE) -> float:
    """计算年化 Sortino Ratio。"""
    if not daily_returns:
        return 0.0
    cleaned = [_safe_float(r) for r in daily_returns]
    n = len(cleaned)
    if n < 2:
        return 0.0
    mean_ret = sum(cleaned) / n
    daily_rf = risk_free_rate / ANNUAL_TRADING_DAYS
    excess_mean = mean_ret - daily_rf
    downside = [(r - daily_rf) ** 2 for r in cleaned if r < daily_rf]
    if not downside:
        return 0.0
    downside_std = math.sqrt(sum(downside) / n)
    if downside_std < 1e-15:
        return 0.0
    sortino = (excess_mean / downside_std) * math.sqrt(ANNUAL_TRADING_DAYS)
    if not math.isfinite(sortino):
        return 0.0
    return sortino


def _compute_volatility(daily_returns: Sequence[float]) -> float:
    """计算年化波动率 (小数)。"""
    if not daily_returns:
        return 0.0
    cleaned = [_safe_float(r) for r in daily_returns]
    n = len(cleaned)
    if n < 2:
        return 0.0
    mean_ret = sum(cleaned) / n
    variance = sum((r - mean_ret) ** 2 for r in cleaned) / (n - 1)
    vol = math.sqrt(variance) * math.sqrt(ANNUAL_TRADING_DAYS)
    if not math.isfinite(vol):
        return 0.0
    return vol


def _compute_annualized_return(total_return: float, trading_days: int) -> float:
    """年化收益率。"""
    if trading_days <= 0 or total_return <= -1.0:
        return 0.0
    try:
        ann = (1.0 + total_return) ** (ANNUAL_TRADING_DAYS / trading_days) - 1.0
        if not math.isfinite(ann):
            return 0.0
        return ann
    except (OverflowError, ZeroDivisionError):
        return 0.0


def _compute_trading_days_in_period(start_date: str, end_date: str) -> int:
    """估算区间内交易日数 (日历日 * 5/7 近似)。"""
    start_dt = _parse_date(start_date)
    end_dt = _parse_date(end_date)
    if start_dt is None or end_dt is None:
        return 5
    calendar_days = max(1, (end_dt - start_dt).days)
    return max(1, int(calendar_days * 5 / 7))


def _resolve_trade_pnl(trade: Mapping[str, Any]) -> float:
    """Resolve a trade's PnL value, preferring ``pnl`` over ``return_pct``.

    The previous ``trade.get("pnl") or trade.get("return_pct")`` pattern
    silently misclassified break-even trades (``pnl == 0``) because the
    ``or`` short-circuits on the falsy zero.  Now we check presence
    explicitly.
    """
    if "pnl" in trade and trade["pnl"] is not None:
        return _safe_float(trade["pnl"], 0.0)
    if "return_pct" in trade and trade["return_pct"] is not None:
        return _safe_float(trade["return_pct"], 0.0)
    return 0.0


def _aggregate_trades(trades: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """聚合交易统计。"""
    if not trades:
        return {
            "total_trades": 0,
            "win_count": 0,
            "loss_count": 0,
            "win_rate": 0.0,
            "avg_win": 0.0,
            "avg_loss": 0.0,
            "profit_factor": 0.0,
        }
    wins: list[float] = []
    losses: list[float] = []
    for trade in trades:
        pnl = _resolve_trade_pnl(trade)
        if pnl > 0:
            wins.append(pnl)
        elif pnl < 0:
            losses.append(pnl)
    total = len(wins) + len(losses)
    win_rate = (len(wins) / total) if total > 0 else 0.0
    avg_win = (sum(wins) / len(wins)) if wins else 0.0
    avg_loss = (sum(losses) / len(losses)) if losses else 0.0
    if losses and abs(avg_loss) > 1e-10:
        profit_factor = avg_win / abs(avg_loss)
    elif wins:
        profit_factor = float("inf")
    else:
        profit_factor = 0.0
    return {
        "total_trades": total,
        "win_count": len(wins),
        "loss_count": len(losses),
        "win_rate": win_rate,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "profit_factor": profit_factor,
    }


def _aggregate_strategy_attribution(trades: Sequence[Mapping[str, Any]], positions_history: Sequence[Mapping[str, Any]]) -> dict[str, float]:
    """按策略聚合 PnL -> {strategy: total_pnl_pct}。

    优先从 trades 聚合; 若 trades 为空则从 positions_history 聚合。
    返回值为收益率百分比 (如 +1.2 表示 +1.2%)。
    """
    strategy_pnl: dict[str, float] = {}
    if trades:
        for trade in trades:
            strategy = str(trade.get("strategy", "") or "unknown").strip().lower()
            if not strategy or strategy == "unknown":
                continue
            pnl = _resolve_trade_pnl(trade)
            strategy_pnl[strategy] = strategy_pnl.get(strategy, 0.0) + pnl
        if strategy_pnl:
            return strategy_pnl
    for snap in positions_history:
        positions = snap.get("positions")
        if not isinstance(positions, list):
            continue
        for pos in positions:
            if not isinstance(pos, dict):
                continue
            strategy = str(pos.get("strategy", "") or "unknown").strip().lower()
            if not strategy or strategy == "unknown":
                continue
            pnl = _safe_float(pos.get("daily_pnl") or pos.get("return_pct"), 0.0)
            strategy_pnl[strategy] = strategy_pnl.get(strategy, 0.0) + pnl
    return strategy_pnl


def _find_top_winners_losers(trades: Sequence[Mapping[str, Any]], top_n: int = 3) -> tuple[list[dict], list[dict]]:
    """找最佳/最差交易。"""
    if not trades:
        return [], []
    scored: list[dict] = []
    for trade in trades:
        ticker = str(trade.get("ticker", "") or "")
        name = str(trade.get("name", "") or "")
        pnl = _safe_float(trade.get("pnl") or trade.get("return_pct"), 0.0)
        scored.append({"ticker": ticker, "name": name, "return_pct": pnl})
    scored.sort(key=lambda x: x["return_pct"], reverse=True)
    winners = [{"ticker": s["ticker"], "name": s["name"], "return_pct": s["return_pct"]} for s in scored[:top_n] if s["return_pct"] > 0]
    losers = [{"ticker": s["ticker"], "name": s["name"], "return_pct": s["return_pct"]} for s in scored[-top_n:] if s["return_pct"] < 0]
    losers.sort(key=lambda x: x["return_pct"])
    return winners, losers


def _compute_recommendation_hit_rate(recommendations: Sequence[Mapping[str, Any]], tracking_history: Sequence[Mapping[str, Any]]) -> tuple[int, float, int]:
    """计算推荐命中率。

    Returns:
        (total_recommendations, hit_rate, consecutive_hit_count)
    """
    if not recommendations and not tracking_history:
        return 0, 0.0, 0
    if tracking_history:
        hits = sum(1 for rec in tracking_history if _safe_float(rec.get("next_day_return")) > 0)
        total_tracked = sum(1 for rec in tracking_history if rec.get("next_day_return") is not None)
        hit_rate = (hits / total_tracked) if total_tracked > 0 else 0.0
        consecutive_hits = sum(1 for rec in tracking_history if _safe_int(rec.get("consecutive_days", 0)) >= 3 and _safe_float(rec.get("next_day_return")) > 0)
        return total_tracked, hit_rate, consecutive_hits
    if recommendations:
        hits = sum(1 for r in recommendations if _safe_float(r.get("next_day_return")) > 0)
        tracked = sum(1 for r in recommendations if r.get("next_day_return") is not None)
        hit_rate = (hits / tracked) if tracked > 0 else 0.0
        return tracked, hit_rate, 0
    return 0, 0.0, 0


def _resolve_period_dates(period: str, end_date: str | None = None) -> tuple[str, str]:
    """根据 period 和 end_date 解析出 (start_date, end_date) YYYYMMDD。"""
    if end_date:
        end_dt = _parse_date(end_date)
    else:
        end_dt = datetime.now()
    if end_dt is None:
        end_dt = datetime.now()
    end_str = end_dt.strftime("%Y%m%d")
    if period == "monthly":
        start_dt = end_dt - timedelta(days=30)
    else:
        start_dt = end_dt - timedelta(days=7)
    start_str = start_dt.strftime("%Y%m%d")
    return start_str, end_str


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


@dataclass
class PerformanceReport:
    """组合绩效周报/月报。"""

    period: str  # "weekly" / "monthly"
    start_date: str
    end_date: str

    # 收益
    total_return: float  # 小数 (0.032 = 3.2%)
    annualized_return: float
    benchmark_return: float
    excess_return: float  # alpha

    # 风险
    max_drawdown: float
    sharpe_ratio: float
    sortino_ratio: float
    volatility: float

    # 交易统计
    total_trades: int
    win_count: int
    loss_count: int
    win_rate: float  # 0-1
    avg_win: float
    avg_loss: float
    profit_factor: float

    # 归因
    strategy_attribution: dict[str, float] = field(default_factory=dict)  # {strategy: pnl_pct}
    top_winners: list[dict] = field(default_factory=list)  # [{ticker, name, return_pct}]
    top_losers: list[dict] = field(default_factory=list)

    # 推荐
    total_recommendations: int = 0
    recommendation_hit_rate: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Main entry
# ---------------------------------------------------------------------------


def generate_performance_report(
    positions_history: list[dict],
    trades: list[dict],
    recommendations: list[dict],
    tracking_history: list[dict],
    period: str = "weekly",
    end_date: str | None = None,
    benchmark_return: float = 0.0,
) -> PerformanceReport:
    """聚合指定周期的绩效数据。

    Args:
        positions_history: 逐日持仓快照 [{date, portfolio_value, positions: [...]}]
        trades: 交易记录 [{date, ticker, action, pnl/return_pct, strategy, ...}]
        recommendations: 推荐记录 (P1-3 格式)
        tracking_history: P1-3 追踪数据
        period: "weekly" / "monthly"
        end_date: 结束日期 YYYYMMDD; None = 今天
        benchmark_return: 基准收益率 (小数)

    Returns:
        PerformanceReport
    """
    start_date, resolved_end = _resolve_period_dates(period, end_date)

    # 1. 收益
    total_return = _compute_total_return(positions_history, start_date, resolved_end)
    trading_days = _compute_trading_days_in_period(start_date, resolved_end)
    annualized_return = _compute_annualized_return(total_return, trading_days)
    excess_return = total_return - benchmark_return

    # 2. 风险
    daily_returns = _compute_daily_returns(positions_history)
    max_drawdown = _compute_max_drawdown(positions_history)
    sharpe_ratio = _compute_sharpe(daily_returns)
    sortino_ratio = _compute_sortino(daily_returns)
    volatility = _compute_volatility(daily_returns)

    # 3. 交易统计
    trade_stats = _aggregate_trades(trades)

    # 4. 策略归因
    strategy_attribution = _aggregate_strategy_attribution(trades, positions_history)

    # 5. Top winners/losers
    top_winners, top_losers = _find_top_winners_losers(trades)

    # 6. 推荐命中率
    total_recs, hit_rate, _ = _compute_recommendation_hit_rate(recommendations, tracking_history)

    return PerformanceReport(
        period=period,
        start_date=start_date,
        end_date=resolved_end,
        total_return=total_return,
        annualized_return=annualized_return,
        benchmark_return=benchmark_return,
        excess_return=excess_return,
        max_drawdown=max_drawdown,
        sharpe_ratio=sharpe_ratio,
        sortino_ratio=sortino_ratio,
        volatility=volatility,
        total_trades=trade_stats["total_trades"],
        win_count=trade_stats["win_count"],
        loss_count=trade_stats["loss_count"],
        win_rate=trade_stats["win_rate"],
        avg_win=trade_stats["avg_win"],
        avg_loss=trade_stats["avg_loss"],
        profit_factor=trade_stats["profit_factor"],
        strategy_attribution=strategy_attribution,
        top_winners=top_winners,
        top_losers=top_losers,
        total_recommendations=total_recs,
        recommendation_hit_rate=hit_rate,
    )


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _fmt_pct(value: float) -> str:
    """格式化为百分比字符串 (带符号)。"""
    sign = "+" if value >= 0 else ""
    return f"{sign}{value * 100:.1f}%"


def _fmt_ratio(value: float) -> str:
    """格式化比率 (Sharpe / Sortino 等)。"""
    if not math.isfinite(value):
        return "N/A"
    return f"{value:.2f}"


def _bar(value: float, max_val: float, width: int = 16) -> str:
    """ASCII 条形图。"""
    if max_val <= 0:
        return "░" * width
    ratio = min(1.0, abs(value) / max_val)
    filled = int(round(ratio * width))
    return "█" * filled + "░" * (width - filled)


def render_performance_report(report: PerformanceReport) -> str:
    """渲染 ASCII 周报/月报。

    Returns:
        多行字符串报告。
    """
    period_cn = "周报" if report.period == "weekly" else "月报"
    start_display = _format_date_display(report.start_date)
    end_display = _format_date_display(report.end_date)

    lines: list[str] = []
    lines.append(f"━━━ 组合绩效{period_cn} · {start_display} ~ {end_display} ━━━")
    lines.append("")

    # -- 收益概览 --
    lines.append("── 收益概览 ──")
    lines.append(f"  期间收益: {_fmt_pct(report.total_return)}  年化: {_fmt_pct(report.annualized_return)}  基准(沪深300): {_fmt_pct(report.benchmark_return)}")
    lines.append(f"  超额收益(alpha): {_fmt_pct(report.excess_return)}")
    lines.append("")

    # -- 风险指标 --
    lines.append("── 风险指标 ──")
    lines.append(f"  最大回撤: -{report.max_drawdown * 100:.1f}%  Sharpe: {_fmt_ratio(report.sharpe_ratio)}  Sortino: {_fmt_ratio(report.sortino_ratio)}")
    lines.append(f"  波动率: {report.volatility * 100:.1f}%")
    lines.append("")

    # -- 交易统计 --
    lines.append("── 交易统计 ──")
    lines.append(f"  总交易: {report.total_trades}  盈利: {report.win_count}  亏损: {report.loss_count}  胜率: {report.win_rate * 100:.1f}%")
    lines.append(f"  平均盈利: {_fmt_pct(report.avg_win)}  平均亏损: {_fmt_pct(report.avg_loss)}  盈亏比: {_fmt_ratio(report.profit_factor)}")
    lines.append("")

    # -- 策略归因 --
    if report.strategy_attribution:
        lines.append("── 策略归因 ──")
        max_abs = max(abs(v) for v in report.strategy_attribution.values()) if report.strategy_attribution else 1.0
        sorted_strats = sorted(report.strategy_attribution.items(), key=lambda x: abs(x[1]), reverse=True)
        for strategy, pnl in sorted_strats:
            display = STRATEGY_DISPLAY_NAMES.get(strategy, strategy)
            sign = "+" if pnl >= 0 else ""
            lines.append(f"  {display:<8} {sign}{pnl:.1f}%  {_bar(pnl, max_abs)}")
        lines.append("")

    # -- 最佳/最差 --
    if report.top_winners or report.top_losers:
        lines.append("── 最佳/最差 ──")
        for w in report.top_winners[:3]:
            label = f"{w.get('ticker', '')} {w.get('name', '')}".strip()
            lines.append(f"  最佳: {label} {_fmt_pct(w.get('return_pct', 0))}")
        for lo in report.top_losers[:3]:
            label = f"{lo.get('ticker', '')} {lo.get('name', '')}".strip()
            lines.append(f"  最差: {label} {_fmt_pct(lo.get('return_pct', 0))}")
        lines.append("")

    # -- 推荐有效性 --
    lines.append("── 推荐有效性 ──")
    lines.append(f"  推荐 {report.total_recommendations} 只, 命中率 {report.recommendation_hit_rate * 100:.0f}%")

    return "\n".join(lines)
