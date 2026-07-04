#!/usr/bin/env python3
"""Trend sub-factor direction 诊断 (基于 light-stage 全 universe 回测).

目标: 定位是哪个 trend sub-factor (ema_alignment / adx_strength / momentum /
volatility / long_trend_alignment) 的 direction 判定把 trend 信号压制了.

对每个交易日:
  1. 取全 universe, 调 score_trend_strategy 拿到 sub_factors dict
  2. 统计每个 sub-factor 的 direction 分布 (-1 / 0 / +1)
  3. 按 sub-factor × direction 分组, 算 T+1 平均收益
  4. 如果某 sub-factor direction=0 占比高, 且这些票 T+1 不差 → 阈值设错, 该松绑

复用 _backtest_light_stage_universe.py 的数据获取逻辑 (重新跑, 不依赖中间文件).
"""

from __future__ import annotations

import logging
import os
import sys
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from dotenv import load_dotenv

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

try:
    from scripts.btst_data_utils import build_beijing_exchange_mask
except ModuleNotFoundError:
    from btst_data_utils import build_beijing_exchange_mask  # type: ignore[no-redef]

from src.screening.strategy_scorer import score_trend_strategy

load_dotenv(_PROJECT_ROOT / ".env")

logger = logging.getLogger("trend_subfactor_diag")

# 关注的 trend sub-factors (顺序固定)
TREND_SUBFACTORS = [
    "ema_alignment",
    "adx_strength",
    "momentum",
    "volatility",
    "long_trend_alignment",
]


# ---------------------------------------------------------------------------
# 数据获取 (复用 _backtest_light_stage_universe.py 的逻辑)
# ---------------------------------------------------------------------------


def _get_pro():
    import tushare as ts

    token = os.getenv("TUSHARE_TOKEN")
    if not token:
        raise RuntimeError("TUSHARE_TOKEN 未设置")
    ts.set_token(token)
    return ts.pro_api()


def get_trading_dates(pro, n_days: int, end_date: str | None = None) -> list[str]:
    end = datetime.strptime(end_date, "%Y%m%d") if end_date else datetime.now()
    start = end - timedelta(days=n_days * 2 + 60)
    cal = pro.trade_cal(
        exchange="SSE",
        start_date=start.strftime("%Y%m%d"),
        end_date=end.strftime("%Y%m%d"),
        is_open="1",
    )
    return sorted(cal["cal_date"].tolist())[-n_days:]


def get_universe_for_date(pro, trade_date: str, stock_basic: pd.DataFrame) -> pd.DataFrame:
    df = pro.daily(trade_date=trade_date)
    if df is None or df.empty:
        return pd.DataFrame()
    df = df.merge(stock_basic[["ts_code", "name"]], on="ts_code", how="left")
    df = df[df["amount"] >= 100000]
    df = df[~df["name"].str.contains("ST|退", na=False)]
    df = df[~build_beijing_exchange_mask(df["ts_code"])]
    df = df[df["pct_chg"].between(-9.5, 9.5)]
    return df


def get_history_batch(pro, codes: list[str], start_date: str, end_date: str, batch_size: int = 10) -> pd.DataFrame:
    """批量取历史日线.

    关键修复:
    1. tushare vol → volume (项目评分器期望 volume 字段)
    2. batch_size 必须 ≤10: tushare daily 批量接口默认返回上限约 3000 行,
       超过会截断 (80 票×250 天=20000 行, 实际每票只剩 50-76 行, 导致
       momentum/volatility/long_trend 因 len<126 全部跳过)
    """
    frames: list[pd.DataFrame] = []
    for i in range(0, len(codes), batch_size):
        batch = codes[i : i + batch_size]
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
    # 关键修复: tushare vol → volume, 否则 momentum/volatility sub-factor 全部抛 KeyError
    if "vol" in df.columns and "volume" not in df.columns:
        df = df.rename(columns={"vol": "volume"})
    return df


# ---------------------------------------------------------------------------
# 诊断主流程
# ---------------------------------------------------------------------------


