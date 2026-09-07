"""R140 Op1: 零 hit 日门槛有效性归因 — 纯函数与聚合面 fixture 驱动测试。

fixture 全部非对称 (R13 教训: 对称 fixture 的数值断言无牙); 零本地数据
依赖 (R10 纪律: slot 验证必须自足)。
"""

from __future__ import annotations

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
