"""Expected-session spine for official evaluation (Plan 03 Task 2).

Official sessions are enrolled with fixed assessment dates BEFORE any
observation is recorded; every enrolled session carries exactly one
immutable status lineage. Cancellations append a signed calendar revision
(``SESSION_CANCELLED``) and never delete the enrollment; a finalized
session with no recorded run becomes ``NO_RUN``.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import Callable, Final

import sqlalchemy as sa


class SessionStatus(StrEnum):
    RUN = "RUN"
    NO_SIGNAL = "NO_SIGNAL"
    BLOCKED = "BLOCKED"
    NO_RUN = "NO_RUN"
    DATA_UNKNOWN = "DATA_UNKNOWN"
    SESSION_CANCELLED = "SESSION_CANCELLED"


_SCHEMA_DDL: Final[tuple[str, ...]] = (
    """
    CREATE TABLE IF NOT EXISTS expected_sessions (
        research_program_id TEXT NOT NULL,
        signal_session TEXT NOT NULL,
        assessment_date TEXT NOT NULL,
        enrolled_at TEXT NOT NULL,
        PRIMARY KEY (research_program_id, signal_session)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS session_status_revisions (
        research_program_id TEXT NOT NULL,
        signal_session TEXT NOT NULL,
        revision INTEGER NOT NULL,
        status TEXT NOT NULL,
        calendar_revision_hash TEXT,
        recorded_at TEXT NOT NULL,
        PRIMARY KEY (research_program_id, signal_session, revision)
    )
    """,
    "CREATE TRIGGER IF NOT EXISTS no_update_expected_sessions "
    "BEFORE UPDATE ON expected_sessions "
    "BEGIN SELECT RAISE(ABORT, 'immutable table: expected_sessions "
    "rejects UPDATE'); END;",
    "CREATE TRIGGER IF NOT EXISTS no_delete_expected_sessions "
    "BEFORE DELETE ON expected_sessions "
    "BEGIN SELECT RAISE(ABORT, 'immutable table: expected_sessions "
    "rejects DELETE'); END;",
    "CREATE TRIGGER IF NOT EXISTS no_update_session_status_revisions "
    "BEFORE UPDATE ON session_status_revisions "
    "BEGIN SELECT RAISE(ABORT, 'immutable table: "
    "session_status_revisions rejects UPDATE'); END;",
    "CREATE TRIGGER IF NOT EXISTS no_delete_session_status_revisions "
    "BEFORE DELETE ON session_status_revisions "
    "BEGIN SELECT RAISE(ABORT, 'immutable table: "
    "session_status_revisions rejects DELETE'); END;",
)


@dataclass(frozen=True)
class SessionEnrollment:
    research_program_id: str
    signal_session: date
    assessment_date: date


@dataclass(frozen=True)
class CalendarRevision:
    """One signed exchange-calendar correction."""

    calendar_revision_hash: str
    research_program_id: str
    signal_session: date
    reason: str
    issued_at: datetime


class SessionSpineError(RuntimeError):
    """Fail-closed rejection of a session spine operation."""

    def __init__(self, code: str, message: str, **details: object) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.details = details


class SessionSpine:
    """Append-only enrolled-session timeline for one evaluation scope."""

    def __init__(
        self,
        *,
        database_path: str,
        clock: Callable[[], datetime],
    ) -> None:
        self._clock = clock
        self._engine = sa.create_engine(
            f"sqlite:///{database_path}",
            connect_args={"check_same_thread": False},
        )
        sa.event.listen(self._engine, "connect", _configure_connection)
        with self._engine.begin() as conn:
            for ddl in _SCHEMA_DDL:
                conn.execute(sa.text(ddl))

    def enroll_expected_sessions(
        self, enrollments: tuple[SessionEnrollment, ...]
    ) -> int:
        """Enroll the fixed assessment calendar before observations.

        Enrolling an already-enrolled session fails closed: the calendar
        is frozen once committed.
        """

        if not enrollments:
            raise SessionSpineError(
                "enrollment_empty", "no sessions to enroll"
            )
        enrolled_at = self._clock()
        with self._engine.begin() as conn:
            try:
                for enrollment in enrollments:
                    if enrollment.assessment_date < enrollment.signal_session:
                        raise SessionSpineError(
                            "assessment_before_signal",
                            "assessment date precedes the signal session",
                        )
                    conn.execute(
                        sa.text(
                            "INSERT INTO expected_sessions ("
                            " research_program_id, signal_session,"
                            " assessment_date, enrolled_at)"
                            " VALUES (:program, :session, :assessment,"
                            " :enrolled_at)"
                        ),
                        {
                            "program": enrollment.research_program_id,
                            "session": enrollment.signal_session.isoformat(),
                            "assessment": (
                                enrollment.assessment_date.isoformat()
                            ),
                            "enrolled_at": enrolled_at.isoformat(),
                        },
                    )
            except sa.exc.IntegrityError as exc:
                raise SessionSpineError(
                    "session_already_enrolled",
                    "session calendar is frozen once committed",
                    reason=str(exc),
                ) from exc
        return len(enrollments)

    def _require_enrolled(
        self,
        conn: sa.engine.Connection,
        research_program_id: str,
        signal_session: date,
    ) -> None:
        row = conn.execute(
            sa.text(
                "SELECT 1 FROM expected_sessions"
                " WHERE research_program_id = :program"
                " AND signal_session = :session"
            ),
            {
                "program": research_program_id,
                "session": signal_session.isoformat(),
            },
        ).first()
        if row is None:
            raise SessionSpineError(
                "session_not_enrolled",
                "status can only be recorded for enrolled sessions",
            )

    def _next_revision(
        self,
        conn: sa.engine.Connection,
        research_program_id: str,
        signal_session: date,
    ) -> int:
        row = conn.execute(
            sa.text(
                "SELECT COALESCE(MAX(revision), 0) AS r"
                " FROM session_status_revisions"
                " WHERE research_program_id = :program"
                " AND signal_session = :session"
            ),
            {
                "program": research_program_id,
                "session": signal_session.isoformat(),
            },
        ).one()
        return int(row.r) + 1

    def _append_status(
        self,
        research_program_id: str,
        signal_session: date,
        status: SessionStatus,
        calendar_revision_hash: str | None,
    ) -> int:
        """Append one status revision with exact-idempotent terminal semantics.

        A non-cancel status is a terminal fact: retrying the identical status
        is quiet (returns the existing revision, no new row); a conflicting
        non-cancel status fails closed; ``SESSION_CANCELLED`` is itself
        terminal and can never be superseded. Only a signed calendar revision
        may supersede any terminal status with ``SESSION_CANCELLED`` (the
        caller enforces that the revision exists).
        """

        recorded_at = self._clock()
        with self._engine.begin() as conn:
            self._require_enrolled(
                conn, research_program_id, signal_session
            )
            latest = conn.execute(
                sa.text(
                    "SELECT status FROM session_status_revisions"
                    " WHERE research_program_id = :program"
                    " AND signal_session = :session"
                    " ORDER BY revision DESC LIMIT 1"
                ),
                {
                    "program": research_program_id,
                    "session": signal_session.isoformat(),
                },
            ).first()
            if latest is not None:
                latest_status = SessionStatus(latest.status)
                if latest_status is SessionStatus.SESSION_CANCELLED:
                    raise SessionSpineError(
                        "cancelled_terminal",
                        "a cancelled session is terminal; no status may"
                        " supersede it",
                    )
                if latest_status is status:
                    # Identical status retry: quiet, no duplicate row.
                    return int(
                        conn.execute(
                            sa.text(
                                "SELECT MAX(revision) FROM"
                                " session_status_revisions"
                                " WHERE research_program_id = :program"
                                " AND signal_session = :session"
                            ),
                            {
                                "program": research_program_id,
                                "session": signal_session.isoformat(),
                            },
                        ).scalar()
                    )
                if status is not SessionStatus.SESSION_CANCELLED:
                    raise SessionSpineError(
                        "status_terminal_conflict",
                        "a non-cancel status is terminal; only a signed"
                        " calendar revision may supersede it",
                    )
            revision = self._next_revision(
                conn, research_program_id, signal_session
            )
            conn.execute(
                sa.text(
                    "INSERT INTO session_status_revisions ("
                    " research_program_id, signal_session, revision,"
                    " status, calendar_revision_hash, recorded_at)"
                    " VALUES (:program, :session, :revision, :status,"
                    " :calendar_hash, :recorded_at)"
                ),
                {
                    "program": research_program_id,
                    "session": signal_session.isoformat(),
                    "revision": revision,
                    "status": status.value,
                    "calendar_hash": calendar_revision_hash,
                    "recorded_at": recorded_at.isoformat(),
                },
            )
        return revision

    def record_session_status(
        self,
        research_program_id: str,
        signal_session: date,
        status: SessionStatus,
        calendar_revision: CalendarRevision | None = None,
    ) -> int:
        """Append one status revision; cancellations require the signed
        calendar revision and never delete the enrollment."""

        if status is SessionStatus.SESSION_CANCELLED:
            if calendar_revision is None:
                raise SessionSpineError(
                    "cancellation_requires_calendar_revision",
                    "cancelled sessions need a signed calendar revision",
                )
            if (
                calendar_revision.research_program_id
                != research_program_id
                or calendar_revision.signal_session != signal_session
            ):
                raise SessionSpineError(
                    "calendar_revision_mismatch",
                    "calendar revision does not match the session",
                )
            return self._append_status(
                research_program_id,
                signal_session,
                status,
                calendar_revision.calendar_revision_hash,
            )
        return self._append_status(
            research_program_id, signal_session, status, None
        )

    def mark_no_run(
        self, research_program_id: str, signal_session: date
    ) -> int:
        """Finalize a missing run: enrolled but nothing was recorded."""

        return self._append_status(
            research_program_id,
            signal_session,
            SessionStatus.NO_RUN,
            None,
        )

    def status(
        self, research_program_id: str, signal_session: date
    ) -> SessionStatus | None:
        with self._engine.connect() as conn:
            row = conn.execute(
                sa.text(
                    "SELECT status FROM session_status_revisions"
                    " WHERE research_program_id = :program"
                    " AND signal_session = :session"
                    " ORDER BY revision DESC LIMIT 1"
                ),
                {
                    "program": research_program_id,
                    "session": signal_session.isoformat(),
                },
            ).first()
        if row is None:
            return None
        return SessionStatus(row.status)

    def is_enrolled(
        self, research_program_id: str, signal_session: date
    ) -> bool:
        with self._engine.connect() as conn:
            row = conn.execute(
                sa.text(
                    "SELECT 1 FROM expected_sessions"
                    " WHERE research_program_id = :program"
                    " AND signal_session = :session"
                ),
                {
                    "program": research_program_id,
                    "session": signal_session.isoformat(),
                },
            ).first()
        return row is not None

    def enrolled_sessions(
        self, research_program_id: str
    ) -> tuple[SessionEnrollment, ...]:
        """All enrolled expected sessions for one program, in calendar order."""

        with self._engine.connect() as conn:
            rows = conn.execute(
                sa.text(
                    "SELECT signal_session, assessment_date"
                    " FROM expected_sessions"
                    " WHERE research_program_id = :program"
                    " ORDER BY signal_session"
                ),
                {"program": research_program_id},
            ).fetchall()
        return tuple(
            SessionEnrollment(
                research_program_id=research_program_id,
                signal_session=date.fromisoformat(row[0]),
                assessment_date=date.fromisoformat(row[1]),
            )
            for row in rows
        )


def _configure_connection(dbapi_connection: object, _record: object) -> None:
    if not isinstance(dbapi_connection, sqlite3.Connection):
        return
    dbapi_connection.execute("PRAGMA journal_mode=WAL")
    dbapi_connection.execute("PRAGMA synchronous=NORMAL")
    dbapi_connection.execute("PRAGMA foreign_keys=ON")
    dbapi_connection.execute("PRAGMA busy_timeout=15000")


__all__ = [
    "CalendarRevision",
    "SessionEnrollment",
    "SessionSpine",
    "SessionSpineError",
    "SessionStatus",
]
