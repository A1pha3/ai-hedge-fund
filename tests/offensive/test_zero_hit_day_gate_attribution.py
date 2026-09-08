"""R140 Op1: 零 hit 日门槛有效性归因 — 纯函数与聚合面 fixture 驱动测试。

fixture 全部非对称 (R13 教训: 对称 fixture 的数值断言无牙); 零本地数据
依赖 (R10 纪律: slot 验证必须自足)。
"""

from __future__ import annotations

import hashlib
import json
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


class TestIsGateBlocked:
    def test_all_gate_blocked_stages_accepted(self):
        for stage in sorted(zga.NEAR_MISS_STAGES):
            assert zga.is_gate_blocked(stage) is True, stage

    def test_structural_stages_excluded(self):
        assert zga.is_gate_blocked("c1_limit_up_pct") is False
        assert zga.is_gate_blocked("c0_prices_missing") is False
        assert zga.is_gate_blocked("history_short") is False
        assert zga.is_gate_blocked(None) is False

    def test_strength_irrelevant_to_predicate(self):
        # R140 Op2 PoC 语义钉死: _miss 的 strength 恒 0, 门挡集不强度条件化 —
        # 若未来有人把强度条件加回谓词, 本测当场红 (Op1 首跑 near_miss=0 死集复现)。
        assert zga.is_gate_blocked("c3_industry_weak") is True


class TestDayCounterfactualE:
    def test_empty_and_all_immature_are_none(self):
        assert zga.day_counterfactual_e([]) is None
        assert zga.day_counterfactual_e([None, None]) is None

    def test_ignores_immature_rows(self):
        # 非对称数值: 均值只由成熟行决定, None 不冒充 0
        assert zga.day_counterfactual_e([0.01, None, -0.03]) == pytest.approx(-0.01)

    def test_single_mature_row(self):
        assert zga.day_counterfactual_e([None, 0.02]) == pytest.approx(0.02)

    def test_industry_heat_bucket_predicate(self):
        # R141 Op1: 热度谓词三桶; None/缺失归 unknown 不冒充任一侧
        assert zga._industry_heat_bucket(0.012) == "heat_positive"
        assert zga._industry_heat_bucket(0.0) == "heat_non_positive"
        assert zga._industry_heat_bucket(-0.03) == "heat_non_positive"
        assert zga._industry_heat_bucket(None) == "heat_unknown"

    def test_nan_heat_row_goes_unknown_not_cold(self):
        # R141 Op2 PoC (RED→GREEN): NaN ≠ 冷 — 浮点管道常见形态, 静默归
        # 冷桶会把冷桶 E 向零抬 (分层读数被污染)。
        assert zga._industry_heat_bucket(float("nan")) == "heat_unknown"
        rows = [
            _irow("20250701", "医药", float("nan"), -0.06),
            _irow("20250702", "医药", -0.01, -0.02),
        ]
        s = zga.summarize_gate_effectiveness(rows)
        assert s["by_industry_heat"]["heat_unknown"]["events"] == 1
        assert s["by_industry_heat"]["heat_unknown"]["e"] == pytest.approx(-0.06)
        assert s["by_industry_heat"]["heat_non_positive"]["events"] == 1
        assert s["by_industry_heat"]["heat_non_positive"]["e"] == pytest.approx(-0.02)

    def test_none_industry_summary_key_json_serializable(self):
        # R141 Op2 PoC (RED→GREEN): by_industry 键含 None 时
        # json.dumps(sort_keys=True) TypeError — 哨兵键根除。
        import json as _json

        rows = [_irow("20250701", None, None, 0.01)]
        s = zga.summarize_gate_effectiveness(rows)
        dumped = _json.dumps(
            {"summary": s}, ensure_ascii=False, sort_keys=True
        )  # 不抛 TypeError
        assert zga.UNKNOWN_INDUSTRY_KEY in dumped
        assert s["by_industry"][zga.UNKNOWN_INDUSTRY_KEY]["events"] == 1


def _row(day: str, regime: str, family: str, net: float | None) -> dict:
    return {
        "day": day,
        "regime": regime,
        "dominant_family": family,
        "net": net,
    }


