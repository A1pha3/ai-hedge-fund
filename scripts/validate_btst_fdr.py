"""真实数据验证: Setup-1 (BTST T+10) 的 FDR 校正 verdict.

复用 explore_btst_fullpool.py 的数据加载 (300 ticker + fund flow + prices),
用刚接线的 evaluate_setups 跑, 验证 Setup-1 的 p-value / q-value / FDR 显著性.

注意: 单 setup 时 phase0_verdict 必 FAIL (文档 §3.3 要求 ≥2 个), 但
fdr_significant 会显示该 setup 本身的统计显著性是否成立.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from scripts.setup_research import evaluate_setups, render_phase0_report
from src.screening.offensive.data.fund_flow_store import FundFlowStore
from src.screening.offensive.execution_adjuster import ExecutionConfig
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


def main() -> None:
    pool = json.loads(_CANDIDATE_POOL.read_text(encoding="utf-8"))
    all_tickers = [d["ticker"] for d in pool if isinstance(d, dict) and d.get("ticker")]
    store = FundFlowStore(cache_dir=str(_FUND_FLOW_CACHE))

    print(f"加载候选池 {len(all_tickers)} ticker 的价格 + 资金流...")
    prices_by_ticker: dict[str, pd.DataFrame] = {}
    fund_flow_by_ticker: dict[str, list] = {}
    # 枚举所有涨停日候选 (BTST 条件1 预过滤)
    candidate_samples: list[tuple[str, str]] = []
    for i, t in enumerate(all_tickers, 1):
        prices = _load_prices(t)
        if prices is None or len(prices) == 0:
            continue
        prices_by_ticker[t] = prices
        fund_flow_by_ticker[t] = store.get_range(t, "20200101", "20260706")
        for _, row in prices[prices["pct_change"] >= 9.5].iterrows():
            candidate_samples.append((t, row["date"].strftime("%Y%m%d")))
        if i % 100 == 0:
            print(f"  进度 {i}/{len(all_tickers)}, 候选={len(candidate_samples)}")

    tickers = [s[0] for s in candidate_samples]
    trade_dates = [s[1] for s in candidate_samples]
    # industry_pct 近似 (与 explore_btst_fullpool.py 一致)
    industry_pct_by_date = {d: 3.0 for d in set(trade_dates)}
    regimes_by_date = {d: "normal" for d in set(trade_dates)}

    print(f"\n候选涨停日样本: {len(candidate_samples)}")
    print(f"跑 evaluate_setups([BtstBreakoutSetup()], horizon=10, execution-adjusted)...")

    result = evaluate_setups(
        setups=[BtstBreakoutSetup()],
        tickers=tickers,
        trade_dates=trade_dates,
        prices_by_ticker=prices_by_ticker,
        fund_flow_by_ticker=fund_flow_by_ticker,
        industry_pct_by_date=industry_pct_by_date,
        regimes_by_date=regimes_by_date,
        horizons=(10,),
        config=ExecutionConfig(slippage_bps=30, limit_up_unbuyable=True, t_plus_1_lock=True),
    )

    print()
    print(render_phase0_report(result))

    # 额外: 直接显示 setup 级结果
    s = result["setups"][0]
    print(f"\n--- Setup-1 (BTST T+10) 详情 ---")
    print(f"  p-value (IS, 训练段): {s['p_value']:.2e}")
    print(f"  q-value (FDR 校正后): {s['q_value']:.2e}")
    print(f"  p-value (OOS, 验证段): {s['p_value_oos']:.2e}")
    print(f"  FDR 显著: {s['fdr_significant']}")
    print(f"  qualified_is: {s['qualified_is']}  qualified_oos: {s['qualified_oos']}")
    print(f"  IS returns n={len(s['is_returns'])}, OOS returns n={len(s['oos_returns'])}")


if __name__ == "__main__":
    main()
