"""Plan Task 14 Step 1: RED tests for the BTST regime paired-trial CLI.

The CLI (``src/cli/v3_regime_trial.py`` + ``scripts/v3_regime_trial.py``) is a
thin operator-facing wrapper over the already-green paired runner
(Task 11), replay engine (Task 12), and frozen evaluator (Task 13). Its own
contract — the part this file pins — is the security boundary around an
on-disk Trial root:

- the root must resolve to a real directory; path-traversal roots and
  symlink roots are rejected before anything is loaded;
- ``validate`` is strictly read-only (no writes, ever) and fails closed on
  any missing sealed artifact (governance bundle, genesis manifest, session
  spine, writer lease);
- the CLI recognizes NO policy / regime / cap / mode override flags — those
  frozen values come only from the sealed artifacts, never from the command
  line or the environment;
- ``assess`` writes its deletable report ONLY to the explicit ``--output``
  path;
- each subcommand dispatches to exactly one library entrypoint and nothing
  else (no broker, no gateway authority, no activation surface — that
  import boundary is pinned separately in
  ``test_regime_trial_import_boundary``).

The happy-path *execution* (real root → real runner → real commit) is
already proven by the Task 11–13 suites; these tests prove the CLI's own
guard and dispatch logic, so they need no fully-sealed Trial root.
"""

from __future__ import annotations

import importlib
from datetime import date
from pathlib import Path

import pytest

_CLI_MODULE = "src.cli.v3_regime_trial"


def _cli():
    """Import the CLI module fresh (it is the RED target)."""

    return importlib.import_module(_CLI_MODULE)


# =============================================================================
# Surface: the module, its subcommands, and the fail-closed error exist
# =============================================================================


def test_cli_module_exposes_surface() -> None:
    """The thin CLI module exposes its four commands, the root resolver, and
    a typed fail-closed error."""

    mod = _cli()
    assert callable(mod.main)
    assert callable(mod.validate_trial)
    assert callable(mod.decide_session)
    assert callable(mod.advance_market_session)
    assert callable(mod.assess_trial)
    assert callable(mod._resolve_trial_root)
    assert issubclass(mod.RegimeTrialCliError, Exception)


# =============================================================================
# Root resolution: missing / path-traversal / symlink roots reject, no writes
# =============================================================================


def test_resolve_root_rejects_missing_path(tmp_path: Path) -> None:
    mod = _cli()
    missing = tmp_path / "does-not-exist"
    with pytest.raises(mod.RegimeTrialCliError) as excinfo:
        mod._resolve_trial_root(missing)
    assert excinfo.value.code == "root_not_found"


def test_resolve_root_rejects_path_traversal(tmp_path: Path) -> None:
    mod = _cli()
    # A root whose path contains a `..` segment is a traversal attempt; it
    # must reject before any file under it is touched.
    traversal = tmp_path / ".." / "escape"
    with pytest.raises(mod.RegimeTrialCliError) as excinfo:
        mod._resolve_trial_root(traversal)
    assert excinfo.value.code == "root_path_traversal"


def test_resolve_root_rejects_symlink(tmp_path: Path) -> None:
    mod = _cli()
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real)
    with pytest.raises(mod.RegimeTrialCliError) as excinfo:
        mod._resolve_trial_root(link)
    assert excinfo.value.code == "root_symlink_rejected"


def test_resolve_root_accepts_real_directory(tmp_path: Path) -> None:
    mod = _cli()
    root = tmp_path / "trial-root"
    root.mkdir()
    resolved = mod._resolve_trial_root(root)
    assert resolved == root.resolve()


# =============================================================================
# validate: read-only, fails closed on any missing sealed artifact
# =============================================================================


def test_validate_rejects_empty_root_and_writes_nothing(tmp_path: Path) -> None:
    mod = _cli()
    root = tmp_path / "empty-root"
    root.mkdir()
    before = {p.relative_to(root) for p in root.rglob("*")}
    with pytest.raises(mod.RegimeTrialCliError):
        mod.validate_trial(root=root, trial_id="trial-regime-001")
    after = {p.relative_to(root) for p in root.rglob("*")}
    # validate is strictly read-only: an empty root is rejected AND untouched.
    assert after == before


def test_validate_fails_closed_on_missing_spine(tmp_path: Path) -> None:
    """A root whose session spine is absent is not a loadable trial."""

    mod = _cli()
    root = tmp_path / "partial-root"
    root.mkdir()
    (root / "decisions.sqlite3").write_bytes(b"")  # placeholder, not loaded yet
    with pytest.raises(mod.RegimeTrialCliError):
        mod.validate_trial(root=root, trial_id="trial-regime-001")