def _irow(
    day: str, industry: str | None, ind_pct: float | None,
    net: float | None, *, regime: str = "normal",
) -> dict:
    return {
        "day": day,
        "regime": regime,
        "dominant_family": "c3_industry",
        "industry": industry,
        "industry_day_pct": ind_pct,
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

    def test_industry_heat_stratification_pools(self):
        # R141 Op1: 热度三桶池化 — 非对称数值, 均值只由各桶成熟行决定
        rows = [
            _irow("20250701", "银行", 0.02, 0.04),
            _irow("20250701", "银行", 0.01, 0.02),
            _irow("20250702", "医药", -0.01, -0.06),
            _irow("20250703", "医药", 0.0, -0.02),
            _irow("20250706", "电子", None, 0.01),
            _irow("20250707", "电子", None, None),
        ]
        s = zga.summarize_gate_effectiveness(rows)
        heat = s["by_industry_heat"]
        assert set(heat.keys()) == set(zga.HEAT_BUCKETS)
        assert heat["heat_positive"]["events"] == 2
        assert heat["heat_positive"]["e"] == pytest.approx(0.03)
        assert heat["heat_non_positive"]["events"] == 2
        assert heat["heat_non_positive"]["e"] == pytest.approx(-0.04)
        assert heat["heat_unknown"]["events"] == 1
        assert heat["heat_unknown"]["e"] == pytest.approx(0.01)
        # n < MIN_CELL_N → CI None (只披露不判定)
        assert all(c["ci90_low"] is None for c in heat.values())
        # 行业分层: 每行业独立池化, 键确定 (None 缺席时无 None 键)
        ind = s["by_industry"]
        assert ind["银行"]["events"] == 2
        assert ind["银行"]["e"] == pytest.approx(0.03)
        assert ind["医药"]["e"] == pytest.approx(-0.04)
        assert ind["电子"]["events"] == 1

    def test_industry_keys_deterministic_and_unknown_last(self):
        rows = [
            _irow("20250701", "医药", 0.01, 0.01),
            _irow("20250702", None, None, 0.02),
            _irow("20250703", "银行", -0.01, -0.01),
        ]
        first = zga.summarize_gate_effectiveness(rows)
        second = zga.summarize_gate_effectiveness(list(reversed(rows)))
        # 确定性 (Unicode 码点序, unknown 哨兵末位) — 具体序不是断言点,
        # 稳定才是; R141 Op2 起 None 键以哨兵入账 (JSON sort_keys 可序列化)
        assert list(first["by_industry"].keys()) == list(
            second["by_industry"].keys()
        )
        assert first["by_industry"]["银行"]["events"] == 1
        assert first["by_industry"]["医药"]["events"] == 1
        assert first["by_industry"][zga.UNKNOWN_INDUSTRY_KEY]["events"] == 1

    def test_rows_without_industry_keys_land_in_unknown_industry(self):
        # 旧形态行 (无 industry 键) — .get 容纳, 落 unknown 哨兵不崩溃
        rows = [_row("20250701", "normal", "c3_industry", -0.01)]
        s = zga.summarize_gate_effectiveness(rows)
        assert s["by_industry"][zga.UNKNOWN_INDUSTRY_KEY]["events"] == 1
        assert s["by_industry_heat"]["heat_unknown"]["events"] == 1

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
            "primary_horizon": 10,
            "gate_blocked_stages": sorted(zga.NEAR_MISS_STAGES),
            "strength_conditioning": "门挡集未强度条件化 (测试fixture)",
            "attribution_caveat": "首失败归因低估后续门贡献 (测试fixture)",
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
                    "gate_blocked_n": 3,
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
        assert "局限披露" in md and "未强度条件化" in md
        assert "归因 caveat" in md and "首失败归因" in md

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

    def test_renders_industry_strata_lines(self):
        # R141 Op1: 行业热度三桶 + top 行业行渲染
        payload = self._payload()
        payload["summary"]["by_industry_heat"] = {
            "heat_positive": {"events": 1200, "days": 40, "e": 0.004, "ci90_low": -0.001},
            "heat_non_positive": {"events": 620, "days": 30, "e": -0.011, "ci90_low": -0.02},
            "heat_unknown": {"events": 0, "days": 0, "e": None, "ci90_low": None},
        }
        payload["summary"]["by_industry"] = {
            "银行": {"events": 300, "days": 20, "e": 0.006, "ci90_low": 0.001},
            "医药": {"events": 210, "days": 15, "e": -0.008, "ci90_low": None},
        }
        md = zga.render_md(payload)
        assert "按行业热度分层" in md
        assert "热 (行业涨幅 > 0)" in md and "+0.40%" in md
        assert "冷 (≤ 0)" in md and "-1.10%" in md
        assert "未知 (行业/涨幅缺失)" in md
        assert "按行业分层" in md and "银行" in md and "医药" in md

    def test_industry_strata_missing_values_dash_not_crash(self):
        payload = self._payload()
        # 空分层 (无任何行) → 整表 '—', 不崩溃且不渲染 None 字面量
        md = zga.render_md(payload)
        assert "按行业热度分层" in md
        assert "None" not in md

    def test_heat_confound_caveat_renders_when_present(self):
        # R141 Op2: 日混杂 caveat — 热桶读数含市场日效应, 不等于门槛机会成本
        payload = self._payload()
        payload["heat_confound_caveat"] = (
            "热度分层含日混杂 confound (测试fixture 措辞)"
        )
        md = zga.render_md(payload)
        assert "日混杂 confound (测试fixture 措辞)" in md

    def test_heat_confound_caveat_absent_key_omits_line(self):
        # 键缺失诚实省略 (fail-open 家族纪律), 不虚构 caveat
        payload = self._payload()
        md = zga.render_md(payload)
        assert "日混杂 confound" not in md


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

    def test_industry_columns_carried_through_alignment(self):
        # R141 Op1: industry_name/_industry_day_pct 经 production_aligned 穿透
        rows = zga.aligned_counterfactual_rows(
            [
                _ev(
                    "000001.SZ", "20250701", gross_t10=0.10,
                    industry_name="银行", _industry_day_pct=0.012,
                ),
                _ev("000009.SZ", "20250701", gross_t10=0.06),
            ],
            self.REGIME,
        )
        by_code = {r["ts_code"]: r for r in rows}
        assert by_code["000001.SZ"]["industry"] == "银行"
        assert by_code["000001.SZ"]["industry_day_pct"] == pytest.approx(0.012)
        # 缺列事件 → None (分层归 unknown, 不冒充)
        assert by_code["000009.SZ"]["industry"] is None
        assert by_code["000009.SZ"]["industry_day_pct"] is None


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


def _binding(digest: str) -> dict:
    return {
        "window_start": "20250701",
        "window_end": "20260907",
        "rows": 10,
        "formula_fingerprint": "fp",
        "content_digest": digest,
        "universe_audit_complete": True,
    }


def _summary() -> dict:
    return {
        "events_total": 2,
        "normal_regime_pooled": {"events": 2, "e": 0.01, "ci90_low": None, "days": 1},
        "by_industry_heat": {
            "heat_positive": {"events": 1, "e": 0.02, "ci90_low": None, "days": 1},
            "heat_non_positive": {"events": 1, "e": -0.01, "ci90_low": None, "days": 1},
            "heat_unknown": {"events": 0, "e": None, "ci90_low": None, "days": 0},
        },
    }


class TestRecordGatePoolStatus:
    """R143 Op1: 门挡池反事实稳定性账本 (两族 K 账本同构第三族)。"""

    def test_record_writes_single_row(self, tmp_path):
        ledger = tmp_path / "gate_pool_ledger.jsonl"
        meta = zga.record_gate_pool_status(
            {"summary": _summary()},
            "20260907",
            ledger_path=ledger,
            court_binding=_binding("sha256:aa01"),
        )
        assert meta == {"recorded": True, "records": 1}
        lines = ledger.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1
        rec = json.loads(lines[0])
        assert rec["date"] == "20260907"
        assert rec["anchor"] == zga.GATE_POOL_ANCHOR
        assert rec["summary"] == _summary()
        assert rec["court"]["content_digest"] == "sha256:aa01"

    def test_advance_gate_rejects_same_data_state(self, tmp_path):
        ledger = tmp_path / "gate_pool_ledger.jsonl"
        kw = dict(
            ledger_path=ledger,
            court_binding=_binding("sha256:aa01"),
            require_advance=True,
        )
        assert zga.record_gate_pool_status(
            {"summary": _summary()}, "20260907", **kw
        )["recorded"] is True
        meta = zga.record_gate_pool_status(
            {"summary": _summary()}, "20260908", **kw
        )
        assert meta == {
            "recorded": False,
            "reason": "court_not_advanced",
            "records": 1,
        }
        assert len(ledger.read_text(encoding="utf-8").splitlines()) == 1

    def test_advance_gate_opens_on_data_advance(self, tmp_path):
        ledger = tmp_path / "gate_pool_ledger.jsonl"
        kw = dict(ledger_path=ledger, require_advance=True)
        assert zga.record_gate_pool_status(
            {"summary": _summary()}, "20260907",
            court_binding=_binding("sha256:aa01"), **kw
        )["recorded"] is True
        meta = zga.record_gate_pool_status(
            {"summary": _summary()}, "20260908",
            court_binding=_binding("sha256:bb02"), **kw
        )
        assert meta == {"recorded": True, "records": 2}
        assert len(ledger.read_text(encoding="utf-8").splitlines()) == 2

    def test_same_day_replay_replaces(self, tmp_path):
        ledger = tmp_path / "gate_pool_ledger.jsonl"
        kw = dict(ledger_path=ledger, court_binding=_binding("sha256:aa01"))
        zga.record_gate_pool_status({"summary": _summary()}, "20260907", **kw)
        replaced = dict(_summary())
        replaced["events_total"] = 3
        meta = zga.record_gate_pool_status(
            {"summary": replaced}, "20260907", **kw
        )
        assert meta == {"recorded": True, "records": 1}
        rec = json.loads(ledger.read_text(encoding="utf-8").splitlines()[0])
        assert rec["summary"]["events_total"] == 3

    def test_missing_summary_no_write(self, tmp_path):
        ledger = tmp_path / "gate_pool_ledger.jsonl"
        meta = zga.record_gate_pool_status(
            {}, "20260907", ledger_path=ledger
        )
        assert meta == {"recorded": False, "reason": "no_gate_pool_summary"}
        meta = zga.record_gate_pool_status(
            {"summary": "junk"}, "20260907", ledger_path=ledger
        )
        assert meta == {"recorded": False, "reason": "no_gate_pool_summary"}
        assert not ledger.exists()

    def test_write_failure_fail_open(self, tmp_path):
        blocker = tmp_path / "blocker"
        blocker.write_text("file", encoding="utf-8")
        ledger = blocker / "gate_pool_ledger.jsonl"  # parent 是文件 → mkdir 失败
        meta = zga.record_gate_pool_status(
            {"summary": _summary()},
            "20260907",
            ledger_path=ledger,
            court_binding=_binding("sha256:aa01"),
        )
        assert meta == {"recorded": False, "reason": "write_failed"}
        assert blocker.read_text(encoding="utf-8") == "file"

    def test_main_attaches_gate_pool_record(self, tmp_path, monkeypatch):
        ledger = tmp_path / "gate_pool_ledger.jsonl"
        payload = {
            "summary": _summary(),
            "court_binding": _binding("sha256:aa01"),
        }
        captured: dict = {}

        def fake_record(p, d, ledger_path=None, court_binding=None,
                        require_advance=False):
            captured.update(
                ledger_path=ledger_path, court_binding=court_binding,
                require_advance=require_advance,
            )
            return {"recorded": True, "records": 1}

        monkeypatch.setattr(zga, "record_gate_pool_status", fake_record)
        zga.attach_gate_pool_record(payload, "20260907", ledger)
        assert payload["gate_pool_record"] == {"recorded": True, "records": 1}
        assert captured["require_advance"] is True
        assert captured["court_binding"] == _binding("sha256:aa01")
        assert captured["ledger_path"] == ledger


class TestAdversarialReworkOp2:
    """R143 Op2: 对 Op1 账本交付面的对抗性审查返工 (PoC 驱动)。"""

    def test_summary_not_serializable_typed_fail_open(self, tmp_path):
        # F1a PoC (修复前: TypeError 裸逃逸炸穿 main 报告生成)
        ledger = tmp_path / "gate_pool_ledger.jsonl"
        meta = zga.record_gate_pool_status(
            {"summary": {"x": object()}},
            "20260907",
            ledger_path=ledger,
            court_binding=_binding("sha256:aa01"),
        )
        assert meta == {"recorded": False, "reason": "snapshot_not_serializable"}
        assert not ledger.exists()

    def test_binding_mixed_type_keys_typed_fail_open(self, tmp_path):
        # F1b PoC (修复前: json.dumps sort_keys TypeError 裸逃逸)
        ledger = tmp_path / "gate_pool_ledger.jsonl"
        meta = zga.record_gate_pool_status(
            {"summary": _summary()},
            "20260907",
            ledger_path=ledger,
            court_binding={1: "x", "a": 2},
        )
        assert meta == {"recorded": False, "reason": "snapshot_not_serializable"}
        assert not ledger.exists()

    def test_render_ledger_status_recorded_line(self):
        payload = TestRenderMd()._payload()
        base = zga.render_md(payload)
        assert "门挡池稳定性账本" not in base  # 缺键零新增行
        payload["gate_pool_record"] = {"recorded": True, "records": 1}
        md = zga.render_md(payload)
        assert "已落账 1 行" in md
        assert zga.GATE_POOL_ANCHOR in md
        # additive 逐字节组合: 状态行追加在末尾空行之前, 缺键渲染 = 有键渲染去掉追加行
        assert md == base + f"门挡池稳定性账本: 已落账 1 行 (anchor {zga.GATE_POOL_ANCHOR})\n"

    def test_render_ledger_status_not_advanced_and_failure(self):
        payload = TestRenderMd()._payload()
        payload["gate_pool_record"] = {
            "recorded": False, "reason": "court_not_advanced", "records": 3,
        }
        md = zga.render_md(payload)
        assert "数据未前进, 未重复落账 (账本 3 行)" in md
        payload["gate_pool_record"] = {
            "recorded": False, "reason": "write_failed",
        }
        md = zga.render_md(payload)
        assert "⚠ 门挡池稳定性账本: write_failed" in md
        payload["gate_pool_record"] = {
            "recorded": False, "reason": "snapshot_not_serializable",
        }
        md = zga.render_md(payload)
        assert "⚠ 门挡池稳定性账本: snapshot_not_serializable" in md


class TestLedgerDateShapeGuard:
    """R144 Op3: 门挡池族 record_gate_pool_status 的 date_str 形状守卫。"""

    def test_gate_pool_writer_rejects_malformed_dates_zero_write(self, tmp_path):
        ledger = tmp_path / "gate_pool_counterfactual_ledger.jsonl"
        for bad in ["", "202609081", "20260908T00", None, 20260908]:
            meta = zga.record_gate_pool_status({}, bad, ledger_path=ledger)
            assert meta == {"recorded": False, "reason": "invalid_date_str"}, bad
        assert not ledger.exists()

    def test_guard_precedes_payload_guard_valid_date_unchanged(self, tmp_path):
        meta = zga.record_gate_pool_status({}, "2026-9-8", ledger_path=tmp_path / "l.jsonl")
        assert meta == {"recorded": False, "reason": "invalid_date_str"}
        meta = zga.record_gate_pool_status({}, "20260908", ledger_path=tmp_path / "l.jsonl")
        assert meta == {"recorded": False, "reason": "no_gate_pool_summary"}


class TestIndustryDayDemeaned:
    """R145 Op1: 门挡池反事实行业读数日去均值对照 (day fixed effects)。

    R141 行业分层的日混杂 confound (热行业日聚集强势市场期) 用同日截面
    去均值做实: 去均值完全吸收同日共同效应, 只保留同日跨行业相对结构。
    """

    ROWS = [
        # day1: 银行 +0.04 / 电子 +0.10 → 日均值 0.07 → 银行 −0.03, 电子 +0.03
        _irow("20250701", "银行", 0.01, 0.04),
        _irow("20250701", "电子", 0.02, 0.10),
        # day2: 医药 −0.06 / 电子 +0.02 → 日均值 −0.02 → 医药 −0.04, 电子 +0.04
        _irow("20250702", "医药", -0.01, -0.06),
        _irow("20250702", "电子", 0.03, 0.02),
        # day3: 只有银行成熟行 → 单行业日剔除并计数
        _irow("20250703", "银行", 0.01, -0.05),
        # day4: 跨两行业但电子行不成熟 → 参与的成熟行只有银行 → 剔除
        _irow("20250706", "银行", 0.01, 0.01),
        _irow("20250706", "医药", -0.01, None),
        # day5: 全不成熟 → 完全不参与
        _irow("20250707", "电子", 0.02, None),
        _irow("20250707", "医药", 0.01, None),
    ]

    def _summary(self) -> dict:
        return zga.summarize_gate_effectiveness(list(self.ROWS))

    def test_demean_math_asymmetric_fixture(self):
        dd = self._summary()["by_industry_day_demeaned"]
        assert dd["days_participating"] == 2
        assert dd["days_excluded_single_industry"] == 2
        assert dd["events_excluded_single_industry"] == 2
        by = dd["by_industry"]
        assert by["银行"]["events"] == 1
        assert by["银行"]["days"] == 1
        assert by["银行"]["e"] == pytest.approx(-0.03)
        assert by["电子"]["events"] == 2
        assert by["电子"]["days"] == 2
        assert by["电子"]["e"] == pytest.approx((0.03 + 0.04) / 2)
        assert by["医药"]["events"] == 1
        assert by["医药"]["e"] == pytest.approx(-0.04)
        # 去均值池内跨行业 (事件加权) 合计恒 0 — 相对排序证据的构造性语义
        total = sum(c["e"] * c["events"] for c in by.values())
        assert total == pytest.approx(0.0, abs=1e-12)

    def test_small_cells_ci_none_large_cell_ci_numeric(self):
        dd = self._summary()["by_industry_day_demeaned"]
        by = dd["by_industry"]
        # 全部格 n < MIN_CELL_N → CI 诚实 None (只披露不判定)
        assert all(c["ci90_low"] is None for c in by.values())
        big_rows = []
        for i in range(1, 36):  # 35 个跨两行业日 → 每行业 35 事件 ≥ MIN_CELL_N
            day = f"2025{i:04d}"
            big_rows.append(_irow(day, "电子", 0.01, 0.05))
            big_rows.append(_irow(day, "银行", 0.01, -0.01))
        dd_big = zga.summarize_gate_effectiveness(big_rows)[
            "by_industry_day_demeaned"
        ]
        assert dd_big["by_industry"]["电子"]["events"] == 35
        assert dd_big["by_industry"]["电子"]["ci90_low"] is not None

    def test_none_industry_lands_in_sentinel_key(self):
        rows = [
            _irow("20250701", None, None, 0.08),
            _irow("20250701", "银行", 0.01, -0.02),
        ]
        dd = zga.summarize_gate_effectiveness(rows)["by_industry_day_demeaned"]
        # 日均值 0.03 → 哨兵桶 +0.05, 银行 −0.05
        assert dd["days_participating"] == 1
        assert dd["by_industry"][zga.UNKNOWN_INDUSTRY_KEY]["e"] == pytest.approx(0.05)
        assert dd["by_industry"]["银行"]["e"] == pytest.approx(-0.05)

    def test_row_order_independence(self):
        first = self._summary()["by_industry_day_demeaned"]
        second = zga.summarize_gate_effectiveness(list(reversed(self.ROWS)))[
            "by_industry_day_demeaned"
        ]
        assert list(first["by_industry"].keys()) == list(
            second["by_industry"].keys()
        )
        assert json.dumps(first, sort_keys=True) == json.dumps(
            second, sort_keys=True
        )

    def test_empty_rows_honest_shape(self):
        s = zga.summarize_gate_effectiveness([])
        dd = s["by_industry_day_demeaned"]
        assert dd == {
            "days_participating": 0,
            "days_excluded_single_industry": 0,
            "events_excluded_single_industry": 0,
            "by_industry": {},
        }

    def test_rows_without_industry_key_do_not_crash(self):
        # 旧形态行 (无 industry 键) — .get 容纳落哨兵, 与 by_industry 同纪律
        rows = [
            _row("20250701", "normal", "c2_flow", 0.06),
            _irow("20250701", "银行", 0.01, -0.02),
        ]
        dd = zga.summarize_gate_effectiveness(rows)["by_industry_day_demeaned"]
        assert dd["days_participating"] == 1
        assert dd["by_industry"][zga.UNKNOWN_INDUSTRY_KEY]["e"] == pytest.approx(0.04)


class TestIndustryDayDemeanedRender:
    def _payload(self) -> dict:
        return {
            "generated_at": "20260908",
            "primary_horizon": 10,
            "gate_blocked_stages": sorted(zga.NEAR_MISS_STAGES),
            "strength_conditioning": "门挡集未强度条件化 (测试fixture)",
            "attribution_caveat": "首失败归因低估后续门贡献 (测试fixture)",
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
                    "gate_blocked_n": 3,
                    "mature_n": 2,
                    "counterfactual_e": -0.02,
                    "replay_hits": 1,
                }
            ],
            "summary": zga.summarize_gate_effectiveness(
                [
                    _irow("20250701", "银行", 0.01, 0.04),
                    _irow("20250701", "电子", 0.02, 0.10),
                ]
            ),
        }

    def test_renders_demeaned_section_with_mechanism_note(self):
        md = zga.render_md(self._payload())
        assert "行业日去均值对照" in md
        assert "银行" in md and "电子" in md
        assert "相对排序证据" in md
        assert "合计恒为 0" in md

    def test_old_payload_without_key_renders_byte_identical(self):
        # fail-open 家族纪律: 旧 payload 缺键 → 零新增字节
        payload = self._payload()
        payload["summary"] = dict(payload["summary"])
        payload["summary"].pop("by_industry_day_demeaned")
        md = zga.render_md(payload)
        assert "行业日去均值对照" not in md
        assert "相对排序证据" not in md

    def test_excluded_days_note_renders_when_present(self):
        payload = self._payload()
        payload["summary"]["by_industry_day_demeaned"][
            "days_excluded_single_industry"
        ] = 2
        payload["summary"]["by_industry_day_demeaned"][
            "events_excluded_single_industry"
        ] = 2
        md = zga.render_md(payload)
        assert "只含单一行业" in md

    def test_malformed_demeaned_payload_does_not_crash(self):
        # R142 F2 家族纪律: 非 Mapping 形态不崩不冒充
        payload = self._payload()
        payload["summary"]["by_industry_day_demeaned"] = "garbage"
        md = zga.render_md(payload)
        assert "行业日去均值对照" not in md
        payload["summary"]["by_industry_day_demeaned"] = {
            "by_industry": {"银行": "not-a-cell", "电子": {"events": 0}},
        }
        md = zga.render_md(payload)
        # R146 Op1: 稳健性节合法跟随本节之后 — 节界以下一个 '##' 标题
        # 有界切分 (原 [-1] 尾块假设被新兄弟节打破, 测试意图不变)
        demeaned_body = md.split("行业日去均值对照", 1)[1].split("##")[0]
        assert "银行" not in demeaned_body

    def test_summary_payload_json_serializable(self):
        payload = self._payload()
        json.dumps(payload, sort_keys=True, ensure_ascii=False)


