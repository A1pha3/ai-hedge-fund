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
    COMPONENTS,
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

    def test_missing_core_columns_fail_closed(self):
        """R152 Op2 A1: core 列缺失同入 typed 拒绝 (修复前裸 KeyError 逃逸)。"""
        for col in ("trigger_strength", "signal_date", "gross_ret_t10"):
            ev = _fixture_ev().drop(columns=[col])
            with pytest.raises(SystemExit, match=col):
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

    def test_count_cells_integer_rendering(self):
        """R152 Op2 A2: n 计数格整数渲染 (修复前 '4.000' 三位小数实锤)。"""
        payload = analyze(_fixture_ev())
        md = render_md(payload)
        assert "| 上市板 (board_score) | 4 / " in md
        assert ".000 / " not in md and ".000 |" not in md

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


class TestDeltaCi:
    """R153 Op1: hi−lo 差的配对 bootstrap 区间 — 接线面 (双桶 n≥MIN_CELL_N)。"""

    def _large_fixture(self, *, n_lo=30, n_hi=30, n_days=6):
        """board 分量双桶各 ≥MIN_CELL_N, 跨多日; hi 侧强赢 lo 侧强输。"""
        rows = []
        i = 0
        for d in range(n_days):
            day = f"2026-03-{(d % 28) + 1:02d}"
            for _ in range(n_lo // n_days + 1):
                rows.append(_row(
                    i, strength=0.6, board=0.0, low_vol=0.1, squeeze=0.9,
                    volume=0.6, rng=0.2, ret=0.09 - 0.0007 * i,
                ))
                rows[-1]["signal_date"] = day
                i += 1
            for _ in range(n_hi // n_days + 1):
                rows.append(_row(
                    i, strength=0.6, board=0.95, low_vol=0.1, squeeze=0.9,
                    volume=0.6, rng=0.2, ret=-0.02 - 0.0003 * i,
                ))
                rows[-1]["signal_date"] = day
                i += 1
        return pd.DataFrame(rows)

    def test_delta_ci_present_when_both_cells_large(self):
        ev = self._large_fixture()
        payload = analyze(ev)
        cell = payload["pools"]["all"]["components"]["board_score"]
        lo_n = cell["buckets"]["<0.50"]["n"]
        hi_n = cell["buckets"]["≥0.50"]["n"]
        assert lo_n >= 30 and hi_n >= 30
        ci = cell["hi_lo_delta_ci"]
        assert isinstance(ci, dict)
        assert set(ci) == {"ci_low", "ci_high"}
        assert ci["ci_low"] <= ci["ci_high"]
        # 点估计与既有 hi_lo_delta 同号且区间罩住点估计
        assert cell["hi_lo_delta"] < 0
        assert ci["ci_low"] <= cell["hi_lo_delta"] <= ci["ci_high"]

    def test_delta_ci_deterministic(self):
        ev = self._large_fixture()
        a = json.dumps(analyze(ev), ensure_ascii=False, sort_keys=True)
        b = json.dumps(analyze(ev), ensure_ascii=False, sort_keys=True)
        assert a == b

    def test_delta_ci_none_small_cells(self):
        """8 行 fixture 双桶 n=4 < MIN_CELL_N → delta_ci 全 None 不冒充。"""
        pools = analyze(_fixture_ev())["pools"]
        for pool_key in ("all", "ge050", "ge070"):
            for comp_key, _label in COMPONENTS:
                cell = pools[pool_key]["components"][comp_key]
                assert cell["hi_lo_delta_ci"] is None

    def test_delta_ci_none_all_unknown_component(self):
        ev = _fixture_ev()
        ev["range_score"] = float("nan")
        cell = analyze(ev)["pools"]["all"]["components"]["range_score"]
        assert cell["hi_lo_delta_ci"] is None

    def test_render_md_interval_and_guard(self):
        ev = self._large_fixture()
        md = render_md(analyze(ev))
        assert "hi−lo" in md
        assert "[" in md and "]" in md   # 区间形态落进 hi−lo 列
        # 缺键 payload 不崩 (R142 F2 家族): cell 无 hi_lo_delta_ci 键
        payload = {"available": True, "pools": {"all": {"components": {
            "board_score": {"buckets": {}, "hi_lo_delta": 0.01}}}}}
        assert render_md(payload)  # 不抛异常即可


# ---------------------------------------------------------------------------
# R154 Op1: 低波轴零权反事实读数 (V1 单旋钮, 探索性非提案)
# ---------------------------------------------------------------------------

from scripts.strength_component_decomposition import (  # noqa: E402
    counterfactual_pool_readout,
    counterfactual_selection_readout,
    counterfactual_strength,
)


def _cf_row(i, *, ts, lv, ret, day):
    """反事实 fixture 行: ts/低波/收益全显式, 日期显式 (聚类/半窗可控)。"""
    r = _row(i, strength=ts, board=0.5, low_vol=lv, squeeze=0.5,
             volume=0.5, rng=0.5, ret=ret)
    r["signal_date"] = day
    return r


def _cf_selection_fixture(n_days=12):
    """选股面主 fixture: 每日 6 行, 旧强度排序选坏 3 行 / 反事实排序选好 3 行。

    坏行 ts 0.85/0.84/0.83 + lv 0.90 → cf ≈0.84/0.825/0.8125 (排序下沉);
    好行 ts 0.80/0.79/0.78 + lv 0.05 → cf ≈0.99/0.97/0.96 (排序上升)。
    k=3 旧新选集不相交, ΔE ≈ +0.20 强分离 (CI 必正, 无 bootstrap flake);
    12 日 × 3 = 36 picks/侧 ≥ MIN_CELL_N=30 → CI 落地。
    收益逐日微抖动 (R13 教训: 非对称值形态)。
    """
    rows = []
    i = 0
    for d in range(n_days):
        day = f"2026-04-{d + 1:02d}"
        for j, ts in enumerate((0.85, 0.84, 0.83)):
            rows.append(_cf_row(i, ts=ts, lv=0.90, ret=-0.10 - 0.001 * d, day=day))
            i += 1
        for j, ts in enumerate((0.80, 0.79, 0.78)):
            rows.append(_cf_row(i, ts=ts, lv=0.05, ret=0.10 + 0.001 * d, day=day))
            i += 1
    return pd.DataFrame(rows)


def _cf_pool_fixture(n_days=16):
    """池面主 fixture: G/B/N 三行型, 反事实让 G 入池 B 出池, ΔE ≈ +0.10。

    G (好·波动): ts=0.45 (旧池外), lv=0.05 → cf=0.55 (新池内), ret≈+0.10;
    B (坏·低波): ts=0.58 (旧池内), lv=0.95 → cf=0.4875 (新池外), ret≈-0.10;
    N (中性): ts=0.70, lv=0.50 → cf=0.75 (双池内), ret≈+0.01。
    两侧各 2n 行 (n_days≥15 时 ≥MIN_CELL_N=30 → CI 落地)。
    """
    rows = []
    i = 0
    for d in range(n_days):
        day = f"2026-05-{d + 1:02d}"
        rows.append(_cf_row(i, ts=0.45, lv=0.05, ret=0.095 + 0.0007 * d, day=day))
        i += 1
        rows.append(_cf_row(i, ts=0.58, lv=0.95, ret=-0.10 - 0.0007 * d, day=day))
        i += 1
        rows.append(_cf_row(i, ts=0.70, lv=0.50, ret=0.008 + 0.0002 * d, day=day))
        i += 1
    return pd.DataFrame(rows)


class TestCounterfactualStrength:
    def test_exact_arithmetic(self):
        # (0.75 - 0.20*0.90)/0.80 = 0.7125
        assert math.isclose(counterfactual_strength(0.75, 0.90), 0.7125,
                            rel_tol=1e-12, abs_tol=1e-15)
        # lv=0 → 强度只被重归一化放大
        assert math.isclose(counterfactual_strength(0.60, 0.0), 0.75,
                            rel_tol=1e-12, abs_tol=1e-15)

    def test_monotone_decreasing_in_low_vol(self):
        assert counterfactual_strength(0.7, 0.2) > counterfactual_strength(0.7, 0.8)

    def test_nan_low_vol_not_finite(self):
        assert math.isnan(counterfactual_strength(0.7, float("nan")))


class TestCounterfactualPoolReadout:
    def test_membership_counts_oracle(self):
        work = analyze(_cf_pool_fixture())  # 只为复用列加工; 读数函数直接吃 work
        # analyze 返回 payload 而非 frame — 池面读数经内部加工列, 用专用入口测试
        from scripts.strength_component_decomposition import _cf_work_frame
        frame = _cf_work_frame(_cf_pool_fixture())
        out = counterfactual_pool_readout(frame, floor=0.50)
        assert out["n_old"] == 32   # B+N 各 16
        assert out["n_new"] == 32   # G+N 各 16
        assert out["entered"] == 16  # G 全入
        assert out["left"] == 16     # B 全出
        # E 手算: old = (−0.10+0.008)/2 均值档, new = (+0.095+0.008)/2 均值档
        old_e = out["stats_old"]["expectancy"]
        new_e = out["stats_new"]["expectancy"]
        assert old_e < 0 and new_e > 0
        assert math.isclose(out["delta_point"], new_e - old_e,
                            rel_tol=1e-9, abs_tol=1e-12)
        # 两侧 ≥MIN_CELL_N → CI 落地且强分离下界为正 (hi=new, lo=old 语义)
        ci = out["delta_ci"]
        assert isinstance(ci, dict) and ci["ci_low"] > 0 and ci["ci_high"] > ci["ci_low"]

    def test_small_cell_no_fake_ci(self):
        from scripts.strength_component_decomposition import _cf_work_frame
        frame = _cf_work_frame(_cf_pool_fixture(n_days=3))
        out = counterfactual_pool_readout(frame, floor=0.50)
        assert out["n_old"] == 6 and out["n_new"] == 6
        assert out["delta_ci"] is None  # <MIN_CELL_N 不冒充

    def test_unknown_low_vol_excluded_both_sides(self):
        from scripts.strength_component_decomposition import _cf_work_frame
        ev = _cf_pool_fixture(n_days=2)
        ev.loc[ev.index[0], "low_vol_score"] = float("nan")
        frame = _cf_work_frame(ev)
        out = counterfactual_pool_readout(frame, floor=0.50)
        # 6 行中 1 行低波缺失: recomputable=5 (全表口径), 该行两侧都不计
        assert frame.attrs["cf_recomputable_n"] == 5
        assert frame.attrs["cf_excluded_unknown_n"] == 1
        assert out["n_old"] + out["n_new"] <= 2 * 5

    def test_deterministic(self):
        from scripts.strength_component_decomposition import _cf_work_frame
        a = json.dumps(counterfactual_pool_readout(
            _cf_work_frame(_cf_pool_fixture()), floor=0.50),
            ensure_ascii=False, sort_keys=True)
        b = json.dumps(counterfactual_pool_readout(
            _cf_work_frame(_cf_pool_fixture()), floor=0.50),
            ensure_ascii=False, sort_keys=True)
        assert a == b


class TestCounterfactualSelectionReadout:
    def test_rank_flip_oracle(self):
        from scripts.strength_component_decomposition import _cf_work_frame
        frame = _cf_work_frame(_cf_selection_fixture())
        out = counterfactual_selection_readout(frame, floor=0.50, k=3)
        assert out["days_used"] == 12 and out["days_skipped"] == 0
        assert out["overlap_picks"] == 0  # 旧选坏 3 行 / 新选好 3 行, 不相交
        old_e = out["stats_old"]["expectancy"]
        new_e = out["stats_new"]["expectancy"]
        assert old_e < 0 and new_e > 0
        ci = out["delta_ci"]
        assert isinstance(ci, dict) and ci["ci_low"] > 0

    def test_day_skip_counted(self):
        from scripts.strength_component_decomposition import _cf_work_frame
        ev = _cf_selection_fixture()
        # 砍掉最后一日的 4 行 → 该日只剩 2 行 < k=3, 应跳过并计数
        last_day = "2026-04-12"
        drop_idx = ev.index[ev["signal_date"] == last_day][2:]
        ev = ev.drop(drop_idx)
        frame = _cf_work_frame(ev)
        out = counterfactual_selection_readout(frame, floor=0.50, k=3)
        assert out["days_skipped"] == 1
        assert out["days_used"] == 11

    def test_split_half_sign_surface(self):
        from scripts.strength_component_decomposition import _cf_work_frame
        frame = _cf_work_frame(_cf_selection_fixture())
        out = counterfactual_selection_readout(frame, floor=0.50, k=3)
        sh = out["split_half"]
        assert sh["available"] is True
        assert sh["sign_consistent"] is True  # 两半同构 → 同号

    def test_small_k_no_fake(self):
        from scripts.strength_component_decomposition import _cf_work_frame
        frame = _cf_work_frame(_cf_selection_fixture(n_days=2))
        out = counterfactual_selection_readout(frame, floor=0.50, k=3)
        # 2 日 × 6 行 = 12 picks/侧 < MIN_CELL_N → CI None 不冒充
        assert out["delta_ci"] is None


class TestCounterfactualWiring:
    def test_analyze_payload_keys(self):
        payload = analyze(_fixture_ev())
        cf = payload["counterfactual"]
        assert cf["available"] is True
        assert "0.20" in cf["renormalization"]
        assert cf["excluded_unknown_n"] == 0
        assert set(cf["pools"]) == {"ge050", "ge070"}
        assert set(cf["selection"]) == {"k3", "k5"}
        assert cf["selection"]["k3"]["k"] == 3
        assert cf["selection"]["k5"]["k"] == 5

    def test_analyze_unknown_lowvol_accounting(self):
        ev = _fixture_ev()
        ev.loc[ev.index[0], "low_vol_score"] = float("nan")
        cf = analyze(ev)["counterfactual"]
        assert cf["excluded_unknown_n"] == 1
        assert cf["recomputable_n"] == 7

    def test_payload_deterministic(self):
        a = json.dumps(analyze(_cf_selection_fixture()), ensure_ascii=False, sort_keys=True)
        b = json.dumps(analyze(_cf_selection_fixture()), ensure_ascii=False, sort_keys=True)
        assert a == b

    def test_render_includes_counterfactual_section(self):
        md = render_md(analyze(_cf_selection_fixture()))
        assert "反事实" in md
        assert "不是公式提案" in md          # 纪律句
        assert "稀释" in md                  # 池面混杂披露

    def test_render_missing_key_fail_open(self):
        # 缺 counterfactual 键 → 零新增字节不崩 (R142 F2 家族)
        payload = {"available": True, "n": 8, "pools": {}, "split_half": {}}
        md = render_md(payload)
        assert "反事实" not in md

    def test_cli_writes_counterfactual(self, tmp_path):
        court = tmp_path / "event_table_v1.csv.gz"
        _cf_selection_fixture().to_csv(court, index=False)
        rc = main([
            "--court-table", str(court),
            "--report-dir", str(tmp_path),
            "--date-str", "20260401",
        ])
        assert rc == 0
        body = (tmp_path / "strength_component_decomposition_20260401.md").read_text(encoding="utf-8")
        assert "反事实" in body
        payload = json.loads((tmp_path / "strength_component_decomposition_20260401.json").read_text(encoding="utf-8"))
        assert payload["counterfactual"]["available"] is True
