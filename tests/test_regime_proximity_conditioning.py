"""regime_proximity_conditioning — 邻近度轴算术 + 判读装配 (R166 Op1).

钉死的正确性面:
- 轴算术六形态: d1/d2_5/d6p/no_prior/blocked/unknown (会话索引差, 周末不计数);
- 生产口径不变量: production_aligned 宇宙 blocked 信号日恒 0 (gate 语义);
- 统计装配: win_loss_stats 恒等期望 / 小样本 CI=None / d1 罚分方向;
- 判读纪律: split-half 只判定资格不授权 / n<30 不可判定 / falsy-zero 显示;
- fail-closed: regime history 缺失/畸形 typed 拒绝; 报告确定性 (R13 家族)。
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from scripts.regime_proximity_conditioning import (
    GROUP_LABELS,
    _ratio,
    MIN_CELL_N,
    PROXIMITY_ORDER,
    REGIME_HISTORY_DEFAULT,
    RegimeProximityError,
    _fmt,
    analyze,
    d1_vs_d2_5_delta,
    group_tables,
    label_consistency,
    load_regime_history,
    main,
    proximity_group,
    proximity_groups,
    render_md,
    residual_pool,
    split_half_verdict,
    strength_cross,
)
from scripts.winrate_payoff_decomposition import production_aligned

SESSIONS = [f"202601{d:02d}" for d in range(1, 9)]
REGIMES = {
    "20260101": "crisis",
    "20260102": "normal",
    "20260103": "normal",
    "20260104": "normal",
    "20260105": "normal",
    "20260106": "normal",
    "20260107": "normal",
    "20260108": "normal",
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
    """八会话小世界: 0101 crisis, 0102..0108 normal (d1/d2_5/d6p 各有落点)."""
    net_targets = {  # 期望的 t10 净收益 (毛 = 净 + 0.0065)
        "20260102": [0.10],                    # d1
        "20260103": [0.02, -0.02],             # d2_5 (2 会话)
        "20260104": [0.03],                    # d2_5 (3)
        "20260107": [-0.05],                   # d6p (6)
    }
    rows = [_event_row("20260101", "crisis", 0.0)]
    for day, nets in net_targets.items():
        for i, net in enumerate(nets):
            rows.append(
                _event_row(day, "normal", net + 0.0065, symbol=f"S{day}_{i}")
            )
    return pd.DataFrame(rows)


class TestProximityGroup:
    def test_six_forms_pinned(self):
        labels = dict(REGIMES)
        assert proximity_group("20260102", SESSIONS, labels) == "d1"
        assert proximity_group("20260103", SESSIONS, labels) == "d2_5"
        assert proximity_group("20260106", SESSIONS, labels) == "d2_5"  # 距 5 会话上界
        assert proximity_group("20260107", SESSIONS, labels) == "d6p"   # 距 6 会话
        assert proximity_group("20260101", SESSIONS, labels) == "blocked"
        assert proximity_group("20260101", SESSIONS, {**labels, "20260101": "normal"}) == "no_prior"
        assert proximity_group("20991231", SESSIONS, labels) == "unknown"
        assert proximity_group("20260102", SESSIONS, {}) == "unknown"  # 无标签

    def test_risk_off_blocks_same_as_crisis(self):
        labels = {d: "normal" for d in SESSIONS}
        labels["20260104"] = "risk_off"
        assert proximity_group("20260105", SESSIONS, labels) == "d1"
        assert proximity_group("20260104", SESSIONS, labels) == "blocked"

    def test_batch_matches_single(self):
        prox = proximity_groups(SESSIONS, SESSIONS, REGIMES)
        assert prox == {d: proximity_group(d, SESSIONS, REGIMES) for d in SESSIONS}


class TestLoadRegimeHistory:
    def test_sorted_sessions(self, tmp_path):
        p = tmp_path / "h.json"
        p.write_text(json.dumps({"20260102": "normal", "20260101": "crisis"}), encoding="utf-8")
        sessions, labels = load_regime_history(p)
        assert sessions == ["20260101", "20260102"]
        assert labels["20260101"] == "crisis"

    def test_missing_fail_closed(self, tmp_path):
        with pytest.raises(SystemExit):
            load_regime_history(tmp_path / "absent.json")

    def test_malformed_fail_closed(self, tmp_path):
        bad = tmp_path / "bad.json"
        bad.write_text(json.dumps({"20260101": 42}), encoding="utf-8")
        with pytest.raises(SystemExit):
            load_regime_history(bad)
        (tmp_path / "list.json").write_text(json.dumps(["x"]), encoding="utf-8")
        with pytest.raises(SystemExit):
            load_regime_history(tmp_path / "list.json")


class TestAlignedUniverseInvariant:
    def test_zero_blocked_days_in_production_aligned(self):
        """gate 语义不变量: production_aligned 宇宙不含阻断日信号 (R166 轴前提)."""
        u = production_aligned(_simple_events())
        prox = proximity_groups(u["signal_date"].astype(str).unique(), SESSIONS, REGIMES)
        assert "blocked" not in set(prox.values())
        assert set(u["regime"].unique()) == {"normal"}


class TestGroupTables:
    def test_arithmetic_pinned_small_world(self):
        ev = _simple_events()
        u = production_aligned(ev)
        tables, prox = group_tables(u, SESSIONS, REGIMES)
        t10 = tables["t10"]
        assert prox["20260102"] == "d1"
        assert t10["d1"]["n"] == 1
        assert t10["d1"]["expectancy"] == pytest.approx(0.10)
        assert t10["d2_5"]["n"] == 3
        assert t10["d2_5"]["expectancy"] == pytest.approx((0.02 - 0.02 + 0.03) / 3)
        assert t10["d6p"]["n"] == 1
        assert t10["d6p"]["expectancy"] == pytest.approx(-0.05)
        assert t10["blocked"]["n"] == 0
        # 小样本: 聚类 CI 诚实 None (n<MIN_CELL_N)
        for g in PROXIMITY_ORDER:
            if t10[g]["n"] < MIN_CELL_N:
                assert t10[g]["cluster_ci_low_90"] is None

    def test_t5_contrast_horizon_present(self):
        tables, _ = group_tables(production_aligned(_simple_events()), SESSIONS, REGIMES)
        assert "t5" in tables
        assert tables["t5"]["d1"]["n"] == 1

    def test_unknown_group_honest(self):
        """信号日不在会话序 → unknown 组显形, 不静默消失."""
        ev = _simple_events()
        ghost = _event_row("20990101", "normal", 0.05, symbol="GHOST")
        u = production_aligned(pd.concat([ev, pd.DataFrame([ghost])], ignore_index=True))
        tables, _ = group_tables(u, SESSIONS, REGIMES)
        assert tables["t10"]["unknown"]["n"] == 1


class TestResidualPool:
    def test_residual_excludes_d1(self):
        u = production_aligned(_simple_events())
        resid = residual_pool(u, proximity_groups(u["signal_date"], SESSIONS, REGIMES))
        # d2_5 (0.02,-0.02,0.03) + d6p (-0.05) = 4 行, d1 的 0.10 不在
        assert resid["n"] == 4
        assert resid["expectancy"] == pytest.approx((0.02 - 0.02 + 0.03 - 0.05) / 4)


class TestDeltaAndSplitHalf:
    def _bulk_world(self, d1_ret: float, d25_ret: float, flip_second_half: bool = False):
        """邻近度单元链小世界: 每单元 [阻断日, d1 日, d2 日×4], 两半各 5 单元.

        只有紧贴阻断日后的 1 天是 d1 — d1 日必须逐个插入阻断日重置距离,
        连续 normal 天的第二天起就是 d2_5。每仓 6 只 → 每半窗 d1 30 仓 /
        d2_5 120 仓 (R15 可判定门槛)。
        """
        rows = []
        sessions: list[str] = []
        labels: dict[str, str] = {}
        from datetime import date as _date, timedelta as _timedelta

        day = _date(2027, 1, 3)

        def next_day() -> str:
            nonlocal day
            s = day.strftime("%Y%m%d")
            day += _timedelta(days=1)
            return s

        for half in range(2):
            d1_r = d1_ret if not (flip_second_half and half == 1) else -d1_ret
            d25_r = d25_ret if not (flip_second_half and half == 1) else -d25_ret
            for _unit in range(5):
                b = next_day()
                sessions.append(b)
                labels[b] = "crisis" if half == 0 else "risk_off"
                for tag, ret, count in (
                    ("d1", d1_r, 1),
                    ("d25", d25_r, 4),
                ):
                    for _i in range(count):
                        d = next_day()
                        sessions.append(d)
                        labels[d] = "normal"
                        for k in range(6):
                            rows.append(
                                _event_row(d, "normal", ret + 0.0065,
                                           symbol=f"H{half}{tag}{d}{k}")
                            )
        ev = pd.DataFrame(rows)
        u = production_aligned(ev)
        prox = proximity_groups(u["signal_date"].astype(str).unique(), sessions, labels)
        from scripts.regime_proximity_conditioning import _horizon_rows

        return _horizon_rows(u, 10, prox)

    def test_delta_ci_small_n_none(self):
        rows = pd.DataFrame(
            {"net": [0.01, 0.02], "signal_date": ["20270102", "20270103"],
             "group": ["d1", "d2_5"]}
        )
        delta = d1_vs_d2_5_delta(rows)
        assert delta["ci_low"] is None and delta["ci_high"] is None

    def test_delta_ci_positive_penalty(self):
        rows = self._bulk_world(d1_ret=-0.01, d25_ret=0.02)
        delta = d1_vs_d2_5_delta(rows)
        assert delta["ci_low"] is not None and delta["ci_high"] is not None
        assert delta["ci_high"] > 0 and delta["ci_low"] > 0  # 3pp 罚分全区间为正
        assert delta["n_d1"] == 60 and delta["n_d2_5"] == 240  # 两半合计 (5 单元×6 仓)×2

    def test_split_half_consistent(self):
        rows = self._bulk_world(d1_ret=-0.01, d25_ret=0.02)
        verdict = split_half_verdict(rows)
        assert verdict["verdict"] == "跨半一致"
        assert verdict["consistent"] is True

    def test_split_half_flipped(self):
        rows = self._bulk_world(d1_ret=-0.01, d25_ret=0.02, flip_second_half=True)
        verdict = split_half_verdict(rows)
        assert verdict["verdict"] == "跨半翻转"
        assert verdict["consistent"] is False

    def test_split_half_undecidable_small_n(self):
        rows = pd.DataFrame(
            {
                "net": [0.01] * 4 + [0.02] * 4,
                "signal_date": [f"2027010{i}" for i in range(1, 5)] * 2,
                "group": ["d1"] * 4 + ["d2_5"] * 4,
            }
        )
        verdict = split_half_verdict(rows)
        assert verdict["verdict"] == "不可判定 (任一半 n<30)"
        assert verdict["consistent"] is None


class TestStrengthCross:
    def test_bucket_boundary_and_unknown(self):
        """0.50 左闭入 0.50-0.60 桶; NaN 强度 → unknown 桶; 落各自邻近度组."""
        rows = [
            _event_row("20260102", "normal", 0.05, symbol="A", strength=0.50),   # d1 × 0.50-0.60
            _event_row("20260102", "normal", 0.06, symbol="B", strength=0.49),   # d1 × <0.50
            _event_row("20260103", "normal", 0.07, symbol="C", strength=float("nan")),  # d2_5 × unknown
        ]
        u = production_aligned(pd.DataFrame(rows))
        cross = strength_cross(u, proximity_groups(u["signal_date"], SESSIONS, REGIMES))
        by = {(c["bucket"], c["group"]): c for c in cross}
        assert by[("0.50-0.60", "d1")]["n"] == 1
        assert by[("<0.50", "d1")]["n"] == 1
        assert by[("unknown", "d2_5")]["n"] == 1


class TestLabelConsistency:
    def test_label_consistency_zero_mismatch_when_consistent(self):
        ev = _simple_events()
        lc = label_consistency(ev, REGIMES)
        assert lc["checked"] == 5 and lc["mismatch_count"] == 0

    def test_mismatch_disclosed(self):
        ev = _simple_events()
        drifted = dict(REGIMES)
        drifted["20260102"] = "risk_off"
        lc = label_consistency(ev, drifted)
        assert lc["mismatch_count"] == 1
        assert lc["mismatches"][0]["signal_date"] == "20260102"


class TestFmtFalsyZero:
    def test_zero_renders_not_dash(self):
        """R158 falsy-zero 家族: 0.0 是有效读数, 不得渲染为缺失 '—'."""
        assert _fmt(0.0) == "+0.00%"
        assert _fmt(None) == "—"
        assert _fmt(float("nan")) == "—"
        assert _fmt("x") == "—"
        assert _fmt(True) == "—"
        assert _fmt(30, pct=False) == "30"

    def test_group_labels_complete(self):
        for g in PROXIMITY_ORDER:
            assert g in GROUP_LABELS
        assert "blocked" in GROUP_LABELS


class TestPayoffRatioAndRenderSurvival:
    """R167 Op2 F-a 钉住: payoff 比率语义 + 渲染防御面."""

    def test_ratio_formatting(self):
        assert _ratio(0.9852) == "0.99"
        assert _ratio(1.0) == "1.00"
        assert _ratio(1.22) == "1.22"
        assert _ratio(None) == "—"
        assert _ratio(float("nan")) == "—"
        assert _ratio(True) == "—"

    @staticmethod
    def _cell(row: str, idx: int) -> str:
        return row.split("|")[idx].strip()

    def test_md_payoff_column_is_ratio(self, tmp_path):
        """端到端: MD 表 payoff 列 (第 6 列) 为纯比率无 '%' 形态.

        小世界数值: d1 组单笔全胜 → payoff 未定义 '—' (win_loss_stats 契约);
        d2_5 组 (净 0.02/-0.02/0.03) avg_win 0.025 / avg_loss −0.02 → '1.25';
        修复前该列渲染 '+125.00%' 即 F-a 缺陷形态。
        """
        ev = _simple_events()
        table = tmp_path / "event_table.csv"
        ev.to_csv(table, index=False)
        history = tmp_path / "regime_history.json"
        history.write_text(json.dumps(REGIMES), encoding="utf-8")
        payload = analyze(pd.read_csv(table), history)
        md = render_md(payload, "20260910")
        t10_section = md.split("## t10")[1].split("## t5")[0]
        rows = {
            self._cell(ln, 1): ln
            for ln in t10_section.splitlines()
            if ln.startswith("| d") or ln.startswith("| blocked") or ln.startswith("| no") or ln.startswith("| unknown")
        }
        d1_row = rows["d1 (距阻断日 1 会话)"]
        d25_row = rows["d2_5 (2-5 会话)"]
        assert self._cell(d1_row, 6) == "—"  # 单笔全胜 → payoff 未定义
        assert self._cell(d25_row, 6) == "1.25"
        for ln in (d1_row, d25_row):
            assert "%" not in self._cell(ln, 6)  # F-a 修复: 比率列零百分比形态
            assert "%" in self._cell(ln, 7)  # E 列仍为百分比语义

    def test_render_survives_missing_group_key(self):
        """防御面: tables 缺任意组键 → 整行 '—' 不崩 (dict.get 单一守卫)."""
        payload = {
            "court_window": {"start": "20250702", "end": "20260909"},
            "aligned_n": 5,
            "tables": {"t10": {"d1": {"n": 1, "winrate": 1.0, "avg_win": 0.1,
                                      "avg_loss": -0.05, "payoff": 2.0,
                                      "expectancy": 0.1}},
                       "t5": {}},
            "residual_pool_t10": {},
            "d1_vs_d2_5_delta_t10": {"ci_low": None, "n_d1": 0, "n_d2_5": 0},
            "split_half": {"verdict": "不可判定 (任一半 n<30)", "halves": []},
            "strength_cross_t10": [],
            "label_consistency": {"checked": 0, "mismatch_count": 0},
        }
        md = render_md(payload, "20260910")
        assert md.count("| —") >= 5  # 缺键组整行 '—'


class TestAnalyzeEndToEnd:
    def _write_fixture(self, tmp_path: Path) -> tuple[Path, Path]:
        ev = _simple_events()
        table = tmp_path / "event_table.csv"
        ev.to_csv(table, index=False)
        history = tmp_path / "regime_history.json"
        history.write_text(json.dumps(REGIMES), encoding="utf-8")
        return table, history

    def test_analyze_payload_shape(self, tmp_path):
        table, history = self._write_fixture(tmp_path)
        payload = analyze(pd.read_csv(table), history)
        assert payload["aligned_n"] == 5
        assert set(payload["tables"].keys()) == {"t10", "t5"}
        assert payload["label_consistency"]["mismatch_count"] == 0
        assert payload["split_half"]["verdict"].startswith("不可判定")

    def test_main_writes_reports_deterministic(self, tmp_path):
        table, history = self._write_fixture(tmp_path)
        out = tmp_path / "reports"
        argv = ["--court-table", str(table), "--regime-history", str(history),
                "--out-dir", str(out), "--date", "20260910"]
        assert main(argv) == 0
        j1 = (out / "regime_proximity_conditioning_20260910.json").read_bytes()
        m1 = (out / "regime_proximity_conditioning_20260910.md").read_bytes()
        assert main(argv) == 0
        assert (out / "regime_proximity_conditioning_20260910.json").read_bytes() == j1
        assert (out / "regime_proximity_conditioning_20260910.md").read_bytes() == m1
        payload = json.loads(j1)
        assert payload["tables"]["t10"]["d1"]["expectancy"] == pytest.approx(0.10)
        assert "d1 (距阻断日 1 会话)" in m1.decode("utf-8")

    def test_main_missing_table_fail_closed(self, tmp_path):
        history = tmp_path / "h.json"
        history.write_text(json.dumps(REGIMES), encoding="utf-8")
        with pytest.raises(SystemExit):
            main(["--court-table", str(tmp_path / "nope.csv"),
                  "--regime-history", str(history), "--out-dir", str(tmp_path)])

    def test_main_missing_history_fail_closed(self, tmp_path):
        table, _ = self._write_fixture(tmp_path)
        with pytest.raises(SystemExit):
            main(["--court-table", str(table),
                  "--regime-history", str(tmp_path / "absent.json"),
                  "--out-dir", str(tmp_path)])


class TestHistoryDefaultPathContract:
    def test_default_points_at_production_truth(self):
        """与 daily_action regime gate 同源 (daily_action.py:165 同一路径)."""
        assert str(REGIME_HISTORY_DEFAULT) == "data/reports/regime_history.json"
