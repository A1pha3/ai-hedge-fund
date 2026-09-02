"""BTST 持有期配对差证据包 — 选择效应修正 + 资金占用调整 (t2..t15 vs T+10).

第一性原理: R95 horizon_curve 实锤 T+10 非 E 最优退出点 (production_aligned
t14 E=+1.99% CI[+0.62] vs t10 +1.32% CI[−0.29]), 但其 ΔE 是**跨事件集比较**
(t10 n=1378 vs t14 n=1354) — unexited 选择效应未修正; 且 E(per-trade) 提升未做
资金占用调整。本工具在同一事件内配对比较两个持有期, 让两个 confound 都可观测:

  1. 配对差 (选择效应消元): k>10 时可退出(k) ⊆ 可退出(10) (顺延语义下更长
     窗口蕴含更短窗口), 故共享交集 = 可退出(k) 事件集; 在该集合上逐事件
     d_i = net_k(i) − net_10(i)。持有期比较不再混杂「近期事件是否入选」。
  2. 对齐基线漂移: 每 k 披露 t10 在该 k 交集上的基线 E 与 t10 全样本 E 之差
     — 选择效应的大小本身成为可观测对象, 不再是隐藏假设。
  3. 边际对数增速 (资金占用调整): mean(log(1+net_k) − log(1+net_10))/(k−10)。
     宪法 #2 的经济目标是组合单位净值长期对数增长; 多持有 (k−10) 天换来的
     边际对数收益若为负, per-trade E 提升不构成采纳理由。一阶近似: 单票串行
     资金、无再入场机会成本建模 (组合级留 owner 前向 Trial)。
     **方向语义**: k>10 时正值 = 延长持有的每日边际对数收益 (好); k<10 时
     除以负天数 — 正值 = **缩短持有的每日对数代价** (提前退出放弃的收益,
     不是延长收益), 解读方向相反, 渲染层有标注。
  4. 稳定性: split-half (signal_date 中点切分) 符号合取 + 跨焦点 k 排序稳定
     (R15 判据镜像); regime/strength 切面 (n<30 只披露); early 窗同构。

纪律 (先于数据写死):
  - 复用单一实现: event_horizon_gross/aligned_mask (btst_horizon_curve),
    cluster_boot_ci_low/win_loss_stats/strength_bucket (winrate_payoff_
    decomposition)。零口径 fork。
  - 聚类 CI per-call seeded RNG (R13); n<MIN_CELL_N 只披露不判定。
  - 预注册焦点 k∈{12,14} (R95 报告锚定: t14 E 峰 / t12 胜率峰); 全曲线
    t2..t15 同表披露, 焦点列 Bonferroni×2 注记 — 不做事后挑亮。
  - 确定性: 同输入逐字节同输出。

纯诊断 (宪法 #2): 持有期契约 (T+10) 变化 = 新证据世代 owner 决策, 本工具只产出证据。

用法:
    uv run python scripts/btst_holding_evidence.py
    uv run python scripts/btst_holding_evidence.py --output-json PATH --output-md PATH
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

import pandas as pd

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from scripts.btst_exit_anatomy import (  # noqa: E402
    ANATOMY_CAL_START,
    EARLY_DAILY_DIR,
    EVENT_TABLE,
    EVENT_TABLE_EARLY,
    RAW_DAILY_DIR,
    extract_path_bars,
    load_daily_bars,
    load_event_table,
    sessions_for_window,
)
from scripts._btst_court_common import (  # noqa: E402
    FORWARD_SESSIONS,
    load_sessions,
)
from scripts.btst_horizon_curve import (  # noqa: E402
    HORIZONS,
    PRIMARY_K,
    _offset,
    aligned_mask,
    event_horizon_gross,
)
from scripts.winrate_payoff_decomposition import (  # noqa: E402
    MIN_CELL_N,
    ROUNDTRIP_COST,
    cluster_boot_ci_low,
    strength_bucket,
    win_loss_stats,
)

# ---- 预注册常量 ----
FOCUS_KS = (12, 14)  # R95 锚定: t14 E 峰 / t12 胜率峰; 报告 Bonferroni×2 注记
SPEARMAN_MIN = 0.5  # R15 合取判据的排序稳定分量


def holding_evidence_error(message: str) -> "SystemExit":
    print(f"btst_holding_evidence: {message}", file=sys.stderr)
    return SystemExit(2)


# ---------------------------------------------------------------------------
# 配对差核心 (纯函数, 测试锚点)
# ---------------------------------------------------------------------------

def paired_rows(
    grids: list[dict[int, float]],
    signal_days: list[str],
    extras: list[dict[str, Any]],
    k: int,
) -> list[dict[str, Any]] | None:
    """k vs PRIMARY_K 的共享交集配对行。

    交集 = 同时含 k 与 PRIMARY_K 毛收益网格的事件 (k>10 时即可退出(k) 事件集,
    嵌套性由测试钉死)。返回 None 表示 k 非法 (k == PRIMARY_K 或窗口外)。
    """
    if k == PRIMARY_K or k not in HORIZONS:
        return None
    rows: list[dict[str, Any]] = []
    for grid, day, extra in zip(grids, signal_days, extras):
        if k in grid and PRIMARY_K in grid:
            net_k = grid[k] - ROUNDTRIP_COST
            net_10 = grid[PRIMARY_K] - ROUNDTRIP_COST
            rows.append(
                {
                    "d": net_k - net_10,
                    "log_d": math.log1p(net_k) - math.log1p(net_10),
                    "day": day,
                    **extra,
                }
            )
    return rows


def paired_summary(
    rows: list[dict[str, Any]],
    k: int,
) -> dict[str, Any]:
    """配对差聚合: 均值 + 聚类 CI90 下界 + 边际对数增速 + 事件数。确定性。"""
    ds = [r["d"] for r in rows]
    days = [r["day"] for r in rows]
    return {
        "k": k,
        "n": len(rows),
        "mean_d": (sum(ds) / len(ds)) if rows else None,
        "ci90_low": (
            cluster_boot_ci_low(ds, days) if len(ds) >= MIN_CELL_N else None
        ),
        # 边际对数增速: 多持有 (k−10) 天的平均对数收益增量 (k>10 时除正天数)
        "marginal_log_per_day": (
            (sum(r["log_d"] for r in rows) / len(rows)) / (k - PRIMARY_K)
            if rows
            else None
        ),
    }


def aligned_baseline_drift(
    grids: list[dict[int, float]],
    signal_days: list[str],
    k: int,
) -> dict[str, Any] | None:
    """对齐基线漂移: t10 在 k 交集上的 E vs t10 全样本 E (选择效应可观测)。"""
    if k == PRIMARY_K or k not in HORIZONS:
        return None
    sub: list[float] = []
    days: list[str] = []
    full: list[float] = []
    for grid, day in zip(grids, signal_days):
        if PRIMARY_K in grid:
            full.append(grid[PRIMARY_K] - ROUNDTRIP_COST)
            if k in grid:
                sub.append(grid[PRIMARY_K] - ROUNDTRIP_COST)
                days.append(day)
    e_full = (sum(full) / len(full)) if full else None
    e_sub = (sum(sub) / len(sub)) if sub else None
    return {
        "k": k,
        "n_full": len(full),
        "n_aligned": len(sub),
        "e10_full": e_full,
        "e10_aligned": e_sub,
        "drift": (e_sub - e_full) if (e_sub is not None and e_full is not None) else None,
    }


def split_half_verdict(
    rows: list[dict[str, Any]],
    all_days: list[str],
) -> dict[str, Any]:
    """split-half 符号合取 (R15 判据镜像): 时间中点切分, 两半配对差符号一致
    才 sign_consistent; 单日/退化切分如实标注不判定。"""
    if not rows or not all_days:
        return {"sign_consistent": None, "reason": "empty_input"}
    sorted_days = sorted(set(all_days))
    if len(sorted_days) < 2:
        return {"sign_consistent": None, "reason": "single_day"}
    mid = sorted_days[len(sorted_days) // 2]
    first = [r["d"] for r in rows if r["day"] < mid]
    second = [r["d"] for r in rows if r["day"] >= mid]
    if not first or not second:
        return {"sign_consistent": None, "reason": "degenerate_split"}
    m1 = sum(first) / len(first)
    m2 = sum(second) / len(second)
    consistent = (m1 > 0 and m2 > 0) or (m1 < 0 and m2 < 0)
    return {
        "sign_consistent": consistent,
        "split_date": mid,
        "mean_d_first": m1,
        "mean_d_second": m2,
        "n_first": len(first),
        "n_second": len(second),
    }


def _spearman(a: list[float], b: list[float]) -> float | None:
    """Spearman rank 相关 (纯函数, 无 scipy 依赖); <2 点或零分母返回 None。"""
    if len(a) != len(b) or len(a) < 2:
        return None

    def _ranks(xs: list[float]) -> list[float]:
        order = sorted(range(len(xs)), key=lambda i: xs[i])
        ranks = [0.0] * len(xs)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
                j += 1
            avg = (i + j) / 2 + 1
            for t in range(i, j + 1):
                ranks[order[t]] = avg
            i = j + 1
        return ranks

    ra, rb = _ranks(a), _ranks(b)
    n = len(a)
    d2 = sum((x - y) ** 2 for x, y in zip(ra, rb))
    denom = n * (n * n - 1)
    return 1 - 6 * d2 / denom if denom else None


def qualification(
    summaries: dict[int, dict[str, Any]],
    splits: dict[int, dict[str, Any]],
) -> dict[str, Any]:
    """R15 合取判据 (镜像): 焦点 k 各自 CI 越零 ∧ split-half 符号一致 →
    supported; 排序稳定分量 = 焦点 k 的 mean_d 排序在两半窗之间 Spearman≥0.5
    (焦点 <3 个时排序不可估, 如实 None 不做惩罚性放大)。全部 supported 且
    排序不违背 → qualified; 任一不满足 → not_qualified。"""
    focus = {k: summaries[k] for k in FOCUS_KS if k in summaries}
    verdicts: dict[int, str] = {}
    for k, s in focus.items():
        ci = s.get("ci90_low")
        sign = splits.get(k, {}).get("sign_consistent")
        if ci is None or sign is None:
            verdicts[k] = "insufficient_n"
        elif ci > 0 and sign:
            verdicts[k] = "supported"
        else:
            verdicts[k] = "not_supported"
    rho: float | None = None
    if len(focus) >= 3:
        ks = sorted(focus)
        firsts = []
        seconds = []
        for k in ks:
            sp = splits.get(k, {})
            f, s2 = sp.get("mean_d_first"), sp.get("mean_d_second")
            if f is None or s2 is None:
                firsts, seconds = [], []
                break
            firsts.append(f)
            seconds.append(s2)
        if firsts:
            rho = _spearman(firsts, seconds)
    qualified = bool(verdicts) and all(v == "supported" for v in verdicts.values()) and (
        rho is None or rho >= SPEARMAN_MIN
    )
    # 家族级稳健性: 焦点对 (Bonferroni×2) 之外, 全 k 曲线里 CI 越零的计数 —
    # 焦点选择的事后性 (t12/t14 是 R95 看数据后的峰) 使该披露成为消费纪律:
    # 若家族内有越零 k, 「焦点未越零」的结论不能外推为「持有轴无信号」。
    ks_judged = sorted(k for k, s in summaries.items() if s.get("ci90_low") is not None)
    ks_above = sorted(k for k in ks_judged if summaries[k]["ci90_low"] > 0)
    family = {
        "n_ks_judged": len(ks_judged),
        "n_ks_ci_above_zero": len(ks_above),
        "ks_ci_above_zero": ks_above,
    }
    return {
        "qualified": qualified,
        "focus_k": list(FOCUS_KS),
        "per_k": {str(k): v for k, v in verdicts.items()},
        "spearman_halves": rho,
        "family_robustness": family,
        "criterion": "focus CI90_low>0 ∧ split-half sign consistent ∧ (3+ focus: halves Spearman≥0.5)",
    }


# ---------------------------------------------------------------------------
# 宇宙分析 (镜像 btst_horizon_curve.analyze_universe 的构造纪律)
# ---------------------------------------------------------------------------

def _build_grids(
    ev: pd.DataFrame,
    raw_dir: Path,
    cal: list[str],
) -> dict[str, Any]:
    """逐事件毛收益网格 + 排除计数 + work 位置对齐 (与 horizon_curve 同构)。"""
    work = ev[ev["fillable"] == True].copy()  # noqa: E712
    sessions_union = sorted(
        {
            s
            for _, e in work.iterrows()
            if _offset(e) is not None
            for s in sessions_for_window(str(e["signal_date"]), FORWARD_SESSIONS, cal)
        }
    )
    by_day = load_daily_bars(raw_dir, sessions_union)
    grids: list[dict[int, float]] = []
    days: list[str] = []
    extras: list[dict[str, Any]] = []
    work_pos: list[int] = []
    exclusions: dict[str, int] = {}
    for pos, (_, event) in enumerate(work.iterrows()):
        out = event_horizon_gross(event, by_day, cal)
        if not out or all(isinstance(key, str) for key in out):
            key = next(iter(out)) if out else "excluded_no_exit_bars"
            exclusions[key] = exclusions.get(key, 0) + 1
            continue
        grids.append(out)  # type: ignore[arg-type]
        days.append(str(event["signal_date"]))
        strength = event.get("trigger_strength")
        extras.append(
            {
                "regime": str(event.get("regime_label", event.get("regime", "unknown"))),
                "strength": (
                    float(strength)
                    if strength is not None
                    and not (isinstance(strength, float) and strength != strength)
                    else None
                ),
            }
        )
        work_pos.append(pos)
    return {
        "grids": grids,
        "days": days,
        "extras": extras,
        "exclusions": exclusions,
        "work_pos": work_pos,
        "work": work,
    }


def analyze_universe(ev: pd.DataFrame, raw_dir: Path, cal: list[str]) -> dict[str, Any]:
    """单宇宙端到端: 配对差曲线 + 漂移 + split-half + 切面 + 资格判定。"""
    built = _build_grids(ev, raw_dir, cal)
    grids, days, extras = built["grids"], built["days"], built["extras"]
    mask = aligned_mask(built["work"])

    def _scope(idx: list[int]) -> dict[str, Any]:
        g = [grids[i] for i in idx]
        d = [days[i] for i in idx]
        x = [extras[i] for i in idx]
        curve: list[dict[str, Any]] = []
        drift: list[dict[str, Any]] = []
        splits: dict[int, dict[str, Any]] = {}
        summaries: dict[int, dict[str, Any]] = {}
        for k in HORIZONS:
            if k == PRIMARY_K:
                net10 = [grid[PRIMARY_K] - ROUNDTRIP_COST for grid in g if PRIMARY_K in grid]
                stats = win_loss_stats(net10)
                stats.update({"k": k, "n": len(net10)})
                curve.append(stats)
                continue
            rows = paired_rows(g, d, x, k)
            assert rows is not None
            s = paired_summary(rows, k)
            summaries[k] = s
            curve.append(s)
            drift_row = aligned_baseline_drift(g, d, k)
            assert drift_row is not None
            drift.append(drift_row)
            splits[k] = split_half_verdict(rows, d)
        slices: dict[str, Any] = {}
        for k in FOCUS_KS:
            rows = paired_rows(g, d, x, k)
            assert rows is not None
            by_regime: dict[str, tuple[list[float], list[str]]] = {}
            by_strength: dict[str, tuple[list[float], list[str]]] = {}
            for r in rows:
                vals, dd = by_regime.setdefault(r["regime"], ([], []))
                vals.append(r["d"])
                dd.append(r["day"])
                s_vals, s_days = by_strength.setdefault(
                    strength_bucket(r["strength"]), ([], [])
                )
                s_vals.append(r["d"])
                s_days.append(r["day"])
            slices[f"t{k}"] = {
                "by_regime": {
                    key: {
                        "n": len(v),
                        "mean_d": sum(v) / len(v),
                        "ci90_low": (
                            cluster_boot_ci_low(v, dd) if len(v) >= MIN_CELL_N else None
                        ),
                    }
                    for key, (v, dd) in sorted(by_regime.items())
                },
                "by_strength": {
                    key: {
                        "n": len(v),
                        "mean_d": sum(v) / len(v),
                        "ci90_low": (
                            cluster_boot_ci_low(v, dd) if len(v) >= MIN_CELL_N else None
                        ),
                    }
                    for key, (v, dd) in sorted(by_strength.items())
                },
            }
        return {
            "n_events": len(g),
            "exclusions": dict(built["exclusions"]),
            "curve": curve,
            "baseline_drift": drift,
            "split_half": {str(k): v for k, v in splits.items()},
            "slices": slices,
            "qualification": qualification(summaries, splits),
        }

    payload: dict[str, Any] = {"all_candidates": _scope(list(range(len(grids))))}
    if mask is not None:
        aligned_idx = [
            i for i, pos in enumerate(built["work_pos"]) if mask[pos]
        ]
        payload["production_aligned"] = _scope(aligned_idx)
    else:
        payload["production_aligned"] = {"skipped": "production_filter_columns_missing"}
    return payload


# ---------------------------------------------------------------------------
# 渲染 + CLI
# ---------------------------------------------------------------------------


def _fmt_pct(v: object) -> str:
    return "—" if v is None else f"{float(v) * 100:+.2f}%"


def render_md(payload: dict[str, Any]) -> str:
    lines = [
        "# BTST 持有期配对差证据包 (t2..t15 vs T+10, 共享交集, 净口径)",
        "",
        "纯诊断 (宪法 #2); 配对差在同一事件集内消元 unexited 选择效应;",
        "对齐基线漂移单独披露; 边际对数增速 = 资金占用调整后的每持有日对数增量;",
        "**方向**: k>10 边际列正值 = 延长持有每日边际对数收益; k<10 除以负天数,",
        "正值 = 缩短持有的每日对数代价 (提前退出放弃的收益) — 解读方向相反;",
        f"预注册焦点 k∈{list(FOCUS_KS)} (R95 锚定, Bonferroni×2); 全曲线同表披露;",
        "CI 为信号日聚类 bootstrap 90% 下界 (per-call seeded); n<30 只披露不判定。",
        "",
    ]
    for universe, block in payload.items():
        for scope in ("production_aligned", "all_candidates"):
            agg = block.get(scope)
            if agg is None:
                continue
            lines.append(f"## {universe} / {scope}")
            if "skipped" in agg:
                lines.append("")
                lines.append(f"skipped: {agg['skipped']}")
                lines.append("")
                continue
            lines[-1] += f" (n={agg['n_events']})"
            lines.append("")
            lines.append("| k | n | mean_d | CI90下界 | 边际log/天 | 对齐基线E10 | 基线漂移 | split-half |")
            lines.append("|---|---|---|---|---|---|---|---|")
            drift_by_k = {r["k"]: r for r in agg["baseline_drift"]}
            split_by_k = {int(k): v for k, v in agg["split_half"].items()}
            for r in agg["curve"]:
                k = r["k"]
                if k == PRIMARY_K:
                    lines.append(
                        f"| t{k} (基准) | {r['n']} | — | {_fmt_pct(r.get('ci90_low'))} "
                        f"| — | {_fmt_pct(r.get('expectancy'))} | — | — |"
                    )
                    continue
                dr = drift_by_k.get(k, {})
                sp = split_by_k.get(k, {})
                sign = sp.get("sign_consistent")
                sign_txt = (
                    "—" if sign is None else ("一致" if sign else "翻转")
                )
                lines.append(
                    f"| t{k}{' *' if k in FOCUS_KS else ''} | {r['n']} "
                    f"| {_fmt_pct(r['mean_d'])} | {_fmt_pct(r['ci90_low'])} "
                    f"| {_fmt_pct(r['marginal_log_per_day'])} "
                    f"| {_fmt_pct(dr.get('e10_aligned'))} | {_fmt_pct(dr.get('drift'))} "
                    f"| {sign_txt} |"
                )
            lines.append("")
            q = agg["qualification"]
            lines.append(
                f"资格判定 (R15 合取镜像): **{'qualified' if q['qualified'] else 'not_qualified'}**"
                f" — per_k={q['per_k']}, halves_spearman={q['spearman_halves']}"
            )
            fam = q.get("family_robustness") or {}
            if fam:
                if fam["n_ks_ci_above_zero"] == 0:
                    fam_txt = (
                        f"family robust: no k has paired CI90>0 "
                        f"({fam['n_ks_judged']} k judged) — not_qualified 对焦点选择事后性与"
                        " 多重比较稳健"
                    )
                else:
                    fam_txt = (
                        f"family caveat: {fam['n_ks_ci_above_zero']}/{fam['n_ks_judged']} k "
                        f"CI90>0 {fam['ks_ci_above_zero']} — 焦点未越零不可外推为持有轴无信号"
                    )
                lines.append(f"family 声明: {fam_txt}")
            lines.append("")
            for fk, sl in agg["slices"].items():
                lines.append(f"### {scope} / {fk} 切面")
                lines.append("")
                lines.append("| 切面 | 桶 | n | mean_d |")
                lines.append("|---|---|---|---|")
                for axis in ("by_regime", "by_strength"):
                    for bucket, v in sl[axis].items():
                        lines.append(
                            f"| {axis} | {bucket} | {v['n']} | {_fmt_pct(v['mean_d'])} |"
                        )
                lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="BTST 持有期配对差证据包 (纯诊断)")
    parser.add_argument("--event-table", type=Path, default=EVENT_TABLE)
    parser.add_argument("--event-table-early", type=Path, default=EVENT_TABLE_EARLY)
    parser.add_argument("--raw-dir", type=Path, default=RAW_DAILY_DIR)
    parser.add_argument("--raw-dir-early", type=Path, default=EARLY_DAILY_DIR)
    parser.add_argument("--output-json", type=Path, default=None)
    parser.add_argument("--output-md", type=Path, default=None)
    args = parser.parse_args()

    cal = load_sessions(ANATOMY_CAL_START, "29991231")
    universes = {
        "production": (args.event_table, args.raw_dir),
        "early": (args.event_table_early, args.raw_dir_early),
    }
    payload: dict[str, Any] = {}
    for name, (table, raw_dir) in universes.items():
        if not table.exists():
            print(f"btst_holding_evidence: 跳过 {name} (事件表缺失: {table})")
            continue
        ev = load_event_table(table)
        payload[name] = analyze_universe(ev, raw_dir, cal)

    body = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=1)
    if args.output_json:
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(body + "\n", encoding="utf-8")
    if args.output_md:
        args.output_md.parent.mkdir(parents=True, exist_ok=True)
        args.output_md.write_text(render_md(payload) + "\n", encoding="utf-8")
    print(body if not args.output_json else f"written: {args.output_json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
