"""Phase 0 探索性验证 — Setup-1 BTST 突破 (3 ticker 真实数据)。

用已 backfill 的 3 只 ticker (300502/300308/300054) + tushare 价格 +
fund_flow_store 数据, 跑真实 Setup-1 分布回测。

⚠ 限制 (诚实标注):
- 只 3 只 ticker (非全候选池, 样本量受限)
- industry_pct 用 ticker 自身 pct_change 近似 (无完整行业指数数据)
- 这是探索性信号, 不是 Phase 0 正式 verdict
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from src.screening.offensive.data.fund_flow_store import FundFlowStore
from src.screening.offensive.distribution_builder import build_distribution
from src.screening.offensive.execution_adjuster import ExecutionConfig
from src.screening.offensive.setups.btst_breakout import BtstBreakoutSetup
from src.tools.tushare_api import _get_pro


def _load_prices_tushare(ticker: str) -> pd.DataFrame:
    """tushare daily → 标准化 DataFrame (date/close/open/pct_change)。"""
    pro = _get_pro()
    raw = pro.daily(ts_code=f"{ticker}.SZ" if ticker.startswith(("0", "3")) else f"{ticker}.SH",
                    start_date="20200101", end_date="20260706")
    df = raw.copy()
    df["date"] = pd.to_datetime(df["trade_date"], format="%Y%m%d")
    df["pct_change"] = df["pct_chg"].astype(float)
    df["close"] = df["close"].astype(float)
    df["open"] = df["open"].astype(float)
    df["high"] = df["high"].astype(float)
    df["low"] = df["low"].astype(float)
    return df[["date", "close", "open", "high", "low", "pct_change"]].sort_values("date").reset_index(drop=True)


def main():
    tickers = ["300502", "300308", "300054"]
    store = FundFlowStore(cache_dir="data/fund_flow_cache/")

    prices_by_ticker: dict[str, pd.DataFrame] = {}
    fund_flow_by_ticker: dict[str, list] = {}
    candidate_samples: list[tuple[str, str]] = []  # (ticker, date_str)

    for t in tickers:
        print(f"\n=== {t} ===")
        prices = _load_prices_tushare(t)
        prices_by_ticker[t] = prices
        flow = store.get_range(t, "20200101", "20260706")
        fund_flow_by_ticker[t] = flow
        print(f"  价格: {len(prices)} 条, 资金流: {len(flow)} 条")

        # 候选: 所有交易日 (setup.detect 会过滤到 涨停+主力 的命中)
        for _, row in prices.iterrows():
            candidate_samples.append((t, row["date"].strftime("%Y%m%d")))

    print(f"\n候选样本总数: {len(candidate_samples)}")

    # 用 BtstBreakoutSetup 包装, 注入 fund_flow + industry_pct (近似: 用 ticker 自身 pct_change)
    # industry_pct 近似: 涨停日 (pct>=9.5) 视为行业至少 +3% (满足板块效应阈值)
    class _ExploratoryBtst(BtstBreakoutSetup):
        def detect(self, ticker, trade_date, context):
            # 注入 industry_pct 近似 (用 ticker 自身涨幅, floor 到 3.0 if 涨停)
            prices_df = context.get("prices")
            if prices_df is not None:
                row = prices_df[prices_df["date"].dt.strftime("%Y%m%d") == trade_date]
                if len(row) > 0:
                    pct = float(row.iloc[0]["pct_change"])
                    context = dict(context)
                    context["industry_day_pct"] = max(pct, 3.0) if pct >= 9.5 else pct
            return super().detect(ticker, trade_date, context)

    setup = _ExploratoryBtst()

    # 构造 context_by_ticker (build_distribution 内部用)
    # 但 build_distribution 签名是 (tickers, trade_dates, ...), 我们直接调
    tickers_list = [s[0] for s in candidate_samples]
    dates_list = [s[1] for s in candidate_samples]

    # regime 全 normal (探索性, 不分 regime)
    regimes = {d: "normal" for d in set(dates_list)}

    # 包装 setup 注入 fund_flow
    from src.screening.offensive.setups.base import Setup, DetectionResult

    class _ContextWrapper(Setup):
        name = "btst_breakout"
        natural_horizon = 3

        def __init__(self):
            self._inner = setup

        def detect(self, ticker, trade_date, context):
            ctx = dict(context)
            ctx["fund_flow_records"] = fund_flow_by_ticker.get(ticker, [])
            ctx["prices"] = prices_by_ticker.get(ticker)
            return self._inner.detect(ticker, trade_date, ctx)

    # 执行: IS (≤2024) / OOS (≥2025) 两段 + execution-adjusted
    config = ExecutionConfig(slippage_bps=30, limit_up_unbuyable=True, t_plus_1_lock=True)

    def _run(period_filter, label):
        idx = [i for i, d in enumerate(dates_list) if period_filter(d)]
        tk = [tickers_list[i] for i in idx]
        td = [dates_list[i] for i in idx]
        tsd = build_distribution(
            setup=_ContextWrapper(), tickers=tk, trade_dates=td,
            prices_by_ticker=prices_by_ticker, regimes_by_date=regimes,
            horizons=(1, 3, 5, 10), config=config, period=label,
        )
        return tsd

    is_tsd = _run(lambda d: d < "20250101", "IS")
    oos_tsd = _run(lambda d: d >= "20250101", "OOS")
    all_tsd = _run(lambda d: True, "ALL")

    print("\n" + "=" * 70)
    print("Setup-1 BTST 突破 — 真实数据 Phase 0 探索性验证")
    print("=" * 70)
    print(f"样本: 3 ticker × 2020-2026, 候选 {len(candidate_samples)} 日, 命中 {all_tsd.n_hits} 日")

    for label, tsd in [("ALL", all_tsd), ("IS (≤2024)", is_tsd), ("OOS (≥2025)", oos_tsd)]:
        print(f"\n--- {label} (n_hits={tsd.n_hits}) ---")
        for h in (1, 3, 5, 10):
            d = tsd.horizons.get(h)
            if d is None or d.n == 0:
                print(f"  T+{h}: n=0")
                continue
            print(f"  T+{h}: n={d.n}  winrate={d.winrate:.1%}  E[r]={d.expected_return:+.2%}  "
                  f"avg_gain={d.avg_gain:+.2%}  avg_loss={d.avg_loss:+.2%}  "
                  f"convexity={d.convexity_ratio:.2f}  CI=[{d.ci_low:+.2%}, {d.ci_high:+.2%}]")

    # natural horizon = T+3 的 verdict
    nh = 3
    is_d = is_tsd.horizons.get(nh)
    oos_d = oos_tsd.horizons.get(nh)
    print("\n" + "=" * 70)
    print(f"Verdict (natural_horizon=T+{nh}, 准入: convexity≥1.5 + winrate≥50% + n≥50):")
    if is_d and oos_d:
        is_ok = is_d.convexity_ratio >= 1.5 and is_d.winrate >= 0.50 and is_d.n >= 50
        oos_ok = oos_d.convexity_ratio >= 1.5 and oos_d.winrate >= 0.50 and oos_d.n >= 50
        verdict = "✅ PASS" if (is_ok and oos_ok) else "❌ FAIL"
        print(f"  IS  : n={is_d.n} winrate={is_d.winrate:.1%} convexity={is_d.convexity_ratio:.2f} → {'✅' if is_ok else '❌'}")
        print(f"  OOS : n={oos_d.n} winrate={oos_d.winrate:.1%} convexity={oos_d.convexity_ratio:.2f} → {'✅' if oos_ok else '❌'}")
        print(f"  Overall: {verdict}")
    else:
        print(f"  样本不足 (IS或OOS 无 T+{nh} 分布)")

    print("\n⚠ 探索性限制: 只 3 ticker; industry_pct 近似; 非 Phase 0 正式 verdict")
    print("  正式 verdict 需: 全候选池 backfill + 真实行业指数 + FDR 校正")


if __name__ == "__main__":
    main()