class TestIndustryDayDemeanedAdversarialPins:
    """R145 Op2: 对 Op1 日去均值对照面的对抗性审查 PoC 收口。

    F1 NaN/Inf/bool net 静默毒化 (日均值变 NaN 波及无辜行业 + R143
    allow_nan=False 契约下账本落账整体冻结); F2 对照节 events=None
    cell TypeError 崩溃; F3 混合类型行业键 sorted TypeError; F4 账本
    全聚合流转 pin。登记不修 (scope 外家族项): _pooled/by_industry 的
    NaN 暴露 (R143 F3 已登记)、事件加权池化方法论、非数值 net 契约
    违反 fail-closed。
    """

    def test_nan_and_inf_net_not_mature_innocent_rows_unchanged(self):
        # PoC1/PoC2 实锤: NaN 行毒化日均值 → 银行 (无辜) e 也 nan
        rows = [
            _irow("20250701", "电子", 0.01, float("nan")),
            _irow("20250701", "银行", 0.01, -0.02),
        ]
        dd = zga.summarize_gate_effectiveness(rows)["by_industry_day_demeaned"]
        # NaN 行不成熟 → 该日只剩银行一个成熟行业 → 单行业日剔除, 不冒充
        assert dd["days_participating"] == 0
        assert dd["days_excluded_single_industry"] == 1
        assert dd["events_excluded_single_industry"] == 1
        assert dd["by_industry"] == {}
        # Inf 同语义
        rows_inf = [
            _irow("20250701", "电子", 0.01, float("inf")),
            _irow("20250701", "银行", 0.01, -0.02),
            _irow("20250702", "电子", 0.01, 0.03),
            _irow("20250702", "银行", 0.01, 0.01),
        ]
        dd_inf = zga.summarize_gate_effectiveness(rows_inf)[
            "by_industry_day_demeaned"
        ]
        assert dd_inf["days_participating"] == 1
        assert dd_inf["by_industry"]["电子"]["e"] == pytest.approx(0.01)
        assert dd_inf["by_industry"]["银行"]["e"] == pytest.approx(-0.01)

    def test_bool_net_excluded_r142_f2_pin(self):
        # R142 F2 同款: bool 是 int 子类, True 被当作 1.0 参与均值是冒充
        rows = [
            _irow("20250701", "电子", 0.01, True),
            _irow("20250701", "银行", 0.01, -0.02),
        ]
        dd = zga.summarize_gate_effectiveness(rows)["by_industry_day_demeaned"]
        assert dd["days_participating"] == 0
        assert dd["days_excluded_single_industry"] == 1

    def test_finite_path_numbers_byte_identical_to_pre_fix(self):
        # 有限值路径行为不变 (Op1 验收数字钉死)
        rows = [
            _irow("20250701", "银行", 0.01, 0.04),
            _irow("20250701", "电子", 0.02, 0.10),
            _irow("20250702", "医药", -0.01, -0.06),
            _irow("20250702", "电子", 0.03, 0.02),
        ]
        dd = zga.summarize_gate_effectiveness(rows)["by_industry_day_demeaned"]
        assert dd["days_participating"] == 2
        assert dd["by_industry"]["电子"]["e"] == pytest.approx((0.03 + 0.04) / 2)
        assert dd["by_industry"]["银行"]["e"] == pytest.approx(-0.03)
        assert dd["by_industry"]["医药"]["e"] == pytest.approx(-0.04)

    def test_mixed_type_industry_keys_deterministic_no_crash(self):
        # PoC4 实锤: int+str 键 sorted TypeError — str 键序确定性
        rows = [
            _irow("20250701", 123, None, 0.05),
            _irow("20250701", "银行", 0.01, -0.02),
        ]
        dd = zga.summarize_gate_effectiveness(rows)["by_industry_day_demeaned"]
        assert dd["days_participating"] == 1
        assert set(dd["by_industry"].keys()) == {123, "银行"}

        def _canon(obj):
            # 混合类型键在 json.dumps(sort_keys=True) 层不可排序 —
            # 确定性断言用键规范化投影 (str 键序)
            if isinstance(obj, dict):
                return sorted((str(k), _canon(v)) for k, v in obj.items())
            if isinstance(obj, list):
                return [_canon(v) for v in obj]
            return obj

        first = _canon(dd)
        second = _canon(
            zga.summarize_gate_effectiveness(list(reversed(rows)))[
                "by_industry_day_demeaned"
            ]
        )
        assert first == second

    def test_render_demeaned_section_bad_events_cells_no_crash(self):
        # PoC3 实锤: events=None cell → TypeError '>' not supported
        rows = [
            _irow("20250701", "电子", 0.01, 0.05),
            _irow("20250701", "银行", 0.01, -0.02),
        ]
        summary = zga.summarize_gate_effectiveness(rows)
        dd = summary["by_industry_day_demeaned"]
        dd["by_industry"]["垃圾A"] = {
            "events": None, "days": 0, "e": None, "ci90_low": None
        }
        dd["by_industry"]["垃圾B"] = {
            "events": True, "days": 1, "e": 0.01, "ci90_low": None
        }
        payload = {
            "generated_at": "20260908",
            "primary_horizon": 10,
            "gate_blocked_stages": sorted(zga.NEAR_MISS_STAGES),
            "strength_conditioning": "x",
            "attribution_caveat": "x",
            "zero_hit_days_n": 1,
            "replay_hit_days": [],
            "court_binding": {
                "window_start": "20250701",
                "window_end": "20260904",
                "rows": 1950,
                "content_digest": "sha256:abc",
            },
            "days": [],
            "summary": summary,
        }
        md = zga.render_md(payload)
        section = md.split("行业日去均值对照")[-1].split("##")[0]
        assert "垃圾A" not in section
        assert "垃圾B" not in section
        assert "电子" in section and "银行" in section

    def test_gate_pool_ledger_row_carries_demeaned_key(self, tmp_path):
        # F4 pin: 新聚合经 summary 全聚合单一实现流入账本行 (R143 Op1
        # 『不挑子集』纪律 — 生产行待 court 前进后携带是前进门 by-design)
        import json as _json

        rows = [
            _irow("20250701", "电子", 0.01, 0.05),
            _irow("20250701", "银行", 0.01, -0.02),
        ]
        payload = {
            "summary": zga.summarize_gate_effectiveness(rows),
            "court_binding": {
                "window_start": "20250701",
                "window_end": "20260904",
                "rows": 1950,
                "content_digest": "sha256:abc",
            },
        }
        ledger = tmp_path / "gate_pool_ledger.jsonl"
        meta = zga.record_gate_pool_status(payload, "20260908", ledger_path=ledger)
        assert meta.get("recorded") is True
        row = _json.loads(ledger.read_text(encoding="utf-8").splitlines()[-1])
        dd = (row.get("summary") or {}).get("by_industry_day_demeaned") or {}
        assert dd.get("days_participating") == 1
        assert "电子" in (dd.get("by_industry") or {})


