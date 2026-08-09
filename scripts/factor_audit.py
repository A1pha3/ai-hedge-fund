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
from src.screening.offensive.price_returns import chained_return_pct  # noqa: E402
from src.screening.offensive.setups.btst_breakout import (  # noqa: E402
    _board_quality_score,
    _compute_limit_up_streak,
    _compute_low_vol_score,
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
# 连续值 (volume_ratio, low_vol_score) 按预设区间分桶; 离散值 (0/0.5/1, streak) 直接按值分桶.
# Q6: low_vol_score 是连续 [0,1] 浮点 (rv20 线性映射), 必须按区间分桶 — 误入 DISCRETE 会
# 被 _bucket_key 的 str(float) 粉碎成上万孤桶 (n=1), verdict 失能 (对抗审查发现). 区间锚定
# Q6 复核验证过的单调五分位 (E[r] 自低分桶 −0.039% 升至高分桶 +0.940%).
# position_score 仍列入离散以持续对照 (已移出 strength, 监控其是否彻底失效).
DISCRETE_FEATURES = ["weekday_score", "board_score", "position_score", "squeeze_score", "volume_score", "streak"]
CONTINUOUS_FEATURES = {
    "volume_ratio": [(0, 0.5), (0.5, 0.8), (0.8, 1.0), (1.0, 1.2), (1.2, 1.5), (1.5, 2.0), (2.0, math.inf)],
    "low_vol_score": [(0.0, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 0.8), (0.8, 1.0001)],
}


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
            # low_vol_score: Q6 新进 strength 的正交轴 (20日已实现波动率), 同口径纳入审计 —
            # 复核双重计权是否真解除 + 它自身的区分度是否兑现. position 留作对照 (已移出 strength).
            low_vol_score = _compute_low_vol_score(df, i)
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
            # pre_runup_pct: 涨停前 5 日涨幅 (条件4 池过滤同口径), 供冗余问责 —
            # position(新鲜突破) 与它大概率同源, 相关矩阵回答「是否双重计权同一方向」.
            pre_runup_pct = None
            if ref_idx >= 0 and i - 1 >= 0:
                pre_runup_pct = chained_return_pct(df, ref_idx, i - 1)

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
                "low_vol_score": low_vol_score,
                "squeeze_score": squeeze_score,
                "volume_score": volume_score,
                "volume_ratio": volume_ratio,
                "pre_runup_pct": (round(pre_runup_pct, 4) if pre_runup_pct is not None else None),
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


def _group(signals: list[dict], feature: str, *, measure=None) -> dict[str, dict]:
    """按特征分桶统计. measure 是一等公民的测度谓词 (见 MEASURES):
    同一份 scan, 同一个分桶聚合, 只是换一个测度 — 挖掘/监控/正交/尾部全是自由组合.
    measure=None 等价 raw (全样本)."""
    pred = measure if measure is not None else MEASURES["raw"]
    buckets: dict[str, list[float]] = defaultdict(list)
    counts: dict[str, int] = defaultdict(int)
    for s in signals:
        if not pred(s):
            continue
        key = _bucket_key(feature, s.get(feature))
        if key is None:
            continue
        counts[key] += 1
        if s["t10_return"] is not None:
            buckets[key].append(s["t10_return"])
    return {k: _agg_returns(buckets.get(k, []), counts[k]) for k in _ordered_keys(feature, counts)}


def _exec(s: dict) -> bool:
    """execution-adjusted 测度基座: 剔除次日续涨停买不到样本 (幸存者偏差护栏)."""
    return not s["unbuyable_next_day"]


def _make_tail_predicate(signals: list[dict], q: float = 0.10):
    """尾部测度: 在组合最差日子 (t10_return 最差 q 分位) 上的条件测度.
    geometry-of-alpha: 全样本相关是会撒谎的统计量; 危机时刻相关性才真."""
    rets = sorted(s["t10_return"] for s in signals if s["t10_return"] is not None)
    if not rets:
        return lambda s: False
    cut = rets[int(len(rets) * q)]
    return lambda s: s["t10_return"] is not None and s["t10_return"] <= cut


# 测度注册表: 唯一状态. 每个测度是一个谓词 s->bool, 作用于同一批信号.
# raw/exec 是基座; 时间块/尾部在 audit 时按当前 signals 动态绑定 (见 audit_feature).
MEASURES = {
    "raw": lambda s: True,
    "exec": _exec,
}


def _time_block_split(signals: list[dict]) -> tuple[list[dict], list[dict], str]:
    """按信号日升序对半切 (跨窗同向检验). 返回 (前半, 后半, 分界日)."""
    days = sorted({s["date"] for s in signals})
    if len(days) < 2:
        return signals, [], ""
    mid = days[len(days) // 2]
    first = [s for s in signals if s["date"] < mid]
    second = [s for s in signals if s["date"] >= mid]
    return first, second, mid


# 参与正交性/冗余问责的分量 (归一 [0,1] 的打分分量 + pre_runup 池过滤器).
# volume_score 与 volume_ratio 同源, 只取离散 score 避免平凡自相关; pre_runup 连续,
# 相关用 Spearman (秩) 天然抗量纲.
# Q6 复核: strength 现含 low_vol (替换 position). 把 low_vol 与 position 都列入 —
# 验证 low_vol 是否与 pre_runup 正交 (双重计权是否解除), 及 strength 分量间有无新冗余.
ORTHO_FEATURES = ["board_score", "position_score", "low_vol_score", "squeeze_score", "volume_score", "pre_runup_pct"]


def _spearman(x: list[float], y: list[float]) -> float:
    s1, s2 = pd.Series(x), pd.Series(y)
    if len(s1) < 10 or s1.nunique() < 2 or s2.nunique() < 2:
        return float("nan")
    return float(s1.rank().corr(s2.rank()))


def correlation_report(signals: list[dict]) -> dict:
    """分量两两 Spearman 相关矩阵 + 有效维度 (geometry-of-alpha 正交性问责).

    回答: 我们以为的 N 个分散赌注, 实际是几个独立方向? 有效维度 = 相关矩阵
    谱集中度 (participation ratio): (Σλ)² / Σλ². N 个正交分量 → eff_dim=N;
    完全共线 → eff_dim=1. eff_dim 远低于分量数 = 复印件集合 (同一赌注多份).
    用 executable 测度, 与判定口径一致. pre_runup 是池过滤器, 纳入以问责
    position(新鲜突破) 是否与「防追高」双重计权同一方向.
    """
    import numpy as np

    exe = [s for s in signals if MEASURES["exec"](s) and all(s.get(f) is not None for f in ORTHO_FEATURES)]
    n = len(exe)
    feats = {f: [s[f] for s in exe] for f in ORTHO_FEATURES}

    matrix: dict[str, dict[str, float]] = {}
    for a in ORTHO_FEATURES:
        matrix[a] = {b: (1.0 if a == b else round(_spearman(feats[a], feats[b]), 4)) for b in ORTHO_FEATURES}

    # 退化分量检测 (对抗审查发现): 恒定/近恒定分量 (nunique<2) 使 _spearman 返回 NaN.
    # 旧版 nan_to_num(nan=0.0) 把"无法测量相关"伪造成"完全正交", 退化分量被当独立轴,
    # 反而抬高 effective_dimension 掩盖冗余. 正确做法: 剔除退化分量, 显式标注.
    degenerate = [f for f in ORTHO_FEATURES if pd.Series(feats[f]).nunique() < 2]
    active = [f for f in ORTHO_FEATURES if f not in degenerate]

    if not active:
        # 全退化 (小宇宙/单票夹具): 无可算相关, 跳过 numpy 空矩阵 (fill_diagonal/eigvalsh
        # 要求 ≥2-d, 空矩阵崩溃). eff_dim=0 诚实反映"零可测独立方向".
        return {
            "n_executable": n, "features": ORTHO_FEATURES, "active_features": [],
            "degenerate_features": degenerate, "spearman_matrix": matrix,
            "effective_dimension": 0.0, "n_components": 0, "top_redundant_pairs": [],
            "note": "全部分量退化 (nunique<2), 无可测相关 — 检查特征函数是否恒定返回值",
        }

    M = np.array([[matrix[a][b] for b in active] for a in active], dtype=float)
    M = np.nan_to_num(M, nan=0.0)
    np.fill_diagonal(M, 1.0)
    eig = np.linalg.eigvalsh(M)
    eig = eig[eig > 1e-9]
    eff_dim = float((eig.sum() ** 2) / (eig ** 2).sum()) if len(eig) else 0.0

    # 最强冗余对 (非对角 |ρ| 最大)
    pairs = [(a, b, matrix[a][b]) for i, a in enumerate(ORTHO_FEATURES) for b in ORTHO_FEATURES[i + 1:]]
    pairs = [p for p in pairs if not math.isnan(p[2])]
    pairs.sort(key=lambda p: -abs(p[2]))

    return {
        "n_executable": n,
        "features": ORTHO_FEATURES,
        "active_features": active,
        "degenerate_features": degenerate,
        "spearman_matrix": matrix,
        "effective_dimension": round(eff_dim, 2),
        "n_components": len(active),
        "top_redundant_pairs": [{"a": a, "b": b, "rho": r} for a, b, r in pairs[:3]],
        "note": "eff_dim 基于 active 分量 (退化分量剔除); eff_dim << n_components → 复印件集合",
    }


def _verdict(exe_groups: dict[str, dict]) -> dict:
    """从 executable 分桶提炼判定: 最佳桶 vs 最差桶, edge 方向与 Wilson 显著性.

    best/worst 按 mean 选 (E[r]=策略期望收益, 对单调因子 low_vol/streak/volume_ratio 正确).
    长尾鲁棒性诊断 (对抗审查第3轮): 涨停后 T+10 收益严重右偏 (mean+0.73% vs median−2.61%,
    max+225%), 小/混合语义桶 (如各分量 0.5 的「数据不足回退」桶, n~128) 的 mean 会被单条
    极端值抬高 → mean-best 误选噪声桶 (position/squeeze/volume_score 的 0.5 回退桶 mean 居
    然最高, 但 winrate 最低). 同时算 median-best: 实测 mean-best≠median-best 恰好标中这 4
    个被污染特征, 不触及 4 个干净单调因子 (零误报). 不改选桶准则为 winrate — 二元量级丢失会
    打反 low_vol 方向; median 作对照 + 分歧警告, 让污染可见并给出可靠读法 (winrate_spread +
    Wilson), 是否把 median 提为主判据留给 owner."""
    scored = [(k, g) for k, g in exe_groups.items() if g["n_with_t10_return"] >= 30]
    if len(scored) < 2:
        return {"note": "有效桶 <2 (n>=30), 样本不足以判区分度", "n_buckets_ge30": len(scored)}
    best = max(scored, key=lambda kv: kv[1]["mean_t10_return"])
    worst = min(scored, key=lambda kv: kv[1]["mean_t10_return"])
    er_spread = (best[1]["mean_t10_return"] - worst[1]["mean_t10_return"]) * 100
    wr_spread = (best[1]["winrate"] - worst[1]["winrate"]) * 100
    # 非重叠 CI 区间检验 (对抗审查修正): 旧版 best.CI.lower > worst.winrate 不对称 (一侧 CI
    # 一侧点估计), 系统性偏松 — CI 实际重叠却被判分离, 倾向"留弱因子". 改为两侧都用 CI
    # 边界 (best 下界 > worst 上界), 重叠区间诚实判"未分离".
    wilson_sep = best[1]["wilson_ci95"][0] > worst[1]["wilson_ci95"][1]
    # 长尾分歧诊断: mean-best 与 median-best 不同 → best 桶 mean 被极端值抬高 (典型=0.5 回退桶).
    # wr_spread<0 是交叉铁证: mean 选出的 best 胜率反比 worst 低 = 纯长尾幻象.
    median_best_k = max(scored, key=lambda kv: kv[1]["median_t10_return"])[0]
    median_worst_k = min(scored, key=lambda kv: kv[1]["median_t10_return"])[0]
    median_spread = (max(g["median_t10_return"] for _, g in scored)
                     - min(g["median_t10_return"] for _, g in scored)) * 100
    diverge = best[0] != median_best_k
    return {
        "best_bucket": best[0], "best": best[1],
        "worst_bucket": worst[0], "worst": worst[1],
        "mean_return_spread_pp": round(er_spread, 2),
        "winrate_spread_pp": round(wr_spread, 2),
        "median_return_spread_pp": round(median_spread, 2),
        "median_best_bucket": median_best_k,
        "median_worst_bucket": median_worst_k,
        "wilson_separated": bool(wilson_sep),
        "robustness_warning": bool(diverge),
        "robustness_note": (
            f"⚠ mean-best({best[0]})≠median-best({median_best_k}): best 桶 mean 被长尾极端值抬高"
            + ("且 winrate_spread 为负(铁证)" if wr_spread < 0 else "")
            + " — 判读须看 winrate_spread + wilson_separated, 勿单凭 mean best/worst"
        ) if diverge else "",
        "note": "best>worst 且 Wilson 分离 => 该分量有区分度; 否则权重待复核",
    }


def audit_feature(signals: list[dict], feature: str) -> dict:
    """对单个特征出完整审计: 双账本 + 时间块 + 尾部测度 + 判定.
    所有切片共用同一 scan 同一聚合, 只是换测度."""
    raw = _group(signals, feature, measure=MEASURES["raw"])
    exe = _group(signals, feature, measure=MEASURES["exec"])

    # 跨窗同向 (executable 测度): 前后半各自分桶
    first, second, mid = _time_block_split([s for s in signals if MEASURES["exec"](s)])
    half1 = _group(first, feature)
    half2 = _group(second, feature) if second else {}

    # 尾部测度 (geometry-of-alpha 第3门): 组合最差日子上的条件区分度.
    # 一个因子在太平日子有区分度不算数, 危机时仍区分才配叫真方向.
    tail_pred = _make_tail_predicate(signals)
    tail = _group(signals, feature, measure=lambda s: _exec(s) and tail_pred(s))

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
        "tail_window": {
            "note": "尾部测度: 组合最差 10% 日子上的区分度. 全样本区分度会撒谎, 危机切片才真.",
            "by_bucket": tail,
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
        if v.get("robustness_warning"):
            print(f"  ⚠ 长尾污染: mean-best({v['best_bucket']})≠median-best({v['median_best_bucket']}), "
                  f"best桶mean被极端值抬高 — 判读看胜率差/Wilson, 勿凭mean")
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

    # 正交性/冗余问责 (geometry-of-alpha): 分量相关矩阵 + 有效维度. 仅全量运行.
    if only is None:
        corr = correlation_report(signals)
        corr["generated_at"] = stamp
        corr["universe"] = meta
        out = REPORT_DIR / "factor_audit_orthogonality.json"
        out.write_text(json.dumps(corr, ensure_ascii=False, indent=2), encoding="utf-8")
        print("\n" + "=" * 78)
        print("正交性问责: 分量相关矩阵 (Spearman, executable 测度)")
        print("=" * 78)
        print(f"  有效维度: {corr['effective_dimension']} / {corr['n_components']} 分量")
        for p in corr["top_redundant_pairs"]:
            print(f"  冗余对: {p['a']} ↔ {p['b']}  ρ={p['rho']:+.3f}")
        print(f"  → {out}")


if __name__ == "__main__":
    main()
