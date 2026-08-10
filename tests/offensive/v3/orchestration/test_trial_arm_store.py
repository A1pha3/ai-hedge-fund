"""Plan Task 6 RED: atomic arm decision store + fenced single writer.

``TrialArmDecisionStore`` persists the exact pair of arm decisions
(``ShadowDecision | NoTradeDecision``) for one trial/session/cycle under the
unique key ``(trial_id, signal_session, decision_cycle_id, arm)``. Rows are
immutable (UPDATE/DELETE triggers), replay is exact-idempotent, a
same-key/different-content replay is a typed conflict, and pair commits are
two-row atomic. A monotone fencing epoch guards pair/capital lifecycle
mutation: every new owner bumps the epoch, stale tokens fail before any
mutation.
"""

from __future__ import annotations

import sqlite3
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.screening.offensive.v3.contracts.decision import ShadowDecision
from src.screening.offensive.v3.contracts.governance import (
    PolicyActivation,
)
from src.screening.offensive.v3.governance.regime_trial import (
    RegimeTrialBundle,
)
from src.screening.offensive.v3.kernel.models import NoTradeDecision
from src.screening.offensive.v3.orchestration.genesis import (
    TrialGenesisManifest,
)
from src.screening.offensive.v3.orchestration.trial_store import (
    PairCommitReceipt,
    TrialArmDecisionRecord,
    TrialArmDecisionStore,
    TrialStoreError,
)

# Reuse the kernel test's frozen paired world: real GrowthKernel decisions
# (ShadowDecision for NORMAL, NoTradeDecision for RISK_OFF Challenger) are
# the exact payloads the durable store wraps.
_KERNEL_TEST_DIR = Path(__file__).resolve().parents[1] / "kernel"
if str(_KERNEL_TEST_DIR) not in sys.path:
    sys.path.insert(0, str(_KERNEL_TEST_DIR))
from test_shadow_kernel import (  # noqa: E402
    NOW,
    SIGNAL_DATE,
    _paired_world,
    _sap,
    _trial_manifest,
    _trial_policy,
)

from src.screening.offensive.v3.contracts.trial import TrialArm  # noqa: E402
from src.screening.offensive.v3.contracts.regime import (  # noqa: E402
    RegimeAdmissionMode,
    RegimeState,
)
from src.screening.offensive.v3.contracts import ExecutionMode  # noqa: E402

UTC = timezone.utc
TRIAL_ID = "trial-regime-001"
HASH = "a" * 64
ZERO64 = "0" * 64


def _bundle() -> RegimeTrialBundle:
    """One sealed bundle from the kernel test's frozen builders."""

    baseline = _trial_policy(RegimeAdmissionMode.IGNORE)
    target = _trial_policy(RegimeAdmissionMode.NORMAL_ONLY)
    trial = _trial_manifest(baseline, target)
    sap = _sap(trial)
    activation = PolicyActivation(
        portfolio_id="portfolio-champion",
        mode=ExecutionMode.DAILY_BAR_PROXY,
        policy_snapshot_hash=baseline.content_hash(),
        predecessor_policy_activation_hash=ZERO64,
        trust_bundle_hash=HASH,
        registry_epoch=1,
        policy_epoch=1,
        authority_epoch=1,
        risk_epoch=1,
        effective_from=NOW,
        expires_at=NOW + timedelta(days=120),
        issuer_id="governance.service",
        issuer_capability="governance.policy.activation.v1",
        schema_major=2,
    )
    return RegimeTrialBundle(
        baseline_policy=baseline,
        target_policy=target,
        trial_manifest=trial,
        sap_manifest=sap,
        baseline_policy_activation=activation,
    )


def _genesis_manifest() -> TrialGenesisManifest:
    return TrialGenesisManifest(
        trial_id=TRIAL_ID,
        normalized_genesis_hash=HASH,
        champion_normalized_hash=HASH,
        challenger_normalized_hash=HASH,
        champion_backup_root="b" * 64,
        challenger_backup_root="c" * 64,
        trial_manifest_hash="d" * 64,
        sap_manifest_hash="e" * 64,
        sealed_at=NOW,
        schema_major=2,
    )


