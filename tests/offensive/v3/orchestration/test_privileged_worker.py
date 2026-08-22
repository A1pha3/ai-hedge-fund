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
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.screening.offensive.v3.contracts.decision import ShadowDecision
from src.screening.offensive.v3.contracts.regime import RegimeAdmissionMode
from src.screening.offensive.v3.contracts.trial import TrialArm
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
    PrivilegedWorkerError,
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


def _seal_request():
    sign, verifier, current_head, caps = _governance_trust()
    baseline = _trial_policy(RegimeAdmissionMode.IGNORE)
    target = _trial_policy(RegimeAdmissionMode.NORMAL_ONLY)
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
        _seal_request()
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


# --- 第九轮: 候选消费面防御断言 (排程侧双层/候选侧单层不对称的收口) ----------


class _DuckRepo:
    """鸭子 btst 仓库: 直接返回构造好的 active 记录 (镜像第七轮 Op2 手法,
    不依赖上游信任层兜底 — 消费面断言独立于 sealer 层可达性)。"""

    def __init__(self, record) -> None:
        self._record = record

    def active_revision(self, evidence_id, cutoff):
        del evidence_id, cutoff
        return self._record

    def raw_payload(self, content_hash):
        del content_hash
        raise AssertionError("face assertions must fire before payload decode")


def _face(assembler, record):
    return assembler._committed_candidate("whatever-id", CUTOFF, SESSION)


def test_candidate_face_rejects_non_signal_envelope(worker_world):
    """kind 断言: 非 SignalEvidence 信封在 worker 面即拒 (candidate_kind_mismatch,
    与 sealer _candidate_binding 同码)。"""
    schedule_record = publish_schedule(worker_world["batch"])
    assembler = ForwardSessionAssembler(
        sealer=worker_world["batch"].sealer,
        governance=worker_world["governance"],
        trial_id=TRIAL_ID,
        stage_receipt=worker_world["receipt"],
        regime_repository=worker_world["batch"].regime_rig.repository,
        schedule_repository=worker_world["batch"].schedule_rig.repository,
        btst_repository=_DuckRepo(schedule_record),
    )
    with pytest.raises(PrivilegedWorkerError) as ei:
        _face(assembler, schedule_record)
    assert ei.value.code == "candidate_kind_mismatch"


def test_candidate_face_rejects_non_selected_stage(worker_world):
    """stage 断言: 非 SELECTED 候选在 worker 面即拒 (candidate_stage_mismatch)。"""
    from src.screening.offensive.v3.contracts.base import SignalStage

    record = publish_candidate(
        worker_world["batch"], "300002", stage=SignalStage.CANDIDATE
    )
    assembler = ForwardSessionAssembler(
        sealer=worker_world["batch"].sealer,
        governance=worker_world["governance"],
        trial_id=TRIAL_ID,
        stage_receipt=worker_world["receipt"],
        regime_repository=worker_world["batch"].regime_rig.repository,
        schedule_repository=worker_world["batch"].schedule_rig.repository,
        btst_repository=_DuckRepo(record),
    )
    with pytest.raises(PrivilegedWorkerError) as ei:
        _face(assembler, record.evidence)
    assert ei.value.code == "candidate_stage_mismatch"


def test_assemble_rejects_cross_wired_candidate_session(worker_world, tmp_path):
    """端到端 PoC (错接线, RED 主证): sealer/库 X 完备通过, worker 的
    btst_repository 指向库 Y — 同 evidence_id 在 Y 上属于另一信号会话
    (publish_candidate 的 id 不含 session)。修复前 assemble 放行错位
    候选进入 kernel 输入, 修复后 worker 面类型化拒绝。"""
    clean = build_batch_world(tmp_path / "clean")
    cross_wired = build_batch_world(tmp_path / "cross")
    publish_regime(clean)
    schedule = publish_schedule(clean)
    candidate = publish_candidate(clean, "300001")

    # 库 Y: 同 evidence_id, effective_at 属 2026-08-13 (T+1..T+10 整体错位)
    publish_candidate(cross_wired, "300001", session=date(2026, 8, 13))

    assembler = ForwardSessionAssembler(
        sealer=clean.sealer,
        governance=worker_world["governance"],
        trial_id=TRIAL_ID,
        stage_receipt=worker_world["receipt"],
        regime_repository=clean.regime_rig.repository,
        schedule_repository=clean.schedule_rig.repository,
        btst_repository=cross_wired.btst_repository,
    )
    with pytest.raises(PrivilegedWorkerError) as ei:
        assembler.assemble(
            session=SESSION,
            cutoff=CUTOFF,
            cycle_id="daily-action-20260806",
            trusted_at=datetime(2026, 8, 6, 15, 30, tzinfo=UTC),
            schedule_evidence_id=schedule.evidence.evidence_id,
            candidate_evidence_ids=(candidate.evidence.evidence_id,),
        )
    assert ei.value.code == "candidate_session_mismatch"


