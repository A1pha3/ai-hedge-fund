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

import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.screening.offensive.v3.contracts.decision import ShadowDecision
from src.screening.offensive.v3.contracts.governance import StageManifest
from src.screening.offensive.v3.contracts.regime import (
    RegimeObservation,
    RegimeObservationReason,
    RegimeSourceRevision,
    RegimeState,
)
from src.screening.offensive.v3.contracts.trial import TrialArm
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
    StageIssuanceReceipt,
    StageIssuanceRequest,
)
from src.screening.offensive.v3.kernel.decide import GrowthKernel
from src.screening.offensive.v3.kernel.models import (
    FrozenTradingSessionSchedule,
    ShadowCapitalCheckpoint,
    ShadowSharedInput,
)
from src.screening.offensive.v3.orchestration.paired_trial import (
    build_arm_kernel_inputs,
    freeze_shared_input,
)

from test_regime_trial_governance import (  # noqa: E402 - sibling crib
    ENROLLMENT_START,
    HASH,
    NOW,
    _seal_request,
)

# 跨目录 crib (test_trial_arm_store 先例): kernel 冻结世界构造器 + 胶水
# 测试的候选构造器 — 最后一米断言需要真实 kernel 决策。
for _dir in (
    Path(__file__).resolve().parents[1] / "kernel",
    Path(__file__).resolve().parents[1] / "orchestration",
):
    if str(_dir) not in sys.path:
        sys.path.insert(0, str(_dir))