@dataclass
class SubFactorRow:
    ticker: str
    subfactor: str
    direction: int
    confidence: float
    completeness: float
    weight: float
    next_ret: float


def run_diagnosis(n_days: int = 30, end_date: str | None = None) -> None:
    """跑 n_days 个交易日的诊断, 输出 sub-factor direction 分布与 T+1 收益."""
    pro = _get_pro()
    stock_basic = pro.stock_basic(exchange="", list_status="L", fields="ts_code,name")
    trade_dates = get_trading_dates(pro, n_days + 1, end_date=end_date)
    if len(trade_dates) < 2:
        print("交易日不足")
        return
    test_dates = trade_dates[:-1]

    print(f"\n{'=' * 110}")
    print(f"Trend sub-factor direction 诊断: {test_dates[0]} ~ {test_dates[-1]} ({len(test_dates)} 日期)")
    print(f"目标: 定位哪个 sub-factor 把 trend 信号压制 (direction=0 占比高且 T+1 不差)")
    print(f"{'=' * 110}")

    # 累积所有日的记录
    all_rows: list[SubFactorRow] = []
    daily_summary: list[dict[str, Any]] = []

    for di, test_date in enumerate(test_dates):
        next_date = trade_dates[di + 1]
        t0 = time.time()

        universe = get_universe_for_date(pro, test_date, stock_basic)
        if universe.empty:
            continue

        try:
            dfn = pro.daily(trade_date=next_date)[["ts_code", "pct_chg"]].rename(columns={"pct_chg": "next_ret"})
        except Exception:
            continue
        universe = universe.merge(dfn, on="ts_code", how="inner")
        if len(universe) < 100:
            continue

        history_start = (datetime.strptime(test_date, "%Y%m%d") - timedelta(days=400)).strftime("%Y%m%d")
        codes = universe["ts_code"].tolist()
        hist = get_history_batch(pro, codes, history_start, test_date)
        if hist.empty:
            continue
        hist["trade_date"] = pd.to_datetime(hist["trade_date"], format="%Y%m%d")
        hist = hist.sort_values(["ts_code", "trade_date"])

        next_ret_map = dict(zip(universe["ts_code"], universe["next_ret"]))
        day_rows: list[SubFactorRow] = []
        direction_counts: dict[str, dict[int, int]] = {sf: {-1: 0, 0: 0, 1: 0} for sf in TREND_SUBFACTORS}
        # 调试: 统计 prices_df 行数分布
        len_bins = {">=126": 0, "50-126": 0, "<50": 0}

        for code, g in hist.groupby("ts_code"):
            if len(g) < 50:
                len_bins["<50"] += 1
                continue
            if len(g) >= 126:
                len_bins[">=126"] += 1
            else:
                len_bins["50-126"] += 1
            prices_df = g.set_index("trade_date")
            try:
                trend_sig = score_trend_strategy(prices_df, ticker=code)
            except Exception:
                continue
            next_ret = next_ret_map.get(code)
            if next_ret is None or not np.isfinite(next_ret):
                continue

            # sub_factors 是 dict[str, dict], 每个 dict 是 SubFactor.model_dump()
            for sf_name, sf_dump in trend_sig.sub_factors.items():
                if sf_name not in TREND_SUBFACTORS:
                    continue
                direction = int(sf_dump.get("direction", 0))
                confidence = float(sf_dump.get("confidence", 0.0))
                completeness = float(sf_dump.get("completeness", 0.0))
                weight = float(sf_dump.get("weight", 0.0))
                day_rows.append(
                    SubFactorRow(
                        ticker=code,
                        subfactor=sf_name,
                        direction=direction,
                        confidence=confidence,
                        completeness=completeness,
                        weight=weight,
                        next_ret=float(next_ret),
                    )
                )
                direction_counts[sf_name][direction] += 1

        all_rows.extend(day_rows)
        elapsed = time.time() - t0

        # 当日 direction 分布 (简短一行)
        n_stocks = len(set(r.ticker for r in day_rows))
        dist_str = " ".join(f"{sf[:8]}={direction_counts[sf][1]:+d}/{direction_counts[sf][0]}/{direction_counts[sf][-1]:-d}" for sf in TREND_SUBFACTORS)
        print(f"[{di + 1}/{len(test_dates)}] {test_date} n={n_stocks} " f"(len: >126={len_bins['>=126']} 50-126={len_bins['50-126']} <50={len_bins['<50']}) " f"(+1/0/-1: {dist_str}) ({elapsed:.1f}s)")

        daily_summary.append({"trade_date": test_date, "n_stocks": n_stocks, **{f"{sf}_pos": direction_counts[sf][1] for sf in TREND_SUBFACTORS}})

    if not all_rows:
        print("无有效数据")
        return

    _print_diagnosis(all_rows, n_days=len(test_dates))