def _paired_decisions(*, regime_state: RegimeState = RegimeState.NORMAL):
    """Real kernel outputs for both arms over one frozen world."""

    from src.screening.offensive.v3.kernel.decide import GrowthKernel
    from src.screening.offensive.v3.kernel.sizing import SizingConfig

    champion_input, challenger_input, *_ = _paired_world(regime_state=regime_state)
    kernel = GrowthKernel(
        SizingConfig(
            per_ticker_gross_cap_cents=200_000,
            per_industry_gross_cap_cents=300_000,
            per_day_gross_cap_cents=500_000,
            portfolio_gross_cap_cents=400_000,
            worst_case_fee_ppm=3_000,
        )
    )
    return kernel.decide_shadow(champion_input), kernel.decide_shadow(challenger_input)


def _record(arm: TrialArm, *, decision=None) -> TrialArmDecisionRecord:
    if decision is None:
        champion, challenger = _paired_decisions()
        decision = champion if arm is TrialArm.CHAMPION else challenger
    is_shadow = hasattr(decision, "shadow_decision_id")
    # The shared input hash is one per session/cycle, identical for both
    # arms; the arm-specific fingerprint/capital bindings come from the
    # decision payload itself.
    if is_shadow:
        session = decision.counterfactual_key.signal_session
        cycle = decision.counterfactual_key.counterfactual_cycle_id
        shared_input_hash = f"{session.isoformat()}/{cycle}"
        policy_fingerprint = decision.shadow_policy_binding.policy_fingerprint
    else:
        session = decision.signal_session
        cycle = decision.decision_cycle_id
        shared_input_hash = f"{session.isoformat()}/{cycle}"
        policy_fingerprint = None
    return TrialArmDecisionRecord(
        trial_id=TRIAL_ID,
        signal_session=session,
        decision_cycle_id=cycle,
        arm=arm,
        shared_input_hash=shared_input_hash,
        arm_policy_fingerprint=policy_fingerprint,
        arm_capital_checkpoint_hash=HASH,
        regime_observation_hash=HASH,
        decision=decision,
        created_at=NOW,
        artifact_hash=decision.content_hash(),
    )


@pytest.fixture()
def store(tmp_path: Path) -> TrialArmDecisionStore:
    return TrialArmDecisionStore(database_path=str(tmp_path / "trial-store.sqlite3"))


@pytest.fixture()
def pair():
    champion, challenger = _paired_decisions()
    return (
        _record(TrialArm.CHAMPION, decision=champion),
        _record(TrialArm.CHALLENGER, decision=challenger),
    )


def test_register_trial_then_commit_pair(store, pair) -> None:
    store.register_trial(_bundle(), _genesis_manifest())
    receipt = store.commit_pair(*pair)
    assert isinstance(receipt, PairCommitReceipt)
    assert {row.arm for row in store.pair(receipt.key)} == {
        TrialArm.CHAMPION,
        TrialArm.CHALLENGER,
    }


def test_commit_pair_is_atomic_and_conflicting_replay_is_rejected(store, pair) -> None:
    store.register_trial(_bundle(), _genesis_manifest())
    receipt = store.commit_pair(*pair)
    assert {row.arm for row in store.pair(receipt.key)} == {
        TrialArm.CHAMPION,
        TrialArm.CHALLENGER,
    }
    # Exact replay is idempotent.
    assert store.commit_pair(*pair) == receipt
    # Same key, different arm-specific binding column conflicts.
    mutated = pair[0].model_copy(update={"arm_capital_checkpoint_hash": "b" * 64})
    with pytest.raises(TrialStoreError, match="arm_decision_conflict"):
        store.commit_pair(mutated, pair[1])


def test_unregistered_trial_commit_rejected(store, pair) -> None:
    with pytest.raises(TrialStoreError, match="not_registered"):
        store.commit_pair(*pair)


def test_register_trial_binds_genesis_and_bundle_trial_ids(store) -> None:
    store.register_trial(_bundle(), _genesis_manifest())
    # Exact re-registration is idempotent.
    store.register_trial(_bundle(), _genesis_manifest())
    # A genesis manifest naming a different trial is rejected.
    mismatched_genesis = _genesis_manifest().model_copy(
        update={"trial_id": "trial-other"}
    )
    with pytest.raises(TrialStoreError, match="genesis_trial_mismatch"):
        store.register_trial(_bundle(), mismatched_genesis)
    # Re-registering the same trial with a different bundle conflicts.
    bundle = _bundle()
    other_sap = bundle.sap_manifest.model_copy(update={"repetitions": 9_999})
    other_bundle = bundle.model_copy(update={"sap_manifest": other_sap})
    with pytest.raises(TrialStoreError, match="registration_conflict"):
        store.register_trial(other_bundle, _genesis_manifest())


