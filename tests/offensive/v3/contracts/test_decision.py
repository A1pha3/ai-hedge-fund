"""Revision 2 contracts for a complete, entry-only portfolio proposal."""

from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest
from pydantic import ValidationError


UTC = timezone.utc
SIGNAL_SESSION = date(2026, 7, 17)
TARGET_ENTRY_SESSION = date(2026, 7, 20)
DECISION_CUTOFF = datetime(2026, 7, 19, 8, 2, tzinfo=UTC)
PROPOSAL_CREATED_AT = datetime(2026, 7, 19, 8, 4, tzinfo=UTC)

POLICY_HASH = "d" * 64
TRUST_HASH = "b" * 64
ACCOUNT_FINGERPRINT = "c" * 64
EVIDENCE_ROOT = "e" * 64
ENTRY_FENCE_HASH = "f" * 64
PLAN_PAYLOAD_HASH_1 = "1" * 64
PLAN_PAYLOAD_HASH_2 = "2" * 64

PORTFOLIO_ID = "portfolio-v3"
BROKER_ACCOUNT_ID = "broker-account-001"
AUTHORIZATION_ID = "authorization-001"
AUTHORIZATION_VERSION = 8
PRODUCER = "daily-action.btst"
FAMILY_ID = "btst-family"
LINEAGE_ID = "lineage-btst"
PROGRAM_ID = "program-btst"
STAGE_ID = "stage-broker-2pct"
STAGE_MANIFEST_HASH = "3" * 64
GRANT_ID = "grant-btst-2pct"
GRANT_CERTIFICATE_HASH = "4" * 64
STAGE_LOSS_BUDGET_ID = "stage-loss-001"
STAGE_LOSS_VERSION = 7


def _decision_contracts(*required_names: str) -> SimpleNamespace:
    from src.screening.offensive.v3.contracts import decision

    missing = [name for name in required_names if not hasattr(decision, name)]
    if missing:
        pytest.fail(
            "missing final Task 3B decision API(s): " + ", ".join(missing),
            pytrace=False,
        )
    return SimpleNamespace(
        module=decision,
        **{name: getattr(decision, name) for name in required_names},
    )


def _authorization_envelope():
    from src.screening.offensive.v3.contracts.authorization import (
        CapitalAuthorizationEnvelope,
    )
    from tests.offensive.v3.contracts.test_authorization import _envelope, _grant

    grant = _grant(
        grant_id=GRANT_ID,
        grant_certificate_hash=GRANT_CERTIFICATE_HASH,
        subject_producer=PRODUCER,
        family_id=FAMILY_ID,
        economic_lineage_id=LINEAGE_ID,
        research_program_id=PROGRAM_ID,
        behavior_fingerprint="5" * 64,
        execution_version="t1-open-t10-open-v1",
        cost_version="broker-cost-v1",
        stage_id=STAGE_ID,
        stage_manifest_hash=STAGE_MANIFEST_HASH,
        stage_loss_budget_id=STAGE_LOSS_BUDGET_ID,
        stage_loss_budget_cents=100_000,
        stage_loss_version=STAGE_LOSS_VERSION,
    )
    payload = _envelope(
        authorization_id=AUTHORIZATION_ID,
        authorization_version=AUTHORIZATION_VERSION,
        portfolio_id=PORTFOLIO_ID,
        broker_account_id=BROKER_ACCOUNT_ID,
        broker_account_fingerprint=ACCOUNT_FINGERPRINT,
        policy_activation_hash=POLICY_HASH,
        trust_bundle_hash=TRUST_HASH,
        registry_epoch=7,
        policy_epoch=4,
        authority_epoch=5,
        risk_epoch=6,
        research_program_ids=(PROGRAM_ID,),
        baseline_portfolio_policy_fingerprint="6" * 64,
        target_portfolio_policy_fingerprint="7" * 64,
        lineage_grants=(grant,),
        evidence_as_of=datetime(2026, 7, 19, 7, 55, tzinfo=UTC),
        evidence_set_merkle_root=EVIDENCE_ROOT,
        issued_at=datetime(2026, 7, 19, 7, 59, tzinfo=UTC),
        expires_at=datetime(2026, 7, 19, 8, 20, tzinfo=UTC),
        activation_capital_snapshot_id="activation-capital-001",
        activation_capital_snapshot_hash="8" * 64,
        program_loss_budget_bindings=(
            {
                "research_program_id": PROGRAM_ID,
                "budget_id": "program-loss-001",
                "budget_cents": 200_000,
                "consumed_cents": 10_000,
                "version": 7,
                "schema_major": 2,
            },
        ),
    )
    return CapitalAuthorizationEnvelope.model_validate(payload)


