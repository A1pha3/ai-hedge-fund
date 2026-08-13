"""Thin operator CLI for the BTST regime paired-trial primitives.

Four subcommands over one on-disk Trial root:

- ``validate``        — reserved read-only entrypoint. It checks only the
  root's path shape, then fails closed until a signed Stage, an immutable
  store-seal receipt, and a hash-bound complete session spine are available.
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

- the root must be supplied as a canonical absolute path to a real directory;
  path-traversal roots and any symlinked path component reject before anything
  is loaded;
- the CLI recognizes NO policy / regime / cap / mode / evidence-cutoff
  override flags and reads NO environment switches. While all commands are
  unavailable, it does not read or bind any frozen value from disk either;
- the CLI never auto-creates or auto-seals a Trial;
- the module imports only the trial-path surface (runner, replay engine,
  proxy adapter, lifecycle, decision store, genesis, evaluator); it never
  reaches broker, gateway authority/decisions, activation, outbox, or
  ``shadow_trust``.

Execution boundary: none of the four commands is self-contained today. Every
command performs only no-follow path/layout checks and then fails closed. In
particular, an active WAL database is not opened with SQLite ``immutable=1``:
that mode ignores committed WAL pages and therefore cannot witness current
truth. The Task 11–13 runner, replay, and evaluator primitives and tests do
not make an official Trial executable, validatable, or evaluable by themselves.
"""

from __future__ import annotations

import argparse
import json
import stat
import sys
from datetime import date, datetime
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

# Stable operator-facing result for a well-formed command whose required
# governance/operational proof is not wired. Usage errors remain argparse's 2.
UNAVAILABLE_EXIT_CODE = 78


class RegimeTrialCliError(RuntimeError):
    """Fail-closed rejection of a CLI operation (bad root, missing artifact,
    unsealed trial, or unavailable operational inputs). Never swallowed by
    ``main``."""

    def __init__(self, code: str, message: str, **details: object) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.details = details