# --- R20: 特权 worker UDS 进程边界原语 --------------------------------------


class TestWorkerServer:
    def _server(self, worker_world, tmp_path, **kw):
        # macOS sun_path 限制 104 字节, pytest basetemp 过长 → 系统 mkdtemp
        # (短路径; /var/folders 下由操作系统自动清理)
        import tempfile

        from src.screening.offensive.v3.orchestration.worker_server import (
            PrivilegedWorkerServer,
            WorkerServerConfig,
        )

        short_dir = Path(tempfile.mkdtemp(prefix="wks-"))
        return PrivilegedWorkerServer(
            assembler=worker_world["assembler"],
            config=WorkerServerConfig(socket_dir=short_dir),
            **kw,
        )

    def _client_roundtrip(self, sock_path, request, uid=None):
        import socket as s

        if uid is None:
            uid = os.getuid()
        conn = s.socket(s.AF_UNIX, s.SOCK_STREAM)
        conn.connect(str(sock_path))
        conn.sendall(json.dumps(request).encode("utf-8"))
        conn.shutdown(s.SHUT_WR)
        data = b""
        while True:
            chunk = conn.recv(65536)
            if not chunk:
                break
            data += chunk
        conn.close()
        # serve_once 需要在 accept 前启动 — 本测试由调用方线程驱动
        return data

    def test_bind_serve_roundtrip(self, worker_world, tmp_path):
        import threading

        server = self._server(worker_world, tmp_path, peer_uid_extractor=lambda c: os.getuid())
        sock_path = server.bind()
        assert sock_path.is_socket()

        result = {}

        def run():
            result["response"] = server.serve_once()

        t = threading.Thread(target=run)
        t.start()
        import socket as s

        conn = s.socket(s.AF_UNIX, s.SOCK_STREAM)
        conn.connect(str(sock_path))
        conn.sendall(
            json.dumps(
                {
                    "op": "assemble",
                    "session": SESSION.isoformat(),
                    "cutoff": CUTOFF.isoformat(),
                    "cycle_id": "daily-action-20260806",
                    "trusted_at": "2026-08-06T15:30:00+00:00",
                    "schedule_evidence_id": worker_world["schedule_id"],
                    "candidate_evidence_ids": [worker_world["candidate_id"]],
                }
            ).encode("utf-8")
        )
        conn.shutdown(s.SHUT_WR)
        data = b""
        while True:
            chunk = conn.recv(65536)
            if not chunk:
                break
            data += chunk
        conn.close()
        t.join(timeout=10)

        resp = result["response"]
        assert resp["ok"] is True
        assert resp["stage_id"] == worker_world["receipt"].stage_id
        assert resp["candidates"] == 1
        assert len(resp["evidence_set_merkle_root"]) == 64
        assert json.loads(data)["ok"] is True
        server.close()

    def test_peer_uid_rejected(self, worker_world, tmp_path):
        import threading
        import socket as s

        server = self._server(
            worker_world, tmp_path, peer_uid_extractor=lambda c: 99999
        )
        sock_path = server.bind()
        result = {}

        def run():
            result["response"] = server.serve_once()

        t = threading.Thread(target=run)
        t.start()
        conn = s.socket(s.AF_UNIX, s.SOCK_STREAM)
        conn.connect(str(sock_path))
        conn.sendall(b'{"op":"assemble"}')
        conn.shutdown(s.SHUT_WR)
        data = b""
        while True:
            chunk = conn.recv(65536)
            if not chunk:
                break
            data += chunk
        conn.close()
        t.join(timeout=10)
        assert result["response"]["ok"] is False
        assert result["response"]["code"] == "peer_uid_rejected"
        server.close()

    def test_op_unknown_and_bad_request(self, worker_world, tmp_path):
        import threading
        import socket as s

        server = self._server(worker_world, tmp_path, peer_uid_extractor=lambda c: os.getuid())
        sock_path = server.bind()
        for payload, expected_code in (
            ({"op": "nope"}, "op_unknown"),
            ({"op": "assemble", "session": "not-a-date"}, "request_invalid"),
        ):
            result = {}

            def run():
                result["response"] = server.serve_once()

            t = threading.Thread(target=run)
            t.start()
            conn = s.socket(s.AF_UNIX, s.SOCK_STREAM)
            conn.connect(str(sock_path))
            conn.sendall(json.dumps(payload).encode("utf-8"))
            conn.shutdown(s.SHUT_WR)
            while conn.recv(65536):
                pass
            conn.close()
            t.join(timeout=10)
            assert result["response"]["ok"] is False, payload
            assert result["response"]["code"] == expected_code, payload
        server.close()

    def test_live_lease_conflict_and_stale_cleanup(self, worker_world, tmp_path):
        from src.screening.offensive.v3.orchestration.worker_server import (
            WorkerServerError,
        )

        server = self._server(worker_world, tmp_path, peer_uid_extractor=lambda c: os.getuid())
        sock_path = server.bind()
        shared_dir = server._config.socket_dir  # 同一 socket 目录才谈得上冲突
        from src.screening.offensive.v3.orchestration.worker_server import (
            PrivilegedWorkerServer,
            WorkerServerConfig,
        )

        def _sibling():
            return PrivilegedWorkerServer(
                assembler=worker_world["assembler"],
                config=WorkerServerConfig(socket_dir=shared_dir),
                peer_uid_extractor=lambda c: os.getuid(),
            )

        with pytest.raises(WorkerServerError) as ei:
            _sibling().bind()
        assert ei.value.code == "worker_server_conflict"

        # 模拟进程死亡: lease 指向不存在 pid → stale 清理重绑
        lease = sock_path.parent / "privileged-worker.lease.json"
        lease.write_text(json.dumps({"pid": 999999999, "service_name": "privileged-worker", "started_at": "x", "owner_uid": os.getuid()}))
        third = _sibling()
        third.bind()  # stale → 清理成功
        third.close()
        server.close()

    def test_serve_before_bind_rejected(self, worker_world, tmp_path):
        from src.screening.offensive.v3.orchestration.worker_server import (
            WorkerServerError,
        )

        server = self._server(worker_world, tmp_path)
        with pytest.raises(WorkerServerError) as ei:
            server.serve_once()
        assert ei.value.code == "worker_server_not_bound"


