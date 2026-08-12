"""Thin operator CLI for the BTST regime paired-trial primitives.

Four subcommands over one on-disk Trial root:

- ``validate``        — read-only: load the sealed governance bundle, the
  equal-genesis manifest, the session spine, and verify they are mutually
  consistent. This is the only currently usable command; it strictly does
  not write.
- ``decide-session``  — reserved entrypoint that fails closed until the real
  producer input and independent per-arm capital context are wired.
- ``advance-session`` — reserved entrypoint that fails closed until the
  exchange-calendar, cutoff, bar, mark, corporate-action, and lot-lifecycle
  context is wired.
- ``assess``          — reserved entrypoint that fails closed without real
  replay, per-arm capital, and evidence-consumption inputs. It writes no
  output while those inputs are unavailable.

Security boundary (pinned by ``test_v3_regime_trial_cli`` +
``test_regime_trial_import_boundary``):

- the root must resolve to a real directory; path-traversal roots and
  symlink roots reject before anything is loaded;
- the CLI recognizes NO policy / regime / cap / mode / evidence-cutoff
  override flags and reads NO environment switches — those frozen values
  come only from the sealed artifacts;
- the CLI never auto-creates or auto-seals a Trial;
- the module imports only the trial-path surface (runner, replay engine,
  proxy adapter, lifecycle, decision store, genesis, evaluator); it never
  reaches broker, gateway authority/decisions, activation, outbox, or
  ``shadow_trust``.

Execution boundary: only ``validate`` is self-contained over the sealed
artifacts. ``decide-session``, ``advance-session``, and ``assess`` first load
and verify the sealed registration, then fail closed because their required
operational inputs are not connected to this standalone CLI. The Task 11–13
runner, replay, and evaluator primitives and tests do not make an official
Trial executable or evaluable by themselves.
"""

from __future__ import annotations

import argparse
import hashlib
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable

#: The fixed on-disk layout of one Trial root. The CLI consumes (never
#: creates) this layout; a separate sealing flow populates it.
_LAYOUT_FILES: tuple[str, ...] = (
    "decisions.sqlite3",
    "spine.sqlite3",
    "evidence.sqlite3",
)
_LAYOUT_DIRS: tuple[str, ...] = ("archive", "blobs")


class RegimeTrialCliError(RuntimeError):
    """Fail-closed rejection of a CLI operation (bad root, missing artifact,
    unsealed trial, or unavailable operational inputs). Never swallowed by
    ``main``."""

    def __init__(self, code: str, message: str, **details: object) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.details = details


def _wall_clock() -> datetime:
    return datetime.now(timezone.utc)


def _resolve_trial_root(root: str | Path) -> Path:
    """Resolve a Trial root, rejecting traversal / symlink / missing roots.

    The root must name a real directory whose path contains no ``..``
    segment and is not itself a symlink. Resolution is absolute so the
    rest of the CLI is immune to the caller's cwd.
    """

    path = Path(root)
    # Path-traversal roots reject before anything is touched. A Trial root
    # is always an explicit directory; a ``..`` segment is an attempt to
    # escape the intended location.
    if ".." in path.parts:
        raise RegimeTrialCliError(
            "root_path_traversal",
            "a Trial root must not contain a '..' path segment",
            root=str(root),
        )
    # A symlinked root can be silently repointed; a real Trial root is a
    # real directory.
    if path.is_symlink():
        raise RegimeTrialCliError(
            "root_symlink_rejected",
            "a Trial root must be a real directory, not a symlink",
            root=str(root),
        )
    if not path.is_dir():
        raise RegimeTrialCliError(
            "root_not_found",
            "a Trial root must be an existing directory",
            root=str(root),
        )
    return path.resolve()


