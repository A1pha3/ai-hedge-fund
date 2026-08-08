"""Plan 06 Task 5 (RED): shadow 一致性与差异分类.

锁定约束:
1. 对比维度覆盖 inputs/candidates/admission/rank/size/cash/reserve/risk/exit/
   outcomes; 每个差异归入 EXPECTED_POLICY_CHANGE | DATA_MISMATCH |
   KERNEL_BUG | LEGACY_BUG | UNKNOWN 恰好一类.
2. 已知策略变化 (T+1/T+10、cost、OB、regime/streak、整数手) 经
   ExpectedDifferencePolicy 注册后归 EXPECTED_POLICY_CHANGE.
3. 同输入同输出重跑 → audit 确定性 (同输入同 verdict).
4. 门禁: 存在未解决 DATA_MISMATCH | KERNEL_BUG | UNKNOWN 且影响
   capital/exit/sample attribution 时, flip/canary 阻断.
5. audit 不修改生产状态 (只读).
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from src.screening.offensive.v3.migration.shadow_audit import (
    BLOCKING_CATEGORIES,
    Category,
    Difference,
    ExpectedDifferencePolicy,
    GateError,
    ShadowAuditReport,
    audit_shadow_parity,
    assert_no_blocking_differences,
)

UTC = timezone.utc
NOW = datetime(2026, 8, 7, 9, 0, tzinfo=UTC)


def _v2_record(**overrides: object) -> dict[str, object]:
    record: dict[str, object] = {
        "ticker": "000001",
        "admission": "admitted",
        "rank": 1,
        "size": "0.10",
        "cash": "100000.0",
        "reserve": "0.10",
        "risk": "normal",
        "exit": "T+10",
        "outcome": "pending",
    }
    record.update(overrides)
    return record


def _v3_record(**overrides: object) -> dict[str, object]:
    return _v2_record(**overrides)


# ---------------------------------------------------------------------------
# 分类
# ---------------------------------------------------------------------------


def test_identical_runs_have_no_differences() -> None:
    report = audit_shadow_parity(
        v2_records=[_v2_record()],
        v3_records=[_v3_record()],
        policy=ExpectedDifferencePolicy(expected=()),
    )
    assert report.differences == ()
    assert report.blocking() == ()


def test_registered_policy_change_is_expected() -> None:
    policy = ExpectedDifferencePolicy(expected=(("exit", "T+10", "T+1"),))
    report = audit_shadow_parity(
        v2_records=[_v2_record(exit="T+10")],
        v3_records=[_v3_record(exit="T+1")],
        policy=policy,
    )
    assert len(report.differences) == 1
    assert report.differences[0].category is Category.EXPECTED_POLICY_CHANGE
    assert report.blocking() == ()


def test_unregistered_numeric_drift_is_kernel_bug() -> None:
    report = audit_shadow_parity(
        v2_records=[_v2_record(size="0.10")],
        v3_records=[_v3_record(size="0.12")],
        policy=ExpectedDifferencePolicy(expected=()),
    )
    assert report.differences[0].category is Category.KERNEL_BUG
    assert report.blocking()


def test_v2_only_record_is_data_mismatch() -> None:
    report = audit_shadow_parity(
        v2_records=[_v2_record(), _v2_record(ticker="000002")],
        v3_records=[_v3_record()],
        policy=ExpectedDifferencePolicy(expected=()),
    )
    kinds = {difference.category for difference in report.differences}
    assert Category.DATA_MISMATCH in kinds


def test_unclassifiable_difference_is_unknown() -> None:
    report = audit_shadow_parity(
        v2_records=[_v2_record(admission="admitted")],
        v3_records=[_v3_record(admission="shadow-only")],
        policy=ExpectedDifferencePolicy(expected=()),
    )
    assert report.differences[0].category is Category.UNKNOWN
    assert report.blocking()


def test_blocking_categories_exactly_cover_gate() -> None:
    assert BLOCKING_CATEGORIES == frozenset(
        {Category.DATA_MISMATCH, Category.KERNEL_BUG, Category.UNKNOWN}
    )


# ---------------------------------------------------------------------------
# 确定性 / 门禁 / 只读
# ---------------------------------------------------------------------------


def test_audit_is_deterministic_for_same_inputs() -> None:
    kwargs = dict(
        v2_records=[_v2_record(size="0.10"), _v2_record(ticker="000002")],
        v3_records=[_v3_record(size="0.12")],
        policy=ExpectedDifferencePolicy(expected=()),
    )
    first = audit_shadow_parity(**kwargs)
    second = audit_shadow_parity(**kwargs)
    assert first.canonical_hash == second.canonical_hash
    assert first.differences == second.differences


def test_gate_blocks_unresolved_blocking_differences() -> None:
    report = audit_shadow_parity(
        v2_records=[_v2_record(size="0.10")],
        v3_records=[_v3_record(size="0.12")],
        policy=ExpectedDifferencePolicy(expected=()),
    )
    with pytest.raises(GateError):
        assert_no_blocking_differences(report)


def test_gate_passes_when_only_expected_differences() -> None:
    policy = ExpectedDifferencePolicy(expected=(("exit", "T+10", "T+1"),))
    report = audit_shadow_parity(
        v2_records=[_v2_record(exit="T+10")],
        v3_records=[_v3_record(exit="T+1")],
        policy=policy,
    )
    assert_no_blocking_differences(report)


def test_audit_does_not_mutate_inputs() -> None:
    v2 = [_v2_record()]
    v3 = [_v3_record(exit="T+1")]
    audit_shadow_parity(
        v2_records=v2,
        v3_records=v3,
        policy=ExpectedDifferencePolicy(expected=(("exit", "T+10", "T+1"),)),
    )
    assert v2 == [_v2_record()]
    assert v3 == [_v3_record(exit="T+1")]
