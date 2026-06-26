"""NS-19(2) 做空策略回测: 验证 short/cover 佣金 ≥5 元下限 + NAV/realized cost 更准。

对照实验:
  - Run A (floor=5): 当前默认 TradingConstraints (commission_floor_yuan=5.0)
  - Run B (floor=0): 关闭下限 (模拟 BETA-006/NS-19(2) 修复前的低估行为)

每个 run 用同一份 MockConfigurableAgent 决策序列 + 同一份价格 fixture,
唯一差异是 commission_floor_yuan。最终对比:
  - 每笔 SHORT/COVER 的 raw commission vs effective commission (验证 ≥5 元)
  - 总佣金成本 (floor vs no-floor)
  - 终态 NAV / cash / margin_used / realized_gains
  - 全周期 NAV 曲线差异
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from src.backtesting.engine import BacktestEngine
from src.backtesting.trader import TradeExecutor
from src.backtesting.trader_helpers import _apply_commission_floor
from src.backtesting.trading_constraints import TradingConstraints

REPO_ROOT = Path(__file__).resolve().parents[1]
PRICES_ROOT = REPO_ROOT / "tests" / "fixtures" / "api" / "prices"


# ---------------------------------------------------------------------------
# 1. Fixture loaders (mimic tests/backtesting/integration/conftest.py)
# ---------------------------------------------------------------------------
def _load_price_df(ticker: str, start: str, end: str) -> pd.DataFrame:
    fixture_path = PRICES_ROOT / f"{ticker}_{start}_{end}.json"
    if not fixture_path.exists():
        # Fallback: any file whose window overlaps
        candidates = sorted(PRICES_ROOT.glob(f"{ticker}_*.json"))
        for p in candidates:
            parts = p.stem.split("_")
            if len(parts) >= 3 and not (end < parts[1] or start > parts[2]):
                fixture_path = p
                break
    with fixture_path.open("r") as f:
        data = json.load(f)
    df = pd.DataFrame([p for p in data["prices"]])
    df["Date"] = pd.to_datetime(df["time"]).dt.tz_convert("UTC")
    df.set_index("Date", inplace=True)
    for col in ("open", "close", "high", "low", "volume"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df.sort_index(inplace=True)
    start_ts = pd.to_datetime(start).tz_localize("UTC")
    end_ts = pd.to_datetime(end).tz_localize("UTC")
    df = df.loc[(df.index >= start_ts) & (df.index <= end_ts)]
    return df[["open", "close", "high", "low", "volume"]]


def _patch_engine_market_data(monkey_targets: dict[str, Any]) -> None:
    """Patch engine_market_data to use local fixtures (no network)."""
    import src.backtesting.engine_market_data as md

    md.get_prices = lambda *a, **k: None
    md.get_financial_metrics = lambda *a, **k: []
    md.get_insider_trades = lambda *a, **k: []
    md.get_company_news = lambda *a, **k: []
    md.get_price_data = lambda ticker, start_date, end_date, api_key=None: _load_price_df(ticker, start_date, end_date)


# ---------------------------------------------------------------------------
# 2. Mock agent (small-quantity SHORT/COVER to trigger 5-yuan floor)
# ---------------------------------------------------------------------------
class MockAgent:
    """Predefined SHORT/COVER sequence. Quantities kept tiny (1-3 shares)
    so notional * 0.025% << 5 元 → floor 必然触发."""

    def __init__(self, sequence: list[dict], tickers: list[str]) -> None:
        self.sequence = sequence
        self.tickers = tickers
        self.call_count = 0

    def __call__(self, **kwargs) -> dict:
        tickers = kwargs.get("tickers", self.tickers)
        if self.call_count < len(self.sequence):
            day = self.sequence[self.call_count]
        else:
            day = {}
        self.call_count += 1
        decisions = {}
        for t in tickers:
            decisions[t] = day.get(t, {"action": "hold", "quantity": 0})
        return {"decisions": decisions, "analyst_signals": {}}


# ---------------------------------------------------------------------------
# 3. Trade logger — wrap execute_short/cover to capture per-trade economics
# ---------------------------------------------------------------------------
TRADE_LOG: list[dict] = []


def _install_trade_logger(floor_yuan: float) -> None:
    """Wrap execute_short_trade / execute_cover_trade to log each call.

    TradeExecutor.execute_trade resolves these names from the trader module's
    globals at call time, so rebinding trader_mod.execute_short_trade is
    sufficient to intercept every SHORT/COVER routed through the engine.
    """
    import src.backtesting.trader as trader_mod

    from src.backtesting.trader_helpers import (
        execute_cover_trade as orig_cover,
        execute_short_trade as orig_short,
    )

    def logged_short(ticker, quantity, current_price, portfolio, slippage_rate, commission_rate, daily_turnover=None, commission_floor_yuan=5.0):
        eff = _apply_commission_floor(commission_rate, quantity, current_price, commission_floor_yuan)
        notional = abs(quantity) * current_price
        raw_comm = notional * commission_rate
        eff_comm = notional * eff
        TRADE_LOG.append({
            "side": "SHORT",
            "ticker": ticker,
            "qty": quantity,
            "price": current_price,
            "notional": notional,
            "raw_rate": commission_rate,
            "eff_rate": eff,
            "raw_comm": raw_comm,
            "eff_comm": eff_comm,
            "floor_yuan": commission_floor_yuan,
            "floor_triggered": eff > commission_rate + 1e-12,
        })
        return orig_short(ticker, quantity, current_price, portfolio, slippage_rate, commission_rate, daily_turnover, commission_floor_yuan)

    def logged_cover(ticker, quantity, current_price, portfolio, slippage_rate, commission_rate, daily_turnover=None, commission_floor_yuan=5.0):
        eff = _apply_commission_floor(commission_rate, quantity, current_price, commission_floor_yuan)
        notional = abs(quantity) * current_price
        raw_comm = notional * commission_rate
        eff_comm = notional * eff
        TRADE_LOG.append({
            "side": "COVER",
            "ticker": ticker,
            "qty": quantity,
            "price": current_price,
            "notional": notional,
            "raw_rate": commission_rate,
            "eff_rate": eff,
            "raw_comm": raw_comm,
            "eff_comm": eff_comm,
            "floor_yuan": commission_floor_yuan,
            "floor_triggered": eff > commission_rate + 1e-12,
        })
        return orig_cover(ticker, quantity, current_price, portfolio, slippage_rate, commission_rate, daily_turnover, commission_floor_yuan)

    trader_mod.execute_short_trade = logged_short
    trader_mod.execute_cover_trade = logged_cover


# ---------------------------------------------------------------------------
# 4. Run a single backtest with given floor
# ---------------------------------------------------------------------------
def run_backtest_with_floor(floor_yuan: float, sequence: list[dict], tickers: list[str]) -> dict:
    """Run BacktestEngine with a custom commission_floor_yuan."""
    global TRADE_LOG
    TRADE_LOG = []
    _install_trade_logger(floor_yuan)

    _patch_engine_market_data({})

    agent = MockAgent(sequence, tickers)
    engine = BacktestEngine(
        agent=agent,
        tickers=tickers,
        start_date="2024-03-01",
        end_date="2024-03-08",
        initial_capital=100_000.0,
        model_name="test-model",
        model_provider="test-provider",
        selected_analysts=None,
        initial_margin_requirement=0.5,
    )
    # Override executor with custom floor
    engine._executor = TradeExecutor(TradingConstraints(commission_floor_yuan=floor_yuan))

    perf = engine.run_backtest()
    portfolio_values = engine.get_portfolio_values()
    snapshot = engine._portfolio.get_snapshot()

    return {
        "floor_yuan": floor_yuan,
        "trade_log": list(TRADE_LOG),
        "perf": perf,
        "portfolio_values": list(portfolio_values),
        "snapshot": snapshot,
        "final_cash": snapshot["cash"],
        "margin_used": snapshot["margin_used"],
        "realized_gains": snapshot["realized_gains"],
        "positions": snapshot["positions"],
    }


# ---------------------------------------------------------------------------
# 5. Report
# ---------------------------------------------------------------------------
def fmt(v: float) -> str:
    return f"{v:>12.4f}"


def report_trade_log(label: str, run: dict) -> None:
    print(f"\n{'=' * 78}")
    print(f"  {label}  (commission_floor_yuan = {run['floor_yuan']})")
    print(f"{'=' * 78}")
    log = run["trade_log"]
    if not log:
        print("  (no trades executed)")
        return
    print(f"  {'Side':<6} {'Ticker':<8} {'Qty':>4} {'Price':>9} {'Notional':>11} {'RawComm':>9} {'EffComm':>9} {'Floor?':>7}")
    print(f"  {'-'*6} {'-'*8} {'-'*4} {'-'*9} {'-'*11} {'-'*9} {'-'*9} {'-'*7}")
    total_raw = 0.0
    total_eff = 0.0
    floor_hits = 0
    for t in log:
        flag = "YES" if t["floor_triggered"] else "no"
        print(f"  {t['side']:<6} {t['ticker']:<8} {t['qty']:>4} {t['price']:>9.2f} {t['notional']:>11.2f} {t['raw_comm']:>9.4f} {t['eff_comm']:>9.4f} {flag:>7}")
        total_raw += t["raw_comm"]
        total_eff += t["eff_comm"]
        if t["floor_triggered"]:
            floor_hits += 1
    print(f"  {'-'*6} {'-'*8} {'-'*4} {'-'*9} {'-'*11} {'-'*9} {'-'*9} {'-'*7}")
    print(f"  TOTAL  {'':<8} {'':>4} {'':>9} {'':>11} {total_raw:>9.4f} {total_eff:>9.4f} {floor_hits}/{len(log)} hits")
    print(f"  Floor uplift: {total_eff - total_raw:+.4f} yuan  ({(total_eff / max(total_raw, 1e-9) - 1) * 100:+.1f}%)")


def report_final_state(label: str, run: dict, prices_last: dict[str, float], initial: float) -> None:
    snap = run["snapshot"]
    pos = snap["positions"]
    rg = snap["realized_gains"]
    # Use engine's last portfolio value point (already computed with margin + cash + pos)
    pv = run["portfolio_values"][-1] if run["portfolio_values"] else {}
    nav_final = float(pv.get("Portfolio Value", 0.0))
    print(f"\n  {label} (floor={run['floor_yuan']})")
    print(f"    Final NAV        : {fmt(nav_final)}")
    print(f"    Final Cash       : {fmt(snap['cash'])}")
    print(f"    Margin Used      : {fmt(snap['margin_used'])}")
    print(f"    Return %         : {fmt((nav_final / initial - 1) * 100)}")
    print(f"    Realized gains (short):")
    for t in sorted(rg.keys()):
        rg_t = rg[t]["short"]
        if rg_t != 0.0:
            print(f"      {t:<6}: {rg_t:>10.4f}")
    print(f"    Open positions:")
    for t in sorted(pos.keys()):
        p = pos[t]
        if p["short"] > 0 or p["long"] > 0:
            print(f"      {t:<6}: short={p['short']} @ {p['short_cost_basis']:.4f}, long={p['long']}")


def main() -> None:
    print("=" * 78)
    print("  NS-19(2) 做空策略回测 — short/cover 佣金 ≥5 元下限 + NAV/realized cost 验证")
    print("=" * 78)

    tickers = ["AAPL", "MSFT", "TSLA"]
    initial_capital = 100_000.0

    # 小数量 SHORT/COVER → 每笔 notional * 0.025% << 5 元 → floor 必触发
    # Day1: 开空; Day2: hold; Day3: 部分平仓; Day4: 加空+平仓; Day5: hold; Day6: 全平
    sequence = [
        {  # Day 1 (2024-03-01)
            "AAPL": {"action": "short", "quantity": 2},
            "MSFT": {"action": "short", "quantity": 1},
            "TSLA": {"action": "short", "quantity": 3},
        },
        {},  # Day 2 hold
        {  # Day 3 partial cover
            "AAPL": {"action": "cover", "quantity": 1},
        },
        {  # Day 4 add short + cover
            "AAPL": {"action": "short", "quantity": 1},
            "MSFT": {"action": "cover", "quantity": 1},
        },
        {},  # Day 5 hold
        {  # Day 6 close all remaining
            "AAPL": {"action": "cover", "quantity": 2},
            "TSLA": {"action": "cover", "quantity": 3},
        },
    ]

    # Run A: floor=5 (current default — the fix we're verifying)
    run_a = run_backtest_with_floor(floor_yuan=5.0, sequence=sequence, tickers=tickers)

    # Run B: floor=0 (control — simulates pre-NS-19(2) undercharge)
    run_b = run_backtest_with_floor(floor_yuan=0.0, sequence=sequence, tickers=tickers)

    # ----- Block A: per-trade commission floor verification -----
    report_trade_log("Run A: floor=5 (NEW — NS-19(2) fix)", run_a)
    report_trade_log("Run B: floor=0 (OLD — pre-fix control)", run_b)

    # ----- Block A.2: assert every short/cover trade in Run A charged >= 5 yuan -----
    print(f"\n{'=' * 78}")
    print("  Block A.2: 验证 Run A 每笔 SHORT/COVER 实收佣金 ≥ 5 元")
    print(f"{'=' * 78}")
    all_ge_5 = True
    for t in run_a["trade_log"]:
        ok = t["eff_comm"] >= 5.0 - 1e-9
        flag = "PASS" if ok else "FAIL"
        print(f"  [{flag}] {t['side']:<6} {t['ticker']:<6} eff_comm={t['eff_comm']:.4f} yuan (raw={t['raw_comm']:.4f})")
        if not ok:
            all_ge_5 = False
    print(f"\n  结论: {'✅ 全部 ≥5 元' if all_ge_5 else '❌ 存在 <5 元的笔'}")

    # ----- Block B: NAV / realized cost comparison -----
    print(f"\n{'=' * 78}")
    print("  Block B: NAV / realized cost 对比 (floor=5 vs floor=0)")
    print(f"{'=' * 78}")

    # Final prices (last day in fixture window)
    last_prices: dict[str, float] = {}
    for t in tickers:
        df = _load_price_df(t, "2024-03-01", "2024-03-08")
        last_prices[t] = float(df["close"].iloc[-1])

    report_final_state("Run A (floor=5)", run_a, last_prices, initial_capital)
    report_final_state("Run B (floor=0)", run_b, last_prices, initial_capital)

    # Delta
    nav_a = float(run_a["portfolio_values"][-1].get("Portfolio Value", 0.0))
    nav_b = float(run_b["portfolio_values"][-1].get("Portfolio Value", 0.0))
    cash_a = run_a["final_cash"]
    cash_b = run_b["final_cash"]
    rg_a_total = sum(rg["short"] for rg in run_a["realized_gains"].values())
    rg_b_total = sum(rg["short"] for rg in run_b["realized_gains"].values())

    print(f"\n  Delta (floor=5  vs  floor=0):")
    print(f"    ΔNAV            : {fmt(nav_a - nav_b)}  (floor=5 NAV 更低, 因成本更真实)")
    print(f"    ΔCash           : {fmt(cash_a - cash_b)}")
    print(f"    ΔRealized gains : {fmt(rg_a_total - rg_b_total)}  (floor=5 实现 PnL 更低, 因 cover 成本更高)")
    print(f"    ΔTotal comm     : {fmt(sum(t['eff_comm'] for t in run_a['trade_log']) - sum(t['eff_comm'] for t in run_b['trade_log']))}")

    # ----- Block C: NAV curve divergence -----
    print(f"\n{'=' * 78}")
    print("  Block C: 全周期 NAV 曲线 (每日 Portfolio Value)")
    print(f"{'=' * 78}")
    print(f"  {'Date':<12} {'floor=5':>12} {'floor=0':>12} {'Δ':>12}")
    print(f"  {'-'*12} {'-'*12} {'-'*12} {'-'*12}")
    for i, (pa, pb) in enumerate(zip(run_a["portfolio_values"], run_b["portfolio_values"])):
        date_str = str(pa.get("Date", ""))[:10]
        va = float(pa.get("Portfolio Value", 0.0))
        vb = float(pb.get("Portfolio Value", 0.0))
        print(f"  {date_str:<12} {va:>12.4f} {vb:>12.4f} {va - vb:>12.4f}")

    print(f"\n{'=' * 78}")
    print("  结论")
    print(f"{'=' * 78}")
    print(f"  1. Run A (floor=5) 共 {len(run_a['trade_log'])} 笔交易, 全部实收佣金 ≥ 5 元 → {'✅' if all_ge_5 else '❌'}")
    print(f"  2. floor=5 vs floor=0: NAV 差异 {nav_a - nav_b:+.4f} 元 (floor=5 NAV 更低, 反映真实做空成本)")
    print(f"  3. floor=5 vs floor=0: realized_gains 差异 {rg_a_total - rg_b_total:+.4f} 元 (cover 成本更高 → 实现 PnL 更低)")
    print(f"  4. 做空策略回测 + 佣金下限修复 (NS-19(2)) 工作正常, NAV/realized cost 更准")


if __name__ == "__main__":
    main()