# --- R24: runner 解锁端到端 (官方 decide 链) ---------------------------------


class TestRunnerUnlock:
    def _armed_trial_root(self, tmp_path: Path) -> Path:
        """真实 genesis 资本链: seed(proxy) → seal → 双臂 restore 至约定路径。"""
        from datetime import timezone

        from src.screening.offensive.v3.capital.flows import GenesisRequest
        from src.screening.offensive.v3.capital.identity import AccountBinding
        from src.screening.offensive.v3.capital.repository import CapitalRepository
        from src.screening.offensive.v3.contracts.base import ExecutionMode
        from src.screening.offensive.v3.orchestration.arm_capital import (
            read_genesis_manifest,
        )
        from src.screening.offensive.v3.orchestration.arm_layout import (
            arm_capital_database_path,
        )
        from src.screening.offensive.v3.orchestration.genesis import (
            restore_genesis_arm,
        )

        now = datetime(2026, 8, 6, 9, 0, tzinfo=timezone.utc)
        root = tmp_path / "trial-root"
        seed = tmp_path / "seed-capital.sqlite3"
        repo = CapitalRepository.initialize(seed)
        repo.initialize_genesis(GenesisRequest(
            idempotency_key="genesis-1",
            account_binding=AccountBinding(
                portfolio_id="pf-btst-trial",
                mode=ExecutionMode.DAILY_BAR_PROXY,
                broker_account_id=None,
                base_currency="CNY",
                environment_fingerprint=None,
            ),
            unit_quanta=10_000, unit_price_numerator=1_000, unit_price_denominator=1,
            source_authority="governance.test", authorization_reference="test-1",
            effective_at=now, as_of=now,
        ))
        from src.screening.offensive.v3.orchestration.genesis import (
            TrialArmGenesisSource,
            TrialGenesisArchive,
        )

        source = TrialArmGenesisSource(capital_repository=repo)
        manifest = TrialGenesisArchive(root).seal(
            TRIAL_ID, champion_source=source, challenger_source=source
        )
        for arm in ("CHAMPION", "CHALLENGER"):
            target = arm_capital_database_path(root, TrialArm[arm])
            target.parent.mkdir(parents=True, exist_ok=True)
            restore_genesis_arm(manifest, root, target, arm=arm)
        return root

    def test_decide_signal_session_end_to_end(self, worker_world, tmp_path):
        from src.screening.offensive.v3.kernel.decide import GrowthKernel
        from src.screening.offensive.v3.orchestration.paired_trial import (
            ForwardPairedTrialRunner,
            SignalSessionRequest,
        )

        trial_root = self._armed_trial_root(tmp_path)
        store = TrialArmDecisionStore(
            database_path=str(worker_world["root"] / "decisions.sqlite3")
        )
        store.register_trial(worker_world["bundle"], _registration_genesis())
        runner = ForwardPairedTrialRunner(
            assembler=worker_world["assembler"],
            capital_trial_root=trial_root,
            portfolio_id="pf-btst-trial",
            sizing_config=_config(),
            decision_store=store,
        )
        request = SignalSessionRequest(
            trial_id=TRIAL_ID,
            signal_session=SESSION,
            decision_cycle_id="daily-action-20260806",
            trusted_evidence_cutoff=CUTOFF,
            trusted_at=datetime(2026, 8, 6, 15, 30, tzinfo=UTC),
            schedule_evidence_id=worker_world["schedule_id"],
            candidate_evidence_ids=(worker_world["candidate_id"],),
            deadlines=DeadlineContract(
                close_finalized_at=datetime(2026, 8, 6, 15, 0, tzinfo=UTC),
                seal_creation_deadline=datetime(2026, 8, 6, 16, 0, tzinfo=UTC),
                permit_issue_deadline=datetime(2026, 8, 6, 16, 30, tzinfo=UTC),
                permit_expires_at=datetime(2026, 8, 7, 9, 25, tzinfo=UTC),
                gateway_send_deadline=datetime(2026, 8, 7, 9, 25, tzinfo=UTC),
                broker_auction_cutoff=datetime(2026, 8, 7, 9, 30, tzinfo=UTC),
            ),
        )
        receipt = runner.decide_signal_session(request)
        assert receipt.trial_id == TRIAL_ID
        assert receipt.decision_cycle_id == "daily-action-20260806"
        assert len(receipt.regime_observation_hash) == 64
        assert receipt.pair_key == (TRIAL_ID, SESSION.isoformat(), "daily-action-20260806")
        # 幂等重放: 同请求再决策返回同 receipt (commit_pair 恰等收敛)
        again = runner.decide_signal_session(request)
        assert again.pair_key == receipt.pair_key
        assert again.regime_observation_hash == receipt.regime_observation_hash

    def test_locked_runner_rejects_and_advance_still_closed(self, worker_world):
        from src.screening.offensive.v3.orchestration.paired_trial import (
            ForwardPairedTrialRunner,
            PairedTrialRunnerError,
            SignalSessionRequest,
        )

        locked = ForwardPairedTrialRunner()
        req = SignalSessionRequest(trial_id=TRIAL_ID, signal_session=SESSION)
        with pytest.raises(PairedTrialRunnerError) as ei:
            locked.decide_signal_session(req)
        assert ei.value.code == "forward_input_authority_unavailable"
        with pytest.raises(PairedTrialRunnerError) as ei:
            locked.advance_market_session(req)
        assert ei.value.code == "forward_input_authority_unavailable"
        with pytest.raises(PairedTrialRunnerError) as ei:
            locked.finalize_missed_sessions(datetime(2026, 8, 7, tzinfo=UTC))
        assert ei.value.code == "forward_input_authority_unavailable"


