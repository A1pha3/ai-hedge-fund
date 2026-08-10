"""Plan Task 11 RED: ForwardPairedTrialRunner + terminal SessionSpine semantics.

The runner is the thin forward orchestrator of one paired shadow trial: it
freezes the trusted clock once per signal session, reads the sealed bundle
and one canonical regime observation before cutoff, runs the BTST producer
exactly once, calls ``decide_shadow`` exactly once per arm over the same
frozen shared input/time, commits one pair, records one session status, and
only then reserves both decisions. It contains no classifier, ranking,
sizing, fee, fill, NAV, statistical, signing, activation, or broker logic.

SessionSpine non-cancel statuses become exact-idempotent terminal facts:
an identical status retry is quiet, a conflicting non-cancel status fails,
only a signed calendar revision may supersede them with
``SESSION_CANCELLED``, and cancelled is terminal.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

import pytest

from src.screening.offensive.v3.contracts import ExecutionMode
from src.screening.offensive.v3.contracts.evidence import EvidenceRecord
from src.screening.offensive.v3.contracts.regime import (
    RegimeObservation,
    RegimeObservationReason,
    RegimeSourceRevision,
    RegimeState,
)
from src.screening.offensive.v3.contracts.trial import TrialArm
from src.screening.offensive.v3.evidence.regime import RegimeObservationPublisher
from src.screening.offensive.v3.evidence.session_spine import (
    CalendarRevision,
    SessionEnrollment,
    SessionSpine,
    SessionSpineError,
    SessionStatus,
)
from src.screening.offensive.v3.kernel.shadow import economic_shadow_projection
from src.screening.offensive.v3.orchestration.paired_trial import (  # RED target
    ForwardPairedTrialRunner,
    PairedSignalReceipt,
    PairedTrialRunnerError,
    SignalSessionRequest,
    classify_pair_session,
)

UTC = timezone.utc
TRIAL_ID = "trial-regime-001"
PROGRAM = "research.btst.regime"
PORTFOLIO = "paper-v3"
HASH = "a" * 64
SIGNAL_DATE = date(2026, 8, 5)
CLOSE = datetime(2026, 8, 5, 15, 0, tzinfo=UTC)
CUTOFF = CLOSE - timedelta(minutes=5)
ENROLLMENT_START = datetime(2026, 8, 1, 0, 0, tzinfo=UTC)
ENROLLMENT_END = datetime(2026, 8, 31, 0, 0, tzinfo=UTC)


class _Clock:
    def __init__(self, start: datetime) -> None:
        self._moment = start
        self.calls = 0

    def __call__(self) -> datetime:
        self.calls += 1
        return self._moment

    def freeze(self, at: datetime) -> None:
        self._moment = at


class _CountingProducer:
    """The runner must call the producer exactly once per session."""

    def __init__(self, records: tuple | None = None) -> None:
        self.calls = 0
        self.records = records if records is not None else (_selected_record(),)

    def produce_and_publish(self, snapshot) -> tuple:
        self.calls += 1
        return self.records


def _selected_record() -> EvidenceRecord:
    """One SELECTED SignalEvidence record; the runner's shared candidate."""

    from src.screening.offensive.v3.contracts import SUPPORTED_SCHEMA_MAJOR
    from src.screening.offensive.v3.contracts.base import SignalStage
    from src.screening.offensive.v3.contracts.evidence import (
        EvidenceScope,
        SignalEvidence,
    )

    envelope = SignalEvidence(
        evidence_id="btst:sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb:300001:btst_breakout:SELECTED",
        subject_scope=EvidenceScope.STRATEGY_LINEAGE,
        subject_producer="btst",
        family_id="btst:sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        strategy_semver="0.1.0",
        behavior_fingerprint=HASH,
        policy_epoch=1,
        execution_version="btst.funnel.v1",
        cost_version="cn-a-share-costs.v1",
        effective_at=CUTOFF,
        provider_published_at=CUTOFF,
        observed_at=CUTOFF,
        available_at=CUTOFF + timedelta(days=1),
        mode=ExecutionMode.RESEARCH_RECONSTRUCTION,
        source_authority="btst.producer",
        payload_content_hash=HASH,
        schema_major=SUPPORTED_SCHEMA_MAJOR,
        evidence_kind="signal",
        stage=SignalStage.SELECTED,
    )
    return EvidenceRecord[SignalEvidence](
        evidence=envelope,
        ingested_at=CUTOFF,
        commit_sequence=1,
        revision=1,
        supersedes_revision=None,
        active_revision=1,
    )


