"""Exit-strategy backtester — 用真实回测数据对比不同止损/退出策略的表现.

第一性原理验证: 在改 paper_tracker 的止损逻辑前, 必须先用 data/paper_trading_backtest
的历史成交 + data/price_cache 的 OHLCV 数据, 回测各种退出策略的 E[r]/winrate/
最大亏损/Sharpe, 确认优化方向有数据支持 (而不是拍脑袋).

用法:
    uv run python scripts/backtest_exit_strategies.py

输出: 各策略的对比表 (stdout).
"""

from __future__ import annotations

import json
import re
import statistics as st
from pathlib import Path
from typing import Any

import pandas as pd

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_REALIZED_RE = re.compile(r"realized=([+-]?\d+(?:\.\d+)?)%")
_SLIPPAGE = 0.001  # 10 bps (与 ExecutionConfig 一致)


def _load_btst_trades() -> list[dict[str, Any]]:
    """从 backtest journal 加载 BTST BUY+EXIT 配对, 返回 (sigdate, ticker, horizon, orig_ret)."""
    journal = _PROJECT_ROOT / "data/paper_trading_backtest/journal.jsonl"
    if not journal.exists():
        return []
    records = [json.loads(line) for line in journal.read_text(encoding="utf-8").splitlines() if line.strip()]
    realized_by_key: dict[tuple[str, str], float] = {}
    for rec in records:
        if rec.get("action") == "EXIT" and rec.get("setup") == "btst_breakout":
            m = _REALIZED_RE.search(str(rec.get("reasoning", "")))
            if m:
                realized_by_key[(str(rec["date"]), str(rec["ticker"]))] = float(m.group(1)) / 100.0
    trades: list[dict[str, Any]] = []
    for rec in records:
        if rec.get("action") != "BUY" or rec.get("setup") != "btst_breakout":
            continue
        key = (str(rec["date"]), str(rec["ticker"]))
        if key not in realized_by_key:
            continue
        trades.append(
            {
                "sigdate": str(rec["date"]),
                "ticker": str(rec["ticker"]),
                "horizon": int(rec.get("horizon", 10)),
                "orig_ret": realized_by_key[key],
            }
        )
    return trades


def _load_prices(ticker: str) -> pd.DataFrame | None:
    cache = _PROJECT_ROOT / "data" / "price_cache" / f"{ticker}.csv"
    if not cache.exists():
        return None
    df = pd.read_csv(cache, dtype={"date": str})
    df["date_c"] = df["date"].str.replace("-", "", regex=False)
    return df.sort_values("date_c").reset_index(drop=True)


def _compute_atr(prices: pd.DataFrame, period: int = 20) -> float | None:
    """计算 Wilder ATR (委托给共享工具 atr_utils.compute_atr)."""
    from src.screening.offensive.atr_utils import compute_atr

    return compute_atr(prices, period=period)


def _simulate_exit(
    trades: list[dict[str, Any]],
    *,
    stop_mode: str = "none",  # "none" | "fixed_pct" | "atr"
    stop_param: float = 0.08,  # fixed: -0.08; atr: k=2.0
    time_exit: int = 10,
) -> dict[str, float | int]:
    """回测一种退出策略, 返回统计摘要.

    Args:
        stop_mode: "none" (T+N 收盘), "fixed_pct" (固定百分比止损), "atr" (ATR 倍数止损)
        stop_param: fixed_pct → 止损百分比 (如 -0.08); atr → ATR 倍数 (如 2.0)
        time_exit: 时间退出 horizon (交易日)
    """
    returns: list[float] = []
    stop_trig_count = 0
    analyzed = 0

    for trade in trades:
        prices = _load_prices(trade["ticker"])
        if prices is None:
            continue
        matches = prices.index[prices["date_c"] == trade["sigdate"]]
        if len(matches) == 0:
            continue
        sig_idx = int(matches[0])
        entry_idx = sig_idx + 1
        exit_idx = sig_idx + time_exit
        if entry_idx >= len(prices) or exit_idx >= len(prices):
            continue
        entry_open = float(prices.iloc[entry_idx]["open"])
        exit_close = float(prices.iloc[exit_idx]["close"])
        if entry_open <= 0:
            continue
        entry_price = entry_open * (1 + _SLIPPAGE)

        # 确定止损价
        if stop_mode == "fixed_pct":
            stop_price = entry_price * (1 + stop_param)  # stop_param 为负, 如 -0.08
        elif stop_mode == "atr":
            # 用 entry 前的 ATR (不含 entry 日, 避免未来函数)
            pre_entry = prices.iloc[:entry_idx]
            atr = _compute_atr(pre_entry)
            if atr is None or atr <= 0:
                stop_price = None  # ATR 不可算 → 无止损 (降级到时间退出)
            else:
                stop_price = entry_price - stop_param * atr  # stop_param=k, 如 2.0
        else:
            stop_price = None  # no stop

        # 扫描持仓期间每日 low, 触止损就出场
        holding = prices.iloc[entry_idx : exit_idx + 1]
        exited_at_stop = False
        realized_ret = None
        if stop_price is not None:
            for _, row in holding.iterrows():
                low = float(row.get("low", 0) or 0)
                if low <= stop_price and low > 0:
                    realized_ret = (stop_price * (1 - _SLIPPAGE) / entry_price) - 1.0
                    exited_at_stop = True
                    stop_trig_count += 1
                    break
        if realized_ret is None:
            exit_price = exit_close * (1 - _SLIPPAGE)
            realized_ret = (exit_price / entry_price) - 1.0

        returns.append(realized_ret)
        analyzed += 1

    if not returns:
        return {"n": 0, "E": 0.0, "winrate": 0.0, "median": 0.0, "max_loss": 0.0, "big_loss_pct": 0.0, "sharpe": 0.0, "stop_trig": 0}

    wins = [r for r in returns if r > 0]
    big_losses = [r for r in returns if r < -0.10]
    # Sharpe-like: mean / std (年化系数忽略, 仅比较相对)
    sharpe = st.mean(returns) / st.stdev(returns) if len(returns) > 1 and st.stdev(returns) > 0 else 0.0
    return {
        "n": analyzed,
        "E": st.mean(returns),
        "winrate": len(wins) / len(returns),
        "median": st.median(returns),
        "max_loss": min(returns),
        "big_loss_pct": len(big_losses) / len(returns),
        "sharpe": sharpe,
        "stop_trig": stop_trig_count,
    }


