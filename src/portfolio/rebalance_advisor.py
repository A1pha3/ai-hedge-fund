"""组合再平衡建议 — 基于当前持仓和市场状态,输出具体操作列表。

P1-12 目标: 当某些持仓因涨跌偏离目标权重、或市场状态变化时,自动给出
「加仓 / 减仓 / 调仓」建议,供 CLI / Web 端消费。

设计原则:
  - **纯函数 + dataclass**: 不读写文件,不依赖外部状态,便于单测。
  - **数值安全**: 所有输入字段经 NaN/Inf 兜底,杜绝告警污染。
  - **优先级三档**: 1=强制(行业 / 单一标的超限) / 2=强烈建议(偏离 > target_drift_strong) / 3=低优(细微调整)。
  - **行业集中度硬约束**: 行业占比超过 ``INDUSTRY_HARD_LIMIT``(默认 25%) 强制减仓到上限内。

主入口:
  - :class:`RebalanceAction` — 单条再平衡操作 (ticker / action / delta_weight / reason / priority)
  - :func:`compute_rebalance_actions` — 输入持仓 list[dict] + portfolio_value, 输出 list[RebalanceAction]
  - :func:`format_rebalance_actions` — CLI / 报告渲染辅助
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Mapping, Sequence

# ---------------------------------------------------------------------------
# 默认阈值
# ---------------------------------------------------------------------------

#: 偏离目标权重多少触发建议 (默认 5%)
DEFAULT_DRIFT_THRESHOLD: float = 0.05
#: 严重偏离阈值,触发优先级 1/2 升级 (默认 10%)
STRONG_DRIFT_THRESHOLD: float = 0.10
#: 行业硬限制 (默认 25%) — 与 risk_metrics.INDUSTRY_CONCENTRATION_WARNING_THRESHOLD 对齐
INDUSTRY_HARD_LIMIT: float = 0.25
#: 单一标的硬限制 (默认 15%)
SINGLE_NAME_HARD_LIMIT: float = 0.15
#: 默认最小交易金额 (元) — 低于此值视为 "hold"
DEFAULT_MIN_TRADE_AMOUNT: float = 1_000.0


# ---------------------------------------------------------------------------
# 数据模型
# ---------------------------------------------------------------------------


@dataclass
class RebalanceAction:
    """单条再平衡操作。

    Fields:
        ticker: 6 位 A 股代码或美股 ticker
        name: 中文 / 英文名 (可空)
        action: "buy" / "sell" / "hold" / "trim" / "add"
            - "buy":  当前 0 仓位 → 新开仓
            - "sell": 强制清仓 (硬约束触发)
            - "trim": 减仓 (有现仓位)
            - "add":  加仓 (有现仓位)
            - "hold": 不变 (偏离 < 阈值, 或调整金额 < 最小交易金额)
        sector: 行业名 (申万一级) — 用于行业集中度可视化
        current_weight: 当前权重 [0, 1]
        target_weight: 目标权重 [0, 1]
        delta_weight: 调整量 (target - current); >0 = 加仓, <0 = 减仓
        delta_amount: 调整金额 (元) = delta_weight * portfolio_value
        reason: 操作理由 (中文短句)
        priority: 1=高(强制) / 2=中(强烈建议) / 3=低(细微调整)
    """

    ticker: str
    name: str
    action: str
    sector: str
    current_weight: float
    target_weight: float
    delta_weight: float
    delta_amount: float
    reason: str
    priority: int

    def to_dict(self) -> dict[str, Any]:
        """JSON-safe dict (供 Web 端响应)。"""
        return asdict(self)


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------


def _safe_float(value: object, default: float = 0.0) -> float:
    """NaN/Inf/非数值 → default,杜绝告警污染。"""
    if isinstance(value, bool):
        return default
    if value is None:
        return default
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(out):
        return default
    return out


def _aggregate_sector_weights(positions_with_weights: Sequence[Mapping[str, Any]]) -> dict[str, float]:
    """按行业聚合当前权重。"""
    bucket: dict[str, float] = {}
    for pos in positions_with_weights:
        sector = str(pos.get("sector", "") or "UNKNOWN").strip() or "UNKNOWN"
        weight = _safe_float(pos.get("current_weight"), 0.0)
        bucket[sector] = bucket.get(sector, 0.0) + max(0.0, weight)
    return bucket


# ---------------------------------------------------------------------------
# 核心算法
# ---------------------------------------------------------------------------


def compute_rebalance_actions(
    positions: Sequence[Mapping[str, Any]],
    portfolio_value: float,
    *,
    drift_threshold: float = DEFAULT_DRIFT_THRESHOLD,
    strong_drift_threshold: float = STRONG_DRIFT_THRESHOLD,
    min_trade_amount: float = DEFAULT_MIN_TRADE_AMOUNT,
    industry_hard_limit: float = INDUSTRY_HARD_LIMIT,
    single_name_hard_limit: float = SINGLE_NAME_HARD_LIMIT,
) -> list[RebalanceAction]:
    """计算再平衡建议。

    Args:
        positions: 持仓列表,每条至少含 ``ticker`` / ``current_value`` /
            ``target_weight``。可选字段: ``name`` / ``sector``。
            ``current_value`` 单位与 ``portfolio_value`` 一致(元)。
        portfolio_value: 当前组合总价值(元)。
        drift_threshold: 偏离触发阈值,|delta| > 阈值 才生成建议(默认 5%)。
        strong_drift_threshold: 严重偏离阈值,>= 阈值 触发优先级 2(默认 10%)。
        min_trade_amount: 最小交易金额,低于此值的调整改为 "hold"。
        industry_hard_limit: 行业占比硬限制,超过强制减仓到上限内(默认 25%)。
        single_name_hard_limit: 单一标的硬限制,超过强制减仓(默认 15%)。

    Returns:
        list[RebalanceAction] — 按 priority 升序 (1 在前) + |delta_amount| 降序。

    算法步骤:
        1. 计算每标的 current_weight = current_value / portfolio_value
        2. 检测硬约束:
           - sector 累计 > industry_hard_limit → 该 sector 内最大持仓减仓到限内
           - 单一标的 > single_name_hard_limit → 强制减仓到上限
        3. 普通漂移检测:
           - |delta| < drift_threshold → "hold"
           - delta > 0 (加仓): 优先级按 |delta| 与 strong_drift_threshold 比较
           - delta < 0 (减仓): 同上
        4. 最小交易金额过滤: |delta_amount| < min_trade_amount → "hold"
        5. 按 priority + |delta_amount| 排序
    """
    portfolio_value = _safe_float(portfolio_value, 0.0)
    if portfolio_value <= 0.0:
        return []

    drift_threshold = max(0.0, _safe_float(drift_threshold, DEFAULT_DRIFT_THRESHOLD))
    strong_drift_threshold = max(drift_threshold, _safe_float(strong_drift_threshold, STRONG_DRIFT_THRESHOLD))
    min_trade_amount = max(0.0, _safe_float(min_trade_amount, DEFAULT_MIN_TRADE_AMOUNT))
    industry_hard_limit = max(0.0, _safe_float(industry_hard_limit, INDUSTRY_HARD_LIMIT))
    single_name_hard_limit = max(0.0, _safe_float(single_name_hard_limit, SINGLE_NAME_HARD_LIMIT))

    # Pass 1: 计算 current_weight 与 normalized target_weight
    enriched: list[dict[str, Any]] = []
    total_target = 0.0
    for pos in positions:
        ticker = str(pos.get("ticker", "")).strip()
        if not ticker:
            continue
        current_value = max(0.0, _safe_float(pos.get("current_value"), 0.0))
        target_weight = max(0.0, _safe_float(pos.get("target_weight"), 0.0))
        total_target += target_weight
        enriched.append(
            {
                "ticker": ticker,
                "name": str(pos.get("name", "") or ""),
                "sector": str(pos.get("sector", "") or "UNKNOWN").strip() or "UNKNOWN",
                "current_value": current_value,
                "current_weight": current_value / portfolio_value,
                "target_weight": target_weight,
            }
        )

    # 容差: 用户传入的 target_weight 可能未归一化, 仅在显著偏离 1.0 时警告
    # 这里不强制归一化 — 让 caller 自行决定 (避免被动改写用户意图)

    # Pass 2: 检测行业硬约束
    sector_weights = _aggregate_sector_weights(enriched)
    sector_over_limit: dict[str, float] = {
        sec: weight for sec, weight in sector_weights.items() if weight > industry_hard_limit
    }

    actions: list[RebalanceAction] = []
    handled_tickers: set[str] = set()

    # 优先级 1: 单一标的硬约束 + 行业硬约束
    for pos in enriched:
        ticker = pos["ticker"]
        cw = pos["current_weight"]
        sector = pos["sector"]

        # 单一标的超限
        if cw > single_name_hard_limit:
            target = single_name_hard_limit
            delta = target - cw
            delta_amount = delta * portfolio_value
            actions.append(
                RebalanceAction(
                    ticker=ticker,
                    name=pos["name"],
                    action="sell",
                    sector=sector,
                    current_weight=cw,
                    target_weight=target,
                    delta_weight=delta,
                    delta_amount=delta_amount,
                    reason=f"单标的超配 (>{single_name_hard_limit:.0%}), 强制减仓",
                    priority=1,
                )
            )
            handled_tickers.add(ticker)
            continue

        # 行业超限 — 减仓本行业内最重的标的, 一次只动一只 (避免连锁清仓)
        if sector in sector_over_limit:
            # 本行业内当前权重最高的优先减
            heaviest = max(
                (p for p in enriched if p["sector"] == sector and p["ticker"] not in handled_tickers),
                key=lambda p: p["current_weight"],
                default=None,
            )
            if heaviest is not None and heaviest["ticker"] == ticker:
                excess = sector_weights[sector] - industry_hard_limit
                # 把超出部分从本标的减出
                target_weight_after = max(0.0, cw - excess)
                delta = target_weight_after - cw
                delta_amount = delta * portfolio_value
                actions.append(
                    RebalanceAction(
                        ticker=ticker,
                        name=pos["name"],
                        action="sell",
                        sector=sector,
                        current_weight=cw,
                        target_weight=target_weight_after,
                        delta_weight=delta,
                        delta_amount=delta_amount,
                        reason=f"行业 {sector} 超限 ({sector_weights[sector]:.0%} > {industry_hard_limit:.0%}), 强制减仓",
                        priority=1,
                    )
                )
                handled_tickers.add(ticker)
                # 把 sector 从超限集合移除, 避免本行业重复触发
                del sector_over_limit[sector]

    # 优先级 2/3: 普通漂移
    for pos in enriched:
        if pos["ticker"] in handled_tickers:
            continue
        cw = pos["current_weight"]
        tw = pos["target_weight"]
        delta = tw - cw
        delta_amount = delta * portfolio_value
        abs_delta = abs(delta)

        # 偏离过小 — hold
        if abs_delta < drift_threshold:
            continue

        # 最小交易金额过滤 — hold
        if abs(delta_amount) < min_trade_amount:
            continue

        # 决定 action / priority / reason
        priority = 2 if abs_delta >= strong_drift_threshold else 3
        if cw <= 0.0 and delta > 0.0:
            action = "buy"
            reason = f"新开仓位 (目标 {tw:.1%})"
        elif tw <= 0.0 and delta < 0.0:
            action = "sell"
            reason = "目标权重为 0, 清仓"
        elif delta > 0.0:
            action = "add"
            reason = f"严重低配 {abs_delta:.1%}" if priority == 2 else f"略低配 {abs_delta:.1%}"
        else:  # delta < 0
            action = "trim"
            reason = f"严重超配 {abs_delta:.1%}" if priority == 2 else f"略超配 {abs_delta:.1%}"

        actions.append(
            RebalanceAction(
                ticker=pos["ticker"],
                name=pos["name"],
                action=action,
                sector=pos["sector"],
                current_weight=cw,
                target_weight=tw,
                delta_weight=delta,
                delta_amount=delta_amount,
                reason=reason,
                priority=priority,
            )
        )

    # 排序: priority 升序 + |delta_amount| 降序
    actions.sort(key=lambda a: (a.priority, -abs(a.delta_amount)))
    return actions


# ---------------------------------------------------------------------------
# CLI 渲染辅助
# ---------------------------------------------------------------------------


def format_rebalance_actions(
    actions: Sequence[RebalanceAction],
    portfolio_value: float,
    *,
    drift_threshold: float = DEFAULT_DRIFT_THRESHOLD,
    date_label: str | None = None,
) -> str:
    """渲染再平衡建议为人类可读的文本块 (无 ANSI 颜色)。

    与 CLI ``--rebalance`` 配合使用。Web 端可使用 ``to_dict`` 直接返回 JSON。
    """
    label = (date_label or datetime.now().strftime("%Y-%m-%d"))
    lines: list[str] = []
    lines.append(f"━━━ 组合再平衡建议 · {label} ━━━")
    lines.append("")
    lines.append(f"当前组合价值: ¥{portfolio_value:,.0f}")
    lines.append(f"再平衡阈值: {drift_threshold:.0%} 偏离")
    lines.append("")

    if not actions:
        lines.append("当前持仓与目标权重对齐, 无再平衡建议。")
        lines.append("")
        return "\n".join(lines)

    def _act_label(action: str, delta_amount: float) -> str:
        if action == "sell":
            return "卖出"
        if action == "buy":
            return "买入"
        if action == "trim":
            return "减仓"
        if action == "add":
            return "加仓"
        return "保持"

    groups: dict[int, list[RebalanceAction]] = {1: [], 2: [], 3: []}
    for a in actions:
        groups.setdefault(a.priority, []).append(a)

    section_labels = {1: "强烈建议 (优先级 1)", 2: "建议 (优先级 2)", 3: "保持 (优先级 3)"}
    for prio in (1, 2, 3):
        bucket = groups.get(prio, [])
        if not bucket:
            continue
        lines.append(section_labels[prio] + ":")
        for a in bucket:
            label_str = _act_label(a.action, a.delta_amount)
            name_str = f"{a.ticker} {a.name}" if a.name else a.ticker
            direction_label = "减仓" if a.delta_amount < 0 else "加仓"
            amount_str = f"{direction_label} ¥{abs(a.delta_amount):,.0f}"
            lines.append(
                f"  {label_str:>4}  {name_str:<18}  当前 {a.current_weight:>5.1%} → 目标 {a.target_weight:>5.1%}  {amount_str}  原因: {a.reason}"
            )
        lines.append("")

    if not any(groups.get(p) for p in (1, 2, 3)):
        lines.append("保持 (优先级 3):")
        lines.append("  无操作")
        lines.append("")
    return "\n".join(lines)


__all__ = [
    "DEFAULT_DRIFT_THRESHOLD",
    "STRONG_DRIFT_THRESHOLD",
    "INDUSTRY_HARD_LIMIT",
    "SINGLE_NAME_HARD_LIMIT",
    "DEFAULT_MIN_TRADE_AMOUNT",
    "RebalanceAction",
    "compute_rebalance_actions",
    "format_rebalance_actions",
]