class _CountingKernel:
    """The runner must call decide_shadow exactly once per arm."""

    def __init__(self, decisions: dict[TrialArm, object]) -> None:
        self.calls_by_arm = {TrialArm.CHAMPION: 0, TrialArm.CHALLENGER: 0}
        self.decisions = decisions

    def decide_shadow(self, shadow_input) -> object:
        self.calls_by_arm[shadow_input.shared.trial_arm] += 1
        return self.decisions[shadow_input.shared.trial_arm]


class _RegimeReader:
    """One injected regime observation; counts PIT reads."""

    def __init__(self, observation: RegimeObservation) -> None:
        self.observation = observation
        self.calls = 0

    def active(self, evidence_id: str, cutoff: datetime):
        self.calls += 1
        return type(
            "Active",
            (),
            {
                "record": None,
                "observation": self.observation,
                "observation_hash": HASH,
            },
        )()


class _MissingRegimeReader(_RegimeReader):
    def active(self, evidence_id: str, cutoff: datetime):
        self.calls += 1
        from src.screening.offensive.v3.evidence.regime import (
            RegimeEvidenceError,
        )

        raise RegimeEvidenceError(
            "evidence_not_committed_before_cutoff",
            "no active regime observation at the cutoff",
        )


class _BundleReader:
    """One sealed bundle; counts reads."""

    def __init__(self, bundle) -> None:
        self.bundle = bundle
        self.calls = 0

    def __call__(self, trial_id: str):
        self.calls += 1
        return self.bundle


class _GovernanceBundleReader(_BundleReader):
    def __call__(self, trial_id: str):
        self.calls += 1
        if trial_id != TRIAL_ID:
            raise LookupError(f"unknown trial: {trial_id}")
        return self.bundle


class _CapitalReader:
    """One frozen capital checkpoint; identical for both arms."""

    def __init__(self, snapshot) -> None:
        self.snapshot = snapshot
        self.calls = 0

    def __call__(self, portfolio_id: str, as_of: datetime):
        self.calls += 1
        return self.snapshot


# -- decisions ---------------------------------------------------------------


