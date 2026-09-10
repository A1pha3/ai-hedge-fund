"""R168 d1_run 罚分时代条件性 — 幸存者偏差反事实敏感度界 (R180 Op1).

R178 判定「d1 罚分仅当前时代可检 (时代条件证据)」+ R179 判定「宇宙构成
不解释时代差 (匹配视图 +7.09pp ≈ 全宇宙 +7.51pp)」后, 机制二元剩 (时代
行为差异 vs 早期侧幸存者缺失)。本工具把幸存者解释机械化: 早期表缺席的
退市票 (隐藏行, 不可观测) 占早期信号池份额 phi, 若要使早期点罚分达到
当前观测量级 (复制当前点罚分或只触及 current CI 下界), 隐藏行的
run-vs-blip 差分与均值需要多极端 — 反事实敏感度界。

三面披露 (机械, 零判定):
① 差分形式 — delta_h(phi, target) = (target − (1−phi)·P_obs)/phi。
   结构性质 (逐网格点计算验证非假设): target > P_obs 时 delta_h > target
   对全部 phi<1 成立 — 隐藏行差分必须超过被解释的当前罚分本身;
② 水平形式 (宽容锚定假设: 隐藏 blip 均值 = 观测 blip 均值, 即幸存者偏差
   不作用于 blip 侧) — hidden_run_mean = E_blip_obs − delta_h; 机械不可能
   旗标: 所需均值低于全早期表 (生产对齐) 最差单行观测 — 子总体均值低于
   最极端单行意味着其大多数行低于任何已观测结局;
③ 锚点反演 — 以观测日均值极距 (对总体差分是宽容上界锚) 为隐藏差分,
   反演所需隐藏份额 phi* = (target − P_obs)/(spread − P_obs)。

边界诚实: 两时代配对区间重叠时点差问题只在点估计面 (ci_overlap 披露);
CI 缺失 (组 n<MIN_CELL_N) 走不可判定诚实路径。参数化假设 (同比例隐藏/
隐藏内差分均匀/水平形式锚定) 全部成文披露; 判定权在 owner — 本工具只
把『幸存者解释需要什么』变成可读数, 不判定幸存者解释是否成立。

单一实现纪律: 双时代分析 100% 委托 R168 analyze (经 R178 _era_view/
_point_penalty import 身份复用, 零统计 fork); 指纹 loader 与 digest 附加
同为 R178 模块对象; 日均值极距/行极值经 R168 同一套 production_aligned +
run_groups + _horizon_rows 面 (分组语义逐字继承)。
纪律 (宪法 #2): 纯诊断披露, 不判定 d1_run 重入规则; 任何策略变化 = 新
证据世代 owner 决策。早期侧冻结 (20220104-20241231); 当前侧随 court
重建每夜保鲜 (夜刷链第 10 成员)。
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import date
from pathlib import Path

import pandas as pd

from scripts.regime_proximity_conditioning import (
    COURT_TABLE_DEFAULT,
    REGIME_HISTORY_DEFAULT,
    REPORT_DIR_DEFAULT,
    load_regime_history,
)
from scripts.regime_blocked_run_conditioning import (
    analyze,
    run_groups,
    _horizon_rows,
    PRIMARY_HORIZON,
)
from scripts.regime_run_cross_era_validation import (
    CURRENT_MANIFEST_DEFAULT,
    EARLY_MANIFEST_DEFAULT,
    EARLY_TABLE_DEFAULT,
    _attach_digest,
    _era_view,
    _fmt,
    _point_penalty,
    load_manifest_fingerprint,
)
from scripts.winrate_payoff_decomposition import production_aligned

REPORT_STEM = "regime_run_survivorship_sensitivity_validation"

# 隐藏行份额网格 (隐藏行占早期 blip+run 信号池份额; 网格是披露选择,
# 非统计推断 — 任意 phi 的要求由连续代数给出, 网格只取代表点)
PHI_GRID: tuple[float, ...] = (0.05, 0.10, 0.15, 0.20, 0.30, 0.50)

DISCIPLINE: dict[str, str] = {
    "scope": (
        "本工具只回答『幸存者解释需要多极端才能复制当前点罚分』, 不判定"
        " d1_run 重入规则; 任何策略变化 = 新证据世代 owner 决策 (宪法 #2)"
    ),
    "direction_semantics": (
        "delta_h 正值 = 隐藏行内 run 侧比 blip 侧差 (罚分方向); 与 R168 "
        "grouped_delta (hi=blip 基线, lo=run 对照) 同向"
    ),
    "one_shot": (
        "早期侧冻结 (20220104-20241231), 数字不随新数据变化; 当前时代侧"
        "刷新后夜刷链重跑本工具刷新边界"
    ),
    "verdict_semantics": (
        "CI 重叠/不可能旗标是描述性机械读数不是假设检验; R170 placebo 面"
        "的时序脆弱性与 R178 时代条件性结论不受本工具影响"
    ),
}

# 参数化假设 (全部成文 — 敏感度界只在这些假设下成立)
ASSUMPTIONS: dict[str, str] = {
    "proportional_hiding": (
        "隐藏行按观测池内 blip/run 行数比例同比例进入两池 — 隐藏构成比例"
        "与观测构成相同的充分参数化; 真实隐藏构成不可观测"
    ),
    "uniform_differential": (
        "隐藏行内 run-vs-blip 差分取单一值 delta_h — 隐藏内异质性以均值"
        "形式进入混合代数"
    ),
    "level_form_anchor": (
        "水平形式锚定假设: 隐藏 blip 均值 = 观测 blip 均值 (宽容 — 假设"
        "幸存者偏差不作用于 blip 侧, 全部解释负担压在 run 侧)"
    ),
    "pool_share_semantics": (
        "phi 是隐藏行占观测信号池 (blip+run 行) 的份额; 隐藏行数不可观测,"
        "phi 网格是披露代表点非统计推断"
    ),
}

CONFOUNDS: dict[str, dict[str, str]] = {
    "survivorship_direction": {
        "finding": (
            "早期宇宙缺退市票; 退市票的灾难结局不成比例集中在危机后入场组"
            " (d1_run) — 早期罚分读数系统性乐观 (R178 成文继承)"
        ),
        "implication": (
            "本工具量化该乐观偏差『若要解释点差』所需的最极端形态; 不可能"
            "旗标不证伪幸存者解释 — 它给出解释的代价边界, 判定权在 owner"
        ),
    },
    "day_spread_anchor_noise": {
        "finding": (
            "日均值极距锚点是单日小样本均值的极差 — 比总体差分噪声大, 对"
            "总体差分是宽容上界锚 (反演 phi* 因此偏小/偏有利于幸存者解释)"
        ),
        "implication": (
            "phi* 读数是『最宽容差分下所需隐藏份额』下界读数; 与网格两面"
            "合读, 不单点消费"
        ),
    },
}


class RegimeRunSurvivorshipSensitivityError(SystemExit):
    """输入缺失/畸形 — typed fail-closed, 绝不产空报告冒充成功."""


def required_hidden_differential(
    p_obs: float, target: float, phi: float
) -> float:
    """混合代数: (1−phi)·P_obs + phi·delta_h = target 的解 (单一实现)."""
    if not 0.0 < phi < 1.0:
        raise RegimeRunSurvivorshipSensitivityError(
            f"phi_out_of_range: {phi}"
        )
    return (target - (1.0 - phi) * p_obs) / phi


def hidden_run_mean_level(e_blip_obs: float, delta_h: float) -> float:
    """水平形式: 隐藏 blip 均值锚定观测 blip 均值时的隐藏 run 均值."""
    return e_blip_obs - delta_h


def _observed_anchors(
    early_events: pd.DataFrame, history_path: Path
) -> dict[str, object]:
    """行极值 + 日均值极距 (R168 同一套 production_aligned/run_groups/
    _horizon_rows 面 — 分组语义逐字继承, 零 fork)."""
    sessions, labels = load_regime_history(history_path)
    u = production_aligned(early_events)
    if len(u) == 0:
        raise RegimeRunSurvivorshipSensitivityError(
            "empty_production_aligned_universe"
        )
    prox = run_groups(pd.unique(u["signal_date"].astype(str)), sessions, labels)
    rows = _horizon_rows(u, PRIMARY_HORIZON, prox)
    day_means = rows.groupby("signal_date")["net"].mean()
    net_min, net_max = float(rows["net"].min()), float(rows["net"].max())
    return {
        "row_min": net_min,
        "row_max": net_max,
        "day_mean_spread": float(day_means.max() - day_means.min()),
        "day_means_count": int(len(day_means)),
    }


def _require_columns(ev: pd.DataFrame, columns: tuple[str, ...], label: str) -> None:
    missing = [c for c in columns if c not in ev.columns]
    if missing:
        raise RegimeRunSurvivorshipSensitivityError(
            f"missing_column: {label}: {sorted(missing)}"
        )


def _blend_rows(
    *,
    phi: float,
    pool_n: int,
    p_obs: float,
    e_blip_obs: float,
    row_min: float,
    target: float | None,
) -> dict[str, object] | None:
    """单网格点 × 单目标的敏感度行 (target None → None 诚实路径)."""
    if target is None:
        return None
    delta_h = required_hidden_differential(p_obs, float(target), phi)
    level = hidden_run_mean_level(e_blip_obs, delta_h)
    return {
        "required_hidden_differential": delta_h,
        "structural_above_target": bool(delta_h > float(target)),
        "hidden_run_mean_level": level,
        "level_below_row_min_impossible": bool(level < row_min),
        "hidden_rows_at_phi": int(round(phi * pool_n)),
    }


def build_grid(
    *,
    phi_grid: tuple[float, ...],
    pool_n: int,
    p_obs: float,
    e_blip_obs: float,
    row_min: float,
    targets: dict[str, float | None],
) -> list[dict[str, object]]:
    """phi 网格全装配 (双目标并行; 目标缺失走 None 诚实路径)."""
    grid: list[dict[str, object]] = []
    for phi in phi_grid:
        grid.append(
            {
                "phi": phi,
                "to_current_point": _blend_rows(
                    phi=phi,
                    pool_n=pool_n,
                    p_obs=p_obs,
                    e_blip_obs=e_blip_obs,
                    row_min=row_min,
                    target=targets["current_point"],
                ),
                "to_current_ci_low": _blend_rows(
                    phi=phi,
                    pool_n=pool_n,
                    p_obs=p_obs,
                    e_blip_obs=e_blip_obs,
                    row_min=row_min,
                    target=targets["current_ci_low"],
                ),
            }
        )
    return grid


def invert_required_share(
    p_obs: float, target: float | None, anchor: float
) -> float | None:
    """锚点反演: delta_h(phi*) = anchor 的 phi*; anchor ≤ target → 不可达."""
    if target is None or anchor <= float(target) or anchor <= p_obs:
        return None
    return (float(target) - p_obs) / (anchor - p_obs)


def _ci_of(era: dict[str, object]) -> dict[str, float | None]:
    delta = (era.get("run_deltas_t10") or {}).get("d1_run_vs_blip") or {}
    return {
        "ci_low": delta.get("ci_low"),
        "ci_high": delta.get("ci_high"),
    }


def _ci_overlap(
    early_ci: dict[str, float | None], current_ci: dict[str, float | None]
) -> bool | None:
    """区间重叠机械谓词 (任一侧缺失 → None 不可判定)."""
    lo_e, hi_e = early_ci["ci_low"], early_ci["ci_high"]
    lo_c, hi_c = current_ci["ci_low"], current_ci["ci_high"]
    if any(v is None for v in (lo_e, hi_e, lo_c, hi_c)):
        return None
    return bool(hi_e >= lo_c and hi_c >= lo_e)


def _verdict(
    *,
    monotonic_holds: bool,
    impossible_phis: list[float],
    overlap: bool | None,
    indeterminate_ci: bool,
) -> dict[str, object]:
    """判定陈述装配 (机械谓词 + 分支陈述; 陈述是显示层, 谓词是机器面)."""
    if indeterminate_ci:
        tail = "; 配对区间缺失 — CI 重叠面不可判定 (不冒充判定)"
    elif overlap:
        tail = "; 两时代区间重叠 — 点差问题只在点估计面 (统计一致性面无矛盾)"
    else:
        tail = "; 两时代区间不重叠 — 点差在区间面亦可见 (描述性, 非假设检验)"

    if not monotonic_holds:
        statement = "当前点罚分不高于早期 — 点差面无幸存者解释需求 (机械)" + tail
    elif impossible_phis:
        phis = ", ".join(f"phi={p:.2f}" for p in impossible_phis)
        statement = (
            f"{phis} 区间所需隐藏 run 均值低于全早期表最差单行观测"
            " (机械不可能区 — 子总体均值低于最极端单行); 更大 phi 下要求"
            "渐缓但仍在网格内为正罚分方向 — 幸存者解释的代价边界, 判定权在 owner"
            + tail
        )
    else:
        statement = (
            "全网格所需隐藏差分/均值未落入机械不可能区 — 参数化假设下幸存者"
            "解释不与观测极值矛盾 (要求量级见网格, 判定权在 owner)" + tail
        )
    return {
        "structural_monotonicity_holds": monotonic_holds,
        "impossible_region_phi": impossible_phis,
        "ci_overlap_present": overlap,
        "statement": statement,
    }


def assemble_payload(
    current_events: pd.DataFrame,
    early_events: pd.DataFrame,
    history_path: Path,
    current_manifest: Path,
    early_manifest: Path,
) -> dict[str, object]:
    """纯装配: 双表 + history + 双 manifest → payload (零 IO 副作用)."""
    for label, ev in (("current", current_events), ("early", early_events)):
        _require_columns(ev, ("signal_date", "gross_ret_t10"), label)

    fp_cur = load_manifest_fingerprint(current_manifest)
    fp_early = load_manifest_fingerprint(early_manifest)
    if fp_cur != fp_early:
        raise RegimeRunSurvivorshipSensitivityError(
            "manifest_fingerprint_drift: current vs early formula_fingerprint"
        )

    cur_view = _era_view(current_events, history_path)
    early_view = _era_view(early_events, history_path)

    points = {
        "current": _point_penalty(cur_view["group_table"]),
        "early": _point_penalty(early_view["group_table"]),
    }
    if points["early"] is None or points["current"] is None:
        raise RegimeRunSurvivorshipSensitivityError(
            "point_penalty_undefined: d1_blip/d1_run 组估计缺失"
        )
    p_obs = float(points["early"])
    p_cur = float(points["current"])

    early_ci = _ci_of(early_view)
    current_ci = _ci_of(cur_view)
    overlap = _ci_overlap(early_ci, current_ci)
    indeterminate_ci = overlap is None

    blip_row = (early_view["group_table"].get("d1_blip") or {})
    run_row = (early_view["group_table"].get("d1_run") or {})
    n_blip = int(blip_row.get("n") or 0)
    n_run = int(run_row.get("n") or 0)
    pool_n = n_blip + n_run
    e_blip_obs = blip_row.get("expectancy")
    if e_blip_obs is None:
        raise RegimeRunSurvivorshipSensitivityError(
            "e_blip_early_undefined: d1_blip 期望缺失"
        )
    e_blip_obs = float(e_blip_obs)

    anchors = _observed_anchors(early_events, history_path)
    row_min = float(anchors["row_min"])
    spread = float(anchors["day_mean_spread"])

    targets = {
        "current_point": p_cur,
        "current_ci_low": (
            None if current_ci["ci_low"] is None else float(current_ci["ci_low"])
        ),
    }
    grid = build_grid(
        phi_grid=PHI_GRID,
        pool_n=pool_n,
        p_obs=p_obs,
        e_blip_obs=e_blip_obs,
        row_min=row_min,
        targets=targets,
    )

    point_rows = [
        r["to_current_point"]
        for r in grid
        if r["to_current_point"] is not None
    ]
    monotonic_holds = all(r["structural_above_target"] for r in point_rows)
    impossible_phis = [
        r["phi"]
        for r in grid
        if r["to_current_point"] is not None
        and r["to_current_point"]["level_below_row_min_impossible"]
    ]

    return {
        "schema_version": 1,
        "axis_definition": {
            "hidden_pool": "早期表缺席的退市票信号行 (不可观测反事实)",
            "blend_algebra": "(1−phi)·P_obs + phi·delta_h = target",
            "targets": {
                "current_point": "当前时代 d1 点罚分 (组表点估计)",
                "current_ci_low": "当前时代配对差 CI90 下界 (最弱复制主张)",
            },
            "phi_grid": list(PHI_GRID),
            "preregistered": "2026-09-11 (R179 登记开放项第二轴, 探索性 in-sample)",
        },
        "pool": {"n_blip": n_blip, "n_run": n_run, "n_pool": pool_n},
        "eras": {"current": cur_view, "early": early_view},
        "observed": {
            "early_point_penalty": p_obs,
            "current_point_penalty": p_cur,
            "e_blip_early": e_blip_obs,
            "early_ci": early_ci,
            "current_ci": current_ci,
            "row_min": row_min,
            "row_max": anchors["row_max"],
            "day_mean_spread": spread,
            "day_means_count": anchors["day_means_count"],
        },
        "targets": targets,
        "sensitivity_grid": grid,
        "anchor_inversion": {
            "anchor": "day_mean_spread",
            "anchor_value": spread,
            "required_hidden_share_point": invert_required_share(
                p_obs, p_cur, spread
            ),
            "required_hidden_share_ci_low": invert_required_share(
                p_obs, targets["current_ci_low"], spread
            ),
        },
        "ci_overlap": {"present": overlap},
        "verdict": _verdict(
            monotonic_holds=monotonic_holds,
            impossible_phis=impossible_phis,
            overlap=overlap,
            indeterminate_ci=indeterminate_ci,
        ),
        "assumptions": ASSUMPTIONS,
        "confounds": CONFOUNDS,
        "discipline": DISCIPLINE,
        "manifest_fingerprints": {"match": True, "formula_fingerprint": fp_cur},
        "d1_point_penalty": {"current": p_cur, "early": p_obs},
    }


def render_md(payload: dict[str, object], date_str: str) -> str:
    """Markdown 渲染 (缺键存活 — R158 家族; 判读纪律节固定成文)."""
    lines: list[str] = []
    lines.append(f"# R168 d1_run 时代条件性 — 幸存者敏感度界 — {date_str}")
    lines.append("")
    lines.append("## 判定 (机械谓词装配)")
    lines.append("")
    verdict = payload.get("verdict") or {}
    lines.append(f"- statement: {verdict.get('statement') or '—'}")
    lines.append(
        "- structural_monotonicity_holds: "
        f"{verdict.get('structural_monotonicity_holds') if verdict.get('structural_monotonicity_holds') is not None else '—'}"
    )
    imp = verdict.get("impossible_region_phi")
    imp_str = (
        ", ".join(f"{p:.2f}" for p in imp) if isinstance(imp, list) and imp else "∅"
    )
    lines.append(f"- impossible_region: {imp_str}")
    lines.append(
        "- ci_overlap_present: "
        f"{verdict.get('ci_overlap_present') if verdict.get('ci_overlap_present') is not None else '不可判定'}"
    )
    lines.append("")

    obs = payload.get("observed") or {}
    lines.append("## 观测量 (早期冻结, 当前夜刷保鲜)")
    lines.append("")
    lines.append("| 量 | 值 |")
    lines.append("|---|---|")
    lines.append(f"| early_point_penalty | {_fmt(obs.get('early_point_penalty'))} |")
    lines.append(f"| current_point_penalty | {_fmt(obs.get('current_point_penalty'))} |")
    lines.append(f"| e_blip_early | {_fmt(obs.get('e_blip_early'))} |")
    early_ci = obs.get("early_ci") or {}
    cur_ci = obs.get("current_ci") or {}
    lines.append(
        f"| early_ci90 | [{_fmt(early_ci.get('ci_low'))}, {_fmt(early_ci.get('ci_high'))}] |"
    )
    lines.append(
        f"| current_ci90 | [{_fmt(cur_ci.get('ci_low'))}, {_fmt(cur_ci.get('ci_high'))}] |"
    )
    lines.append(f"| row_min (全早期表最差单行) | {_fmt(obs.get('row_min'))} |")
    lines.append(f"| day_mean_spread (极距锚) | {_fmt(obs.get('day_mean_spread'))} |")
    pool = payload.get("pool") or {}
    lines.append(
        f"| 池规模 (blip+run) | {_fmt(pool.get('n_pool'), pct=False)} "
        f"(blip {_fmt(pool.get('n_blip'), pct=False)} / run {_fmt(pool.get('n_run'), pct=False)}) |"
    )
    lines.append("")

    lines.append("## 敏感度网格 (隐藏行份额 phi → 复制当前所需)")
    lines.append("")
    lines.append("| phi | 隐藏行≈ | →当前点罚分 delta_h | 隐藏 run 均值 | 不可能 | →CI 下界 delta_h | 隐藏 run 均值 | 不可能 |")
    lines.append("|---|---|---|---|---|---|---|---|")
    grid = payload.get("sensitivity_grid") or []
    for row in grid:
        pt = row.get("to_current_point") or {}
        cl = row.get("to_current_ci_low") or {}
        lines.append(
            f"| {row.get('phi', 0):.2f} | {_fmt(pt.get('hidden_rows_at_phi'), pct=False)} "
            f"| {_fmt(pt.get('required_hidden_differential'))} | {_fmt(pt.get('hidden_run_mean_level'))} "
            f"| {'⚠' if pt.get('level_below_row_min_impossible') else '—'} "
            f"| {_fmt(cl.get('required_hidden_differential')) if cl else '—'} "
            f"| {_fmt(cl.get('hidden_run_mean_level')) if cl else '—'} "
            f"| {'⚠' if (cl or {}).get('level_below_row_min_impossible') else ('—' if cl else 'n/a')} |"
        )
    lines.append("")

    inv = payload.get("anchor_inversion") or {}
    lines.append("## 锚点反演 (宽容差分 = 日均值极距)")
    lines.append("")
    lines.append(f"- anchor_value: {_fmt(inv.get('anchor_value'))}")
    share_pt = inv.get("required_hidden_share_point")
    share_cl = inv.get("required_hidden_share_ci_low")
    lines.append(
        f"- →当前点罚分所需隐藏份额 phi*: "
        + (_fmt(share_pt) if share_pt is not None else "不可达 (anchor ≤ target)")
    )
    lines.append(
        f"- →CI 下界所需隐藏份额 phi*: "
        + (_fmt(share_cl) if share_cl is not None else "不可达 (anchor ≤ target 或 CI 缺失)")
    )
    lines.append("")

    assumptions = payload.get("assumptions") or {}
    lines.append("## 参数化假设 (判读前必读)")
    lines.append("")
    for key, text in assumptions.items():
        lines.append(f"- **{key}**: {text}")
    lines.append("")

    confounds = payload.get("confounds") or {}
    lines.append("## 混杂披露")
    lines.append("")
    for key, item in confounds.items():
        lines.append(f"- **{key}**: {item.get('finding', '—')}")
        lines.append(f"  - 含义: {item.get('implication', '—')}")
    lines.append("")

    lines.append("## 纪律")
    lines.append("")
    for key, text in (payload.get("discipline") or {}).items():
        lines.append(f"- **{key}**: {text}")
    lines.append("")
    lines.append(
        "公式指纹一致性: "
        f"{(payload.get('manifest_fingerprints') or {}).get('match')} "
        "(双表 manifest formula_fingerprint 逐字段比对, 不一致即 typed 拒绝)"
    )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="R168 d1_run 时代条件性幸存者敏感度界 (纯诊断)"
    )
    parser.add_argument("--court-table", type=Path, default=COURT_TABLE_DEFAULT)
    parser.add_argument("--early-court-table", type=Path, default=EARLY_TABLE_DEFAULT)
    parser.add_argument("--regime-history", type=Path, default=REGIME_HISTORY_DEFAULT)
    parser.add_argument(
        "--current-manifest", type=Path, default=CURRENT_MANIFEST_DEFAULT
    )
    parser.add_argument(
        "--early-manifest", type=Path, default=EARLY_MANIFEST_DEFAULT
    )
    parser.add_argument("--out-dir", type=Path, default=REPORT_DIR_DEFAULT)
    parser.add_argument("--date", type=str, default=None, help="报告日期标签 (默认今日; 测试注入)")
    args = parser.parse_args(argv)

    for label, path in (
        ("court_table", args.court_table),
        ("early_court_table", args.early_court_table),
        ("regime_history", args.regime_history),
        ("current_manifest", args.current_manifest),
        ("early_manifest", args.early_manifest),
    ):
        if not path.exists():
            raise RegimeRunSurvivorshipSensitivityError(f"{label}_missing: {path}")

    current_ev = pd.read_csv(args.court_table)
    early_ev = pd.read_csv(args.early_court_table)
    payload = assemble_payload(
        current_ev,
        early_ev,
        args.regime_history,
        args.current_manifest,
        args.early_manifest,
    )
    date_str = args.date or date.today().strftime("%Y%m%d")
    payload["report_date"] = date_str
    _attach_digest(
        payload,
        args.court_table,
        args.early_court_table,
        int(len(current_ev)),
        int(len(early_ev)),
    )

    args.out_dir.mkdir(parents=True, exist_ok=True)
    md_path = args.out_dir / f"{REPORT_STEM}_{date_str}.md"
    json_path = args.out_dir / f"{REPORT_STEM}_{date_str}.json"
    md_path.write_text(render_md(payload, date_str), encoding="utf-8")
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True, default=str),
        encoding="utf-8",
    )
    verdict = payload.get("verdict") or {}
    points = payload.get("d1_point_penalty") or {}
    print(
        f"{REPORT_STEM}: cur_penalty={_fmt(points.get('current'))} "
        f"early_penalty={_fmt(points.get('early'))} · "
        f"ci_overlap={verdict.get('ci_overlap_present')} · "
        f"{verdict.get('statement')} → {md_path}"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
