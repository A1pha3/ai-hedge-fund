"""强度分量级解剖 — trigger_strength 五分量的事件级证据面 (R152 Op1, R153 Op1 扩区间).

动机: 0.50 门槛与 ≥0.70 阈值锚的全部既有证据都建在 trigger_strength
聚合层 (R141-R149 分解/触发器/近期窗), 「池内哪个分量在做功」从未被
度量 — day_feature_attribution (R133) 是日层聚合 (结论: 无日层特征
具备判别资格), 本工具是事件级分量视图, 与其互补不重叠。

R153 Op1: hi−lo 差从点估计升级为配对 (按日联合重采样) 聚类 bootstrap
双侧区间 (cluster_boot_delta_ci, 单一实现落 winrate_payoff_decomposition)
— 兑现 R152 Op1 docstring 预注册的「配对 bootstrap 属后续 op」。

Observe 期真实 court 数据快查实证 (生产对齐 n=1677 全成熟, T+10,
20260909): ≥0.50 池 (n=1147, E=+1.49%) 内低波分量反向区分
(score<0.5: n=703 E=+2.45% vs ≥0.5: n=444 E=-0.04%), 压缩/量能正向,
board_score 池内反向但 n=75 小样本 — 分量结构与聚合层梯度不同构。

纪律 (宪法 #2):
- 纯诊断披露 — 分量级读数是 owner 阈值/公式权重判读的输入, 不进入
  任何评分/排序/仓位/触发器判定路径; 任何据此的公式变化 = 新证据世代
  owner 决策 (预注册 champion/challenger)。
- 探索性 in-sample: 0.5 分界与三池划分选自同一次观测数据 (镜像 R92
  gap 桶标注), 边界敏感性未做, 单读数不冒充结论。
- 单一实现复用 (R17 收敛纪律): production_aligned/net_returns/
  win_loss_stats (含 per-call seeded 聚类 CI)/MIN_CELL_N/
  court_window_from_events/COURT_TABLE/REPORT_DIR 全部 import 自
  winrate_payoff_decomposition, 本模块零新 RNG 零口径 fork。
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from datetime import date
from pathlib import Path

import pandas as pd

_SCRIPTS = str(Path(__file__).resolve().parent)
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

from winrate_payoff_decomposition import (  # noqa: E402
    COURT_TABLE,
    MIN_CELL_N,
    REPORT_DIR,
    cluster_boot_delta_ci,
    court_window_from_events,
    net_returns,
    production_aligned,
    win_loss_stats,
)

# 五分量 (生产序, 镜像 src daily_action._STRENGTH_COMPONENT_LABELS 的键序;
# 中文标签独立维护 — src 是展示面, 本模块是诊断面, 值域语义同源)。
COMPONENTS: tuple[tuple[str, str], ...] = (
    ("board_score", "上市板"),
    ("low_vol_score", "低波"),
    ("squeeze_score", "压缩"),
    ("volume_score", "量能"),
    ("range_score", "振幅"),
)

# 0.5 分界 — 预注册探索性 (选自同一次观测数据, 边界敏感性未做, R92 先例)。
COMPONENT_SPLIT = 0.5
COMPONENT_BUCKETS: tuple[str, ...] = ("<0.50", "≥0.50", "unknown")

# 池划分 (触发器锚同源): all=生产对齐全样本; ge050=生产入场池 (0.50 门槛);
# ge070=阈值上调讨论锚 (≥0.70 触发器条件①桶)。
POOLS: tuple[tuple[str, float], ...] = (
    ("all", float("-inf")),
    ("ge050", 0.50),
    ("ge070", 0.70),
)

# 生产公式低波权重 (btst_breakout strength: 0.20×五分量和 + energy_bonus,
# 能量门 = squeeze≥1.0 ∧ low_vol≥0.75) — 本模块镜像该冻结常数做反事实
# 算术, 不 import src (诊断面与生产面的既有隔离纪律)。
COUNTERFACTUAL_LOWVOL_WEIGHT = 0.20

# 选股面资格门槛 = 生产入场池 (0.50 门槛, POOLS ge050 同源)。
PRODUCTION_ENTRY_FLOOR = 0.50


def counterfactual_strength(trigger_strength: float, low_vol_score: float) -> float:
    """V1 单旋钮反事实强度: 清零低波 0.20 权重并重归一化。

    strength' = (trigger_strength − 0.20·low_vol_score)/0.80。重归一化使
    0.50/0.70 门槛刻度与原公式可比 (分量和归一化到 4 轴); 不封顶 (封顶是
    第二旋钮, 排序/门槛算术不需要); energy_bonus 原样保留 — bonus 门含
    低波条件是 V1「只清零权重」最小解释的一部分, 该混杂在 payload
    bonus_note 如实披露。low_vol 为 NaN 时算术自然传播 NaN (不可计算行
    由 _attach_counterfactual 标记并从两侧同集比较中排除)。
    """
    w = COUNTERFACTUAL_LOWVOL_WEIGHT
    return (trigger_strength - w * low_vol_score) / (1.0 - w)


def _attach_counterfactual(work: "pd.DataFrame") -> "pd.DataFrame":
    """work 帧附加 _cf_strength 列 + recomputable 计数 (attrs)。

    low_vol_score 非有限 (缺失/NaN/inf/非数值) → _cf_strength = NaN:
    该行从反事实的池面/选股面两侧同集比较中排除并计数披露 (不虚构
    归属); trigger_strength 非有限的行同样不可计算 (门槛比较对 NaN
    自然为 False, 与既有 _pool_frame 纪律一致)。
    """
    lv = pd.to_numeric(work["low_vol_score"], errors="coerce")
    ts = pd.to_numeric(work["trigger_strength"], errors="coerce")
    lv_finite = lv.map(math.isfinite)
    ts_finite = ts.map(math.isfinite)
    w = COUNTERFACTUAL_LOWVOL_WEIGHT
    work["_cf_strength"] = [
        (t - w * v) / (1.0 - w) if tf and vf else float("nan")
        for t, v, tf, vf in zip(ts, lv, ts_finite, lv_finite)
    ]
    work.attrs["cf_recomputable_n"] = int(lv_finite.sum())
    work.attrs["cf_excluded_unknown_n"] = int((~lv_finite).sum())
    return work


def _cf_work_frame(ev: "pd.DataFrame") -> "pd.DataFrame":
    """生产对齐 + 净收益 + 分量桶 + 反事实列 — 读数入口与 analyze 共享加工。"""
    work = _aligned_work_frame(ev)
    return _attach_counterfactual(work)


def counterfactual_pool_readout(
    work: "pd.DataFrame", *, floor: float, ret_col: str = "net_ret_t10"
) -> dict[str, object]:
    """池面反事实读数: 固定门槛下旧/新池构成与期望差 (含配对差区间)。

    hi=new 池 (低波零权), lo=旧池 — delta>0 = 清零低波权重后该门槛池
    更好。两侧只在低波可计算行上比较 (同集)。注意混杂: 重归一化会放行
    更多票入新池 (n_new 通常 > n_old), 池面 ΔE 混合了轴反向与稀释两
    种效应 — 判读以下游 counterfactual_selection_readout (无稀释) 为准。
    任一侧 n < MIN_CELL_N → delta_ci None 不冒充 (R153 门槛纪律)。
    """
    sub = work[work["_cf_strength"].notna()]
    old = sub[sub["trigger_strength"] >= floor]
    new = sub[sub["_cf_strength"] >= floor]
    old_idx, new_idx = set(old.index), set(new.index)
    stats_old = win_loss_stats(
        old[ret_col].tolist(), old["signal_date"].astype(str).tolist()
    )
    stats_new = win_loss_stats(
        new[ret_col].tolist(), new["signal_date"].astype(str).tolist()
    )
    e_old, e_new = stats_old.get("expectancy"), stats_new.get("expectancy")
    delta_point = (
        e_new - e_old if e_old is not None and e_new is not None else None
    )
    delta_ci = None
    if len(old) >= MIN_CELL_N and len(new) >= MIN_CELL_N:
        delta_ci = cluster_boot_delta_ci(
            new[ret_col].tolist(),
            new["signal_date"].astype(str).tolist(),
            old[ret_col].tolist(),
            old["signal_date"].astype(str).tolist(),
        )
    return {
        "floor": floor,
        "n_old": int(len(old)),
        "n_new": int(len(new)),
        "entered": int(len(new_idx - old_idx)),
        "left": int(len(old_idx - new_idx)),
        "stats_old": stats_old,
        "stats_new": stats_new,
        "delta_point": delta_point,
        "delta_ci": delta_ci,
    }


def counterfactual_selection_readout(
    work: "pd.DataFrame",
    *,
    floor: float = PRODUCTION_ENTRY_FLOOR,
    k: int = 3,
    ret_col: str = "net_ret_t10",
) -> dict[str, object]:
    """选股面反事实读数: 每日 top-K 旧/新排序选集的期望差 (无稀释)。

    资格 = 旧强度 ≥ floor (生产入场池); 每信号日按旧强度 vs 反事实强度
    各取 top-K (平票以 symbol 升序定序 — 确定性), 差值 = new−old 配对
    (cluster_boot_delta_ci 按日联合重采样, hi=new 选集)。日候选 < K 跳过
    并计数 (不凑数); 任一侧 picks n < MIN_CELL_N → delta_ci None。
    split_half 镜像 component_split_half 判据 (日序对分, 符号一致性,
    单半 expectancy 缺 → None 不冒充)。
    """
    sub = work[work["_cf_strength"].notna() & (work["trigger_strength"] >= floor)]
    old_by_day: dict[str, list[float]] = {}
    new_by_day: dict[str, list[float]] = {}
    overlap = used = skipped = 0
    for day, g in sub.groupby(sub["signal_date"].astype(str), sort=True):
        if len(g) < k:
            skipped += 1
            continue
        used += 1
        go = g.sort_values(
            ["trigger_strength", "symbol"], ascending=[False, True]
        ).head(k)
        gn = g.sort_values(
            ["_cf_strength", "symbol"], ascending=[False, True]
        ).head(k)
        overlap += len(set(go.index) & set(gn.index))
        old_by_day[day] = go[ret_col].tolist()
        new_by_day[day] = gn[ret_col].tolist()
    old_rets = [r for d in sorted(old_by_day) for r in old_by_day[d]]
    new_rets = [r for d in sorted(new_by_day) for r in new_by_day[d]]
    old_days = [d for d in sorted(old_by_day) for _ in old_by_day[d]]
    new_days = [d for d in sorted(new_by_day) for _ in new_by_day[d]]
    stats_old = win_loss_stats(old_rets, old_days)
    stats_new = win_loss_stats(new_rets, new_days)
    e_old, e_new = stats_old.get("expectancy"), stats_new.get("expectancy")
    delta_ci = None
    if len(old_rets) >= MIN_CELL_N and len(new_rets) >= MIN_CELL_N:
        delta_ci = cluster_boot_delta_ci(
            new_rets, new_days, old_rets, old_days
        )
    split_half: dict[str, object] = {"available": False, "reason": "insufficient_days"}
    if used >= 2:
        all_days = sorted(old_by_day)
        half = len(all_days) // 2
        deltas: dict[str, float | None] = {}
        for label, day_set in (
            ("early", set(all_days[:half])),
            ("late", set(all_days[half:])),
        ):
            so = win_loss_stats(
                [r for d in all_days if d in day_set for r in old_by_day[d]]
            )
            sn = win_loss_stats(
                [r for d in all_days if d in day_set for r in new_by_day[d]]
            )
            eo, en = so.get("expectancy"), sn.get("expectancy")
            deltas[label] = en - eo if eo is not None and en is not None else None
        early, late = deltas["early"], deltas["late"]
        split_half = {
            "available": True,
            "days_early": half,
            "days_late": len(all_days) - half,
            "early_delta": early,
            "late_delta": late,
            "sign_consistent": (
                (early > 0) == (late > 0)
                if early is not None and late is not None
                else None
            ),
        }
    return {
        "k": k,
        "floor": floor,
        "days_used": used,
        "days_skipped": skipped,
        "overlap_picks": overlap,
        "stats_old": stats_old,
        "stats_new": stats_new,
        "delta_point": (
            e_new - e_old if e_old is not None and e_new is not None else None
        ),
        "delta_ci": delta_ci,
        "split_half": split_half,
    }


def component_bucket(value: object) -> str:
    """分量值 → 桶 (非数值/NaN/inf → unknown, 不虚构归属)。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return "unknown"
    if not math.isfinite(float(value)):
        return "unknown"
    return "<0.50" if float(value) < COMPONENT_SPLIT else "≥0.50"