def _champion_decision():
    """A minimal schema-3 ShadowDecision-shaped object for pair commits."""
    from src.screening.offensive.v3.contracts import ArtifactKind
    from src.screening.offensive.v3.contracts.decision import (
        CounterfactualDecisionKey,
        ShadowDecision,
        ShadowIssuerBinding,
        ShadowOrderLine,
        ShadowStageBinding,
    )
    from src.screening.offensive.v3.contracts.trial import (
        BaselineShadowPolicyBinding,
        ShadowPolicySourceKind,
    )

    trial_manifest_hash = HASH
    sap_manifest_hash = HASH
    binding = BaselineShadowPolicyBinding(
        source_kind=ShadowPolicySourceKind.BASELINE_POLICY_ACTIVATION,
        baseline_policy_activation_hash=HASH,
        policy_snapshot_hash=HASH,
        policy_fingerprint=HASH,
    )
    stage_binding = ShadowStageBinding(
        research_program_id=PROGRAM,
        economic_lineage_id="btst-regime-paired",
        stage_id="stage-1",
        trial_id=TRIAL_ID,
        stage_manifest_hash=trial_manifest_hash,
    )
    line = ShadowOrderLine(
        shadow_line_id="shadow-line-cand-1",
        security_id="300001.SZ",
        producer_namespace="btst",
        family_id="btst.limit-up-breakout",
        economic_lineage_id="btst-regime-paired",
        research_program_id=PROGRAM,
        stage_id="stage-1",
        trial_id=TRIAL_ID,
        stage_manifest_hash=trial_manifest_hash,
        evidence_id="btst:sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb:300001:btst_breakout:SELECTED",
        evidence_artifact_hash=HASH,
        evidence_payload_hash=HASH,
        target_quantity_units=100,
        lot_size_units=100,
        lot_rule_version="cn-board-lot.v1",
        order_type="LIMIT",
        limit_price_cents=1000,
        worst_case_price_cents=1000,
        price_boundary_version="cn-price-limit.v1",
        time_in_force="OPEN_AUCTION",
        exit_session_ordinal=10,
        estimated_fee_cents=0,
        estimated_cash_reserve_cents=100_000,
        cost_assumption_version="cn-a-share-costs.v1",
        execution_assumption_version="t0-close-t1-open-t10-open.v1",
        target_exit_session=SIGNAL_DATE + timedelta(days=10),
    )
    return ShadowDecision(
        artifact_kind=ArtifactKind.SHADOW_DECISION,
        artifact_namespace="growth-kernel.shadow.v2",
        schema_major=3,
        shadow_decision_id=f"shadow-{SIGNAL_DATE.isoformat()}-champion",
        counterfactual_key=CounterfactualDecisionKey(
            portfolio_id=PORTFOLIO,
            signal_session=SIGNAL_DATE,
            counterfactual_cycle_id=f"daily-action-{SIGNAL_DATE.isoformat()}",
        ),
        portfolio_id=PORTFOLIO,
        mode=ExecutionMode.DAILY_BAR_PROXY,
        target_entry_session=SIGNAL_DATE + timedelta(days=1),
        producer_namespace="btst",
        family_id="btst.limit-up-breakout",
        research_program_id=PROGRAM,
        economic_lineage_id="btst-regime-paired",
        stage_id="stage-1",
        trial_id=TRIAL_ID,
        shadow_policy_binding=binding,
        policy_epoch=1,
        evidence_set_merkle_root=HASH,
        shadow_stage_binding=stage_binding,
        counterfactual_lines=(line,),
        cost_assumption_version="cn-a-share-costs.v1",
        execution_assumption_version="t0-close-t1-open-t10-open.v1",
        created_at=CUTOFF,
        available_at=CUTOFF,
        execution_authority="NONE",
        issuer_binding=ShadowIssuerBinding(
            issuer_id="growth-kernel.shadow.service",
            key_id="shadow-key-1",
            capability_artifact_kind=ArtifactKind.SHADOW_DECISION,
            capability_namespace="growth-kernel.shadow.v2",
            capability_mode=ExecutionMode.DAILY_BAR_PROXY,
            capability_schema_major=3,
            capability_version="growth-kernel-shadow.v2",
            capability_scope=f"portfolio:{PORTFOLIO}",
            verification_result="VALID",
            verified_at=CUTOFF,
            valid_until=CUTOFF + timedelta(days=1),
            trust_bundle_hash=HASH,
            registry_epoch=1,
        ),
    )


def _challenger_decision():
    """The NORMAL-blocked challenger: a typed NoTradeDecision."""
    from src.screening.offensive.v3.kernel.models import (
        BlockReason,
        NoTradeDecision,
    )

    return NoTradeDecision(
        portfolio_id=PORTFOLIO,
        signal_session=SIGNAL_DATE,
        decision_cycle_id=f"daily-action-{SIGNAL_DATE.isoformat()}",
        reason=BlockReason.REGIME_ADMISSION_BLOCKED,
    )


# -- regime + spine ----------------------------------------------------------


def _regime_observation(state: RegimeState) -> RegimeObservation:
    reason = (
        RegimeObservationReason.CLASSIFIED
        if state is not RegimeState.UNKNOWN
        else RegimeObservationReason.UNRECOGNIZED_RAW_STATE
    )
    raw = None if state is RegimeState.UNKNOWN else state.value
    return RegimeObservation(
        signal_session=SIGNAL_DATE,
        state=state,
        reason=reason,
        raw_state=raw,
        source_revisions=(
            RegimeSourceRevision(
                evidence_id="regime:csi300:1.0",
                revision=1,
                artifact_hash=HASH,
            ),
        ),
        effective_at=CUTOFF,
        provider_published_at=CUTOFF,
        observed_at=CUTOFF,
        classifier_semver="1.0.0",
        behavior_fingerprint=HASH,
        input_schema_hash=HASH,
    )


def _enroll(spine: SessionSpine, *sessions: date) -> None:
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


class _CountingReserve:
    """The runner must reserve both decisions exactly once after the pair
    commit (the final side-effect step)."""

    def __init__(self) -> None:
        self.calls = 0
        self.pair_keys: list[tuple[str, str, str]] = []

    def __call__(self, pair_key: tuple[str, str, str]) -> None:
        self.calls += 1
        self.pair_keys.append(pair_key)


