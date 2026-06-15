"""组合风险指标计算 — VaR / CVaR / 回撤预警 / 集中度。

为前端 risk-monitor-panel 提供 API-ready 的风险指标快照。

设计原则:
- 纯函数 + dataclass: 无 I/O、无全局状态、可独立单测
- 数值安全: NaN/Inf 输入视为 0,避免污染下游告警
- 历史模拟法: 直接排序 lookback 收益,不依赖参数分布假设
- 行宽 420 字符
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Iterable, Mapping, Sequence

# 行业 / 单一标的 / 回撤预警阈值 (与产业文档保持一致)
INDUSTRY_CONCENTRATION_WARNING_THRESHOLD = 0.25
SINGLE_POSITION_WARNING_THRESHOLD = 0.12
DRAWDOWN_WARNING_THRESHOLD = 0.10


def _safe_float(value: object, default: float = 0.0) -> float:
    """Convert value to finite float; NaN/Inf/non-numeric → default (GAMMA-009 safety)."""
    if isinstance(value, bool):
        return default
    if not isinstance(value, (int, float)):
        return default
    out = float(value)
    if not math.isfinite(out):
        return default
    return out


def _normalise_weights(weights: Mapping[str, float]) -> dict[str, float]:
    """Return weights normalised to sum 1.0; degenerate input → empty dict."""
    cleaned = {str(k): _safe_float(v) for k, v in weights.items()}
    cleaned = {k: max(0.0, v) for k, v in cleaned.items()}
    total = sum(cleaned.values())
    if total <= 0.0:
        return {}
    return {k: v / total for k, v in cleaned.items()}


def _histogram_var(returns: Sequence[float], confidence: float) -> float:
    """Historical-simulation VaR (loss expressed as a positive number).

    ``returns`` are decimal returns (e.g. -0.02 means -2%). Returns the
    *positive* loss number (e.g. 0.03 = 3% loss at 95% confidence). An
    empty / all-zero series returns 0.0 (no measurable risk).
    """
    cleaned = sorted(_safe_float(r) for r in returns)
    if not cleaned:
        return 0.0
    if not any(cleaned):
        return 0.0
    # loss = -return; pick the (1-confidence) lower-tail loss
    tail_index = max(0, min(len(cleaned) - 1, int(math.floor((1.0 - confidence) * len(cleaned)))))
    return max(0.0, -cleaned[tail_index])


def _histogram_cvar(returns: Sequence[float], confidence: float) -> float:
    """Historical-simulation CVaR / Expected Shortfall (positive loss number).

    CVaR averages the losses strictly *beyond* the VaR quantile — i.e. the
    ``tail_index`` worst observations (not including the VaR boundary itself).
    This matches the standard definition of Expected Shortfall (Acerbi 2002).
    """
    cleaned = sorted(_safe_float(r) for r in returns)
    if not cleaned:
        return 0.0
    tail_index = max(0, min(len(cleaned) - 1, int(math.floor((1.0 - confidence) * len(cleaned)))))
    if tail_index == 0:
        return max(0.0, -cleaned[0])
    tail = cleaned[:tail_index]
    return max(0.0, -sum(tail) / len(tail))


def _max_drawdown_from_equity(equity: Sequence[float]) -> float:
    """Return max drawdown as a non-negative decimal (e.g. 0.12 = 12%)."""
    if not equity:
        return 0.0
    peak = _safe_float(equity[0])
    max_dd = 0.0
    for value in equity:
        v = _safe_float(value)
        if v > peak:
            peak = v
        if peak > 0.0:
            dd = (peak - v) / peak
            if dd > max_dd:
                max_dd = dd
    return max_dd


def _current_drawdown_from_equity(equity: Sequence[float]) -> float:
    """Return drawdown *to the latest* observation as a non-negative decimal."""
    if not equity:
        return 0.0
    peak = max(_safe_float(v) for v in equity)
    last = _safe_float(equity[-1])
    if peak <= 0.0:
        return 0.0
    return max(0.0, (peak - last) / peak)


@dataclass
class RiskSnapshot:
    """单点风险快照 (每个时间窗口计算一次)。

    字段单位约定:
    - 货币字段 (var_*, cvar_*) 单位与 ``portfolio_value`` 一致 (元)
    - 回撤 / 占比字段为小数 (0.05 = 5%)
    - 行业集中度: ``industry_concentration`` 为 ``{行业: 占比}`` 映射, 占比总和 = 1.0
    """

    timestamp: str
    portfolio_value: float
    var_95: float = 0.0
    var_99: float = 0.0
    cvar_95: float = 0.0
    cvar_99: float = 0.0
    max_drawdown: float = 0.0
    current_drawdown: float = 0.0
    drawdown_warning: bool = False
    industry_concentration: dict[str, float] = field(default_factory=dict)
    concentration_warning: bool = False
    single_position_max: float = 0.0
    position_count: int = 0
    beta_adjusted: float = 1.0

    def to_dict(self) -> dict[str, object]:
        """Stable JSON-ready dict (frontend consumers rely on key order)."""
        return asdict(self)


def _resolve_industry_for_position(position: Mapping[str, object]) -> str:
    """Return ``industry_sw`` from a position dict, falling back to 'UNKNOWN'."""
    industry = position.get("industry_sw") or position.get("industry") or "UNKNOWN"
    return str(industry).strip() or "UNKNOWN"


def _position_market_value(position: Mapping[str, object]) -> float:
    """Compute market value (in 元) from a position dict.

    Accepts either ``market_value`` directly, or ``shares`` * ``current_price``.
    """
    mv = position.get("market_value")
    if mv is not None:
        return max(0.0, _safe_float(mv))
    shares = _safe_float(position.get("shares", 0))
    price = _safe_float(position.get("current_price", 0))
    return max(0.0, shares * price)


def _aggregate_industry_weights(
    portfolio_positions: Sequence[Mapping[str, object]],
) -> dict[str, float]:
    """Aggregate position market values into ``{industry: weight}`` map (sums to 1.0)."""
    bucket: dict[str, float] = {}
    for position in portfolio_positions:
        industry = _resolve_industry_for_position(position)
        bucket[industry] = bucket.get(industry, 0.0) + _position_market_value(position)
    return _normalise_weights(bucket)


def _portfolio_equity_curve(
    portfolio_daily_returns: Sequence[float],
    initial_value: float,
) -> list[float]:
    """Build a synthetic equity curve from portfolio-level daily returns.

    ``portfolio_daily_returns`` is a sequence of decimal returns (e.g. -0.02
    = -2%). The function compounds them starting from ``initial_value``. An
    empty input collapses the curve to ``[initial_value]`` (no drawdown).
    """
    equity: list[float] = [max(0.0, _safe_float(initial_value))]
    running = max(0.0, _safe_float(initial_value))
    for r in portfolio_daily_returns:
        running = max(0.0, running * (1.0 + _safe_float(r)))
        equity.append(running)
    return equity


def _weighted_portfolio_daily_returns(
    portfolio_positions: Sequence[Mapping[str, object]],
    lookback_returns: Sequence[Mapping[str, object]],
) -> list[float]:
    """Aggregate per-ticker lookback returns into portfolio-level daily returns.

    Each ``lookback_returns`` row contains ``{date, ticker, return_pct}``. The
    portfolio's daily return is the value-weighted average across all
    positions that have a return observation that day. If a position has no
    observation on a given date, that position's weight is excluded (rather
    than assumed-zero), which is consistent with the dashboard's "skip
    days we have no data" semantics.

    Days with no observations at all are dropped (not zero-filled) to avoid
    contaminating the historical tail with spurious zero-returns.
    """
    weights: dict[str, float] = {}
    for position in portfolio_positions:
        ticker = str(position.get("ticker", "")).strip()
        if not ticker:
            continue
        weights[ticker] = _position_market_value(position)
    weight_total = sum(weights.values())
    if weight_total <= 0.0:
        return []
    norm_weights = {t: w / weight_total for t, w in weights.items()}

    by_date: dict[str, dict[str, float]] = {}
    for row in lookback_returns:
        date = str(row.get("date", "")).strip()
        ticker = str(row.get("ticker", "")).strip()
        if not date or not ticker:
            continue
        by_date.setdefault(date, {})[ticker] = _safe_float(row.get("return_pct", 0.0))

    portfolio_returns: list[float] = []
    for date in sorted(by_date.keys()):
        per_day = by_date[date]
        numerator = 0.0
        denominator = 0.0
        for ticker, w in norm_weights.items():
            if ticker in per_day:
                numerator += w * per_day[ticker]
                denominator += w
        if denominator > 0.0:
            portfolio_returns.append(numerator / denominator)
    return portfolio_returns


def _portfolio_var_amount(
    per_ticker_returns: Sequence[float],
    portfolio_value: float,
    confidence: float,
) -> float:
    """Scale historical VaR from decimal-return space into absolute 元 amount."""
    var_decimal = _histogram_var(per_ticker_returns, confidence)
    return max(0.0, var_decimal * max(0.0, portfolio_value))


def _portfolio_cvar_amount(
    per_ticker_returns: Sequence[float],
    portfolio_value: float,
    confidence: float,
) -> float:
    """Scale historical CVaR from decimal-return space into absolute 元 amount."""
    cvar_decimal = _histogram_cvar(per_ticker_returns, confidence)
    return max(0.0, cvar_decimal * max(0.0, portfolio_value))


def _resolve_beta(
    portfolio_returns: Iterable[float],
    benchmark_returns: Sequence[float] | None,
) -> float:
    """Lightweight beta estimate of a portfolio return series against an
    optional benchmark series.

    ``portfolio_returns`` is the value-weighted portfolio daily-return series
    (decimal). Falls back to 1.0 (market-neutral proxy) when insufficient
    overlap; this is acceptable for dashboard purposes and avoids producing
    misleading near-zero betas from too-few observations (GAMMA-005 /
    ALPHA-007). The caller must pass the *aggregated* portfolio series, not
    raw per-ticker rows (ALPHA-008).
    """
    if not benchmark_returns or len(benchmark_returns) < 10:
        return 1.0
    portfolio = [_safe_float(r) for r in portfolio_returns]
    if len(portfolio) < 10:
        return 1.0
    n = min(len(portfolio), len(benchmark_returns))
    port_arr = portfolio[:n]
    bench_arr = [(_safe_float(b)) for b in benchmark_returns[:n]]
    bench_var = sum((b - (sum(bench_arr) / n)) ** 2 for b in bench_arr) / max(1, n - 1)
    if bench_var < 1e-12:
        return 1.0
    port_mean = sum(port_arr) / n
    bench_mean = sum(bench_arr) / n
    cov = sum((port_arr[i] - port_mean) * (bench_arr[i] - bench_mean) for i in range(n)) / max(1, n - 1)
    beta = cov / bench_var
    if not math.isfinite(beta):
        return 1.0
    return float(beta)


def compute_risk_snapshot(
    portfolio_positions: Sequence[Mapping[str, object]],
    lookback_returns: Sequence[Mapping[str, object]] | None = None,
    *,
    timestamp: str = "",
    initial_portfolio_value: float = 0.0,
    var_horizon_days: int = 1,
    confidence_levels: tuple[float, ...] = (0.95, 0.99),
    benchmark_returns: Sequence[float] | None = None,
    drawdown_warning_threshold: float = DRAWDOWN_WARNING_THRESHOLD,
    industry_warning_threshold: float = INDUSTRY_CONCENTRATION_WARNING_THRESHOLD,
    single_position_warning_threshold: float = SINGLE_POSITION_WARNING_THRESHOLD,
) -> RiskSnapshot:
    """从持仓 + 回溯收益计算 RiskSnapshot。

    算法:
    1. VaR/CVaR: 历史模拟法 (1日), 按 ``confidence_levels`` 计算, 缩放为元
    2. 多日 VaR 缩放: 沿用业界惯例 ``sqrt(T)`` (参数假设), 非纯历史法
    3. 最大回撤 + 当前回撤: 从 lookback_returns 累计得到 equity curve
    4. 行业集中度: 从 ``portfolio_positions.industry_sw`` 聚合
    5. 单一标的占比上限: ``max(weights)``
    6. 预警: drawdown > 10% 或 单行业 > 25% 或 单一标的 > 12%

    所有浮点字段在 NaN/Inf 时退化为 0.0,确保前端展示不报错。
    ``var_horizon_days`` 控制 sqrt(T) 缩放; 若严格要求纯历史法,调用方应
    传入实际 T 日 rolling 收益而非 1 日收益。
    """
    lookback_returns = lookback_returns or []
    cleaned_confidence = tuple(sorted({float(c) for c in confidence_levels if 0.0 < float(c) < 1.0}))
    if not cleaned_confidence:
        cleaned_confidence = (0.95, 0.99)

    # ----- 总市值 -----
    market_values = [_position_market_value(p) for p in portfolio_positions]
    position_market_total = sum(market_values)
    portfolio_value = max(0.0, _safe_float(initial_portfolio_value) or position_market_total)

    # ----- 行业集中度 -----
    industry_weights = _aggregate_industry_weights(portfolio_positions)
    concentration_warning = any(w > industry_warning_threshold for w in industry_weights.values())

    # ----- 单一标的占比 -----
    if position_market_total > 0.0:
        single_position_max = max((mv / position_market_total for mv in market_values), default=0.0)
    else:
        single_position_max = 0.0
    if single_position_max > single_position_warning_threshold:
        # 单一标的超额也算集中度预警
        concentration_warning = True

    # ----- VaR / CVaR -----
    portfolio_daily_returns = _weighted_portfolio_daily_returns(portfolio_positions, lookback_returns)
    horizon_scale = math.sqrt(max(1, int(var_horizon_days)))
    var_95 = _portfolio_var_amount(portfolio_daily_returns, portfolio_value, 0.95) * horizon_scale if 0.95 in cleaned_confidence else _portfolio_var_amount(portfolio_daily_returns, portfolio_value, min(cleaned_confidence))
    var_99 = _portfolio_var_amount(portfolio_daily_returns, portfolio_value, 0.99) * horizon_scale if 0.99 in cleaned_confidence else _portfolio_var_amount(portfolio_daily_returns, portfolio_value, max(cleaned_confidence))
    cvar_95 = _portfolio_cvar_amount(portfolio_daily_returns, portfolio_value, 0.95) * horizon_scale if 0.95 in cleaned_confidence else _portfolio_cvar_amount(portfolio_daily_returns, portfolio_value, min(cleaned_confidence))
    cvar_99 = _portfolio_cvar_amount(portfolio_daily_returns, portfolio_value, 0.99) * horizon_scale if 0.99 in cleaned_confidence else _portfolio_cvar_amount(portfolio_daily_returns, portfolio_value, max(cleaned_confidence))

    # ----- 回撤 -----
    equity_curve = _portfolio_equity_curve(portfolio_daily_returns, initial_value=portfolio_value)
    max_dd = _max_drawdown_from_equity(equity_curve)
    current_dd = _current_drawdown_from_equity(equity_curve)
    drawdown_warning = current_dd >= drawdown_warning_threshold

    # ----- Beta -----
    # Regress the *value-weighted portfolio* daily-return series (not the raw
    # per-ticker rows) against the benchmark. Passing ``lookback_returns``
    # directly conflates cross-sectional stock variation with the time-series
    # portfolio series and produces a meaningless beta (ALPHA-008).
    beta = _resolve_beta(portfolio_daily_returns, benchmark_returns)

    return RiskSnapshot(
        timestamp=str(timestamp or ""),
        portfolio_value=round(portfolio_value, 2),
        var_95=round(var_95, 2),
        var_99=round(var_99, 2),
        cvar_95=round(cvar_95, 2),
        cvar_99=round(cvar_99, 2),
        max_drawdown=round(max_dd, 4),
        current_drawdown=round(current_dd, 4),
        drawdown_warning=bool(drawdown_warning),
        industry_concentration={k: round(v, 4) for k, v in sorted(industry_weights.items(), key=lambda item: item[1], reverse=True)},
        concentration_warning=bool(concentration_warning),
        single_position_max=round(single_position_max, 4),
        position_count=len(portfolio_positions),
        beta_adjusted=round(beta, 4),
    )