def _authorization_status(envelope=None):
    from src.screening.offensive.v3.contracts.governance import (
        AuthorizationLifecycle,
        AuthorizationStatus,
    )
    from tests.offensive.v3.contracts.test_governance_remediation_b import (
        _authorization_status as _status_payload,
    )

    envelope = envelope or _authorization_envelope()
    payload = _status_payload(
        portfolio_id=PORTFOLIO_ID,
        broker_account_id=BROKER_ACCOUNT_ID,
        broker_account_fingerprint=ACCOUNT_FINGERPRINT,
        mode=envelope.mode,
        authorization_id=AUTHORIZATION_ID,
        authorization_version=AUTHORIZATION_VERSION,
        authorization_envelope_hash=envelope.artifact_hash(),
        evidence_set_merkle_root=EVIDENCE_ROOT,
        authorization_issued_at=envelope.issued_at,
        authorization_expires_at=envelope.expires_at,
        policy_activation_hash=POLICY_HASH,
        trust_bundle_hash=TRUST_HASH,
        registry_epoch=7,
        policy_epoch=4,
        authority_epoch=5,
        risk_epoch=6,
        status_version=3,
        status=AuthorizationLifecycle.ACTIVE,
        entry_fence_version=4,
        activated_at=datetime(2026, 7, 19, 8, 0, tzinfo=UTC),
        status_effective_at=datetime(2026, 7, 19, 8, 0, tzinfo=UTC),
        status_reason=None,
        status_cause_hash=None,
        as_of=datetime(2026, 7, 19, 8, 3, tzinfo=UTC),
    )
    return AuthorizationStatus.model_validate(payload)


def _capital_risk_snapshot():
    from src.screening.offensive.v3.contracts import capital
    from tests.offensive.v3.contracts.test_capital import (
        _exposure,
        _risk_snapshot_payload,
    )

    exposures = tuple(
        _exposure(
            capital,
            scope,
            unattributed_risk_cents=0,
            total_gross_cents=480_000,
        )
        for scope in capital.ExposureScope
    )
    payload = _risk_snapshot_payload(
        capital,
        unattributed_risk_cents=0,
        exposures=exposures,
        total_gross_exposure_cents=480_000,
        reconciliation_latch=capital.ReconciliationLatchState.CLEAR,
    )
    return capital.CapitalRiskSnapshot.model_validate(payload)


def _plan_evidence(
    *,
    suffix: str = "1",
    producer_namespace: str = PRODUCER,
    family_id: str = FAMILY_ID,
    economic_lineage_id: str = LINEAGE_ID,
):
    from src.screening.offensive.v3.contracts.base import (
        EvidenceScope,
        ExecutionMode,
    )
    from src.screening.offensive.v3.contracts.decision import PlanEvidence

    payload_hash = PLAN_PAYLOAD_HASH_1 if suffix == "1" else PLAN_PAYLOAD_HASH_2
    return PlanEvidence(
        evidence_id=f"plan-evidence-{suffix}",
        evidence_kind="plan",
        subject_scope=EvidenceScope.STRATEGY_LINEAGE,
        subject_producer=producer_namespace,
        family_id=family_id,
        strategy_semver="3.0.0",
        behavior_fingerprint="5" * 64,
        policy_epoch=4,
        execution_version="t1-open-t10-open-v1",
        cost_version="broker-cost-v1",
        effective_at=datetime(2026, 7, 17, 7, 0, tzinfo=UTC),
        provider_published_at=datetime(2026, 7, 19, 7, 55, tzinfo=UTC),
        observed_at=datetime(2026, 7, 19, 7, 56, tzinfo=UTC),
        available_at=datetime(2026, 7, 19, 7, 58, tzinfo=UTC),
        mode=ExecutionMode.BROKER_CONFIRMED,
        source_authority="evidence-store",
        payload_content_hash=payload_hash,
        schema_major=2,
        portfolio_id=PORTFOLIO_ID,
        signal_session=SIGNAL_SESSION,
        economic_lineage_id=economic_lineage_id,
        snapshot_id="pit-snapshot-20260717",
        raw_target_fraction=Decimal("0.01"),
        created_at=datetime(2026, 7, 19, 7, 56, tzinfo=UTC),
    )


