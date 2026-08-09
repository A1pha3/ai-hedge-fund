"""近端交易日 BTST 生产选股演示 (只读) — range 因子落地后的新公式 0.20×5 选股.

用途: range 落地 (commit 04ded7f4) 后, 用真实近期数据跑生产 BtstBreakoutSetup.detect()
全 4 条件 (涨停/资金流/行业/防追高), 看新公式选出的票 + range_score 的作用.
扫最近 N 个交易日的全 universe (1442 票), 报每个有 hit 的日子的 top picks.

数据 (全部只读, 不碰 data/paper_trading*/):
  - 价格:   data/price_cache/ (factor_audit 同源加载)
  - 资金流: data/fund_flow_cache/<ticker>.csv (已回填)
  - 行业:   data/industry_index_cache/8010*.SI.csv + _industry_codes.json (真实行业指数涨幅)

对照: 同一批 hit, 同时算 新公式 (0.20×5 含 range) vs 旧公式 (0.25×4 不含 range),
看 range 是否改变排序/入池.
"""
from __future__ import annotations

import json
import math
import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.factor_audit import _load_all_prices  # noqa: E402
from src.screening.offensive.data.fund_flow_store import FundFlowStore  # noqa: E402
from src.screening.offensive.setups.btst_breakout import BtstBreakoutSetup  # noqa: E402
from src.tools.ashare_board_utils import limit_up_pct_for_ticker  # noqa: E402

RECENT_N_DATES = 8
INDUSTRY_DIR = Path("data/industry_index_cache")
CODES_PATH = INDUSTRY_DIR / "_industry_codes.json"


def _industry_pct_all_dates() -> dict[str, dict[str, float]]:
    """{trade_date: {industry_name: pct_chg}} — 全部日期, 一次加载."""
    codes = json.loads(CODES_PATH.read_text(encoding="utf-8"))
    by_date: dict[str, dict[str, float]] = defaultdict(dict)
    for index_code, name in codes.items():
        path = INDUSTRY_DIR / f"{index_code}.csv"
        if not path.exists():
            continue
        df = pd.read_csv(path)
        df["trade_date"] = df["trade_date"].astype(str)
        for _, row in df.iterrows():
            by_date[str(row["trade_date"])][name] = float(row["pct_chg"])
    return by_date


