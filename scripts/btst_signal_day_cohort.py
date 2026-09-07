"""信号日 cohort 分解 — 组合胜率/赔率的日层证据 (纯诊断, 宪法 #2).

第一性原理: per-trade 证据线 (winrate_payoff_decomposition / btst_realized_vs_court /
btst_condition_replay) 已完备, 但同日入场共享同一 T+1..T+10 市场路径 — 组合实现
的胜率/赔率由信号日 cohort 层决定, 该层此前无量化工具。Observe 期探针
(production_aligned t10, 20260904 表): n=1627 中 35.7% 结果方差在信号日之间
(between-day); cohort 中位 8 只/日 (max 60), 96.2% 事件在 ≥4 只 cohort 日;
journal 0710 cohort 5 笔 4 负、0817 cohort 6 笔全损 — 日层共振在实现面直接可见。

本工具把该层量化:

  1. 方差分解: between-day + within-day = total (构造性恒等, residual 显形 ~0)
  2. cohort 规模分桶 (1 / 2-3 / 4-9 / 10-19 / 20+): 日数/日E中位/事件面
     win_loss_stats (聚类 CI90, MIN_CELL_N=30 披露纪律 — n<30 CI=None 只披露)
  3. split-half 稳定性: signal_date 中点切分, 桶级符号跨半一致 + 桶序 Spearman
     (R15 判据镜像: Spearman ≥0.5 且符号跨半一致才「具备资格」; 任一半
     n<MIN_CELL_N 的桶不判定只披露)
  4. worst-5 日解剖: 日期/规模/日E/strong 占比 — 日层灾难显形
  5. strength 构成 × cohort: 日内 strong(≥0.70) 占比与日 E 的 Pearson 相关

纪律 (先于数据写死):
  - 纯诊断 (宪法 #2): 组合路径证据是唯一经济裁判, 本工具是诊断不是授权;
    任何据此的生产参数变化 (日层风险预算/入场错峰等组合构造) = 新证据世代
    owner 决策。
  - 复用单一实现零口径 fork: production_aligned / net_returns / win_loss_stats /
    MIN_CELL_N / BOOT_SEED (winrate_payoff_decomposition), strength_bucket
    (src.screening.offensive.threshold_trigger), normalize_day
    (btst_realized_vs_court), cohort_size_bucket/COHORT_BUCKET_EDGES/LABELS
    (src.screening.offensive.gap_disclosure — R125 Op3 上移, 与操作员渲染行
    同源零漂移)。
  - 聚类 CI 经 win_loss_stats → cluster_boot_ci_low: per-call seeded RNG
    (R13 纪律), 同输入逐字节同输出。
  - fixture 断言必须非对称 (R13 教训: 对称 fixture 的数值断言无牙)。

用法:
    uv run python scripts/btst_signal_day_cohort.py
    uv run python scripts/btst_signal_day_cohort.py --court-table PATH --report-dir PATH
"""

from __future__ import annotations

import argparse
import json
import math
from datetime import date
from pathlib import Path
from typing import Any, Mapping, Sequence

import pandas as pd

from src.screening.offensive.cohort_trigger import (
    COHORT_TRIGGER_LEDGER_PATH,
    COHORT_K_REGISTRATION_PATH,
    COHORT_K_OBSERVATION_LOG_PATH,
    cohort_k_qualification_disclosure,
    cohort_trigger_stability,
    load_cohort_k_registration,
    load_cohort_trigger_ledger,
    observe_cohort_k_registration,
)
from src.screening.offensive.threshold_trigger import (
    ALL_STRENGTH_BUCKETS,
    court_data_state_equal,
    load_k_observations,
)
from src.screening.offensive.gap_disclosure import (
    COHORT_BUCKET_EDGES,
    COHORT_BUCKET_LABELS,
    cohort_size_bucket,
)
from src.screening.offensive.threshold_trigger import strength_bucket

COURT_TABLE = Path("data/research/btst_court/event_tables/event_table_v1.csv.gz")
REPORTS_DIR = Path("data/reports")
HORIZON = 10
GROSS_COL = f"gross_ret_t{HORIZON}"

# cohort 规模分桶 (左闭右闭日数边界; 显式边界不玩 cut 花活)
# COHORT_BUCKET_EDGES/LABELS/cohort_size_bucket 自 src.screening.offensive.
# gap_disclosure 导入 (R125 Op3 单一实现上移) — 模块级名字保留供既有消费面。
STRONG_BUCKET = "≥0.70"
SPEARMAN_MIN = 0.5  # R15 判据镜像
WORST_DAYS_K = 5
# 日层 cohort 触发器锚 (R126 Op1): 与强度族 (production_aligned/t10) 同宇宙,
# 分组维度换成信号日 cohort 规模桶; 账本路径单一事实源在 src 读取面模块。
COHORT_TRIGGER_ANCHOR = "production_aligned/t10/cohort_size"


def _ensure_scripts_on_path() -> None:
    """兄弟脚本单一实现的包模式导入面 (production_aligned 同款手法)。

    测试经 ``scripts.btst_signal_day_cohort`` 导入时 scripts/ 不在 sys.path,
    裸名 ``winrate_payoff_decomposition``/``btst_realized_vs_court`` 不可达 —
    每个懒导入点先经此 helper (幂等)。
    """
    import sys

    here = str(Path(__file__).resolve().parent)
    if here not in sys.path:
        sys.path.insert(0, here)


