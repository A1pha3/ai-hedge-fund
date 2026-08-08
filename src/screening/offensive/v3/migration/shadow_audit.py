"""Plan 06 Task 5: shadow 一致性与差异分类.

`audit_shadow_parity()` 对比 v2 与 v3 shadow 在同一输入上的决策记录,
逐字段归类差异:

- ``EXPECTED_POLICY_CHANGE``: 经 ExpectedDifferencePolicy 显式注册的已知
  策略变化 (T+1/T+10、cost、OB、regime/streak、整数手).
- ``DATA_MISMATCH``: 一侧缺失的记录 (输入覆盖不一致).
- ``KERNEL_BUG``: 已注册策略之外的数值/枚举漂移 (rank/size/cash/...).
- ``UNKNOWN``: 无法归入上述三类的差异 (如 admission 语义变化).

runbook 门禁: 任何未解决的 DATA_MISMATCH | KERNEL_BUG | UNKNOWN 阻断
flip/canary. 审计只读, 不修改输入, 同输入必得同结论.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Iterable, Mapping

from src.screening.offensive.v3.contracts import CanonicalModel, content_hash

COMPARE_FIELDS = (
    "admission",
    "rank",
    "size",
    "cash",
    "reserve",
    "risk",
    "exit",
    "outcome",
)


class Category(StrEnum):
    EXPECTED_POLICY_CHANGE = "EXPECTED_POLICY_CHANGE"
    DATA_MISMATCH = "DATA_MISMATCH"
    KERNEL_BUG = "KERNEL_BUG"
    LEGACY_BUG = "LEGACY_BUG"
    UNKNOWN = "UNKNOWN"


BLOCKING_CATEGORIES = frozenset(
    {Category.DATA_MISMATCH, Category.KERNEL_BUG, Category.UNKNOWN}
)


class GateError(ValueError):
    """存在阻断级差异时抛出."""


class Difference(CanonicalModel):
    ticker: str
    field: str
    v2_value: str
    v3_value: str
    category: Category


class ExpectedDifferencePolicy(CanonicalModel):
    """显式注册的已知策略变化: (field, v2_value, v3_value) 三元组."""

    expected: tuple[tuple[str, str, str], ...]

    def covers(self, field: str, v2_value: str, v3_value: str) -> bool:
        return (field, v2_value, v3_value) in set(self.expected)


class ShadowAuditReport(CanonicalModel):
    differences: tuple[Difference, ...]

    @property
    def canonical_hash(self) -> str:
        return content_hash(
            {
                "differences": [
                    {
                        "ticker": difference.ticker,
                        "field": difference.field,
                        "v2_value": difference.v2_value,
                        "v3_value": difference.v3_value,
                        "category": difference.category.value,
                    }
                    for difference in self.differences
                ]
            }
        )

    def blocking(self) -> tuple[Difference, ...]:
        return tuple(
            difference
            for difference in self.differences
            if difference.category in BLOCKING_CATEGORIES
        )


def audit_shadow_parity(
    *,
    v2_records: Iterable[Mapping[str, Any]],
    v3_records: Iterable[Mapping[str, Any]],
    policy: ExpectedDifferencePolicy,
) -> ShadowAuditReport:
    """只读对比 v2/v3 决策记录; 同输入必得同报告."""

    v2_by_ticker = _index(v2_records)
    v3_by_ticker = _index(v3_records)
    differences: list[Difference] = []
    for ticker in sorted(set(v2_by_ticker) | set(v3_by_ticker)):
        v2 = v2_by_ticker.get(ticker)
        v3 = v3_by_ticker.get(ticker)
        if v2 is None or v3 is None:
            present = v2 if v2 is not None else v3
            assert present is not None
            differences.append(
                Difference(
                    ticker=ticker,
                    field="record",
                    v2_value="present" if v2 is not None else "absent",
                    v3_value="present" if v3 is not None else "absent",
                    category=Category.DATA_MISMATCH,
                )
            )
            continue
        for field in COMPARE_FIELDS:
            v2_value = _stringify(v2.get(field))
            v3_value = _stringify(v3.get(field))
            if v2_value == v3_value:
                continue
            differences.append(
                Difference(
                    ticker=ticker,
                    field=field,
                    v2_value=v2_value,
                    v3_value=v3_value,
                    category=_classify(field, v2_value, v3_value, policy),
                )
            )
    return ShadowAuditReport(differences=tuple(differences))


def assert_no_blocking_differences(report: ShadowAuditReport) -> None:
    blocking = report.blocking()
    if blocking:
        summary = ", ".join(
            f"{difference.ticker}.{difference.field}:{difference.category.value}"
            for difference in blocking
        )
        raise GateError(
            f"blocking shadow differences prohibit flip/canary: {summary}"
        )


def _index(
    records: Iterable[Mapping[str, Any]],
) -> dict[str, Mapping[str, Any]]:
    indexed: dict[str, Mapping[str, Any]] = {}
    for record in records:
        ticker = str(record.get("ticker"))
        indexed[ticker] = dict(record)
    return indexed


def _stringify(value: Any) -> str:
    return "None" if value is None else str(value)


def _classify(
    field: str,
    v2_value: str,
    v3_value: str,
    policy: ExpectedDifferencePolicy,
) -> Category:
    if policy.covers(field, v2_value, v3_value):
        return Category.EXPECTED_POLICY_CHANGE
    if field == "admission":
        return Category.UNKNOWN
    if field in {"rank", "size", "cash", "reserve"}:
        return Category.KERNEL_BUG
    return Category.UNKNOWN
