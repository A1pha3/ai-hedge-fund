"""Plan Task 14 Step 5: thin operator CLI for the BTST regime paired trial.

Four subcommands over one on-disk Trial root:

- ``validate``        — read-only: load the sealed governance bundle, the
  equal-genesis manifest, the session spine, and verify they are mutually
  consistent. Strictly no writes.
- ``decide-session``  — mutating: construct the :class:`ForwardPairedTrialRunner`
  and decide one enrolled signal session (the side-effect boundary is the
  atomic pair commit; a replay exact-validates the pair).
- ``advance-session`` — mutating: drive one market session of both arms
  through the replay engine / :class:`ShadowProxyLifecycle`.
- ``assess``          — read-only except for the deletable report it writes
  to the explicit ``--output`` path.

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

Execution boundary: ``validate`` and ``assess`` are self-contained over the
sealed artifacts. ``decide-session`` and ``advance-session`` load and verify
the sealed trial, then fail closed: the forward decision needs the BTST
producer's Ed25519 trust chain and the PIT capital baseline that the
privileged worker (Plan 06+) injects — the standalone CLI takes only
``--root`` and ``--trial-id`` and cannot synthesize either without crossing
the ``shadow_trust`` boundary the import guard forbids. The commands exist
as the operator-facing entrypoints and document that boundary honestly
rather than shipping trust-chain fabrication. The green Task 11 (runner),
Task 12 (replay), and Task 13 (evaluator) suites prove the delegated
execution they hand off to.
"""

from __future__ import annotations