def _line_payload(
    *,
    suffix: str = "1",
    security_id: str = "600000.SH",
    producer_namespace: str = PRODUCER,
    family_id: str = FAMILY_ID,
    economic_lineage_id: str = LINEAGE_ID,
    research_program_id: str = PROGRAM_ID,
    stage_id: str = STAGE_ID,
    stage_manifest_hash: str = STAGE_MANIFEST_HASH,
    grant_id: str = GRANT_ID,
    grant_certificate_hash: str = GRANT_CERTIFICATE_HASH,
    **overrides: object,
) -> dict[str, object]:
    from src.screening.offensive.v3.contracts.base import ExecutionMode

    plan = _plan_evidence(
        suffix=suffix,
        producer_namespace=producer_namespace,
        family_id=family_id,
        economic_lineage_id=economic_lineage_id,
    )
    from src.screening.offensive.v3.contracts.evidence import EvidenceRecord

    plan_record = EvidenceRecord[type(plan)](
        evidence=plan,
        ingested_at=plan.available_at,
        commit_sequence=int(suffix),
        revision=1,
        supersedes_revision=None,
        active_revision=1,
    )
    if suffix == "1":
        sealed_quantity_units = 100
        limit_price_cents = 1_020
        worst_case_price_cents = 1_050
        worst_case_fee_reserve_cents = 50
    else:
        sealed_quantity_units = 200
        limit_price_cents = 780
        worst_case_price_cents = 800
        worst_case_fee_reserve_cents = 75
    payload: dict[str, object] = {
        "order_line_id": f"line-{suffix}",
        "security_id": security_id,
        "order_action": "ENTRY",
        "producer_namespace": producer_namespace,
        "family_id": family_id,
        "economic_lineage_id": economic_lineage_id,
        "research_program_id": research_program_id,
        "stage_id": stage_id,
        "stage_manifest_hash": stage_manifest_hash,
        "grant_id": grant_id,
        "grant_certificate_hash": grant_certificate_hash,
        "authorization_id": AUTHORIZATION_ID,
        "authorization_version": AUTHORIZATION_VERSION,
        "plan_evidence": plan_record,
        "plan_evidence_artifact_hash": plan_record.artifact_hash(),
        "plan_payload_content_hash": plan.payload_content_hash,
        "mode": ExecutionMode.BROKER_CONFIRMED,
        "target_entry_session": TARGET_ENTRY_SESSION,
        "exit_session_ordinal": 10,
        "sealed_quantity_units": sealed_quantity_units,
        "lot_size_units": 100,
        "lot_rule_version": "cn-a-share-lot-v1",
        "order_type": "LIMIT",
        "limit_price_cents": limit_price_cents,
        "worst_case_price_cents": worst_case_price_cents,
        "price_boundary_version": "cn-price-limit-v1",
        "time_in_force": "OPEN_AUCTION",
        "worst_case_fee_reserve_cents": worst_case_fee_reserve_cents,
        "worst_case_cash_reserve_cents": (
            worst_case_price_cents * sealed_quantity_units
            + worst_case_fee_reserve_cents
        ),
    }
    payload.update(overrides)
    return payload


def _order_lines(api) -> tuple[object, object]:
    return (
        api.PortfolioOrderLine.model_validate(_line_payload()),
        api.PortfolioOrderLine.model_validate(
            _line_payload(suffix="2", security_id="600001.SH")
        ),
    )


def _stage_loss_expected_versions(api) -> tuple[object, ...]:
    from src.screening.offensive.v3.contracts.capital import StageLossLatchState

    return (
        api.StageLossExpectedVersion(
            research_program_id=PROGRAM_ID,
            economic_lineage_id=LINEAGE_ID,
            stage_id=STAGE_ID,
            stage_loss_budget_id=STAGE_LOSS_BUDGET_ID,
            stage_loss_version=STAGE_LOSS_VERSION,
            stage_loss_latch=StageLossLatchState.CLEAR,
        ),
    )


def _expected_versions(api, **overrides: object):
    envelope = _authorization_envelope()
    status = _authorization_status(envelope)
    risk = _capital_risk_snapshot()
    payload: dict[str, object] = {
        "policy_activation_hash": POLICY_HASH,
        "trust_bundle_hash": TRUST_HASH,
        "registry_epoch": 7,
        "policy_epoch": 4,
        "authority_epoch": 5,
        "risk_epoch": 6,
        "authorization_id": AUTHORIZATION_ID,
        "authorization_version": AUTHORIZATION_VERSION,
        "authorization_envelope_hash": envelope.artifact_hash(),
        "authorization_status_version": status.status_version,
        "authorization_status_hash": status.artifact_hash(),
        "evidence_set_merkle_root": EVIDENCE_ROOT,
        "entry_fence_id": "entry-fence-001",
        "entry_fence_hash": ENTRY_FENCE_HASH,
        "entry_fence_version": status.entry_fence_version,
        "risk_snapshot_id": risk.risk_snapshot_id,
        "risk_snapshot_artifact_hash": risk.artifact_hash(),
        "capital_version": risk.capital_version,
        "capital_stream_version": 29,
        "writer_fencing_epoch": risk.writer_fencing_epoch,
        "stage_loss_expected_versions": _stage_loss_expected_versions(api),
        "expected_active_seal_id": None,
        "expected_active_seal_revision": None,
        "expected_active_seal_logical_key": None,
        "expected_active_seal_artifact_hash": None,
        "schema_major": 2,
    }
    payload.update(overrides)
    return api.GatewayExpectedVersions.model_validate(payload)


