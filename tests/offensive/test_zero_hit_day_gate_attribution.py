"""R140 Op1: 零 hit 日门槛有效性归因 — 纯函数与聚合面 fixture 驱动测试。

fixture 全部非对称 (R13 教训: 对称 fixture 的数值断言无牙); 零本地数据
依赖 (R10 纪律: slot 验证必须自足)。
"""

from __future__ import annotations

import math

import pytest

import scripts.zero_hit_day_gate_attribution as zga
from scripts.winrate_payoff_decomposition import ROUNDTRIP_COST


class TestStageFamily:
    def test_c2_c3_c4_map_to_families(self):
        assert zga.stage_family("c2_flow_below_mean") == "c2_flow"
        assert zga.stage_family("c2_flow_missing") == "c2_flow"
        assert zga.stage_family("c3_industry_weak") == "c3_industry"
        assert zga.stage_family("c3_industry_missing") == "c3_industry"
        assert zga.stage_family("c4_runup_exceeded") == "c4_runup"
        assert zga.stage_family("c4_data_short") == "c4_runup"

    def test_structural_and_unknown(self):
        assert zga.stage_family("c0_prices_missing") == "structural"
        assert zga.stage_family("c1_limit_up_pct") == "structural"
        assert zga.stage_family("history_short") == "structural"
        assert zga.stage_family(None) == "structural"
        assert zga.stage_family("未来新增的 stage 标签") == "structural"


class TestDominantBlockedFamily:
    def test_empty_is_none_not_structural(self):
        assert zga.dominant_blocked_family({}) is None
        assert zga.dominant_blocked_family({"c3_industry_weak": 0}) is None

    def test_asymmetric_counts_pick_leader(self):
        counts = {"c3_industry_weak": 5, "c2_flow_below_mean": 1,
                  "c1_limit_up_pct": 2}
        assert zga.dominant_blocked_family(counts) == "c3_industry"

    def test_tie_is_mixed(self):
        assert zga.dominant_blocked_family(
            {"c3_industry_weak": 3, "c2_flow_below_mean": 3}
        ) == "mixed"

    def test_zero_count_entries_ignored(self):
        assert zga.dominant_blocked_family(
            {"c3_industry_weak": 0, "c2_flow_below_mean": 2}
        ) == "c2_flow"

    def test_structural_can_dominate(self):
        assert zga.dominant_blocked_family(
            {"c1_limit_up_pct": 4, "c3_industry_weak": 1}
        ) == "structural"

    def test_determinism_same_input_same_output(self):
        counts = {"c2_flow_below_mean": 7, "c4_runup_exceeded": 2,
                  "c3_industry_weak": 1}
        assert (
            zga.dominant_blocked_family(counts)
            == zga.dominant_blocked_family(dict(counts))
        )


class TestIsNearMiss:
    def test_boundary_strength_included(self):
        assert zga.is_near_miss("c3_industry_weak", 0.50) is True

    def test_below_threshold_excluded(self):
        assert zga.is_near_miss("c3_industry_weak", 0.4999) is False

    def test_structural_stages_excluded_even_with_strength(self):
        assert zga.is_near_miss("c1_limit_up_pct", 0.9) is False
        assert zga.is_near_miss("c0_prices_missing", 0.9) is False
        assert zga.is_near_miss(None, 0.9) is False

    def test_nan_strength_excluded(self):
        assert zga.is_near_miss("c2_flow_below_mean", float("nan")) is False

    def test_all_near_miss_stages_accepted(self):
        for stage in sorted(zga.NEAR_MISS_STAGES):
            assert zga.is_near_miss(stage, 0.50) is True, stage


class TestDayCounterfactualE:
    def test_empty_and_all_immature_are_none(self):
        assert zga.day_counterfactual_e([]) is None
        assert zga.day_counterfactual_e([None, None]) is None

    def test_ignores_immature_rows(self):
        # 非对称数值: 均值只由成熟行决定, None 不冒充 0
        assert zga.day_counterfactual_e([0.01, None, -0.03]) == pytest.approx(-0.01)

    def test_single_mature_row(self):
        assert zga.day_counterfactual_e([None, 0.02]) == pytest.approx(0.02)


def _row(day: str, regime: str, family: str, net: float | None) -> dict:
    return {
        "day": day,
        "regime": regime,
        "dominant_family": family,
        "net": net,
    }


