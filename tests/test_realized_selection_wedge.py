"""realized_selection_wedge — 实现面选中楔子恒等三分解的 fixture 驱动测试.

零网络/零 gitignored 资产: 全部输入在测试内构造 (R10 slot 自足纪律)。
楔子恒等式: E[bought] − E[universe] = 日选择 + 日内合格选择 + 不合格买入,
三个分量都是单元格格子均值的 plainly difference — 恒等不依赖 RNG。
"""

from __future__ import annotations

import json

import pandas as pd
import pytest

from scripts.btst_realized_vs_court import (
    STORE_LEDGER_V2,
    build_classification_inputs,
    reconcile,
)
from scripts.realized_selection_wedge import (
    classify_ineligible_reasons,
    decompose_wedge,
    eligible_universe_cells,
    production_buy_days,
    recover_paper_strengths,
    render_md,
    split_bought_cells,
    build_payload,
)


# ---------------------------------------------------------------------------
# fixture 构造 — 非对称双日宇宙 (均值刻意互异, 数值断言防全对称漂移掩盖)
# ---------------------------------------------------------------------------

def _ev_row(
    day: str,
    code: str,
    *,
    strength: float,
    ret: float,
    fillable: bool = True,
    gate_blocked: bool = False,
    price_ge_3: bool = True,
    degraded: bool = False,
    st_name: str = "",
    industry_missing: bool = False,
    excluded_ticker: bool = False,
    t1_unbuyable: bool = False,
) -> dict:
    return {
        "signal_date": int(day),
        "ts_code": f"{code}.SZ",
        "trigger_strength": strength,
        "gross_ret_t10": ret,
        "gross_ret_t8": ret * 0.5,
        "fillable": fillable,
        "gate_blocked": gate_blocked,
        "price_ge_3": price_ge_3,
        "degraded": degraded,
        "st_name": st_name,
        "industry_missing": industry_missing,
        "excluded_ticker": excluded_ticker,
        "t1_unbuyable": t1_unbuyable,
    }


def _fixture_world() -> dict:
    """双日宇宙 + 一个 gate_blocked 格 (000006, 不入 U 但可被 matched 买入)。

    U (production_aligned) = 5 格均值 0.0% (000006 被 gate 排除);
    day1 均值 +1.0% (3 格) / day2 合格集均值 -1.5% (2 格) — 非对称。
    买入: A1 (day1, 合格) / B1 (day2, 合格但 court 终态强度 0.45 — 漂移面
    披露, 宇宙仍含 <0.50 行) / B2 (day2, h=8 → 不进主恒等面) /
    C1 = 000006 (day2, gate_blocked → 不合格面承载)。
    """
    ev = pd.DataFrame(
        [
            _ev_row("20260701", "000001", strength=0.75, ret=0.03),
            _ev_row("20260701", "000002", strength=0.65, ret=0.01),
            _ev_row("20260701", "000003", strength=0.55, ret=-0.01),
            _ev_row("20260702", "000004", strength=0.45, ret=-0.05),
            _ev_row("20260702", "000005", strength=0.70, ret=0.02),
            _ev_row("20260702", "000006", strength=0.80, ret=-0.10, gate_blocked=True),
        ]
    )
    days = ["20260701", "20260702"]
    inputs = build_classification_inputs(
        court_table=ev,
        window_sessions=days,
        regime_labels={d: "normal" for d in days},
        panel_dates=days,
    )
    journal = [
        {"date": "20260701", "ticker": "000001", "action": "BUY", "horizon": 10,
         "trigger_strength": 0.75},
        {"date": "20260702", "ticker": "000004", "action": "BUY", "horizon": 10,
         "trigger_strength": 0.60},
        {"date": "20260702", "ticker": "000005", "action": "BUY", "horizon": 8,
         "trigger_strength": 0.70},
        {"date": "20260702", "ticker": "000006", "action": "BUY", "horizon": 10,
         "trigger_strength": 0.80},
    ]
    recon = reconcile(journal, inputs, extra_buys=[])
    return {"ev": ev, "inputs": inputs, "recon": recon}


def test_identity_zero_residual() -> None:
    """恒等零残差: 三分量之和 == wedge (非对称 fixture, 浮点容差)。"""
    world = _fixture_world()
    payload = build_payload(
        world["recon"], world["ev"], world["inputs"], log_dir=None, report_date="20260906"
    )
    comp = payload["components"]
    assert comp["residual_pp"] is not None
    assert abs(comp["residual_pp"]) < 1e-9
    wedge = comp["wedge_pp"]
    total = comp["day_pp"] + comp["within_day_pp"] + comp["ineligible_pp"]
    assert abs((wedge - total)) < 1e-9
    # 手工 oracle: U 均值 0.0 (000006 被 gate 排除) /
    # D 均值 0.0 (两买入日覆盖 U 全部 5 格) /
    # B_all 均值 (3-5-10)/3=-4.0 / B_elig 均值 (3-5)/2=-1.0
    assert abs(payload["faces"]["universe_mean_pct"] - 0.0) < 1e-9
    assert abs(comp["wedge_pp"] - (-4.0)) < 1e-9
    assert abs(comp["day_pp"] - 0.0) < 1e-9
    assert abs(comp["within_day_pp"] - (-1.0)) < 1e-9
    assert abs(comp["ineligible_pp"] - (-3.0)) < 1e-9