def _decision_payload(api, **overrides: object) -> dict[str, object]:
    from src.screening.offensive.v3.contracts.base import ExecutionMode

    envelope = _authorization_envelope()
    risk = _capital_risk_snapshot()
    lines = _order_lines(api)
    payload: dict[str, object] = {
        "logical_key": api.DecisionLogicalKey(
            portfolio_id=PORTFOLIO_ID,
            signal_session=SIGNAL_SESSION,
            decision_cycle_id="daily-t1-open-v1",
        ),
        "portfolio_id": PORTFOLIO_ID,
        "broker_account_id": BROKER_ACCOUNT_ID,
        "broker_account_fingerprint": ACCOUNT_FINGERPRINT,
        "base_currency": "CNY",
        "mode": ExecutionMode.BROKER_CONFIRMED,
        "target_entry_session": TARGET_ENTRY_SESSION,
        "target_portfolio_policy_fingerprint": (
            envelope.target_portfolio_policy_fingerprint
        ),
        "policy_activation_hash": POLICY_HASH,
        "trust_bundle_hash": TRUST_HASH,
        "registry_epoch": 7,
        "policy_epoch": 4,
        "authority_epoch": 5,
        "risk_epoch": 6,
        "authorization_id": envelope.authorization_id,
        "authorization_version": envelope.authorization_version,
        "authorization_artifact_hash": envelope.artifact_hash(),
        "evidence_set_merkle_root": EVIDENCE_ROOT,
        "risk_snapshot_id": risk.risk_snapshot_id,
        "risk_snapshot_artifact_hash": risk.artifact_hash(),
        "risk_snapshot_as_of": risk.as_of,
        "capital_version": risk.capital_version,
        "capital_stream_version": 29,
        "writer_fencing_epoch": risk.writer_fencing_epoch,
        "order_lines": lines,
        "total_worst_case_cash_reserve_cents": sum(
            line.worst_case_cash_reserve_cents for line in lines
        ),
        "decision_cutoff": DECISION_CUTOFF,
        "proposal_created_at": PROPOSAL_CREATED_AT,
        "schema_major": 2,
    }
    payload.update(overrides)
    return payload


def _decision(api):
    return api.PortfolioDecision.model_validate(_decision_payload(api))


def test_task2_authorization_and_task3a_risk_builders_are_valid() -> None:
    from src.screening.offensive.v3.contracts.capital import (
        ReconciliationLatchState,
    )
    from src.screening.offensive.v3.contracts.governance import (
        AuthorizationLifecycle,
    )

    envelope = _authorization_envelope()
    status = _authorization_status(envelope)
    risk = _capital_risk_snapshot()

    assert envelope.lineage_grants[0].stage_id == STAGE_ID
    assert status.status is AuthorizationLifecycle.ACTIVE
    assert status.authorization_envelope_hash == envelope.artifact_hash()
    assert risk.reconciliation_latch is ReconciliationLatchState.CLEAR
    assert risk.authorization_id == envelope.authorization_id
    assert risk.authorization_version == envelope.authorization_version


def test_decision_logical_key_is_the_exact_economic_idempotency_key() -> None:
    from src.screening.offensive.v3.contracts.decision import DecisionLogicalKey

    assert set(DecisionLogicalKey.model_fields) == {
        "portfolio_id",
        "signal_session",
        "decision_cycle_id",
    }
    key = DecisionLogicalKey(
        portfolio_id=PORTFOLIO_ID,
        signal_session=SIGNAL_SESSION,
        decision_cycle_id="daily-t1-open-v1",
    )
    assert key.model_dump() == {
        "portfolio_id": PORTFOLIO_ID,
        "signal_session": SIGNAL_SESSION,
        "decision_cycle_id": "daily-t1-open-v1",
    }