# =============================================================================
# assess: writes ONLY to the explicit --output path
# =============================================================================


def test_assess_writes_only_to_explicit_output(tmp_path: Path) -> None:
    """Even when the trial cannot be fully loaded, ``assess`` must never
    scatter writes — it fails closed rather than writing anywhere except the
    explicit ``--output`` path."""

    mod = _cli()
    root = tmp_path / "no-trial"
    root.mkdir()
    output = tmp_path / "report.json"
    before = {p for p in tmp_path.rglob("*")}
    with pytest.raises(mod.RegimeTrialCliError):
        mod.assess_trial(root=root, trial_id="trial-regime-001", output=output)
    after = {p for p in tmp_path.rglob("*")}
    # No file was created anywhere under tmp_path (the output is written only
    # on a fully successful assessment, never on the failure path).
    assert after == before
    assert not output.exists()


# =============================================================================
# main: unknown subcommand and unrecognized override flags reject; dispatch
# =============================================================================


def test_main_unknown_subcommand_returns_nonzero(tmp_path: Path) -> None:
    mod = _cli()
    rc = mod.main(["bogus-command", "--root", str(tmp_path)])
    assert rc != 0


@pytest.mark.parametrize(
    "flag,value",
    [
        ("--policy-mode", "shadow"),
        ("--runtime-mode", "AUTHORITATIVE"),
        ("--admission-mode", "NORMAL_ONLY"),
        ("--portfolio-cap", "0.5"),
        ("--evidence-cutoff", "2026-09-01"),
    ],
)
def test_main_recognizes_no_override_flags(
    tmp_path: Path, flag: str, value: str
) -> None:
    """No policy / regime / cap / mode / cutoff override may be accepted:
    those frozen values come only from the sealed artifacts. argparse must
    reject every such flag as unrecognized."""

    mod = _cli()
    rc = mod.main(
        ["validate", "--root", str(tmp_path), "--trial-id", "t1", flag, value]
    )
    assert rc != 0


def test_main_validate_dispatches_to_validate_trial(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    mod = _cli()
    seen: dict[str, object] = {}

    def spy(*, root, trial_id, clock=None):
        seen["root"] = root
        seen["trial_id"] = trial_id
        seen["clock"] = clock
        return 0

    monkeypatch.setattr(mod, "validate_trial", spy)
    root = tmp_path / "trial-root"
    root.mkdir()
    rc = mod.main(
        ["validate", "--root", str(root), "--trial-id", "trial-regime-001"]
    )
    assert rc == 0
    assert seen["trial_id"] == "trial-regime-001"
    assert Path(seen["root"]) == root.resolve()


def test_main_decide_session_dispatches_with_parsed_date(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    mod = _cli()
    seen: dict[str, object] = {}

    def spy(*, root, trial_id, signal_session, clock=None):
        seen["signal_session"] = signal_session
        seen["trial_id"] = trial_id
        return 0

    monkeypatch.setattr(mod, "decide_session", spy)
    root = tmp_path / "trial-root"
    root.mkdir()
    rc = mod.main(
        [
            "decide-session",
            "--root",
            str(root),
            "--trial-id",
            "trial-regime-001",
            "--signal-session",
            "2026-08-05",
        ]
    )
    assert rc == 0
    assert seen["signal_session"] == date(2026, 8, 5)


def test_main_assess_dispatches_with_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    mod = _cli()
    seen: dict[str, object] = {}

    def spy(*, root, trial_id, output, clock=None):
        seen["output"] = output
        seen["trial_id"] = trial_id
        return 0

    monkeypatch.setattr(mod, "assess_trial", spy)
    root = tmp_path / "trial-root"
    root.mkdir()
    output = tmp_path / "assessment.json"
    rc = mod.main(
        [
            "assess",
            "--root",
            str(root),
            "--trial-id",
            "trial-regime-001",
            "--output",
            str(output),
        ]
    )
    assert rc == 0
    assert Path(seen["output"]) == output


def test_main_advance_session_dispatches_with_parsed_date(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    mod = _cli()
    seen: dict[str, object] = {}

    def spy(*, root, trial_id, market_session, clock=None):
        seen["market_session"] = market_session
        return 0

    monkeypatch.setattr(mod, "advance_market_session", spy)
    root = tmp_path / "trial-root"
    root.mkdir()
    rc = mod.main(
        [
            "advance-session",
            "--root",
            str(root),
            "--trial-id",
            "trial-regime-001",
            "--market-session",
            "2026-08-06",
        ]
    )
    assert rc == 0
    assert seen["market_session"] == date(2026, 8, 6)
