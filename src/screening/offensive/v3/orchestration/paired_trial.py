"""Disabled paired-trial entry point and authority-free pure builders.

The official runner has no injected capabilities and always fails closed.
Module-level builders preserve the deterministic target construction for
direct tests; they do not grant forward input authority.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from pydantic import model_validator

from src.screening.offensive.v3.contracts import CanonicalModel, Sha256
from src.screening.offensive.v3.contracts.btst_candidate import (
    BtstCandidateIndustryState,
    BtstRawCandidatePayload,
)
from src.screening.offensive.v3.contracts.decision import ShadowDecision
from src.screening.offensive.v3.contracts.evidence import (
    EvidenceRecord,
    SignalEvidence,
)
from src.screening.offensive.v3.contracts.regime import RegimeObservation
from src.screening.offensive.v3.contracts.trial import (
    BaselineShadowPolicyBinding,
    ShadowPolicySourceKind,
    TargetShadowPolicyBinding,
    TrialArm,
)
from src.screening.offensive.v3.evidence.session_spine import SessionStatus
from src.screening.offensive.v3.governance.regime_trial import (
    ValidatedRegimeTrialBundle,
)
from src.screening.offensive.v3.kernel.admission import BTST_FAMILY
from src.screening.offensive.v3.kernel.models import (
    CandidateEvidenceBinding,
    DeadlineContract,
    NoTradeDecision,
    RawCandidate,
    ShadowCapitalCheckpoint,
    ShadowKernelInput,
    ShadowSharedInput,
)
from src.screening.offensive.v3.kernel.sizing import SizingConfig
from src.screening.offensive.v3.orchestration.trial_store import (
    ArmDecision,
    TrialArmDecisionRecord,
)


class PairedTrialRunnerError(RuntimeError):
    """Fail-closed rejection of a forward paired-trial session."""

    def __init__(self, code: str, message: str, **details: object) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.details = details


@dataclass(frozen=True)
class SignalSessionRequest:
    """Identity of a future forward signal-session request.

    The disabled runner does not inspect it.  In particular, caller-owned
    values cannot stand in for the missing store-owned batch authority.
    """

    trial_id: str
    signal_session: date


@dataclass(frozen=True)
class PairedSignalReceipt:
    """The durable outcome of one signal session decision."""

    trial_id: str
    signal_session: date
    pair_key: tuple[str, str, str]
    champion_status: SessionStatus
    challenger_status: SessionStatus
    decision_cycle_id: str
    regime_observation_hash: Sha256


#: The one regime evidence id the paired trial consumes (published by the
#: RegimeObservationPublisher in evidence/regime.py).
REGIME_EVIDENCE_ID: str = "regime:csi300:1.0"


class CommittedBtstCandidate(CanonicalModel):
    """A strict binding value produced after store verification.

    The DTO is not authority by itself. Forward and replay entry points must
    independently prove the record and payload against their authoritative
    Evidence Store before passing it to the pure input builder.
    """

    record: EvidenceRecord[SignalEvidence]
    payload: BtstRawCandidatePayload

    @model_validator(mode="after")
    def validate_binding(self) -> "CommittedBtstCandidate":
        envelope = self.record.evidence
        if envelope.stage.value != "selected":
            raise ValueError("committed candidate requires SELECTED signal evidence")
        if envelope.payload_content_hash != self.payload.content_hash():
            raise ValueError("signal record does not bind the raw candidate payload")
        if envelope.evidence_id != (
            f"{self.payload.candidate_id}:{self.payload.signal_stage.value}"
        ):
            raise ValueError("signal evidence identity does not match raw candidate")
        if envelope.effective_at.date() != self.payload.signal_session:
            raise ValueError("signal evidence session does not match raw candidate")
        return self


def classify_pair_session(
    champion: ArmDecision | None,
    challenger: ArmDecision | None,
    *,
    shared_candidate_count: int,
) -> SessionStatus:
    """The pure session-status classification for one committed pair.

    - shared empty candidates (or a NO_SIGNAL no-trade on both arms) →
      ``NO_SIGNAL``;
    - a common capital/risk/integrity block (the same non-NO_SIGNAL no-trade
      reason on both arms) → ``BLOCKED``;
    - no pair at all after the decision cutoff → ``NO_RUN``;
    - otherwise the session ran (a Champion trade with a regime-blocked
      Challenger is a normal paired run) → ``RUN``.
    """

    if champion is None or challenger is None:
        return SessionStatus.NO_RUN
    if shared_candidate_count == 0:
        return SessionStatus.NO_SIGNAL
    champion_block = (
        champion.reason if isinstance(champion, NoTradeDecision) else None
    )
    challenger_block = (
        challenger.reason if isinstance(challenger, NoTradeDecision) else None
    )
    if (
        champion_block is not None
        and challenger_block is not None
        and champion_block == challenger_block
        and champion_block.value != "NO_SIGNAL"
    ):
        return SessionStatus.BLOCKED
    return SessionStatus.RUN


class ForwardPairedTrialRunner:
    """Disabled official forward entry point with no ambient capabilities.

    Individually verified snapshots, evidence rows, decision pairs and session
    statuses cannot prove a complete session batch.  Until Evidence Store owns
    that batch authority and governance seals the exchange decision window,
    every mutating runner operation rejects before reading a clock, store or
    injected callback.  Pure construction helpers remain module-level below.
    """

    __slots__ = ()

    def decide_signal_session(
        self, request: SignalSessionRequest
    ) -> PairedSignalReceipt:
        """Reject before observing the request or invoking any capability."""

        raise PairedTrialRunnerError(
            "forward_input_authority_unavailable",
            "official forward input batch authority is not implemented",
        )

    # ===================================================================
    # forward market-session advance (exit run-out through finality)
    # ===================================================================

    def advance_market_session(self, request: SignalSessionRequest) -> object:
        """Reject before reading lifecycle state or invoking a capability."""

        raise PairedTrialRunnerError(
            "forward_input_authority_unavailable",
            "official forward input batch authority is not implemented",
        )

    def finalize_missed_sessions(self, trusted_at: datetime) -> tuple[date, ...]:
        """Reject before reading time, calendar, spine or decision state."""

        raise PairedTrialRunnerError(
            "forward_input_authority_unavailable",
            "official forward input batch authority is not implemented",
        )


def freeze_shared_input(
    *,
    portfolio_id: str,
    trial_id: str,
    validated: ValidatedRegimeTrialBundle,
    session: date,
    cycle_id: str,
    regime: RegimeObservation,
    regime_hash: str,
    trusted_at: datetime,
) -> ShadowSharedInput:
    """One frozen shared input, identical for both arms (official + replay).

    The single construction is shared by the forward runner and the Task 12
    replay engine so a current-cost replay reproduces the official decision
    bytes exactly.
    """

    raise PairedTrialRunnerError(
        "forward_input_authority_unavailable",
        "store-owned trading schedule receipt is not implemented",
    )


def build_arm_kernel_inputs(
    *,
    validated: ValidatedRegimeTrialBundle,
    shared_input: ShadowSharedInput,
    candidates: tuple[CommittedBtstCandidate, ...],
    champion_capital_checkpoint: ShadowCapitalCheckpoint,
    challenger_capital_checkpoint: ShadowCapitalCheckpoint,
    deadlines: DeadlineContract,
    sizing_config: SizingConfig,
) -> tuple[ShadowKernelInput, ShadowKernelInput]:
    """Build two arm inputs from two independently verified checkpoints.

    Candidates are built exclusively from the producer's SELECTED records;
    every binding is frozen from the record, never synthesized.  Economic
    inputs are explicit: the builder has no single-snapshot shortcut and does
    not manufacture a schedule, deadline or sizing configuration.
    """

    trial = validated.trial_manifest
    raw_candidate_specs: list[tuple[CommittedBtstCandidate, str]] = []
    evidence_bindings: list[CandidateEvidenceBinding] = []
    prices: list[tuple[str, int]] = []
    industries: list[tuple[str, str]] = []
    for committed in candidates:
        record = committed.record
        envelope = record.evidence
        payload = committed.payload
        candidate_id = payload.candidate_id
        raw_candidate_specs.append((committed, candidate_id))
        evidence_bindings.append(
            CandidateEvidenceBinding(
                candidate_id=candidate_id,
                evidence_id=envelope.evidence_id,
                evidence_artifact_hash=record.artifact_hash(),
                evidence_payload_hash=envelope.payload_content_hash,
            )
        )
        prices.append((candidate_id, payload.entry_price_micros))
        if payload.industry_state is BtstCandidateIndustryState.KNOWN:
            assert payload.industry is not None
            industries.append((candidate_id, payload.industry))

    def raw_candidates_for(
        checkpoint: ShadowCapitalCheckpoint,
    ) -> tuple[RawCandidate, ...]:
        snapshot = checkpoint.capital_snapshot
        return tuple(
            RawCandidate(
                candidate_id=candidate_id,
                producer_namespace=committed.record.evidence.subject_producer,
                family_id=BTST_FAMILY,
                economic_lineage_id=trial.economic_lineage_id,
                research_program_id=trial.research_program_id,
                stage_id="stage-1",
                security_id=committed.payload.security_id,
                direction="LONG",
                unscaled_target_gross_cents=(
                    snapshot.as_observed_nav_cents
                    * committed.payload.target_weight_ppm
                    // 1_000_000
                ),
                behavior_fingerprint=(
                    committed.record.evidence.behavior_fingerprint
                ),
                execution_version=committed.record.evidence.execution_version,
                cost_version=committed.record.evidence.cost_version,
                evidence_ids=(),
            )
            for committed, candidate_id in raw_candidate_specs
        )

    champion_raw_candidates = raw_candidates_for(champion_capital_checkpoint)
    challenger_raw_candidates = raw_candidates_for(challenger_capital_checkpoint)
    champion_binding = BaselineShadowPolicyBinding(
        source_kind=ShadowPolicySourceKind.BASELINE_POLICY_ACTIVATION,
        baseline_policy_activation_hash=trial.baseline_policy_activation_hash,
        policy_snapshot_hash=validated.baseline_policy.content_hash(),
        policy_fingerprint=validated.baseline_policy.policy_fingerprint,
    )
    challenger_binding = TargetShadowPolicyBinding(
        source_kind=ShadowPolicySourceKind.TARGET_POLICY_REGISTRATION,
        target_policy_registration_hash=trial.target_policy_snapshot_registration_hash,
        policy_snapshot_hash=validated.target_policy.content_hash(),
        policy_fingerprint=validated.target_policy.policy_fingerprint,
    )
    champion_input = ShadowKernelInput(
        portfolio_id=champion_capital_checkpoint.portfolio_id,
        arm=TrialArm.CHAMPION,
        shared=shared_input,
        policy_snapshot=validated.baseline_policy,
        shadow_policy_binding=champion_binding,
        capital_checkpoint=champion_capital_checkpoint,
        deadlines=deadlines,
        sizing_config=sizing_config,
        candidate_evidence_bindings=tuple(evidence_bindings),
        raw_candidates=champion_raw_candidates,
        price_micros_by_candidate=tuple(prices),
        industry_by_candidate=tuple(industries),
    )
    challenger_input = ShadowKernelInput(
        portfolio_id=challenger_capital_checkpoint.portfolio_id,
        arm=TrialArm.CHALLENGER,
        shared=shared_input,
        policy_snapshot=validated.target_policy,
        shadow_policy_binding=challenger_binding,
        capital_checkpoint=challenger_capital_checkpoint,
        deadlines=deadlines,
        sizing_config=sizing_config,
        candidate_evidence_bindings=tuple(evidence_bindings),
        raw_candidates=challenger_raw_candidates,
        price_micros_by_candidate=tuple(prices),
        industry_by_candidate=tuple(industries),
    )
    return champion_input, challenger_input


def build_pair_records(
    *,
    trial_id: str,
    session: date,
    cycle_id: str,
    shared_input: ShadowSharedInput,
    regime_hash: str,
    champion: ArmDecision,
    challenger: ArmDecision,
    trusted_at: datetime,
    champion_input: ShadowKernelInput,
    challenger_input: ShadowKernelInput,
) -> tuple[TrialArmDecisionRecord, TrialArmDecisionRecord]:
    """The two immutable arm records of one committed pair (official + replay).

    ``created_at`` freezes the same trusted instant both paths consume so a
    current-cost replay reproduces the official rows byte-for-byte.
    """

    for expected_arm, kernel_input, decision in (
        (TrialArm.CHAMPION, champion_input, champion),
        (TrialArm.CHALLENGER, challenger_input, challenger),
    ):
        checkpoint = kernel_input.capital_checkpoint
        if kernel_input.arm is not expected_arm:
            raise PairedTrialRunnerError(
                "economic_input_authority_unavailable",
                "kernel input is bound to the wrong trial arm",
            )
        if kernel_input.shared.content_hash() != shared_input.content_hash():
            raise PairedTrialRunnerError(
                "economic_input_authority_unavailable",
                "kernel input does not bind the committed shared external facts",
            )
        if checkpoint.arm is not expected_arm:
            raise PairedTrialRunnerError(
                "economic_input_authority_unavailable",
                "arm capital checkpoint is bound to the wrong trial arm",
            )
        if (
            checkpoint.trial_id != shared_input.trial_id
            or checkpoint.portfolio_id != kernel_input.portfolio_id
            or checkpoint.mode is not shared_input.mode
        ):
            raise PairedTrialRunnerError(
                "economic_input_authority_unavailable",
                "arm capital checkpoint does not match the shared trial identity",
            )
        if decision.kernel_input_hash != kernel_input.content_hash():
            raise PairedTrialRunnerError(
                "economic_input_authority_unavailable",
                "decision does not bind the exact arm kernel input",
            )

    shared_hash = shared_input.content_hash()
    return (
        TrialArmDecisionRecord(
            trial_id=trial_id,
            signal_session=session,
            decision_cycle_id=cycle_id,
            arm=TrialArm.CHAMPION,
            shared_input_hash=shared_hash,
            arm_policy_fingerprint=(
                champion.shadow_policy_binding.policy_fingerprint
                if isinstance(champion, ShadowDecision)
                else None
            ),
            arm_capital_checkpoint_hash=(
                champion_input.capital_checkpoint.content_hash()
            ),
            regime_observation_hash=regime_hash,
            decision=champion,
            created_at=trusted_at,
            artifact_hash=champion.content_hash(),
        ),
        TrialArmDecisionRecord(
            trial_id=trial_id,
            signal_session=session,
            decision_cycle_id=cycle_id,
            arm=TrialArm.CHALLENGER,
            shared_input_hash=shared_hash,
            arm_policy_fingerprint=(
                challenger.shadow_policy_binding.policy_fingerprint
                if isinstance(challenger, ShadowDecision)
                else None
            ),
            arm_capital_checkpoint_hash=(
                challenger_input.capital_checkpoint.content_hash()
            ),
            regime_observation_hash=regime_hash,
            decision=challenger,
            created_at=trusted_at,
            artifact_hash=challenger.content_hash(),
        ),
    )


__all__ = [
    "CommittedBtstCandidate",
    "ForwardPairedTrialRunner",
    "PairedSignalReceipt",
    "PairedTrialRunnerError",
    "REGIME_EVIDENCE_ID",
    "SignalSessionRequest",
    "build_arm_kernel_inputs",
    "build_pair_records",
    "classify_pair_session",
    "freeze_shared_input",
]
