"""Store-owned decision-session batch authority — 特权 worker primitive (2026-08-20).

二轮审查 P1 精修的三段式背书模型, store 侧落地: 特权 worker **声明**消费集
→ 本封存器经各命名空间仓库的 public ``active_revision`` 逐成员背书
(cutoff 正确的 active 修订 + artifact hash) → 背书集上用唯一 merkle 实现
(``evidence_set_merkle_root``) 计算**根**。根不再由调用方拼装哈希, 而由
store 已提交真相派生; 候选集 (规则的可变部分) 另做**完备性校验** — btst
命名空间内该会话全部 SELECTED 信号证据必须恰被声明, 多出即冲突。

成员规则 v2 (预注册成文 — worker 落地前不许静默改, 改即新 rule_version):
一次 BTST 配对 Trial 决策会话的证据集 = ``regime:csi300:1.0`` (固定) +
该信号会话的排程证据 (worker 声明, 单条; **v2 起同会话全部排程证据必须
恰被声明, 多出即冲突 — 与候选完备性对称**; 会话归属由绑定 blob 严格解码
的 ``signal_session`` 权威判定, 不解析 evidence_id 词法) + 该会话全部
SELECTED btst 候选 (完备性强制)。bar-set 证据**不在**决策批内 (执行层,
cutoff 后才存在)。v1 历史: 排程完备性缺位 — worker 可在同会话多条排程
证据间选择性声明 (v1 落地时登记为 "升级规则版本时补", 2026-08-21 v2 收口)。

封存表 ``session_batch_seals`` 与证据时间轴同库 (单 sqlite), append-only
(UPDATE/DELETE 触发器拒绝), (session, rule_version) 唯一键, 恰等重放幂等、
背离冲突。offline primitive: 不解锁 runner fail-closed、不构成权限。
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Mapping
from datetime import date, datetime
from typing import ClassVar, Self

from pydantic import ValidationError, model_validator

from src.screening.offensive.v3.contracts import CanonicalModel, Sha256
from src.screening.offensive.v3.contracts.base import SignalStage, UtcInstant
from src.screening.offensive.v3.contracts.evidence import SignalEvidence, SnapshotEvidence
from src.screening.offensive.v3.evidence.merkle import evidence_set_merkle_root
from src.screening.offensive.v3.evidence.repository import EvidenceRepository, EvidenceStoreError
from src.screening.offensive.v3.evidence.trading_schedule import SCHEDULE_PRODUCER
from src.screening.offensive.v3.kernel.models import FrozenTradingSessionSchedule
from src.screening.offensive.v3.orchestration.paired_trial import REGIME_EVIDENCE_ID

#: 预注册成员规则版本 (成员集合构成变化 = 新版本, 不许原地改)
DECISION_BATCH_RULE_VERSION: str = "btst-decision.v2"
REGIME_NAMESPACE: str = "regime"
SCHEDULE_NAMESPACE: str = SCHEDULE_PRODUCER
BTST_NAMESPACE: str = "btst"

_SEAL_DDL: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS session_batch_seals (
        session TEXT NOT NULL,
        rule_version TEXT NOT NULL,
        authority_json TEXT NOT NULL,
        sealed_at TEXT NOT NULL,
        PRIMARY KEY (session, rule_version)
    )
    """,
    "CREATE TRIGGER IF NOT EXISTS no_update_session_batch_seals "
    "BEFORE UPDATE ON session_batch_seals "
    "BEGIN SELECT RAISE(ABORT, 'immutable table: session_batch_seals rejects "
    "UPDATE'); END;",
    "CREATE TRIGGER IF NOT EXISTS no_delete_session_batch_seals "
    "BEFORE DELETE ON session_batch_seals "
    "BEGIN SELECT RAISE(ABORT, 'immutable table: session_batch_seals rejects "
    "DELETE'); END;",
)


class SessionBatchError(RuntimeError):
    def __init__(self, code: str, message: str, **details: object) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.details = details


class BatchBinding(CanonicalModel):
    """One attested evidence member: namespace-scoped id + artifact hash."""

    HASH_DOMAIN: ClassVar[str] = "ai-hedge-fund.v3.evidence.batch-binding.v1"

    issuer_namespace: str
    evidence_id: str
    artifact_hash: Sha256