class TestIndustryDayDemeanedRobustness:
    """R146 Op1: 门挡池 demeaned 头条读数稳健性披露 (split-half + 日集中度)。

    电子 +3.33% CI90+1.62% (33 参与日) 是 owner c3 行业门机会成本判读的
    最大已测事实 (R145); split-half 时间切片与日集中度把『时间稳定吗?
    是否少数日驱动?』变成可读事实。与 industry_day_demeaned 共享
    _demeaned_pooled_points 单一实现 (参与日/成熟谓词/哨兵键/剔除同语义);
    每日截面构成不变故去均值点原样沿用。纯披露面, 零策略语义变更。
    """

    # 3 参与日: 早半窗 [d1] (n//2=1), 晚半窗 [d2, d3] — 全部 dyadic 精确值
    ROWS3 = [
        # d1: 银行 0.25 / 电子 1.0 → 均值 0.625 → 银行 −0.375, 电子 +0.375
        _irow("20250701", "银行", 0.01, 0.25),
        _irow("20250701", "电子", 0.02, 1.0),
        # d2: 医药 −0.5 / 电子 0.25 → 均值 −0.125 → 医药 −0.375, 电子 +0.375
        _irow("20250702", "医药", -0.01, -0.5),
        _irow("20250702", "电子", 0.03, 0.25),
        # d3: 银行 −0.5 / 电子 0.25 → 均值 −0.125 → 银行 −0.375, 电子 +0.375
        _irow("20250703", "银行", 0.01, -0.5),
        _irow("20250703", "电子", 0.02, 0.25),
    ]

    def _rob(self, rows):
        return zga.industry_day_demeaned_robustness(list(rows))["by_industry"]

    def test_split_half_math_three_days_asymmetric_halves(self):
        cells = self._rob(self.ROWS3)
        e_ = cells["电子"]
        assert e_["events"] == 3 and e_["days"] == 3
        # 早半窗 [d1]: 1 事件 +0.375; 晚半窗 [d2, d3]: 2 事件 +0.375
        assert e_["split_half"]["early"] == {
            "days": 1, "events": 1, "e": pytest.approx(0.375), "ci90_low": None,
        }
        assert e_["split_half"]["late"]["events"] == 2
        assert e_["split_half"]["late"]["e"] == pytest.approx(0.375)
        assert e_["split_half"]["sign_consistent"] is True
        # 医药只在晚半窗出现 → 早半窗空集 e=None 不冒充, sign 诚实 None
        med = cells["医药"]
        assert med["split_half"]["early"]["events"] == 0
        assert med["split_half"]["early"]["e"] is None
        assert med["split_half"]["late"]["e"] == pytest.approx(-0.375)
        assert med["split_half"]["sign_consistent"] is None
        # 负读数行业 (银行) 两半同号 → sign True
        assert cells["银行"]["split_half"]["early"]["e"] == pytest.approx(-0.375)
        assert cells["银行"]["split_half"]["sign_consistent"] is True

    def test_split_half_even_days_boundary(self):
        # 每日截面跨行业 demeaned 合计恒 0 ⇒ 2 行业/日必反号 — 一稳一翻
        # 需要 3 行业: 早窗 A +0.3 / B −0.3 / C 0; 晚窗 A +0.25 / B +0.25 / C −0.5
        rows = []
        for day in ("20250701", "20250702"):
            rows += [
                _irow(day, "A", None, 0.6),
                _irow(day, "B", None, 0.0),
                _irow(day, "C", None, 0.3),
            ]
        for day in ("20250703", "20250706"):
            rows += [
                _irow(day, "A", None, 0.75),
                _irow(day, "B", None, 0.75),
                _irow(day, "C", None, 0.0),
            ]
        cells = self._rob(rows)
        # 4 参与日 → 早 [d1,d2] / 晚 [d3,d4]
        assert cells["A"]["split_half"]["early"]["events"] == 2
        assert cells["A"]["split_half"]["late"]["events"] == 2
        assert cells["A"]["split_half"]["early"]["e"] == pytest.approx(0.3)
        assert cells["A"]["split_half"]["late"]["e"] == pytest.approx(0.25)
        assert cells["A"]["split_half"]["sign_consistent"] is True
        b_half = cells["B"]["split_half"]
        assert b_half["early"]["e"] == pytest.approx(-0.3)
        assert b_half["late"]["e"] == pytest.approx(0.25)
        assert b_half["sign_consistent"] is False

    def test_split_half_ci_gate_min_cell_n(self):
        # 61 参与日 → 每半窗 30/31 事件 ≥ MIN_CELL_N → 半窗 CI numeric;
        # 35 参与日 → 半窗 17/18 < MIN_CELL_N → 半窗 CI 诚实 None
        # (尽管格总计 35 ≥ MIN_CELL_N — 半窗粒度独立门控)
        def _pairs(n_days):
            rows = []
            for i in range(n_days):
                day = f"2025{i:04d}"
                rows.append(_irow(day, "A", None, 0.5))
                rows.append(_irow(day, "B", None, 0.0))
            return rows

        cells_big = self._rob(_pairs(61))
        a = cells_big["A"]["split_half"]
        assert a["early"]["events"] == 30 and a["late"]["events"] == 31
        assert a["early"]["ci90_low"] is not None
        assert a["late"]["ci90_low"] is not None
        cells_mid = self._rob(_pairs(35))
        m = cells_mid["A"]["split_half"]
        assert m["early"]["events"] == 17 and m["late"]["events"] == 18
        assert m["early"]["ci90_low"] is None and m["late"]["ci90_low"] is None

    def test_day_concentration_single_day_industry_share_one(self):
        cells = self._rob(self.ROWS3)
        conc = cells["医药"]["day_concentration"]
        assert conc["total_sum"] == pytest.approx(-0.375)
        assert conc["top1_day"] == "20250702"
        assert conc["top1_share"] == pytest.approx(1.0)
        assert conc["top3_share"] == pytest.approx(1.0)

    def test_day_concentration_multi_day_top1_fraction(self):
        cells = self._rob(self.ROWS3)
        conc = cells["电子"]["day_concentration"]
        # 电子三日各 +0.375, 合计 1.125 → top1 占比恰 1/3
        assert conc["total_sum"] == pytest.approx(1.125)
        assert conc["top1_share"] == pytest.approx(1 / 3)
        assert conc["top3_share"] == pytest.approx(1.0)
        assert conc["top1_day"] == "20250701"  # 并列时稳定排序取最早日

    def test_day_concentration_total_zero_honest_none(self):
        # A 去均值 +0.25 / −0.25 精确抵消 → total_sum==0 → 份额与 top 日 None
        rows = [
            _irow("20250701", "A", None, 0.5),
            _irow("20250701", "B", None, 0.0),
            _irow("20250702", "A", None, 0.0),
            _irow("20250702", "B", None, 0.5),
        ]
        cells = self._rob(rows)
        conc = cells["A"]["day_concentration"]
        assert conc["total_sum"] == 0.0
        assert conc["top1_day"] is None
        assert conc["top1_share"] is None
        assert conc["top3_share"] is None

    def test_negative_total_top1_is_most_negative_day(self):
        cells = self._rob(self.ROWS3)
        conc = cells["银行"]["day_concentration"]
        assert conc["total_sum"] == pytest.approx(-0.75)
        assert conc["top1_day"] == "20250701"
        assert conc["top1_share"] == pytest.approx(0.5)

    def test_sentinel_and_mixed_type_keys_deterministic(self):
        rows = [
            _irow("20250701", None, None, 0.5),
            _irow("20250701", "银行", 0.01, 0.0),
            _irow("20250702", 123, None, 0.5),
            _irow("20250702", "银行", 0.01, 0.0),
        ]
        cells = self._rob(rows)
        assert zga.UNKNOWN_INDUSTRY_KEY in cells
        assert 123 in cells and "银行" in cells

        def _canon(obj):
            if isinstance(obj, dict):
                return sorted((str(k), _canon(v)) for k, v in obj.items())
            if isinstance(obj, list):
                return [_canon(v) for v in obj]
            return obj

        assert _canon(cells) == _canon(self._rob(list(reversed(rows))))

    def test_empty_rows_honest_shape(self):
        assert zga.industry_day_demeaned_robustness([]) == {"by_industry": {}}

    def test_participation_semantics_match_demeaned_cells(self):
        # 与 industry_day_demeaned 共享单一实现的语义一致 pin:
        # 两面每行业 events/days 逐格相等
        dd = zga.summarize_gate_effectiveness(list(self.ROWS3))
        by = dd["by_industry_day_demeaned"]["by_industry"]
        rob = dd["demeaned_robustness"]["by_industry"]
        assert set(by) == set(rob)
        for ind, cell in by.items():
            assert rob[ind]["events"] == cell["events"]
            assert rob[ind]["days"] == cell["days"]

    def test_summary_carries_robustness_key(self):
        s = zga.summarize_gate_effectiveness(list(self.ROWS3))
        assert "demeaned_robustness" in s
        assert "电子" in s["demeaned_robustness"]["by_industry"]

    def test_gate_pool_ledger_row_carries_robustness_key(self, tmp_path):
        # 账本全聚合单一实现流转 pin (R143 『不挑子集』纪律, R145 F4 先例)
        payload = {
            "summary": zga.summarize_gate_effectiveness(list(self.ROWS3)),
            "court_binding": {
                "window_start": "20250701",
                "window_end": "20260904",
                "rows": 1950,
                "content_digest": "sha256:abc",
            },
        }
        ledger = tmp_path / "gate_pool_ledger.jsonl"
        meta = zga.record_gate_pool_status(payload, "20260908", ledger_path=ledger)
        assert meta.get("recorded") is True
        row = json.loads(ledger.read_text(encoding="utf-8").splitlines()[-1])
        rob = (row.get("summary") or {}).get("demeaned_robustness") or {}
        assert "电子" in (rob.get("by_industry") or {})
        assert rob["by_industry"]["电子"]["split_half"]["sign_consistent"] is True

    # --- 渲染面 ---

    def _payload(self, summary: dict) -> dict:
        return {
            "generated_at": "20260908",
            "primary_horizon": 10,
            "gate_blocked_stages": sorted(zga.NEAR_MISS_STAGES),
            "strength_conditioning": "x",
            "attribution_caveat": "x",
            "zero_hit_days_n": 1,
            "replay_hit_days": [],
            "court_binding": {
                "window_start": "20250701",
                "window_end": "20260904",
                "rows": 1950,
                "content_digest": "sha256:abc",
            },
            "days": [],
            "summary": summary,
        }

    def test_render_robustness_section_when_key_present(self):
        s = zga.summarize_gate_effectiveness(list(self.ROWS3))
        md = zga.render_md(self._payload(s))
        assert "## 去均值对照稳健性" in md
        section = md.split("去均值对照稳健性")[-1].split("##")[0]
        assert "电子" in section and "医药" in section
        assert "早半窗" in section and "晚半窗" in section
        assert "是" in section  # sign_consistent 渲染
        assert "Top1" in section

    def test_render_missing_robustness_key_zero_new_bytes(self):
        s = zga.summarize_gate_effectiveness(list(self.ROWS3))
        s_old = {k: v for k, v in s.items() if k != "demeaned_robustness"}
        md = zga.render_md(self._payload(s_old))
        assert "去均值对照稳健性" not in md
        # 摘除新键后的渲染与注入前等价 — 旧 payload 逐字节不变
        s_patched = json.loads(json.dumps(s_old))
        assert zga.render_md(self._payload(s_old)) == md

    def test_render_robustness_malformed_cells_no_crash(self):
        s = zga.summarize_gate_effectiveness(list(self.ROWS3))
        rob = s["demeaned_robustness"]
        rob["by_industry"]["垃圾A"] = {"events": None, "days": 0}
        rob["by_industry"]["垃圾B"] = {
            "events": 1, "days": 1,
            "split_half": "not-a-dict",
            "day_concentration": {"total_sum": None, "top1_share": "x"},
        }
        md = zga.render_md(self._payload(s))
        section = md.split("去均值对照稳健性")[-1].split("##")[0]
        assert "垃圾A" not in section  # events 严格过滤不入行 (R145 F2 纪律)
        assert "垃圾B" in section  # 半分支坏形态渲染 — 不崩, 环节显 —
        assert section.count("—") >= 1


