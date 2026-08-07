"""Plan 05 Task 9 S2 (RED): family_id 契约断裂回归 — 真实 BtstProducerApi + 真实 GrowthKernel。

缺陷: ``DailyActionFlow._build_kernel_input`` (orchestration/daily_action_flow.py:636)
当前以 ``family_id=envelope.family_id or ""`` 构造 RawCandidate — 真实 producer
信封的 family 是 ``f"btst:{snapshot_id}"`` (producers/auto.py:122), 而 kernel
admission 白名单只认 ``BTST_FAMILY = "btst.limit-up-breakout"``
(kernel/admission.py:25; 行 100 对非白名单恒 BLOCKED(NO_AUTHORIZED_ENVELOPE))。
结果: 全部真实候选被 admission 挡下 → kernel 恒 NoTrade(NO_SIGNAL) →
shadow 管线永远走不到 persist, --daily-action SHADOW 模式零产出。

修复契约 (主代理 GREEN): ``_build_kernel_input`` 改为
``family_id=BTST_FAMILY`` (import from kernel/admission), 使真实 producer
候选通过 admission 白名单。

本文件用**真实** ``BtstProducerApi`` (真实 Ed25519 信任上下文 + BlobStore +
evidence.sqlite3, 组装范式同 test_auto_flow._AutoWorld /
test_btst_producer_api._World) 与**真实** ``GrowthKernel`` (非 _FakeKernel)
端到端锁定该契约。flow 其余端口沿用 test_daily_action_flow 的 fake
(capital/snapshot loader/persister), kernel 外包一层 recording wrapper 捕获
``KernelInput`` 供直接断言。

snapshot_id 说明: 生产格式是 ``"sha256:"+hex`` (daily_action_snapshot.py:447,
含冒号), 与 ``_evidence_ticker`` 的 ``split(":")[2]`` 段错位属正交问题; 本回归
只锁 family 契约, 故用无冒号 snapshot_id 将其解耦 (ticker/价格路径保持真实)。

当前 RED (三个测试全失败, 断言失败而非 import 错误):
1. ``test_kernel_input_candidates_carry_btst_family_whitelist``
   — RawCandidate.family_id 实为 ``"btst:<snapshot_id>"`` ≠ BTST_FAMILY;
2. ``test_real_admission_admits_real_producer_candidates``
   — 真实 admission 对真实候选恒 BLOCKED(NO_AUTHORIZED_ENVELOPE);
3. ``test_real_kernel_produces_and_persists_shadow_decision``
   — shadow_decision_status 实为 "no_signal" (全候选被挡), 零持久化。
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from test_auto_flow import (
    _Clock,
    _hit_result,
    _issuer,
    _root_context,
    _signed,
    _snapshot as _verified_snapshot,
    _trust_capability,
)
from test_daily_action_flow import (
    _FakePersister,
    _FakeSnapshotLoader,
    _config,
    _envelope,
    _grant,
    _make_flow,
    _policy_activation,
    _run,
    SIGNAL_DATE,
)

from src.screening.offensive.daily_action_snapshot import VerifiedSnapshotResult
from src.screening.offensive.setups.btst_breakout import BtstBreakoutSetup
from src.screening.offensive.v3 import trust as v3_trust
from src.screening.offensive.v3.contracts.authorization import (
    CapitalAuthorizationEnvelope,
)
from src.screening.offensive.v3.contracts.governance import PolicyActivation
from src.screening.offensive.v3.evidence.blob_store import BlobStore
from src.screening.offensive.v3.kernel.admission import (
    BTST_FAMILY,
    admit_candidates,
)
from src.screening.offensive.v3.kernel.decide import GrowthKernel
from src.screening.offensive.v3.kernel.models import (
    BlockReason,
    KernelInput,
    NoTradeDecision,
    PortfolioDecision,
)
from src.screening.offensive.v3.orchestration.daily_action_flow import (
    DailyActionFlow,
)
from src.screening.offensive.v3.services.btst_producer_api import BtstProducerApi

UTC = timezone.utc
# producer 可信时钟: 与 test_auto_flow.NOW 同值 (信号次日 09:00 UTC) — 该锚点的
# 信任上下文 (capability/issuer/bundle 有效期 + trust head observed_at) 已在
# test_auto_flow / test_btst_producer_api 端到端验证, 原样复用以消除时间链变量。
PRODUCER_CLOCK_AT = datetime(2026, 8, 6, 9, 0, tzinfo=UTC)
BTST_NS = "btst"
BEHAVIOR = "b" * 64  # 与 grant.behavior_fingerprint 一致 (admission 精确匹配)
# 无冒号 snapshot_id: 解耦 _evidence_ticker 段错位 (见模块 docstring)。
SNAPSHOT_ID = "b" * 64
EXPECTED_SHADOW_ID = f"shadow-daily-action-{SIGNAL_DATE.isoformat()}"


class _BtstWorld:
    """真实信任上下文 + 同一 evidence DB 上的真实 ``BtstProducerApi``。

    范式同 test_auto_flow._AutoWorld / test_btst_producer_api._World: 真实
    Ed25519 signer (issuer namespace="btst") + BlobStore(tmp_path) +
    evidence.sqlite3 + CapabilityVerifier + CurrentTrustHeadWitness。
    """

    def __init__(self, tmp_path: Path) -> None:
        self.clock = _Clock(PRODUCER_CLOCK_AT)
        self.key = Ed25519PrivateKey.generate()
        self.capability = _trust_capability(BTST_NS)
        registry = v3_trust.TrustedRegistry(
            issuers=(
                _issuer(
                    self.key,
                    self.capability,
                    issuer_id="btst.producer",
                    key_id="btst-key-1",
                    kind=v3_trust.IssuerKind.SIGNAL_PRODUCER,
                ),
            )
        )
        verifier, head_provider = _root_context(registry)
        self.producer = BtstProducerApi(
            database_path=str(tmp_path / "evidence.sqlite3"),
            blob_store=BlobStore(tmp_path / "blobs"),
            verifier=verifier,
            trust_head_provider=head_provider,
            clock=self.clock,
            signer=self.sign,
            behavior_fingerprint=BEHAVIOR,
        )

    def sign(self, payload: bytes) -> v3_trust.SignedEnvelope:
        return _signed(
            self.key,
            self.capability,
            issuer_id="btst.producer",
            key_id="btst-key-1",
            payload=payload,
        )


class _RecordingKernel:
    """包一层真实 GrowthKernel: 记录 (kernel_input, trusted_at) 与返回决策。"""

    def __init__(self, inner: GrowthKernel) -> None:
        self.inner = inner
        self.calls: list[tuple[KernelInput, datetime]] = []
        self.decisions: list[PortfolioDecision | NoTradeDecision] = []

    def decide(
        self, kernel_input: KernelInput, *, trusted_at: datetime
    ) -> PortfolioDecision | NoTradeDecision:
        self.calls.append((kernel_input, trusted_at))
        decision = self.inner.decide(kernel_input, trusted_at=trusted_at)
        self.decisions.append(decision)
        return decision


@dataclass(frozen=True)
class _FamilyWorld:
    """一次 family 回归的全部句柄: 真实 producer/kernel + fake persister。"""

    flow: DailyActionFlow
    kernel: _RecordingKernel
    persister: _FakePersister
    policy: PolicyActivation
    envelope: CapitalAuthorizationEnvelope


@pytest.fixture()
def family_world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> _FamilyWorld:
    # scan_from_verified_snapshot 会真实跑 BtstBreakoutSetup.detect; 固定命中,
    # 使 2 个可扫 ticker 各产 CANDIDATE+SELECTED 信封 (test_auto_flow 同款)。
    monkeypatch.setattr(
        BtstBreakoutSetup,
        "detect",
        lambda self, ticker, trade_date, context: _hit_result(ticker),
    )
    world = _BtstWorld(tmp_path)
    snapshot = dataclasses.replace(_verified_snapshot(), snapshot_id=SNAPSHOT_ID)
    policy = _policy_activation()
    # admission 精确匹配契约 (kernel/admission.py:106-115): grant 的
    # behavior_fingerprint/execution_version/cost_version 须与 producer 信封一致
    # — producer 信封 execution_version 恒 "btst.funnel.v1"
    # (producers/auto.py:126), cost_version 恒 "cn-a-share-costs.v1"。
    envelope = _envelope(
        policy,
        lineage_grants=(_grant(execution_version="btst.funnel.v1"),),
    )
    kernel = _RecordingKernel(GrowthKernel(_config()))
    persister = _FakePersister()
    flow = _make_flow(
        snapshot_loader=_FakeSnapshotLoader(
            VerifiedSnapshotResult(snapshot=snapshot)
        ),
        producer=world.producer,
        kernel=kernel,
        persister=persister,
        policy=policy,
        envelope=envelope,
    )
    return _FamilyWorld(
        flow=flow,
        kernel=kernel,
        persister=persister,
        policy=policy,
        envelope=envelope,
    )


# --------------------------------------------------------------------------
# 回归测试 (修复后全绿; 当前全 RED)
# --------------------------------------------------------------------------


def test_kernel_input_candidates_carry_btst_family_whitelist(
    family_world: _FamilyWorld, tmp_path: Path
) -> None:
    """RawCandidate.family_id 必须是 admission 白名单 ``BTST_FAMILY``。"""
    _run(family_world.flow, tmp_path)

    assert len(family_world.kernel.calls) == 1
    kernel_input, _trusted_at = family_world.kernel.calls[0]
    # 真实 producer 确有 SELECTED 候选进入 kernel (2 个可扫 ticker)
    assert len(kernel_input.raw_candidates) == 2
    assert {
        candidate.security_id for candidate in kernel_input.raw_candidates
    } == {"300001.SZ", "300002.SZ"}
    for candidate in kernel_input.raw_candidates:
        assert candidate.producer_namespace == "btst"
        # RED 锚点: 修复前为 f"btst:{snapshot_id}" (非白名单), 修复后恒 BTST_FAMILY
        assert candidate.family_id == BTST_FAMILY


def test_real_admission_admits_real_producer_candidates(
    family_world: _FamilyWorld, tmp_path: Path
) -> None:
    """真实 admission 对真实 producer 候选: 全部 ADMITTED, 无 NO_AUTHORIZED_ENVELOPE。"""
    _run(family_world.flow, tmp_path)

    assert len(family_world.kernel.calls) == 1
    kernel_input, _trusted_at = family_world.kernel.calls[0]
    statuses = admit_candidates(
        kernel_input.raw_candidates,
        envelope=family_world.envelope,
        policy_activation=family_world.policy,
    )

    assert len(statuses) == 2
    for status in statuses:
        # RED 锚点: 修复前 family 非白名单 → status="BLOCKED" +
        # block_reason=NO_AUTHORIZED_ENVELOPE (kernel/admission.py:100-101)
        assert status.status == "ADMITTED"
        assert status.block_reason is None
        assert status.block_reason is not BlockReason.NO_AUTHORIZED_ENVELOPE


def test_real_kernel_produces_and_persists_shadow_decision(
    family_world: _FamilyWorld, tmp_path: Path
) -> None:
    """端到端: 真实 kernel 产出 PortfolioDecision → 持久化确定性 ShadowDecision。"""
    result = _run(family_world.flow, tmp_path)

    # RED 锚点: 修复前全候选被 admission 挡下 → NoTrade(NO_SIGNAL) →
    # shadow_decision_status="no_signal" 且零持久化
    assert result.shadow_decision_status == "ok"
    assert result.no_trade_reason is None
    assert result.failure_reason == {}
    assert len(family_world.kernel.decisions) == 1
    assert isinstance(family_world.kernel.decisions[0], PortfolioDecision)
    # 确定性 shadow id + 持久化契约 (fake persister 返回 decision id)
    assert result.shadow_decision_id == EXPECTED_SHADOW_ID
    assert len(family_world.persister.calls) == 1
    persisted = family_world.persister.calls[0]
    assert persisted.execution_authority == "NONE"
    assert len(persisted.counterfactual_lines) >= 1
