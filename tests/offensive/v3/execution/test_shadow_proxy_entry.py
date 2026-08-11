"""Plan Task 9 RED: ShadowDecision-only T0 reserve and T+1 entry adapter.

The shadow adapter is the counterfactual counterpart to the authorised
``DailyBarProxy``. It consumes schema-major-3 ``ShadowDecision`` artifacts
read from a complete committed pair (never an ``ExecutionPermit`` or
``PortfolioDecisionSeal``), reserves worst-case cash per arm at T0, and
settles the T+1 entry through the shared ``settle_proxy_open`` core after a
frozen mechanical shrink. Every decision-derived fact lands in the arm's
mode-pure ``DAILY_BAR_PROXY`` ledger with a ``SHADOW_DECISION`` source
binding. The two arm ledgers are not one transaction: a crash after one arm
commits must let replay commit the other without changing the first.

RED today: ``ShadowProxyAdapter``, ``shadow_economic_id``, and the execution
context/receipt types do not exist yet.
"""

from __future__ import annotations

import sys
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from src.screening.offensive.v3.capital.fees import FeePolicy
from src.screening.offensive.v3.capital.provenance import CapitalSourceBinding
from src.screening.offensive.v3.capital.repository import (
    AccountBinding,
    CapitalCommand,
    CapitalCommandPayload,
    CapitalRepository,
)
from src.screening.offensive.v3.contracts import (
    ArtifactKind,
    CashEconomicEventLeg,
    CashReceivableEconomicEventLeg,
    EconomicAssetKind,
    EconomicEventKind,
    EconomicLegDirection,
    ExecutionMode,
)
from src.screening.offensive.v3.contracts.decision import ShadowDecision
from src.screening.offensive.v3.contracts.execution import (
    PermitLineMechanicalBinding,
    PermitReasonCode,
    resolve_mechanical_quantity,
)
from src.screening.offensive.v3.contracts.trial import TrialArm
from src.screening.offensive.v3.execution.lifecycle import (
    DailyBar,
    OpenExecutionVerdict,
)
from src.screening.offensive.v3.execution.proxy_core import ProxyCostScenario
from src.screening.offensive.v3.execution.shadow_proxy import (  # RED target
    ShadowArmExecutionContext,
    ShadowEntryResult,
    ShadowProxyAdapter,
    ShadowProxyError,
    ShadowReserveReceipt,
    shadow_economic_id,
)
from src.screening.offensive.v3.orchestration.trial_store import (
    TrialArmDecisionRecord,
    TrialArmDecisionStore,
)

# Reuse the kernel test's frozen paired world (real GrowthKernel ShadowDecisions
# are the exact payloads the durable store wraps and the adapter consumes).
_KERNEL_TEST_DIR = Path(__file__).resolve().parents[1] / "kernel"
if str(_KERNEL_TEST_DIR) not in sys.path:
    sys.path.insert(0, str(_KERNEL_TEST_DIR))
from test_shadow_kernel import (  # noqa: E402
    CLOSE,
    HASH,
    NOW,
    PORTFOLIO,
    SIGNAL_DATE,
    _paired_world,
    _sap,
    _trial_manifest,
    _trial_policy,
)

from src.screening.offensive.v3.contracts.governance import PolicyActivation  # noqa: E402
from src.screening.offensive.v3.contracts.regime import (  # noqa: E402
    RegimeAdmissionMode,
    RegimeState,
)
from src.screening.offensive.v3.governance.regime_trial import (  # noqa: E402
    RegimeTrialBundle,
)
from src.screening.offensive.v3.kernel.decide import GrowthKernel  # noqa: E402
from src.screening.offensive.v3.kernel.sizing import SizingConfig  # noqa: E402
from src.screening.offensive.v3.orchestration.genesis import (  # noqa: E402
    TrialGenesisManifest,
)

UTC = timezone.utc
TRIAL_ID = "trial-regime-001"
ZERO64 = "0" * 64
# The T+1 entry command is issued inside the T0 evening window; the gateway
# send deadline is CLOSE + 18h25 (2026-08-06 09:25 UTC). The settlement
# records at the T+1 opening-auction moment, which follows the T0 command.
COMMAND_AT = datetime(2026, 8, 5, 16, 0, tzinfo=UTC)
SEND_DEADLINE = CLOSE + timedelta(hours=18, minutes=25)
RECORDED_AT = datetime(2026, 8, 6, 1, 25, tzinfo=UTC)
OBSERVE_AT = RECORDED_AT