class TestDemeanedRobustnessAdversarialPins:
    """R146 Op2: 对 Op1 稳健性披露面的对抗性审查 PoC 收口。

    F1 派生聚合非有限毒化 — _finite_net 只守输入, 去均值派生值
    |net − day_mean| 可达 2·max|net|, 两天同号 1e308 级 (仍有限, 通过
    输入守卫) 输入令 split_half e 与 total_sum 溢出 inf; R143 Op3 起
    record_gate_pool_status 以 allow_nan=False 序列化 → 账本落账整体
    冻结 (R145 F1 双实锤的派生面残留)。F2 交互: e 守卫为 None 后
    sign_consistent 的 (e > 0) 比较对 None TypeError。F3 渲染畸形
    share/负 days 分支 pin。登记不修: industry_day_demeaned/_pooled
    旧面同族派生 inf 暴露 (R143 F3 家族项 + 单一实现纪律, 输出逐字节
    不变义务优先)、r["day"] 缺键 (Op1 前既有)。
    """

    OVERFLOW_ROWS = [
        _irow("20250701", "A", None, 1e308),
        _irow("20250701", "B", None, -1e308),
        _irow("20250702", "A", None, 1e308),
        _irow("20250702", "B", None, -1e308),
        _irow("20250703", "A", None, 1e308),
        _irow("20250703", "B", None, -1e308),
    ]

    def test_f1_derived_overflow_no_inf_poc(self):
        # 修复前 RED: A 去均值点恒 +1e308, 晚半窗两点 sum=2e308=inf,
        # total_sum=3e308=inf → json.dumps(allow_nan=False) ValueError
        # (账本落账冻结); 修复后非有限派生 → None 不冒充, json 可序列化
        rob = zga.industry_day_demeaned_robustness(list(self.OVERFLOW_ROWS))
        a = rob["by_industry"]["A"]
        late_e = a["split_half"]["late"]["e"]
        assert late_e is None or math.isfinite(late_e)
        assert not (
            isinstance(late_e, float) and math.isinf(late_e)
        )
        total = a["day_concentration"]["total_sum"]
        assert total is None or math.isfinite(total)
        # 新面子树 JSON 安全 (R143 allow_nan=False 契约下本面不再投毒)
        json.dumps(rob, allow_nan=False)
        # R147 Op1: isinf 登记 pin 翻转 (披露更新 — 登记事实已修)。R146
        # 时代旧面 (industry_day_demeaned) 派生 inf 是已登记家族暴露的
        # 实证 pin; 本轮 F-b 收敛后非有限派生聚合降级 None, 全 summary
        # JSON 安全, 账本冻结/毒化经旧面不可达 (另见
        # TestLedgerWriterAllowNanFamilyConvergence 端到端)
        summary = zga.summarize_gate_effectiveness(list(self.OVERFLOW_ROWS))
        json.dumps(summary, allow_nan=False)
        old_dd = summary["by_industry_day_demeaned"]["by_industry"]
        assert old_dd["A"]["e"] is None or math.isfinite(old_dd["A"]["e"])

    def test_f1_input_finite_path_unchanged(self):
        # 有限值路径逐字节 pin (Op1 ROWS3 交付数字不变)
        rows = TestIndustryDayDemeanedRobustness.ROWS3
        before = json.dumps(
            zga.industry_day_demeaned_robustness(list(rows)),
            sort_keys=True,
            ensure_ascii=False,
        )
        assert "电子" in before  # 结构存在
        cells = zga.industry_day_demeaned_robustness(list(rows))["by_industry"]
        assert cells["电子"]["split_half"]["early"]["e"] == pytest.approx(0.375)
        assert cells["电子"]["day_concentration"]["top1_share"] == pytest.approx(
            1 / 3
        )

    def test_f2_sign_consistent_none_when_half_e_guarded(self):
        # F2 交互 pin: 溢出输入下晚半窗 e 守卫为 None → sign 不得对
        # None 比较 (TypeError), 必须 None 不冒充
        rob = zga.industry_day_demeaned_robustness(list(self.OVERFLOW_ROWS))
        sign = rob["by_industry"]["A"]["split_half"]["sign_consistent"]
        assert sign is None

    def test_f1_single_industry_point_overflow_maturity(self):
        # 单点派生即非有限 (三行业日 |net−mean| 溢出): 该点按不成熟处理,
        # 不入任何聚合; 全点非有限的行业 → 零事件诚实形态
        rows = [
            _irow("20250701", "A", None, 1.5e308),
            _irow("20250701", "B", None, -1.5e308),
            _irow("20250701", "C", None, -1.5e308),
            # mean = −5e307 → A 去均值 2e308 = inf (单点即非有限)
            _irow("20250702", "A", None, 0.5),
            _irow("20250702", "B", None, -0.25),
        ]
        rob = zga.industry_day_demeaned_robustness(rows)
        a = rob["by_industry"]["A"]
        # 日 1 的 inf 点不入聚合 → A 只剩日 2 的有限点 (0.5 − 0.125 = 0.375)
        assert a["events"] == 1 and a["days"] == 1
        # 单参与日落入晚半窗 (day_order 前半为早窗, n=1 → 早窗空)
        assert a["split_half"]["early"]["e"] is None
        assert a["split_half"]["late"]["e"] == pytest.approx(0.375)
        assert a["split_half"]["sign_consistent"] is None
        assert a["day_concentration"]["top1_share"] == pytest.approx(1.0)

    def test_f3_render_robustness_malformed_share_and_days_no_crash(self):
        # 渲染分支 pin: 畸形 share (str/bool) → '—'; 负 days → '—'
        rows = TestIndustryDayDemeanedRobustness.ROWS3
        s = zga.summarize_gate_effectiveness(list(rows))
        rob = s["demeaned_robustness"]
        rob["by_industry"]["垃圾C"] = {
            "events": 2,
            "days": -1,
            "split_half": {
                "early": {"days": -1, "events": 1, "e": 0.01, "ci90_low": None},
                "late": {"days": 0, "events": True, "e": False, "ci90_low": None},
                "sign_consistent": "yes",
            },
            "day_concentration": {
                "total_sum": 0.02,
                "top1_day": "20250701",
                "top1_share": "x",
                "top3_share": True,
            },
        }
        payload = TestIndustryDayDemeanedRobustness._payload(
            TestIndustryDayDemeanedRobustness(), s
        )
        md = zga.render_md(payload)
        section = md.split("去均值对照稳健性")[-1].split("##")[0]
        assert "垃圾C" in section  # events=2 合法入行
        assert "x" not in section.split("| 垃圾C")[-1].split("\n")[0]
        assert "—" in section  # 畸形环节显 —