def main() -> None:
    setup = BtstBreakoutSetup()
    prices_by = _load_all_prices()
    store = FundFlowStore(cache_dir="data/fund_flow_cache/")
    industry_by_date = _industry_pct_all_dates()

    all_dates = sorted({d for df in prices_by.values() for d in df["date_str"].values})
    recent_dates = all_dates[-RECENT_N_DATES:]
    print(f"扫最近 {RECENT_N_DATES} 个交易日: {recent_dates}")
    print(f"universe: {len(prices_by)} 票 | 行业数据: {len(industry_by_date)} 个日期\n")

    # 预处理: 每 ticker 排序 + date_str + 资金流(一次加载)
    flows_by_ticker: dict[str, list] = {}
    for ticker, df in prices_by.items():
        flows_by_ticker[ticker] = store.get_range(ticker, "20200101", recent_dates[-1])

    all_hits: list[dict] = []
    for trade_date in recent_dates:
        ind_pct = industry_by_date.get(trade_date, {})
        date_hits = 0
        for ticker, df in prices_by.items():
            df = df.sort_values("date").reset_index(drop=True)
            if trade_date not in set(df["date_str"].values):
                continue
            idx = df[df["date_str"] == trade_date].index[0]
            pct = df["pct_change"].iloc[idx]
            try:
                pct = float(pct)
            except (TypeError, ValueError):
                continue
            if math.isnan(pct) or pct < limit_up_pct_for_ticker(ticker):
                continue
            ctx = {
                "prices": df,
                "fund_flow_records": flows_by_ticker.get(ticker, []),
                "industry_day_pct": None,  # 全 universe 不逐票映射行业; None=跳过行业过滤标degraded(诚实)
            }
            result = setup.detect(ticker, trade_date, ctx)
            if not result.hit:
                continue
            date_hits += 1
            m = result.metadata
            # detect metadata 只暴露 range_score (不暴露 raw range_pct); 从价格重算 raw 供显示
            hi = float(df["high"].iloc[idx])
            lo = float(df["low"].iloc[idx])
            pc = float(df["close"].iloc[idx - 1]) if idx >= 1 else 0.0
            raw_range = round((hi - lo) / pc, 4) if pc > 0 and hi >= lo else 0.0
            old_strength = min(
                1.0,
                0.25 * (m["board_score"] + m["low_vol_score"] + m["squeeze_score"] + m["volume_score"])
                + m["energy_bonus"],
            )
            all_hits.append({
                "date": trade_date, "ticker": ticker,
                "strength_new": result.trigger_strength, "strength_old": round(old_strength, 5),
                "range_score": m["range_score"], "range_pct": raw_range,
                "board": m["board_score"], "low_vol": m["low_vol_score"],
                "squeeze": m["squeeze_score"], "volume": m["volume_score"],
                "energy_bonus": m["energy_bonus"], "pct": pct,
                "degraded": result.degraded,
            })
        print(f"  {trade_date}: hit {date_hits}")

    print(f"\n总 hit: {len(all_hits)}")
    if not all_hits:
        print("近端交易日无 BTST 命中 (全 4 条件). 可能是近期涨停票主力净流出被条件2挡.")
        return

    # 全 hit 按新 strength 排序, 取 top
    all_hits.sort(key=lambda h: (-h["strength_new"], h["date"], h["ticker"]))
    top = all_hits[:15]
    print(f"\n=== 新公式 (0.20×5 含 range) top {len(top)} hits ===")
    print(f"{'日期':<9} {'票':<8} {'strength新/旧':>14} {'range':>5} {'r%':>5} {'b':>4} {'lv':>4} {'sq':>4} {'vol':>4} {'bonus':>5} {'pct':>5}")
    for h in top:
        print(f"{h['date']:<9} {h['ticker']:<8} "
              f"{h['strength_new']:.3f}/{h['strength_old']:.3f} "
              f"{h['range_score']:.1f} {h['range_pct']:.2f} "
              f"{h['board']:.2f} {h['low_vol']:.2f} {h['squeeze']:.2f} {h['volume']:.2f} "
              f"{h['energy_bonus']:.2f} {h['pct']:.1f}")

    # range 对排序/入池的影响 (全 hit 口径)
    old_pass = sum(1 for h in all_hits if h["strength_old"] >= 0.50)
    new_pass = sum(1 for h in all_hits if h["strength_new"] >= 0.50)
    newly_pass = [h for h in all_hits if h["strength_new"] >= 0.50 > h["strength_old"]]
    newly_block = [h for h in all_hits if h["strength_old"] >= 0.50 > h["strength_new"]]
    print(f"\n=== 0.50 闸对照 (全 {len(all_hits)} hits) ===")
    print(f"  旧公式过闸 {old_pass} → 新公式过闸 {new_pass} (放入 {len(newly_pass)} / 挡出 {len(newly_block)})")
    if len(all_hits) >= 2:
        s_new = pd.Series([h["strength_new"] for h in all_hits])
        s_old = pd.Series([h["strength_old"] for h in all_hits])
        print(f"  新旧 strength 秩相关: {float(s_new.rank().corr(s_old.rank())):.4f}")
    rs = {}
    for h in all_hits:
        rs[h["range_score"]] = rs.get(h["range_score"], 0) + 1
    print(f"  hit 的 range_score 分布: {dict(sorted(rs.items()))}")
    if newly_pass:
        print(f"  range 放入的票: {[(h['date'], h['ticker'], h['range_score']) for h in newly_pass]}")
    if newly_block:
        print(f"  range 挡出的票: {[(h['date'], h['ticker'], h['range_score']) for h in newly_block]}")


if __name__ == "__main__":
    main()
