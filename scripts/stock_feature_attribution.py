"""stock 级 within-day T0 特征归因 — 生产实际控制的横截面轴 (纯诊断, 宪法 #2).

第一性原理: R132 恒等三分解钉死选中楔子 -5.14pp 中日内合格选择 +2.48pp
方向正确 — 同一天内买哪只票是 --daily-action 排序实际作用的轴; R133
日层归因诚实负结果 (无 T0 日层特征具备判别资格) 只closed日层轴, stock 级
within-day 轴此前无任何工具度量。R132 逐日表显示 20260817 生产买入
-11.58% 劣于日均值 -7.96% (该日内选择为负) — 同日横截面是否存在可观测
结构是证据链缺环。between-day 方差 35.7% (R131 cohort 分解) 意味着不做
日固定效应的票级归因会被日层共同因子污染: 高 cohort 日整体差会淹没
同日内强弱排序。本工具把该缺环量化:

  1. stock 级 T0 特征表 (恒等面, 逐格可由宇宙行复算): trigger_strength
     (界内 [0,1]) / 6 个 score 分量 / signal_close / industry_peer_n
     (同日同行业计数, 行业缺失 None)
  2. within-day 去均值 Pearson (日固定效应): 组内 (x-x̄_d, y-ȳ_d) 逐日
     去均值后事件池化; 单票日 (<2 有效观测) 与组内零方差日剔除且计数;
     pooled Pearson 对照列同有效集计算 — 两列之差即日层混淆显形
  3. 日聚类 bootstrap CI90 下界 (day-cluster, per-call seeded RNG,
     n_events>=MIN_CELL_N 且 n_days>=2 才产出)
  4. within-day 秩三分位事件面 (有效观测 >=3 的日组内排序 thirds, n<3
     剔除+计数; win_loss_stats 单一实现, n<MIN_CELL_N CI=None 只披露)
  5. 逐特征 split-half 稳定性 (signal_date 中点切分; 预注册判据 R134:
     两半同号且两半 |r|>=0.10 — 事件级横截面 IC 惯用强因子门槛; 与
     R133 日层 |r|>=0.5 是不同观测单位的不同门槛, 本判据成文于首读
     within-day 数据之前)

纪律 (先于数据写死):
  - 纯诊断 (宪法 #2): 本工具零判定逻辑零行为授权; 任何据此的生产变化
    (排序权重 / 强度阈值 / 组合构造) = 策略行为变化 = 新证据世代
    owner 决策。
  - T0 可观测性: 只用信号日收盘可得列; gap_t1_open 等 T+1 列显式排除
    (决策时不可见 — 用它归因会把执行面信息泄漏进选择面)。
  - 复用单一实现零口径 fork: production_aligned/net_returns/win_loss_stats/
    MIN_CELL_N/court_binding (winrate_payoff_decomposition),
    strength_bucket (threshold_trigger), pearson_r (day_feature_attribution)。
  - 零 RNG 主面: 去均值 Pearson/特征表/秩三分位全部确定性; 仅日聚类 CI
    经 per-call seeded RNG (R13 纪律) 确定性。
  - 退化形态诚实: 单票日/零方差日/越界强度/缺失特征全部显式剔除+计数,
    绝不以 0 冒充观测。
  - fixture 断言非对称 (R13 教训: 对称 fixture 的数值断言无牙)。

用法:
    uv run python scripts/stock_feature_attribution.py
    uv run python scripts/stock_feature_attribution.py --court-table PATH --report-dir PATH
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from winrate_payoff_decomposition import (  # noqa: E402
    COURT_TABLE,
    MIN_CELL_N,
    REPORT_DIR,
    ROUNDTRIP_COST,
    court_binding,
    net_returns,
    production_aligned,
    win_loss_stats,
)
from day_feature_attribution import pearson_r  # noqa: E402
from src.screening.offensive.threshold_trigger import strength_bucket  # noqa: E402

PRIMARY_HORIZON = 10

# T0 可观测 score 分量列 (信号日收盘已定; 列缺失 = 口径理解错误, fail-closed)
SCORE_COMPONENT_COLS: tuple[str, ...] = (
    "board_score",
    "low_vol_score",
    "squeeze_score",
    "volume_score",
    "range_score",
    "energy_bonus",
)

# 特征注册表: (特征名, 中文名)。注册面即 T0 可观测性承诺面 — 任何非 T0
# 列进入此表都是口径违规。industry_peer_n 是派生特征 (由 industry_name+
# industry_missing 在信号日收盘可得面内构造), 同属 T0。
FEATURE_REGISTRY: tuple[tuple[str, str], ...] = (
    ("trigger_strength", "决策时强度"),
    *((c, f"{c}") for c in SCORE_COMPONENT_COLS),
    ("signal_close", "信号日收盘价"),
    ("industry_peer_n", "同日同行业计数"),
)

SPLIT_HALF_MIN_R = 0.10  # 预注册 (R134): 事件级横截面 IC 强因子门槛
N_BOOT = 10_000
BOOT_SEED = 20260906  # 每次调用新建 seeded RNG — 与进程历史/行序无关 (R13)


def _finite(v: object) -> bool:
    return (
        isinstance(v, (int, float))
        and not isinstance(v, bool)
        and not (isinstance(v, float) and np.isnan(v))
    )


def _net_column(ev: pd.DataFrame, horizon: int) -> list[float]:
    """宇宙净收益列 (fail-closed: 缺失列或未成熟行都是口径错误, 绝不冒充 0)."""
    ret_col = f"gross_ret_t{horizon}"
    if ret_col not in ev.columns:
        raise SystemExit(f"court 事件表缺少列: {ret_col}")
    net = net_returns(list(ev[ret_col]))
    missing = sum(1 for v in net if v is None)
    if missing:
        raise SystemExit(
            f"宇宙行含缺失 gross_ret_t{horizon} {missing} 行 — "
            "特征面只接受 production_aligned 全成熟宇宙"
        )
    return [float(v) for v in net]


def _industry_peer_n(day_frame: pd.DataFrame) -> list[float | None]:
    """同日同行业计数 (含自身); 行业缺失行 None (绝不冒充 1 或 0)."""
    industries: list[str | None] = []
    for ind, miss in zip(day_frame["industry_name"], day_frame["industry_missing"]):
        valid = (
            (not bool(miss))
            and ind is not None
            and str(ind).strip() != ""
            and str(ind).lower() != "nan"
        )
        industries.append(str(ind) if valid else None)
    counts: dict[str, int] = {}
    for ind in industries:
        if ind is not None:
            counts[ind] = counts.get(ind, 0) + 1
    return [counts[i] if i is not None else None for i in industries]


def stock_feature_table(
    ev: pd.DataFrame, horizon: int = PRIMARY_HORIZON
) -> list[dict[str, Any]]:
    """逐票 T0 特征表 (恒等面; 宇宙行 = production_aligned, 全部成熟)."""
    required = [f"gross_ret_t{horizon}", "signal_date", "ts_code",
                "trigger_strength", "signal_close",
                "industry_name", "industry_missing", *SCORE_COMPONENT_COLS]
    missing = [c for c in required if c not in ev.columns]
    if missing:
        raise SystemExit(f"court 事件表缺少 T0 特征列: {sorted(missing)}")

    net_col = f"net_ret_t{horizon}"
    work = ev.copy()
    work[net_col] = _net_column(work, horizon)

    rows: list[dict[str, Any]] = []
    for day_value, group in work.groupby("signal_date", sort=True):
        day = str(int(day_value))
        peers = _industry_peer_n(group)
        for pos, (_, r) in enumerate(group.iterrows()):
            strength = r["trigger_strength"]
            strength_v = (
                float(strength) if _finite(strength) and 0.0 <= float(strength) <= 1.0
                else None
            )
            row: dict[str, Any] = {
                "signal_date": day,
                "ts_code": str(r["ts_code"]),
                "net_ret_t10": float(r[net_col]),
                "trigger_strength": strength_v,
                # 单一实现零 fork: 缺失/越界 → strength_bucket(None) = "unknown"
                "strength_bucket": strength_bucket(strength_v),
            }
            for col in SCORE_COMPONENT_COLS:
                v = r[col]
                row[col] = float(v) if _finite(v) else None
            close = r["signal_close"]
            row["signal_close"] = float(close) if _finite(close) else None
            row["industry_peer_n"] = peers[pos]
            rows.append(row)
    return rows


def _feature_points(
    table: Sequence[Mapping[str, Any]], feature: str
) -> tuple[dict[str, list[tuple[float, float]]], int, int, int]:
    """按日收集 (feature, net_ret) 有效点对。

    返回 (逐日点对, 特征缺失事件数, 低于配对下限日数, 零组内方差日数)。
    低于配对下限 = 有效观测 <2 的日 (无组内信息); 零组内方差 = 特征当日
    恒定 — 去均值后全 0, 计入会把 r 拉向 0 (伪稀释), 剔除且显形。
    """
    by_day: dict[str, list[tuple[float | None, float]]] = {}
    for row in table:
        by_day.setdefault(str(row["signal_date"]), []).append(
            (row.get(feature), float(row["net_ret_t10"]))
        )
    missing = 0
    below_floor = 0
    zero_var = 0
    pairs: dict[str, list[tuple[float, float]]] = {}
    for day, items in sorted(by_day.items()):
        valid = [(x, y) for x, y in items if _finite(x)]
        missing += len(items) - len(valid)
        if len(valid) < 2:
            below_floor += 1
            continue
        xs = [x for x, _ in valid]
        ys = [y for _, y in valid]
        mx = sum(xs) / len(xs)
        my = sum(ys) / len(ys)
        if all(x == mx for x in xs):
            zero_var += 1
            continue
        pairs[day] = [(x - mx, y - my) for x, y in valid]
    return pairs, missing, below_floor, zero_var


def _pooled_r_raw(
    table: Sequence[Mapping[str, Any]], feature: str
) -> tuple[float | None, int]:
    """pooled Pearson (原始值, 同有效集) — 与 r_within 对照暴露日层混淆."""
    xs: list[float] = []
    ys: list[float] = []
    for row in table:
        v = row.get(feature)
        if _finite(v):
            xs.append(float(v))
            ys.append(float(row["net_ret_t10"]))
    return pearson_r(xs, ys), len(xs)


def within_day_pearson(
    table: Sequence[Mapping[str, Any]], feature: str
) -> dict[str, Any]:
    """within-day 去均值 Pearson + pooled 对照 + 日聚类 CI90 下界.

    CI: day-cluster bootstrap (整日重采样, 组内结构保持), per-call seeded
    RNG; n_events < MIN_CELL_N 或 n_days < 2 → None + 原因 (不冒充).
    """
    pairs, missing, below_floor, zero_var = _feature_points(table, feature)
    xs: list[float] = []
    ys: list[float] = []
    days_used: list[str] = []
    for day in sorted(pairs):
        for x, y in pairs[day]:
            xs.append(x)
            ys.append(y)
            days_used.append(day)
    r_within = pearson_r(xs, ys)
    r_pooled, n_raw = _pooled_r_raw(table, feature)
    n_events = len(xs)
    n_days = len(pairs)
    ci_low: float | None = None
    ci_reason: str | None = None
    if n_events < MIN_CELL_N:
        ci_reason = "insufficient_events"
    elif n_days < 2:
        ci_reason = "insufficient_days"
    else:
        ci_low = _day_cluster_ci_low(pairs)
    return {
        "feature": feature,
        "n_events": n_events,
        "n_days": n_days,
        "events_feature_missing": missing,
        "days_below_pair_floor": below_floor,
        "days_zero_within_variance": zero_var,
        "pearson_r_within": r_within,
        "pearson_r_pooled": r_pooled,
        "pooled_n": n_raw,
        "cluster_ci_low_90": ci_low,
        "ci_reason": ci_reason,
    }


def _day_cluster_ci_low(
    pairs: Mapping[str, list[tuple[float, float]]], reps: int = N_BOOT
) -> float | None:
    """日聚类 bootstrap 的 r 90% 下界 (第 5 百分位); 全退化 → None."""
    days = sorted(pairs)
    n_d = len(days)
    per_day = {
        "n": np.array([len(pairs[d]) for d in days], dtype=np.int64),
        "sx": np.array([sum(x for x, _ in pairs[d]) for d in days]),
        "sy": np.array([sum(y for _, y in pairs[d]) for d in days]),
        "sxx": np.array([sum(x * x for x, _ in pairs[d]) for d in days]),
        "syy": np.array([sum(y * y for _, y in pairs[d]) for d in days]),
        "sxy": np.array([sum(x * y for x, y in pairs[d]) for d in days]),
    }
    rng = np.random.default_rng(BOOT_SEED)
    idx = rng.integers(0, n_d, size=(reps, n_d))
    n = per_day["n"][idx].sum(axis=1)
    sx = per_day["sx"][idx].sum(axis=1)
    sy = per_day["sy"][idx].sum(axis=1)
    sxx = per_day["sxx"][idx].sum(axis=1)
    syy = per_day["syy"][idx].sum(axis=1)
    sxy = per_day["sxy"][idx].sum(axis=1)
    denom_x = n * sxx - sx * sx
    denom_y = n * syy - sy * sy
    with np.errstate(divide="ignore", invalid="ignore"):
        r = (n * sxy - sx * sy) / np.sqrt(denom_x * denom_y)
    finite = r[np.isfinite(r)]
    if len(finite) == 0:
        return None
    return float(np.percentile(finite, 5.0))


def within_day_terciles(
    table: Sequence[Mapping[str, Any]], feature: str
) -> dict[str, Any] | None:
    """within-day 秩三分位事件面 (有效观测 >=3 的日组内排序 thirds).

    排序键 (特征值, ts_code) 双稳定 — 同值票按代码定序, 边界不依赖输入
    行序。有效观测 <3 的日整日剔除且计数 (1 票无组内序, 2 票 thirds 退化)。
    特征全缺失 → None。
    """
    by_day: dict[str, list[tuple[float | None, float, str]]] = {}
    for row in table:
        by_day.setdefault(str(row["signal_date"]), []).append(
            (row.get(feature), float(row["net_ret_t10"]), str(row["ts_code"]))
        )
    cells: list[list[tuple[float, str]]] = [[], [], []]
    days_excluded = 0
    events_excluded = 0
    days_used = 0
    for day in sorted(by_day):
        valid = [(x, code, y) for x, y, code in by_day[day] if _finite(x)]
        nv = len(valid)
        if nv < 3:
            days_excluded += 1
            events_excluded += nv
            continue
        days_used += 1
        ordered = sorted(valid, key=lambda t: (t[0], t[2]))
        cut1 = nv // 3
        cut2 = nv - nv // 3
        for rank, (lo, hi) in enumerate(((0, cut1), (cut1, cut2), (cut2, nv))):
            cells[rank].extend((y, day) for _, _, y in ordered[lo:hi])
    if days_used == 0:
        return None
    labels = ("T1(日内低)", "T2", "T3(日内高)")
    return {
        "feature": feature,
        "days_total": days_used + days_excluded,
        "days_used": days_used,
        "days_excluded_small": days_excluded,
        "events_excluded": events_excluded,
        "cells": [
            {
                "tercile": labels[i],
                "event_stats": win_loss_stats([y for y, _ in cells[i]],
                                              [d for _, d in cells[i]]),
            }
            for i in range(3)
        ],
    }


def split_half_within(
    table: Sequence[Mapping[str, Any]], feature: str
) -> dict[str, Any] | None:
    """signal_date 中点切分, 两半 within-day Pearson 同号且两半 |r|>=0.10
    才「具备资格」; 任一半事件 <MIN_CELL_N 或特征退化 → 只披露.

    预注册判据 (R134, 成文于首读 within-day 数据之前): SPLIT_HALF_MIN_R
    =0.10 是事件级横截面 IC 惯用强因子门槛 — 与 R133 日层 |r|>=0.5 是
    不同观测单位的不同门槛。只判定资格不授权 (宪法 #2)。
    """
    days = sorted({str(r["signal_date"]) for r in table})
    if not days:
        return None
    mid = len(days) // 2
    halves = (set(days[:mid]), set(days[mid:]))
    out_halves: list[dict[str, Any]] = []
    for label, half_days in (("前半", halves[0]), ("后半", halves[1])):
        sub = [r for r in table if str(r["signal_date"]) in half_days]
        a = within_day_pearson(sub, feature)
        out_halves.append({
            "half": label,
            "n_days": len(half_days),
            "n_events": a["n_events"],
            "pearson_r_within": a["pearson_r_within"],
        })
    h1, h2 = out_halves
    r1, r2 = h1["pearson_r_within"], h2["pearson_r_within"]
    if h1["n_events"] < MIN_CELL_N or h2["n_events"] < MIN_CELL_N:
        verdict = "样本不足 — 只披露"
    elif r1 is None or r2 is None:
        verdict = "特征退化 — 只披露"
    elif r1 * r2 > 0 and abs(r1) >= SPLIT_HALF_MIN_R and abs(r2) >= SPLIT_HALF_MIN_R:
        verdict = "具备资格"
    else:
        verdict = "只披露"
    return {
        "feature": feature,
        "halves": out_halves,
        "verdict": verdict,
    }


def build_payload(
    ev: pd.DataFrame,
    court_table: Path,
    horizon: int = PRIMARY_HORIZON,
    report_date: str | None = None,
) -> dict[str, Any]:
    """装配 JSON payload (确定性; 仅 CI 面经 seeded RNG, 逐次恒同)."""
    table = stock_feature_table(ev, horizon)
    attributions = [
        within_day_pearson(table, f) for f, _ in FEATURE_REGISTRY
    ]
    terciles = [
        t for t in (within_day_terciles(table, f) for f, _ in FEATURE_REGISTRY)
        if t is not None
    ]
    stabilities = [
        s for s in (split_half_within(table, f) for f, _ in FEATURE_REGISTRY)
        if s is not None
    ]
    return {
        "title": "stock 级 within-day T0 特征归因 (纯诊断, 宪法 #2)",
        "report_date": report_date or date.today().isoformat(),
        "court_binding": court_binding(Path(court_table), rows=int(len(ev))),
        "caliber": {
            "universe": f"production_aligned/t{horizon}",
            "net_roundtrip_cost": ROUNDTRIP_COST,
            "caliber_note": "净=毛−0.65% (与 winrate 分解报告同式, 跨报告直比须先同口径)",
            "t0_note": "特征只用信号日收盘可得列; gap_t1_open 等 T+1 列显式排除 (决策时不可见)",
            "fixed_effect_note": (
                "within-day 面逐日去均值 (日固定效应); 单票日与组内零方差日剔除且计数"
            ),
            "universe_rows": int(len(ev)),
            "days": len({r["signal_date"] for r in table}),
        },
        "stock_features": table,
        "within_day_pearson": attributions,
        "within_day_rank_terciles": terciles,
        "split_half_stability": stabilities,
        "discipline": {
            "constitution_2": "纯诊断: 组合路径证据是唯一经济裁判; 零判定逻辑零行为授权",
            "min_cell_n": MIN_CELL_N,
            "split_half_min_r": SPLIT_HALF_MIN_R,
            "disclosure_only": (
                "n<MIN_CELL_N 桶 CI=None 只披露不判定; split-half 判据预注册只判定不提案"
            ),
        },
    }


def _fmt(v: object, pct: bool = True) -> str:
    if v is None:
        return "—"
    if not _finite(v):
        return "—"
    f = float(v)
    return f"{f * 100:+.2f}%" if pct else f"{f:+.3f}"


def render_md(payload: Mapping[str, Any]) -> str:
    """渲染 markdown 报告 (纪律句先于数字)."""
    L: list[str] = []
    cal = payload["caliber"]
    L.append(f"# {payload['title']} ({payload['report_date']})")
    L.append("")
    L.append("纯诊断 (宪法 #2)。回答: 同一信号日内哪些 T0 票级特征区分赢家/输家 —")
    L.append("R132 三分解钉死日内合格选择 +2.48pp 是生产排序实际作用的轴, R133 已")
    L.append("closed日层轴 (诚实负结果); 本报告不构成任何行为授权 — 参数变化 = 新")
    L.append("证据世代 owner 决策。")
    L.append("")
    L.append(f"口径: {cal['caliber_note']}; 宇宙 {cal['universe']} "
             f"({cal['universe_rows']} 行 / {cal['days']} 日)")
    L.append(f"T0 可观测性: {cal['t0_note']}")
    L.append(f"日固定效应: {cal['fixed_effect_note']}")
    L.append("")
    cb = payload["court_binding"]
    L.append(f"court 身份: rows={cb.get('rows')} content_digest={str(cb.get('content_digest'))[:16]}…")
    L.append("")

    L.append("## within-day 去均值 Pearson (日固定效应, 事件池化)")
    L.append("")
    L.append("| 特征 | n_events | n_days | r_within | r_pooled | CI90下界 | 缺失事件 | 单票日 | 零方差日 |")
    L.append("|---|---|---|---|---|---|---|---|---|")
    for a in payload["within_day_pearson"]:
        ci = a["cluster_ci_low_90"]
        ci_text = "—" if ci is None else _fmt(ci)
        if ci is None and a["ci_reason"]:
            ci_text = f"— ({a['ci_reason']})"
        L.append(
            f"| {a['feature']} | {a['n_events']} | {a['n_days']} "
            f"| {_fmt(a['pearson_r_within'], pct=False)} "
            f"| {_fmt(a['pearson_r_pooled'], pct=False)} | {ci_text} "
            f"| {a['events_feature_missing']} | {a['days_below_pair_floor']} "
            f"| {a['days_zero_within_variance']} |"
        )
    L.append("")
    L.append("注: r_within 与 r_pooled 同有效集 — 两列之差即日层混淆显形; "
             "CI=日聚类 bootstrap (per-call seeded, n>=30 且日数>=2 才产出); "
             "r=— 为组内零方差全剔除后退化, 如实 None 不冒充 0。")
    L.append("")

    L.append("## within-day 秩三分位事件面 (净口径)")
    L.append("")
    for t in payload["within_day_rank_terciles"]:
        cells = t["cells"]
        head = " | ".join(
            f"{c['tercile']} E={_fmt(c['event_stats']['expectancy'])} (n={c['event_stats']['n']})"
            for c in cells
        )
        L.append(f"- **{t['feature']}**: {head}"
                 + (f" · 小日剔除 {t['days_excluded_small']} 日/{t['events_excluded']} 事件"
                    if t["days_excluded_small"] else ""))
    L.append("")
    L.append(f"注: 有效观测 <3 的日整日剔除 (组内 thirds 退化); 格内事件 "
             f"n<{payload['discipline']['min_cell_n']} 的聚类 CI 不产出 (只披露); "
             "组内排序键 (特征值, ts_code) 双稳定, 不依赖输入行序。")
    L.append("")

    L.append(f"## split-half 稳定性 (预注册判据 R134: 两半同号且两半 |r|>={SPLIT_HALF_MIN_R})")
    L.append("")
    L.append("| 特征 | 前半 r (n_events) | 后半 r (n_events) | verdict |")
    L.append("|---|---|---|---|")

    def _half_cell(h: Mapping[str, Any]) -> str:
        r = h["pearson_r_within"]
        r_text = "—" if r is None else f"{r:+.3f}"
        return f"{r_text} ({h['n_events']})"

    for s in payload["split_half_stability"]:
        h1, h2 = s["halves"]
        L.append(f"| {s['feature']} | {_half_cell(h1)} | {_half_cell(h2)} | {s['verdict']} |")
    L.append("")
    L.append("注: 判据成文于首读 within-day 数据之前 (事件级横截面 IC 强因子门槛, "
             "与 R133 日层 |r|>=0.5 是不同观测单位的不同门槛); 只判定资格不授权。")
    L.append("")

    L.append("## 纪律")
    L.append("")
    L.append(f"- {payload['discipline']['constitution_2']}")
    L.append("- 恒等面: stock_features 表逐格可由宇宙行复算; 零 RNG 主面 "
             "(去均值 Pearson/特征表/秩三分位确定性, 仅 CI 经 per-call seeded RNG)")
    L.append(f"- {payload['discipline']['disclosure_only']}")
    L.append("- T0 可观测性: gap_t1_open 等 T+1 列显式排除 — 决策时不可见, "
             "用其归因会把执行面信息泄漏进选择面")
    L.append("- 任何据此的生产参数变化 = 策略行为变化 = 新证据世代 owner 决策")
    return "\n".join(L) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--court-table", default=str(COURT_TABLE))
    parser.add_argument("--report-dir", default=str(REPORT_DIR))
    parser.add_argument("--date-str", default=date.today().strftime("%Y%m%d"))
    args = parser.parse_args(argv)
    # R119 P2 同族纪律: 日期形状守卫 — 非法形状在零副作用前 fail-closed
    if not re.fullmatch(r"[0-9]{8}", str(args.date_str)):
        raise SystemExit(
            f"--date-str 必须是 8 位数字 YYYYMMDD, got: {args.date_str!r}"
        )

    court_table = Path(args.court_table)
    ev = pd.read_csv(court_table)
    universe = production_aligned(ev)
    payload = build_payload(universe, court_table, report_date=str(args.date_str))

    report_dir = Path(args.report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    md_path = report_dir / f"stock_feature_attribution_{args.date_str}.md"
    json_path = report_dir / f"stock_feature_attribution_{args.date_str}.json"
    md_path.write_text(render_md(payload), encoding="utf-8")
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=1),
        encoding="utf-8",
    )

    qualified = [s["feature"] for s in payload["split_half_stability"]
                 if s["verdict"] == "具备资格"]
    print(f"stock_feature_attribution: {len(universe)} events / "
          f"{payload['caliber']['days']} days -> {md_path}")
    print(f"split-half 具备资格特征: {qualified or '无'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
