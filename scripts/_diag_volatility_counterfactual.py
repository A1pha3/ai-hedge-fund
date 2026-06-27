#!/usr/bin/env python3
"""Volatility factor 修复方向 counterfactual 诊断 (risk-retirement for bl-volatility-factor-fix).

问题 (来自全 universe 诊断 n=8136): calculate_volatility_signals 的 dual-AND gate
  bullish if vol_regime<0.8 AND vol_z<-1
  bearish if vol_regime>1.2 AND vol_z>1
导致 direction=0 (neutral) 占 55.7%; 且 +1 (bullish) vs -1 (bearish) T+1 差 -0.453%
(bullish 票实际 T+1 更低 = 方向疑似反).

修复方向 (待诊断后定) 三选:
  A 松绑 AND→OR:    bullish if regime<0.8 OR z<-1;  bearish if regime>1.2 OR z>1
  B 缩窄中性带:      bullish if regime<0.9 AND z<-1; bearish if regime>1.1 AND z>1
  C 翻转方向:        bullish if regime>1.2 AND z>1;  bearish if regime<0.8 AND z<-1  (swap)

本诊断对每个 stock-day 取 vol_regime+vol_z (来自 calculate_volatility_signals metrics),
计算 4 个 variant 的 direction, 按 variant×direction 分组算 T+1 均值, 定位:
  - 哪个 variant 最降 dir=0 (更多可操作信号)
  - 哪个 variant 让 bullish T+1 > bearish T+1 (方向正确)
注意: T+1 是同一 realized return, 只重新打标 — 若翻转 (C) 让 separation 反向变正, 说明是方向标签错.

复用 _diag_trend_subfactor_direction.py 的 universe/history 获取逻辑 (tushare, 全 A, 剔除 ST/退/北交所/流动性<10万/|pct_chg|>9.5%).
WIP-compatible: 纯只读诊断, 不改 technicals.py / screening, 不污染 C220 BUY-gate-horizon 归因.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from dotenv import load_dotenv

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

try:
    from scripts.btst_data_utils import build_beijing_exchange_mask
except ModuleNotFoundError:
    from btst_data_utils import build_beijing_exchange_mask  # type: ignore[redef]

from src.agents.technicals import calculate_volatility_signals  # noqa: E402

load_dotenv(_PROJECT_ROOT / ".env")
logger = logging.getLogger("vol_counterfactual")

VOL_LOW, VOL_HIGH, VOL_Z = 0.8, 1.2, 1.0  # current thresholds (technicals.py)
VOL_LOW_B, VOL_HIGH_B = 0.9, 1.1          # option B narrow band


def _dir_current(r, z):
    if r < VOL_LOW and z < -VOL_Z:
        return 1
    if r > VOL_HIGH and z > VOL_Z:
        return -1
    return 0


def _dir_A_or(r, z):
    if r < VOL_LOW or z < -VOL_Z:
        return 1
    if r > VOL_HIGH or z > VOL_Z:
        return -1
    return 0


def _dir_B_narrow(r, z):
    if r < VOL_LOW_B and z < -VOL_Z:
        return 1
    if r > VOL_HIGH_B and z > VOL_Z:
        return -1
    return 0


def _dir_C_flip(r, z):
    # swap bullish/bearish labels (tests reversal hypothesis)
    if r > VOL_HIGH and z > VOL_Z:
        return 1
    if r < VOL_LOW and z < -VOL_Z:
        return -1
    return 0


VARIANTS = {"current_AND": _dir_current, "A_OR": _dir_A_or, "B_narrow": _dir_B_narrow, "C_flip": _dir_C_flip}


def _get_pro():
    import tushare as ts
    token = os.getenv("TUSHARE_TOKEN")
    if not token:
        raise RuntimeError("TUSHARE_TOKEN 未设置")
    ts.set_token(token)
    return ts.pro_api()


def get_trading_dates(pro, n_days, end_date=None):
    end = datetime.strptime(end_date, "%Y%m%d") if end_date else datetime.now()
    start = end - timedelta(days=n_days * 2 + 60)
    cal = pro.trade_cal(exchange="SSE", start_date=start.strftime("%Y%m%d"),
                        end_date=end.strftime("%Y%m%d"), is_open="1")
    return sorted(cal["cal_date"].tolist())[-n_days:]


def get_universe_for_date(pro, trade_date, stock_basic):
    df = pro.daily(trade_date=trade_date)
    if df is None or df.empty:
        return pd.DataFrame()
    df = df.merge(stock_basic[["ts_code", "name"]], on="ts_code", how="left")
    df = df[df["amount"] >= 100000]
    df = df[~df["name"].str.contains("ST|退", na=False)]
    df = df[~build_beijing_exchange_mask(df["ts_code"])]
    df = df[df["pct_chg"].between(-9.5, 9.5)]
    return df


def get_history_batch(pro, codes, start_date, end_date, batch_size=10):
    frames = []
    for i in range(0, len(codes), batch_size):
        batch = codes[i:i + batch_size]
        for attempt in range(3):
            try:
                h = pro.daily(ts_code=",".join(batch), start_date=start_date, end_date=end_date)
                if h is not None and not h.empty:
                    frames.append(h)
                break
            except Exception as e:
                if attempt == 2:
                    logger.warning("history batch %d-%d 失败: %s", i, i + len(batch), e)
                time.sleep(0.6 * (attempt + 1))
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames, ignore_index=True)
    if "vol" in df.columns and "volume" not in df.columns:
        df = df.rename(columns={"vol": "volume"})
    return df


def run(n_dates, sample_n, end_date=None, seed=42):
    pro = _get_pro()
    stock_basic = pro.stock_basic(exchange="", list_status="L", fields="ts_code,name")
    trade_dates = get_trading_dates(pro, n_dates + 1, end_date=end_date)
    if len(trade_dates) < 2:
        print("交易日不足")
        return
    test_dates = trade_dates[:-1]
    rng = np.random.default_rng(seed)

    rows = []
    print(f"\nVolatility counterfactual 诊断: {test_dates[0]}~{test_dates[-1]} ({len(test_dates)} 日期, sample={sample_n}/date)")
    print("=" * 92)

    for di, td in enumerate(test_dates):
        next_date = trade_dates[di + 1]
        t0 = time.time()
        uni = get_universe_for_date(pro, td, stock_basic)
        if uni.empty:
            continue
        if sample_n and len(uni) > sample_n:
            uni = uni.sample(n=sample_n, random_state=rng.integers(1 << 31))
        try:
            dfn = pro.daily(trade_date=next_date)[["ts_code", "pct_chg"]].rename(columns={"pct_chg": "next_ret"})
        except Exception:
            continue
        uni = uni.merge(dfn, on="ts_code", how="inner")
        if len(uni) < 50:
            continue
        hist_start = (datetime.strptime(td, "%Y%m%d") - timedelta(days=400)).strftime("%Y%m%d")
        hist = get_history_batch(pro, uni["ts_code"].tolist(), hist_start, td)
        if hist.empty:
            continue
        hist["trade_date"] = pd.to_datetime(hist["trade_date"], format="%Y%m%d")
        hist = hist.sort_values(["ts_code", "trade_date"])
        next_map = dict(zip(uni["ts_code"], uni["next_ret"]))
        n_ok = 0
        for code, g in hist.groupby("ts_code"):
            if len(g) < 126:
                continue
            nr = next_map.get(code)
            if nr is None or not np.isfinite(nr):
                continue
            try:
                sig = calculate_volatility_signals(g.set_index("trade_date"))
            except Exception:
                continue
            m = sig["metrics"]
            r = m["volatility_regime"]
            z = m["volatility_z_score"]
            if not (np.isfinite(r) and np.isfinite(z)):
                continue
            row = {"ticker": code, "trade_date": td, "vol_regime": r, "vol_z": z, "next_ret": float(nr)}
            for vname, fn in VARIANTS.items():
                row[vname] = fn(r, z)
            rows.append(row)
            n_ok += 1
        print(f"[{di+1}/{len(test_dates)}] {td} universe={len(uni)} scored={n_ok} ({time.time()-t0:.1f}s)")

    if not rows:
        print("无有效数据")
        return
    _analyze(rows, test_dates)


def _analyze(rows, test_dates):
    df = pd.DataFrame(rows)
    print(f"\n样本: {len(df)} stock-days, {df['trade_date'].nunique()} 日期, {df['ticker'].nunique()} 票")
    print("=" * 92)
    print(f"\n{'variant':<16s} {'dir=+1':>8s} {'dir=0':>8s} {'dir=-1':>8s} {'%neutral':>10s}"
          f" {'T+1(+1)':>10s} {'T+1(0)':>10s} {'T+1(-1)':>10s} {'sep(+--)':>10s}")
    print("-" * 92)
    results = {}
    for v in VARIANTS:
        d = df[v]
        n1 = int((d == 1).sum())
        n0 = int((d == 0).sum())
        nm = int((d == -1).sum())
        t1 = df.loc[d == 1, "next_ret"].mean()
        t0 = df.loc[d == 0, "next_ret"].mean()
        tm = df.loc[d == -1, "next_ret"].mean()
        sep = (t1 - tm) if (np.isfinite(t1) and np.isfinite(tm)) else float("nan")
        results[v] = dict(n_pos=n1, n_zero=n0, n_neg=nm, pct_neutral=100.0*n0/len(df),
                          t1_pos=t1, t1_zero=t0, t1_neg=tm, sep=sep)
        print(f"{v:<16s} {n1:>8d} {n0:>8d} {nm:>8d} {100.0*n0/len(df):>9.1f}%"
              f" {t1:>10.3f} {t0:>10.3f} {tm:>10.3f} {sep:>+10.3f}")

    cur = results["current_AND"]
    print("\n" + "=" * 92)
    print("判定 (sep = T+1(bullish) - T+1(bearish); 正=方向正确, 负=反向):")
    print(f"  current: %neutral={cur['pct_neutral']:.1f}%, sep={cur['sep']:+.3f}"
          f" (症状复现预期: ~55% neutral, sep<0 反向)")
    best_sep = max(results.items(), key=lambda kv: kv[1]["sep"])
    least_neutral = min(results.items(), key=lambda kv: kv[1]["pct_neutral"])
    print(f"  方向最正 (max sep): {best_sep[0]} sep={best_sep[1]['sep']:+.3f} %neutral={best_sep[1]['pct_neutral']:.1f}%")
    print(f"  最少 neutral (max actionable): {least_neutral[0]} %neutral={least_neutral[1]['pct_neutral']:.1f}% sep={least_neutral[1]['sep']:+.3f}")

    def _clean(o):
        if isinstance(o, np.floating):
            return float(o)
        if isinstance(o, np.integer):
            return int(o)
        if isinstance(o, float) and not np.isfinite(o):
            return None
        return o
    out = _PROJECT_ROOT / "data/reports/volatility_counterfactual_diag_latest.json"
    out.write_text(json.dumps({
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "n_stock_days": len(df), "n_dates": int(df["trade_date"].nunique()),
        "n_tickers": int(df["ticker"].nunique()), "test_dates": test_dates,
        "variants": {k: {kk: _clean(vv) for kk, vv in v.items()} for k, v in results.items()},
    }, ensure_ascii=False, indent=2))
    print(f"\n结果已写: {out.relative_to(_PROJECT_ROOT)}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dates", type=int, default=4)
    ap.add_argument("--sample-n", type=int, default=400, help="每交易日随机采样股票数 (0=全 universe)")
    ap.add_argument("--end-date", default=None)
    a = ap.parse_args()
    logging.basicConfig(level=logging.WARNING)
    run(a.dates, a.sample_n, a.end_date)
