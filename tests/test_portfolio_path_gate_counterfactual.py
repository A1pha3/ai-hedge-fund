"""portfolio_path_gate_counterfactual — 组合路径 gate 反事实模拟 (R214 Op1).

把单票/日条件化证据换算成宪法 #2 经济目标口径 (组合单位净值长期对数增长
路径) 的路径模拟器. 钉死的正确性面:
- oracle: 单事件全路径 NAV 精确算术 (T0 承诺 → T+1 open 入 → T+10 open 出,
  净成本 ROUNDTRIP_COST 单一实现同式);
- 容量: 并发 60% cap / 单票 8% per-ticket 二元语义, cap 跳过计数,
  strength 降序 + ts_code tie-break 确定性选择;
- gate 配置: no_gate/baseline/baseline_plus_d1run_block 三配置宇宙差分
  (d1_run 分类 = regime 工具 blocked_run_group 单一实现 identity pin);
- 事件表单一事实源: 收益结算用事件表 gross_ret_t10, bars 重演只作一致性锚,
  失配如实计数; 顺延 close 标记 (陈旧 close) 计数;
- fail-closed: 缺入场 bar / 缺出场 offset 统计, 全空 typed 拒绝,
  未知配置 typed 拒绝, baseline ≡ production_aligned identity pin;
- 确定性: 同输入两次 analyze 逐字节同 payload (无随机数);
- 渲染契约: md 配置对比/Δ 表/组归因/纪律节;
- Op2 对抗收口三钉: 选择方向可观测 (差异化 gross, P03) / NaN 强度
  不挤占有限席位 (P16) / ret 非空子句夹具行 (P18); P08 (cap > → >=)
  为等价变异如实定谳 — 0.60 非 0.08 的整数倍, 边界等值算术不可达.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pandas as pd
import pytest

from scripts import regime_blocked_run_conditioning
from scripts.portfolio_path_gate_counterfactual import (
    CONFIGS,
    PORTFOLIO_GROSS_CAP,
    ROUNDTRIP_COST,
    TICKER_LIMIT_WEIGHT,
    PortfolioPathCounterfactualError,
    analyze,
    assert_baseline_identity,
    blocked_run_group,
    build_cohorts,
    config_universe,
    load_daily_marks,
    main,
    pre_gate_production_universe,
    render_md,
    simulate_path,
)
from scripts.winrate_payoff_decomposition import ROUNDTRIP_COST as _WT_ROUNDTRIP

# ---------------------------------------------------------------------------
# fixture 世界: 会话序 + regime + 事件表 + raw daily bars
# ---------------------------------------------------------------------------

SESSIONS = [f"202601{d:02d}" for d in range(1, 21)]  # 20 会话工作世界


def _labels_all_normal() -> dict[str, str]:
    return {s: "normal" for s in SESSIONS}


def _write_history(tmp_path: Path, labels: dict[str, str]) -> Path:
    path = tmp_path / "regime_history.json"
    path.write_text(json.dumps(labels), encoding="utf-8")
    return path


def _write_bars(tmp_path: Path, bars: dict[tuple[str, str], tuple[float | None, float | None]]) -> Path:
    """{(session, ts_code): (open, close)} → daily_YYYYMMDD.csv 目录。"""
    daily = tmp_path / "daily"
    daily.mkdir(exist_ok=True)
    by_session: dict[str, list[tuple[str, float | None, float | None]]] = {}
    for (session, ts_code), (open_, close) in bars.items():
        by_session.setdefault(session, []).append((ts_code, open_, close))
    for session, rows in by_session.items():
        lines = ["ts_code,open,close"]
        for ts_code, open_, close in rows:
            o = "" if open_ is None else f"{open_:.4f}"
            c = "" if close is None else f"{close:.4f}"
            lines.append(f"{ts_code},{o},{c}")
        (daily / f"daily_{session}.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return daily


def _event(
    ts_code: str,
    day: str,
    *,
    strength: float = 0.80,
    gate_blocked: bool = False,
    gross10: float = 0.0,
    exit_offset: int = 10,
    fillable: bool = True,
) -> dict:
    return {
        "symbol": ts_code.split(".")[0],
        "ts_code": ts_code,
        "signal_date": day,
        "regime": "crisis" if gate_blocked else "normal",
        "trigger_strength": strength,
        "signal_close": 10.0,
        "gap_t1_open": 0.0,
        "fillable": fillable,
        "t1_unbuyable": False,
        "t1_missing_bar": False,
        "degraded": False,
        "industry_missing": False,
        "industry_name": "测试",
        "st_name": False,
        "excluded_ticker": False,
        "price_ge_3": True,
        "gate_blocked": gate_blocked,
        "gross_ret_t10": gross10,
        "exit_session_t10": exit_offset,
    }


def _bars_for_event(
    bars: dict,
    sessions: list[str],
    day: str,
    ts_code: str,
    *,
    entry_open: float = 10.0,
    exit_open: float = 10.0,
    exit_offset: int = 10,
    closes: dict[int, float] | None = None,
    omit_sessions: set[str] | None = None,
) -> None:
    """按 (signal, T+offset] 切片写该票 bars; omit_sessions 整会话缺行。"""
    fwd = [s for s in sessions if s > day][:exit_offset]
    omit = omit_sessions or set()
    for off, session in enumerate(fwd, start=1):
        if session in omit:
            continue
        open_ = entry_open if off == 1 else (exit_open if off == exit_offset else None)
        close = (closes or {}).get(off)
        bars[(session, ts_code)] = (open_, close)


def _flat_bars(
    sessions: list[str],
    day: str,
    ts_code: str,
    *,
    entry_open: float = 10.0,
    exit_open: float = 10.0,
    exit_offset: int = 10,
) -> None:
    """便利包装: 逐会话 close = entry (平价), 入场/出场 open 指定。"""
    bars = _BARS_LOCAL["bars"]
    fwd = [s for s in sessions if s > day][:exit_offset]
    for off, session in enumerate(fwd, start=1):
        open_ = entry_open if off == 1 else (exit_open if off == exit_offset else None)
        bars[(session, ts_code)] = (open_, entry_open)


_BARS_LOCAL: dict[str, dict] = {"bars": {}}


@pytest.fixture()
def world(tmp_path: Path):
    """(events, history, daily_dir) 工厂 — 每例独立 bars 字典。"""

    def _make(labels, events, bars):
        ev = pd.DataFrame(events)
        history = _write_history(tmp_path, labels)
        daily = _write_bars(tmp_path, bars)
        return ev, history, daily

    _BARS_LOCAL["bars"] = {}
    return _make


# ---------------------------------------------------------------------------
# oracle: 单事件全路径精确算术
# ---------------------------------------------------------------------------


def test_oracle_single_event_exact_nav(world, tmp_path):
    events = [_event("A.SZ", SESSIONS[0], strength=0.90, gross10=1.0)]
    bars: dict = {}
    _BARS_LOCAL["bars"] = bars
    _bars_for_event(
        bars, SESSIONS, SESSIONS[0], "A.SZ",
        entry_open=10.0, exit_open=20.0, exit_offset=10,
        closes={**{o: 12.0 for o in range(1, 10)}, 10: 20.0},
    )
    ev, history, daily = world(_labels_all_normal(), events, bars)
    payload = analyze(ev, history, daily)
    r = payload["results"]["baseline"]

    net = 1.0 - ROUNDTRIP_COST
    expected_final = 1.0 + TICKER_LIMIT_WEIGHT * net  # 0.08 × 0.9935
    assert r["deployed_events"] == 1
    assert r["skipped_by_cap"] == 0
    assert r["cap_binding_days"] == 0
    assert r["anchor_mismatch"] == 0
    assert r["carried_marks"] == 0
    assert r["open_at_end"] == 0
    assert r["final_nav"] == pytest.approx(expected_final)
    assert r["log_growth"] == pytest.approx(math.log(expected_final))
    # 出场会话 = 信号日后第 10 个会话 = SESSIONS[10]; 模拟格 n = 11。
    assert r["n_sessions"] == 11
    assert r["ann_log_growth"] == pytest.approx(math.log(expected_final) * 252.0 / 11)
    # 组归因: 无前导阻断日 → no_prior, 现金贡献 = w × net。
    cell = r["group_contribution"]["no_prior"]
    assert cell["events"] == 1
    assert cell["contribution"] == pytest.approx(TICKER_LIMIT_WEIGHT * net)


def test_mdd_positive_on_loss_path(world, tmp_path):
    # 入场后浮亏: close 深跌 → NAV 路径先跌破成本再按表值出场。
    events = [_event("A.SZ", SESSIONS[0], gross10=-0.10)]
    bars: dict = {}
    _BARS_LOCAL["bars"] = bars
    _bars_for_event(
        bars, SESSIONS, SESSIONS[0], "A.SZ",
        entry_open=10.0, exit_open=9.0, exit_offset=10,
        closes={**{o: 8.0 for o in range(1, 10)}, 10: 9.0},
    )
    ev, history, daily = world(_labels_all_normal(), events, bars)
    payload = analyze(ev, history, daily)
    r = payload["results"]["baseline"]
    # 最深标记: 0.92 + 0.08×0.8 = 0.984 → MDD = (1−0.984)/1。
    assert r["max_drawdown"] == pytest.approx(0.016)
    assert r["final_nav"] == pytest.approx(1.0 + TICKER_LIMIT_WEIGHT * (-0.10 - ROUNDTRIP_COST))


# ---------------------------------------------------------------------------
# 容量: cap 绑定与确定性选择
# ---------------------------------------------------------------------------


def _eight_candidate_world(world, tmp_path, strengths):
    events = [
        _event(f"A{i}.SZ", SESSIONS[0], strength=strengths[i - 1], gross10=0.0)
        for i in range(1, 9)
    ]
    bars: dict = {}
    _BARS_LOCAL["bars"] = bars
    for i in range(1, 9):
        _bars_for_event(bars, SESSIONS, SESSIONS[0], f"A{i}.SZ")
    return world(_labels_all_normal(), events, bars)


def test_cap_binds_at_seven_positions(world, tmp_path):
    ev, history, daily = _eight_candidate_world(world, tmp_path, [0.5] * 8)
    payload = analyze(ev, history, daily)
    r = payload["results"]["baseline"]
    assert r["deployed_events"] == 7  # 7×8% = 56% ≤ 60% < 8×8%
    assert r["skipped_by_cap"] == 1
    assert r["cap_binding_days"] == 1


def test_selection_strength_desc_then_ticker_asc(world, tmp_path):
    # A8 强度最高 → 必然入场; 其余同强度按 ts_code 升序取前 6。
    strengths = [0.5] * 7 + [0.90]
    ev, history, daily = _eight_candidate_world(world, tmp_path, strengths)
    payload = analyze(ev, history, daily)
    r = payload["results"]["baseline"]
    assert r["deployed_events"] == 7
    assert r["skipped_by_cap"] == 1
    # 全部 gross=0 → 终值精确: 1 − 7×w×cost; A8 在场与否不影响终值,
    # 用 selection 可观测面: cap_binding_days=1 (第 8 顺位被拒)。
    assert r["final_nav"] == pytest.approx(1.0 - 7 * TICKER_LIMIT_WEIGHT * ROUNDTRIP_COST)
    # 确定性: 同输入重跑同一结果。
    payload2 = analyze(ev, history, daily)
    assert payload == payload2


def test_selection_deploys_highest_strength_under_cap(world, tmp_path):
    # 选择方向可观测钉 (Op2 P03 变异「强度反序」BLIND 收口): cap 7 槽 +
    # 差异化 gross — 强度降序必须部署高强度高毛利候选; 反序下 A8 被拒、
    # 7 个 0% 候选入场, 终值不同 → 当场红。
    strengths = [0.5] * 7 + [0.90]
    grosses = [0.0] * 7 + [0.05]
    events = [
        _event(f"A{i}.SZ", SESSIONS[0], strength=strengths[i - 1], gross10=grosses[i - 1])
        for i in range(1, 9)
    ]
    bars: dict = {}
    _BARS_LOCAL["bars"] = bars
    for i in range(1, 9):
        _bars_for_event(
            bars, SESSIONS, SESSIONS[0], f"A{i}.SZ",
            exit_open=10.0 if grosses[i - 1] == 0.0 else 10.5,
        )
    ev, history, daily = world(_labels_all_normal(), events, bars)
    payload = analyze(ev, history, daily)
    r = payload["results"]["baseline"]
    assert r["deployed_events"] == 7
    assert r["anchor_mismatch"] == 0
    expected = (
        1.0
        + TICKER_LIMIT_WEIGHT * (0.05 - ROUNDTRIP_COST)
        - 6 * TICKER_LIMIT_WEIGHT * ROUNDTRIP_COST
    )
    assert r["final_nav"] == pytest.approx(expected)


def test_nan_strength_sorts_after_finite(world, tmp_path):
    # NaN 强度钉 (Op2 P16 变异「NaN 视为最高」BLIND 收口): NaN 候选不得
    # 挤占有限强度席位 — 7 个有限 0.6 全入场, NaN (+50% 诱饵毛利) 被拒;
    # 若 NaN 被当成最高强度则 A9 入场、一个有限候选被拒, 终值不同 → 当场红。
    events = [
        _event(f"A{i}.SZ", SESSIONS[0], strength=0.6, gross10=0.0)
        for i in range(1, 8)
    ]
    events.append(_event("A9.SZ", SESSIONS[0], strength=float("nan"), gross10=0.50))
    bars: dict = {}
    _BARS_LOCAL["bars"] = bars
    for i in range(1, 8):
        _bars_for_event(bars, SESSIONS, SESSIONS[0], f"A{i}.SZ")
    _bars_for_event(bars, SESSIONS, SESSIONS[0], "A9.SZ", exit_open=15.0)
    ev, history, daily = world(_labels_all_normal(), events, bars)
    payload = analyze(ev, history, daily)
    r = payload["results"]["baseline"]
    assert r["deployed_events"] == 7
    assert r["final_nav"] == pytest.approx(
        1.0 - 7 * TICKER_LIMIT_WEIGHT * ROUNDTRIP_COST
    )


def test_ret_nan_rows_excluded_from_pre_gate_universe(world, tmp_path):
    # ret 非空子句钉 (Op2 P18 变异「ret 非空子句删除」BLIND 收口): 夹具世界
    # 此前无 NaN 毛利行, 子句被删时全部测试仍绿 (真空泛化)。fillable 但
    # gross_ret_t10 缺失的行不属于任何配置宇宙, identity pin 面依赖该子句。
    events = [_event("K1.SZ", SESSIONS[0], gross10=0.0)]
    events.append(_event("K2.SZ", SESSIONS[0], gross10=float("nan")))
    ev = pd.DataFrame(events)
    pre = pre_gate_production_universe(ev)
    assert set(pre["ts_code"]) == {"K1.SZ"}
    baseline = pre.loc[pre["gate_blocked"] != True]  # noqa: E712
    # NaN 行缺席时 identity pin 通过 (与 production_aligned 集合恒等)。
    assert_baseline_identity(ev, baseline)


def test_cash_never_binds_under_cap(world, tmp_path):
    # 60% cap 恒保证 cash ≥ 40% > 8% — cash_below_weight_with_cap_headroom
    # 防御分支在合法输入下不可达。
    ev, history, daily = _eight_candidate_world(world, tmp_path, [0.5] * 8)
    payload = analyze(ev, history, daily)
    assert "cash_below_weight" not in json.dumps(payload)


# ---------------------------------------------------------------------------
# gate 配置: 三配置宇宙差分 + d1_run 单一实现
# ---------------------------------------------------------------------------


def _gate_world_events() -> list[dict]:
    return [
        # day2 crisis 单日 (gate_blocked) → baseline 拒; no_gate 收。
        _event("B1.SZ", SESSIONS[1], strength=0.9, gate_blocked=True),
        # day3 = 距单日闪断 1 会话 → d1_blip → 两配置都保留。
        _event("B2.SZ", SESSIONS[2], strength=0.8),
        # day4/day5 crisis 连跑 run=2 → day6 = d1_run → 杠杆 F 候选拒。
        _event("B3.SZ", SESSIONS[5], strength=0.7),
        # day10 正常深处 → 非 d1_run。
        _event("B4.SZ", SESSIONS[9], strength=0.6),
    ]


def _gate_world_labels() -> dict[str, str]:
    labels = _labels_all_normal()
    labels[SESSIONS[1]] = "crisis"
    labels[SESSIONS[3]] = "crisis"
    labels[SESSIONS[4]] = "crisis"
    return labels


def _gate_world(world, tmp_path):
    events = _gate_world_events()
    labels = _gate_world_labels()
    bars: dict = {}
    _BARS_LOCAL["bars"] = bars
    for e in events:
        _bars_for_event(bars, SESSIONS, e["signal_date"], e["ts_code"])
    ev, history, daily = world(labels, events, bars)
    # d1_run 分类单一实现: 工具引用与 regime 模块同函数对象。
    assert blocked_run_group is regime_blocked_run_conditioning.blocked_run_group
    assert blocked_run_group(SESSIONS[5], SESSIONS, labels) == "d1_run"
    assert blocked_run_group(SESSIONS[2], SESSIONS, labels) == "d1_blip"
    return ev, history, daily


def test_gate_configs_universe_and_deployment(world, tmp_path):
    ev, history, daily = _gate_world(world, tmp_path)
    labels = _gate_world_labels()
    pre = pre_gate_production_universe(ev)
    assert len(pre) == 4
    baseline = pre.loc[pre["gate_blocked"] != True]  # noqa: E712
    assert_baseline_identity(ev, baseline)  # 不抛 = identity pin 通过
    u_no = config_universe(ev, "no_gate", SESSIONS, labels)
    u_base = config_universe(ev, "baseline", SESSIONS, labels)
    u_blk = config_universe(ev, "baseline_plus_d1run_block", SESSIONS, labels)
    assert set(u_no["ts_code"]) == {"B1.SZ", "B2.SZ", "B3.SZ", "B4.SZ"}
    assert set(u_base["ts_code"]) == {"B2.SZ", "B3.SZ", "B4.SZ"}
    assert set(u_blk["ts_code"]) == {"B2.SZ", "B4.SZ"}  # d1_run (B3) 被拒


def test_gate_configs_deployment_and_attribution(world, tmp_path):
    ev, history, daily = _gate_world(world, tmp_path)
    payload = analyze(ev, history, daily)
    r_no = payload["results"]["no_gate"]
    r_base = payload["results"]["baseline"]
    r_blk = payload["results"]["baseline_plus_d1run_block"]
    assert r_no["deployed_events"] == 4
    assert r_base["deployed_events"] == 3
    assert r_blk["deployed_events"] == 2
    # d1_run 组归因: baseline 有, d1run_block 无。
    assert r_base["group_contribution"]["d1_run"]["events"] == 1
    assert "d1_run" not in r_blk["group_contribution"]
    # 全部 gross=0 → 各配置终值 = 1 − deployed×w×cost。
    for r, n in ((r_no, 4), (r_base, 3), (r_blk, 2)):
        assert r["final_nav"] == pytest.approx(1.0 - n * TICKER_LIMIT_WEIGHT * ROUNDTRIP_COST)


# ---------------------------------------------------------------------------
# 事件表单一事实源 + 顺延标记
# ---------------------------------------------------------------------------


def test_anchor_mismatch_disclosed_table_is_source_of_truth(world, tmp_path):
    # bars 暗示毛收益 +10%, 事件表声称 +20% → 失配计数 1, 结算按事件表。
    events = [_event("C1.SZ", SESSIONS[0], gross10=0.20)]
    bars: dict = {}
    _BARS_LOCAL["bars"] = bars
    _bars_for_event(
        bars, SESSIONS, SESSIONS[0], "C1.SZ",
        entry_open=10.0, exit_open=11.0, exit_offset=10,
        closes={o: 10.5 for o in range(1, 10)},
    )
    bars[(SESSIONS[10], "C1.SZ")] = (11.0, 10.5)  # bars 出场 open 11 → path_gross 10%
    ev, history, daily = world(_labels_all_normal(), events, bars)
    payload = analyze(ev, history, daily)
    r = payload["results"]["baseline"]
    assert r["anchor_mismatch"] == 1
    # 失配幅度如实披露: |0.10 − 0.20| = 0.10。
    assert r["anchor_mismatch_max_abs"] == pytest.approx(0.10)
    assert r["anchor_mismatch_median_abs"] == pytest.approx(0.10)
    # 结算以事件表 +20% 为准。
    assert r["final_nav"] == pytest.approx(1.0 + TICKER_LIMIT_WEIGHT * (0.20 - ROUNDTRIP_COST))


def test_carried_marks_counted_for_stale_close(world, tmp_path):
    # off2 缺 close → off2 标记用 off1 陈旧 close → carried_marks ≥1;
    # off1 有新鲜 close → 不计。入场日 (off1) close 缺失按成本计不计数。
    events = [_event("D1.SZ", SESSIONS[0], gross10=0.0)]
    bars: dict = {}
    _BARS_LOCAL["bars"] = bars
    fwd = [s for s in SESSIONS if s > SESSIONS[0]][:10]
    closes = {o: 10.0 for o in range(1, 11)}
    _bars_for_event(
        bars, SESSIONS, SESSIONS[0], "D1.SZ",
        entry_open=10.0, exit_open=10.0, exit_offset=10, closes=closes,
        omit_sessions={fwd[1]},  # off2 整行缺失
    )
    ev, history, daily = world(_labels_all_normal(), events, bars)
    payload = analyze(ev, history, daily)
    r = payload["results"]["baseline"]
    assert r["carried_marks"] == 1  # 仅 off2 一次陈旧标记
    assert r["anchor_mismatch"] == 0
    assert r["final_nav"] == pytest.approx(1.0 - TICKER_LIMIT_WEIGHT * ROUNDTRIP_COST)


def test_missing_entry_bar_skipped_with_stat(world, tmp_path):
    events = [_event("E1.SZ", SESSIONS[0], gross10=0.0)]
    bars: dict = {}
    _BARS_LOCAL["bars"] = bars
    fwd = [s for s in SESSIONS if s > SESSIONS[0]][:10]
    # 入场会话 (off1) 整行缺失 → 入场价不可得 → 跳过并计数。
    for off, session in enumerate(fwd, start=1):
        if off == 1:
            continue
        bars[(session, "E1.SZ")] = (None, 10.0)
    ev, history, daily = world(_labels_all_normal(), events, bars)
    cohorts, stats = build_cohorts(
        pre_gate_production_universe(ev), SESSIONS, load_daily_marks(
            daily, SESSIONS, {"E1.SZ"}
        )
    )
    assert stats["missing_entry_bar"] == 1
    assert cohorts == {}


def test_missing_exit_offset_stat(world, tmp_path):
    events = [_event("F1.SZ", SESSIONS[-1], gross10=0.0, exit_offset=10)]
    bars: dict = {}
    _BARS_LOCAL["bars"] = bars
    # 尾日信号, 后继会话不足 10 → exit_off > len(fwd) → 统计不部署。
    ev, history, daily = world(_labels_all_normal(), events, bars)
    cohorts, stats = build_cohorts(
        pre_gate_production_universe(ev), SESSIONS, load_daily_marks(
            daily, SESSIONS, {"F1.SZ"}
        )
    )
    assert stats["missing_exit_offset"] == 1
    assert cohorts == {}


# ---------------------------------------------------------------------------
# fail-closed 与 identity pin
# ---------------------------------------------------------------------------


def test_unknown_config_typed_rejection(world, tmp_path):
    ev, history, daily = _gate_world(world, tmp_path)
    labels = _gate_world_labels()
    with pytest.raises(PortfolioPathCounterfactualError, match="unknown_config"):
        config_universe(ev, "no_gate_plus", SESSIONS, labels)


def test_missing_column_typed_rejection(world, tmp_path):
    events = [_event("G1.SZ", SESSIONS[0])]
    ev = pd.DataFrame(events).drop(columns=["price_ge_3"])
    with pytest.raises(PortfolioPathCounterfactualError, match="缺少生产过滤列"):
        pre_gate_production_universe(ev)


def test_identity_pin_mismatch_raises(world, tmp_path):
    events = [_event("H1.SZ", SESSIONS[0])]
    ev = pd.DataFrame(events)
    baseline = pre_gate_production_universe(ev)
    tampered = baseline.drop(baseline.index[0])  # 人为缺一行
    with pytest.raises(PortfolioPathCounterfactualError, match="identity_mismatch"):
        assert_baseline_identity(ev, tampered)


def test_all_events_undeployable_typed_rejection(world, tmp_path):
    events = [_event("I1.SZ", SESSIONS[0], gross10=0.0)]
    bars: dict = {}
    _BARS_LOCAL["bars"] = bars
    ev, history, daily = world(_labels_all_normal(), events, bars)  # 无任何 bars
    with pytest.raises(PortfolioPathCounterfactualError, match="no_tradeable_signal_session"):
        analyze(ev, history, daily)


def test_exit_beyond_grid_typed_rejection(world, tmp_path):
    # cohort 出场会话不在模拟格内 → simulate_path 防御断言 (build 层已拦,
    # 此为纵深)。
    cohort = {
        "signal_date": SESSIONS[0],
        "ts_code": "J1.SZ",
        "strength": 0.9,
        "entry_session": SESSIONS[1],
        "exit_session": "ZZZZ",  # 不在格内
        "entry_open": 10.0,
        "closes_by_offset": {1: 10.0},
        "fresh_offsets": {1},
        "gross_ret_t10": 0.0,
        "path_gross": 0.0,
        "anchor_mismatch": False,
    }
    with pytest.raises(PortfolioPathCounterfactualError, match="exit_session_beyond_grid"):
        simulate_path({SESSIONS[0]: [cohort]}, SESSIONS, _labels_all_normal())


# ---------------------------------------------------------------------------
# 常量钉 + 渲染 + 端到端
# ---------------------------------------------------------------------------


def test_constants_and_single_implementation_pins():
    assert TICKER_LIMIT_WEIGHT == 0.08
    assert PORTFOLIO_GROSS_CAP == 0.60
    assert CONFIGS == (
        "no_gate",
        "baseline",
        "baseline_plus_d1run_block",
    )
    # 净成本单一实现: 与 winrate 工具同值同源 (net_returns 同式)。
    assert ROUNDTRIP_COST == _WT_ROUNDTRIP == 0.0065
    # d1_run 分类单一实现 (函数对象 identity)。
    assert blocked_run_group is regime_blocked_run_conditioning.blocked_run_group


def test_render_md_contract(world, tmp_path):
    ev, history, daily = _gate_world(world, tmp_path)
    payload = analyze(ev, history, daily)
    md = render_md(payload, "20260131")
    assert "# 组合路径 gate 反事实模拟 (20260131)" in md
    for token in (
        "## 配置对比",
        "## Δ vs baseline",
        "## 读数前提",
        "## 信号日组现金归因",
        "## 构建边界",
        "## 纪律",
        "no_gate",
        "baseline_plus_d1run_block",
        "宪法 #2",
    ):
        assert token in md, token
    # d1_run 组归因行: baseline 有 n=1 (gross=0 → 贡献 = w×(−cost) = −0.0005),
    # d1run_block 无该组。
    assert "d1_run: -0.0005 (n=1)" in md


def test_main_end_to_end_hermetic(world, tmp_path, capsys):
    ev, history, daily = _gate_world(world, tmp_path)
    court_csv = tmp_path / "event_table.csv"
    ev.to_csv(court_csv, index=False)
    out_dir = tmp_path / "reports"
    rc = main(
        [
            "--court-table", str(court_csv),
            "--regime-history", str(history),
            "--raw-daily", str(daily),
            "--out-dir", str(out_dir),
            "--date", "20260131",
        ]
    )
    assert rc == 0
    md_path = out_dir / "portfolio_path_gate_counterfactual_20260131.md"
    json_path = out_dir / "portfolio_path_gate_counterfactual_20260131.json"
    assert md_path.exists() and json_path.exists()
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["report_date"] == "20260131"
    assert payload["results"]["baseline"]["deployed_events"] == 3
    assert "court_table_sha256" in payload["input_digest"]
    out = capsys.readouterr().out
    assert "+d1run_block" in out


def test_determinism_same_payload_twice(world, tmp_path):
    ev, history, daily = _gate_world(world, tmp_path)
    p1 = analyze(ev, history, daily)
    p2 = analyze(ev, history, daily)
    assert json.dumps(p1, sort_keys=True) == json.dumps(p2, sort_keys=True)