def _pool_frame(work: "pd.DataFrame", floor: float) -> "pd.DataFrame":
    """trigger_strength ≥ floor 的行 (NaN 比较为 False 自然排除)。"""
    if floor == float("-inf"):
        return work
    return work[work["trigger_strength"] >= floor]


def _hi_lo_delta(lo: dict, hi: dict) -> float | None:
    """hi−lo 期望差点估计 (两侧 expectancy 均 None 才 None, 不重算)。"""
    e_lo = lo.get("expectancy")
    e_hi = hi.get("expectancy")
    if e_lo is None or e_hi is None:
        return None
    return e_hi - e_lo


def component_anatomy(
    work: "pd.DataFrame", *, ret_col: str = "net_ret_t10"
) -> dict[str, object]:
    """三池 × 五分量 × 双桶 win_loss_stats 矩阵 (零新口径)。

    每格 (pool, component, bucket) 是独立 win_loss_stats 调用 — 日聚类
    CI 由其内建 n≥MIN_CELL_N 门槛给出, 小样本格诚实 None; unknown 桶
    全量保留 (缺失分量如实显形不剔除)。hi_lo_delta 是点估计;
    hi_lo_delta_ci 是配对 (按日联合重采样) 聚类 bootstrap 双侧区间
    (R153 Op1 — 兑现本函数此前「配对 bootstrap 属后续 op」的预注册),
    双桶 n≥MIN_CELL_N 才给, 否则 None 不冒充; 差值符号判读 (反向分量
    是否可区分于零) 用区间, 点估计只作方向。
    """
    pools: dict[str, object] = {}
    for pool_key, floor in POOLS:
        sub = _pool_frame(work, floor)
        per_component: dict[str, object] = {}
        for comp_key, _label in COMPONENTS:
            buckets: dict[str, object] = {}
            cells: dict[str, "pd.DataFrame"] = {}
            for bucket in COMPONENT_BUCKETS:
                cell = sub[sub[f"_comp_{comp_key}"] == bucket]
                cells[bucket] = cell
                buckets[bucket] = win_loss_stats(
                    cell[ret_col].tolist(),
                    cell["signal_date"].astype(str).tolist(),
                )
            lo_cell, hi_cell = cells["<0.50"], cells["≥0.50"]
            if len(lo_cell) >= MIN_CELL_N and len(hi_cell) >= MIN_CELL_N:
                hi_lo_delta_ci: dict[str, float] | None = cluster_boot_delta_ci(
                    hi_cell[ret_col].tolist(),
                    hi_cell["signal_date"].astype(str).tolist(),
                    lo_cell[ret_col].tolist(),
                    lo_cell["signal_date"].astype(str).tolist(),
                )
            else:
                hi_lo_delta_ci = None
            per_component[comp_key] = {
                "buckets": buckets,
                "hi_lo_delta": _hi_lo_delta(
                    buckets["<0.50"], buckets["≥0.50"]
                ),
                "hi_lo_delta_ci": hi_lo_delta_ci,
            }
        pools[pool_key] = {
            "floor": None if floor == float("-inf") else floor,
            "n": int(len(sub)),
            "components": per_component,
        }
    return pools