class TestRunnerAdvanceUnlock:
    """R25: advance_market_session 解锁 — 市场会话推进端到端。"""

    def test_advance_end_to_end(self, worker_world, tmp_path):
        """decide (R24 链) → bar 证据发布 → advance → 双臂守恒 + 幂等。"""
        from datetime import time as _time

        from src.screening.offensive.v3.contracts.decision import ShadowDecision
        from src.screening.offensive.v3.evidence.market_bars import (
            MarketBarSetPublisher,
        )
        from src.screening.offensive.v3.capital.fills import FillAttribution
        from src.screening.offensive.v3.execution.lifecycle import DailyBar
        from src.screening.offensive.v3.orchestration.arm_lifecycle import (
            CURRENT_COST_SCENARIO,
        )
        from src.screening.offensive.v3.orchestration.paired_trial import (
            ForwardPairedTrialRunner,
            MarketSessionAdvanceRequest,
            SignalSessionRequest,
        )

        trial_root = TestRunnerUnlock()._armed_trial_root(tmp_path)
        store = TrialArmDecisionStore(
            database_path=str(worker_world["root"] / "decisions.sqlite3")
        )
        store.register_trial(worker_world["bundle"], _registration_genesis())
        runner = ForwardPairedTrialRunner(
            assembler=worker_world["assembler"],
            capital_trial_root=trial_root,
            portfolio_id="pf-btst-trial",
            sizing_config=_config(),
            decision_store=store,
        )
        receipt = runner.decide_signal_session(SignalSessionRequest(
            trial_id=TRIAL_ID, signal_session=SESSION,
            decision_cycle_id="daily-action-20260806",
            trusted_evidence_cutoff=CUTOFF,
            trusted_at=datetime(2026, 8, 6, 15, 30, tzinfo=UTC),
            schedule_evidence_id=worker_world["schedule_id"],
            candidate_evidence_ids=(worker_world["candidate_id"],),
            deadlines=DeadlineContract(
                close_finalized_at=datetime(2026, 8, 6, 15, 0, tzinfo=UTC),
                seal_creation_deadline=datetime(2026, 8, 6, 16, 0, tzinfo=UTC),
                permit_issue_deadline=datetime(2026, 8, 6, 16, 30, tzinfo=UTC),
                permit_expires_at=datetime(2026, 8, 7, 9, 25, tzinfo=UTC),
                gateway_send_deadline=datetime(2026, 8, 7, 9, 25, tzinfo=UTC),
                broker_auction_cutoff=datetime(2026, 8, 7, 9, 30, tzinfo=UTC),
            ),
        ))
        # 从已 commit 的 pair 读 kernel 行 → 确定 entry/exit 会话与标的
        champion, challenger = store.pair(receipt.pair_key)
        decision = champion.decision
        assert isinstance(decision, ShadowDecision)
        line = decision.counterfactual_lines[0]
        entry_session = decision.target_entry_session
        exit_session = line.target_exit_session

        # bar 证据发布 (证据时间轴唯一入口): 窗口内每会话一张 bar-set
        from src.screening.offensive.v3.evidence.offline_rig import (
            build_offline_evidence_rig,
        )

        bars_rig = build_offline_evidence_rig(
            database_path=tmp_path / "bars-evidence.sqlite3",
            blobs_dir=tmp_path / "blobs",
            namespace="btst-bars",
            clock=lambda: datetime(2026, 8, 6, 9, 0, tzinfo=UTC),
            trust_now=datetime(2026, 8, 6, 9, 0, tzinfo=UTC),
        )
        publisher = MarketBarSetPublisher(
            repository=bars_rig.repository,
            clock=lambda: datetime(2026, 8, 6, 9, 0, tzinfo=UTC),
            signer=bars_rig.signer,
        )
        sessions = []
        s = entry_session
        while s <= exit_session:
            sessions.append(s)
            s += timedelta(days=1)
        bar_records = {}
        for s in sessions:
            # bar 对齐 candidate entry 价 (fixture 1.00 元 = 100 cents,
            # 板块 10% fences: 110/90) — 买入上限 100 >= open 100 → FILLED
            bar = DailyBar(
                security_id=line.security_id, session=s,
                open_cents=100, high_cents=106,
                low_cents=95, close_cents=103,
                limit_up_cents=110, limit_down_cents=90,
            )
            bar_records[s] = publisher.publish(session=s, bars={line.security_id: bar})

        advance = ForwardPairedTrialRunner(
            assembler=worker_world["assembler"],
            capital_trial_root=trial_root,
            portfolio_id="pf-btst-trial",
            sizing_config=_config(),
            decision_store=store,
            bar_repository=bars_rig.repository,
            market_scenario=CURRENT_COST_SCENARIO,
            trial_attribution=FillAttribution(
                producer_namespace="btst",
                research_program_id="prog-1",
                economic_lineage_id="eline-1",
                stage_id="stage-1",
            ),
        )
        result = advance.advance_market_session(MarketSessionAdvanceRequest(
            trial_id=TRIAL_ID,
            through_session=exit_session,
            execution_sessions=tuple(sessions),
            bar_records=bar_records,
        ))
        assert result.conservation_ok_by_arm == {
            "CHAMPION": True, "CHALLENGER": True,
        }

        assert result.settlements_by_arm["CHAMPION"] >= 2  # entry + exit
        # 幂等: 同窗口重放收敛 (append-only + 幂等结算)
        again = advance.advance_market_session(MarketSessionAdvanceRequest(
            trial_id=TRIAL_ID,
            through_session=exit_session,
            execution_sessions=tuple(sessions),
            bar_records=bar_records,
        ))
        assert again.settlements_by_arm == result.settlements_by_arm

    def test_advance_without_authority_rejected(self, worker_world):
        from src.screening.offensive.v3.orchestration.paired_trial import (
            ForwardPairedTrialRunner,
            MarketSessionAdvanceRequest,
            PairedTrialRunnerError,
        )

        runner = ForwardPairedTrialRunner()
        req = MarketSessionAdvanceRequest(
            trial_id=TRIAL_ID, through_session=date(2026, 8, 20)
        )
        with pytest.raises(PairedTrialRunnerError) as ei:
            runner.advance_market_session(req)
        assert ei.value.code == "forward_input_authority_unavailable"