def _require_layout(root: Path) -> None:
    """Every layout file/dir must exist before any artifact is loaded."""

    missing: list[str] = []
    for name in _LAYOUT_FILES:
        if not (root / name).is_file():
            missing.append(name)
    for name in _LAYOUT_DIRS:
        if not (root / name).is_dir():
            missing.append(name + "/")
    if missing:
        raise RegimeTrialCliError(
            "trial_root_not_sealed",
            "the Trial root is missing sealed layout artifacts",
            root=str(root),
            missing=missing,
        )


@dataclass(frozen=True)
class _SealedTrial:
    """The verified read-only handle shared by all four commands."""

    root: Path
    trial_id: str
    store: object
    bundle: object
    genesis_manifest: object
    spine: object
    trusted_at: datetime


@dataclass(frozen=True)
class _ReadOnlySqlite:
    """A path marker proving the CLI did not construct a writer repository."""

    database_path: Path


def _connect_immutable(database_path: Path) -> sqlite3.Connection:
    """Open a sealed SQLite artifact without journals, sidecars, or migrations."""

    return sqlite3.connect(
        f"{database_path.resolve().as_uri()}?mode=ro&immutable=1",
        uri=True,
    )


def _load_sealed_trial(
    root: str | Path, trial_id: str, *, clock: Callable[[], datetime] | None
) -> _SealedTrial:
    """Resolve and verify the sealed registration without physical writes.

    Both SQLite artifacts open as ``mode=ro&immutable=1``; repository
    constructors are deliberately forbidden here because they initialize
    schemas and WAL sidecars. One trusted time is frozen for governance and
    writer checks. Governance semantics, complete genesis equality/bindings,
    content roots, research-program enrollment, and the current writer lease
    must all verify or every command fails closed.
    """

    resolved = _resolve_trial_root(root)
    _require_layout(resolved)
    clk = clock if clock is not None else _wall_clock
    trusted_at = clk()
    decisions_path = resolved / "decisions.sqlite3"
    spine_path = resolved / "spine.sqlite3"
    try:
        bundle, genesis_manifest = _read_registration(decisions_path, trial_id)
        _validate_governance_bundle(bundle, trusted_at)
        _validate_live_writer(decisions_path, trusted_at)
        archived = _read_archive_manifest(resolved, trial_id)
        _validate_genesis_binding(
            root=resolved,
            trial_id=trial_id,
            bundle=bundle,
            registered=genesis_manifest,
            archived=archived,
        )
        _validate_spine(spine_path, bundle)
    except RegimeTrialCliError:
        raise
    except Exception as exc:
        raise RegimeTrialCliError(
            "validation_evidence_unavailable",
            "the sealed Trial artifacts could not be verified read-only",
            trial_id=trial_id,
            reason=str(exc),
        ) from exc
    return _SealedTrial(
        root=resolved,
        trial_id=trial_id,
        store=_ReadOnlySqlite(decisions_path),
        bundle=bundle,
        genesis_manifest=genesis_manifest,
        spine=_ReadOnlySqlite(spine_path),
        trusted_at=trusted_at,
    )


def _read_registration(
    database_path: Path, trial_id: str
) -> tuple[object, object]:
    """Read the sealed (bundle, genesis_manifest) for one trial from the store."""

    conn = _connect_immutable(database_path)
    try:
        try:
            row = conn.execute(
                "SELECT bundle_json, genesis_manifest_json"
                " FROM trial_registrations WHERE trial_id = :trial_id",
                {"trial_id": trial_id},
            ).fetchone()
        except sqlite3.DatabaseError as exc:
            raise RegimeTrialCliError(
                "trial_registration_unreadable",
                "the immutable decision store has no readable registration",
                trial_id=trial_id,
                reason=str(exc),
            ) from exc
    finally:
        conn.close()
    if row is None:
        raise RegimeTrialCliError(
            "trial_not_registered",
            "the trial is not registered in the decision store",
            trial_id=trial_id,
        )
    from src.screening.offensive.v3.governance.regime_trial import (
        RegimeTrialBundle,
    )
    from src.screening.offensive.v3.orchestration.genesis import (
        TrialGenesisManifest,
    )

    return (
        RegimeTrialBundle.model_validate_json(row[0], strict=True),
        TrialGenesisManifest.model_validate_json(row[1], strict=True),
    )