class SessionBatchAuthority(CanonicalModel):
    """Store-sealed batch authority: 成员背书 + 根 + 水位, 自验证模型。

    校验器从 bindings 本身复算 merkle 根 — 篡改任一 artifact hash 或根
    在构造/解析时即拒; 根的完整语义 (成员恰为决策消费集) 由封存器的
    完备性校验与 ``verify_decision_batch`` 的全量重推导保证。
    """

    HASH_DOMAIN: ClassVar[str] = (
        "ai-hedge-fund.v3.evidence.session-batch-authority.v1"
    )

    session: date
    rule_version: str
    trusted_evidence_cutoff: UtcInstant
    bindings: tuple[BatchBinding, ...]
    evidence_set_merkle_root: Sha256
    commit_sequence_watermark: int
    sealed_at: UtcInstant

    @model_validator(mode="after")
    def validate_authority(self) -> Self:
        if not self.bindings:
            raise ValueError("a decision batch cannot be empty")
        keys = [(b.issuer_namespace, b.evidence_id) for b in self.bindings]
        if keys != sorted(set(keys)):
            raise ValueError("bindings must be unique and canonically sorted")
        if any(b.artifact_hash == "0" * 64 for b in self.bindings):
            raise ValueError("artifact hash cannot use the zero sentinel")
        recomputed = evidence_set_merkle_root(
            (b.evidence_id, b.artifact_hash) for b in self.bindings
        )
        if recomputed != self.evidence_set_merkle_root:
            raise ValueError("merkle root does not bind the attested bindings")
        if self.commit_sequence_watermark < 1:
            raise ValueError("commit sequence watermark must be positive")
        return self