class _Rig:
    """One registered store + spine + injected pure dependencies."""

    def __init__(
        self,
        tmp_path: Path,
        *,
        regime_state: RegimeState = RegimeState.NORMAL,
        producer_records: tuple | None = None,
    ) -> None:
        from tests.offensive.v3.services.test_btst_producer_api import (
            _World,
        )

        self.world = _World(tmp_path / "evidence")
        # The runner's trusted clock is frozen exactly once per session; the
        # spine's recorded_at is a separate wall clock.
        self.clock = _Clock(_frozen_trusted_at())
        self.spine_clock = _Clock(CLOSE)
        self.store_path = tmp_path / "trial.sqlite3"
        self.store = _new_store(self.store_path, tmp_path)
        self.store.register_trial(self._bundle(), self._genesis_manifest())
        self.spine = SessionSpine(
            database_path=str(tmp_path / "spine.sqlite3"),
            clock=self.spine_clock,
        )
        # The forward calendar is enrolled before any observation.
        _enroll(self.spine, SIGNAL_DATE)
        self.bundle_reader = _BundleReader(self._bundle())
        self.regime_reader = _RegimeReader(_regime_observation(regime_state))
        self.producer = _CountingProducer(producer_records)
        self.kernel = _CountingKernel(
            {
                TrialArm.CHAMPION: _champion_decision(),
                TrialArm.CHALLENGER: _challenger_decision(),
            }
        )
        self.capital_reader = _CapitalReader(self._capital())
        self.reserve = _CountingReserve()
        self.runner = _new_runner(self)

    def _bundle(self):
        from tests.offensive.v3.execution.test_shadow_proxy_entry import (
            _bundle,
        )

        return _bundle()

    def _genesis_manifest(self):
        from tests.offensive.v3.execution.test_shadow_proxy_entry import (
            _genesis_manifest,
        )

        return _genesis_manifest()

    def _capital(self):
        from tests.offensive.v3.kernel.test_shadow_kernel import (
            _capital_checkpoint,
        )

        return _capital_checkpoint()

    def request(self) -> SignalSessionRequest:
        return SignalSessionRequest(
            trial_id=TRIAL_ID,
            signal_session=SIGNAL_DATE,
        )

    def decision_cycle_id(self) -> str:
        return f"daily-action-{SIGNAL_DATE.isoformat()}"

    def pair_key(self) -> tuple[str, str, str]:
        return (TRIAL_ID, SIGNAL_DATE.isoformat(), self.decision_cycle_id())

    def arms(self) -> tuple[TrialArm, TrialArm]:
        return (TrialArm.CHAMPION, TrialArm.CHALLENGER)


def _frozen_trusted_at() -> datetime:
    # Inside the shared bundle's enrollment window [2026-08-06, 2026-09-05).
    return datetime(2026, 8, 20, 15, 0, tzinfo=UTC)


def _new_store(path: Path, tmp_path: Path):
    from src.screening.offensive.v3.orchestration.trial_store import (
        TrialArmDecisionStore,
    )

    return TrialArmDecisionStore(database_path=str(path))


def _new_runner(rig: _Rig) -> ForwardPairedTrialRunner:
    return ForwardPairedTrialRunner(
        trial_id=TRIAL_ID,
        research_program_id=PROGRAM,
        portfolio_id=PORTFOLIO,
        decision_store=rig.store,
        spine=rig.spine,
        bundle_reader=rig.bundle_reader,
        regime_reader=rig.regime_reader,
        producer=rig.producer,
        kernel=rig.kernel,
        capital_reader=rig.capital_reader,
        clock=rig.clock,
        reserve_pair=rig.reserve,
    )


@pytest.fixture()
def rig(tmp_path: Path) -> _Rig:
    return _Rig(tmp_path)


# =============================================================================
# Step 1: orchestration-count tests (one healthy signal session)
# =============================================================================


def _by_arm(rig: _Rig, receipt: PairedSignalReceipt):
    """The committed pair read back, keyed by arm (the store's pair() returns
    rows in alphabetical arm order, so lookups must be by arm)."""

    champion, challenger = rig.store.pair(receipt.pair_key)
    rows = {row.arm: row for row in (champion, challenger)}
    return rows[TrialArm.CHAMPION], rows[TrialArm.CHALLENGER]