def _validate_governance_bundle(bundle: object, trusted_at: datetime) -> None:
    from src.screening.offensive.v3.governance.regime_trial import (
        validate_regime_trial_bundle,
    )

    try:
        validate_regime_trial_bundle(bundle, trusted_at=trusted_at)
    except Exception as exc:
        raise RegimeTrialCliError(
            "governance_bundle_invalid",
            "the registered governance bundle failed semantic validation",
            reason=str(exc),
        ) from exc


def _validate_live_writer(database_path: Path, _trusted_at: datetime) -> None:
    conn = _connect_immutable(database_path)
    try:
        row = conn.execute(
            "SELECT s.epoch, s.owner_id, l.epoch, l.expires_at"
            " FROM trial_writer_state s"
            " LEFT JOIN trial_writer_leases l ON l.writer_id = s.owner_id"
            " WHERE s.id = 1"
        ).fetchone()
    finally:
        conn.close()
    if row is None or row[1] is None or row[2] is None:
        raise RegimeTrialCliError(
            "writer_lease_unavailable",
            "the Trial has no current writer lease",
        )
    try:
        datetime.fromisoformat(row[3])
    except (TypeError, ValueError) as exc:
        raise RegimeTrialCliError(
            "writer_lease_unavailable",
            "the current writer lease has an invalid expiry",
        ) from exc
    # The current writer contract treats presence of the current owner/epoch
    # row as liveness; ``expires_at`` is validated structurally but is not a
    # wall-clock TTL in ``TrialArmDecisionStore.require_writer``.
    if int(row[0]) != int(row[2]):
        raise RegimeTrialCliError(
            "writer_lease_unavailable",
            "the current writer lease epoch disagrees with writer state",
        )


def _read_archive_manifest(root: Path, trial_id: str) -> object:
    from src.screening.offensive.v3.orchestration.genesis import (
        TrialGenesisManifest,
    )

    manifest_path = root / "archive" / trial_id / "genesis-manifest.json"
    if not manifest_path.is_file() or manifest_path.is_symlink():
        raise RegimeTrialCliError(
            "genesis_not_sealed",
            "the genesis archive holds no real manifest for this trial",
            trial_id=trial_id,
        )
    try:
        return TrialGenesisManifest.model_validate_json(
            manifest_path.read_text(encoding="utf-8"), strict=True
        )
    except Exception as exc:
        raise RegimeTrialCliError(
            "genesis_not_sealed",
            "the genesis archive manifest is unreadable",
            trial_id=trial_id,
            reason=str(exc),
        ) from exc


def _validate_content_root(path: Path, expected: str, label: str) -> None:
    if not path.is_file() or path.is_symlink():
        raise RegimeTrialCliError(
            "genesis_archive_incomplete",
            f"the sealed {label} artifact is missing or symlinked",
        )
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual != expected:
        raise RegimeTrialCliError(
            "genesis_content_root_mismatch",
            f"the sealed {label} artifact no longer matches its content root",
        )


