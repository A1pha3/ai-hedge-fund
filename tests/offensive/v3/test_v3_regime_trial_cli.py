"""Capability-boundary tests for the BTST regime paired-trial CLI.

The CLI (``src/cli/v3_regime_trial.py`` + ``scripts/v3_regime_trial.py``) is a
thin operator-facing surface over paired-trial primitives. Only ``validate``
is operationally usable today. ``decide-session``, ``advance-session``, and
``assess`` require operational producer/capital, market/lifecycle, and
replay/capital/consumption inputs, respectively, and therefore fail closed.
This file pins the security boundary around an on-disk Trial root:

- the root must resolve to a real directory; path-traversal roots and
  symlink roots are rejected before anything is loaded;
- ``validate`` is strictly read-only (no writes, ever) and fails closed on
  any missing sealed artifact (governance bundle, genesis manifest, session
  spine, writer lease);
- the CLI recognizes NO policy / regime / cap / mode override flags — those
  frozen values come only from the sealed artifacts, never from the command
  line or the environment;
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
import hashlib
import gc
import json
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace

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


class _CountingClock:
    def __init__(self, value: datetime) -> None:
        self.value = value
        self.calls = 0

    def __call__(self) -> datetime:
        self.calls += 1
        return self.value


def _sealed_trial_root(
    root: Path,
    *,
    invalid_bundle: bool = False,
    archive_manifest_drift: bool = False,
    enrolled_program: str | None = None,
    live_writer: bool = True,
) -> tuple[str, datetime]:
    """Build one real, fully laid-out Trial root through production writers.

    The CLI under test only consumes the resulting files.  The helper closes
    every writer before returning, so any later byte or sidecar change belongs
    to the read path under test.
    """

    from tests.offensive.v3.orchestration.test_trial_arm_store import (
        _bundle,
    )
    from src.screening.offensive.v3.evidence.session_spine import (
        SessionEnrollment,
        SessionSpine,
    )
    from src.screening.offensive.v3.orchestration.genesis import (
        TrialGenesisManifest,
    )
    from src.screening.offensive.v3.orchestration.trial_store import (
        TrialArmDecisionStore,
    )

    root.mkdir()
    (root / "archive").mkdir()
    (root / "blobs").mkdir()
    sqlite3.connect(root / "evidence.sqlite3").close()

    bundle = _bundle()
    if invalid_bundle:
        bundle = bundle.model_copy(
            update={
                "sap_manifest": bundle.sap_manifest.model_copy(
                    update={"trial_manifest_hash": "f" * 64}
                )
            }
        )
    trial = bundle.trial_manifest
    trusted_at = trial.enrollment_start
    trial_id = trial.trial_id

    champion_bytes = b"sealed champion capital backup"
    challenger_bytes = b"sealed challenger capital backup"
    champion_root = hashlib.sha256(champion_bytes).hexdigest()
    challenger_root = hashlib.sha256(challenger_bytes).hexdigest()
    for content_root, payload in (
        (champion_root, champion_bytes),
        (challenger_root, challenger_bytes),
    ):
        destination = root / "archive" / trial_id / content_root
        destination.mkdir(parents=True, exist_ok=True)
        (destination / "capital.sqlite3").write_bytes(payload)

    manifest = TrialGenesisManifest(
        trial_id=trial_id,
        normalized_genesis_hash="a" * 64,
        champion_normalized_hash="a" * 64,
        challenger_normalized_hash="a" * 64,
        champion_backup_root=champion_root,
        challenger_backup_root=challenger_root,
        trial_manifest_hash=trial.artifact_hash(),
        sap_manifest_hash=bundle.sap_manifest.artifact_hash(),
        sealed_at=trial.trial_manifest_sealed_at,
        schema_major=2,
    )
    manifest_path = root / "archive" / trial_id / "genesis-manifest.json"
    manifest_path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")

    store = TrialArmDecisionStore(str(root / "decisions.sqlite3"))
    store.register_trial(bundle, manifest)
    if live_writer:
        store.claim_writer()
    del store

    program = enrolled_program or trial.research_program_id
    spine = SessionSpine(
        database_path=str(root / "spine.sqlite3"),
        clock=lambda: trial.trial_manifest_sealed_at,
    )
    spine.enroll_expected_sessions(
        (
            SessionEnrollment(
                research_program_id=program,
                signal_session=trusted_at.date(),
                assessment_date=trusted_at.date(),
            ),
        )
    )
    spine._engine.dispose()  # noqa: SLF001 - close the test fixture's writer
    del spine
    gc.collect()
    for database in (root / "decisions.sqlite3", root / "spine.sqlite3"):
        with sqlite3.connect(database) as conn:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    if archive_manifest_drift:
        archived = json.loads(manifest_path.read_text(encoding="utf-8"))
        archived["sealed_at"] = trial.enrollment_start.isoformat()
        manifest_path.write_text(
            json.dumps(archived, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )
    return trial_id, trusted_at


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


def test_validate_laid_out_invalid_database_does_not_migrate(
    tmp_path: Path,
) -> None:
    """A complete path layout is not permission to initialize its databases."""

    mod = _cli()
    root = tmp_path / "invalid-root"
    root.mkdir()
    (root / "archive").mkdir()
    (root / "blobs").mkdir()
    for name in ("decisions.sqlite3", "spine.sqlite3", "evidence.sqlite3"):
        (root / name).write_bytes(b"")
    before = _tree_bytes(root)

    with pytest.raises(mod.RegimeTrialCliError):
        mod.validate_trial(root=root, trial_id="trial-regime-001")

    assert _tree_bytes(root) == before


def test_validate_real_sealed_root_is_byte_for_byte_read_only(
    tmp_path: Path,
) -> None:
    """Validation must not migrate DBs, change journal mode, or add sidecars."""

    mod = _cli()
    root = tmp_path / "sealed-root"
    trial_id, trusted_at = _sealed_trial_root(root)
    clock = _CountingClock(trusted_at)
    before = _tree_bytes(root)

    assert mod.validate_trial(root=root, trial_id=trial_id, clock=clock) == 0

    assert clock.calls == 1
    assert _tree_bytes(root) == before


def test_validate_rejects_semantically_invalid_governance_bundle(
    tmp_path: Path,
) -> None:
    """A parseable bundle with a broken SAP binding is not a valid seal."""

    mod = _cli()
    root = tmp_path / "invalid-bundle"
    trial_id, trusted_at = _sealed_trial_root(root, invalid_bundle=True)

    with pytest.raises(mod.RegimeTrialCliError) as excinfo:
        mod.validate_trial(root=root, trial_id=trial_id, clock=lambda: trusted_at)

    assert excinfo.value.code == "governance_bundle_invalid"


def test_validate_rejects_full_genesis_manifest_drift(tmp_path: Path) -> None:
    """Equal normalized hashes cannot hide drift in another manifest field."""

    mod = _cli()
    root = tmp_path / "manifest-drift"
    trial_id, trusted_at = _sealed_trial_root(
        root, archive_manifest_drift=True
    )

    with pytest.raises(mod.RegimeTrialCliError) as excinfo:
        mod.validate_trial(root=root, trial_id=trial_id, clock=lambda: trusted_at)

    assert excinfo.value.code == "genesis_manifest_drift"


def test_validate_rejects_spine_without_trial_program_enrollment(
    tmp_path: Path,
) -> None:
    """A layout-only spine for another program cannot satisfy this Trial."""

    mod = _cli()
    root = tmp_path / "wrong-program"
    trial_id, trusted_at = _sealed_trial_root(
        root, enrolled_program="another-research-program"
    )

    with pytest.raises(mod.RegimeTrialCliError) as excinfo:
        mod.validate_trial(root=root, trial_id=trial_id, clock=lambda: trusted_at)

    assert excinfo.value.code == "spine_program_not_enrolled"


def test_validate_rejects_missing_live_writer_lease(tmp_path: Path) -> None:
    """A sealed layout without the current writer lease is not runnable."""

    mod = _cli()
    root = tmp_path / "no-live-writer"
    trial_id, trusted_at = _sealed_trial_root(root, live_writer=False)

    with pytest.raises(mod.RegimeTrialCliError) as excinfo:
        mod.validate_trial(root=root, trial_id=trial_id, clock=lambda: trusted_at)

    assert excinfo.value.code == "writer_lease_unavailable"


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


def test_assess_rejects_unavailable_inputs_without_writing_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A sealed registration alone cannot prove an assessment.

    Replay, per-arm capital, and evidence-consumption inputs are operational
    facts.  Until they are wired, ``assess`` must fail closed instead of
    filling their hashes and eligibility gates with placeholders.
    """

    mod = _cli()
    sealed = mod._SealedTrial(
        root=tmp_path,
        trial_id="trial-regime-001",
        store=object(),
        bundle=SimpleNamespace(
            trial_manifest=SimpleNamespace(
                research_program_id="program-regime-001",
                economic_lineage_id="lineage-btst",
                artifact_hash=lambda: "1" * 64,
            ),
            sap_manifest=SimpleNamespace(artifact_hash=lambda: "2" * 64),
        ),
        genesis_manifest=SimpleNamespace(normalized_genesis_hash="3" * 64),
        spine=object(),
        trusted_at=datetime(2026, 8, 12, tzinfo=timezone.utc),
    )
    monkeypatch.setattr(mod, "_load_sealed_trial", lambda *args, **kwargs: sealed)
    output = tmp_path / "assessment.json"

    with pytest.raises(mod.RegimeTrialCliError) as excinfo:
        mod.assess_trial(
            root=tmp_path,
            trial_id="trial-regime-001",
            output=output,
        )

    assert excinfo.value.code == "assessment_inputs_unavailable"
    assert not output.exists()


def test_assess_valid_sealed_root_is_byte_for_byte_read_only(
    tmp_path: Path,
) -> None:
    """Failing closed must leave every Trial artifact and sidecar unchanged."""

    mod = _cli()
    root = tmp_path / "sealed-root"
    trial_id, trusted_at = _sealed_trial_root(root)
    output = tmp_path / "assessment.json"
    before = _tree_bytes(root)

    with pytest.raises(mod.RegimeTrialCliError) as excinfo:
        mod.assess_trial(
            root=root,
            trial_id=trial_id,
            output=output,
            clock=lambda: trusted_at,
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
    """Reserved entrypoints may validate, but cannot mutate before rejecting."""

    mod = _cli()
    root = tmp_path / "sealed-root"
    trial_id, trusted_at = _sealed_trial_root(root)
    before = _tree_bytes(root)

    with pytest.raises(mod.RegimeTrialCliError) as excinfo:
        if command == "decide":
            mod.decide_session(
                root=root,
                trial_id=trial_id,
                signal_session=session_argument,
                clock=lambda: trusted_at,
            )
        else:
            mod.advance_market_session(
                root=root,
                trial_id=trial_id,
                market_session=session_argument,
                clock=lambda: trusted_at,
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
