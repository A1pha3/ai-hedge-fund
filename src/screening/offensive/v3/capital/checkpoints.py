"""Monotone session checkpoints for the capital authority store.

Plan 02 Task 7 scope (spec section 12.2): one trading session advances
through a fixed phase ladder; the checkpoint key is ``(session, phase)``
with the committed ``stream_version`` watermark. Crash restart converges
idempotently on the committed checkpoint; a phase behind the session
watermark or an ``as_of`` earlier than the newest committed checkpoint is
rejected fail-closed. Late corrections append at the current recorded
instant with an advancing stream and never reopen or rewrite committed
checkpoints.

Enforcing zero-write rejection of production requests older than the
watermark consumes these watermarks together with the permit capital
version binding; that gating ships with the Plan 04 gateway.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Final

import sqlalchemy as sa

from src.screening.offensive.v3.capital.repository import CapitalConflict
from src.screening.offensive.v3.contracts import CanonicalModel
from src.screening.offensive.v3.contracts.evidence import NonEmptyStr
from src.screening.offensive.v3.storage.metadata import utc_iso

if TYPE_CHECKING:
    from src.screening.offensive.v3.capital.repository import CapitalRepository

SESSION_PHASES: Final[tuple[str, ...]] = (
    "CORPORATE_ACTIONS_APPLIED",
    "PREOPEN_RISK_LOCKED",
    "ORDER_INTENTS_DURABLE",
    "OPEN_RECONCILED",
    "CLOSE_VALUED",
    "SESSION_FINALIZED",
)

_PHASE_INDEX: Final[dict[str, int]] = {
    phase: index for index, phase in enumerate(SESSION_PHASES)
}


class SessionCheckpointRequest(CanonicalModel):
    """One requested session checkpoint advance."""

    session: NonEmptyStr
    phase: NonEmptyStr
    as_of: "datetime"
    expected_stream_version: int


class SessionCheckpointReceipt(CanonicalModel):
    """The committed checkpoint after an advance (or idempotent retry)."""

    session: NonEmptyStr
    phase: NonEmptyStr
    stream_version: int
    capital_version: int
    recorded_at: "datetime"


class CheckpointService:
    """Advance and read the monotone session checkpoints of one ledger."""

    def __init__(self, repository: "CapitalRepository") -> None:
        self._repository = repository

    def watermark(self, session: str) -> int:
        """Highest stream version any checkpoint of the session committed."""

        with self._repository.engine.connect() as conn:
            row = conn.execute(
                sa.text(
                    "SELECT COALESCE(MAX(stream_version), 0) AS v"
                    " FROM session_checkpoints WHERE session = :session"
                ),
                {"session": session},
            ).one()
        return int(row.v)

    def advance(
        self, request: SessionCheckpointRequest
    ) -> SessionCheckpointReceipt:
        if request.phase not in _PHASE_INDEX:
            raise CapitalConflict(
                "checkpoint_phase_unknown",
                "session checkpoint phase is not in the frozen ladder",
                phase=request.phase,
            )
        repository = self._repository
        table = repository._metadata.tables["session_checkpoints"]
        with repository.engine.begin() as conn:
            current_stream = int(
                conn.execute(
                    sa.text(
                        "SELECT COALESCE(MAX(stream_version), 0) AS v"
                        " FROM economic_events"
                    )
                ).one().v
            )
            if current_stream != int(request.expected_stream_version):
                raise CapitalConflict(
                    "stream_version_mismatch",
                    "compare-and-swap failed: the capital stream advanced",
                    expected_stream_version=int(
                        request.expected_stream_version
                    ),
                    current_stream_version=current_stream,
                )
            capital_version = int(
                conn.execute(
                    sa.text(
                        "SELECT COALESCE("
                        " (SELECT capital_version FROM capital_projection),"
                        " 0) AS v"
                    )
                ).one().v
            )
            rows = conn.execute(
                table.select().where(table.c.session == request.session)
            ).all()
            newest_index = -1
            newest_recorded_at: str | None = None
            same_phase_row = None
            for row in rows:
                index = _PHASE_INDEX.get(row.phase, -1)
                if index > newest_index:
                    newest_index = index
                    newest_recorded_at = row.recorded_at
                if row.phase == request.phase:
                    same_phase_row = row
            requested_index = _PHASE_INDEX[request.phase]
            if requested_index < newest_index:
                raise CapitalConflict(
                    "checkpoint_order_conflict",
                    "session checkpoint phase is behind the session"
                    " watermark",
                    session=request.session,
                    phase=request.phase,
                )
            if (
                same_phase_row is not None
                and int(same_phase_row.stream_version) == current_stream
            ):
                if str(same_phase_row.recorded_at) != utc_iso(request.as_of):
                    raise CapitalConflict(
                        "checkpoint_content_conflict",
                        "checkpoint already committed for this phase and"
                        " stream with different content",
                        session=request.session,
                        phase=request.phase,
                    )
                return SessionCheckpointReceipt(
                    session=request.session,
                    phase=request.phase,
                    stream_version=current_stream,
                    capital_version=capital_version,
                    recorded_at=request.as_of,
                )
            if newest_recorded_at is not None and (
                utc_iso(request.as_of) < newest_recorded_at
            ):
                raise CapitalConflict(
                    "checkpoint_time_conflict",
                    "session checkpoint as_of is earlier than the newest"
                    " committed checkpoint",
                    session=request.session,
                    as_of=utc_iso(request.as_of),
                    newest_recorded_at=newest_recorded_at,
                )
            if same_phase_row is not None and (
                int(same_phase_row.stream_version) > current_stream
            ):
                raise CapitalConflict(
                    "checkpoint_content_conflict",
                    "checkpoint stream watermark must be monotone",
                    session=request.session,
                    phase=request.phase,
                )
            conn.execute(
                sa.text(
                    "INSERT INTO session_checkpoints (session, phase,"
                    " stream_version, recorded_at)"
                    " VALUES (:session, :phase, :stream_version,"
                    " :recorded_at)"
                    " ON CONFLICT(session, phase) DO UPDATE SET"
                    " stream_version = excluded.stream_version,"
                    " recorded_at = excluded.recorded_at"
                ),
                {
                    "session": request.session,
                    "phase": request.phase,
                    "stream_version": current_stream,
                    "recorded_at": utc_iso(request.as_of),
                },
            )
        return SessionCheckpointReceipt(
            session=request.session,
            phase=request.phase,
            stream_version=current_stream,
            capital_version=capital_version,
            recorded_at=request.as_of,
        )
