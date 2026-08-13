"""Capability-boundary tests for the BTST regime paired-trial CLI.

The CLI (``src/cli/v3_regime_trial.py`` + ``scripts/v3_regime_trial.py``) is a
thin operator-facing surface over paired-trial primitives. None of the four
commands is operationally usable today: the standalone root does not yet
contain a signed Stage, an immutable store-seal receipt, or a hash-bound
complete session spine, and an active WAL database cannot be treated as an
immutable current-truth snapshot. Every command therefore fails closed.
This file pins the security boundary around an on-disk Trial root:

- the root must be a canonical absolute path to a real directory;
  path-traversal roots and every symlinked component are rejected before
  anything is loaded;
- every command is strictly read-only (no writes, migrations, SQLite opens,
  or sidecars) and rejects symlinked layout artifacts before failing closed;
- the CLI recognizes NO policy / regime / cap / mode override flags and,
  while unavailable, reads or binds NO frozen values from disk, the command
  line, or the environment;
- ``assess`` never fabricates a report from placeholder hashes or gates and
  writes no output while its real inputs are unavailable;
- each subcommand dispatches to exactly one library entrypoint and nothing
  else (no broker, no gateway authority, no activation surface — that
  import boundary is pinned separately in
  ``test_regime_trial_import_boundary``).

The Task 11–13 suites cover the isolated runner, replay, and evaluator
primitives; they do not prove that this CLI can start, advance, or assess an
official Trial. These tests cover the CLI's own guards and dispatch logic.
"""

from __future__ import annotations

import importlib
import json
from datetime import date
from pathlib import Path

import pytest

_CLI_MODULE = "src.cli.v3_regime_trial"


def _cli():
    """Import the CLI module fresh (it is the RED target)."""

    return importlib.import_module(_CLI_MODULE)


def _tree_bytes(root: Path) -> dict[str, bytes]:
    """Exact regular-file snapshot, including any SQLite sidecars."""

    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _layout_only_root(root: Path) -> Path:
    """Create path-shape fixtures, never synthetic governance truth."""

    root.mkdir()
    for dirname in ("archive", "blobs"):
        (root / dirname).mkdir()
    for filename in (
        "decisions.sqlite3",
        "spine.sqlite3",
        "evidence.sqlite3",
    ):
        (root / filename).write_bytes(b"not-opened")
    return root


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


def test_resolve_root_rejects_noncanonical_relative_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Operators must spell the root as its canonical absolute path."""

    mod = _cli()
    root = tmp_path / "trial-root"
    root.mkdir()
    monkeypatch.chdir(tmp_path)

    with pytest.raises(mod.RegimeTrialCliError) as excinfo:
        mod._resolve_trial_root(Path("trial-root"))

    assert excinfo.value.code == "root_not_canonical"


def test_resolve_root_rejects_symlink(tmp_path: Path) -> None:
    mod = _cli()
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real)
    with pytest.raises(mod.RegimeTrialCliError) as excinfo:
        mod._resolve_trial_root(link)
    assert excinfo.value.code == "root_symlink_rejected"


def test_resolve_root_rejects_symlinked_existing_parent(tmp_path: Path) -> None:
    mod = _cli()
    real_parent = tmp_path / "real-parent"
    real_parent.mkdir()
    (real_parent / "trial-root").mkdir()
    linked_parent = tmp_path / "linked-parent"
    linked_parent.symlink_to(real_parent, target_is_directory=True)

    with pytest.raises(mod.RegimeTrialCliError) as excinfo:
        mod._resolve_trial_root(linked_parent / "trial-root")

    assert excinfo.value.code == "root_symlink_rejected"


def test_resolve_root_accepts_real_directory(tmp_path: Path) -> None:
    mod = _cli()
    root = tmp_path / "trial-root"
    root.mkdir()
    resolved = mod._resolve_trial_root(root)
    assert resolved == root.resolve()


def test_resolve_root_uses_only_lstat_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The final directory check must not re-follow the path after lstat."""

    mod = _cli()
    root = tmp_path / "trial-root"
    root.mkdir()

    def forbidden_is_dir(_path: Path) -> bool:
        raise AssertionError("Path.is_dir follows symlinks")

    monkeypatch.setattr(Path, "is_dir", forbidden_is_dir)

    assert mod._resolve_trial_root(root) == root.absolute()


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


def test_validate_layout_fails_closed_without_opening_sqlite(
    tmp_path: Path,
) -> None:
    """A plausible layout is not a trustworthy sealed-root receipt."""

    mod = _cli()
    root = _layout_only_root(tmp_path / "trial-root")
    before = _tree_bytes(root)

    with pytest.raises(mod.RegimeTrialCliError) as excinfo:
        mod.validate_trial(root=root, trial_id="trial-regime-001")

    assert excinfo.value.code == "validation_inputs_unavailable"
    assert "signed Stage" in str(excinfo.value)
    assert _tree_bytes(root) == before


