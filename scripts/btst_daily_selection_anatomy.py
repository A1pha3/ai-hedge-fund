"""日内选择结构解剖 — top_1 优势归因 + 带内日内排名 + 拥挤度 (纯诊断, R99).

第一性原理: 生产发射按 trigger_strength 降序全量放行 (daily_action.py
ranked_candidates.sort + 敞口截断), 没有每日新仓数量上限。R98 先验漂移
决策包留下未归因的落差 — top_1 日选口径 E=+1.46% vs 全体 +0.01%
(production_aligned t10): 该落差若是强度带构成 (composition), 日内排名无
独立信息, 「每日新仓上限」杠杆假设收口; 若带内日内排名 (within-day rank)
携带独立信号, 该轴是与强度阈值正交的杠杆候选 (hypothesis-generating)。

预注册定义 (先于数据写死):
- 宇宙 = production_aligned (复用 winrate_payoff_decomposition 单一实现);
- 日内排名 = signal_date 内 trigger_strength 降序、ts_code 升序 tiebreak
  (镜像生产 daily_action.py:2386-2391 的排序键), day_rank ∈ 1..n;
- top-k 视图 = 逐日 head(k) 池化 (k=1,2,3,5) vs 全体;
- 带内配对对照 = (signal_date, strength_bucket) 组内 ≥2 候选时 rank-1 vs
  rank-2+ (singleton 组从两侧同时排除 — 配对设计, 消除「独苗日只进 rank-1
  侧」的不对称);
- top_1 优势精确恒等归因:
    ΔE(top_1 − all) = rank 贡献 + 构成贡献 (零残差)
    rank 贡献  = Σ_b v_b·(E_b^{r1} − E_b)
    构成贡献   = Σ_b (v_b − w_b)·E_b
  其中 v_b/w_b = top_1/全体的强度带混合, E_b^{r1} = 该带 rank-1 笔均值
  (含独苗日 — top_1-of-day 定义; 配对表才是因果读法, 两面同时呈现);
- 拥挤度 = 每日 production_aligned 候选数分桶 1 / 2-3 / ≥4 (探索性
  in-sample 预注册, R92 同款披露语言), 笔级 E + 日级 E + 带混合;
- 稳定性判定 (R15 合取判据镜像, 只判资格不授权): 每强度带, 带内配对
  premium = E(rank-2+) − E(rank-1), 窗内时间序中位切分 split-half;
  「具备资格」iff 两半各自 rank-1/rank-2+ 格 n≥30 且 premium 符号跨半一致;
- 跨窗 = early 表 (event_tables_early, 2022-24) 整窗配对对照披露
  (幸存者偏差方向乐观化, R97 成文方向); 生产窗跨半 + 半年度切片披露。

纪律:
- 纯诊断 (宪法 #2): 任何每日新仓上限/选择规则变化 = 策略行为变化 =
  新证据世代 (owner 决策 + 预注册); 本工具不提案参数。
- 确定性: 排序显式 tiebreak; CI 复用分解工具 per-call seeded bootstrap;
  同输入逐字节同输出。

用法:
    uv run python scripts/btst_daily_selection_anatomy.py
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any, Mapping, Sequence

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from winrate_payoff_decomposition import (  # noqa: E402
    MIN_CELL_N,
    ROUNDTRIP_COST,
    ALL_STRENGTH_BUCKETS,
    production_aligned,
    strength_bucket,
    win_loss_stats,
)

COURT_TABLE = Path("data/research/btst_court/event_tables/event_table_v1.csv.gz")
EARLY_TABLE = Path("data/research/btst_court/event_tables_early/event_table_v1.csv.gz")
REPORTS_DIR = Path("data/reports")
PRIMARY_HORIZON = 10
CONTRAST_HORIZONS = (5,)
TOPK_SET = (1, 2, 3, 5)
CROWD_BUCKETS: tuple[tuple[int, int, str], ...] = (
    (1, 1, "1"),
    (2, 3, "2-3"),
    (4, 10**9, "≥4"),
)
BANDS = ("0.50-0.60", "0.60-0.70", "≥0.70")  # 生产放行带 (production_aligned 已无 <0.50)
RESIDUAL_TOL = 1e-9


def _ret_col(horizon: int) -> str:
    return f"net_ret_t{horizon}"


def with_daily_rank(u: pd.DataFrame, horizon: int) -> pd.DataFrame:
    """加 day_rank / candidates_per_day / strength_bucket / 净收益列。

    排序键镜像生产: trigger_strength 降序、ts_code 升序 (确定性 tiebreak);
    signal_date 规范化为 'YYYYMMDD' (畸形 fail-closed)。
    """
    ret_col = _ret_col(horizon)
    df = u.copy()
    df["signal_date"] = df["signal_date"].map(normalize_day)
    df["strength_bucket"] = df["trigger_strength"].map(strength_bucket)
    df[ret_col] = df[f"gross_ret_t{horizon}"] - ROUNDTRIP_COST
    df = df[df[ret_col].notna()].copy()
    df = df.sort_values(
        ["signal_date", "trigger_strength", "ts_code"],
        ascending=[True, False, True],
        kind="mergesort",
    )
    df["day_rank"] = df.groupby("signal_date").cumcount() + 1
    df["candidates_per_day"] = df.groupby("signal_date")["ts_code"].transform("size")
    return df


def topk_curve(df: pd.DataFrame, horizon: int) -> list[dict[str, Any]]:
    """逐日 head(k) 池化 vs 全体: n/E/胜率/CI90 下界/天数 (k=1,2,3,5, all)。"""
    ret_col = _ret_col(horizon)
    rows: list[dict[str, Any]] = []
    views: list[tuple[str, pd.DataFrame]] = [("all", df)]
    for k in TOPK_SET:
        views.append((f"top_{k}", df[df["day_rank"] <= k]))
    for name, sub in views:
        s = win_loss_stats(sub[ret_col].tolist(), sub["signal_date"].tolist())
        rows.append(
            {
                "view": name,
                "n": s["n"],
                "winrate": s["winrate"],
                "expectancy": s["expectancy"],
                "cluster_ci_low_90": s["cluster_ci_low_90"],
                "days": int(sub["signal_date"].nunique()),
            }
        )
    return rows


def within_band_rank_table(df: pd.DataFrame, horizon: int) -> list[dict[str, Any]]:
    """每强度带: 多候选 (signal_date, band) 组的 rank-1 vs rank-2+ 配对对照。

    singleton 组 (组内仅 1 笔) 从两侧同时排除 — 配对设计。每格
    n/胜率/E/CI90 下界; 另披露被排除的 singleton 笔数与其 E (不静默丢弃)。
    """
    ret_col = _ret_col(horizon)
    grp_size = df.groupby(["signal_date", "strength_bucket"])["ts_code"].transform("size")
    multi = df[grp_size >= 2]
    single = df[grp_size == 1]
    rows: list[dict[str, Any]] = []
    for band in BANDS:
        bm = multi[multi["strength_bucket"] == band]
        bs = single[single["strength_bucket"] == band]
        r1 = bm[bm.groupby(["signal_date", "strength_bucket"]).cumcount() == 0]
        r2 = bm[bm.groupby(["signal_date", "strength_bucket"]).cumcount() > 0]
        cell1 = win_loss_stats(r1[ret_col].tolist(), r1["signal_date"].tolist())
        cell2 = win_loss_stats(r2[ret_col].tolist(), r2["signal_date"].tolist())
        singleton = win_loss_stats(bs[ret_col].tolist(), bs["signal_date"].tolist()) if len(bs) else None
        premium = (
            float(cell2["expectancy"]) - float(cell1["expectancy"])
            if (cell1["expectancy"] is not None and cell2["expectancy"] is not None)
            else None
        )
        rows.append(
            {
                "band": band,
                "rank1": cell1,
                "rank2plus": cell2,
                "premium_rank2plus_minus_rank1": premium,
                "singleton_days_excluded": {
                    "n": singleton["n"] if singleton else 0,
                    "expectancy": singleton["expectancy"] if singleton else None,
                },
            }
        )
    return rows


def top1_gap_attribution(df: pd.DataFrame, horizon: int) -> dict[str, Any]:
    """top_1 − all 的精确恒等归因: rank 贡献 + 构成贡献 (零残差断言)。

    E_b^{r1} 含独苗日 rank-1 (top_1-of-day 定义) — 与配对表口径的差异
    在报告里成文; 恒等式按构造精确成立。
    """
    ret_col = _ret_col(horizon)
    top1 = df[df["day_rank"] == 1]
    e_all = float(df[ret_col].mean())
    e_top1 = float(top1[ret_col].mean())
    w = {b: len(df[df["strength_bucket"] == b]) / len(df) for b in ALL_STRENGTH_BUCKETS}
    v = {b: len(top1[top1["strength_bucket"] == b]) / len(top1) for b in ALL_STRENGTH_BUCKETS}
    rank_contrib = 0.0
    comp_contrib = 0.0
    per_band: dict[str, dict[str, float]] = {}
    for b in ALL_STRENGTH_BUCKETS:
        sub = df[df["strength_bucket"] == b]
        sub1 = top1[top1["strength_bucket"] == b]
        e_b = float(sub[ret_col].mean()) if len(sub) else 0.0
        e_b1 = float(sub1[ret_col].mean()) if len(sub1) else 0.0
        rc = v[b] * (e_b1 - e_b)
        cc = (v[b] - w[b]) * e_b
        rank_contrib += rc
        comp_contrib += cc
        per_band[b] = {
            "w_all": w[b],
            "v_top1": v[b],
            "e_band": e_b,
            "e_band_rank1": e_b1,
            "rank_contribution": rc,
            "composition_contribution": cc,
        }
    delta = e_top1 - e_all
    residual = delta - (rank_contrib + comp_contrib)
    if abs(residual) > RESIDUAL_TOL:
        raise AssertionError(f"attribution identity residual {residual:.3e} exceeds tol")
    return {
        "e_all": e_all,
        "e_top1": e_top1,
        "delta": delta,
        "rank_contribution": rank_contrib,
        "composition_contribution": comp_contrib,
        "residual": residual,
        "per_band": per_band,
    }


def crowding_table(df: pd.DataFrame, horizon: int) -> list[dict[str, Any]]:
    """每日候选数分桶 (1/2-3/≥4): 笔级 E、日级 E、带混合 (构成披露)。"""
    ret_col = _ret_col(horizon)
    rows: list[dict[str, Any]] = []
    for lo, hi, label in CROWD_BUCKETS:
        sub = df[(df["candidates_per_day"] >= lo) & (df["candidates_per_day"] <= hi)]
        if not len(sub):
            rows.append({"bucket": label, "n": 0, "days": 0})
            continue
        trade = win_loss_stats(sub[ret_col].tolist(), sub["signal_date"].tolist())
        daily_mean = float(sub.groupby("signal_date")[ret_col].mean().mean())
        mix = {
            b: round(len(sub[sub["strength_bucket"] == b]) / len(sub), 4)
            for b in ALL_STRENGTH_BUCKETS
            if len(sub[sub["strength_bucket"] == b])
        }
        rows.append(
            {
                "bucket": label,
                "n": trade["n"],
                "days": int(sub["signal_date"].nunique()),
                "trade_level": {
                    "winrate": trade["winrate"],
                    "expectancy": trade["expectancy"],
                    "cluster_ci_low_90": trade["cluster_ci_low_90"],
                },
                "day_level_mean_expectancy": daily_mean,
                "band_mix": mix,
            }
        )
    return rows


def _split_halves(dates: Sequence[str]) -> tuple[list[str], list[str]]:
    """时间序中位切分 (奇数日前半含中位; 与 census.split_halves 同语义)。"""
    ordered = sorted(set(dates))
    mid = (len(ordered) + 1) // 2
    return ordered[:mid], ordered[mid:]


def _band_premium_stats(
    df: pd.DataFrame, horizon: int, band: str | None, dates: Sequence[str] | None = None
) -> dict[str, Any]:
    """配对 premium (E(rank2+) − E(rank1)); band=None 池化全部带; dates 限定子窗。"""
    ret_col = _ret_col(horizon)
    sub = df if dates is None else df[df["signal_date"].isin(set(dates))]
    if band is not None:
        sub = sub[sub["strength_bucket"] == band]
    grp_size = sub.groupby(["signal_date", "strength_bucket"])["ts_code"].transform("size")
    multi = sub[grp_size >= 2]
    cum = multi.groupby(["signal_date", "strength_bucket"]).cumcount()
    r1 = win_loss_stats(multi[cum == 0][ret_col].tolist(), multi[cum == 0]["signal_date"].tolist())
    r2 = win_loss_stats(multi[cum > 0][ret_col].tolist(), multi[cum > 0]["signal_date"].tolist())
    premium = (
        float(r2["expectancy"]) - float(r1["expectancy"])
        if (r1["expectancy"] is not None and r2["expectancy"] is not None)
        else None
    )
    return {"rank1": r1, "rank2plus": r2, "premium": premium}


def rank_premium_stability(df: pd.DataFrame, horizon: int) -> list[dict[str, Any]]:
    """每强度带 split-half 资格判定 (R15 合取判据镜像: 两半各格 n≥30 且
    premium 符号跨半一致 → qualified; 否则按缺口命名)。

    premium < 0 = rank-1 更好 (日内排名携带信息); premium > 0 = 排名末位更好
    (拥挤稀释); 判定只命名资格与方向, 不授权任何行为。
    """
    h1_dates, h2_dates = _split_halves(df["signal_date"].tolist())
    rows: list[dict[str, Any]] = []
    for band in BANDS:
        s1 = _band_premium_stats(df, horizon, band, h1_dates)
        s2 = _band_premium_stats(df, horizon, band, h2_dates)
        n_ok = all(
            cell["n"] >= MIN_CELL_N
            for cell in (s1["rank1"], s1["rank2plus"], s2["rank1"], s2["rank2plus"])
        )
        p1, p2 = s1["premium"], s2["premium"]
        if not n_ok or p1 is None or p2 is None:
            verdict = "insufficient"
        elif (p1 < 0) == (p2 < 0):
            verdict = "qualified_sign_consistent"
        else:
            verdict = "sign_flip"
        rows.append(
            {
                "band": band,
                "half1": {"premium": p1, "rank1_n": s1["rank1"]["n"], "rank2plus_n": s1["rank2plus"]["n"]},
                "half2": {"premium": p2, "rank1_n": s2["rank1"]["n"], "rank2plus_n": s2["rank2plus"]["n"]},
                "verdict": verdict,
            }
        )
    return rows


def cross_window_premium(
    early_df: pd.DataFrame | None, horizon: int
) -> list[dict[str, Any]] | None:
    """early 窗 (2022-24) 整窗带内配对 premium 披露 (幸存者偏差方向成文)。"""
    if early_df is None or not len(early_df):
        return None
    rows = []
    for band in BANDS:
        s = _band_premium_stats(early_df, horizon, band)
        rows.append(
            {
                "band": band,
                "premium": s["premium"],
                "rank1_n": s["rank1"]["n"],
                "rank2plus_n": s["rank2plus"]["n"],
                "rank1_e": s["rank1"]["expectancy"],
                "rank2plus_e": s["rank2plus"]["expectancy"],
            }
        )
    return rows


def segment_premium(df: pd.DataFrame, horizon: int) -> list[dict[str, Any]]:
    """半年度切片 × 池化带内 premium (方向性披露, 切片边界沿用分解工具)。"""
    from review_btst_prior_court import TIME_SLICE_BOUNDS

    rows: list[dict[str, Any]] = []
    for label, lo, hi in TIME_SLICE_BOUNDS:
        sub = df[(df["signal_date"] >= str(lo)) & (df["signal_date"] <= str(hi))]
        if not len(sub):
            continue
        pooled = _band_premium_stats(sub, horizon, None)
        rows.append({"segment": label, "n": len(sub), "premium": pooled["premium"]})
    return rows


def normalize_day(value: object) -> str:
    """signal_date → 'YYYYMMDD' 字符串 (镜像 census 语义, 畸形值 fail-closed)。"""
    text = str(value).replace("-", "").strip()
    if len(text) == 8 and text.isdigit():
        return text
    raise ValueError(f"unparseable signal_date: {value!r}")


def load_universe(path: Path) -> pd.DataFrame:
    ev = pd.read_csv(path)
    u = production_aligned(ev)
    return u


def build_report(
    court_path: Path, early_path: Path | None, horizons: Sequence[int]
) -> dict[str, Any]:
    u = load_universe(court_path)
    early_u = load_universe(early_path) if early_path and early_path.exists() else None
    report: dict[str, Any] = {
        "generated_for": str(court_path),
        "min_cell_n": MIN_CELL_N,
        "horizons": {},
    }
    for h in horizons:
        df = with_daily_rank(u, h)
        early_df = with_daily_rank(early_u, h) if early_u is not None else None
        report["horizons"][f"t{h}"] = {
            "n": len(df),
            "days": int(df["signal_date"].nunique()),
            "topk_curve": topk_curve(df, h),
            "within_band_rank": within_band_rank_table(df, h),
            "top1_gap_attribution": top1_gap_attribution(df, h),
            "crowding": crowding_table(df, h),
            "rank_premium_stability": rank_premium_stability(df, h),
            "segment_premium": segment_premium(df, h),
            "cross_window_early": cross_window_premium(early_df, h),
        }
    return report


def render_markdown(report: Mapping[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# 日内选择结构解剖 (top_1 归因 / 带内排名 / 拥挤度)")
    lines.append("")
    lines.append("纯诊断 (宪法 #2)。生产发射按强度降序全量放行 (无每日新仓上限);")
    lines.append("本工具回答 top_1 优势 = 强度带构成 vs 带内日内排名, 以及拥挤日是否稀释 E。")
    lines.append("任何每日新仓上限/选择规则 = 策略行为变化 = 新证据世代 (owner 决策)。")
    lines.append("")
    lines.append("口径: 宇宙 = production_aligned (复用分解工具单一实现 — 含 <0.50 行,")
    lines.append("与分解报告 ALL 逐字对齐); 带内配对面只覆盖生产放行带 (0.50+),")
    lines.append("<0.50 行仅出现在 top-k/拥挤度视图。")
    lines.append("")
    for key, block in report["horizons"].items():
        lines.append(f"## {key} (n={block['n']}, {block['days']} 日)")
        lines.append("")
        lines.append("### top-k 曲线")
        lines.append("| 视图 | n | 天数 | 胜率 | E | CI90下界 |")
        lines.append("|---|---|---|---|---|---|")
        for row in block["topk_curve"]:
            wr = "—" if row["winrate"] is None else f"{row['winrate']:+.2%}"
            e = "—" if row["expectancy"] is None else f"{row['expectancy']:+.2%}"
            ci = "—" if row["cluster_ci_low_90"] is None else f"{row['cluster_ci_low_90']:+.2%}"
            lines.append(f"| {row['view']} | {row['n']} | {row['days']} | {wr} | {e} | {ci} |")
        lines.append("")
        lines.append("### 带内日内排名 (多候选日×带配对; singleton 侧披露)")
        lines.append("| 带 | r1 n | r1 E | r2+ n | r2+ E | premium | singleton n/E |")
        lines.append("|---|---|---|---|---|---|---|")
        for row in block["within_band_rank"]:
            r1, r2 = row["rank1"], row["rank2plus"]
            e1 = "—" if r1["expectancy"] is None else f"{r1['expectancy']:+.2%}"
            e2 = "—" if r2["expectancy"] is None else f"{r2['expectancy']:+.2%}"
            pm = "—" if row["premium_rank2plus_minus_rank1"] is None else f"{row['premium_rank2plus_minus_rank1']:+.2%}"
            sn = row["singleton_days_excluded"]
            se = "—" if sn["expectancy"] is None else f"{sn['expectancy']:+.2%}"
            lines.append(f"| {row['band']} | {r1['n']} | {e1} | {r2['n']} | {e2} | {pm} | {sn['n']} / {se} |")
        lines.append("")
        att = block["top1_gap_attribution"]
        lines.append("### top_1 − 全体 恒等归因 (零残差)")
        lines.append(f"- E(top_1)={att['e_top1']:+.4%} · E(all)={att['e_all']:+.4%} · ΔE={att['delta']:+.4%}")
        lines.append(f"- rank 贡献 {att['rank_contribution']:+.4%} · 构成贡献 {att['composition_contribution']:+.4%} · 残差 {att['residual']:.2e}")
        lines.append("")
        lines.append("### 拥挤度 (每日候选数)")
        lines.append("| 桶 | n | 天数 | 笔级E | CI90下界 | 日级E | 带混合 |")
        lines.append("|---|---|---|---|---|---|---|")
        for row in block["crowding"]:
            if not row.get("n"):
                lines.append(f"| {row['bucket']} | 0 | 0 | — | — | — | — |")
                continue
            t = row["trade_level"]
            ci = "—" if t["cluster_ci_low_90"] is None else f"{t['cluster_ci_low_90']:+.2%}"
            mix = ", ".join(f"{b}:{p:.0%}" for b, p in row["band_mix"].items())
            lines.append(
                f"| {row['bucket']} | {row['n']} | {row['days']} | {t['expectancy']:+.2%} | {ci} | "
                f"{row['day_level_mean_expectancy']:+.2%} | {mix} |"
            )
        lines.append("")
        lines.append("### 带内排名 premium split-half 资格 (R15 合取判据镜像)")
        lines.append("| 带 | 前半 premium (n1/n2) | 后半 premium (n1/n2) | 判定 |")
        lines.append("|---|---|---|---|")
        for row in block["rank_premium_stability"]:
            h1, h2 = row["half1"], row["half2"]
            f1 = "—" if h1["premium"] is None else f"{h1['premium']:+.2%}"
            f2 = "—" if h2["premium"] is None else f"{h2['premium']:+.2%}"
            lines.append(
                f"| {row['band']} | {f1} ({h1['rank1_n']}/{h1['rank2plus_n']}) | "
                f"{f2} ({h2['rank1_n']}/{h2['rank2plus_n']}) | {row['verdict']} |"
            )
        lines.append("")
        lines.append("### 半年度切片池化 premium (方向披露)")
        for row in block["segment_premium"]:
            pm = "—" if row["premium"] is None else f"{row['premium']:+.2%}"
            lines.append(f"- {row['segment']}: n={row['n']}, premium={pm}")
        cw = block["cross_window_early"]
        if cw:
            lines.append("")
            lines.append("### early 窗 (2022-24) 整窗配对 premium (幸存者偏差乐观化, 方向性披露)")
            for row in cw:
                pm = "—" if row["premium"] is None else f"{row['premium']:+.2%}"
                e1 = "—" if row["rank1_e"] is None else f"{row['rank1_e']:+.2%}"
                e2 = "—" if row["rank2plus_e"] is None else f"{row['rank2plus_e']:+.2%}"
                lines.append(
                    f"- {row['band']}: premium={pm} (r1 n={row['rank1_n']} E={e1}, "
                    f"r2+ n={row['rank2plus_n']} E={e2})"
                )
        lines.append("")
    lines.append("## 纪律")
    lines.append("")
    lines.append("- 本报告是诊断证据, 不是参数变更提案; 任何每日新仓上限/选择规则调整 =")
    lines.append("  策略行为变化 = 新证据世代 (owner 决策 + 预注册)。")
    lines.append("- premium = E(rank-2+) − E(rank-1): 负 = rank-1 更好; n<30 只披露不判定。")
    lines.append("- 确定性: 显式 tiebreak + per-call seeded bootstrap; 同输入逐字节同输出。")
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--court-table", type=Path, default=COURT_TABLE)
    parser.add_argument("--early-table", type=Path, default=EARLY_TABLE)
    parser.add_argument(
        "--horizons", type=int, nargs="+", default=[PRIMARY_HORIZON, *CONTRAST_HORIZONS]
    )
    parser.add_argument("--reports-dir", type=Path, default=REPORTS_DIR)
    args = parser.parse_args(argv)

    report = build_report(args.court_table, args.early_table, args.horizons)
    args.reports_dir.mkdir(parents=True, exist_ok=True)
    stem = f"daily_selection_anatomy_{date.today():%Y%m%d}"
    json_path = args.reports_dir / f"{stem}.json"
    md_path = args.reports_dir / f"{stem}.md"
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8"
    )
    md_path.write_text(render_markdown(report), encoding="utf-8")
    print(f"wrote {json_path} and {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
