"""Plan 03 Task 2: expected-session spine and calendar revisions."""

from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from src.screening.offensive.v3.evidence.session_spine import (
    CalendarRevision,
    SessionEnrollment,
    SessionSpine,
    SessionSpineError,
    SessionStatus,
)

UTC = timezone.utc
NOW = datetime(2026, 8, 5, 9, 0, tzinfo=UTC)
PROGRAM = "prog-1"


class _Clock:
    def __init__(self, start: datetime) -> None:
        self.now_value = start

    def __call__(self) -> datetime:
        return self.now_value


@pytest.fixture()
def spine(tmp_path: Path) -> SessionSpine:
    return SessionSpine(
        database_path=str(tmp_path / "spine.sqlite3"),
        clock=_Clock(NOW),
    )


def _enroll(spine, *sessions: date) -> None:
    spine.enroll_expected_sessions(
        tuple(
            SessionEnrollment(
                research_program_id=PROGRAM,
                signal_session=session,
                assessment_date=session,
            )
            for session in sessions
        )
    )


def test_enrollment_is_fixed_and_assessment_dates_bound(
    spine: SessionSpine,
) -> None:
    day = date(2026, 8, 3)
    assert spine.enroll_expected_sessions(
        (
            SessionEnrollment(
                research_program_id=PROGRAM,
                signal_session=day,
                assessment_date=day,
            ),
        )
    ) == 1
    assert spine.is_enrolled(PROGRAM, day)
    # Re-enrolling the same session fails closed: the calendar is frozen.
    with pytest.raises(SessionSpineError) as excinfo:
        _enroll(spine, day)
    assert excinfo.value.code == "session_already_enrolled"


def test_assessment_cannot_precede_signal(spine: SessionSpine) -> None:
    with pytest.raises(SessionSpineError) as excinfo:
        spine.enroll_expected_sessions(
            (
                SessionEnrollment(
                    research_program_id=PROGRAM,
                    signal_session=date(2026, 8, 4),
                    assessment_date=date(2026, 8, 3),
                ),
            )
        )
    assert excinfo.value.code == "assessment_before_signal"


def test_status_revisions_append_and_latest_wins(spine: SessionSpine) -> None:
    day = date(2026, 8, 3)
    _enroll(spine, day)
    assert spine.status(PROGRAM, day) is None
    spine.record_session_status(PROGRAM, day, SessionStatus.DATA_UNKNOWN)
    assert spine.status(PROGRAM, day) is SessionStatus.DATA_UNKNOWN
    # A conflicting non-cancel status is now terminal (Task 11 hardening):
    # the first status stands and the conflict fails closed.
    with pytest.raises(SessionSpineError) as excinfo:
        spine.record_session_status(PROGRAM, day, SessionStatus.RUN)
    assert excinfo.value.code == "status_terminal_conflict"
    assert spine.status(PROGRAM, day) is SessionStatus.DATA_UNKNOWN


def test_status_requires_enrollment(spine: SessionSpine) -> None:
    with pytest.raises(SessionSpineError) as excinfo:
        spine.record_session_status(
            PROGRAM, date(2026, 1, 1), SessionStatus.RUN
        )
    assert excinfo.value.code == "session_not_enrolled"


def test_cancellation_requires_signed_calendar_revision_and_keeps_row(
    spine: SessionSpine,
) -> None:
    day = date(2026, 8, 3)
    _enroll(spine, day)
    with pytest.raises(SessionSpineError) as excinfo:
        spine.record_session_status(
            PROGRAM, day, SessionStatus.SESSION_CANCELLED
        )
    assert excinfo.value.code == "cancellation_requires_calendar_revision"

    revision = CalendarRevision(
        calendar_revision_hash="e" * 64,
        research_program_id=PROGRAM,
        signal_session=day,
        reason="exchange announced trading halt",
        issued_at=NOW,
    )
    spine.record_session_status(
        PROGRAM, day, SessionStatus.SESSION_CANCELLED, revision
    )
    # The enrollment is never deleted; the status lineage carries the
    # signed cancellation.
    assert spine.is_enrolled(PROGRAM, day)
    assert spine.status(PROGRAM, day) is SessionStatus.SESSION_CANCELLED


def test_calendar_revision_mismatch_is_rejected(spine: SessionSpine) -> None:
    day = date(2026, 8, 3)
    _enroll(spine, day)
    wrong = CalendarRevision(
        calendar_revision_hash="e" * 64,
        research_program_id=PROGRAM,
        signal_session=date(2026, 8, 4),
        reason="wrong session",
        issued_at=NOW,
    )
    with pytest.raises(SessionSpineError) as excinfo:
        spine.record_session_status(
            PROGRAM, day, SessionStatus.SESSION_CANCELLED, wrong
        )
    assert excinfo.value.code == "calendar_revision_mismatch"


def test_finalized_missing_run_becomes_no_run(spine: SessionSpine) -> None:
    day = date(2026, 8, 3)
    _enroll(spine, day)
    spine.mark_no_run(PROGRAM, day)
    assert spine.status(PROGRAM, day) is SessionStatus.NO_RUN


def test_identical_status_retry_is_quiet_terminal(spine: SessionSpine) -> None:
    """A non-cancel status is an exact-idempotent terminal fact: retrying the
    same status is quiet, not a duplicate or an error."""
    day = date(2026, 8, 3)
    _enroll(spine, day)
    spine.record_session_status(PROGRAM, day, SessionStatus.RUN)
    spine.record_session_status(PROGRAM, day, SessionStatus.RUN)
    spine.record_session_status(PROGRAM, day, SessionStatus.RUN)
    assert spine.status(PROGRAM, day) is SessionStatus.RUN


def test_conflicting_non_cancel_status_fails_closed(spine: SessionSpine) -> None:
    """Once a non-cancel status is terminal, a conflicting non-cancel status
    fails closed instead of silently superseding it."""
    day = date(2026, 8, 3)
    _enroll(spine, day)
    spine.record_session_status(PROGRAM, day, SessionStatus.RUN)
    with pytest.raises(SessionSpineError) as excinfo:
        spine.record_session_status(PROGRAM, day, SessionStatus.NO_SIGNAL)
    assert excinfo.value.code == "status_terminal_conflict"


def test_signed_calendar_revision_supersedes_terminal_status(
    spine: SessionSpine,
) -> None:
    """A signed calendar revision may supersede any terminal status with
    SESSION_CANCELLED; cancellation is itself terminal."""
    day = date(2026, 8, 3)
    _enroll(spine, day)
    spine.record_session_status(PROGRAM, day, SessionStatus.RUN)
    revision = CalendarRevision(
        calendar_revision_hash="e" * 64,
        research_program_id=PROGRAM,
        signal_session=day,
        reason="exchange announced trading halt",
        issued_at=NOW,
    )
    spine.record_session_status(
        PROGRAM, day, SessionStatus.SESSION_CANCELLED, revision
    )
    assert spine.status(PROGRAM, day) is SessionStatus.SESSION_CANCELLED
    # CANCELLED is terminal: neither another cancel nor a status retry moves it.
    with pytest.raises(SessionSpineError) as excinfo:
        spine.record_session_status(PROGRAM, day, SessionStatus.RUN)
    assert excinfo.value.code == "cancelled_terminal"
