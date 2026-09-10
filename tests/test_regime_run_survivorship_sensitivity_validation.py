"""regime_run_survivorship_sensitivity_validation — 时代条件性的幸存者敏感度界 (R180 Op1).

R179 判定「构成轴不解释时代差」后, 机制二元剩 (时代行为差异 vs 早期侧幸
存者缺失)。本工具把幸存者解释机械化: 早期表缺席的退市票 (隐藏行) 需要多
大的 run-vs-blip 差分 / 多负的均值, 才能把早期点罚分推到当前观测量级。
钉死的正确性面:
- 双时代 100% 委托 R168 analyze 单一实现 (经 R178 _era_view/_point_penalty
  复用, import 身份断言钉住零 fork); 指纹 loader / digest 附加同为 R178
  模块对象本身;
- 敏感度代数外部 oracle 精确值: delta_h(phi,target) 与 hidden_run_mean
  逐网格点独立复算 (R171 M-d 教训: 直接 oracle, 不靠间接秩测试);
- 结构单调性 delta_h > target 逐点验证 (机械计算非假设);
- 机械不可能旗标 (所需隐藏 run 均值低于全早期表最差单行) 双形态 fixture
  分别触发 + 结构单调性假形态 (当前不高于早期 — 无解释需求) + CI 缺失
  不可判定诚实路径 (n<MIN_CELL_N);
- CI 重叠谓词与载荷内 CI 机械自洽;
- manifest 公式指纹漂移 / 关键列缺失 typed fail-closed (绝不产空报告冒充
  成功); 空生产对齐宇宙 typed 传播;
- 渲染缺键存活 (R158 家族) + 报告确定性 (R13 家族: 同输入双装配逐字节 /
  e2e 双 out-dir 跨目录逐字节 — R179 Op2 硬化后语义);
- 夜刷链成员 (pinned-set 同步在 test_court_nightly_refresh 面钉住)。
纪律 (宪法 #2): 纯诊断披露, 不判定 d1_run 规则; fixture 驱动 slot 自足
(R10 纪律), 不依赖 gitignored 本地资产。
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from scripts.regime_run_survivorship_sensitivity_validation import (
    PHI_GRID,
    REPORT_STEM,
    RegimeRunSurvivorshipSensitivityError,
    assemble_payload,
    main,
    render_md,
    required_hidden_differential,
)

# ---------------------------------------------------------------------------
# fixture 世界: 15 会话 (R178/R179 同构阻断形状), 非对称罚分世界
# ---------------------------------------------------------------------------
CURRENT_LABELS = {
    "20260101": "crisis",
    "20260102": "crisis",
    "20260103": "normal",
    "20260104": "normal",
    "20260105": "risk_off",
    "20260106": "normal",
    "20260107": "normal",
    "20260108": "crisis",
    "20260109": "crisis",
    "20260110": "normal",
    "20260111": "normal",
    "20260112": "risk_off",
    "20260113": "normal",
    "20260114": "normal",
    "20260115": "normal",
}

FINGERPRINT = {
    "btst_breakout_sha256": "a" * 64,
    "exit_policy_sha256": "b" * 64,
}

GROUP_DAYS = {
    "d1_blip": ["20260106", "20260113"],
    "d1_run": ["20260103", "20260110"],
}

COST = 0.0065


def _rows(
    *,
    prefix: str,
    blip_gross: float,
    run_gross: float,
    rows_per_day: int = 20,
) -> pd.DataFrame:
    """d1_blip/d1_run 两组合成行 (含全部生产过滤列)."""
    rows: list[dict] = []
    for group, days in GROUP_DAYS.items():
        gross = blip_gross if group == "d1_blip" else run_gross
        for day in days:
            for i in range(rows_per_day):
                sym = f"{prefix}_{group}_{day}_{i}"
                rows.append(
                    {
                        "symbol": sym,
                        "ts_code": sym + ".SZ",
                        "signal_date": day,
                        "regime": "normal",
                        "trigger_strength": 0.75,
                        "signal_close": 10.0,
                        "gap_t1_open": 0.0,
                        "fillable": True,
                        "t1_unbuyable": False,
                        "t1_missing_bar": False,
                        "degraded": False,
                        "industry_missing": False,
                        "industry_name": "测试",
                        "st_name": False,
                        "excluded_ticker": False,
                        "price_ge_3": True,
                        "gate_blocked": False,
                        "gross_ret_t5": gross,
                        "exit_session_t5": 5.0,
                        "gross_ret_t10": gross,
                        "exit_session_t10": 10.0,
                    }
                )
    return pd.DataFrame(rows)


def _single_row(group: str, sym: str, day: str, gross: float) -> dict:
    base = _rows(prefix="t_", blip_gross=gross, run_gross=gross, rows_per_day=1)
    row = base.iloc[0].to_dict()
    row["symbol"] = sym
    row["ts_code"] = sym + ".SZ"
    row["signal_date"] = day
    return row


def _world(
    *,
    early_blip: float = 0.05,
    early_run: float = -0.05,
    cur_blip: float = 0.25,
    cur_run: float = -0.05,
    rows_per_day: int = 20,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """早期罚分 0.10 (gross); 当前罚分由 cur_blip 参数化 (World A 0.30 /
    World B 0.12 / World C 0.04 — 当前低于早期)."""
    current = _rows(
        prefix="c_", blip_gross=cur_blip, run_gross=cur_run,
        rows_per_day=rows_per_day,
    )
    early = _rows(
        prefix="e_", blip_gross=early_blip, run_gross=early_run,
        rows_per_day=rows_per_day,
    )
    return current, early


def _payload(tmp: Path, current: pd.DataFrame, early: pd.DataFrame) -> dict:
    history = tmp / "history.json"
    history.write_text(json.dumps(CURRENT_LABELS), encoding="utf-8")
    cm = tmp / "cm.json"
    cm.write_text(json.dumps({"formula_fingerprint": FINGERPRINT}), encoding="utf-8")
    em = tmp / "em.json"
    em.write_text(json.dumps({"formula_fingerprint": FINGERPRINT}), encoding="utf-8")
    return assemble_payload(current, early, history, cm, em)


# ---------------------------------------------------------------------------
# 零 fork 委托 — import 身份断言 (R176/R179 先例)
# ---------------------------------------------------------------------------
def test_core_analysis_surfaces_are_single_implementation() -> None:
    """_era_view/_point_penalty/指纹 loader/digest 附加是 R178 模块对象本身."""
    from scripts import regime_run_survivorship_sensitivity_validation as m
    from scripts import regime_run_cross_era_validation as x
    from scripts.regime_blocked_run_conditioning import analyze

    assert m._era_view is x._era_view
    assert m._point_penalty is x._point_penalty
    assert m.load_manifest_fingerprint is x.load_manifest_fingerprint
    assert m._attach_digest is x._attach_digest
    assert m.analyze is analyze


# ---------------------------------------------------------------------------
# 敏感度代数 — 纯函数外部 oracle
# ---------------------------------------------------------------------------
def test_required_hidden_differential_algebra_exact() -> None:
    """delta_h = (target − (1−phi)·P_obs)/phi 独立复算逐点精确."""
    for phi in PHI_GRID:
        expected = (0.30 - (1.0 - phi) * 0.10) / phi
        assert required_hidden_differential(0.10, 0.30, phi) == pytest.approx(expected)
    # 结构单调: target > P_obs 时 delta_h > target 对全部 phi 成立
    for phi in PHI_GRID:
        assert required_hidden_differential(0.10, 0.30, phi) > 0.30
        assert required_hidden_differential(0.10, 0.12, phi) > 0.12


# ---------------------------------------------------------------------------
# 载荷装配 — 组表/池/锚点外部 oracle
# ---------------------------------------------------------------------------
def test_payload_observed_surfaces_exact_oracle(tmp_path: Path) -> None:
    """双时代罚分/组表 n/池规模/行极值/日均值极距逐值精确 (独立复算)."""
    current, early = _world()
    payload = _payload(tmp_path, current, early)

    obs = payload["observed"]
    # 点罚分 = E[blip] − E[run] (net 差 = gross 差, 成本两侧相消)
    assert obs["early_point_penalty"] == pytest.approx(0.10)
    assert obs["current_point_penalty"] == pytest.approx(0.30)
    assert obs["e_blip_early"] == pytest.approx(0.05 - COST)
    # 池规模 = 组表 n 之和
    gt = payload["eras"]["early"]["group_table"]
    assert payload["pool"]["n_blip"] == gt["d1_blip"]["n"]
    assert payload["pool"]["n_run"] == gt["d1_run"]["n"]
    assert payload["pool"]["n_pool"] == gt["d1_blip"]["n"] + gt["d1_run"]["n"]
    # 行极值: 全 fixture 同值 → min = run net, max = blip net
    assert obs["row_min"] == pytest.approx(-0.05 - COST)
    assert obs["row_max"] == pytest.approx(0.05 - COST)
    # 日均值极距: 同组内各日均同值 → spread = max 组均值 − min 组均值
    assert obs["day_mean_spread"] == pytest.approx(0.10)
    assert obs["day_means_count"] == 4


def test_sensitivity_grid_exact_oracle_world_a(tmp_path: Path) -> None:
    """World A (P_cur=0.30): 网格逐点 delta_h/level/旗标精确 + 不可能区."""
    current, early = _world(cur_blip=0.25)
    payload = _payload(tmp_path, current, early)

    grid = {row["phi"]: row for row in payload["sensitivity_grid"]}
    assert sorted(grid) == sorted(PHI_GRID)
    e_blip = 0.05 - COST
    row_min = -0.05 - COST
    for phi in PHI_GRID:
        row = grid[phi]
        d_h = (0.30 - (1.0 - phi) * 0.10) / phi
        pt = row["to_current_point"]
        assert pt["required_hidden_differential"] == pytest.approx(d_h)
        assert pt["structural_above_target"] is True
        assert pt["hidden_run_mean_level"] == pytest.approx(e_blip - d_h)
        # World A: 所需 level 恒低于 run net (= row_min) → 旗标全燃
        assert pt["level_below_row_min_impossible"] is (
            (e_blip - d_h) < row_min
        )
        assert pt["level_below_row_min_impossible"] is True
    # 结构单调性谓词与网格逐点一致; 不可能区 = 全网格
    assert payload["verdict"]["structural_monotonicity_holds"] is True
    assert payload["verdict"]["impossible_region_phi"] == list(PHI_GRID)


def test_sensitivity_grid_world_b_hetero_no_impossible(tmp_path: Path) -> None:
    """World B (异质: 注入极端行): 小点差 + row_min 远低于 run 均值.

    早期 run 40 行中 1 行 gross=-0.60 (net -0.6065), 其余 -0.05 → run 均
    值 net -0.07025, P_obs = 0.0435 − (−0.07025) = 0.11375; row_min =
    -0.6065 → 不可能阈值 = e_blip − row_min = 0.65. 当前罚分 0.12 → 网格
    delta_h ∈ [0.12625, 0.23875] 全部低于阈值 → 不可能区空 + 单调性真.
    """
    current, early = _world(cur_blip=0.07)
    run_mask = early["symbol"].str.contains("_d1_run_")
    extreme_idx = early[run_mask].index[0]
    early.loc[extreme_idx, "gross_ret_t10"] = -0.60
    early.loc[extreme_idx, "gross_ret_t5"] = -0.60
    payload = _payload(tmp_path, current, early)
    verdict = payload["verdict"]
    assert verdict["structural_monotonicity_holds"] is True
    assert verdict["impossible_region_phi"] == []

    obs = payload["observed"]
    p_obs = 0.0435 - (-0.07025)
    assert obs["early_point_penalty"] == pytest.approx(p_obs)
    assert obs["row_min"] == pytest.approx(-0.60 - COST)
    grid = {row["phi"]: row for row in payload["sensitivity_grid"]}
    assert grid[0.5]["to_current_point"]["required_hidden_differential"] == pytest.approx(
        (0.12 - 0.5 * p_obs) / 0.5
    ) == pytest.approx(0.12625)
    assert grid[0.05]["to_current_point"]["required_hidden_differential"] == pytest.approx(
        (0.12 - 0.95 * p_obs) / 0.05
    ) == pytest.approx(0.23875)
    # 锚点反演: spread=0.1275 > target=0.12 → 可达
    assert obs["day_mean_spread"] == pytest.approx(0.0435 - (-0.084))
    assert payload["anchor_inversion"]["required_hidden_share_point"] is not None

    # P-p 钉住: targets.current_ci_low 的源是 current_ci.ci_low (非 ci_high)
    # — 精确相等断言 (非 approx): 同质/异质 fixture 的 CI 都退化为点
    # (双簇 bootstrap), 宽度仅浮点噪声 ~1e-17, approx 容差会吞掉 low/high
    # 差异 (R13/R178 同族 fixture 对称掩盖教训); 精确相等下源互换即刻暴露.
    ci_low = obs["current_ci"]["ci_low"]
    assert payload["targets"]["current_ci_low"] == ci_low
    ci_high = obs["current_ci"]["ci_high"]
    assert ci_low is not None and ci_high is not None
    grid_b = {row["phi"]: row for row in payload["sensitivity_grid"]}
    cl_row = grid_b[0.5]["to_current_ci_low"]
    expected_cl = (ci_low - 0.5 * p_obs) / 0.5
    assert (
        cl_row["required_hidden_differential"] == pytest.approx(expected_cl)
    )


def test_world_c_no_gap_to_explain(tmp_path: Path) -> None:
    """World C (P_cur=0.04 < P_obs=0.10): 无点差解释需求 — 单调性假形态."""
    current, early = _world(cur_blip=-0.01)
    payload = _payload(tmp_path, current, early)
    verdict = payload["verdict"]
    assert verdict["structural_monotonicity_holds"] is False
    assert verdict["impossible_region_phi"] == []
    assert "无幸存者解释需求" in verdict["statement"]


# ---------------------------------------------------------------------------
# CI 重叠谓词 — 与载荷内 CI 机械自洽 + 双形态
# ---------------------------------------------------------------------------
def test_ci_overlap_pure_dual_form() -> None:
    """_ci_overlap 纯函数双形态 + 不可判定 (同质 fixture 聚类 CI 退化为
    点, 形态面在纯函数覆盖 — fixture 级只留机械自洽)."""
    from scripts.regime_run_survivorship_sensitivity_validation import _ci_overlap

    assert _ci_overlap(
        {"ci_low": 0.0, "ci_high": 0.1}, {"ci_low": 0.05, "ci_high": 0.2}
    ) is True
    assert _ci_overlap(
        {"ci_low": 0.0, "ci_high": 0.1}, {"ci_low": 0.3, "ci_high": 0.4}
    ) is False
    assert _ci_overlap(
        {"ci_low": None, "ci_high": 0.1}, {"ci_low": 0.05, "ci_high": 0.2}
    ) is None


def test_ci_overlap_fixture_self_consistent(tmp_path: Path) -> None:
    """fixture 级: ci_overlap_present 由载荷 CI 两端机械复算 (自洽 oracle)."""
    cur_a, early_a = _world(cur_blip=0.25)
    pa = _payload(tmp_path, cur_a, early_a)
    lo_e = pa["observed"]["early_ci"]["ci_low"]
    hi_e = pa["observed"]["early_ci"]["ci_high"]
    lo_c = pa["observed"]["current_ci"]["ci_low"]
    hi_c = pa["observed"]["current_ci"]["ci_high"]
    expected = (
        lo_e is not None
        and hi_e is not None
        and lo_c is not None
        and hi_c is not None
        and (hi_e >= lo_c and hi_c >= lo_e)
    )
    assert pa["ci_overlap"]["present"] is expected


# ---------------------------------------------------------------------------
# 不可判定诚实路径 — CI 缺失 (n < MIN_CELL_N)
# ---------------------------------------------------------------------------
def test_ci_missing_indeterminate_path(tmp_path: Path) -> None:
    """n<MIN_CELL_N → 配对区间缺失: ci 面 None + 不可判定陈述 (不冒充判定)."""
    current, early = _world(cur_blip=0.25, rows_per_day=5)
    payload = _payload(tmp_path, current, early)

    assert payload["observed"]["early_ci"]["ci_low"] is None
    assert payload["observed"]["current_ci"]["ci_low"] is None
    assert payload["ci_overlap"]["present"] is None
    assert payload["targets"]["current_ci_low"] is None
    # 点目标仍可判 (组表点估计在场) — CI 低界目标面 null, 点目标面在场
    row = payload["sensitivity_grid"][0]
    assert row["to_current_point"] is not None
    assert row["to_current_ci_low"] is None
    assert "不可判定" in payload["verdict"]["statement"]


# ---------------------------------------------------------------------------
# 锚点反演 — 宽容差分下的所需隐藏份额
# ---------------------------------------------------------------------------
def _hetero_early_world(cur_blip: float) -> tuple[pd.DataFrame, pd.DataFrame]:
    """早期 blip 两日异质 (day1 +0.25 / day2 −0.05) → 日均值极距 > 罚分.

    早期: blip 日均值 +0.2435 / −0.0565, run 两日 −0.0565; 组均值 blip
    +0.10 / run −0.0565 → P_obs = 0.1565; spread = 0.30 (外部 oracle).
    当前: run 同 −0.0565, blip 两日同 cur_blip → P_cur = cur_blip − COST
    − (−0.0565).
    """
    early_rows: list[dict] = []
    day_gross = {"20260106": 0.25, "20260113": -0.05}
    for day, gross in day_gross.items():
        for i in range(20):
            sym = f"e_blip_{day}_{i}"
            early_rows.append(_single_row("e_blip", sym, day, gross))
    for day in GROUP_DAYS["d1_run"]:
        for i in range(20):
            sym = f"e_run_{day}_{i}"
            early_rows.append(_single_row("e_run", sym, day, -0.05))
    early = pd.DataFrame(early_rows)
    current = _rows(prefix="c_", blip_gross=cur_blip, run_gross=-0.05)
    return current, early


def test_anchor_inversion_exact_oracle(tmp_path: Path) -> None:
    """phi* = (target − P_obs)/(spread − P_obs) 独立复算; spread≤target → None."""
    # 异质世界: spread=0.30 > target=0.20 → 点目标反演可达, 外部 oracle 精确
    current, early = _hetero_early_world(cur_blip=0.15)
    payload = _payload(tmp_path, current, early)
    obs = payload["observed"]
    assert obs["day_mean_spread"] == pytest.approx(0.30)
    # blip 组均值 net = 0.10 − COST = 0.0935; run 组均值 net = −0.0565
    p_obs = (0.10 - COST) - (-0.05 - COST)
    assert obs["early_point_penalty"] == pytest.approx(p_obs)
    inv = payload["anchor_inversion"]
    expected = (0.20 - p_obs) / (0.30 - p_obs)
    assert inv["required_hidden_share_point"] == pytest.approx(expected)
    # CI 低界目标: 用载荷 CI 低界复算反演代数 (CI 本体由 R168 面钉住)
    ci_low = obs["current_ci"]["ci_low"]
    if ci_low is not None and ci_low < 0.30:
        assert inv["required_hidden_share_ci_low"] == pytest.approx(
            (ci_low - p_obs) / (0.30 - p_obs)
        )

    # 同质 World A: spread=0.10 < target=0.30 → 两目标反演均不可达 None
    cur_a, early_a = _world(cur_blip=0.25)
    pa = _payload(tmp_path, cur_a, early_a)
    assert pa["anchor_inversion"]["required_hidden_share_point"] is None
    assert pa["anchor_inversion"]["required_hidden_share_ci_low"] is None


# ---------------------------------------------------------------------------
# fail-closed — 指纹漂移 / 缺列 / 空宇宙
# ---------------------------------------------------------------------------
def test_manifest_fingerprint_drift_typed_reject(tmp_path: Path) -> None:
    """双表公式指纹不一致 → typed 拒绝 (R178 单一实现纪律)."""
    current, early = _world()
    history = tmp_path / "history.json"
    history.write_text(json.dumps(CURRENT_LABELS), encoding="utf-8")
    cm = tmp_path / "cm.json"
    cm.write_text(json.dumps({"formula_fingerprint": FINGERPRINT}), encoding="utf-8")
    em = tmp_path / "em.json"
    em.write_text(
        json.dumps(
            {"formula_fingerprint": {**FINGERPRINT, "exit_policy_sha256": "c" * 64}}
        ),
        encoding="utf-8",
    )
    with pytest.raises(
        RegimeRunSurvivorshipSensitivityError, match="fingerprint_drift"
    ):
        assemble_payload(current, early, history, cm, em)


def test_missing_required_column_typed_reject(tmp_path: Path) -> None:
    """gross_ret_t10 / signal_date 缺列 → typed 拒绝 (不静默当 0)."""
    current, early = _world()
    history = tmp_path / "history.json"
    history.write_text(json.dumps(CURRENT_LABELS), encoding="utf-8")
    cm = tmp_path / "cm.json"
    cm.write_text(json.dumps({"formula_fingerprint": FINGERPRINT}), encoding="utf-8")
    em = tmp_path / "em.json"
    em.write_text(json.dumps({"formula_fingerprint": FINGERPRINT}), encoding="utf-8")

    bad = current.drop(columns=["gross_ret_t10"])
    with pytest.raises(RegimeRunSurvivorshipSensitivityError, match="missing_column"):
        assemble_payload(bad, early, history, cm, em)

    bad2 = early.drop(columns=["signal_date"])
    with pytest.raises(RegimeRunSurvivorshipSensitivityError, match="missing_column"):
        assemble_payload(current, bad2, history, cm, em)


def test_empty_aligned_universe_typed_propagate(tmp_path: Path) -> None:
    """全 fillable=False → 生产对齐宇宙空 — R168 analyze typed 拒绝传播."""
    current, early = _world()
    early = early.copy()
    early["fillable"] = False
    history = tmp_path / "history.json"
    history.write_text(json.dumps(CURRENT_LABELS), encoding="utf-8")
    cm = tmp_path / "cm.json"
    cm.write_text(json.dumps({"formula_fingerprint": FINGERPRINT}), encoding="utf-8")
    em = tmp_path / "em.json"
    em.write_text(json.dumps({"formula_fingerprint": FINGERPRINT}), encoding="utf-8")
    with pytest.raises(SystemExit, match="empty_production_aligned_universe"):
        assemble_payload(current, early, history, cm, em)


# ---------------------------------------------------------------------------
# 渲染 — 缺键存活 + 确定性
# ---------------------------------------------------------------------------
def test_render_survives_missing_keys(tmp_path: Path) -> None:
    """payload 缺渲染键 → 存活不崩 (R158 家族; 显示层不掩盖装配层缺陷)."""
    current, early = _world()
    payload = _payload(tmp_path, current, early)
    stripped = {
        k: v
        for k, v in payload.items()
        if k not in ("sensitivity_grid", "anchor_inversion")
    }
    text = render_md(stripped, "20260911")
    assert "# R168 d1_run 时代条件性 — 幸存者敏感度界 — 20260911" in text
    assert "公式指纹一致性" in text


def test_payload_and_render_deterministic(tmp_path: Path) -> None:
    """同输入双装配逐字节 (R13 家族: dict 相等 + 渲染两次逐字节)."""
    current, early = _world()
    p1 = _payload(tmp_path, current, early)
    p2 = _payload(tmp_path, current, early)
    assert p1 == p2
    r1 = render_md(p1, "20260911")
    r2 = render_md(p2, "20260911")
    assert r1 == r2


# ---------------------------------------------------------------------------
# e2e — main() 双 out-dir 跨目录逐字节 (R179 Op2 硬化语义)
# ---------------------------------------------------------------------------
def _write_world_tables(
    tmp: Path, current: pd.DataFrame, early: pd.DataFrame
) -> dict[str, Path]:
    cur_path = tmp / "current.csv.gz"
    early_path = tmp / "early.csv.gz"
    current.to_csv(cur_path, index=False, compression="gzip")
    early.to_csv(early_path, index=False, compression="gzip")
    history = tmp / "history.json"
    history.write_text(json.dumps(CURRENT_LABELS), encoding="utf-8")
    cm = tmp / "cm.json"
    cm.write_text(json.dumps({"formula_fingerprint": FINGERPRINT}), encoding="utf-8")
    em = tmp / "em.json"
    em.write_text(json.dumps({"formula_fingerprint": FINGERPRINT}), encoding="utf-8")
    return {
        "current": cur_path,
        "early": early_path,
        "history": history,
        "cm": cm,
        "em": em,
    }


def _cli_args(paths: dict[str, Path], out_dir: Path) -> list[str]:
    return [
        "--court-table", str(paths["current"]),
        "--early-court-table", str(paths["early"]),
        "--regime-history", str(paths["history"]),
        "--current-manifest", str(paths["cm"]),
        "--early-manifest", str(paths["em"]),
        "--out-dir", str(out_dir),
        "--date", "20260911",
    ]


def test_main_double_run_byte_identical_across_out_dirs(tmp_path: Path) -> None:
    """两次独立运行 (不同 out-dir) 报告逐字节相等 — 同跑只证稳定."""
    current, early = _world()
    paths = _write_world_tables(tmp_path, current, early)
    out1 = tmp_path / "out1"
    out2 = tmp_path / "out2"
    rc1 = main(_cli_args(paths, out1))
    rc2 = main(_cli_args(paths, out2))
    assert rc1 == 0
    assert rc2 == 0
    stem = REPORT_STEM
    for suffix in (".md", ".json"):
        b1 = (out1 / f"{stem}_20260911{suffix}").read_bytes()
        b2 = (out2 / f"{stem}_20260911{suffix}").read_bytes()
        assert b1 == b2
        assert len(b1) > 0


# ---------------------------------------------------------------------------
# 夜刷链成员 (pinned-set 全集钉住在 test_court_nightly_refresh 面)
# ---------------------------------------------------------------------------
def test_nightly_chain_membership() -> None:
    from src.screening.offensive.court_nightly_refresh import DIAGNOSTIC_SCRIPTS

    assert "scripts/regime_run_survivorship_sensitivity_validation.py" in DIAGNOSTIC_SCRIPTS


# ---------------------------------------------------------------------------
# R180 Op2 对抗审查钉住 — 探针实锤的无牙缺口 (P-f/P-j/P-k/P-l/P-p)
# ---------------------------------------------------------------------------
def test_phi_grid_literal_preregistered() -> None:
    """P-k 钉住: phi 网格是预注册披露参数 — 字面漂移 (0.10→0.12) 即暴露.

    PHI_GRID 是载荷与渲染的共享常量, 测试经同一 symbol 消费时字面漂移
    不可见 (自引用); 网格点集本身是轴定义的一部分, 逐值钉死.
    """
    from scripts.regime_run_survivorship_sensitivity_validation import (
        PHI_GRID as _GRID,
    )

    assert _GRID == (0.05, 0.10, 0.15, 0.20, 0.30, 0.50)


def test_render_grid_row_column_order_and_exact_values(tmp_path: Path) -> None:
    """P-j 钉住: 渲染网格列序 (delta_h 列在 level 列左) + 精确形态.

    R171 M-f / R177 P-j / R178 P-j / R179 P-j 同族显示面缺口第四次复活 —
    列互换或值漂移在此当场暴露 (点目标三列子串精确锚定).
    """
    from scripts.regime_run_survivorship_sensitivity_validation import render_md

    current, early = _world(cur_blip=0.25)
    payload = _payload(tmp_path, current, early)
    text = render_md(payload, "20260911")
    # World A (同质): phi=0.50 行 — delta_h=+50.00% 在 level=-45.65% 之前
    assert "| 0.50 | 40 | +50.00% | -45.65% | ⚠ |" in text
    assert "| 0.05 | 4 | +410.00% | -405.65% | ⚠ |" in text
    # 互换形态 (探针 P-j 的输出形态) 不得出现
    assert "| 0.50 | 40 | -45.65% | +50.00% |" not in text


def test_row_min_full_era_anchor_and_asymmetric_pool(tmp_path: Path) -> None:
    """P-f + P-l 钉住: row_min 锚点覆盖全时代 (d2 极端行) + 非对称池计数.

    P-f: 极端行在 d1 池之外 (d2_blip, 独立信号日) — 全时代最差单行
    -0.6065 显著低于 d1 池内最小值 -0.0565; 锚点面收缩 (d1_run 池) 在此
    当场暴露 (不可能区从 [0.05,0.10] 扩成全网格).
    P-l: 池计数非对称 (blip 40 / run 35) — n_blip/n_run 互换在此暴露.
    """
    current, early = _world(cur_blip=0.25)
    run_idx = early[early["symbol"].str.contains("_d1_run_")].index[:5]
    early = early.drop(run_idx)
    extreme = _single_row("d2_blip", "e_d2_blip_extreme", "20260104", -0.60)
    early = pd.concat([early, pd.DataFrame([extreme])], ignore_index=True)
    payload = _payload(tmp_path, current, early)

    obs = payload["observed"]
    assert obs["row_min"] == pytest.approx(-0.60 - COST)
    pool = payload["pool"]
    assert pool["n_blip"] == 40
    assert pool["n_run"] == 35
    assert pool["n_pool"] == 75
    # 锚点面: 阈值 = e_blip − row_min = 0.65; delta_h 网格
    # 1.367/0.687/1.433/1.100/0.767/0.500 → 不可能区恰为 [0.05..0.30]
    # (P-f 收缩后 row_min=-0.0565 → 阈值=0.10 → 全网格燃烧 — 即刻暴露)
    assert payload["verdict"]["impossible_region_phi"] == [
        0.05, 0.10, 0.15, 0.20, 0.30,
    ]
    # 锚点反演: spread = 0.0435 − (−0.6065) = 0.65 > target=0.30
    assert obs["day_mean_spread"] == pytest.approx(0.0435 - (-0.60 - COST))
    inv = payload["anchor_inversion"]
    assert inv["required_hidden_share_point"] == pytest.approx(0.20 / 0.55)
    # φ=0.50 处 level=-0.4565 > row_min=-0.6065 → 旗标假 (与 World A 相反形态)
    grid = {row["phi"]: row for row in payload["sensitivity_grid"]}
    assert (
        grid[0.5]["to_current_point"]["level_below_row_min_impossible"] is False
    )