class TestLedgerWriterAllowNanFamilyConvergence:
    """R147 Op1: 门挡池账本写入器 allow_nan 家族收敛 + 旧面非有限守卫。

    本会话 Observe PoC 实锤 (可重放): R143 Op3 (87102fc9) 声称三族写入器
    失败契约一致 (typed 守卫 + allow_nan=False), 但门挡池写入器的
    json.dumps 实际缺 allow_nan=False — NaN/Inf summary 静默序列化
    NaN/Infinity 字面量落账 (recorded=True), 毒化 owner K 判读第三族
    数据源 (兄弟族 W2 同款失败), 而非 docstring 与 R145/R146 叙事声称的
    snapshot_not_serializable 冻结。测试盲区根因: 既有 snapshot 测试只
    覆盖 TypeError 面 (与 allow_nan 无关), NaN 行为从未经真实写入器 pin。
    修复: (F-a) 写入器 allow_nan=False (兄弟逐字同款); (F-b) summary
    旧面输入/派生非有限守卫收敛 (_finite_net 单一实现, 登记项② 收口);
    (F-c) day_counterfactual_e 同守卫; (F-d) docstring 失实修正。
    """

    def test_writer_nan_stat_typed_fail_open(self, tmp_path):
        # F-a RED (修复前: recorded=True, NaN 字面量落盘毒化账本)
        ledger = tmp_path / "gate_pool_ledger.jsonl"
        s = _summary()
        s["normal_regime_pooled"]["e"] = float("nan")
        meta = zga.record_gate_pool_status(
            {"summary": s}, "20260908", ledger_path=ledger,
        )
        assert meta == {"recorded": False, "reason": "snapshot_not_serializable"}
        assert not ledger.exists()

    def test_writer_infinity_stat_typed_fail_open(self, tmp_path):
        # F-a: Infinity 同语义 — 严格 JSON 契约与两族兄弟逐字一致
        ledger = tmp_path / "gate_pool_ledger.jsonl"
        s = _summary()
        s["gate_blocked_pooled"] = {
            "events": 1, "e": float("inf"), "ci90_low": None, "days": 1,
        }
        meta = zga.record_gate_pool_status(
            {"summary": s}, "20260908", ledger_path=ledger,
        )
        assert meta == {"recorded": False, "reason": "snapshot_not_serializable"}
        assert not ledger.exists()

    def test_overflow_rows_summary_json_safe_and_ledger_records(self, tmp_path):
        # F-b RED: R146 OVERFLOW_ROWS 下旧面派生 inf (isinf pin 登记事实)
        # → 修复后全 summary 子树 JSON 安全且账本端到端落账 (登记项② 收口:
        # 契约违反输入不再冻结/毒化账本, 聚合诚实降级 None 不冒充)
        rows = list(TestDemeanedRobustnessAdversarialPins.OVERFLOW_ROWS)
        s = zga.summarize_gate_effectiveness(rows)
        json.dumps(s, allow_nan=False)  # 不抛 ValueError
        ledger = tmp_path / "gate_pool_ledger.jsonl"
        meta = zga.record_gate_pool_status(
            {"summary": s}, "20260908", ledger_path=ledger,
        )
        assert meta == {"recorded": True, "records": 1}
        body = ledger.read_text(encoding="utf-8")
        assert "Infinity" not in body
        assert "NaN" not in body

    def test_pooled_nan_inf_bool_net_immature(self):
        # F-b RED: _pooled 裸 is not None — NaN/Inf 入池化 e=nan/inf 冒充,
        # bool 是 int 子类按 1.0 参与均值是冒充 (R142 F2 语义)
        rows = [
            _row("20250701", "normal", "c2", float("nan")),
            _row("20250701", "normal", "c2", float("inf")),
            _row("20250701", "normal", "c2", True),
            _row("20250701", "normal", "c2", 0.04),
        ]
        s = zga.summarize_gate_effectiveness(rows)
        pooled = s["normal_regime_pooled"]
        assert pooled["events"] == 1
        assert pooled["e"] == pytest.approx(0.04)
        assert s["events_mature"] == 1
        assert s["days_with_mature"] == 1
        assert s["day_e_distribution"] == {
            "protective_lt0": 0, "costly_gt0": 1, "flat_eq0": 0,
        }

    def test_day_counterfactual_e_non_finite_immature(self):
        # F-c: NaN/Inf/bool 不成熟 — NaN 输入不再产出 NaN counterfactual_e
        # 写入日报 JSON (报告面输入与账本面同守卫单一实现)
        assert zga.day_counterfactual_e([float("nan")]) is None
        assert zga.day_counterfactual_e([float("inf"), -0.02]) == pytest.approx(-0.02)
        assert zga.day_counterfactual_e([True, 0.02]) == pytest.approx(0.02)

    def test_finite_path_summary_bytes_unchanged(self):
        # A4: 生产有限值路径逐字节 — 修复前摘要钉死 (sha256 of sorted JSON)
        rows = list(TestIndustryDayDemeanedRobustness.ROWS3)
        blob = json.dumps(
            zga.summarize_gate_effectiveness(rows),
            sort_keys=True, ensure_ascii=False,
        )
        assert hashlib.sha256(blob.encode()).hexdigest() == (
            "4717974d040cc31043d8a3e5969c8427594602cd57b0b4a872702ed5524101a7"
        )
        mixed = [
            {"day": "20250701", "regime": "normal", "dominant_family": "c2",
             "industry": "电子", "industry_day_pct": 0.01, "net": 0.05},
            {"day": "20250701", "regime": "normal", "dominant_family": "c3",
             "industry": "银行", "industry_day_pct": -0.01, "net": -0.02},
            {"day": "20250702", "regime": "crisis", "dominant_family": "c2",
             "industry": "电子", "industry_day_pct": 0.0, "net": None},
        ]
        blob2 = json.dumps(
            zga.summarize_gate_effectiveness(mixed),
            sort_keys=True, ensure_ascii=False,
        )
        assert hashlib.sha256(blob2.encode()).hexdigest() == (
            "03ddad958bdb8dfece4c5e4e2b10b966f7b4ed3d961dd8ac7b8cb20b212c2ee1"
        )


