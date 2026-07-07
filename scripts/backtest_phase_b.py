"""Phase B 30 天历史回测 — 龙虎榜机构共振 + 主力净流入 vs Phase A (BTST)。

在同一 30 天窗口上运行两个策略并对比 P&L:
- Phase A (BTST T+10): 涨停+主力+行业 → BUY
- Phase B (LHB机构): 龙虎榜机构净买入>0 + 主力净流入>0 → BUY

目标: Phase B 的 edge 是否 > Phase A?
"""
from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pandas as pd

logging.basicConfig(level=logging.WARNING, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger(__name__)

_POSITION_PCT = 0.10
_MAX_POSITIONS = 6
_HARD_STOP = -0.08
_SLIPPAGE = 0.003
_HORIZON = 10

# Phase B LHB 缓存
_LHB_CACHE_DIR = Path("data/lhb_cache/")


def _ensure_lhb_backfill(entry_days: list[str]):
    """确保 entry_days 的龙虎榜数据已缓存。"""
    import tushare as ts, os
    from pathlib import Path

    token = ""
    if os.path.exists(".env"):
        for l in open(".env").read().splitlines():
            if l.startswith("TUSHARE_TOKEN="):
                token = l.split("=", 1)[1].strip().strip("'\"")
    ts.set_token(token)
    pro = ts.pro_api()

    _LHB_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    for d in entry_days:
        cf = _LHB_CACHE_DIR / f"{d}.csv"
        if cf.exists():
            continue
        try:
            raw = pro.top_inst(trade_date=d)
            if raw is not None and len(raw) > 0:
                raw.to_csv(cf, index=False)
            import time

            time.sleep(0.2)
        except Exception:
            pass
    print(f"[LHB] backfill done: {sum(1 for f in _LHB_CACHE_DIR.iterdir())} days cached")


def _load_lhb_inst_net_buy(trade_date: str) -> dict[str, float]:
    """加载某日龙虎榜机构净买入 {ts_code: net_buy(元)}。"""
    cf = _LHB_CACHE_DIR / f"{trade_date}.csv"
    if not cf.exists():
        return {}
    df = pd.read_csv(cf)
    if len(df) == 0:
        return {}
    inst = df[df["exalter"] == "机构专用"]
    if len(inst) == 0:
        return {}
    _W = 10_000.0
    agg = inst.groupby("ts_code")["net_buy"].sum()
    ts_to_ticker = {}
    for tsc, nb in agg.items():
        ticker = tsc.split(".")[0]
        ts_to_ticker[ticker] = float(nb) * _W
    return ts_to_ticker


def _load_prices_all() -> dict[str, pd.DataFrame]:
    """加载 cached 价格。"""
    prices: dict[str, pd.DataFrame] = {}
    for pf in Path("data/price_cache/").glob("*.csv"):
        df = pd.read_csv(pf, dtype={"date": str})
        df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y%m%d")
        prices[pf.stem] = df.sort_values("date").reset_index(drop=True)
    return prices


def _load_fund_flow_all() -> dict[str, list]:
    """加载 cached 资金流。"""
    from src.screening.offensive.data.fund_flow_store import FundFlowRecord

    flow: dict[str, list] = {}
    for ff in Path("data/fund_flow_cache/").glob("*.csv"):
        t = ff.stem
        df = pd.read_csv(ff, dtype={"date": str})
        flow[t] = [
            FundFlowRecord(
                ticker=t, date=str(r["date"]),
                close=float(r.get("close", 0) or 0),
                pct_change=float(r.get("pct_change", 0) or 0),
                main_net_inflow=float(r.get("main_net_inflow", 0) or 0),
                main_net_pct=float(r.get("main_net_pct", 0) or 0),
            )
            for _, r in df.iterrows()
        ]
    return flow


def run_backtest_pb(
    entry_days: list[str],
    trading_days: list[str],
    prices_by_ticker: dict[str, pd.DataFrame],
    flow_by_ticker: dict[str, list],
    use_lhb: bool = False,
) -> dict:
    """通用回测: use_lhb=True → Phase B (机构), False → Phase A (BTST)。

    返回 stats dict (total_return, win_rate, max_dd, sharpe, n_trades, exit_reasons)。
    """
    from src.screening.offensive.setups.btst_breakout import BtstBreakoutSetup

    setup = BtstBreakoutSetup() if not use_lhb else None
    nav = 1.0
    positions: list = []
    closed: list = []
    nav_curve: list[tuple[str, float]] = []
    peak = 1.0
    max_dd = 0.0
    entry_set = set(entry_days)

    for d_idx, today in enumerate(trading_days):
        # 出场
        still_open = []
        for pos in positions:
            tdf = prices_by_ticker.get(pos["ticker"])
            if tdf is None:
                continue
            row = tdf[tdf["date"] == today]
            if len(row) == 0:
                still_open.append(pos)
                continue
            low = float(row.iloc[0]["low"])
            close = float(row.iloc[0]["close"])
            pos["days_held"] += 1
            stop_price = pos["entry_price"] * (1 + _HARD_STOP)
            if low <= stop_price:
                pos["exit_date"] = today
                pos["exit_price"] = stop_price * (1 - _SLIPPAGE)
                pos["exit_reason"] = "hard_stop"
                trade_ret = (pos["exit_price"] / pos["entry_price"]) - 1
                pos["pnl_pct"] = pos["size_pct"] * trade_ret
                nav *= (1 + pos["pnl_pct"])
                closed.append(pos)
                continue
            if pos["days_held"] >= _HORIZON:
                pos["exit_date"] = today
                pos["exit_price"] = close * (1 - _SLIPPAGE)
                pos["exit_reason"] = "time_exit"
                trade_ret = (pos["exit_price"] / pos["entry_price"]) - 1
                pos["pnl_pct"] = pos["size_pct"] * trade_ret
                nav *= (1 + pos["pnl_pct"])
                closed.append(pos)
                continue
            still_open.append(pos)
        positions = still_open

        # 入场
        if today in entry_set and len(positions) < _MAX_POSITIONS:
            slots = _MAX_POSITIONS - len(positions)
            new_buys = 0

            if use_lhb:
                # Phase B: 龙虎榜机构净买入 > 0 + 主力净流入 > 0
                inst_buys = _load_lhb_inst_net_buy(today)
                for ticker, nb in sorted(inst_buys.items(), key=lambda kv: -abs(kv[1])):
                    if new_buys >= slots:
                        break
                    if any(p["ticker"] == ticker for p in positions):
                        continue
                    if nb <= 0:
                        continue
                    tdf = prices_by_ticker.get(ticker)
                    if tdf is None:
                        continue
                    row_idx = tdf.index[tdf["date"] == today].tolist()
                    if not row_idx or row_idx[0] + 1 >= len(tdf):
                        continue
                    # 主力净流入 > 0
                    flow_recs = flow_by_ticker.get(ticker, [])
                    today_flow = next((r.main_net_inflow for r in flow_recs if r.date == today), 0)
                    if today_flow <= 0:
                        continue
                    next_open = float(tdf.iloc[row_idx[0] + 1]["open"])
                    entry_price = next_open * (1 + _SLIPPAGE)
                    positions.append({
                        "ticker": ticker, "entry_date": today,
                        "entry_price": entry_price, "size_pct": _POSITION_PCT,
                        "days_held": 0, "pnl_pct": 0.0,
                    })
                    new_buys += 1

            else:
                # Phase A: BTST detect
                for ticker, tdf in prices_by_ticker.items():
                    if new_buys >= slots:
                        break
                    if any(p["ticker"] == ticker for p in positions):
                        continue
                    row_idx = tdf.index[tdf["date"] == today].tolist()
                    if not row_idx or row_idx[0] + 1 >= len(tdf):
                        continue
                    ti = row_idx[0]
                    p_up = tdf.iloc[: ti + 1].copy()
                    p_up["date"] = pd.to_datetime(p_up["date"], format="%Y%m%d")
                    f_up = [r for r in flow_by_ticker.get(ticker, []) if r.date <= today]
                    last_pct = float(p_up.iloc[-1].get("pct_change", 0) or 0)
                    ind_pct = max(last_pct, 3.0) if last_pct >= 9.5 else last_pct
                    ctx = {"prices": p_up, "fund_flow_records": f_up, "industry_day_pct": ind_pct, "regime": "normal"}
                    if setup.detect(ticker, today, ctx).hit:
                        next_open = float(tdf.iloc[ti + 1]["open"])
                        entry_price = next_open * (1 + _SLIPPAGE)
                        positions.append({
                            "ticker": ticker, "entry_date": today,
                            "entry_price": entry_price, "size_pct": _POSITION_PCT,
                            "days_held": 0, "pnl_pct": 0.0,
                        })
                        new_buys += 1

        nav_curve.append((today, nav))
        peak = max(peak, nav)
        max_dd = min(max_dd, nav / peak - 1)

    n_trades = len(closed)
    n_wins = sum(1 for p in closed if p["pnl_pct"] > 0)
    rets = [nav_curve[i][1] / nav_curve[i - 1][1] - 1 for i in range(1, len(nav_curve)) if nav_curve[i - 1][1] > 0]
    sharpe = 0.0
    if rets and np.std(rets) > 0:
        sharpe = float(np.mean(rets) / np.std(rets) * (252 ** 0.5))
    reasons = {}
    for p in closed:
        reasons[p["exit_reason"]] = reasons.get(p["exit_reason"], 0) + 1
    pnls = [p["pnl_pct"] * 100 for p in closed]
    return {
        "nav": nav, "total_return": (nav - 1) * 100,
        "win_rate": n_wins / n_trades if n_trades > 0 else 0,
        "max_dd": max_dd * 100, "sharpe": sharpe,
        "n_trades": n_trades, "n_wins": n_wins,
        "exit_reasons": reasons,
        "avg_pnl": np.mean(pnls) if pnls else 0,
        "median_pnl": np.median(pnls) if pnls else 0,
        "best_pnl": max(pnls) if pnls else 0,
        "worst_pnl": min(pnls) if pnls else 0,
    }


def main():
    prices_by_ticker = _load_prices_all()
    flow_by_ticker = _load_fund_flow_all()
    # 交易日历
    all_dates = sorted(set(
        d for tdf in prices_by_ticker.values() for d in tdf["date"].tolist()
    ))
    end_idx = len(all_dates) - _HORIZON
    start_idx = end_idx - 30
    entry_days = all_dates[start_idx:end_idx]
    trading_all = all_dates[start_idx:]

    print(f"窗口: {entry_days[0]} → {entry_days[-1]} ({len(entry_days)} 入场日)")
    print(f"总交易日 (含成熟): {len(trading_all)}")

    # 确保 LHB 数据已 backfill
    _ensure_lhb_backfill(entry_days)

    # Phase A (BTST)
    result_a = run_backtest_pb(entry_days, trading_all, prices_by_ticker, flow_by_ticker, use_lhb=False)
    # Phase B (LHB 机构)
    result_b = run_backtest_pb(entry_days, trading_all, prices_by_ticker, flow_by_ticker, use_lhb=True)

    print("\n" + "=" * 60)
    print("Phase A vs Phase B — 30 天同窗口回测")
    print("=" * 60)
    headers = ["指标", "Phase A (BTST)", "Phase B (LHB机构)"]
    rows = [
        ("交易数", f"{result_a['n_trades']}", f"{result_b['n_trades']}"),
        ("胜率", f"{result_a['win_rate']:.1%}", f"{result_b['win_rate']:.1%}"),
        ("总收益", f"{result_a['total_return']:+.2f}%", f"{result_b['total_return']:+.2f}%"),
        ("最大回撤", f"{result_a['max_dd']:+.2f}%", f"{result_b['max_dd']:+.2f}%"),
        ("Sharpe", f"{result_a['sharpe']:.2f}", f"{result_b['sharpe']:.2f}"),
        ("均值 P&L", f"{result_a['avg_pnl']:+.2f}%", f"{result_b['avg_pnl']:+.2f}%"),
        ("中位 P&L", f"{result_a['median_pnl']:+.2f}%", f"{result_b['median_pnl']:+.2f}%"),
        ("最好", f"{result_a['best_pnl']:+.2f}%", f"{result_b['best_pnl']:+.2f}%"),
        ("最差", f"{result_a['worst_pnl']:+.2f}%", f"{result_b['worst_pnl']:+.2f}%"),
        ("退出", f"{result_a['exit_reasons']}", f"{result_b['exit_reasons']}"),
    ]
    for h in headers:
        print(f"  {h:<20}", end="")
    print()
    print("  " + "-" * 60)
    for label, va, vb in rows:
        print(f"  {label:<15}  {va:<18}  {vb:<18}")

    # 推荐
    if result_b["total_return"] > result_a["total_return"]:
        print(f"\n✅ Phase B (LHB) 总收益更高 → 进 Phase B 继续深耕 龙虎榜 + 北向")
    else:
        print(f"\n⚠ Phase A (BTST) 更好或接近 → 继续巩固 A，B 降到次要")
    print(f"\nPhase B 同窗口收益 {result_b['total_return']:+.2f}% vs Phase A {result_a['total_return']:+.2f}%")


if __name__ == "__main__":
    main()