def component_split_half(
    work: "pd.DataFrame", *, ret_col: str = "net_ret_t10"
) -> dict[str, object]:
    """逐池逐分量按日序半窗 hi−lo 差的符号一致性 (R133 判据风格)。

    半窗划分镜像 trailing_window (R149 Op1): 有成熟行的信号日全序对分;
    单半内某桶缺 expectancy → 该半 delta None (不冒充); sign_consistent
    仅两半 delta 均 None 才 None, 否则按 (early>0)==(late>0) 判 (恰 0
    归负侧 — 镜像 win_loss_stats 保守侧)。
    """
    valid = work[work[ret_col].notna()].copy()
    all_days = sorted(valid["signal_date"].astype(str).unique())
    if len(all_days) < 2:
        return {"available": False, "reason": "insufficient_days"}
    half = len(all_days) // 2
    day_sets = {
        "early": set(all_days[:half]),
        "late": set(all_days[half:]),
    }
    pools: dict[str, object] = {}
    for pool_key, floor in POOLS:
        sub = _pool_frame(valid, floor)
        per_component: dict[str, object] = {}
        for comp_key, _label in COMPONENTS:
            deltas: dict[str, float | None] = {}
            for label, day_set in day_sets.items():
                cell = sub[sub["signal_date"].astype(str).isin(day_set)]
                lo = win_loss_stats(
                    cell.loc[
                        cell[f"_comp_{comp_key}"] == "<0.50", ret_col
                    ].tolist()
                )
                hi = win_loss_stats(
                    cell.loc[
                        cell[f"_comp_{comp_key}"] == "≥0.50", ret_col
                    ].tolist()
                )
                deltas[label] = _hi_lo_delta(lo, hi)
            early, late = deltas["early"], deltas["late"]
            per_component[comp_key] = {
                "early_delta": early,
                "late_delta": late,
                "sign_consistent": (
                    (early > 0) == (late > 0)
                    if early is not None and late is not None
                    else None
                ),
            }
        pools[pool_key] = per_component
    return {"available": True, "days_early": half, "days_late": len(all_days) - half, "pools": pools}


