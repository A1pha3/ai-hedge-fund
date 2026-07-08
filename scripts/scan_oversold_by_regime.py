"""扫描 OversoldBounce 历史 hit, 按当时 regime 分层 — 验证 crisis 样本量.

优化: 预建 date→idx 索引, 避免 detect 内部每次 pd.to_datetime 全表转换.
用于判断 OversoldBounce 是否能做 regime 分层准入 (每层 ≥30 hits).
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import pandas as pd

from src.screening.offensive.data.fund_flow_store import FundFlowRecord
from src.screening.offensive.setups.base import DetectionResult
from src.screening.offensive.setups.oversold_bounce import (
    _DROP_THRESHOLD,
    _FLOW_LOOKBACK_DAYS,
    _LOOKBACK_DROP_DAYS,
    _VOLUME_RATIO_MIN,
    OversoldBounceSetup,
)


def detect_fast(
    setup: OversoldBounceSetup,
    prices: pd.DataFrame,
    records_by_date: dict[str, FundFlowRecord],
    date_yyyymmdd: str,
    idx: int,
    ticker: str,
) -> DetectionResult | None:
    """内联版 detect, 复用预建索引. 返回 None=miss, DetectionResult=hit/miss."""
    # 条件 1: 近 30 日跌幅 > 20%
    ref_idx = idx - _LOOKBACK_DROP_DAYS
    if ref_idx < 0:
        return None
    ref_close = float(prices.iloc[ref_idx]["close"])
    trigger_close = float(prices.iloc[idx]["close"])
    drop_pct = (trigger_close / ref_close - 1) * 100
    if drop_pct > _DROP_THRESHOLD:
        return None

    # 条件 2: 近 3 日主力净流入累计 > 0
    recent_dates = set()
    for i in range(1, _FLOW_LOOKBACK_DAYS + 1):
        if idx - i >= 0:
            d = prices.iloc[idx - i]["date_str"]
            recent_dates.add(d)
    recent_flow = sum(
        r.main_net_inflow
        for d in recent_dates
        for r in [records_by_date.get(d)]
        if r is not None and r.date <= date_yyyymmdd
    )
    if recent_flow <= 0:
        return None

    # 条件 3: 量比 > 1.5
    degraded = False
    degradation_reason = ""
    volume_col = "volume" if "volume" in prices.columns else None
    if volume_col is None:
        degraded = True
        degradation_reason = "条件3 (量比>1.5) 跳过: price_cache 无 volume 列"
    elif idx < 20:
        degraded = True
        degradation_reason = f"条件3 跳过: 历史数据不足 (idx={idx} < 20)"
    else:
        today_vol = float(prices.iloc[idx][volume_col])
        avg_vol = float(prices.iloc[idx - 20 : idx][volume_col].mean())
        vol_ratio = today_vol / avg_vol if avg_vol > 0 else 0
        if vol_ratio < _VOLUME_RATIO_MIN:
            return None

    low_30 = (
        float(prices.iloc[ref_idx : idx + 1]["low"].min())
        if "low" in prices.columns
        else trigger_close * 0.9
    )
    depth_score = min(1.0, abs(drop_pct) / 40.0)
    flow_score = min(1.0, recent_flow / 10_000_000)
    strength = depth_score * 0.6 + flow_score * 0.4

    return DetectionResult(
        hit=True,
        ticker=ticker,
        trade_date=date_yyyymmdd,
        trigger_strength=strength,
        invalidation_condition=f"价格跌破 {low_30 * 0.95:.2f} (30 日低点 -5%)",
        metadata={"drop_30d_pct": drop_pct, "recent_flow_3d": recent_flow},
        degraded=degraded,
        degradation_reason=degradation_reason,
    )


def main() -> None:
    regime_map = json.load(open("data/reports/regime_history.json"))
    setup = OversoldBounceSetup()
    price_dir = Path("data/price_cache")
    flow_dir = Path("data/fund_flow_cache")

    tickers = sorted(p.stem for p in price_dir.glob("*.csv"))
    print(f"扫描 {len(tickers)} 个 ticker")

    hits_by_regime: dict[str, list[tuple]] = defaultdict(list)
    total_scans = 0
    tickers_loaded = 0

    for ti, ticker in enumerate(tickers):
        pf = price_dir / f"{ticker}.csv"
        ff = flow_dir / f"{ticker}.csv"
        if not pf.exists() or not ff.exists():
            continue
        prices = pd.read_csv(pf, dtype={"date": str})
        if "close" not in prices.columns or len(prices) < 50:
            continue
        # 预建 date_str 列 (YYYYMMDD) + date→idx 索引 — 关键优化
        prices["date_str"] = prices["date"].str.replace("-", "", regex=False)
        date_to_idx = {d: i for i, d in enumerate(prices["date_str"])}

        flow_df = pd.read_csv(ff, dtype={"date": str})
        records_by_date: dict[str, FundFlowRecord] = {}
        for _, r in flow_df.iterrows():
            try:
                records_by_date[str(r["date"])] = FundFlowRecord(
                    ticker=ticker,
                    date=str(r["date"]),
                    close=float(r.get("close") or 0),
                    pct_change=float(r.get("pct_change") or 0),
                    main_net_inflow=float(r.get("main_net_inflow") or 0),
                    main_net_pct=float(r.get("main_net_pct") or 0),
                )
            except (ValueError, TypeError):
                pass
        if not records_by_date:
            continue
        tickers_loaded += 1

        # 只扫该 ticker 价格数据里有的、且在 regime_map 里的日期
        for date_yyyymmdd in regime_map:
            idx = date_to_idx.get(date_yyyymmdd)
            if idx is None:
                continue
            total_scans += 1
            try:
                result = detect_fast(setup, prices, records_by_date, date_yyyymmdd, idx, ticker)
                if result is not None and result.hit:
                    hits_by_regime[regime_map[date_yyyymmdd]].append(
                        (ticker, date_yyyymmdd, result.degraded)
                    )
            except Exception:
                pass

        if (ti + 1) % 50 == 0:
            total = sum(len(v) for v in hits_by_regime.values())
            print(f"  {ti+1}/{len(tickers)} ticker, 累计 hits={total}")

    total_hits = sum(len(v) for v in hits_by_regime.values())
    total_degraded = sum(1 for v in hits_by_regime.values() for _, _, d in v if d)
    print(f"\n加载 {tickers_loaded} ticker, 扫描 {total_scans} (ticker×date)")
    print(f"=== OversoldBounce hit 按 regime 分层 ===")
    print(f"总 hits: {total_hits} (degraded={total_degraded})")
    print(f"\n{'Regime':<10} {'Hits':>6} {'Degraded':>9} {'占比':>7} {'分层够?':>10}")
    for r in ("normal", "crisis", "risk_off"):
        hits = hits_by_regime.get(r, [])
        n = len(hits)
        deg = sum(1 for _, _, d in hits if d)
        pct = n / total_hits * 100 if total_hits else 0
        ok = "✅ ≥30" if n >= 30 else ("⚠️ 10-29" if n >= 10 else "❌ <10")
        print(f"{r:<10} {n:>6} {deg:>9} {pct:>6.1f}% {ok:>10}")

    out = {
        r: [{"ticker": t, "date": d, "degraded": deg} for t, d, deg in v]
        for r, v in hits_by_regime.items()
    }
    Path("data/reports/oversold_bounce_hits_by_regime.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\n→ hit 清单已存 data/reports/oversold_bounce_hits_by_regime.json")


if __name__ == "__main__":
    main()
