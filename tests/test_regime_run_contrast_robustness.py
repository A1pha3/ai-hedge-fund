"""regime_run_contrast_robustness — d1_run 决定性对比的规格稳健性审计 (R170 Op1).

R168 的 d1_blip vs d1_run 配对聚类差是工作线首个统计决定性对比, 但只受过
单一规格检验。本工具对其做三面规格攻击 (纯诊断, 宪法 #2 只披露不判定):
- placebo_circular_shift: label 会话序全部循环移位的穷举精确置换 (零 RNG,
  k=0 恒等复现自检) — 检验阻断日时序识别力;
- influence_leave_one_day_out: 逐 d1_run 信号日剔除重算罚分 — 检验脆弱性
  集中度 (单日剔除翻符号 = 脆弱);
- definition_sensitivity: run≥3 阈值 / 纯 crisis vs 含 risk_off 连跑分解 /
  d1 桶内精确连跑长度剂量反应 — 检验轴定义敏感性。

钉死的正确性面:
- 轴几何: run_geometry 与 blocked_run_group 全形态等价 (委托单一实现);
- placebo: k=0 恒等 / 极端世界秩最小 / 平坦世界无识别力 / 逐字节确定性 /
  单会话退化披露;
- 影响集中度: 已知主导日世界翻符号计数与份额精确算术 / MIN_CELL_N 守卫;
- 定义敏感度: 阈值重分 n 会计 / label 分解算术 / 剂量反应表;
- 渲染存活: 缺组键 '—' 不崩 / falsy-zero 显示 (R158 家族);
- fail-closed: 空 production_aligned / history 缺失 typed 拒绝;
- 报告确定性 (R13 家族)。
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from scripts.regime_blocked_run_conditioning import blocked_run_group
from scripts.regime_run_contrast_robustness import (
    REPORT_STEM,
    RegimeRunRobustnessError,
    analyze,
    definition_sensitivity,
    dose_response,
    influence_leave_one_day_out,
    main,
    placebo_circular_shift,
    render_md,
    run_threshold_3_groups,
)
from scripts.winrate_payoff_decomposition import MIN_CELL_N, production_aligned

SESSIONS = [f"202601{d:02d}" for d in range(1, 16)]  # 15 会话小世界
REGIMES = {
    "20260101": "crisis",
    "20260102": "crisis",   # run=2 → 0103 是 d1_run
    "20260103": "normal",
    "20260104": "normal",
    "20260105": "risk_off",  # 单日闪断 → 0106 是 d1_blip
    "20260106": "normal",
    "20260107": "normal",
    "20260108": "normal",
    "20260109": "normal",
    "20260110": "normal",
    "20260111": "normal",
    "20260112": "normal",
    "20260113": "normal",
    "20260114": "normal",
    "20260115": "normal",
}


def _event_row(day: str, regime: str, gross10: float, *, symbol: str | None = None,
               strength: float = 0.75, gross5: float | None = None) -> dict:
    blocked = regime in ("crisis", "risk_off")
    return {
        "symbol": symbol or f"S{day}",
        "ts_code": (symbol or f"S{day}") + ".SZ",
        "signal_date": day,
        "regime": regime,
        "trigger_strength": strength,
        "signal_close": 10.0,
        "gap_t1_open": 0.0,
        "fillable": not blocked,
        "t1_unbuyable": False,
        "t1_missing_bar": False,
        "degraded": False,
        "industry_missing": False,
        "industry_name": "测试",
        "st_name": False,
        "excluded_ticker": False,
        "price_ge_3": True,
        "gate_blocked": blocked,
        "gross_ret_t10": gross10,
        "gross_ret_t5": gross5 if gross5 is not None else gross10,
    }


def _world(net_by_day: dict[str, list[float]], regimes: dict[str, str]) -> pd.DataFrame:
    """按日净收益目标构造事件表 (毛收益 = 净 + 0.0065 往返费); 净行只放 normal 日."""
    rows = [
        _event_row(day, regime, 0.0)
        for day, regime in regimes.items()
        if regime != "normal"
    ]
    for day, nets in net_by_day.items():
        for i, net in enumerate(nets):
            rows.append(_event_row(day, "normal", net + 0.0065, symbol=f"S{day}_{i}"))
    return pd.DataFrame(rows)


def _history(tmp_path: Path, regimes: dict[str, str] | None = None) -> Path:
    p = tmp_path / "regime_history.json"
    p.write_text(json.dumps(regimes or REGIMES), encoding="utf-8")
    return p


def _rows(world: pd.DataFrame, regimes: dict[str, str]) -> pd.DataFrame:
    """事件表 → t10 净收益行 + blocked_run_group 归属 (工具消费同款管道)."""
    from scripts.regime_blocked_run_conditioning import run_groups
    from scripts.regime_proximity_conditioning import _horizon_rows

    u = production_aligned(world)
    sessions = sorted(regimes)
    prox = run_groups(pd.unique(u["signal_date"].astype(str)), sessions, regimes)
    return _horizon_rows(u, 10, prox)


def _big_extreme_world() -> tuple[dict[str, str], dict[str, list[float]]]:
    """39 会话大世界 (30+ 样本, R153 门槛): run 阻断 0101-0102 / blip 闪断 0120.

    d1_run (0103) 全深负 ×3 / d1_blip (0121) 全正 ×3 / 其余中性填充。
    """
    regimes: dict[str, str] = {f"202601{d:02d}": "normal" for d in range(1, 40)}
    regimes["20260101"] = "crisis"
    regimes["20260102"] = "crisis"
    regimes["20260120"] = "risk_off"
    nets: dict[str, list[float]] = {}
    for d in range(24, 40):
        nets[f"202601{d:02d}"] = [0.005, -0.005]
    nets["20260103"] = [-0.05] * (MIN_CELL_N + 1)
    nets["20260121"] = [0.03] * (MIN_CELL_N + 1)
    return regimes, nets


class TestRunGeometryEquivalence:
    def test_all_forms_equivalent_to_blocked_run_group(self):
        from scripts.regime_blocked_run_conditioning import run_geometry

        labels = dict(REGIMES)
        for day in SESSIONS:
            form, dist, run_len, run_labels = run_geometry(day, SESSIONS, labels)
            kind = "blip" if run_len == 1 else "run"
            if form == "normal":
                expected = (
                    f"d1_{kind}" if dist == 1
                    else f"d2_{kind}" if dist == 2
                    else f"d3p_{kind}" if dist <= 5
                    else "d6p"
                )
            else:
                expected = form  # blocked / unknown / no_prior
            assert blocked_run_group(day, SESSIONS, labels) == expected, day

    def test_geometry_values_pinned(self):
        from scripts.regime_blocked_run_conditioning import run_geometry

        labels = dict(REGIMES)
        assert run_geometry("20260103", SESSIONS, labels) == (
            "normal", 1, 2, ("crisis", "crisis")
        )
        assert run_geometry("20260106", SESSIONS, labels)[2:] == (1, ("risk_off",))
        assert run_geometry("20260101", SESSIONS, labels)[0] == "blocked"
        assert run_geometry("20260201", SESSIONS, labels)[0] == "unknown"
        assert run_geometry("20260104", SESSIONS, labels)[1] == 2


class TestPlaceboCircularShift:
    def test_k_zero_identity(self):
        rows = _rows(_world(
            {"20260103": [-0.05, -0.05], "20260106": [0.03, 0.03]}, REGIMES
        ), REGIMES)
        result = placebo_circular_shift(rows, SESSIONS, dict(REGIMES))
        # k=0 移位恒等复现观测点估计 (自检); 双侧 p 至少含恒等移位
        assert result["observed_delta"] == pytest.approx(result["identity_shift_delta"])
        assert result["n_shifts"] == len(SESSIONS)
        assert result["p_value"] >= 1 / result["n_valid_shifts"]

    def test_extreme_world_rank_is_minimal(self):
        regimes, nets = _big_extreme_world()
        rows = _rows(_world(nets, regimes), regimes)
        result = placebo_circular_shift(rows, sorted(regimes), regimes)
        assert result["observed_delta"] > 0
        # 恒等移位 (及其至多一个镜像平手) 是唯一达到 |观测| 的移位
        assert result["p_value"] <= 2 / result["n_valid_shifts"]

    def test_flat_world_no_identification(self):
        nets = {f"202601{d:02d}": [0.001, -0.001] for d in range(3, 16)}
        rows = _rows(_world(nets, REGIMES), REGIMES)
        result = placebo_circular_shift(rows, SESSIONS, dict(REGIMES))
        # 平坦世界: 观测罚分为 0 → 全部移位 |delta| ≥ 0 → p = 1 (无识别力)
        assert result["p_value"] == pytest.approx(1.0)

    def test_deterministic(self):
        rows = _rows(_world(
            {"20260103": [-0.05, -0.05], "20260106": [0.03, 0.03]}, REGIMES
        ), REGIMES)
        a = placebo_circular_shift(rows, SESSIONS, dict(REGIMES))
        b = placebo_circular_shift(rows, SESSIONS, dict(REGIMES))
        assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)

    def test_single_session_degenerate(self):
        regimes = {"20260101": "normal"}
        rows = _rows(_world({"20260101": [0.01]}, regimes), regimes)
        result = placebo_circular_shift(rows, ["20260101"], regimes)
        assert result["placebo_undefined"] is True


class TestInfluenceLeaveOneDayOut:
    def test_dominant_day_flips_sign(self):
        regimes = {
            "20260101": "crisis",
            "20260102": "crisis",    # run A=2 → 0103 是 d1_run
            "20260106": "crisis",
            "20260107": "crisis",
            "20260108": "crisis",    # run B=3 → 0109 是 d1_run
            "20260113": "risk_off",  # blip → 0114 是 d1_blip
            **{f"202601{d:02d}": "normal" for d in (3, 4, 5, 9, 10, 11, 12, 14, 15)},
        }
        nets = {
            "20260103": [0.04] * (MIN_CELL_N + 1),    # 填充 run 日: 正收益 (剔除主导日后翻符号的关键)
            "20260109": [-0.50] * (MIN_CELL_N + 1),   # 主导 run 日: 深亏集中
            "20260114": [0.03] * (MIN_CELL_N + 1),    # blip 基线
        }
        rows = _rows(_world(nets, regimes), regimes)
        result = influence_leave_one_day_out(rows)
        run_mean = (0.04 + (-0.50)) / 2
        delta_full = 0.03 - run_mean
        assert result["delta_full"] == pytest.approx(delta_full)
        assert result["delta_full"] > 0
        assert result["n_days"] == 2
        # 剔除主导日: run 侧只剩填充日 (mean=+0.04) → delta_wo = 0.03-0.04 < 0 → 翻符号
        assert result["sign_flip_days"] == 1
        assert result["top_days"][0]["date"] == "20260109"
        assert result["top_days"][0]["delta_without"] == pytest.approx(-0.01)
        # 逐日份额精确分解: Σ share = 1; 主导日 share = 31·(0.03+0.50)/(62·0.26)
        expected_share = 31 * (0.03 + 0.50) / (62 * delta_full)
        assert result["top_days"][0]["share"] == pytest.approx(expected_share)
        assert result["top1_penalty_share"] == pytest.approx(expected_share)
        assert result["top1_penalty_share"] > 1.0

    def test_diffuse_world_no_flips(self):
        regimes = dict(REGIMES)
        nets = {
            "20260103": [-0.05] * (MIN_CELL_N + 1),  # 均匀深负, 无单点主导
            "20260106": [0.03] * (MIN_CELL_N + 1),
        }
        rows = _rows(_world(nets, regimes), regimes)
        result = influence_leave_one_day_out(rows)
        assert result["delta_full"] > 0
        assert result["sign_flip_days"] == 0

    def test_min_cell_n_guard(self):
        regimes = dict(REGIMES)
        nets = {"20260103": [-0.05] * MIN_CELL_N, "20260106": [0.03] * MIN_CELL_N}
        rows = _rows(_world(nets, regimes), regimes)
        result = influence_leave_one_day_out(rows)
        # 剔除唯一 d1_run 日后 run 侧 n=0 < MIN_CELL_N → delta_without=None (R153)
        assert result["top_days"][0]["delta_without"] is None


class TestDefinitionSensitivity:
    def test_run_threshold_3_excludes_run2(self):
        nets = {"20260103": [-0.05, -0.05], "20260106": [0.03, 0.03]}
        rows = _rows(_world(nets, REGIMES), REGIMES)
        rows3 = run_threshold_3_groups(rows, SESSIONS, dict(REGIMES))
        assert (rows3["group"] == "d1_run").sum() == 0
        assert (rows3["group"] == "d1_run3").sum() == 0
        assert (rows3["group"] == "d1_blip").sum() == 2

    def test_run_threshold_3_keeps_run3(self):
        regimes = {
            "20260101": "crisis",
            "20260102": "crisis",
            "20260103": "crisis",   # run=3 → 0104 是 d1_run3
            "20260107": "risk_off",  # blip → 0108
            **{f"202601{d:02d}": "normal" for d in (4, 5, 6, 8, 9, 10, 11, 12, 13, 14, 15)},
        }
        nets = {"20260104": [-0.05, -0.05], "20260108": [0.03, 0.03]}
        rows = _rows(_world(nets, regimes), regimes)
        rows3 = run_threshold_3_groups(rows, sorted(regimes), regimes)
        assert (rows3["group"] == "d1_run3").sum() == 2
        assert (rows3["group"] == "d1_blip").sum() == 2

    def test_label_decomposition(self):
        regimes = {
            "20260101": "risk_off",
            "20260102": "crisis",   # 混合连跑 → 0103 含 risk_off
            **{f"202601{d:02d}": "normal" for d in range(3, 16)},
        }
        nets = {"20260103": [-0.05, -0.04]}
        rows = _rows(_world(nets, regimes), regimes)
        dec = definition_sensitivity(rows, SESSIONS, regimes)["label_decomposition"]
        assert dec["contains_risk_off"]["n"] == 2
        assert dec["pure_crisis"]["n"] == 0
        assert dec["pure_crisis"]["expectancy"] is None

    def test_dose_response_run_lengths(self):
        regimes = {f"202601{d:02d}": "normal" for d in range(1, 16)}
        regimes.update({
            "20260101": "crisis", "20260102": "crisis",                    # run=2 → 0103
            "20260105": "crisis", "20260106": "crisis", "20260107": "crisis",   # run=3 → 0108
            "20260110": "crisis", "20260111": "crisis", "20260112": "crisis",
            "20260113": "crisis",                                          # run=4 → 0114
        })
        nets = {
            "20260103": [-0.05, -0.05],
            "20260108": [-0.02, -0.02],
            "20260114": [-0.01, -0.01],
        }
        rows = _rows(_world(nets, regimes), regimes)
        table = dose_response(rows, sorted(regimes), regimes)
        by_len = {row["run_len"]: row for row in table}
        assert by_len[2]["n"] == 2
        assert by_len[3]["n"] == 2
        assert by_len["4+"]["n"] == 2
        assert by_len[1] == {"run_len": 1, "n": 0, "winrate": None, "expectancy": None}


class TestAnalyzeRenderMain:
    def test_analyze_deterministic_payload(self, tmp_path):
        regimes, nets = _big_extreme_world()
        world = _world(nets, regimes)
        hist = _history(tmp_path, regimes)
        a = analyze(world, hist)
        b = analyze(world, hist)
        assert json.dumps(a, sort_keys=True, ensure_ascii=False) == json.dumps(
            b, sort_keys=True, ensure_ascii=False
        )
        assert a["schema_version"] == 1
        assert a["aligned_n"] > 0
        for key in ("placebo_circular_shift", "influence_leave_one_day_out",
                    "definition_sensitivity", "observed", "axis_definition"):
            assert key in a
        assert a["observed"]["t10"]["delta_ci"]["ci_low"] is not None  # 30+ 样本 CI 在场

    def test_render_survives_missing_keys_and_falsy_zero(self, tmp_path):
        regimes, nets = _big_extreme_world()
        payload = analyze(_world(nets, regimes), _history(tmp_path, regimes))
        payload["placebo_circular_shift"]["t10"].pop("observed_delta", None)
        payload["influence_leave_one_day_out"]["delta_full"] = 0.0
        md = render_md(payload, "20260910")
        assert "—" in md
        assert "+0.00%" in md  # falsy-zero 显示 (R158 家族)

    def test_p_value_render_form(self):
        from scripts.regime_run_contrast_robustness import _p_value

        assert _p_value(0.14819350887936314) == "0.148"
        assert _p_value(1 / 3) == "0.333"
        assert _p_value(0) == "0.000"
        assert _p_value(None) == "—"
        assert _p_value(float("nan")) == "—"
        assert _p_value(True) == "—"  # bool 形态守卫 (R158 家族)
        assert _p_value(1.5) == "1.500"  # 越界形态仍渲染 (披露面不静默)

    def test_main_writes_reports(self, tmp_path):
        regimes, nets = _big_extreme_world()
        court = tmp_path / "event_table.csv.gz"
        _world(nets, regimes).to_csv(court, index=False, compression="gzip")
        rc = main([
            "--court-table", str(court),
            "--regime-history", str(_history(tmp_path, regimes)),
            "--report-dir", str(tmp_path),
        ])
        assert rc == 0
        assert (tmp_path / f"{REPORT_STEM}_20260910.md").exists()
        assert (tmp_path / f"{REPORT_STEM}_20260910.json").exists()

    def test_empty_universe_typed(self, tmp_path):
        empty = pd.DataFrame([_event_row("20260103", "normal", 0.0, symbol="X")])
        empty["gross_ret_t10"] = None
        empty["gross_ret_t5"] = None
        with pytest.raises(RegimeRunRobustnessError):
            analyze(empty, _history(tmp_path))

    def test_missing_history_typed(self, tmp_path):
        regimes, nets = _big_extreme_world()
        with pytest.raises(SystemExit) as exc_info:  # RegimeProximityError 族
            analyze(_world(nets, regimes), tmp_path / "nope.json")
        assert "regime_history" in str(exc_info.value)


class TestAdversarialPinsR171:
    """R171 Op2 对抗收口: 变异探针有牙实证后的四枚形态钉住.

    探针定谳 (隔离 slot 实跑): M-b ('<'→'<=', 20 passed 无牙实锤) 与
    M-c (run_labels 反序 insert(0), 41 passed 无牙实锤) 为真实钉住缺口;
    M-a (share 分母 N→参与日数) 与 M-d (_delta_point 轴 fork→proximity)
    意外有牙 (分别被 top1 精确值 oracle / 极端世界秩测试间接钉住, M-d
    3 failed) — 仍补直连 oracle 钉住作防御纵深 (实现正确仅因实现正确
    无测试保障 = R167/R169 同族教训)。

    审查排除项成文: placebo eps 平手容差只影响与观测精确平手的移位计数
    (方向保守: 只会抬高 p, 不制造假极端); 离散经验分位 sorted[floor(q·
    (m−1))] 无插值已由确定性字节测试覆盖; 翻符号方向谓词与 threshold/剂量
    分桶边界已有牙 (互换即 RED, 审查期复证)。
    """

    def test_min_cell_n_boundary_kept_exact(self):
        """P-b: kept==MIN_CELL_N 恰边界必须产出 delta_without (不是 None).

        '<'→'<=' 变异探针无牙实证 (20 passed) 后钉住: run 侧 31 样本跨
        两日 (1+30), 剔除单样本日后 kept=30 恰在门槛上 — 合法剔除。
        """
        regimes = {
            "20260101": "crisis",
            "20260102": "crisis",    # run A=2 → 0103
            "20260106": "crisis",
            "20260107": "crisis",    # run B=2 → 0108
            "20260111": "risk_off",  # blip → 0112
            **{f"202601{d:02d}": "normal" for d in (3, 4, 5, 8, 9, 10, 12, 13, 14, 15)},
        }
        nets = {
            "20260103": [-0.02],                       # 单样本日 (被剔除日)
            "20260108": [-0.05] * MIN_CELL_N,          # kept 恰 == MIN_CELL_N
            "20260112": [0.03] * MIN_CELL_N,
        }
        rows = _rows(_world(nets, regimes), regimes)
        result = influence_leave_one_day_out(rows)
        assert result["n_days"] == 2
        by_date = {st["date"]: st for st in result["top_days"]}
        assert by_date["20260103"]["delta_without"] is not None

    def test_run_labels_nearest_first_order(self):
        """P-c: run_labels 自近及远序钉住 (混合连跑双 label 才有区分度).

        既有钉住形态全同 label ('crisis','crisis') 或单 label ('risk_off',)
        — 反序变异 (insert(0)) 在 41 测下存活; 混合连跑钉住后 RED。
        label_decomposition 的 'risk_off' in run_labels 判属对序不敏感,
        故该序契约此前零消费零钉住 — 本测试使其成为显式契约。
        """
        from scripts.regime_blocked_run_conditioning import run_geometry

        regimes = {
            "20260101": "risk_off",
            "20260102": "crisis",   # 混合连跑 (近端 crisis, 远端 risk_off) → 0103
            **{f"202601{d:02d}": "normal" for d in range(3, 16)},
        }
        assert run_geometry("20260103", SESSIONS, regimes)[3] == ("crisis", "risk_off")

    def test_delta_point_matches_r168_group_table_oracle(self):
        """P-d: placebo 点估计与 R168 group table 外部 oracle 逐值一致.

        k=0 恒等只证 placebo 内部自洽 (同轴错则双双放行); 本测试把
        _delta_point 直接钉在 blocked-run 轴的 group 列算术上 — 轴 fork
        (proximity 单维替代) 不再依赖间接的世界工程读数才暴露。
        """
        nets = {"20260103": [-0.05, -0.05], "20260106": [0.03, 0.03]}
        rows = _rows(_world(nets, REGIMES), REGIMES)
        expected = (
            rows.loc[rows["group"] == "d1_blip", "net"].mean()
            - rows.loc[rows["group"] == "d1_run", "net"].mean()
        )
        from scripts.regime_run_contrast_robustness import _delta_point

        assert _delta_point(rows, SESSIONS, dict(REGIMES)) == pytest.approx(expected)

    def test_share_sums_to_one_telescoping(self):
        """P-a 排除项的显式化: 份额全和恒 1 (telescoping) 多日世界钉住.

        M-a 探针 (分母 N→参与日数) 实为有牙 — top1 精确值 oracle 间接
        钉住 (1 failed 实证); 本测试把可加性本身升为显式契约, 多日世界
        下 Σshare == 1 逐值断言。
        """
        regimes = {
            "20260101": "crisis",
            "20260102": "crisis",    # run A=2 → 0103
            "20260106": "crisis",
            "20260107": "crisis",
            "20260108": "crisis",    # run B=3 → 0109
            "20260113": "risk_off",  # blip → 0114
            **{f"202601{d:02d}": "normal" for d in (3, 4, 5, 9, 10, 11, 12, 14, 15)},
        }
        nets = {
            "20260103": [0.04] * 5,
            "20260109": [-0.50] * (MIN_CELL_N + 1),
            "20260114": [0.03] * MIN_CELL_N,
        }
        rows = _rows(_world(nets, regimes), regimes)
        result = influence_leave_one_day_out(rows)
        total_share = sum(
            st["share"] for st in result["top_days"]  # top3 含全部参与日时
            if st["share"] is not None
        ) if result["n_days"] <= 3 else None
        assert total_share == pytest.approx(1.0)
