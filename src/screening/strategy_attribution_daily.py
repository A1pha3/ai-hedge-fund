"""P1-11 策略归因日报 — 每日收盘后自动归因：哪个策略贡献最大、哪个失效。

本模块是一组**纯函数**：所有计算可在无外部 IO / 网络 / 时间依赖下完成,
便于单元测试覆盖；输入只需要一份按策略标签好的持仓快照
(``[{ticker, strategy, current_value, prev_value, cost_basis}]``)。

输出:
    - ``StrategyDailyAttribution`` 单策略日度归因
    - ``compute_strategy_daily_attribution`` 主入口 (返回 ``dict[strategy_name, StrategyDailyAttribution]``)
    - ``render_attribution_report`` 渲染中文文本报告 (用于 CLI / paper_trading 日报附件)

策略名集合 (默认 4 类):
    - ``trend``           — 趋势策略
    - ``mean_reversion``  — 均值回归
    - ``fundamental``     — 基本面策略
    - ``event_sentiment`` — 事件情绪策略

判定规则 (status):
    - ``winning``  : attribution_pct > 5%   且 hit_rate > 50%
    - ``failing``  : attribution_pct < -5%  或 hit_rate < 30%
    - ``neutral``  : 其它

诊断文案 (diagnosis) 由 ``_build_diagnosis`` 根据 (策略名, status, hit_rate, top_winner/top_loser)
按规则模板生成 — 见 ``DIAGNOSIS_TEMPLATES``。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

from src.screening.custom_weights import STRATEGY_KEYS
from src.utils.numeric import safe_float as _safe_float

# ---------------------------------------------------------------------------
# Public constants
# ---------------------------------------------------------------------------

#: 已知策略名集合 — 复用 ``custom_weights.STRATEGY_KEYS`` 单一来源
#: (键与 ``src/screening/models.py:DEFAULT_STRATEGY_WEIGHTS`` 对齐)。
KNOWN_STRATEGIES: tuple[str, ...] = STRATEGY_KEYS

#: 策略名 → 中文显示名 (用于报告渲染)。
STRATEGY_DISPLAY_NAMES: dict[str, str] = {
    "trend": "趋势策略",
    "mean_reversion": "均值回归",
    "fundamental": "基本面策略",
    "event_sentiment": "事件情绪",
}

#: status 判定阈值 (可通过参数覆盖)。
WINNING_ATTR_PCT: float = 5.0
WINNING_HIT_RATE: float = 0.50
FAILING_ATTR_PCT: float = -5.0
FAILING_HIT_RATE: float = 0.30


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StrategyDailyAttribution:
    """单策略日度归因。

    Attributes:
        strategy_name: 策略名 (trend / mean_reversion / fundamental / event_sentiment)。
        daily_pnl: 当日 PnL (¥, 含已实现 + 浮动)。
        attribution_pct: 占组合总 PnL 百分比 (例 12.3 表示 12.3%)；当 portfolio_total_pnl == 0 时为 0。
        hit_rate: 命中率 ∈ [0, 1] = 盈利标的数 / 总标的数 (并列基准 daily_pnl > 0)。
        top_winner: 当日最大盈利标的 ticker；空持仓时为 None。
        top_winner_pnl: top_winner 当日 PnL；无标的时为 0.0。
        top_loser: 当日最大亏损标的 ticker；空持仓时为 None。
        top_loser_pnl: top_loser 当日 PnL；无标的时为 0.0。
        n_positions: 该策略下持仓数量。
        status: ``winning`` / ``neutral`` / ``failing``。
        diagnosis: 自然语言诊断 (中文)。
    """

    strategy_name: str
    daily_pnl: float
    attribution_pct: float
    hit_rate: float
    top_winner: str | None
    top_winner_pnl: float
    top_loser: str | None
    top_loser_pnl: float
    n_positions: int
    status: str
    diagnosis: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy_name": self.strategy_name,
            "daily_pnl": self.daily_pnl,
            "attribution_pct": self.attribution_pct,
            "hit_rate": self.hit_rate,
            "top_winner": self.top_winner,
            "top_winner_pnl": self.top_winner_pnl,
            "top_loser": self.top_loser,
            "top_loser_pnl": self.top_loser_pnl,
            "n_positions": self.n_positions,
            "status": self.status,
            "diagnosis": self.diagnosis,
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _position_daily_pnl(position: Mapping[str, Any]) -> float:
    """从单条持仓中提取当日 PnL。

    优先级:
      1. 显式 ``daily_pnl`` 字段
      2. ``current_value - prev_value`` (二者均需为有限实数, 否则返回 0 — 避免单边 NaN 污染)
      3. 否则 0
    """
    if "daily_pnl" in position:
        return _safe_float(position.get("daily_pnl"))
    current_raw = position.get("current_value")
    prev_raw = position.get("prev_value")
    # 任意一边缺失 / NaN / Inf, 该持仓的 PnL 不可信 — 整条归 0
    if current_raw is None or prev_raw is None:
        return 0.0
    try:
        current_f = float(current_raw)
        prev_f = float(prev_raw)
    except (TypeError, ValueError):
        return 0.0
    if not (math.isfinite(current_f) and math.isfinite(prev_f)):
        return 0.0
    return current_f - prev_f


def _coerce_strategy(name: Any) -> str:
    """策略名归一化 (小写 + 去空白)；空值 → ``unknown``。"""
    if name is None:
        return "unknown"
    s = str(name).strip().lower()
    return s or "unknown"


# ---------------------------------------------------------------------------
# Diagnosis templates
# ---------------------------------------------------------------------------


#: (strategy_name, status) → 中文诊断模板 (可包含 {hit_rate_pct} / {top_winner} / {top_loser} 占位)。
DIAGNOSIS_TEMPLATES: dict[tuple[str, str], str] = {
    ("trend", "winning"): "趋势持续验证，动量因子贡献突出",
    ("trend", "neutral"): "趋势信号中性，持仓表现分化",
    ("trend", "failing"): "趋势反转风险升温，动量因子失效",
    ("mean_reversion", "winning"): "趋势市中均值回归信号生效，超买/超卖方向兑现",
    ("mean_reversion", "neutral"): "震荡市中表现平稳",
    ("mean_reversion", "failing"): "震荡市中均值回归信号失效，动量反转",
    ("fundamental", "winning"): "估值修复 + 业绩验证驱动，长期价值回归",
    ("fundamental", "neutral"): "基本面驱动平淡，等待财报或政策催化",
    ("fundamental", "failing"): "估值偏差导致部分标的回撤",
    ("event_sentiment", "winning"): "催化剂主题持续发酵",
    ("event_sentiment", "neutral"): "事件驱动信号平稳，缺乏新催化",
    ("event_sentiment", "failing"): "情绪退潮，主题切换风险升高",
}


def _build_diagnosis(
    strategy_name: str,
    status: str,
    hit_rate: float,
    top_winner: str | None,
    top_loser: str | None,
) -> str:
    """根据规则模板生成中文诊断。

    模板查不到时 (例如 ``unknown`` 策略) 回退到通用文案。
    """
    key = (strategy_name, status)
    template = DIAGNOSIS_TEMPLATES.get(key)
    if template is None:
        if status == "winning":
            return f"{STRATEGY_DISPLAY_NAMES.get(strategy_name, strategy_name)} 表现亮眼，命中率 {hit_rate * 100:.0f}%"
        if status == "failing":
            return f"{STRATEGY_DISPLAY_NAMES.get(strategy_name, strategy_name)} 短期承压，命中率仅 {hit_rate * 100:.0f}%"
        return f"{STRATEGY_DISPLAY_NAMES.get(strategy_name, strategy_name)} 表现中性"
    return template


def _classify_status(
    attribution_pct: float,
    hit_rate: float,
    *,
    winning_attr_pct: float = WINNING_ATTR_PCT,
    winning_hit_rate: float = WINNING_HIT_RATE,
    failing_attr_pct: float = FAILING_ATTR_PCT,
    failing_hit_rate: float = FAILING_HIT_RATE,
) -> str:
    """根据 (attribution_pct, hit_rate) 判定 status。

    判定顺序 (重要 — failing 优先):
      1. attribution_pct < failing_attr_pct  → failing
      2. hit_rate        < failing_hit_rate  → failing
      3. attribution_pct > winning_attr_pct AND hit_rate > winning_hit_rate → winning
      4. 其它 → neutral
    """
    if attribution_pct < failing_attr_pct:
        return "failing"
    if hit_rate < failing_hit_rate:
        return "failing"
    if attribution_pct > winning_attr_pct and hit_rate > winning_hit_rate:
        return "winning"
    return "neutral"


# ---------------------------------------------------------------------------
# Public computation entry
# ---------------------------------------------------------------------------


def compute_strategy_daily_attribution(
    portfolio_positions: Sequence[Mapping[str, Any]],
    today_date: str,
    *,
    lookback_window: int = 20,
    known_strategies: Iterable[str] | None = None,
    winning_attr_pct: float = WINNING_ATTR_PCT,
    winning_hit_rate: float = WINNING_HIT_RATE,
    failing_attr_pct: float = FAILING_ATTR_PCT,
    failing_hit_rate: float = FAILING_HIT_RATE,
) -> dict[str, StrategyDailyAttribution]:
    """计算四策略的日度归因。

    Args:
        portfolio_positions: 持仓列表，每项至少包含::

            {
                "ticker":        str,
                "strategy":      str (trend / mean_reversion / fundamental / event_sentiment),
                "current_value": float,   # 当日收盘市值
                "prev_value":    float,   # 前一日收盘市值
                "cost_basis":    float,   # 成本基础 (可选, 暂未使用)
                "daily_pnl":     float,   # 可选, 优先级最高
            }
        today_date: 当日日期 (仅作上下文记录, 不参与计算)。
        lookback_window: 滚动窗口 (保留参数, 用于将来扩展 — e.g. 滚动 Sharpe / IR)。
        known_strategies: 策略白名单, 默认 ``KNOWN_STRATEGIES``；未在白名单内的策略统一聚到 ``unknown``。
        winning_attr_pct / winning_hit_rate / failing_attr_pct / failing_hit_rate:
            status 判定阈值, 默认值见模块常量。

    Returns:
        ``{strategy_name: StrategyDailyAttribution}`` 映射。空持仓 → 空 dict。
    """
    _ = today_date  # 仅记录, 当前未参与计算
    _ = lookback_window
    whitelist = set(known_strategies) if known_strategies is not None else set(KNOWN_STRATEGIES)

    # 1. 按 strategy 分组
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for pos in portfolio_positions:
        if not isinstance(pos, Mapping):
            continue
        strategy = _coerce_strategy(pos.get("strategy"))
        if strategy not in whitelist:
            strategy = "unknown"
        grouped.setdefault(strategy, []).append(pos)

    if not grouped:
        return {}

    # 2. 组合总 PnL — 用于计算 attribution_pct
    total_pnl = 0.0
    for pos in portfolio_positions:
        if not isinstance(pos, Mapping):
            continue
        total_pnl += _position_daily_pnl(pos)

    attributions: dict[str, StrategyDailyAttribution] = {}
    for strategy_name, positions in grouped.items():
        # 3. 单策略 daily_pnl
        per_position_pnl: list[tuple[str, float]] = []
        for pos in positions:
            ticker = str(pos.get("ticker", "")).strip()
            pnl = _position_daily_pnl(pos)
            per_position_pnl.append((ticker, pnl))

        strategy_pnl = sum(pnl for _, pnl in per_position_pnl)
        n_positions = len(per_position_pnl)

        # 4. attribution_pct (% scale; 0 when total_pnl == 0 → 避免除零)
        if total_pnl == 0.0:
            attribution_pct = 0.0
        else:
            attribution_pct = (strategy_pnl / total_pnl) * 100.0

        # 5. hit_rate (并列基准 pnl > 0)
        winners = [pnl for _, pnl in per_position_pnl if pnl > 0]
        hit_rate = (len(winners) / n_positions) if n_positions > 0 else 0.0

        # 6. top winner / top loser
        if per_position_pnl:
            top_winner_entry = max(per_position_pnl, key=lambda x: x[1])
            top_loser_entry = min(per_position_pnl, key=lambda x: x[1])
            top_winner = top_winner_entry[0] if top_winner_entry[1] > 0 else None
            top_winner_pnl = top_winner_entry[1] if top_winner_entry[1] > 0 else 0.0
            top_loser = top_loser_entry[0] if top_loser_entry[1] < 0 else None
            top_loser_pnl = top_loser_entry[1] if top_loser_entry[1] < 0 else 0.0
        else:
            top_winner = None
            top_winner_pnl = 0.0
            top_loser = None
            top_loser_pnl = 0.0

        # 7. status
        status = _classify_status(
            attribution_pct,
            hit_rate,
            winning_attr_pct=winning_attr_pct,
            winning_hit_rate=winning_hit_rate,
            failing_attr_pct=failing_attr_pct,
            failing_hit_rate=failing_hit_rate,
        )

        # 8. diagnosis
        diagnosis = _build_diagnosis(strategy_name, status, hit_rate, top_winner, top_loser)

        attributions[strategy_name] = StrategyDailyAttribution(
            strategy_name=strategy_name,
            daily_pnl=strategy_pnl,
            attribution_pct=attribution_pct,
            hit_rate=hit_rate,
            top_winner=top_winner,
            top_winner_pnl=top_winner_pnl,
            top_loser=top_loser,
            top_loser_pnl=top_loser_pnl,
            n_positions=n_positions,
            status=status,
            diagnosis=diagnosis,
        )

    return attributions


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _format_currency(value: float) -> str:
    """¥ 显示, 千分位; 正数前加 ``+`` 符号。"""
    sign = "+" if value > 0 else ""
    return f"{sign}¥{value:,.0f}"


def _status_symbol(status: str) -> str:
    """status → 视觉符号 (终端友好, 不依赖 ANSI 颜色)。"""
    return {"winning": "✓", "failing": "✗", "neutral": "○"}.get(status, "·")


def _summary_line(attributions: Mapping[str, StrategyDailyAttribution]) -> str:
    """根据各策略 status 生成总结句。"""
    winners = sorted(
        [a for a in attributions.values() if a.status == "winning"],
        key=lambda a: a.attribution_pct,
        reverse=True,
    )
    failers = sorted(
        [a for a in attributions.values() if a.status == "failing"],
        key=lambda a: a.attribution_pct,
    )
    winner_names = "、".join(STRATEGY_DISPLAY_NAMES.get(a.strategy_name, a.strategy_name) for a in winners)
    failer_names = "、".join(STRATEGY_DISPLAY_NAMES.get(a.strategy_name, a.strategy_name) for a in failers)

    if winners and failers:
        return f"总结: {winner_names} 双驱动，{failer_names} 短期承压。"
    if winners and not failers:
        return f"总结: {winner_names} 主导今日组合收益。"
    if failers and not winners:
        return f"总结: {failer_names} 整体承压，需关注风格切换。"
    return "总结: 策略表现整体中性，等待下一交易日信号确认。"


def render_attribution_report(
    attributions: Mapping[str, StrategyDailyAttribution],
    portfolio_total_pnl: float,
    date: str,
    *,
    portfolio_value_base: float | None = None,
) -> str:
    """渲染策略归因日报 (中文文本)。

    Args:
        attributions: ``{strategy_name: StrategyDailyAttribution}``。
        portfolio_total_pnl: 组合当日总 PnL (¥)。
        date: 报告日期 (YYYY-MM-DD 或 YYYYMMDD, 仅用于标题展示)。
        portfolio_value_base: 组合昨日净值 (¥), 用于显示百分比涨幅；为 None 时不显示百分比。

    Returns:
        多行字符串报告。
    """
    if not attributions:
        return f"━━━ 策略归因日报 · {date} ━━━\n\n暂无持仓 — 无可归因数据。\n"

    lines: list[str] = []
    header = f"━━━ 策略归因日报 · {date} ━━━"
    lines.append(header)
    lines.append("")

    if portfolio_value_base and portfolio_value_base > 0:
        pct = (portfolio_total_pnl / portfolio_value_base) * 100.0
        lines.append(f"组合当日 PnL: {_format_currency(portfolio_total_pnl)} ({pct:+.2f}%)")
    else:
        lines.append(f"组合当日 PnL: {_format_currency(portfolio_total_pnl)}")
    lines.append("")
    lines.append("各策略表现:")

    # 按 attribution_pct 降序展示
    sorted_attrs = sorted(attributions.values(), key=lambda a: a.attribution_pct, reverse=True)
    for attr in sorted_attrs:
        display_name = STRATEGY_DISPLAY_NAMES.get(attr.strategy_name, attr.strategy_name)
        symbol = _status_symbol(attr.status)
        contributor = f"最大贡献: {attr.top_winner}" if attr.top_winner else (f"最大拖累: {attr.top_loser}" if attr.top_loser else "无方向标的")
        # 第一行: 符号 + 名称 + PnL + 占比 + 命中率 + 最大贡献/拖累
        lines.append(f"  {symbol} {display_name:<8} {_format_currency(attr.daily_pnl):<10} " f"({attr.attribution_pct:+.1f}%)  命中率 {attr.hit_rate * 100:.0f}%  {contributor}")
        # 第二行: 诊断 (缩进 4 空格 + 箭头)
        lines.append(f"    ─→ {attr.diagnosis}")

    lines.append("")
    lines.append(_summary_line(attributions))
    lines.append("")
    return "\n".join(lines)
