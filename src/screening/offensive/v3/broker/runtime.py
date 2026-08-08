"""Plan 08: production composition layer wiring the fence into the send path.

``BrokerRuntime`` is the single entry point that couples the broker
dispatcher to the fencing authorities. Every entry/resend passes the
WriterHandoff fence (and the disaster-recovery entry gate) BEFORE the
dispatcher is touched, so a stale fencing epoch, a non-authority writer,
or an incomplete recovery is fail-closed before any command reaches the
broker — closing Plan 07 review finding M1 (the fence previously ran only
as an in-process invariant, not on the send path).

The fencing epoch is read live from the fence authority at send time (the
DR epoch when a recovery coordinator is present, else the handoff epoch),
never snapshotted at construction, so a completed handoff/DR that raised
the epoch is honored immediately.

Offline primitive: the adapter stays disabled, no real credential/DSN/
capital is touched. This proves the fence code invariant, not a broker
authorization.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from src.screening.offensive.v3.broker.disaster_recovery import (
    DisasterRecoveryCoordinator,
)
from src.screening.offensive.v3.broker.dispatcher import (
    BrokerDispatcher,
    DispatchOutcome,
)
from src.screening.offensive.v3.broker.handoff import WriterHandoff


class BrokerRuntimeError(RuntimeError):
    """Runtime composition failure with a stable machine-readable ``code``.

    Reserved for errors raised by the composition layer itself. Fence
    failures surface the fencing authority's own error unchanged —
    ``HandoffError`` from the WriterHandoff, ``DisasterRecoveryError`` from
    the DR coordinator — so callers handle one consistent contract per
    authority.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


@dataclass
class BrokerRuntime:
    """Couples the broker dispatcher to the fencing authorities.

    The single send-path entry point: every submit passes the fence before
    the dispatcher is invoked. The runtime holds no authorization, seal,
    reserve, or capital logic — it only adds the send-path fence.
    """

    dispatcher: BrokerDispatcher
    handoff: WriterHandoff
    writer_id: str
    recovery: DisasterRecoveryCoordinator | None = None

    @property
    def _authority(self) -> WriterHandoff | DisasterRecoveryCoordinator:
        """The single fencing authority: the DR coordinator when present (a
        completed recovery establishes the new writer + fencing epoch and
        subsumes the handoff fence), else the WriterHandoff. Centralizing this
        choice keeps the epoch and the fence check on the same authority."""

        return self.recovery if self.recovery is not None else self.handoff

    def current_fencing_epoch(self) -> int:
        """The live fencing epoch from the fence authority (DR wins)."""

        return self._authority.fencing_epoch

    def _fence(self) -> None:
        """Fail-closed fence before any dispatcher call (zero side effects).

        The epoch passed to the fence is always the fencing authority's own
        live epoch, read at send time (never a construction-time snapshot), so
        the two fencing authorities are never arbitrated against each other.
        """

        self._authority.fence_send(
            writer_id=self.writer_id, epoch=self._authority.fencing_epoch
        )

    def submit_entry(self, permit, expected_versions, *, context) -> DispatchOutcome:
        """Fence, then dispatch one claimed entry."""

        self._fence()
        return self.dispatcher.run_once(permit, expected_versions, context=context)

    def submit_resend(
        self,
        permit,
        *,
        context,
        broker_cutoff: datetime | None = None,
        certified_idempotent: bool | None = None,
        now: datetime | None = None,
    ) -> DispatchOutcome:
        """Fence, then resend exact claimed client ids (dispatcher keeps its
        cutoff/idempotency pre-guards; the runtime only adds the fence)."""

        self._fence()
        return self.dispatcher.resend(
            permit,
            context=context,
            broker_cutoff=broker_cutoff,
            certified_idempotent=certified_idempotent,
            now=now,
        )
