"""--top-setups 编排器 — Phase 1 核心。

整合: setup 检测 → 分布查询 → 凸性过滤 → Kelly 排序 → 相关性折价 →
市场温度 → 风险计划 → 组合约束。

输出: 按 Kelly 仓位排序的 Top-N 命中票, 每只带分布/仓位/风险计划。

⚠ Phase 1 SHADOW 模式: 未经验证 (Phase 0 IS/OOS) 的 setup 不应实盘交易。
   渲染时强制标注 "SHADOW — 未验证, 仅供观察"。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from src.screening.offensive.context_factors import (
    correlation_discount,
    market_temperature_factor,
)
from src.screening.offensive.kelly import KellySize, compute_kelly_size
from src.screening.offensive.risk_framework import RiskPlan, build_risk_plan
from src.screening.offensive.setups.base import DetectionResult, Setup
from src.screening.offensive.statistics import Distribution

# 已注册 setup (Phase 0 验证后逐步启用; 未验证的标 shadow)
_REGISTERED_SETUPS: dict[str, type[Setup]] = {}


def register_setup(name: str, cls: type[Setup]) -> None:
    _REGISTERED_SETUPS[name] = cls


def list_setups() -> list[str]:
    return list(_REGISTERED_SETUPS.keys())


@dataclass
class SetupPick:
    """单只入选票的全部信息。"""

    ticker: str
    setup_name: str
    natural_horizon: int
    distribution: Distribution
    kelly: KellySize
    risk_plan: RiskPlan
    trigger_metadata: dict[str, Any] = field(default_factory=dict)
    correlation_discount: float = 1.0
    market_temperature_factor: float = 1.0
    shadow: bool = True  # 未经验证 = shadow


def run_top_setups(
    tickers: list[str],
    trade_date: str,
    context_by_ticker: dict[str, dict[str, Any]],
    distribution_lookup: dict[str, Distribution],
    market_temp_inputs: dict[str, float] | None = None,
    top_n: int = 10,
    max_position_pct: float = 0.10,
    convexity_min: float = 1.5,
    winrate_min: float = 0.50,
    n_min: int = 30,  # shadow 模式放宽 (Phase 0 验证后提到 50)
    shadow: bool = True,
    setups_to_run: list[str] | None = None,
) -> list[SetupPick]:
    """扫描全市场, 检测 setup 命中, 按 Kelly 排序输出 Top-N。

    Args:
        tickers: 候选 ticker (进攻池)
        trade_date: YYYYMMDD
        context_by_ticker: {ticker: context dict for setup.detect}
        distribution_lookup: {setup_name: Distribution} 历史 distribution (Phase 0 产出)
        market_temp_inputs: {n_limit_up, n_total, turnover_ratio} for market_temperature
        top_n: 输出前 N
        max_position_pct: 单票仓位上限
        convexity_min / winrate_min / n_min: 准入门槛
        shadow: True = 未经验证模式 (默认, 强制标注)
        setups_to_run: 要跑的 setup 名单; None = 全部已注册

    Returns:
        list[SetupPick] 按 kelly.position_pct 降序
    """
    setup_names = setups_to_run or list(_REGISTERED_SETUPS.keys())
    setups = [_REGISTERED_SETUPS[n]() for n in setup_names if n in _REGISTERED_SETUPS]

    # 市场温度因子
    mt_factor = 1.0
    if market_temp_inputs:
        mt_factor = market_temperature_factor(
            n_limit_up=int(market_temp_inputs.get("n_limit_up", 0)),
            n_total=int(market_temp_inputs.get("n_total", 0)),
            turnover_ratio=float(market_temp_inputs.get("turnover_ratio", 1.0)),
        )

    # 1. 扫描所有 ticker × 所有 setup → 命中列表
    hits: list[tuple[str, Setup, DetectionResult]] = []
    for ticker in tickers:
        ctx = context_by_ticker.get(ticker, {})
        for setup in setups:
            result = setup.detect(ticker, trade_date, ctx)
            if result.hit:
                hits.append((ticker, setup, result))

    # 2. 每个 setup 命中查历史分布 + 凸性过滤
    qualified: list[SetupPick] = []
    for ticker, setup, result in hits:
        dist = distribution_lookup.get(setup.name)
        if dist is None or dist.n < n_min:
            continue  # 无历史分布或样本不足
        if dist.convexity_ratio < convexity_min:
            continue
        if dist.winrate < winrate_min:
            continue

        # 3. 相关性折价 (同票多 setup 命中时)
        same_ticker_setups = [s.name for t, s, _ in hits if t == ticker]
        corr_disc = correlation_discount(same_ticker_setups)

        # 4. Kelly 仓位 (half-Kelly × 折价 × 温度)
        kelly = compute_kelly_size(
            dist,
            correlation_discount=corr_disc,
            market_temperature_factor=mt_factor,
            max_pct=max_position_pct,
        )
        if kelly.position_pct <= 0:
            continue

        # 5. 风险计划
        risk = build_risk_plan(
            invalidation_condition=result.invalidation_condition,
            avg_loss=dist.avg_loss,
            natural_horizon=setup.natural_horizon,
        )

        qualified.append(
            SetupPick(
                ticker=ticker,
                setup_name=setup.name,
                natural_horizon=setup.natural_horizon,
                distribution=dist,
                kelly=kelly,
                risk_plan=risk,
                trigger_metadata=result.metadata,
                correlation_discount=corr_disc,
                market_temperature_factor=mt_factor,
                shadow=shadow,
            )
        )

    # 6. 同票多 setup 去重: 保留 Kelly 最大的 (主 setup), 其余作为"共振"标注
    qualified.sort(key=lambda p: p.kelly.position_pct, reverse=True)
    seen_tickers: set[str] = set()
    final: list[SetupPick] = []
    for pick in qualified:
        if pick.ticker in seen_tickers:
            continue
        seen_tickers.add(pick.ticker)
        final.append(pick)
        if len(final) >= top_n:
            break

    return final


def render_top_setups(picks: list[SetupPick], trade_date: str) -> str:
    """渲染 --top-setups 输出 (decision support 格式)。

    每只票显示: setup 类型 + 历史分布 + Kelly 仓位 + 风险计划 + 失效条件。
    shadow 模式时强制标注警告。
    """
    from colorama import Fore, Style

    lines = [f"\n{Fore.CYAN}{Style.BRIGHT}🎯 Top Setups — {trade_date}{Style.RESET_ALL}"]

    if picks and picks[0].shadow:
        lines.append(f"{Fore.RED}⚠ SHADOW 模式 — setup 未经验证 (Phase 0 IS/OOS), 仅供观察, 勿实盘交易{Style.RESET_ALL}")
        lines.append(f"{Fore.RED}  完整验证 (convexity≥1.5 + winrate≥50% + n≥50 + IC>0.05 + OOS 达标) 前所有数字是回测假设, 不是承诺{Style.RESET_ALL}")

    if not picks:
        lines.append(f"  {Fore.YELLOW}今日无 setup 命中 (或全部未达凸性/样本门槛){Style.RESET_ALL}")
        return "\n".join(lines)

    lines.append("")
    for i, p in enumerate(picks, 1):
        d = p.distribution
        shadow_tag = f" {Fore.RED}[SHADOW]{Style.RESET_ALL}" if p.shadow else ""
        lines.append(f"  {Fore.WHITE}{i}.{Style.RESET_ALL} {Fore.CYAN}{p.ticker}{Style.RESET_ALL} " f"({p.setup_name}, T+{p.natural_horizon}){shadow_tag}")
        lines.append(f"     {Fore.GREEN}Kelly 仓位: {p.kelly.position_pct:.1%}{Style.RESET_ALL}  " f"(half-Kelly, 含相关性折价 {p.correlation_discount:.2f} + 温度因子 {p.market_temperature_factor:.2f})")
        lines.append(f"     历史分布: n={d.n}  winrate={d.winrate:.0%}  E[r]={d.expected_return:+.2%}  " f"convexity={d.convexity_ratio:.2f}  CI=[{d.ci_low:+.2%}, {d.ci_high:+.2%}]")
        lines.append(f"     风险计划: 止损 {p.risk_plan.stop_loss_pct:+.1%} / 硬止损 {p.risk_plan.hard_stop_pct:+.1%} / " f"时间退出 {p.risk_plan.time_exit}")
        lines.append(f"     {Fore.YELLOW}失效条件: {p.risk_plan.invalidation_condition}{Style.RESET_ALL}")
        lines.append("")

    return "\n".join(lines)


# 默认注册已实现的 setup (shadow = 未经验证)
def _register_defaults():
    try:
        from src.screening.offensive.setups.btst_breakout import BtstBreakoutSetup
        from src.screening.offensive.setups.oversold_bounce import OversoldBounceSetup
        from src.screening.offensive.setups.sector_rotation import SectorRotationSetup

        register_setup("btst_breakout", BtstBreakoutSetup)
        register_setup("oversold_bounce", OversoldBounceSetup)
        register_setup("sector_rotation", SectorRotationSetup)
    except ImportError:
        pass


_register_defaults()