class TestRunnerFinalizeUnlock:
    """R26: finalize_missed_sessions 解锁 — 错过会话 NO_RUN 补记。"""

    def test_finalize_marks_missed_idempotent(self, worker_world, tmp_path):
        from src.screening.offensive.v3.evidence.session_spine import (
            SessionEnrollment,
            SessionSpine,
            SessionStatus,
        )
        from src.screening.offensive.v3.orchestration.paired_trial import (
            ForwardPairedTrialRunner,
        )

        program = "prog-btst-trial"
        spine = SessionSpine(
            database_path=str(worker_world["root"] / "spine.sqlite3"),
            clock=lambda: datetime(2026, 8, 6, 15, 30, tzinfo=UTC),
        )
        # 两个已注册会话: 08-06 (将被 decide) 与 08-13 (将错过)
        spine.enroll_expected_sessions((
            SessionEnrollment(program, SESSION, SESSION),
            SessionEnrollment(program, date(2026, 8, 13), date(2026, 8, 13)),
        ))
        store = TrialArmDecisionStore(
            database_path=str(worker_world["root"] / "decisions.sqlite3")
        )
        store.register_trial(worker_world["bundle"], _registration_genesis())
        runner = ForwardPairedTrialRunner(
            assembler=worker_world["assembler"],
            capital_trial_root=TestRunnerUnlock()._armed_trial_root(tmp_path),
            portfolio_id="pf-btst-trial",
            sizing_config=_config(),
            decision_store=store,
            session_spine=spine,
            research_program_id=program,
        )
        # 两个会话评估窗均已过 (trusted_at 08-20) 且无 pair → 全部补记 (日历序)
        finalized = runner.finalize_missed_sessions(datetime(2026, 8, 20, 15, 0, tzinfo=UTC))
        assert finalized == (SESSION, date(2026, 8, 13))
        assert spine.status(program, SESSION) is SessionStatus.NO_RUN
        assert spine.status(program, date(2026, 8, 13)) is SessionStatus.NO_RUN
        # 幂等: 重复 finalize 不再补记 (终态已存在)
        again = runner.finalize_missed_sessions(datetime(2026, 8, 21, 15, 0, tzinfo=UTC))
        assert again == ()

    def test_finalize_without_authority_rejected(self, worker_world):
        from src.screening.offensive.v3.orchestration.paired_trial import (
            ForwardPairedTrialRunner,
            PairedTrialRunnerError,
        )

        runner = ForwardPairedTrialRunner()
        with pytest.raises(PairedTrialRunnerError) as ei:
            runner.finalize_missed_sessions(datetime(2026, 8, 20, tzinfo=UTC))
        assert ei.value.code == "forward_input_authority_unavailable"