def main() -> None:
    trades = _load_btst_trades()
    print(f"=== Exit-Strategy Backtest (BTST, {len(trades)} trades from paper_trading_backtest) ===\n")

    strategies = [
        ("no_stop (T+10 收盘)", {"stop_mode": "none"}),
        ("fixed -5%", {"stop_mode": "fixed_pct", "stop_param": -0.05}),
        ("fixed -8% (当前硬止损)", {"stop_mode": "fixed_pct", "stop_param": -0.08}),
        ("fixed -12%", {"stop_mode": "fixed_pct", "stop_param": -0.12}),
        ("fixed -15%", {"stop_mode": "fixed_pct", "stop_param": -0.15}),
        ("ATR 1.5x", {"stop_mode": "atr", "stop_param": 1.5}),
        ("ATR 2.0x", {"stop_mode": "atr", "stop_param": 2.0}),
        ("ATR 2.5x", {"stop_mode": "atr", "stop_param": 2.5}),
        ("ATR 3.0x", {"stop_mode": "atr", "stop_param": 3.0}),
    ]

    header = f"{'strategy':<28} {'n':>3} {'E[r]':>8} {'win':>5} {'median':>8} {'maxloss':>8} {'big>10%':>7} {'sharpe':>7} {'stops':>5}"
    print(header)
    print("-" * len(header))
    for label, kwargs in strategies:
        r = _simulate_exit(trades, **kwargs)
        if r["n"] == 0:
            print(f"{label:<28} n=0 (no data)")
            continue
        print(
            f"{label:<28} {r['n']:>3} {r['E']*100:>+7.2f}% {r['winrate']*100:>4.0f}% "
            f"{r['median']*100:>+7.2f}% {r['max_loss']*100:>+7.2f}% "
            f"{r['big_loss_pct']*100:>6.0f}% {r['sharpe']:>7.2f} {r['stop_trig']:>5}"
        )

    print("\n=== 关键对比 (决策依据) ===")
    no_stop = _simulate_exit(trades, stop_mode="none")
    fixed_8 = _simulate_exit(trades, stop_mode="fixed_pct", stop_param=-0.08)
    atr_2 = _simulate_exit(trades, stop_mode="atr", stop_param=2.0)
    atr_3 = _simulate_exit(trades, stop_mode="atr", stop_param=3.0)
    print(f"  no_stop:     E={no_stop['E']*100:+.2f}%  max_loss={no_stop['max_loss']*100:+.2f}%  big>10%={no_stop['big_loss_pct']*100:.0f}%  sharpe={no_stop['sharpe']:.2f}")
    print(f"  fixed -8%:   E={fixed_8['E']*100:+.2f}%  max_loss={fixed_8['max_loss']*100:+.2f}%  big>10%={fixed_8['big_loss_pct']*100:.0f}%  sharpe={fixed_8['sharpe']:.2f}")
    print(f"  ATR 2.0x:    E={atr_2['E']*100:+.2f}%  max_loss={atr_2['max_loss']*100:+.2f}%  big>10%={atr_2['big_loss_pct']*100:.0f}%  sharpe={atr_2['sharpe']:.2f}")
    print(f"  ATR 3.0x:    E={atr_3['E']*100:+.2f}%  max_loss={atr_3['max_loss']*100:+.2f}%  big>10%={atr_3['big_loss_pct']*100:.0f}%  sharpe={atr_3['sharpe']:.2f}")
    print()
    best_e = max(no_stop["E"], fixed_8["E"], atr_2["E"], atr_3["E"])
    best_sharpe = max(no_stop["sharpe"], fixed_8["sharpe"], atr_2["sharpe"], atr_3["sharpe"])
    print(f"  最高 E[r]: {best_e*100:+.2f}%  |  最高 Sharpe: {best_sharpe:.2f}")
    print("  (若 ATR 止损的 E[r] 或 Sharpe 优于 no_stop, 则值得集成到 paper_tracker)")


if __name__ == "__main__":
    main()