def test_runner_freezes_shared_work_once(rig: _Rig) -> None:
    receipt = rig.runner.decide_signal_session(rig.request())
    assert isinstance(receipt, PairedSignalReceipt)
    assert receipt.trial_id == TRIAL_ID
    assert receipt.signal_session == SIGNAL_DATE
    assert receipt.pair_key == rig.pair_key()
    # One frozen trusted time; one regime read; one producer call; one kernel
    # call per arm; one committed pair.
    assert rig.clock.calls == 1
    assert rig.regime_reader.calls == 1
    assert rig.producer.calls == 1
    assert rig.kernel.calls_by_arm == {
        TrialArm.CHAMPION: 1,
        TrialArm.CHALLENGER: 1,
    }
    champion, challenger = _by_arm(rig, receipt)
    assert champion.shared_input_hash == challenger.shared_input_hash
    assert champion.regime_observation_hash == challenger.regime_observation_hash
    assert rig.spine.status(PROGRAM, SIGNAL_DATE) is SessionStatus.RUN


# =============================================================================
# Step 3: failure order — side effects only after the pair commit
# =============================================================================


def test_pair_computation_failure_yields_zero_side_effects(rig: _Rig) -> None:
    """A pair-computation failure (regime read, producer, kernel) must leave
    zero cycle capital side effects: no pair, no status, no reserve."""

    rig.regime_reader = _MissingRegimeReader(_regime_observation(RegimeState.NORMAL))
    rig.runner = _new_runner(rig)
    with pytest.raises(PairedTrialRunnerError):
        rig.runner.decide_signal_session(rig.request())
    # No pair, no status, no reserve call.
    with pytest.raises(Exception):
        rig.store.pair(rig.pair_key())
    assert rig.spine.status(PROGRAM, SIGNAL_DATE) is None
    assert rig.reserve.calls == 0


def test_pair_commit_then_reserve_crash_replays_stable_ids(rig: _Rig) -> None:
    """A crash after the pair commit but before the reserve replays with the
    same stable pair: the kernel and producer are not re-run, the status is
    completed, and the reserve is invoked exactly once more (idempotent)."""

    from src.screening.offensive.v3.orchestration.paired_trial import (
        ForwardPairedTrialRunner,
    )

    class _CrashReserve:
        def __init__(self, rig: _Rig) -> None:
            self.rig = rig
            self.calls = 0

        def __call__(self, pair_key: tuple[str, str, str]) -> None:
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("simulated crash after pair commit, before reserve")

    crashing = _CrashReserve(rig)
    crashing_runner = ForwardPairedTrialRunner(
        trial_id=TRIAL_ID,
        research_program_id=PROGRAM,
        portfolio_id=PORTFOLIO,
        decision_store=rig.store,
        spine=rig.spine,
        bundle_reader=rig.bundle_reader,
        regime_reader=rig.regime_reader,
        producer=rig.producer,
        kernel=rig.kernel,
        capital_reader=rig.capital_reader,
        clock=rig.clock,
        reserve_pair=crashing,
    )
    with pytest.raises(RuntimeError, match="simulated crash"):
        crashing_runner.decide_signal_session(rig.request())
    # The pair committed; the status may or may not have landed, the reserve
    # did not complete.
    pair = rig.store.pair(rig.pair_key())
    assert len(pair) == 2
    # Replay: the pair is exact-validated, kernels are skipped, the reserve
    # completes. The producer/kernel are not re-run.
    rig.producer.calls = 0
    rig.kernel.calls_by_arm = {TrialArm.CHAMPION: 0, TrialArm.CHALLENGER: 0}
    receipt = rig.runner.decide_signal_session(rig.request())
    assert receipt.pair_key == rig.pair_key()
    assert rig.producer.calls == 0
    assert rig.kernel.calls_by_arm == {TrialArm.CHAMPION: 0, TrialArm.CHALLENGER: 0}
    assert rig.reserve.calls == 1
    assert rig.spine.status(PROGRAM, SIGNAL_DATE) is SessionStatus.RUN


