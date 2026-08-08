"""Plan 06 Task 3: 逐项资本守恒证明.

`verify_conservation()` 对比 source 盘点与 prepared target projection 的每个
守恒节 — 只比总 NAV 不足够: cash / positions / plans / pending_exits / fees /
counts 任一漂移即 ConservationError 并点名 section.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Mapping

from src.screening.offensive.v3.contracts import CanonicalModel

from src.screening.offensive.v3.migration.inventory import V2Inventory

CONSERVATION_MISMATCH = "CONSERVATION_MISMATCH"
MISSING_SECTION = "MISSING_SECTION"

_SECTIONS = (
    "cash",
    "positions",
    "plans",
    "pending_exits",
    "fees",
    "counts",
)


class ConservationError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


class ConservationProof(CanonicalModel):
    verified_sections: tuple[str, ...]


def verify_conservation(
    source: V2Inventory,
    target_projection: Mapping[str, Any],
) -> ConservationProof:
    """逐项对比; 全部一致才返回 proof."""

    verified: list[str] = []
    for section in _SECTIONS:
        if section not in target_projection:
            raise ConservationError(
                MISSING_SECTION, f"target projection missing section {section!r}"
            )
        expected = _expected_section(source, section)
        actual = target_projection[section]
        if _normalize(actual) != _normalize(expected):
            raise ConservationError(
                CONSERVATION_MISMATCH,
                f"section {section!r} drifted: expected {expected!r}, "
                f"observed {actual!r}",
            )
        verified.append(section)
    return ConservationProof(verified_sections=tuple(verified))


def _expected_section(source: V2Inventory, section: str) -> Any:
    if section == "cash":
        return {
            "initial_cash": str(source.cash.initial_cash),
            "event_cash_delta_sum": str(source.cash.event_cash_delta_sum),
            "cash_balance": str(source.cash.cash_balance),
        }
    if section == "positions":
        return [
            {
                "trade_id": p.trade_id,
                "ticker": p.ticker,
                "state": p.state,
                "quantity": p.quantity,
                "raw_entry_price": (
                    str(p.raw_entry_price) if p.raw_entry_price is not None else None
                ),
            }
            for p in source.positions
        ]
    if section == "plans":
        return [
            {
                "trade_id": p.trade_id,
                "ticker": p.ticker,
                "planned_weight": str(p.planned_weight),
                "priority": p.priority,
            }
            for p in source.plans
        ]
    if section == "pending_exits":
        return [
            {
                "trade_id": p.trade_id,
                "exit_trigger_date": (
                    p.exit_trigger_date.isoformat() if p.exit_trigger_date else None
                ),
                "defer_count": p.defer_count,
            }
            for p in source.pending_exits
        ]
    if section == "fees":
        return {
            "entry_commission": str(source.fees.entry_commission),
            "entry_tax": str(source.fees.entry_tax),
            "entry_slippage": str(source.fees.entry_slippage),
            "exit_commission": str(source.fees.exit_commission),
            "exit_tax": str(source.fees.exit_tax),
            "exit_slippage": str(source.fees.exit_slippage),
        }
    if section == "counts":
        return {
            "event_count": source.event_count,
            "trade_count": source.trade_count,
        }
    raise AssertionError(section)  # pragma: no cover


def _normalize(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _normalize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normalize(item) for item in value]
    if isinstance(value, Decimal):
        return str(value)
    return value
