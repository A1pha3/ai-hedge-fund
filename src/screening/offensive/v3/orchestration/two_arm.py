"""Deterministic two-arm orchestration — re-enable gate clause ⑥ primitive.

Clause 6 of the shadow-capital mutation withdrawal re-enable gate
(``docs/superpowers/migrations/2026-08-13-shadow-capital-mutation-withdrawal.md``)
requires "deterministic two-arm orchestration without pretending the two
databases form one transaction". The champion and challenger arms are two
physical SQLite ledgers (``orchestration.arm_layout``); nothing can make
writes across them one transaction, and any orchestration that behaves as if
they were — a joint commit, a silent partial retry, an implied ordering — is
exactly the pretense this clause forbids. This module is the clause-⑥
construction material, mirroring ``capital.fence`` / ``capital.replay_latch``
/ ``capital.exit_liveness``:

- ``ARM_DRIVE_ORDER`` is the canonical arm order (champion, then
  challenger). Nothing here reads clocks, dictionary iteration order, or the
  environment to sequence arms — the order is a named constant, and the
  plan digest pins it.
- ``derive_two_arm_plan`` is a pure function of durable inputs (the
  pair-derived per-arm entry lines and the frozen advance window). It
  canonicalizes the plan — sessions sorted, lines sorted by identity, arms
  in canonical order — and binds it with a content digest, so two
  derivations from the same truth are byte-identical and a divergent
  re-derivation is *detectable* instead of silently driving a different
  window.
- ``execute_two_arm_plan`` accepts **no repositories and no connections** —
  that is the structural non-cross-DB-transaction declaration: there is no
  surface to hand two arm databases into one call, so no caller can pretend
  this module commits them atomically. Each arm step runs through a
  caller-supplied arm-local callback that owns that arm's repository, fence
  ticket, and local transactions. A later-arm failure raises a typed
  partial-completion error disclosing which arms already committed durably;
  those writes are never rolled back here (there is no cross-arm
  transaction to roll back). Recovery is the same-window re-drive contract:
  re-derive the plan, assert it unchanged, re-drive — convergence is each
  arm's own idempotency (append-only ledger, first-observation valuation,
  replay latch), not orchestration memory.
- ``arm_drive_watermark`` derives one arm's durable per-session progress
  watermark from that arm's ledger alone — the latest session of an
  ``AS_OBSERVED`` NAV observation (both mark and liquid valuations land
  there). It is a quiet read: no orchestration state table, no version
  growth, crash recovery = re-derivation.
- ``assert_resume_plan`` is the resume contract: a retry must re-derive the
  identical plan; a divergent digest is a typed refusal, mirroring the
  replay-latch philosophy one level up (a different plan after a crash is
  an operator-visible conflict, never a silent re-scope).

Discipline: derivation and watermark never write, never open a write
transaction, and never claim authority. Nothing here touches the withdrawn
mutation facades, any live production read path, or any real trial root;
the module is unreachable from production code until the owner-approved
re-enable operation wires it in. Possessing a plan confers no authority
beyond the right to drive the two arms in canonical order through the
caller's own arm-local writers.
"""

from __future__ import annotations

import hashlib
import inspect
from datetime import date, datetime
from typing import TYPE_CHECKING, Any, Final, Mapping, Sequence

from pydantic import model_validator

from src.screening.offensive.v3.contracts import CanonicalModel
from src.screening.offensive.v3.contracts.evidence import NonEmptyStr
from src.screening.offensive.v3.contracts.trial import TrialArm

if TYPE_CHECKING:
    from src.screening.offensive.v3.capital.repository import CapitalRepository

#: The canonical arm drive order. Both arms are always planned and driven in
#: this order; the plan digest binds it so a reordered drive is detectable.
ARM_DRIVE_ORDER: Final = (TrialArm.CHAMPION, TrialArm.CHALLENGER)

#: Digest prefix of a plan fingerprint (sha256 over canonical plan bytes).
_DIGEST_PREFIX: Final = "sha256:"
_DIGEST_HEX_LENGTH: Final = 64


class TwoArmOrchestrationError(RuntimeError):
    def __init__(self, code: str, message: str, **details: object) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.details = details


class ArmEntryLine(CanonicalModel):
    """One arm's executable entry line, pinned for the advance window.

    Field-for-field the driver's ``OpenLine`` identity (kernel line is the
    authority for identity/quantity/limits); the plan freezes it so the
    digest binds exactly what was derived at plan time.
    """

    decision_id: NonEmptyStr
    security_id: NonEmptyStr
    quantity_units: int
    limit_price_cents: int
    position_lineage_id: NonEmptyStr
    economic_lot_id: NonEmptyStr

    @model_validator(mode="after")
    def validate_line(self) -> "ArmEntryLine":
        if self.quantity_units <= 0:
            raise ValueError("quantity_units must be positive")
        if self.limit_price_cents <= 0:
            raise ValueError("limit_price_cents must be positive")
        return self


