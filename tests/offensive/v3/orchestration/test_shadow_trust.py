"""Plan 05 Task 9 S4a: shadow_trust helper 单元测试。

验证 composition 辅助的三个契约 (S5 集成测试做真实 DB + flow 端到端):
1. build_shadow_trust_context — 每 namespace signer 产的信封能被 verifier 验证
   (信任链自洽; 与 EvidenceRepository.publish 内部 verifier.verify 同路径)。
2. synthesize_shadow_authority — envelope.policy_activation_hash ==
   policy_activation.artifact_hash() (admission 前置硬校验), 且用匹配 grant 的
   RawCandidate 跑 admit_candidates 恒 ADMITTED (证明合成 authority 解锁 kernel)。
3. derive_deadline_contract — ordering_valid() 通过 (KernelInput 结构合法)。
4. 合成 authority 确定性: 同 (portfolio_id, trust_bundle_hash, reference_time)
   两次构造产出相同 policy_activation.artifact_hash() (可复现, 利于诊断)。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.screening.offensive.v3 import trust as v3_trust
from src.screening.offensive.v3.evidence.repository import required_capability
from src.screening.offensive.v3.kernel.admission import (
    BTST_FAMILY,
    admit_candidates,
)
from src.screening.offensive.v3.kernel.models import RawCandidate
from src.screening.offensive.v3.orchestration.shadow_trust import (
    SHADOW_AUTO_SPEC,
    SHADOW_BTST_SPEC,
    SHADOW_OUTCOME_SPEC,
    build_shadow_trust_context,
    derive_deadline_contract,
    synthesize_shadow_authority,
)
from src.screening.offensive.v3.producers.btst import BTST_BEHAVIOR_BASELINE

NOW = datetime(2026, 8, 6, 9, 0, tzinfo=timezone.utc)
PORTFOLIO = "paper-v3"
BUNDLE_HASH = "f" * 64  # 任意确定值; 合成 authority 内部一致即可
_ALL_SPECS = (SHADOW_BTST_SPEC, SHADOW_AUTO_SPEC, SHADOW_OUTCOME_SPEC)


@pytest.mark.parametrize("spec", _ALL_SPECS, ids=lambda s: s.namespace)
def test_trust_context_verifies_signed_envelope_round_trip(spec):
    """signer_for(ns) 产的信封能被 ctx.verifier 验证 (信任链自洽, 每 namespace 独立)。"""
    ctx = build_shadow_trust_context(reference_time=NOW, specs=_ALL_SPECS)
    signed = ctx.signer_for(spec.namespace)(b'{"k":"v"}')
    # 与 EvidenceRepository.publish 内部完全同路径: required_capability(signed)
    # 从信封声明派生所需能力, verifier + head_provider 验证签名链。
    required = required_capability(signed)
    head = ctx.head_provider.current_trust_head(NOW)
    # 不抛即通过 (verify 失败会抛 TrustVerificationError)。
    ctx.verifier.verify(signed, required, current_head=head, trusted_at=NOW)


def test_trust_context_unknown_namespace_raises():
    """signer_for 对未配置 namespace 抛 KeyError (fail-closed, 不静默回退)。"""
    ctx = build_shadow_trust_context(reference_time=NOW, specs=(SHADOW_BTST_SPEC,))
    with pytest.raises(KeyError):
        ctx.signer_for("unknown")


def test_authority_envelope_matches_policy_activation_hash():
    """envelope.policy_activation_hash == policy_activation.artifact_hash() (admission:60 前置)。"""
    authority = synthesize_shadow_authority(
        portfolio_id=PORTFOLIO, trust_bundle_hash=BUNDLE_HASH, reference_time=NOW
    )
    assert (
        authority.envelope.policy_activation_hash
        == authority.policy_activation.artifact_hash()
    )


def test_authority_unlocks_kernel_admission_for_btst_candidate():
    """匹配 grant 的 RawCandidate → admit_candidates 恒 ADMITTED (S2b family_id 修复 + 合成 grant 协同)。

    这是"合成 authority 解锁 kernel"的核心证明: candidate 取 grant 的 lineage/
    program/stage + producer 信封的 behavior/execution/cost (与 _build_kernel_input
    同源构造), admission 全校验通过。若任一常量漂移 (family/behavior/execution/cost)
    即 BLOCKED — 本测试锁定合成 grant 与 producer 信封逐字一致。
    """
    authority = synthesize_shadow_authority(
        portfolio_id=PORTFOLIO, trust_bundle_hash=BUNDLE_HASH, reference_time=NOW
    )
    grant = authority.envelope.lineage_grants[0]
    assert grant.subject_producer == "btst"
    candidate = RawCandidate(
        candidate_id="btst:snap:300001",
        producer_namespace="btst",
        family_id=BTST_FAMILY,
        economic_lineage_id=grant.economic_lineage_id,
        research_program_id=grant.research_program_id,
        stage_id=grant.stage_id,
        security_id="300001.SZ",
        direction="LONG",
        unscaled_target_gross_cents=100_000,
        behavior_fingerprint=BTST_BEHAVIOR_BASELINE,
        execution_version="btst.funnel.v1",
        cost_version="cn-a-share-costs.v1",
    )
    results = admit_candidates(
        (candidate,),
        envelope=authority.envelope,
        policy_activation=authority.policy_activation,
    )
    assert len(results) == 1
    assert results[0].status == "ADMITTED"
    assert results[0].block_reason is None


def test_authority_grant_fingerprints_match_producer_envelope():
    """合成 grant 的 behavior/execution/cost 与 producers/auto._signal_envelope 逐字一致。"""
    authority = synthesize_shadow_authority(
        portfolio_id=PORTFOLIO, trust_bundle_hash=BUNDLE_HASH, reference_time=NOW
    )
    grant = authority.envelope.lineage_grants[0]
    assert grant.behavior_fingerprint == BTST_BEHAVIOR_BASELINE
    assert grant.execution_version == "btst.funnel.v1"
    assert grant.cost_version == "cn-a-share-costs.v1"


def test_authority_is_deterministic_for_same_inputs():
    """同 (portfolio_id, trust_bundle_hash, reference_time) → 相同 policy_activation hash (可复现诊断)。"""
    a = synthesize_shadow_authority(
        portfolio_id=PORTFOLIO, trust_bundle_hash=BUNDLE_HASH, reference_time=NOW
    )
    b = synthesize_shadow_authority(
        portfolio_id=PORTFOLIO, trust_bundle_hash=BUNDLE_HASH, reference_time=NOW
    )
    assert a.policy_activation.artifact_hash() == b.policy_activation.artifact_hash()
    assert a.envelope.artifact_hash() == b.envelope.artifact_hash()


def test_derive_deadline_contract_satisfies_ordering():
    """derive_deadline_contract 产出的 6 时点满足 ordering_valid() (KernelInput 结构合法)。"""
    close = datetime(2026, 8, 5, 15, 0, tzinfo=timezone.utc)
    deadlines = derive_deadline_contract(close_finalized_at=close)
    assert deadlines.ordering_valid() is True


def test_trust_context_bundle_hash_exposed_for_authority_consistency():
    """active_bundle_hash 暴露给合成 authority 的 envelope.trust_bundle_hash (内部一致)。"""
    ctx = build_shadow_trust_context(reference_time=NOW, specs=(SHADOW_BTST_SPEC,))
    authority = synthesize_shadow_authority(
        portfolio_id=PORTFOLIO,
        trust_bundle_hash=ctx.active_bundle_hash,
        reference_time=NOW,
    )
    assert authority.envelope.trust_bundle_hash == ctx.active_bundle_hash