def _validate_genesis_binding(
    *,
    root: Path,
    trial_id: str,
    bundle: object,
    registered: object,
    archived: object,
) -> None:
    if archived != registered:
        raise RegimeTrialCliError(
            "genesis_manifest_drift",
            "the registered and archived genesis manifests differ",
            trial_id=trial_id,
        )
    trial = bundle.trial_manifest
    sap = bundle.sap_manifest
    if (
        registered.trial_id != trial_id
        or registered.normalized_genesis_hash
        != registered.champion_normalized_hash
        or registered.normalized_genesis_hash
        != registered.challenger_normalized_hash
        or registered.trial_manifest_hash != trial.artifact_hash()
        or registered.sap_manifest_hash != sap.artifact_hash()
    ):
        raise RegimeTrialCliError(
            "genesis_binding_invalid",
            "the genesis manifest does not exactly bind this Trial and SAP",
            trial_id=trial_id,
        )
    archive = root / "archive" / trial_id
    _validate_content_root(
        archive / registered.champion_backup_root / "capital.sqlite3",
        registered.champion_backup_root,
        "Champion capital backup",
    )
    _validate_content_root(
        archive / registered.challenger_backup_root / "capital.sqlite3",
        registered.challenger_backup_root,
        "Challenger capital backup",
    )
    for field, filename, label in (
        ("champion_exit_lane_root", "exit-lane-champion.sqlite3", "Champion exit lane"),
        ("challenger_exit_lane_root", "exit-lane-challenger.sqlite3", "Challenger exit lane"),
        ("champion_proxy_root", "proxy-champion.sqlite3", "Champion proxy state"),
        ("challenger_proxy_root", "proxy-challenger.sqlite3", "Challenger proxy state"),
    ):
        expected = getattr(registered, field)
        if expected is not None:
            _validate_content_root(archive / filename, expected, label)


def _validate_spine(database_path: Path, bundle: object) -> None:
    trial = bundle.trial_manifest
    conn = _connect_immutable(database_path)
    try:
        rows = conn.execute(
            "SELECT signal_session, assessment_date FROM expected_sessions"
            " WHERE research_program_id = :program ORDER BY signal_session",
            {"program": trial.research_program_id},
        ).fetchall()
    finally:
        conn.close()
    if not rows:
        raise RegimeTrialCliError(
            "spine_program_not_enrolled",
            "the SessionSpine has no enrollment for this research program",
            research_program_id=trial.research_program_id,
        )
    start = trial.enrollment_start.date()
    end = trial.enrollment_end.date()
    fixed_assessment = trial.fixed_assessment_date.date()
    for signal_text, assessment_text in rows:
        try:
            signal = date.fromisoformat(signal_text)
            assessment = date.fromisoformat(assessment_text)
        except (TypeError, ValueError) as exc:
            raise RegimeTrialCliError(
                "spine_binding_invalid",
                "the SessionSpine contains a malformed enrollment",
            ) from exc
        if not (start <= signal < end) or not (
            signal <= assessment <= fixed_assessment
        ):
            raise RegimeTrialCliError(
                "spine_binding_invalid",
                "the SessionSpine enrollment lies outside the sealed Trial dates",
                signal_session=signal_text,
            )


def validate_trial(
    *, root: str | Path, trial_id: str, clock: Callable[[], datetime] | None = None
) -> int:
    """Read-only validation of the sealed Trial artifacts. Never writes."""

    _load_sealed_trial(root, trial_id, clock=clock)
    return 0


def decide_session(
    *,
    root: str | Path,
    trial_id: str,
    signal_session: date,
    clock: Callable[[], datetime] | None = None,
) -> int:
    """Fail closed until the forward runner's operational inputs are wired.

    The sealed Trial is verified read-only first. The standalone process has
    no producer trust chain or independent per-arm PIT capital context, so it
    rejects rather than claiming to delegate work it cannot perform.
    """

    sealed = _load_sealed_trial(root, trial_id, clock=clock)
    raise RegimeTrialCliError(
        "privileged_context_required",
        "decide-session delegates to the ForwardPairedTrialRunner, whose producer"
        " trust chain and PIT capital baseline the privileged worker (Plan 06+)"
        " injects; the standalone CLI cannot synthesize them from the sealed root"
        " without crossing the shadow_trust boundary",
        trial_id=sealed.trial_id,
        signal_session=signal_session.isoformat(),
    )


def advance_market_session(
    *,
    root: str | Path,
    trial_id: str,
    market_session: date,
    clock: Callable[[], datetime] | None = None,
) -> int:
    """Fail closed until the replay lifecycle inputs are wired.

    The sealed Trial is verified read-only first. Constructing the full
    replay input (bars, marks, snapshot evidence, calendar and corporate
    actions) is the future operational driver's responsibility.
    """

    sealed = _load_sealed_trial(root, trial_id, clock=clock)
    raise RegimeTrialCliError(
        "privileged_context_required",
        "advance-session delegates to the Task 12 replay engine, whose"
        " TrialReplayInput (bars, marks, snapshot evidence) the operational"
        " replay driver assembles; the standalone CLI cannot invent market"
        " facts from the sealed root",
        trial_id=sealed.trial_id,
        market_session=market_session.isoformat(),
    )


