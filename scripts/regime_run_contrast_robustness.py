"""regime_run_contrast_robustness — d1_run 决定性对比的规格稳健性审计 (R170 Op1, 纯披露).

R168 的 d1_blip (+1.77%/胜率 53.7%) vs d1_run (−5.74%/30.8%) 配对聚类差
CI90 [+2.49%, +11.94%] 是胜率/赔率工作线首个统计决定性对比 — 但它至今只受
过单一规格检验 (in-sample 单窗口单轴定义)。owner 的重入规则决策 (连跑危机
后首日是否停入) 押在该发现上; 本工具对该发现做三面规格攻击, 两种走向都推
进证据质量 (稳健 → 决策级; 脆弱 → 如实降格):

1. placebo_circular_shift — 把 regime label 会话序做全部 n 个循环移位的
   穷举精确置换 (零 RNG; k=0 即恒等, 有自检), 每个移位用与生产轴同一
   run_geometry 算术重算 d1 归属后取确定性点估计 E(d1_blip) − E(d1_run)。
   观测罚分在移位分布中的双侧精确秩回答: 「阻断日时序相对收益带信息」
   还是「任意随机日集合都能造出同幅分裂」。
2. influence_leave_one_day_out — 逐 d1_run 信号日剔除重算罚分; 报告
   delta 域、翻符号日数、逐日罚分份额 (精确 telescoping 分解: 逐日
   share = n_d·(blip_mean − day_mean) / (N·delta_full), 全和恒 1) 与
   top-1 份额 — 单日剔除即翻符号 = 脆弱信号。
3. definition_sensitivity — run≥3 深危机阈值重算 (run==2 退出两侧)、
   d1_run 内纯 crisis vs 含 risk_off 连跑分解、d1 桶内精确连跑长度
   1/2/3/4+ 剂量反应 — 轴定义敏感性。

实现单一事实源纪律: 复用 winrate 工具 (production_aligned/net_returns/
win_loss_stats/cluster_boot_delta_ci/MIN_CELL_N/court_binding)、邻近度工具
(load_regime_history/_horizon_rows/grouped_delta/label_consistency) 与
blocked-run 工具 (run_geometry 轴算术单一实现 + _fmt/_ratio 渲染守卫)。
净收益与 btst_court_views 同式 (毛 − 往返 0.65%)。

纯诊断 (宪法 #2: 只披露不判定; 任何 gate 平滑/重入条件收紧 = 策略行为
变化 = owner 决策 + 新证据世代)。规格攻击面 2026-09-10 预注册 (探索性
in-sample; placebo 双 horizon, 影响与定义敏感度取 t10 主 horizon)。
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import date
from pathlib import Path

import pandas as pd

from scripts.regime_blocked_run_conditioning import (
    REPORT_DIR_DEFAULT,
    _fmt,
    _ratio,
    run_geometry,
)
from scripts.regime_proximity_conditioning import (
    BLOCKED_REGIMES,
    PRIMARY_HORIZON,
    REGIME_HISTORY_DEFAULT,
    COURT_TABLE_DEFAULT,
    _horizon_rows,
    grouped_delta,
    label_consistency,
    load_regime_history,
    production_aligned,
)
from scripts.regime_blocked_run_conditioning import run_groups
from scripts.winrate_payoff_decomposition import (
    MIN_CELL_N,
    court_binding,
    court_window_from_events,
    win_loss_stats,
)

REPORT_STEM = "regime_run_contrast_robustness"
CONTRAST_HORIZONS = (PRIMARY_HORIZON, 5)
_EPS = 1e-12


class RegimeRunRobustnessError(SystemExit):
    """输入缺失/畸形 — typed fail-closed, 绝不产空报告冒充成功."""


def _shifted_labels(
    sessions: list[str], labels: dict[str, str], k: int
) -> dict[str, str]:
    """label 会话序向前循环移位 k (k=0 恒等)."""
    n = len(sessions)
    return {sessions[i]: labels[sessions[(i + k) % n]] for i in range(n)}


def _delta_point(rows: pd.DataFrame, sessions: list[str], labels_map: dict[str, str]) -> float | None:
    """E(d1_blip) − E(d1_run) 确定性点估计 (任一侧空 → None)."""
    groups = run_groups(pd.unique(rows["signal_date"].astype(str)), sessions, labels_map)
    blip: list[float] = []
    run: list[float] = []
    for net, day in zip(rows["net"].astype(float), rows["signal_date"].astype(str)):
        if groups.get(day) == "d1_blip":
            blip.append(float(net))
        elif groups.get(day) == "d1_run":
            run.append(float(net))
    if not blip or not run:
        return None
    return sum(blip) / len(blip) - sum(run) / len(run)


def placebo_circular_shift(
    rows: pd.DataFrame, sessions: list[str], labels: dict[str, str]
) -> dict[str, object]:
    """穷举循环移位精确置换 (零 RNG). p = #{|delta_k| ≥ |观测|} / n_valid.

    k=0 恒等移位恒在列 (自检: identity_shift_delta == observed_delta);
    单会话窗口或观测侧为空 → placebo_undefined (无移位分布可言)。
    分位数是离散经验分位 (sorted[floor(q·(m−1))], 无插值) — 确定性优先。
    """
    n = len(sessions)
    observed = _delta_point(rows, sessions, labels)
    out: dict[str, object] = {
        "observed_delta": observed,
        "identity_shift_delta": None,
        "n_shifts": n,
        "n_valid_shifts": 0,
        "p_value": None,
        "placebo_undefined": True,
        "delta_quantiles": {"p05": None, "p50": None, "p95": None},
    }
    if n < 2 or observed is None:
        return out
    deltas: list[float] = []
    identity: float | None = None
    for k in range(n):
        shifted = _shifted_labels(sessions, labels, k)
        delta = _delta_point(rows, sessions, shifted)
        if delta is None:
            continue
        if k == 0:
            identity = delta
        deltas.append(delta)
    m = len(deltas)
    out["identity_shift_delta"] = identity
    if identity is None or m == 0:
        return out
    rank = sum(1 for d in deltas if abs(d) >= abs(observed) - _EPS)
    sorted_d = sorted(deltas)

    def _quantile(q: float) -> float:
        return sorted_d[int(q * (m - 1))]

    out.update({
        "n_valid_shifts": m,
        "p_value": rank / m,
        "placebo_undefined": False,
        "delta_quantiles": {
            "p05": _quantile(0.05),
            "p50": _quantile(0.50),
            "p95": _quantile(0.95),
        },
    })
    return out


def influence_leave_one_day_out(rows: pd.DataFrame) -> dict[str, object]:
    """逐 d1_run 信号日剔除重算罚分; 逐日份额是精确 telescoping 分解.

    share_d = n_d·(blip_mean − day_mean) / (N·delta_full) (全和恒 1);
    剔除后 run 侧 n<MIN_CELL_N → delta_without=None (R153 纪律)。
    翻符号: delta_full>0 且 delta_without≤0 (或镜像)。
    """
    blip = rows[rows["group"] == "d1_blip"]
    run = rows[rows["group"] == "d1_run"]
    out: dict[str, object] = {
        "delta_full": None, "n_days": 0, "n_run": int(len(run)),
        "n_blip": int(len(blip)), "sign_flip_days": None,
        "top_days": [], "top1_penalty_share": None,
    }
    if len(blip) < MIN_CELL_N or len(run) < MIN_CELL_N:
        return out
    blip_mean = float(blip["net"].astype(float).mean())
    day_stats: list[dict[str, object]] = []
    for day in sorted(run["signal_date"].astype(str).unique()):
        cell = run[run["signal_date"].astype(str) == day]
        day_mean = float(cell["net"].astype(float).mean())
        kept = run[run["signal_date"].astype(str) != day]
        delta_without: float | None
        if len(kept) < MIN_CELL_N:
            delta_without = None
        else:
            delta_without = blip_mean - float(kept["net"].astype(float).mean())
        day_stats.append({
            "date": day, "n": int(len(cell)), "mean": day_mean,
            "delta_without": delta_without,
        })
    n_total = int(len(run))
    delta_full = blip_mean - float(run["net"].astype(float).mean())
    for st in day_stats:
        st["share"] = (
            st["n"] * (blip_mean - float(st["mean"])) / (n_total * delta_full)
            if delta_full != 0 else None
        )
    flip = (lambda d: d <= 0) if delta_full > 0 else (lambda d: d >= 0)
    sign_flips = sum(
        1
        for st in day_stats
        if isinstance(st["delta_without"], float) and flip(st["delta_without"])
    )
    ranked = sorted(
        day_stats,
        key=lambda st: abs(float(st["share"])) if st["share"] is not None else 0.0,
        reverse=True,
    )
    out.update({
        "delta_full": delta_full,
        "n_days": len(day_stats),
        "sign_flip_days": sign_flips,
        "top_days": ranked[:3],
        "top1_penalty_share": ranked[0]["share"] if ranked else None,
    })
    return out


def run_threshold_3_groups(
    rows: pd.DataFrame, sessions: list[str], labels: dict[str, str]
) -> pd.DataFrame:
    """run≥3 深危机阈值重分: run==2 → d1_run_lt3 (退出两侧), run≥3 → d1_run3."""
    out = rows.copy()
    new_groups: list[str] = []
    for _, row in out.iterrows():
        group = str(row["group"])
        if group in ("d1_blip", "d1_run"):
            form, dist, run_len, _ = run_geometry(
                str(row["signal_date"]), sessions, labels
            )
            if form == "normal" and dist == 1:
                if run_len == 1:
                    new_groups.append("d1_blip")
                elif run_len >= 3:
                    new_groups.append("d1_run3")
                else:
                    new_groups.append("d1_run_lt3")
                continue
        new_groups.append(group)
    out["group"] = new_groups
    return out


def _label_decomposition(
    rows: pd.DataFrame, sessions: list[str], labels: dict[str, str]
) -> dict[str, object]:
    """d1_run 内: 纯 crisis 连跑 vs 含 risk_off 连跑 (win_loss_stats 只披露)."""
    run = rows[rows["group"] == "d1_run"]
    pure: list[tuple[float, str]] = []
    mixed: list[tuple[float, str]] = []
    for net, day in zip(run["net"].astype(float), run["signal_date"].astype(str)):
        _, _, _, run_labels = run_geometry(day, sessions, labels)
        (mixed if "risk_off" in run_labels else pure).append((float(net), day))
    out: dict[str, object] = {}
    for name, pairs in (("pure_crisis", pure), ("contains_risk_off", mixed)):
        st = win_loss_stats([p[0] for p in pairs], [p[1] for p in pairs])
        out[name] = {
            "n": st["n"], "winrate": st["winrate"],
            "expectancy": st["expectancy"],
            "cluster_ci_low_90": st["cluster_ci_low_90"],
        }
    return out


def dose_response(
    rows: pd.DataFrame, sessions: list[str], labels: dict[str, str]
) -> list[dict[str, object]]:
    """d1 桶内精确连跑长度 1/2/3/4+ 的 n/胜率/E (只披露; 未预注册判定)."""
    d1 = rows[rows["group"].isin(("d1_blip", "d1_run"))]
    buckets: dict[object, list[tuple[float, str]]] = {
        1: [], 2: [], 3: [], "4+": [],
    }
    for net, day in zip(d1["net"].astype(float), d1["signal_date"].astype(str)):
        _, dist, run_len, _ = run_geometry(day, sessions, labels)
        if dist != 1:
            continue
        buckets[run_len if run_len in (1, 2, 3) else "4+"].append((float(net), day))
    table: list[dict[str, object]] = []
    for key in (1, 2, 3, "4+"):
        pairs = buckets[key]
        st = win_loss_stats([p[0] for p in pairs], [p[1] for p in pairs])
        table.append({
            "run_len": key, "n": st["n"],
            "winrate": st["winrate"], "expectancy": st["expectancy"],
        })
    return table


def definition_sensitivity(
    rows: pd.DataFrame, sessions: list[str], labels: dict[str, str]
) -> dict[str, object]:
    """轴定义敏感度: run≥3 阈值差区间 + label 分解 (t10, 只披露)."""
    rows3 = run_threshold_3_groups(rows, sessions, labels)
    threshold_3 = grouped_delta(
        rows3, "d1_blip", "d1_run3", n_hi_key="n_blip", n_lo_key="n_run3"
    )
    return {
        "threshold_3_delta": threshold_3,
        "label_decomposition": _label_decomposition(rows, sessions, labels),
    }


def analyze(ev: pd.DataFrame, history_path: Path) -> dict[str, object]:
    """装配完整 payload (纯函数: 事件表 + history 路径 → dict)."""
    sessions, labels = load_regime_history(history_path)
    u = production_aligned(ev)
    if len(u) == 0:
        raise RegimeRunRobustnessError("empty_production_aligned_universe")
    prox = run_groups(pd.unique(u["signal_date"].astype(str)), sessions, labels)
    rows_by_h = {h: _horizon_rows(u, h, prox) for h in CONTRAST_HORIZONS}
    rows10 = rows_by_h[PRIMARY_HORIZON]
    return {
        "schema_version": 1,
        "headline": {
            "contrast": "d1_blip vs d1_run 配对聚类差 (R168 决定性对比的规格攻击)",
            "preregistered": (
                "2026-09-10 (探索性 in-sample; placebo 双 horizon, "
                "影响/定义敏感度取 t10 主 horizon)"
            ),
        },
        "axis_definition": {
            "blocked_regimes": list(BLOCKED_REGIMES),
            "attack_faces": [
                "placebo_circular_shift (时序识别力, 穷举精确置换)",
                "influence_leave_one_day_out (脆弱性集中度)",
                "definition_sensitivity (run 阈值/label 分解/剂量反应)",
            ],
            "run_censoring": "窗口起点即阻断日时 run 从 sessions[0] 起计 — 右删失下界 (R169 同款披露)",
        },
        "court_window": court_window_from_events(ev),
        "aligned_n": int(len(u)),
        "observed": {
            f"t{h}": {
                "delta_point": _delta_point(rows_by_h[h], sessions, labels),
                "delta_ci": grouped_delta(
                    rows_by_h[h], "d1_blip", "d1_run",
                    n_hi_key="n_blip", n_lo_key="n_run",
                ),
            }
            for h in CONTRAST_HORIZONS
        },
        "placebo_circular_shift": {
            f"t{h}": placebo_circular_shift(rows_by_h[h], sessions, labels)
            for h in CONTRAST_HORIZONS
        },
        "influence_leave_one_day_out": influence_leave_one_day_out(rows10),
        "definition_sensitivity": definition_sensitivity(rows10, sessions, labels),
        "dose_response_t10": dose_response(rows10, sessions, labels),
        "label_consistency": label_consistency(ev, labels),
    }


def _cell(v: object, *, ratio: bool = False) -> str:
    if ratio:
        return _ratio(v)
    return _fmt(v)


def _p_value(v: object) -> str:
    """精确置换 p 值 3 位小数 (0≤p≤1 形态守卫, 非/非有限 → '—')."""
    if (
        not isinstance(v, (int, float))
        or isinstance(v, bool)
        or (isinstance(v, float) and not math.isfinite(v))
    ):
        return "—"
    return f"{v:.3f}"


def render_md(payload: dict[str, object], date_str: str) -> str:
    """payload → MD 报告 (渲染存活: 缺键/None → '—', falsy-zero 显示)."""
    observed = payload.get("observed") or {}
    placebo = payload.get("placebo_circular_shift") or {}
    influence = payload.get("influence_leave_one_day_out") or {}
    definition = payload.get("definition_sensitivity") or {}
    dose = payload.get("dose_response_t10") or []
    lines: list[str] = []
    lines.append(f"# regime 连跑对比规格稳健性审计 ({date_str})")
    lines.append("")
    lines.append(
        "纯诊断 (宪法 #2: 只披露不判定)。对 R168 d1_blip vs d1_run 决定性对比"
        "的三面规格攻击: 循环移位精确置换 placebo (穷举零 RNG) / leave-one-"
        "day-out 影响集中度 / 定义替代敏感度。任何 gate 行为变化 = owner 决策 "
        "+ 新证据世代。"
    )
    lines.append("")
    window = payload.get("court_window") or {}
    lines.append(
        f"court 窗口: {window.get('start')}..{window.get('end')}"
        f" · 生产对齐 n={payload.get('aligned_n')}"
    )
    lines.append("")
    lines.append("## 观测基线 (净口径点估计 + 配对聚类差 CI90)")
    lines.append("")
    lines.append("| horizon | E(blip)−E(run) | CI 下界 | CI 上界 | n blip | n run |")
    lines.append("|---|---|---|---|---|---|")
    for h in ("t10", "t5"):
        cell = observed.get(h) or {}
        ci = cell.get("delta_ci") or {}
        lines.append(
            f"| {h} | {_cell(cell.get('delta_point'))} "
            f"| {_cell(ci.get('ci_low'))} | {_cell(ci.get('ci_high'))} "
            f"| {ci.get('n_blip', '—')} | {ci.get('n_run', '—')} |"
        )
    lines.append("")
    lines.append("## 循环移位精确置换 placebo (零 RNG)")
    lines.append("")
    lines.append(
        "p = 移位分布中 |Δ| ≥ |观测| 的精确频率 (含 k=0 恒等自检); "
        "小 p = 阻断日时序识别力成立, 大 p = 任意随机日集合可造出同幅分裂。"
    )
    lines.append("")
    lines.append("| horizon | 观测 Δ | 恒等 Δ | 有效移位 | p | Δ p05 | Δ p50 | Δ p95 |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for h in ("t10", "t5"):
        cell = placebo.get(h) or {}
        q = cell.get("delta_quantiles") or {}
        if cell.get("placebo_undefined"):
            lines.append(
                f"| {h} | {_cell(cell.get('observed_delta'))} | — | 0 | — "
                "(退化/无观测) | — | — | — |"
            )
            continue
        lines.append(
            f"| {h} | {_cell(cell.get('observed_delta'))} "
            f"| {_cell(cell.get('identity_shift_delta'))} "
            f"| {cell.get('n_valid_shifts', '—')} | {_p_value(cell.get('p_value'))} "
            f"| {_cell(q.get('p05'))} | {_cell(q.get('p50'))} "
            f"| {_cell(q.get('p95'))} |"
        )
    lines.append("")
    lines.append("## leave-one-day-out 影响集中度 (t10)")
    lines.append("")
    lines.append(
        f"delta_full {_cell(influence.get('delta_full'))} · 参与 run 日 "
        f"{influence.get('n_days', '—')} · 翻符号日 {influence.get('sign_flip_days', '—')}"
        f" · top-1 份额 {_cell(influence.get('top1_penalty_share'))} "
        "(翻符号 > 0 或 top-1 份额 ≫ 1 = 单日驱动的脆弱信号)"
    )
    lines.append("")
    lines.append("| run 日 | n | 日均净 | 份额 | 剔除后 Δ |")
    lines.append("|---|---|---|---|---|")
    for st in influence.get("top_days") or []:
        lines.append(
            f"| {st.get('date', '—')} | {st.get('n', '—')} "
            f"| {_cell(st.get('mean'))} | {_cell(st.get('share'))} "
            f"| {_cell(st.get('delta_without'))} |"
        )
    lines.append("")
    lines.append("## 定义替代敏感度 (t10)")
    lines.append("")
    t3 = (definition.get("threshold_3_delta") or {})
    lines.append(
        f"- run≥3 阈值: Δ(blip−run3) {_cell(t3.get('ci_low'))}.."
        f"{_cell(t3.get('ci_high'))} (n blip={t3.get('n_blip', '—')}"
        f"/ run3={t3.get('n_run3', '—')}; run==2 退出两侧)"
    )
    dec = definition.get("label_decomposition") or {}
    for name in ("pure_crisis", "contains_risk_off"):
        cell = dec.get(name) or {}
        lines.append(
            f"- {name}: n={cell.get('n', '—')} 胜率 {_cell(cell.get('winrate'))} "
            f"E {_cell(cell.get('expectancy'))}"
        )
    lines.append("")
    lines.append("### 剂量反应 (d1 桶按精确连跑长度, t10)")
    lines.append("")
    lines.append("| 连跑长度 | n | 胜率 | E |")
    lines.append("|---|---|---|---|")
    for row in dose:
        lines.append(
            f"| {row.get('run_len', '—')} | {row.get('n', '—')} "
            f"| {_cell(row.get('winrate'))} | {_cell(row.get('expectancy'))} |"
        )
    lines.append("")
    consistency = payload.get("label_consistency") or {}
    lines.append(
        f"regime label 一致性 (event_table vs regime_history): 核查 "
        f"{consistency.get('checked', '—')} 日, 错配 "
        f"{consistency.get('mismatch_count', '—')} — 错配非零 = 两真相源分歧。"
    )
    lines.append("")
    lines.append("## 纪律")
    lines.append("")
    lines.append(
        "- 本报告是诊断证据, 不是参数变更提案; 规格攻击结论不构成任何自动 "
        "gate 行为 (宪法 #2)。\n"
        "- placebo/影响/定义敏感度均为探索性 in-sample 读数; 判读属 owner 门。\n"
        "- 复现: `uv run python scripts/regime_run_contrast_robustness.py` "
        "(穷举置换零 RNG, 同输入逐字节可复现)。"
    )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--court-table", type=Path, default=COURT_TABLE_DEFAULT)
    parser.add_argument("--regime-history", type=Path, default=REGIME_HISTORY_DEFAULT)
    parser.add_argument("--report-dir", type=Path, default=REPORT_DIR_DEFAULT)
    args = parser.parse_args(argv)

    ev = pd.read_csv(args.court_table)
    payload = analyze(ev, args.regime_history)
    date_str = date.today().strftime("%Y%m%d")
    out_dir = args.report_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    md_path = out_dir / f"{REPORT_STEM}_{date_str}.md"
    json_path = out_dir / f"{REPORT_STEM}_{date_str}.json"
    md_path.write_text(render_md(payload, date_str), encoding="utf-8")
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    binding = court_binding(args.court_table, int(len(ev)))
    placebo10 = (payload.get("placebo_circular_shift") or {}).get("t10") or {}
    influence = payload.get("influence_leave_one_day_out") or {}
    print(json.dumps({
        "report": str(md_path),
        "binding": binding,
        "aligned_n": payload.get("aligned_n"),
        "placebo_p_t10": placebo10.get("p_value"),
        "sign_flip_days": influence.get("sign_flip_days"),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