def test_decision_logical_key_rejects_authority_epoch_laundering() -> None:
    from src.screening.offensive.v3.contracts.decision import DecisionLogicalKey

    with pytest.raises(ValidationError):
        DecisionLogicalKey.model_validate(
            {
                "portfolio_id": PORTFOLIO_ID,
                "signal_session": SIGNAL_SESSION,
                "decision_cycle_id": "daily-t1-open-v1",
                "authority_epoch": 5,
            }
        )


def test_stage_loss_expected_version_has_exact_public_fields() -> None:
    api = _decision_contracts("StageLossExpectedVersion")

    assert set(api.StageLossExpectedVersion.model_fields) == {
        "research_program_id",
        "economic_lineage_id",
        "stage_id",
        "stage_loss_budget_id",
        "stage_loss_version",
        "stage_loss_latch",
    }


def test_portfolio_order_line_has_exact_entry_only_public_fields() -> None:
    api = _decision_contracts("PortfolioOrderLine")

    assert set(api.PortfolioOrderLine.model_fields) == {
        "order_line_id",
        "security_id",
        "order_action",
        "producer_namespace",
        "family_id",
        "economic_lineage_id",
        "research_program_id",
        "stage_id",
        "stage_manifest_hash",
        "grant_id",
        "grant_certificate_hash",
        "authorization_id",
        "authorization_version",
        "plan_evidence",
        "plan_evidence_artifact_hash",
        "plan_payload_content_hash",
        "mode",
        "target_entry_session",
        "exit_session_ordinal",
        "sealed_quantity_units",
        "lot_size_units",
        "lot_rule_version",
        "order_type",
        "limit_price_cents",
        "worst_case_price_cents",
        "price_boundary_version",
        "time_in_force",
        "worst_case_fee_reserve_cents",
        "worst_case_cash_reserve_cents",
    }
    line = api.PortfolioOrderLine.model_validate(_line_payload())
    assert line.order_action == "ENTRY"
    assert line.exit_session_ordinal == 10
    assert line.sealed_quantity_units == 100
    assert line.worst_case_cash_reserve_cents == 105_050


@pytest.mark.parametrize("bad", [True, 10.0, Decimal("10"), "10"])
def test_portfolio_order_line_requires_native_integer_t_plus_10(bad) -> None:
    api = _decision_contracts("PortfolioOrderLine")
    with pytest.raises(ValidationError, match="integer|int|literal"):
        api.PortfolioOrderLine.model_validate(_line_payload(exit_session_ordinal=bad))


def test_gateway_expected_versions_has_the_exact_full_cas_bundle() -> None:
    api = _decision_contracts(
        "StageLossExpectedVersion",
        "GatewayExpectedVersions",
    )

    assert set(api.GatewayExpectedVersions.model_fields) == {
        "policy_activation_hash",
        "trust_bundle_hash",
        "registry_epoch",
        "policy_epoch",
        "authority_epoch",
        "risk_epoch",
        "authorization_id",
        "authorization_version",
        "authorization_envelope_hash",
        "authorization_status_version",
        "authorization_status_hash",
        "evidence_set_merkle_root",
        "entry_fence_id",
        "entry_fence_hash",
        "entry_fence_version",
        "risk_snapshot_id",
        "risk_snapshot_artifact_hash",
        "capital_version",
        "capital_stream_version",
        "writer_fencing_epoch",
        "stage_loss_expected_versions",
        "expected_active_seal_id",
        "expected_active_seal_revision",
        "expected_active_seal_logical_key",
        "expected_active_seal_artifact_hash",
        "schema_major",
    }
    versions = _expected_versions(api)
    assert versions.expected_active_seal_id is None
    assert versions.expected_active_seal_revision is None
    assert versions.capital_version == 10
    assert versions.capital_stream_version == 29


def test_gateway_expected_versions_pairs_first_or_existing_active_seal() -> None:
    api = _decision_contracts(
        "DecisionLogicalKey",
        "StageLossExpectedVersion",
        "GatewayExpectedVersions",
    )

    first = _expected_versions(api)
    logical_key = api.DecisionLogicalKey(
        portfolio_id=PORTFOLIO_ID,
        signal_session=SIGNAL_SESSION,
        decision_cycle_id="daily-t1-open-v1",
    )
    existing = _expected_versions(
        api,
        expected_active_seal_id="seal-001",
        expected_active_seal_revision=2,
        expected_active_seal_logical_key=logical_key,
        expected_active_seal_artifact_hash="9" * 64,
    )
    assert (
        first.expected_active_seal_id,
        first.expected_active_seal_revision,
        first.expected_active_seal_logical_key,
        first.expected_active_seal_artifact_hash,
    ) == (
        None,
        None,
        None,
        None,
    )
    assert (
        existing.expected_active_seal_id,
        existing.expected_active_seal_revision,
        existing.expected_active_seal_logical_key,
        existing.expected_active_seal_artifact_hash,
    ) == ("seal-001", 2, logical_key, "9" * 64)
    for drift in (
        {"expected_active_seal_id": "seal-001"},
        {"expected_active_seal_revision": 1},
        {"expected_active_seal_logical_key": logical_key},
        {"expected_active_seal_artifact_hash": "9" * 64},
    ):
        with pytest.raises(ValidationError, match="active seal|all-or-none|tuple"):
            _expected_versions(api, **drift)