def variance_decomposition(net: Sequence[float], days: Sequence[str]) -> dict[str, Any]:
    """日层方差分解: between + within = total (总体方差口径, ddof=0)。

    between/within 各自独立计算, residual 显形 (浮点 ~1e-17, 恒等式由
    构造保证); between_share = between/total。单一信号日 (total=0) →
    shares None (不造 0/0 假读数)。
    """
    if len(net) != len(days):
        raise ValueError(f"net/days length mismatch: {len(net)} vs {len(days)}")
    if not net:
        raise ValueError("empty net series")
    values = [float(v) for v in net]
    n = len(values)
    grand = sum(values) / n
    total = sum((v - grand) ** 2 for v in values) / n
    by_day: dict[str, list[float]] = {}
    for v, d in zip(values, days):
        by_day.setdefault(d, []).append(v)
    between = 0.0
    within = 0.0
    for members in by_day.values():
        mean_d = sum(members) / len(members)
        between += len(members) * (mean_d - grand) ** 2
        within += sum((v - mean_d) ** 2 for v in members)
    between /= n
    within /= n
    residual = total - between - within
    return {
        "n_events": n,
        "n_days": len(by_day),
        "grand_mean": grand,
        "total": total,
        "between": between,
        "within": within,
        "residual": residual,
        "between_share": (between / total) if total > 0 else None,
        "within_share": (within / total) if total > 0 else None,
    }


def _day_table(net: Sequence[float], days: Sequence[str], strong: Sequence[bool]):
    by_day: dict[str, list[float]] = {}
    strong_by_day: dict[str, list[bool]] = {}
    for v, d, s in zip(net, days, strong):
        by_day.setdefault(d, []).append(float(v))
        strong_by_day.setdefault(d, []).append(bool(s))
    day_e = {d: sum(v) / len(v) for d, v in by_day.items()}
    day_n = {d: len(v) for d, v in by_day.items()}
    strong_share = {
        d: (sum(1 for s in strong_by_day[d] if s) / len(strong_by_day[d]))
        for d in by_day
    }
    return by_day, day_e, day_n, strong_share


