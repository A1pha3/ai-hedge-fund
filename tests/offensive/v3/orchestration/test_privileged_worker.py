"""ForwardSessionAssembler + stage archive — 特权 worker 组装面 (2026-08-20).

端到端钉死: 一次信号会话的官方决策输入**全部从 store 真相派生** — 治理
回执 ↔ 封存库互证、store 侧批授权 (三段式)、cutoff 正确的 regime/排程/
候选解析、freeze_shared_input 调用方零供给 — 然后接既有 builder 完成
决策/配对/提交 (证明组装面产物正是 kernel 消费的形态)。归档面: 幂等/
损坏拒绝/symlink 拒绝/穿越拒绝。

诚实边界: runner fail-closed 未解锁 (owner 决策); 两臂 PIT capital
snapshot 仍为 fixture (台账读取缺口开放)。
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.screening.offensive.v3.contracts.decision import ShadowDecision
from src.screening.offensive.v3.contracts.regime import RegimeAdmissionMode
from src.screening.offensive.v3.contracts.trial import TrialArm
from src.screening.offensive.v3.evidence.trading_schedule import CALENDAR_VERSION
from src.screening.offensive.v3.governance.regime_trial import (
    RegimeTrialBundle,
)
from src.screening.offensive.v3.governance.repository import (
    GovernanceRepository,
    RegimeTrialSealRequest,
)
from src.screening.offensive.v3.governance.stage_issuance import (
    GovernanceStageIssuer,
    StageIssuanceRequest,
)
from src.screening.offensive.v3.kernel.decide import GrowthKernel
from src.screening.offensive.v3.kernel.models import DeadlineContract
from src.screening.offensive.v3.kernel.models import ShadowCapitalCheckpoint
from src.screening.offensive.v3.orchestration.genesis import TrialGenesisManifest
from src.screening.offensive.v3.orchestration.paired_trial import (
    build_arm_kernel_inputs,
    build_pair_records,
)
from src.screening.offensive.v3.orchestration.privileged_worker import (
    ForwardSessionAssembler,
)
from src.screening.offensive.v3.orchestration.stage_archive import (
    StageArchiveError,
    read_stage_issuance_receipt,
    stage_receipt_path,
    write_stage_issuance_receipt,
)
from src.screening.offensive.v3.orchestration.trial_store import (
    TrialArmDecisionStore,
)
from src.screening.offensive.v3.policy.models import PolicySnapshot

# 跨目录 crib: 治理信任链/封存请求 (governance)、kernel 冻结世界 (kernel)、
# 批授权证据栈 (evidence)
for _dir in (
    Path(__file__).resolve().parents[1] / "governance",
    Path(__file__).resolve().parents[1] / "kernel",
    Path(__file__).resolve().parents[1] / "evidence",
):
    if str(_dir) not in sys.path:
        sys.path.insert(0, str(_dir))
from test_regime_trial_governance import (  # noqa: E402
    ENROLLMENT_START,
    HASH,
    NOW as GOV_NOW,
    _baseline_activation,
    _governance_trust,
    _sap_manifest,
    _trial_manifest,
    _trial_policy,
)
from test_shadow_kernel import (  # noqa: E402
    _capital_checkpoint,
    _config,
)
from test_session_batch import (  # noqa: E402
    CUTOFF,
    PUBLISH_AT,
    SESSION,
    build_batch_world,
    publish_candidate,
    publish_regime,
    publish_schedule,
)

UTC = timezone.utc
TRIAL_ID = "trial-regime-001"


def _policy_with_authoritative_calendar(policy: PolicySnapshot) -> PolicySnapshot:
    """夹具 policy 钉的 ``sse-szse-official-sessions.v1`` 从未被排程发布器
    产出 (权威身份是 ``sse-sessions-v1``); 本测试把版本对齐权威后再封存。
    夹具与冻结 goldens 的全面对齐是独立的后续项 (触碰 Plan 01 完成门)。"""
    values = json.loads(policy.model_dump_json())
    values["versions"]["calendar_version"] = CALENDAR_VERSION
    return PolicySnapshot.model_validate_json(json.dumps(values), strict=True)


def _seal_request_authoritative_calendar():
    sign, verifier, current_head, caps = _governance_trust()
    baseline = _policy_with_authoritative_calendar(
        _trial_policy(RegimeAdmissionMode.IGNORE)
    )
    target = _policy_with_authoritative_calendar(
        _trial_policy(RegimeAdmissionMode.NORMAL_ONLY)
    )
    trial = _trial_manifest(baseline, target)
    sap = _sap_manifest(trial)
    activation = _baseline_activation(baseline)
    request = RegimeTrialSealRequest(
        stage_id="stage-regime-001",
        signed_trial_envelope=sign(trial.canonical_bytes(), caps["trial"]),
        trial_manifest=trial,
        trial_capability=caps["trial"],
        signed_sap_envelope=sign(sap.canonical_bytes(), caps["sap"]),
        sap_manifest=sap,
        sap_capability=caps["sap"],
        signed_baseline_activation_envelope=sign(
            activation.canonical_bytes(), caps["activation"]
        ),
        baseline_policy_activation=activation,
        baseline_activation_capability=caps["activation"],
        baseline_policy=baseline,
        target_policy=target,
        expected_signal_cutoff=PUBLISH_AT,
    )
    bundle = RegimeTrialBundle(
        baseline_policy=baseline,
        target_policy=target,
        trial_manifest=trial,
        sap_manifest=sap,
        baseline_policy_activation=activation,
    )
    return request, sign, verifier, current_head, caps, bundle


def _registration_genesis() -> TrialGenesisManifest:
    return TrialGenesisManifest(
        trial_id=TRIAL_ID,
        normalized_genesis_hash=HASH,
        champion_normalized_hash=HASH,
        challenger_normalized_hash=HASH,
        champion_backup_root="b" * 64,
        challenger_backup_root="c" * 64,
        trial_manifest_hash="d" * 64,
        sap_manifest_hash="e" * 64,
        sealed_at=GOV_NOW,
        schema_major=2,
    )


@pytest.fixture()
def worker_world(tmp_path: Path):
    batch = build_batch_world(tmp_path)
    publish_regime(batch)
    schedule_record = publish_schedule(batch)
    candidate = publish_candidate(batch, "300001")

    governance = GovernanceRepository(
        database_path=str(tmp_path / "governance.sqlite3"), clock=lambda: GOV_NOW
    )
    request, sign, verifier, current_head, caps, bundle = (
        _seal_request_authoritative_calendar()
    )
    governance.seal_regime_trial(
        request, verifier=verifier, current_head=current_head,
        trusted_at=ENROLLMENT_START,
    )
    issuer = GovernanceStageIssuer(
        repository=governance,
        signer=lambda payload: sign(payload, caps["stage"]),
        stage_capability=caps["stage"],
        verifier=verifier,
        trust_head=lambda: current_head,
        clock=lambda: GOV_NOW,
    )
    receipt = issuer.issue(
        StageIssuanceRequest(
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
            issued_at=GOV_NOW,
        )
    )
    root = tmp_path / "trial-root"
    root.mkdir()
    assembler = ForwardSessionAssembler(
        sealer=batch.sealer,
        governance=governance,
        trial_id=TRIAL_ID,
        stage_receipt=receipt,
        regime_repository=batch.regime_rig.repository,
        schedule_repository=batch.schedule_rig.repository,
        btst_repository=batch.btst_repository,
    )
    return {
        "batch": batch,
        "governance": governance,
        "bundle": bundle,
        "receipt": receipt,
        "root": root,
        "assembler": assembler,
        "schedule_id": schedule_record.evidence.evidence_id,
        "candidate_id": candidate.evidence.evidence_id,
    }


def _assemble(world):
    return world["assembler"].assemble(
        session=SESSION,
        cutoff=CUTOFF,
        cycle_id="daily-action-20260806",
        trusted_at=datetime(2026, 8, 6, 15, 30, tzinfo=UTC),
        schedule_evidence_id=world["schedule_id"],
        candidate_evidence_ids=(world["candidate_id"],),
    )


def test_assemble_end_to_end_then_decide_and_commit_pair(worker_world):
    assembled = _assemble(worker_world)
    receipt = worker_world["receipt"]

    # 冻结输入的全部外部参数取自回执/批授权 — 调用方零供给
    assert assembled.shared_input.stage_id == receipt.stage_id
    assert assembled.shared_input.stage_manifest_hash == receipt.stage_manifest_hash
    assert assembled.shared_input.registry_epoch == receipt.registry_epoch
    assert (
        assembled.shared_input.evidence_set_merkle_root
        == assembled.authority.evidence_set_merkle_root
    )
    assert assembled.shared_input.trial_manifest_hash == receipt.trial_manifest_hash
    # 证据时间轴成员: cutoff 正确、会话一致
    assert assembled.regime.observation.signal_session == SESSION
    assert assembled.schedule.signal_session == SESSION
    assert len(assembled.schedule.following_sessions) == 10
    assert len(assembled.candidates) == 1
    assert assembled.candidates[0].payload.candidate_id.startswith("btst:snap-1:300001")

    # 组装产物正是 kernel 消费形态: 决策/配对/提交全链 (glue/issuance crib)
    capital = _capital_checkpoint(
        as_of=datetime(2026, 8, 6, 15, 0, tzinfo=UTC),
        valid_until=datetime(2026, 8, 7, 9, 0, tzinfo=UTC),
    )
    sizing = _config()
    # 宪法 #10 时序 (本会话 08-06): cutoff 12:00 < close 15:00 < seal 16:00
    # < permit 16:30 < expires/gateway 08-07 09:25 < broker 09:30; trusted_at 15:30
    deadlines = DeadlineContract(
        close_finalized_at=datetime(2026, 8, 6, 15, 0, tzinfo=UTC),
        seal_creation_deadline=datetime(2026, 8, 6, 16, 0, tzinfo=UTC),
        permit_issue_deadline=datetime(2026, 8, 6, 16, 30, tzinfo=UTC),
        permit_expires_at=datetime(2026, 8, 7, 9, 25, tzinfo=UTC),
        gateway_send_deadline=datetime(2026, 8, 7, 9, 25, tzinfo=UTC),
        broker_auction_cutoff=datetime(2026, 8, 7, 9, 30, tzinfo=UTC),
    )
    checkpoints = {}
    for arm, genesis_root in ((TrialArm.CHAMPION, "2" * 64), (TrialArm.CHALLENGER, "3" * 64)):
        checkpoints[arm] = ShadowCapitalCheckpoint(
            trial_id=TRIAL_ID,
            arm=arm,
            portfolio_id="paper-v3",
            mode=assembled.shared_input.mode,
            capital_store_id=f"{TRIAL_ID}:{arm.value}:capital",
            trial_genesis_manifest_hash="1" * 64,
            arm_capital_genesis_root=genesis_root,
            capital_snapshot_hash=capital.content_hash(),
            capital_snapshot=capital,
        )
    champion_input, challenger_input = build_arm_kernel_inputs(
        validated=assembled.validated_bundle,
        shared_input=assembled.shared_input,
        candidates=assembled.candidates,
        champion_capital_checkpoint=checkpoints[TrialArm.CHAMPION],
        challenger_capital_checkpoint=checkpoints[TrialArm.CHALLENGER],
        deadlines=deadlines,
        sizing_config=sizing,
    )
    champion = GrowthKernel(sizing).decide_shadow(champion_input)
    challenger = GrowthKernel(sizing).decide_shadow(challenger_input)
    assert isinstance(champion, ShadowDecision) and champion.counterfactual_lines
    assert champion.counterfactual_lines[0].target_quantity_units >= 100
    # 治理签发的 stage 哈希活着进入决策工件 (全链最后一米, 批授权根同源)
    assert champion.shadow_stage_binding.stage_manifest_hash == receipt.stage_manifest_hash
    records = build_pair_records(
        trial_id=TRIAL_ID,
        session=assembled.shared_input.signal_session,
        cycle_id=assembled.shared_input.decision_cycle_id,
        shared_input=assembled.shared_input,
        regime_hash=assembled.regime.observation_hash,
        champion=champion,
        challenger=challenger,
        trusted_at=assembled.shared_input.trusted_at,
        champion_input=champion_input,
        challenger_input=challenger_input,
    )
    store = TrialArmDecisionStore(database_path=str(worker_world["root"] / "decisions.sqlite3"))
    store.register_trial(worker_world["bundle"], _registration_genesis())
    first = store.commit_pair(*records)
    assert store.commit_pair(*records) == first  # 恰等重放幂等


def test_stage_archive_write_read_idempotent_and_guards(worker_world):
    receipt, root = worker_world["receipt"], worker_world["root"]
    target = stage_receipt_path(root, receipt)
    assert write_stage_issuance_receipt(root, receipt) == target
    assert write_stage_issuance_receipt(root, receipt) == target  # 幂等
    assert read_stage_issuance_receipt(target).content_hash() == receipt.content_hash()
    assert target.is_file() and not target.is_symlink()

    # 已归档文件被篡改 → 类型化损坏拒绝 (不是静默覆盖)
    target.write_text("{corrupt", encoding="utf-8")
    with pytest.raises(StageArchiveError) as ei:
        write_stage_issuance_receipt(root, receipt)
    assert ei.value.code == "archive_artifact_corrupt"

    # symlink 目标拒绝
    target.unlink()
    target.symlink_to("/etc/hosts")
    with pytest.raises(StageArchiveError) as ei:
        write_stage_issuance_receipt(root, receipt)
    assert ei.value.code == "archive_artifact_rejected"
    target.unlink()
    target.write_text(receipt.model_dump_json(), encoding="utf-8")  # 复位

    # 根路径穿越拒绝
    with pytest.raises(StageArchiveError) as ei:
        write_stage_issuance_receipt(root / ".." / "elsewhere", receipt)
    assert ei.value.code == "root_path_traversal"

    # 冷读拒绝 symlink
    link = root / "receipt-link.json"
    if os.path.exists(link) or link.is_symlink():
        link.unlink()
    link.symlink_to(target)
    with pytest.raises(StageArchiveError):
        read_stage_issuance_receipt(link)


def test_stage_archive_rejects_hostile_tmp(worker_world):
    """预置 tmp symlink → 类型化拒绝且不写穿 (P2-2 修复)。"""
    receipt, root = worker_world["receipt"], worker_world["root"]
    target = stage_receipt_path(root, receipt)
    target.parent.mkdir(parents=True, exist_ok=True)
    sentinel = root / "sentinel.txt"
    sentinel.write_text("innocent", encoding="utf-8")
    tmp = target.parent / f".{receipt.stage_id}.json.tmp"
    tmp.symlink_to(sentinel)
    with pytest.raises(StageArchiveError) as ei:
        write_stage_issuance_receipt(root, receipt)
    assert ei.value.code == "archive_tmp_conflict"
    assert sentinel.read_text(encoding="utf-8") == "innocent"  # 未写穿