def test_day_only_scenario_components() -> None:
    """日选择面单独承载: 全部买入合格且 B_elig 均值 == D 均值 → 其余两分量零。"""
    world = _fixture_world()
    universe = eligible_universe_cells(world["ev"])
    # 买 day1 的 A2 (ret +1.0%): D 均值 = (3+1-1-5+2)/5 = 0 ; B_elig={A2}=+1.0
    # → within = +1.0 ≠ 0... 改用买全部 day1 三格: B_elig 均值 = 1.0 == D? 不。
    # 最干净的 day-only 形态: 只买 day1 的全部三格 → D = day1 三格 (均值 1.0),
    # B_elig = 同三格 (均值 1.0) → within = 0, ineligible = 0, day = wedge = 1.0。
    ev2 = world["ev"]
    inputs2 = build_classification_inputs(
        court_table=ev2,
        window_sessions=["20260701", "20260702"],
        regime_labels={"20260701": "normal", "20260702": "normal"},
        panel_dates=["20260701", "20260702"],
    )
    journal2 = [
        {"date": "20260701", "ticker": c, "action": "BUY", "horizon": 10,
         "trigger_strength": 0.7}
        for c in ("000001", "000002", "000003")
    ]
    recon2 = reconcile(journal2, inputs2, extra_buys=[])
    payload = build_payload(recon2, ev2, inputs2, log_dir=None, report_date="20260906")
    comp = payload["components"]
    assert abs(comp["wedge_pp"] - 1.0) < 1e-9
    assert abs(comp["day_pp"] - 1.0) < 1e-9
    assert abs(comp["within_day_pp"]) < 1e-9
    assert comp["ineligible_pp"] is not None and abs(comp["ineligible_pp"]) < 1e-9
    assert abs(comp["residual_pp"]) < 1e-9


def test_ineligible_reason_classification() -> None:
    """漂移面: 不合格格的原因逐项分类 (strength<0.50 / 不可成交 / gate)。"""
    row = {"trigger_strength": 0.45, "fillable": True, "gate_blocked": False,
           "price_ge_3": True, "degraded": False, "st_name": "",
           "industry_missing": False, "excluded_ticker": False,
           "t1_unbuyable": False, "gross_ret_t10": -0.05}
    reasons = classify_ineligible_reasons(row)
    assert reasons == ["strength_below_threshold"]
    blocked = classify_ineligible_reasons(
        {**row, "trigger_strength": 0.8, "gate_blocked": True, "t1_unbuyable": True}
    )
    assert "gate_blocked" in blocked and "t1_unbuyable" in blocked
    assert "strength_below_threshold" not in blocked


def test_decision_strength_join_and_missing_disclosure(tmp_path) -> None:
    """v2 台账行 join setup_output_log eligible 行; 缺行 → None + 计数。"""
    log_dir = tmp_path / "setup_output_log"
    log_dir.mkdir()
    rows = [
        "corrupt-line-without-json",
        {"ticker": "000004", "plan_eligible": True, "trigger_strength": 0.60},
        {"ticker": "000009", "plan_eligible": True, "trigger_strength": 0.55},
    ]
    (log_dir / "20260702.jsonl").write_text(
        "\n".join(r if isinstance(r, str) else json.dumps(r) for r in rows) + "\n",
        encoding="utf-8",
    )
    world = _fixture_world()
    # 把 B1 记录标成 ledger_v2 (store 面驱动 join), B2 保持 legacy
    records = world["recon"].matched_records
    from scripts.btst_realized_vs_court import SignalRecord

    relabeled = [
        SignalRecord(
            signal_date=r.signal_date, ticker=r.ticker, horizon=r.horizon,
            paper_strength=None if r.ticker == "000004" else r.paper_strength,
            classification=r.classification, court_strength=r.court_strength,
            strength_drift=None, realized_pct=r.realized_pct,
            court_gross_ret_horizon=r.court_gross_ret_horizon,
            direction_agree=r.direction_agree,
            store=STORE_LEDGER_V2 if r.ticker == "000004" else r.store,
        )
        for r in records
    ]
    # 追加一行 v2 记录指向无日志文件日 → missing 计数 +1
    relabeled.append(
        SignalRecord(
            signal_date="20260703", ticker="000009", horizon=10,
            paper_strength=None, classification="matched", court_strength=0.55,
            strength_drift=None, realized_pct=None, court_gross_ret_horizon=1.0,
            direction_agree=None, store=STORE_LEDGER_V2,
        )
    )
    mapping, missing = recover_paper_strengths(relabeled, log_dir)
    assert mapping[("20260702", "000004")] == pytest.approx(0.60)
    assert ("20260703", "000009") not in mapping
    assert missing == 1
    # 损坏行跳过不崩 (skip-corrupt 语义 — 其后的 000004 行被正常解析)
    assert ("20260702", "000009") not in mapping  # 非买入记录不入 map


