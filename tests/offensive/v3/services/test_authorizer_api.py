"""Plan 05 Task 2 (RED): AuthorizerApi 能力矩阵 + EDGE 授权行为。

覆盖 Step 1 能力矩阵(import 边界、无 gateway/capital 方法、kind 隔离、
signer 私有)与 Step 3 行为(INACTIVE candidate、精确 issuer capability、
幂等、signer 失败无残留 + 恢复后确定性重试)。

本文件引用尚未实现的服务骨架(方法体一律 raise NotImplementedError);
当前应整体 RED, 由主代理随后实现 GREEN。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from src.screening.offensive.v3 import trust
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
from src.screening.offensive.v3.services import authorizer_api as az_module
from src.screening.offensive.v3.services.authorizer_api import AuthorizerApi

UTC = timezone.utc
NOW = datetime(2026, 8, 5, 9, 0, tzinfo=UTC)
CUTOFF = NOW - timedelta(days=1)
HASH = "a" * 64
HASH2 = "b" * 64
PORTFOLIO = "paper-v3"
MODE = ExecutionMode.DAILY_BAR_PROXY
SIGNER_NAMESPACE = "capital.edge.btst"

GATEWAY_METHODS = (
    "activate_trust_bundle",
    "activate_policy_and_envelope",
    "replace_envelope",
    "raise_entry_fence",
    "acknowledge_fence",
    "active_state",
    "publish_entry",
    "issue_permit",
    "make_outbox_durable",
)
CAPITAL_METHODS = (
    "run_append",
    "append_atomic",
    "record_fill_revision",
    "record_fee_revision",
    "confirm_observed_nav",
)


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
    import hashlib as _hashlib
    from base64 import b64encode

    def sign(payload: bytes):
        digest = _hashlib.sha256(payload).hexdigest()
        return trust.SignedEnvelope(
            issuer_id="authorizer.service",
            key_id="key-1",
            schema_major=2,
            artifact=trust.ArtifactKind.EDGE_AUTHORIZATION,
            namespace=SIGNER_NAMESPACE,
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


def _make_api(tmp_path: Path, ledgers, *, signer=None) -> AuthorizerApi:
    _, attempts, consumption = ledgers
    return AuthorizerApi(
        database_path=str(tmp_path / "authorizer.sqlite3"),
        signer=signer or _dummy_signer(),
        clock=_Clock(NOW),
        attempts=attempts,
        consumption=consumption,
        expected_mode=MODE,
        expected_behavior_fingerprint=HASH,
        expected_cost_version="cn-a-share-costs.v1",
        expected_execution_version="t1-open-t10-open.v1",
        expected_broker_account_id=None,
    )


@pytest.fixture()
def api(tmp_path: Path, ledgers) -> AuthorizerApi:
    return _make_api(tmp_path, ledgers)


def _request(**overrides) -> EdgeAssessmentRequest:
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


def _forbidden_import_segments(source: str) -> list[str]:
    violations: list[str] = []
    for line in source.splitlines():
        if not line or line[0].isspace():
            continue
        if line.startswith("import "):
            module = (
                line[len("import "):].split(" as ")[0].split(",")[0].strip()
            )
        elif line.startswith("from "):
            module = line[len("from "):].split(" import ")[0].strip()
        else:
            continue
        for segment in module.split("."):
            if segment in {"capital", "gateway", "execution"}:
                violations.append(line)
                break
    return violations


# --------------------------------------------------------------------------
# Step 1: 能力矩阵
# --------------------------------------------------------------------------


def test_import_boundaries_no_capital_gateway_execution(
    api: AuthorizerApi,
) -> None:
    source = Path(az_module.__file__).read_text(encoding="utf-8")
    assert _forbidden_import_segments(source) == []


def test_api_surface_excludes_gateway_capital_and_governance_lanes(
    api: AuthorizerApi,
) -> None:
    # 服务应暴露的两个方法
    assert callable(api.assess_edge)
    assert callable(api.issued_status)
    # gateway 状态激活/入口发布/permits 一律不得出现
    for name in GATEWAY_METHODS:
        assert not hasattr(api, name), name
    # capital 写入面一律不得出现
    for name in CAPITAL_METHODS:
        assert not hasattr(api, name), name
    # governance/issuer/publisher/finalizer 面一律不得出现
    for name in (
        "seal_trial",
        "issue_exploration",
        "issue_recovery",
        "sealed_trial",
        "target_policy",
        "publish_snapshot",
        "active_snapshot",
        "raw_payload",
        "register_plan_line",
        "finalize_due",
        "outcome_fact",
    ):
        assert not hasattr(api, name), name


def test_kind_isolation_authorizer_only_signs_edge(
    api: AuthorizerApi, ledgers,
) -> None:
    _reserve(ledgers[1], "attempt-kind-1")
    exploration = _envelope(
        kind=AuthorizationKind.EXPLORATION,
        mode=ExecutionMode.BROKER_CONFIRMED,
        broker_account_id="acct-1",
        broker_account_fingerprint=HASH,
    )
    with pytest.raises(AuthorizerError) as excinfo:
        api.assess_edge(
            _request(
                attempt_id="attempt-kind-1",
                sample_evidence_id="sample-kind-1",
                envelope=exploration,
            )
        )
    assert excinfo.value.code == "envelope_kind_mismatch"


def test_signer_is_private_no_public_accessor(api: AuthorizerApi) -> None:
    assert hasattr(api, "_signer")
    for name in ("signer", "get_signer", "sign", "signing_key"):
        assert not hasattr(api, name), name


# --------------------------------------------------------------------------
# Step 3: Authorizer 行为
# --------------------------------------------------------------------------


def test_edge_assessment_signs_inactive_complete_envelope(
    api: AuthorizerApi, ledgers,
) -> None:
    budget, attempts, _ = ledgers
    _reserve(attempts)
    envelope, signed = api.assess_edge(_request())
    assert envelope.authorization_kind is AuthorizationKind.EDGE
    # 产出必须是 INACTIVE 候选 (Authorizer 本身保证 status=INACTIVE)
    assert api.issued_status(envelope.authorization_id) == "INACTIVE"
    assert signed.payload_hash
    # 精确 issuer capability: 签名信封的 artifact/namespace/scope 与注册
    # capability 精确一致
    assert signed.artifact is trust.ArtifactKind.EDGE_AUTHORIZATION
    assert signed.namespace == SIGNER_NAMESPACE
    assert signed.capability_version == "capital.authorizer.v1"
    assert signed.capability_scope == "portfolio:paper-v3"
    assert envelope.issuer_capability == "authorizer.edge.envelope.v1"
    # Issuance consumes the global multiplicity budget and closes the
    # attempt as CONSUMED.
    assert budget.consumed(MultiplicityBudgetKind.ALPHA) == 1
    assert attempts.status("attempt-edge") is AttemptStatus.CONSUMED


@pytest.mark.parametrize(
    "override,code",
    [
        ({"benchmark_as_of": None}, "benchmark_missing"),
        (
            {"benchmark_as_of": CUTOFF - timedelta(days=3)},
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
    api: AuthorizerApi, override: dict, code: str
) -> None:
    with pytest.raises(AuthorizerError) as excinfo:
        api.assess_edge(_request(**override))
    assert excinfo.value.code == code
    # Nothing was issued.
    with pytest.raises(AuthorizerError):
        api.issued_status("auth-1")


def test_reissue_same_sample_is_rejected(
    api: AuthorizerApi, ledgers,
):
    budget, attempts, _ = ledgers
    _reserve(attempts)
    api.assess_edge(_request())
    _reserve(attempts, "attempt-edge-b")
    with pytest.raises(AuthorizerError) as excinfo:
        api.assess_edge(
            _request(
                attempt_id="attempt-edge-b",
                envelope=_envelope(authorization_id="auth-dup"),
            )
        )
    assert excinfo.value.code == "sample_reuse"
    # The failed issuance consumed no additional sample budget.
    assert budget.consumed(MultiplicityBudgetKind.ALPHA) == 2


def test_signer_failure_leaves_no_envelope_and_retry_is_deterministic(
    tmp_path: Path, ledgers,
) -> None:
    budget, attempts, consumption = ledgers
    failing = _FailingSigner()
    api = _make_api(tmp_path, ledgers, signer=failing)
    _reserve(attempts)
    with pytest.raises(RuntimeError):
        api.assess_edge(_request())
    # A failed signature leaves no consumption and no issued envelope:
    # the budget count stays at the reservation (1), the attempt stays
    # RESERVED, and the sample is unconsumed.
    with pytest.raises(AuthorizerError):
        api.issued_status("auth-1")
    assert failing.calls == 1
    assert budget.consumed(MultiplicityBudgetKind.ALPHA) == 1
    assert attempts.status("attempt-edge") is AttemptStatus.RESERVED
    consumption.consume_primary_promotion(
        research_program_id="prog-1",
        attempt_id="attempt-edge",
        evidence_id="sample-edge-1",
        payload_hash=HASH,
    )
    # Deterministic retry after the signer recovers: a fresh service over
    # the same database and ledgers succeeds.
    recovered = _make_api(tmp_path, ledgers)
    _reserve(attempts, "attempt-edge-2")
    envelope, _ = recovered.assess_edge(
        _request(
            attempt_id="attempt-edge-2",
            sample_evidence_id="sample-edge-2",
        )
    )
    assert recovered.issued_status(envelope.authorization_id) == "INACTIVE"
