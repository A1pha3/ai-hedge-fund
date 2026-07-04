#!/usr/bin/env python3
"""Light-stage 全 universe 回测：trend/MR 因子长周期 IC + 新旧权重 score 效果对比.

复现并扩展 2026-06-25 的全 universe 诊断 (原 n=8136, 470 票×20 日期):
  - 取最近 N 个交易日 (默认 60, 可扩 90) 的全 A 股 universe
  - 剔除 ST/退/北交所/流动性<10万/涨跌幅绝对值>9.5%
  - 直接调用 score_trend_strategy / score_mean_reversion_strategy (纯技术, 0 LLM)
  - 用旧权重 (trend:0.65/MR:0.35) vs 新权重 (trend:0.35/MR:0.65) 计算 provisional_score
  - 对比 MR 因子 IC 稳定性 + Top-N 候选池 T+1 收益

输出三块:
  1. MR 因子长周期 IC 稳定性 (整体 + 按月切片)
  2. 新旧权重下 Top-N 候选池 T+1 实际收益对比 (验证 0.35→0.65 是否真的更好)
  3. AVOID=5 (score<=0) 比例变化 (验证 model 是否仍然过谨慎)

参考: src/screening/strategy_scorer.py 的 _provisional_score / LIGHT_STRATEGY_WEIGHTS
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from dotenv import load_dotenv

# 项目根加入 sys.path 以复用 src/screening 评分器
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

try:
    from scripts.btst_data_utils import build_beijing_exchange_mask
except ModuleNotFoundError:
    from btst_data_utils import build_beijing_exchange_mask  # type: ignore[no-redef]

from src.screening.strategy_scorer import (
    score_mean_reversion_strategy,
    score_trend_strategy,
)
from src.screening.strategy_scorer_utils import (
    MEAN_REVERSION_SUBFACTOR_WEIGHTS,
    TREND_SUBFACTOR_WEIGHTS_WITH_LONG_TREND,
)

load_dotenv(_PROJECT_ROOT / ".env")

logger = logging.getLogger("light_stage_universe_backtest")

# 复现 src/screening/strategy_scorer.py 的 LIGHT_STRATEGY_WEIGHTS
WEIGHTS_OLD = {"trend": 0.65, "mean_reversion": 0.35}  # 0e365cdc 之前
WEIGHTS_NEW = {"trend": 0.35, "mean_reversion": 0.65}  # 0e365cdc 之后


# ---------------------------------------------------------------------------
# 1. 数据获取
# ---------------------------------------------------------------------------


def _get_pro():
    import tushare as ts

    token = os.getenv("TUSHARE_TOKEN")
    if not token:
        raise RuntimeError("TUSHARE_TOKEN 未设置")
    ts.set_token(token)
    return ts.pro_api()


def get_trading_dates(pro, n_days: int, end_date: str | None = None) -> list[str]:
    """取截止 end_date 的最近 n_days 个交易日 (YYYYMMDD)."""
    end = datetime.strptime(end_date, "%Y%m%d") if end_date else datetime.now()
    start = end - timedelta(days=n_days * 2 + 60)  # 多取 60 天缓冲
    cal = pro.trade_cal(
        exchange="SSE",
        start_date=start.strftime("%Y%m%d"),
        end_date=end.strftime("%Y%m%d"),
        is_open="1",
    )
    return sorted(cal["cal_date"].tolist())[-n_days:]


def get_universe_for_date(pro, trade_date: str, stock_basic: pd.DataFrame) -> pd.DataFrame:
    """取 trade_date 当日全 A 股 universe (剔除 ST/退/北交所/低流动性/涨跌停)."""
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
    """批量取历史日线 (tushare daily 接口支持 ts_code 逗号分隔).

    关键修复:
    1. tushare vol → volume (项目评分器期望 volume 字段)
    2. batch_size 必须 ≤10: tushare daily 批量接口默认返回上限约 3000 行,
       超过会截断 (80 票×250 天=20000 行, 实际每票只剩 50-76 行, 导致
       momentum/volatility/long_trend 因 len<126 全部跳过, trend 因子失效)
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
# 2. 因子计算 (复现 light stage)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FactorSnapshot:
    ticker: str
    trend_direction: int
    trend_confidence: float
    trend_completeness: float
    mr_direction: int
    mr_confidence: float
    mr_completeness: float