def _aligned_work_frame(ev: "pd.DataFrame") -> "pd.DataFrame":
    """生产对齐 + 净收益 + 分量桶列 — analyze 与反事实读数的共享加工 (单一实现)。"""
    universe = production_aligned(ev)
    work = universe.copy()
    work["net_ret_t10"] = net_returns(work["gross_ret_t10"].tolist())
    for comp_key, _label in COMPONENTS:
        work[f"_comp_{comp_key}"] = work[comp_key].map(component_bucket)
    return work


def analyze(ev: "pd.DataFrame") -> dict[str, object]:
    """事件表 → 完整分量解剖 payload (生产对齐 × T+10 主 horizon)。

    列缺失 = 口径理解错误, SystemExit fail-closed (镜像
    production_aligned 的过滤列纪律 — 静默当作缺失列会渲染全 unknown
    假装分析了)。R152 Op2: 必需列全集 = 五分量 + trigger_strength +
    signal_date + gross_ret_t10 — 缺 core 列时此前经 _pool_frame/
    net_returns/component_split_half 裸 KeyError 逃逸 (PoC 实锤),
    与分量列同入 typed 拒绝。ret 列经 net_returns 统一扣成本。
    R154 Op1: counterfactual 节 — 低波轴零权反事实读数 (池面 + 选股面),
    V1 单旋钮探索性诊断非提案 (宪法 #2)。
    """
    required = [
        *(c for c, _ in COMPONENTS),
        "trigger_strength",
        "signal_date",
        "gross_ret_t10",
    ]
    missing = [c for c in required if c not in ev.columns]
    if missing:
        raise SystemExit(f"court 事件表缺少必需列: {missing}")
    work = _cf_work_frame(ev)
    counterfactual = {
        "available": True,
        "renormalization": "(trigger_strength − 0.20·low_vol_score)/0.80",
        "bonus_note": (
            "energy_bonus 原样保留 (V1 单旋钮: 仅清零低波 0.20 权重;"
            " 重归一化保持门槛刻度可比, 但会放行更多票入新池 — 池面 ΔE"
            " 含稀释混杂, 判读看选股面)"
        ),
        "recomputable_n": int(work.attrs["cf_recomputable_n"]),
        "excluded_unknown_n": int(work.attrs["cf_excluded_unknown_n"]),
        "pools": {
            name: counterfactual_pool_readout(work, floor=floor)
            for name, floor in POOLS
            if name != "all"
        },
        "selection": {
            "k3": counterfactual_selection_readout(
                work, floor=PRODUCTION_ENTRY_FLOOR, k=3
            ),
            "k5": counterfactual_selection_readout(
                work, floor=PRODUCTION_ENTRY_FLOOR, k=5
            ),
        },
    }
    return {
        "available": True,
        "n": int(len(work)),
        "min_cell_n": MIN_CELL_N,
        "component_split": COMPONENT_SPLIT,
        "pools": component_anatomy(work),
        "split_half": component_split_half(work),
        "counterfactual": counterfactual,
    }


