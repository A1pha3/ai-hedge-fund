#!/usr/bin/env python3
"""组合路径 gate 反事实模拟器 (纯诊断, 宪法 #2: 只披露不判定).

回答的问题: 把已成熟的单票/日条件化证据 (regime d1_run 罚分、crisis gate)
换算成宪法 #2 的经济目标口径 — 组合单位净值长期对数增长路径 — 三种 gate
配置下的路径差是多少。这是 owner 待决杠杆 (F: d1_run→gate) 此前缺失的
组合路径证据; 现有诊断工具全是单票 E/胜率/归因口径, 无路径级换算。

三种配置 (预注册, 只对比披露):
  no_gate                    全部生产可比候选都交易 (含 gate 阻断日) — 参照系,
                             量化现有 regime gate 本身对路径的贡献
  baseline                   production_aligned 语义 (阻断日不建仓) = 当前生产
  baseline_plus_d1run_block  baseline 再排除 d1_run 信号日 (距阻断日 1 会话且
                             前导连跑≥2) 的 cohort — 杠杆 F 候选

路径模型 (固定合约, 如实披露近似):
  - 生产对齐 sizing: 单票 8% / 组合并发总敞口 60% 上限 (v2 生产语义,
    setup_output_log/*.capacity.jsonl 同口径), 同日候选按 trigger_strength
    降序 (tie-break ts_code) 依次尝试占用, 装不下即跳过 (生产 per-ticket
    二元语义; cap 是绑定约束 — R15 结论; 60% cap 恒保证 cash≥40%>8%)。
  - T0 收盘决策即承诺资本 (从 cash 扣除), T+1 开盘入场 (入场价 = raw daily
    bars 的 T+1 open, 与 court build 同源), T+10 开盘退出 (出场价/顺延会话 =
    事件表 exit_open_t10/exit_session_t10 单一事实源, 停牌顺延语义由 build
    层保证), 持仓期逐会话以 close 标记 (缺 bar 顺延最后已知 close)。
  - 净成本 = 毛收益 − ROUNDTRIP_COST 0.65% (net_returns 单一实现同式),
    退出时结算进 cash。
  - 一致性锚: bars 重演毛收益 vs 事件表 gross_ret_t10 逐事件核对, 失配计数
    如实披露 (收益结算仍以事件表为准 — 单一事实源; 测试钉死合成世界零失配)。
  - 归因: 每个 cohort 的现金贡献 w×net_ret 按信号日的 (距离×连跑) 组归并
    (run_geometry 单一实现), 是现金空间归因不是逐会话对数精确分解 (如实)。

纪律: 本工具是诊断证据, 不是参数变更提案; 任何 gate/参数变化 = 新证据世代
owner 决策 (宪法 #2)。幸存者偏差与 court 宇宙边界与 winrate 工具同源。

复现: uv run python scripts/portfolio_path_gate_counterfactual.py
(确定性: 无随机数, 同输入逐字节可复现)
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import date
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
_SCRIPTS = str(REPO_ROOT / "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

from scripts.regime_blocked_run_conditioning import (  # noqa: E402
    RUN_GROUPS,
    blocked_run_group,
)
from scripts.regime_proximity_conditioning import (  # noqa: E402
    COURT_TABLE_DEFAULT,
    REGIME_HISTORY_DEFAULT,
    REPORT_DIR_DEFAULT,
    load_regime_history,
)
from scripts.review_btst_prior_court import (  # noqa: E402
    HORIZON_COL,
    PRODUCTION_EXCLUDE_COLS,
)
from scripts.winrate_payoff_decomposition import (  # noqa: E402
    ROUNDTRIP_COST,
    court_window_from_events,
    production_aligned,
)

REPORT_STEM = "portfolio_path_gate_counterfactual"

# 生产对齐 sizing 合约 (字面量; 与 v2 生产 capacity 日志同口径):
# 单票 8% / 组合并发总敞口 60% — cap 是绑定约束 (R15), 现金恒充足。
TICKER_LIMIT_WEIGHT = 0.08
PORTFOLIO_GROSS_CAP = 0.60
# 数值比较容差 (占比加总用; 价格核对用更紧的 1e-9)。
_WEIGHT_EPS = 1e-9
_ANCHOR_EPS = 1e-9

CONFIGS: tuple[str, ...] = (
    "no_gate",
    "baseline",
    "baseline_plus_d1run_block",
)

CONFIG_LABELS: dict[str, str] = {
    "no_gate": "no_gate (全部生产可比候选, 含 gate 阻断日 — 参照系)",
    "baseline": "baseline (gate 阻断日 crisis/risk_off 不建仓 = 当前生产语义)",
    "baseline_plus_d1run_block": "baseline + d1_run 信号日阻断 (杠杆 F 候选)",
}

BTST_RAW_DAILY_DEFAULT = Path("data/research/btst_court/raw/daily")


class PortfolioPathCounterfactualError(SystemExit):
    """输入缺失/畸形 — typed fail-closed, 绝不产空报告冒充成功."""


# ---------------------------------------------------------------------------
# 宇宙构造 (baseline 侧 = production_aligned 单一实现; no_gate = 门 clause 分离)
# ---------------------------------------------------------------------------


def pre_gate_production_universe(ev: "pd.DataFrame") -> "pd.DataFrame":
    """门 clause 分离的生产可比宇宙 (candidate_universe 的无门镜像).

    candidate_universe = fillable & !gate_blocked & ret 非空 (review 层单一
    实现, 不 fork); 本函数只做同一组子句去掉 !gate_blocked 的版本, 生产排除
    列与 winrate.production_aligned 完全一致。identity 由
    assert_baseline_identity 在运行时钉死: pre_gate ∩ !gate_blocked ≡
    production_aligned, 失配 fail-closed。
    """
    required = ["fillable", HORIZON_COL, *PRODUCTION_EXCLUDE_COLS, "price_ge_3"]
    missing = [c for c in required if c not in ev.columns]
    if missing:
        raise PortfolioPathCounterfactualError(
            f"court 事件表缺少生产过滤列: {sorted(missing)}"
        )
    mask = (ev["fillable"] == True) & ev[HORIZON_COL].notna()  # noqa: E712
    universe = ev.loc[mask]
    excluded_any = universe[list(PRODUCTION_EXCLUDE_COLS)].any(axis=1) | (
        universe["price_ge_3"] != True  # noqa: E712
    )
    return universe.loc[~excluded_any].copy()


def assert_baseline_identity(
    ev: "pd.DataFrame", baseline: "pd.DataFrame"
) -> None:
    """baseline 宇宙 ≡ production_aligned 单一实现 (索引集合恒等, 失配即炸)."""
    reference = production_aligned(ev)
    if set(baseline.index) != set(reference.index):
        raise PortfolioPathCounterfactualError(
            "baseline_universe_identity_mismatch: "
            f"{len(baseline)} vs production_aligned {len(reference)}"
        )


def config_universe(
    ev: "pd.DataFrame",
    config: str,
    sessions: list[str],
    labels: dict[str, str],
) -> "pd.DataFrame":
    """配置 → 该配置下允许建仓的候选宇宙 (纯函数)."""
    pre = pre_gate_production_universe(ev)
    if config == "no_gate":
        return pre
    baseline = pre.loc[pre["gate_blocked"] != True]  # noqa: E712
    if config == "baseline":
        return baseline
    if config == "baseline_plus_d1run_block":
        keep = baseline["signal_date"].astype(str).map(
            lambda d: blocked_run_group(d, sessions, labels) != "d1_run"
        )
        return baseline.loc[keep]
    raise PortfolioPathCounterfactualError(f"unknown_config: {config}")


# ---------------------------------------------------------------------------
# bars 装载 (仅作持仓期 close 标记与入场价重演; 出场以事件表为单一事实源)
# ---------------------------------------------------------------------------


def load_daily_marks(
    raw_dir: Path,
    needed_sessions: list[str],
    tickers: set[str],
) -> dict[tuple[str, str], tuple[float | None, float | None]]:
    """(session, ts_code) → (open, close); 缺文件/缺行/NaN 原样缺失。

    逐会话读 daily_YYYYMMDD.csv 后立即按 tickers 过滤提炼, 不保留整帧。
    """
    marks: dict[tuple[str, str], tuple[float | None, float | None]] = {}
    for session in needed_sessions:
        path = raw_dir / f"daily_{session}.csv"
        if not path.exists():
            continue
        frame = pd.read_csv(path)
        if "ts_code" not in frame.columns:
            raise PortfolioPathCounterfactualError(
                f"daily_csv_missing_ts_code: {path}"
            )
        sub = frame[frame["ts_code"].isin(tickers)]
        for _, row in sub.iterrows():
            def _num(value: object) -> float | None:
                if value is None or (isinstance(value, float) and value != value):
                    return None
                return float(value)  # type: ignore[arg-type]

            marks[(session, str(row["ts_code"]))] = (
                _num(row.get("open")),
                _num(row.get("close")),
            )
    return marks


# ---------------------------------------------------------------------------
# 事件 → 持仓生命周期展开 (纯函数)
# ---------------------------------------------------------------------------


def _strength_sort_key(row: "pd.Series") -> tuple[float, str]:
    s = row["trigger_strength"]
    if s is None or (isinstance(s, float) and math.isnan(s)):
        s = -math.inf
    return (-float(s), str(row["ts_code"]))


def build_cohorts(
    universe: "pd.DataFrame",
    sessions: list[str],
    bars: dict[tuple[str, str], tuple[float | None, float | None]],
) -> tuple[dict[str, list[dict[str, object]]], dict[str, int]]:
    """宇宙 → {signal_date: [cohort…]} (选择确定性: strength 降序, tie ts_code)。

    cohort 字段: signal_date, ts_code, entry_session, exit_session,
    entry_open, closes_by_offset, gross_ret_t10, anchor_mismatch。

    exit_session_t10 是 build 层 fixed_open 的 1-based offset (停牌顺延后
    的实际出场 offset), 出场会话 = 信号日后第 exit_session_t10 个会话。
    入场 = 信号日后第 1 个会话的 open (build 同源; fillable 已保证非空)。
    """
    index = {s: i for i, s in enumerate(sessions)}
    cohorts: dict[str, list[dict[str, object]]] = {}
    stats = {"missing_entry_bar": 0, "missing_exit_offset": 0}
    for signal_date, group in universe.groupby("signal_date", sort=True):
        day = str(signal_date)
        if day not in index:
            # 不在 regime 会话序的信号日: gate 语义与出场会话都无法评估,
            # 如实跳过并计数 (生产宇宙中应为 0; 非零即数据边界显形)。
            stats["missing_exit_offset"] += int(len(group))
            continue
        rows = sorted(
            [row for _, row in group.iterrows()], key=_strength_sort_key
        )
        fwd = sessions[index[day] + 1 :]
        for row in rows:
            ts_code = str(row["ts_code"])
            if not fwd:
                stats["missing_exit_offset"] += 1
                continue
            entry_session = fwd[0]
            entry_open, _ = bars.get((entry_session, ts_code), (None, None))
            if entry_open is None or entry_open <= 0:
                stats["missing_entry_bar"] += 1
                continue
            exit_off = row.get("exit_session_t10")
            if exit_off is None or pd.isna(exit_off) or int(exit_off) < 1:
                stats["missing_exit_offset"] += 1
                continue
            exit_off = int(exit_off)
            if exit_off > len(fwd):
                stats["missing_exit_offset"] += 1
                continue
            exit_session = fwd[exit_off - 1]
            closes: dict[int, float] = {}
            fresh: set[int] = set()
            last: float | None = None
            for off in range(1, exit_off + 1):
                _, close = bars.get((fwd[off - 1], ts_code), (None, None))
                if close is not None and close > 0:
                    last = close
                    fresh.add(off)
                if last is not None:
                    closes[off] = last
            table_gross = row[HORIZON_COL]
            table_gross = None if pd.isna(table_gross) else float(table_gross)
            exit_open = bars.get((exit_session, ts_code), (None, None))[0]
            path_gross = (exit_open / entry_open - 1) if exit_open else None
            cohorts.setdefault(day, []).append(
                {
                    "signal_date": day,
                    "ts_code": ts_code,
                    "strength": row["trigger_strength"],
                    "entry_session": entry_session,
                    "exit_session": exit_session,
                    "entry_open": entry_open,
                    "closes_by_offset": closes,
                    "fresh_offsets": fresh,
                    "gross_ret_t10": table_gross,
                    "path_gross": path_gross,
                    "anchor_mismatch": (
                        path_gross is None
                        or table_gross is None
                        or abs(path_gross - table_gross) > _ANCHOR_EPS
                    ),
                }
            )
    return cohorts, stats


# ---------------------------------------------------------------------------
# 路径模拟 (资本瀑布: 并发 60% cap, 单票 8%, T0 承诺 → T+1 入场 → T+10 退出)
# ---------------------------------------------------------------------------


def simulate_path(
    cohorts: dict[str, list[dict[str, object]]],
    sessions: list[str],
    labels: dict[str, str],
) -> dict[str, object]:
    index = {s: i for i, s in enumerate(sessions)}
    active_sessions = sorted(
        (d for d in cohorts if d in index), key=lambda d: index[d]
    )
    if not active_sessions:
        raise PortfolioPathCounterfactualError("no_tradeable_signal_session")
    for d in active_sessions:
        for c in cohorts[d]:
            if c["exit_session"] not in index:
                raise PortfolioPathCounterfactualError(
                    f"exit_session_beyond_grid: {d} {c['ts_code']}"
                )

    cash = 1.0
    pending: list[dict[str, object]] = []  # T0 已承诺, 待 T+1 入场
    holding: list[dict[str, object]] = []  # 已入场, 持有至 exit_session
    nav_path: list[tuple[str, float]] = []
    deployed_events = 0
    skipped_by_cap = 0
    cap_binding_days = 0
    anchor_mismatch = 0
    mismatch_mags: list[float] = []
    carried_marks = 0
    contributions: list[tuple[str, str, float]] = []
    weight = TICKER_LIMIT_WEIGHT

    last_idx = max(
        max(index[c["exit_session"]] for d in active_sessions for c in cohorts[d]),
        max(index[d] for d in active_sessions),
    )
    sim_grid = sessions[: last_idx + 1]

    for session in sim_grid:
        # 1) 出场 (T+10 开盘卖出, 净 proceeds 入 cash)
        still: list[dict[str, object]] = []
        for pos in holding:
            if pos["exit_session"] == session:
                w = float(pos["weight"])
                net = float(pos["gross_ret_t10"]) - ROUNDTRIP_COST
                cash += w * (1.0 + net)
                contributions.append(
                    (str(pos["signal_date"]), str(pos["ts_code"]), w * net)
                )
                if pos["anchor_mismatch"]:
                    anchor_mismatch += 1
                    path_gross = pos["path_gross"]
                    if path_gross is not None and pos["gross_ret_t10"] is not None:
                        mismatch_mags.append(abs(float(path_gross) - float(pos["gross_ret_t10"])))
            else:
                still.append(pos)
        holding = still

        # 2) T0 决策承诺 (先查 cap 再扣 cash; per-ticket 二元语义)
        day_skipped = 0
        for cohort in cohorts.get(session, []):
            deployed = sum(float(p["weight"]) for p in pending) + sum(
                float(p["weight"]) for p in holding
            )
            if deployed + weight > PORTFOLIO_GROSS_CAP + _WEIGHT_EPS:
                skipped_by_cap += 1
                day_skipped += 1
                continue
            if cash + _WEIGHT_EPS < weight:
                # 60% cap 恒保证 cash≥40%, 不可达; 防御断言保持诚实。
                raise PortfolioPathCounterfactualError(
                    "cash_below_weight_with_cap_headroom"
                )
            pending.append({**cohort, "weight": weight})
            cash -= weight
            deployed_events += 1
        if day_skipped:
            cap_binding_days += 1

        # 3) 入场 (T+1 开盘): pending → holding
        entering = [p for p in pending if p["entry_session"] != session]
        for pos in pending:
            if pos["entry_session"] == session:
                holding.append(pos)
        pending = entering

        # 4) 收盘标记: NAV = cash + pending(成本) + holding(w × close/entry)
        nav = cash + sum(float(p["weight"]) for p in pending)
        for pos in holding:
            off = index[session] - index[str(pos["signal_date"])]
            closes = pos["closes_by_offset"]
            if isinstance(closes, dict) and off in closes:
                if off not in pos["fresh_offsets"]:
                    carried_marks += 1  # 陈旧 close (顺延标记), 如实计数
                nav += float(pos["weight"]) * (
                    closes[off] / float(pos["entry_open"])
                )
            else:
                # 入场日 close 缺失 (或 offset 无任何已知 close) → 按成本计。
                nav += float(pos["weight"])
        nav_path.append((session, nav))

    final_nav = nav_path[-1][1]
    log_growth = math.log(final_nav)
    n = len(sim_grid)
    peak = -math.inf
    mdd = 0.0
    for _, v in nav_path:
        peak = max(peak, v)
        if peak > 0:
            mdd = max(mdd, (peak - v) / peak)

    by_group: dict[str, dict[str, float]] = {}
    for signal_date, _ts, contribution in contributions:
        g = blocked_run_group(signal_date, sessions, labels)
        cell = by_group.setdefault(g, {"events": 0.0, "contribution": 0.0})
        cell["events"] += 1
        cell["contribution"] += contribution

    return {
        "final_nav": final_nav,
        "log_growth": log_growth,
        "ann_log_growth": log_growth * 252.0 / n,
        "max_drawdown": mdd,
        "n_sessions": n,
        "deployed_events": deployed_events,
        "skipped_by_cap": skipped_by_cap,
        "cap_binding_days": cap_binding_days,
        "anchor_mismatch": anchor_mismatch,
        "anchor_mismatch_max_abs": max(mismatch_mags) if mismatch_mags else None,
        "anchor_mismatch_median_abs": (
            sorted(mismatch_mags)[len(mismatch_mags) // 2] if mismatch_mags else None
        ),
        "carried_marks": carried_marks,
        "open_at_end": len(holding) + len(pending),
        "group_contribution": by_group,
    }


def _simulate_config(
    ev: "pd.DataFrame",
    config: str,
    sessions: list[str],
    labels: dict[str, str],
    bars: dict[tuple[str, str], tuple[float | None, float | None]],
) -> dict[str, object]:
    universe = config_universe(ev, config, sessions, labels)
    cohorts, stats = build_cohorts(universe, sessions, bars)
    result = simulate_path(cohorts, sessions, labels)
    result["config"] = config
    result["universe_n"] = int(len(universe))
    result["cohort_days"] = len(cohorts)
    result["build_stats"] = stats
    return result


# ---------------------------------------------------------------------------
# payload 装配 + 渲染
# ---------------------------------------------------------------------------


def analyze(
    ev: "pd.DataFrame",
    history_path: Path,
    raw_daily_dir: Path = BTST_RAW_DAILY_DEFAULT,
) -> dict[str, object]:
    """装配完整 payload (纯函数: 事件表 + regime history + bars 目录 → dict)."""
    sessions, labels = load_regime_history(history_path)
    pre = pre_gate_production_universe(ev)
    assert_baseline_identity(ev, pre.loc[pre["gate_blocked"] != True])  # noqa: E712
    if len(pre) == 0:
        raise PortfolioPathCounterfactualError("empty_production_universe")
    first_signal = min(pre["signal_date"].astype(str))
    sim_sessions = [s for s in sessions if s >= first_signal]
    if not sim_sessions:
        raise PortfolioPathCounterfactualError(
            f"signal_dates_outside_regime_history: {first_signal}"
        )
    needed = sorted(set(sim_sessions))
    bars = load_daily_marks(raw_daily_dir, needed, set(pre["ts_code"].astype(str)))

    results = {
        config: _simulate_config(ev, config, sim_sessions, labels, bars)
        for config in CONFIGS
    }
    base = results["baseline"]
    deltas = {
        "log_growth": {
            c: float(results[c]["log_growth"]) - float(base["log_growth"])
            for c in CONFIGS
            if c != "baseline"
        },
        "max_drawdown": {
            c: float(results[c]["max_drawdown"]) - float(base["max_drawdown"])
            for c in CONFIGS
            if c != "baseline"
        },
    }
    return {
        "schema_version": 1,
        "path_model": {
            "ticker_limit_weight": TICKER_LIMIT_WEIGHT,
            "portfolio_gross_cap": PORTFOLIO_GROSS_CAP,
            "roundtrip_cost": ROUNDTRIP_COST,
            "cap_semantics": "v2 生产并发语义: 组合总敞口 ≤60%, 单票 8%, per-ticket 二元",
            "entry": "T+1 open (raw daily bars 同源重演)",
            "exit": "T+10 open (事件表 exit_open_t10/exit_session_t10 单一事实源, 停牌顺延)",
            "marks": "持仓期逐会话 close, 缺 bar 顺延最后已知 close",
            "attribution": "cohort 现金贡献 w×net_ret 按信号日 (距离×连跑) 组归并",
            "approximations": [
                "同日选择按 trigger_strength 降序 (生产 investability 排序的披露近似)",
                "并发 60% cap 常年绑满时部署由队列顺序 (日期×强度) 主导 — 路径差"
                "对选择顺序敏感, 组归因是『被部署子集』的条件读数, 与单票全候选"
                "口径 (regime 工具) 不可直接对表",
                "归因是现金空间分解, 非逐会话对数精确分解",
                "窗口末端未平仓持仓按成本/最后已知 close 计值 (不强制平仓)",
                "bars 一致性锚失配 = raw daily 现快照与事件表构建时点的价格漂移,"
                "收益结算不受影响 (事件表单一事实源)",
            ],
        },
        "configs": {c: CONFIG_LABELS[c] for c in CONFIGS},
        "groups": {g: g for g in RUN_GROUPS},
        "court_window": court_window_from_events(ev),
        "results": results,
        "deltas_vs_baseline": deltas,
        "baseline_identity": (
            "baseline 宇宙 ≡ production_aligned (运行时 identity pin 通过)"
        ),
    }


def render_md(payload: dict[str, object], date_str: str) -> str:
    results = payload["results"]
    window = payload["court_window"] or {}
    lines = [
        f"# 组合路径 gate 反事实模拟 ({date_str})",
        "",
        "纯诊断 (宪法 #2: 只披露不判定)。三种 gate 配置下的组合单位净值路径 —",
        "宪法 #2 经济目标 (扣净成本后组合单位净值长期对数增长) 的路径级换算。",
        "单票 8% / 组合并发 60% (v2 生产语义) · T+1 open 入 · T+10 open 出 ·",
        "净成本 0.65% · d1_run 分类 = run_geometry 单一实现。",
        "任何 gate 变化 = 新证据世代 owner 决策。",
        "",
        f"court 窗口: {window.get('start')}..{window.get('end')}"
        " · baseline 宇宙 identity pin: 通过",
        "",
        "## 配置对比",
        "",
        "| 配置 | 宇宙 | 事件 | cap 跳过 | 终值 NAV | log growth | 年化 log | MDD | 锚失配 | 顺延标记 |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for c in CONFIGS:
        r = results[c]
        lines.append(
            f"| {c} | {r['universe_n']} | {r['deployed_events']} "
            f"| {r['skipped_by_cap']} | {r['final_nav']:.4f} "
            f"| {r['log_growth']:+.4f} | {r['ann_log_growth']:+.4f} "
            f"| {r['max_drawdown']:.2%} | {r['anchor_mismatch']} "
            f"| {r['carried_marks']} |"
        )
    lines += [
        "",
        "## Δ vs baseline",
        "",
        "| 配置 | Δlog growth | ΔMDD |",
        "|---|---|---|",
    ]
    deltas = payload["deltas_vs_baseline"]
    for c in CONFIGS:
        if c == "baseline":
            continue
        lines.append(
            f"| {c} | {deltas['log_growth'][c]:+.4f} "
            f"| {deltas['max_drawdown'][c]:+.2%} |"
        )
    lines += [
        "",
        "## 读数前提 (判读前必读)",
        "",
        "- 并发 cap 在本窗口绑满 (baseline 绝大多数候选被 cap 拒绝): 部署构成",
        "  由队列顺序 (日期 × 强度) 内生决定。组归因 (上节) 是『被部署子集』",
        "  的条件读数, 与单票全候选口径 (regime 工具的 d1_run E=−5.74%) 不可",
        "  直接对表; Δlog 同样由边际队列构成驱动, 对选择顺序敏感。",
        "- 锚失配计数与幅度 = raw daily 现快照 vs 事件表构建时点的价格漂移;",
        "  收益结算不受影响 (事件表单一事实源)。",
    ]
    lines += [
        "",
        "## 信号日组现金归因 (Σ w×net_ret)",
        "",
    ]
    for c in CONFIGS:
        r = results[c]
        cells = [
            f"{g}: {cell['contribution']:+.4f} (n={int(cell['events'])})"
            for g, cell in sorted(r["group_contribution"].items())
            if cell["events"]
        ]
        lines.append(f"- **{c}**: " + ("; ".join(cells) if cells else "无持仓"))
    lines += [
        "",
        "## 构建边界 (如实披露)",
        "",
    ]
    for c in CONFIGS:
        r = results[c]
        stats = r["build_stats"]
        mm = r.get("anchor_mismatch_median_abs")
        mx = r.get("anchor_mismatch_max_abs")
        lines.append(
            f"- {c}: missing_entry_bar={stats['missing_entry_bar']} "
            f"missing_exit_offset={stats['missing_exit_offset']} "
            f"cohort_days={results[c]['cohort_days']} "
            f"open_at_end={results[c]['open_at_end']} "
            f"锚失配幅度 median={'' if mm is None else format(mm, '.4%')} "
            f"max={'' if mx is None else format(mx, '.4%')}"
        )
    lines += [
        "",
        "## 纪律",
        "",
        "- 本报告是诊断证据, 不是参数变更提案; d1_run 阻断的路径差是 owner",
        "  杠杆 F 决策的组合路径维度输入, 与单票证据 (regime 工具 split-half",
        "  一致性、配对 CI) 并列消费, 不替代前向 Trial 证据。",
        "- cap 跳过 = 并发 60% 上限拒绝的候选 (生产 per-ticket 二元语义);",
        "  no_gate 参照系含 gate 阻断日 (crisis/risk_off), 量化现有 gate 的路径贡献。",
        "- 幸存者偏差与 court 宇宙边界与 winrate 工具同源; 报告不入 git",
        "  (owner 报告策略 ⑧), 固定输入逐字节可复现 (无随机数)。",
    ]
    return "\n".join(lines) + "\n"


def _attach_digest(payload: dict[str, object], court_table: Path, rows: int) -> None:
    import hashlib

    payload["input_digest"] = {
        "court_table_sha256": "sha256:"
        + hashlib.sha256(court_table.read_bytes()).hexdigest(),
        "court_rows": rows,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="组合路径 gate 反事实模拟 (纯披露)")
    parser.add_argument("--court-table", type=Path, default=COURT_TABLE_DEFAULT)
    parser.add_argument("--regime-history", type=Path, default=REGIME_HISTORY_DEFAULT)
    parser.add_argument("--raw-daily", type=Path, default=BTST_RAW_DAILY_DEFAULT)
    parser.add_argument("--out-dir", type=Path, default=REPORT_DIR_DEFAULT)
    parser.add_argument(
        "--date", type=str, default=None, help="报告日期标签 (默认今日; 测试注入)"
    )
    args = parser.parse_args(argv)

    if not args.court_table.exists():
        raise PortfolioPathCounterfactualError(
            f"court_table_missing: {args.court_table}"
        )
    if not args.raw_daily.exists():
        raise PortfolioPathCounterfactualError(f"raw_daily_missing: {args.raw_daily}")
    ev = pd.read_csv(args.court_table, dtype={"signal_date": str})
    payload = analyze(ev, args.regime_history, args.raw_daily)
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
    base = payload["results"]["baseline"]
    delta = payload["deltas_vs_baseline"]["log_growth"]["baseline_plus_d1run_block"]
    print(
        f"portfolio_path_gate_counterfactual: baseline log={base['log_growth']:+.4f} "
        f"(nav {base['final_nav']:.4f}, mdd {base['max_drawdown']:.2%}) · "
        f"+d1run_block Δlog={delta:+.4f} → {md_path}"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
