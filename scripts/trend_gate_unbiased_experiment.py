"""无偏对照实验 — 决定 spec 是否需要 (writing-plans 前的 30 分钟实验).

对抗审查证伪了 spec 的动机叙事 (候选宇宙混淆 / 选择偏差 / Q5 仍正). 本脚本用
factor_audit 的全 universe 涨停候选日口径 (无选择偏差) + 截止涨停日切片 (无 look-ahead)
回答两个决定性问题:

  实验 1 — trend 全 universe IC: score_trend_strategy 的 confidence 在全 universe
           涨停候选日上是否区分 T+10 收益? 方向是正是反?
           (推荐池 n=175 显示反向, 但那是 MR family 同构的选择偏差伪象)

  实验 2 — trigger_strength gate 增量 alpha: 全 universe 涨停候选日上, strength>=gate
           vs <gate 的 T+10 是否分离? gate 有没有增量 alpha?
           (+3.55% 来自 BTST full_market 路径, 但那是不同候选宇宙 — 本实验在同池测 gate)

判据: 复用 factor_audit 的 _agg_returns / Wilson CI / exec 测度 (剔除次日续涨停).
特征契约: trend 用生产 score_trend_strategy; strength 分量用生产 btst 纯函数.

只读 data/price_cache; 结果落 data/reports/trend_gate_unbiased_experiment.json.
"""
from __future__ import annotations

import json
import math
import sys
import time
from collections import defaultdict
from pathlib import Path
from statistics import mean, median

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.backtest_paper_loop import _load_all_prices  # noqa: E402
from scripts.factor_audit import _agg_returns, _time_block_split  # noqa: E402
from src.screening.offensive.execution_adjuster import is_limit_up_unbuyable_next_day  # noqa: E402
from src.screening.offensive.price_returns import chained_return_pct  # noqa: E402
from src.screening.offensive.setups.btst_breakout import (  # noqa: E402
    _board_quality_score,
    _compute_limit_up_streak,
    _compute_low_vol_score,
    _compute_trend_vol_scores,
    _compute_volume_score,
)
from src.screening.strategy_scorer import score_trend_strategy  # noqa: E402
from src.tools.ashare_board_utils import (  # noqa: E402
    limit_up_cap_pct_for_ticker,
    limit_up_pct_for_ticker,
)

REPORT_DIR = Path("data/reports")
T_HORIZON = 10
GATE_THRESHOLD = 0.50  # _MIN_TRIGGER_STRENGTH (daily_action.py)
MIN_HISTORY = 200  # score_trend_strategy 需要 200 日 EMA


def _wilson(wins: int, n: int) -> list[float]:
    if n == 0:
        return [0.0, 0.0]
    p = wins / n
    z = 1.96
    denom = 1 + z * z / n
    c = (p + z * z / (2 * n)) / denom
    m = (z / denom) * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return [round(max(0, c - m), 4), round(min(1, c + m), 4)]


def _bucket_stats(values_returns: dict) -> dict:
    """values_returns: {bucket_key: [t10 returns]}."""
    out = {}
    for k in sorted(values_returns, key=lambda x: (len(x), x)):
        rets = values_returns[k]
        out[k] = _agg_returns(rets, len(rets))
    return out


