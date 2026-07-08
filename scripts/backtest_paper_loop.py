"""paper trading 闭环回测 — 快速版 (预加载数据, 绕过 generate_daily_action 的重复初始化).

验证目标: close_matured 平仓 + drawdown 熔断 + 实际 P&L vs Phase 0 预期.
"""
from __future__ import annotations

import json
import logging
import shutil
from collections import defaultdict
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

_PRICE_CACHE = Path("data/price_cache")
_FUND_FLOW_CACHE = Path("data/fund_flow_cache")


def _load_all_prices() -> dict[str, pd.DataFrame]:
    prices = {}
    for f in _PRICE_CACHE.glob("*.csv"):
        df = pd.read_csv(f, dtype={"date": str})
        if "close" in df.columns and len(df) > 60:
            df["date_str"] = df["date"].str.replace("-", "", regex=False)
            df["date"] = pd.to_datetime(df["date"])
            prices[f.stem] = df
    return prices


def _load_all_fund_flow() -> dict[str, list]:
    from src.screening.offensive.data.fund_flow_store import FundFlowStore

    store = FundFlowStore(cache_dir=str(_FUND_FLOW_CACHE))
    ff = {}
    for ticker in _PRICE_CACHE.glob("*.csv"):
        t = ticker.stem
        try:
            ff[t] = store.get_range(t, "20200101", "20260707")
        except Exception:
            ff[t] = []
    return ff


def _get_trading_days(prices_by: dict[str, pd.DataFrame], start: str, end: str) -> list[str]:
    all_dates: set[str] = set()
    for df in prices_by.values():
        ds = df[(df["date_str"] >= start) & (df["date_str"] <= end)]["date_str"]
        all_dates.update(ds)
    return sorted(all_dates)


def _make_offline_fetcher(prices_by: dict[str, pd.DataFrame]):
    """fetch_actual_returns 的离线替代."""

    def fetcher(ticker: str, start_date: str, end_date: str) -> list[dict]:
        df = prices_by.get(ticker)
        if df is None:
            return []
        start = start_date.replace("-", "")
        end = end_date.replace("-", "")
        mask = (df["date_str"] >= start) & (df["date_str"] <= end)
        sub = df[mask].sort_values("date_str")
        return [
            {"time": str(row["date_str"]), "close": float(row["close"])}
            for _, row in sub.iterrows()
        ]

    return fetcher


def _resolve_industry_day_pct(
    ticker: str,
    trade_date: str,
    *,
    ticker_to_industry: dict[str, str],
    industry_day_pct: dict[tuple[str, str], float],
) -> float:
    industry = ticker_to_industry.get(ticker, "")
    if not industry:
        return 0.0
    return float(industry_day_pct.get((industry, trade_date), 0.0) or 0.0)


