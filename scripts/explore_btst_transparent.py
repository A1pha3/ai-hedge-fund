"""BTST 选股透明回测 — 披露完整选股/操作/统计过程。

目的: 让 operator 看到 --daily-action 的 BTST T+10 选股
(1) 怎么选 (3 条件逐条过滤)
(2) 怎么操作 (次日开盘买入 + T+10 收盘平 + 滑点 + 涨停买不到剔除)
(3) 怎么算胜率/收益 (execution-adjusted, IS/OOS 分段)

诚实披露:
- 条件3 (行业涨幅>2%) 在回测里近似为 max(pct, 3.0) — 涨停日自动满足
  (与 explore_btst_fullpool.py 同口径, 因 data/ 无逐日行业涨幅源)
- daily_action.py 的 entry_price 用触发日收盘 (偏乐观); 本回测用 execution-adjusted
  (次日开盘 + 滑点 + 涨停剔除), 更接近真实可执行
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

from src.screening.offensive.data.fund_flow_store import FundFlowStore
from src.screening.offensive.execution_adjuster import ExecutionConfig, adjust_returns, is_limit_up_unbuyable_next_day
from src.screening.offensive.setups.btst_breakout import BtstBreakoutSetup

_CANDIDATE_POOL = Path("data/snapshots/candidate_pool_20260527_top300.json")
_PRICE_CACHE = Path("data/price_cache/")
_FUND_FLOW_CACHE = Path("data/fund_flow_cache/")


def _load_prices(ticker: str) -> pd.DataFrame:
    f = _PRICE_CACHE / f"{ticker}.csv"
    if not f.exists():
        return pd.DataFrame()
    df = pd.read_csv(f, dtype={"date": str})
    df["date"] = pd.to_datetime(df["date"])
    return df


def main(verbose: bool = True) -> None:
    # ---- Step 0: 加载候选池 ----
    pool = json.loads(_CANDIDATE_POOL.read_text(encoding="utf-8"))
    all_tickers = [d["ticker"] for d in pool if isinstance(d, dict) and d.get("ticker")]
    store = FundFlowStore(cache_dir=str(_FUND_FLOW_CACHE))

    print("=" * 78)
    print("BTST T+10 选股透明回测 (全池 300 ticker × 2020-2026)")
    print("=" * 78)
    print(f"候选池: {len(all_tickers)} tickers")

    # ---- Step 1: 枚举所有涨停日候选 (条件1预过滤) ----
    # BTST 条件1 要求 pct_change >= 9.5%, 非涨停日必不命中 → 只扫涨停日
    candidate_samples: list[tuple[str, str]] = []  # (ticker, date_str)
    prices_by_ticker: dict[str, pd.DataFrame] = {}
    flow_by_ticker: dict[str, list] = {}
    loaded = 0
    for t in all_tickers:
        prices = _load_prices(t)
        if prices is None or len(prices) == 0:
            continue
        prices_by_ticker[t] = prices
        flow_by_ticker[t] = store.get_range(t, "20200101", "20260706")
        loaded += 1
        limit_up_mask = prices["pct_change"] >= 9.5
        for _, row in prices[limit_up_mask].iterrows():
            candidate_samples.append((t, row["date"].strftime("%Y%m%d")))
    print(f"有数据 ticker: {loaded}/{len(all_tickers)}")
    print(f"Step 1 候选 (涨停日 pct>=9.5%): {len(candidate_samples)} 样本")

    # ---- Step 2: 逐条条件过滤 (透明披露每步剔除数) ----
    btst = BtstBreakoutSetup()
    # 手动跑条件, 统计每条剔除多少
    n_cond1_pass = 0  # 涨停 (已是候选, 全过)
    n_cond2_pass = 0  # 主力净流入 > 0 且 > 20日均值
    n_cond3_pass = 0  # 行业涨幅 > 2% (近似: max(pct,3.0) on 涨停日 → 自动过)
    hits: list[tuple[str, str, float, float, float]] = []  # (ticker, date, pct, flow, ind_pct)
    n_no_price_row = 0
    n_no_flow = 0
    n_flow_le0 = 0
    n_flow_le_mean = 0

    for ticker, date_str in candidate_samples:
        prices = prices_by_ticker.get(ticker)
        if prices is None:
            continue
        row_mask = prices["date"].dt.strftime("%Y%m%d") == date_str
        if not row_mask.any():
            n_no_price_row += 1
            continue
        trigger_row = prices[row_mask].iloc[0]
        pct = float(trigger_row.get("pct_change", 0.0) or 0.0)
        # 条件1 已保证 (候选都是涨停日)
        n_cond1_pass += 1
        # 条件2: 主力净流入
        records = flow_by_ticker.get(ticker, [])
        today_flow = next((r.main_net_inflow for r in records if r.date == date_str), None)
        if today_flow is None:
            n_no_flow += 1
            continue
        if today_flow <= 0:
            n_flow_le0 += 1
            continue
        historical = [r.main_net_inflow for r in records if r.date < date_str]
        if len(historical) >= 5:
            lookback = historical[-20:]
            hist_mean = sum(lookback) / len(lookback)
            if today_flow <= hist_mean:
                n_flow_le_mean += 1
                continue
        n_cond2_pass += 1
        # 条件3: 行业涨幅 (近似, 涨停日自动满足)
        industry_pct = max(pct, 3.0) if pct >= 9.5 else pct
        n_cond3_pass += 1
        hits.append((ticker, date_str, pct, today_flow, industry_pct))

    print(f"\nStep 2 逐条条件过滤:")
    print(f"  条件1 (涨停 >=9.5%): {n_cond1_pass} 通过 (候选已是涨停日)")
    print(f"    └ 无价格行: {n_no_price_row}")
    print(f"  条件2 (主力净流入>0 且>20日均): {n_cond2_pass} 通过")
    print(f"    └ 无资金流数据: {n_no_flow}")
    print(f"    └ 净流入<=0: {n_flow_le0}")
    print(f"    └ 净流入<=20日均: {n_flow_le_mean}")
    print(f"  条件3 (行业涨幅>2%): {n_cond3_pass} 通过 (近似: 涨停日 max(pct,3.0) 自动过)")
    print(f"\n→ BTST 命中: {len(hits)} 样本")

    if not hits:
        print("无命中, 退出")
        return

    # ---- Step 3: execution-adjusted T+10 收益 ----
    hit_tickers = [h[0] for h in hits]
    hit_dates = [h[1] for h in hits]
    config = ExecutionConfig(slippage_bps=30, limit_up_unbuyable=True, t_plus_1_lock=True)
    adj_returns = adjust_returns(hit_dates, hit_tickers, prices_by_ticker, horizon=10, config=config)
    finite_mask = np.isfinite(adj_returns)
    finite_returns = adj_returns[finite_mask]
    n_unbuyable = int((~finite_mask).sum())

    print(f"\nStep 3 execution-adjusted T+10 收益:")
    print(f"  入口价 = 次日开盘 × (1 + 0.3% 滑点)")
    print(f"  出口价 = T+10 收盘 × (1 - 0.3% 滑点)")
    print(f"  涨停次日续涨停 → 剔除 (买不到): {n_unbuyable} 样本")
    print(f"  有效样本: {len(finite_returns)} (n_hits={len(hits)} - unbuyable={n_unbuyable})")

    if len(finite_returns) == 0:
        print("无有效收益, 退出")
        return

    # ---- Step 4: 按年 + IS/OOS 分段统计 ----
    def _stats(returns: np.ndarray) -> dict:
        wins = returns[returns > 0]
        losses = returns[returns <= 0]
        return {
            "n": len(returns),
            "winrate": len(wins) / len(returns) if len(returns) > 0 else 0.0,
            "mean": float(np.mean(returns)),
            "median": float(np.median(returns)),
            "avg_gain": float(np.mean(wins)) if len(wins) > 0 else 0.0,
            "avg_loss": float(np.mean(losses)) if len(losses) > 0 else 0.0,
            "p25": float(np.percentile(returns, 25)),
            "p75": float(np.percentile(returns, 75)),
        }

    # 全量
    all_s = _stats(finite_returns)
    # 按年
    year_returns: dict[str, list[float]] = defaultdict(list)
    for i, ok in enumerate(finite_mask):
        if not ok:
            continue
        d = hit_dates[i]
        yr = d[:4]
        year_returns[yr].append(float(adj_returns[i]))
    # IS / OOS
    is_returns = np.array([r for r, d in zip(finite_returns, [hit_dates[i] for i, m in enumerate(finite_mask) if m]) if d < "20250101"]) if finite_mask.any() else np.array([])
    oos_returns = np.array([r for r, d in zip(finite_returns, [hit_dates[i] for i, m in enumerate(finite_mask) if m]) if d >= "20250101"]) if finite_mask.any() else np.array([])

    print(f"\n{'='*78}")
    print(f"Step 4 统计结果 (T+10 execution-adjusted)")
    print(f"{'='*78}")
    print(f"\n{'时段':<14} {'n':>6} {'胜率':>8} {'均值':>9} {'中位':>9} {'均盈':>9} {'均亏':>9} {'P25':>9} {'P75':>9}")
    print("-" * 92)
    for label, s in [("ALL 全量", all_s)]:
        print(f"{label:<14} {s['n']:>6} {s['winrate']:>7.1%} {s['mean']:>+8.2%} {s['median']:>+8.2%} {s['avg_gain']:>+8.2%} {s['avg_loss']:>+8.2%} {s['p25']:>+8.2%} {s['p75']:>+8.2%}")
    if len(is_returns) > 0:
        s = _stats(is_returns)
        print(f"{'IS (≤2024)':<14} {s['n']:>6} {s['winrate']:>7.1%} {s['mean']:>+8.2%} {s['median']:>+8.2%} {s['avg_gain']:>+8.2%} {s['avg_loss']:>+8.2%} {s['p25']:>+8.2%} {s['p75']:>+8.2%}")
    if len(oos_returns) > 0:
        s = _stats(oos_returns)
        print(f"{'OOS (≥2025)':<14} {s['n']:>6} {s['winrate']:>7.1%} {s['mean']:>+8.2%} {s['median']:>+8.2%} {s['avg_gain']:>+8.2%} {s['avg_loss']:>+8.2%} {s['p25']:>+8.2%} {s['p75']:>+8.2%}")
    print("-" * 92)
    for yr in sorted(year_returns.keys()):
        s = _stats(np.array(year_returns[yr]))
        print(f"{yr:<14} {s['n']:>6} {s['winrate']:>7.1%} {s['mean']:>+8.2%} {s['median']:>+8.2%} {s['avg_gain']:>+8.2%} {s['avg_loss']:>+8.2%} {s['p25']:>+8.2%} {s['p75']:>+8.2%}")

    # ---- Step 5: 命中样本示例 (收益最高10 + 最低10) ----
    print(f"\n{'='*78}")
    print(f"Step 5 命中样本明细 (收益最高10 + 最低10)")
    print(f"{'='*78}")
    print(f"{'ticker':<8} {'触发日':<10} {'涨停%':>6} {'次日开盘':>9} {'T+10收盘':>9} {'调整收益':>9}")
    print("-" * 60)
    valid_idx = [i for i in range(len(hits)) if np.isfinite(adj_returns[i])]
    valid_idx.sort(key=lambda i: adj_returns[i], reverse=True)
    sample_idx = valid_idx[:10] + valid_idx[-10:]
    for i in sample_idx:
        ticker, date_str, pct, flow, ind = hits[i]
        prices = prices_by_ticker[ticker]
        row_mask = prices["date"].dt.strftime("%Y%m%d") == date_str
        tidx = prices[row_mask].index[0]
        next_open = float(prices.iloc[tidx + 1]["open"]) if tidx + 1 < len(prices) else float("nan")
        t10_close = float(prices.iloc[tidx + 10]["close"]) if tidx + 10 < len(prices) else float("nan")
        r = adj_returns[i]
        print(f"{ticker:<8} {date_str:<10} {pct:>5.1f}% {next_open:>9.2f} {t10_close:>9.2f} {r:>+8.2%}")

    # ---- Step 5b: 止损影响对比 (纯T+10收盘 vs 期间触-8%止损) ----
    print(f"\n{'='*78}")
    print(f"Step 5b 止损规则影响: 纯T+10收盘 vs -8%硬止损模拟")
    print(f"{'='*78}")
    stop_returns = []
    for i in valid_idx:
        ticker, date_str = hits[i][0], hits[i][1]
        prices = prices_by_ticker[ticker]
        row_mask = prices["date"].dt.strftime("%Y%m%d") == date_str
        tidx = prices[row_mask].index[0]
        entry_idx = tidx + 1
        exit_idx = tidx + 10
        if entry_idx >= len(prices) or exit_idx >= len(prices):
            continue
        entry_price = float(prices.iloc[entry_idx]["open"]) * (1 + 0.0003)
        stop_line = entry_price * 0.92
        period_low = float(prices.iloc[entry_idx:exit_idx + 1]["low"].min())
        t10_close = float(prices.iloc[exit_idx]["close"]) * (1 - 0.0003)
        pure = (t10_close / entry_price) - 1.0
        if period_low <= stop_line:
            stop_returns.append(-0.08)
        else:
            stop_returns.append(pure)
    stop_arr = np.array(stop_returns)
    if len(stop_arr) > 0:
        s_stop = _stats(stop_arr)
        print(f"\n{'策略':<20} {'n':>6} {'胜率':>8} {'均值':>9} {'中位':>9} {'均亏':>9} {'最差':>9}")
        print("-" * 75)
        print(f"{'纯T+10收盘 (无止损)':<20} {all_s['n']:>6} {all_s['winrate']:>7.1%} {all_s['mean']:>+8.2%} {all_s['median']:>+8.2%} {all_s['avg_loss']:>+8.2%} {float(np.min(finite_returns)):>+8.2%}")
        print(f"{'-8%硬止损模拟':<20} {s_stop['n']:>6} {s_stop['winrate']:>7.1%} {s_stop['mean']:>+8.2%} {s_stop['median']:>+8.2%} {s_stop['avg_loss']:>+8.2%} {float(np.min(stop_arr)):>+8.2%}")
        n_triggered = int((stop_arr == -0.08).sum())
        print(f"\n  期间触-8%止损: {n_triggered}/{len(stop_arr)} ({n_triggered/len(stop_arr):.1%})")
        print(f"  止损把最差单笔从 {float(np.min(finite_returns)):+.2%} 收窄到 {float(np.min(stop_arr)):+.2%}")
        delta = s_stop['mean'] - all_s['mean']
        print(f"  均值从 {all_s['mean']:+.2%} → {s_stop['mean']:+.2%} ({'提升' if delta>0 else '降低'} {abs(delta):.2%})")

    # ---- Step 6: 操作流程总结 ----
    print(f"\n{'='*78}")
    print(f"Step 6 --daily-action 实际操作流程 (从回测口径推导)")
    print(f"{'='*78}")
    print(f"""
选股 (每个交易日对候选池 300 ticker 逐一检测):
  条件1: 当日涨停 (pct_change >= 9.5%)
  条件2: 主力净流入 > 0 且 > 过去20日均值 (需>=5日历史)
  条件3: 所属行业当日涨幅 > 2% (⚠ 回测近似为涨停日自动满足, 无独立行业源)

操作 (次日执行):
  买入: 触发日次日开盘价 × (1+0.3%滑点); 若次日开盘继续涨停 → 放弃 (买不到)
  止损: 触发日收盘 × 0.92 (-8% 硬止损), 盘中触及当日收盘平
  时间退出: T+10 收盘无条件平
  仓位: half-Kelly, 单票 ≤10%, 组合 ≤60%

⚠ 口径差异 (诚实披露):
  - 回测收益 (本表): execution-adjusted, 次日开盘买入, 含滑点+涨停剔除
  - daily_action.py entry_price: 触发日收盘 (偏乐观, 未含次日开盘滑点)
  - 二者差异 = 次日开盘跳空 + 滑点; 回测口径更保守、更接近真实可执行
  - 条件3 行业涨幅: 回测近似 (max(pct,3.0)), 实盘需独立行业数据源
""")


if __name__ == "__main__":
    main()
