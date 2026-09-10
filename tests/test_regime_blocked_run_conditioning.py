"""regime_blocked_run_conditioning — 阻断连跑条件化轴算术 + 判读装配 (R168 Op1).

R166 邻近度轴的 Observe 探针实锤 d1 聚合组是混合总体 (单日闪断后 vs 连续
危机后), 本工具把「前导阻断连跑长度」升为显式条件化轴. 钉死的正确性面:
- 轴算术十形态: d1_blip/d1_run/d2_blip/d2_run/d3p_blip/d3p_run/d6p/
  no_prior/blocked/unknown (连跑=连续阻断日计数, 被 normal 日打断重新计);
- 参数化泛化助手: grouped_delta/split_half_stability 泛化后 R166 特化包装
  行为与键名契约零漂移;
- 统计装配: 配对差方向 / n<MIN_CELL_N → None / 去 d1_run 残余池精确算术;
- 判读纪律: split-half 只判定资格不授权 / falsy-zero 显示 (R158 家族);
- fail-closed: 空 production_aligned / history 缺失/畸形 typed 拒绝;
  报告确定性 (R13 家族: 同输入两次调用逐字节同 payload)。
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from scripts.regime_blocked_run_conditioning import (
    GROUP_LABELS,
    RUN_GROUPS,
    _fmt,
    _ratio,
    analyze,
    blocked_run_group,
    main,
    render_md,
)
from scripts.regime_proximity_conditioning import (
    d1_vs_d2_5_delta,
    load_regime_history,
    split_half_verdict,
)
from scripts.winrate_payoff_decomposition import production_aligned

SESSIONS = [f"202601{d:02d}" for d in range(1, 16)]  # 15 会话工作世界
REGIMES = {
    "20260101": "crisis",
    "20260102": "crisis",   # 连跑 run=2 → 0103 是 d1_run (注释与码同宽: 尾日连跑=2)
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


def _simple_events() -> pd.DataFrame:
    """十五会话小世界 (非对称 fixture, R13 教训): 各组落点 + 方向工程化.

    d1_blip (0106) 净 +3%×2 / d1_run (0103) 净 −5%×2 → 配对差显著为正;
    d2_run (0104) 净 +2%; d2_blip 无落点 (n=0 披露行);
    d3p_blip (0108) 净 +1%; d6p (0115) 净 0 (falsy-zero 渲染面)。
    """
    net_targets = {
        "20260103": [-0.05, -0.05],   # d1_run (距 0102 阻断尾日 1 会话, run=2)
        "20260104": [0.02],           # d2_run (距 0102 尾日 2 会话)
        "20260106": [0.03, 0.03],     # d1_blip (距 0105 单日闪断 1 会话, run=1)
        "20260108": [0.01],           # d3p_blip
        "20260115": [0.0],            # d6p (距 0105 共 8 会话)
    }
    rows = [
        _event_row("20260101", "crisis", 0.0),
        _event_row("20260102", "crisis", 0.0),
        _event_row("20260105", "risk_off", 0.0),
    ]
    for day, nets in net_targets.items():
        for i, net in enumerate(nets):
            rows.append(
                _event_row(day, "normal", net + 0.0065, symbol=f"S{day}_{i}")
            )
    return pd.DataFrame(rows)


def _history(tmp_path: Path) -> Path:
    p = tmp_path / "regime_history.json"
    p.write_text(json.dumps(REGIMES), encoding="utf-8")
    return p


class TestBlockedRunGroup:
    def test_ten_forms_pinned(self):
        labels = dict(REGIMES)
        # d1 双形态: 连跑长度 1 vs ≥2
        assert blocked_run_group("20260103", SESSIONS, labels) == "d1_run"
        assert blocked_run_group("20260106", SESSIONS, labels) == "d1_blip"
        # d2 双形态: 0104 距 0102 尾日 2 会话 (尾日连跑=2); 0107 距 0105 单日
        assert blocked_run_group("20260104", SESSIONS, labels) == "d2_run"
        assert blocked_run_group("20260107", SESSIONS, labels) == "d2_blip"
        # d3p_blip: 距 0105 尾日 3 会话
        assert blocked_run_group("20260108", SESSIONS, labels) == "d3p_blip"
        # d6p 池化 (不按连跑细分, 只披露)
        assert blocked_run_group("20260115", SESSIONS, labels) == "d6p"
        # no_prior / blocked / unknown / 标签缺失按非阻断处理 (邻近度轴同语义)
        all_normal = {d: "normal" for d in SESSIONS}
        assert blocked_run_group("20260101", SESSIONS, all_normal) == "no_prior"
        assert blocked_run_group("20260101", SESSIONS, labels) == "blocked"
        assert blocked_run_group("20991231", SESSIONS, labels) == "unknown"
        assert blocked_run_group("20260103", SESSIONS, {}) == "no_prior"

    def test_run_chain_broken_by_normal_day(self):
        """连跑计数被单个 normal 日打断: [b,b,n,b,b,n..] 各尾日形态判定性钉住.

        前段 (s1,s2) 不延伸到后段连跑计数 — run 只数「结束于最后阻断日」的
        连续段; d3p_run 在距离 3-5 处仍带连跑标记; dist≥6 池化为 d6p。
        """
        sessions = [f"202603{d:02d}" for d in range(1, 13)]
        labels = {d: "normal" for d in sessions}
        for d in ("20260301", "20260302", "20260304", "20260305", "20260306"):
            labels[d] = "crisis"
        assert blocked_run_group("20260303", sessions, labels) == "d1_run"   # run=2
        assert blocked_run_group("20260307", sessions, labels) == "d1_run"   # run=3 (前段不延伸)
        assert blocked_run_group("20260308", sessions, labels) == "d2_run"
        assert blocked_run_group("20260309", sessions, labels) == "d3p_run"  # 距 0306 尾日 3
        assert blocked_run_group("20260310", sessions, labels) == "d3p_run"  # 距 4
        assert blocked_run_group("20260311", sessions, labels) == "d3p_run"  # 距 5 (上界)
        assert blocked_run_group("20260312", sessions, labels) == "d6p"      # 距 6, 连跑不再细分

    def test_risk_off_same_as_crisis_and_long_run(self):
        sessions = [f"202602{d:02d}" for d in range(1, 12)]
        labels = {d: "normal" for d in sessions}
        for d in sessions[0:7]:
            labels[d] = "risk_off"
        assert blocked_run_group("20260208", sessions, labels) == "d1_run"   # 7 连跑
        assert blocked_run_group("20260209", sessions, labels) == "d2_run"

    def test_group_labels_cover_all_table_groups(self):
        for g in RUN_GROUPS:
            assert g in GROUP_LABELS
        assert "blocked" in GROUP_LABELS


class TestParameterizedHelpersNoDrift:
    """参数化泛化后 R166 特化面零漂移 (键名契约 + 默认行为)."""

    def _prox_rows(self, tmp_path):
        from scripts.regime_proximity_conditioning import proximity_groups
        ev = _simple_events()
        sessions, labels = load_regime_history(_history(tmp_path))
        u = production_aligned(ev)
        prox = proximity_groups(
            pd.unique(u["signal_date"].astype(str)), sessions, labels
        )
        col = "gross_ret_t10"
        sub = u[u[col].notna()]
        rows = pd.DataFrame({
            "net": [v - 0.0065 for v in sub[col].astype(float)],
            "signal_date": sub["signal_date"].astype(str).values,
        })
        rows["group"] = rows["signal_date"].map(lambda d: prox.get(d, "unknown"))
        return rows

    def test_specialized_wrapper_key_contract(self, tmp_path):
        rows = self._prox_rows(tmp_path)
        delta = d1_vs_d2_5_delta(rows)
        assert list(delta) == ["ci_low", "ci_high", "n_d1", "n_d2_5"]
        spec = split_half_verdict(rows)
        assert set(spec) == {"verdict", "consistent", "halves"}
        if spec["halves"]:
            assert list(spec["halves"][0]) == [
                "half", "n_d1", "n_d2_5", "e_d1", "e_d2_5", "penalty", "decidable",
            ]

    def test_generic_delta_direction_fixture(self, tmp_path):
        """配对差方向钉住: 30+ 样本世界 (R153 门槛把关后才进 delta CI).

        3 个单日闪断 (各 11 候选, 净 +3%) vs 2 次两连跑 (各 16 候选, 净 −5%)
        — blip−run 差对任何合法 replicate 恒 +8% → CI 两端 > 0。
        """
        from scripts.regime_blocked_run_conditioning import (
            run_deltas,
            run_groups,
        )
        sessions = [f"202604{d:02d}" for d in range(1, 13)]
        labels = {d: "normal" for d in sessions}
        for d in ("20260401", "20260403", "20260405",
                  "20260407", "20260408", "20260410", "20260411"):
            labels[d] = "crisis"
        rows_out = [
            _event_row(d, "crisis", 0.0, symbol=f"B_{d}")
            for d in labels if labels[d] == "crisis"
        ]
        for d in ("20260402", "20260404", "20260406"):       # d1_blip ×3 日
            for i in range(11):
                rows_out.append(_event_row(
                    d, "normal", 0.03 + 0.0065, symbol=f"blip_{d}_{i}"))
        for d in ("20260409", "20260412"):                   # d1_run ×2 日
            for i in range(16):
                rows_out.append(_event_row(
                    d, "normal", -0.05 + 0.0065, symbol=f"run_{d}_{i}"))
        ev = pd.DataFrame(rows_out)
        u = production_aligned(ev)
        col = "gross_ret_t10"
        sub = u[u[col].notna()]
        rmap = run_groups(pd.unique(u["signal_date"].astype(str)), sessions, labels)
        assert {rmap[d] for d in ("20260402", "20260404", "20260406")} == {"d1_blip"}
        assert {rmap[d] for d in ("20260409", "20260412")} == {"d1_run"}
        rows = pd.DataFrame({
            "net": [v - 0.0065 for v in sub[col].astype(float)],
            "signal_date": sub["signal_date"].astype(str).values,
        })
        rows["group"] = rows["signal_date"].map(lambda d: rmap.get(d, "unknown"))
        deltas = run_deltas(rows)
        headline = deltas["d1_run_vs_blip"]
        # fixture 工程: blip 净 +3% vs run 净 −5% → 罚分 (blip−run) 恒正
        assert headline["n_blip"] == 33
        assert headline["n_run"] == 32
        assert headline["ci_low"] > 0
        assert headline["ci_high"] > 0
        # d2_blip 无落点 (n=0 < MIN_CELL_N) → 区间 None, n 如实披露
        assert deltas["d2_run_vs_blip"]["ci_low"] is None
        assert deltas["d2_run_vs_blip"]["n_blip"] == 0
        assert deltas["d2_run_vs_blip"]["n_run"] == 0


class TestAnalyzeAssemblies:
    def test_group_tables_directional_fixture(self, tmp_path):
        payload = analyze(_simple_events(), _history(tmp_path))
        t10 = payload["tables"]["t10"]
        assert t10["d1_blip"]["n"] == 2
        assert t10["d1_blip"]["winrate"] == pytest.approx(1.0)
        assert t10["d1_blip"]["expectancy"] == pytest.approx(0.03)
        assert t10["d1_run"]["n"] == 2
        assert t10["d1_run"]["expectancy"] == pytest.approx(-0.05)
        assert t10["d2_run"]["n"] == 1
        assert t10["d2_run"]["expectancy"] == pytest.approx(0.02)
        assert t10["d2_blip"]["n"] == 0  # 无落点披露行
        assert t10["d6p"]["expectancy"] == pytest.approx(0.0)  # falsy-zero 保真
        # 生产口径不变量: blocked 恒 0 (gate 语义)
        assert t10["blocked"]["n"] == 0
        # t5 次表同构存在
        assert payload["tables"]["t5"]["d1_blip"]["n"] == 2

    def test_blocked_invariant_production_aligned(self, tmp_path):
        ev = _simple_events()
        u = production_aligned(ev)
        assert u["gate_blocked"].sum() == 0  # 生产宇宙无阻断日 (前置不变量)
        payload = analyze(ev, _history(tmp_path))
        assert payload["tables"]["t10"]["blocked"]["n"] == 0

    def test_residual_ex_d1_run_exact_arithmetic(self, tmp_path):
        payload = analyze(_simple_events(), _history(tmp_path))
        resid = payload["residual_ex_d1_run_t10"]
        # 全体净收益: [−5,−5,+2,+3,+3,+1,0] → 剔 d1_run (−5,−5) 后
        # n=5, E=(2+3+3+1+0)/5=1.8%
        assert resid["n"] == 5
        assert resid["expectancy"] == pytest.approx(0.018)

    def test_split_half_undecidable_on_tiny_world(self, tmp_path):
        # fixture 世界任一半 n<MIN_CELL_N → 不可判定形态 (只判定资格不授权)
        payload = analyze(_simple_events(), _history(tmp_path))
        sh = payload["split_half_d1"]
        assert sh["consistent"] is None
        assert "不可判定" in sh["verdict"]

    def test_label_consistency_zero_on_coherent_world(self, tmp_path):
        payload = analyze(_simple_events(), _history(tmp_path))
        assert payload["label_consistency"]["checked"] > 0
        assert payload["label_consistency"]["mismatch_count"] == 0


class TestDeterminismAndRender:
    def test_analyze_deterministic_bytes(self, tmp_path):
        ev = _simple_events()
        hist = _history(tmp_path)
        a = json.dumps(analyze(ev, hist), sort_keys=True, default=str)
        b = json.dumps(analyze(ev, hist), sort_keys=True, default=str)
        assert a == b

    def test_render_falsy_zero_and_ratio_guards(self, tmp_path):
        assert _fmt(0.0) == "+0.00%"          # falsy-zero: 0.0 非 '—' (R158 家族)
        assert _fmt(None) == "—"
        assert _fmt(0.03) == "+3.00%"
        assert _ratio(1.25) == "1.25"
        assert _ratio(1.0) == "1.00"
        assert _ratio(None) == "—"
        payload = analyze(_simple_events(), _history(tmp_path))
        md = render_md(payload, "20260910")
        assert "d1_blip" in md
        assert "+3.00%" in md
        assert "+0.00%" in md                  # d6p 的 falsy-zero E 保真渲染

    def test_render_survives_missing_group_keys(self, tmp_path):
        payload = analyze(_simple_events(), _history(tmp_path))
        # 渲染存活: 表缺任意组键整行 '—' 不崩 (R167 同款防御面)
        broken = json.loads(json.dumps(payload, default=str))
        broken["tables"]["t10"].pop("d1_run")
        md = render_md(broken, "20260910")
        assert "—" in md


class TestFailClosed:
    def test_empty_production_aligned_typed(self, tmp_path):
        ev = _simple_events()
        ev["excluded_ticker"] = True  # 全体被生产排除 → 空 production_aligned
        with pytest.raises(SystemExit) as ei:
            analyze(ev, _history(tmp_path))
        assert "empty_production_aligned_universe" in str(ei.value)

    def test_missing_history_typed(self, tmp_path):
        with pytest.raises(SystemExit):
            load_regime_history(tmp_path / "absent.json")

    def test_malformed_history_typed(self, tmp_path):
        p = tmp_path / "regime_history.json"
        p.write_text("{not json", encoding="utf-8")
        with pytest.raises(SystemExit):
            load_regime_history(p)


class TestMain:
    def test_main_writes_reports_and_summary(self, tmp_path, capsys):
        ev_path = tmp_path / "events.csv"
        _simple_events().to_csv(ev_path, index=False)
        hist = _history(tmp_path)
        out_dir = tmp_path / "reports"
        rc = main([
            "--court-table", str(ev_path),
            "--regime-history", str(hist),
            "--out-dir", str(out_dir),
            "--date", "20260910",
        ])
        assert rc == 0
        md = (out_dir / "regime_blocked_run_conditioning_20260910.md").read_text(
            encoding="utf-8"
        )
        js = json.loads(
            (out_dir / "regime_blocked_run_conditioning_20260910.json").read_text(
                encoding="utf-8"
            )
        )
        assert "d1_run" in md and "d1_blip" in md
        assert js["tables"]["t10"]["d1_blip"]["n"] == 2
        # 预注册边界成文于报告
        assert "2026-09-10" in md
        out = capsys.readouterr().out
        assert "d1_blip" in out and "d1_run" in out

    def test_main_missing_court_table_typed(self, tmp_path):
        with pytest.raises(SystemExit):
            main([
                "--court-table", str(tmp_path / "absent.csv"),
                "--regime-history", str(_history(tmp_path)),
                "--out-dir", str(tmp_path),
                "--date", "20260910",
            ])