def test_gateway_expected_versions_requires_unique_canonical_stage_versions() -> None:
    from src.screening.offensive.v3.contracts.capital import StageLossLatchState

    api = _decision_contracts(
        "StageLossExpectedVersion",
        "GatewayExpectedVersions",
    )
    stage_a = api.StageLossExpectedVersion(
        research_program_id="program-a",
        economic_lineage_id="lineage-a",
        stage_id="stage-a",
        stage_loss_budget_id="budget-a",
        stage_loss_version=1,
        stage_loss_latch=StageLossLatchState.CLEAR,
    )
    stage_b = api.StageLossExpectedVersion(
        research_program_id="program-b",
        economic_lineage_id="lineage-b",
        stage_id="stage-a",
        stage_loss_budget_id="budget-b",
        stage_loss_version=2,
        stage_loss_latch=StageLossLatchState.STAGE_LOSS_HALTED,
    )
    base = _expected_versions(api).model_dump(mode="python", round_trip=True)

    legal = api.GatewayExpectedVersions.model_validate(
        base | {"stage_loss_expected_versions": (stage_a, stage_b)}
    )
    assert tuple(
        (item.research_program_id, item.economic_lineage_id, item.stage_id)
        for item in legal.stage_loss_expected_versions
    ) == (
        ("program-a", "lineage-a", "stage-a"),
        ("program-b", "lineage-b", "stage-a"),
    )
    for invalid in ((stage_b, stage_a), (stage_a, stage_a)):
        with pytest.raises(ValidationError, match="stage|canonical|unique"):
            api.GatewayExpectedVersions.model_validate(
                base | {"stage_loss_expected_versions": invalid}
            )


def test_portfolio_decision_has_exact_public_fields_and_multiline_reserve() -> None:
    api = _decision_contracts(
        "DecisionLogicalKey",
        "StageLossExpectedVersion",
        "PortfolioOrderLine",
        "GatewayExpectedVersions",
        "PortfolioDecision",
    )

    assert set(api.PortfolioDecision.model_fields) == {
        "logical_key",
        "portfolio_id",
        "broker_account_id",
        "broker_account_fingerprint",
        "base_currency",
        "mode",
        "target_entry_session",
        "target_portfolio_policy_fingerprint",
        "policy_activation_hash",
        "trust_bundle_hash",
        "registry_epoch",
        "policy_epoch",
        "authority_epoch",
        "risk_epoch",
        "authorization_id",
        "authorization_version",
        "authorization_artifact_hash",
        "evidence_set_merkle_root",
        "risk_snapshot_id",
        "risk_snapshot_artifact_hash",
        "risk_snapshot_as_of",
        "capital_version",
        "capital_stream_version",
        "writer_fencing_epoch",
        "order_lines",
        "total_worst_case_cash_reserve_cents",
        "decision_cutoff",
        "proposal_created_at",
        "schema_major",
    }
    decision = _decision(api)
    assert len(decision.order_lines) == 2
    assert decision.total_worst_case_cash_reserve_cents == 265_125
    assert decision.decision_cutoff < decision.proposal_created_at
    assert decision.risk_snapshot_as_of <= decision.proposal_created_at


@pytest.mark.parametrize(
    ("field_name", "bad_value"),
    [
        ("sealed_quantity_units", True),
        ("sealed_quantity_units", 100.0),
        ("sealed_quantity_units", Decimal("100")),
        ("lot_size_units", False),
        ("lot_size_units", 100.0),
        ("lot_size_units", Decimal("100")),
        ("limit_price_cents", True),
        ("limit_price_cents", 1_020.0),
        ("limit_price_cents", Decimal("1020")),
        ("worst_case_fee_reserve_cents", False),
        ("worst_case_fee_reserve_cents", 50.0),
        ("worst_case_cash_reserve_cents", Decimal("105050")),
    ],
)
def test_order_line_rejects_bool_float_and_decimal_integer_laundering(
    field_name: str,
    bad_value: object,
) -> None:
    api = _decision_contracts("PortfolioOrderLine")

    with pytest.raises(ValidationError, match="integer|native int|valid integer"):
        api.PortfolioOrderLine.model_validate(_line_payload(**{field_name: bad_value}))