def test_other_horizon_excluded_from_primary() -> None:
    """h≠10 买入不进主恒等面, 单独披露 n/均值。"""
    world = _fixture_world()
    payload = build_payload(
        world["recon"], world["ev"], world["inputs"], log_dir=None, report_date="20260906"
    )
    assert payload["faces"]["b_all_n"] == 3  # A1+B1+C1; h=8 的 B2 不在
    others = {str(item["horizon"]): item for item in payload["other_horizons"]}
    assert others["8"]["n"] == 1
    assert others["8"]["mean_pct"] == pytest.approx(1.0)


def test_per_day_table_oracle() -> None:
    """逐日表计数与均值对得上手工 oracle。"""
    world = _fixture_world()
    payload = build_payload(
        world["recon"], world["ev"], world["inputs"], log_dir=None, report_date="20260906"
    )
    rows = {r["signal_date"]: r for r in payload["per_day"]}
    d1 = rows["20260701"]
    assert d1["eligible_n"] == 3
    assert d1["day_mean_pct"] == pytest.approx(1.0)
    assert d1["bought_elig_n"] == 1
    assert d1["bought_elig_mean_pct"] == pytest.approx(3.0)
    assert d1["bought_inelig_n"] == 0
    d2 = rows["20260702"]
    assert d2["eligible_n"] == 2
    assert d2["day_mean_pct"] == pytest.approx(-1.5)
    assert d2["bought_elig_n"] == 1
    assert d2["bought_elig_mean_pct"] == pytest.approx(-5.0)
    assert d2["bought_inelig_n"] == 1


def test_universe_fail_closed_on_missing_columns() -> None:
    """过滤列缺失 → production_aligned fail-closed (口径理解错误不静默)。"""
    ev = pd.DataFrame([{"signal_date": 20260701, "ts_code": "000001.SZ"}])
    with pytest.raises(SystemExit):
        eligible_universe_cells(ev)


def test_decompose_empty_faces_none_propagation() -> None:
    """空面退化: 任一分量缺面 → None + residual None, 绝不假装 0。"""
    comp = decompose_wedge(u_vals=[0.0, 0.0], d_vals=[], be_vals=[0.5], ba_vals=[0.5])
    assert comp["day_pp"] is None
    assert comp["within_day_pp"] is None
    assert comp["ineligible_pp"] is not None
    assert comp["wedge_pp"] == pytest.approx(0.5)
    assert comp["residual_pp"] is None


def test_deterministic_payload_bytes() -> None:
    """同输入逐字节同输出 (无 RNG)。"""
    world = _fixture_world()
    p1 = build_payload(
        world["recon"], world["ev"], world["inputs"], log_dir=None, report_date="20260906"
    )
    p2 = build_payload(
        world["recon"], world["ev"], world["inputs"], log_dir=None, report_date="20260906"
    )
    assert json.dumps(p1, ensure_ascii=False, sort_keys=True) == json.dumps(
        p2, ensure_ascii=False, sort_keys=True
    )
    assert render_md(p1) == render_md(p2)


def test_md_discipline_lines() -> None:
    """MD 含纪律句 + n<30 披露 + 恒等式行。"""
    world = _fixture_world()
    payload = build_payload(
        world["recon"], world["ev"], world["inputs"], log_dir=None, report_date="20260906"
    )
    md = render_md(payload)
    assert "纯诊断" in md
    assert "n<30" in md
    assert "日选择" in md
    assert "owner" in md


def test_production_buy_days_includes_split_days() -> None:
    """日集合来自全部生产 BUY (含 split 未 matched 的日子)。"""
    world = _fixture_world()
    days = production_buy_days(world["recon"].records)
    assert days == ["20260701", "20260702"]


def test_split_bought_cells_membership() -> None:
    """b_elig ⊆ universe; b_inelig 携带原因; 键形状 (day, 6位代码)。"""
    world = _fixture_world()
    universe = eligible_universe_cells(world["ev"])
    b_all, b_elig, b_inelig = split_bought_cells(
        world["recon"].matched_records, universe, world["inputs"].court_rows
    )
    assert [c["key"] for c in b_all] == [
        ("20260701", "000001"),
        ("20260702", "000004"),
        ("20260702", "000006"),
    ]
    assert [c["key"] for c in b_elig] == [("20260701", "000001"), ("20260702", "000004")]
    assert [c["key"] for c in b_inelig] == [("20260702", "000006")]
    assert b_inelig[0]["reasons"] == ["gate_blocked"]
    assert universe[("20260701", "000001")] == pytest.approx(3.0)