from test_shadow_kernel import (  # noqa: E402
    _capital_checkpoint,
    _config,
    _deadlines,
)
from test_glue_replay_assembly_session_driver import (  # noqa: E402
    _committed_candidate,
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
        issued_at=NOW,
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


def _issuer(sealed, *, signer_caps_key: str = "stage", clock=None) -> GovernanceStageIssuer:
    repository, sign, verifier, current_head, caps, _ = sealed
    return GovernanceStageIssuer(
        repository=repository,
        signer=lambda payload: sign(payload, caps[signer_caps_key]),
        stage_capability=caps["stage"],
        verifier=verifier,
        trust_head=lambda: current_head,
        clock=clock or (lambda: NOW),
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
    assert manifest.issued_at == NOW  # 请求声明的签发时刻 (P2-c: 行为身份), 非墙上钟
    assert manifest.issuer_capability == STAGE_ISSUER_CAPABILITY
    assert manifest.maximum_loss_budget_cents == 1_000_000  # 请求的外部台账事实
    # 回执冗余字段与派生源一致
    assert receipt.trial_manifest_hash == trial.artifact_hash()
    assert receipt.statistical_analysis_plan_hash == sap.artifact_hash()
    assert receipt.execution_mode is trial.execution_mode
    assert receipt.issued_at == NOW  # 签发时刻 (与 manifest.issued_at 同源, 非 store 落库时刻)
    # 冻结参数集自足 (P2-d): registry_epoch / trust_bundle_hash 来自封存 trial
    assert receipt.registry_epoch == trial.registry_epoch
    assert receipt.trust_bundle_hash == trial.trust_bundle_hash


def test_receipt_is_hash_bound_and_drift_proof(sealed) -> None:
    """回执 = frozen CanonicalModel: 严格往返、content_hash 稳定、与签名
    manifest 的任何漂移在构造时拒绝 — 冗余字段不可被单独篡改。"""
    receipt = _issuer(sealed).issue(_request())
    rebuilt = StageIssuanceReceipt.model_validate_json(
        receipt.model_dump_json(), strict=True
    )
    assert rebuilt == receipt
    assert rebuilt.content_hash() == receipt.content_hash()
    tampered = json.loads(receipt.model_dump_json())
    tampered["execution_version"] = "drifted.v9"
    with pytest.raises(ValidationError, match="does not match the signed manifest"):
        StageIssuanceReceipt.model_validate_json(json.dumps(tampered), strict=True)


def test_exact_replay_is_idempotent(sealed) -> None:
    """crash 后重试同一请求: 推进中的墙钟下仍逐字节收敛 (P2-c 落地)。

    签发时刻在请求内, 幂等不再依赖环境钟; 两次 issue 之间时钟前进 1 小时,
    签名信封仍逐字节相同 (确定性 Ed25519 + 请求决定的 manifest 字节)。
    """
    class _AdvancingClock:
        def __init__(self) -> None:
            self._moment = NOW

        def __call__(self) -> datetime:
            self._moment += timedelta(hours=1)
            return self._moment

    clock = _AdvancingClock()
    issuer = _issuer(sealed, clock=clock)
    first = issuer.issue(_request())  # trusted_at = NOW+1h (首读推进)
    second = issuer.issue(_request())  # trusted_at = NOW+2h, 字节仍收敛
    assert second.stage_manifest_hash == first.stage_manifest_hash
    assert (
        second.signed_stage_envelope.payload == first.signed_stage_envelope.payload
    )


def test_future_issuance_instant_rejected(sealed) -> None:
    """签发方不得声明未来时刻 — 对注入钟校验后拒绝, 不落库。"""
    with pytest.raises(StageIssuanceError) as ei:
        _issuer(sealed).issue(_request(issued_at=NOW + timedelta(seconds=1)))
    assert ei.value.code == "future_issuance_instant"


def test_sealed_stage_reader_round_trips(sealed) -> None:
    """sealed_stage 读面: 从封存真相严格重解析, 与回执逐字节一致。"""
    receipt = _issuer(sealed).issue(_request())
    record = sealed[0].sealed_stage("stage-regime-001")
    assert record.stage_manifest.artifact_hash() == receipt.stage_manifest_hash
    assert record.signed_stage_envelope.payload == receipt.signed_stage_envelope.payload
    assert record.trial_id == TRIAL_ID
    with pytest.raises(GovernanceStoreError) as ei:
        sealed[0].sealed_stage("stage-unknown")
    assert ei.value.code == "stage_unknown"


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
    cutoff = NOW + timedelta(hours=5)  # 14:00 < kernel 世界 close_finalized 15:00
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
        trusted_at=NOW + timedelta(hours=5, minutes=30),
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
        registry_epoch=receipt.registry_epoch,  # 回执自足, 不再硬编码
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

    # 最后一米 (P2-e, 第二轮审查): 治理签发的 stage 哈希活着进入 kernel
    # 决策工件 — 签名 → 冻结输入 → ShadowStageBinding 全链钉死。
    capital = _capital_checkpoint()
    checkpoints = {}
    for arm, genesis_root in ((TrialArm.CHAMPION, "2" * 64), (TrialArm.CHALLENGER, "3" * 64)):
        checkpoints[arm] = ShadowCapitalCheckpoint(
            trial_id=shared.trial_id,
            arm=arm,
            portfolio_id="paper-v3",
            mode=shared.mode,
            capital_store_id=f"{shared.trial_id}:{arm.value}:capital",
            trial_genesis_manifest_hash="1" * 64,
            arm_capital_genesis_root=genesis_root,
            capital_snapshot_hash=capital.content_hash(),
            capital_snapshot=capital,
        )
    sizing = _config()
    champion_input, _challenger_input = build_arm_kernel_inputs(
        validated=validated,
        shared_input=shared,
        candidates=(_committed_candidate(),),
        champion_capital_checkpoint=checkpoints[TrialArm.CHAMPION],
        challenger_capital_checkpoint=checkpoints[TrialArm.CHALLENGER],
        deadlines=_deadlines(),
        sizing_config=sizing,
    )
    decision = GrowthKernel(sizing).decide_shadow(champion_input)
    assert isinstance(decision, ShadowDecision)
    assert decision.shadow_stage_binding.stage_manifest_hash == receipt.stage_manifest_hash
    assert decision.shadow_stage_binding.stage_id == receipt.stage_id
    assert decision.shadow_stage_binding.trial_id == receipt.trial_id
