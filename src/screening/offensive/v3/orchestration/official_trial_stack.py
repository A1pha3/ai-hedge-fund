"""官方 Trial 运行栈组装器 — 真实治理身份接线 (2026-08-23, R27).

把散落的原语 (治理身份目录 / arm_layout 资本约定 / SessionSpine / 决策库
/ 三入口 runner) 组装成**从磁盘一次构造**的官方运行栈 — runbook 启动顺序
第 2-3 步的落地。此前官方链全部在测试夹具 (ephemeral rig) 上验证; 本层
之后, ephemeral 只在测试/播种, 官方栈的每个签名面都来自持久身份目录。

布局约定 (trial root 单库形态 + arm_layout 唯一权威):

    <trial_root>/
      evidence.sqlite3          # regime/schedule/btst 三命名空间共库
      bars-evidence.sqlite3     # bar-set 证据 (btst-bars 命名空间)
      spine.sqlite3             # SessionSpine (append-only)
      decisions.sqlite3         # TrialArmDecisionStore
      governance.sqlite3        # 治理库 (由封存流程预置, 本层只读路径暴露)
      arms/<champion|challenger>/capital.sqlite3   # arm_layout 约定

诚实边界: 治理库的 trial/seal 由封存流程 (genesis/签发) 预置, 本层不
重签; stage 签发密钥不在当前身份目录 namespace 清单内 (v1 只覆盖证据
发布面) — 身份目录 v2 轮换时补, 此前 stage 回执经归档冷读消费。本层
不解锁任何权限、不连接 broker; 它只是把"官方栈构造"从散件变成一个
可审计的函数。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from src.screening.offensive.v3.evidence.governance_identity import (
    load_governance_identity,
)
from src.screening.offensive.v3.evidence.repository import EvidenceRepository
from src.screening.offensive.v3.evidence.session_spine import SessionSpine
from src.screening.offensive.v3.governance.stage_issuance import (
    StageIssuanceReceipt,
)
from src.screening.offensive.v3.kernel.sizing import SizingConfig
from src.screening.offensive.v3.orchestration.paired_trial import (
    ForwardPairedTrialRunner,
)
from src.screening.offensive.v3.orchestration.trial_store import (
    TrialArmDecisionStore,
)


class OfficialStackError(RuntimeError):
    def __init__(self, code: str, message: str, **details: object) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.details = details


@dataclass(frozen=True)
class OfficialTrialStack:
    """One fully-wired official trial runtime over the persistent identity."""

    identity_dir: Path
    trial_root: Path
    trial_id: str
    stage_receipt: StageIssuanceReceipt
    regime_repository: EvidenceRepository
    schedule_repository: EvidenceRepository
    btst_repository: EvidenceRepository
    bars_repository: EvidenceRepository
    spine: SessionSpine
    decision_store: TrialArmDecisionStore
    runner: ForwardPairedTrialRunner

    def governance_database(self) -> Path:
        return self.trial_root / "governance.sqlite3"


def build_official_trial_stack(
    *,
    identity_dir: Path,
    trial_root: Path,
    trial_id: str,
    sizing_config: SizingConfig,
    clock: Callable[[], datetime],
    market_scenario: object,
    trial_attribution: object,
    research_program_id: str,
    stage_id: str | None = None,
) -> OfficialTrialStack:
    """从身份目录 + trial root 一次构造官方栈 (全部真实身份签名面)。

    前置: 身份目录已经 ``generate`` 且 ``check`` 通过; trial root 下
    genesis/治理封存已由各自流程预置 (缺库 fail-closed 由 arm_layout
    读面强制)。资本/治理的写入流程 (seal/restore/签发) 不在本层 —
    本层是运行栈的读侧组装。

    stage 选择 (R28): 消费哪个 stage 是治理事实。显式 ``stage_id``
    精确选择; 缺省时全量严格冷读按 receipt 的权威签发时刻
    ``issued_at`` 取最新 — 文件名字典序不是治理事实 (stage_id 无
    命名约束), 任何一个回执损坏都 fail-closed, 同 ``issued_at``
    双签是治理异常 (歧义拒绝)。
    """
    from src.screening.offensive.v3 import trust as v3trust
    from src.screening.offensive.v3.orchestration.arm_layout import (
        open_arm_capital_repository,
    )

    root = Path(trial_root).resolve()
    identity_dir = Path(identity_dir)
    now = clock()
    identity = load_governance_identity(identity_dir, trusted_at=now)
    head = v3trust.CurrentTrustHeadWitness.model_validate_json(
        __import__("json").dumps(identity.manifest["head_witness"])
    )

    evidence_db = root / "evidence.sqlite3"
    bars_db = root / "bars-evidence.sqlite3"
    blobs = root / "blobs"
    missing = [
        str(p.relative_to(root))
        for p in (evidence_db, bars_db)
        if not p.is_file()
    ]
    if missing:
        raise OfficialStackError(
            "trial_root_not_initialized",
            "the trial root lacks pre-initialized evidence databases"
            " (seeding/genesis flows must run first)",
            missing=missing,
        )

    def repo(namespace: str, database: Path) -> EvidenceRepository:
        return identity.repository_for(
            namespace=namespace,
            database_path=str(database),
            blobs_dir=blobs,
            clock=clock,
            trust_head=head,
        )

    spine = SessionSpine(database_path=str(root / "spine.sqlite3"), clock=clock)
    store = TrialArmDecisionStore(database_path=str(root / "decisions.sqlite3"))
    # 资本约定路径在构造期即校验 (缺库 fail-closed 提前到组装面)
    from src.screening.offensive.v3.contracts.trial import TrialArm

    for arm in (TrialArm.CHAMPION, TrialArm.CHALLENGER):
        open_arm_capital_repository(root, arm)

    from src.screening.offensive.v3.orchestration.privileged_worker import (
        ForwardSessionAssembler,
    )
    from src.screening.offensive.v3.governance.repository import (
        GovernanceRepository,
    )

    governance = GovernanceRepository(
        database_path=str(root / "governance.sqlite3"), clock=clock
    )
    from src.screening.offensive.v3.governance.stage_issuance import (
        StageIssuanceReceipt,
    )

    receipt = _latest_stage_receipt(root, trial_id, stage_id)
    assembler = ForwardSessionAssembler(
        sealer=_build_sealer(root, identity, clock),
        governance=governance,
        trial_id=trial_id,
        stage_receipt=receipt,
        regime_repository=repo("regime", evidence_db),
        schedule_repository=repo("sse-sessions", evidence_db),
        btst_repository=repo("btst", evidence_db),
    )
    runner = ForwardPairedTrialRunner(
        assembler=assembler,
        capital_trial_root=root,
        portfolio_id=_portfolio_id_for(trial_id),
        sizing_config=sizing_config,
        decision_store=store,
        bar_repository=repo("btst-bars", bars_db),
        market_scenario=market_scenario,
        trial_attribution=trial_attribution,
        session_spine=spine,
        research_program_id=research_program_id,
    )
    return OfficialTrialStack(
        identity_dir=identity_dir,
        trial_root=root,
        trial_id=trial_id,
        stage_receipt=receipt,
        regime_repository=repo("regime", evidence_db),
        schedule_repository=repo("sse-sessions", evidence_db),
        btst_repository=repo("btst", evidence_db),
        bars_repository=repo("btst-bars", bars_db),
        spine=spine,
        decision_store=store,
        runner=runner,
    )


def _portfolio_id_for(trial_id: str) -> str:
    return f"pf-{trial_id}"


def _latest_stage_receipt(root: Path, trial_id: str, stage_id: str | None) -> object:
    """Stage 签发回执选择 (R28 修复): 治理事实决定, 不由文件名决定。

    - 显式 ``stage_id``: 单段形状校验 (穿越/绝对注入到不了 lstat) 后
      精确路径冷读 (确定性最强的审计路径);
    - 缺省: 归档中全部回执严格冷读 — 任何一个损坏即 fail-closed
      (预置文件不能靠字典序静默出局操纵选择面) — 按 receipt 权威
      签发时刻 ``issued_at`` (签发行为身份的一部分, P2-c) 取最新;
    - 同 ``issued_at`` 不同 stage_id: 治理异常, ``stage_selection_ambiguous``。

    identity v1 无 stage 签发 key, 回执由签发流程归档、本层不重签。
    """
    from src.screening.offensive.v3.orchestration.stage_archive import (
        StageArchiveError,
        read_stage_issuance_receipt,
    )

    archive = root / "archive" / "stage-issuance" / trial_id
    if stage_id is not None:
        # 单段形状校验先于拼路径 (对抗审查 R28: stage_id 直拼会让
        # ``../`` 穿越归档读外部文件 — 与 stage_receipt_path 同款纪律)。
        from src.screening.offensive.v3.orchestration.path_guards import (
            require_safe_segment,
        )

        safe_stage_id = require_safe_segment(
            stage_id, field="stage_id", fail=OfficialStackError
        )
        target = archive / f"{safe_stage_id}.json"
        try:
            return read_stage_issuance_receipt(target)
        except StageArchiveError as exc:
            if exc.code == "archive_artifact_missing":
                raise OfficialStackError(
                    "stage_receipt_missing",
                    "the requested archived stage issuance receipt does not"
                    " exist (issuance flow must run first; identity v1 has"
                    " no stage signing key — receipts are consumed from"
                    " the archive)",
                    stage_id=stage_id,
                ) from exc
            raise OfficialStackError(
                "stage_receipt_corrupt",
                "the requested archived stage issuance receipt failed"
                " strict cold-read",
                stage_id=stage_id,
            ) from exc
    receipts = sorted(archive.glob("*.json")) if archive.is_dir() else []
    if not receipts:
        raise OfficialStackError(
            "stage_receipt_missing",
            "no archived stage issuance receipt for this trial"
            " (issuance flow must run first; identity v1 has no stage"
            " signing key — receipts are consumed from the archive)",
            archive=str(archive),
        )
    parsed: list[StageIssuanceReceipt] = []
    for path in receipts:
        try:
            parsed.append(read_stage_issuance_receipt(path))
        except StageArchiveError as exc:
            raise OfficialStackError(
                "stage_receipt_corrupt",
                "an archived stage receipt failed strict cold-read;"
                " a corrupt artifact must not silently drop out of the"
                " selection set",
                path=str(path),
            ) from exc
    latest_at = max(receipt.issued_at for receipt in parsed)
    candidates = sorted(
        receipt.stage_id for receipt in parsed if receipt.issued_at == latest_at
    )
    if len(candidates) > 1:
        raise OfficialStackError(
            "stage_selection_ambiguous",
            "multiple distinct stages share the same issuance instant;"
            " issuance identity includes the instant — an explicit"
            " stage_id is required to consume this archive",
            issued_at=latest_at.isoformat(),
            stage_ids=candidates,
        )
    for receipt in parsed:
        if receipt.stage_id == candidates[0]:
            return receipt
    raise OfficialStackError(  # pragma: no cover — candidates 来自 parsed
        "stage_receipt_corrupt",
        "selected stage receipt vanished between parse and select",
    )


def _build_sealer(root: Path, identity, clock) -> object:
    """SessionBatchSealer over 真实身份的三个命名空间仓库句柄。"""
    from src.screening.offensive.v3.evidence.session_batch import (
        BTST_NAMESPACE,
        REGIME_NAMESPACE,
        SCHEDULE_NAMESPACE,
        SessionBatchSealer,
    )
    import json as _json

    from src.screening.offensive.v3 import trust as v3trust

    head = v3trust.CurrentTrustHeadWitness.model_validate_json(
        _json.dumps(identity.manifest["head_witness"])
    )
    evidence_db = root / "evidence.sqlite3"
    blobs = root / "blobs"

    def repo(namespace: str) -> EvidenceRepository:
        return identity.repository_for(
            namespace=namespace,
            database_path=str(evidence_db),
            blobs_dir=blobs,
            clock=clock,
            trust_head=head,
        )

    return SessionBatchSealer(
        database_path=str(evidence_db),
        repositories={
            REGIME_NAMESPACE: repo(REGIME_NAMESPACE),
            SCHEDULE_NAMESPACE: repo(SCHEDULE_NAMESPACE),
            BTST_NAMESPACE: repo(BTST_NAMESPACE),
        },
        clock=clock,
    )


__all__ = [
    "OfficialStackError",
    "OfficialTrialStack",
    "build_official_trial_stack",
]