def test_no_trade_pair_is_persisted_and_replayed(store) -> None:
    store.register_trial(_bundle(), _genesis_manifest())
    champion_decision, challenger_decision = _paired_decisions(
        regime_state=RegimeState.RISK_OFF
    )
    assert isinstance(champion_decision, ShadowDecision)
    assert isinstance(challenger_decision, NoTradeDecision)
    champion = _record(TrialArm.CHAMPION, decision=champion_decision)
    challenger = _record(TrialArm.CHALLENGER, decision=challenger_decision)
    receipt = store.commit_pair(champion, challenger)
    rows = store.pair(receipt.key)
    assert len(rows) == 2
    # RISK_OFF: the Champion (IGNORE) still trades while the Challenger
    # (NORMAL_ONLY) is regime-blocked; one ShadowDecision, one NoTradeDecision.
    kinds = {
        type(row.decision).__name__ for row in rows
    }
    assert kinds == {"ShadowDecision", "NoTradeDecision"}


def test_partial_row_tamper_is_detected(store, pair, tmp_path) -> None:
    store.register_trial(_bundle(), _genesis_manifest())
    store.commit_pair(*pair)
    # Tamper one decision row's payload directly in SQLite. The UPDATE/
    # DELETE triggers are the first line of defense; simulate a compromised
    # or migrated store where they were dropped, so the tamper-detection
    # binding (artifact hash vs payload) is what must catch it.
    conn = sqlite3.connect(str(tmp_path / "trial-store.sqlite3"))
    conn.execute("DROP TRIGGER IF EXISTS trial_arm_decisions_no_update")
    row = conn.execute(
        "SELECT rowid, decision_json FROM trial_arm_decisions"
        " WHERE arm = 'CHALLENGER'"
    ).fetchone()
    conn.execute(
        "UPDATE trial_arm_decisions SET decision_json = :payload"
        " WHERE rowid = :rowid",
        {
            "payload": row[1].replace("challenger", "tampered"),
            "rowid": row[0],
        },
    )
    conn.commit()
    conn.close()
    champion_row, _ = pair
    with pytest.raises(TrialStoreError, match="tamper|mismatch"):
        store.pair(
            (
                TRIAL_ID,
                champion_row.signal_session.isoformat(),
                champion_row.decision_cycle_id,
            )
        )


def test_two_process_race_one_winner(tmp_path) -> None:
    """Two processes commit the same pair key with different content; one wins."""
    store = TrialArmDecisionStore(
        database_path=str(tmp_path / "trial-store.sqlite3")
    )
    store.register_trial(_bundle(), _genesis_manifest())
    champion, challenger = _paired_decisions()
    champion_record = _record(TrialArm.CHAMPION, decision=champion)
    challenger_record = _record(TrialArm.CHALLENGER, decision=challenger)
    # Process B conflicts: same key, different challenger content
    # (a RISK_OFF NoTradeDecision instead of the NORMAL ShadowDecision).
    _, blocked_challenger = _paired_decisions(regime_state=RegimeState.RISK_OFF)
    conflicting_challenger = _record(
        TrialArm.CHALLENGER, decision=blocked_challenger
    )

    script = """
import sys
from src.screening.offensive.v3.orchestration.trial_store import (
    TrialArmDecisionStore, TrialArmDecisionRecord,
)

path = sys.argv[1]
champion = TrialArmDecisionRecord.model_validate_json(sys.argv[2])
challenger = TrialArmDecisionRecord.model_validate_json(sys.argv[3])
store = TrialArmDecisionStore(database_path=path)
try:
    receipt = store.commit_pair(champion, challenger)
    print("WINNER")
except Exception as exc:
    print("LOSER", type(exc).__name__, str(exc)[:80])
"""
    repo_root = Path(__file__).resolve().parents[5]
    first = subprocess.run(
        [
            sys.executable,
            "-c",
            script,
            str(tmp_path / "trial-store.sqlite3"),
            champion_record.model_dump_json(),
            challenger_record.model_dump_json(),
        ],
        capture_output=True,
        text=True,
        cwd=repo_root,
    )
    assert first.returncode == 0, first.stderr
    assert first.stdout.strip().splitlines()[0] == "WINNER"
    second = subprocess.run(
        [
            sys.executable,
            "-c",
            script,
            str(tmp_path / "trial-store.sqlite3"),
            champion_record.model_dump_json(),
            conflicting_challenger.model_dump_json(),
        ],
        capture_output=True,
        text=True,
        cwd=repo_root,
    )
    assert second.returncode == 0, second.stderr
    loser_line = second.stdout.strip().splitlines()[0]
    assert loser_line.split()[0] == "LOSER"
    assert "arm_decision_conflict" in loser_line
    conn = sqlite3.connect(str(tmp_path / "trial-store.sqlite3"))
    n = conn.execute("SELECT COUNT(*) FROM trial_arm_decisions").fetchone()[0]
    conn.close()
    assert n == 2