class TestSummarizeGateEffectiveness:
    def test_empty_rows_honest_shape(self):
        s = zga.summarize_gate_effectiveness([])
        assert s["events_total"] == 0
        assert s["events_mature"] == 0
        assert s["days_with_mature"] == 0
        assert s["normal_regime_pooled"] == {
            "events": 0, "e": None, "ci90_low": None, "days": 0
        }
        assert s["day_e_distribution"] == {
            "protective_lt0": 0, "costly_gt0": 0, "flat_eq0": 0
        }

    def test_regime_split_and_direction_counts(self):
        rows = [
            # normal: 两保护日 + 一机会成本日 + 一全不成熟日
            _row("20250701", "normal", "c3_industry", -0.01),
            _row("20250701", "normal", "c3_industry", -0.03),
            _row("20250702", "normal", "c2_flow", -0.02),
            _row("20250703", "normal", "c4_runup", 0.04),
            _row("20250706", "normal", "c3_industry", None),
            # crisis: gate_blocked 行不入 normal 池
            _row("20250707", "crisis", "c3_industry", -0.05),
        ]
        s = zga.summarize_gate_effectiveness(rows)
        assert s["events_total"] == 6
        assert s["events_mature"] == 5
        assert s["days_with_mature"] == 4
        assert s["day_e_distribution"]["protective_lt0"] == 3
        assert s["day_e_distribution"]["costly_gt0"] == 1
        assert s["day_e_distribution"]["flat_eq0"] == 0
        nr = s["normal_regime_pooled"]
        assert nr["events"] == 4
        assert nr["days"] == 3
        assert nr["e"] == pytest.approx((-0.01 - 0.03 - 0.02 + 0.04) / 4)
        gb = s["gate_blocked_pooled"]
        assert gb["events"] == 1
        assert gb["e"] == pytest.approx(-0.05)
        assert s["by_dominant_family"]["c3_industry"]["events"] == 3
        assert s["by_dominant_family"]["c2_flow"]["events"] == 1
        assert s["by_dominant_family"]["mixed"]["events"] == 0

    def test_ci_below_min_cell_n_is_none(self):
        rows = [_row("20250701", "normal", "c3_industry", -0.01)]
        s = zga.summarize_gate_effectiveness(rows)
        assert s["normal_regime_pooled"]["ci90_low"] is None

    def test_ci_deterministic_per_call(self):
        # R13 纪律: 同输入两次调用恒等 (per-call seeded, 与调用历史无关)
        rows = [
            _row("20250701" if i % 2 == 0 else "20250702", "normal",
                 "c3_industry", (-1) ** i * (0.001 + i / 1000))
            for i in range(40)
        ]
        first = zga.summarize_gate_effectiveness(rows)
        second = zga.summarize_gate_effectiveness(list(reversed(rows)))
        # 同一集合 (行序无关的池化语义) → CI 恒等
        assert first["normal_regime_pooled"]["ci90_low"] == pytest.approx(
            second["normal_regime_pooled"]["ci90_low"]
        )
        assert isinstance(first["normal_regime_pooled"]["ci90_low"], float)


class TestRenderMd:
    def _payload(self) -> dict:
        return {
            "generated_at": "20260907",
            "gate_ts": 0.50,
            "primary_horizon": 10,
            "zero_hit_days_n": 1,
            "replay_hit_days": ["20250701"],
            "court_binding": {
                "window_start": "20250701",
                "window_end": "20260904",
                "rows": 1950,
                "content_digest": "sha256:abc",
            },
            "days": [
                {
                    "day": "20250701",
                    "regime": "normal",
                    "dominant_family": "c3_industry",
                    "candidates": 81,
                    "near_miss_n": 3,
                    "mature_n": 2,
                    "counterfactual_e": -0.02,
                    "replay_hits": 1,
                }
            ],
            "summary": zga.summarize_gate_effectiveness(
                [
                    _row("20250701", "normal", "c3_industry", -0.01),
                    _row("20250701", "normal", "c3_industry", -0.03),
                ]
            ),
        }

    def test_renders_key_numbers_and_disclosure(self):
        md = zga.render_md(self._payload())
        assert "零 hit 日门槛有效性归因" in md
        assert "重放 hit 披露" in md and "20250701" in md
        assert "c3 行业/市场状态" in md
        assert "-2.00%" in md  # 日反事实 E

    def test_missing_values_render_dash_not_crash(self):
        payload = self._payload()
        payload["summary"]["normal_regime_pooled"] = {
            "events": 0, "e": None, "ci90_low": None, "days": 0
        }
        payload["days"][0]["counterfactual_e"] = None
        md = zga.render_md(payload)
        assert "—" in md
        assert "None" not in md

    def test_no_replay_hit_days_no_disclosure_line(self):
        payload = self._payload()
        payload["replay_hit_days"] = []
        md = zga.render_md(payload)
        assert "重放 hit 披露" not in md