class ArmSessionEntries(CanonicalModel):
    """One arm's entry lines settling at one session (non-empty, canonical)."""

    session: date
    lines: tuple[ArmEntryLine, ...]


class ArmAdvancePlan(CanonicalModel):
    """One arm's canonical share of the two-arm advance plan."""

    arm: TrialArm
    entries: tuple[ArmSessionEntries, ...]


class TwoArmAdvancePlan(CanonicalModel):
    """The canonical two-arm advance plan; digest-pinned and order-stable.

    Canonical form: ``arm_plans`` in ``ARM_DRIVE_ORDER``, each arm's entries
    sorted by session, each session's lines sorted by
    ``(decision_id, security_id, economic_lot_id)``. Per-line settlement
    order inside a session is the driver's idempotent-per-line business, not
    the plan's; canonical sorting makes the plan a pure function of content
    so nondeterministic caller accumulation can never hide behind it.
    """

    trial_id: NonEmptyStr
    window: tuple[date, ...]
    arm_plans: tuple[ArmAdvancePlan, ...]

    def plan_digest(self) -> str:
        return _DIGEST_PREFIX + hashlib.sha256(self.canonical_bytes()).hexdigest()


def _fail(code: str, message: str, **details: object) -> TwoArmOrchestrationError:
    return TwoArmOrchestrationError(code, message, **details)


def _validated_window(window: Sequence[date]) -> tuple[date, ...]:
    if not isinstance(window, Sequence) or isinstance(window, (str, bytes)):
        raise _fail(
            "two_arm_window_invalid",
            "the advance window must be a sequence of dates",
            window_type=type(window).__name__,
        )
    sessions = tuple(window)
    if not sessions:
        raise _fail(
            "two_arm_window_invalid",
            "the advance window must carry at least one session",
        )
    if any(not isinstance(s, date) for s in sessions):
        raise _fail(
            "two_arm_window_invalid",
            "every advance-window session must be a date",
        )
    if list(sessions) != sorted(sessions) or len(set(sessions)) != len(sessions):
        raise _fail(
            "two_arm_window_invalid",
            "the advance window must be strictly ordered without duplicates",
        )
    return sessions


def _canonical_entries(
    raw_entries: Mapping[Any, Sequence[Any]], arm: TrialArm
) -> tuple[ArmSessionEntries, ...]:
    if not isinstance(raw_entries, Mapping):
        raise _fail(
            "two_arm_entries_invalid",
            "an arm's entries must be a mapping of session to lines",
            arm=arm.value,
            entries_type=type(raw_entries).__name__,
        )
    sessions = sorted(raw_entries)
    canonical: list[ArmSessionEntries] = []
    for session in sessions:
        if not isinstance(session, date):
            raise _fail(
                "two_arm_entries_invalid",
                "every entry session must be a date",
                arm=arm.value,
                session=repr(session),
            )
        lines = raw_entries[session]
        if not isinstance(lines, Sequence) or isinstance(lines, (str, bytes)):
            raise _fail(
                "two_arm_entries_invalid",
                "a session's entry lines must be a sequence",
                arm=arm.value,
                session=session.isoformat(),
            )
        if not lines:
            raise _fail(
                "two_arm_entries_invalid",
                "a session's entry group is empty; drop the session instead",
                arm=arm.value,
                session=session.isoformat(),
            )
        seen: set[tuple[str, str]] = set()
        checked: list[ArmEntryLine] = []
        for line in lines:
            if not isinstance(line, ArmEntryLine):
                raise _fail(
                    "two_arm_line_invalid",
                    "an entry line is not an ArmEntryLine",
                    arm=arm.value,
                    session=session.isoformat(),
                    line_type=type(line).__name__,
                )
            key = (line.decision_id, line.security_id)
            if key in seen:
                raise _fail(
                    "two_arm_line_duplicate",
                    "one session carries the same decision line twice",
                    arm=arm.value,
                    session=session.isoformat(),
                    decision_id=line.decision_id,
                    security_id=line.security_id,
                )
            seen.add(key)
            checked.append(line)
        checked.sort(
            key=lambda line: (
                line.decision_id,
                line.security_id,
                line.economic_lot_id,
            )
        )
        canonical.append(ArmSessionEntries(session=session, lines=tuple(checked)))
    return tuple(canonical)