def _print_diagnosis(rows: list[SubFactorRow], *, n_days: int) -> None:
    df = pd.DataFrame([{"subfactor": r.subfactor, "direction": r.direction, "confidence": r.confidence, "completeness": r.completeness, "weight": r.weight, "next_ret": r.next_ret} for r in rows])

    print(f"\n{'=' * 110}")
    print(f"汇总: {n_days} 个交易日, {len(df)} 条 sub-factor 记录")
    print(f"{'=' * 110}")

    # ====== Block 1: 各 sub-factor direction 分布 ======
    print("\n[Block 1] Trend sub-factor direction 分布")
    print("-" * 100)
    print(f"{'sub-factor':<24s} {'样本':>8s} {'completeness':>12s} {'direction=+1':>14s} {'direction=0':>12s} {'direction=-1':>14s}")
    print("-" * 100)

    for sf in TREND_SUBFACTORS:
        sub = df[df["subfactor"] == sf]
        if sub.empty:
            continue
        n = len(sub)
        # 只统计 completeness>0 的样本 (有效计算)
        valid = sub[sub["completeness"] > 0]
        if valid.empty:
            print(f"{sf:<24s} {n:>8d} {float(sub['completeness'].mean()):>11.1%} {'N/A':>14s} {'N/A':>12s} {'N/A':>14s}")
            continue
        n_valid = len(valid)
        pos_rate = float((valid["direction"] == 1).mean())
        zero_rate = float((valid["direction"] == 0).mean())
        neg_rate = float((valid["direction"] == -1).mean())
        print(f"{sf:<24s} {n:>8d} {float(sub['completeness'].mean()):>11.1%} " f"{pos_rate:>13.1%} {zero_rate:>11.1%} {neg_rate:>13.1%}")

    # ====== Block 2: 各 sub-factor × direction 的 T+1 收益 ======
    print(f"\n[Block 2] sub-factor × direction → T+1 平均收益 (关键诊断)")
    print("-" * 100)
    print(f"{'sub-factor':<24s} {'dir=+1 样本':>12s} {'+1 T+1':>10s} {'dir=0 样本':>12s} {'0 T+1':>10s} {'dir=-1 样本':>12s} {'-1 T+1':>10s}")
    print("-" * 100)

    # 全 universe 基准
    baseline = float(df["next_ret"].mean())
    print(f"{'(全样本基准)':<24s} {len(df):>12d} {baseline:>+9.3f}%")
    print("-" * 100)

    for sf in TREND_SUBFACTORS:
        sub = df[(df["subfactor"] == sf) & (df["completeness"] > 0)]
        if sub.empty:
            continue
        pos = sub[sub["direction"] == 1]
        zero = sub[sub["direction"] == 0]
        neg = sub[sub["direction"] == -1]

        pos_ret = float(pos["next_ret"].mean()) if not pos.empty else float("nan")
        zero_ret = float(zero["next_ret"].mean()) if not zero.empty else float("nan")
        neg_ret = float(neg["next_ret"].mean()) if not neg.empty else float("nan")

        print(f"{sf:<24s} {len(pos):>12d} {pos_ret:>+9.3f}% {len(zero):>12d} {zero_ret:>+9.3f}% {len(neg):>12d} {neg_ret:>+9.3f}%")

    # ====== Block 3: 关键判断 — 哪些 sub-factor 该松绑 ======
    print(f"\n[Block 3] 关键判断 — 哪些 sub-factor 的 direction 判定压制了信号")
    print("-" * 100)

    print(f"\n判定逻辑:")
    print(f"  - 如果 dir=0 占比高 (>40%) 且 dir=0 的 T+1 不差 (≥基准) → 阈值过严, 该松绑")
    print(f"  - 如果 dir=+1 的 T+1 显著 > dir=-1 的 T+1 → 因子有效, 阈值正确")
    print(f"  - 如果 dir=+1 的 T+1 ≈ dir=-1 的 T+1 → 因子失效, 调阈值无用")

    print(f"\n{'sub-factor':<24s} {'dir=0 占比':>10s} {'dir=0 T+1 vs 基准':>18s} {'+1 vs -1 T+1':>14s} {'诊断结论':>20s}")
    print("-" * 100)

    for sf in TREND_SUBFACTORS:
        sub = df[(df["subfactor"] == sf) & (df["completeness"] > 0)]
        if sub.empty:
            continue
        zero_rate = float((sub["direction"] == 0).mean())
        zero = sub[sub["direction"] == 0]
        pos = sub[sub["direction"] == 1]
        neg = sub[sub["direction"] == -1]

        zero_ret = float(zero["next_ret"].mean()) if not zero.empty else float("nan")
        pos_ret = float(pos["next_ret"].mean()) if not pos.empty else float("nan")
        neg_ret = float(neg["next_ret"].mean()) if not neg.empty else float("nan")

        zero_vs_base = zero_ret - baseline if np.isfinite(zero_ret) else float("nan")
        pos_vs_neg = pos_ret - neg_ret if np.isfinite(pos_ret) and np.isfinite(neg_ret) else float("nan")

        # 诊断
        if zero_rate > 0.40 and np.isfinite(zero_vs_base) and zero_vs_base >= 0:
            verdict = "⚠️ 该松绑 (0 占比高且 T+1 不差)"
        elif np.isfinite(pos_vs_neg) and abs(pos_vs_neg) < 0.05:
            verdict = "✗ 因子失效 (调阈值无用)"
        elif np.isfinite(pos_vs_neg) and pos_vs_neg > 0.1:
            verdict = "✓ 因子有效 (阈值正确)"
        else:
            verdict = "? 信号弱, 需进一步看"

        print(f"{sf:<24s} {zero_rate:>9.1%} {zero_vs_base:>+17.3f}% {pos_vs_neg:>+13.3f}% {verdict:>20s}")

    # ====== Block 4: confidence 分布 (辅助判断) ======
    print(f"\n[Block 4] sub-factor confidence 分布 (辅助)")
    print("-" * 100)
    print(f"{'sub-factor':<24s} {'conf 平均':>10s} {'conf 中位':>10s} {'conf<10 占比':>12s} {'conf>50 占比':>12s}")
    print("-" * 100)
    for sf in TREND_SUBFACTORS:
        sub = df[(df["subfactor"] == sf) & (df["completeness"] > 0)]
        if sub.empty:
            continue
        conf = sub["confidence"]
        print(f"{sf:<24s} {float(conf.mean()):>9.2f} {float(conf.median()):>9.2f} " f"{float((conf < 10).mean()):>11.1%} {float((conf > 50).mean()):>11.1%}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    import argparse

    parser = argparse.ArgumentParser(description="Trend sub-factor direction 诊断")
    parser.add_argument("--n-days", type=int, default=30, help="诊断交易日数 (默认 30, 够看分布了)")
    parser.add_argument("--end-date", default="", help="结束日期 YYYYMMDD")
    args = parser.parse_args()
    run_diagnosis(
        n_days=args.n_days,
        end_date=args.end_date or None,
    )