def _fmt(v: object, pct: bool = True) -> str:
    """单元格防御渲染 (镜像分解工具 _fmt): 非有限 → '—' 不渲染垃圾。"""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return "—"
    if not math.isfinite(float(v)):
        return "—"
    return f"{v:+.2%}" if pct else f"{v:.3f}"


def _fmt_count(v: object) -> str:
    """计数格整数渲染 (R152 Op2: 修复前 n 经 _fmt(pct=False) 渲染 '226.000'
    三位小数 — int 计数被 :.3f 浮点格式化, 真实报告实锤)。"""
    if isinstance(v, bool) or not isinstance(v, int):
        return "—"
    return str(v)


def render_md(payload: object) -> str:
    """payload → MD 报告 (fail-open 家族: 缺键/非 dict 零新增字节不崩)。

    纪律句必在 (探索性 in-sample + 宪法 #2); 每格 _fmt 防御渲染。
    """
    if not isinstance(payload, dict) or payload.get("available") is not True:
        return ""
    lines: list[str] = [
        "# 强度分量级解剖 (trigger_strength 五分量, R152)",
        "",
        (
            f"- 宇宙: production_aligned × T+10 净口径, n={payload.get('n', '—')}"
            f" · 0.5 分界 · MIN_CELL_N={payload.get('min_cell_n', '—')}"
        ),
        (
            "- 纪律: 探索性 in-sample (分界与池划分选自同次观测数据), 只披露"
            "不判定 (宪法 #2); 任何据此的公式/阈值变化 = 新证据世代 owner 决策;"
            " hi−lo 差区间是配对 (按日联合重采样) bootstrap 双侧 90% 估计,"
            " 探索性 read-out, 区间证据与各桶 CI90 下界互为侧面。"
        ),
        "",
    ]
    pools = payload.get("pools")
    split = payload.get("split_half")
    split_pools = split.get("pools") if isinstance(split, dict) else None
    labels = {k: lbl for k, lbl in COMPONENTS}
    if isinstance(pools, dict):
        for pool_key, _floor in POOLS:
            pool = pools.get(pool_key)
            if not isinstance(pool, dict):
                continue
            lines.append(f"## 池 {pool_key} (n={pool.get('n', '—')})")
            lines.append("")
            lines.append("| 分量 | <0.50: n / E / CI90下界 | ≥0.50: n / E / CI90下界 | hi−lo | 半窗符号 |")
            lines.append("|---|---|---|---|---|")
            comps = pool.get("components")
            if not isinstance(comps, dict):
                lines.append("| (缺 components 键) | — | — | — | — |")
            else:
                for comp_key, label in COMPONENTS:
                    cell = comps.get(comp_key)
                    if not isinstance(cell, dict):
                        lines.append(f"| {label} | — | — | — | — |")
                        continue
                    buckets = cell.get("buckets")
                    lo = (
                        buckets.get("<0.50", {})
                        if isinstance(buckets, dict)
                        else {}
                    )
                    hi = (
                        buckets.get("≥0.50", {})
                        if isinstance(buckets, dict)
                        else {}
                    )
                    lo = lo if isinstance(lo, dict) else {}
                    hi = hi if isinstance(hi, dict) else {}
                    sign = "—"
                    if isinstance(split_pools, dict):
                        sp = split_pools.get(pool_key)
                        if isinstance(sp, dict):
                            sc = sp.get(comp_key)
                            if isinstance(sc, dict):
                                raw = sc.get("sign_consistent")
                                if raw is True:
                                    sign = "一致"
                                elif raw is False:
                                    sign = "翻转"
                    raw_ci = cell.get("hi_lo_delta_ci")
                    if isinstance(raw_ci, dict):
                        ci_cell = (
                            f"[{_fmt(raw_ci.get('ci_low'))}"
                            f", {_fmt(raw_ci.get('ci_high'))}]"
                        )
                    else:
                        ci_cell = "—"
                    lines.append(
                        f"| {label} ({comp_key}) "
                        f"| {_fmt_count(lo.get('n'))} / {_fmt(lo.get('expectancy'))}"
                        f" / {_fmt(lo.get('cluster_ci_low_90'))} "
                        f"| {_fmt_count(hi.get('n'))} / {_fmt(hi.get('expectancy'))}"
                        f" / {_fmt(hi.get('cluster_ci_low_90'))} "
                        f"| {_fmt(cell.get('hi_lo_delta'))} {ci_cell} | {sign} |"
                    )
            lines.append("")
    cf = payload.get("counterfactual")
    if isinstance(cf, dict) and cf.get("available") is True:
        lines.append("## 反事实: 低波轴零权 (V1 单旋钮, 探索性非提案)")
        lines.append("")
        lines.append(
            f"- 口径: strength' = {cf.get('renormalization', '—')};"
            f" {cf.get('bonus_note', '')}"
        )
        lines.append(
            f"- 低波缺失行 n={_fmt_count(cf.get('excluded_unknown_n'))}"
            f" 不计入反事实 (两侧同集对比); 可计算 n={_fmt_count(cf.get('recomputable_n'))}。"
        )
        lines.append(
            "- 纪律: 反事实是诊断读数不是公式提案 — 任何权重变化 = 新证据"
            "世代 owner 决策 (预注册); 池面计数含重归一化稀释混杂, 判读看选股面;"
            " ΔE 区间是配对 (按日联合重采样) bootstrap 双侧 90% 估计。"
        )
        lines.append("")
        cf_pools = cf.get("pools")
        if isinstance(cf_pools, dict) and cf_pools:
            lines.append("| 池面 | n_old→n_new (入/出) | E_old | E_new | ΔE(new−old) [90% CI] |")
            lines.append("|---|---|---|---|---|")
            for name in ("ge050", "ge070"):
                cell = cf_pools.get(name)
                if not isinstance(cell, dict):
                    continue
                old_stats = (
                    cell.get("stats_old") if isinstance(cell.get("stats_old"), dict) else {}
                )
                new_stats = (
                    cell.get("stats_new") if isinstance(cell.get("stats_new"), dict) else {}
                )
                raw_ci = cell.get("delta_ci")
                ci_cell = (
                    f"[{_fmt(raw_ci.get('ci_low'))}, {_fmt(raw_ci.get('ci_high'))}]"
                    if isinstance(raw_ci, dict)
                    else "—"
                )
                lines.append(
                    f"| {name} "
                    f"| {_fmt_count(cell.get('n_old'))}→{_fmt_count(cell.get('n_new'))}"
                    f" ({_fmt_count(cell.get('entered'))}/{_fmt_count(cell.get('left'))}) "
                    f"| {_fmt(old_stats.get('expectancy'))} "
                    f"| {_fmt(new_stats.get('expectancy'))} "
                    f"| {_fmt(cell.get('delta_point'))} {ci_cell} |"
                )
            lines.append("")
        cf_sel = cf.get("selection")
        if isinstance(cf_sel, dict) and cf_sel:
            lines.append(
                "| 选股面 (每日 top-K, ge050 资格) | 天数 (跳过) | 选集重叠"
                " | E_old | E_new | ΔE [90% CI] | 半窗符号 |"
            )
            lines.append("|---|---|---|---|---|---|---|")
            for key in ("k3", "k5"):
                cell = cf_sel.get(key)
                if not isinstance(cell, dict):
                    continue
                old_stats = (
                    cell.get("stats_old") if isinstance(cell.get("stats_old"), dict) else {}
                )
                new_stats = (
                    cell.get("stats_new") if isinstance(cell.get("stats_new"), dict) else {}
                )
                raw_ci = cell.get("delta_ci")
                ci_cell = (
                    f"[{_fmt(raw_ci.get('ci_low'))}, {_fmt(raw_ci.get('ci_high'))}]"
                    if isinstance(raw_ci, dict)
                    else "—"
                )
                sh = cell.get("split_half")
                sign = "—"
                if isinstance(sh, dict) and sh.get("available") is True:
                    raw_sign = sh.get("sign_consistent")
                    if raw_sign is True:
                        sign = "一致"
                    elif raw_sign is False:
                        sign = "翻转"
                lines.append(
                    f"| {key} (K={_fmt_count(cell.get('k'))}) "
                    f"| {_fmt_count(cell.get('days_used'))} ({_fmt_count(cell.get('days_skipped'))}) "
                    f"| {_fmt_count(cell.get('overlap_picks'))} "
                    f"| {_fmt(old_stats.get('expectancy'))} "
                    f"| {_fmt(new_stats.get('expectancy'))} "
                    f"| {_fmt(cell.get('delta_point'))} {ci_cell} | {sign} |"
                )
            lines.append("")
    return "\n".join(lines)


