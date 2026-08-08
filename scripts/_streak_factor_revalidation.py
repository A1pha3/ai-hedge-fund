"""[已被取代 2026-08-08] 本一次性脚本的功能已由通用审计器 scripts/factor_audit.py 覆盖
(streak 是其首个插件特征). 保留仅为溯源; 新复核请用 factor_audit.py streak.

一次性因子复核 (历史存档): streak_bonus: streak_bonus (连板数) 在当前全量数据下是否仍有预测力.

动机 (2026-08-08): streak_bonus=0.04 (7/19 commit 8c7fc078) 当初仅凭 9497 涨停样本
(截至 7/19 数据) 的因子层统计落地, 从未用最新数据复核. 因子会过期 (涨停生态/拥挤度
变化). 本脚本用当前全量 price_cache (1442 只, 至 2026-08-07) 重放所有涨停信号,
按 limit_up_streak 分组统计 T+10 真实收益, 验证 2连板 vs 首板 的 edge 是否仍成立.

口径与原始 9497 统计一致 (price-eligible 涨停):
  limit_up_pct_for_ticker <= pct_change <= limit_up_cap_pct_for_ticker + 0.5
即板块自适应涨停 (主板≥9.5 / 创业科创≥19.5 / 北交≥29), 上界护栏剔除无涨跌幅限制日.
streak 由 _compute_limit_up_streak (价格纯函数) 计算, 与 detect 内一致.

execution-adjusted (对齐 known_distributions / Kelly 先验口径):
  剔除「次日开盘继续涨停 → 实际买不到」的样本 (is_limit_up_unbuyable_next_day).
  不剔会把一字连板妖股的理论涨停收益算进去 —— 幸存者偏差, 虚增 3+连板 E[r].
  streak_bonus 影响的是真实买入决策, 因子复核必须用可买入口径.

只读 data/price_cache; 结果落 data/reports/. 不碰 data/paper_trading*/.

收益口径: T+10 收盘 / T+1 开盘 - 1 (BTST = 涨停次日买入). T+1 开盘优先用真实 open,
缺失回退 close. T+1/T+10 数据不足 (期末附近) 的信号剔除出 T+10 统计但保留计数.
"""
from __future__ import annotations

import json
import math
import sys
import time
from collections import defaultdict
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.backtest_paper_loop import _load_all_prices  # noqa: E402
from src.screening.offensive.execution_adjuster import (  # noqa: E402
    is_limit_up_unbuyable_next_day,
)
from src.screening.offensive.setups.btst_breakout import (  # noqa: E402
    _compute_limit_up_streak,
)
from src.tools.ashare_board_utils import (  # noqa: E402
    limit_up_cap_pct_for_ticker,
    limit_up_pct_for_ticker,
)

OUT_PATH = Path("data/reports/streak_factor_revalidation.json")
T_HORIZON = 10  # T+10 收益 (与 known_distributions/natural_horizon 口径一致)