def scan() -> list[dict]:
    """全 universe 涨停候选日 scan, 算 trend confidence + strength 分量 + T+10."""
    prices_by = _load_all_prices()
    signals: list[dict] = []
    n_tickers = len(prices_by)
    for ti, (ticker, df) in enumerate(prices_by.items()):
        if ti % 300 == 0:
            print(f"  scan 进度 {ti}/{n_tickers} tickers, signals={len(signals)}", flush=True)
        df = df.sort_values("date").reset_index(drop=True)
        if "pct_change" not in df.columns or "close" not in df.columns:
            continue
        pct = pd.to_numeric(df["pct_change"], errors="coerce").values
        close = pd.to_numeric(df["close"], errors="coerce").values
        open_ = pd.to_numeric(df["open"], errors="coerce").values if "open" in df.columns else close
        date_str = df["date_str"].values
        limit_up_pct = limit_up_pct_for_ticker(ticker)
        limit_up_cap = limit_up_cap_pct_for_ticker(ticker)
        n = len(df)

        for i in range(n):
            p = pct[i]
            if math.isnan(p) or p < limit_up_pct or p > limit_up_cap + 0.5:
                continue
            ref_idx = i - 5
            pre_window = df.iloc[ref_idx:i] if ref_idx >= 0 else df.iloc[0:0]
            _, squeeze_score = _compute_trend_vol_scores(pre_window, df, i)
            volume_score = _compute_volume_score(df, i)
            low_vol_score = _compute_low_vol_score(df, i)
            board_score = _board_quality_score(ticker)
            # range 分量 (strength 第5分量)
            range_score = 0.0
            high = pd.to_numeric(df["high"], errors="coerce").values if "high" in df.columns else close
            low = pd.to_numeric(df["low"], errors="coerce").values if "low" in df.columns else close
            if i >= 1:
                prev_c = close[i - 1]
                if math.isfinite(prev_c) and prev_c > 0 and math.isfinite(high[i]) and math.isfinite(low[i]) and high[i] >= low[i]:
                    range_pct = (high[i] - low[i]) / prev_c
                    # range_score: 池内 A/B 验证过的倒U甜区映射 (近似生产)
                    if range_pct < 0.04 or range_pct >= 0.14:
                        range_score = 0.0
                    elif 0.06 <= range_pct < 0.09:
                        range_score = 1.0
                    elif 0.04 <= range_pct < 0.06 or 0.09 <= range_pct < 0.11:
                        range_score = 0.5
                    else:  # [0.11, 0.14)
                        range_score = 0.25

            # trigger_strength proxy: 5 分量等权 + energy_bonus (squeeze>=1 AND low_vol>=0.75)
            strength = 0.20 * (board_score + low_vol_score + squeeze_score + volume_score + range_score)
            if squeeze_score >= 1.0 and low_vol_score >= 0.75:
                strength = min(1.0, strength + 0.10)

            # trend confidence: 截止涨停日切片 (无 look-ahead). 需要 >=200 历史.
            trend_dir, trend_conf = None, None
            if i + 1 >= MIN_HISTORY:
                try:
                    sig = score_trend_strategy(df.iloc[:i + 1], ticker=ticker)
                    trend_dir = float(sig.direction)
                    trend_conf = float(sig.confidence)
                except Exception:
                    trend_dir, trend_conf = None, None

            unbuyable = is_limit_up_unbuyable_next_day(df, i, ticker)
            entry_idx, exit_idx = i + 1, i + T_HORIZON
            ret = None
            if entry_idx < n and exit_idx < n:
                ep = open_[entry_idx]
                if math.isnan(ep) or ep <= 0:
                    ep = close[entry_idx]
                xp = close[exit_idx]
                if not (math.isnan(ep) or math.isnan(xp) or ep <= 0):
                    ret = xp / ep - 1.0

            signals.append({
                "ticker": ticker,
                "date": str(date_str[i]),
                "trend_dir": trend_dir,
                "trend_conf": trend_conf,
                "strength": round(strength, 4),
                "unbuyable_next_day": bool(unbuyable),
                "t10_return": (round(ret, 5) if ret is not None else None),
            })
    return signals


