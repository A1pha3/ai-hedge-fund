"""Phase A 30 天历史回测 — 验证 --daily-action 在真实历史数据上的 P&L。

模拟: 过去 30 个交易日, 每天用 BTST T+10 setup 扫全 300 ticker,
hit 就次日开盘买入 (10% 仓位), 持有到 T+10 或硬止损 -10%, 平仓后算 P&L。

输出: 总收益 / 胜率 / 最大回撤 / Sharpe / 交易数 vs 等权基线。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from src.screening.offensive.setups.btst_breakout import BtstBreakoutSetup

logging.basicConfig(level=logging.WARNING, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger(__name__)

_POSITION_PCT = 0.10  # 单票 10%
_MAX_POSITIONS = 6  # 最多 6 个并发 (60%)
_HARD_STOP = -0.10  # -10% 硬止损 (优化后)
_SLIPPAGE = 0.003  # 0.3% 单边
_HORIZON = 10  # T+10


@dataclass
class Position:
    ticker: str
    entry_date: str  # YYYYMMDD
    entry_price: float
    size_pct: float  # 占 entry 时 NAV 的比例
    days_held: int = 0
    exit_date: str = ""
    exit_price: float = 0.0
    pnl_pct: float = 0.0  # 单笔相对 NAV 的收益贡献
    exit_reason: str = ""  # "hard_stop" / "time_exit"


@dataclass
class BacktestResult:
    trades: list[Position] = field(default_factory=list)
    nav_curve: list[tuple[str, float]] = field(default_factory=list)  # (date, nav)
    final_nav: float = 1.0
    total_return_pct: float = 0.0
    win_rate: float = 0.0
    max_drawdown_pct: float = 0.0
    sharpe: float = 0.0
    n_trades: int = 0
    n_wins: int = 0


def _load_universe() -> tuple[dict[str, pd.DataFrame], dict[str, list], list[str]]:
    """加载全部 cached ticker 的价格 + 资金流; 返回统一交易日历。"""
    price_dir = Path("data/price_cache/")
    flow_dir = Path("data/fund_flow_cache/")
    prices_by_ticker: dict[str, pd.DataFrame] = {}
    flow_by_ticker: dict[str, list] = {}
    all_dates: set[str] = set()

    for pf in price_dir.glob("*.csv"):
        ticker = pf.stem
        df = pd.read_csv(pf, dtype={"date": str})
        df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y%m%d")
        df = df.sort_values("date").reset_index(drop=True)
        prices_by_ticker[ticker] = df
        all_dates.update(df["date"].tolist())

    for ff in flow_dir.glob("*.csv"):
        ticker = ff.stem
        df = pd.read_csv(ff, dtype={"date": str})
        from src.screening.offensive.data.fund_flow_store import FundFlowRecord

        flow_by_ticker[ticker] = [
            FundFlowRecord(
                ticker=ticker,
                date=str(row["date"]),
                close=float(row.get("close", 0) or 0),
                pct_change=float(row.get("pct_change", 0) or 0),
                main_net_inflow=float(row.get("main_net_inflow", 0) or 0),
                main_net_pct=float(row.get("main_net_pct", 0) or 0),
            )
            for _, row in df.iterrows()
        ]

    trading_days = sorted(all_dates)
    return prices_by_ticker, flow_by_ticker, trading_days


def run_backtest(n_days: int = 30) -> BacktestResult:
    """跑最近 n_days 个交易日的 BTST T+10 回测。"""
    prices_by_ticker, flow_by_ticker, trading_days = _load_universe()
    if len(trading_days) < n_days + _HORIZON + 5:
        print(f"数据不足: 需 ≥{n_days + _HORIZON + 5} 天, 实际 {len(trading_days)}")
        return BacktestResult()

    # 回测窗口: 最后 n_days 天作为"入场日", 但需要 +HORIZON 天让仓位成熟
    # 所以入场日 = trading_days[-(n_days+HORIZON) : -HORIZON]
    end_idx = len(trading_days) - _HORIZON  # 留 HORIZON 天让最后一批成熟
    start_idx = end_idx - n_days
    entry_days = trading_days[start_idx:end_idx]
    print(f"回测窗口: {entry_days[0]} → {entry_days[-1]} ({len(entry_days)} 入场日)")
    print(f"成熟窗口延伸到: {trading_days[end_idx + _HORIZON - 1]}")

    setup = BtstBreakoutSetup()
    nav = 1.0
    positions: list[Position] = []
    closed: list[Position] = []
    nav_curve: list[tuple[str, float]] = []
    peak = 1.0
    max_dd = 0.0

    # 遍历从 start_idx 到结尾的所有交易日 (处理入场 + 出场)
    for d_idx in range(start_idx, len(trading_days)):
        today = trading_days[d_idx]

        # 1. 检查现有持仓的止损 / 时间退出
        still_open: list[Position] = []
        for pos in positions:
            ticker_df = prices_by_ticker.get(pos.ticker)
            if ticker_df is None:
                continue
            row = ticker_df[ticker_df["date"] == today]
            if len(row) == 0:
                still_open.append(pos)
                continue
            low = float(row.iloc[0]["low"])
            close = float(row.iloc[0]["close"])
            pos.days_held += 1

            # 硬止损: 当日最低 <= entry × (1-0.08)
            stop_price = pos.entry_price * (1 + _HARD_STOP)
            if low <= stop_price:
                pos.exit_date = today
                pos.exit_price = stop_price * (1 - _SLIPPAGE)
                pos.exit_reason = "hard_stop"
                trade_ret = (pos.exit_price / pos.entry_price) - 1
                pos.pnl_pct = pos.size_pct * trade_ret
                nav *= 1 + pos.pnl_pct
                closed.append(pos)
                continue
            # 时间退出: T+10
            if pos.days_held >= _HORIZON:
                pos.exit_date = today
                pos.exit_price = close * (1 - _SLIPPAGE)
                pos.exit_reason = "time_exit"
                trade_ret = (pos.exit_price / pos.entry_price) - 1
                pos.pnl_pct = pos.size_pct * trade_ret
                nav *= 1 + pos.pnl_pct
                closed.append(pos)
                continue
            still_open.append(pos)
        positions = still_open

        # 2. 当日入场 (只在 entry_days 内)
        if today in entry_days and len(positions) < _MAX_POSITIONS:
            slots = _MAX_POSITIONS - len(positions)
            new_buys = 0
            for ticker, tdf in prices_by_ticker.items():
                if new_buys >= slots:
                    break
                # 已经持仓的不再加
                if any(p.ticker == ticker for p in positions):
                    continue
                # 需要 today 是该 ticker 的交易日 + 有 next day (入场)
                row_idx = tdf.index[tdf["date"] == today].tolist()
                if not row_idx:
                    continue
                t_idx = row_idx[0]
                if t_idx + 1 >= len(tdf):
                    continue  # 无次日开盘
                # PIT: 用 today 及之前的数据
                prices_up_to = tdf.iloc[: t_idx + 1].copy()
                prices_up_to["date"] = pd.to_datetime(prices_up_to["date"], format="%Y%m%d")
                flow_up_to = [r for r in flow_by_ticker.get(ticker, []) if r.date <= today]
                last_pct = float(prices_up_to.iloc[-1].get("pct_change", 0) or 0)
                industry_pct = max(last_pct, 3.0) if last_pct >= 9.5 else last_pct
                ctx = {
                    "prices": prices_up_to,
                    "fund_flow_records": flow_up_to,
                    "industry_day_pct": industry_pct,
                    "regime": "normal",
                }
                result = setup.detect(ticker, today, ctx)
                if not result.hit:
                    continue
                # 次日开盘买入 (× 1+slippage)
                next_open = float(tdf.iloc[t_idx + 1]["open"])
                entry_price = next_open * (1 + _SLIPPAGE)
                positions.append(
                    Position(
                        ticker=ticker,
                        entry_date=today,
                        entry_price=entry_price,
                        size_pct=_POSITION_PCT,
                    )
                )
                new_buys += 1

        nav_curve.append((today, nav))
        peak = max(peak, nav)
        max_dd = min(max_dd, nav / peak - 1)

    # 统计
    n_trades = len(closed)
    n_wins = sum(1 for p in closed if p.pnl_pct > 0)
    result = BacktestResult(
        trades=closed,
        nav_curve=nav_curve,
        final_nav=nav,
        total_return_pct=(nav - 1) * 100,
        win_rate=n_wins / n_trades if n_trades > 0 else 0,
        max_drawdown_pct=max_dd * 100,
        n_trades=n_trades,
        n_wins=n_wins,
    )
    # Sharpe (日 P&L)
    if len(nav_curve) > 1:
        rets = [nav_curve[i][1] / nav_curve[i - 1][1] - 1 for i in range(1, len(nav_curve)) if nav_curve[i - 1][1] > 0]
        if rets and np.std(rets) > 0:
            result.sharpe = np.mean(rets) / np.std(rets) * (252**0.5)
    return result


def main():
    result = run_backtest(n_days=30)
    print("\n" + "=" * 60)
    print("Phase A 30 天历史回测 — BTST T+10 + half-Kelly + 硬止损")
    print("=" * 60)
    print(f"交易数: {result.n_trades}  (盈利 {result.n_wins})")
    print(f"胜率: {result.win_rate:.1%}")
    print(f"总收益: {result.total_return_pct:+.2f}%  (NAV {result.final_nav:.4f})")
    print(f"最大回撤: {result.max_drawdown_pct:+.2f}%")
    print(f"Sharpe (年化): {result.sharpe:.2f}")
    # 退出原因分布
    reasons = {}
    for p in result.trades:
        reasons[p.exit_reason] = reasons.get(p.exit_reason, 0) + 1
    print(f"退出原因: {reasons}")
    # 单笔 P&L 分布
    if result.trades:
        pnls = [p.pnl_pct * 100 for p in result.trades]
        print(f"单笔 P&L: 均 {np.mean(pnls):+.2f}%  中位 {np.median(pnls):+.2f}%  最差 {min(pnls):+.2f}%  最好 {max(pnls):+.2f}%")


if __name__ == "__main__":
    main()