def test_validate_rejects_symlinked_layout_file_before_reading(
    tmp_path: Path,
) -> None:
    mod = _cli()
    root = _layout_only_root(tmp_path / "trial-root")
    outside = tmp_path / "outside.sqlite3"
    outside.write_bytes(b"external")
    (root / "decisions.sqlite3").unlink()
    (root / "decisions.sqlite3").symlink_to(outside)

    with pytest.raises(mod.RegimeTrialCliError) as excinfo:
        mod.validate_trial(root=root, trial_id="trial-regime-001")

    assert excinfo.value.code == "layout_symlink_rejected"


@pytest.mark.parametrize("trial_id", ("../escape", "a/b", "a\\b", ".", ".."))
def test_commands_reject_trial_id_path_syntax(
    tmp_path: Path, trial_id: str
) -> None:
    mod = _cli()
    root = _layout_only_root(tmp_path / "trial-root")

    with pytest.raises(mod.RegimeTrialCliError) as excinfo:
        mod.validate_trial(root=root, trial_id=trial_id)

    assert excinfo.value.code == "trial_id_path_rejected"


# =============================================================================
# assess: refuses to invent an assessment without operational inputs
# =============================================================================


def test_assess_rejects_unsealed_root_without_writing_output(tmp_path: Path) -> None:
    """An unsealed Trial root rejects before creating any output."""

    mod = _cli()
    root = tmp_path / "no-trial"
    root.mkdir()
    output = tmp_path / "report.json"
    before = {p for p in tmp_path.rglob("*")}
    with pytest.raises(mod.RegimeTrialCliError):
        mod.assess_trial(root=root, trial_id="trial-regime-001", output=output)
    after = {p for p in tmp_path.rglob("*")}
    # No file was created anywhere under tmp_path.
    assert after == before
    assert not output.exists()


def test_assess_laid_out_root_is_byte_for_byte_read_only(
    tmp_path: Path,
) -> None:
    """Unavailable assessment must not inspect or mutate SQLite bytes."""

    mod = _cli()
    root = _layout_only_root(tmp_path / "trial-root")
    output = tmp_path / "assessment.json"
    before = _tree_bytes(root)

    with pytest.raises(mod.RegimeTrialCliError) as excinfo:
        mod.assess_trial(
            root=root,
            trial_id="trial-regime-001",
            output=output,
        )

    assert excinfo.value.code == "assessment_inputs_unavailable"
    assert _tree_bytes(root) == before
    assert not output.exists()


@pytest.mark.parametrize(
    ("command", "session_argument"),
    [
        ("decide", date(2026, 8, 6)),
        ("advance", date(2026, 8, 7)),
    ],
)
def test_unavailable_reserved_commands_are_byte_for_byte_read_only(
    tmp_path: Path, command: str, session_argument: date
) -> None:
    """Reserved entrypoints check path shape but never inspect Trial bytes."""

    mod = _cli()
    root = _layout_only_root(tmp_path / "trial-root")
    before = _tree_bytes(root)

    with pytest.raises(mod.RegimeTrialCliError) as excinfo:
        if command == "decide":
            mod.decide_session(
                root=root,
                trial_id="trial-regime-001",
                signal_session=session_argument,
            )
        else:
            mod.advance_market_session(
                root=root,
                trial_id="trial-regime-001",
                market_session=session_argument,
            )

    assert excinfo.value.code == "privileged_context_required"
    assert _tree_bytes(root) == before


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
    the unavailable CLI does not currently read or bind them at all. argparse
    must reject every such flag as unrecognized."""

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


@pytest.mark.parametrize(
    ("argv_tail", "expected_code"),
    [
        (("validate",), "validation_inputs_unavailable"),
        (
            ("decide-session", "--signal-session", "2026-08-06"),
            "privileged_context_required",
        ),
        (
            ("advance-session", "--market-session", "2026-08-07"),
            "privileged_context_required",
        ),
        (
            ("assess", "--output", "assessment.json"),
            "assessment_inputs_unavailable",
        ),
    ],
)
def test_main_renders_unavailable_as_stable_typed_json_without_traceback(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    argv_tail: tuple[str, ...],
    expected_code: str,
) -> None:
    """The operator surface reports one typed rejection, not an exception trace."""

    mod = _cli()
    root = _layout_only_root(tmp_path / "trial-root")
    output = tmp_path / "assessment.json"
    rendered_tail = tuple(
        str(output) if value == "assessment.json" else value
        for value in argv_tail
    )

    rc = mod.main(
        [
            rendered_tail[0],
            "--root",
            str(root),
            "--trial-id",
            "trial-regime-001",
            *rendered_tail[1:],
        ]
    )

    captured = capsys.readouterr()
    assert rc == mod.UNAVAILABLE_EXIT_CODE
    assert captured.out == ""
    error = json.loads(captured.err)
    assert error["code"] == expected_code
    assert error["details"]["trial_id"] == "trial-regime-001"
    assert captured.err.count("\n") == 1
    assert "Traceback" not in captured.err
    assert not output.exists()
