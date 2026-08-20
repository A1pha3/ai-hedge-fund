"""Per-arm open-fill lifecycle driver — Phase 5c of the paired BTST forward trial.

Ownership layering (2026-08-20 adversarial-review ruling): the market judgment
(UNKNOWN/NO_FILL/FILLED and the fill price) belongs to
``execution.lifecycle.resolve_open_execution`` — the locked decision table with
its defensive ordering; the ledger truth belongs to the capital repository's
fill-revision primitive. This driver only MAPS one to the other. It contains no
market math and no fence derivation; the withdrawn replay mutation helpers stay
withdrawn (the capital repository owns lifecycle mutation).

Deterministic execution identity ``{arm}:{decision_id}:{side}`` makes replays
idempotent by construction; fills are appended only for ``FILLED`` verdicts —
UNKNOWN keeps the cash and NO_FILL is a legal empty (both per the constitution's
locked daily-bar-proxy semantics).
"""

from __future__ import annotations

from datetime import datetime

from src.screening.offensive.v3.capital.fills import FillAttribution
from src.screening.offensive.v3.capital.fills import FillRevisionRequest
from src.screening.offensive.v3.capital.repository import CapitalRepository
from src.screening.offensive.v3.contracts.execution import ExecutionSide
from src.screening.offensive.v3.execution.lifecycle import (
    DailyBar,
    OpenExecutionResolution,
    resolve_open_execution,
)

_PROXY_AUTHORITY = "daily-bar-proxy.trial"


class ArmLifecycleError(RuntimeError):
    def __init__(self, code: str, message: str, **details: object) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.details = details


def drive_open_fill(
    repository: CapitalRepository,
    *,
    arm: str,
    decision_id: str,
    side: ExecutionSide,
    security_id: str,
    position_lineage_id: str,
    economic_lot_id: str,
    limit_price_cents: int,
    quantity: int,
    bar: DailyBar | None,
    command_at: datetime,
    send_deadline: datetime,
    attribution: FillAttribution,
    as_of: datetime,
) -> OpenExecutionResolution:
    """Resolve one open execution and, only on FILLED, append the fill.

    Returns the resolution unchanged so callers record UNKNOWN/NO_FILL
    outcomes in their own journals without touching the ledger (UNKNOWN keeps
    the cash; NO_FILL means the limit was never touched).
    """
    if quantity <= 0:
        raise ArmLifecycleError("quantity_not_positive", f"quantity {quantity} must be positive")
    # 宪法 #9 纪律 (对抗审查 2026-08-20): EXIT 的 quantity 必须取自资本仓位的
    # 当前投影 (未知可卖量不得卖出/超卖); 台账原语是最后防线, 本签名要求
    # 调用方 (顺序重放驱动) 先查投影再传量。
    resolution = resolve_open_execution(
        side=side,
        limit_price_cents=limit_price_cents,
        bar=bar,
        command_at=command_at,
        send_deadline=send_deadline,
    )
    if resolution.fill_price_cents is None:
        return resolution
    execution_id = f"{arm}:{decision_id}:{side.value}"
    request = FillRevisionRequest(
        execution_id=execution_id,
        revision=1,
        order_id=f"ord-{execution_id}",
        side=side,
        security_id=security_id,
        price_micros=resolution.fill_price_cents * 10_000,
        quantity=quantity,
        position_lineage_id=position_lineage_id,
        economic_lot_id=economic_lot_id,
        attribution=attribution,
        source_authority=_PROXY_AUTHORITY,
        effective_at=command_at,
        as_of=as_of,
        expected_stream_version=repository.stream_version(),
    )
    repository.record_fill_revision(request)
    return resolution


__all__ = ["ArmLifecycleError", "drive_open_fill"]
