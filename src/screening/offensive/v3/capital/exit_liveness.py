"""Ledger-only exit-obligation derivation — re-enable gate clause ⑤ primitive.

Re-enable gate clause 5 of the shadow-capital mutation withdrawal
(``docs/superpowers/migrations/2026-08-13-shadow-capital-mutation-withdrawal.md``)
requires "independent exit liveness, including crash recovery and
correction/bust reopening, without relying on entry authority". The live
trial's current exit path derives holding identity by cross-checking every
open capital lot against the committed pair decision records and refuses
otherwise (``paired_trial._seed_initial_holdings`` →
``seed_lot_identity_unresolved``): an entry-side dependency. This module is
the clause-⑤ construction material: exit obligations derived from the arm
ledger **alone** — open position rows plus their opening fill events — with
the frozen executable contract (T+1 open entry, T+10 open exit) supplying
the target exit session through a caller-injected authoritative schedule
slice.

Discipline (mirrors ``fence.py`` / ``replay_latch.py``):

- Pure read face. Derivation never writes, never opens a transaction, and
  never claims authority; it consumes quiet reads on the caller's repository
  (``capital_risk_snapshot`` convention) and leaves the ledger byte-identical.
- Derivation is a pure function of (current ledger state, injected schedule
  slices). There is no remembered derivation state, so crash recovery is
  re-derivation: two fresh reads of the same ledger produce equal
  obligations. Correction/bust reopening is inherited from ledger truth — a
  position row that re-enters ``OPEN`` re-enters the obligation set on the
  next derivation, never through derivation memory.
- The T+10 session formula is **not** forked here: the caller injects the
  frozen schedule slice for each entry settlement session (official wiring
  binds ``evidence.trading_schedule.derive_trading_schedule``, the single
  implementation, anchored at the calendar session immediately before the
  entry). The primitive validates the slice it receives — exactly
  ten following sessions, the first of which must be the entry settlement
  session — and takes the last as the target exit session.
- Cross-checking against pair-record identities is **advisory**: passing
  ``expectations=None`` derives obligations with no entry-side input at all
  (the clause-⑤ point). Supplying expectations turns divergences into typed
  breaches for disclosure — never auto-resolution, never silent adoption.
- The unconditional-exit limit (1 cent floor) is the frozen executable
  contract; the constant is declared here because this module must not
  import the orchestration layer. A test pins it equal to
  ``orchestration.session_driver.UNCONDITIONAL_EXIT_LIMIT_CENTS`` so the two
  spellings cannot drift.
- Nothing here touches the withdrawn mutation facades, any production read
  path, or any live trial root. This module is unreachable from production
  code until the owner-approved re-enable operation wires it in.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING, Final, Mapping, Protocol, Sequence, runtime_checkable

import sqlalchemy as sa

from src.screening.offensive.v3.contracts import CanonicalModel
from src.screening.offensive.v3.contracts.evidence import NonEmptyStr

if TYPE_CHECKING:
    from src.screening.offensive.v3.capital.repository import CapitalRepository

#: The T+10 exit is an unconditional open sell: the sell floor is 1 cent so
#: the limit is always touched and the fill executes at the open price.
#: Mirrors ``orchestration.session_driver.UNCONDITIONAL_EXIT_LIMIT_CENTS``
#: (pinned equal by test; this module must not import the orchestration
#: layer).
EXIT_LIMIT_PRICE_CENTS: Final = 1

#: Exactly ten sessions strictly after the frozen signal session (the
#: schedule slice contract). Validated on every injected slice so a malformed
#: caller cannot silently shift the exit session.
FOLLOWING_SESSION_COUNT: Final = 10

_OPEN_POSITION_STATES: Final = ("OPEN", "EXIT_PENDING")


class ExitLivenessError(RuntimeError):
    def __init__(self, code: str, message: str, **details: object) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.details = details


@runtime_checkable
class ScheduleSlice(Protocol):
    """The structural shape of a frozen trading-session schedule slice.

    Official wiring passes ``FrozenTradingSessionSchedule`` from
    ``evidence.trading_schedule`` (the single implementation of "exactly ten
    sessions strictly after the signal session"); tests may pass structural
    fakes of the same shape.
    """

    signal_session: date
    following_sessions: Sequence[date]


@runtime_checkable
class LedgerExitView(Protocol):
    """Quiet reads the derivation consumes; no writes, no version growth."""

    def open_position_rows(self) -> Sequence: ...

    def opening_event_for(self, event_id: str) -> tuple[str, str, str] | None:
        """(event_id, event_kind, effective_at ISO text) or None if absent."""
        ...


class ExitObligation(CanonicalModel):
    """One open capital lot's exit obligation, derived from ledger truth."""

    security_id: NonEmptyStr
    position_lineage_id: NonEmptyStr
    economic_lot_id: NonEmptyStr
    quantity_units: int
    opening_event_id: NonEmptyStr
    entry_settlement_session: date
    signal_session: date
    target_exit_session: date
    exit_limit_price_cents: int


class LineExpectation(CanonicalModel):
    """One pair-record line identity offered for advisory cross-checking."""

    economic_lot_id: NonEmptyStr
    security_id: NonEmptyStr
    quantity_units: int
    target_exit_session: date
    exit_limit_price_cents: int


def repository_exit_view(repository: "CapitalRepository") -> LedgerExitView:
    """Build the derivation's quiet reads on an open capital repository.

    Mirrors the ``ArmLedgerQuietReads`` convention: read-only connections,
    no stream/capital version growth, no transaction. Kept next to the
    derivation so the whole clause-⑤ face stays in one module.
    """

    class _View:
        def open_position_rows(self) -> Sequence:
            from src.screening.offensive.v3.capital.repository import (
                GatewayTransactionContext,
            )

            with repository.engine.connect() as conn:
                return tuple(
                    GatewayTransactionContext(repository, conn).open_position_rows()
                )

        def opening_event_for(self, event_id: str) -> tuple[str, str, str] | None:
            with repository.engine.connect() as conn:
                row = conn.execute(
                    sa.text(
                        "SELECT economic_event_id, event_kind, effective_at"
                        " FROM economic_events WHERE economic_event_id = :event_id"
                    ),
                    {"event_id": event_id},
                ).first()
            if row is None:
                return None
            return (str(row[0]), str(row[1]), str(row[2]))

    return _View()


def _fail(code: str, message: str, **details: object) -> ExitLivenessError:
    return ExitLivenessError(code, message, **details)


def _parse_effective_session(effective_at: str, event_id: str) -> date:
    try:
        moment = datetime.fromisoformat(effective_at.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise _fail(
            "exit_obligation_opening_event_invalid",
            "the opening event's effective_at is not a parseable timestamp",
            opening_event_id=event_id,
            effective_at=effective_at,
        ) from exc
    if moment.tzinfo is None:
        raise _fail(
            "exit_obligation_opening_event_invalid",
            "the opening event's effective_at is naive; a settlement session"
            " cannot be derived from an unzoned instant",
            opening_event_id=event_id,
        )
    return moment.date()


def _validated_slice(
    slice_for_entry: ScheduleSlice, entry_session: date
) -> tuple[date, date]:
    following = list(getattr(slice_for_entry, "following_sessions", None) or ())
    signal = getattr(slice_for_entry, "signal_session", None)
    if signal is None or not isinstance(signal, date):
        raise _fail(
            "exit_obligation_schedule_slice_invalid",
            "the injected schedule slice has no signal_session date",
        )
    if len(following) != FOLLOWING_SESSION_COUNT:
        raise _fail(
            "exit_obligation_schedule_slice_invalid",
            "the injected schedule slice does not carry exactly ten"
            " following sessions",
            signal_session=signal.isoformat(),
            following_count=len(following),
        )
    if any(not isinstance(d, date) for d in following):
        raise _fail(
            "exit_obligation_schedule_slice_invalid",
            "the injected schedule slice has non-date following sessions",
        )
    if sorted(following) != following or len(set(following)) != FOLLOWING_SESSION_COUNT:
        raise _fail(
            "exit_obligation_schedule_slice_invalid",
            "the injected schedule slice's following sessions are not"
            " strictly ordered",
        )
    if following[0] != entry_session:
        raise _fail(
            "exit_obligation_entry_session_mismatch",
            "the schedule slice's first following session is not the"
            " entry settlement session recorded in the ledger; the"
            " calendar and the capital truth disagree",
            entry_settlement_session=entry_session.isoformat(),
            slice_first_following_session=following[0].isoformat(),
            signal_session=signal.isoformat(),
        )
    return signal, following[-1]


def derive_exit_obligations(
    view: LedgerExitView,
    schedule_slice_for_entry,
) -> tuple[ExitObligation, ...]:
    """Derive every open lot's exit obligation from the ledger alone.

    ``schedule_slice_for_entry`` maps an entry settlement session to the
    frozen ``ScheduleSlice`` of that session's signal session (the official
    rule: the signal session is the calendar session immediately before the
    entry settlement session). It must consult only the authoritative
    calendar — never entry-side decision records — for the derivation to
    remain ledger-only. Passing a ``Callable[[date], ScheduleSlice]`` binds
    the official ``derive_trading_schedule``; a plain ``Mapping[date,
    ScheduleSlice]`` also works for hermetic callers.
    """

    def slice_for(entry_session: date) -> ScheduleSlice:
        source = schedule_slice_for_entry
        if (
            source is None
            or isinstance(source, (str, bytes))
            or not (callable(source) or hasattr(source, "__getitem__"))
        ):
            raise _fail(
                "exit_obligation_schedule_source_invalid",
                "the injected schedule source is not a slice factory,"
                " mapping, or callable; pass the official slice factory",
                entry_settlement_session=entry_session.isoformat(),
                source_type=type(source).__name__,
            )
        try:
            slice_ = (
                source[entry_session]
                if hasattr(source, "__getitem__")
                else source(entry_session)
            )
        except KeyError as exc:
            raise _fail(
                "exit_obligation_schedule_unavailable",
                "the injected schedule source has no slice for the entry"
                " settlement session",
                entry_settlement_session=entry_session.isoformat(),
            ) from exc
        if slice_ is None:
            raise _fail(
                "exit_obligation_schedule_unavailable",
                "the injected schedule source produced no slice for the"
                " entry settlement session",
                entry_settlement_session=entry_session.isoformat(),
            )
        return slice_

    obligations: list[ExitObligation] = []
    for row in view.open_position_rows():
        lineage = str(row.position_lineage_id)
        lot = str(row.economic_lot_id)
        security = str(row.security_id)
        state = str(getattr(row, "state", ""))
        if state not in _OPEN_POSITION_STATES:
            continue
        quantity = int(row.settled_quantity_units or 0)
        if quantity <= 0:
            raise _fail(
                "exit_obligation_quantity_invalid",
                "an open position row carries no settled quantity; its exit"
                " obligation cannot be established",
                position_lineage_id=lineage,
                economic_lot_id=lot,
                state=state,
                settled_quantity_units=int(row.settled_quantity_units or 0),
            )
        opening_event_id = str(row.opened_by_event_id or "")
        if not opening_event_id:
            raise _fail(
                "exit_obligation_opening_event_missing",
                "an open position row records no opening event; its entry"
                " settlement session cannot be established",
                position_lineage_id=lineage,
                economic_lot_id=lot,
            )
        event = view.opening_event_for(opening_event_id)
        if event is None:
            raise _fail(
                "exit_obligation_opening_event_missing",
                "the opening event recorded by an open position row is"
                " absent from the ledger",
                position_lineage_id=lineage,
                opening_event_id=opening_event_id,
            )
        event_id, event_kind, effective_at = event
        if event_kind != "TRADE_EXECUTED":
            raise _fail(
                "exit_obligation_opening_event_invalid",
                "the opening event of an open position row is not a"
                " TRADE_EXECUTED fill",
                opening_event_id=event_id,
                event_kind=event_kind,
            )
        entry_session = _parse_effective_session(effective_at, event_id)
        signal_session, exit_session = _validated_slice(
            slice_for(entry_session), entry_session
        )
        obligations.append(
            ExitObligation(
                security_id=security,
                position_lineage_id=lineage,
                economic_lot_id=lot,
                quantity_units=quantity,
                opening_event_id=event_id,
                entry_settlement_session=entry_session,
                signal_session=signal_session,
                target_exit_session=exit_session,
                exit_limit_price_cents=EXIT_LIMIT_PRICE_CENTS,
            )
        )
    obligations.sort(
        key=lambda o: (o.security_id, o.position_lineage_id, o.economic_lot_id)
    )
    return tuple(obligations)


def cross_check_exit_identity(
    obligations: tuple[ExitObligation, ...],
    expectations: Mapping[str, LineExpectation] | None,
) -> None:
    """Advisory cross-check against pair-record line identities.

    ``expectations`` maps ``position_lineage_id`` to the identity the
    committed decision records claim. ``None`` skips the check entirely —
    the derivation stands alone on ledger truth (the clause-⑤ point). A
    supplied mapping turns every divergence into a typed breach:
    - an open lot with no expectation → ``exit_obligation_expectation_missing``
      (capital fact without decision provenance — the mirror of the seed
      path's ``seed_lot_identity_unresolved``, disclosed instead of blocking);
    - any field divergence → ``exit_obligation_identity_breach`` with
      per-field attribution. Expectations without open lots (closed lots,
      no-fill lines) are normal and never a breach.
    """

    if expectations is None:
        return
    for obligation in obligations:
        expected = expectations.get(obligation.position_lineage_id)
        if expected is None:
            raise ExitLivenessError(
                "exit_obligation_expectation_missing",
                "an open capital lot has no committed line identity to"
                " cross-check against",
                position_lineage_id=obligation.position_lineage_id,
                economic_lot_id=obligation.economic_lot_id,
                security_id=obligation.security_id,
            )
        divergences: dict[str, dict[str, object]] = {}
        checks = (
            ("economic_lot_id", obligation.economic_lot_id, expected.economic_lot_id),
            ("security_id", obligation.security_id, expected.security_id),
            ("quantity_units", obligation.quantity_units, expected.quantity_units),
            (
                "target_exit_session",
                obligation.target_exit_session.isoformat(),
                expected.target_exit_session.isoformat(),
            ),
            (
                "exit_limit_price_cents",
                obligation.exit_limit_price_cents,
                expected.exit_limit_price_cents,
            ),
        )
        for field, derived, claimed in checks:
            if derived != claimed:
                divergences[field] = {"derived": derived, "claimed": claimed}
        if divergences:
            raise ExitLivenessError(
                "exit_obligation_identity_breach",
                "the ledger-derived exit obligation diverges from the"
                " committed line identity",
                position_lineage_id=obligation.position_lineage_id,
                divergences=divergences,
            )


__all__ = [
    "EXIT_LIMIT_PRICE_CENTS",
    "FOLLOWING_SESSION_COUNT",
    "ExitLivenessError",
    "ExitObligation",
    "LedgerExitView",
    "LineExpectation",
    "ScheduleSlice",
    "cross_check_exit_identity",
    "derive_exit_obligations",
    "repository_exit_view",
]