def _write_report(payload: dict, json_path: Path, md_path: Path) -> None:
    """双产物落盘 — serialize-first + allow_nan=False + typed fail-closed
    (R148 Op1 门挡池主报告面同款失败契约: 序列化失败零部分产物)。
    """
    try:
        body = json.dumps(payload, ensure_ascii=False, indent=1, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise SystemExit(f"report_not_serializable: {exc}") from exc
    md = render_md(payload)
    try:
        json_path.write_text(body, encoding="utf-8")
        md_path.write_text(md, encoding="utf-8")
    except OSError as exc:
        # 写盘对失败 → best-effort 清除本运行已落盘产物再 typed 退出
        # (R148 Op2 F-a 同款: 不留新 md 配无/旧 json 的半套对)。
        for p in (json_path, md_path):
            try:
                if p.is_file():
                    os.unlink(p)
            except OSError:
                pass
        raise SystemExit(f"report_write_failed: {exc}") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--court-table", default=str(COURT_TABLE),
                        help="court 事件表路径 (默认生产 csv.gz; 测试用 fixture)")
    parser.add_argument("--report-dir", default=str(REPORT_DIR),
                        help="报告输出目录 (测试用 tmp)")
    parser.add_argument("--date-str", default=None,
                        help="报告日期串 YYYYMMDD (默认今日; 夜刷链传入)")
    args = parser.parse_args(argv)

    date_str = args.date_str or date.today().strftime("%Y%m%d")
    if not (isinstance(date_str, str) and len(date_str) == 8 and date_str.isdigit()):
        raise SystemExit(f"invalid_date_str: {date_str!r}")

    court_table = Path(args.court_table)
    if not court_table.exists():
        raise SystemExit(f"court 事件表缺失: {court_table}")
    ev = pd.read_csv(court_table)
    payload = analyze(ev)
    payload["court_rows"] = len(ev)
    payload["court_sessions"] = int(ev["signal_date"].nunique())
    payload["court_window"] = court_window_from_events(ev)

    report_dir = Path(args.report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    json_path = report_dir / f"strength_component_decomposition_{date_str}.json"
    md_path = report_dir / f"strength_component_decomposition_{date_str}.md"
    _write_report(payload, json_path, md_path)
    print(f"report: {json_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