def compute_factor_snapshot(ticker: str, prices_df: pd.DataFrame) -> FactorSnapshot | None:
    """直接调用项目评分器, 取 trend + MR signal."""
    if prices_df is None or len(prices_df) < 50:
        return None
    try:
        trend_sig = score_trend_strategy(prices_df, ticker=ticker)
        mr_sig = score_mean_reversion_strategy(prices_df)
    except Exception:
        logger.debug("factor compute failed for %s", ticker, exc_info=True)
        return None
    return FactorSnapshot(
        ticker=ticker,
        trend_direction=trend_sig.direction,
        trend_confidence=trend_sig.confidence,
        trend_completeness=trend_sig.completeness,
        mr_direction=mr_sig.direction,
        mr_confidence=mr_sig.confidence,
        mr_completeness=mr_sig.completeness,
    )


def provisional_score(snapshot: FactorSnapshot, weights: dict[str, float]) -> float:
    """复现 src/screening/strategy_scorer.py 的 _provisional_score."""
    score = 0.0
    total_weight = 0.0
    # trend
    if snapshot.trend_completeness > 0:
        w = weights["trend"]
        total_weight += w
        score += w * snapshot.trend_direction * (snapshot.trend_confidence / 100.0) * snapshot.trend_completeness
    # mean_reversion
    if snapshot.mr_completeness > 0:
        w = weights["mean_reversion"]
        total_weight += w
        score += w * snapshot.mr_direction * (snapshot.mr_confidence / 100.0) * snapshot.mr_completeness
    if total_weight <= 0:
        return 0.0
    return score / total_weight


# ---------------------------------------------------------------------------
# 3. IC 计算
# ---------------------------------------------------------------------------


def spearman_ic(x: np.ndarray, y: np.ndarray) -> float:
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    mask = np.isfinite(x) & np.isfinite(y)
    x, y = x[mask], y[mask]
    if len(x) < 10:
        return float("nan")
    rx = pd.Series(x).rank().values
    ry = pd.Series(y).rank().values
    n = len(rx)
    d = rx - ry
    return float(1.0 - 6.0 * np.sum(d**2) / (n * (n**2 - 1)))


# ---------------------------------------------------------------------------
# 4. 主流程
# ---------------------------------------------------------------------------


