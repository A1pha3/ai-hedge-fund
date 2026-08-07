"""Plan 04 Task 8: MANUAL_CONFIRMED execution against the capital kernel.

Official OOS requires a pre-sealed, mode-matched PortfolioDecisionSeal: the
operator records operator/source/observed/attachment hash/exact price/quantity
and the versioned fee policy, the service verifies the seal artifact hash and
the plan/line binding, and the fill lands as an attributed, reserve-consuming
revision. Out-of-protocol real trades (no pre-sealed plan, or a trade that
contradicts its plan) still land in AccountCapitalTruth as unattributed risk:
they are preserved under a sentinel lot, excluded from official OOS, and latch
no-entry reconciliation until a source-authorized correction or legal
settlement resolves them. Broker matching links the same economic fact or posts
a delta correction against the same execution identity, never copies a fact
across modes; a manual issuer that directly claims broker provenance is
rejected zero-write. Corrections continue the same execution_id under linked
BUSTED/CORRECTED revisions and never duplicate or transport the fact.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.screening.offensive.v3.capital.execution_revisions import (
    ExecutionRevisionReceipt,
)
from src.screening.offensive.v3.capital.fees import FeePolicy
from src.screening.offensive.v3.capital.fills import (
    FeeRevisionReceipt,
    FillRevisionReceipt,
)
from src.screening.offensive.v3.capital.repository import (
    AccountBinding,
    CapitalCommand,
    CapitalCommandPayload,
    CapitalRepository,
)
from src.screening.offensive.v3.capital.reserves import ReserveEntryRequest
from src.screening.offensive.v3.contracts import (
    CashEconomicEventLeg,
    CashReceivableEconomicEventLeg,
    EconomicAssetKind,
    EconomicEventKind,
    EconomicLegDirection,
    ExecutionMode,
    ExecutionRevisionKind,
    ExecutionSide,
    ReconciliationLatchState,
)
from src.screening.offensive.v3.execution.manual import (
    ExecutionError,
    ManualCorrectionContext,
    ManualCorrectionResult,
    ManualExecutionRecord,
    ManualExecutionService,
    ManualRecordContext,
    ManualRecordResult,
)
from tests.offensive.v3.contracts.checkpoint2_helpers import (
    ACCOUNT_FINGERPRINT,
    ACCOUNT_ID,
    AUTHORIZATION_ID,
    AUTHORIZATION_VERSION,
    BROKER_CUTOFF,
    CLOSE_FINALIZED,
    EVIDENCE_ROOT,
    HASH_A,
    HASH_B,
    HASH_C,
    HASH_D,
    HASH_E,
    PORTFOLIO_ID,
    SIGNAL_SESSION,
    STAGE_ID,
    TARGET_SESSION,
    _api,
    _permit,
    _permit_line,
    _seal,
    _window,
)

UTC = timezone.utc
# The operator records a confirmed manual fill on the T+1 session, after the
# T0 evening execution window sealed the plan.
NOW = datetime(2026, 7, 30, 2, 0, tzinfo=UTC)
SEED_T0 = datetime(2026, 7, 29, 7, 0, tzinfo=UTC)
EXECUTED_AT = datetime(2026, 7, 30, 1, 30, tzinfo=UTC)  # T+1 opening auction
OBSERVED_AT = datetime(2026, 7, 30, 2, 0, tzinfo=UTC)  # operator confirmation

# Versioned fee policy copied from the Plan 02 capital tests: 30bps commission
# with a 5 yuan per-order minimum, 10bps sell-side stamp tax, 2bps transfer fee.
POLICY_V1 = FeePolicy(
    fee_policy_version="fee-schedule-2026-v1",
    commission_rate_ppm=3_000,
    min_commission_cents=500,
    stamp_tax_rate_ppm=1_000,
    transfer_fee_rate_ppm=20,
)

# Manual mode binds a real broker account AND an environment fingerprint (the
# opposite of proxy mode): identity.py forbids MANUAL_CONFIRMED without both.
MANUAL_BINDING = AccountBinding(
    portfolio_id=PORTFOLIO_ID,
    mode=ExecutionMode.MANUAL_CONFIRMED,
    broker_account_id=ACCOUNT_ID,
    base_currency="CNY",
    environment_fingerprint=ACCOUNT_FINGERPRINT,
)

# Sealed line-1 reserve (worst case price x qty + fee): 1050 * 100 + 50.
LINE_1_RESERVE = 1_050 * 100 + 50  # 105_050
# Real fill price the operator reports: 1040 cents -> 10_400_000 price micros.
FILL_PRICE_MICROS = 10_400_000
FILL_GROSS_CENTS = 104_000  # 10_400_000 * 100 / 10_000
# Fee under POLICY_V1 at 104_000 gross: commission base 312 (< 500 minimum) so
# the 500 minimum dominates; transfer fee 2; no stamp tax on entry. Total 502.
FILL_FEE_CENTS = 502


class _Clock:
    def __init__(self, start: datetime) -> None:
        self.now_value = start

    def __call__(self) -> datetime:
        return self.now_value


@pytest.fixture()
def clock() -> _Clock:
    return _Clock(NOW)


@pytest.fixture()
def api() -> SimpleNamespace:
    return _api()


@pytest.fixture()
def repository(tmp_path: Path) -> CapitalRepository:
    return CapitalRepository.initialize(tmp_path / "capital.sqlite3")


@pytest.fixture()
def seal(api):
    return _manual_seal(api)


@pytest.fixture()
def permit(api, seal):
    return _manual_permit(api, seal)


@pytest.fixture()
def service(tmp_path: Path, clock: _Clock) -> ManualExecutionService:
    return ManualExecutionService(
        database_path=str(tmp_path / "manual.sqlite3"),
        clock=clock,
    )


@pytest.fixture()
def capital(repository: CapitalRepository, seal) -> CapitalRepository:
    """A bound manual ledger with seed cash and the sealed reserve live."""

    _deposit(repository, 1_000_000, 1)
    _seed_reserves(repository, seal)
    return repository


# -- manual-mode seal/permit world -------------------------------------------
#
# The checkpoint-2 helpers hardcode BROKER_CONFIRMED with a bound broker
# account. MANUAL_CONFIRMED likewise binds the account and environment
# fingerprint, but the artifact mode and the issuer capability mode must equal
# MANUAL_CONFIRMED so the manual service can prove mode provenance.


def _manual_plan(
    api,
    *,
    suffix: str = "1",
    economic_lineage_id: str = "btst-lineage-a",
    producer_namespace: str = "btst",
):
    return api.PlanEvidence(
        evidence_id=f"plan-{suffix}",
        subject_scope=api.EvidenceScope.STRATEGY_LINEAGE,
        subject_producer=producer_namespace,
        family_id="btst-family",
        strategy_semver="3.0.0",
        behavior_fingerprint=HASH_A,
        policy_epoch=4,
        execution_version="t1-open-t10-open.v1",
        cost_version="cn-a-share.v1",
        effective_at=CLOSE_FINALIZED,
        provider_published_at=CLOSE_FINALIZED,
        observed_at=CLOSE_FINALIZED,
        available_at=CLOSE_FINALIZED,
        mode=api.ExecutionMode.MANUAL_CONFIRMED,
        source_authority="btst-producer",
        payload_content_hash=HASH_B,
        schema_major=2,
        evidence_kind="plan",
        portfolio_id=PORTFOLIO_ID,
        signal_session=SIGNAL_SESSION,
        economic_lineage_id=economic_lineage_id,
        snapshot_id=f"signal-snapshot-{suffix}",
        raw_target_fraction=Decimal("0.01"),
        created_at=CLOSE_FINALIZED,
    )


def _manual_line(
    api,
    *,
    suffix: str = "1",
    security_id: str = "600000.SH",
    producer_namespace: str = "btst",
):
    is_first = suffix == "1"
    lineage = "btst-lineage-a" if is_first else "btst-lineage-b"
    program = "btst-program-a" if is_first else "btst-program-b"
    stage = STAGE_ID if is_first else "stage-broker-2pct-b"
    plan = _manual_plan(
        api,
        suffix=suffix,
        economic_lineage_id=lineage,
        producer_namespace=producer_namespace,
    )
    plan_record = api.EvidenceRecord[api.PlanEvidence](
        evidence=plan,
        ingested_at=plan.available_at,
        commit_sequence=int(suffix),
        revision=1,
        supersedes_revision=None,
        active_revision=1,
    )
    quantity = 100 if is_first else 200
    price = 1_050 if is_first else 800
    fee = 50 if is_first else 75
    return api.PortfolioOrderLine(
        order_line_id=f"line-{suffix}",
        security_id=security_id,
        order_action="ENTRY",
        producer_namespace=producer_namespace,
        family_id="btst-family",
        economic_lineage_id=lineage,
        research_program_id=program,
        stage_id=stage,
        stage_manifest_hash=HASH_C,
        grant_id=f"grant-{lineage}",
        grant_certificate_hash=HASH_D,
        authorization_id=AUTHORIZATION_ID,
        authorization_version=AUTHORIZATION_VERSION,
        plan_evidence=plan_record,
        plan_evidence_artifact_hash=plan_record.artifact_hash(),
        plan_payload_content_hash=plan.payload_content_hash,
        mode=api.ExecutionMode.MANUAL_CONFIRMED,
        target_entry_session=TARGET_SESSION,
        exit_session_ordinal=10,
        sealed_quantity_units=quantity,
        lot_size_units=100,
        lot_rule_version="cn-a-share-lot.v1",
        order_type="LIMIT",
        limit_price_cents=price,
        worst_case_price_cents=price,
        price_boundary_version="cn-price-limit.v1",
        time_in_force="OPEN_AUCTION",
        worst_case_fee_reserve_cents=fee,
        worst_case_cash_reserve_cents=price * quantity + fee,
    )


def _manual_proposal(api, *, producer_namespace: str = "btst"):
    lines = (_manual_line(api, producer_namespace=producer_namespace),)
    return api.PortfolioDecision(
        logical_key=api.DecisionLogicalKey(
            portfolio_id=PORTFOLIO_ID,
            signal_session=SIGNAL_SESSION,
            decision_cycle_id="daily-t1-open-v1",
        ),
        portfolio_id=PORTFOLIO_ID,
        broker_account_id=ACCOUNT_ID,
        broker_account_fingerprint=None,
        base_currency="CNY",
        mode=api.ExecutionMode.MANUAL_CONFIRMED,
        target_entry_session=TARGET_SESSION,
        target_portfolio_policy_fingerprint=HASH_E,
        policy_activation_hash=HASH_A,
        trust_bundle_hash=HASH_B,
        registry_epoch=7,
        policy_epoch=4,
        authority_epoch=5,
        risk_epoch=6,
        authorization_id=AUTHORIZATION_ID,
        authorization_version=AUTHORIZATION_VERSION,
        authorization_artifact_hash=HASH_C,
        evidence_set_merkle_root=EVIDENCE_ROOT,
        risk_snapshot_id="risk-snapshot-1",
        risk_snapshot_artifact_hash=HASH_D,
        risk_snapshot_as_of=CLOSE_FINALIZED,
        capital_version=10,
        capital_stream_version=29,
        writer_fencing_epoch=11,
        order_lines=lines,
        total_worst_case_cash_reserve_cents=sum(
            line.worst_case_cash_reserve_cents for line in lines
        ),
        decision_cutoff=CLOSE_FINALIZED + timedelta(seconds=30),
        proposal_created_at=CLOSE_FINALIZED + timedelta(seconds=45),
        schema_major=2,
    )


def _manual_issuer(api, artifact_kind, namespace):
    return api.GatewayIssuerBinding(
        issuer_id="capital-gateway.service",
        key_id="capital-gateway-key-1",
        capability_artifact_kind=artifact_kind,
        capability_namespace=namespace,
        capability_mode=api.ExecutionMode.MANUAL_CONFIRMED,
        capability_schema_major=2,
        capability_version="capital-gateway.v1",
        capability_scope=f"portfolio:{PORTFOLIO_ID}",
        verification_result="VALID",
        verified_at=CLOSE_FINALIZED,
        valid_until=BROKER_CUTOFF,
        trust_bundle_hash=HASH_B,
        registry_epoch=7,
    )


def _manual_seal(api, **overrides):
    # The seal artifact_namespace is a fixed Literal
    # ("capital-gateway.entry-seal.v1"); the issuer capability_namespace must
    # equal it exactly. MANUAL_CONFIRMED only changes the capability_mode
    # (and the account rules on the proposal), not the artifact namespace.
    return _seal(
        api,
        proposal=_manual_proposal(api),
        issuer_binding=_manual_issuer(
            api,
            api.ArtifactKind.PORTFOLIO_DECISION_SEAL,
            "capital-gateway.entry-seal.v1",
        ),
        **overrides,
    )


def _manual_permit(api, seal=None, **overrides):
    # Same reasoning as _manual_seal: the permit artifact_namespace is the
    # fixed Literal "capital-gateway.entry-permit.v1".
    if seal is None:
        seal = _manual_seal(api)
    return _permit(
        api,
        seal=seal,
        issuer_binding=_manual_issuer(
            api,
            api.ArtifactKind.EXECUTION_PERMIT,
            "capital-gateway.entry-permit.v1",
        ),
        **overrides,
    )


# -- capital world -------------------------------------------------------------


def _seed_moment(step: int) -> datetime:
    return SEED_T0 + timedelta(minutes=step)


def _deposit(repository: CapitalRepository, cents: int, sequence: int) -> None:
    """Seed cash with the only inflow available before Task 3 genesis."""

    amount = Decimal(cents) / 100
    receivable_id = f"rcv-{sequence}"
    repository.append_atomic(
        CapitalCommand(
            idempotency_key=f"declare-{sequence}",
            account_binding=MANUAL_BINDING,
            expected_stream_version=repository.stream_version(),
            as_of=_seed_moment(sequence),
            payload=CapitalCommandPayload(
                event_kind=EconomicEventKind.DIVIDEND_RECEIVABLE,
                effective_at=_seed_moment(sequence),
                source_authority="test.seed",
                legs=(
                    CashReceivableEconomicEventLeg(
                        leg_id=f"declare-{sequence}-r",
                        direction=EconomicLegDirection.CREDIT,
                        asset_kind=EconomicAssetKind.CASH_RECEIVABLE,
                        receivable_id=receivable_id,
                        security_id="000001.SZ",
                        cash_amount=amount,
                    ),
                ),
            ),
        )
    )
    repository.append_atomic(
        CapitalCommand(
            idempotency_key=f"settle-{sequence}",
            account_binding=MANUAL_BINDING,
            expected_stream_version=repository.stream_version(),
            as_of=_seed_moment(sequence) + timedelta(seconds=30),
            payload=CapitalCommandPayload(
                event_kind=EconomicEventKind.DIVIDEND_CASH_SETTLED,
                effective_at=_seed_moment(sequence) + timedelta(seconds=30),
                source_authority="test.seed",
                legs=(
                    CashReceivableEconomicEventLeg(
                        leg_id=f"settle-{sequence}-r",
                        direction=EconomicLegDirection.DEBIT,
                        asset_kind=EconomicAssetKind.CASH_RECEIVABLE,
                        receivable_id=receivable_id,
                        security_id="000001.SZ",
                        cash_amount=amount,
                    ),
                    CashEconomicEventLeg(
                        leg_id=f"settle-{sequence}-c",
                        direction=EconomicLegDirection.CREDIT,
                        asset_kind=EconomicAssetKind.CASH,
                        cash_amount=amount,
                    ),
                ),
            ),
        )
    )


def _seed_reserves(repository: CapitalRepository, seal) -> None:
    """Open the live reserve the seal admission would have created."""

    lines_by_id = {line.order_line_id: line for line in seal.proposal.order_lines}
    for step, item in enumerate(seal.line_reserve_bindings, start=2):
        order_line = lines_by_id[item.order_line_id]
        repository.reserve_entry(
            ReserveEntryRequest(
                source_id=item.reservation_allocation_id,
                research_program_id=order_line.research_program_id,
                economic_lineage_id=order_line.economic_lineage_id,
                stage_id=order_line.stage_id,
                reserved_entry_gross_cents=item.reserved_cash_cents,
                expected_stream_version=repository.stream_version(),
                as_of=_seed_moment(step),
            )
        )


def _official_context(
    repository: CapitalRepository,
    seal,
    permit,
    *,
    execution_id: str = "manual-exec-1",
    operator_id: str | None = "operator-alice",
    source_authority: str | None = "manual-operator.v1",
    observed_at: datetime | None = OBSERVED_AT,
    executed_at: datetime | None = EXECUTED_AT,
    attachment_hash: str | None = HASH_A,
    price_micros: int | None = FILL_PRICE_MICROS,
    quantity: int | None = 100,
    order_line_id: str | None = "line-1",
) -> ManualRecordContext:
    """Context for the official OOS record path (pre-sealed plan present)."""

    permit_line = _permit_line_for(permit, order_line_id)
    return ManualRecordContext(
        repository=repository,
        fee_policy=POLICY_V1,
        operator_id=operator_id,
        source_authority=source_authority,
        observed_at=observed_at,
        executed_at=executed_at,
        attachment_hash=attachment_hash,
        execution_id=execution_id,
        order_id=(permit_line.client_order_id if permit_line is not None else "client-line-1"),
        side=ExecutionSide.ENTRY,
        security_id="600000.SH",
        price_micros=price_micros,
        quantity=quantity,
        seal=seal,
        permit=permit,
        order_line_id=order_line_id,
    )


def _permit_line_for(permit, order_line_id: str | None):
    if permit is None or order_line_id is None:
        return None
    for line in permit.permit_lines:
        if line.order_line_id == order_line_id:
            return line
    return None


def _out_of_protocol_context(
    repository: CapitalRepository,
    *,
    execution_id: str = "manual-oop-1",
    operator_id: str | None = "operator-alice",
    source_authority: str | None = "manual-operator.v1",
    observed_at: datetime | None = OBSERVED_AT,
    executed_at: datetime | None = EXECUTED_AT,
    attachment_hash: str | None = HASH_A,
    price_micros: int | None = FILL_PRICE_MICROS,
    quantity: int | None = 100,
    order_id: str = "broker-order-XYZ",
    security_id: str = "600000.SH",
) -> ManualRecordContext:
    """Context for an out-of-protocol real trade (no pre-sealed plan)."""

    return ManualRecordContext(
        repository=repository,
        fee_policy=POLICY_V1,
        operator_id=operator_id,
        source_authority=source_authority,
        observed_at=observed_at,
        executed_at=executed_at,
        attachment_hash=attachment_hash,
        execution_id=execution_id,
        order_id=order_id,
        side=ExecutionSide.ENTRY,
        security_id=security_id,
        price_micros=price_micros,
        quantity=quantity,
        seal=None,
        permit=None,
        order_line_id=None,
    )


def _record_official(
    service: ManualExecutionService,
    repository: CapitalRepository,
    seal,
    permit,
    **overrides,
) -> ManualRecordResult:
    return service.record(
        context=_official_context(repository, seal, permit, **overrides),
    )


# =============================================================================
# Scenario 1: official OOS record requires and consumes a pre-sealed plan
# =============================================================================


def test_record_official_oos_attributes_fill_and_consumes_reserve(
    service, capital, seal, permit
) -> None:
    result = _record_official(service, capital, seal, permit)

    assert result.execution_id == "manual-exec-1"
    assert result.order_id == "client-line-1"
    assert result.official_oos is True
    assert result.unattributed is False

    fill = result.fill_receipt
    assert isinstance(fill, FillRevisionReceipt)
    assert fill.unattributed is False
    assert fill.side is ExecutionSide.ENTRY
    assert fill.security_id == "600000.SH"
    assert fill.quantity == 100
    assert fill.gross_cents == FILL_GROSS_CENTS
    # Attributed lineage derived from the sealed plan provenance, never the
    # sentinel unattributed lot.
    assert fill.position_lineage_id == "btst-lineage-a"
    assert not fill.economic_lot_id.startswith("unattributed:")
    # The fill consumed the sealed reserve; surplus is auto-released by the
    # kernel's reserve consumption path.
    assert result.reserve_source_id == "reserve-allocation-line-1"
    assert fill.reserve_consumed_cents == LINE_1_RESERVE

    fee = result.fee_receipt
    assert isinstance(fee, FeeRevisionReceipt)
    assert fee.fee_policy_version == POLICY_V1.fee_policy_version
    assert fee.total_cents == FILL_FEE_CENTS

    snapshot = capital.capital_risk_snapshot(NOW)
    assert snapshot.mode is ExecutionMode.MANUAL_CONFIRMED
    assert snapshot.available_cash_cents == 1_000_000 - FILL_GROSS_CENTS - FILL_FEE_CENTS
    assert snapshot.reserved_cash_cents == 0
    assert snapshot.restricted_cash_cents == 0
    assert snapshot.unattributed_risk_cents == 0
    assert snapshot.reconciliation_latch is ReconciliationLatchState.CLEAR
    quantities = {
        position.security_id: position.settled_quantity for position in snapshot.positions
    }
    assert quantities == {"600000.SH": 100}
    assert result.record.official_oos is True
    capital.assert_conservation()


# =============================================================================
# Scenario 2: missing any required field fails closed before any capital write
# =============================================================================


@pytest.mark.parametrize(
    "missing",
    [
        "operator_id",
        "source_authority",
        "observed_at",
        "attachment_hash",
        "price_micros",
        "quantity",
        "fee_policy",
    ],
)
def test_record_official_missing_required_field_fails_closed(
    service, repository, seal, permit, missing
) -> None:
    _deposit(repository, 1_000_000, 1)
    _seed_reserves(repository, seal)
    stream_before = repository.stream_version()
    overrides = {missing: None}
    if missing == "fee_policy":
        # FeePolicy has no natural null; drop it by overriding after build.
        context = _official_context(repository, seal, permit)
        object.__setattr__(context, "fee_policy", None)
    else:
        context = _official_context(repository, seal, permit, **overrides)
    with pytest.raises(ExecutionError) as excinfo:
        service.record(context=context)
    assert excinfo.value.code == "manual_missing_required_field"
    # Zero-write: the capital stream never moved.
    assert repository.stream_version() == stream_before


# =============================================================================
# Scenario 3: a pre-sealed plan whose mode is not MANUAL_CONFIRMED is rejected
# =============================================================================


def test_record_official_rejects_broker_confirmed_seal(service, repository, api) -> None:
    # The checkpoint-2 helper default is BROKER_CONFIRMED with a bound account.
    broker_seal = _seal(api)
    broker_permit = _permit(api, seal=broker_seal)
    _deposit(repository, 1_000_000, 1)
    stream_before = repository.stream_version()
    context = ManualRecordContext(
        repository=repository,
        fee_policy=POLICY_V1,
        operator_id="operator-alice",
        source_authority="manual-operator.v1",
        observed_at=OBSERVED_AT,
        executed_at=EXECUTED_AT,
        attachment_hash=HASH_A,
        execution_id="manual-exec-broker",
        order_id="client-line-1",
        side=ExecutionSide.ENTRY,
        security_id="600000.SH",
        price_micros=FILL_PRICE_MICROS,
        quantity=100,
        seal=broker_seal,
        permit=broker_permit,
        order_line_id="line-1",
    )
    with pytest.raises(ExecutionError) as excinfo:
        service.record(context=context)
    assert excinfo.value.code == "manual_mode_mismatch"
    assert repository.stream_version() == stream_before


# =============================================================================
# Scenario 4: a manual issuer claiming broker provenance is rejected zero-write
# =============================================================================


def test_record_official_rejects_broker_namespace_producer(
    service, repository, api
) -> None:
    broker_lineage_seal = _seal(
        api,
        proposal=_manual_proposal(api, producer_namespace="broker.execution"),
        issuer_binding=_manual_issuer(
            api,
            api.ArtifactKind.PORTFOLIO_DECISION_SEAL,
            "capital-gateway.entry-seal.v1",
        ),
    )
    broker_lineage_permit = _permit(
        api,
        seal=broker_lineage_seal,
        issuer_binding=_manual_issuer(
            api,
            api.ArtifactKind.EXECUTION_PERMIT,
            "capital-gateway.entry-permit.v1",
        ),
    )
    _deposit(repository, 1_000_000, 1)
    stream_before = repository.stream_version()
    context = ManualRecordContext(
        repository=repository,
        fee_policy=POLICY_V1,
        operator_id="operator-alice",
        source_authority="manual-operator.v1",
        observed_at=OBSERVED_AT,
        executed_at=EXECUTED_AT,
        attachment_hash=HASH_A,
        execution_id="manual-exec-broker-ns",
        order_id="client-line-1",
        side=ExecutionSide.ENTRY,
        security_id="600000.SH",
        price_micros=FILL_PRICE_MICROS,
        quantity=100,
        seal=broker_lineage_seal,
        permit=broker_lineage_permit,
        order_line_id="line-1",
    )
    with pytest.raises(ExecutionError) as excinfo:
        service.record(context=context)
    assert excinfo.value.code == "manual_broker_namespace"
    assert repository.stream_version() == stream_before


# =============================================================================
# Scenario 5: out-of-protocol real trade -> unattributed risk + halt latch
# =============================================================================


def test_out_of_protocol_trade_lands_unattributed_and_halts(service, repository) -> None:
    _deposit(repository, 1_000_000, 1)
    stream_before = repository.stream_version()
    result = service.record(
        context=_out_of_protocol_context(repository, execution_id="manual-oop-1"),
    )

    # Excluded from official OOS, preserved as unattributed risk.
    assert result.official_oos is False
    assert result.unattributed is True
    assert result.reserve_source_id is None

    fill = result.fill_receipt
    assert fill.unattributed is True
    # Sentinel lot derived from the execution identity (no plan to vouch).
    assert fill.position_lineage_id == "unattributed:manual-oop-1"
    assert fill.economic_lot_id == "unattributed:manual-oop-1"
    assert fill.reserve_consumed_cents is None
    assert fill.gross_cents == FILL_GROSS_CENTS

    fee = result.fee_receipt
    assert fee.total_cents == FILL_FEE_CENTS

    snapshot = repository.capital_risk_snapshot(NOW)
    # Triple assertion: sentinel exposure + unattributed risk + halt latch.
    assert snapshot.unattributed_risk_cents == FILL_GROSS_CENTS
    assert snapshot.reconciliation_latch is ReconciliationLatchState.RECONCILIATION_HALT
    # The real fill still booked (cash left the account); capital advanced by
    # the fill and fee revisions (two capital writes, matching the proxy).
    assert repository.stream_version() == stream_before + 2
    assert snapshot.available_cash_cents == (
        1_000_000 - FILL_GROSS_CENTS - FILL_FEE_CENTS
    )
    unattributed_positions = [
        position
        for position in snapshot.positions
        if position.producer_namespace == "UNATTRIBUTED"
    ]
    assert len(unattributed_positions) == 1
    assert unattributed_positions[0].settled_quantity == 100
    assert result.record.official_oos is False
    repository.assert_conservation()


def test_out_of_protocol_halt_clears_only_after_reconciled(
    service, repository
) -> None:
    # The no-entry latch is one-way: it persists until a source-authorized
    # correction resolves the unattributed exposure.
    _deposit(repository, 1_000_000, 1)
    service.record(
        context=_out_of_protocol_context(repository, execution_id="manual-oop-2"),
    )
    halted = repository.capital_risk_snapshot(NOW)
    assert halted.reconciliation_latch is ReconciliationLatchState.RECONCILIATION_HALT
    assert halted.unattributed_risk_cents == FILL_GROSS_CENTS

    # Reconciliation here = a BUSTED correction removes the unattributed fill.
    service.correct(
        execution_id="manual-oop-2",
        revision=2,
        kind=ExecutionRevisionKind.BUSTED,
        operator_id="operator-alice",
        attachment_hash=HASH_B,
        context=ManualCorrectionContext(
            repository=repository,
            source_authority="manual-operator.v1",
            effective_at=OBSERVED_AT,
            observed_at=OBSERVED_AT,
        ),
    )
    cleared = repository.capital_risk_snapshot(NOW)
    assert cleared.unattributed_risk_cents == 0
    assert cleared.reconciliation_latch is ReconciliationLatchState.CLEAR
    # Cash restored minus the still-charged fee (fee revisions follow fills).
    assert cleared.available_cash_cents == 1_000_000 - FILL_FEE_CENTS
    repository.assert_conservation()


# =============================================================================
# Scenario 6: BUSTED correction zeroes the recorded fill
# =============================================================================


def test_correct_busted_zeroes_fill_and_restores_cash(
    service, capital, seal, permit
) -> None:
    _record_official(service, capital, seal, permit, execution_id="manual-exec-bust")
    cash_before = capital.capital_risk_snapshot(NOW).available_cash_cents

    result = service.correct(
        execution_id="manual-exec-bust",
        revision=2,
        kind=ExecutionRevisionKind.BUSTED,
        operator_id="operator-alice",
        attachment_hash=HASH_B,
        context=ManualCorrectionContext(
            repository=capital,
            source_authority="manual-operator.v1",
            effective_at=OBSERVED_AT,
            observed_at=OBSERVED_AT,
        ),
    )
    receipt = result.revision_receipt
    assert isinstance(receipt, ExecutionRevisionReceipt)
    assert receipt.revision == 2
    assert receipt.revision_kind is ExecutionRevisionKind.BUSTED
    assert receipt.reversed_gross_cents == FILL_GROSS_CENTS
    assert receipt.reversed_quantity == 100
    assert receipt.applied_gross_cents == 0
    assert receipt.applied_quantity == 0

    snapshot = capital.capital_risk_snapshot(NOW)
    # The busted entry's gross returns to cash; the fee stays charged.
    assert snapshot.available_cash_cents == cash_before + FILL_GROSS_CENTS
    assert snapshot.reconciliation_latch is ReconciliationLatchState.CLEAR
    assert snapshot.unattributed_risk_cents == 0
    quantities = {
        position.security_id: position.settled_quantity for position in snapshot.positions
    }
    assert quantities == {}
    capital.assert_conservation()


# =============================================================================
# Scenario 7: CORRECTED correction replaces price and quantity (delta)
# =============================================================================


def test_correct_corrected_replaces_price_and_quantity(
    service, capital, seal, permit
) -> None:
    _record_official(service, capital, seal, permit, execution_id="manual-exec-corr")
    cash_before = capital.capital_risk_snapshot(NOW).available_cash_cents

    # Correct to 990 cents (9_900_000 micros) x 90 -> applied gross 89_100.
    result = service.correct(
        execution_id="manual-exec-corr",
        revision=2,
        kind=ExecutionRevisionKind.CORRECTED,
        corrected_price_micros=9_900_000,
        corrected_quantity=90,
        operator_id="operator-alice",
        attachment_hash=HASH_C,
        context=ManualCorrectionContext(
            repository=capital,
            source_authority="manual-operator.v1",
            effective_at=OBSERVED_AT,
            observed_at=OBSERVED_AT,
        ),
    )
    receipt = result.revision_receipt
    assert receipt.revision_kind is ExecutionRevisionKind.CORRECTED
    assert receipt.reversed_gross_cents == FILL_GROSS_CENTS
    assert receipt.reversed_quantity == 100
    assert receipt.applied_gross_cents == 89_100
    assert receipt.applied_quantity == 90
    assert receipt.reopened is False

    snapshot = capital.capital_risk_snapshot(NOW)
    # Cash delta: the 104_000 gross returns and the 89_100 corrected gross
    # leaves again.
    assert snapshot.available_cash_cents == cash_before + FILL_GROSS_CENTS - 89_100
    quantities = {
        position.security_id: position.settled_quantity for position in snapshot.positions
    }
    assert quantities == {"600000.SH": 90}
    capital.assert_conservation()


def test_correct_after_bust_reopens_the_lot(service, capital, seal, permit) -> None:
    # BUST then CORRECT recreates real exposure through the reopen machinery:
    # the fact continues under the same execution_id, never a fresh copy.
    _record_official(service, capital, seal, permit, execution_id="manual-exec-reopen")
    service.correct(
        execution_id="manual-exec-reopen",
        revision=2,
        kind=ExecutionRevisionKind.BUSTED,
        operator_id="operator-alice",
        attachment_hash=HASH_B,
        context=ManualCorrectionContext(
            repository=capital,
            source_authority="manual-operator.v1",
            effective_at=OBSERVED_AT,
            observed_at=OBSERVED_AT,
        ),
    )
    result = service.correct(
        execution_id="manual-exec-reopen",
        revision=3,
        kind=ExecutionRevisionKind.CORRECTED,
        corrected_price_micros=10_500_000,
        corrected_quantity=105,
        operator_id="operator-alice",
        attachment_hash=HASH_D,
        context=ManualCorrectionContext(
            repository=capital,
            source_authority="manual-operator.v1",
            effective_at=OBSERVED_AT,
            observed_at=OBSERVED_AT,
        ),
    )
    assert result.revision_receipt.revision == 3
    assert result.revision_receipt.reopened is True
    assert result.revision_receipt.applied_quantity == 105
    snapshot = capital.capital_risk_snapshot(NOW)
    quantities = {
        position.security_id: position.settled_quantity for position in snapshot.positions
    }
    assert quantities == {"600000.SH": 105}
    capital.assert_conservation()


def test_correct_busted_after_corrected_quantity_change_uses_active_quantity(
    service, capital, seal, permit
) -> None:
    # record 100 -> CORRECTED to 90 -> BUSTED must bust the active 90, not the
    # stale recorded 100. The service tracks the active quantity so a bust
    # after a quantity-changing correction restates exactly what is live.
    _record_official(service, capital, seal, permit, execution_id="manual-exec-cb")
    service.correct(
        execution_id="manual-exec-cb",
        revision=2,
        kind=ExecutionRevisionKind.CORRECTED,
        corrected_price_micros=9_900_000,
        corrected_quantity=90,
        operator_id="operator-alice",
        attachment_hash=HASH_D,
        context=ManualCorrectionContext(
            repository=capital,
            source_authority="manual-operator.v1",
            effective_at=OBSERVED_AT,
            observed_at=OBSERVED_AT,
        ),
    )
    result = service.correct(
        execution_id="manual-exec-cb",
        revision=3,
        kind=ExecutionRevisionKind.BUSTED,
        operator_id="operator-alice",
        attachment_hash=HASH_B,
        context=ManualCorrectionContext(
            repository=capital,
            source_authority="manual-operator.v1",
            effective_at=OBSERVED_AT,
            observed_at=OBSERVED_AT,
        ),
    )
    receipt = result.revision_receipt
    assert receipt.revision_kind is ExecutionRevisionKind.BUSTED
    assert receipt.reversed_quantity == 90
    snapshot = capital.capital_risk_snapshot(NOW)
    assert {
        position.security_id: position.settled_quantity
        for position in snapshot.positions
    } == {}
    capital.assert_conservation()


# =============================================================================
# Scenario 8: corrections never copy a fact across modes or executions
# =============================================================================


def test_correct_rejects_execution_the_manual_service_never_recorded(
    service, repository
) -> None:
    _deposit(repository, 1_000_000, 1)
    stream_before = repository.stream_version()
    with pytest.raises(ExecutionError) as excinfo:
        service.correct(
            execution_id="foreign-broker-exec",
            revision=2,
            kind=ExecutionRevisionKind.BUSTED,
            operator_id="operator-alice",
            attachment_hash=HASH_B,
            context=ManualCorrectionContext(
                repository=repository,
                source_authority="manual-operator.v1",
                effective_at=OBSERVED_AT,
                observed_at=OBSERVED_AT,
            ),
        )
    assert excinfo.value.code == "manual_execution_unknown"
    # Zero-write: the unknown-execution guard fires before any capital write,
    # so the stream stays at its post-deposit position.
    assert repository.stream_version() == stream_before


def test_correct_continues_same_execution_without_copying(
    service, capital, seal, permit
) -> None:
    _record_official(service, capital, seal, permit, execution_id="manual-exec-cont")
    service.correct(
        execution_id="manual-exec-cont",
        revision=2,
        kind=ExecutionRevisionKind.BUSTED,
        operator_id="operator-alice",
        attachment_hash=HASH_B,
        context=ManualCorrectionContext(
            repository=capital,
            source_authority="manual-operator.v1",
            effective_at=OBSERVED_AT,
            observed_at=OBSERVED_AT,
        ),
    )
    # Every durable manual record shares the one execution identity; no fact
    # was transported to a second execution or another mode.
    execution_ids = {record.execution_id for record in service.records()}
    assert execution_ids == {"manual-exec-cont"}


# =============================================================================
# Scenario 9: idempotent replay and divergent-replay conflict
# =============================================================================


def test_record_replay_is_idempotent(service, capital, seal, permit) -> None:
    first = _record_official(service, capital, seal, permit)
    capital_version = capital.capital_version()
    stream_version = capital.stream_version()

    replay = _record_official(service, capital, seal, permit)
    # The ledger never advances on an idempotent replay.
    assert capital.capital_version() == capital_version
    assert capital.stream_version() == stream_version
    assert replay.execution_id == first.execution_id
    # The replayed fill/fee are the same economic fact (same execution id and
    # content-addressed event id). The returned receipts also carry an
    # environmental capital_version that tracks the live ledger, so the whole
    # receipt object is not byte-stable across replays even when the fact is;
    # compare economic identity instead (mirroring the proxy replay test).
    assert replay.fill_receipt.execution_id == first.fill_receipt.execution_id
    assert replay.fill_receipt.event_id == first.fill_receipt.event_id
    assert replay.fee_receipt.fill_execution_id == first.fee_receipt.fill_execution_id
    assert replay.fee_receipt.event_id == first.fee_receipt.event_id
    assert replay.record == first.record
    capital.assert_conservation()


def test_record_divergent_replay_conflicts(service, capital, seal, permit) -> None:
    _record_official(service, capital, seal, permit, execution_id="manual-exec-div")
    stream_before = capital.stream_version()
    # Same execution identity, different fill content: the service must fail
    # closed rather than overwrite the committed fact.
    divergent = _official_context(
        capital,
        seal,
        permit,
        execution_id="manual-exec-div",
        price_micros=9_900_000,  # different price under the same execution_id
        quantity=90,
    )
    with pytest.raises(ExecutionError) as excinfo:
        service.record(context=divergent)
    assert excinfo.value.code == "manual_record_conflict"
    assert capital.stream_version() == stream_before


# =============================================================================
# Scenario 10: crash mid-record replays to a complete state
# =============================================================================


_MANUAL_CRASH_PHASES = (
    "manual.after_fill",
    "manual.after_fee",
    "manual.after_record",
)


def _crashing_service(tmp_path: Path, clock: _Clock, phase: str) -> ManualExecutionService:
    def hook(name: str) -> None:
        if name == phase:
            raise RuntimeError(f"simulated crash at {name}")

    return ManualExecutionService(
        database_path=str(tmp_path / "manual-crash.sqlite3"),
        clock=clock,
        _fault_hook=hook,
    )


@pytest.mark.parametrize("phase", _MANUAL_CRASH_PHASES)
def test_crash_mid_record_replays_to_complete_state(
    tmp_path, clock, seal, permit, phase
) -> None:
    repository = CapitalRepository.initialize(tmp_path / "capital-crash.sqlite3")
    _deposit(repository, 1_000_000, 1)
    _seed_reserves(repository, seal)

    crashing = _crashing_service(tmp_path, clock, phase)
    crashed = False
    try:
        _record_official(crashing, repository, seal, permit, execution_id="manual-exec-crash")
    except ExecutionError:
        raise
    except RuntimeError as exc:
        assert "simulated crash" in str(exc)
        crashed = True
    assert crashed

    recovered = ManualExecutionService(
        database_path=str(tmp_path / "manual-crash.sqlite3"),
        clock=clock,
    )
    result = _record_official(
        recovered, repository, seal, permit, execution_id="manual-exec-crash"
    )
    assert result.official_oos is True
    assert result.fill_receipt.gross_cents == FILL_GROSS_CENTS

    snapshot = repository.capital_risk_snapshot(NOW)
    assert snapshot.available_cash_cents == 1_000_000 - FILL_GROSS_CENTS - FILL_FEE_CENTS
    assert snapshot.unattributed_risk_cents == 0
    assert snapshot.reconciliation_latch is ReconciliationLatchState.CLEAR
    quantities = {
        position.security_id: position.settled_quantity for position in snapshot.positions
    }
    assert quantities == {"600000.SH": 100}

    # A further replay stays converged: no duplicate economic effect.
    capital_version = repository.capital_version()
    _record_official(
        recovered, repository, seal, permit, execution_id="manual-exec-crash"
    )
    assert repository.capital_version() == capital_version
    repository.assert_conservation()


def test_manual_records_survive_restart(tmp_path, clock, capital, seal, permit) -> None:
    database_path = str(tmp_path / "manual-restart.sqlite3")
    first = ManualExecutionService(database_path=database_path, clock=clock)
    result = _record_official(first, capital, seal, permit, execution_id="manual-exec-restart")
    first_records = first.records()

    restarted = ManualExecutionService(database_path=database_path, clock=clock)
    restarted_records = restarted.records()
    assert restarted_records == first_records
    assert {record.execution_id for record in restarted_records} == {
        "manual-exec-restart"
    }
    # Replay through the restarted service converges to the same fact.
    replay = _record_official(
        restarted, capital, seal, permit, execution_id="manual-exec-restart"
    )
    assert replay.record == result.record
    capital.assert_conservation()
