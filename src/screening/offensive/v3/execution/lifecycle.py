"""Plan 04 Task 8: shared execution-lifecycle primitives.

Two execution modes coexist in this layer - ``DAILY_BAR_PROXY`` and
``MANUAL_CONFIRMED`` - but neither may copy the other's economic facts. The
shared primitives here keep that boundary mechanical:

- ``DailyBar`` is the only market observation the proxy consumes. It carries
  the target-session open/high/low/close together with the price-limit
  fences, so the decision table can tell a one-price limit lock (one daily
  bar can never prove a queue position) from an ordinary limit touch.
- ``resolve_open_execution`` is the pure decision table: missing bar,
  suspension, and a late command all resolve ``UNKNOWN`` and keep the cash;
  a one-price limit lock on the locked side is ambiguous and also
  ``UNKNOWN``; an ordinary limit touch fills at ``min(open, limit)`` for
  buys and ``max(open, limit)`` for sells; an untouched limit resolves
  ``NO_FILL``. No known executable open ever means a stale-close fill.
- ``ExecutionError`` is the typed fail-closed channel shared by both modes,
  mirroring ``CapitalGatewayError`` / ``ExitLaneError``.

Nothing in this module touches storage, network, or a clock: the table is a
pure function of injected truth, so the same bar and command always resolve
to the same verdict across processes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from typing import Final

from src.screening.offensive.v3.contracts import ExecutionSide


class ExecutionError(Exception):
    """Typed fail-closed error for the execution layer.

    Mirrors ``CapitalGatewayError`` / ``ExitLaneError``: a stable ``code``
    plus a human message and arbitrary structured ``details`` so callers
    never branch on string matching.
    """

    def __init__(self, code: str, message: str, **details: object) -> None:
        super().__init__(message)
        self.code = code
        self.details = details


class OpenExecutionVerdict(Enum):
    """The outcome of resolving one open execution against a daily bar."""

    FILLED = "FILLED"
    NO_FILL = "NO_FILL"
    # UNKNOWN covers every case where one daily bar cannot prove the order
    # filled: missing bar, suspension, a late command, or a one-price limit
    # lock on the locked side. UNKNOWN keeps the cash and never guesses.
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class OpenExecutionResolution:
    """One resolved open execution: verdict, fill price (or None), reason."""

    verdict: OpenExecutionVerdict
    fill_price_cents: int | None
    reason: str


@dataclass(frozen=True)
class DailyBar:
    """One target-session daily bar plus its price-limit fences.

    All prices are integer cents. ``suspended`` marks a session with no
    tradable open. The one-price limit helpers express the A-share
    one-character涨停/跌停 ambiguity: when open == high == low == close ==
    the limit fence, a single daily bar cannot prove the order's queue
    position on the locked side.
    """

    security_id: str
    session: date
    open_cents: int
    high_cents: int
    low_cents: int
    close_cents: int
    limit_up_cents: int
    limit_down_cents: int
    suspended: bool = False

    @property
    def is_one_price_limit_up(self) -> bool:
        """Four prices collapse onto the up-limit fence."""

        fence = self.limit_up_cents
        return (
            self.open_cents == fence
            and self.high_cents == fence
            and self.low_cents == fence
            and self.close_cents == fence
        )

    @property
    def is_one_price_limit_down(self) -> bool:
        """Four prices collapse onto the down-limit fence."""

        fence = self.limit_down_cents
        return (
            self.open_cents == fence
            and self.high_cents == fence
            and self.low_cents == fence
            and self.close_cents == fence
        )


# Reason vocabulary used by the decision table. The strings are part of the
# execution contract: tests and downstream provenance pin them, so they are
# gathered here as named constants rather than scattered literals.
REASON_MISSING_BAR: Final[str] = "missing_bar"
REASON_SUSPENDED_BAR: Final[str] = "suspended_bar"
REASON_LATE_COMMAND: Final[str] = "late_command"
REASON_ONE_PRICE_LIMIT_UP: Final[str] = "one_price_limit_up"
REASON_ONE_PRICE_LIMIT_DOWN: Final[str] = "one_price_limit_down"
REASON_LIMIT_TOUCHED: Final[str] = "limit_touched"
REASON_LIMIT_NOT_TOUCHED: Final[str] = "limit_not_touched"


def resolve_open_execution(
    *,
    side: ExecutionSide,
    limit_price_cents: int,
    bar: DailyBar | None,
    command_at: datetime,
    send_deadline: datetime,
) -> OpenExecutionResolution:
    """Resolve one open execution against the locked decision table.

    The resolution order is deliberately defensive: the unprovable cases
    (missing bar, suspension, late command, one-price limit lock on the
    locked side) are tested before any fill, so no close inside the limit
    can rescue a bar whose open is unproven.

    - missing bar, suspension, or a command issued strictly after the
      gateway send deadline resolve ``UNKNOWN`` and keep the cash;
    - a one-price limit-up lock is ambiguous for a buy, a one-price
      limit-down lock is ambiguous for a sell -> ``UNKNOWN``;
    - an ordinary limit touch fills at ``min(open, limit)`` for buys and
      ``max(open, limit)`` for sells;
    - an untouched limit resolves ``NO_FILL``.
    """

    if bar is None:
        return OpenExecutionResolution(
            OpenExecutionVerdict.UNKNOWN, None, REASON_MISSING_BAR
        )
    if bar.suspended:
        return OpenExecutionResolution(
            OpenExecutionVerdict.UNKNOWN, None, REASON_SUSPENDED_BAR
        )
    if command_at > send_deadline:
        return OpenExecutionResolution(
            OpenExecutionVerdict.UNKNOWN, None, REASON_LATE_COMMAND
        )
    if side is ExecutionSide.ENTRY and bar.is_one_price_limit_up:
        return OpenExecutionResolution(
            OpenExecutionVerdict.UNKNOWN, None, REASON_ONE_PRICE_LIMIT_UP
        )
    if side is ExecutionSide.EXIT and bar.is_one_price_limit_down:
        return OpenExecutionResolution(
            OpenExecutionVerdict.UNKNOWN, None, REASON_ONE_PRICE_LIMIT_DOWN
        )
    if side is ExecutionSide.ENTRY:
        touched = bar.low_cents <= limit_price_cents
        if not touched:
            return OpenExecutionResolution(
                OpenExecutionVerdict.NO_FILL, None, REASON_LIMIT_NOT_TOUCHED
            )
        fill_price = min(bar.open_cents, limit_price_cents)
        return OpenExecutionResolution(
            OpenExecutionVerdict.FILLED, fill_price, REASON_LIMIT_TOUCHED
        )
    # EXIT: a sell touches when the session traded at or above the limit.
    touched = bar.high_cents >= limit_price_cents
    if not touched:
        return OpenExecutionResolution(
            OpenExecutionVerdict.NO_FILL, None, REASON_LIMIT_NOT_TOUCHED
        )
    fill_price = max(bar.open_cents, limit_price_cents)
    return OpenExecutionResolution(
        OpenExecutionVerdict.FILLED, fill_price, REASON_LIMIT_TOUCHED
    )


__all__ = [
    "DailyBar",
    "ExecutionError",
    "OpenExecutionResolution",
    "OpenExecutionVerdict",
    "REASON_LATE_COMMAND",
    "REASON_LIMIT_NOT_TOUCHED",
    "REASON_LIMIT_TOUCHED",
    "REASON_MISSING_BAR",
    "REASON_ONE_PRICE_LIMIT_DOWN",
    "REASON_ONE_PRICE_LIMIT_UP",
    "REASON_SUSPENDED_BAR",
    "resolve_open_execution",
]