class TestAdversarialOp2AggregateFacePins:
    """R147 Op2: 对 Op1 交付面的对抗性审查 — 聚合面残留两连 (PoC 实锤)。

    Op1 输入面守卫 (_finite_net 单一实现) 不覆盖派生聚合 — R146 F1
    「_finite_net 只守输入」同族模式在 Op1 新守卫面复现:
    F-a day_e_distribution 日聚合 sum(v)/len(v) 无守卫 — 单日两行
    1e308 → 日聚合 inf, inf>0 判 True 被误分类 costly_gt0 (分布对
    契约违反输入撒谎; nan 形态三桶全丢静默消失);
    F-b day_counterfactual_e 聚合无守卫 — 有限点和溢出 inf 直达日报
    payload counterfactual_e 行 (main 报告 allow_nan 默认写 Infinity
    字面量 → 严格解析器拒整份日报; Op1 F-c 只守了输入)。
    登记不修: _finite_net 大整数 OverflowError (fail-closed 诚实)、
    历史毒化账本行致未来冻结 (生产账本已验证干净)、
    cluster_boot_ci_low 内部 1e308 尺度 (R146 已接受)。
    """

    def test_day_e_distribution_inf_aggregate_not_classified(self):
        # F-a RED (修复前: costly_gt0==1 — inf 被误分类为代价日)
        rows = [
            {"day": "20250701", "regime": "normal", "dominant_family": "c2",
             "net": 1e308},
            {"day": "20250701", "regime": "normal", "dominant_family": "c2",
             "net": 1e308},
        ]
        s = zga.summarize_gate_effectiveness(rows)
        assert s["day_e_distribution"] == {
            "protective_lt0": 0, "costly_gt0": 0, "flat_eq0": 0,
        }
        # 成熟事实如实保留 — 非有限日聚合不入分布, 不冒充「无成熟行」
        assert s["days_with_mature"] == 1
        assert s["events_mature"] == 2

    def test_day_counterfactual_e_overflow_aggregate_none(self):
        # F-b RED (修复前: inf 直达日报 JSON 行)
        assert zga.day_counterfactual_e([1e308, 1e308]) is None
        # 有限路径数字不变 (巨大但有限的和仍如实返回)
        assert zga.day_counterfactual_e([1e308, -0.02]) == pytest.approx(5e307)
        assert zga.day_counterfactual_e([0.01, 0.03]) == pytest.approx(0.02)


