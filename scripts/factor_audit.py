"""通用因子审计器 (factor_audit) — 挖掘与保质期监控合并成同一个动词.

设计 (2026-08-08, 第一性原理三轮塌缩的终点):
  因子研究这个决策循环只有四个环节: 观测 -> 主张 -> 证伪 -> 行动.
    观测: price_cache (已存在, 只读)
    主张: 一个纯函数 f(历史) -> 值            <- 因子就是函数
    证伪: 冻结口径的 audit(f) -> 分桶分布      <- 本脚本是唯一要建的东西
    行动: autodev /loop 定期重跑 + owner 拍板  <- 已存在

  不建事实表 (查一次分钟级, 物化产物只会腐坏 — 零新增持久产物 = 零腐坏面).
  口径冻结在 audit 内部 (T+1 open->T+10, execution 双账本, Wilson CI, 时间块切片),
  全局唯一一处, 任何脚本没有机会漂.

  特征契约: 特征值必须由「生产同一函数」算出 (研究/运行时同一份实现).
  本轮 5 个 strength 分量全部由 btst_breakout 的生产纯函数计算, 不复制逻辑.

用法:
  uv run python scripts/factor_audit.py                 # 审计全部 5 分量 + streak
  uv run python scripts/factor_audit.py volume_score    # 只审计一个

只读 data/price_cache; 结果落 data/reports/factor_audit_<name>.json.
绝不写 data/paper_trading*/.

样本 = 全 universe 的 price-eligible 涨停候选日 (不施加 detect 的资金流/行业/追高
过滤 — 因子层审计要测的是「分量对涨停后收益的区分度」, 推荐池过滤是下游,
在池内测会引入选择偏差. 见 memory mr-family / R6 教训).

收益口径 (与 streak 复核 + known_distributions/Kelly 先验一致):
  T+1 open -> T+10 close. execution-adjusted 剔除次日续涨停买不到样本.
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
    _board_quality_score,
    _compute_limit_up_streak,
    _compute_trend_vol_scores,
    _compute_volume_score,
)
from src.tools.ashare_board_utils import (  # noqa: E402
    limit_up_cap_pct_for_ticker,
    limit_up_pct_for_ticker,
)

REPORT_DIR = Path("data/reports")
T_HORIZON = 10  # T+10 (与 known_distributions/natural_horizon 口径一致)

# 时间块切片: 按信号日升序对半切, 回答「跨窗同向」(5月方法文档 G2 证据稳定性门).
# Wilson 名义 CI 在重叠 T+10 窗口下偏窄 — 相邻信号日共享未来收益, 独立样本量 < 名义 n.
# 时间块 split-half 是对重叠的诚实修正: 若 edge 只在一个半窗成立, 是单窗偶然, 不可信.

# 待审计特征: 值由生产纯函数在 scan 时算出, 存进每条 signal 记录.
# 连续值 (volume_ratio) 按预设区间分桶; 离散值 (0/0.5/1, streak) 直接按值分桶.
DISCRETE_FEATURES = ["weekday_score", "board_score", "position_score", "squeeze_score", "volume_score", "streak"]
CONTINUOUS_FEATURES = {"volume_ratio": [(0, 0.5), (0.5, 0.8), (0.8, 1.0), (1.0, 1.2), (1.2, 1.5), (1.5, 2.0), (2.0, math.inf)]}


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
    """扫描全 universe 涨停候选日, 用生产纯函数算全部特征 + T+10 收益."""
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
            if p < limit_up_pct or p > limit_up_cap + 0.5:
                continue
            n_limitup_days += 1

            # === 特征: 全部由 btst_breakout 生产纯函数计算 (研究/运行时同一份) ===
            streak = _compute_limit_up_streak(df, i, limit_up_pct)
            ref_idx = i - 5
            pre_window = df.iloc[ref_idx:i] if ref_idx >= 0 else df.iloc[0:0]
            position_score, squeeze_score = _compute_trend_vol_scores(pre_window, df, i)
            volume_score = _compute_volume_score(df, i)
            # volume_ratio: 与 _compute_volume_score 同口径的原始比率 (供连续分桶)
            volume_ratio = None
            if "volume" in df.columns and i >= 1:
                vols = pd.to_numeric(df["volume"], errors="coerce").values
                today_vol = vols[i]
                prior = vols[max(0, i - 20):i]
                prior = prior[~pd.isna(prior)]
                if today_vol > 0 and len(prior) >= 5:
                    avg = float(prior.mean())
                    if avg > 0:
                        volume_ratio = round(float(today_vol) / avg, 4)
            weekday_score = 1.0 if pd.Timestamp(date_str[i]).weekday() >= 2 else 0.0
            board_score = _board_quality_score(ticker)

            unbuyable = is_limit_up_unbuyable_next_day(df, i, ticker)

            # T+1 open -> T+10 close
            entry_idx, exit_idx = i + 1, i + T_HORIZON
            ret = None
            if entry_idx < n and exit_idx < n:
                entry_price = open_[entry_idx]
                if math.isnan(entry_price) or entry_price <= 0:
                    entry_price = close[entry_idx]
                exit_price = close[exit_idx]
                if not (math.isnan(entry_price) or math.isnan(exit_price) or entry_price <= 0):
                    ret = exit_price / entry_price - 1.0

            signals.append({
                "ticker": ticker,
                "date": str(date_str[i]),
                "streak": streak,
                "weekday_score": weekday_score,
                "board_score": board_score,
                "position_score": position_score,
                "squeeze_score": squeeze_score,
                "volume_score": volume_score,
                "volume_ratio": volume_ratio,
                "unbuyable_next_day": bool(unbuyable),
                "t10_return": (round(ret, 5) if ret is not None else None),
            })

    return signals, {"universe_tickers": len(prices_by), "limitup_signal_days": n_limitup_days}


def _bucket_key(feature: str, value) -> str | None:
    """把特征值映射到分桶 key. 缺失返回 None (该样本不进此特征的统计)."""
    if value is None:
        return None
    if feature in CONTINUOUS_FEATURES:
        for lo, hi in CONTINUOUS_FEATURES[feature]:
            if lo <= value < hi:
                hi_s = "inf" if hi == math.inf else f"{hi}"
                return f"[{lo},{hi_s})"
        return None
    if feature == "streak":
        return str(int(value)) if value < 3 else "3+"
    return str(float(value))


def _agg_returns(rets: list[float], n_signals: int) -> dict:
    n = len(rets)
    wins = sum(1 for r in rets if r > 0)
    lo, hi = _wilson_ci(wins, n)
    return {
        "n_signals": n_signals,
        "n_with_t10_return": n,
        "winrate": round(wins / n, 4) if n else 0.0,
        "wilson_ci95": [round(lo, 4), round(hi, 4)],
        "mean_t10_return": round(sum(rets) / n, 5) if n else 0.0,
        "median_t10_return": round(sorted(rets)[n // 2], 5) if n else 0.0,
    }


def _ordered_keys(feature: str, keys) -> list[str]:
    if feature in CONTINUOUS_FEATURES:
        order = {f"[{lo},{'inf' if hi == math.inf else f'{hi}'})": i for i, (lo, hi) in enumerate(CONTINUOUS_FEATURES[feature])}
        return sorted(keys, key=lambda k: order.get(k, 99))
    if feature == "streak":
        return sorted(keys, key=lambda k: (k == "3+", k))  # "1","2", then "3+"
    return sorted(keys, key=lambda k: float(k))


def _group(signals: list[dict], feature: str, *, executable_only: bool) -> dict[str, dict]:
    """按特征分桶统计 (executable_only=双账本的执行口径)."""
    buckets: dict[str, list[float]] = defaultdict(list)
    counts: dict[str, int] = defaultdict(int)
    for s in signals:
        if executable_only and s.get("unbuyable_next_day"):
            continue
        key = _bucket_key(feature, s.get(feature))
        if key is None:
            continue
        counts[key] += 1
        if s["t10_return"] is not None:
            buckets[key].append(s["t10_return"])
    return {k: _agg_returns(buckets.get(k, []), counts[k]) for k in _ordered_keys(feature, counts)}


def _time_block_split(signals: list[dict]) -> tuple[list[dict], list[dict], str]:
    """按信号日升序对半切 (跨窗同向检验). 返回 (前半, 后半, 分界日)."""
    days = sorted({s["date"] for s in signals})
    if len(days) < 2:
        return signals, [], ""
    mid = days[len(days) // 2]
    first = [s for s in signals if s["date"] < mid]
    second = [s for s in signals if s["date"] >= mid]
    return first, second, mid


def _verdict(exe_groups: dict[str, dict]) -> dict:
    """从 executable 分桶提炼判定: 最佳桶 vs 最差桶, edge 方向与 Wilson 显著性."""
    scored = [(k, g) for k, g in exe_groups.items() if g["n_with_t10_return"] >= 30]
    if len(scored) < 2:
        return {"note": "有效桶 <2 (n>=30), 样本不足以判区分度", "n_buckets_ge30": len(scored)}
    best = max(scored, key=lambda kv: kv[1]["mean_t10_return"])
    worst = min(scored, key=lambda kv: kv[1]["mean_t10_return"])
    er_spread = (best[1]["mean_t10_return"] - worst[1]["mean_t10_return"]) * 100
    wr_spread = (best[1]["winrate"] - worst[1]["winrate"]) * 100
    wilson_sep = best[1]["wilson_ci95"][0] > worst[1]["winrate"]
    return {
        "best_bucket": best[0], "best": best[1],
        "worst_bucket": worst[0], "worst": worst[1],
        "mean_return_spread_pp": round(er_spread, 2),
        "winrate_spread_pp": round(wr_spread, 2),
        "wilson_separated": bool(wilson_sep),
        "note": "best>worst 且 Wilson 分离 => 该分量有区分度; 否则权重待复核",
    }


def audit_feature(signals: list[dict], feature: str) -> dict:
    """对单个特征出完整审计: 双账本 + 时间块切片 + 判定."""
    raw = _group(signals, feature, executable_only=False)
    exe = _group(signals, feature, executable_only=True)

    # 跨窗同向 (executable 口径): 前后半各自分桶
    first, second, mid = _time_block_split([s for s in signals if not s["unbuyable_next_day"]])
    half1 = _group(first, feature, executable_only=False)
    half2 = _group(second, feature, executable_only=False) if second else {}

    return {
        "feature": feature,
        "execution_adjusted": {"note": "判定以此为准", "by_bucket": exe},
        "raw_price_eligible": {"note": "理论口径供对照", "by_bucket": raw},
        "time_blocks": {
            "note": "跨窗同向 (executable). split-half 对重叠窗口的诚实修正; 两半同向才可信.",
            "split_date": mid,
            "first_half": half1,
            "second_half": half2,
        },
        "verdict": _verdict(exe),
    }


def _print(feature: str, rep: dict) -> None:
    print("\n" + "=" * 78)
    print(f"特征审计: {feature}  (T+{T_HORIZON}, execution-adjusted 判定)")
    print("=" * 78)
    exe = rep["execution_adjusted"]["by_bucket"]
    print(f"{'桶':<12} {'n':>6} {'胜率':>7} {'Wilson95%CI':>20} {'E[r]':>8} {'中位':>8}")
    for k, g in exe.items():
        print(f"{k:<12} {g['n_with_t10_return']:>6} {g['winrate']:>6.1%} "
              f"[{g['wilson_ci95'][0]:.3f},{g['wilson_ci95'][1]:.3f}] "
              f"{g['mean_t10_return']:>+7.2%} {g['median_t10_return']:>+7.2%}")
    v = rep["verdict"]
    if "best_bucket" in v:
        print(f"  → 最佳 {v['best_bucket']} vs 最差 {v['worst_bucket']}: "
              f"E[r]差 {v['mean_return_spread_pp']:+.2f}pp 胜率差 {v['winrate_spread_pp']:+.2f}pp "
              f"{'【Wilson分离】' if v['wilson_separated'] else '(未分离)'}")
    tb = rep["time_blocks"]
    if tb["second_half"]:
        print(f"  跨窗(split@{tb['split_date']}): 见 JSON first_half/second_half")
    else:
        print("  跨窗: 样本不足以前后对半")


def main() -> None:
    only = sys.argv[1] if len(sys.argv) > 1 else None
    t = time.time()
    print("扫描全 universe 涨停候选日 (用生产纯函数算特征) ...")
    signals, meta = scan()
    print(f"  {meta['universe_tickers']} tickers, {meta['limitup_signal_days']} 涨停候选日, {time.time()-t:.0f}s")

    features = [only] if only else DISCRETE_FEATURES + list(CONTINUOUS_FEATURES)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")

    for feat in features:
        rep = audit_feature(signals, feat)
        rep["generated_at"] = stamp
        rep["horizon"] = f"T+{T_HORIZON} (T+1 open -> T+{T_HORIZON} close)"
        rep["universe"] = meta
        out = REPORT_DIR / f"factor_audit_{feat}.json"
        out.write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
        _print(feat, rep)
        print(f"  → {out}")


if __name__ == "__main__":
    main()
