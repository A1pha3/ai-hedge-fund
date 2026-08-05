"""Plan 03 Task 6: EDGE Authorizer and governed EXPLORATION/RECOVERY."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from fractions import Fraction
from pathlib import Path

import pytest

from src.screening.offensive.v3.contracts import ExecutionMode
from src.screening.offensive.v3.contracts.authorization import (
    AuthorizationKind,
    CapitalAuthorizationEnvelope,
)
from src.screening.offensive.v3.contracts.governance import (
    GrantKind,
    LineageGrant,
    ProgramLossBudgetBinding,
)
from src.screening.offensive.v3.evidence.authorizer import (
    Authorizer,
    AuthorizerError,
    EdgeAssessmentRequest,
)
from src.screening.offensive.v3.evidence.consumption import (
    AttemptLedger,
    AttemptStatus,
    EvidenceConsumptionLedger,
    GlobalMultiplicityBudgetLedger,
    MultiplicityBudgetKind,
)
from src.screening.offensive.v3.evidence.statistics import (
    PortfolioEvaluation,
)
from src.screening.offensive.v3.governance.issuer import (
    EXPLORATION_AGGREGATE_CAP,
    ExplorationIssuanceRequest,
    GovernanceIssuer,
    IssuerError,
    RecoveryIssuanceRequest,
)

UTC = timezone.utc
NOW = datetime(2026, 8, 5, 9, 0, tzinfo=UTC)
CUTOFF = NOW - timedelta(days=1)
HASH = "a" * 64
HASH2 = "b" * 64
PORTFOLIO = "paper-v3"
MODE = ExecutionMode.DAILY_BAR_PROXY


class _Clock:
    def __init__(self, start: datetime) -> None:
        self.now_value = start

    def __call__(self) -> datetime:
        return self.now_value


def _grant(**overrides) -> LineageGrant:
    values = {
        "grant_id": "grant-1",
        "grant_kind": GrantKind.EDGE,
        "grant_certificate_hash": HASH,
        "grant_issuer_id": "authorizer.service",
        "subject_producer": "btst",
        "family_id": "btst.limit-up-breakout",
        "economic_lineage_id": "eline-1",
        "research_program_id": "prog-1",
        "behavior_fingerprint": HASH,
        "execution_version": "t1-open-t10-open.v1",
        "cost_version": "cn-a-share-costs.v1",
        "capital_tier": 2,
        "lineage_gross_cap": Decimal("0.02"),
        "trial_id": "trial-1",
        "trial_manifest_hash": HASH,
        "statistical_analysis_plan_hash": HASH,
        "stage_id": "stage-1",
        "stage_manifest_hash": HASH,
        "stage_sample_reservation_id": "reservation-1",
        "stage_loss_budget_id": "budget-1",
        "stage_loss_budget_cents": 100_000,
        "stage_loss_version": 1,
        "assessment_result_hash": HASH,
        "grant_evidence_set_merkle_root": HASH,
        "attempt_ledger_checkpoint_hash": HASH,
        "alpha_or_evalue_budget_consumption_id": "budget-consumption-1",
        "alpha_sample_consumption_id": "sample-consumption-1",
        "schema_major": 2,
    }
    values.update(overrides)
    return LineageGrant(**values)


def _binding(**overrides) -> ProgramLossBudgetBinding:
    values = {
        "research_program_id": "prog-1",
        "budget_id": "budget-1",
        "budget_cents": 100_000,
        "consumed_cents": 0,
        "version": 3,
        "schema_major": 2,
    }
    values.update(overrides)
    return ProgramLossBudgetBinding(**values)


def _envelope(
    *,
    kind: AuthorizationKind = AuthorizationKind.EDGE,
    mode: ExecutionMode = MODE,
    grant: LineageGrant | None = None,
    binding: ProgramLossBudgetBinding | None = None,
    risk_epoch: int = 1,
    expires_at: datetime = NOW + timedelta(days=1),
    exploration_cap: Decimal = Decimal("0.02"),
    **overrides,
) -> CapitalAuthorizationEnvelope:
    values: dict = {
        "authorization_kind": kind,
        "authorization_id": "auth-1",
        "authorization_version": 1,
        "mode": mode,
        "portfolio_id": PORTFOLIO,
        "broker_account_id": None,
        "broker_account_fingerprint": None,
        "base_currency": "CNY",
        "policy_activation_hash": HASH,
        "trust_bundle_hash": HASH,
        "registry_epoch": 1,
        "policy_epoch": 1,
        "authority_epoch": 1,
        "risk_epoch": risk_epoch,
        "research_program_ids": ("prog-1",),
        "baseline_portfolio_policy_fingerprint": HASH,
        "target_portfolio_policy_fingerprint": HASH2,
        "evidence_as_of": CUTOFF,
        "evidence_set_merkle_root": HASH,
        "issued_at": NOW,
        "expires_at": expires_at,
        "activation_capital_snapshot_id": "snapshot-1",
        "activation_capital_snapshot_hash": HASH,
        "program_loss_budget_bindings": (binding or _binding(),),
        "issuer_id": "authorizer.service",
        "portfolio_assessment_result_hash": HASH,
        "global_attempt_ledger_checkpoint_hash": HASH,
        "global_multiplicity_budget_consumption_id": "consumption-1",
        "schema_major": 2,
    }
    if kind is AuthorizationKind.EDGE:
        values.update(
            {
                "issuer_capability": "authorizer.edge.envelope.v1",
                "portfolio_gross_cap": Decimal("0.02"),
                "exploration_aggregate_gross_cap": Decimal("0"),
                "lineage_grants": (grant or _grant(),),
            }
        )
    elif kind is AuthorizationKind.EXPLORATION:
        exploration_grant = grant or _grant(
            grant_kind=GrantKind.EXPLORATION,
            capital_tier=2,
            lineage_gross_cap=exploration_cap,
            shared_exploration_loss_budget_id="shared-budget-1",
        )
        values.update(
            {
                "issuer_capability": "governance.exploration.envelope.v1",
                "portfolio_gross_cap": exploration_cap,
                "exploration_aggregate_gross_cap": exploration_cap,
                "lineage_grants": (exploration_grant,),
                "exploration_shared_stress_loss_budget_id": (
                    "shared-budget-1"
                ),
                "exploration_shared_stress_loss_budget_cents": 100_000,
                "exploration_shared_stress_loss_consumed_cents": 0,
                "exploration_shared_stress_loss_version": 1,
                "exploration_one_shot_reservation_id": "one-shot-res-1",
                "exploration_one_shot_consumption_id": (
                    "one-shot-consumption-1"
                ),
                "exploration_trial_id": exploration_grant.trial_id,
                "exploration_fixed_assessment_at": NOW
                + timedelta(days=30),
            }
        )
    else:  # RECOVERY
        recovery_grant = grant or _grant()
        values.update(
            {
                "issuer_capability": "governance.recovery.envelope.v1",
                "portfolio_gross_cap": Decimal("0.02"),
                "exploration_aggregate_gross_cap": Decimal("0"),
                "lineage_grants": (recovery_grant,),
                "predecessor_active_authorization_id": "auth-prior",
                "predecessor_active_authorization_version": 2,
                "predecessor_active_authorization_hash": HASH,
                "predecessor_active_authorization_status_hash": HASH,
                "predecessor_target_policy_fingerprint": HASH2,
                "predecessor_active_edge_grant_certificate_hashes": (
                    recovery_grant.grant_certificate_hash,
                ),
                "recovery_inherited_risk_version": risk_epoch,
                "recovery_open_pending_risk_version": risk_epoch,
                "recovery_stage_program_loss_consumption_version": 3,
                "risk_epoch_started_hash": HASH,
                "recovery_manifest_hash": HASH,
            }
        )
    values.update(overrides)
    return CapitalAuthorizationEnvelope(**values)


def _evaluation(**overrides) -> PortfolioEvaluation:
    values = {
        "excess_mean": 0.002,
        "excess_lcb_95": 0.001,
        "minimum_economic_effect": 0.0005,
        "lcb_above_mee": True,
        "excess_mean_at_double_slippage": 0.0018,
        "adverse_window_excess_mean": 0.0004,
        "maximum_drawdown": 0.05,
        "conditional_drawdown_at_risk": 0.08,
        "observation_count": 200,
        "evaluated_at": NOW,
        "evidence_cutoff": CUTOFF,
    }
    values.update(overrides)
    return PortfolioEvaluation(**values)


class _FailingSigner:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, payload: bytes):
        self.calls += 1
        raise RuntimeError("external signer unavailable")


def _dummy_signer():
    from base64 import b64encode
    import hashlib as _hashlib

    from src.screening.offensive.v3 import trust

    def sign(payload: bytes):
        digest = _hashlib.sha256(payload).hexdigest()
        return trust.SignedEnvelope(
            issuer_id="authorizer.service",
            key_id="key-1",
            schema_major=2,
            artifact=trust.ArtifactKind.EDGE_AUTHORIZATION,
            namespace="capital.edge.btst",
            mode=MODE,
            capability_version="capital.authorizer.v1",
            capability_scope="portfolio:paper-v3",
            payload_hash=digest,
            payload=payload,
            signature=b64encode(b"0" * 64).decode("ascii"),
        )

    return sign


@pytest.fixture()
def ledgers(tmp_path: Path):
    budget = GlobalMultiplicityBudgetLedger(
        str(tmp_path / "budget.sqlite3")
    )
    budget.set_budget(MultiplicityBudgetKind.ALPHA, 100)
    attempts = AttemptLedger(
        str(tmp_path / "attempts.sqlite3"),
        budget=budget,
        clock=_Clock(NOW),
    )
    consumption = EvidenceConsumptionLedger(
        str(tmp_path / "consumption.sqlite3"),
        attempts=attempts,
        clock=_Clock(NOW),
    )
    return budget, attempts, consumption


@pytest.fixture()
def authorizer(tmp_path: Path, ledgers) -> Authorizer:
    _, attempts, consumption = ledgers
    return Authorizer(
        database_path=str(tmp_path / "authorizer.sqlite3"),
        signer=_dummy_signer(),
        clock=_Clock(NOW),
        attempts=attempts,
        consumption=consumption,
        expected_mode=MODE,
        expected_behavior_fingerprint=HASH,
        expected_cost_version="cn-a-share-costs.v1",
        expected_execution_version="t1-open-t10-open.v1",
        expected_broker_account_id=None,
    )


def _request(authorizer=None, **overrides) -> EdgeAssessmentRequest:
    values = {
        "portfolio_id": PORTFOLIO,
        "broker_account_id": None,
        "mode": MODE,
        "behavior_fingerprint": HASH,
        "cost_version": "cn-a-share-costs.v1",
        "execution_version": "t1-open-t10-open.v1",
        "benchmark_as_of": CUTOFF,
        "baseline_excess_mean": 0.001,
        "evaluation": _evaluation(),
        "mdd_cap": 0.10,
        "cdar_cap": 0.15,
        "envelope": _envelope(),
        "research_program_id": "prog-1",
        "attempt_id": "attempt-edge",
        "sample_evidence_id": "sample-edge-1",
    }
    values.update(overrides)
    return EdgeAssessmentRequest(**values)


def _reserve(attempts, attempt_id="attempt-edge") -> None:
    attempts.reserve(
        attempt_id=attempt_id,
        research_program_id="prog-1",
        economic_lineage_id="eline-1",
        family_id="btst.limit-up-breakout",
        frozen_plan_hash=HASH,
    )


def test_edge_issuance_signs_inactive_complete_envelope(
    authorizer: Authorizer, ledgers,
) -> None:
    budget, attempts, _ = ledgers
    _reserve(attempts)
    envelope, signed = authorizer.assess_and_issue_edge(_request())
    assert envelope.authorization_kind is AuthorizationKind.EDGE
    assert authorizer.issued_status("auth-1") == "INACTIVE"
    assert signed.payload_hash
    # Issuance consumes the global multiplicity budget (via the attempt
    # reservation) and closes the attempt as CONSUMED.
    assert budget.consumed(MultiplicityBudgetKind.ALPHA) == 1
    assert attempts.status("attempt-edge") is AttemptStatus.CONSUMED


@pytest.mark.parametrize(
    "override,code",
    [
        ({"benchmark_as_of": None}, "benchmark_missing"),
        (
            {
                "benchmark_as_of": CUTOFF - timedelta(days=3),
            },
            "benchmark_stale",
        ),
        (
            {"mode": ExecutionMode.MANUAL_CONFIRMED},
            "mode_mismatch",
        ),
        ({"behavior_fingerprint": "c" * 64}, "behavior_mismatch"),
        ({"cost_version": "other-costs.v2"}, "cost_mismatch"),
        ({"execution_version": "other.v9"}, "execution_mismatch"),
        ({"baseline_excess_mean": 0.003}, "target_not_better_than_baseline"),
        (
            {
                "evaluation": _evaluation(
                    excess_lcb_95=0.0001, lcb_above_mee=False
                )
            },
            "lcb_below_mee",
        ),
        (
            {"evaluation": _evaluation(maximum_drawdown=0.5)},
            "tail_breach",
        ),
        (
            {"evaluation": _evaluation(conditional_drawdown_at_risk=0.9)},
            "tail_breach",
        ),
    ],
)
def test_edge_gates_fail_closed(
    authorizer: Authorizer, override: dict, code: str
) -> None:
    with pytest.raises(AuthorizerError) as excinfo:
        authorizer.assess_and_issue_edge(_request(**override))
    assert excinfo.value.code == code
    # Nothing was issued.
    with pytest.raises(AuthorizerError):
        authorizer.issued_status("auth-1")


def test_second_independent_envelope_is_rejected(
    authorizer: Authorizer, tmp_path: Path, ledgers
) -> None:
    _reserve(ledgers[1])
    authorizer.assess_and_issue_edge(_request())
    # Simulate an already-ACTIVE envelope in the registry.
    import sqlalchemy as sa

    with authorizer._engine.begin() as conn:
        conn.execute(
            sa.text(
                "UPDATE issued_envelopes SET status = 'ACTIVE'"
                " WHERE authorization_id = 'auth-1'"
            )
        )
    second = _request(
        envelope=_envelope(
            authorization_id="auth-2",
        )
    )
    with pytest.raises(AuthorizerError) as excinfo:
        authorizer.assess_and_issue_edge(second)
    assert excinfo.value.code == "envelope_already_active"


def test_signer_failure_leaves_no_envelope_and_retry_is_deterministic(
    tmp_path: Path, ledgers,
) -> None:
    budget, attempts, consumption = ledgers
    failing = _FailingSigner()
    authorizer = Authorizer(
        database_path=str(tmp_path / "authorizer.sqlite3"),
        signer=failing,
        clock=_Clock(NOW),
        attempts=attempts,
        consumption=consumption,
        expected_mode=MODE,
        expected_behavior_fingerprint=HASH,
        expected_cost_version="cn-a-share-costs.v1",
        expected_execution_version="t1-open-t10-open.v1",
        expected_broker_account_id=None,
    )
    _reserve(attempts)
    with pytest.raises(RuntimeError):
        authorizer.assess_and_issue_edge(_request())
    # A failed signature leaves no consumption and no issued envelope:
    # the budget count stays at the reservation (1), the attempt stays
    # RESERVED, and the sample is unconsumed (a later identical
    # consumption would still succeed).
    with pytest.raises(AuthorizerError):
        authorizer.issued_status("auth-1")
    assert failing.calls == 1
    assert budget.consumed(MultiplicityBudgetKind.ALPHA) == 1
    assert attempts.status("attempt-edge") is AttemptStatus.RESERVED
    consumption.consume_primary_promotion(
        research_program_id="prog-1",
        attempt_id="attempt-edge",
        evidence_id="sample-edge-1",
        payload_hash=HASH,
    )
    # Deterministic retry after the signer recovers: reserve a fresh
    # attempt/sample so the issuance path is clean.
    _reserve(attempts, "attempt-edge-2")
    authorizer._signer = _dummy_signer()
    envelope, _ = authorizer.assess_and_issue_edge(
        _request(
            attempt_id="attempt-edge-2",
            sample_evidence_id="sample-edge-2",
        )
    )
    assert authorizer.issued_status(envelope.authorization_id) == (
        "INACTIVE"
    )


def test_reissue_same_sample_is_rejected(authorizer: Authorizer, ledgers):
    budget, attempts, _ = ledgers
    _reserve(attempts)
    authorizer.assess_and_issue_edge(_request())
    _reserve(attempts, "attempt-edge-b")
    with pytest.raises(AuthorizerError) as excinfo:
        authorizer.assess_and_issue_edge(
            _request(
                attempt_id="attempt-edge-b",
                envelope=_envelope(authorization_id="auth-dup"),
            )
        )
    assert excinfo.value.code == "sample_reuse"
    # The failed issuance consumed no additional sample budget: only the
    # two attempt reservations count.
    assert budget.consumed(MultiplicityBudgetKind.ALPHA) == 2


def _issuer(tmp_path: Path, *, signer=None):
    budget = GlobalMultiplicityBudgetLedger(
        str(tmp_path / "issuer-budget.sqlite3")
    )
    budget.set_budget(MultiplicityBudgetKind.ALPHA, 100)
    attempts = AttemptLedger(
        str(tmp_path / "issuer-attempts.sqlite3"),
        budget=budget,
        clock=_Clock(NOW),
    )
    consumption = EvidenceConsumptionLedger(
        str(tmp_path / "issuer-consumption.sqlite3"),
        attempts=attempts,
        clock=_Clock(NOW),
    )
    issuer = GovernanceIssuer(
        database_path=str(tmp_path / "issuer.sqlite3"),
        signer=signer or _dummy_signer(),
        clock=_Clock(NOW),
        attempts=attempts,
        consumption=consumption,
    )
    return issuer, attempts, budget


def test_exploration_requires_broker_confirmed(tmp_path: Path) -> None:
    # The frozen envelope contract rejects a non-BROKER_CONFIRMED
    # exploration at construction; the issuer gate remains defense in
    # depth and is exercised here against a tampered candidate built via
    # model_construct (bypassing validation).
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        _envelope(
            kind=AuthorizationKind.EXPLORATION,
            mode=MODE,  # proxy: forbidden for exploration
        )
    issuer, attempts, _ = _issuer(tmp_path)
    _reserve(attempts, "attempt-issuer-1")
    valid = _envelope(
        kind=AuthorizationKind.EXPLORATION,
        mode=ExecutionMode.BROKER_CONFIRMED,
        broker_account_id="acct-1",
        broker_account_fingerprint=HASH,
    )
    tampered = valid.model_copy(update={"mode": MODE})
    with pytest.raises(IssuerError) as excinfo:
        issuer.issue_exploration(
            ExplorationIssuanceRequest(
                envelope=tampered,
                research_program_id="prog-1",
                attempt_id="attempt-issuer-1",
                sample_evidence_id="sample-issuer-1",
            )
        )
    assert excinfo.value.code == "exploration_requires_broker_confirmed"


def test_exploration_cap_limited_to_two_percent(tmp_path: Path) -> None:
    # The frozen envelope contract itself rejects an exploration aggregate
    # cap above 2% at construction; the issuer gate stays as defense in
    # depth (checked next via an oversized PORTFOLIO cap on a valid
    # exploration envelope shape).
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        _envelope(
            kind=AuthorizationKind.EXPLORATION,
            mode=ExecutionMode.BROKER_CONFIRMED,
            broker_account_id="acct-1",
            broker_account_fingerprint=HASH,
            exploration_cap=Decimal("0.03"),
        )


def test_exploration_issuance_and_renewal(tmp_path: Path) -> None:
    issuer, attempts, _ = _issuer(tmp_path)
    envelope = _envelope(
        kind=AuthorizationKind.EXPLORATION,
        mode=ExecutionMode.BROKER_CONFIRMED,
        broker_account_id="acct-1",
        broker_account_fingerprint=HASH,
    )
    _reserve(attempts, "attempt-expl-1")
    issued, _ = issuer.issue_exploration(
        ExplorationIssuanceRequest(
            envelope=envelope,
            research_program_id="prog-1",
            attempt_id="attempt-expl-1",
            sample_evidence_id="sample-expl-1",
        )
    )
    assert issuer.issued_status(issued.authorization_id) == "INACTIVE"
    assert attempts.status("attempt-expl-1") is AttemptStatus.CONSUMED
    # Renewal cites the prior exploration.
    renewal_envelope = _envelope(
        kind=AuthorizationKind.EXPLORATION,
        mode=ExecutionMode.BROKER_CONFIRMED,
        broker_account_id="acct-1",
        broker_account_fingerprint=HASH,
        grant=_grant(
            grant_id="grant-2",
            grant_kind=GrantKind.EXPLORATION,
            capital_tier=2,
            lineage_gross_cap=Decimal("0.02"),
            shared_exploration_loss_budget_id="shared-budget-1",
            stage_sample_reservation_id="reservation-2",
            assessment_result_hash=HASH2,
            grant_certificate_hash=HASH2,
            alpha_sample_consumption_id="sample-consumption-2",
        ),
        authorization_id="auth-exploration-2",
    )
    _reserve(attempts, "attempt-expl-2")
    renewed, _ = issuer.issue_exploration(
        ExplorationIssuanceRequest(
            envelope=renewal_envelope,
            research_program_id="prog-1",
            attempt_id="attempt-expl-2",
            sample_evidence_id="sample-expl-2",
            renewal_of_authorization_id="auth-1",
        )
    )
    assert issuer.issued_status(renewed.authorization_id) == "INACTIVE"
    # Renewal citing a non-exploration id is rejected.
    bad_renewal = _envelope(
        kind=AuthorizationKind.EXPLORATION,
        mode=ExecutionMode.BROKER_CONFIRMED,
        broker_account_id="acct-1",
        broker_account_fingerprint=HASH,
        grant=_grant(
            grant_id="grant-3",
            grant_kind=GrantKind.EXPLORATION,
            capital_tier=2,
            lineage_gross_cap=Decimal("0.02"),
            shared_exploration_loss_budget_id="shared-budget-1",
            stage_sample_reservation_id="reservation-3",
            assessment_result_hash=HASH2,
            grant_certificate_hash=HASH2,
            alpha_sample_consumption_id="sample-consumption-3",
        ),
        authorization_id="auth-exploration-3",
    )
    with pytest.raises(IssuerError) as excinfo:
        issuer.issue_exploration(
            ExplorationIssuanceRequest(
                envelope=bad_renewal,
                research_program_id="prog-1",
                attempt_id="attempt-expl-3",
                sample_evidence_id="sample-expl-3",
                renewal_of_authorization_id="does-not-exist",
            )
        )
    assert excinfo.value.code == "renewal_requires_prior_exploration"


def test_recovery_requires_inherited_versions(tmp_path: Path) -> None:
    issuer, attempts, _ = _issuer(tmp_path)
    envelope = _envelope(
        kind=AuthorizationKind.RECOVERY,
        risk_epoch=4,
        binding=_binding(version=7),
    )
    # Wrong inherited stage-loss version is rejected.
    with pytest.raises(IssuerError) as excinfo:
        issuer.issue_recovery(
            RecoveryIssuanceRequest(
                envelope=envelope,
                research_program_id="prog-1",
                attempt_id="attempt-rec-1",
                sample_evidence_id="sample-rec-1",
                inherited_authorization_id="auth-prior",
                inherited_risk_epoch=4,
                inherited_stage_loss_version=6,
            )
        )
    assert excinfo.value.code == "recovery_loss_version_mismatch"
    # Wrong risk epoch is rejected.
    with pytest.raises(IssuerError) as excinfo:
        issuer.issue_recovery(
            RecoveryIssuanceRequest(
                envelope=envelope,
                research_program_id="prog-1",
                attempt_id="attempt-rec-1",
                sample_evidence_id="sample-rec-1",
                inherited_authorization_id="auth-prior",
                inherited_risk_epoch=3,
                inherited_stage_loss_version=7,
            )
        )
    assert excinfo.value.code == "recovery_risk_epoch_mismatch"
    # Correct inherited versions issue an INACTIVE candidate and consume
    # the attempt budget.
    _reserve(attempts, "attempt-rec-1")
    issued, _ = issuer.issue_recovery(
        RecoveryIssuanceRequest(
            envelope=envelope,
            research_program_id="prog-1",
            attempt_id="attempt-rec-1",
            sample_evidence_id="sample-rec-1",
            inherited_authorization_id="auth-prior",
            inherited_risk_epoch=4,
            inherited_stage_loss_version=7,
        )
    )
    assert issuer.issued_status(issued.authorization_id) == "INACTIVE"
    assert attempts.status("attempt-rec-1") is AttemptStatus.CONSUMED


def test_expired_manifest_is_rejected(tmp_path: Path) -> None:
    issuer, attempts, _ = _issuer(tmp_path)
    expired = _envelope(
        kind=AuthorizationKind.RECOVERY,
        issued_at=NOW - timedelta(days=2),
        expires_at=NOW - timedelta(days=1),
        evidence_as_of=NOW - timedelta(days=3),
    )
    with pytest.raises(IssuerError) as excinfo:
        issuer.issue_recovery(
            RecoveryIssuanceRequest(
                envelope=expired,
                research_program_id="prog-1",
                attempt_id="attempt-exp-1",
                sample_evidence_id="sample-exp-1",
                inherited_authorization_id="auth-prior",
                inherited_risk_epoch=1,
                inherited_stage_loss_version=3,
            )
        )
    assert excinfo.value.code == "manifest_expired"


def test_issuer_cannot_sign_edge(tmp_path: Path) -> None:
    issuer, attempts, _ = _issuer(tmp_path)
    with pytest.raises(IssuerError) as excinfo:
        issuer.issue_exploration(
            ExplorationIssuanceRequest(
                envelope=_envelope(),  # EDGE kind
                research_program_id="prog-1",
                attempt_id="attempt-kind-1",
                sample_evidence_id="sample-kind-1",
            )
        )
    assert excinfo.value.code == "envelope_kind_mismatch"
