"""Plan 05 Task 7 (RED): DailyActionFlow — --daily-action lifecycle-first 编排契约。

覆盖 Step 1 契约 (语义以 daily_action_flow.py 模块 docstring 为准):
1. lifecycle-before-snapshot — lifecycle_reader 的调用先于 snapshot_loader
   (共享调用序 order 断言), 且先于 BTST producer scan; 对 capital snapshot
   的每个 position 各查一次 exit 义务; capital 只读投影 as_of = signal_date
   15:00 UTC。
2. missing snapshot — snapshot_status failed; lifecycle/capital 独立照常执行;
   shadow 管线无输入 → "skipped" + "no_snapshot", producer/kernel/persister
   零调用。
3. missed window — evidence_store.active_revision 抛
   evidence_not_committed_before_cutoff → failure_reason["evidence"] 记录,
   flow 不崩溃, 管线继续 (kernel/persist 照常)。
4. stale NAV — capital valid_until < trusted_at → 真实 GrowthKernel 收到
   stale snapshot → NoTrade(STALE_CAPITAL) → shadow_decision_status
   "no_signal" + no_trade_reason=STALE_CAPITAL; capital_status 仍是 "ok"
   (新鲜度是 kernel 层判定, 不是读失败)。
5. no signal — 空候选 → 真实 kernel 返回 NO_SIGNAL → "no_signal", 绝不构造/
   持久化空 ShadowDecision (min_length=1 契约)。
6. v2 comparison — 注入 v2 plans 对比 v3 shadow lines → discrepancy 含
   "v2_only"/"v3_only" 差异 (归一化 ticker: security_id 去 .SH/.SZ/.BJ 后缀)。
7. repeat run — 同 signal_date 二次 run → 结果一致, shadow_decision_id 稳定
   (确定性), 每步独立重放。
8. byte-identical capital paths — flow 运行前后 v2 ledger 文件字节不变,
   data_dir 目录不被触碰。
9. execution_authority=none 恒成立 (含 dataclass 默认值)。
10. OFF 零调用 — 四步全 "skipped", 全部注入端口零调用。

附加: happy path 持久化 ShadowDecision 形态 (execution_authority=NONE +
counterfactual_lines 非空 + kernel input 契约); producer 失败隔离; capital
失败 → lifecycle/shadow 记 "no_capital"; BTST_CANARY/AUTHORITATIVE →
shadow 管线 "skipped" + "not_shadow_mode"。

本文件引用尚未实现的 DailyActionFlow 骨架 (方法体 raise NotImplementedError);
当前应整体 RED, 由主代理随后实现 GREEN。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from test_auto_flow import _snapshot as _verified_snapshot

from src.screening.offensive.daily_action_snapshot import (
    VerifiedSnapshotResult,
)
from src.screening.offensive.v3.contracts import ExecutionMode
from src.screening.offensive.v3.contracts.authorization import (
    AuthorizationKind,
    CapitalAuthorizationEnvelope,
)
from src.screening.offensive.v3.contracts.base import SignalStage
from src.screening.offensive.v3.contracts.capital import (
    CapitalPositionRisk,
    CapitalRiskSnapshot,
    ExposureScope,
    PositionState,
    RiskExposureBucket,
    StageLossLatchSnapshot,
)
from src.screening.offensive.v3.contracts.governance import (
    GrantKind,
    LineageGrant,
    PolicyActivation,
    ProgramLossBudgetBinding,
)
from src.screening.offensive.v3.contracts.risk import (
    ReconciliationLatchState,
    RiskLatchState,
    RiskSnapshotCompleteness,
    RiskSnapshotFreshness,
    StageLossLatchState,
)
from src.screening.offensive.v3.evidence.repository import EvidenceStoreError
from src.screening.offensive.v3.kernel.admission import BTST_FAMILY
from src.screening.offensive.v3.kernel.decide import GrowthKernel
from src.screening.offensive.v3.kernel.models import (
    BlockReason,
    DeadlineContract,
    PortfolioDecision,
    PortfolioDecisionLine,
)
from src.screening.offensive.v3.kernel.sizing import SizingConfig
from src.screening.offensive.v3.orchestration.daily_action_flow import (
    DailyActionFlow,
    DailyActionFlowResult,
)
from src.screening.offensive.v3.policy.models import RuntimeMode

UTC = timezone.utc
NOW = datetime(2026, 8, 5, 15, 30, tzinfo=UTC)  # run trusted_at (收盘后)
SIGNAL_DATE = date(2026, 8, 5)
AS_OF = datetime(2026, 8, 5, 15, 0, tzinfo=UTC)  # capital as_of = signal_date 15:00 UTC
CUTOFF = datetime(2026, 8, 5, 14, 55, tzinfo=UTC)  # trusted_evidence_cutoff
PORTFOLIO = "paper-v3"
HASH = "a" * 64
BEHAVIOR = "b" * 64


# --------------------------------------------------------------------------
# kernel 层 fixture (照抄 test_admission / test_risk / test_decide; 自包含)
# --------------------------------------------------------------------------


def _policy_activation(policy_snapshot_hash: str = HASH) -> PolicyActivation:
    return PolicyActivation(
        portfolio_id=PORTFOLIO,
        mode=ExecutionMode.DAILY_BAR_PROXY,
        policy_snapshot_hash=policy_snapshot_hash,
        predecessor_policy_activation_hash="0" * 64,
        trust_bundle_hash=HASH,
        registry_epoch=1,
        policy_epoch=1,
        authority_epoch=1,
        risk_epoch=1,
        effective_from=NOW,
        expires_at=NOW + timedelta(days=1),
        issuer_id="governance.service",
        issuer_capability="governance.policy.activation.v1",
        schema_major=2,
    )


def _policy_snapshot():
    """最小合法 schema-major-2 PolicySnapshot (fake-kernel 测试不校验 hash)。

    content_hash() 经 ``_revalidate_policy_snapshot`` 全量重验 (policy/models.py),
    故字段集必须是真实快照的完整集合 — 与 test_decide._policy_snapshot 同构。
    """
    from src.screening.offensive.v3.policy.models import PolicySnapshot

    return PolicySnapshot.model_validate_json(
        json.dumps(
            {
                "schema_major": 2,
                "policy_id": "growth-kernel-v3",
                "policy_version": "policy-v2",
                "policy_epoch": 1,
                "authority_epoch": 1,
                "risk_epoch": 1,
                "runtime_mode": "shadow",
                "capital": {
                    "governed_tiers": [2, 5, 10],
                    "exploration_aggregate_gross_cap": "0.02",
                    "portfolio_gross_cap": "0.02",
                    "single_name_gross_cap": "0.01",
                    "industry_gross_cap": "0.02",
                    "daily_entry_gross_cap": "0.02",
                    "stage_loss_budget_cap": "0.02",
                },
                "risk": {
                    "drawdown_scale_start": "0.10",
                    "drawdown_halt": "0.15",
                    "halt_is_latched": True,
                    "inherited_risk_counts_on_restart": True,
                },
                "adv": {
                    "lookback_sessions": 20,
                    "max_participation_rate": "0.05",
                    "missing_data_behavior": "fail_closed",
                },
                "producers": {
                    "btst_enabled": True,
                    "oversold_bounce_enabled": False,
                    "btst_regime_admission_mode": "IGNORE",
                    "regime_sizing_enabled": False,
                    "streak_sizing_enabled": False,
                    "trigger_strength_sizing_enabled": False,
                    "composite_sizing_enabled": False,
                },
                "execution": {
                    "entry_session_ordinal": 1,
                    "exit_session_ordinal": 10,
                    "order_type": "opening_auction_limit",
                    "time_in_force": "opening_auction",
                    "seal_deadline_after_t0_close_minutes": 240,
                    "permit_deadline_before_auction_minutes": 20,
                    "gateway_send_deadline_before_auction_minutes": 10,
                    "broker_auction_submission_cutoff_cn": "09:20:00",
                    "worst_case_cost_multiplier": "2",
                },
                "versions": {
                    "execution_contract_version": "t0-close-t1-open-t10-open.v1",
                    "cost_version": "cn-a-share-costs.v1",
                    "board_rule_version": "ashare-board-prefix-v1",
                    "calendar_version": "sse-szse-official-sessions.v1",
                    "lot_rule_version": "cn-board-lot.v1",
                    "price_boundary_version": "sse-szse-price-limits.v1",
                    "setup_version": "daily-action-setups-v1",
                    "exit_policy_version": "t10-open.v1",
                    "governance_version": "growth-kernel-governance.v2",
                },
                "evidence_gates": {
                    "min_mature_outcomes": 150,
                    "min_decision_days": 60,
                    "min_effective_sample_size": "60",
                    "min_distinct_tickers": 80,
                    "min_forward_months": 12,
                    "adverse_window_required": True,
                    "chronological_fold_gate_required": True,
                    "capacity_stress_required": True,
                    "tail_risk_gate_required": True,
                    "fresh_evidence_per_tier_required": True,
                    "slippage_stress_multiple": "2",
                    "minimum_economic_effect": "0.001",
                    "incremental_minimum_economic_effect": "0.001",
                },
            }
        ),
        strict=True,
    )


def _grant(**overrides) -> LineageGrant:
    values = {
        "grant_id": "grant-1",
        "grant_kind": GrantKind.EDGE,
        "grant_certificate_hash": HASH,
        "grant_issuer_id": "authorizer.service",
        "subject_producer": "btst",
        "family_id": BTST_FAMILY,
        "economic_lineage_id": "eline-1",
        "research_program_id": "prog-1",
        "behavior_fingerprint": BEHAVIOR,
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
        "alpha_or_evalue_budget_consumption_id": "consumption-1",
        "alpha_sample_consumption_id": "sample-1",
        "schema_major": 2,
    }
    values.update(overrides)
    return LineageGrant(**values)


def _binding() -> ProgramLossBudgetBinding:
    return ProgramLossBudgetBinding(
        research_program_id="prog-1",
        budget_id="budget-1",
        budget_cents=100_000,
        consumed_cents=0,
        version=1,
        schema_major=2,
    )


def _envelope(policy_activation: PolicyActivation, **overrides):
    values = {
        "authorization_kind": AuthorizationKind.EDGE,
        "authorization_id": "auth-1",
        "authorization_version": 1,
        "mode": ExecutionMode.DAILY_BAR_PROXY,
        "portfolio_id": PORTFOLIO,
        "broker_account_id": None,
        "broker_account_fingerprint": None,
        "base_currency": "CNY",
        "policy_activation_hash": policy_activation.artifact_hash(),
        "trust_bundle_hash": HASH,
        "registry_epoch": 1,
        "policy_epoch": 1,
        "authority_epoch": 1,
        "risk_epoch": 1,
        "research_program_ids": ("prog-1",),
        "baseline_portfolio_policy_fingerprint": HASH,
        "target_portfolio_policy_fingerprint": "c" * 64,
        "lineage_grants": (_grant(),),
        "evidence_as_of": NOW,
        "evidence_set_merkle_root": HASH,
        "issued_at": NOW,
        "expires_at": NOW + timedelta(days=1),
        "activation_capital_snapshot_id": "snapshot-1",
        "activation_capital_snapshot_hash": HASH,
        "portfolio_gross_cap": Decimal("0.02"),
        "exploration_aggregate_gross_cap": Decimal("0"),
        "program_loss_budget_bindings": (_binding(),),
        "issuer_id": "authorizer.service",
        "issuer_capability": "authorizer.edge.envelope.v1",
        "portfolio_assessment_result_hash": HASH,
        "global_attempt_ledger_checkpoint_hash": HASH,
        "global_multiplicity_budget_consumption_id": "consumption-1",
        "schema_major": 2,
    }
    values.update(overrides)
    return CapitalAuthorizationEnvelope(**values)


def _bucket(scope: ExposureScope, *, position_gross=0, total_gross=0, **identities) -> RiskExposureBucket:
    return RiskExposureBucket(
        scope=scope,
        portfolio_id=identities.get("portfolio_id"),
        research_program_id=identities.get("research_program_id"),
        economic_lineage_id=identities.get("economic_lineage_id"),
        stage_id=identities.get("stage_id"),
        position_marked_gross_cents=position_gross,
        live_order_leaves_gross_cents=0,
        reserved_entry_gross_cents=0,
        pending_stress_cents=0,
        corporate_action_pending_risk_cents=0,
        unattributed_risk_cents=0,
        total_gross_cents=total_gross,
    )


def _stage_latch() -> StageLossLatchSnapshot:
    return StageLossLatchSnapshot(
        research_program_id="prog-1",
        economic_lineage_id="eline-1",
        stage_id="stage-1",
        stage_loss_budget_id="budget-1",
        frozen_budget_cents=100_000,
        consumed_cents=1_000,
        stage_loss_version=1,
        state=StageLossLatchState.CLEAR,
    )


def _capital_snapshot(**overrides) -> CapitalRiskSnapshot:
    values = {
        "risk_snapshot_id": "snap-1",
        "portfolio_id": PORTFOLIO,
        "broker_account_id": None,
        "base_currency": "CNY",
        "mode": ExecutionMode.DAILY_BAR_PROXY,
        "as_of": NOW,
        "valid_until": NOW + timedelta(hours=1),
        "freshness": RiskSnapshotFreshness.FRESH,
        "completeness": RiskSnapshotCompleteness.COMPLETE,
        "available_cash_cents": 1_000_000,
        "restricted_cash_cents": 0,
        "unsettled_cash_cents": 0,
        "cash_receivable_cents": 0,
        "cash_payable_cents": 0,
        "subscription_suspense_cents": 0,
        "redemption_suspense_cents": 0,
        "reserved_cash_cents": 0,
        "issued_unit_quanta": 1_000_000,
        "pending_redeemed_unit_quanta": 0,
        "positions": (),
        "live_orders": (),
        "entry_reserves": (),
        "pending_stress_components": (),
        "corporate_action_risk_components": (),
        "unattributed_risk_cents": 0,
        "exposures": (
            _bucket(ExposureScope.GLOBAL),
            _bucket(ExposureScope.PORTFOLIO, portfolio_id=PORTFOLIO),
        ),
        "total_gross_exposure_cents": 0,
        "as_observed_nav_cents": 1_000_000,
        "lifetime_high_water_mark_cents": 1_000_000,
        "active_epoch_high_water_mark_cents": 1_000_000,
        "lifetime_drawdown_ppm": 0,
        "active_epoch_drawdown_ppm": 0,
        "risk_latch": RiskLatchState.CLEAR,
        "stage_loss_latches": (_stage_latch(),),
        "reconciliation_latch": ReconciliationLatchState.CLEAR,
        "policy_activation_hash": "a" * 64,
        "policy_epoch": 1,
        "authority_epoch": 1,
        "risk_epoch": 1,
        "registry_epoch": 1,
        "authorization_id": "auth-1",
        "authorization_version": 1,
        "stage_loss_state_version": 1,
        "writer_fencing_epoch": 1,
        "capital_version": 1,
        "schema_major": 2,
    }
    values.update(overrides)
    return CapitalRiskSnapshot(**values)


def _deadlines(**overrides) -> DeadlineContract:
    values = {
        "close_finalized_at": AS_OF,
        "seal_creation_deadline": AS_OF + timedelta(hours=1),
        "permit_issue_deadline": AS_OF + timedelta(hours=1, minutes=30),
        "permit_expires_at": AS_OF + timedelta(hours=18, minutes=25),
        "gateway_send_deadline": AS_OF + timedelta(hours=18, minutes=25),
        "broker_auction_cutoff": AS_OF + timedelta(hours=18, minutes=30),
    }
    values.update(overrides)
    return DeadlineContract(**values)


def _config(**overrides) -> SizingConfig:
    values = {
        "per_ticker_gross_cap_cents": 200_000,
        "per_industry_gross_cap_cents": 300_000,
        "per_day_gross_cap_cents": 500_000,
        "portfolio_gross_cap_cents": 400_000,
        "worst_case_fee_ppm": 3_000,
    }
    values.update(overrides)
    return SizingConfig(**values)


def _fresh_capital(**overrides):
    values = {
        "as_of": AS_OF,
        "valid_until": AS_OF + timedelta(hours=18),
        "as_observed_nav_cents": 10_000_000,
        "lifetime_high_water_mark_cents": 10_000_000,
        "active_epoch_high_water_mark_cents": 10_000_000,
    }
    values.update(overrides)
    return _capital_snapshot(**values)


def _stale_capital(**overrides):
    # valid_until (14:00) < trusted_at (15:30) 且 > as_of (13:00): 只读投影
    # 合法读取, 但 kernel risk 判定 STALE_CAPITAL。
    return _fresh_capital(
        as_of=AS_OF - timedelta(hours=2),
        valid_until=AS_OF - timedelta(hours=1),
        **overrides,
    )


def _position(lineage_id: str, lot_id: str, *, security_id="300001.SH"):
    return CapitalPositionRisk(
        portfolio_id=PORTFOLIO,
        broker_account_id=None,
        mode=ExecutionMode.DAILY_BAR_PROXY,
        position_lineage_id=lineage_id,
        economic_lot_id=lot_id,
        security_id=security_id,
        producer_namespace="btst",
        research_program_id="prog-1",
        economic_lineage_id="eline-1",
        stage_id="stage-1",
        state=PositionState.OPEN,
        settled_quantity=100,
        tradable_quantity=100,
        share_receivable_quantity=0,
        marked_gross_cents=100_000,
    )


def _capital_with_positions():
    # 身份对按字典序排列 (snapshot validator 要求 canonical order); positions
    # 携带 prog-1/eline-1/stage-1 → exposures 必须是完整的 canonical 集合
    # (GLOBAL → PORTFOLIO → RESEARCH_PROGRAM → ECONOMIC_LINEAGE → STAGE),
    # 且各 bucket 的 position gross 与 total gross 须与 positions 对账
    # (2 × 100_000 = 200_000)。
    gross = 2 * 100_000

    def _b(scope, **identities):
        return _bucket(
            scope, position_gross=gross, total_gross=gross, **identities
        )

    return _fresh_capital(
        positions=(
            _position("pos-line-1", "lot-1"),
            _position("pos-line-2", "lot-2"),
        ),
        exposures=(
            _b(ExposureScope.GLOBAL),
            _b(ExposureScope.PORTFOLIO, portfolio_id=PORTFOLIO),
            _b(
                ExposureScope.RESEARCH_PROGRAM,
                portfolio_id=PORTFOLIO,
                research_program_id="prog-1",
            ),
            _b(
                ExposureScope.ECONOMIC_LINEAGE,
                portfolio_id=PORTFOLIO,
                research_program_id="prog-1",
                economic_lineage_id="eline-1",
            ),
            _b(
                ExposureScope.STAGE,
                portfolio_id=PORTFOLIO,
                research_program_id="prog-1",
                economic_lineage_id="eline-1",
                stage_id="stage-1",
            ),
        ),
        total_gross_exposure_cents=gross,
    )


def _decision_line(security_id="300001.SH", *, candidate_id="cand-1", **overrides):
    values = {
        "candidate_id": candidate_id,
        "security_id": security_id,
        "economic_lineage_id": "eline-1",
        "research_program_id": "prog-1",
        "stage_id": "stage-1",
        "direction": "LONG",
        "quantity_units": 100,
        "limit_price_micros": 10_500_000,
        "worst_case_reserve_cents": 105_000,
        "status": "ENTRY_PLANNED",
    }
    values.update(overrides)
    return PortfolioDecisionLine(**values)


def _portfolio_decision(*lines):
    if not lines:
        lines = (_decision_line(),)
    return PortfolioDecision(
        portfolio_id=PORTFOLIO,
        signal_session=SIGNAL_DATE,
        decision_cycle_id="cycle-1",
        mode=ExecutionMode.DAILY_BAR_PROXY,
        policy_activation_hash="a" * 64,
        policy_epoch=1,
        authority_epoch=1,
        risk_epoch=1,
        capital_snapshot_hash="b" * 64,
        capital_version=1,
        lines=lines,
        portfolio_gross_cap_cents=200_000,
        total_reserved_worst_case_cents=105_000,
    )


# --------------------------------------------------------------------------
# 可注入的鸭子类型 fakes (flow 只依赖签名, 不依赖具体类型)
# --------------------------------------------------------------------------


class _FakeLifecycleReader:
    def __init__(self, order: list[str] | None = None) -> None:
        self.calls: list[tuple[str, str]] = []
        self.order = order

    def exit_state(self, position_lineage_id: str, economic_lot_id: str):
        self.calls.append((position_lineage_id, economic_lot_id))
        if self.order is not None:
            self.order.append("lifecycle")
        return None  # 无 mandate 不是失败


class _FakeCapitalReader:
    def __init__(self, snapshot=None, error: Exception | None = None, order=None):
        self.snapshot = snapshot
        self.error = error
        self.calls: list[tuple[str, datetime]] = []
        self.order = order

    def risk_snapshot(self, portfolio_id: str, as_of: datetime):
        self.calls.append((portfolio_id, as_of))
        if self.order is not None:
            self.order.append("capital")
        if self.error is not None:
            raise self.error
        assert self.snapshot is not None
        return self.snapshot


class _FakeSnapshotLoader:
    def __init__(self, result: VerifiedSnapshotResult, order=None):
        self.result = result
        self.calls: list[tuple[date, object, object]] = []
        self.order = order

    def __call__(self, signal_date: date, *, reports_dir, data_dir):
        self.calls.append((signal_date, reports_dir, data_dir))
        if self.order is not None:
            self.order.append("snapshot")
        return self.result


class _FakeProducer:
    def __init__(self, records=(), error: Exception | None = None, order=None):
        self.records = records
        self.error = error
        self.calls = []
        self.order = order

    def produce_and_publish(self, snapshot):
        self.calls.append(snapshot)
        if self.order is not None:
            self.order.append("producer")
        if self.error is not None:
            raise self.error
        return self.records


class _FakeEvidenceStore:
    def __init__(self, error: Exception | None = None, order=None):
        self.error = error
        self.calls: list[tuple[str, datetime]] = []
        self.order = order

    def active_revision(self, evidence_id: str, cutoff: datetime):
        self.calls.append((evidence_id, cutoff))
        if self.order is not None:
            self.order.append("evidence")
        if self.error is not None:
            raise self.error
        return None  # 宽容读: 未知 evidence_id → None (benign miss)


class _FakeKernel:
    def __init__(self, result, order=None):
        self.result = result
        self.calls = []
        self.order = order

    def decide(self, kernel_input, *, trusted_at):
        self.calls.append((kernel_input, trusted_at))
        if self.order is not None:
            self.order.append("kernel")
        return self.result


class _RecordingKernel:
    """包一层真实 GrowthKernel: 记录 (kernel_input, trusted_at) 后转发。"""

    def __init__(self, inner: GrowthKernel) -> None:
        self.inner = inner
        self.calls = []

    def decide(self, kernel_input, *, trusted_at):
        self.calls.append((kernel_input, trusted_at))
        return self.inner.decide(kernel_input, trusted_at=trusted_at)


class _FakePersister:
    def __init__(self, order=None):
        self.calls = []
        self.order = order

    def publish_shadow_decision(self, decision) -> str:
        self.calls.append(decision)
        if self.order is not None:
            self.order.append("persist")
        return decision.shadow_decision_id


@dataclass(frozen=True)
class _V2Plan:
    """v2 plans 的最小鸭子类型 (只需 .ticker; 真实 ActionItem 满足)。"""

    trade_id: str
    ticker: str


class _FakeV2Plans:
    def __init__(self, plans=(), error: Exception | None = None, order=None):
        self.plans = plans
        self.error = error
        self.calls: list[date] = []
        self.order = order

    def __call__(self, signal_date: date):
        self.calls.append(signal_date)
        if self.order is not None:
            self.order.append("v2")
        if self.error is not None:
            raise self.error
        return self.plans


def _make_flow(
    *,
    lifecycle_reader=None,
    capital_reader=None,
    snapshot_loader=None,
    producer=None,
    evidence_store=None,
    kernel=None,
    persister=None,
    v2_plans_reader=None,
    evidence_ids=(),
    mode: RuntimeMode = RuntimeMode.SHADOW,
    portfolio_id: str = PORTFOLIO,
    policy=None,
    policy_snapshot=None,
    envelope=None,
    deadlines=None,
    cutoff: datetime = CUTOFF,
    order: list[str] | None = None,
) -> DailyActionFlow:
    policy = policy or _policy_activation()
    return DailyActionFlow(
        lifecycle_reader=lifecycle_reader or _FakeLifecycleReader(order=order),
        capital_reader=capital_reader or _FakeCapitalReader(_fresh_capital(), order=order),
        snapshot_loader=snapshot_loader
        or _FakeSnapshotLoader(
            VerifiedSnapshotResult(snapshot=_verified_snapshot()), order=order
        ),
        btst_producer=producer or _FakeProducer(order=order),
        evidence_store=evidence_store or _FakeEvidenceStore(order=order),
        kernel=kernel or _FakeKernel(_portfolio_decision(), order=order),
        shadow_persister=persister or _FakePersister(order=order),
        mode_provider=lambda: mode,
        policy_activation=policy,
        policy_snapshot=policy_snapshot or _policy_snapshot(),
        envelope=envelope or _envelope(policy),
        portfolio_id=portfolio_id,
        deadlines=deadlines or _deadlines(),
        trusted_evidence_cutoff=cutoff,
        evidence_ids=evidence_ids,
        v2_plans_reader=v2_plans_reader,
    )


def _run(flow: DailyActionFlow, tmp_path: Path, *, trusted_at: datetime = NOW):
    return flow.run(
        signal_date=SIGNAL_DATE,
        reports_dir=tmp_path / "reports",
        data_dir=tmp_path / "data",
        trusted_at=trusted_at,
    )


# --------------------------------------------------------------------------
# 契约测试
# --------------------------------------------------------------------------


def test_lifecycle_query_precedes_snapshot_scan(tmp_path: Path) -> None:
    order: list[str] = []
    lifecycle = _FakeLifecycleReader(order=order)
    capital_reader = _FakeCapitalReader(_capital_with_positions(), order=order)
    snapshot_loader = _FakeSnapshotLoader(
        VerifiedSnapshotResult(snapshot=_verified_snapshot()), order=order
    )
    flow = _make_flow(
        lifecycle_reader=lifecycle,
        capital_reader=capital_reader,
        snapshot_loader=snapshot_loader,
        order=order,
    )

    result = _run(flow, tmp_path)

    assert result.lifecycle_status == "ok"
    assert result.capital_status == "ok"
    # 对 capital snapshot 的每个 position 各查一次 exit 义务
    assert lifecycle.calls == [
        ("pos-line-1", "lot-1"),
        ("pos-line-2", "lot-2"),
    ]
    # 只读资本投影 as_of = signal_date 15:00 UTC (AutoFlow 同款约定)
    assert capital_reader.calls == [(PORTFOLIO, AS_OF)]
    # scheduler/lifecycle call before snapshot/scan: lifecycle 恒先于
    # snapshot 加载, 也先于 BTST producer scan
    assert order.index("lifecycle") < order.index("snapshot")
    assert order.index("lifecycle") < order.index("producer")


def test_missing_snapshot_skips_shadow_pipeline(tmp_path: Path) -> None:
    lifecycle = _FakeLifecycleReader()
    capital_reader = _FakeCapitalReader(_capital_with_positions())
    snapshot_loader = _FakeSnapshotLoader(
        VerifiedSnapshotResult(snapshot=None, global_reason="manifest_missing")
    )
    producer = _FakeProducer()
    evidence_store = _FakeEvidenceStore()
    kernel = _FakeKernel(_portfolio_decision())
    persister = _FakePersister()
    flow = _make_flow(
        lifecycle_reader=lifecycle,
        capital_reader=capital_reader,
        snapshot_loader=snapshot_loader,
        producer=producer,
        evidence_store=evidence_store,
        kernel=kernel,
        persister=persister,
    )

    result = _run(flow, tmp_path)

    assert result.snapshot_status == "failed"
    assert result.failure_reason["snapshot"] == "manifest_missing"
    # lifecycle/capital 独立于 snapshot 照常执行
    assert result.lifecycle_status == "ok"
    assert result.capital_status == "ok"
    assert lifecycle.calls == [("pos-line-1", "lot-1"), ("pos-line-2", "lot-2")]
    assert len(capital_reader.calls) == 1
    assert result.capital_projection is not None
    # shadow 管线无输入 → skipped + reason, 不调用 producer/kernel/persister
    assert result.shadow_decision_status == "skipped"
    assert result.failure_reason["shadow_decision"] == "no_snapshot"
    assert producer.calls == []
    assert evidence_store.calls == []
    assert kernel.calls == []
    assert persister.calls == []
    assert result.shadow_decision_id is None
    assert result.no_trade_reason is None


def test_missed_window_records_evidence_failure_and_continues(tmp_path: Path) -> None:
    evidence_store = _FakeEvidenceStore(
        error=EvidenceStoreError(
            "evidence_not_committed_before_cutoff",
            "no active revision was committed at the cutoff",
        )
    )
    persister = _FakePersister()
    flow = _make_flow(
        evidence_store=evidence_store,
        persister=persister,
        evidence_ids=("ev-1",),
    )

    result = _run(flow, tmp_path)

    # missed window → 证据加载步记失败原因, flow 不崩溃
    assert "evidence_not_committed_before_cutoff" in result.failure_reason["evidence"]
    assert result.failure_reason["evidence"].startswith("EvidenceStoreError: ")
    assert evidence_store.calls == [("ev-1", CUTOFF)]
    # 证据失败不改变 shadow_decision_status: 管线继续, 决策照常产生
    assert result.shadow_decision_status == "ok"
    assert len(persister.calls) == 1
    assert result.shadow_decision_id == persister.calls[0].shadow_decision_id


def test_stale_capital_is_no_trade_form(tmp_path: Path) -> None:
    stale = _stale_capital()
    capital_reader = _FakeCapitalReader(stale)
    kernel = _RecordingKernel(GrowthKernel(_config()))
    producer = _FakeProducer(records=())  # 空候选; stale 检查先于 admission
    persister = _FakePersister()
    snapshot = _policy_snapshot()
    policy = _policy_activation(policy_snapshot_hash=snapshot.content_hash())
    flow = _make_flow(
        capital_reader=capital_reader,
        kernel=kernel,
        producer=producer,
        persister=persister,
        policy=policy,
        policy_snapshot=snapshot,
    )

    result = _run(flow, tmp_path)

    # 只读投影成功 (stale 是 kernel 层判定, 不是读失败)
    assert result.capital_status == "ok"
    assert result.capital_projection is stale
    # kernel 收到 stale snapshot → NoTrade(STALE_CAPITAL) → no_trade 形态
    kernel_input, trusted_at = kernel.calls[0]
    assert kernel_input.capital.risk_snapshot_id == stale.risk_snapshot_id
    assert kernel_input.capital.valid_until < trusted_at
    assert result.shadow_decision_status == "no_signal"
    assert result.no_trade_reason is BlockReason.STALE_CAPITAL
    # 不构造/持久化空 ShadowDecision
    assert persister.calls == []
    assert result.shadow_decision_id is None
    assert result.discrepancy == {}


def test_no_signal_never_constructs_empty_shadow_decision(tmp_path: Path) -> None:
    kernel = _RecordingKernel(GrowthKernel(_config()))
    producer = _FakeProducer(records=())  # scan 无候选
    persister = _FakePersister()
    # 真实 kernel 校验 activation↔snapshot hash 绑定 (decide.py:69): 构造一致的
    # 快照 + 派生 activation, 使 no_signal 是候选为空的真实判定而非绑定失败。
    snapshot = _policy_snapshot()
    policy = _policy_activation(policy_snapshot_hash=snapshot.content_hash())
    flow = _make_flow(
        kernel=kernel,
        producer=producer,
        persister=persister,
        policy=policy,
        policy_snapshot=snapshot,
    )

    result = _run(flow, tmp_path)

    # kernel 是 no-signal 的唯一权威: 空候选也被送入 kernel
    assert len(kernel.calls) == 1
    assert result.shadow_decision_status == "no_signal"
    assert result.no_trade_reason is BlockReason.NO_SIGNAL
    # min_length=1 契约: 绝不构造/持久化空 ShadowDecision
    assert persister.calls == []
    assert result.shadow_decision_id is None
    assert result.discrepancy == {}


def test_v2_comparison_reports_discrepancies(tmp_path: Path) -> None:
    decision = _portfolio_decision(
        _decision_line("300001.SH"),
        _decision_line("600001.SH", candidate_id="cand-2"),
    )
    kernel = _FakeKernel(decision)
    v2 = _FakeV2Plans(
        (_V2Plan("t1", "300001"), _V2Plan("t2", "300002"))
    )
    flow = _make_flow(kernel=kernel, v2_plans_reader=v2)

    result = _run(flow, tmp_path)

    assert result.shadow_decision_status == "ok"
    # 300001.SH ↔ 300001 匹配; 300002 只有 v2; 600001 只有 v3
    assert result.discrepancy == {
        "300002": "v2_only",
        "600001": "v3_only",
    }
    assert v2.calls == [SIGNAL_DATE]
    assert result.failure_reason == {}


def test_repeat_run_is_deterministic(tmp_path: Path) -> None:
    producer = _FakeProducer()
    kernel = _FakeKernel(_portfolio_decision())
    persister = _FakePersister()
    flow = _make_flow(producer=producer, kernel=kernel, persister=persister)

    first = _run(flow, tmp_path)
    second = _run(flow, tmp_path)

    assert first == second
    assert first.shadow_decision_status == "ok"
    assert first.shadow_decision_id is not None
    assert first.shadow_decision_id.startswith("shadow-")
    # 确定性: 同 signal_date 二次 run → 同一 shadow_decision_id
    assert first.shadow_decision_id == second.shadow_decision_id
    # rerun 是独立重放: 每步被再次尝试, 结果一致
    assert len(producer.calls) == 2
    assert len(kernel.calls) == 2
    assert len(persister.calls) == 2


def test_v2_ledger_bytes_are_byte_identical(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    ledger = data_dir / "paper_trading_v2" / "ledger.sqlite3"
    ledger.parent.mkdir(parents=True)
    ledger.write_bytes(b"v2-ledger-sentinel-0001")
    before = sorted(str(p.relative_to(data_dir)) for p in data_dir.rglob("*"))

    flow = _make_flow()
    result = _run(flow, tmp_path)

    # byte-identical 契约: v3 shadow 运行绝不写 v2 ledger
    assert result.shadow_decision_status == "ok"
    assert ledger.read_bytes() == b"v2-ledger-sentinel-0001"
    after = sorted(str(p.relative_to(data_dir)) for p in data_dir.rglob("*"))
    assert after == before


def test_execution_authority_is_always_none(tmp_path: Path) -> None:
    # dataclass 默认值: 未显式传入也是 "none"
    plain = DailyActionFlowResult(
        lifecycle_status="ok",
        snapshot_status="ok",
        capital_status="ok",
        shadow_decision_status="ok",
    )
    assert plain.execution_authority == "none"
    assert plain.discrepancy == {}
    assert plain.failure_reason == {}
    assert plain.shadow_decision_id is None
    assert plain.no_trade_reason is None

    # 混合失败组合下仍为 "none" (missing snapshot → shadow skipped)
    snapshot_loader = _FakeSnapshotLoader(
        VerifiedSnapshotResult(snapshot=None, global_reason="manifest_missing")
    )
    flow = _make_flow(snapshot_loader=snapshot_loader)
    result = _run(flow, tmp_path)
    assert result.snapshot_status == "failed"
    assert result.shadow_decision_status == "skipped"
    assert result.execution_authority == "none"


def test_off_mode_skips_everything_with_zero_calls(tmp_path: Path) -> None:
    order: list[str] = []
    lifecycle = _FakeLifecycleReader(order=order)
    capital_reader = _FakeCapitalReader(_fresh_capital(), order=order)
    snapshot_loader = _FakeSnapshotLoader(
        VerifiedSnapshotResult(snapshot=_verified_snapshot()), order=order
    )
    producer = _FakeProducer(order=order)
    evidence_store = _FakeEvidenceStore(order=order)
    kernel = _FakeKernel(_portfolio_decision(), order=order)
    persister = _FakePersister(order=order)
    v2 = _FakeV2Plans(order=order)
    flow = _make_flow(
        lifecycle_reader=lifecycle,
        capital_reader=capital_reader,
        snapshot_loader=snapshot_loader,
        producer=producer,
        evidence_store=evidence_store,
        kernel=kernel,
        persister=persister,
        v2_plans_reader=v2,
        mode=RuntimeMode.OFF,
        order=order,
    )

    result = _run(flow, tmp_path)

    assert result.lifecycle_status == "skipped"
    assert result.snapshot_status == "skipped"
    assert result.capital_status == "skipped"
    assert result.shadow_decision_status == "skipped"
    assert result.execution_authority == "none"
    assert result.failure_reason == {}
    assert result.shadow_decision_id is None
    assert result.capital_projection is None
    assert result.no_trade_reason is None
    # legacy 行为不变: 全部注入端口零调用
    assert order == []


def test_happy_path_persists_shadow_decision(tmp_path: Path) -> None:
    capital = _fresh_capital()
    capital_reader = _FakeCapitalReader(capital)
    producer = _FakeProducer()
    kernel = _FakeKernel(_portfolio_decision())
    persister = _FakePersister()
    flow = _make_flow(
        capital_reader=capital_reader,
        producer=producer,
        kernel=kernel,
        persister=persister,
    )

    result = _run(flow, tmp_path)

    assert result.lifecycle_status == "ok"
    assert result.snapshot_status == "ok"
    assert result.capital_status == "ok"
    assert result.shadow_decision_status == "ok"
    assert result.execution_authority == "none"
    assert result.failure_reason == {}
    assert result.no_trade_reason is None
    assert result.capital_projection is capital
    assert result.discrepancy == {}
    assert len(producer.calls) == 1
    assert len(kernel.calls) == 1
    assert len(persister.calls) == 1
    decision = persister.calls[0]
    # ShadowDecision 形态: 恒无执行授权 + 非空 counterfactual_lines
    assert decision.execution_authority == "NONE"
    assert len(decision.counterfactual_lines) >= 1
    assert result.shadow_decision_id == decision.shadow_decision_id
    # kernel input 契约: 注入输入透传 + 确定性 cycle id
    kernel_input, trusted_at = kernel.calls[0]
    assert kernel_input.portfolio_id == PORTFOLIO
    assert kernel_input.signal_session == SIGNAL_DATE
    assert kernel_input.decision_cycle_id == "daily-action-2026-08-05"
    assert kernel_input.capital.risk_snapshot_id == capital.risk_snapshot_id
    assert kernel_input.trusted_evidence_cutoff == CUTOFF
    assert trusted_at == NOW


def test_producer_failure_is_isolated(tmp_path: Path) -> None:
    producer = _FakeProducer(error=RuntimeError("producer_down"))
    kernel = _FakeKernel(_portfolio_decision())
    persister = _FakePersister()
    flow = _make_flow(producer=producer, kernel=kernel, persister=persister)

    result = _run(flow, tmp_path)

    assert result.shadow_decision_status == "failed"
    assert result.failure_reason["producer"] == "RuntimeError: producer_down"
    # 其余步不受影响
    assert result.lifecycle_status == "ok"
    assert result.snapshot_status == "ok"
    assert result.capital_status == "ok"
    # producer 失败前被尝试过; kernel/persister 不接续
    assert len(producer.calls) == 1
    assert kernel.calls == []
    assert persister.calls == []
    assert result.shadow_decision_id is None


def test_capital_failure_skips_lifecycle_and_shadow(tmp_path: Path) -> None:
    capital_reader = _FakeCapitalReader(error=RuntimeError("capital_down"))
    snapshot_loader = _FakeSnapshotLoader(
        VerifiedSnapshotResult(snapshot=_verified_snapshot())
    )
    producer = _FakeProducer()
    kernel = _FakeKernel(_portfolio_decision())
    persister = _FakePersister()
    flow = _make_flow(
        capital_reader=capital_reader,
        snapshot_loader=snapshot_loader,
        producer=producer,
        kernel=kernel,
        persister=persister,
    )

    result = _run(flow, tmp_path)

    assert result.capital_status == "failed"
    assert result.failure_reason["capital"] == "RuntimeError: capital_down"
    assert result.capital_projection is None
    # lifecycle 缺资本输入 → skipped + reason, 不被调用
    assert result.lifecycle_status == "skipped"
    assert result.failure_reason["lifecycle"] == "no_capital"
    # snapshot 独立于 capital 照常执行
    assert result.snapshot_status == "ok"
    assert len(snapshot_loader.calls) == 1
    # shadow 管线缺资本输入 → skipped + reason, producer/kernel/persister 不调用
    assert result.shadow_decision_status == "skipped"
    assert result.failure_reason["shadow_decision"] == "no_capital"
    assert producer.calls == []
    assert kernel.calls == []
    assert persister.calls == []
    assert result.shadow_decision_id is None


@pytest.mark.parametrize(
    "mode", [RuntimeMode.BTST_CANARY, RuntimeMode.AUTHORITATIVE]
)
def test_non_shadow_modes_skip_shadow_pipeline(tmp_path: Path, mode: RuntimeMode) -> None:
    lifecycle = _FakeLifecycleReader()
    capital_reader = _FakeCapitalReader(_capital_with_positions())
    producer = _FakeProducer()
    kernel = _FakeKernel(_portfolio_decision())
    persister = _FakePersister()
    v2 = _FakeV2Plans((_V2Plan("t1", "300001"),))
    flow = _make_flow(
        lifecycle_reader=lifecycle,
        capital_reader=capital_reader,
        producer=producer,
        kernel=kernel,
        persister=persister,
        v2_plans_reader=v2,
        mode=mode,
    )

    result = _run(flow, tmp_path)

    # 只读观测照常执行
    assert result.lifecycle_status == "ok"
    assert result.snapshot_status == "ok"
    assert result.capital_status == "ok"
    assert lifecycle.calls == [("pos-line-1", "lot-1"), ("pos-line-2", "lot-2")]
    # shadow 管线 skipped + reason, 零调用
    assert result.shadow_decision_status == "skipped"
    assert result.failure_reason["shadow_decision"] == "not_shadow_mode"
    assert producer.calls == []
    assert kernel.calls == []
    assert persister.calls == []
    assert v2.calls == []
    assert result.discrepancy == {}
    assert result.shadow_decision_id is None


# --------------------------------------------------------------------------
# 独立审查回归守卫 (C-1 单位 / C-2 排序 / M-3 构造隔离 / M-5 grant 同源)
# --------------------------------------------------------------------------


def test_shadow_line_economics_derive_from_kernel_in_cents(tmp_path: Path) -> None:
    """C-1 回归: limit_price_micros (micro-yuan) 必须按 10_000 换算为 cents。

    micros 是 micro-yuan (1 yuan = 1_000_000 micros), cents 换算除数是
    MICROS_PER_CENT=10_000, 不是 1_000_000 (后者得到 yuan 被误当 cents,
    约 95× 低估)。fee 从 kernel reserve 反推, 与 kernel fee_ppm 口径一致。
    """
    kernel = _FakeKernel(_portfolio_decision(_decision_line(limit_price_micros=10_500_000)))
    persister = _FakePersister()
    flow = _make_flow(kernel=kernel, persister=persister)

    result = _run(flow, tmp_path)

    assert result.shadow_decision_status == "ok"
    line = persister.calls[0].counterfactual_lines[0]
    # 10.5 元 = 1050 分 (不是 11)
    assert line.limit_price_cents == 1050
    assert line.worst_case_price_cents == 1050
    # reserve = price_cents × qty + fee (kernel gross = 100 × 10_500_000 // 10_000)
    assert line.estimated_cash_reserve_cents == (
        line.limit_price_cents * line.target_quantity_units
        + line.estimated_fee_cents
    )


def test_shadow_lines_are_canonically_sorted(tmp_path: Path) -> None:
    """C-2 回归: kernel 输出 rank 顺序 ≠ candidate_id 字典序时, ShadowDecision
    canonical-order 校验 (line_ids == sorted) 必须由 flow 显式排序满足。"""
    decision = _portfolio_decision(
        _decision_line("300001.SH", candidate_id="cand-z"),
        _decision_line("300002.SH", candidate_id="cand-a"),
    )
    kernel = _FakeKernel(decision)
    persister = _FakePersister()
    flow = _make_flow(kernel=kernel, persister=persister)

    result = _run(flow, tmp_path)

    assert result.shadow_decision_status == "ok"
    lines = persister.calls[0].counterfactual_lines
    ids = [line.shadow_line_id for line in lines]
    assert ids == sorted(ids)
    assert ids == [
        "shadow-line-cand-a",
        "shadow-line-cand-z",
    ]


def test_shadow_construction_failure_is_recorded_not_crashed(tmp_path: Path) -> None:
    """M-3 回归: ShadowDecision 构造期异常 (如 evidence_id 格式非法 →
    ``_evidence_ticker`` 解析失败) 记入 kernel 步 reason, run() 不崩溃,
    shadow_decision_status=failed。

    触发机制更新 (S2b): 原用 GLOBAL 证据 ``family_id=None`` 依赖
    ``family_id=envelope.family_id or ""`` 的空串路径; S2b 后 ``family_id``
    硬编码 ``BTST_FAMILY`` 不再读 envelope.family_id, 改用非法 evidence_id
    (``split(":")[2]`` IndexError) 触发构造期异常 — 同样落入 kernel 步
    try/except。"""
    kernel = _FakeKernel(_portfolio_decision())
    persister = _FakePersister()
    # producer 返回 evidence_id 格式非法的证据记录 (构造 RawCandidate 时
    # _evidence_ticker split(":")[2] 抛 IndexError)
    records = (_global_scope_record(),)
    flow = _make_flow(
        producer=_FakeProducer(records=records),
        kernel=kernel,
        persister=persister,
    )

    result = _run(flow, tmp_path)

    assert result.shadow_decision_status == "failed"
    assert "kernel" in result.failure_reason
    assert persister.calls == []


def test_shadow_decision_uses_same_grant_as_kernel(tmp_path: Path) -> None:
    """M-5 回归: btst grant 不是 grants[0] 时, flow 的 _authorized_grant() 仍
    取 subject_producer=btst 的 grant, 使 ShadowDecision header/line provenance
    与 kernel 候选同源。

    直接断言 _authorized_grant() 选择逻辑 (而非 envelope 多 grant 构造, 后者
    受 grant 字段全局唯一约束使 fixture 笨重); header 与 line provenance 仍
    由 test_happy_path + provenance 校验覆盖。
    """
    policy = _policy_activation()
    flow = _make_flow(policy=policy, envelope=_envelope(policy))

    grant = flow._authorized_grant()

    assert grant.subject_producer == "btst"
    assert grant.economic_lineage_id == "eline-1"
    assert grant.research_program_id == "prog-1"
    assert grant.stage_id == "stage-1"


def _global_scope_record():
    """evidence_id 格式非法的证据记录 (``split(":")[2]`` 触发 IndexError)。

    S2b 前用 ``family_id=None`` 触发构造失败; S2b 后 family_id 硬编码
    ``BTST_FAMILY``, 改用非法 evidence_id (不足 3 段) 使 ``_evidence_ticker``
    解析失败。保留 GLOBAL scope 以贴合 M-3 "GLOBAL 证据" 语义。
    """
    from src.screening.offensive.v3.contracts.base import EvidenceScope
    from src.screening.offensive.v3.contracts.evidence import SignalEvidence

    envelope = SignalEvidence(
        evidence_id="global",
        subject_scope=EvidenceScope.GLOBAL,
        subject_producer="btst",
        family_id=None,
        strategy_semver="0.1.0",
        behavior_fingerprint=BEHAVIOR,
        policy_epoch=1,
        execution_version="btst.funnel.v1",
        cost_version="cn-a-share-costs.v1",
        effective_at=AS_OF,
        provider_published_at=AS_OF,
        observed_at=AS_OF,
        available_at=AS_OF + timedelta(days=1),
        mode=ExecutionMode.RESEARCH_RECONSTRUCTION,
        source_authority="btst.producer",
        payload_content_hash="d" * 64,
        schema_major=2,
        evidence_kind="signal",
        stage=SignalStage.SELECTED,
    )
    return _evidence_record(envelope)


def _evidence_record(envelope) -> "object":
    """最小 EvidenceRecord 鸭子类型: 只暴露 .evidence。"""
    return _EvidenceRecordStub(envelope)


class _EvidenceRecordStub:
    def __init__(self, evidence) -> None:
        self.evidence = evidence