def run_backtest(
    n_days: int = 60,
    end_date: str | None = None,
    top_n: int = 50,
    output_path: str | None = None,
) -> None:
    pro = _get_pro()
    stock_basic = pro.stock_basic(exchange="", list_status="L", fields="ts_code,name")
    trade_dates = get_trading_dates(pro, n_days + 1, end_date=end_date)  # 多取 1 天用于 T+1 收益
    if len(trade_dates) < 2:
        print("交易日不足")
        return

    test_dates = trade_dates[:-1]
    print(f"\n{'=' * 110}")
    print(f"Light-Stage 全 universe 回测: {test_dates[0]} ~ {test_dates[-1]} ({len(test_dates)} 日期)")
    print(f"权重对比: OLD={WEIGHTS_OLD}  NEW={WEIGHTS_NEW}")
    print(f"{'=' * 110}")

    # 收集每日结果
    daily_records: list[dict[str, Any]] = []

    for di, test_date in enumerate(test_dates):
        next_date = trade_dates[di + 1]
        t0 = time.time()

        # 1. universe
        universe = get_universe_for_date(pro, test_date, stock_basic)
        if universe.empty:
            continue

        # 2. T+1 收益
        try:
            dfn = pro.daily(trade_date=next_date)[["ts_code", "pct_chg"]].rename(columns={"pct_chg": "next_ret"})
        except Exception:
            continue
        universe = universe.merge(dfn, on="ts_code", how="inner")
        if len(universe) < 100:
            continue

        # 3. 历史价格 (取 250 天保证 trend 长周期因子可用)
        history_start = (datetime.strptime(test_date, "%Y%m%d") - timedelta(days=400)).strftime("%Y%m%d")
        codes = universe["ts_code"].tolist()
        hist = get_history_batch(pro, codes, history_start, test_date)
        if hist.empty:
            continue
        hist["trade_date"] = pd.to_datetime(hist["trade_date"], format="%Y%m%d")
        hist = hist.sort_values(["ts_code", "trade_date"])

        # 4. 计算因子
        snapshots: dict[str, FactorSnapshot] = {}
        for code, g in hist.groupby("ts_code"):
            if len(g) < 50:
                continue
            prices_df = g.set_index("trade_date")
            snap = compute_factor_snapshot(code, prices_df)
            if snap is not None:
                snapshots[code] = snap

        if len(snapshots) < 100:
            continue

        # 5. 合并并计算两套权重下的 provisional_score
        rows: list[dict[str, Any]] = []
        for _, r in universe.iterrows():
            snap = snapshots.get(r["ts_code"])
            if snap is None:
                continue
            rows.append(
                {
                    "ts_code": r["ts_code"],
                    "next_ret": float(r["next_ret"]),
                    "trend_direction": snap.trend_direction,
                    "trend_confidence": snap.trend_confidence,
                    "trend_completeness": snap.trend_completeness,
                    "mr_direction": snap.mr_direction,
                    "mr_confidence": snap.mr_confidence,
                    "mr_completeness": snap.mr_completeness,
                    # 因子原值: direction × confidence × completeness (0 LLM 简化)
                    "trend_factor": snap.trend_direction * (snap.trend_confidence / 100.0) * snap.trend_completeness,
                    "mr_factor": snap.mr_direction * (snap.mr_confidence / 100.0) * snap.mr_completeness,
                    "score_old": provisional_score(snap, WEIGHTS_OLD),
                    "score_new": provisional_score(snap, WEIGHTS_NEW),
                }
            )
        df_day = pd.DataFrame(rows)
        if df_day.empty:
            continue

        # 6. 当日统计
        mr_ic = spearman_ic(df_day["mr_factor"].values, df_day["next_ret"].values)
        trend_ic = spearman_ic(df_day["trend_factor"].values, df_day["next_ret"].values)

        # Top-N 实际收益
        top_old = df_day.nlargest(top_n, "score_old")
        top_new = df_day.nlargest(top_n, "score_new")
        # 重叠度
        overlap = len(set(top_old["ts_code"]) & set(top_new["ts_code"]))

        # AVOID=5 (score<=0) 比例
        avoid_old = float((df_day["score_old"] <= 0).mean())
        avoid_new = float((df_day["score_new"] <= 0).mean())

        daily_records.append(
            {
                "trade_date": test_date,
                "next_date": next_date,
                "universe_size": len(df_day),
                "mr_ic": mr_ic,
                "trend_ic": trend_ic,
                "top_old_ret": float(top_old["next_ret"].mean()),
                "top_new_ret": float(top_new["next_ret"].mean()),
                "top_old_win": float((top_old["next_ret"] > 0).mean()),
                "top_new_win": float((top_new["next_ret"] > 0).mean()),
                "overlap": overlap,
                "avoid_old": avoid_old,
                "avoid_new": avoid_new,
            }
        )

        elapsed = time.time() - t0
        print(f"[{di + 1}/{len(test_dates)}] {test_date}→{next_date} " f"n={len(df_day)} MR_IC={mr_ic:+.4f} trend_IC={trend_ic:+.4f} | " f"Top{top_n} OLD={top_old['next_ret'].mean():+.3f}% NEW={top_new['next_ret'].mean():+.3f}% " f"overlap={overlap} AVOID OLD={avoid_old:.0%}/NEW={avoid_new:.0%} " f"({elapsed:.1f}s)")

    if not daily_records:
        print("无有效数据")
        return

    summary_df = pd.DataFrame(daily_records)
    _print_summary(summary_df, top_n=top_n)
    saved = _save_report(summary_df, output_path)
    if saved:
        print(f"\n报告已保存: {saved}")