def test_order_line_requires_exact_reserve_and_whole_lots() -> None:
    api = _decision_contracts("PortfolioOrderLine")

    for drift in (
        {"worst_case_cash_reserve_cents": 105_049},
        {"worst_case_cash_reserve_cents": 105_051},
        {"sealed_quantity_units": 150},
        {"limit_price_cents": 1_051},
    ):
        with pytest.raises(ValidationError, match="reserve|lot|price"):
            api.PortfolioOrderLine.model_validate(_line_payload(**drift))


@pytest.mark.parametrize(
    ("field_name", "bad_value", "match"),
    [
        ("economic_lineage_id", "other-lineage", "lineage"),
        ("stage_id", "other-stage", "stage"),
        ("stage_manifest_hash", "9" * 64, "stage"),
        ("grant_id", "other-grant", "grant"),
        ("grant_certificate_hash", "9" * 64, "grant"),
        ("authorization_id", "other-authorization", "authorization"),
        ("authorization_version", 9, "authorization"),
        ("plan_evidence_artifact_hash", "9" * 64, "plan evidence"),
        ("plan_payload_content_hash", "9" * 64, "payload"),
    ],
)
def test_portfolio_decision_rejects_nested_line_provenance_drift(
    field_name: str,
    bad_value: object,
    match: str,
) -> None:
    api = _decision_contracts(
        "DecisionLogicalKey",
        "StageLossExpectedVersion",
        "PortfolioOrderLine",
        "GatewayExpectedVersions",
        "PortfolioDecision",
    )
    raw = _decision_payload(api)
    line_payloads = [
        line.model_dump(mode="python", round_trip=True) for line in raw["order_lines"]
    ]
    line_payloads[0][field_name] = bad_value
    raw["order_lines"] = tuple(line_payloads)
    raw["total_worst_case_cash_reserve_cents"] = sum(
        line["worst_case_cash_reserve_cents"] for line in line_payloads
    )

    with pytest.raises(ValidationError, match=match):
        api.PortfolioDecision.model_validate(raw)


def test_portfolio_decision_and_gateway_cas_are_independent_immutable_inputs() -> None:
    api = _decision_contracts(
        "DecisionLogicalKey",
        "StageLossExpectedVersion",
        "PortfolioOrderLine",
        "GatewayExpectedVersions",
        "PortfolioDecision",
    )
    proposal = _decision(api)
    expected = _expected_versions(api)
    assert not set(api.PortfolioDecision.model_fields) & {
        "capital_authorization",
        "authorization_status",
        "capital_risk_snapshot",
        "gateway_expected_versions",
    }

    changed_expected = api.GatewayExpectedVersions.model_validate(
        expected.model_dump(mode="python", round_trip=True)
        | {"capital_stream_version": expected.capital_stream_version + 1}
    )
    assert changed_expected.capital_stream_version != expected.capital_stream_version
    assert proposal.artifact_hash() == _decision(api).artifact_hash()

    changed_proposal = api.PortfolioDecision.model_validate(
        proposal.model_dump(mode="python", round_trip=True)
        | {"risk_snapshot_artifact_hash": "9" * 64}
    )
    assert changed_proposal.artifact_hash() != proposal.artifact_hash()
    assert expected.capital_stream_version == 29


def test_portfolio_decision_requires_exact_aggregate_reserve() -> None:
    api = _decision_contracts(
        "DecisionLogicalKey",
        "StageLossExpectedVersion",
        "PortfolioOrderLine",
        "GatewayExpectedVersions",
        "PortfolioDecision",
    )

    for drift in (265_124, 265_126):
        with pytest.raises(ValidationError, match="reserve"):
            api.PortfolioDecision.model_validate(
                _decision_payload(
                    api,
                    total_worst_case_cash_reserve_cents=drift,
                )
            )