def experiment1_trend_ic(signals: list[dict]) -> dict:
    """实验1: trend confidence 全 universe 分桶 -> T+10 (exec 测度, 无选择偏差)."""
    exe = [s for s in signals if not s["unbuyable_next_day"] and s["trend_conf"] is not None and s["t10_return"] is not None]
    exe.sort(key=lambda s: s["trend_conf"])
    n = len(exe)
    print(f"\n[实验1] trend 全 universe IC (exec 测度, n={n})")
    if n < 100:
        return {"note": f"样本不足 n={n}"}
    # 五分位
    buckets = defaultdict(list)
    for j, s in enumerate(exe):
        q = min(4, j * 5 // n)
        buckets[f"Q{q+1}"].append(s["t10_return"])
    stats = _bucket_stats(buckets)
    # 也按 direction 分 (多头/空头/中性)
    by_dir = defaultdict(list)
    for s in exe:
        d = s["trend_dir"]
        key = "long(+1)" if d > 0 else "short(-1)" if d < 0 else "neutral(0)"
        by_dir[key].append(s["t10_return"])
    # Spearman(conf, return)
    confs = [s["trend_conf"] for s in exe]
    rets = [s["t10_return"] for s in exe]
    rho = float(pd.Series(confs).rank().corr(pd.Series(rets).rank()))
    # 跨窗同向 (前半 vs 后半)
    first, second, mid = _time_block_split(exe)
    rho1 = float(pd.Series([s["trend_conf"] for s in first]).rank().corr(pd.Series([s["t10_return"] for s in first]).rank())) if len(first) > 30 else float("nan")
    rho2 = float(pd.Series([s["trend_conf"] for s in second]).rank().corr(pd.Series([s["t10_return"] for s in second]).rank())) if len(second) > 30 else float("nan")
    print(f"  Spearman(trend_conf, T+10) = {rho:+.4f}  跨窗: H1={rho1:+.4f} H2={rho2:+.4f}")
    for k, st in stats.items():
        print(f"  {k}: n={st['n_with_t10_return']} WR={st['winrate']*100:.1f}% median={st['median_t10_return']:+.2f}%")
    print("  按方向:")
    for k, st in _bucket_stats(by_dir).items():
        print(f"  {k}: n={st['n_with_t10_return']} WR={st['winrate']*100:.1f}% median={st['median_t10_return']:+.2f}%")
    direction = "正IC(trend高→收益高)" if rho > 0.02 else "反IC(trend高→收益低)" if rho < -0.02 else "无IC"
    # NS-4 避坑: 不盲目翻转 direction (short 子集 54% WR 是真信号, 翻转会污染).
    # 精确诊断 long(+1) 子集内部 confidence 是否区分 T+10 (long 占 85%, 是主战场).
    long_exe = [s for s in exe if s["trend_dir"] is not None and s["trend_dir"] > 0]
    long_rho = float("nan")
    long_cross = "n/a"
    if len(long_exe) > 100:
        long_rho = float(pd.Series([s["trend_conf"] for s in long_exe]).rank().corr(pd.Series([s["t10_return"] for s in long_exe]).rank()))
        lf, ls, _ = _time_block_split(long_exe)
        lr1 = float(pd.Series([s["trend_conf"] for s in lf]).rank().corr(pd.Series([s["t10_return"] for s in lf]).rank())) if len(lf) > 30 else float("nan")
        lr2 = float(pd.Series([s["trend_conf"] for s in ls]).rank().corr(pd.Series([s["t10_return"] for s in ls]).rank())) if len(ls) > 30 else float("nan")
        long_cross = f"H1={lr1:+.4f} H2={lr2:+.4f} {'同向' if (lr1 > 0) == (lr2 > 0) else '不一致'}"
    print(f"\n  [long子集内部诊断] n={len(long_exe)} Spearman(conf,T+10)={long_rho:+.4f} 跨窗:{long_cross}")
    long_verdict = ("long内部正IC" if long_rho > 0.02 else "long内部反IC" if long_rho < -0.02 else "long内部无IC(trend对85%的票无贡献→降权非翻转)")
    return {
        "n": n, "spearman_rho": round(rho, 4),
        "half1_rho": round(rho1, 4), "half2_rho": round(rho2, 4),
        "quintile_buckets": stats, "by_direction": _bucket_stats(by_dir),
        "long_subset_n": len(long_exe), "long_subset_rho": (round(long_rho, 4) if not math.isnan(long_rho) else None),
        "long_subset_verdict": long_verdict,
        "verdict": f"全{direction}; long子集: {long_verdict}",
    }


def experiment2_gate_alpha(signals: list[dict]) -> dict:
    """实验2: trigger_strength gate>=0.50 vs <0.50 的 T+10 差异 (全 universe, 同池)."""
    exe = [s for s in signals if not s["unbuyable_next_day"] and s["t10_return"] is not None]
    print(f"\n[实验2] trigger_strength gate 增量 alpha (exec 测度, n={len(exe)}, gate={GATE_THRESHOLD})")
    if len(exe) < 100:
        return {"note": f"样本不足 n={len(exe)}"}
    passed = [s["t10_return"] for s in exe if s["strength"] >= GATE_THRESHOLD]
    blocked = [s["t10_return"] for s in exe if s["strength"] < GATE_THRESHOLD]
    wp = _agg_returns(passed, len(passed))
    wb = _agg_returns(blocked, len(blocked))
    # Wilson 非重叠检验
    sep = wp["wilson_ci95"][0] > wb["wilson_ci95"][1]
    print(f"  gate>=0.50 (通过): n={len(passed)} WR={wp['winrate']*100:.1f}% median={wp['median_t10_return']:+.2f}% mean={wp['mean_t10_return']:+.2f}% CI={wp['wilson_ci95']}")
    print(f"  gate< 0.50 (拦截): n={len(blocked)} WR={wb['winrate']*100:.1f}% median={wb['median_t10_return']:+.2f}% mean={wb['mean_t10_return']:+.2f}% CI={wb['wilson_ci95']}")
    print(f"  Wilson 非重叠分离: {sep}")
    print(f"  median spread (通过-拦截): {(wp['median_t10_return']-wb['median_t10_return'])*100:+.2f}pp")
    return {
        "gate_threshold": GATE_THRESHOLD,
        "passed": wp, "blocked": wb,
        "wilson_separated": bool(sep),
        "median_spread_pp": round((wp["median_t10_return"] - wb["median_t10_return"]) * 100, 2),
        "verdict": ("gate有增量alpha(通过组显著更好)" if sep and wp["median_t10_return"] > wb["median_t10_return"]
                    else "gate无增量alpha(通过组不显著更好或更差)"),
    }


def main() -> None:
    t0 = time.time()
    print("=== 无偏对照实验: trend IC + gate alpha (全 universe, 无选择偏差) ===")
    signals = scan()
    exe_n = sum(1 for s in signals if not s["unbuyable_next_day"] and s["t10_return"] is not None)
    print(f"\nscan 完成: {len(signals)} 涨停候选日, exec+有T+10: {exe_n}, 耗时 {time.time()-t0:.0f}s")
    e1 = experiment1_trend_ic(signals)
    e2 = experiment2_gate_alpha(signals)
    report = {
        "experiment1_trend_ic": e1,
        "experiment2_gate_alpha": e2,
        "meta": {
            "exec_n": exe_n,
            "total_signals": len(signals),
            "verdict_summary": (
                "trend正IC → 剔除前提崩塌; " if e1.get("spearman_rho", 0) > 0.02 else
                "trend反IC → 剔除前提成立; " if e1.get("spearman_rho", 0) < -0.02 else "trend无IC; "
            ) + (
                "gate有增量alpha → 流入分数动机待验" if e2.get("wilson_separated") else "gate无增量alpha → 流入分数动机崩塌"
            ),
        },
    }
    REPORT_DIR.mkdir(exist_ok=True)
    out = REPORT_DIR / "trend_gate_unbiased_experiment.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"\n=== 结论 ===\n{report['meta']['verdict_summary']}")
    print(f"报告: {out} (耗时 {time.time()-t0:.0f}s)")


if __name__ == "__main__":
    main()