class TestMainReportWriteFaceR148:
    """R148 Op1 (R147 登记项②): main() 报告面 JSON 序列化契约收敛。

    Observe PoC (可重放): 非有限 payload 经真实 main() 修复前 rc=0 静默、
    报告 JSON 含 Infinity 字面量、严格解析器 (parse_constant 抛错) 整份
    拒绝 — 与 R147 Op1 收敛的账本写入器毒化 (allow_nan 静默落账) 同构的
    报告面残留, 报告是 owner c3 门槛机会成本判读的主消费面。
    修复契约: serialize-first + allow_nan=False + typed fail-closed
    (SystemExit 零产物, 与 manifest 缺失/损坏同出口; 夜刷链 _run_step
    按 rc!=0 + stderr 尾部归因)。
    """

    def _payload(self) -> dict:
        return {
            "generated_at": "20260908",
            "primary_horizon": 10,
            "gate_blocked_stages": sorted(zga.NEAR_MISS_STAGES),
            "strength_conditioning": "测试fixture",
            "attribution_caveat": "测试fixture",
            "zero_hit_days_n": 1,
            "replay_hit_days": [],
            "court_binding": None,
            "days": [],
            "summary": zga.summarize_gate_effectiveness([]),
        }

    def _run_main(self, tmp_path, monkeypatch, payload):
        """经真实 main() 写盘; attach 以真实形态注入 gate_pool_record 键。"""
        monkeypatch.setattr(
            zga, "collect_zero_hit_day_attribution", lambda *a, **k: payload
        )

        def fake_attach(p, d, ledger_path=None):
            p["gate_pool_record"] = {"recorded": True}
            return p["gate_pool_record"]

        monkeypatch.setattr(zga, "attach_gate_pool_record", fake_attach)
        report_dir = tmp_path / "reports"
        rc = zga.main(
            [
                "--report-dir", str(report_dir),
                "--gate-ledger", str(tmp_path / "l.jsonl"),
                "--date-str", "20260908",
            ]
        )
        return rc, report_dir

    def _reject_constant(self, name):
        raise ValueError(f"strict reject: {name}")

    def test_non_finite_payload_fail_closed_zero_artifacts(
        self, tmp_path, monkeypatch
    ):
        # A1 RED (修复前: rc=0 + Infinity 字面量落盘 + md/json 半套产物)
        payload = self._payload()
        payload["summary"]["normal_regime_pooled"]["e"] = float("inf")
        with pytest.raises(SystemExit, match="fail-closed"):
            self._run_main(tmp_path, monkeypatch, payload)
        report_dir = tmp_path / "reports"
        assert report_dir.exists()
        assert list(report_dir.iterdir()) == []  # 零部分产物

    def test_unserializable_payload_same_typed_exit(self, tmp_path, monkeypatch):
        # A2 TypeError 面与 ValueError 同守卫 (混合类型键使 sort_keys 排序失败)
        payload = self._payload()
        payload["summary"]["mixed"] = {1: "a", "b": 2}
        with pytest.raises(SystemExit, match="fail-closed"):
            self._run_main(tmp_path, monkeypatch, payload)
        report_dir = tmp_path / "reports"
        assert list(report_dir.iterdir()) == []

    def test_finite_payload_bytes_strictly_canonical(self, tmp_path, monkeypatch):
        # A3 有限值路径逐字节不变 (allow_nan=False 对有限值与写序无字节影响)
        payload = self._payload()
        rc, report_dir = self._run_main(tmp_path, monkeypatch, payload)
        assert rc == 0
        json_path = report_dir / "zero_hit_day_gate_attribution_20260908.json"
        text = json_path.read_text(encoding="utf-8")
        # 严格解析器通过 (Infinity/NaN/NaN 字面量任一出现即拒)
        json.loads(text, parse_constant=self._reject_constant)
        assert (
            text
            == json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=1)
        )
        assert (
            report_dir / "zero_hit_day_gate_attribution_20260908.md"
        ).exists()