def _resolve_trial_root(root: str | Path) -> Path:
    """Resolve a Trial root, rejecting traversal / symlink / missing roots.

    The root must name a real directory using its canonical absolute spelling.
    Its path contains no ``..`` segment and no component may be a symlink.
    Metadata is inspected exclusively with ``lstat`` so the final directory
    check cannot re-follow a path after the no-symlink proof.
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
    if not path.is_absolute():
        raise RegimeTrialCliError(
            "root_not_canonical",
            "a Trial root must be supplied as a canonical absolute path",
            root=str(root),
        )
    # Reject a symlink at any existing component, not only the leaf. A
    # non-symlink leaf under a symlinked parent is equally repointable.
    absolute = path.absolute()
    current = Path(absolute.anchor)
    leaf_mode: int | None = None
    missing_component = False
    for part in absolute.parts[1:]:
        current /= part
        try:
            mode = current.lstat().st_mode
        except FileNotFoundError:
            missing_component = True
            break
        leaf_mode = mode
        if stat.S_ISLNK(mode):
            raise RegimeTrialCliError(
                "root_symlink_rejected",
                "a Trial root must have no symlinked path component",
                root=str(root),
                component=str(current),
            )
    if missing_component or leaf_mode is None or not stat.S_ISDIR(leaf_mode):
        raise RegimeTrialCliError(
            "root_not_found",
            "a Trial root must be an existing directory",
            root=str(root),
        )
    return absolute


def _require_layout(root: Path) -> None:
    """Check the fixed layout by lstat only; never follow or open artifacts."""

    missing: list[str] = []
    for name in _LAYOUT_FILES:
        path = root / name
        try:
            mode = path.lstat().st_mode
        except FileNotFoundError:
            missing.append(name)
            continue
        if stat.S_ISLNK(mode):
            raise RegimeTrialCliError(
                "layout_symlink_rejected",
                "Trial layout artifacts must not be symlinks",
                artifact=name,
            )
        if not stat.S_ISREG(mode):
            missing.append(name)
    for name in _LAYOUT_DIRS:
        path = root / name
        try:
            mode = path.lstat().st_mode
        except FileNotFoundError:
            missing.append(name + "/")
            continue
        if stat.S_ISLNK(mode):
            raise RegimeTrialCliError(
                "layout_symlink_rejected",
                "Trial layout artifacts must not be symlinks",
                artifact=name + "/",
            )
        if not stat.S_ISDIR(mode):
            missing.append(name + "/")
    if missing:
        raise RegimeTrialCliError(
            "trial_root_not_sealed",
            "the Trial root is missing sealed layout artifacts",
            root=str(root),
            missing=missing,
        )


def _validate_trial_id(trial_id: str) -> None:
    """Keep an opaque Trial id from becoming an archive path."""

    if (
        not trial_id
        or trial_id in {".", ".."}
        or "/" in trial_id
        or "\\" in trial_id
        or "\x00" in trial_id
    ):
        raise RegimeTrialCliError(
            "trial_id_path_rejected",
            "trial_id must be one non-path identifier",
            trial_id=trial_id,
        )


def _guard_unavailable_root(root: str | Path, trial_id: str) -> Path:
    """Perform the entire safe standalone check: path shape, never content."""

    resolved = _resolve_trial_root(root)
    _validate_trial_id(trial_id)
    _require_layout(resolved)
    return resolved


def validate_trial(
    *, root: str | Path, trial_id: str, clock: Callable[[], datetime] | None = None
) -> int:
    """Fail closed: the standalone root lacks a complete validation proof."""

    _guard_unavailable_root(root, trial_id)
    raise RegimeTrialCliError(
        "validation_inputs_unavailable",
        "validate requires a signed Stage, an immutable store-seal receipt,"
        " and a hash-bound complete SessionSpine read from a cold immutable"
        " snapshot; an active WAL database is not current truth under"
        " SQLite immutable mode",
        trial_id=trial_id,
    )


def decide_session(
    *,
    root: str | Path,
    trial_id: str,
    signal_session: date,
    clock: Callable[[], datetime] | None = None,
) -> int:
    """Fail closed until the forward runner's operational inputs are wired.

    Only the no-follow root layout is checked. The standalone process has no
    producer trust chain or independent per-arm PIT capital context, so it
    rejects without opening untrusted Trial content.
    """

    _guard_unavailable_root(root, trial_id)
    raise RegimeTrialCliError(
        "privileged_context_required",
        "decide-session delegates to the ForwardPairedTrialRunner, whose producer"
        " trust chain and PIT capital baseline the privileged worker (Plan 06+)"
        " injects; the standalone CLI cannot synthesize them from the sealed root"
        " without crossing the shadow_trust boundary",
        trial_id=trial_id,
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

    Only the no-follow root layout is checked. Constructing the full replay
    input (bars, marks, snapshot evidence, calendar and corporate actions) is
    the future operational driver's responsibility.
    """

    _guard_unavailable_root(root, trial_id)
    raise RegimeTrialCliError(
        "privileged_context_required",
        "advance-session delegates to the Task 12 replay engine, whose"
        " TrialReplayInput (bars, marks, snapshot evidence) the operational"
        " replay driver assembles; the standalone CLI cannot invent market"
        " facts from the sealed root",
        trial_id=trial_id,
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

    _guard_unavailable_root(root, trial_id)
    raise RegimeTrialCliError(
        "assessment_inputs_unavailable",
        "assess requires official current and stress replay outputs, independent"
        " per-arm capital reports, and the evidence-consumption ledger; the"
        " standalone CLI cannot derive those facts from the sealed registration",
        trial_id=trial_id,
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
            "Reserved operator CLI for the BTST regime paired shadow trial."
            " All commands currently fail closed without reading or binding"
            " frozen policy/regime/cap/mode values. No override flags or"
            " environment switches are recognized; --root must be a canonical"
            " absolute path with no symlinked component."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_validate = sub.add_parser(
        "validate",
        help="unavailable: requires a complete immutable validation proof",
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
    try:
        root = _resolve_trial_root(args.root)
        if args.command == "validate":
            return validate_trial(root=root, trial_id=args.trial_id)
        if args.command == "decide-session":
            return decide_session(
                root=root,
                trial_id=args.trial_id,
                signal_session=args.signal_session,
            )
        if args.command == "advance-session":
            return advance_market_session(
                root=root,
                trial_id=args.trial_id,
                market_session=args.market_session,
            )
        if args.command == "assess":
            return assess_trial(root=root, trial_id=args.trial_id, output=args.output)
    except RegimeTrialCliError as exc:
        print(
            json.dumps(
                {
                    "code": exc.code,
                    "details": exc.details,
                    "message": str(exc),
                    "status": "unavailable",
                },
                ensure_ascii=False,
                sort_keys=True,
                default=str,
            ),
            file=sys.stderr,
        )
        return UNAVAILABLE_EXIT_CODE
    return 2


__all__ = [
    "RegimeTrialCliError",
    "UNAVAILABLE_EXIT_CODE",
    "advance_market_session",
    "assess_trial",
    "decide_session",
    "main",
    "validate_trial",
]