def _ev(ts_code: str, day: str, *, gross_t10: float | None, **overrides) -> dict:
    """合成近失事件行 (_build_event 生产对齐列 + _stage/_strength, 数值非对称)。"""
    ev = {
        "symbol": ts_code.split(".")[0],
        "ts_code": ts_code,
        "signal_date": day,
        "regime": "normal",
        "trigger_strength": 0.55,
        "signal_close": 10.0,
        "gap_t1_open": 0.01,
        "fillable": True,
        "t1_unbuyable": False,
        "t1_missing_bar": False,
        "degraded": False,
        "industry_missing": False,
        "st_name": False,
        "excluded_ticker": False,
        "price_ge_3": True,
        "gate_blocked": False,
        "gross_ret_t10": gross_t10,
        "_stage": "c3_industry_weak",
        "_strength": 0.55,
    }
    ev.update(overrides)
    return ev


class TestAlignedCounterfactualRows:
    REGIME = {"20250701": "normal", "20250702": "crisis"}

    def test_empty_input_empty_rows(self):
        assert zga.aligned_counterfactual_rows([], self.REGIME) == []

    def test_mature_fillable_row_survives_with_net(self):
        rows = zga.aligned_counterfactual_rows(
            [_ev("000001.SZ", "20250701", gross_t10=0.10)], self.REGIME
        )
        assert len(rows) == 1
        assert rows[0]["net"] == pytest.approx(0.10 - ROUNDTRIP_COST)
        assert rows[0]["day"] == "20250701"
        assert rows[0]["regime"] == "normal"
        assert rows[0]["stage"] == "c3_industry_weak"

    def test_unfillable_row_missing_exit_key_normalized_and_dropped(self):
        ev = _ev("000001.SZ", "20250701", gross_t10=None, fillable=False)
        del ev["gross_ret_t10"]  # _build_event 不可成交分支不带 exit 键
        assert zga.aligned_counterfactual_rows([ev], self.REGIME) == []

    def test_production_exclusions_dropped(self):
        rows = zga.aligned_counterfactual_rows(
            [
                _ev("000001.SZ", "20250701", gross_t10=0.10, st_name=True),
                _ev("000002.SZ", "20250701", gross_t10=0.10, price_ge_3=False),
                _ev("000004.SZ", "20250701", gross_t10=0.10, degraded=True),
                _ev("000005.SZ", "20250701", gross_t10=0.10, excluded_ticker=True),
                _ev("000006.SZ", "20250701", gross_t10=0.10, industry_missing=True),
                _ev("000007.SZ", "20250701", gross_t10=0.10, gate_blocked=True),
                _ev("000008.SZ", "20250701", gross_t10=None),
                _ev("000009.SZ", "20250701", gross_t10=0.06),
            ],
            self.REGIME,
        )
        assert [r["ts_code"] for r in rows] == ["000009.SZ"]


class TestCollectFailClosed:
    def test_missing_manifest_typed_exit(self, tmp_path):
        with pytest.raises(SystemExit, match="manifest 缺失"):
            zga.collect_zero_hit_day_attribution(tmp_path, tmp_path, "20260907")

    def test_corrupt_manifest_typed_exit(self, tmp_path):
        (tmp_path / "manifest_v1.json").write_text("{broken", encoding="utf-8")
        with pytest.raises(SystemExit, match="损坏"):
            zga.collect_zero_hit_day_attribution(tmp_path, tmp_path, "20260907")

    def test_legacy_manifest_without_zero_hit_days(self, tmp_path):
        (tmp_path / "manifest_v1.json").write_text('{"rows": 1}', encoding="utf-8")
        with pytest.raises(SystemExit, match="zero_hit_days"):
            zga.collect_zero_hit_day_attribution(tmp_path, tmp_path, "20260907")

    def test_corrupt_zero_hit_record_typed_exit(self, tmp_path):
        (tmp_path / "manifest_v1.json").write_text(
            '{"zero_hit_days": ["20250701"]}', encoding="utf-8"
        )
        with pytest.raises(SystemExit, match="损坏"):
            zga.collect_zero_hit_day_attribution(tmp_path, tmp_path, "20260907")
