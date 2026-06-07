"""P1-10 条件单建议 — 基于回测历史波动率 (ATR) 给出每只推荐标的的
「建议买入区间 / 止损价 / 止盈价 / 盈亏比 / 历史命中率」。

设计原则:
  - **纯函数 + dataclass**: 不读写文件, 不发网络, 便于单测。
  - **ATR 波动率代理**: 14 日平均真实波幅 (Average True Range) 是业界标准的
    短期波动率指标, 用它把建议价位归一化到「波动率自适应」尺度。
  - **买入区间宽度 / 止损 / 止盈**: 以 ATR 倍数表示, 默认 ±0.5 ATR / -2 ATR / +3 ATR。
  - **历史命中率**: 标的最近 N 个交易日的收盘价, 落在「建议买入区间」的比例。
  - **数值安全**: NaN / Inf / None 输入一律兜底, 不抛异常 (除参数级 ValueError)。
  - **降级**: 数据不足 (价格 < atr_period+1) → 触发降级, 仍返回占位结果,
    ``confidence = 0.0`` + ``reasoning`` 含降级原因。

主入口:
  - :class:`ConditionalOrderAdvice`  单标的条件单建议 (dataclass)
  - :func:`compute_conditional_advice`  核心算法 (ATR + 区间 + 止损/止盈 + 命中率)
  - :func:`compute_advice_from_history`  便捷 wrapper: 直接接受 ``[{date, close, ...}]`` 历史
  - :func:`format_conditional_advice_table`  CLI / 报告渲染 (中文文本表)
  - :func:`run_conditional_orders_cli`  CLI 入口 (供 main.py --conditional-orders 复用)
  - :func:`attach_conditional_orders_to_payload`  集成到 :func:`src.main.compute_auto_screening_results`
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Iterable, Mapping, Sequence

from src.utils.numeric import safe_float as _safe_float, is_finite_number as _is_finite

# ---------------------------------------------------------------------------
# Constants & defaults
# ---------------------------------------------------------------------------

#: ATR 周期 (默认 14 日 — 与业界技术分析标准一致)
DEFAULT_ATR_PERIOD: int = 14

#: 回溯窗口 (默认 60 日 — 约 3 个月)
DEFAULT_LOOKBACK_SESSIONS: int = 60

#: 买入区间半宽 = 0.5 × ATR (默认) → 总宽度 = 1.0 × ATR
DEFAULT_ZONE_WIDTH_ATR: float = 0.5

#: 止损距离 = 2.0 × ATR (默认)
DEFAULT_STOP_LOSS_ATR: float = 2.0

#: 止盈距离 = 3.0 × ATR (默认) → 盈亏比 = 1.5
DEFAULT_TAKE_PROFIT_ATR: float = 3.0

#: 价格序列最少需要多少点 (低于此值降级)
MIN_PRICE_SESSIONS: int = 5


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class ConditionalOrderAdvice:
    """单只股票的条件单建议。

    Fields:
        ticker: 6 位 A 股代码或美股 ticker
        name: 标的中文 / 英文名 (可空)
        current_price: 当前价 (元 / 美元, 与 price_history 单位一致)
        atr: 计算出的 ATR 值 (与价格同单位)
        suggested_buy_zone: ``(low, high)`` 建议买入区间 (元)
        suggested_stop_loss: 建议止损价 (元)
        suggested_take_profit: 建议止盈价 (元)
        confidence: 建议置信度 0-1 (基于历史数据量 + 波动率稳定性)
        reasoning: 文字理由 (中文, 单行)
        historical_hit_rate: 历史区间命中率 (历史 N 日中收盘价落在
            ``[buy_low, buy_high]`` 的天数比例, 0-1)
        risk_reward_ratio: 盈亏比 = (take_profit - current) / (current - stop_loss)
        n_sessions: 实际用于计算的历史日数
        degraded: 是否降级 (数据不足 / 异常)
        atr_period: ATR 周期 (回显)
        params: 计算参数快照 (供审计)
    """

    ticker: str
    name: str
    current_price: float
    atr: float
    suggested_buy_zone: tuple[float, float]
    suggested_stop_loss: float
    suggested_take_profit: float
    confidence: float
    reasoning: str
    historical_hit_rate: float
    risk_reward_ratio: float
    n_sessions: int
    degraded: bool
    atr_period: int
    params: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """JSON-safe dict (供 Web 端响应, NaN → None)。"""
        out = asdict(self)
        # tuple 不可 JSON 序列化, 转 list
        low, high = out["suggested_buy_zone"]
        out["suggested_buy_zone"] = [float(low), float(high)]
        out["suggested_buy_zone_low"] = float(low)
        out["suggested_buy_zone_high"] = float(high)
        # NaN / Inf 兜底
        for key, value in list(out.items()):
            if isinstance(value, float):
                if math.isnan(value) or math.isinf(value):
                    out[key] = None
        return out


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------






def _clean_price_series(values: Iterable[object]) -> list[float]:
    """过滤 NaN/Inf/None, 保留有限 float 序列。"""
    out: list[float] = []
    for v in values:
        if _is_finite(v):
            out.append(float(v))
    return out


# ---------------------------------------------------------------------------
# Core algorithm
# ---------------------------------------------------------------------------


def compute_atr(price_history: Sequence[float], *, period: int = DEFAULT_ATR_PERIOD) -> float:
    """计算平均真实波幅 (Average True Range)。

    算法 (经典 Wilder 平滑):
      TR_t = max(high-low, |high - prev_close|, |low - prev_close|)
      当仅有 close 单序列时, 退化为:
        TR_t = |close_t - close_{t-1}|  (近似, 业界常见 fallback)
      ATR = (1/period) × Σ_{i=0..period-1} TR_{t-i}
      至少需要 ``period + 1`` 个数据点 (含 prev_close)。

    Args:
        price_history: 收盘价序列 (升序, 最新的在末尾)
        period: ATR 周期 (默认 14)

    Returns:
        ATR 值; 数据不足 / 全部 NaN → 0.0
    """
    if period <= 0:
        return 0.0
    cleaned = _clean_price_series(price_history)
    # 至少需要 period+1 个点 (含 prev_close)
    if len(cleaned) < period + 1:
        # 数据实在不够 → 用全部 close 差值平均
        if len(cleaned) < 2:
            return 0.0
        diffs = [abs(cleaned[i] - cleaned[i - 1]) for i in range(1, len(cleaned))]
        if not diffs:
            return 0.0
        return sum(diffs) / len(diffs)

    # 取最后 period+1 个点
    window = cleaned[-(period + 1) :]
    trs: list[float] = []
    for i in range(1, len(window)):
        trs.append(abs(window[i] - window[i - 1]))
    return sum(trs) / len(trs) if trs else 0.0


def compute_conditional_advice(
    ticker: str,
    current_price: float,
    price_history: Sequence[float],
    *,
    name: str = "",
    atr_period: int = DEFAULT_ATR_PERIOD,
    lookback_sessions: int = DEFAULT_LOOKBACK_SESSIONS,
    zone_width_atr: float = DEFAULT_ZONE_WIDTH_ATR,
    stop_loss_atr: float = DEFAULT_STOP_LOSS_ATR,
    take_profit_atr: float = DEFAULT_TAKE_PROFIT_ATR,
) -> ConditionalOrderAdvice:
    """给定当前价 + 价格历史, 计算条件单建议。

    算法步骤:
      1. 清理价格序列 (去 NaN/Inf), 取最近 ``lookback_sessions`` 个点
      2. 计算 ATR (周期 = ``atr_period``)
      3. 建议买入区间: ``[current - zone_width_atr * ATR, current + zone_width_atr * ATR]``
      4. 建议止损:   ``current - stop_loss_atr * ATR``
      5. 建议止盈:   ``current + take_profit_atr * ATR``
      6. 历史命中率: 历史中收盘价落在 [buy_low, buy_high] 的天数比例
      7. 盈亏比:     ``(take_profit - current) / (current - stop_loss)``
      8. 置信度:     基于 ``min(1.0, n_sessions / 30) × 0.7 + (1 - 异常波动惩罚) × 0.3``
      9. 数据不足 (价格点数 < MIN_PRICE_SESSIONS 或 ATR=0) → 触发降级

    Args:
        ticker: 标的代码
        current_price: 当前价 (与 price_history 同单位)
        price_history: 收盘价序列 (升序)
        name: 标的中文名 (可空)
        atr_period: ATR 周期 (默认 14)
        lookback_sessions: 实际回看的最近 N 个交易日 (默认 60)
        zone_width_atr: 买入区间半宽的 ATR 倍数 (默认 0.5)
        stop_loss_atr: 止损距离的 ATR 倍数 (默认 2.0)
        take_profit_atr: 止盈距离的 ATR 倍数 (默认 3.0)

    Returns:
        :class:`ConditionalOrderAdvice` 实例; **不会** 抛异常 (除参数级 ValueError)。
    """
    # 参数级校验 — 防止 0/负值导致反向建议
    if atr_period <= 0:
        raise ValueError(f"atr_period 必须为正整数, 实际: {atr_period}")
    if lookback_sessions <= 0:
        raise ValueError(f"lookback_sessions 必须为正整数, 实际: {lookback_sessions}")
    if zone_width_atr < 0:
        raise ValueError(f"zone_width_atr 必须为非负, 实际: {zone_width_atr}")
    if stop_loss_atr < 0:
        raise ValueError(f"stop_loss_atr 必须为非负, 实际: {stop_loss_atr}")
    if take_profit_atr < 0:
        raise ValueError(f"take_profit_atr 必须为非负, 实际: {take_profit_atr}")

    # 安全化输入
    current = _safe_float(current_price, 0.0)
    cleaned = _clean_price_series(price_history or [])

    # 取最近 lookback_sessions
    if len(cleaned) > lookback_sessions:
        cleaned = cleaned[-lookback_sessions:]

    n_sessions = len(cleaned)

    # 触发降级的条件:
    #   - 价格序列不足 MIN_PRICE_SESSIONS
    #   - current_price <= 0
    #   - 清洗后无任何数据
    degraded = (n_sessions < MIN_PRICE_SESSIONS) or (current <= 0.0) or (n_sessions == 0)

    if not degraded:
        atr = compute_atr(cleaned, period=atr_period)
    else:
        atr = 0.0

    # 即使 ATR=0 也不直接降级, 而是给一个固定 0.5% 的占位 ATR (用 current_price × 0.005)
    # 以保证 output 不会因 ATR=0 出现 [x, x] 的退化区间
    if atr <= 0.0 and not degraded:
        atr = current * 0.005
    elif atr <= 0.0 and degraded:
        atr = max(current * 0.005, 0.01) if current > 0.0 else 0.01

    # 计算建议价位
    buy_low = current - zone_width_atr * atr
    buy_high = current + zone_width_atr * atr
    stop_loss = current - stop_loss_atr * atr
    take_profit = current + take_profit_atr * atr

    # 价格 <= 0 的极端降级: 把建议价位固定为 current=0
    if current <= 0.0:
        buy_low = buy_high = stop_loss = take_profit = 0.0
        atr = 0.0

    # 历史命中率
    if not degraded and n_sessions > 0:
        hits = sum(1 for p in cleaned if buy_low <= p <= buy_high)
        hit_rate = hits / n_sessions
    else:
        hit_rate = 0.0

    # 盈亏比
    risk = current - stop_loss
    reward = take_profit - current
    if risk > 0.0:
        rr = reward / risk
    else:
        rr = 0.0

    # 置信度
    # 0.7 × 数据充分度 (min(1, n/30)) + 0.3 × 波动率稳定性 (1 - cv_clip)
    # cv = stdev/mean, 越大说明价格波动相对幅度越剧烈, 建议越不可靠
    if not degraded and n_sessions >= 2 and current > 0.0:
        data_sufficiency = min(1.0, n_sessions / 30.0)
        mean_price = sum(cleaned) / n_sessions
        if mean_price > 0.0:
            var = sum((p - mean_price) ** 2 for p in cleaned) / n_sessions
            cv = math.sqrt(var) / mean_price
        else:
            cv = 1.0
        # cv 越小越好; 截到 [0, 1] — cv=0 → 1.0, cv>=1 → 0.0
        stability = max(0.0, 1.0 - cv)
        confidence = data_sufficiency * 0.7 + stability * 0.3
    else:
        confidence = 0.0

    # 限定在 [0, 1]
    confidence = max(0.0, min(1.0, confidence))

    # Reasoning
    if degraded:
        reason = (
            f"降级: 数据不足 (n_sessions={n_sessions} < {MIN_PRICE_SESSIONS} 或 current_price 异常),"
            f" 建议仅作参考, 请补充至少 {MIN_PRICE_SESSIONS} 个交易日数据"
        )
    else:
        # 简明理由
        reason = (
            f"基于 {n_sessions} 日历史, ATR(period={atr_period})={atr:.4f}; "
            f"建议在 ±{zone_width_atr:.1f}×ATR 区间分批买入, "
            f"止损 {stop_loss_atr:.1f}×ATR, 止盈 {take_profit_atr:.1f}×ATR"
        )

    return ConditionalOrderAdvice(
        ticker=str(ticker or "").strip(),
        name=str(name or "").strip(),
        current_price=current,
        atr=atr,
        suggested_buy_zone=(buy_low, buy_high),
        suggested_stop_loss=stop_loss,
        suggested_take_profit=take_profit,
        confidence=confidence,
        reasoning=reason,
        historical_hit_rate=hit_rate,
        risk_reward_ratio=rr,
        n_sessions=n_sessions,
        degraded=degraded,
        atr_period=atr_period,
        params={
            "lookback_sessions": float(lookback_sessions),
            "zone_width_atr": float(zone_width_atr),
            "stop_loss_atr": float(stop_loss_atr),
            "take_profit_atr": float(take_profit_atr),
        },
    )


def compute_advice_from_history(
    ticker: str,
    *,
    name: str = "",
    history_bars: Sequence[Mapping[str, Any]] | None = None,
    current_price: float | None = None,
    **kwargs: Any,
) -> ConditionalOrderAdvice:
    """便捷 wrapper: 接受 ``[{date, close, ...}]`` 风格历史 bars。

    Args:
        ticker: 标的代码
        name: 中文名
        history_bars: 历史 K 线 dict 列表 (每条至少含 ``close``);
            缺省 / None → 视为空历史 (触发降级)
        current_price: 当前价; None 时取 ``history_bars[-1]['close']``
        **kwargs: 透传给 :func:`compute_conditional_advice`

    Returns:
        :class:`ConditionalOrderAdvice` 实例
    """
    cleaned: list[float] = []
    if history_bars:
        for bar in history_bars:
            if not isinstance(bar, Mapping):
                continue
            close_val = bar.get("close", bar.get("close_price", bar.get("price")))
            if _is_finite(close_val):
                cleaned.append(float(close_val))

    if current_price is None and cleaned:
        current_price = cleaned[-1]
    elif current_price is None:
        current_price = 0.0

    return compute_conditional_advice(
        ticker=ticker,
        current_price=float(current_price),
        price_history=cleaned,
        name=name,
        **kwargs,
    )


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def format_conditional_advice_table(
    advices: Sequence[ConditionalOrderAdvice],
    *,
    date_label: str | None = None,
    title: str = "条件单建议 · 基于 ATR 波动率",
) -> str:
    """渲染为人类可读的文本表 (类似 ``tabulate`` 输出)。

    Args:
        advices: ``ConditionalOrderAdvice`` 列表
        date_label: 表头日期 (默认今天)
        title: 表头标题

    Returns:
        多行字符串 (含空数据降级信息)
    """
    label = date_label or datetime.now().strftime("%Y-%m-%d")
    lines: list[str] = []
    lines.append(f"━━━ {title} · {label} ━━━")
    lines.append("")

    if not advices:
        lines.append("无推荐标的 (请先运行 --auto 生成 Top N 推荐)")
        return "\n".join(lines) + "\n"

    # 表头
    header = (
        f"{'代码':<8} | {'名称':<10} | {'现价':>9} | "
        f"{'买入区间':<20} | {'止损':>9} | {'止盈':>9} | "
        f"{'盈亏比':>6} | {'置信度':>6} | {'状态':<4}"
    )
    lines.append(header)
    lines.append("-" * len(header))

    for adv in advices:
        low, high = adv.suggested_buy_zone
        zone_text = f"[{low:.2f}, {high:.2f}]"
        rr_text = f"{adv.risk_reward_ratio:.1f}" if adv.risk_reward_ratio > 0 else "—"
        conf_text = f"{adv.confidence * 100:.0f}%"
        status = "降级" if adv.degraded else "OK"
        name_disp = adv.name[:8] if adv.name else "—"
        lines.append(
            f"{adv.ticker:<8} | {name_disp:<10} | {adv.current_price:>9.2f} | "
            f"{zone_text:<20} | {adv.suggested_stop_loss:>9.2f} | "
            f"{adv.suggested_take_profit:>9.2f} | {rr_text:>6} | {conf_text:>6} | {status:<4}"
        )

    lines.append("")
    ok_count = sum(1 for a in advices if not a.degraded)
    deg_count = len(advices) - ok_count
    lines.append(f"共 {len(advices)} 条建议 (有效 {ok_count} / 降级 {deg_count})")
    lines.append("使用提示: 条件单按「买入区间」分批挂单, 止损/止盈按建议价挂单")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Integration with auto_screening payload
# ---------------------------------------------------------------------------


def attach_conditional_orders_to_payload(
    payload: Mapping[str, Any],
    *,
    price_provider: Any | None = None,
    atr_period: int = DEFAULT_ATR_PERIOD,
    lookback_sessions: int = DEFAULT_LOOKBACK_SESSIONS,
    top_n: int | None = None,
) -> list[dict[str, Any]]:
    """集成到 ``compute_auto_screening_results`` 的 payload。

    Args:
        payload: ``compute_auto_screening_results`` 返回的 dict;
            读 ``payload["recommendations"]`` (含 ticker / name / score_b 等)
        price_provider: 可调用 ``price_provider(ticker, n_sessions) -> list[float]``;
            None 时使用 :func:`_fallback_price_provider` (返回空历史, 全降级)
        atr_period: ATR 周期
        lookback_sessions: 回溯窗口
        top_n: 仅处理 Top N 标的 (None = 全部)

    Returns:
        ``[advice.to_dict(), ...]`` 列表 — 供 caller 写入 payload["conditional_orders"]
    """
    recs = payload.get("recommendations") or []
    if not isinstance(recs, list) or not recs:
        return []

    if top_n is not None and top_n > 0:
        recs = recs[:top_n]

    advices: list[dict[str, Any]] = []
    for rec in recs:
        if not isinstance(rec, Mapping):
            continue
        ticker = str(rec.get("ticker", "")).strip()
        if not ticker:
            continue
        name = str(rec.get("name", "") or "")

        # 拉价格历史
        if price_provider is not None:
            try:
                history = price_provider(ticker, lookback_sessions)
            except Exception:  # noqa: BLE001 — 价格 provider 容错
                history = []
        else:
            history = _fallback_price_provider(ticker, lookback_sessions)

        history_list = list(history) if history else []
        current_price = float(rec.get("current_price") or 0.0)
        if current_price <= 0.0 and history_list:
            current_price = float(history_list[-1])

        advice = compute_conditional_advice(
            ticker=ticker,
            current_price=current_price,
            price_history=history_list,
            name=name,
            atr_period=atr_period,
            lookback_sessions=lookback_sessions,
        )
        advices.append(advice.to_dict())

    return advices


def _fallback_price_provider(ticker: str, n_sessions: int) -> list[float]:
    """Fallback 价格 provider — 返回空列表, 触发全降级。

    实际生产环境应由 caller 注入真实 provider (akshare / tushare)。
    """
    return []


# ---------------------------------------------------------------------------
# CLI entry
# ---------------------------------------------------------------------------


def run_conditional_orders_cli(
    top_n: int = 20,
    *,
    atr_period: int = DEFAULT_ATR_PERIOD,
    lookback_sessions: int = DEFAULT_LOOKBACK_SESSIONS,
    price_provider: Any | None = None,
) -> int:
    """CLI 入口 — 加载最新 auto_screening 报告, 输出条件单建议。

    Args:
        top_n: 处理 Top N 推荐 (默认 20, 最大 50)
        atr_period: ATR 周期 (默认 14)
        lookback_sessions: 回溯窗口 (默认 60)
        price_provider: 价格 provider (None = fallback, 全降级)

    Returns:
        退出码 (0 = 成功, 1 = 未找到报告, 2 = 报告无推荐)
    """
    from colorama import Fore, Style

    # 1. 加载最新报告
    from src.screening.compare_tool import load_latest_recommendations

    recs = load_latest_recommendations()
    if not recs:
        print(
            f"{Fore.YELLOW}[ConditionalOrders] 未找到有效 auto_screening 报告, "
            f"请先运行 --auto{Style.RESET_ALL}"
        )
        return 1

    # 2. 截到 Top N
    recs = recs[: max(1, min(50, top_n))]
    if not recs:
        print(f"{Fore.YELLOW}[ConditionalOrders] 报告中无推荐标的{Style.RESET_ALL}")
        return 2

    # 3. 计算每只标的的条件单建议
    advices: list[ConditionalOrderAdvice] = []
    for rec in recs:
        if not isinstance(rec, Mapping):
            continue
        ticker = str(rec.get("ticker", "")).strip()
        if not ticker:
            continue
        name = str(rec.get("name", "") or "")
        if price_provider is not None:
            try:
                history = price_provider(ticker, lookback_sessions)
            except Exception:  # noqa: BLE001
                history = []
        else:
            history = _fallback_price_provider(ticker, lookback_sessions)
        history_list = list(history) if history else []
        current_price = float(rec.get("current_price") or 0.0)
        if current_price <= 0.0 and history_list:
            current_price = float(history_list[-1])

        advice = compute_conditional_advice(
            ticker=ticker,
            current_price=current_price,
            price_history=history_list,
            name=name,
            atr_period=atr_period,
            lookback_sessions=lookback_sessions,
        )
        advices.append(advice)

    # 4. 打印
    print(f"\n{Fore.CYAN}{Style.BRIGHT}{'=' * 70}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}{Style.BRIGHT}[P1-10] 条件单建议 (ATR 波动率法){Style.RESET_ALL}")
    print(f"  ATR 周期: {atr_period}  |  回溯: {lookback_sessions} 日  |  Top N: {len(advices)}")
    print(f"{Fore.CYAN}{Style.BRIGHT}{'=' * 70}{Style.RESET_ALL}\n")
    print(format_conditional_advice_table(advices), end="")
    return 0


__all__ = [
    "DEFAULT_ATR_PERIOD",
    "DEFAULT_LOOKBACK_SESSIONS",
    "DEFAULT_ZONE_WIDTH_ATR",
    "DEFAULT_STOP_LOSS_ATR",
    "DEFAULT_TAKE_PROFIT_ATR",
    "MIN_PRICE_SESSIONS",
    "ConditionalOrderAdvice",
    "compute_atr",
    "compute_conditional_advice",
    "compute_advice_from_history",
    "format_conditional_advice_table",
    "attach_conditional_orders_to_payload",
    "run_conditional_orders_cli",
]