def _wilson_ci(wins: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval for a win-rate proportion."""
    if n == 0:
        return (0.0, 0.0)
    p = wins / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    margin = (z / denom) * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (max(0.0, center - margin), min(1.0, center + margin))


def scan() -> tuple[list[dict], dict]:
    """扫描全 universe 所有涨停信号, 记录 streak + T+1 open -> T+10 close 收益."""
    prices_by = _load_all_prices()
    signals: list[dict] = []
    n_limitup_days = 0

    for ticker, df in prices_by.items():
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
            if math.isnan(p):
                continue
            # price-eligible 涨停口径 (与原始 9497 统计一致)
            if p < limit_up_pct or p > limit_up_cap + 0.5:
                continue
            n_limitup_days += 1
            streak = _compute_limit_up_streak(df, i, limit_up_pct)

            # execution-adjusted: 次日开盘继续涨停 → 买不到, 剔除 (幸存者偏差护栏)
            unbuyable = is_limit_up_unbuyable_next_day(df, i, ticker)

            # T+1 open -> T+10 close 收益
            entry_idx = i + 1
            exit_idx = i + T_HORIZON
            ret = None
            entry_price = None
            if entry_idx < n and exit_idx < n:
                entry_price = open_[entry_idx]
                if math.isnan(entry_price) or entry_price <= 0:
                    entry_price = close[entry_idx]
                exit_price = close[exit_idx]
                if not (math.isnan(entry_price) or math.isnan(exit_price) or entry_price <= 0):
                    ret = exit_price / entry_price - 1.0

            signals.append(
                {
                    "ticker": ticker,
                    "date": str(date_str[i]),
                    "streak": streak,
                    "pct_change": round(float(p), 3),
                    "unbuyable_next_day": bool(unbuyable),
                    "t10_return": (round(ret, 5) if ret is not None else None),
                }
            )

    meta = {
        "universe_tickers": len(prices_by),
        "limitup_signal_days": n_limitup_days,
    }
    return signals, meta


def aggregate(signals: list[dict], *, executable_only: bool) -> dict:
    """按 streak 分组统计 T+10 收益 / 胜率 / Wilson CI.

    executable_only=True 时剔除「次日续涨停买不到」样本 (execution-adjusted,
    对齐 Kelly 先验口径); False 为原始 price-eligible (理论口径).
    """
    by_streak: dict[int, list[float]] = defaultdict(list)
    counts: dict[int, int] = defaultdict(int)
    for s in signals:
        if executable_only and s.get("unbuyable_next_day"):
            continue
        streak = s["streak"]
        counts[streak] += 1
        if s["t10_return"] is not None:
            by_streak[streak].append(s["t10_return"])

    groups: dict[str, dict] = {}
    for streak in sorted(counts):
        rets = by_streak.get(streak, [])
        n_with_ret = len(rets)
        wins = sum(1 for r in rets if r > 0)
        mean_ret = sum(rets) / n_with_ret if n_with_ret else 0.0
        winrate = wins / n_with_ret if n_with_ret else 0.0
        lo, hi = _wilson_ci(wins, n_with_ret)
        median = sorted(rets)[n_with_ret // 2] if n_with_ret else 0.0
        groups[str(streak)] = {
            "n_signals": counts[streak],
            "n_with_t10_return": n_with_ret,
            "winrate": round(winrate, 4),
            "wilson_ci95": [round(lo, 4), round(hi, 4)],
            "mean_t10_return": round(mean_ret, 5),
            "median_t10_return": round(median, 5),
        }
    return groups


def _ge3_bucket(signals: list[dict], *, executable_only: bool) -> dict:
    rets = [
        s["t10_return"]
        for s in signals
        if s["streak"] >= 3 and s["t10_return"] is not None
        and not (executable_only and s.get("unbuyable_next_day"))
    ]
    n = len(rets)
    wins = sum(1 for r in rets if r > 0)
    return {
        "n_with_t10_return": n,
        "winrate": round(wins / n, 4) if n else 0.0,
        "mean_t10_return": round(sum(rets) / n, 5) if n else 0.0,
        "wilson_ci95": [round(x, 4) for x in _wilson_ci(wins, n)],
    }


def _compare(groups: dict, ge3: dict) -> dict:
    def _grp(k: str) -> dict:
        return groups.get(k, {"n_with_t10_return": 0, "winrate": 0.0, "mean_t10_return": 0.0, "wilson_ci95": [0, 0]})

    first, second = _grp("1"), _grp("2")
    wr_diff_pp = (second["winrate"] - first["winrate"]) * 100
    er_diff_pp = (second["mean_t10_return"] - first["mean_t10_return"]) * 100
    edge_holds = bool(second["mean_t10_return"] > first["mean_t10_return"] and second["winrate"] > first["winrate"])
    robust = bool(second["wilson_ci95"][0] > first["winrate"]) if second["n_with_t10_return"] and first["n_with_t10_return"] else False
    return {
        "first_board (streak=1)": first,
        "second_board (streak=2)": second,
        "third_plus (streak>=3)": ge3,
        "winrate_diff_2vs1_pp": round(wr_diff_pp, 2),
        "mean_return_diff_2vs1_pp": round(er_diff_pp, 2),
        "edge_holds_2gt1": edge_holds,
        "robust_wilson": robust,
    }


def _print_table(title: str, groups: dict, ge3: dict, cmp: dict) -> None:
    print(f"\n{title}")
    print(f"{'streak':<8} {'n':>6} {'胜率':>7} {'Wilson95%CI':>18} {'E[r]':>8} {'中位':>8}")
    for k in sorted(groups, key=int):
        g = groups[k]
        print(f"{k:<8} {g['n_with_t10_return']:>6} {g['winrate']:>6.1%} "
              f"[{g['wilson_ci95'][0]:.3f},{g['wilson_ci95'][1]:.3f}] "
              f"{g['mean_t10_return']:>+7.2%} {g['median_t10_return']:>+7.2%}")
    print(f"{'3+合并':<7} {ge3['n_with_t10_return']:>6} {ge3['winrate']:>6.1%} "
          f"[{ge3['wilson_ci95'][0]:.3f},{ge3['wilson_ci95'][1]:.3f}] "
          f"{ge3['mean_t10_return']:>+7.2%}")
    print(f"  核心: 2连板 vs 首板  胜率差 {cmp['winrate_diff_2vs1_pp']:+.2f}pp  "
          f"E[r]差 {cmp['mean_return_diff_2vs1_pp']:+.2f}pp  "
          f"→ edge {'成立' if cmp['edge_holds_2gt1'] else '【不成立】'}"
          f"{' (Wilson robust)' if cmp['robust_wilson'] else ''}")


def main() -> None:
    t = time.time()
    print("扫描全 universe 涨停信号 ...")
    signals, meta = scan()
    print(f"  {meta['universe_tickers']} tickers, {meta['limitup_signal_days']} 涨停信号日, {time.time()-t:.0f}s")

    # 双口径: 原始 price-eligible (理论) vs execution-adjusted (剔除买不到, 对齐 Kelly 先验)
    raw_groups = aggregate(signals, executable_only=False)
    raw_ge3 = _ge3_bucket(signals, executable_only=False)
    raw_cmp = _compare(raw_groups, raw_ge3)

    exe_groups = aggregate(signals, executable_only=True)
    exe_ge3 = _ge3_bucket(signals, executable_only=True)
    exe_cmp = _compare(exe_groups, exe_ge3)

    result = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "purpose": "streak_bonus=0.04 因子有效性复核 (vs 原始 9497 样本 2026-07-19)",
        "horizon": f"T+{T_HORIZON} (T+1 open -> T+{T_HORIZON} close)",
        "universe": meta,
        "execution_adjusted": {
            "note": "剔除次日续涨停买不到样本, 对齐 known_distributions/Kelly 先验口径. 判定以此为准.",
            "by_streak": exe_groups,
            "key_comparison": exe_cmp,
        },
        "raw_price_eligible": {
            "note": "原始理论口径 (含买不到样本), 供对照.",
            "by_streak": raw_groups,
            "key_comparison": raw_cmp,
        },
        "original_20260719_reference": {
            "note": "原始 9497 涨停样本 (price-eligible), 供对照",
            "first_board": {"n": 9019, "winrate": 0.455, "mean_return": 0.0098},
            "second_board": {"n": 456, "winrate": 0.480, "mean_return": 0.0220},
            "third_plus": {"n": 22, "winrate": 0.227, "mean_return": -0.0434},
        },
        "verdict": exe_cmp,
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n" + "=" * 74)
    print(f"streak 因子复核 (T+{T_HORIZON})  universe={meta['universe_tickers']}票  信号日={meta['limitup_signal_days']}")
    print("=" * 74)
    _print_table("【判定口径】execution-adjusted (剔除买不到, 对齐 Kelly 先验)", exe_groups, exe_ge3, exe_cmp)
    _print_table("【参照口径】raw price-eligible (含买不到)", raw_groups, raw_ge3, raw_cmp)
    print(f"\n  原始(7/19 9497): 胜率+2.5pp  E[r]+1.22pp  (首板45.5%/+0.98% vs 2连板48.0%/+2.20%)")
    print(f"\n→ 落盘 {OUT_PATH}")


if __name__ == "__main__":
    main()
