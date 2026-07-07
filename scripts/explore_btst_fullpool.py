"""全池 Phase 0 验证 — Setup-1 BTST 突破 (300 ticker)。

用全候选池 300 只 ticker × 2020-2026 真实数据 (已 backfill) + tushare 价格,
跑 BTST 突破 setup 的完整 execution-adjusted 分布回测。

预过滤: 只取涨停日 (pct>=9.5%) 作为候选, 大幅加速 (472k → ~14k 样本)。
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pandas as pd

from src.screening.offensive.data.fund_flow_store import FundFlowStore
from src.screening.offensive.distribution_builder import build_distribution
from src.screening.offensive.execution_adjuster import ExecutionConfig
from src.screening.offensive.setups.btst_breakout import BtstBreakoutSetup
from src.screening.offensive.setups.base import Setup


def _load_token() -> str:
    if os.path.exists(".env"):
        for line in Path(".env").read_text(encoding="utf-8").splitlines():
            if line.startswith("TUSHARE_TOKEN="):
                return line.split("=", 1)[1].strip().strip("'\"")
    return os.environ.get("TUSHARE_TOKEN", "")


_PRICE_CACHE_DIR = Path("data/price_cache/")


def _load_prices_tushare(ticker: str) -> pd.DataFrame:
    """tushare daily, 带文件缓存避免重跑。"""
    _PRICE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = _PRICE_CACHE_DIR / f"{ticker}.csv"
    if cache_file.exists():
        df = pd.read_csv(cache_file, dtype={"date": str})
        df["date"] = pd.to_datetime(df["date"])
        return df

    import tushare as ts

    ts.set_token(_load_token())
    pro = ts.pro_api()
    suffix = ".SZ" if ticker.startswith(("0", "3")) else ".SH"
    raw = pro.daily(ts_code=f"{ticker}{suffix}", start_date="20200101", end_date="20260706")
    if raw is None or len(raw) == 0:
        return pd.DataFrame()
    df = pd.DataFrame({
        "date": pd.to_datetime(raw["trade_date"], format="%Y%m%d"),
        "close": raw["close"].astype(float),
        "open": raw["open"].astype(float),
        "high": raw["high"].astype(float),
        "low": raw["low"].astype(float),
        "pct_change": raw["pct_chg"].astype(float),
    }).sort_values("date").reset_index(drop=True)
    df.to_csv(cache_file, index=False)
    return df


def main():
    with open("data/snapshots/candidate_pool_20260527_top300.json") as f:
        data = json.load(f)
    all_tickers = [item.get("ticker") for item in data if isinstance(item, dict) and item.get("ticker")]
    print(f"全候选池: {len(all_tickers)} tickers")

    store = FundFlowStore(cache_dir="data/fund_flow_cache/")
    prices_by_ticker: dict[str, pd.DataFrame] = {}
    fund_flow_by_ticker: dict[str, list] = {}
    # 预过滤: 只取涨停日 (BTST setup 要求涨停, 非涨停日必不命中)
    candidate_samples: list[tuple[str, str]] = []

    loaded = 0
    for i, t in enumerate(all_tickers, 1):
        prices = _load_prices_tushare(t)
        if prices is None or len(prices) == 0:
            continue
        prices_by_ticker[t] = prices
        flow = store.get_range(t, "20200101", "20260706")
        fund_flow_by_ticker[t] = flow
        # 涨停日候选
        limit_up_mask = prices["pct_change"] >= 9.5
        for _, row in prices[limit_up_mask].iterrows():
            candidate_samples.append((t, row["date"].strftime("%Y%m%d")))
        loaded += 1
        if i % 50 == 0:
            print(f"  进度 {i}/{len(all_tickers)}, loaded={loaded}, 候选样本={len(candidate_samples)}")

    print(f"\n加载完成: {loaded}/{len(all_tickers)} ticker 有数据")
    print(f"涨停日候选样本总数: {len(candidate_samples)}")

    # 包装 setup 注入 fund_flow + industry_pct 近似
    class _ContextWrapper(Setup):
        name = "btst_breakout"
        natural_horizon = 3

        def __init__(self):
            self._inner = BtstBreakoutSetup()

        def detect(self, ticker, trade_date, context):
            ctx = dict(context)
            ctx["fund_flow_records"] = fund_flow_by_ticker.get(ticker, [])
            ctx["prices"] = prices_by_ticker.get(ticker)
            # industry_pct 近似: 涨停日视为行业至少 +3%
            prices_df = ctx.get("prices")
            if prices_df is not None:
                row = prices_df[prices_df["date"].dt.strftime("%Y%m%d") == trade_date]
                if len(row) > 0:
                    pct = float(row.iloc[0]["pct_change"])
                    ctx["industry_day_pct"] = max(pct, 3.0) if pct >= 9.5 else pct
            return self._inner.detect(ticker, trade_date, ctx)

    tickers_list = [s[0] for s in candidate_samples]
    dates_list = [s[1] for s in candidate_samples]
    regimes = {d: "normal" for d in set(dates_list)}
    config = ExecutionConfig(slippage_bps=30, limit_up_unbuyable=True, t_plus_1_lock=True)

    def _run(period_filter, label):
        idx = [i for i, d in enumerate(dates_list) if period_filter(d)]
        if not idx:
            return None
        tk = [tickers_list[i] for i in idx]
        td = [dates_list[i] for i in idx]
        return build_distribution(
            setup=_ContextWrapper(), tickers=tk, trade_dates=td,
            prices_by_ticker=prices_by_ticker, regimes_by_date=regimes,
            horizons=(1, 3, 5, 10), config=config, period=label,
        )

    is_tsd = _run(lambda d: d < "20250101", "IS")
    oos_tsd = _run(lambda d: d >= "20250101", "OOS")
    all_tsd = _run(lambda d: True, "ALL")

    print("\n" + "=" * 75)
    print("Setup-1 BTST 突破 — 全池 Phase 0 真实验证 (300 ticker)")
    print("=" * 75)
    print(f"候选涨停日: {len(candidate_samples)}, 命中 (含主力过滤): {all_tsd.n_hits if all_tsd else 0}")

    for label, tsd in [("ALL", all_tsd), ("IS (≤2024)", is_tsd), ("OOS (≥2025)", oos_tsd)]:
        if tsd is None:
            continue
        print(f"\n--- {label} (n_hits={tsd.n_hits}) ---")
        for h in (1, 3, 5, 10):
            d = tsd.horizons.get(h)
            if d is None or d.n == 0:
                print(f"  T+{h}: n=0")
                continue
            qual = "✅" if (d.convexity_ratio >= 1.5 and d.winrate >= 0.50 and d.n >= 50) else "❌"
            print(f"  T+{h}: n={d.n}  winrate={d.winrate:.1%}  E[r]={d.expected_return:+.2%}  "
                  f"avg_gain={d.avg_gain:+.2%}  avg_loss={d.avg_loss:+.2%}  "
                  f"convexity={d.convexity_ratio:.2f}  CI=[{d.ci_low:+.2%}, {d.ci_high:+.2%}] {qual}")

    print("\n" + "=" * 75)
    print("Verdict (per horizon: convexity≥1.5 + winrate≥50% + n≥50, IS&OOS 都达标):")
    for h in (1, 3, 5, 10):
        is_d = is_tsd.horizons.get(h) if is_tsd else None
        oos_d = oos_tsd.horizons.get(h) if oos_tsd else None
        if not is_d or not oos_d or is_d.n == 0 or oos_d.n == 0:
            print(f"  T+{h}: 样本不足")
            continue
        is_ok = is_d.convexity_ratio >= 1.5 and is_d.winrate >= 0.50 and is_d.n >= 50
        oos_ok = oos_d.convexity_ratio >= 1.5 and oos_d.winrate >= 0.50 and oos_d.n >= 50
        v = "✅ PASS" if (is_ok and oos_ok) else "❌ FAIL"
        print(f"  T+{h}: IS({'✅' if is_ok else '❌'} n={is_d.n} cv={is_d.convexity_ratio:.2f} wr={is_d.winrate:.0%}) "
              f"OOS({'✅' if oos_ok else '❌'} n={oos_d.n} cv={oos_d.convexity_ratio:.2f} wr={oos_d.winrate:.0%}) → {v}")


if __name__ == "__main__":
    main()