FEE_POLICY = FeePolicy(
    fee_policy_version="cn-a-share-30bps-tax.v2",
    commission_rate_ppm=3_000,
    min_commission_cents=500,
    stamp_tax_rate_ppm=1_000,
    transfer_fee_rate_ppm=20,
)


def _cost_scenario(slippage_bps: int = 30) -> ProxyCostScenario:
    return ProxyCostScenario(
        scenario_id="current-cost" if slippage_bps == 30 else "double-slippage",
        entry_slippage_bps=slippage_bps,
        exit_slippage_bps=slippage_bps,
        fee_policy=FEE_POLICY,
    )


# =============================================================================
# Frozen paired world: real kernel ShadowDecisions committed to a store
# =============================================================================


def _bundle() -> RegimeTrialBundle:
    baseline = _trial_policy(RegimeAdmissionMode.IGNORE)
    target = _trial_policy(RegimeAdmissionMode.NORMAL_ONLY)
    trial = _trial_manifest(baseline, target)
    sap = _sap(trial)
    activation = PolicyActivation(
        portfolio_id=PORTFOLIO,
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


def _paired_decisions():
    champion_input, challenger_input, *_ = _paired_world(regime_state=RegimeState.NORMAL)
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


def _record(arm: TrialArm, decision) -> TrialArmDecisionRecord:
    session = decision.counterfactual_key.signal_session
    cycle = decision.counterfactual_key.counterfactual_cycle_id
    return TrialArmDecisionRecord(
        trial_id=TRIAL_ID,
        signal_session=session,
        decision_cycle_id=cycle,
        arm=arm,
        shared_input_hash=f"{session.isoformat()}/{cycle}",
        arm_policy_fingerprint=decision.shadow_policy_binding.policy_fingerprint,
        arm_capital_checkpoint_hash=HASH,
        regime_observation_hash=HASH,
        decision=decision,
        created_at=NOW,
        artifact_hash=decision.content_hash(),
    )


def _pair_key(decision: ShadowDecision) -> tuple[str, str, str]:
    key = decision.counterfactual_key
    return (TRIAL_ID, key.signal_session.isoformat(), key.counterfactual_cycle_id)


class _Clock:
    def __init__(self, start: datetime) -> None:
        self._moment = start

    def __call__(self) -> datetime:
        return self._moment


# -- capital seeding (mirror the proxy economic-core seed) -------------------


def _seed_moment(step: int) -> datetime:
    return CLOSE - timedelta(minutes=10) + timedelta(minutes=step)


def _deposit(repository: CapitalRepository, cents: int, sequence: int) -> None:
    amount = Decimal(cents) / 100
    receivable_id = f"rcv-{sequence}"
    binding = AccountBinding(
        portfolio_id=PORTFOLIO,
        mode=ExecutionMode.DAILY_BAR_PROXY,
        broker_account_id=None,
        base_currency="CNY",
        environment_fingerprint=None,
    )
    repository.append_atomic(
        CapitalCommand(
            idempotency_key=f"declare-{sequence}",
            account_binding=binding,
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
            account_binding=binding,
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


def _funded_repo(tmp_path: Path, name: str) -> CapitalRepository:
    repository = CapitalRepository.initialize(tmp_path / f"{name}.sqlite3")
    _deposit(repository, 1_000_000, 1)
    return repository


def _mechanical_bindings(decision: ShadowDecision) -> dict[str, PermitLineMechanicalBinding]:
    """Unchanged-quantity frozen caps for every shadow line (no shrink)."""

    bindings: dict[str, PermitLineMechanicalBinding] = {}
    for line in decision.counterfactual_lines:
        bindings[line.shadow_line_id] = PermitLineMechanicalBinding(
            order_line_id=line.shadow_line_id,
            predicate_policy_version=line.execution_assumption_version,
            preopen_fact_snapshot_id="preopen-facts-shadow-1",
            preopen_fact_snapshot_hash=HASH,
            preopen_fact_as_of=NOW,
            availability_cap_units=line.target_quantity_units,
            price_cap_units=line.target_quantity_units,
            capacity_cap_units=line.target_quantity_units,
            cash_cap_units=line.target_quantity_units,
            capital_risk_cap_units=line.target_quantity_units,
        )
    return bindings


def _touching_bars(decision: ShadowDecision) -> dict[str, DailyBar]:
    """A buy bar whose open sits below each line's limit so the entry fills."""

    bars: dict[str, DailyBar] = {}
    for line in decision.counterfactual_lines:
        limit = int(line.limit_price_cents)
        bars[line.security_id] = DailyBar(
            security_id=line.security_id,
            session=decision.target_entry_session,
            open_cents=limit - 10,
            high_cents=limit + 5,
            low_cents=limit - 15,
            close_cents=limit - 5,
            limit_up_cents=int(limit * 11 // 10),
            limit_down_cents=int(limit * 9 // 10),
        )
    return bars


# =============================================================================
# Shared world fixture: registered trial + committed pair + funded arms
# =============================================================================


class _World:
    """One frozen paired world bound to per-test temp directories."""

    def __init__(self, tmp_path: Path) -> None:
        self.champion_decision, self.challenger_decision = _paired_decisions()
        self.decisions = {
            TrialArm.CHAMPION: self.champion_decision,
            TrialArm.CHALLENGER: self.challenger_decision,
        }
        self.pair_key = _pair_key(self.champion_decision)
        self.target_session = self.champion_decision.target_entry_session
        self.store = TrialArmDecisionStore(database_path=str(tmp_path / "trial.sqlite3"))
        self.store.register_trial(_bundle(), _genesis_manifest())
        self.store.commit_pair(
            _record(TrialArm.CHAMPION, self.champion_decision),
            _record(TrialArm.CHALLENGER, self.challenger_decision),
        )
        self.lease = self.store.claim_writer()
        self.capital = {
            TrialArm.CHAMPION: _funded_repo(tmp_path, "champion-capital"),
            TrialArm.CHALLENGER: _funded_repo(tmp_path, "challenger-capital"),
        }
        self.adapter = ShadowProxyAdapter(
            database_path=str(tmp_path / "shadow-proxy.sqlite3"),
            clock=_Clock(RECORDED_AT),
        )

    def context(self, arm: TrialArm, **overrides) -> ShadowArmExecutionContext:
        defaults = dict(
            trial_id=TRIAL_ID,
            arm=arm,
            portfolio_id=PORTFOLIO,
            decision_store=self.store,
            capital_repository=self.capital[arm],
            writer_lease=self.lease,
        )
        defaults.update(overrides)
        return ShadowArmExecutionContext(**defaults)

    def contexts(self, **overrides_per_arm) -> dict[TrialArm, ShadowArmExecutionContext]:
        return {
            TrialArm.CHAMPION: self.context(TrialArm.CHAMPION, **overrides_per_arm.get(TrialArm.CHAMPION, {})),
            TrialArm.CHALLENGER: self.context(TrialArm.CHALLENGER, **overrides_per_arm.get(TrialArm.CHALLENGER, {})),
        }


@pytest.fixture()
def world(tmp_path: Path) -> _World:
    return _World(tmp_path)


# =============================================================================
# Step 1: admission boundary
# =============================================================================


def test_shadow_economic_id_is_stable_and_deterministic() -> None:
    # Same inputs -> same id; any field change -> different id.
    base = shadow_economic_id(TRIAL_ID, TrialArm.CHAMPION, "cyc-1", "line-1", "entry-reserve")
    assert base == shadow_economic_id(TRIAL_ID, TrialArm.CHAMPION, "cyc-1", "line-1", "entry-reserve")
    assert base != shadow_economic_id(TRIAL_ID, TrialArm.CHALLENGER, "cyc-1", "line-1", "entry-reserve")
    assert base != shadow_economic_id(TRIAL_ID, TrialArm.CHAMPION, "cyc-2", "line-1", "entry-reserve")
    assert base != shadow_economic_id(TRIAL_ID, TrialArm.CHAMPION, "cyc-1", "line-2", "entry-reserve")
    assert base != shadow_economic_id(TRIAL_ID, TrialArm.CHAMPION, "cyc-1", "line-1", "entry-fill")


def test_reserve_requires_complete_pair(world) -> None:
    contexts = world.contexts()
    before = {
        arm: ctx.capital_repository.capital_risk_snapshot(OBSERVE_AT)
        for arm, ctx in contexts.items()
    }
    # A key with no committed pair is not a complete pair.
    bogus_key = (TRIAL_ID, SIGNAL_DATE.isoformat(), "nonexistent-cycle")
    with pytest.raises(ShadowProxyError, match="pair_not_committed"):
        world.adapter.reserve_committed_pair(bogus_key, contexts)
    after = {
        arm: ctx.capital_repository.capital_risk_snapshot(OBSERVE_AT)
        for arm, ctx in contexts.items()
    }
    # No capital write happened on rejection.
    assert after == before


def test_reserve_rejects_stale_writer_lease(world) -> None:
    contexts = world.contexts()
    # A second claim bumps the epoch; the original lease is now stale.
    world.store.claim_writer()
    with pytest.raises((ShadowProxyError, Exception), match="fencing|stale"):
        world.adapter.reserve_committed_pair(world.pair_key, contexts)


def test_reserve_rejects_wrong_trial(world) -> None:
    contexts = world.contexts(
        **{TrialArm.CHAMPION: dict(trial_id="trial-other")},
    )
    with pytest.raises(ShadowProxyError, match="trial_mismatch"):
        world.adapter.reserve_committed_pair(world.pair_key, contexts)


def test_reserve_rejects_wrong_portfolio(world) -> None:
    contexts = world.contexts(
        **{TrialArm.CHAMPION: dict(portfolio_id="portfolio-other")},
    )
    with pytest.raises(ShadowProxyError, match="portfolio_mismatch"):
        world.adapter.reserve_committed_pair(world.pair_key, contexts)


def test_reserve_rejects_non_shadow_authority(world) -> None:
    # The contract pins ``execution_authority`` to Literal["NONE"] and the
    # content hash re-validates it, so the store can never hold a non-NONE
    # decision. The adapter still re-validates defensively: if a tampered
    # decision reached the admission gate, it must fail before any capital
    # write. Bypass the frozen field without touching content_hash.
    arm = TrialArm.CHAMPION
    tampered = world.decisions[arm]
    object.__setattr__(tampered, "execution_authority", "FULL")
    with pytest.raises(ShadowProxyError, match="execution_authority"):
        world.adapter._validate_admission(tampered, world.context(arm))


# =============================================================================
# Step 2: lifecycle — atomic T0 reserves, bindings, shrink, fill, release
# =============================================================================


def test_atomic_multi_line_t0_reserves_bind_decision_and_arm(world) -> None:
    contexts = world.contexts()
    receipts = world.adapter.reserve_committed_pair(world.pair_key, contexts)
    assert set(receipts) == {TrialArm.CHAMPION, TrialArm.CHALLENGER}
    for arm, ctx in contexts.items():
        receipt = receipts[arm]
        decision = world.decisions[arm]
        assert isinstance(receipt, ShadowReserveReceipt)
        assert receipt.arm is arm
        assert receipt.portfolio_id == PORTFOLIO
        assert receipt.shadow_decision_id == decision.shadow_decision_id
        assert receipt.artifact_hash == decision.artifact_hash()
        expected_reserved = sum(
            int(line.estimated_cash_reserve_cents)
            for line in decision.counterfactual_lines
        )
        assert receipt.reserved_cash_cents == expected_reserved
        snapshot = ctx.capital_repository.capital_risk_snapshot(OBSERVE_AT)
        assert snapshot.reserved_cash_cents == expected_reserved
        assert snapshot.restricted_cash_cents == expected_reserved
        ctx.capital_repository.assert_conservation()


def test_reserve_source_bindings_carry_shadow_decision(world) -> None:
    contexts = world.contexts()
    receipts = world.adapter.reserve_committed_pair(world.pair_key, contexts)
    import sqlalchemy as sa

    for arm, ctx in contexts.items():
        decision = world.decisions[arm]
        receipt = receipts[arm]
        with ctx.capital_repository.engine.connect() as conn:  # noqa: SLF001
            rows = conn.execute(
                sa.text(
                    "SELECT source_binding_json FROM reserves"
                    " WHERE source_id IN :ids"
                ).bindparams(sa.bindparam("ids", expanding=True)),
                {"ids": list(receipt.reserve_source_ids)},
            ).fetchall()
        assert rows
        for row in rows:
            binding = CapitalSourceBinding.model_validate_json(row.source_binding_json)
            assert binding.mode is ExecutionMode.DAILY_BAR_PROXY
            assert binding.artifact_kind is ArtifactKind.SHADOW_DECISION
            assert binding.artifact_id == decision.shadow_decision_id
            assert binding.artifact_hash == decision.artifact_hash()


def test_reserve_stable_source_ids_are_deterministic(world) -> None:
    contexts = world.contexts()
    receipts = world.adapter.reserve_committed_pair(world.pair_key, contexts)
    for arm, ctx in contexts.items():
        decision = world.decisions[arm]
        for line in decision.counterfactual_lines:
            expected = shadow_economic_id(
                TRIAL_ID, arm, decision.counterfactual_key.counterfactual_cycle_id,
                line.shadow_line_id, "entry-reserve",
            )
            assert expected in receipts[arm].reserve_source_ids


def test_mechanical_shrink_never_exceeds_t0_target(world) -> None:
    contexts = world.contexts()
    world.adapter.reserve_committed_pair(world.pair_key, contexts)
    # A sub-lot cash cap floors the executable quantity to zero; it can never
    # grow beyond the sealed target. The reason follows the frozen cap
    # priority (cash owns this shrink).
    arm = TrialArm.CHAMPION
    decision = world.decisions[arm]
    line = decision.counterfactual_lines[0]
    lot = int(line.lot_size_units)
    shrunk = dict(_mechanical_bindings(decision))
    shrunk[line.shadow_line_id] = shrunk[line.shadow_line_id].model_copy(
        update={"cash_cap_units": lot // 2}
    )
    result = world.adapter.execute_entries(
        world.pair_key,
        world.context(arm),
        mechanical_bindings=shrunk,
        bars=_touching_bars(decision),
        scenario=_cost_scenario(30),
        command_at=COMMAND_AT,
        send_deadline=SEND_DEADLINE,
    )
    line_result = next(r for r in result.lines if r.shadow_line_id == line.shadow_line_id)
    assert line_result.permitted_quantity_units == 0
    assert line_result.permitted_quantity_units <= int(line.target_quantity_units)
    assert line_result.reason_code is PermitReasonCode.CASH_REDUCTION
    assert line_result.verdict is OpenExecutionVerdict.NO_FILL
    world.capital[arm].assert_conservation()


def test_current_cost_fill_consumes_reserve_and_books_fee(world) -> None:
    contexts = world.contexts()
    world.adapter.reserve_committed_pair(world.pair_key, contexts)
    arm = TrialArm.CHAMPION
    decision = world.decisions[arm]
    result = world.adapter.execute_entries(
        world.pair_key,
        world.context(arm),
        mechanical_bindings=_mechanical_bindings(decision),
        bars=_touching_bars(decision),
        scenario=_cost_scenario(30),
        command_at=COMMAND_AT,
        send_deadline=SEND_DEADLINE,
    )
    assert isinstance(result, ShadowEntryResult)
    assert result.arm is arm
    line = decision.counterfactual_lines[0]
    line_result = next(r for r in result.lines if r.shadow_line_id == line.shadow_line_id)
    assert line_result.verdict is OpenExecutionVerdict.FILLED
    assert line_result.fill_receipt is not None
    assert line_result.fee_receipt is not None
    assert line_result.fee_receipt.fee_policy_version == FEE_POLICY.fee_policy_version
    world.capital[arm].assert_conservation()


def test_unknown_bar_releases_reserve_and_keeps_cash(world) -> None:
    contexts = world.contexts()
    world.adapter.reserve_committed_pair(world.pair_key, contexts)
    arm = TrialArm.CHAMPION
    decision = world.decisions[arm]
    result = world.adapter.execute_entries(
        world.pair_key,
        world.context(arm),
        mechanical_bindings=_mechanical_bindings(decision),
        bars={},  # missing bar -> UNKNOWN
        scenario=_cost_scenario(30),
        command_at=COMMAND_AT,
        send_deadline=SEND_DEADLINE,
    )
    line_result = result.lines[0]
    assert line_result.verdict is OpenExecutionVerdict.UNKNOWN
    assert line_result.reason == "missing_bar"
    decision_line = decision.counterfactual_lines[0]
    assert line_result.released_reserve_cents == int(
        decision_line.estimated_cash_reserve_cents
    )
    snapshot = world.capital[arm].capital_risk_snapshot(OBSERVE_AT)
    assert snapshot.reserved_cash_cents == 0
    assert snapshot.available_cash_cents == 1_000_000
    world.capital[arm].assert_conservation()


def test_execute_rejects_wrong_target_session(world) -> None:
    contexts = world.contexts()
    world.adapter.reserve_committed_pair(world.pair_key, contexts)
    arm = TrialArm.CHAMPION
    decision = world.decisions[arm]
    with pytest.raises(ShadowProxyError, match="target_session"):
        world.adapter.execute_entries(
            world.pair_key,
            world.context(arm),
            mechanical_bindings=_mechanical_bindings(decision),
            bars={},
            scenario=_cost_scenario(30),
            command_at=COMMAND_AT,
            send_deadline=SEND_DEADLINE,
            target_session=date(2099, 1, 1),
        )


def test_execute_requires_committed_reserve_first(world) -> None:
    arm = TrialArm.CHAMPION
    decision = world.decisions[arm]
    with pytest.raises(ShadowProxyError, match="reserve_not_committed|reserve"):
        world.adapter.execute_entries(
            world.pair_key,
            world.context(arm),
            mechanical_bindings=_mechanical_bindings(decision),
            bars=_touching_bars(decision),
            scenario=_cost_scenario(30),
            command_at=COMMAND_AT,
            send_deadline=SEND_DEADLINE,
        )


# =============================================================================
# Step 2: replay, conflict, crash recovery
# =============================================================================


def test_exact_replay_of_reserve_is_idempotent(world) -> None:
    contexts = world.contexts()
    first = world.adapter.reserve_committed_pair(world.pair_key, contexts)
    champ_v = world.capital[TrialArm.CHAMPION].capital_version()
    champ_sv = world.capital[TrialArm.CHAMPION].stream_version()
    replay = world.adapter.reserve_committed_pair(world.pair_key, contexts)
    assert {arm: r.reserve_source_ids for arm, r in replay.items()} == {
        arm: r.reserve_source_ids for arm, r in first.items()
    }
    assert world.capital[TrialArm.CHAMPION].capital_version() == champ_v
    assert world.capital[TrialArm.CHAMPION].stream_version() == champ_sv


def test_exact_replay_of_execute_is_idempotent(world) -> None:
    contexts = world.contexts()
    world.adapter.reserve_committed_pair(world.pair_key, contexts)
    arm = TrialArm.CHAMPION
    decision = world.decisions[arm]
    bars = _touching_bars(decision)
    first = world.adapter.execute_entries(
        world.pair_key,
        world.context(arm),
        mechanical_bindings=_mechanical_bindings(decision),
        bars=bars,
        scenario=_cost_scenario(30),
        command_at=COMMAND_AT,
        send_deadline=SEND_DEADLINE,
    )
    cap_v = world.capital[arm].capital_version()
    stream_v = world.capital[arm].stream_version()
    replay = world.adapter.execute_entries(
        world.pair_key,
        world.context(arm),
        mechanical_bindings=_mechanical_bindings(decision),
        bars=bars,
        scenario=_cost_scenario(30),
        command_at=COMMAND_AT,
        send_deadline=SEND_DEADLINE,
    )
    assert replay.lines[0].verdict is first.lines[0].verdict
    assert replay.lines[0].fill_price_cents == first.lines[0].fill_price_cents
    assert world.capital[arm].capital_version() == cap_v
    assert world.capital[arm].stream_version() == stream_v


def test_divergent_replay_raises_protocol_breach(world) -> None:
    contexts = world.contexts()
    world.adapter.reserve_committed_pair(world.pair_key, contexts)
    arm = TrialArm.CHAMPION
    decision = world.decisions[arm]
    bars = _touching_bars(decision)
    world.adapter.execute_entries(
        world.pair_key,
        world.context(arm),
        mechanical_bindings=_mechanical_bindings(decision),
        bars=bars,
        scenario=_cost_scenario(30),
        command_at=COMMAND_AT,
        send_deadline=SEND_DEADLINE,
    )
    # Replay under a different cost scenario (60bps vs 30bps) under the same
    # stable execution id is a protocol breach, not a silent re-settlement.
    with pytest.raises(ShadowProxyError, match="shadow_proxy_protocol_breach|protocol_breach"):
        world.adapter.execute_entries(
            world.pair_key,
            world.context(arm),
            mechanical_bindings=_mechanical_bindings(decision),
            bars=bars,
            scenario=_cost_scenario(60),
            command_at=COMMAND_AT,
            send_deadline=SEND_DEADLINE,
        )


def test_one_arm_crash_then_recover_commits_other_arm(tmp_path) -> None:
    world = _World(tmp_path)
    contexts = world.contexts()

    # Crash after the champion arm's reserve lands but before the challenger
    # arm is touched. The champion capital write is durable; the process dies.
    def crash_after_champion(phase: str) -> None:
        if phase == "shadow.after_arm_reserve:CHAMPION":
            raise RuntimeError("simulated crash after champion reserve")

    crashing = ShadowProxyAdapter(
        database_path=str(tmp_path / "crash-proxy.sqlite3"),
        clock=_Clock(NOW),
        _fault_hook=crash_after_champion,
    )
    with pytest.raises(RuntimeError, match="simulated crash"):
        crashing.reserve_committed_pair(world.pair_key, contexts)

    # Champion reserve is durable; champion capital reflects the reserve.
    champ_snap = world.capital[TrialArm.CHAMPION].capital_risk_snapshot(OBSERVE_AT)
    assert champ_snap.reserved_cash_cents > 0
    # Challenger capital is untouched.
    chall_snap = world.capital[TrialArm.CHALLENGER].capital_risk_snapshot(OBSERVE_AT)
    assert chall_snap.reserved_cash_cents == 0

    # Recovery: a fresh adapter commits the challenger arm without changing
    # the champion arm.
    recovered = ShadowProxyAdapter(
        database_path=str(tmp_path / "crash-proxy.sqlite3"),
        clock=_Clock(NOW),
    )
    receipts = recovered.reserve_committed_pair(world.pair_key, contexts)
    assert receipts[TrialArm.CHALLENGER].reserved_cash_cents > 0
    champ_after = world.capital[TrialArm.CHAMPION].capital_risk_snapshot(OBSERVE_AT)
    assert champ_after == champ_snap
    for arm in (TrialArm.CHAMPION, TrialArm.CHALLENGER):
        world.capital[arm].assert_conservation()


def test_execute_crash_recovery_from_append_only_phase_facts(tmp_path) -> None:
    world = _World(tmp_path)
    contexts = world.contexts()
    world.adapter.reserve_committed_pair(world.pair_key, contexts)
    arm = TrialArm.CHAMPION
    decision = world.decisions[arm]
    bars = _touching_bars(decision)

    # Crash after the capital settle lands but before the durable phase fact
    # is recorded. On replay, the append-only fact store must converge to the
    # direct-settle state without double-charging.
    def crash_after_settle(phase: str) -> None:
        if phase == "shadow.after_settle":
            raise RuntimeError("simulated crash after settle")

    crashing = ShadowProxyAdapter(
        database_path=str(tmp_path / "shadow-proxy.sqlite3"),
        clock=_Clock(RECORDED_AT),
        _fault_hook=crash_after_settle,
    )
    with pytest.raises(RuntimeError, match="simulated crash"):
        crashing.execute_entries(
            world.pair_key,
            world.context(arm),
            mechanical_bindings=_mechanical_bindings(decision),
            bars=bars,
            scenario=_cost_scenario(30),
            command_at=COMMAND_AT,
            send_deadline=SEND_DEADLINE,
        )
    cap_after_crash = world.capital[arm].capital_version()

    recovered = ShadowProxyAdapter(
        database_path=str(tmp_path / "shadow-proxy.sqlite3"),
        clock=_Clock(RECORDED_AT),
    )
    result = recovered.execute_entries(
        world.pair_key,
        world.context(arm),
        mechanical_bindings=_mechanical_bindings(decision),
        bars=bars,
        scenario=_cost_scenario(30),
        command_at=COMMAND_AT,
        send_deadline=SEND_DEADLINE,
    )
    assert result.lines[0].verdict is OpenExecutionVerdict.FILLED
    # No double-charge: the recovered settle did not advance capital again.
    assert world.capital[arm].capital_version() == cap_after_crash
    world.capital[arm].assert_conservation()


def test_both_arms_settle_independently_with_equal_genesis(world) -> None:
    # Both arms reserve and settle the same economics; their normalized
    # capital snapshots must match exactly (identity excluded only by
    # portfolio, which both share here).
    contexts = world.contexts()
    world.adapter.reserve_committed_pair(world.pair_key, contexts)
    for arm in (TrialArm.CHAMPION, TrialArm.CHALLENGER):
        decision = world.decisions[arm]
        world.adapter.execute_entries(
            world.pair_key,
            world.context(arm),
            mechanical_bindings=_mechanical_bindings(decision),
            bars=_touching_bars(decision),
            scenario=_cost_scenario(30),
            command_at=COMMAND_AT,
            send_deadline=SEND_DEADLINE,
        )
    champ = world.capital[TrialArm.CHAMPION].capital_risk_snapshot(OBSERVE_AT)
    chall = world.capital[TrialArm.CHALLENGER].capital_risk_snapshot(OBSERVE_AT)
    assert champ.available_cash_cents == chall.available_cash_cents
    assert champ.reserved_cash_cents == chall.reserved_cash_cents
    for arm in (TrialArm.CHAMPION, TrialArm.CHALLENGER):
        world.capital[arm].assert_conservation()


# =============================================================================
# Step 7: forbidden-dependency AST boundary
# =============================================================================

#: The shadow adapter may depend only on contracts, evidence/capital read
#: models, the capital kernel, the shared settlement core, and the durable
#: arm decision store. It must never import gateway decisions/authority,
#: orchestration shadow trust, broker, outbox, network, or the production
#: adapter (the authorised ``DailyBarProxy``).
_V3_PREFIX = "src.screening.offensive.v3."

#: Allowed v3 submodule paths (prefix-match on the dotted path after the
#: v3 prefix). ``contracts`` and ``capital`` are broad; execution is narrowed
#: to the shared core + lifecycle only; orchestration is narrowed to the
#: trial decision store only.
_ALLOWED_V3_PREFIXES = (
    "contracts",
    "capital",
    "execution.proxy_core",
    "execution.lifecycle",
    "kernel.models",
    "orchestration.trial_store",
)

#: Explicitly forbidden first-level v3 packages — a clear failure if any
#: import touches them at all.
_FORBIDDEN_V3_FIRST_LEVEL = frozenset(
    {
        "gateway",
        "broker",
        "services",
        "storage",
        "trust",
        "migration",
        "producers",
        "reporting",
        "canary",
        "policy",
        "cli",
    }
)

#: Forbidden execution submodules — the production adapter and the manual
#: adapter must never feed a counterfactual shadow entry.
_FORBIDDEN_EXECUTION_SUBMODULES = frozenset(
    {
        "execution.proxy",
        "execution.manual",
    }
)


def test_shadow_proxy_imports_only_allowed_dependencies() -> None:
    import ast

    module_path = (
        Path(__file__).resolve().parents[4]
        / "src/screening/offensive/v3/execution/shadow_proxy.py"
    )
    tree = ast.parse(module_path.read_text(encoding="utf-8"), filename=str(module_path))

    v3_imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith(_V3_PREFIX):
            v3_imports.append(node.module)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith(_V3_PREFIX):
                    v3_imports.append(alias.name)

    assert v3_imports, "expected the adapter to import at least one v3 submodule"

    violations: list[str] = []
    for module in v3_imports:
        sub = module[len(_V3_PREFIX):]
        first_level = sub.split(".", 1)[0]
        if first_level in _FORBIDDEN_V3_FIRST_LEVEL:
            violations.append(f"{module}: forbidden package '{first_level}'")
            continue
        if sub in _FORBIDDEN_EXECUTION_SUBMODULES:
            violations.append(f"{module}: forbidden execution submodule")
            continue
        # orchestration is allowed only via the trial decision store.
        if first_level == "orchestration" and not sub.startswith("orchestration.trial_store"):
            violations.append(f"{module}: orchestration imports must be trial_store only")
            continue
        if not any(sub == prefix or sub.startswith(prefix + ".") for prefix in _ALLOWED_V3_PREFIXES):
            violations.append(f"{module}: not in the allowed dependency set")
    assert not violations, "shadow_proxy.py has forbidden dependencies:\n  " + "\n  ".join(
        sorted(violations)
    )


def test_shadow_proxy_exposes_no_permit_or_seal_or_broker_surface() -> None:
    # The adapter's public surface must not accept or return any gateway,
    # broker, outbox, or permit artifact: a shadow entry can never be turned
    # into an executable order through this module.
    import inspect

    from src.screening.offensive.v3.execution import shadow_proxy

    public = {
        name
        for name, member in inspect.getmembers(shadow_proxy)
        if (inspect.isclass(member) or inspect.isfunction(member))
        and member.__module__ == shadow_proxy.__name__
    }
    forbidden_substrings = ("Permit", "Seal", "Broker", "Outbox", "Gateway", "Envelope", "Authority")
    leaked = [name for name in public if any(s in name for s in forbidden_substrings)]
    assert not leaked, f"shadow_proxy leaks gateway/authority surface: {leaked}"
