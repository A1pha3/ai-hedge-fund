"""regime_blocked_run_conditioning — 阻断连跑条件化诊断 (R168 Op1, 纯披露).

R166 邻近度轴 (scripts/regime_proximity_conditioning.py) 把「距上一阻断日
(crisis|risk_off) 的会话数」条件化后, 其 Observe 探针与宿主首读进一步实锤:
d1 聚合组是两个相反总体的混合 —
- d1_blip (前导阻断连跑=1, 单日闪断后): E=+1.77% n=460 胜率 53.7%;
- d1_run  (前导阻断连跑≥2, 连续危机后): E=-5.74% n=341 胜率 30.8%;
- 配对聚类差 CI90 [+2.49%, +11.94%] 清晰越零 (本工作线首个统计决定性对比);
- d1_run split-half 跨半一致深负 (-2.70%/-6.79%); d2_run 已恢复 (+1.87%)。

本工具把「前导阻断连跑长度」升为显式条件化轴: 组 = (距离, blip|run) 二维,
回答「d1 罚分是连跑危机的机制, 还是任何阻断日后的首日机制」— 这正是
owner 重入规则 (单日闪断 vs 多日危机后何时恢复入场) 的证据维度。

纯诊断 (宪法 #2: 只披露不判定; 任何 gate 平滑/重入条件收紧 = 策略行为变化
= owner 决策 + 新证据世代)。净收益与 btst_court_views 同式 (毛 − 往返
0.65%); 聚类 CI 按信号日池化 bootstrap (per-call seeded, 同输入逐字节可
复现)。轴边界 2026-09-10 预注册 (探索性 in-sample, 与 gap>5% 轴同款纪律)。

实现单一事实源纪律: 复用 winrate 工具 (production_aligned/net_returns/
win_loss_stats/cluster_boot_delta_ci/MIN_CELL_N/court_binding) 与邻近度工具
(load_regime_history/_horizon_rows/grouped_delta/split_half_stability/
strength_cross/label_consistency — 后三者为 R168 Op1 原地参数化的泛化形态,
R166 特化包装行为零漂移); 新增的只有轴算术 (blocked_run_group: 距离 × 连跑
长度会话索引算术) 与判读装配。
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
    BLOCKED_REGIMES,
    CONTRAST_HORIZONS,
    COURT_TABLE_DEFAULT,
    HORIZON_COLS,
    PRIMARY_HORIZON,
    REGIME_HISTORY_DEFAULT,
    REPORT_DIR_DEFAULT,
    UNKNOWN_GROUP,
    RegimeProximityError,
    _horizon_rows,
    grouped_delta,
    label_consistency,
    load_regime_history,
    production_aligned,
    split_half_stability,
    strength_cross,
)
from scripts.winrate_payoff_decomposition import (
    MIN_CELL_N,
    court_binding,
    court_window_from_events,
    net_returns,
    win_loss_stats,
)
from src.screening.offensive.threshold_trigger import ALL_STRENGTH_BUCKETS
from src.screening.offensive.regime_session_geometry import (
    is_blocked as _is_blocked,
    run_geometry,
)

REPORT_STEM = "regime_blocked_run_conditioning"

RUN_GROUPS: tuple[str, ...] = (
    "d1_blip",
    "d1_run",
    "d2_blip",
    "d2_run",
    "d3p_blip",
    "d3p_run",
    "d6p",
    "no_prior",
    "unknown",
)
TABLE_GROUPS: tuple[str, ...] = (*RUN_GROUPS, "blocked")  # blocked 参照行恒 n=0
GROUP_LABELS: dict[str, str] = {
    "d1_blip": "d1_blip (距阻断日 1 会话, 前导连跑=1 单日闪断)",
    "d1_run": "d1_run (距阻断日 1 会话, 前导连跑≥2 连续危机)",
    "d2_blip": "d2_blip (距 2 会话, 前导连跑=1)",
    "d2_run": "d2_run (距 2 会话, 前导连跑≥2)",
    "d3p_blip": "d3p_blip (距 3-5 会话, 前导连跑=1)",
    "d3p_run": "d3p_run (距 3-5 会话, 前导连跑≥2)",
    "d6p": "d6p (≥6 会话, 不按连跑细分)",
    "no_prior": "no_prior (窗口内无阻断日)",
    "unknown": "unknown (信号日不在会话序)",
    "blocked": "blocked (信号日自身阻断; 生产口径恒 0)",
}


class RegimeBlockedRunError(SystemExit):
    """输入缺失/畸形 — typed fail-closed, 绝不产空报告冒充成功."""


def blocked_run_group(
    signal_date: str, sessions: list[str], labels: dict[str, str]
) -> str:
    """信号日 → (距离 × 前导连跑) 组 (委托 run_geometry, R170 Op1 前为单一实现).

    - 自身即阻断日 → blocked; 不在会话序 → unknown; 窗口内无阻断日 → no_prior;
    - dist==1 → d1_blip (run==1) / d1_run (run≥2); dist==2 → d2_*;
      dist 3..5 → d3p_*; dist≥6 → d6p (池化只披露, 不按连跑细分)。
    """
    form, dist, run, _ = run_geometry(signal_date, sessions, labels)
    if form == "blocked":
        return "blocked"
    if form == "unknown":
        return UNKNOWN_GROUP
    if form == "no_prior":
        return "no_prior"
    kind = "blip" if run == 1 else "run"
    if dist == 1:
        return f"d1_{kind}"
    if dist == 2:
        return f"d2_{kind}"
    if dist <= 5:
        return f"d3p_{kind}"
    return "d6p"


def run_groups(
    signal_dates, sessions: list[str], labels: dict[str, str]
) -> dict[str, str]:
    """批量形态 (与单日形态逐日一致, 有测试钉住)."""
    return {d: blocked_run_group(d, sessions, labels) for d in signal_dates}


def grouped_tables(
    u: pd.DataFrame, sessions: list[str], labels: dict[str, str]
) -> tuple[dict[str, dict[str, object]], dict[str, str]]:
    """主分组面: 每 horizon × 组 → win_loss_stats (n≥MIN_CELL_N 才有聚类 CI)."""
    prox = run_groups(pd.unique(u["signal_date"].astype(str)), sessions, labels)
    tables: dict[str, dict[str, object]] = {}
    for horizon in (PRIMARY_HORIZON, *CONTRAST_HORIZONS):
        rows = _horizon_rows(u, horizon, prox)
        table: dict[str, object] = {}
        for group in TABLE_GROUPS:
            cell = rows[rows["group"] == group]
            stats = win_loss_stats(cell["net"].tolist(), cell["signal_date"].tolist())
            stats["group"] = group
            table[group] = stats
        tables[f"t{horizon}"] = table
    return tables, prox


def run_deltas(rows: pd.DataFrame) -> dict[str, object]:
    """三组配对聚类差 (hi=blip 基线, lo=run 对照 — 正值 = run 罚分).

    R153 纪律: 任一侧 n<MIN_CELL_N → 区间 None (门槛把关后才进 delta CI)。
    headline = d1_run_vs_blip (Observe 实锤的决定性对比); d2 是罚分衰减
    (恢复) 检查; d3p 是次级披露。
    """
    out: dict[str, object] = {}
    for key, hi_group, lo_group in (
        ("d1_run_vs_blip", "d1_blip", "d1_run"),
        ("d2_run_vs_blip", "d2_blip", "d2_run"),
        ("d3p_run_vs_blip", "d3p_blip", "d3p_run"),
    ):
        out[key] = grouped_delta(
            rows, hi_group, lo_group, n_hi_key="n_blip", n_lo_key="n_run"
        )
    return out


def residual_ex_d1_run(u: pd.DataFrame, prox: dict[str, str]) -> dict[str, object]:
    """去 d1_run 残余池 (t10) — 「只在连跑危机后首日停, 其余照常」的池形态.

    与 R166 residual_pool (去全部 d1) 对照: 本行保留 d1_blip — 两个残余池
    之差就是「单日闪断日是否值得保留」的直接读数。
    """
    rows = _horizon_rows(u, PRIMARY_HORIZON, prox)
    resid = rows[rows["group"] != "d1_run"]
    stats = win_loss_stats(resid["net"].tolist(), resid["signal_date"].tolist())
    stats["group"] = "ex_d1_run_residual"
    return stats


def analyze(ev: pd.DataFrame, history_path: Path) -> dict[str, object]:
    """装配完整 payload (纯函数: 事件表 + history 路径 → dict)."""
    sessions, labels = load_regime_history(history_path)
    u = production_aligned(ev)
    if len(u) == 0:
        raise RegimeBlockedRunError("empty_production_aligned_universe")
    tables, prox = grouped_tables(u, sessions, labels)
    rows10 = _horizon_rows(u, PRIMARY_HORIZON, prox)
    return {
        "schema_version": 1,
        "axis_definition": {
            "blocked_regimes": list(BLOCKED_REGIMES),
            "groups": {g: GROUP_LABELS[g] for g in TABLE_GROUPS},
            "run_definition": "结束于最后阻断日的连续阻断日计数 (被 normal 日打断重新计)",
            "run_censoring": "窗口起点即阻断日时 run 从 sessions[0] 起计 — 右删失下界 (真 run 可能早于窗口); 真实窗口起点 normal, 理论形态",
            "preregistered": "2026-09-10 (探索性 in-sample, 与 gap>5% 轴同款纪律)",
        },
        "court_window": court_window_from_events(ev),
        "aligned_n": int(len(u)),
        "tables": tables,
        "run_deltas_t10": run_deltas(rows10),
        "split_half_d1": split_half_stability(rows10, "d1_blip", "d1_run"),
        "residual_ex_d1_run_t10": residual_ex_d1_run(u, prox),
        "strength_cross_t10": strength_cross(
            u, prox, groups=("d1_blip", "d1_run")
        ),
        "label_consistency": label_consistency(ev, labels),
    }


def _fmt(v: object, pct: bool = True) -> str:
    if (
        not isinstance(v, (int, float))
        or isinstance(v, bool)
        or (isinstance(v, float) and not math.isfinite(v))
    ):
        return "—"
    return f"{v:+.2%}" if pct else f"{v:,.0f}"


def _ratio(v: object) -> str:
    """payoff 是比率不是百分比 (R167 Op2 F-a 同款纪律)."""
    if (
        not isinstance(v, (int, float))
        or isinstance(v, bool)
        or (isinstance(v, float) and not math.isfinite(v))
    ):
        return "—"
    return f"{v:.2f}"


def _stats_row(table: dict[str, object], group: str) -> dict[str, object]:
    """渲染存活: 表缺任意组键 → 整行 '—' 不崩 (R167 Op2 同款防御面)."""
    stats = table.get(group)
    if not isinstance(stats, dict):
        return {"n": None, "winrate": None, "avg_win": None, "avg_loss": None,
                "payoff": None, "expectancy": None, "cluster_ci_low_90": None}
    return stats


def _render_table(table: dict[str, object], title: str) -> list[str]:
    lines = [f"## {title}", "", "| 组 | n | 胜率 | avg_win | avg_loss | payoff | E | CI90 下界 |",
             "|---|---|---|---|---|---|---|---|"]
    for group in TABLE_GROUPS:
        s = _stats_row(table, group)
        lines.append(
            f"| {GROUP_LABELS[group]} | {_fmt(s.get('n'), pct=False)} "
            f"| {_fmt(s.get('winrate'))} | {_fmt(s.get('avg_win'))} "
            f"| {_fmt(s.get('avg_loss'))} | {_ratio(s.get('payoff'))} "
            f"| {_fmt(s.get('expectancy'))} | {_fmt(s.get('cluster_ci_low_90'))} |"
        )
    lines.append("")
    return lines


def render_md(payload: dict[str, object], date_str: str) -> str:
    """payload → markdown 报告 (纯函数; falsy-zero 保真, 缺键整行 '—')."""
    tables = payload.get("tables") or {}
    t10 = tables.get("t10") or {}
    t5 = tables.get("t5") or {}
    deltas = payload.get("run_deltas_t10") or {}
    sh = payload.get("split_half_d1") or {}
    resid = payload.get("residual_ex_d1_run_t10") or {}
    cross = payload.get("strength_cross_t10") or []
    lc = payload.get("label_consistency") or {}
    axis = payload.get("axis_definition") or {}

    lines = [
        f"# regime 阻断连跑条件化诊断 ({date_str})",
        "",
        "纯诊断 (宪法 #2: 只披露不判定)。R166 邻近度轴实锤 d1 聚合组为混合",
        "总体; 本工具按「距离 × 前导阻断连跑长度」二维条件化 — 回答 d1 罚分",
        "属连跑危机机制还是任何阻断后首日机制 (owner 重入规则的证据维度)。",
        "净收益 = 毛收益 − 往返 0.65% (winrate 工具同式); 聚类 CI 按信号日",
        "池化 bootstrap (per-call seeded, 可复现)。轴边界 2026-09-10 预注册",
        "(探索性 in-sample); 任何 gate 平滑/重入条件收紧 = owner 决策 + 新证据世代。",
        "",
        f"court 窗口: {payload.get('court_window', {}).get('start')}.."
        f"{payload.get('court_window', {}).get('end')} · 生产对齐 n={payload.get('aligned_n')}"
        f" · 连跑定义: {axis.get('run_definition')}",
        "",
    ]
    lines += _render_table(t10, f"t{PRIMARY_HORIZON} (净口径)")
    lines += _render_table(t5, f"t{CONTRAST_HORIZONS[0]} (净口径)")

    resid_n = resid.get("n")
    lines += [
        f"去 d1_run 残余池 (t10, 保留 d1_blip): n={_fmt(resid_n, pct=False)} "
        f"E={_fmt(resid.get('expectancy'))} 胜率={_fmt(resid.get('winrate'))} "
        f"— 与全体池聚合读数并列即「只停连跑危机首日」的池形态直读。",
        "",
    ]

    d1 = deltas.get("d1_run_vs_blip") or {}
    d2 = deltas.get("d2_run_vs_blip") or {}
    d3p = deltas.get("d3p_run_vs_blip") or {}
    lines += [
        "配对聚类差区间 (blip − run, 正值 = run 罚分; 双侧 90%, 按信号日配对):",
        f"- d1 (headline): [{_fmt(d1.get('ci_low'))}, {_fmt(d1.get('ci_high'))}] "
        f"(n blip={_fmt(d1.get('n_blip'), pct=False)} / run={_fmt(d1.get('n_run'), pct=False)})",
        f"- d2 (罚分衰减检查): [{_fmt(d2.get('ci_low'))}, {_fmt(d2.get('ci_high'))}] "
        f"(n blip={_fmt(d2.get('n_blip'), pct=False)} / run={_fmt(d2.get('n_run'), pct=False)})",
        f"- d3p (次级披露): [{_fmt(d3p.get('ci_low'))}, {_fmt(d3p.get('ci_high'))}] "
        f"(n blip={_fmt(d3p.get('n_blip'), pct=False)} / run={_fmt(d3p.get('n_run'), pct=False)})",
        "",
        f"split-half 稳定性 (d1_blip vs d1_run, R15 判据镜像, 只判定资格不授权): "
        f"**{sh.get('verdict', '—')}**",
    ]
    for h in sh.get("halves", []):
        lines.append(
            f"- {h.get('half')}: blip n={_fmt(h.get('n_hi'), pct=False)} "
            f"E={_fmt(h.get('e_hi'))} · run n={_fmt(h.get('n_lo'), pct=False)} "
            f"E={_fmt(h.get('e_lo'))} · 罚分={_fmt(h.get('penalty'))}"
        )
    lines += ["", "### 强度桶 × 连跑组交叉 (t10, 净口径; n<30 只披露不判定 — R131 同门)", "",
              "| 强度桶 | 组 | n | 胜率 | E |", "|---|---|---|---|---|"]
    for cell in cross:
        lines.append(
            f"| {cell.get('bucket')} | {cell.get('group')} "
            f"| {_fmt(cell.get('n'), pct=False)} | {_fmt(cell.get('winrate'))} "
            f"| {_fmt(cell.get('expectancy'))} |"
        )
    mismatch = lc.get("mismatch_count")
    lines += [
        "",
        f"regime label 一致性 (event_table vs regime_history): 核查 "
        f"{_fmt(lc.get('checked'), pct=False)} 日, 错配 {_fmt(mismatch, pct=False)} "
        f"— 错配非零 = 两真相源分歧, 判读前必须归因。",
        "",
        "## 纪律",
        "",
        "- 本报告是诊断证据, 不是参数变更提案; blip/run 分化不构成任何自动 gate 行为。",
        "- 连跑危机后首日深负的机制归因 (隔夜风险偏好/流动性/反转效应) 属 owner 判读门;",
        "  强度桶 × 连跑组的交互读数只披露 (多重比较未校正, 探索性 in-sample)。",
        "- 窗口起点即阻断日时连跑计数右删失 (下界语义, 见 axis_definition.run_censoring);",
        "- 复现: `uv run python scripts/regime_blocked_run_conditioning.py` "
        "(固定 bootstrap 种子, 同输入逐字节可复现)。",
        "",
    ]
    return "\n".join(lines)


def _attach_digest(payload: dict[str, object], court_table: Path, rows: int) -> None:
    """court 表内容身份 (复用 winrate 工具 court_binding 单一实现); 失败不阻断本体."""
    try:
        binding = court_binding(court_table, rows)
    except Exception:  # noqa: BLE001 — 身份装饰失败只降级为无 digest
        return
    payload["digest"] = binding.get("content_digest")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="regime 阻断连跑条件化诊断 (纯披露)")
    parser.add_argument("--court-table", type=Path, default=COURT_TABLE_DEFAULT)
    parser.add_argument("--regime-history", type=Path, default=REGIME_HISTORY_DEFAULT)
    parser.add_argument("--out-dir", type=Path, default=REPORT_DIR_DEFAULT)
    parser.add_argument("--date", type=str, default=None, help="报告日期标签 (默认今日; 测试注入)")
    args = parser.parse_args(argv)

    if not args.court_table.exists():
        raise RegimeBlockedRunError(f"court_table_missing: {args.court_table}")
    ev = pd.read_csv(args.court_table)
    payload = analyze(ev, args.regime_history)
    date_str = args.date or date.today().strftime("%Y%m%d")
    payload["report_date"] = date_str
    _attach_digest(payload, args.court_table, rows=int(len(ev)))

    args.out_dir.mkdir(parents=True, exist_ok=True)
    md_path = args.out_dir / f"{REPORT_STEM}_{date_str}.md"
    json_path = args.out_dir / f"{REPORT_STEM}_{date_str}.json"
    md_path.write_text(render_md(payload, date_str), encoding="utf-8")
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True, default=str),
        encoding="utf-8",
    )
    t10 = (payload.get("tables") or {}).get("t10") or {}
    blip = _stats_row(t10, "d1_blip")
    run = _stats_row(t10, "d1_run")
    print(
        f"regime_blocked_run_conditioning: d1_blip n={blip.get('n')} "
        f"E={_fmt(blip.get('expectancy'))} · d1_run n={run.get('n')} "
        f"E={_fmt(run.get('expectancy'))} · split-half: "
        f"{(payload.get('split_half_d1') or {}).get('verdict')} → {md_path}"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
