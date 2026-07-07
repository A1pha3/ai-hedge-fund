"""--daily-action — Phase A 核心: 每日机械交易动作 (移除情绪决策)。

输入: 最新 auto_screening 报告 + fund_flow store + paper_trading 状态
输出: 今日的具体动作 (BUY/EXIT/SKIP) + 入场价 + 止损 + 仓位 + 风险计划

设计原则 (Phase A "稳定小 edge"):
- 用 BTST T+10 验证过的分布作 Kelly 先验 (不动态拟合, 防过拟合)
- drawdown 熔断自动降仓/清仓 (移除"亏时恐慌" 的情绪)
- 预提交止损 + 时间退出 (移除"希望/恐惧")
- 每笔写入 paper_trading journal (暴露行为偏差, 30 天后复盘)
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from src.screening.offensive.kelly import compute_kelly_size
from src.screening.offensive.known_distributions import get_known_distribution
from src.screening.offensive.paper_tracker import PaperTracker, TradeAction
from src.screening.offensive.risk_framework import build_risk_plan
from src.screening.offensive.setups.btst_breakout import BtstBreakoutSetup

logger = logging.getLogger(__name__)

# Phase A: 单 setup (BTST T+10), 单仓位上限, 严格风控
_MAX_POSITION_PCT = 0.10  # 单票 ≤ 10%
_MAX_PORTFOLO_PCT = 0.60  # 组合 ≤ 60%
_USE_TUSHARE_PRICES = True  # akshare 在本 env 代理封了


@dataclass
class DailyAction:
    """今日单只票的动作。"""

    ticker: str
    setup: str
    action: str  # "BUY" | "SKIP"
    kelly_pct: float
    entry_price: float
    soft_stop: float
    hard_stop: float
    time_exit: str
    invalidation_condition: str
    distribution_summary: str  # "n=5374 winrate=51% cv=1.53 E=+2.6%"
    reasoning: str


def _load_prices_for_ticker(ticker: str, report_date: str) -> pd.DataFrame:
    """加载 ticker 价格 (tushare 优先, 含报告日前的历史)。"""
    cache = Path("data/price_cache") / f"{ticker}.csv"
    if cache.exists():
        df = pd.read_csv(cache, dtype={"date": str})
        df["date"] = pd.to_datetime(df["date"])
        return df
    # 拉取 (tushare)
    import os

    token = ""
    if os.path.exists(".env"):
        for line in Path(".env").read_text(encoding="utf-8").splitlines():
            if line.startswith("TUSHARE_TOKEN="):
                token = line.split("=", 1)[1].strip().strip("'\"")
    if not token:
        return pd.DataFrame()
    import tushare as ts

    ts.set_token(token)
    pro = ts.pro_api()
    suffix = ".SZ" if ticker.startswith(("0", "3")) else ".SH"
    raw = pro.daily(ts_code=f"{ticker}{suffix}", start_date="20200101", end_date=report_date)
    if raw is None or len(raw) == 0:
        return pd.DataFrame()
    df = (
        pd.DataFrame(
            {
                "date": pd.to_datetime(raw["trade_date"], format="%Y%m%d"),
                "close": raw["close"].astype(float),
                "open": raw["open"].astype(float),
                "high": raw["high"].astype(float),
                "low": raw["low"].astype(float),
                "pct_change": raw["pct_chg"].astype(float),
            }
        )
        .sort_values("date")
        .reset_index(drop=True)
    )
    cache.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(cache, index=False)
    return df


def generate_daily_action(
    report_path: Path | str | None = None,
    tracker: PaperTracker | None = None,
    tickers_to_scan: int = 30,
    *,
    use_data_fetcher: Any = None,
    price_loader: Any = None,
) -> list[DailyAction]:
    """生成今日机械动作。

    流程:
    1. 加载最新报告候选 + fund_flow store + paper_trading 状态
    2. **先平到期仓位 + 回填 realized P&L** (驱动 drawdown, 保证熔断基于最新 nav)
    3. drawdown 熔断检查 (决定是否允许新仓)
    4. 对候选跑 BTST detect (T+10 horizon)
    5. 命中票查 BTST_BREAKOUT_T10 已知分布 → Kelly 仓位
    6. 风险计划 (止损 + 时间退出 + 失效条件)
    7. 写入 paper journal

    Args:
        use_data_fetcher: ``(ticker, start, end) -> [{"time", "close"}, ...]`` 注入
            seam, 传给 close_matured 取 T+N 收益 (测试用, 对齐 recommendation_tracker)
        price_loader: ``(ticker, report_date) -> DataFrame`` 注入 seam, 传给
            close_matured 读 low 序列检测止损触发 (测试用)
    """
    if tracker is None:
        tracker = PaperTracker()

    # 1. 加载报告
    if report_path is None:
        from src.screening.consecutive_recommendation import resolve_report_dir
        from src.screening.data_quality_audit import _find_latest_report

        latest = _find_latest_report(resolve_report_dir())
        if latest is None:
            return []
        report_path = latest

    with open(report_path, encoding="utf-8") as f:
        report = json.loads(f.read())
    trade_date = str(report.get("date", ""))
    recs = report.get("recommendations", [])[:tickers_to_scan]

    # 2. 先平到期仓位 + 回填 realized P&L → 驱动 drawdown (闭环核心)
    #    必须在 drawdown_action() 之前, 否则熔断基于陈旧 nav (永远是初始 1.0).
    tracker.close_matured(trade_date, use_data_fetcher=use_data_fetcher, price_loader=price_loader)

    # 3. drawdown 熔断 (此时基于 close_matured 回填后的最新 nav)
    dd_action = tracker.drawdown_action()
    if dd_action == "liquidate":
        return []  # -20% 清仓, 不出新仓信号

    # 3. 资金流 store
    from src.screening.offensive.data.fund_flow_store import FundFlowStore

    store = FundFlowStore(cache_dir="data/fund_flow_cache/")

    # 4. 已知分布 (BTST T+10)
    known_dist = get_known_distribution("btst_breakout", 10)
    if known_dist is None:
        logger.warning("无 BTST T+10 已知分布, --daily-action 无法出信号")
        return []

    btst = BtstBreakoutSetup()
    actions: list[DailyAction] = []
    portfolio_position_used = 0.0  # 已用仓位 (本批)
    _load_prices = price_loader if price_loader is not None else _load_prices_for_ticker

    for rec in recs:
        ticker = str(rec.get("ticker", ""))
        if not ticker:
            continue

        prices = _load_prices(ticker, trade_date)
        if prices is None or len(prices) == 0:
            continue
        flow_records = store.get_range(ticker, "20200101", trade_date)

        # BTST detect (industry_pct 近似: 用 ticker 自身 pct, floor 3.0 if 涨停)
        last_row = prices.iloc[-1]
        pct = float(last_row.get("pct_change", 0.0) or 0.0)
        industry_pct = max(pct, 3.0) if pct >= 9.5 else pct

        ctx = {
            "prices": prices,
            "fund_flow_records": flow_records,
            "industry_day_pct": industry_pct,
            "regime": str(report.get("market_state", {}).get("regime_gate_level", "normal")),
        }
        result = btst.detect(ticker, trade_date, ctx)
        if not result.hit:
            tracker.record_skip(trade_date, ticker, "btst_breakout", 10, reasoning=f"未触发 (pct={pct:.1f}%)")
            continue

        # 5. Kelly 仓位 (drawdown decrease 时减半)
        kelly = compute_kelly_size(known_dist, max_pct=_MAX_POSITION_PCT)
        size_factor = 0.5 if dd_action == "decrease" else 1.0  # -15% 降仓
        kelly_pct = kelly.position_pct * size_factor

        # 组合仓位上限
        if portfolio_position_used + kelly_pct > _MAX_PORTFOLO_PCT:
            kelly_pct = max(0, _MAX_PORTFOLO_PCT - portfolio_position_used)
        if kelly_pct <= 0:
            tracker.record_skip(trade_date, ticker, "btst_breakout", 10, reasoning="组合仓位已满")
            continue

        # 6. 风险计划
        risk = build_risk_plan(
            invalidation_condition=result.invalidation_condition,
            avg_loss=known_dist.avg_loss,
            natural_horizon=10,
        )
        entry_price = float(last_row["close"])  # 简化: 用触发日收盘 (实际次日开盘)
        soft_stop_price = entry_price * (1 + risk.stop_loss_pct)
        hard_stop_price = entry_price * (1 + risk.hard_stop_pct)

        dist_summary = f"n={known_dist.n} winrate={known_dist.winrate:.0%} " f"cv={known_dist.convexity_ratio:.2f} E=+{known_dist.expected_return:.1%}"

        action = DailyAction(
            ticker=ticker,
            setup="btst_breakout",
            action="BUY",
            kelly_pct=kelly_pct,
            entry_price=entry_price,
            soft_stop=soft_stop_price,
            hard_stop=hard_stop_price,
            time_exit=risk.time_exit,
            invalidation_condition=result.invalidation_condition,
            distribution_summary=dist_summary,
            reasoning=f"BTST T+10 命中; half-Kelly {kelly_pct:.1%}; drawdown={dd_action}",
        )
        actions.append(action)
        portfolio_position_used += kelly_pct

        # 写入 journal
        tracker.record_buy(
            trade_date=trade_date,
            ticker=ticker,
            setup="btst_breakout",
            horizon=10,
            entry_price=entry_price,
            kelly_pct=kelly_pct,
            soft_stop=soft_stop_price,
            hard_stop=hard_stop_price,
            invalidation=result.invalidation_condition,
            reasoning=action.reasoning,
        )

    return actions


def render_daily_action(
    actions: list[DailyAction],
    trade_date: str,
    tracker: PaperTracker,
    *,
    closed_positions: list[dict[str, Any]] | None = None,
) -> str:
    """渲染机械动作 (decision support, 移除情绪)。

    Args:
        closed_positions: close_matured 返回的平仓摘要 (今日到期平仓的仓位).
            若有, 在组合状态后渲染平仓段, 让 operator 看到 realized P&L 演进.
            默认从 tracker.last_closed_positions 读 (generate_daily_action 已缓存).
    """
    from colorama import Fore, Style

    # 默认从 tracker 缓存读 (generate_daily_action 调 close_matured 时已写入)
    if closed_positions is None:
        closed_positions = getattr(tracker, "last_closed_positions", None) or []

    state = tracker.state
    dd = tracker.drawdown_action()
    dd_tag = {  # risk state
        "normal": f"{Fore.GREEN}正常{Style.RESET_ALL}",
        "decrease": f"{Fore.YELLOW}-15%降仓{Style.RESET_ALL}",
        "liquidate": f"{Fore.RED}-20%清仓{Style.RESET_ALL}",
    }[dd]

    lines = [
        f"\n{Fore.CYAN}{Style.BRIGHT}📋 今日机械动作 — {trade_date} (Phase A paper trading){Style.RESET_ALL}",
        f"  组合净值: {state.nav:.3f}  回撤: {state.drawdown_pct:+.1%}  风控状态: {dd_tag}",
        f"  持仓数: {state.open_positions}  累计已实现: {state.realized_pnl_pct:+.2%}",
    ]

    # 今日平仓摘要 (闭环核心: operator 看到 realized P&L 演进 + 止损触发披露)
    if closed_positions:
        lines.append(f"\n  {Fore.WHITE}📤 今日到期平仓 ({len(closed_positions)} 只):{Style.RESET_ALL}")
        for c in closed_positions:
            pnl = c.get("realized_pnl", 0.0)
            pnl_color = Fore.GREEN if pnl >= 0 else Fore.RED
            stop_flag = ""
            if c.get("stop_would_have_triggered"):
                stop_flag = f"  {Fore.YELLOW}⚠ 期间触硬止损{Style.RESET_ALL}"
            lines.append(
                f"  - {Fore.CYAN}{c.get('ticker', '')}{Style.RESET_ALL}  "
                f"realized {pnl_color}{pnl:+.1%}{Style.RESET_ALL}  "
                f"exit ~{c.get('exit_price', 0.0):.2f}{stop_flag}"
            )

    if dd == "liquidate":
        lines.append(f"\n  {Fore.RED}⚠ DRAWDOWN 熔断 (-20%) — 不出新仓, 平掉所有持仓{Style.RESET_ALL}")
        return "\n".join(lines)

    if not actions:
        lines.append(f"\n  {Fore.YELLOW}今日无 BTST T+10 命中 (空仓等待){Style.RESET_ALL}")
        return "\n".join(lines)

    lines.append(f"\n  {Fore.GREEN}今日 BUY ({len(actions)} 只):{Style.RESET_ALL}\n")
    for i, a in enumerate(actions, 1):
        lines.append(f"  {Fore.WHITE}{i}. {Fore.CYAN}{a.ticker}{Style.RESET_ALL}  仓位 {a.kelly_pct:.1%}  入场 ~{a.entry_price:.2f}")
        lines.append(f"     止损: 软 {a.soft_stop:.2f} / 硬 {a.hard_stop:.2f}  时间退出: {a.time_exit}")
        lines.append(f"     先验分布: {a.distribution_summary}")
        lines.append(f"     {Fore.YELLOW}失效: {a.invalidation_condition}{Style.RESET_ALL}\n")

    lines.append(f"  {Fore.WHITE}执行规则 (移除情绪):{Style.RESET_ALL}")
    lines.append(f"  - 次日开盘买入 (不追涨, 涨停买不到就放弃)")
    lines.append(f"  - 触硬止损或失效条件 → 当日收盘平")
    lines.append(f"  - T+10 到期 → 无条件平 (不恋战)")
    lines.append(f"  - 回撤 -15% 自动降仓 / -20% 清仓")
    # 闭环已自动: close_matured 在 generate_daily_action 开头平到期仓并回填 P&L.
    # 此前写 "30 天后用 --paper-pnl 复盘" 是死承诺 (该命令从未实现).
    lines.append(f"\n  {Fore.WHITE}已写入 paper journal (T+10 到期自动平仓 + 回填 realized P&L){Style.RESET_ALL}")
    return "\n".join(lines)
