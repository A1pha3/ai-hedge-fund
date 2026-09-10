"""regime_excess_return_decomposition — 净收益的 beta/selection 恒等分解 (R172 Op1, 纯披露).

工作线证据 (R166-R171) 至今全部在净收益空间: R168 决定性对比 d1_blip +1.77%
vs d1_run −5.74% 与全体池 E 从未与市场基准对照。crisis 会话本质是市场回撤期,
T+10 窗口的高动量涨停候选天然高 beta — 罚分可能是市场 beta 而非选股 alpha,
这改变 gate 证据的机制解读 (择时 vs 选股) 与胜率/赔率改进力量的投向。

本工具把每个候选的净收益做恒等分解:
    net = bench + excess,  E(group) = E_bench(group) + E_excess(group)
bench = 等权全市场 (raw daily 快照全体) open→open 收益, 与 court 执行口径同
一窗口: 入场 = 信号日后首会话开盘, 退出 = exit_session_t{k} 偏移量处的开盘
(顺延语义与构建器 forward_open_returns 一致)。窗口逐位自检: 逐候选用 raw
daily 重算 gross 必须与事件表列一致, 不一致 = 窗口约定漂移, fail-closed 不
产报告。

四面披露 (t10 主 horizon + t8):
1. 分组恒等分解 (d1_blip / d1_run / 全体池): n / E_net / E_bench / E_excess
   / 胜率 (净与超额两口径 — 超额胜率 = 跑赢市场率)。
2. d1_blip vs d1_run 决定性对比: 净/超额两空间并排 (grouped_delta 单一实现,
   per-call seeded RNG)。
3. 基准完整性: 自检 mismatch 数 / 基准对名单数 min/median / 覆盖率。
4. 强度分桶 × 恒等分解 (R174): strength_bucket 单一实现分桶 (左闭右开
   0.50/0.60/0.70), 桶表与 regime 表同算术; ≥0.70 vs <0.50 阈值选择对比
   净/超额两空间 — 回答强度阈值的优势是 selection 还是 beta (与 regime
   blip 纯 beta 形成互补双轴)。

纯诊断 (宪法 #2: 只披露不判定; 任何 gate 行为变化 = owner 决策 + 新证据世
代)。基准含候选自身 (~1/5400 权重, 可忽略); 等权 buy-hold 基准不等于市值
加权指数, 口径在报告披露; T+10 窗口跨信号日重叠是 BTST 合约固有属性, 群组
间窗口构成差异由分解如实呈现, 不在本工具消除。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

import pandas as pd

from scripts._btst_court_common import RAW_DIR
from scripts.regime_blocked_run_conditioning import (
    REPORT_DIR_DEFAULT,
    _fmt,
)
from scripts.regime_blocked_run_conditioning import run_groups
from scripts.regime_proximity_conditioning import (
    BLOCKED_REGIMES,
    COURT_TABLE_DEFAULT,
    PRIMARY_HORIZON,
    REGIME_HISTORY_DEFAULT,
    grouped_delta,
    label_consistency,
    load_regime_history,
)
from scripts.winrate_payoff_decomposition import (
    ROUNDTRIP_COST,
    court_binding,
    court_window_from_events,
    production_aligned,
    win_loss_stats,
)
from src.screening.offensive.threshold_trigger import (
    ALL_STRENGTH_BUCKETS,
    strength_bucket,
)

REPORT_STEM = "regime_excess_return_decomposition"
DECOMPOSITION_HORIZONS = (PRIMARY_HORIZON, 8)
GROUP_ORDER = ("d1_blip", "d1_run", "all")
GROUP_LABELS = {
    "d1_blip": "d1_blip (单日闪断后)",
    "d1_run": "d1_run (连续危机后)",
    "all": "全体池",
}
MIN_PAIR_NAMES = 100  # 基准对有效名单数下界 — 低于此 = 数据损坏非市场真相
_SELFCHECK_TOL = 1e-9
_IDENTITY_TOL = 1e-12


class ExcessDecompositionError(SystemExit):
    """输入缺失/畸形/窗口自检失败 — typed fail-closed, 绝不产报告冒充成功."""


def _fail(code: str) -> ExcessDecompositionError:
    return ExcessDecompositionError(f"excess_decomposition_{code}")


def t_session(
    cal_s: list[str], cal_idx: dict[str, int], sig: str, offset: int
) -> str:
    """信号日后第 offset 个会话 (offset=1 → T+1); 越界/未知信号日 typed 拒绝."""
    i = cal_idx.get(sig)
    if i is None:
        raise _fail(f"signal_session_not_in_calendar:{sig}")
    j = i + offset
    if j >= len(cal_s) or j <= i:
        raise _fail(f"benchmark_window_beyond_calendar:{sig}:{offset}")
    return cal_s[j]


def pair_benchmark(
    opens: dict[str, pd.Series], entry: str, exit_s: str
) -> tuple[float, int]:
    """等权全市场 open→open 收益 (entry/exit 两会话均有有效开盘的全体名单).

    会话缺失 (raw daily 文件缺) = 数据撕裂, typed fail-closed; 有效名单
    < MIN_PAIR_NAMES = 快照损坏而非市场真相, 同拒。
    """
    o_in = opens.get(entry)
    o_out = opens.get(exit_s)
    if o_in is None or o_out is None or o_in.empty or o_out.empty:
        raise _fail(f"benchmark_source_session_missing:{entry}:{exit_s}")
    common = o_in.index.intersection(o_out.index)
    rets = o_out.loc[common] / o_in.loc[common] - 1
    rets = rets.replace([float("inf"), float("-inf")], pd.NA).dropna()
    if len(rets) < MIN_PAIR_NAMES:
        raise _fail(f"benchmark_pair_degenerate:{entry}:{exit_s}:{len(rets)}")
    return float(rets.mean()), int(len(rets))


def horizon_rows_with_benchmark(
    u: pd.DataFrame,
    horizon: int,
    prox: dict[str, str],
    opens: dict[str, pd.Series],
    cal_s: list[str],
) -> tuple[pd.DataFrame, dict[str, object]]:
    """单 horizon 成熟行 + 基准/超额列 + 窗口逐位自检 (任何不一致 typed 拒绝).

    行集 = gross 非空且 offset 非空 (gross 在而 offset 缺 = 事件表契约破坏,
    拒绝)。bench 按 (entry, exit) 对缓存 — 同日候选共享同窗基准。自检: 逐
    候选从 opens 重算 gross 与事件表列比对 (_SELFCHECK_TOL); 候选开盘缺失
    而 gross 在场 = raw 源与事件表撕裂, 同拒。
    """
    gross_col = f"gross_ret_t{horizon}"
    off_col = f"exit_session_t{horizon}"
    if gross_col not in u.columns or off_col not in u.columns:
        raise _fail(f"court_columns_missing:{gross_col}/{off_col}")
    if "trigger_strength" not in u.columns:
        raise _fail("strength_column_missing")
    sub = u[u[gross_col].notna()].copy()
    bad_offset = sub[sub[off_col].isna()]
    if len(bad_offset):
        raise _fail(f"exit_offset_missing_with_gross_present:{len(bad_offset)}")
    cal_idx = {d: i for i, d in enumerate(cal_s)}
    cache: dict[tuple[str, str], tuple[float, int]] = {}
    rows: list[dict[str, object]] = []
    checked = 0
    for _, r in sub.iterrows():
        sig = str(r["signal_date"])
        offset = int(r[off_col])
        entry = t_session(cal_s, cal_idx, sig, 1)
        exit_s = t_session(cal_s, cal_idx, sig, offset)
        key = (entry, exit_s)
        if key not in cache:
            cache[key] = pair_benchmark(opens, entry, exit_s)
        bench = cache[key][0]
        ts = r["ts_code"]
        o_in = opens[entry]
        o_out = opens[exit_s]
        if ts not in o_in.index or ts not in o_out.index:
            raise _fail(f"benchmark_selfcheck_open_missing:{ts}:{sig}")
        recomputed = float(o_out[ts]) / float(o_in[ts]) - 1
        gross = float(r[gross_col])
        if abs(recomputed - gross) > _SELFCHECK_TOL:
            raise _fail(f"benchmark_selfcheck_mismatch:{ts}:{sig}")
        checked += 1
        net = gross - ROUNDTRIP_COST
        raw_strength = r["trigger_strength"]
        rows.append(
            {
                "net": net,
                "bench": bench,
                "excess": net - bench,
                "signal_date": sig,
                "group": prox.get(sig, "unknown"),
                "strength": (
                    None if pd.isna(raw_strength) else float(raw_strength)
                ),
            }
        )
    pair_sizes = [n for _, n in cache.values()]
    integrity: dict[str, object] = {
        "selfcheck_checked": checked,
        "selfcheck_mismatch": 0,
        "n_pairs": len(cache),
        "pair_names_min": min(pair_sizes) if pair_sizes else None,
        "pair_names_median": (
            float(pd.Series(pair_sizes).median()) if pair_sizes else None
        ),
    }
    return pd.DataFrame(rows), integrity


def group_decomposition(
    df: pd.DataFrame,
    group_order: tuple[str, ...] = GROUP_ORDER,
) -> dict[str, object]:
    """分组恒等分解: E_net = E_bench + E_excess (逐组 _IDENTITY_TOL 内显式核对).

    'all' = 全体池对照行 (仅 regime 轴有); 桶轴 (R174) 传 ALL_STRENGTH_BUCKETS
    复用同算术。胜率给净/超额两口径 (超额胜率 = 跑赢市场率)。
    """
    out: dict[str, object] = {}
    for group in group_order:
        cell = df if group == "all" else df[df["group"] == group]
        days = cell["signal_date"].astype(str).tolist()
        net_st = win_loss_stats(cell["net"].astype(float).tolist(), days)
        ex_st = win_loss_stats(cell["excess"].astype(float).tolist(), days)
        bench_mean = (
            float(cell["bench"].astype(float).mean()) if len(cell) else None
        )
        entry: dict[str, object] = {
            "n": net_st["n"],
            "e_net": net_st["expectancy"],
            "e_bench": bench_mean,
            "e_excess": ex_st["expectancy"],
            "winrate_net": net_st["winrate"],
            "winrate_excess": ex_st["winrate"],
            "n_days": len(set(days)),
        }
        if (
            net_st["expectancy"] is not None
            and bench_mean is not None
            and ex_st["expectancy"] is not None
        ):
            entry["identity_residual"] = abs(
                net_st["expectancy"] - (bench_mean + ex_st["expectancy"])
            )
        out[group] = entry
    return out


def two_space_contrast(
    df: pd.DataFrame,
    hi_group: str,
    lo_group: str,
    *,
    n_hi_key: str,
    n_lo_key: str,
) -> dict[str, object]:
    """任意 hi/lo 两组的净/超额两空间并排对比 (grouped_delta 单一实现).

    正值 = hi 侧优势。任一侧 n<MIN_CELL_N → 区间 None (R153 纪律, 门槛把关
    后才进 delta CI)。列视图只取 (值, 信号日, 组) 三列再统一改名 — 原地
    rename 会产生重复列名 (net 与 excess 改名后同名), 后续取列静默变形。
    """
    out: dict[str, object] = {}
    for space, col in (("raw", "net"), ("excess", "excess")):
        view = df[[col, "signal_date", "group"]].rename(columns={col: "net"})
        out[space] = grouped_delta(
            view, hi_group, lo_group, n_hi_key=n_hi_key, n_lo_key=n_lo_key
        )
    return out


def contrast_spaces(df: pd.DataFrame) -> dict[str, object]:
    """d1_blip vs d1_run 决定性对比 (two_space_contrast 参数化委托)."""
    return two_space_contrast(
        df, "d1_blip", "d1_run", n_hi_key="n_blip", n_lo_key="n_run"
    )


def strength_decomposition(rows: pd.DataFrame) -> dict[str, object]:
    """强度分桶 × 恒等分解 (R174): 桶归属走 strength_bucket 单一实现
    (左闭右开 0.50/0.60/0.70, NaN/None → unknown), 桶表复用 group_decomposition
    同算术; ≥0.70 vs <0.50 阈值选择对比两空间 (正值 = 强度优势)."""
    view = rows.copy()
    view["group"] = view["strength"].map(strength_bucket)
    return {
        "buckets": group_decomposition(view, ALL_STRENGTH_BUCKETS),
        "threshold_contrast": two_space_contrast(
            view, "≥0.70", "<0.50",
            n_hi_key="n_hi_strength", n_lo_key="n_lo_strength",
        ),
    }


def analyze(
    ev: pd.DataFrame,
    history_path: Path,
    opens: dict[str, pd.Series],
    cal_s: list[str],
) -> dict[str, object]:
    """装配完整 payload (纯函数: 事件表 + history 路径 + opens + 日历 → dict)."""
    sessions, labels = load_regime_history(history_path)
    u = production_aligned(ev)
    if len(u) == 0:
        raise _fail("empty_production_aligned_universe")
    prox = run_groups(pd.unique(u["signal_date"].astype(str)), sessions, labels)
    by_h: dict[str, object] = {}
    integrity: dict[str, object] | None = None
    for h in DECOMPOSITION_HORIZONS:
        rows, integ = horizon_rows_with_benchmark(u, h, prox, opens, cal_s)
        by_h[f"t{h}"] = {
            "groups": group_decomposition(rows),
            "contrast": contrast_spaces(rows),
            "strength": strength_decomposition(rows),
        }
        if integrity is None:
            integrity = integ
    return {
        "schema_version": 1,
        "headline": {
            "question": "工作线证据的机制归属: 净收益优势多少是市场 beta, 多少是 selection",
            "identity": "net = bench + excess (逐组恒等分解, 无残差)",
        },
        "axis_definition": {
            "benchmark": (
                "等权全市场 open→open (raw daily 快照全体名单), 与 court 执行"
                "口径同窗: T+1 开盘入场 → exit_session_t{k} 偏移量开盘退出 "
                "(顺延语义与构建器一致)"
            ),
            "blocked_regimes": list(BLOCKED_REGIMES),
            "benchmark_notes": [
                "基准含候选自身 (~1/5400 权重, 可忽略)",
                "等权 buy-hold 基准 ≠ 市值加权指数; 口径差异如实披露",
                "T+10 窗口跨信号日重叠是 BTST 合约固有属性, 群组间窗口构成差异由分解呈现",
            ],
        },
        "court_window": court_window_from_events(ev),
        "aligned_n": int(len(u)),
        "rows_with_benchmark": (
            integrity["selfcheck_checked"] if integrity else 0
        ),
        "benchmark_integrity": integrity or {},
        "decomposition": by_h,
        "label_consistency": label_consistency(ev, labels),
    }


def render_md(payload: dict[str, object], date_str: str) -> str:
    """payload → MD 报告 (渲染存活: 缺键/None → '—', falsy-zero 显示)."""
    decomposition = payload.get("decomposition") or {}
    integrity = payload.get("benchmark_integrity") or {}
    lines: list[str] = []
    lines.append(f"# 超额收益 beta/selection 恒等分解 ({date_str})")
    lines.append("")
    lines.append(
        "纯诊断 (宪法 #2: 只披露不判定)。净收益恒等分解 net = bench + excess "
        "(等权全市场 open→open 基准, 与 court 执行口径同窗)。任何 gate 行为"
        "变化 = owner 决策 + 新证据世代。"
    )
    lines.append("")
    window = payload.get("court_window") or {}
    lines.append(
        f"court 窗口: {window.get('start')}..{window.get('end')}"
        f" · 生产对齐 n={payload.get('aligned_n')}"
        f" · 带基准行 {payload.get('rows_with_benchmark', '—')}"
    )
    lines.append("")
    lines.append(
        f"基准完整性: 自检 {integrity.get('selfcheck_checked', '—')} 行 "
        f"mismatch {integrity.get('selfcheck_mismatch', '—')} (非零即 typed "
        f"拒绝不产报告) · 基准对 {integrity.get('n_pairs', '—')} 个 · 名单数 "
        f"min {integrity.get('pair_names_min', '—')} / median "
        f"{integrity.get('pair_names_median', '—')}"
    )
    lines.append("")
    for h in ("t10", "t8"):
        cell = decomposition.get(h) or {}
        groups = cell.get("groups") or {}
        lines.append(f"## 分组恒等分解 ({h})")
        lines.append("")
        lines.append(
            "| 组 | n | 日数 | E_net | E_bench | E_excess | 胜率(净) | 胜率(超额) | 恒等残差 |"
        )
        lines.append("|---|---|---|---|---|---|---|---|---|")
        for group in GROUP_ORDER:
            g = groups.get(group) or {}
            resid = g.get("identity_residual")
            resid_s = (
                "—"
                if resid is None
                else ("OK" if resid <= _IDENTITY_TOL else f"{resid:.2e}")
            )
            lines.append(
                f"| {GROUP_LABELS[group]} | {g.get('n', '—')} "
                f"| {g.get('n_days', '—')} "
                f"| {_fmt(g.get('e_net'))} | {_fmt(g.get('e_bench'))} "
                f"| {_fmt(g.get('e_excess'))} "
                f"| {_fmt(g.get('winrate_net'))} "
                f"| {_fmt(g.get('winrate_excess'))} | {resid_s} |"
            )
        strength = cell.get("strength") or {}
        buckets = strength.get("buckets") or {}
        lines.append("### 强度分桶 × 恒等分解 (桶归属 = strength_bucket 单一实现)")
        lines.append("")
        lines.append("| 桶 | n | E_net | E_bench | E_excess | 胜率(净) | 胜率(超额) | 恒等残差 |")
        lines.append("|---|---|---|---|---|---|---|---|")
        for bucket in ALL_STRENGTH_BUCKETS:
            g = buckets.get(bucket) or {}
            resid = g.get("identity_residual")
            resid_s = (
                "—"
                if resid is None
                else ("OK" if resid <= _IDENTITY_TOL else f"{resid:.2e}")
            )
            lines.append(
                f"| {bucket} | {g.get('n', '—')} "
                f"| {_fmt(g.get('e_net'))} | {_fmt(g.get('e_bench'))} "
                f"| {_fmt(g.get('e_excess'))} "
                f"| {_fmt(g.get('winrate_net'))} "
                f"| {_fmt(g.get('winrate_excess'))} | {resid_s} |"
            )
        tc = strength.get("threshold_contrast") or {}
        tc_raw = tc.get("raw") or {}
        tc_ex = tc.get("excess") or {}
        lines.append("")
        lines.append(
            f"阈值选择对比 ≥0.70 vs <0.50 ({h}): 净空间 Δ "
            f"{_fmt(tc_raw.get('ci_low'))}..{_fmt(tc_raw.get('ci_high'))} "
            f"(n hi={tc_raw.get('n_hi_strength', '—')}/lo="
            f"{tc_raw.get('n_lo_strength', '—')}) · 超额空间 Δ "
            f"{_fmt(tc_ex.get('ci_low'))}..{_fmt(tc_ex.get('ci_high'))} "
            f"(正值 = 强度优势; 超额空间存活 = selection 证据, 跨零 = 降格)"
        )
        lines.append("")
        contrast = cell.get("contrast") or {}
        raw = contrast.get("raw") or {}
        ex = contrast.get("excess") or {}
        lines.append("")
        lines.append(
            f"### d1_blip vs d1_run 对比 ({h}): 净空间 Δ "
            f"{_fmt(raw.get('ci_low'))}..{_fmt(raw.get('ci_high'))} "
            f"(n blip={raw.get('n_blip', '—')}/run={raw.get('n_run', '—')}) · "
            f"超额空间 Δ {_fmt(ex.get('ci_low'))}..{_fmt(ex.get('ci_high'))} "
            f"(净空间越零而超额跨零 = gate 证据降格为择时证据; 两空间同越零 = "
            f"selection 证据)"
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
        "- 本报告是诊断证据, 不是参数变更提案; beta/selection 归属不构成任何 "
        "自动 gate 行为 (宪法 #2)。\n"
        "- 等权 buy-hold 基准 ≠ 指数收益; 窗口重叠是合约固有属性 — 判读属 "
        "owner 门。\n"
        "- 复现: `uv run python scripts/regime_excess_return_decomposition.py` "
        "(零 RNG 主路径; 对比 CI 为 per-call seeded, 同输入逐字节可复现)。"
    )
    return "\n".join(lines) + "\n"


def load_daily_opens(raw_dir: Path) -> dict[str, pd.Series]:
    """raw daily 快照目录 → {session: ts_code→open Series} (研究命名空间只读)."""
    opens: dict[str, pd.Series] = {}
    for f in sorted(Path(raw_dir).glob("daily_*.csv")):
        day = f.stem.removeprefix("daily_")
        df = pd.read_csv(f, usecols=["ts_code", "open"])
        opens[day] = df.set_index("ts_code")["open"]
    return opens


def load_calendar_sessions(path: Path) -> list[str]:
    """trade_calendar.json → 升序会话列表 (与 court 构建器同源日历真相)."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    sessions = sorted({str(d).replace("-", "")[:8] for d in payload})
    if len(sessions) < 30:
        raise _fail(f"calendar_coverage_too_short:{len(sessions)}")
    return sessions


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--court-table", type=Path, default=COURT_TABLE_DEFAULT)
    parser.add_argument("--regime-history", type=Path, default=REGIME_HISTORY_DEFAULT)
    parser.add_argument("--raw-dir", type=Path, default=RAW_DIR / "daily")
    parser.add_argument(
        "--trade-calendar",
        type=Path,
        default=Path("data/reports/trade_calendar.json"),
    )
    parser.add_argument("--report-dir", type=Path, default=REPORT_DIR_DEFAULT)
    args = parser.parse_args(argv)

    ev = pd.read_csv(args.court_table)
    opens = load_daily_opens(args.raw_dir)
    cal_s = load_calendar_sessions(args.trade_calendar)
    payload = analyze(ev, args.regime_history, opens, cal_s)
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
    t10 = (payload.get("decomposition") or {}).get("t10") or {}
    contrast = (t10.get("contrast") or {}).get("excess") or {}
    print(json.dumps({
        "report": str(md_path),
        "binding": binding,
        "aligned_n": payload.get("aligned_n"),
        "rows_with_benchmark": payload.get("rows_with_benchmark"),
        "excess_delta_ci_t10": [
            contrast.get("ci_low"), contrast.get("ci_high")
        ],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
