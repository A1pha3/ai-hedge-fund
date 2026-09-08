"""R152 Op1: 强度分量级解剖工具 — 纯函数 oracle/守卫/确定性/渲染/CLI。

fixture 纪律 (R13 教训): 非对称 — 两分量方向相反、收益值互异、桶间样本
不等, 值形态检查才能抓到复制粘贴级错误。
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import pandas as pd
import pytest

from scripts.strength_component_decomposition import (
    component_anatomy,
    component_bucket,
    component_split_half,
    analyze,
    render_md,
    main,
)
from scripts.winrate_payoff_decomposition import ROUNDTRIP_COST


def _row(i, *, strength, board, low_vol, squeeze, volume, rng, ret):
    return {
        "symbol": f"{600000 + i}",
        "signal_date": f"2026-01-{(i % 4) + 1:02d}",
        "trigger_strength": strength,
        "board_score": board,
        "low_vol_score": low_vol,
        "squeeze_score": squeeze,
        "volume_score": volume,
        "range_score": rng,
        "gross_ret_t10": ret,
        "gross_ret_t5": ret / 2,
        "fillable": True,
        "gate_blocked": False,
        "degraded": False,
        "st_name": False,
        "industry_missing": False,
        "excluded_ticker": False,
        "price_ge_3": True,
    }


def _fixture_ev() -> pd.DataFrame:
    """8 行非对称: board 低分侧强赢 / squeeze 高分侧强赢, 收益逐行互异。

    行 i=0..7; board_score 0.0 (i<4) vs 0.95 (i>=4); squeeze_score 反向
    0.9 (i<4) vs 0.1 (i>=4); strength 前半 0.55 后半 0.75 (跨 ge050/ge070
    池); 日期 4 天循环 (聚类 CI 有 ≥2 天); 收益前 4 行强正后 4 行强负
    (两分量 hi_lo_delta 方向相反且量级 ~13pp, 无近零浮尘)。
    """
    rets = (0.10, 0.08, 0.06, 0.04, -0.03, -0.05, -0.07, -0.09)
    rows = []
    for i in range(8):
        rows.append(_row(
            i,
            strength=0.55 if i < 4 else 0.75,
            board=0.0 if i < 4 else 0.95,
            low_vol=0.9 if i < 4 else 0.1,
            squeeze=0.9 if i < 4 else 0.1,
            volume=0.6,
            rng=0.2,
            ret=rets[i],
        ))
    return pd.DataFrame(rows)


class TestComponentBucket:
    def test_boundaries(self):
        assert component_bucket(0.0) == "<0.50"
        assert component_bucket(0.499999) == "<0.50"
        assert component_bucket(0.5) == "≥0.50"      # 恰界点归高侧
        assert component_bucket(1.0) == "≥0.50"

    def test_non_numeric_unknown(self):
        assert component_bucket(None) == "unknown"
        assert component_bucket(float("nan")) == "unknown"
        assert component_bucket(float("inf")) == "unknown"
        assert component_bucket("0.7") == "unknown"   # 字符串冒充数值不入桶
        assert component_bucket(True) == "unknown"    # bool 显式排除


class TestComponentAnatomy:
    def test_oracle_hand_computed(self):
        ev = _fixture_ev()
        payload = analyze(ev)
        pools = payload["pools"]
        # analyze 走 production_aligned: 全部 8 行 fillable 且未拦截 → 全保留
        assert payload["n"] == 8
        # net 收益 = gross - ROUNDTRIP_COST
        rets = (0.10, 0.08, 0.06, 0.04, -0.03, -0.05, -0.07, -0.09)

        def net(i):
            return rets[i] - ROUNDTRIP_COST

        # all 池: board <0.50 桶 = i 0..3, 手算 E (期望恒等式两侧累加序不同,
        # 容 float 尘: abs_tol=1e-12)
        board = pools["all"]["components"]["board_score"]
        lo_e = sum(net(i) for i in range(4)) / 4
        lo_stats = board["buckets"]["<0.50"]
        assert lo_stats["n"] == 4
        assert math.isclose(lo_stats["expectancy"], lo_e, rel_tol=1e-9, abs_tol=1e-12)
        # hi 桶 = i 4..7
        hi_e = sum(net(i) for i in range(4, 8)) / 4
        hi_stats = board["buckets"]["≥0.50"]
        assert math.isclose(hi_stats["expectancy"], hi_e, rel_tol=1e-9, abs_tol=1e-12)
        # hi_lo_delta = hi − lo 精确 (量级 ~13pp, rel_tol 足够)
        assert math.isclose(
            board["hi_lo_delta"], hi_e - lo_e, rel_tol=1e-9, abs_tol=1e-12
        )
        # squeeze 反向: hi 桶 (i0..3) E 高于 lo 桶 (i4..7)
        squeeze = pools["all"]["components"]["squeeze_score"]
        assert squeeze["hi_lo_delta"] > 0
        assert board["hi_lo_delta"] < 0   # fixture: board 低分侧 (i0..3) E 更高

    def test_pool_floors(self):
        ev = _fixture_ev()
        pools = analyze(ev)["pools"]
        assert pools["all"]["n"] == 8
        assert pools["ge050"]["n"] == 8          # 全部 strength ≥0.55
        assert pools["ge070"]["n"] == 4          # i4..7 (strength 0.75)
        assert pools["all"]["floor"] is None
        assert pools["ge050"]["floor"] == 0.50

    def test_small_cell_ci_none(self):
        """n<MIN_CELL_N 桶 CI 诚实 None (win_loss_stats 内建门槛透传)。"""
        pools = analyze(_fixture_ev())["pools"]
        cell = pools["all"]["components"]["board_score"]["buckets"]["<0.50"]
        assert cell["n"] < 30
        assert cell["cluster_ci_low_90"] is None

    def test_all_missing_component_unknown_bucket(self):
        """分量列全缺失 → unknown 桶全量, 双值桶 n=0 全 None 不虚构。"""
        ev = _fixture_ev()
        ev["range_score"] = float("nan")
        pools = analyze(ev)["pools"]
        cell = pools["all"]["components"]["range_score"]["buckets"]
        assert cell["unknown"]["n"] == 8
        assert cell["unknown"]["expectancy"] is not None   # unknown 桶自身有统计
        assert cell["<0.50"]["n"] == 0
        assert cell["<0.50"]["expectancy"] is None
        assert cell["≥0.50"]["expectancy"] is None
        # hi_lo_delta 双侧缺 → None
        assert pools["all"]["components"]["range_score"]["hi_lo_delta"] is None

    def test_missing_component_column_fail_closed(self):
        ev = _fixture_ev().drop(columns=["low_vol_score"])
        with pytest.raises(SystemExit, match="low_vol_score"):
            analyze(ev)


class TestSplitHalf:
    def _rows(self, spec):
        """spec: (date, board_score, ret) 三元组序列 → DataFrame。"""
        rows = []
        for i, (d, board, ret) in enumerate(spec):
            rows.append(_row(
                i, strength=0.6, board=board, low_vol=0.1, squeeze=0.9,
                volume=0.6, rng=0.2, ret=ret,
            ))
            rows[-1]["signal_date"] = d
        return pd.DataFrame(rows)

    def test_sign_flip_detected(self):
        """早半 hi 桶赢、晚半 hi 桶输 → sign_consistent=False (R133 判据面)。"""
        ev = self._rows([
            ("2026-01-01", 0.9, 0.10), ("2026-01-01", 0.1, 0.02),
            ("2026-01-02", 0.9, 0.12), ("2026-01-02", 0.1, 0.01),
            ("2026-01-03", 0.9, -0.10), ("2026-01-03", 0.1, -0.02),
            ("2026-01-04", 0.9, -0.12), ("2026-01-04", 0.1, -0.01),
        ])
        payload = analyze(ev)
        sc = payload["split_half"]
        assert sc["available"] is True
        comp = sc["pools"]["all"]["board_score"]
        assert comp["early_delta"] > 0
        assert comp["late_delta"] < 0
        assert comp["sign_consistent"] is False

    def test_stable_same_sign(self):
        ev = self._rows([
            ("2026-01-01", 0.9, 0.10), ("2026-01-01", 0.1, 0.02),
            ("2026-01-02", 0.9, 0.11), ("2026-01-02", 0.1, 0.01),
            ("2026-01-03", 0.9, 0.12), ("2026-01-03", 0.1, 0.03),
            ("2026-01-04", 0.9, 0.13), ("2026-01-04", 0.1, 0.02),
        ])
        payload = analyze(ev)
        comp = payload["split_half"]["pools"]["all"]["board_score"]
        assert comp["early_delta"] > 0 and comp["late_delta"] > 0
        assert comp["sign_consistent"] is True

    def test_one_side_empty_delta_none(self):
        """晚半全部事件同桶 → 该半 delta None → sign_consistent None 不冒充。"""
        ev = self._rows([
            ("2026-01-01", 0.9, 0.10), ("2026-01-01", 0.1, 0.02),
            ("2026-01-02", 0.9, 0.11), ("2026-01-02", 0.1, 0.01),
            ("2026-01-03", 0.9, 0.12), ("2026-01-03", 0.9, 0.13),
            ("2026-01-04", 0.9, 0.14), ("2026-01-04", 0.9, 0.15),
        ])
        payload = analyze(ev)
        comp = payload["split_half"]["pools"]["all"]["board_score"]
        assert comp["early_delta"] is not None
        assert comp["late_delta"] is None
        assert comp["sign_consistent"] is None


class TestDeterminism:
    def test_same_input_byte_identical(self):
        """同输入两次 analyze → JSON 逐字节一致 (per-call seeded 纪律)。"""
        ev = _fixture_ev()
        a = json.dumps(analyze(ev), ensure_ascii=False, sort_keys=True)
        b = json.dumps(analyze(ev), ensure_ascii=False, sort_keys=True)
        assert a == b


class TestRenderMd:
    def test_full_payload_renders_discipline_lines(self):
        payload = analyze(_fixture_ev())
        md = render_md(payload)
        assert "强度分量级解剖" in md
        assert "探索性 in-sample" in md and "宪法 #2" in md
        assert "上市板" in md and "低波" in md
        assert "hi−lo" in md

    def test_malformed_payload_no_crash(self):
        assert render_md(None) == ""
        assert render_md({}) == ""
        assert render_md({"available": False, "reason": "x"}) == ""
        assert render_md("garbage") == ""
        # 结构残缺: pools 非 dict / components 缺 / cell 非 dict → 不崩不垃圾
        payload = {"available": True, "pools": {"all": {"components": {
            "board_score": "garbage"}}}}
        md = render_md(payload)
        assert "garbage" not in md


class TestMainCli:
    def _write_court(self, tmp_path) -> Path:
        p = tmp_path / "events.csv"
        _fixture_ev().to_csv(p, index=False)
        return p

    def test_writes_both_reports(self, tmp_path):
        court = self._write_court(tmp_path)
        out = tmp_path / "reports"
        rc = main([
            "--court-table", str(court),
            "--report-dir", str(out),
            "--date-str", "20260909",
        ])
        assert rc == 0
        j = out / "strength_component_decomposition_20260909.json"
        m = out / "strength_component_decomposition_20260909.md"
        assert j.exists() and m.exists()
        payload = json.loads(j.read_text(encoding="utf-8"))
        assert payload["available"] is True
        assert payload["court_window"]["start"] == "2026-01-01"

    def test_invalid_date_str_zero_files(self, tmp_path):
        """banana 日期 → SystemExit 零产物 (R119 P2 家族)。"""
        court = self._write_court(tmp_path)
        out = tmp_path / "reports"
        with pytest.raises(SystemExit, match="invalid_date_str"):
            main([
                "--court-table", str(court),
                "--report-dir", str(out),
                "--date-str", "banana",
            ])
        assert not out.exists() or not list(out.glob("*"))

    def test_missing_court_table(self, tmp_path):
        with pytest.raises(SystemExit, match="缺失"):
            main([
                "--court-table", str(tmp_path / "nope.csv"),
                "--report-dir", str(tmp_path / "r"),
                "--date-str", "20260909",
            ])