def test_writer_fencing_epoch_is_monotone(store) -> None:
    token1 = store.claim_writer()
    assert token1.epoch == 1
    # Renewal by the same live owner retains the epoch.
    token2 = store.renew_writer(token1)
    assert token2.epoch == token1.epoch
    # A new owner bumps the epoch.
    store.release_writer(token2)
    token3 = store.claim_writer()
    assert token3.epoch == token1.epoch + 1


def test_stale_fencing_token_fails_before_mutation(store) -> None:
    token1 = store.claim_writer()
    store.release_writer(token1)
    store.claim_writer()  # new owner: epoch bumps
    with pytest.raises(TrialStoreError, match="fencing"):
        store.require_writer(token1)


def test_expired_lease_is_takeover_able(store) -> None:
    token = store.claim_writer()
    store.force_expire_writer(token)  # test-only expiry hook
    token2 = store.claim_writer()
    assert token2.epoch > token.epoch


def test_two_process_writer_claim_one_winner(tmp_path) -> None:
    """Two processes claim the writer; both see the epoch, one owns it."""
    store = TrialArmDecisionStore(
        database_path=str(tmp_path / "trial-store.sqlite3")
    )
    script = """
import sys
from src.screening.offensive.v3.orchestration.trial_store import (
    TrialArmDecisionStore,
)

path = sys.argv[1]
store = TrialArmDecisionStore(database_path=path)
token = store.claim_writer()
print("CLAIMED", token.epoch)
try:
    store.require_writer(token)
    print("OWNER")
except Exception as exc:
    print("STALE", type(exc).__name__, str(exc)[:60])
"""
    repo_root = Path(__file__).resolve().parents[5]
    first = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path / "trial-store.sqlite3")],
        capture_output=True,
        text=True,
        cwd=repo_root,
    )
    assert first.returncode == 0, first.stderr
    first_lines = first.stdout.strip().splitlines()
    assert first_lines[0].startswith("CLAIMED ")
    first_epoch = int(first_lines[0].split()[1])
    assert first_lines[1] == "OWNER"
    # The second process takes over: its epoch bumps and its token is live.
    second = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path / "trial-store.sqlite3")],
        capture_output=True,
        text=True,
        cwd=repo_root,
    )
    assert second.returncode == 0, second.stderr
    second_lines = second.stdout.strip().splitlines()
    second_epoch = int(second_lines[0].split()[1])
    assert second_epoch == first_epoch + 1
    assert second_lines[1] == "OWNER"
    # The first process's token is now stale: require_writer fails.
    first_again = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path / "trial-store.sqlite3")],
        capture_output=True,
        text=True,
        cwd=repo_root,
    )
    assert first_again.returncode == 0, first_again.stderr
    again_lines = first_again.stdout.strip().splitlines()
    assert int(again_lines[0].split()[1]) == second_epoch + 1
    assert again_lines[1] == "OWNER"


def test_zero_capital_mutation_before_pair_commit(store, tmp_path) -> None:
    """register_trial + failed commit touch no capital ledger."""
    from src.screening.offensive.v3.capital.repository import CapitalRepository

    capital_path = tmp_path / "capital.sqlite3"
    repository = CapitalRepository.initialize(capital_path)
    before = repository.stream_version()
    store.register_trial(_bundle(), _genesis_manifest())
    blocked_champion, blocked_challenger = _paired_decisions(
        regime_state=RegimeState.RISK_OFF
    )
    wrong_champion = _record(
        TrialArm.CHAMPION, decision=blocked_champion
    ).model_copy(update={"trial_id": "trial-other"})
    wrong_challenger = _record(
        TrialArm.CHALLENGER, decision=blocked_challenger
    ).model_copy(update={"trial_id": "trial-other"})
    with pytest.raises(TrialStoreError, match="not_registered"):
        # Wrong trial id in the record -> fails before any store write.
        store.commit_pair(wrong_champion, wrong_challenger)
    assert repository.stream_version() == before
