"""Phase 0 批量验证 — BTST + OversoldBounce (+ SectorRotation 若数据可用).

用刚接线的 evaluate_setups + FDR, 跑真实的 Phase 0 多 setup 判定.
这是文档 §6.1 的核心命题: "凸性 setup 这个范式本身有没有 alpha" (需 ≥2 个 FDR 显著).

诚实的数据约束:
- Setup-1 (BTST): 数据齐全 (price_cache + fund_flow_cache)
- Setup-2 (OversoldBounce): price_cache 缺 volume 列 → 条件3 (量比>1.5) 跳过, 退化为 2 条件
- Setup-3 (SectorRotation): 需要 industry_2d_pct / industry_net_flow, data/ 无此数据 → 跳过
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from scripts.setup_research import evaluate_setups, render_phase0_report
from src.screening.offensive.data.fund_flow_store import FundFlowStore
from src.screening.offensive.execution_adjuster import ExecutionConfig
from src.screening.offensive.setups.base import Setup
from src.screening.offensive.setups.btst_breakout import BtstBreakoutSetup
from src.screening.offensive.setups.oversold_bounce import OversoldBounceSetup

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

    print(f"加载 {len(all_tickers)} ticker 的价格 + 资金流...")
    prices_by: dict[str, pd.DataFrame] = {}
    fund_flow_by_ticker: dict[str, list] = {}
    for i, t in enumerate(all_tickers, 1):
        prices = _load_prices(t)
        if prices is None or len(prices) == 0:
            continue
        prices_by[t] = prices
        fund_flow_by_ticker[t] = store.get_range(t, "20200101", "20260706")
        if i % 100 == 0:
            print(f"  进度 {i}/{len(all_tickers)}")

    # 各 setup 用自己的候选预过滤 (避免对全样本跑慢 detect):
    # - BTST: 涨停日 (pct>=9.5%)
    # - OversoldBounce: 30日跌幅>20% 的日子 (pct 累计)
    btst_candidates: list[tuple[str, str]] = []
    oversold_candidates: list[tuple[str, str]] = []
    for t, df in prices_by.items():
        if df is None or len(df) == 0:
            continue
        ds = df.copy()
        ds["date_str"] = df["date"].dt.strftime("%Y%m%d")
        # BTST 候选: 涨停日
        for _, row in ds[ds["pct_change"] >= 9.5].iterrows():
            btst_candidates.append((t, row["date_str"]))
        # OversoldBounce 候选: 近30日跌幅>20% (用 close 比 30 日前)
        if len(ds) > 30:
            ds["drop_30d"] = (ds["close"] / ds["close"].shift(30) - 1) * 100
            for _, row in ds[ds["drop_30d"] <= -20.0].iterrows():
                oversold_candidates.append((t, row["date_str"]))

    print(f"BTST 候选 (涨停日): {len(btst_candidates)}")
    print(f"OversoldBounce 候选 (30日跌>20%): {len(oversold_candidates)}")

    # 合并去重; OversoldBounce 候选太多 (27k) 会导致 detect 超时, 采样到与 BTST 同量级
    import random
    random.seed(42)
    if len(oversold_candidates) > len(btst_candidates) * 2:
        sampled_oversold = random.sample(oversold_candidates, len(btst_candidates) * 2)
        print(f"  (OversoldBounce 候选采样: {len(oversold_candidates)} → {len(sampled_oversold)} 控制 detect 耗时)")
    else:
        sampled_oversold = oversold_candidates
    all_candidates = list(set(btst_candidates + sampled_oversold))
    tickers = [c[0] for c in all_candidates]
    dates = [c[1] for c in all_candidates]
    print(f"合并去重候选: {len(all_candidates)}")

    industry_pct_by_date = {d: 3.0 for d in set(dates)}
    regimes_by_date = {d: "normal" for d in set(dates)}

    setups: list[Setup] = [
        BtstBreakoutSetup(),
        OversoldBounceSetup(),
    ]
    print(f"\nSetups: {[s.name for s in setups]}")
    print("(SectorRotation 跳过: data/ 无 industry_2d_pct / industry_net_flow)")
    print("(OversoldBounce 退化: price_cache 缺 volume 列, 条件3 量比跳过)")

    print(f"\n跑 evaluate_setups + FDR...")
    result = evaluate_setups(
        setups=setups,
        tickers=tickers,
        trade_dates=dates,
        prices_by_ticker=prices_by,
        fund_flow_by_ticker=fund_flow_by_ticker,
        industry_pct_by_date=industry_pct_by_date,
        regimes_by_date=regimes_by_date,
        horizons=(5, 10),
        config=ExecutionConfig(slippage_bps=30, limit_up_unbuyable=True, t_plus_1_lock=True),
    )

    print()
    print(render_phase0_report(result))


if __name__ == "__main__":
    main()