def _bucket_stats(
    label: str,
    net: list[float],
    days: list[str],
) -> dict[str, Any]:
    _ensure_scripts_on_path()
    from winrate_payoff_decomposition import win_loss_stats

    day_e: dict[str, list[float]] = {}
    for v, d in zip(net, days):
        day_e.setdefault(d, []).append(v)
    means = sorted(sum(v) / len(v) for v in day_e.values())
    # 真中位: 偶数日数取两中元素均值 (上元素冒充中位 = 语义诚实缺陷 F2)
    n = len(means)
    median = (
        means[n // 2] if n % 2 else (means[n // 2 - 1] + means[n // 2]) / 2
    ) if n else None
    # n<MIN_CELL_N → CI=None (披露纪律由 win_loss_stats 内建)
    stats = win_loss_stats(net, days)
    return {
        "bucket": label,
        "days": len(day_e),
        "n": len(net),
        "day_e_median": median,
        "event_stats": stats,
    }


def cohort_bucket_table(
    net: Sequence[float],
    days: Sequence[str],
    strong: Sequence[bool],
) -> list[dict[str, Any]]:
    """按当日 cohort 规模分桶的事件面统计 (复用 win_loss_stats 单一实现)。"""
    if not (len(net) == len(days) == len(strong)):
        raise ValueError("net/days/strong length mismatch")
    size_of_day: dict[str, int] = {}
    for d in days:
        size_of_day[d] = size_of_day.get(d, 0) + 1
    by_size: dict[str, dict[str, list[Any]]] = {}
    for v, d in zip(net, days):
        label = cohort_size_bucket(size_of_day[d])
        acc = by_size.setdefault(label, {"net": [], "days": []})
        acc["net"].append(float(v))
        acc["days"].append(d)
    return [
        _bucket_stats(label, by_size[label]["net"], by_size[label]["days"])
        for label in COHORT_BUCKET_LABELS
        if label in by_size
    ]


def _mean(xs: Sequence[float]) -> float:
    return sum(float(x) for x in xs) / len(xs)


def _rank(xs: Sequence[float]) -> list[float]:
    """平均秩 (ties 均分); Spearman 用。"""
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    ranks = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        avg = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def _spearman(a: Sequence[float], b: Sequence[float]) -> float:
    if len(a) != len(b) or len(a) < 2:
        raise ValueError("spearman needs equal-length series of length >= 2")
    ra, rb = _rank(a), _rank(b)
    ma, mb = _mean(ra), _mean(rb)
    num = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    den = math.sqrt(sum((x - ma) ** 2 for x in ra) * sum((y - mb) ** 2 for y in rb))
    return num / den if den > 0 else 0.0


def split_half_stability(
    net: Sequence[float],
    days: Sequence[str],
    buckets: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """桶级 split-half 符号稳定性 + 桶序 Spearman (R15 判据镜像)。

    切分点 = 排序信号日的中点 (按日索引, 不按事件数 — 日是本层分析单元)。
    任一半事件数 < MIN_CELL_N 的桶不判定 (judged=False, 只披露); 判定
    verdict = 全部可判桶符号跨半一致 且 Spearman ≥ SPEARMAN_MIN。
    """
    _ensure_scripts_on_path()
    from winrate_payoff_decomposition import MIN_CELL_N

    uniq = sorted(set(days))
    if len(uniq) < 2:
        raise ValueError("split-half needs at least 2 distinct signal days")
    mid = len(uniq) // 2
    first_half = set(uniq[:mid])
    sizes: dict[str, int] = {}
    for d in days:
        sizes[d] = sizes.get(d, 0) + 1
    per_bucket: list[dict[str, Any]] = []
    for row in buckets:
        label = row["bucket"]
        # 本桶成员: 该日 cohort 规模落在本桶 (与 cohort_bucket_table 同口径)
        in_bucket = {
            d for d, s in sizes.items() if cohort_size_bucket(s) == label
        }
        h1 = [v for v, d in zip(net, days) if d in in_bucket and d in first_half]
        h2 = [v for v, d in zip(net, days) if d in in_bucket and d not in first_half]
        if not h1 or not h2:
            per_bucket.append({
                "bucket": label, "e_first": None, "e_second": None,
                "n_first": len(h1), "n_second": len(h2), "judged": False,
                "sign_consistent": None,
            })
            continue
        m1, m2 = _mean(h1), _mean(h2)
        judged = len(h1) >= MIN_CELL_N and len(h2) >= MIN_CELL_N
        per_bucket.append({
            "bucket": label,
            "e_first": m1,
            "e_second": m2,
            "n_first": len(h1),
            "n_second": len(h2),
            "judged": judged,
            "sign_consistent": (m1 > 0) == (m2 > 0) if judged else None,
        })
    judged_rows = [r for r in per_bucket if r["judged"]]
    spearman: float | None = None
    if len(judged_rows) >= 2:
        spearman = _spearman(
            [r["e_first"] for r in judged_rows],
            [r["e_second"] for r in judged_rows],
        )
    all_consistent = bool(judged_rows) and all(r["sign_consistent"] for r in judged_rows)
    if not judged_rows:
        verdict = "证据不足 — 无桶在两半各达 MIN_CELL_N, 不判定"
    elif len(judged_rows) < 2:
        verdict = "证据不足 — 可判桶不足 2 个, 桶序稳定性不可估 (R15 判据需排序面)"
    elif all_consistent and spearman is not None and spearman >= SPEARMAN_MIN:
        verdict = "具备资格 — 可判桶符号跨半一致且桶序 Spearman ≥ 0.5"
    else:
        flips = [r["bucket"] for r in judged_rows if not r["sign_consistent"]]
        why = f"符号翻转桶: {flips}" if flips else f"桶序 Spearman {spearman:.2f} < 0.5"
        verdict = f"不具备资格 — {why}"
    return {
        "mid_date": uniq[mid - 1],
        "first_date": uniq[0],
        "last_date": uniq[-1],
        "per_bucket": per_bucket,
        "spearman": spearman,
        "verdict": verdict,
    }


def worst_days(
    net: Sequence[float],
    days: Sequence[str],
    strong: Sequence[bool],
    k: int = WORST_DAYS_K,
) -> list[dict[str, Any]]:
    """日 E 最差 k 日解剖: 日期/规模/日E/strong 占比。"""
    _, day_e, day_n, strong_share = _day_table(net, days, strong)
    ranked = sorted(day_e.items(), key=lambda kv: (kv[1], kv[0]))[:k]
    return [
        {
            "signal_date": d,
            "n": day_n[d],
            "day_e": e,
            "strong_share": strong_share[d],
        }
        for d, e in ranked
    ]


def strong_share_correlation(
    net: Sequence[float],
    days: Sequence[str],
    strong: Sequence[bool],
) -> dict[str, Any]:
    """日内 strong 占比与日 E 的 Pearson 相关 (n_days<2 或零方差 → None)。"""
    by_day, day_e, _, strong_share = _day_table(net, days, strong)
    xs = [strong_share[d] for d in sorted(day_e)]
    ys = [day_e[d] for d in sorted(day_e)]
    if len(xs) < 2:
        return {"pearson": None, "n_days": len(xs)}
    mx, my = _mean(xs), _mean(ys)
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    den = math.sqrt(sum((x - mx) ** 2 for x in xs) * sum((y - my) ** 2 for y in ys))
    return {"pearson": (num / den if den > 0 else None), "n_days": len(xs)}


def strength_cohort_cross_table(
    net: Sequence[float],
    days: Sequence[str],
    strength_buckets: Sequence[str],
) -> list[dict[str, Any]]:
    """强度桶 × cohort 规模桶 交叉表 (R131 Op1; 探索性 in-sample 诊断)。

    动机: 强度条件化 (threshold_trigger, production_aligned/t10) 与日层
    cohort 条件化 (cohort_trigger, production_aligned/t10/cohort_size) 是
    两个预注册条件化维度, 各有独立触发器机器, 但 owner 若未来并用两门,
    需要先知道两维度是独立还是冗余 — 并用冗余门 = 无证据的过度拟合。
    本视图交叉两维度, 回答『强度 edge 在窄 cohort 日内是否存活』『中间桶
    最差带是否被弱强度候选驱动』(20260905 worst-5 中 strong 占比 0% 的
    -25.24% 灾难日提示联合结构, 边缘视图无法回答)。

    纪律: 两个分组维度各自预注册 (强度桶 = 触发器锚分组, cohort 桶 = 日层
    锚分组), **交叉格判定未预注册** — 本视图只披露不判定, 不产 lit/armed,
    不进任何触发器账本; 探索性 in-sample (分组 in-sample 同 gap_anatomy
    披露纪律)。复用 strength_bucket / cohort_size_bucket / win_loss_stats
    单一实现零口径 fork; n<MIN_CELL_N 格 CI=None 只披露 (win_loss_stats
    内建), 空格 n=0 全 None 诚实呈现; NaN/畸形强度已在上游对齐路径
    fail-closed, 落 "unknown" 桶 (strength_bucket 单一实现语义)。
    """
    if not (len(net) == len(days) == len(strength_buckets)):
        raise ValueError(
            f"net/days/strength_buckets length mismatch: {len(net)} vs "
            f"{len(days)} vs {len(strength_buckets)}"
        )
    _ensure_scripts_on_path()
    from winrate_payoff_decomposition import win_loss_stats
    size_of_day: dict[str, int] = {}
    for d in days:
        size_of_day[d] = size_of_day.get(d, 0) + 1
    cells: dict[tuple[str, str], dict[str, list[Any]]] = {}
    for v, d, s in zip(net, days, strength_buckets):
        key = (cohort_size_bucket(size_of_day[d]), s)
        acc = cells.setdefault(key, {"net": [], "days": []})
        acc["net"].append(float(v))
        acc["days"].append(d)
    out: list[dict[str, Any]] = []
    for cohort_label in COHORT_BUCKET_LABELS:
        row_cells: list[dict[str, Any]] = []
        for s_label in ALL_STRENGTH_BUCKETS:
            acc = cells.get((cohort_label, s_label))
            if acc is None:
                row_cells.append({
                    "strength_bucket": s_label,
                    "days": 0,
                    **win_loss_stats([], []),
                })
            else:
                row_cells.append({
                    "strength_bucket": s_label,
                    "days": len(set(acc["days"])),
                    **win_loss_stats(acc["net"], acc["days"]),
                })
        out.append({"cohort_bucket": cohort_label, "cells": row_cells})
    return out


def cohort_trigger_status(
    bucket_rows: Sequence[Mapping[str, Any]],
    *,
    min_n: int,
) -> dict[str, Any]:
    """预注册日层 cohort 规模条件化触发器的机械判定面 (R126 Op1; 强度族
    threshold_trigger_status 同构, 只判定不提案)。

    锚定 production_aligned / T+10 净口径 cohort 规模桶行 (本工具
    ``cohort_bucket_table`` 输出, anchor=production_aligned/t10/cohort_size):

      条件C1  cohort=20+           n≥min_n 且净口径聚类 CI90 下界 > 0
      条件C2  cohort=4-9 与 10-19  两桶各自 n≥min_n 且净期望均 < 0
                                   (stat = max(两桶期望) — lit ⟺ max<0;
                                    n = min(两桶 n))

    证据基础 = 20260905 split-half 判定『具备资格』(20+ 桶两半期皆正
    +2.20%/+1.02%、4-9/10-19 桶两半期皆负、桶序 Spearman 1.0 — R15 合取
    判据通过)。2-3 与单票桶 split-half 未判定 → 不入选 (预注册只锚定已
    具备资格的分组, 不借未判定桶扩面)。C2 的保护语义镜像强度族条件②:
    合取要求中间桶真正转负, 防止中间桶实为正时误获评估资格 (砍掉正期望
    分组会伤害期望本身)。

    合取 (C1且C2) 点亮 = 具备启动『日层 cohort 规模条件化』(如中间桶
    信号日降权/抑制的正式评估) 的资格 — owner 决策 + 预注册; 本工具只
    判定不提案。桶行缺失 / n<min_n / 统计缺失 = 未判定 = 恒不点亮
    (保守: 未知不驱动参数变更)。『稳定越零』是跨刷新性质 — 单次刷新只
    报告本次状态, 稳定性由连续多次刷新的逐次账本记录累积。
    """
    by_bucket = {str(r.get("bucket")): r for r in bucket_rows}

    def _row(label: str) -> tuple[object, Mapping[str, Any] | None, str | None]:
        row = by_bucket.get(label)
        if row is None:
            return None, None, f"桶行缺失 ({label}) — 未判定, 恒不点亮"
        stats = row.get("event_stats")
        if not isinstance(stats, Mapping):
            return row.get("n"), None, f"event_stats 缺失 ({label}) — 未判定, 恒不点亮"
        return row.get("n"), stats, None

    def _unjudged(n: object, reason: str) -> dict[str, Any]:
        return {"lit": False, "judged": False, "n": n, "stat": None, "reason": reason}

    def _short_n(n: object, label: str) -> str | None:
        if not isinstance(n, int) or isinstance(n, bool) or n < min_n:
            return f"n={n} < {min_n} — 只披露不判定 ({label})"
        return None

    # C1: 20+ 桶净口径 CI90 下界 > 0
    n1, st1, why = _row("20+")
    if why is not None:
        c1 = _unjudged(n1, why)
    elif (short := _short_n(n1, "20+")) is not None:
        c1 = {
            "lit": False, "judged": False, "n": n1,
            "stat": st1.get("cluster_ci_low_90"), "reason": short,
        }
    else:
        ci = st1.get("cluster_ci_low_90")
        if not isinstance(ci, (int, float)) or isinstance(ci, bool):
            c1 = _unjudged(
                n1,
                "cluster_ci_low_90 缺失 (样本不足) — 未判定, 恒不点亮",
            )
            c1["n"] = n1
            c1["stat"] = ci
        else:
            lit = float(ci) > 0
            c1 = {
                "lit": lit, "judged": True, "n": n1, "stat": ci,
                "reason": f"cluster_ci_low_90={float(ci):+.4f} — {'点亮' if lit else '未点亮'}",
            }

    # C2: 4-9 与 10-19 两桶净期望均 < 0 (stat = max, lit ⟺ max < 0)
    n_a, st_a, why_a = _row("4-9")
    n_b, st_b, why_b = _row("10-19")
    e_a = st_a.get("expectancy") if isinstance(st_a, Mapping) else None
    e_b = st_b.get("expectancy") if isinstance(st_b, Mapping) else None
    missing = [w for w in (why_a, why_b) if w]
    shorts = [s for s in (_short_n(n_a, "4-9"), _short_n(n_b, "10-19")) if s]
    bad_stat = [
        label
        for label, e in (("4-9", e_a), ("10-19", e_b))
        if not isinstance(e, (int, float)) or isinstance(e, bool)
    ]
    if missing or shorts or bad_stat:
        if missing:
            reason = missing[0]
        elif shorts:
            reason = shorts[0]
        else:
            reason = (
                f"expectancy 缺失 ({','.join(bad_stat)}) — 未判定, 恒不点亮"
            )
        c2 = _unjudged(None, reason)
    else:
        stat = max(float(e_a), float(e_b))  # type: ignore[arg-type]
        lit = stat < 0
        c2 = {
            "lit": lit, "judged": True,
            "n": min(int(n_a), int(n_b)),  # type: ignore[arg-type]
            "stat": stat,
            "reason": (
                f"4-9 E={float(e_a):+.4f} / 10-19 E={float(e_b):+.4f} "
                f"(max={stat:+.4f}) — {'点亮' if lit else '未点亮'}"
            ),
        }

    armed = bool(c1["lit"]) and bool(c2["lit"])
    if armed:
        verdict = (
            "合取点亮 — 满足启动『日层 cohort 规模条件化』正式评估的资格 "
            "(owner 决策 + 预注册; 本工具不提案)"
        )
    elif c1["lit"]:
        verdict = "条件C1点亮, 条件C2未点亮 — 合取不成立 (强 cohort 桶站稳但中间桶未全转负)"
    elif c2["lit"]:
        verdict = "条件C2点亮, 条件C1未点亮 — 合取不成立 (中间桶转负但强 cohort 桶未站稳)"
    else:
        verdict = "两条件均未点亮 — 日层 cohort 规模条件化维持不评估"
    return {
        "rule": (
            "预注册日层 cohort 触发器 (R126 Op1, 2026-09-05; 证据基础 = "
            "20260905 split_half『具备资格』: 20+ 桶两半期皆正, 4-9/10-19 "
            "两半期皆负, 桶序 Spearman 1.0): C1=20+ 桶净口径 CI90 下界>0 且 "
            "C2=4-9 与 10-19 桶净期望均<0 (各自需 n≥min_n) — 合取点亮才启动"
            "日层 cohort 规模条件化正式评估; 稳定性由连续多次刷新的逐次记录"
            "累积, 单次刷新只报告本次状态"
        ),
        "anchor": COHORT_TRIGGER_ANCHOR,
        "min_n": min_n,
        "condition_strong_bucket_ci_above_zero": c1,
        "condition_mid_buckets_expectancy_negative": c2,
        "conjunction_armed": armed,
        "verdict": verdict,
    }


def record_cohort_trigger_status(
    payload: Mapping[str, Any],
    date_str: str,
    ledger_path: Path | str = COHORT_TRIGGER_LEDGER_PATH,
    court_binding: dict[str, Any] | None = None,
    require_advance: bool = False,
) -> dict[str, Any]:
    """把本次刷新的日层触发器判定快照按日期落账本 (R126 Op1; 强度族
    record_trigger_status 同构)。

    同日刷新替换同日记录: court 表不变则判定数值恒等, 替换即幂等收敛;
    court 表变了则同日晚刷新就是最新事实 (append-only 跨日, 原地更新同日)。
    payload 无 cohort_trigger (如调用方未接判定) → 不写。
    诊断面 fail-open: 写失败/快照不可序列化 (含 NaN/Inf stat,
    allow_nan=False 拒绝静默毒化 — R143 Op3 与门挡池/强度族同款
    typed 守卫) 打印警告返回 write_failed/snapshot_not_serializable,
    不阻断报告生成。

    court_binding = winrate_payoff_decomposition.court_binding() 的数据状态
    身份 (单一实现复用), 随快照落盘。require_advance=True (数据增长耦合
    路径) 时, 绑定与账本**任一**历史记录相同 → skip (R84 Op2-B 同款:
    判定是 (数据状态, 规则) 的确定性纯函数, 同一份数据反复判定不产生新
    证据 — 单点 (最新) 比对会被数据状态回退 (备份恢复旧 court, A→B→A)
    绕过)。R130 Op1 起"相同"按数据状态身份判 (court_data_state_equal,
    强度族同款单一实现): 请求态 window 字段漂移 (非交易日重建) 不再被
    误判为数据前进。旧形态记录无 court 字段 / 缺 digest → 门放行。
    已知边界 (成文): 触发规则/锚/min_n 语义变化 = 新证据世代, 须启用新
    账本文件 (记录内 anchor/min_n 仅供审计比对)。
    非 8 位 ASCII 数字串 date (含 None/int) → invalid_date_str 零写入
    (R144 Op3 三族输入形状守卫, 单一实现 ledger_date_str_valid, 先于
    payload 守卫)。
    """
    from winrate_payoff_decomposition import ledger_date_str_valid

    if not ledger_date_str_valid(date_str):
        return {"recorded": False, "reason": "invalid_date_str"}
    trigger = payload.get("cohort_trigger")
    if not isinstance(trigger, dict):
        return {"recorded": False, "reason": "no_cohort_trigger"}
    snapshot = {
        "date": str(date_str),
        "anchor": trigger.get("anchor"),
        "min_n": trigger.get("min_n"),
        "strong_bucket": {
            k: trigger.get("condition_strong_bucket_ci_above_zero", {}).get(k)
            for k in ("lit", "judged", "n", "stat")
        },
        "mid_buckets": {
            k: trigger.get("condition_mid_buckets_expectancy_negative", {}).get(k)
            for k in ("lit", "judged", "n", "stat")
        },
        "conjunction_armed": bool(trigger.get("conjunction_armed")),
    }
    if court_binding is not None:
        # 无绑定不写字段: 不假装知道数据身份 (强度族同语义)
        snapshot["court"] = dict(court_binding)
    records = load_cohort_trigger_ledger(ledger_path)
    if require_advance and court_binding is not None:
        # R130 Op1: 门比数据状态身份 (content_digest) 而非整字典 — 强度族
        # 同款 (court_data_state_equal 单一实现), 请求态 window 字段漂移
        # 不再被误判为数据前进; 任一侧缺/畸形 digest → 门放行 (保守)。
        for previous in records:
            if court_data_state_equal(previous.get("court"), court_binding):
                return {
                    "recorded": False,
                    "reason": "court_not_advanced",
                    "records": len(records),
                }
    records = [r for r in records if r.get("date") != snapshot["date"]]
    records.append(snapshot)
    import os
    import tempfile

    path = Path(ledger_path)
    try:
        # R143 Op3: 序列化在 typed 守卫内 + allow_nan=False (镜像 Op2
        # 门挡池守卫) — 不可序列化值/NaN/Inf → snapshot_not_serializable
        # fail-open 零写入, 绝不裸逃逸炸穿夜刷诊断或静默毒化账本
        body = "\n".join(
            json.dumps(r, ensure_ascii=False, sort_keys=True, allow_nan=False)
            for r in records
        )
        if body:
            body += "\n"
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(
            dir=str(path.parent), prefix=".cohort_trigger_ledger_", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(body)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, path)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
    except OSError as exc:
        print(f"WARNING: 日层触发器账本写入失败 (诊断面 fail-open): {exc}")
        return {"recorded": False, "reason": "write_failed"}
    except (TypeError, ValueError) as exc:
        print(f"WARNING: 日层触发器账本快照不可序列化 (诊断面 fail-open): {exc}")
        return {"recorded": False, "reason": "snapshot_not_serializable"}
    return {"recorded": True, "records": len(records)}


def _normalize_day_strict(value: object) -> str:
    """normalize_day 的整型化外壳: 整值 float (NaN 污染导致的 dtype 上转型)
    安全归一, 非 NaN 值语义不变 — 合法 float64 日期列不再被 '20260701.0' 拒绝。"""
    _ensure_scripts_on_path()
    from btst_realized_vs_court import normalize_day

    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return normalize_day(value)


def decompose_cohort(ev: "pd.DataFrame") -> dict[str, Any]:
    """court 事件表 → production_aligned t10 的日层分解 payload (纯函数)。"""
    _ensure_scripts_on_path()
    from winrate_payoff_decomposition import net_returns, production_aligned

    universe = production_aligned(ev)
    # 消费列预检 (R119 家族: 缺列类型化拒绝, 不裸 KeyError)
    for col in (GROSS_COL, "signal_date", "trigger_strength"):
        if col not in universe.columns:
            raise SystemExit(f"court 事件表缺列 {col} — 生产对齐消费面无法执行")
    # 畸形日期 fail-closed 且携带归因上下文 (R41 纪律: 不静默跳过);
    # NaN 行不再以 dtype 上转型毒化合法行 (整值 float 先归一)。
    norm_days: list[str] = []
    bad_dates: list[str] = []
    for d in universe["signal_date"].tolist():
        try:
            norm_days.append(_normalize_day_strict(d))
        except (TypeError, ValueError):
            bad_dates.append(repr(d))
    if bad_dates:
        raise SystemExit(
            f"court 事件表 signal_date 畸形 {len(bad_dates)} 行 "
            f"(样例 {bad_dates[:3]}) — 畸形行不静默跳过, fail-closed"
        )
    # 非数值强度 fail-closed 且携带值上下文 (NaN → unknown → 非 strong);
    # 同一循环产出桶标签 (R131 Op1 联合交叉视图的分组输入, 单一实现语义)。
    norm_strong: list[bool] = []
    norm_strength_buckets: list[str] = []
    bad_strengths: list[str] = []
    for s in universe["trigger_strength"].tolist():
        try:
            label = strength_bucket(None if pd.isna(s) else float(s))
            norm_strong.append(label == STRONG_BUCKET)
            norm_strength_buckets.append(label)
        except (TypeError, ValueError):
            bad_strengths.append(repr(s))
    if bad_strengths:
        raise SystemExit(
            f"court 事件表 trigger_strength 非数值 {len(bad_strengths)} 行 "
            f"(样例 {bad_strengths[:3]}) — fail-closed"
        )
    # (net, day, strong, strength_bucket) 四元组逐位对齐 — net_returns 对
    # NaN gross 产 None, 跳过即对齐, 绝不按位置猜。
    pairs = [
        (v, d, f, slabel)
        for v, d, f, slabel in zip(
            net_returns(universe[GROSS_COL].tolist()),
            norm_days,
            norm_strong,
            norm_strength_buckets,
        )
        if v is not None
    ]
    if not pairs:
        raise SystemExit("production_aligned t10 净收益为空 — 无可分解事件")
    net = [p[0] for p in pairs]
    days = [p[1] for p in pairs]
    strong = [p[2] for p in pairs]
    strength_buckets = [p[3] for p in pairs]
    if len(set(days)) < 2:
        raise SystemExit("单一信号日 — 日层分解无定义, fail-closed")
    payload: dict[str, Any] = {
        "universe": "production_aligned",
        "horizon": HORIZON,
        "n_events": len(net),
        "n_days": len(set(days)),
        "variance": variance_decomposition(net, days),
        "cohort_buckets": cohort_bucket_table(net, days, strong),
        "worst_days": worst_days(net, days, strong),
        "strong_share_corr": strong_share_correlation(net, days, strong),
    }
    payload["split_half"] = split_half_stability(net, days, payload["cohort_buckets"])
    payload["strength_cohort_cross"] = strength_cohort_cross_table(
        net, days, strength_buckets
    )
    return payload


def render_md(payload: Mapping[str, Any], date_str: str) -> str:
    """payload → 操作员可读 MD (n<MIN_CELL_N 桶显式披露尾注)。"""
    _ensure_scripts_on_path()
    from winrate_payoff_decomposition import MIN_CELL_N

    L: list[str] = []
    L.append(f"# 信号日 cohort 分解 ({date_str})")
    L.append("")
    L.append(
        "纯诊断 (宪法 #2)。同日入场共享同一 T+1..T+10 市场路径 — 日层共振是 "
        "per-trade E 与组合路径之间的主导楔子; 任何据此的组合构造变化 = "
        "新证据世代 owner 决策。"
    )
    L.append("")
    L.append(
        f"宇宙: {payload['universe']} t{payload['horizon']} · "
        f"事件 n={payload['n_events']} · 信号日 n={payload['n_days']}"
    )
    L.append("")
    var = payload["variance"]
    share = var["between_share"]
    share_txt = f"{share:.1%}" if share is not None else "N/A (单一信号日)"
    L.append(
        f"方差分解: between-day {var['between']:.5f} ({share_txt}) + within-day "
        f"{var['within']:.5f} = total {var['total']:.5f} "
        f"(residual {var['residual']:.2e}, 恒等式无残差)"
    )
    L.append("")
    L.append("## cohort 规模分桶")
    L.append("")
    L.append("| 当日规模 | 日数 | 事件 n | 日E中位 | 事件E | 胜率 | payoff | CI90下界 |")
    L.append("|---|---|---|---|---|---|---|---|")
    for row in payload["cohort_buckets"]:
        st = row["event_stats"]
        ci = st["cluster_ci_low_90"]
        ci_txt = f"{ci:+.2%}" if ci is not None else "—"
        payoff = st["payoff"]
        payoff_txt = f"{payoff:.2f}" if payoff is not None else "—"
        L.append(
            f"| {row['bucket']} | {row['days']} | {st['n']} | "
            f"{row['day_e_median']:+.2%} | {st['expectancy']:+.2%} | "
            f"{st['winrate']:.1%} | "
            f"{payoff_txt} | {ci_txt} |"
        )
    small = [
        r["bucket"] for r in payload["cohort_buckets"]
        if r["event_stats"]["n"] < MIN_CELL_N
    ]
    if small:
        L.append("")
        L.append(
            f"注: 桶 {','.join(small)} 事件 n < {MIN_CELL_N} — CI 不产出, "
            "只披露不判定。"
        )
    L.append("")
    sh = payload["split_half"]
    L.append("## split-half 稳定性 (signal_date 中点切分)")
    L.append("")
    L.append(
        f"切分点 {sh['mid_date']} ({sh['first_date']}..{sh['last_date']}) · "
        f"Spearman {sh['spearman'] if sh['spearman'] is not None else '—'} · "
        f"verdict: {sh['verdict']}"
    )
    L.append("")
    L.append("| 桶 | 前半 E (n) | 后半 E (n) | 判定 | 符号一致 |")
    L.append("|---|---|---|---|---|")
    for row in sh["per_bucket"]:
        e1 = f"{row['e_first']:+.2%} ({row['n_first']})" if row["e_first"] is not None else f"— ({row['n_first']})"
        e2 = f"{row['e_second']:+.2%} ({row['n_second']})" if row["e_second"] is not None else f"— ({row['n_second']})"
        L.append(
            f"| {row['bucket']} | {e1} | {e2} | "
            f"{'判定' if row['judged'] else '只披露'} | "
            f"{row['sign_consistent'] if row['sign_consistent'] is not None else '—'} |"
        )
    L.append("")
    L.append("## worst-5 信号日 (日层灾难显形)")
    L.append("")
    L.append("| 信号日 | cohort 规模 | 日E | strong 占比 |")
    L.append("|---|---|---|---|")
    for row in payload["worst_days"]:
        L.append(
            f"| {row['signal_date']} | {row['n']} | {row['day_e']:+.2%} | "
            f"{row['strong_share']:.0%} |"
        )
    L.append("")
    corr = payload["strong_share_corr"]
    corr_txt = f"{corr['pearson']:+.3f}" if corr["pearson"] is not None else "—"
    L.append(
        f"strong(≥0.70) 占比 × 日E Pearson 相关: {corr_txt} "
        f"(n_days={corr['n_days']}) — 相关弱 ≠ strong 无保护, 日层共同因子主导。"
    )
    L.append("")
    cross = payload.get("strength_cohort_cross")
    if isinstance(cross, list) and cross:
        # R131 Op1: 强度×cohort 联合交叉视图 (探索性 in-sample) — 两门并用
        # 的独立/冗余判断依据; 只披露不判定, 不进触发器账本。
        L.append("## 强度 × cohort 规模交叉 (探索性 in-sample, R131 Op1)")
        L.append("")
        L.append(
            "两个分组维度各自预注册 (强度桶 = 强度触发器锚分组, cohort 桶 = "
            "日层触发器锚分组), **交叉格判定未预注册** — 本视图只披露不判定, "
            "不进触发器账本; 回答『强度 edge 在窄 cohort 日内是否存活』"
            "『中间桶最差带是否被弱强度候选驱动』(两条件化门并用的独立/冗余 "
            "判断依据)。任何据此的组合构造变化 = 新证据世代 owner 决策。"
        )
        L.append("")
        cohort_labels = [row["cohort_bucket"] for row in cross]
        L.append("| 强度桶 | " + " | ".join(cohort_labels) + " |")
        L.append("|---" * (len(cohort_labels) + 1) + "|")
        strength_labels = [c["strength_bucket"] for c in cross[0]["cells"]]
        small_cross: list[str] = []
        for s_label in strength_labels:
            row_txts = []
            for row in cross:
                cell = next(
                    c for c in row["cells"]
                    if c["strength_bucket"] == s_label
                )
                e = cell["expectancy"]
                if cell["n"] == 0 or e is None:
                    row_txts.append("—")
                else:
                    row_txts.append(f"{e:+.2%} ({cell['n']})")
                    if cell["n"] < MIN_CELL_N:
                        small_cross.append(f"{s_label}×{row['cohort_bucket']}")
            L.append(f"| {s_label} | " + " | ".join(row_txts) + " |")
        L.append("")
        L.append(
            "格值 = 净期望 E (事件 n); 完整统计 (胜率/payoff/CI90) 见 JSON "
            "payload `strength_cohort_cross`。"
        )
        if small_cross:
            L.append(
                f"注: 交叉格 {','.join(small_cross)} 事件 n < {MIN_CELL_N} — "
                "CI 不产出, 只披露不判定。"
            )
        L.append("")
    trigger = payload.get("cohort_trigger")
    if isinstance(trigger, dict):
        c1 = trigger.get("condition_strong_bucket_ci_above_zero") or {}
        c2 = trigger.get("condition_mid_buckets_expectancy_negative") or {}
        L.append("## 日层 cohort 触发器状态 (预注册, 只判定不提案)")
        L.append("")
        c1_stat = c1.get("stat")
        if isinstance(c1_stat, (int, float)) and not isinstance(c1_stat, bool):
            c1_txt = f"{float(c1_stat):+.2%} (n={c1.get('n')})"
        else:
            c1_txt = "—"
        L.append(f"- 条件C1 20+ 桶净口径 CI90 下界>0: "
                 f"{'**点亮**' if c1.get('lit') else '**未点亮**'} ({c1_txt})")
        L.append(f"- 条件C2 中间桶 (4-9 与 10-19) 净期望均<0: "
                 f"{'**点亮**' if c2.get('lit') else '**未点亮**'} ({c2.get('reason', '—')})")
        L.append(
            f"- **合取: {'点亮' if trigger.get('conjunction_armed') else '未点亮'}** "
            f"— {trigger.get('verdict', '')}"
        )
        stab = payload.get("cohort_trigger_stability")
        if isinstance(stab, dict) and stab.get("records"):
            # R130 Op2: 措辞收敛至数据状态语义; 折叠>0 显式披露 (零噪声)。
            folded = int(stab.get("folded_duplicates") or 0)
            L.append(
                f"- 稳定计数 (连亮按不同数据状态计数, 同数据重复观测不重复累积): 条件C1 连亮 "
                f"{stab.get('strong_bucket_streak', 0)}/{stab['records']} · "
                f"条件C2 连亮 {stab.get('mid_buckets_streak', 0)}/{stab['records']} · "
                f"合取连亮 {stab.get('conjunction_streak', 0)}/{stab['records']} "
                f"(历史最多合取连亮 {stab.get('max_conjunction_streak', 0)}; "
                f"记录 {stab.get('first_date')}→{stab.get('last_date')})"
            )
            if folded > 0:
                L.append(
                    f"  - 折叠同数据重复观测 {folded} 条 (重复判定不产生新证据; "
                    f"账本 {stab['records']} 条 → 不同数据状态 {stab['records'] - folded} 个)"
                )
        # R129 Op1: 注册/损坏/达标态取单一事实源; 未注册缺席句保持本 MD
        # 历史措辞逐字节 (K 子系统建立前两面已有各自的诚实缺席句, 统一措辞
        # 超出本 op 冻结范围 — 见 cohort_trigger 模块注)。
        k_disc = payload.get("cohort_threshold_k")
        if isinstance(k_disc, dict) and k_disc.get("state") in (
            "registered",
            "malformed",
        ):
            L.append(f"- {k_disc['line']}")
        else:
            L.append("- 稳定阈值 K 未预注册（连亮达标数属 owner 预注册动作）")
        L.append("")
    return "\n".join(L)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--court-table", type=Path, default=COURT_TABLE)
    parser.add_argument("--report-dir", type=Path, default=REPORTS_DIR)
    parser.add_argument(
        "--cohort-trigger-ledger",
        type=Path,
        default=COHORT_TRIGGER_LEDGER_PATH,
        help="日层 cohort 触发器稳定账本路径 (诊断面, 同日替换幂等)",
    )
    parser.add_argument(
        "--cohort-k-registration",
        type=Path,
        default=COHORT_K_REGISTRATION_PATH,
        help="日层族 K 预注册文件 (owner 预注册动作; 缺失=未注册态)",
    )
    parser.add_argument(
        "--cohort-k-observation-log",
        type=Path,
        default=COHORT_K_OBSERVATION_LOG_PATH,
        help="日层族 K 反回溯观测日志 (append-only)",
    )
    args = parser.parse_args(argv)
    if not args.court_table.exists():
        raise SystemExit(f"court 事件表缺失: {args.court_table}")
    ev = pd.read_csv(args.court_table)
    payload = decompose_cohort(ev)
    date_str = date.today().strftime("%Y%m%d")
    # 日层触发器判定 + 数据前进门落账 (R126 Op1; 镜像强度族 R84 路径):
    # court_binding 单一实现复用, require_advance=True 下同数据重刷不追加
    # (判定是 (数据状态, 规则) 的确定性纯函数)。诊断面 fail-open — 落账
    # 失败只降级写面, 报告与稳定计数仍读账本现状真话。
    _ensure_scripts_on_path()
    from winrate_payoff_decomposition import MIN_CELL_N, court_binding

    payload["cohort_trigger"] = cohort_trigger_status(
        payload["cohort_buckets"], min_n=MIN_CELL_N
    )
    binding = court_binding(args.court_table, rows=len(ev))
    trigger_record = record_cohort_trigger_status(
        payload,
        date_str,
        ledger_path=args.cohort_trigger_ledger,
        court_binding=binding,
        require_advance=True,
    )
    payload["cohort_trigger_record"] = trigger_record
    if isinstance(payload["cohort_trigger"], dict):
        ledger_records = load_cohort_trigger_ledger(args.cohort_trigger_ledger)
        payload["cohort_trigger_stability"] = cohort_trigger_stability(
            ledger_records
        )
        # K 预注册消费面 + 反回溯观测 (R129 Op1; 镜像强度族 R112-R115):
        # **先观测后披露** — 本 build 见到的注册内容先落 append-only 观测
        # 日志, 披露窗口再按 max(声明, 首次观测) 起算。观测写入失败
        # advisory 不阻断 build (诊断面家族纪律); 观测缺席时披露以声明日
        # 暂态生效, 最迟下一次成功观测修正。
        k_state, k_reg = load_cohort_k_registration(args.cohort_k_registration)
        observation_meta: dict[str, object] | None = None
        if k_state == "registered" and k_reg is not None:
            try:
                observed = observe_cohort_k_registration(
                    k_reg, date_str, path=args.cohort_k_observation_log
                )
                observation_meta = {
                    "observed": True,
                    "observed_date": observed["observed_date"],
                    "k_hash": observed["k_hash"],
                }
            except OSError as exc:
                print(f"K 注册观测日志写入失败 (advisory, 不阻断): {exc}")
        payload["cohort_threshold_k"] = cohort_k_qualification_disclosure(
            ledger_records,
            registration=(k_state, k_reg),
            observation_log=(
                load_k_observations(args.cohort_k_observation_log)
                if k_state == "registered"
                else None
            ),
        )
        if observation_meta is not None:
            payload["cohort_threshold_k_observation"] = observation_meta
    args.report_dir.mkdir(parents=True, exist_ok=True)
    out_json = args.report_dir / f"signal_day_cohort_{date_str}.json"
    out_md = args.report_dir / f"signal_day_cohort_{date_str}.md"
    out_json.write_text(
        json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True),
        encoding="utf-8",
    )
    out_md.write_text(render_md(payload, date_str), encoding="utf-8")
    var = payload["variance"]
    trig = payload["cohort_trigger"]
    print(
        json.dumps(
            {
                "n_events": payload["n_events"],
                "n_days": payload["n_days"],
                "between_share": var["between_share"],
                "split_half_verdict": payload["split_half"]["verdict"],
                "cohort_trigger_conjunction_armed": bool(
                    trig.get("conjunction_armed")
                ),
                "cohort_trigger_record": trigger_record,
            },
            ensure_ascii=False,
        )
    )
    print(f"written: {out_json} / {out_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