class SessionBatchSealer:
    """Seal (and re-verify) the decision batch of one signal session."""

    def __init__(
        self,
        *,
        database_path: str,
        repositories: Mapping[str, EvidenceRepository],
        clock: Callable[[], datetime],
    ) -> None:
        missing = {REGIME_NAMESPACE, SCHEDULE_NAMESPACE, BTST_NAMESPACE} - set(repositories)
        if missing:
            raise SessionBatchError(
                "namespace_repository_missing",
                "the sealer needs one repository handle per rule namespace",
                missing=sorted(missing),
            )
        self._database_path = database_path
        self._repositories = dict(repositories)
        self._clock = clock
        with sqlite3.connect(self._database_path) as conn:
            conn.execute("PRAGMA busy_timeout=15000")
            for ddl in _SEAL_DDL:
                conn.execute(ddl)
            conn.commit()

    # -- seal ----------------------------------------------------------------

    def seal_decision_batch(
        self,
        *,
        session: date,
        cutoff: datetime,
        schedule_evidence_id: str,
        candidate_evidence_ids: tuple[str, ...] = (),
    ) -> SessionBatchAuthority:
        """Attest the declared set store-side; completeness-enforced for btst.

        恰等重放幂等 (同 session+rule 已封存且 authority 字节相同 → 原样
        返回); 背离 (同键不同内容) 是类型化冲突, 整个事务回滚。
        """
        authority = self._derive_authority(
            session=session,
            cutoff=cutoff,
            schedule_evidence_id=schedule_evidence_id,
            candidate_evidence_ids=candidate_evidence_ids,
        )
        sealed_json = authority.model_dump_json()
        with sqlite3.connect(self._database_path) as conn:
            conn.execute("PRAGMA busy_timeout=15000")
            conn.execute("BEGIN IMMEDIATE")
            try:
                existing = conn.execute(
                    "SELECT authority_json FROM session_batch_seals"
                    " WHERE session = ? AND rule_version = ?",
                    (session.isoformat(), DECISION_BATCH_RULE_VERSION),
                ).fetchone()
                if existing is not None:
                    if str(existing[0]) != sealed_json:
                        raise SessionBatchError(
                            "batch_seal_conflict",
                            "this session already sealed a different batch;"
                            " the replay rolled back",
                            session=session.isoformat(),
                        )
                    return authority  # 恰等重放幂等
                conn.execute(
                    "INSERT INTO session_batch_seals (session, rule_version,"
                    " authority_json, sealed_at) VALUES (?, ?, ?, ?)",
                    (
                        session.isoformat(),
                        DECISION_BATCH_RULE_VERSION,
                        sealed_json,
                        authority.sealed_at.isoformat(),
                    ),
                )
                conn.commit()
            except BaseException:
                conn.rollback()
                raise
        return authority

    def _derive_authority(
        self,
        *,
        session: date,
        cutoff: datetime,
        schedule_evidence_id: str,
        candidate_evidence_ids: tuple[str, ...],
    ) -> SessionBatchAuthority:
        """Store-side derivation only — no persistence (verify 复用, 零写入)."""
        bindings: list[BatchBinding] = [
            self._regime_binding(cutoff),
            self._resolve(SCHEDULE_NAMESPACE, schedule_evidence_id, cutoff),
        ]
        declared = set(candidate_evidence_ids)
        if len(declared) != len(candidate_evidence_ids):
            raise SessionBatchError(
                "candidate_declared_twice",
                "the declared candidate set contains a duplicate id",
            )
        for evidence_id in candidate_evidence_ids:
            bindings.append(self._candidate_binding(evidence_id, session, cutoff))
        self._enforce_schedule_completeness(session, cutoff, schedule_evidence_id)
        self._enforce_candidate_completeness(session, cutoff, declared)
        bindings.sort(key=lambda b: (b.issuer_namespace, b.evidence_id))
        return SessionBatchAuthority(
            session=session,
            rule_version=DECISION_BATCH_RULE_VERSION,
            trusted_evidence_cutoff=cutoff,
            bindings=tuple(bindings),
            evidence_set_merkle_root=evidence_set_merkle_root(
                (b.evidence_id, b.artifact_hash) for b in bindings
            ),
            commit_sequence_watermark=self._repositories[
                REGIME_NAMESPACE
            ].commit_sequence(),
            sealed_at=self._clock(),
        )

    def sealed_batch(
        self, session: date, rule_version: str = DECISION_BATCH_RULE_VERSION
    ) -> SessionBatchAuthority:
        """Read one previously sealed batch authority back (worker/audit face).

        Phase A 审查 P2-3: 封存事实此前只能"重推导验证", 不能读回证明
        "曾封存过且封存的是什么" — 幂等重放/审计需要此读面。
        """
        with sqlite3.connect(self._database_path) as conn:
            row = conn.execute(
                "SELECT authority_json FROM session_batch_seals"
                " WHERE session = ? AND rule_version = ?",
                (session.isoformat(), rule_version),
            ).fetchone()
        if row is None:
            raise SessionBatchError(
                "batch_seal_unknown",
                "no sealed batch for this session/rule",
                session=session.isoformat(),
                rule_version=rule_version,
            )
        try:
            return SessionBatchAuthority.model_validate_json(
                str(row[0]), strict=True
            )
        except ValidationError as exc:
            raise SessionBatchError(
                "batch_seal_corrupt",
                "sealed batch authority failed strict revalidation",
                session=session.isoformat(),
                rule_version=rule_version,
            ) from exc

    def verify_decision_batch(self, authority: SessionBatchAuthority) -> None:
        """Re-derive the whole authority from store truth; mismatch fails.

        纯读零写入。证据时间轴 append-only + 修订链使 cutoff 正确的重推导
        稳定: cutoff 后新发布/激活的修订对 ``active_revision`` 不可见。
        """
        schedule_ids = [
            b.evidence_id
            for b in authority.bindings
            if b.issuer_namespace == SCHEDULE_NAMESPACE
        ]
        candidate_ids = tuple(
            sorted(
                b.evidence_id
                for b in authority.bindings
                if b.issuer_namespace == BTST_NAMESPACE
            )
        )
        if len(schedule_ids) != 1:
            raise SessionBatchError(
                "authority_shape_invalid",
                "the decision-batch rule requires exactly one schedule binding",
            )
        if authority.rule_version != DECISION_BATCH_RULE_VERSION:
            raise SessionBatchError(
                "rule_version_unknown",
                "this sealer only verifies the registered rule version",
                expected=DECISION_BATCH_RULE_VERSION,
                got=authority.rule_version,
            )
        recomputed = self._derive_authority(
            session=authority.session,
            cutoff=authority.trusted_evidence_cutoff,
            schedule_evidence_id=schedule_ids[0],
            candidate_evidence_ids=candidate_ids,
        )
        # sealed_at 是封存时刻 (重推导读当前钟), 幂等重放比较除它以外的全部字段
        if (
            recomputed.model_dump(exclude={"sealed_at"})
            != authority.model_dump(exclude={"sealed_at"})
        ):
            raise SessionBatchError(
                "batch_authority_mismatch",
                "store truth no longer reproduces the sealed authority",
                session=authority.session.isoformat(),
            )

    # -- members ---------------------------------------------------------------

    def _regime_binding(self, cutoff: datetime) -> BatchBinding:
        return self._resolve(REGIME_NAMESPACE, REGIME_EVIDENCE_ID, cutoff)

    def _resolve(
        self, namespace: str, evidence_id: str, cutoff: datetime
    ) -> BatchBinding:
        record = self._repositories[namespace].active_revision(evidence_id, cutoff)
        return BatchBinding(
            issuer_namespace=namespace,
            evidence_id=evidence_id,
            artifact_hash=record.artifact_hash(),
        )

    def _candidate_binding(
        self, evidence_id: str, session: date, cutoff: datetime
    ) -> BatchBinding:
        record = self._repositories[BTST_NAMESPACE].active_revision(evidence_id, cutoff)
        envelope = record.evidence
        if not isinstance(envelope, SignalEvidence):
            raise SessionBatchError(
                "candidate_kind_mismatch",
                "a declared candidate must carry SignalEvidence",
                evidence_id=evidence_id,
            )
        if envelope.stage is not SignalStage.SELECTED:
            raise SessionBatchError(
                "candidate_stage_mismatch",
                "a declared candidate must be SELECTED",
                evidence_id=evidence_id,
                stage=envelope.stage.value,
            )
        if envelope.effective_at.date() != session:
            raise SessionBatchError(
                "candidate_session_mismatch",
                "a declared candidate belongs to another signal session",
                evidence_id=evidence_id,
                candidate_session=envelope.effective_at.date().isoformat(),
            )
        return BatchBinding(
            issuer_namespace=BTST_NAMESPACE,
            evidence_id=evidence_id,
            artifact_hash=record.artifact_hash(),
        )

    def _enforce_schedule_completeness(
        self, session: date, cutoff: datetime, declared_id: str
    ) -> None:
        """排程命名空间内该会话的排程证据必须恰被声明 (v2 补强, 镜像候选侧)。

        会话归属的唯一权威是绑定 blob 严格解码出的 ``signal_session`` —
        与 ``schedule_from_record`` 复核面同源, 不做 evidence_id 词法解析
        (id 格式演化不改变完备性语义)。
        """
        for evidence_id in self._repositories[SCHEDULE_NAMESPACE].evidence_ids_by_kind(
            "snapshot"
        ):
            if evidence_id == declared_id:
                continue
            try:
                record = self._repositories[SCHEDULE_NAMESPACE].active_revision(
                    evidence_id, cutoff
                )
            except EvidenceStoreError as exc:
                # 只吞"cutoff 前未提交"= 该 id 是批外证据; 其余仓库错误必须
                # propagate (与候选完备性同款 P2-1 纪律: 宽吞会假装没看到坏记录).
                if exc.code != "evidence_not_committed_before_cutoff":
                    raise
                continue
            envelope = record.evidence
            if not isinstance(envelope, SnapshotEvidence):
                raise SessionBatchError(
                    "schedule_namespace_polluted",
                    "a snapshot-kind envelope in the schedule namespace is not"
                    " a SnapshotEvidence",
                    evidence_id=evidence_id,
                )
            schedule = self._decode_schedule(evidence_id, envelope)
            if schedule.signal_session == session:
                raise SessionBatchError(
                    "schedule_completeness_violation",
                    "an undeclared trading schedule exists for this session",
                    evidence_id=evidence_id,
                    session=session.isoformat(),
                )

    def _decode_schedule(
        self, evidence_id: str, envelope: SnapshotEvidence
    ) -> FrozenTradingSessionSchedule:
        """Strict decode of the bound blob; 命名空间污染 fail-closed。"""
        blob = self._repositories[SCHEDULE_NAMESPACE].raw_payload(
            envelope.payload_content_hash
        )
        try:
            return FrozenTradingSessionSchedule.model_validate_json(blob, strict=True)
        except Exception as exc:  # noqa: BLE001 - decode failure is fail-closed
            raise SessionBatchError(
                "schedule_decode_failed",
                "a snapshot in the schedule namespace does not decode into a"
                " strict FrozenTradingSessionSchedule",
                evidence_id=evidence_id,
            ) from exc

    def _enforce_candidate_completeness(
        self, session: date, cutoff: datetime, declared: set[str]
    ) -> None:
        """btst 命名空间内该会话全部 SELECTED 证据必须恰被声明。"""
        for evidence_id in self._repositories[BTST_NAMESPACE].evidence_ids_by_kind(
            "signal"
        ):
            if evidence_id in declared:
                continue
            try:
                record = self._repositories[BTST_NAMESPACE].active_revision(
                    evidence_id, cutoff
                )
            except EvidenceStoreError as exc:
                # 只吞"cutoff 前未提交"= 该 id 是批外证据; 其余异常必须
                # propagate (Phase A 审查 P2-1: 宽吞会假装"没看到"坏记录).
                if exc.code != "evidence_not_committed_before_cutoff":
                    raise
                continue
            envelope = record.evidence
            if (
                isinstance(envelope, SignalEvidence)
                and envelope.stage is SignalStage.SELECTED
                and envelope.effective_at.date() == session
            ):
                raise SessionBatchError(
                    "batch_completeness_violation",
                    "an undeclared SELECTED candidate exists for this session",
                    evidence_id=evidence_id,
                    session=session.isoformat(),
                )


__all__ = [
    "BTST_NAMESPACE",
    "BatchBinding",
    "DECISION_BATCH_RULE_VERSION",
    "REGIME_EVIDENCE_ID",
    "REGIME_NAMESPACE",
    "SCHEDULE_NAMESPACE",
    "SessionBatchAuthority",
    "SessionBatchError",
    "SessionBatchSealer",
]