def test_portfolio_decision_requires_unique_canonical_order_lines() -> None:
    api = _decision_contracts(
        "DecisionLogicalKey",
        "StageLossExpectedVersion",
        "PortfolioOrderLine",
        "GatewayExpectedVersions",
        "PortfolioDecision",
    )
    legal = _decision_payload(api)
    lines = legal["order_lines"]
    duplicate = deepcopy(legal)
    duplicate["order_lines"] = (lines[0], lines[0])
    duplicate["total_worst_case_cash_reserve_cents"] = (
        lines[0].worst_case_cash_reserve_cents * 2
    )
    noncanonical = deepcopy(legal)
    noncanonical["order_lines"] = tuple(reversed(lines))

    with pytest.raises(ValidationError, match="unique|duplicate"):
        api.PortfolioDecision.model_validate(duplicate)
    with pytest.raises(ValidationError, match="canonical|order"):
        api.PortfolioDecision.model_validate(noncanonical)


def test_portfolio_decision_keeps_same_security_lines_separate_by_lineage() -> None:
    api = _decision_contracts(
        "DecisionLogicalKey",
        "PortfolioOrderLine",
        "PortfolioDecision",
    )
    first = api.PortfolioOrderLine.model_validate(_line_payload())
    second = api.PortfolioOrderLine.model_validate(
        _line_payload(
            suffix="2",
            security_id=first.security_id,
            producer_namespace="auto.shadow",
            family_id="auto-family",
            economic_lineage_id="lineage-auto",
            research_program_id="program-auto",
            stage_id="stage-auto-shadow",
            stage_manifest_hash="8" * 64,
            grant_id="grant-auto-shadow",
            grant_certificate_hash="9" * 64,
        )
    )
    raw = _decision_payload(api)
    raw["order_lines"] = (first, second)
    raw["total_worst_case_cash_reserve_cents"] = sum(
        line.worst_case_cash_reserve_cents for line in raw["order_lines"]
    )
    decision = api.PortfolioDecision.model_validate(raw)
    assert [line.security_id for line in decision.order_lines] == [
        "600000.SH",
        "600000.SH",
    ]
    assert [line.economic_lineage_id for line in decision.order_lines] == [
        "lineage-btst",
        "lineage-auto",
    ]


def test_task5_roadmap_publish_entry_shape_keeps_proposal_and_cas_separate() -> None:
    import inspect

    from src.screening.offensive.v3.contracts import decision as decision_module
    from src.screening.offensive.v3.contracts.decision import (
        GatewayExpectedVersions,
        PortfolioDecision,
    )

    def publish_entry(
        proposal: PortfolioDecision,
        expected: GatewayExpectedVersions,
    ) -> object:
        raise NotImplementedError

    signature = inspect.signature(publish_entry)
    assert tuple(signature.parameters) == ("proposal", "expected")
    annotations = inspect.get_annotations(
        publish_entry,
        eval_str=True,
        locals={
            "PortfolioDecision": PortfolioDecision,
            "GatewayExpectedVersions": GatewayExpectedVersions,
        },
    )
    assert annotations["proposal"] is PortfolioDecision
    assert annotations["expected"] is GatewayExpectedVersions
    assert not hasattr(decision_module, "CapitalGatewayCommandPort")


def test_portfolio_decision_rejects_research_execution() -> None:
    from src.screening.offensive.v3.contracts.base import ExecutionMode

    api = _decision_contracts(
        "DecisionLogicalKey",
        "StageLossExpectedVersion",
        "PortfolioOrderLine",
        "GatewayExpectedVersions",
        "PortfolioDecision",
    )

    with pytest.raises(ValidationError, match="research|execution"):
        api.PortfolioOrderLine.model_validate(
            _line_payload(mode=ExecutionMode.RESEARCH_RECONSTRUCTION)
        )
    with pytest.raises(ValidationError, match="research|execution"):
        api.PortfolioDecision.model_validate(
            _decision_payload(
                api,
                mode=ExecutionMode.RESEARCH_RECONSTRUCTION,
            )
        )


def test_portfolio_decision_rejects_late_plan_or_future_risk_reference() -> None:
    api = _decision_contracts(
        "DecisionLogicalKey",
        "StageLossExpectedVersion",
        "PortfolioOrderLine",
        "GatewayExpectedVersions",
        "PortfolioDecision",
    )
    raw = _decision_payload(api)
    raw["decision_cutoff"] = datetime(2026, 7, 19, 7, 57, tzinfo=UTC)
    with pytest.raises(ValidationError, match="cutoff|available|PIT"):
        api.PortfolioDecision.model_validate(raw)

    raw = _decision_payload(api)
    raw["risk_snapshot_as_of"] = datetime(2026, 7, 19, 8, 5, tzinfo=UTC)
    with pytest.raises(ValidationError, match="risk|snapshot|as.of|future"):
        api.PortfolioDecision.model_validate(raw)