def assess_trial(
    *,
    root: str | Path,
    trial_id: str,
    output: str | Path,
    clock: Callable[[], datetime] | None = None,
) -> int:
    """Fail closed until the real assessment inputs are operationally wired.

    A sealed Trial registration is insufficient to derive replay, per-arm
    capital, and evidence-consumption hashes or their eligibility gates.
    Placeholder hashes and all-false gates would be a fabricated assessment,
    so this command creates no output while those inputs are unavailable.
    """

    sealed = _load_sealed_trial(root, trial_id, clock=clock)
    raise RegimeTrialCliError(
        "assessment_inputs_unavailable",
        "assess requires official current and stress replay outputs, independent"
        " per-arm capital reports, and the evidence-consumption ledger; the"
        " standalone CLI cannot derive those facts from the sealed registration",
        trial_id=sealed.trial_id,
        output=str(output),
    )


# ---------------------------------------------------------------------------
# argparse dispatcher
# ---------------------------------------------------------------------------


def _iso_date(value: str) -> date:
    return date.fromisoformat(value)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="v3_regime_trial",
        description=(
            "Operator CLI for the BTST regime paired shadow trial. All"
            " policy/regime/cap/mode values come from the sealed Trial"
            " artifacts under --root; no override flags or environment"
            " switches are recognized."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_validate = sub.add_parser(
        "validate", help="read-only check of the sealed Trial artifacts"
    )
    p_validate.add_argument("--root", required=True)
    p_validate.add_argument("--trial-id", required=True, dest="trial_id")

    p_decide = sub.add_parser(
        "decide-session",
        help="unavailable: requires wired producer and per-arm capital context",
    )
    p_decide.add_argument("--root", required=True)
    p_decide.add_argument("--trial-id", required=True, dest="trial_id")
    p_decide.add_argument(
        "--signal-session", required=True, type=_iso_date, dest="signal_session"
    )

    p_advance = sub.add_parser(
        "advance-session",
        help="unavailable: requires wired market and lot-lifecycle context",
    )
    p_advance.add_argument("--root", required=True)
    p_advance.add_argument("--trial-id", required=True, dest="trial_id")
    p_advance.add_argument(
        "--market-session", required=True, type=_iso_date, dest="market_session"
    )

    p_assess = sub.add_parser(
        "assess",
        help="unavailable: requires replay, capital, and consumption inputs",
    )
    p_assess.add_argument("--root", required=True)
    p_assess.add_argument("--trial-id", required=True, dest="trial_id")
    p_assess.add_argument("--output", required=True)

    return parser


def main(argv: list[str] | None = None) -> int:
    """Dispatch one CLI subcommand. Returns a process exit code."""

    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        # argparse exits 2 on a usage error (unknown subcommand or flag);
        # surface it as a non-zero return code instead of killing the process.
        return int(exc.code) if isinstance(exc.code, int) else 2
    root = _resolve_trial_root(args.root)
    if args.command == "validate":
        return validate_trial(root=root, trial_id=args.trial_id)
    if args.command == "decide-session":
        return decide_session(
            root=root, trial_id=args.trial_id, signal_session=args.signal_session
        )
    if args.command == "advance-session":
        return advance_market_session(
            root=root, trial_id=args.trial_id, market_session=args.market_session
        )
    if args.command == "assess":
        return assess_trial(root=root, trial_id=args.trial_id, output=args.output)
    return 2


__all__ = [
    "RegimeTrialCliError",
    "advance_market_session",
    "assess_trial",
    "decide_session",
    "main",
    "validate_trial",
]