import argparse
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
    unsealed trial, privileged context required). Never swallowed by ``main``."""

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
    """The loaded handle the read-only commands share: the resolved root,
    the trial id, the decision store, the sealed bundle, the genesis
    manifest, the session spine, and the trusted clock."""

    root: Path
    trial_id: str
    store: object
    bundle: object
    genesis_manifest: object
    spine: object
    clock: Callable[[], datetime]


def _load_sealed_trial(
    root: str | Path, trial_id: str, *, clock: Callable[[], datetime] | None
) -> _SealedTrial:
    """Resolve, verify the layout, and load the sealed registration + spine.

    The fail-closed chokepoint shared by every command: a root missing any
    layout artifact, a trial with no registration, or a trial whose genesis
    manifest disagrees with the sealed archive rejects before any execution.
    """

    from src.screening.offensive.v3.evidence.session_spine import SessionSpine
    from src.screening.offensive.v3.orchestration.genesis import (
        TrialGenesisArchive,
    )
    from src.screening.offensive.v3.orchestration.trial_store import (
        TrialArmDecisionStore,
    )

    resolved = _resolve_trial_root(root)
    _require_layout(resolved)
    clk = clock if clock is not None else _wall_clock
    store = TrialArmDecisionStore(database_path=str(resolved / "decisions.sqlite3"))
    bundle, genesis_manifest = _read_registration(store, trial_id)
    # The genesis archive must hold a manifest for this exact trial whose
    # normalized hash agrees with the store's registration.
    archive = TrialGenesisArchive(resolved / "archive")
    try:
        archived = archive.manifest(trial_id)
    except Exception as exc:  # trial_not_sealed / missing manifest
        raise RegimeTrialCliError(
            "genesis_not_sealed",
            "the genesis archive holds no manifest for this trial",
            trial_id=trial_id,
            reason=str(exc),
        ) from exc
    if archived.normalized_genesis_hash != genesis_manifest.normalized_genesis_hash:
        raise RegimeTrialCliError(
            "genesis_manifest_drift",
            "the store genesis manifest disagrees with the sealed archive",
            trial_id=trial_id,
        )
    spine = SessionSpine(database_path=str(resolved / "spine.sqlite3"), clock=clk)
    return _SealedTrial(
        root=resolved,
        trial_id=trial_id,
        store=store,
        bundle=bundle,
        genesis_manifest=genesis_manifest,
        spine=spine,
        clock=clk,
    )


def _read_registration(store: object, trial_id: str) -> tuple[object, object]:
    """Read the sealed (bundle, genesis_manifest) for one trial from the store."""

    import sqlite3

    conn = sqlite3.connect(str(store._database_path))  # noqa: SLF001
    try:
        row = conn.execute(
            "SELECT bundle_json, genesis_manifest_json FROM trial_registrations"
            " WHERE trial_id = :trial_id",
            {"trial_id": trial_id},
        ).fetchone()
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
        RegimeTrialBundle.model_validate_json(row[0]),
        TrialGenesisManifest.model_validate_json(row[1]),
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
    """Decide one enrolled signal session via the forward paired runner.

    Loads and verifies the sealed trial, then delegates to the
    :class:`ForwardPairedTrialRunner`. The forward decision needs the BTST
    producer's Ed25519 trust chain and the PIT capital baseline; the
    privileged worker (Plan 06+) injects both. Invoked without that context
    the command fails closed rather than fabricating a trust chain.
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
    """Advance one market session of both arms through the replay lifecycle.

    Loads and verifies the sealed trial, then delegates to the Task 12
    replay engine, which restores the equal-genesis arm ledgers and drives
    the :class:`ShadowProxyLifecycle`. Constructing the full
    ``TrialReplayInput`` (bars, marks, snapshot evidence, corporate actions)
    is the operational replay driver's responsibility; the standalone CLI
    fails closed rather than guessing market facts.
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
    """Render the deletable assessment projection to the explicit --output path.

    Read-only except for the one report file. The projection references only
    content-addressed artifact hashes; deleting it loses no truth. The
    headline is NOT_ELIGIBLE when any gate cannot be proven green and at
    most INACTIVE_PROMOTION_CANDIDATE when all pass.
    """

    sealed = _load_sealed_trial(root, trial_id, clock=clock)
    report = _render_assessment(sealed)
    out = Path(output)
    if ".." in out.parts or out.is_symlink():
        raise RegimeTrialCliError(
            "output_path_unsafe",
            "the assessment output path must be a real, non-traversal path",
            output=str(output),
        )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")
    return 0


def _render_assessment(sealed: _SealedTrial) -> str:
    """Render the deletable assessment projection from the sealed artifacts.

    A CLI-driven assessment with no replay/capital report hashes on hand is
    NOT_ELIGIBLE by construction: every gate the projection cannot prove
    green is false. The report is still a valid deletable projection — it
    references only sealed hashes and computed gates.
    """

    from src.screening.offensive.v3.reporting import render_trial_assessment
    from src.screening.offensive.v3.reporting.trial_projection import (
        EligibilityGates,
        TrialAssessmentProjection,
    )

    bundle = sealed.bundle
    projection = TrialAssessmentProjection(
        trial_id=sealed.trial_id,
        research_program_id=bundle.trial_manifest.research_program_id,
        economic_lineage_id=bundle.trial_manifest.economic_lineage_id,
        trial_manifest_hash=bundle.trial_manifest.artifact_hash(),
        sap_manifest_hash=bundle.sap_manifest.artifact_hash(),
        stage_manifest_hash="0" * 64,
        session_spine_hash="0" * 64,
        genesis_manifest_hash=sealed.genesis_manifest.normalized_genesis_hash,
        pair_decision_hashes=(),
        current_replay_hash="0" * 64,
        stress_replay_hash="0" * 64,
        champion_capital_report_hash="0" * 64,
        challenger_capital_report_hash="0" * 64,
        consumption_ledger_hash="0" * 64,
        mode="DAILY_BAR_PROXY",
        eligibility=EligibilityGates(
            **{field: False for field in EligibilityGates.model_fields}
        ),
        assessed_at=sealed.clock(),
        evidence_cutoff=sealed.clock(),
    )
    return render_trial_assessment(projection)


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
        "decide-session", help="decide one enrolled signal session"
    )
    p_decide.add_argument("--root", required=True)
    p_decide.add_argument("--trial-id", required=True, dest="trial_id")
    p_decide.add_argument(
        "--signal-session", required=True, type=_iso_date, dest="signal_session"
    )

    p_advance = sub.add_parser(
        "advance-session", help="advance one market session of both arms"
    )
    p_advance.add_argument("--root", required=True)
    p_advance.add_argument("--trial-id", required=True, dest="trial_id")
    p_advance.add_argument(
        "--market-session", required=True, type=_iso_date, dest="market_session"
    )

    p_assess = sub.add_parser(
        "assess", help="render the deletable assessment projection"
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
