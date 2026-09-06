"""日层 T0 可观测特征归因 — normal regime 内坏日判别的证据链缺环 (纯诊断, 宪法 #2).

第一性原理: R132 恒等三分解钉死选中楔子 (E[bought]−E[universe] = -5.14pp)
中日选择 -7.62pp 主导 — 生产亏损集中在少数坏日; R131 cohort 分解钉死
between-day 方差 35.7% 但 cohort 规模不判别 worst-5 灾难日 (20260709
cohort 25 属 20+ 桶而日E -25.24%); 生产对齐宇宙已全 regime=normal
(regime gate 在生产过滤 crisis/risk_off) — normal 内部坏日的 T0 可观测
判别特征此前无任何工具度量。本工具把该缺环量化:

  1. 逐信号日 T0 特征表: cohort_n(+bucket) / 强度均值·中位·strong 占比 /
     6 个 score 分量日均值 / 行业宽度 + Top1 行业占比 / close 中位
  2. 特征 × 日期望 Pearson 相关 (日等权; 常量特征 → None 不冒充 0)
  3. 特征三分位事件面: win_loss_stats 单一实现 (n<MIN_CELL_N → CI=None
     只披露)
  4. 逐特征 split-half 稳定性: 两半 Pearson 同号且两半 |r|>=0.5 才
     「具备资格」, 否则「只披露」 (预注册判据, R15/R131 镜像)
  5. worst-5 日特征解剖 (日层灾难显形)

纪律 (先于数据写死):
  - 纯诊断 (宪法 #2): 本工具零判定逻辑零行为授权; 任何据此的生产变化
    (日层 gate / 风险预算 / 入场错峰) = 策略行为变化 = 新证据世代
    owner 决策。
  - T0 可观测性: 只用信号日收盘可得列; gap_t1_open 等 T+1 列显式排除
    (决策时不可见 — 用它归因会把执行面信息泄漏进选择面)。
  - 复用单一实现零口径 fork: production_aligned/net_returns/win_loss_stats/
    MIN_CELL_N/court_binding (winrate_payoff_decomposition),
    cohort_size_bucket (gap_disclosure), strength_bucket (threshold_trigger)。
  - 零 RNG 主面: Pearson 是确定性公式; 三分位面聚类 CI 仅 n>=MIN_CELL_N
    触发且经 per-call seeded RNG (R13 纪律) 确定性。
  - 退化形态诚实: 常量特征相关 None + 常数计数, 行业全缺失 None,
    绝不以 0 冒充观测。
  - fixture 断言非对称 (R13 教训: 对称 fixture 的数值断言无牙)。

用法:
    uv run python scripts/day_feature_attribution.py
    uv run python scripts/day_feature_attribution.py --court-table PATH --report-dir PATH
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import date
from pathlib import Path
from typing import Any, Mapping, Sequence

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
from src.screening.offensive.gap_disclosure import cohort_size_bucket  # noqa: E402
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

# 特征注册表: (特征名, 中文名, 缺失语义)。注册面即 T0 可观测性承诺面 —
# 任何非 T0 列进入此表都是口径违规。
FEATURE_REGISTRY: tuple[tuple[str, str], ...] = (
    ("cohort_n", "cohort 规模"),
    ("strength_mean", "强度均值"),
    ("strength_median", "强度中位"),
    ("strong_share", "strong(>=0.70) 占比"),
    *((f"{c}_mean", f"{c} 日均") for c in SCORE_COMPONENT_COLS),
    ("industry_breadth", "行业宽度"),
    ("top_industry_share", "Top1 行业占比"),
    ("close_median", "close 中位"),
)

SPLIT_HALF_MIN_R = 0.5  # 预注册: 两半 |r| 门槛
WORST_DAYS_K = 5


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


def _mean(xs: Sequence[float]) -> float:
    return sum(xs) / len(xs)


def _median(xs: Sequence[float]) -> float:
    ordered = sorted(xs)
    n = len(ordered)
    if n == 0:
        raise ValueError("median of empty sequence")
    mid = n // 2
    if n % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


def _finite(v: object) -> bool:
    return (
        isinstance(v, (int, float))
        and not isinstance(v, bool)
        and not (isinstance(v, float) and math.isnan(v))
    )


def pearson_r(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    """Pearson 相关 (确定性公式); n<2 或任一侧零方差 → None (不冒充 0)."""
    n = len(xs)
    if n != len(ys) or n < 2:
        return None
    mx, my = _mean(xs), _mean(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx == 0.0 or syy == 0.0:
        return None
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    return sxy / math.sqrt(sxx * syy)


def day_feature_table(
    ev: pd.DataFrame, horizon: int = PRIMARY_HORIZON
) -> list[dict[str, Any]]:
    """逐信号日 T0 特征表 (按日期升序; 宇宙行 = production_aligned, 全部成熟).

    宇宙过滤 (candidate_universe + PRODUCTION_EXCLUDE_COLS + price_ge_3)
    已含 gross_ret_t{h} 非空 — 逐日特征与日期望在同一宇宙行上计算, 日内
    无幸存者口径分叉; 近期未成熟日不入表 (如实披露, 不以部分收益冒充)。
    """
    ret_col = f"gross_ret_t{horizon}"
    required = [ret_col, "signal_date", "trigger_strength", "signal_close",
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
        n = int(len(group))
        rets = [float(v) for v in group[net_col]]
        row: dict[str, Any] = {
            "signal_date": day,
            "cohort_n": n,
            "cohort_bucket": cohort_size_bucket(n),
            "day_e_net_t10": _mean(rets),
            "n": n,
        }
        strengths = [float(v) for v in group["trigger_strength"] if _finite(v)]
        strength_missing = n - len(strengths)
        row["strength_missing"] = strength_missing
        row["strength_mean"] = _mean(strengths) if strengths else None
        row["strength_median"] = _median(strengths) if strengths else None
        buckets = [strength_bucket(float(v)) for v in strengths]
        row["strong_share"] = (
            (sum(1 for b in buckets if b == "≥0.70") / len(buckets))
            if buckets else None
        )
        for col in SCORE_COMPONENT_COLS:
            vals = [float(v) for v in group[col] if _finite(v)]
            row[f"{col}_mean"] = _mean(vals) if vals else None
        # industry_name 是字符串列, 用显式非空判定; industry_missing 行不计入
        industries = [
            str(v)
            for v, miss in zip(group["industry_name"], group["industry_missing"])
            if (not bool(miss)) and v is not None and str(v).strip() != ""
            and str(v).lower() != "nan"
        ]
        row["industry_missing_n"] = n - len(industries)
        if industries:
            counts: dict[str, int] = {}
            for ind in industries:
                counts[ind] = counts.get(ind, 0) + 1
            row["industry_breadth"] = len(counts)
            row["top_industry_share"] = max(counts.values()) / len(industries)
        else:
            row["industry_breadth"] = None
            row["top_industry_share"] = None
        closes = [float(v) for v in group["signal_close"] if _finite(v)]
        row["close_median"] = _median(closes) if closes else None
        rows.append(row)
    return rows


def _feature_values(
    day_table: Sequence[Mapping[str, Any]], feature: str
) -> tuple[list[float], list[str], int]:
    """抽取 (特征值, 信号日, 特征缺失日数); 缺失日剔除并在计数中显形."""
    xs: list[float] = []
    days: list[str] = []
    missing = 0
    for row in day_table:
        v = row[feature]
        if _finite(v):
            xs.append(float(v))
            days.append(str(row["signal_date"]))
        else:
            missing += 1
    return xs, days, missing


def _day_net_by_day(
    ev: pd.DataFrame, horizon: int = PRIMARY_HORIZON
) -> dict[str, list[float]]:
    out: dict[str, list[float]] = {}
    for v, d in zip(_net_column(ev, horizon), ev["signal_date"]):
        out.setdefault(str(int(d)), []).append(v)
    return out


def feature_terciles(
    day_table: Sequence[Mapping[str, Any]],
    day_net: Mapping[str, Sequence[float]],
    feature: str,
) -> dict[str, Any] | None:
    """按特征把信号日分三分位, 输出事件面 win_loss_stats (确定性边界).

    日排序键 (特征值, 信号日) 双稳定 — 同值日按日期定序, 边界不依赖
    输入行序。T1=低特征 / T3=高特征。特征全缺失 → None。
    """
    xs, days, missing = _feature_values(day_table, feature)
    if not xs:
        return None
    order = sorted(range(len(xs)), key=lambda i: (xs[i], days[i]))
    n = len(order)
    cut1 = (n + 2) // 3 if n >= 3 else 1
    cut2 = n - (n + 2) // 3 if n >= 3 else n - 1
    if cut2 <= cut1:
        cut2 = cut1 + 1 if cut1 < n else cut1
    cells: list[dict[str, Any]] = []
    for label, lo, hi in (("T1(低)", 0, cut1), ("T2", cut1, cut2), ("T3(高)", cut2, n)):
        cell_days = {days[i] for i in order[lo:hi]}
        rets: list[float] = []
        ret_days: list[str] = []
        for d in sorted(cell_days):
            for v in day_net.get(d, ()):  # 宇宙行全部成熟, day_net 必有
                rets.append(v)
                ret_days.append(d)
        cells.append({
            "tercile": label,
            "days": len(cell_days),
            "event_stats": win_loss_stats(rets, ret_days),
        })
    return {
        "feature": feature,
        "days_total": n,
        "days_feature_missing": missing,
        "cells": cells,
    }


def feature_pearson(
    day_table: Sequence[Mapping[str, Any]], feature: str
) -> dict[str, Any] | None:
    """特征 × 日期望 Pearson (日等权); 特征全缺失 → None."""
    xs, days, missing = _feature_values(day_table, feature)
    if not xs:
        return None
    day_e = {str(r["signal_date"]): float(r["day_e_net_t10"]) for r in day_table}
    ys = [day_e[d] for d in days]
    r = pearson_r(xs, ys)
    return {
        "feature": feature,
        "n_days": len(xs),
        "days_feature_missing": missing,
        "pearson_r": r,
        "degenerate": r is None,
    }


def split_half_stability(
    day_table: Sequence[Mapping[str, Any]],
    feature: str,
    min_half_days: int = MIN_CELL_N,
) -> dict[str, Any] | None:
    """signal_date 中点切分, 两半 Pearson 同号且两半 |r|>=SPLIT_HALF_MIN_R
    才「具备资格」; 任一半日数 < min_half_days 或特征退化 → 只披露.

    预注册判据 (R15/R131 镜像): 稳定性判据先于数据写死, 只判定不提案。
    """
    xs_all, days_all, missing = _feature_values(day_table, feature)
    if not xs_all:
        return None
    day_e = {str(r["signal_date"]): float(r["day_e_net_t10"]) for r in day_table}
    paired = sorted(zip(days_all, xs_all), key=lambda t: t[0])
    mid = len(paired) // 2
    halves = (paired[:mid], paired[mid:])
    out_halves: list[dict[str, Any]] = []
    for label, half in (("前半", halves[0]), ("后半", halves[1])):
        xs = [v for _, v in half]
        ys = [day_e[d] for d, _ in half]
        out_halves.append({
            "half": label,
            "n_days": len(half),
            "pearson_r": pearson_r(xs, ys),
        })
    h1, h2 = out_halves
    if h1["n_days"] < min_half_days or h2["n_days"] < min_half_days:
        verdict = "样本不足 — 只披露"
    elif h1["pearson_r"] is None or h2["pearson_r"] is None:
        verdict = "特征退化 — 只披露"
    elif (
        h1["pearson_r"] * h2["pearson_r"] > 0
        and abs(h1["pearson_r"]) >= SPLIT_HALF_MIN_R
        and abs(h2["pearson_r"]) >= SPLIT_HALF_MIN_R
    ):
        verdict = "具备资格"
    else:
        verdict = "只披露"
    return {
        "feature": feature,
        "days_feature_missing": missing,
        "halves": out_halves,
        "verdict": verdict,
    }


def worst_days(
    day_table: Sequence[Mapping[str, Any]], k: int = WORST_DAYS_K
) -> list[dict[str, Any]]:
    """日期望最差 k 日 (并列按日期升序稳定) 的特征解剖."""
    ordered = sorted(
        day_table, key=lambda r: (float(r["day_e_net_t10"]), str(r["signal_date"]))
    )
    return [dict(r) for r in ordered[:k]]


def build_payload(
    ev: pd.DataFrame,
    court_table: Path,
    horizon: int = PRIMARY_HORIZON,
    report_date: str | None = None,
) -> dict[str, Any]:
    """装配 JSON payload (确定性; 键序由 sort_keys 序列化决定)."""
    day_table = day_feature_table(ev, horizon)
    day_net = _day_net_by_day(ev, horizon)
    attributions = [a for a in (feature_pearson(day_table, f) for f, _ in FEATURE_REGISTRY) if a]
    tercile_tables = [
        t for t in (feature_terciles(day_table, day_net, f) for f, _ in FEATURE_REGISTRY)
        if t
    ]
    stabilities = [
        s for s in (split_half_stability(day_table, f) for f, _ in FEATURE_REGISTRY)
        if s
    ]
    return {
        "title": "日层 T0 可观测特征归因 (纯诊断, 宪法 #2)",
        "report_date": report_date or date.today().isoformat(),
        "court_binding": court_binding(Path(court_table), rows=int(len(ev))),
        "caliber": {
            "universe": f"production_aligned/t{horizon}",
            "net_roundtrip_cost": ROUNDTRIP_COST,
            "caliber_note": "净=毛−0.65% (与 winrate 分解报告同式, 跨报告直比须先同口径)",
            "t0_note": "特征只用信号日收盘可得列; gap_t1_open 等 T+1 列显式排除 (决策时不可见)",
            "universe_rows": int(len(ev)),
            "days": len(day_table),
        },
        "day_features": day_table,
        "feature_attribution": attributions,
        "feature_terciles": tercile_tables,
        "split_half_stability": stabilities,
        "worst5_anatomy": worst_days(day_table),
        "discipline": {
            "constitution_2": "纯诊断: 组合路径证据是唯一经济裁判; 零判定逻辑零行为授权",
            "min_cell_n": MIN_CELL_N,
            "disclosure_only": "n<MIN_CELL_N 桶 CI=None 只披露不判定; split-half 判据预注册只判定不提案",
        },
    }


def render_md(payload: Mapping[str, Any]) -> str:
    """渲染 markdown 报告 (纪律句先于数字)."""
    L: list[str] = []
    cal = payload["caliber"]
    L.append(f"# {payload['title']} ({payload['report_date']})")
    L.append("")
    L.append("纯诊断 (宪法 #2)。回答: 信号日收盘时哪些日层 T0 特征与该日期望相关 —")
    L.append("R132 楔子三分解钉死日选择 -7.62pp 主导后的缺环量化; 本报告不构成任何")
    L.append("行为授权 — 参数变化 = 新证据世代 owner 决策。")
    L.append("")
    L.append(f"口径: {cal['caliber_note']}; 宇宙 {cal['universe']} "
             f"({cal['universe_rows']} 行 / {cal['days']} 日)")
    L.append(f"T0 可观测性: {cal['t0_note']}")
    L.append("")
    cb = payload["court_binding"]
    L.append(f"court 身份: rows={cb.get('rows')} content_digest={str(cb.get('content_digest'))[:16]}…")
    L.append("")

    L.append("## 特征 × 日期望 Pearson (日等权)")
    L.append("")
    L.append("| 特征 | n_days | Pearson r | 缺失日 |")
    L.append("|---|---|---|---|")
    for a in payload["feature_attribution"]:
        r = a["pearson_r"]
        L.append(f"| {a['feature']} | {a['n_days']} | "
                 f"{'—' if r is None else f'{r:+.3f}'} | {a['days_feature_missing']} |")
    L.append("")
    L.append("注: r=— 为常量特征或样本不足 (零方差), 如实 None 不冒充 0。")
    L.append("")

    L.append("## 特征三分位事件面 (净口径)")
    L.append("")
    for t in payload["feature_terciles"]:
        cells = t["cells"]
        head = " | ".join(
            f"{c['tercile']} E={_fmt(c['event_stats']['expectancy'])} (n={c['event_stats']['n']})"
            for c in cells
        )
        L.append(f"- **{t['feature']}**: {head}"
                 + (f" · 特征缺失 {t['days_feature_missing']} 日" if t["days_feature_missing"] else ""))
    L.append("")
    L.append(f"注: 格内事件 n<{payload['discipline']['min_cell_n']} 的聚类 CI 不产出 (只披露); "
             "三分位边界按 (特征值, 日期) 双稳定排序, 不依赖输入行序。")
    L.append("")

    L.append("## split-half 稳定性 (预注册判据: 两半同号且两半 |r|>=0.5)")
    L.append("")
    L.append("| 特征 | 前半 r (n_days) | 后半 r (n_days) | verdict |")
    L.append("|---|---|---|---|")

    def _half_cell(h: Mapping[str, Any]) -> str:
        r = h["pearson_r"]
        r_text = "—" if r is None else f"{r:+.3f}"
        return f"{r_text} ({h['n_days']})"

    for s in payload["split_half_stability"]:
        h1, h2 = s["halves"]
        L.append(f"| {s['feature']} | {_half_cell(h1)} | {_half_cell(h2)} | {s['verdict']} |")
    L.append("")

    L.append("## worst-5 信号日特征解剖")
    L.append("")
    L.append("| 信号日 | cohort | 强度均值 | 行业宽度 | board | low_vol | 日E |")
    L.append("|---|---|---|---|---|---|---|")
    for w in payload["worst5_anatomy"]:
        L.append(
            f"| {w['signal_date']} | {w['cohort_n']} ({w['cohort_bucket']}) "
            f"| {_fmt(w['strength_mean'], pct=False)} | {w['industry_breadth']} "
            f"| {_fmt(w['board_score_mean'], pct=False)} "
            f"| {_fmt(w['low_vol_score_mean'], pct=False)} "
            f"| {_fmt(w['day_e_net_t10'])} |"
        )
    L.append("")

    L.append("## 纪律")
    L.append("")
    L.append(f"- {payload['discipline']['constitution_2']}")
    L.append("- 恒等面: 特征表逐格可由宇宙行复算; 零 RNG 主面 (Pearson 确定性公式)")
    L.append(f"- {payload['discipline']['disclosure_only']}")
    L.append("- T0 可观测性: gap_t1_open 等 T+1 列显式排除 — 决策时不可见, "
             "用其归因会把执行面信息泄漏进选择面")
    L.append("- 任何据此的生产参数变化 = 策略行为变化 = 新证据世代 owner 决策")
    return "\n".join(L) + "\n"


def _fmt(v: object, pct: bool = True) -> str:
    if v is None:
        return "—"
    if not _finite(v):
        return "—"
    f = float(v)
    return f"{f * 100:+.2f}%" if pct else f"{f:+.3f}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--court-table", default=str(COURT_TABLE))
    parser.add_argument("--report-dir", default=str(REPORT_DIR))
    parser.add_argument("--date-str", default=date.today().strftime("%Y%m%d"))
    args = parser.parse_args(argv)

    court_table = Path(args.court_table)
    ev = pd.read_csv(court_table)
    universe = production_aligned(ev)
    payload = build_payload(universe, court_table, report_date=str(args.date_str))

    report_dir = Path(args.report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    md_path = report_dir / f"day_feature_attribution_{args.date_str}.md"
    json_path = report_dir / f"day_feature_attribution_{args.date_str}.json"
    md_path.write_text(render_md(payload), encoding="utf-8")
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=1),
        encoding="utf-8",
    )

    days = payload["caliber"]["days"]
    qualified = [s["feature"] for s in payload["split_half_stability"]
                 if s["verdict"] == "具备资格"]
    print(f"day_feature_attribution: {len(universe)} events / {days} days -> {md_path}")
    print(f"split-half 具备资格特征: {qualified or '无'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