class TestOfficialTrialStack:
    """R27: 官方栈组装器 — 真实身份接线端到端 (tmp 身份目录 + 官方布局)。"""

    def test_build_and_decide_on_official_stack(self, worker_world, tmp_path):
        import json as _json

        from src.screening.offensive.v3.evidence.governance_identity import (
            generate_governance_identity,
        )
        from src.screening.offensive.v3.governance.repository import (
            GovernanceRepository,
        )
        from src.screening.offensive.v3.governance.stage_issuance import (
            GovernanceStageIssuer,
            StageIssuanceRequest,
        )
        from src.screening.offensive.v3.orchestration.official_trial_stack import (
            build_official_trial_stack,
        )
        from src.screening.offensive.v3.orchestration.stage_archive import (
            write_stage_issuance_receipt,
        )

        # ① 真实身份目录 (tmp 生成, 与 R23 生产目录同形态)
        identity_dir = tmp_path / "identity"
        generate_governance_identity(
            identity_dir, namespaces=("regime", "sse-sessions", "btst-bars", "btst"),
            clock=lambda: datetime(2026, 8, 6, 8, 0, tzinfo=UTC),
        )
        # ② trial root: 官方布局 (资本双臂 + 治理封存 + stage 回执归档)
        root = tmp_path / "trial-root"
        from datetime import timezone as _tz

        from src.screening.offensive.v3.capital.flows import GenesisRequest
        from src.screening.offensive.v3.capital.identity import AccountBinding
        from src.screening.offensive.v3.capital.repository import CapitalRepository
        from src.screening.offensive.v3.contracts.base import ExecutionMode
        from src.screening.offensive.v3.orchestration.arm_layout import (
            arm_capital_database_path,
        )
        from src.screening.offensive.v3.orchestration.arm_capital import (
            read_genesis_manifest,
        )
        from src.screening.offensive.v3.orchestration.genesis import (
            TrialArmGenesisSource,
            TrialGenesisArchive,
            restore_genesis_arm,
        )

        _now = datetime(2026, 8, 6, 8, 0, tzinfo=_tz.utc)
        seed = tmp_path / "seed-capital.sqlite3"
        repo = CapitalRepository.initialize(seed)
        repo.initialize_genesis(GenesisRequest(
            idempotency_key="genesis-1",
            account_binding=AccountBinding(
                portfolio_id="pf-trial-regime-001",
                mode=ExecutionMode.DAILY_BAR_PROXY,
                broker_account_id=None, base_currency="CNY",
                environment_fingerprint=None,
            ),
            unit_quanta=10_000, unit_price_numerator=1_000, unit_price_denominator=1,
            source_authority="governance.test", authorization_reference="t-1",
            effective_at=_now, as_of=_now,
        ))
        source = TrialArmGenesisSource(capital_repository=repo)
        manifest = TrialGenesisArchive(root).seal(
            TRIAL_ID, champion_source=source, challenger_source=source
        )
        for arm in ("CHAMPION", "CHALLENGER"):
            target = arm_capital_database_path(root, TrialArm[arm])
            target.parent.mkdir(parents=True, exist_ok=True)
            restore_genesis_arm(manifest, root, target, arm=arm)
        governance = GovernanceRepository(
            database_path=str(root / "governance.sqlite3"),
            clock=lambda: GOV_NOW,
        )
        request, sign, verifier, current_head, caps, bundle = _seal_request()
        from tests.offensive.v3.evidence.test_session_spine import (  # noqa: F401
            _Clock,
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
                stage_sample_reservation_id="smp-1",
                alpha_sample_consumption_id="alpha-1",
                alpha_or_evalue_budget_consumption_id="budget-1",
                attempt_ledger_checkpoint_hash=HASH,
                stage_loss_budget_id="loss-1",
                stage_loss_version=1,
                maximum_loss_budget_cents=1_000_000,
                issuer_id="governance.service",
                issued_at=GOV_NOW,
            )
        )
        write_stage_issuance_receipt(root, receipt)

        # ③ 证据库预置 (官方布局: 三命名空间共库 + bar 库) — 空文件占位即构造;
        # spine 预置真实 enrollment (R32: 组装面校验非空+归属, touch 空文件
        # 不再静默通过)。
        (root / "evidence.sqlite3").touch()
        (root / "bars-evidence.sqlite3").touch()
        (root / "spine.sqlite3").touch()
        from src.screening.offensive.v3.evidence.session_spine import (
            SessionEnrollment,
            SessionSpine,
        )

        SessionSpine(
            database_path=str(root / "spine.sqlite3"), clock=lambda: GOV_NOW
        ).enroll_expected_sessions(
            (
                SessionEnrollment("prog-1", date(2026, 8, 6), date(2026, 8, 6)),
                SessionEnrollment("prog-1", date(2026, 8, 13), date(2026, 8, 13)),
            )
        )

        # ④ 组装官方栈
        from src.screening.offensive.v3.capital.fills import FillAttribution
        from src.screening.offensive.v3.orchestration.arm_lifecycle import (
            CURRENT_COST_SCENARIO,
        )

        stack = build_official_trial_stack(
            identity_dir=identity_dir,
            trial_root=root,
            trial_id=TRIAL_ID,
            sizing_config=_config(),
            clock=lambda: datetime(2026, 8, 6, 15, 30, tzinfo=UTC),
            market_scenario=CURRENT_COST_SCENARIO,
            trial_attribution=FillAttribution(
                producer_namespace="btst", research_program_id="prog-1",
                economic_lineage_id="eline-1", stage_id="stage-1",
            ),
            research_program_id="prog-1",
        )
        assert stack.runner is not None
        assert stack.governance_database().name == "governance.sqlite3"

    def test_missing_evidence_db_fails_closed(self, worker_world, tmp_path):
        from src.screening.offensive.v3.evidence.governance_identity import (
            generate_governance_identity,
        )
        from src.screening.offensive.v3.orchestration.official_trial_stack import (
            OfficialStackError,
            build_official_trial_stack,
        )

        identity_dir = tmp_path / "identity"
        generate_governance_identity(
            identity_dir, namespaces=("regime", "sse-sessions", "btst-bars", "btst"),
            clock=lambda: datetime(2026, 8, 6, 8, 0, tzinfo=UTC),
        )
        root = tmp_path / "empty-root"
        root.mkdir()
        with pytest.raises(OfficialStackError) as ei:
            build_official_trial_stack(
                identity_dir=identity_dir, trial_root=root, trial_id=TRIAL_ID,
                sizing_config=_config(),
                clock=lambda: datetime(2026, 8, 6, 15, 30, tzinfo=UTC),
                market_scenario=object(), trial_attribution=object(),
                research_program_id="prog-1",
            )
        assert ei.value.code == "trial_root_not_initialized"
