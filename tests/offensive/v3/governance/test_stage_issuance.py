"""GovernanceStageIssuer — 治理签名 primitive (2026-08-20).

锁定: 派生单一事实源 (可派生字段全部取自封存 bundle 的严格重解析, 调用
方不能重复发明 trial/SAP/指纹/版本/日期)、签名载荷绑定 + 签发者身份交叉
核对、恰等重放幂等 / 背离冲突 (seal_stage insert-or-verify-exact)、未封存
trial 拒绝、能力错配拒绝、回执 + 证据时间轴 merkle → ``freeze_shared_input``
接缝 (治理签发冻结参数与证据根在同一 ShadowSharedInput 汇合)。

crib: test_regime_trial_governance 的信任链/封存夹具 (真实 Ed25519 链)。
诚实边界: 测试用 ephemeral 密钥链; 回执/签名 stage 不构成权限。
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest

from src.screening.offensive.v3.contracts.governance import StageManifest
from src.screening.offensive.v3.contracts.regime import (
    RegimeObservation,
    RegimeObservationReason,
    RegimeSourceRevision,
    RegimeState,
)
from src.screening.offensive.v3.evidence.merkle import evidence_set_merkle_root
from src.screening.offensive.v3.evidence.offline_rig import build_offline_evidence_rig
from src.screening.offensive.v3.execution.lifecycle import DailyBar
from src.screening.offensive.v3.governance.regime_trial import (
    ValidatedRegimeTrialBundle,
)
from src.screening.offensive.v3.governance.repository import (
    GovernanceRepository,
    GovernanceStoreError,
)
from src.screening.offensive.v3.governance.stage_issuance import (
    STAGE_ISSUER_CAPABILITY,
    GovernanceStageIssuer,
    StageIssuanceError,
    StageIssuanceRequest,
)
from src.screening.offensive.v3.kernel.models import (
    FrozenTradingSessionSchedule,
    ShadowSharedInput,
)
from src.screening.offensive.v3.orchestration.paired_trial import freeze_shared_input

from test_regime_trial_governance import (  # noqa: E402 - sibling crib
    ENROLLMENT_START,
    HASH,
    NOW,
    _seal_request,
)

TRIAL_ID = "trial-regime-001"
SIGNAL_SESSION = date(2026, 8, 6)


def _request(**overrides) -> StageIssuanceRequest:
    values = dict(
        trial_id=TRIAL_ID,
        stage_id="stage-regime-001",
        stage_sample_reservation_id="stage-sample-001",
        alpha_sample_consumption_id="alpha-001",
        alpha_or_evalue_budget_consumption_id="budget-001",
        attempt_ledger_checkpoint_hash=HASH,
        stage_loss_budget_id="stage-loss-001",
        stage_loss_version=1,
        maximum_loss_budget_cents=1_000_000,
        issuer_id="governance.service",
    )
    values.update(overrides)
    return StageIssuanceRequest(**values)


@pytest.fixture()
def sealed(tmp_path: Path):
    repository = GovernanceRepository(
        database_path=str(tmp_path / "gov.sqlite3"), clock=lambda: NOW
    )
    request, sign, verifier, current_head, caps, bundle = _seal_request()
    repository.seal_regime_trial(
        request, verifier=verifier, current_head=current_head,
        trusted_at=ENROLLMENT_START,
    )
    return repository, sign, verifier, current_head, caps, bundle


def _issuer(sealed, *, signer_caps_key: str = "stage") -> GovernanceStageIssuer:
    repository, sign, verifier, current_head, caps, _ = sealed
    return GovernanceStageIssuer(
        repository=repository,
        signer=lambda payload: sign(payload, caps[signer_caps_key]),
        stage_capability=caps["stage"],
        verifier=verifier,
        trust_head=lambda: current_head,
        clock=lambda: NOW,
    )


def test_issue_derives_every_field_from_sealed_truth(sealed) -> None:
    """可派生字段逐一来自封存 bundle; 请求只贡献台账事实与阶段身份。"""
    receipt = _issuer(sealed).issue(_request())
    bundle = sealed[0].regime_trial_bundle(TRIAL_ID)
    trial, sap = bundle.trial_manifest, bundle.sap_manifest

    manifest = StageManifest.model_validate_json(
        receipt.signed_stage_envelope.payload, strict=True
    )
    assert manifest.artifact_hash() == receipt.stage_manifest_hash  # 回执↔载荷绑定
    assert manifest.trial_manifest_hash == trial.artifact_hash()
    assert manifest.statistical_analysis_plan_hash == sap.artifact_hash()
    assert manifest.research_program_id == trial.research_program_id
    assert manifest.economic_lineage_id == trial.economic_lineage_id
    assert manifest.primary_metric == trial.primary_metric
    assert (
        manifest.baseline_portfolio_policy_fingerprint
        == trial.baseline_portfolio_policy_fingerprint
    )
    assert (
        manifest.target_portfolio_policy_fingerprint
        == trial.target_portfolio_policy_fingerprint
    )
    assert manifest.execution_version == trial.execution_version
    assert manifest.cost_version == trial.cost_version
    assert manifest.execution_mode is trial.execution_mode
    assert (
        manifest.governance_policy_version
        == bundle.baseline_policy.versions.governance_version
    )
    assert manifest.enrollment_start == trial.enrollment_start
    assert manifest.followup_finality_date == trial.followup_finality_date
    assert manifest.fixed_assessment_date == trial.fixed_assessment_date
    assert manifest.promotion_boolean_expression == trial.promotion_boolean_expression
    assert manifest.issued_at == NOW  # 注入时钟, 非墙上钟
    assert manifest.issuer_capability == STAGE_ISSUER_CAPABILITY
    assert manifest.maximum_loss_budget_cents == 1_000_000  # 请求的外部台账事实
    # 回执冗余字段与派生源一致
    assert receipt.trial_manifest_hash == trial.artifact_hash()
    assert receipt.statistical_analysis_plan_hash == sap.artifact_hash()
    assert receipt.execution_mode is trial.execution_mode
    assert receipt.sealed_at == NOW


def test_exact_replay_is_idempotent(sealed) -> None:
    """crash 后重试同一签发: 幂等收敛, 签名信封逐字节相同。"""
    issuer = _issuer(sealed)
    first = issuer.issue(_request())
    second = issuer.issue(_request())
    assert second.stage_manifest_hash == first.stage_manifest_hash
    assert (
        second.signed_stage_envelope.payload == first.signed_stage_envelope.payload
    )  # 确定性 Ed25519 + 冻结时钟 → 同字节


def test_divergent_reissue_conflicts(sealed) -> None:
    issuer = _issuer(sealed)
    issuer.issue(_request())
    with pytest.raises(GovernanceStoreError) as ei:
        issuer.issue(_request(maximum_loss_budget_cents=2_000_000))
    assert ei.value.code == "stage_seal_conflict"


def test_unsealed_trial_rejected(sealed) -> None:
    with pytest.raises(GovernanceStoreError) as ei:
        _issuer(sealed).issue(_request(trial_id="trial-unknown"))
    assert ei.value.code == "regime_trial_unknown"


def test_issuer_identity_mismatch_rejected(sealed) -> None:
    """载荷声称的 issuer 与签名信封身份错位 → 签发前拒绝。"""
    with pytest.raises(StageIssuanceError) as ei:
        _issuer(sealed).issue(_request(issuer_id="someone.else"))
    assert ei.value.code == "issuer_identity_mismatch"


def test_wrong_capability_rejected(sealed) -> None:
    """用 SAP 能力签名 stage → 验签 fail-closed, 不落库。"""
    issuer = _issuer(sealed, signer_caps_key="sap")
    with pytest.raises(GovernanceStoreError) as ei:
        issuer.issue(_request())
    assert ei.value.code == "artifact_verification_failed"


def test_receipt_and_merkle_root_freeze_the_shared_input(sealed, tmp_path: Path) -> None:
    """接缝: 治理签发回执 + 证据时间轴 merkle → 冻结共享输入逐字段汇合。"""
    repository, _sign, _verifier, _head, _caps, bundle = sealed
    receipt = _issuer(sealed).issue(_request())

    # 证据时间轴: 离线 rig 发布两张 bar-set 证据, merkle 根是它们的唯一绑定
    rig = build_offline_evidence_rig(
        database_path=tmp_path / "ev.sqlite3",
        blobs_dir=tmp_path / "blobs",
        namespace="market-bars",
    )
    sessions = (SIGNAL_SESSION, SIGNAL_SESSION + timedelta(days=1))
    records = tuple(
        rig.bar_publisher.publish(
            session=s,
            bars={
                "000001.SZ": DailyBar(
                    security_id="000001.SZ", session=s, open_cents=1000,
                    high_cents=1020, low_cents=990, close_cents=1005,
                    limit_up_cents=1100, limit_down_cents=900,
                )
            },
        )
        for s in sessions
    )
    root = evidence_set_merkle_root(
        (r.evidence.evidence_id, r.artifact_hash()) for r in records
    )

    validated = ValidatedRegimeTrialBundle(
        champion_policy=bundle.baseline_policy,
        challenger_policy=bundle.target_policy,
        baseline_policy=bundle.baseline_policy,
        target_policy=bundle.target_policy,
        trial_manifest=bundle.trial_manifest,
        sap_manifest=bundle.sap_manifest,
        admission_delta=("producers.btst_regime_admission_mode",),
    )
    cutoff = NOW + timedelta(hours=6)
    regime = RegimeObservation(
        signal_session=SIGNAL_SESSION,
        state=RegimeState.NORMAL,
        reason=RegimeObservationReason.CLASSIFIED,
        raw_state="normal",
        source_revisions=(
            RegimeSourceRevision(
                evidence_id="regime:csi300:1.0", revision=1, artifact_hash=HASH
            ),
        ),
        effective_at=cutoff,
        provider_published_at=cutoff,
        observed_at=cutoff,
        classifier_semver="1.0.0",
        behavior_fingerprint="d" * 64,
        input_schema_hash=HASH,
    )
    shared = freeze_shared_input(
        validated=validated,
        session=SIGNAL_SESSION,
        cycle_id="daily-action-20260806",
        regime=regime,
        trusted_at=NOW + timedelta(hours=7),
        trading_schedule=FrozenTradingSessionSchedule(
            calendar_id="sse-szse",
            calendar_version="sse-szse-official-sessions.v1",
            calendar_artifact_hash="c" * 64,
            signal_session=SIGNAL_SESSION,
            following_sessions=tuple(
                SIGNAL_SESSION + timedelta(days=d) for d in (1, 2, 3, 6, 7, 8, 9, 10, 13, 14)
            ),
            available_at=cutoff,
        ),
        evidence_set_merkle_root=root,
        stage_id=receipt.stage_id,
        stage_manifest_hash=receipt.stage_manifest_hash,
        registry_epoch=1,
        trusted_evidence_cutoff=cutoff,
    )
    # 治理签发与证据时间轴在冻结共享输入处逐字段汇合
    assert shared.stage_id == receipt.stage_id
    assert shared.stage_manifest_hash == receipt.stage_manifest_hash
    assert shared.evidence_set_merkle_root == root
    assert shared.trial_manifest_hash == receipt.trial_manifest_hash
    assert shared.sap_manifest_hash == receipt.statistical_analysis_plan_hash
    assert shared.trial_id == receipt.trial_id
    assert ShadowSharedInput.model_validate_json(shared.model_dump_json(), strict=True) == shared
