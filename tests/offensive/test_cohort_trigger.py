"""src.screening.offensive.cohort_trigger — 日层 cohort 触发器账本读取面
(R126 Op1)。

钉死的正确性面:
- 装载单一实现复用 (threshold_trigger.load_trigger_ledger): 损坏行 advisory
  跳过 / 日期升序 / 独立默认路径 (两族账本文件互不混写);
- 连亮计数语义镜像强度族: 最新锚定 streak (未点亮/未判定/缺键断链 — 保守:
  未知不延长连亮) + max_conjunction_streak 全历史独立正向扫描 (R85 Op2 语义:
  该值绝不恒等于当前连亮);
- 读取侧只披露不重推导: 账本里是什么就报什么 (lit/armed 由落账侧冻结)。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.screening.offensive import cohort_trigger as ct
from src.screening.offensive.threshold_trigger import (
    load_trigger_ledger as strength_load,
)


def _record(
    date: str,
    *,
    c1_lit: bool | None = True,
    c2_lit: bool | None = False,
    armed: bool | None = False,
) -> dict:
    """账本记录夹具 (None = 整键缺失 — 旧形态/手工构造的保守断链形态)。"""
    rec: dict = {"date": date}
    if c1_lit is not None:
        rec["strong_bucket"] = {"lit": c1_lit, "judged": True, "n": 864, "stat": 0.01}
    if c2_lit is not None:
        rec["mid_buckets"] = {"lit": c2_lit, "judged": True, "n": 293, "stat": -0.02}
    if armed is not None:
        rec["conjunction_armed"] = armed
    return rec


class TestLedgerLoading:
    def test_default_path_is_cohort_family_file(self):
        assert ct.COHORT_TRIGGER_LEDGER_PATH == Path(
            "data/reports/signal_day_cohort_trigger_ledger.jsonl"
        )

    def test_missing_file_returns_empty(self, tmp_path):
        assert ct.load_cohort_trigger_ledger(tmp_path / "nope.jsonl") == []

    def test_corrupt_lines_skipped_dates_sorted(self, tmp_path):
        ledger = tmp_path / "ledger.jsonl"
        rows = [_record("20260902"), _record("20260901"), _record("20260903")]
        ledger.write_text(
            "garbage-not-json\n"
            + "\n".join(json.dumps(r, ensure_ascii=False) for r in rows)
            + "\n{broken\n",
            encoding="utf-8",
        )
        records = ct.load_cohort_trigger_ledger(ledger)
        assert [r["date"] for r in records] == ["20260901", "20260902", "20260903"]

    def test_loads_via_shared_strength_loader_implementation(self, tmp_path):
        """装载面与强度族同一实现 (传入显式路径时逐字节同结果)。"""
        ledger = tmp_path / "ledger.jsonl"
        ledger.write_text(json.dumps(_record("20260901")), encoding="utf-8")
        assert (
            ct.load_cohort_trigger_ledger(ledger) == strength_load(ledger)
        )


class TestStability:
    def test_empty_records_zeroed(self):
        st = ct.cohort_trigger_stability([])
        assert st["records"] == 0
        assert st["strong_bucket_streak"] == 0
        assert st["conjunction_streak"] == 0
        assert st["max_conjunction_streak"] == 0
        assert st["first_date"] is None and st["last_date"] is None

    def test_streaks_count_from_latest_backward(self):
        records = [
            _record("20260901", c1_lit=False),
            _record("20260902"),
            _record("20260903"),
        ]
        st = ct.cohort_trigger_stability(records)
        assert st["strong_bucket_streak"] == 2  # 0901 未点亮断链
        assert st["mid_buckets_streak"] == 0  # 夹具 C2 恒 False
        assert st["conjunction_streak"] == 0
        assert st["strong_bucket_last_lit"] is True
        assert st["mid_buckets_last_lit"] is False
        assert st["conjunction_last_armed"] is False

    def test_unjudged_and_missing_keys_break_streak(self):
        lit_only = _record("20260903")
        del lit_only["mid_buckets"]  # 缺键 → 未点亮断链 (保守)
        records = [
            _record("20260901"),
            _record("20260902"),
            lit_only,  # 最新记录缺 mid_buckets 键 → 链断且 last_lit None
        ]
        st = ct.cohort_trigger_stability(records)
        assert st["mid_buckets_streak"] == 0
        assert st["mid_buckets_last_lit"] is None
        assert st["strong_bucket_last_lit"] is True  # 键在, 披露真话

    def test_conjunction_streak_needs_literal_true(self):
        records = [
            _record("20260901", armed=True),
            _record("20260902", armed=True),
            _record("20260903", armed=False),
        ]
        st = ct.cohort_trigger_stability(records)
        assert st["conjunction_streak"] == 0  # 最新未武装断链
        assert st["max_conjunction_streak"] == 2  # 全历史扫描保留历史段

    def test_max_not_collapsed_into_latest_anchored(self):
        """R85 Op2 语义镜像: [A,A,U,A] → streak=1 而 max=2 (断链不吞历史)。"""
        records = [
            _record("20260901", armed=True),
            _record("20260902", armed=True),
            _record("20260903", armed=False),
            _record("20260904", armed=True),
        ]
        st = ct.cohort_trigger_stability(records)
        assert st["conjunction_streak"] == 1
        assert st["max_conjunction_streak"] == 2

    def test_all_armed_streak_equals_max(self):
        records = [_record(f"2026090{i}", armed=True) for i in range(1, 4)]
        st = ct.cohort_trigger_stability(records)
        assert st["conjunction_streak"] == 3
        assert st["max_conjunction_streak"] == 3
        assert st["conjunction_last_armed"] is True


class TestInnerShapePoisoningR126Op2:
    """R126 Op2 对抗审查返工: 行内条件值非 dict 形态不得炸读取面。

    PoC 实锤 (修复前): strong_bucket/mid_buckets 为 str/int/list 时
    ``.get`` 裸 AttributeError — Op3 接线 --daily-action 后手编账本/损坏
    写入将炸操作员日度命令, 违反 fail-open 家族纪律 (R115 Op1 同款:
    证据面损坏按缺键 advisory 断链, 不假装有判定也不崩溃)。
    """

    @pytest.mark.parametrize("poison", ["corrupted", 42, ["lit", True], True, 0.5])
    def test_non_dict_condition_value_breaks_not_crashes(self, poison):
        records = [
            _record("20260901"),
            _record("20260902"),
            {**_record("20260903"), "strong_bucket": poison},
        ]
        st = ct.cohort_trigger_stability(records)  # 修复前 AttributeError
        assert st["strong_bucket_streak"] == 0  # 毒化行断链
        assert st["strong_bucket_last_lit"] is None  # 不假装有判定
        assert st["mid_buckets_last_lit"] is False  # 好键披露真话
        assert st["records"] == 3
        assert st["max_conjunction_streak"] == 0

    def test_poisoned_mid_bucket_only_affects_own_chain(self):
        records = [
            {**_record("20260901"), "mid_buckets": {"poisoned": True}},
            _record("20260902"),
        ]
        st = ct.cohort_trigger_stability(records)
        assert st["mid_buckets_streak"] == 0
        assert st["strong_bucket_streak"] == 2  # 他链计数不受污染

    def test_armed_strict_bool_semantics_unchanged(self):
        records = [
            _record("20260901", armed=1),  # truthy 但非字面 True
            _record("20260902", armed=True),
        ]
        st = ct.cohort_trigger_stability(records)
        assert st["conjunction_streak"] == 1  # is True 严格语义原样
        assert st["max_conjunction_streak"] == 1


# ---------- R129 Op1: 日层族 K 预注册机制 (强度族 R112-R115 机器的镜像复用) ----------
#
# owner 注册文件形状 {"anchor", "registered_date", "k", "owner_ref"?}; 装载把 k
# 翻译进 threshold_trigger 规范形状的 k_070 槽位 — 下游 hash/观测/反回溯/资格
# 窗口全部单一实现复用, 本模块零复制第二套机器 (R128 开放项③纪律)。

_K_REG = {
    "anchor": "production_aligned/t10/cohort_size",
    "registered_date": "20260906",
    "k": 3,
}


def _write_k_file(tmp_path, payload):
    path = tmp_path / "cohort_trigger_k.json"
    if payload is None:
        path.write_text("{corrupted", encoding="utf-8")
    else:
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


_COHORT_ANCHOR = "production_aligned/t10/cohort_size"


def _k_rows(*specs):
    """(date, armed) → 带 anchor 的账本行 (真实账本行恒有 anchor)。"""
    return [
        {**_record(date, armed=armed), "anchor": _COHORT_ANCHOR}
        for date, armed in specs
    ]


class TestCohortKRegistrationLoading:
    def test_default_paths_are_cohort_family_files(self):
        assert ct.COHORT_K_REGISTRATION_PATH == Path(
            "data/reports/cohort_trigger_k.json"
        )
        assert ct.COHORT_K_OBSERVATION_LOG_PATH == Path(
            "data/reports/cohort_trigger_k_observations.jsonl"
        )

    def test_missing_file_unregistered(self, tmp_path):
        assert ct.load_cohort_k_registration(tmp_path / "nope.json") == (
            "unregistered",
            None,
        )

    def test_registered_translates_k_into_strength_shape(self, tmp_path):
        state, reg = ct.load_cohort_k_registration(_write_k_file(tmp_path, _K_REG))
        assert state == "registered"
        assert reg == {
            "anchor": "production_aligned/t10/cohort_size",
            "registered_date": "20260906",
            "k_070": 3,
        }

    def test_registered_with_owner_ref_kept(self, tmp_path):
        payload = {**_K_REG, "owner_ref": "decision-memo-1"}
        state, reg = ct.load_cohort_k_registration(_write_k_file(tmp_path, payload))
        assert state == "registered"
        assert reg["owner_ref"] == "decision-memo-1"

    def test_registered_k_must_be_plain_positive_int(self, tmp_path):
        for bad_k in (True, 0, -1, "3", 3.0, None):
            payload = {**_K_REG, "k": bad_k}
            state, reg = ct.load_cohort_k_registration(
                _write_k_file(tmp_path, payload)
            )
            assert state == "malformed", f"k={bad_k!r} 必须判损坏"

    def test_malformed_variants(self, tmp_path):
        for payload in (
            None,  # JSON 损坏
            ["not", "a", "dict"],
            {**_K_REG, "anchor": ""},
            {**_K_REG, "anchor": 42},
            {**_K_REG, "registered_date": "2026-9-6"},
            {**_K_REG, "registered_date": "202609061"},
            {**_K_REG, "registered_date": 20260906},
            {**_K_REG, "owner_ref": 7},
            {"anchor": "a", "registered_date": "20260906"},  # 缺 k
        ):
            state, reg = ct.load_cohort_k_registration(
                _write_k_file(tmp_path, payload)
            )
            assert state == "malformed", f"payload={payload!r} 必须判损坏"
            assert reg is None


class TestCohortKQualification:
    def _rows(self, *specs):
        return _k_rows(*specs)

    def _ledger(self, tmp_path, records):
        path = tmp_path / "day_cohort_trigger_ledger.jsonl"
        path.write_text(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n",
            encoding="utf-8",
        )
        return path

    def test_trailing_armed_streak_and_threshold(self, tmp_path):
        records = _k_rows(
            ("20260901", False), ("20260902", True),
            ("20260903", True), ("20260904", True),
        )
        state, reg = ct.load_cohort_k_registration(
            _write_k_file(tmp_path, {**_K_REG, "registered_date": "20260901"})
        )
        qual = ct.cohort_trigger_qualification(records, reg)
        assert qual["q"] == 3
        assert qual["qualified"] is True
        state2, reg2 = ct.load_cohort_k_registration(
            _write_k_file(tmp_path, {**_K_REG, "registered_date": "20260901", "k": 4})
        )
        qual2 = ct.cohort_trigger_qualification(records, reg2)
        assert qual2["q"] == 3
        assert qual2["qualified"] is False

    def test_registration_date_window_excludes_earlier_lits(self, tmp_path):
        """反前瞻: 注册日前的武装不追溯计数 (K 必须先于它资格化的亮存在)。"""
        records = _k_rows(("20260901", True), ("20260902", True), ("20260903", True))
        state, reg = ct.load_cohort_k_registration(
            _write_k_file(tmp_path, {**_K_REG, "registered_date": "20260903"})
        )
        qual = ct.cohort_trigger_qualification(records, reg)
        assert qual["q"] == 1

    def test_anchor_filter_excludes_foreign_family_rows(self, tmp_path):
        records = [
            {**_record("20260902", armed=True), "anchor": "production_aligned/t10"},
            {**_record("20260903", armed=True), "anchor": _COHORT_ANCHOR},
        ]
        state, reg = ct.load_cohort_k_registration(
            _write_k_file(tmp_path, {**_K_REG, "registered_date": "20260901"})
        )
        qual = ct.cohort_trigger_qualification(records, reg)
        assert qual["q"] == 1

    def test_malformed_date_rows_excluded(self, tmp_path):
        records = [
            {**_record("2026-9-2", armed=True), "anchor": _COHORT_ANCHOR},
            {**_record("20260903", armed=True), "anchor": _COHORT_ANCHOR},
        ]
        state, reg = ct.load_cohort_k_registration(
            _write_k_file(tmp_path, {**_K_REG, "registered_date": "20260901"})
        )
        qual = ct.cohort_trigger_qualification(records, reg)
        assert qual["q"] == 1

    def test_shape_validation_fails_closed_on_raw_dict(self):
        with pytest.raises(ValueError):
            ct.cohort_trigger_qualification([], {"anchor": "a", "registered_date": "20260906"})
        with pytest.raises(ValueError):
            ct.cohort_trigger_qualification([], {
                "anchor": "a", "registered_date": "20260906", "k_070": True
            })


class TestCohortKDisclosure:
    def test_unregistered_line_matches_current_render_tail_bytes(self):
        """未注册态文本 = daily_action 渲染行旧硬编码尾句 (逐字节, A2 钉死)。"""
        disc = ct.cohort_k_qualification_disclosure([_record("20260905")])
        assert disc["state"] == "unregistered"
        assert disc["line"] == "稳定阈值 K 属 owner 预注册；披露不是行为改变"
        assert disc["qualified"] is False

    def test_malformed_discloses_owner_fix_path(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            ct, "COHORT_K_REGISTRATION_PATH", _write_k_file(tmp_path, None)
        )
        disc = ct.cohort_k_qualification_disclosure([_record("20260905")])
        assert disc["state"] == "malformed"
        assert "损坏" in disc["line"]
        assert "cohort_trigger_k.json" in disc["line"]

    def test_registered_line_reports_window_and_threshold(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(
            ct,
            "COHORT_K_REGISTRATION_PATH",
            _write_k_file(tmp_path, {**_K_REG, "registered_date": "20260901"}),
        )
        records = _k_rows(("20260902", True), ("20260903", True), ("20260904", True))
        disc = ct.cohort_k_qualification_disclosure(records)
        assert disc["state"] == "registered"
        assert "预注册 K=3" in disc["line"]
        assert "自 20260901 起计资格连亮 3/3" in disc["line"]
        assert "资格达成" in disc["line"]
        assert disc["qualified"] is True

    def test_registered_backdated_note_from_observation_log(
        self, tmp_path, monkeypatch
    ):
        reg_path = _write_k_file(tmp_path, _K_REG)  # 声明日 20260906
        obs_path = tmp_path / "obs.jsonl"
        obs_path.write_text(
            json.dumps(
                {
                    "observed_date": "20260907",
                    "declared_registered_date": "20260906",
                    "anchor": _K_REG["anchor"],
                    "k_070": 3,
                    "k_hash": ct.k_registration_hash(
                        {
                            "anchor": _K_REG["anchor"],
                            "registered_date": "20260906",
                            "k_070": 3,
                        }
                    ),
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        monkeypatch.setattr(ct, "COHORT_K_REGISTRATION_PATH", reg_path)
        monkeypatch.setattr(ct, "COHORT_K_OBSERVATION_LOG_PATH", obs_path)
        records = _k_rows(("20260908", True))
        disc = ct.cohort_k_qualification_disclosure(records)
        assert disc["state"] == "registered"
        assert disc["backdated"] is True
        assert disc["effective_registered_date"] == "20260907"
        assert "以观测日起算" in disc["line"]

    def test_observe_via_strength_single_implementation(self, tmp_path):
        """观测机器 = threshold_trigger.observe_k_registration 单一实现 (零复制)。"""
        obs_path = tmp_path / "obs.jsonl"
        state, reg = ct.load_cohort_k_registration(_write_k_file(tmp_path, _K_REG))
        first = ct.observe_cohort_k_registration(reg, "20260906", path=obs_path)
        second = ct.observe_cohort_k_registration(reg, "20260906", path=obs_path)
        assert first == second
        lines = [
            ln for ln in obs_path.read_text(encoding="utf-8").splitlines() if ln
        ]
        assert len(lines) == 1


# ---------------------------------------------------------------------------
# R130 Op1: 相邻同数据状态重复观测折叠 (强度族 threshold_trigger 单一实现复用)
# ---------------------------------------------------------------------------

def _dg(tag: str) -> str:
    return "sha256:" + tag * 32


def _cohort_court(digest: str | None, win_end: str = "20260904") -> dict:
    return {
        "window_start": "20250701", "window_end": win_end,
        "rows": 1950, "formula_fingerprint": "aa" * 32,
        "content_digest": digest, "universe_audit_complete": True,
    }


def test_stability_folds_adjacent_duplicate_observations():
    """2026-09-05 形态: 非交易日重复判定记录不膨胀日层连亮。"""
    records = [
        _record("20260904", c1_lit=True, armed=True),
        _record("20260905", c1_lit=True, armed=True),
    ]
    records[1]["court"] = _cohort_court(_dg("e3"), win_end="20260905")
    records[0]["court"] = _cohort_court(_dg("e3"))
    st = ct.cohort_trigger_stability(records)
    assert st["strong_bucket_streak"] == 1  # 同一数据状态只计一次
    assert st["conjunction_streak"] == 1
    assert st["max_conjunction_streak"] == 1
    assert st["records"] == 2  # 原始账本事实保持
    assert st["last_date"] == "20260905"


def test_stability_fold_distinct_states_and_missing_digest():
    """不同状态不折叠; 缺 court/digest 记录永不折叠。"""
    records = [
        _record("20260902", c1_lit=True),
        _record("20260903", c1_lit=True),
        _record("20260904", c1_lit=True),
    ]
    records[0]["court"] = _cohort_court(_dg("c3"))
    records[1]["court"] = _cohort_court(_dg("c4"))
    records[2]["court"] = _cohort_court(None, win_end="20260904")
    st = ct.cohort_trigger_stability(records)
    assert st["strong_bucket_streak"] == 3


def test_stability_reports_folded_duplicates():
    """R130 Op2: 日层族折叠可审计字段 (强度族同构)。"""
    records = [
        _record("20260904", c1_lit=True, armed=True),
        _record("20260905", c1_lit=True, armed=True),
    ]
    records[0]["court"] = _cohort_court(_dg("e3"))
    records[1]["court"] = _cohort_court(_dg("e3"), win_end="20260905")
    st = ct.cohort_trigger_stability(records)
    assert st["folded_duplicates"] == 1
    assert ct.cohort_trigger_stability([_record("20260905", c1_lit=True)])[
        "folded_duplicates"
    ] == 0


def test_cohort_load_delegates_poisoned_line_skip(tmp_path):
    """R150 Op1: 日层族装载经 threshold_trigger 单一实现继承毒化行拒收
    (Infinity/NaN 字面量 = 损坏行家族, advisory 跳过, 干净行保留)。"""
    good = json.dumps(_record("20260901"), ensure_ascii=False, sort_keys=True)
    poison = (
        '{"date": "20260902", "strong_bucket": {"lit": true, "judged": true,'
        ' "n": 864, "stat": Infinity}, "conjunction_armed": true}'
    )
    ledger = tmp_path / "cohort_ledger.jsonl"
    ledger.write_text(good + "\n" + poison + "\n", encoding="utf-8")
    records = ct.load_cohort_trigger_ledger(ledger)
    assert [r["date"] for r in records] == ["20260901"]


def test_cohort_load_delegates_overflow_and_deep_nest_skip(tmp_path):
    """R150 Op2: 日层族委托装载继承数字面旁路拒收与深嵌套跳过。"""
    good = json.dumps(_record("20260901"), ensure_ascii=False, sort_keys=True)
    poison = (
        '{"date": "20260902", "strong_bucket": {"lit": true, "judged": true,'
        ' "n": 864, "stat": 1e400}, "conjunction_armed": true}'
    )
    deep = "[" * 20000 + "]" * 20000
    ledger = tmp_path / "cohort_ledger.jsonl"
    ledger.write_text(good + "\n" + poison + "\n" + deep + "\n", encoding="utf-8")
    records = ct.load_cohort_trigger_ledger(ledger)
    assert [r["date"] for r in records] == ["20260901"]