def test_expired_writer_lease_blocks(rig: _Rig) -> None:
    """The runner's reserve path is lease-fenced: a stale writer token fails
    before any capital mutation (the pair itself is already durable)."""

    def fenced_reserve(pair_key: tuple[str, str, str]) -> None:
        from src.screening.offensive.v3.orchestration.trial_store import (
            TrialStoreError,
        )

        raise TrialStoreError(
            "fencing",
            "writer token is stale; the epoch moved on",
        )

    fenced_runner = _new_runner(rig)
    from src.screening.offensive.v3.orchestration.paired_trial import (
        ForwardPairedTrialRunner,
    )

    fenced_runner = ForwardPairedTrialRunner(
        trial_id=TRIAL_ID,
        research_program_id=PROGRAM,
        portfolio_id=PORTFOLIO,
        decision_store=rig.store,
        spine=rig.spine,
        bundle_reader=rig.bundle_reader,
        regime_reader=rig.regime_reader,
        producer=rig.producer,
        kernel=rig.kernel,
        capital_reader=rig.capital_reader,
        clock=rig.clock,
        reserve_pair=fenced_reserve,
    )
    with pytest.raises(Exception, match="fencing"):
        fenced_runner.decide_signal_session(rig.request())
    # The pair committed before the fencing failure; the session is recorded.
    assert len(rig.store.pair(rig.pair_key())) == 2


def test_reserve_not_wired_fails_loudly(rig: _Rig) -> None:
    """A missing reserve wiring must fail loudly after the commit, never
    silently proceed without T0 worst-case reserves."""

    from src.screening.offensive.v3.orchestration.paired_trial import (
        ForwardPairedTrialRunner,
    )

    unwired = ForwardPairedTrialRunner(
        trial_id=TRIAL_ID,
        research_program_id=PROGRAM,
        portfolio_id=PORTFOLIO,
        decision_store=rig.store,
        spine=rig.spine,
        bundle_reader=rig.bundle_reader,
        regime_reader=rig.regime_reader,
        producer=rig.producer,
        kernel=rig.kernel,
        capital_reader=rig.capital_reader,
        clock=rig.clock,
        reserve_pair=None,
    )
    with pytest.raises(PairedTrialRunnerError) as excinfo:
        unwired.decide_signal_session(rig.request())
    assert excinfo.value.code == "reserve_not_wired"


def test_divergent_replay_never_recomputes_alternate_proposal(rig: _Rig) -> None:
    """After a pair exists, a re-run never recomputes an alternate proposal:
    the runner exact-validates the existing pair and skips the producer and
    kernels entirely — even when the underlying inputs would diverge."""

    receipt = rig.runner.decide_signal_session(rig.request())
    pair_key = receipt.pair_key
    # Replay with a different candidate set and a different regime: the
    # runner must not consult them at all; it converges on the existing pair.
    rig.producer.records = ()
    rig.producer.calls = 0
    rig.regime_reader.calls = 0
    replay = rig.runner.decide_signal_session(rig.request())
    assert replay.pair_key == pair_key
    assert rig.producer.calls == 0
    assert rig.regime_reader.calls == 0
    assert len(rig.store.pair(pair_key)) == 2
    # The store itself latches a same-key/different-content commit: a direct
    # divergent re-commit (a bug in a caller that bypasses the replay path)
    # is a typed breach.
    champion, challenger = _by_arm(rig, receipt)
    from src.screening.offensive.v3.orchestration.trial_store import (
        TrialArmDecisionRecord,
    )

    divergent = TrialArmDecisionRecord(
        trial_id=TRIAL_ID,
        signal_session=SIGNAL_DATE,
        decision_cycle_id=rig.decision_cycle_id(),
        arm=TrialArm.CHAMPION,
        shared_input_hash="d" * 64,
        arm_policy_fingerprint="e" * 64,
        arm_capital_checkpoint_hash="0" * 64,
        regime_observation_hash="f" * 64,
        decision=_champion_decision(),
        created_at=_INSIDE,
        artifact_hash="0" * 64,
    )
    with pytest.raises(Exception, match="arm_decision_conflict|shared_input_mismatch"):
        rig.store.commit_pair(divergent, challenger)


def test_missing_regime_fails_before_any_commit(rig: _Rig) -> None:
    """A missing canonical regime observation is an operational failure that
    happens before the producer, the kernel, the pair commit, or the status."""

    rig.regime_reader = _MissingRegimeReader(_regime_observation(RegimeState.NORMAL))
    rig.runner = _new_runner(rig)
    with pytest.raises(PairedTrialRunnerError) as excinfo:
        rig.runner.decide_signal_session(rig.request())
    assert excinfo.value.code == "regime_observation_missing"
    assert rig.producer.calls == 0
    assert rig.kernel.calls_by_arm == {TrialArm.CHAMPION: 0, TrialArm.CHALLENGER: 0}
    assert rig.spine.status(PROGRAM, SIGNAL_DATE) is None