def backtest_paper_loop(
    start_date: str = "20260101",
    end_date: str = "20260706",
) -> dict:
    """回测 paper trading 闭环 (快速版)."""
    from src.screening.offensive.kelly import compute_kelly_size
    from src.screening.offensive.known_distributions import get_known_distribution
    from src.screening.offensive.paper_tracker import PaperTracker
    from src.screening.offensive.risk_framework import build_risk_plan
    from src.screening.offensive.setups.btst_breakout import BtstBreakoutSetup
    from src.screening.offensive.setups.oversold_bounce import OversoldBounceSetup

    print("预加载数据...")
    prices_by = _load_all_prices()
    fund_flow_by = _load_all_fund_flow()
    trading_days = _get_trading_days(prices_by, start_date, end_date)
    print(f"  价格: {len(prices_by)} ticker, 资金流: {len(fund_flow_by)}, 交易日: {len(trading_days)}")
    from scripts.setup_research import load_industry_day_pct
    from src.screening.offensive.daily_action import _load_ticker_to_industry_from_snapshots

    ticker_to_industry = _load_ticker_to_industry_from_snapshots(list(prices_by))
    industry_day_pct = load_industry_day_pct()

    # 预加载 regime + ST
    regime_path = Path("data/reports/regime_history.json")
    regimes = json.loads(regime_path.read_text(encoding="utf-8")) if regime_path.exists() else {}

    # setup + 分布
    setups = [
        ("btst_breakout", BtstBreakoutSetup(), 10, get_known_distribution("btst_breakout", 10)),
        ("oversold_bounce", OversoldBounceSetup(), 5, get_known_distribution("oversold_bounce", 5)),
    ]

    # 临时 journal
    tmp_dir = Path("data/paper_trading_backtest")
    if tmp_dir.exists():
        shutil.rmtree(tmp_dir)
    tmp_dir.mkdir(parents=True)
    tracker = PaperTracker(journal_dir=str(tmp_dir))
    fetcher = _make_offline_fetcher(prices_by)

    MAX_POS_PCT = 0.10
    MAX_PORTFOLIO_PCT = 0.60

    for i, trade_date in enumerate(trading_days):
        regime = regimes.get(trade_date, "normal")

        # 1. close_matured (平到期仓 + 回填 P&L → 驱动 drawdown)
        tracker.close_matured(trade_date, use_data_fetcher=fetcher, price_loader=None)

        # 2. drawdown 熔断
        dd_action = tracker.drawdown_action()
        if dd_action == "liquidate":
            continue

        # 3. 扫描新信号
        portfolio_used = 0.0
        for ticker, df in prices_by.items():
            rows = df[df["date_str"] == trade_date]
            if len(rows) == 0:
                continue
            pos = df.index.get_loc(rows.index[0])
            last_row = df.iloc[pos]
            pct = float(last_row.get("pct_change", 0) or 0)

            for setup_name, setup_obj, horizon, dist in setups:
                # 快速预过滤
                if setup_name == "btst_breakout" and pct < 9.5:
                    continue
                if setup_name == "oversold_bounce":
                    if pos < 30:
                        continue
                    drop30 = (float(last_row["close"]) / float(df.iloc[pos - 30]["close"]) - 1) * 100
                    if drop30 > -20:
                        continue

                industry_pct = _resolve_industry_day_pct(
                    ticker,
                    trade_date,
                    ticker_to_industry=ticker_to_industry,
                    industry_day_pct=industry_day_pct,
                )
                ctx = {
                    "prices": df,
                    "fund_flow_records": fund_flow_by.get(ticker, []),
                    "industry_day_pct": industry_pct,
                    "regime": regime,
                }
                result = setup_obj.detect(ticker, trade_date, ctx)
                if not result.hit:
                    continue

                # Kelly
                kelly = compute_kelly_size(dist, max_pct=MAX_POS_PCT)
                size_factor = 0.5 if dd_action == "decrease" else 1.0
                kelly_pct = kelly.position_pct * size_factor
                if portfolio_used + kelly_pct > MAX_PORTFOLIO_PCT:
                    kelly_pct = max(0, MAX_PORTFOLIO_PCT - portfolio_used)
                if kelly_pct <= 0:
                    break

                # 风险计划
                risk = build_risk_plan(
                    invalidation_condition=result.invalidation_condition,
                    avg_loss=dist.avg_loss,
                    natural_horizon=horizon,
                )
                entry_price = float(last_row["close"])
                tracker.record_buy(
                    trade_date=trade_date,
                    ticker=ticker,
                    setup=setup_name,
                    horizon=horizon,
                    entry_price=entry_price,
                    kelly_pct=kelly_pct,
                    soft_stop=entry_price * (1 + risk.stop_loss_pct),
                    hard_stop=entry_price * (1 + risk.hard_stop_pct),
                    invalidation=result.invalidation_condition,
                    reasoning=f"{setup_name} T+{horizon}",
                )
                portfolio_used += kelly_pct
                break  # 同票只取第一个命中

        if (i + 1) % 10 == 0:
            s = tracker.state
            print(
                f"  [{i+1}/{len(trading_days)}] {trade_date}: "
                f"nav={s.nav:.3f} dd={s.drawdown_pct:+.1%} "
                f"open={s.open_positions} realized={s.realized_pnl_pct:+.2%} "
                f"dd_action={dd_action}"
            )

    # 最终统计
    journal = tracker._load_journal()
    buys = [r for r in journal if r.get("action") == "BUY"]
    exits = [r for r in journal if r.get("action") == "EXIT"]

    by_setup: dict[str, list] = defaultdict(list)
    for rec in exits:
        reasoning = str(rec.get("reasoning", ""))
        realized = 0.0
        if "realized=" in reasoning:
            import re

            m = re.search(r"realized=([+-]?[\d.]+)%", reasoning)
            if m:
                realized = float(m.group(1))
        by_setup[str(rec.get("setup", ""))].append(realized)

    state = tracker.state
    return {
        "period": f"{start_date} → {end_date}",
        "trading_days": len(trading_days),
        "total_buys": len(buys),
        "total_exits": len(exits),
        "final_nav": state.nav,
        "final_drawdown": state.drawdown_pct,
        "realized_pnl_pct": state.realized_pnl_pct,
        "open_positions_at_end": state.open_positions,
        "by_setup": {
            setup: {
                "n_exits": len(pnls),
                "winrate": (sum(1 for p in pnls if p > 0) / len(pnls)) if pnls else 0,
                "avg_pnl_pct": (sum(pnls) / len(pnls)) if pnls else 0,  # 百分数 (e.g. +5.75 = +5.75%)
            }
            for setup, pnls in by_setup.items()
        },
    }


def main():
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    import time

    t = time.time()
    result = backtest_paper_loop()
    elapsed = time.time() - t

    print("\n" + "=" * 60)
    print("Paper Trading 闭环回测结果")
    print("=" * 60)
    print(f"回测区间: {result['period']} ({result['trading_days']} 交易日, {elapsed:.0f}s)")
    print(f"总 BUY: {result['total_buys']}, 总 EXIT: {result['total_exits']}")
    print(f"最终净值: {result['final_nav']:.4f}")
    print(f"组合已实现 P&L: {result['realized_pnl_pct']:+.2%}")
    print(f"最大回撤: {result['final_drawdown']:+.1%}")
    print(f"期末持仓: {result['open_positions_at_end']}")

    print(f"\n{'Setup':<18} {'EXIT':>5} {'胜率':>6} {'均值P&L':>9}")
    for setup, stats in result["by_setup"].items():
        print(f"  {setup:<16} {stats['n_exits']:>5} {stats['winrate']:>5.0%} {stats['avg_pnl_pct']:>+8.2f}%")

    print(f"\n=== 对比 Phase 0 预期 ===")
    for setup, exp_pct in [("btst_breakout", 4.5), ("oversold_bounce", 3.4)]:
        actual = result["by_setup"].get(setup, {}).get("avg_pnl_pct", 0)
        match = "✅" if abs(actual - exp_pct) < 2.0 else "⚠️"
        print(f"  {setup}: 预期 +{exp_pct:.1f}%, 实际 {actual:+.2f}% {match}")

    out = Path("data/reports/paper_loop_backtest.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n→ 落盘 {out}")


if __name__ == "__main__":
    main()