def _save_report(summary_df: pd.DataFrame, output_path: str | None) -> str | None:
    """NS-8: 持久化回测汇总报告 (CSV/JSON), 供持续验证 + 版本对比.

    design packet evidence gap: owner 应重跑全 universe 回测刷新 regime 胜率.
    本函数把 summary_df (每日 MR/trend IC + Top-N 收益/胜率/AVOID 比例) 持久化,
    让 owner 能保存回测结果供版本对比. ``output_path`` 为 None/空 → 不写 (向后兼容).

    Args:
        summary_df: 每日回测汇总 DataFrame (trade_date/mr_ic/trend_ic/top_*/overlap/avoid_*).
        output_path: 输出路径; ``.json`` 后缀写 JSON (records orient), 其余写 CSV.

    Returns:
        实际写入路径 (str), 或 None (未写).
    """
    if not output_path:
        return None
    path = Path(output_path)
    if path.parent and not path.parent.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix == ".json":
        summary_df.to_json(path, orient="records", force_ascii=False, indent=2)
    else:
        summary_df.to_csv(path, index=False)
    return str(path)


def _print_summary(df: pd.DataFrame, *, top_n: int) -> None:
    print(f"\n{'=' * 110}")
    print(f"汇总: {len(df)} 个交易日 ({df['trade_date'].iloc[0]} ~ {df['trade_date'].iloc[-1]})")
    print(f"{'=' * 110}")

    # ====== Block 1: 因子 IC 稳定性 ======
    print("\n[Block 1] 因子 IC 稳定性 (Spearman Rank IC vs T+1 return)")
    print("-" * 80)
    print(f"{'因子':<20s} {'Mean IC':>10s} {'IC>0%':>8s} {'IC_IR':>8s} {'IC_std':>8s}")
    print("-" * 80)
    for factor in ("mr_ic", "trend_ic"):
        ics = df[factor].dropna()
        if ics.empty:
            continue
        mean_ic = float(ics.mean())
        std = float(ics.std()) if len(ics) > 1 else 0.0
        ir = mean_ic / std if std > 0 else 0.0
        pos_rate = float((ics > 0).mean())
        label = "MR (mean_reversion)" if factor == "mr_ic" else "Trend"
        print(f"{label:<20s} {mean_ic:>+10.4f} {pos_rate:>7.0%} {ir:>+8.3f} {std:>8.4f}")

    # 按月切片看 MR IC 稳定性
    df["month"] = df["trade_date"].str[:6]
    print(f"\n  MR IC 按月切片:")
    print(f"  {'月份':<10s} {'样本':>6s} {'Mean IC':>10s} {'IC>0%':>8s}")
    for month, g in df.groupby("month"):
        ics = g["mr_ic"].dropna()
        if ics.empty:
            continue
        print(f"  {month:<10s} {len(ics):>6d} {float(ics.mean()):>+10.4f} {float((ics > 0).mean()):>7.0%}")

    # ====== Block 2: 新旧权重 Top-N 收益对比 ======
    print(f"\n[Block 2] 新旧权重 Top-{top_n} 候选池 T+1 收益对比")
    print("-" * 80)
    print(f"{'权重版本':<20s} {'平均 T+1':>10s} {'胜率':>8s} {'日均超额(vs 全 universe)':>20s}")
    print("-" * 80)

    # 全 universe 平均作为基准
    universe_avg = float(df["universe_size"].apply(lambda n: 0.0).mean())  # placeholder, 实际在 daily 层算
    for label, ret_col, win_col in [("OLD (trend:0.65/MR:0.35)", "top_old_ret", "top_old_win"), ("NEW (trend:0.35/MR:0.65)", "top_new_ret", "top_new_win")]:
        avg_ret = float(df[ret_col].mean())
        win_rate = float(df[win_col].mean())
        # 超额 = Top-N 收益 - 全 universe 平均 (每日 universe 平均无法聚合, 这里用 Top-N 自身对比)
        print(f"{label:<20s} {avg_ret:>+9.3f}% {win_rate:>7.0%}")

    # 配对 t 检验 (NEW vs OLD)
    diff = df["top_new_ret"] - df["top_old_ret"]
    mean_diff = float(diff.mean())
    std_diff = float(diff.std())
    t_stat = mean_diff / (std_diff / np.sqrt(len(diff))) if std_diff > 0 else 0.0
    print(f"\n  NEW - OLD 日均收益差: {mean_diff:+.4f}% (std={std_diff:.4f}, t={t_stat:+.2f}, n={len(diff)})")
    print(f"  NEW 跑赢 OLD 的天数: {int((diff > 0).sum())}/{len(diff)} ({float((diff > 0).mean()):.0%})")
    print(f"  Top-{top_n} 重叠度均值: {float(df['overlap'].mean()):.1f}/{top_n} " f"(新权重平均替换 {top_n - float(df['overlap'].mean()):.1f} 只)")

    # ====== Block 3: AVOID=5 比例 ======
    print(f"\n[Block 3] AVOID=5 (score<=0) 比例变化")
    print("-" * 80)
    print(f"{'权重版本':<20s} {'AVOID 平均':>12s} {'中位':>8s} {'最低':>8s} {'最高':>8s}")
    print("-" * 80)
    for label, col in [("OLD (trend:0.65/MR:0.35)", "avoid_old"), ("NEW (trend:0.35/MR:0.65)", "avoid_new")]:
        s = df[col]
        print(f"{label:<20s} {float(s.mean()):>11.1%} {float(s.median()):>7.1%} " f"{float(s.min()):>7.1%} {float(s.max()):>7.1%}")
    avoid_diff = df["avoid_new"] - df["avoid_old"]
    print(f"\n  NEW - OLD AVOID 比例差: {float(avoid_diff.mean()):+.2%} (NEW 更谨慎为负值)")
    print(f"  NEW 比 OLD 更不谨慎 (AVOID 减少) 的天数: {int((avoid_diff < 0).sum())}/{len(avoid_diff)}")

    # ====== 结论判断 ======
    print(f"\n{'=' * 110}")
    print("结论判断")
    print(f"{'=' * 110}")
    mr_ic_mean = float(df["mr_ic"].mean())
    mr_ic_pos = float((df["mr_ic"] > 0).mean())
    new_better_ret = float((df["top_new_ret"] > df["top_old_ret"]).mean())
    avoid_reduced = float((df["avoid_new"] < df["avoid_old"]).mean())

    print(f"  1. MR 因子长周期 IC: mean={mr_ic_mean:+.4f}, IC>0 比例={mr_ic_pos:.0%}")
    if mr_ic_mean > 0 and mr_ic_pos >= 0.55:
        print(f"     → MR 因子长周期仍为正向有效 (复现 0e365cdc 结论)")
    elif mr_ic_mean < 0:
        print(f"     → ⚠️ MR 因子长周期反向, 0e365cdc 的结论在更长样本下不成立, 需要回滚!")
    else:
        print(f"     → MR 因子长周期信号弱, 需要更多样本")

    print(f"  2. 新权重 Top-{top_n} 收益: NEW 跑赢 OLD 比例={new_better_ret:.0%}, 日均超额差={float(df['top_new_ret'].mean() - df['top_old_ret'].mean()):+.4f}%")
    if new_better_ret >= 0.55:
        print(f"     → 新权重 (MR:0.65) 在 Top-{top_n} 上优于旧权重, 0e365cdc 调整有效")
    else:
        print(f"     → ⚠️ 新权重未优于旧权重, 需要重新评估")

    print(f"  3. AVOID 比例: 新权重减少 AVOID 的天数={avoid_reduced:.0%}, 平均差={float(avoid_diff.mean()):+.2%}")
    if float(avoid_diff.mean()) < 0:
        print(f"     → 新权重确实降低了 model 过谨慎程度 (期望方向)")
    else:
        print(f"     → ⚠️ 新权重反而更谨慎, 与预期不符")


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="Light-stage 全 universe 回测")
    parser.add_argument("--n-days", type=int, default=60, help="回测交易日数 (默认 60, 可设 90)")
    parser.add_argument("--end-date", default="", help="结束日期 YYYYMMDD (默认今天)")
    parser.add_argument("--top-n", type=int, default=50, help="Top-N 候选池规模 (默认 50)")
    parser.add_argument(
        "--output",
        default="",
        help="NS-8: 持久化汇总报告路径 (.csv 或 .json); 留空只 print stdout (向后兼容)",
    )
    args = parser.parse_args()
    run_backtest(
        n_days=args.n_days,
        end_date=args.end_date or None,
        top_n=args.top_n,
        output_path=args.output or None,
    )