def test_unenrolled_session_rejected_before_any_work(rig: _Rig) -> None:
    """A session outside the enrolled calendar fails before any work."""

    outside = date(2026, 1, 1)
    with pytest.raises(PairedTrialRunnerError) as excinfo:
        rig.runner.decide_signal_session(
            SignalSessionRequest(trial_id=TRIAL_ID, signal_session=outside)
        )
    assert excinfo.value.code == "session_not_enrolled"
    assert rig.producer.calls == 0


# =============================================================================
# Step 2: status classification
# =============================================================================

#: The decision cutoff of SIGNAL_DATE (15:00 UTC close); a session whose
#: cutoff has passed with no pair/status becomes NO_RUN.
_AFTER_CUTOFF = datetime(2026, 9, 6, 9, 0, tzinfo=UTC)
#: A trusted clock moment inside the trial's enrollment window.
_INSIDE = datetime(2026, 8, 20, 15, 0, tzinfo=UTC)


def test_pair_run_with_challenger_regime_blocked(rig: _Rig) -> None:
    from src.screening.offensive.v3.contracts.decision import ShadowDecision

    receipt = rig.runner.decide_signal_session(rig.request())
    champion, challenger = _by_arm(rig, receipt)
    assert isinstance(champion.decision, ShadowDecision)
    assert not hasattr(challenger.decision, "counterfactual_lines")
    assert rig.spine.status(PROGRAM, SIGNAL_DATE) is SessionStatus.RUN


def test_shared_empty_candidates_is_no_signal(rig: _Rig) -> None:
    rig.producer.records = ()
    rig.kernel.decisions = {
        TrialArm.CHAMPION: _no_trade(),
        TrialArm.CHALLENGER: _no_trade(),
    }
    receipt = rig.runner.decide_signal_session(rig.request())
    assert rig.spine.status(PROGRAM, SIGNAL_DATE) is SessionStatus.NO_SIGNAL


def test_shared_core_evidence_failure_is_data_unknown(rig: _Rig) -> None:
    rig.regime_reader = _MissingRegimeReader(_regime_observation(RegimeState.NORMAL))
    rig.runner = _new_runner(rig)
    with pytest.raises(PairedTrialRunnerError) as excinfo:
        rig.runner.decide_signal_session(rig.request())
    assert excinfo.value.code == "regime_observation_missing"
    assert rig.spine.status(PROGRAM, SIGNAL_DATE) is None


def test_common_capital_integrity_block_is_blocked(rig: _Rig) -> None:
    from src.screening.offensive.v3.kernel.models import BlockReason

    rig.kernel.decisions = {
        TrialArm.CHAMPION: _no_trade(BlockReason.STALE_CAPITAL),
        TrialArm.CHALLENGER: _no_trade(BlockReason.STALE_CAPITAL),
    }
    receipt = rig.runner.decide_signal_session(rig.request())
    assert rig.spine.status(PROGRAM, SIGNAL_DATE) is SessionStatus.BLOCKED


def test_absent_regime_observation_after_cutoff_is_no_run(rig: _Rig) -> None:
    # A session whose decision cutoff has passed with no pair/status at all
    # becomes NO_RUN only through finalize_missed_sessions. The rig's spine
    # already enrolled SIGNAL_DATE.
    finalized = rig.runner.finalize_missed_sessions(trusted_at=_AFTER_CUTOFF)
    assert finalized == (SIGNAL_DATE,)
    assert rig.spine.status(PROGRAM, SIGNAL_DATE) is SessionStatus.NO_RUN


def test_canonical_unknown_keeps_champion_run(rig: _Rig) -> None:
    from src.screening.offensive.v3.contracts.decision import ShadowDecision

    rig.regime_reader = _RegimeReader(_regime_observation(RegimeState.UNKNOWN))
    rig.runner = _new_runner(rig)
    receipt = rig.runner.decide_signal_session(rig.request())
    champion, _ = _by_arm(rig, receipt)
    assert isinstance(champion.decision, ShadowDecision)
    assert rig.spine.status(PROGRAM, SIGNAL_DATE) is SessionStatus.RUN


