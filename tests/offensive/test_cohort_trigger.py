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