def derive_two_arm_plan(
    *,
    trial_id: str,
    window: Sequence[date],
    entries_by_arm: Mapping[TrialArm, Mapping[date, Sequence[ArmEntryLine]]],
) -> TwoArmAdvancePlan:
    """Derive the canonical two-arm plan from durable advance inputs.

    Pure function: same (trial, window, per-arm entries) → byte-identical
    plan and digest, regardless of mapping iteration order or caller
    accumulation order. Entry sessions outside the window are legal —
    pre-window historical entries are part of the arm's truth (the runner's
    coverage gate proves their settlement separately) — and are pinned by
    the digest like everything else.
    """
    if not isinstance(trial_id, str) or not trial_id.strip():
        raise _fail(
            "two_arm_trial_invalid",
            "the plan must bind a non-empty trial id",
        )
    sessions = _validated_window(window)
    if not isinstance(entries_by_arm, Mapping):
        raise _fail(
            "two_arm_arms_invalid",
            "entries_by_arm must map each canonical arm to its entries",
            entries_type=type(entries_by_arm).__name__,
        )
    keys = set(entries_by_arm)
    expected = set(ARM_DRIVE_ORDER)
    if keys != expected:
        raise _fail(
            "two_arm_arms_invalid",
            "entries_by_arm must carry exactly the canonical arms",
            missing=sorted(
                str(getattr(a, "value", a)) for a in expected - keys
            ),
            unexpected=sorted(
                str(getattr(a, "value", a)) for a in keys - expected
            ),
        )
    arm_plans = tuple(
        ArmAdvancePlan(
            arm=arm,
            entries=_canonical_entries(entries_by_arm[arm], arm),
        )
        for arm in ARM_DRIVE_ORDER
    )
    return TwoArmAdvancePlan(
        trial_id=trial_id, window=sessions, arm_plans=arm_plans
    )


def execute_two_arm_plan(
    plan: TwoArmAdvancePlan, *, drive_arm
) -> "TwoArmDriveReceipt":
    """Drive both arms in canonical order through arm-local callbacks.

    The signature is the non-cross-DB-transaction declaration: this module
    receives no repositories, connections, or transactions — only one
    arm-local callback per canonical arm step, invoked exactly once, in
    ``ARM_DRIVE_ORDER``. The callback owns everything local to its arm
    (repository, fence ticket, replay-latch consumption, local commits).

    Failure semantics: the first failure raises a typed error that
    discloses the arms already completed — their durable writes stand
    (nothing cross-arm is ever rolled back here), and the original
    exception rides as ``__cause__``. Retry = re-derive, ``assert_resume_plan``
    against the original digest, re-drive; the completed arm converges by
    its own idempotency.
    """
    if not isinstance(plan, TwoArmAdvancePlan):
        raise _fail(
            "two_arm_plan_invalid",
            "execute expects a TwoArmAdvancePlan",
            plan_type=type(plan).__name__,
        )
    if not callable(drive_arm):
        raise _fail(
            "two_arm_drive_invalid",
            "drive_arm must be a callable invoked once per canonical arm",
            drive_type=type(drive_arm).__name__,
        )
    outcomes: list[tuple[TrialArm, Any]] = []
    completed: list[TrialArm] = []
    for arm in ARM_DRIVE_ORDER:
        try:
            outcome = drive_arm(arm)
        except Exception as exc:
            partial = bool(completed)
            raise _fail(
                "two_arm_drive_partial" if partial else "two_arm_drive_failed",
                "an arm drive failed; completed arms keep their durable"
                " writes and resume is the same-window re-drive",
                failed_arm=arm.value,
                completed_arms=[a.value for a in completed],
                plan_digest=plan.plan_digest(),
                **(
                    {"completed_outcomes": tuple(outcomes)}
                    if partial
                    else {}
                ),
            ) from exc
        outcomes.append((arm, outcome))
        completed.append(arm)
    return TwoArmDriveReceipt(
        plan_digest=plan.plan_digest(), outcomes=tuple(outcomes)
    )


def assert_drive_surface_is_arm_local() -> None:
    """Guard the structural declaration: no shared-transaction surface.

    Pins that ``execute_two_arm_plan``'s only inputs are the plan and the
    per-arm callback — there is no parameter a caller could use to hand both
    arm databases into one atomic pretense. The future re-enable wiring
    inherits this shape; a signature drift is a clause-⑥ regression.
    """
    parameters = set(inspect.signature(execute_two_arm_plan).parameters)
    if parameters != {"plan", "drive_arm"}:
        raise _fail(
            "two_arm_surface_drift",
            "execute_two_arm_plan must expose only the plan and the"
            " arm-local callback; a repository or connection parameter"
            " would invite a cross-database transaction pretense",
            parameters=sorted(parameters),
        )