def test_arm_specific_block_keeps_other_arm_run(rig: _Rig) -> None:
    rig.kernel.decisions = {
        TrialArm.CHAMPION: _champion_decision(),
        TrialArm.CHALLENGER: _no_trade(),
    }
    receipt = rig.runner.decide_signal_session(rig.request())
    assert receipt.champion_status == SessionStatus.RUN
    assert receipt.challenger_status == SessionStatus.NO_SIGNAL
    assert rig.spine.status(PROGRAM, SIGNAL_DATE) is SessionStatus.RUN


def test_signed_calendar_correction_cancels(rig: _Rig) -> None:
    revision = CalendarRevision(
        calendar_revision_hash=HASH,
        research_program_id=PROGRAM,
        signal_session=SIGNAL_DATE,
        reason="exchange announced trading halt",
        issued_at=_INSIDE,
    )
    rig.spine.record_session_status(
        PROGRAM, SIGNAL_DATE, SessionStatus.SESSION_CANCELLED, revision
    )
    # The runner rejects decisions for a cancelled session.
    with pytest.raises(PairedTrialRunnerError) as excinfo:
        rig.runner.decide_signal_session(rig.request())
    assert excinfo.value.code == "session_cancelled"


def test_classify_pair_session_pure_function() -> None:
    champion, challenger = _champion_decision(), _challenger_decision()
    assert classify_pair_session(champion, challenger, shared_candidate_count=1) is SessionStatus.RUN
    assert classify_pair_session(champion, challenger, shared_candidate_count=0) is SessionStatus.NO_SIGNAL
    assert classify_pair_session(None, None, shared_candidate_count=0) is SessionStatus.NO_RUN
    from src.screening.offensive.v3.kernel.models import BlockReason

    blocked = _no_trade(BlockReason.STALE_CAPITAL)
    assert classify_pair_session(blocked, blocked, shared_candidate_count=1) is SessionStatus.BLOCKED


# =============================================================================
# Step 8: static dependency guard
# =============================================================================

#: The runner may reach evidence/governance read APIs, the producer, the
#: kernel, the decision store, capital read APIs, and the shadow lifecycle.
#: It must never import activation/permit/outbox/broker/trust or production
#: adapter paths. Bare data fields (e.g. the DeadlineContract's
#: broker_auction_cutoff) are not a broker surface; imports and calls are.
_FORBIDDEN_IMPORT_MARKERS = (
    "gateway.",
    "broker.",
    "outbox",
    "shadow_trust",
    "execution.proxy",
    "execution.manual",
    "services.capital_gateway_api",
    "services.governance_api",
    "services.authorizer_api",
)
_FORBIDDEN_CALL_MARKERS = (
    "activate_",
    "publish_entry",
    "issue_permit",
    "claim_send",
    "make_outbox_durable",
    "record_delivery_outcome",
)


def test_paired_runner_imports_no_forbidden_surface() -> None:
    import ast

    module_path = (
        Path(__file__).resolve().parents[4]
        / "src/screening/offensive/v3/orchestration/paired_trial.py"
    )
    source = module_path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(module_path))
    haystack = "".join(
        ast.get_source_segment(source, node) or ""
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
    )
    violations = [m for m in _FORBIDDEN_IMPORT_MARKERS if m in haystack]
    assert not violations, (
        "paired_trial.py imports a forbidden capability surface:\n  "
        + "\n  ".join(violations)
    )


def test_paired_runner_source_has_no_forbidden_calls() -> None:
    import ast

    module_path = (
        Path(__file__).resolve().parents[4]
        / "src/screening/offensive/v3/orchestration/paired_trial.py"
    )
    source = module_path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(module_path))
    haystack = "".join(
        ast.get_source_segment(source, node) or ""
        for node in ast.walk(tree)
        if isinstance(node, (ast.Call, ast.Import, ast.ImportFrom))
    )
    violations = [m for m in _FORBIDDEN_CALL_MARKERS if m in haystack]
    assert not violations, (
        "paired_trial.py calls a forbidden capability surface:\n  "
        + "\n  ".join(violations)
    )


def _no_trade(reason=None):
    from src.screening.offensive.v3.kernel.models import (
        BlockReason,
        NoTradeDecision,
    )

    return NoTradeDecision(
        portfolio_id=PORTFOLIO,
        signal_session=SIGNAL_DATE,
        decision_cycle_id=f"daily-action-{SIGNAL_DATE.isoformat()}",
        reason=reason or BlockReason.NO_SIGNAL,
    )
