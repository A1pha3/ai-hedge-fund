"""regime 邻近度条件化诊断 — R166 Op1 (owner standing directive 第 14 轮).

纯诊断 (宪法 #2: 只披露不判定; 任何 gate 平滑/重入条件收紧 = 策略行为变化 =
owner 决策 + 新证据世代 + 预注册)。回答「court 生产对齐 normal 池 E≈0 是否为
d1 翻转日负贡献与 d2+ 稳定日正贡献的混合」— regime 是胜率的主导保护轴
(crisis E=-4.89%/胜率 25.85% vs normal E≈0), 而 Observe 探针 (2026-09-10 宿主
实跑) 实锤: 距上一阻断日恰 1 个会话的 normal 信号日 (d1) E=-1.43% (n=801,
占生产对齐池 49%), d2-5 会话 E=+1.23%; split-half 跨半一致; ≥0.70 桶强度
edge 在 d1 日塌缩。现有证据面 (winrate 分解/cohort/触发器机器) 只按当日
regime 三池条件化, 无任何稳定性/邻近度轴。

预注册轴定义 (2026-09-10, 探索性 in-sample: 边界选自同一次观测数据 —
与 gap>5% 轴 (2026-09-01) 同款纪律, 任何政策使用 = owner + 前向验证):
- 阻断日 = regime ∈ {crisis, risk_off} (两池同被 regime gate 拦截, 合并);
- 距离 = 信号日与最近一个早于等于它的阻断日之间的**会话数** (trading-session
  算术, 周末/节假日不计数 — regime_history.json 的键序即权威会话序, 与
  daily_action regime gate 消费同一文件);
- 组: d1 / d2_5 / d6p / no_prior (窗口内无阻断日) / blocked (信号日自身即
  阻断 — production_aligned 宇宙恒 0 = gate 语义不变量, 仅 all_candidates
  参照池出现) / unknown (信号日不在会话序 — 数据缺口诚实显形)。

单一实现纪律 (R17): 宇宙对齐/净收益/统计/聚类 CI/强度分桶全部复用
winrate_payoff_decomposition (strength_bucket 上游 threshold_trigger),
本模块零口径 fork; 新增的只有轴算术 (proximity_group) 与判读装配
(split-half/交叉/一致性核查)。
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import date
from pathlib import Path

import pandas as pd

from scripts.winrate_payoff_decomposition import (
    MIN_CELL_N,
    cluster_boot_delta_ci,
    court_binding,
    court_window_from_events,
    net_returns,
    production_aligned,
    win_loss_stats,
)
from src.screening.offensive.threshold_trigger import (
    ALL_STRENGTH_BUCKETS,
    strength_bucket,
)

COURT_TABLE_DEFAULT = Path("data/research/btst_court/event_tables/event_table_v1.csv.gz")
REGIME_HISTORY_DEFAULT = Path("data/reports/regime_history.json")
REPORT_DIR_DEFAULT = Path("data/reports")
REPORT_STEM = "regime_proximity_conditioning"

PRIMARY_HORIZON = 10
CONTRAST_HORIZONS = (5,)
HORIZON_COLS = {10: "gross_ret_t10", 5: "gross_ret_t5"}

BLOCKED_REGIMES = ("crisis", "risk_off")
PROXIMITY_ORDER: tuple[str, ...] = ("d1", "d2_5", "d6p", "no_prior", "unknown")
TABLE_GROUPS: tuple[str, ...] = (*PROXIMITY_ORDER, "blocked")  # blocked 参照行恒 n=0 (gate 不变量可见化)
UNKNOWN_GROUP = "unknown"
GROUP_LABELS: dict[str, str] = {
    "d1": "d1 (距阻断日 1 会话)",
    "d2_5": "d2_5 (2-5 会话)",
    "d6p": "d6p (≥6 会话)",
    "no_prior": "no_prior (窗口内无阻断日)",
    "unknown": "unknown (信号日不在会话序)",
    "blocked": "blocked (信号日自身阻断; 生产口径恒 0)",
}


class RegimeProximityError(SystemExit):
    """输入缺失/畸形 — typed fail-closed, 绝不产空报告冒充成功."""


def _is_blocked(label: object) -> bool:
    return label in BLOCKED_REGIMES


def proximity_group(signal_date: str, sessions: list[str], labels: dict[str, str]) -> str:
    """单信号日 → 邻近度组 (会话索引算术, 见模块 docstring 预注册定义).

    signal_date 不在会话序 → unknown (数据缺口诚实显形, 不猜最近邻);
    自身即阻断日 → blocked; 逆序/重复会话序 → unknown (输入契约违反)。
    """
    if signal_date not in labels:
        return UNKNOWN_GROUP
    if _is_blocked(labels[signal_date]):
        return "blocked"
    try:
        i = sessions.index(signal_date)
    except ValueError:
        return UNKNOWN_GROUP
    j = i
    while j >= 0 and not _is_blocked(labels.get(sessions[j], "")):
        j -= 1
    if j < 0:
        return "no_prior"
    distance = i - j
    if distance == 1:
        return "d1"
    if distance <= 5:
        return "d2_5"
    return "d6p"


def proximity_groups(signal_dates, sessions: list[str], labels: dict[str, str]) -> dict[str, str]:
    """批量版: {signal_date: group}; 重复信号日同键覆盖 (dict 语义, 值恒等)."""
    return {d: proximity_group(d, sessions, labels) for d in signal_dates}


def load_regime_history(path: Path) -> tuple[list[str], dict[str, str]]:
    """regime_history.json → (升序会话序, {date: label}); 畸形 typed 拒绝.

    该文件是 daily_action regime gate 消费的生产真相 (daily_action.py:165),
    本工具与 gate 同源 — 门看到的 regime 序列即本工具的轴序列。
    """
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise RegimeProximityError(f"regime_history_unreadable: {path}: {exc}") from exc
    if not isinstance(raw, dict) or not raw:
        raise RegimeProximityError(f"regime_history_malformed: {path}")
    labels: dict[str, str] = {}
    for key, value in raw.items():
        if not isinstance(key, str) or not isinstance(value, str) or not value:
            raise RegimeProximityError(f"regime_history_malformed_entry: {key!r}")
        labels[key] = value
    return sorted(labels), labels


def _horizon_rows(u: pd.DataFrame, horizon: int, prox: dict[str, str]) -> pd.DataFrame:
    """单 horizon 成熟行: 净收益 + 信号日 + 邻近度组 (NaN/None 毒化行剔除)."""
    col = HORIZON_COLS[horizon]
    sub = u[u[col].notna()]
    nets = net_returns(sub[col].astype(float).tolist())
    paired = [
        (n, d)
        for n, d in zip(nets, sub["signal_date"].astype(str))
        if n is not None and math.isfinite(n)
    ]
    rows = pd.DataFrame(paired, columns=["net", "signal_date"])
    rows["group"] = rows["signal_date"].map(lambda d: prox.get(d, UNKNOWN_GROUP))
    return rows


def group_tables(
    u: pd.DataFrame, sessions: list[str], labels: dict[str, str]
) -> tuple[dict[str, dict[str, object]], dict[str, str]]:
    """主分组面: 每 horizon × 组 → win_loss_stats (n≥MIN_CELL_N 才有聚类 CI)."""
    prox = proximity_groups(pd.unique(u["signal_date"].astype(str)), sessions, labels)
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


def residual_pool(u: pd.DataFrame, prox: dict[str, str]) -> dict[str, object]:
    """去 d1 残余池 (d2_5+d6p+no_prior 合并) — 混合效应的直观对照行 (t10)."""
    rows = _horizon_rows(u, PRIMARY_HORIZON, prox)
    resid = rows[rows["group"].isin(("d2_5", "d6p", "no_prior"))]
    stats = win_loss_stats(resid["net"].tolist(), resid["signal_date"].tolist())
    stats["group"] = "d2plus_residual"
    return stats


def grouped_delta(
    rows: pd.DataFrame,
    hi_group: str,
    lo_group: str,
    *,
    n_hi_key: str = "n_hi",
    n_lo_key: str = "n_lo",
) -> dict[str, object]:
    """hi vs lo 任意两组的配对聚类差区间 (正值 = lo 侧罚分).

    R168 Op1 泛化: d1_vs_d2_5_delta 的组参数化单一实现 (调用方可用键名
    保持各自 payload 契约)。任一侧 n<MIN_CELL_N → 区间 None (R153 纪律:
    门槛把关后才进 delta CI)。
    """
    hi = rows[rows["group"] == hi_group]
    lo = rows[rows["group"] == lo_group]
    if len(hi) < MIN_CELL_N or len(lo) < MIN_CELL_N:
        return {"ci_low": None, "ci_high": None, n_hi_key: int(len(hi)), n_lo_key: int(len(lo))}
    ci = cluster_boot_delta_ci(
        hi["net"].tolist(), hi["signal_date"].tolist(),
        lo["net"].tolist(), lo["signal_date"].tolist(),
    )
    return {"ci_low": ci["ci_low"], "ci_high": ci["ci_high"], n_hi_key: int(len(hi)), n_lo_key: int(len(lo))}


def d1_vs_d2_5_delta(rows: pd.DataFrame) -> dict[str, object]:
    """d1 vs d2_5 配对聚类差区间 (hi=d2_5, lo=d1 — 正值 = d1 罚分).

    任一侧 n<MIN_CELL_N → 区间 None (R153 纪律: 门槛把关后才进 delta CI)。
    R168 Op1 起委托 grouped_delta 泛化实现 (键名/键序保持 R166 payload 契约)。
    """
    out = grouped_delta(rows, "d2_5", "d1", n_hi_key="n_d2_5", n_lo_key="n_d1")
    return {"ci_low": out["ci_low"], "ci_high": out["ci_high"], "n_d1": out["n_d1"], "n_d2_5": out["n_d2_5"]}


def split_half_stability(
    rows: pd.DataFrame,
    hi_group: str,
    lo_group: str,
) -> dict[str, object]:
    """hi/lo 任意两组的罚分跨半稳定性 (参与日按日期序对半分 — zero_hit_day 同款切分).

    R15 合取判据镜像: 方向跨半一致才"具备资格", 任一半 n<MIN_CELL_N →
    不可判定; 判定的是资格不是授权 (判读属 owner 评估门)。
    penalty = E(hi) − E(lo) (正值 = lo 侧罚分)。
    R168 Op1 泛化: split_half_verdict 的组参数化单一实现。
    """
    days = sorted(rows["signal_date"].unique())
    if len(days) < 2:
        return {"verdict": "不可判定 (参与日不足)", "consistent": None, "halves": []}
    cut = days[len(days) // 2]
    halves = []
    for name, sub in (
        ("前半", rows[rows["signal_date"] < cut]),
        ("后半", rows[rows["signal_date"] >= cut]),
    ):
        lo = sub[sub["group"] == lo_group]["net"]
        hi = sub[sub["group"] == hi_group]["net"]
        e_lo = float(lo.mean()) if len(lo) else None
        e_hi = float(hi.mean()) if len(hi) else None
        halves.append(
            {
                "half": name,
                "n_lo": int(len(lo)),
                "n_hi": int(len(hi)),
                "e_lo": e_lo,
                "e_hi": e_hi,
                "penalty": (e_hi - e_lo) if (e_lo is not None and e_hi is not None) else None,
                "decidable": e_lo is not None
                and e_hi is not None
                and len(lo) >= MIN_CELL_N
                and len(hi) >= MIN_CELL_N,
            }
        )
    penalties = [h["penalty"] for h in halves if h["decidable"]]
    if len(penalties) == 2:
        consistent = (penalties[0] > 0) == (penalties[1] > 0)
        verdict = "跨半一致" if consistent else "跨半翻转"
    else:
        consistent = None
        verdict = "不可判定 (任一半 n<30)"
    return {"verdict": verdict, "consistent": consistent, "halves": halves}


def split_half_verdict(rows: pd.DataFrame) -> dict[str, object]:
    """d1 罚分跨半稳定性 (参与日按日期序对半分 — zero_hit_day 同款切分).

    R15 合取判据镜像: 方向跨半一致才"具备资格", 任一半 n<MIN_CELL_N →
    不可判定; 判定的是资格不是授权 (判读属 owner 评估门)。
    R168 Op1 起委托 split_half_stability 泛化实现 (键名保持 R166 payload 契约)。
    """
    generic = split_half_stability(rows, "d2_5", "d1")
    renamed_halves = [
        {
            "half": h["half"],
            "n_d1": h["n_lo"],
            "n_d2_5": h["n_hi"],
            "e_d1": h["e_lo"],
            "e_d2_5": h["e_hi"],
            "penalty": h["penalty"],
            "decidable": h["decidable"],
        }
        for h in generic["halves"]
    ]
    return {"verdict": generic["verdict"], "consistent": generic["consistent"], "halves": renamed_halves}


def strength_cross(
    u: pd.DataFrame,
    prox: dict[str, str],
    groups: tuple[str, ...] = ("d1", "d2_5"),
) -> list[dict[str, object]]:
    """强度桶 × 邻近度交叉 (t10; n<MIN_CELL_N 只披露不判定 — R131 同门).

    R168 Op1 起组集合参数化 (默认 ("d1","d2_5") 保持 R166 行为逐字节不变)。
    """
    col = HORIZON_COLS[PRIMARY_HORIZON]
    sub = u[u[col].notna()]
    nets = net_returns(sub[col].astype(float).tolist())
    paired = [
        (n, d, s)
        for n, d, s in zip(
            nets, sub["signal_date"].astype(str), sub["trigger_strength"]
        )
        if n is not None and math.isfinite(n)
    ]
    rows = pd.DataFrame(paired, columns=["net", "signal_date", "strength"])
    rows["group"] = rows["signal_date"].map(lambda d: prox.get(d, UNKNOWN_GROUP))
    rows["bucket"] = rows["strength"].map(strength_bucket)
    out = []
    for bucket in ALL_STRENGTH_BUCKETS:
        for group in groups:
            cell = rows[(rows["bucket"] == bucket) & (rows["group"] == group)]
            stats = win_loss_stats(cell["net"].tolist(), cell["signal_date"].tolist())
            out.append({"bucket": bucket, "group": group, **stats})
    return out


def label_consistency(ev: pd.DataFrame, labels: dict[str, str]) -> dict[str, object]:
    """event_table regime 列 vs regime_history 同日标签 — 错配计数披露 (期望 0)."""
    pairs = ev[["signal_date", "regime"]].drop_duplicates()
    mismatches = []
    for _, row in pairs.iterrows():
        d = str(row["signal_date"])
        hist = labels.get(d)
        if hist is not None and hist != str(row["regime"]):
            mismatches.append(
                {"signal_date": d, "event_table": str(row["regime"]), "history": hist}
            )
    return {
        "checked": int(len(pairs)),
        "mismatch_count": len(mismatches),
        "mismatches": mismatches[:5],
    }


def analyze(ev: pd.DataFrame, history_path: Path) -> dict[str, object]:
    """装配完整 payload (纯函数: 事件表 + history 路径 → dict)."""
    sessions, labels = load_regime_history(history_path)
    u = production_aligned(ev)
    if len(u) == 0:
        raise RegimeProximityError("empty_production_aligned_universe")
    tables, prox = group_tables(u, sessions, labels)
    rows10 = _horizon_rows(u, PRIMARY_HORIZON, prox)
    return {
        "schema_version": 1,
        "axis_definition": {
            "blocked_regimes": list(BLOCKED_REGIMES),
            "groups": {g: GROUP_LABELS[g] for g in (*PROXIMITY_ORDER, "blocked")},
            "preregistered": "2026-09-10 (探索性 in-sample, 与 gap>5% 轴同款纪律)",
        },
        "court_window": court_window_from_events(ev),
        "aligned_n": int(len(u)),
        "tables": tables,
        "residual_pool_t10": residual_pool(u, prox),
        "d1_vs_d2_5_delta_t10": d1_vs_d2_5_delta(rows10),
        "split_half": split_half_verdict(rows10),
        "strength_cross_t10": strength_cross(u, prox),
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
    """payoff (avg_win/|avg_loss|) 是比率不是百分比 — R167 Op2 F-a 修复.

    winrate 工具同列渲染纯比率 (1.22); 走 _fmt(pct=True) 会把 0.99 渲成
    '+99.00%' 被操作员误读为收益率。缺失/毒化 → '—' (R158 家族)。
    """
    if (
        not isinstance(v, (int, float))
        or isinstance(v, bool)
        or (isinstance(v, float) and not math.isfinite(v))
    ):
        return "—"
    return f"{v:.2f}"


def render_md(payload: dict[str, object], date_str: str) -> str:
    """操作员/owner 人读面 — 纪律句 + 组表 + 判读输入 + 一致性核查."""
    lines: list[str] = []
    lines.append(f"# regime 邻近度条件化诊断 ({date_str})")
    lines.append("")
    lines.append(
        "纯诊断 (宪法 #2: 只披露不判定)。信号日按「距上一阻断日 (crisis|risk_off) "
        "的会话数」条件化 — 回答 normal 池聚合 E 是否为 d1 翻转日与 d2+ 稳定日的"
        "混合。净收益 = 毛收益 − 往返 0.65% (winrate 工具同式); 聚类 CI 按信号日"
        "池化 bootstrap (per-call seeded, 可复现)。轴边界 2026-09-10 预注册"
        "(探索性 in-sample); 任何 gate 平滑/重入条件收紧 = 策略行为变化 = "
        "owner 决策 + 新证据世代。"
    )
    lines.append("")
    window = payload.get("court_window") or {}
    lines.append(
        f"court 身份: window {window.get('start')}..{window.get('end')} · "
        f"生产对齐 n={payload.get('aligned_n')} · digest {payload.get('digest')}"
    )
    lines.append("")
    for key in ("t10", "t5"):
        table = (payload.get("tables") or {}).get(key) or {}
        lines.append(f"## {key} (净口径)")
        lines.append("")
        lines.append("| 组 | n | 胜率 | avg_win | avg_loss | payoff | E | CI90 下界 |")
        lines.append("|---|---|---|---|---|---|---|---|")
        for group in TABLE_GROUPS:
            s = table.get(group) or {}
            lines.append(
                f"| {GROUP_LABELS[group]} | {_fmt(s.get('n'), pct=False)} "
                f"| {_fmt(s.get('winrate'))} | {_fmt(s.get('avg_win'))} "
                f"| {_fmt(s.get('avg_loss'))} | {_ratio(s.get('payoff'))} "
                f"| {_fmt(s.get('expectancy'))} | {_fmt(s.get('cluster_ci_low_90'))} |"
            )
        lines.append("")
    resid = payload.get("residual_pool_t10") or {}
    lines.append(
        f"去 d1 残余池 (t10, d2_5+d6p+no_prior 合并): n={_fmt(resid.get('n'), pct=False)} "
        f"E={_fmt(resid.get('expectancy'))} 胜率={_fmt(resid.get('winrate'))} "
        "— 与全体 normal 池聚合读数并列即混合效应直观形态。"
    )
    lines.append("")
    delta = payload.get("d1_vs_d2_5_delta_t10") or {}
    if delta.get("ci_low") is None:
        lines.append(
            f"d1 vs d2_5 配对差区间: 不可判定 (n d1={delta.get('n_d1')} / "
            f"d2_5={delta.get('n_d2_5')} < {MIN_CELL_N})"
        )
    else:
        lines.append(
            f"d1 vs d2_5 配对差区间 (d2_5 − d1, 正值 = d1 罚分): "
            f"[{_fmt(delta.get('ci_low'))}, {_fmt(delta.get('ci_high'))}] "
            f"(n d1={delta.get('n_d1')} / d2_5={delta.get('n_d2_5')}; 双侧 90%, "
            "按信号日配对聚类 bootstrap)"
        )
    lines.append("")
    sh = payload.get("split_half") or {}
    lines.append(f"split-half 稳定性 (R15 判据镜像, 只判定资格不授权): **{sh.get('verdict')}**")
    for half in sh.get("halves") or []:
        lines.append(
            f"- {half.get('half')}: d1 n={half.get('n_d1')} E={_fmt(half.get('e_d1'))} · "
            f"d2_5 n={half.get('n_d2_5')} E={_fmt(half.get('e_d2_5'))} · "
            f"罚分={_fmt(half.get('penalty'))}"
            + ("" if half.get("decidable") else " (n<30 不可判定)")
        )
    lines.append("")
    lines.append("### 强度桶 × 邻近度交叉 (t10, 净口径; n<30 只披露不判定 — R131 同门)")
    lines.append("")
    lines.append("| 强度桶 | 组 | n | 胜率 | E |")
    lines.append("|---|---|---|---|---|")
    for cell in payload.get("strength_cross_t10") or []:
        lines.append(
            f"| {cell.get('bucket')} | {GROUP_LABELS.get(cell.get('group'), cell.get('group'))} "
            f"| {_fmt(cell.get('n'), pct=False)} | {_fmt(cell.get('winrate'))} "
            f"| {_fmt(cell.get('expectancy'))} |"
        )
    lines.append("")
    lc = payload.get("label_consistency") or {}
    lines.append(
        f"regime label 一致性 (event_table vs regime_history): 核查 {lc.get('checked')} 日, "
        f"错配 {lc.get('mismatch_count')} — 错配非零 = 两真相源分歧, 判读前必须归因。"
    )
    lines.append("")
    lines.append("## 纪律")
    lines.append("")
    lines.append(
        "- 本报告是诊断证据, 不是参数变更提案; d1 罚分不构成任何自动 gate 行为。"
    )
    lines.append(
        "- 强度 edge 在 d1 日塌缩的机制归因 (隔夜风险偏好/流动性/反转效应) 属 "
        "owner 判读门; 本工具只提供条件化读数。"
    )
    lines.append(
        "- 复现: `uv run python scripts/regime_proximity_conditioning.py` "
        "(固定 bootstrap 种子, 同输入逐字节可复现)。"
    )
    return "\n".join(lines)


def _attach_digest(payload: dict[str, object], court_table: Path, rows: int) -> None:
    """court 表内容身份 (复用 winrate 工具 court_binding 单一实现); 失败不阻断本体."""
    try:
        binding = court_binding(court_table, rows)
    except Exception:  # noqa: BLE001 — 身份装饰失败只降级为无 digest
        return
    payload["digest"] = binding.get("content_digest")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="regime 邻近度条件化诊断 (纯披露)")
    parser.add_argument("--court-table", type=Path, default=COURT_TABLE_DEFAULT)
    parser.add_argument("--regime-history", type=Path, default=REGIME_HISTORY_DEFAULT)
    parser.add_argument("--out-dir", type=Path, default=REPORT_DIR_DEFAULT)
    parser.add_argument("--date", type=str, default=None, help="报告日期标签 (默认今日; 测试注入)")
    args = parser.parse_args(argv)

    if not args.court_table.exists():
        raise RegimeProximityError(f"court_table_missing: {args.court_table}")
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
    d1 = t10.get("d1") or {}
    d25 = t10.get("d2_5") or {}
    print(
        f"regime_proximity_conditioning: d1 n={d1.get('n')} E={_fmt(d1.get('expectancy'))} · "
        f"d2_5 n={d25.get('n')} E={_fmt(d25.get('expectancy'))} · "
        f"split-half: {(payload.get('split_half') or {}).get('verdict')} → {md_path}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