class TwoArmDriveReceipt:
    """Canonical-order record of one two-arm drive (plain frozen value)."""

    __slots__ = ("plan_digest", "outcomes")

    def __init__(
        self,
        *,
        plan_digest: str,
        outcomes: tuple[tuple[TrialArm, Any], ...],
    ) -> None:
        self.plan_digest = plan_digest
        self.outcomes = outcomes

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, TwoArmDriveReceipt):
            return NotImplemented
        return (
            self.plan_digest == other.plan_digest
            and self.outcomes == other.outcomes
        )

    def __repr__(self) -> str:
        arms = [arm.value for arm, _ in self.outcomes]
        return (
            f"TwoArmDriveReceipt(plan_digest={self.plan_digest!r},"
            f" arms={arms!r})"
        )


def assert_resume_plan(
    previous_digest: str, current: TwoArmAdvancePlan
) -> None:
    """Resume contract: a retry must re-derive the identical plan.

    A crash between arm steps leaves a mixed state; the official recovery is
    the same-window re-drive. This guard refuses a re-derived plan whose
    digest differs from the one the original drive started with — a
    different window or different lines after a crash is a conflict to
    disclose (``two_arm_plan_divergence``), never a silent re-scope.
    """
    if (
        not isinstance(previous_digest, str)
        or not previous_digest.startswith(_DIGEST_PREFIX)
        or len(previous_digest) != len(_DIGEST_PREFIX) + _DIGEST_HEX_LENGTH
        or any(
            c not in "0123456789abcdef"
            for c in previous_digest[len(_DIGEST_PREFIX):]
        )
    ):
        raise _fail(
            "two_arm_plan_digest_invalid",
            "the previous plan digest is not a sha256 digest",
            previous_digest=previous_digest,
        )
    if not isinstance(current, TwoArmAdvancePlan):
        raise _fail(
            "two_arm_plan_invalid",
            "resume expects a TwoArmAdvancePlan",
            plan_type=type(current).__name__,
        )
    derived = current.plan_digest()
    if derived != previous_digest:
        raise _fail(
            "two_arm_plan_divergence",
            "the re-derived plan differs from the plan the original drive"
            " started with; a crash resume must re-drive the same window",
            previous_digest=previous_digest,
            rederived_digest=derived,
        )


def _parse_observation_session(as_of_text: str) -> date:
    try:
        moment = datetime.fromisoformat(str(as_of_text).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise _fail(
            "two_arm_watermark_invalid",
            "a NAV observation carries an unparseable as_of timestamp",
            as_of=str(as_of_text),
        ) from exc
    if moment.tzinfo is None:
        raise _fail(
            "two_arm_watermark_invalid",
            "a NAV observation carries a naive as_of; a progress watermark"
            " cannot be derived from an unzoned instant",
            as_of=str(as_of_text),
        )
    return moment.date()


def arm_drive_watermark(repository: "CapitalRepository") -> date | None:
    """One arm's durable per-session progress watermark, from its ledger.

    The latest session of an ``AS_OBSERVED`` NAV observation in this arm's
    ledger — the per-session close valuation the lifecycle driver records at
    every driven session (mark or liquid), so the watermark advances exactly
    when a session's lifecycle pass has durably completed. Quiet read on a
    read-only connection: no writes, no version growth, no orchestration
    state table; crash recovery = re-derivation. ``None`` means the ledger
    has never observed a session.
    """
    import sqlalchemy as sa

    with repository.engine.connect() as conn:
        rows = conn.execute(
            sa.text(
                "SELECT as_of FROM nav_observations"
                " WHERE observation_kind = 'AS_OBSERVED'"
            )
        ).fetchall()
    sessions = [_parse_observation_session(row[0]) for row in rows]
    return max(sessions) if sessions else None


__all__ = [
    "ARM_DRIVE_ORDER",
    "ArmAdvancePlan",
    "ArmEntryLine",
    "ArmSessionEntries",
    "TwoArmAdvancePlan",
    "TwoArmDriveReceipt",
    "TwoArmOrchestrationError",
    "arm_drive_watermark",
    "assert_drive_surface_is_arm_local",
    "assert_resume_plan",
    "derive_two_arm_plan",
    "execute_two_arm_plan",
]
