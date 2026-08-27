"""Official forward-trial daily session driver (R36, offline primitive).

组合面: 把真实日度管道产物 (verified snapshot + 权威日历) 驱入官方栈的三个
runner 入口。runner 三入口 (decide/advance/finalize) 与 R27 官方栈组装器已
解锁, 但此前不存在任何把「readiness manifest → VerifiedDailyActionSnapshot →
证据发布 → decide → bar 证据 → advance → 错过补记」连成一体的日度操作面——
官方前向 Trial 因此零会话证据积累。本模块补齐该断层。

本层是排程与派生, 不是权限: 证据发布走注入身份的签名面, decide/advance/
finalize 由注入官方栈的 runner 执行, 驱动器自身不产生任何 authority。

``trusted_evidence_cutoff`` 的确定性: cutoff = 本会话决策批全部成员
(regime/排程/候选) ``available_at`` 的最大值。首次发布即冻结该水位; 重放时
从既有记录重导出同一水位——同键 pair 重放因此逐字节恰等 (``commit_pair``
的幂等语义), 推进时钟不会制造内容分歧。

宪法时序派生 (非配置): DeadlineContract 全部从排程切片派生
    close_finalized (T0 15:00) < seal_creation (16:00) < permit_issue (16:30)
    < permit_expires == gateway_send (T+1 09:25) < broker_cutoff (T+1 09:30)
T+1/T+10 执行窗口的唯一权威是排程切片 (``FrozenTradingSessionSchedule``)。

幂等纪律: 全部发布先查存在再写 (恰等复用; 内容分歧类型化拒绝, 绝不覆盖),
partial 发布状态 fail-closed。
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

from src.screening.offensive.v3.contracts.base import SignalStage
from src.screening.offensive.v3.contracts.regime import (
    RegimeObservation,
    RegimeObservationReason,
    RegimeSourceRevision,
    normalize_regime_state,
)
from src.screening.offensive.v3.evidence.blob_store import BlobStore
from src.screening.offensive.v3.evidence.market_bars import MarketBarSetPublisher
from src.screening.offensive.v3.evidence.regime import (
    RegimeObservationPublisher,
    RegimeObservationReader,
)
from src.screening.offensive.v3.evidence.repository import (
    EvidenceRepository,
    EvidenceStoreError,
)
from src.screening.offensive.v3.evidence.session_batch import (
    SCHEDULE_NAMESPACE,
    committed_selected_candidate_ids,
)
from src.screening.offensive.v3.evidence.trading_schedule import (
    TradingSchedulePublisher,
    build_schedule_envelope,
    derive_trading_schedule,
    load_authoritative_dates,
    schedule_from_record,
)
from src.screening.offensive.v3.kernel.models import DeadlineContract
from src.screening.offensive.v3.orchestration.paired_trial import (
    REGIME_EVIDENCE_ID,
    MarketAdvanceReceipt,
    MarketSessionAdvanceRequest,
    PairedSignalReceipt,
    SignalSessionRequest,
)

UTC = timezone.utc

#: 宪法 #10 时序常量 (信号日 UTC 表达, 与特权 worker 测试约定逐字一致)。
_CLOSE_FINALIZED = time(15, 0)
_SEAL_CREATION = time(16, 0)
_PERMIT_ISSUE = time(16, 30)
_GATEWAY_SEND = time(9, 25)
_BROKER_CUTOFF = time(9, 30)

#: 发布结算间隔: store 的 active 过滤是 ``activated_at < cutoff`` (严格小于,
#: 官方 OOS 纪律), 因此 cutoff 必须严格晚于全部成员激活时刻。固定 1 秒
#: 常量保证重放时 cutoff 重导出逐字节一致 (水位来自信封 available_at,
#: 不依赖推进的墙钟)。
_PUBLICATION_SETTLE = timedelta(seconds=1)

_REGIME_FINGERPRINT_PREFIX = "sha256:"
_HEX = frozenset("0123456789abcdef")

#: 驱动器 regime 观察的确定性 classifier 身份 (v2 生产 regime gate 的镜像面)。
#: 同一固定 evidence id 的全部修订必须共享该信封绑定字段 (store 修正链的
#: lineage 校验); 单一定义避免发布方各自造常量造成链断裂 (官方栈的播种
#: helper 与本驱动器共享此常量)。
REGIME_CLASSIFIER_FINGERPRINT: str = hashlib.sha256(
    b"ai-hedge-fund.v3.trial-session-driver.regime-v2-gate.v1"
).hexdigest()


class TrialSessionDriverError(RuntimeError):
    """Fail-closed rejection of one driver step (typed code + details)."""

    def __init__(self, code: str, message: str, **details: object) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.details = details


def _instant(session: date, at: time) -> datetime:
    return datetime.combine(session, at, tzinfo=UTC)


def _store_code(exc: Exception) -> str:
    return str(exc).partition(":")[0]


@dataclass(frozen=True)
class SessionEvidencePublication:
    """The driver's publication outcome for one signal session.

    ``trusted_evidence_cutoff`` 是成员 available_at 水位——首发布冻结、重放
    重导出, 保证 pair 重放逐字节一致。
    """

    signal_session: date
    schedule_evidence_id: str
    selected_candidate_evidence_ids: tuple[str, ...]
    trusted_evidence_cutoff: datetime


class _SnapshotSignerPort:
    """Adapts the identity signer to the regime publisher's port."""

    def __init__(self, signer: Callable[[bytes], object]) -> None:
        self._signer = signer

    def sign_snapshot(self, snapshot: object, payload: bytes) -> object:
        del snapshot
        return self._signer(payload)


class _StaticTrustHead:
    """Yields one frozen trust head witness (mirrors identity.repository_for)."""

    def __init__(self, head: object) -> None:
        self._head = head

    def current_trust_head(self, trusted_at: datetime) -> object:
        del trusted_at
        return self._head


class OfficialTrialSessionDriver:
    """Drives the official stack's three runner entries from daily artifacts.

    构造期只读装配签名面/发布器; 三个入口各自的写入全部经存在性检查后走
    store 的 insert-or-verify-exact。不持有任何 activation/permit/envelope
    写面——那些属于 Governance 与 Capital Gateway, 本层零接触。
    """

    def __init__(
        self,
        *,
        stack: object,
        identity: object,
        calendar_path: Path | str,
        clock: Callable[[], datetime],
    ) -> None:
        import json as _json

        from src.screening.offensive.v3 import trust as v3_trust
        from src.screening.offensive.v3.services.btst_producer_api import (
            BtstProducerApi,
        )

        self._stack = stack
        self._identity = identity
        self._calendar_path = Path(calendar_path)
        self._clock = clock

        head = v3_trust.CurrentTrustHeadWitness.model_validate_json(
            _json.dumps(identity.manifest["head_witness"])
        )
        evidence_db = stack.trial_root / "evidence.sqlite3"

        self._regime_publisher = RegimeObservationPublisher(stack.regime_repository)
        self._regime_signer = _SnapshotSignerPort(identity.signer_for("regime"))
        self._regime_reader = RegimeObservationReader(stack.regime_repository)

        self._schedule_publisher = TradingSchedulePublisher(
            repository=stack.schedule_repository,
            clock=clock,
            signer=identity.signer_for(SCHEDULE_NAMESPACE),
        )

        self._producer = BtstProducerApi(
            database_path=str(evidence_db),
            blob_store=BlobStore(stack.trial_root / "blobs"),
            verifier=identity.verifier,
            trust_head_provider=_StaticTrustHead(head),
            clock=clock,
            signer=identity.signer_for("btst"),
        )

        self._bars_publisher = MarketBarSetPublisher(
            repository=stack.bars_repository,
            clock=clock,
            signer=identity.signer_for("btst-bars"),
        )

    # ------------------------------------------------------------------
    # Public entries
    # ------------------------------------------------------------------

    def decide_session(
        self,
        *,
        snapshot: object,
        signal_session: date,
        now: datetime | None = None,
    ) -> PairedSignalReceipt:
        """Publish (or reuse) the session evidence, then run the pair decision.

        重放幂等: 成员存在即复用 → cutoff 水位重导出不变 → 请求逐字段一致 →
        ``commit_pair`` 同键恰等收敛。
        """
        published_at = self._clock() if now is None else now
        publication = self.publish_session_evidence(
            snapshot=snapshot, signal_session=signal_session, now=published_at
        )
        schedule = self._derive_schedule(
            signal_session, available_at=publication.trusted_evidence_cutoff
        )
        return self._stack.runner.decide_signal_session(
            SignalSessionRequest(
                trial_id=self._stack.trial_id,
                signal_session=signal_session,
                decision_cycle_id=f"daily-action-{signal_session:%Y%m%d}",
                trusted_evidence_cutoff=publication.trusted_evidence_cutoff,
                trusted_at=publication.trusted_evidence_cutoff,
                schedule_evidence_id=publication.schedule_evidence_id,
                candidate_evidence_ids=publication.selected_candidate_evidence_ids,
                deadlines=self.deadline_contract(schedule),
            )
        )

    def publish_session_evidence(
        self,
        *,
        snapshot: object,
        signal_session: date,
        now: datetime | None = None,
    ) -> SessionEvidencePublication:
        """Publish regime revision + schedule slice + candidates for one session.

        全部成员的 available_at 构成 cutoff 水位; 已存在成员原样复用 (其
        available_at 计入水位), 内容分歧类型化拒绝。
        """
        published_at = self._clock() if now is None else now
        if snapshot.signal_date != signal_session:
            raise TrialSessionDriverError(
                "snapshot_session_mismatch",
                "the verified snapshot was not taken on the signal session",
                snapshot_session=str(snapshot.signal_date),
                signal_session=signal_session.isoformat(),
            )
        # 排程可导出性先行 (fail-closed 排序: 任何拒绝都在零写入前发生——
        # 日历缺会话/畸形在发布 regime 之前被拒)。
        self._derive_schedule(signal_session, available_at=published_at)

        regime_record = self._publish_regime_observation(
            snapshot=snapshot, signal_session=signal_session, now=published_at
        )
        schedule_record = self._publish_schedule(
            signal_session=signal_session, now=published_at
        )
        candidate_records = self._publish_candidates(
            snapshot=snapshot, signal_session=signal_session, now=published_at
        )
        watermark = max(
            regime_record.evidence.available_at,
            schedule_record.evidence.available_at,
            *(record.evidence.available_at for record in candidate_records),
        )
        return SessionEvidencePublication(
            signal_session=signal_session,
            schedule_evidence_id=schedule_record.evidence.evidence_id,
            selected_candidate_evidence_ids=tuple(
                record.evidence.evidence_id for record in candidate_records
            ),
            trusted_evidence_cutoff=watermark + _PUBLICATION_SETTLE,
        )

    def advance_sessions(
        self,
        *,
        signal_session: date,
        through_session: date,
        bars_by_session: Mapping[date, Mapping[str, object]],
        now: datetime | None = None,
    ) -> MarketAdvanceReceipt:
        """Publish per-session bar-set evidence, then advance the window.

        ``execution_sessions`` 取自该信号会话的冻结排程切片 (窗口 ≤
        through_session 的前缀, 必须以 through_session 结尾——切片是权威,
        驱动器不做位次算术)。
        """
        advance_at = self._clock() if now is None else now
        schedule = self._derive_schedule(
            signal_session, available_at=_instant(signal_session, _CLOSE_FINALIZED)
        )
        window = [
            session
            for session in (signal_session, *schedule.following_sessions)
            if session <= through_session
        ]
        if not window or window[-1] != through_session:
            raise TrialSessionDriverError(
                "advance_window_not_in_schedule",
                "through_session must be a member of the frozen schedule"
                " slice (the schedule is authoritative)",
                signal_session=signal_session.isoformat(),
                through_session=through_session.isoformat(),
                schedule_window=[
                    session.isoformat()
                    for session in (signal_session, *schedule.following_sessions)
                ],
            )
        # Whole-window preflight: when any session's bar set is missing, no
        # bar evidence may be published (a mid-window gap must not leave the
        # operator with a partially published window and a late failure).
        missing_sessions = [
            session for session in window if bars_by_session.get(session) is None
        ]
        if missing_sessions:
            raise TrialSessionDriverError(
                "bar_set_missing",
                "every advanced session needs a bar set (suspended or"
                " otherwise); UNKNOWN fencing happens downstream",
                missing_sessions=[
                    session.isoformat() for session in missing_sessions
                ],
            )
        bar_records = {
            session: self._publish_bar_set(
                session=session, bars=bars_by_session[session], now=advance_at
            )
            for session in window
        }
        return self._stack.runner.advance_market_session(
            MarketSessionAdvanceRequest(
                trial_id=self._stack.trial_id,
                through_session=through_session,
                execution_sessions=tuple(window),
                bar_records=bar_records,
            )
        )

    def finalize_missed(self, *, trusted_at: datetime) -> tuple[date, ...]:
        """Pass-through to the runner's NO_RUN bookkeeping (idempotent)."""
        return self._stack.runner.finalize_missed_sessions(trusted_at)

    def ensure_trial_registration(self) -> None:
        """Register the sealed trial with the decision store (idempotent).

        pair commit 的 FK 前置: bundle 取自治理封存真相 (governance 库),
        genesis 取自归档冷读 (``<root>/<trial_id>/genesis-manifest.json``) —
        两处都是官方栈的既有事实, 本层不构造任何新授权。恰等重放幂等
        (store 语义), 内容分歧由 store 的 ``registration_conflict`` 拒绝。
        """
        from src.screening.offensive.v3.governance.repository import (
            GovernanceRepository,
        )
        from src.screening.offensive.v3.orchestration.arm_capital import (
            read_genesis_manifest,
        )

        governance = GovernanceRepository(
            database_path=str(self._stack.governance_database()),
            clock=self._clock,
        )
        bundle = governance.regime_trial_bundle(self._stack.trial_id)
        manifest = read_genesis_manifest(
            self._stack.trial_root, self._stack.trial_id
        )
        self._stack.decision_store.register_trial(bundle, manifest)

    def deadline_contract(self, schedule: object) -> DeadlineContract:
        """宪法 #10 时序, 全部从排程切片派生 (T+1 = 首个后继会话)。"""
        following = tuple(schedule.following_sessions)
        if not following:
            raise TrialSessionDriverError(
                "schedule_slice_empty",
                "the frozen schedule carries no following sessions; the"
                " deadline contract cannot be derived",
                signal_session=str(schedule.signal_session),
            )
        deadlines = DeadlineContract(
            close_finalized_at=_instant(schedule.signal_session, _CLOSE_FINALIZED),
            seal_creation_deadline=_instant(schedule.signal_session, _SEAL_CREATION),
            permit_issue_deadline=_instant(schedule.signal_session, _PERMIT_ISSUE),
            permit_expires_at=_instant(following[0], _GATEWAY_SEND),
            gateway_send_deadline=_instant(following[0], _GATEWAY_SEND),
            broker_auction_cutoff=_instant(following[0], _BROKER_CUTOFF),
        )
        if not deadlines.ordering_valid():
            raise TrialSessionDriverError(
                "deadline_ordering_invalid",
                "the derived deadline contract violates constitution #10"
                " ordering (schedule slice is malformed)",
                signal_session=str(schedule.signal_session),
            )
        return deadlines

    # ------------------------------------------------------------------
    # Publication internals (existence-checked, fail-closed)
    # ------------------------------------------------------------------

    def _publish_regime_observation(
        self, *, snapshot: object, signal_session: date, now: datetime
    ) -> object:
        """One regime observation revision under the fixed evidence id.

        同会话重放: active 观察已绑定本会话且状态一致 → 复用 (原 available_at
        计入水位); 状态分歧 → 类型化拒绝 (同会话两套 regime 事实是冲突)。
        active 观察属于更早会话 → 本会话观察是新 revision, 正常发布。
        """
        state, reason = normalize_regime_state(
            snapshot.regime,
            reason_if_missing=RegimeObservationReason.MISSING_REQUIRED_INPUT,
        )
        probe_cutoff = now + _PUBLICATION_SETTLE
        existing = None
        try:
            existing = self._regime_reader.active(REGIME_EVIDENCE_ID, probe_cutoff)
        except EvidenceStoreError as exc:
            # 只吞「cutoff 前无提交」= 缺席; 其余仓库错误 propagate
            # (P2-1 纪律: 宽吞会假装没看到坏记录)。
            if _store_code(exc) != "evidence_not_committed_before_cutoff":
                raise
        if existing is not None:
            if existing.observation.signal_session == signal_session:
                if existing.observation.state is state:
                    return existing.record
                raise TrialSessionDriverError(
                    "regime_state_conflict",
                    "an active regime observation for this session carries a"
                    " different state; a session has exactly one regime truth",
                    signal_session=signal_session.isoformat(),
                    published=str(existing.observation.state),
                    snapshot=str(state),
                )
            if existing.observation.signal_session > signal_session:
                # 前向 Trial 的会话序纪律: active 头只能随驱动前进。为更早
                # 会话追加 revision 会把 active 投影倒回 (R41 RED 探针实锤:
                # retro 驱动静默成功后, 本应幂等的晚会话重放以
                # batch_seal_conflict 破裂, 操作员无法与真实损坏区分)。
                # 错过会话的官方出口是 finalize-missed (NO_RUN), 不是补驱动。
                raise TrialSessionDriverError(
                    "regime_session_regression",
                    "the active regime observation belongs to a later session;"
                    " a forward trial drives sessions in order (missed"
                    " sessions are recorded NO_RUN via finalize-missed, never"
                    " retro-decided)",
                    active_session=existing.observation.signal_session.isoformat(),
                    requested_session=signal_session.isoformat(),
                )

        observation = RegimeObservation(
            signal_session=signal_session,
            state=state,
            reason=reason,
            raw_state=snapshot.regime,
            source_revisions=(
                RegimeSourceRevision(
                    evidence_id=(
                        f"readiness:{snapshot.manifest.domain}:"
                        f"{snapshot.manifest.run_id}"
                    ),
                    revision=1,
                    artifact_hash=self._regime_source_artifact_hash(snapshot),
                ),
            ),
            effective_at=now,
            provider_published_at=now,
            observed_at=now,
            classifier_semver="1.0.0",
            behavior_fingerprint=REGIME_CLASSIFIER_FINGERPRINT,
            input_schema_hash=REGIME_CLASSIFIER_FINGERPRINT,
        )
        envelope = self._regime_envelope(observation, now)
        envelope_bytes = envelope.model_dump_json().encode("utf-8")
        signed = self._regime_signer.sign_snapshot(envelope, envelope_bytes)
        repository = self._stack.regime_repository
        # 观察blob 先行 (blob-before-envelope 纪律): publish 与 revision 两路
        # 都必须先把观察字节持久化, 信封才指向可读 payload。
        blob_hash = repository.persist_payload(observation.canonical_bytes())
        if envelope.payload_content_hash != blob_hash:
            raise TrialSessionDriverError(
                "regime_observation_hash_mismatch",
                "regime envelope does not bind the observation bytes",
            )
        if existing is None:
            repository.publish(signed, envelope_bytes)
        else:
            # 次日及以后: 固定 id 的修正链 (prepare→activate 单调投影)。
            # prepare 幂等 (恰等内容复用既有 staged revision); activate 对
            # 当前 active revision 的重试幂等。
            staged = repository.prepare_revision(signed, envelope_bytes)
            repository.activate_revision(REGIME_EVIDENCE_ID, staged.revision)
        return self._regime_reader.active(
            REGIME_EVIDENCE_ID, probe_cutoff
        ).record

    def _regime_source_artifact_hash(self, snapshot: object) -> str:
        fingerprint = snapshot.manifest.shared_evidence.regime_fingerprint
        if fingerprint.startswith(_REGIME_FINGERPRINT_PREFIX):
            fingerprint = fingerprint[len(_REGIME_FINGERPRINT_PREFIX):]
        if len(fingerprint) != 64 or not _HEX.issuperset(fingerprint):
            raise TrialSessionDriverError(
                "regime_source_fingerprint_invalid",
                "the readiness manifest's regime fingerprint is not a"
                " sha256 hex digest; refusing to bind a fabricated source",
                fingerprint=str(
                    snapshot.manifest.shared_evidence.regime_fingerprint
                ),
            )
        return fingerprint

    def _regime_envelope(
        self, observation: RegimeObservation, now: datetime
    ) -> object:
        from src.screening.offensive.v3.contracts import SUPPORTED_SCHEMA_MAJOR
        from src.screening.offensive.v3.contracts.base import (
            EvidenceScope,
            ExecutionMode,
        )
        from src.screening.offensive.v3.contracts.evidence import SnapshotEvidence

        return SnapshotEvidence(
            evidence_id=REGIME_EVIDENCE_ID,
            subject_scope=EvidenceScope.GLOBAL,
            subject_producer="regime",
            family_id=None,
            strategy_semver="1.0.0",
            behavior_fingerprint=REGIME_CLASSIFIER_FINGERPRINT,
            policy_epoch=1,
            execution_version="t1-open-t10-open.v1",
            cost_version="cn-a-share-costs.v1",
            effective_at=now,
            provider_published_at=now,
            observed_at=now,
            available_at=now,
            mode=ExecutionMode.DAILY_BAR_PROXY,
            source_authority="regime.classifier",
            payload_content_hash=hashlib.sha256(
                observation.canonical_bytes()
            ).hexdigest(),
            schema_major=SUPPORTED_SCHEMA_MAJOR,
            evidence_kind="snapshot",
        )

    def _publish_schedule(self, *, signal_session: date, now: datetime) -> object:
        """Publish (or exactly reuse) the schedule slice for this session.

        排程 evidence_id 含内容哈希前缀: 日历分歧自然产生不同 id (老切片不
        被覆盖); 复用路径仍逐字节比对 payload 哈希作纵深。
        """
        schedule = self._derive_schedule(signal_session, available_at=now)
        envelope = build_schedule_envelope(schedule, observed_at=now)
        probe_cutoff = now + _PUBLICATION_SETTLE
        existing = self._existing(
            self._stack.schedule_repository, envelope.evidence_id, cutoff=probe_cutoff
        )
        if existing is not None:
            # evidence_id 含切片指纹前缀, 但信封哈希还绑 available_at/observed_at
            # (重放合法推进) — 复用判定比对其切片本体: 同 signal+following 才是
            # 同一排程; 切片分歧 = 同 id 两套排程, 类型化冲突。
            existing_schedule = schedule_from_record(
                self._stack.schedule_repository,
                existing,
                expected_signal_session=signal_session,
            )
            if (
                existing_schedule.calendar_artifact_hash
                != schedule.calendar_artifact_hash
                or existing_schedule.following_sessions != schedule.following_sessions
            ):
                raise TrialSessionDriverError(
                    "schedule_content_conflict",
                    "an evidence id for this schedule slice already carries a"
                    " different slice (same id, two schedule truths)",
                    evidence_id=envelope.evidence_id,
                )
            return existing
        self._schedule_publisher.publish(
            signal_session=signal_session, calendar_path=self._calendar_path
        )
        return self._existing(
            self._stack.schedule_repository, envelope.evidence_id, cutoff=probe_cutoff
        )

    def _publish_candidates(
        self, *, snapshot: object, signal_session: date, now: datetime
    ) -> tuple[object, ...]:
        """Publish candidates only when absent (partial states fail closed)."""
        from src.screening.offensive.v3.producers.btst import (
            BTST_BEHAVIOR_BASELINE,
            produce_btst_signal_artifacts,
        )

        artifacts = produce_btst_signal_artifacts(
            snapshot, behavior_fingerprint=BTST_BEHAVIOR_BASELINE
        )
        selected_ids = tuple(
            artifact.envelope.evidence_id
            for artifact in artifacts
            if artifact.envelope.stage is SignalStage.SELECTED
        )
        probe_cutoff = now + _PUBLICATION_SETTLE
        # 同会话候选真相序纪律: 该会话一旦有已提交 SELECTED 候选不在当前
        # 快照派生集合内 (crash 后 manifest 重生成再重驱动的分歧形态),
        # 在零新发布处类型化拒绝——否则第二套 SELECTED 会静默入库, 晚失败
        # 于批完备性 (batch_completeness_violation) 且永久污染证据时间轴。
        # 恰等重放不受影响 (committed ⊆ derived 时进入下方复用路径)。
        committed = committed_selected_candidate_ids(
            self._stack.btst_repository, signal_session, probe_cutoff
        )
        unexpected = set(committed) - set(selected_ids)
        if unexpected:
            raise TrialSessionDriverError(
                "candidate_set_divergence",
                "committed SELECTED candidates exist for this session that"
                " the current snapshot does not derive; a session has"
                " exactly one candidate truth",
                signal_session=signal_session.isoformat(),
                committed_not_derived=sorted(unexpected),
                derived_evidence_ids=sorted(selected_ids),
            )
        if not selected_ids:
            return ()
        presence = {
            evidence_id: self._existing(
                self._stack.btst_repository, evidence_id, cutoff=probe_cutoff
            )
            for evidence_id in selected_ids
        }
        if all(record is not None for record in presence.values()):
            return tuple(presence[evidence_id] for evidence_id in selected_ids)
        if any(record is not None for record in presence.values()):
            raise TrialSessionDriverError(
                "candidate_publication_partial",
                "some candidates for this session are already committed while"
                " others are not; a half-published session is a conflict, not"
                " a resumable state",
                signal_session=signal_session.isoformat(),
                committed=[
                    evidence_id
                    for evidence_id, record in presence.items()
                    if record is not None
                ],
                missing=[
                    evidence_id
                    for evidence_id, record in presence.items()
                    if record is None
                ],
            )
        self._producer.produce_and_publish(snapshot)
        records = tuple(
            self._existing(
                self._stack.btst_repository, evidence_id, cutoff=probe_cutoff
            )
            for evidence_id in selected_ids
        )
        if any(record is None for record in records):
            raise TrialSessionDriverError(
                "candidate_publication_incomplete",
                "the producer returned without committing every selected"
                " candidate it derived",
                signal_session=signal_session.isoformat(),
            )
        return records

    def _publish_bar_set(
        self, *, session: date, bars: Mapping[str, object], now: datetime
    ) -> object:
        """Publish (or exactly reuse) one session's bar set.

        bar-set evidence_id 只含会话 (不含内容哈希) — 复用路径必须逐字节
        比对 payload 哈希: 同会话两套 bar 是冲突, 绝不静默择一。
        """
        from src.screening.offensive.v3.evidence.market_bars import (
            build_bar_set_envelope,
            derive_bar_set,
        )

        bar_set = derive_bar_set(session=session, bars=bars)
        expected_hash = hashlib.sha256(bar_set.canonical_bytes()).hexdigest()
        # id 从发布器同一构造器派生 (单一实现; 信封时间戳不进 id)。
        evidence_id = build_bar_set_envelope(
            bar_set, observed_at=now
        ).evidence_id
        existing = self._existing(
            self._stack.bars_repository, evidence_id, cutoff=now + _PUBLICATION_SETTLE
        )
        if existing is not None:
            if existing.evidence.payload_content_hash != expected_hash:
                raise TrialSessionDriverError(
                    "bar_set_content_conflict",
                    "a bar set for this session is already committed with"
                    " different bytes; a session has exactly one bar truth",
                    session=session.isoformat(),
                    evidence_id=evidence_id,
                )
            return existing
        return self._bars_publisher.publish(session=session, bars=bars)

    def _derive_schedule(self, signal_session: date, *, available_at: datetime):
        dates = load_authoritative_dates(self._calendar_path)
        if signal_session not in dates:
            raise TrialSessionDriverError(
                "signal_session_not_in_calendar",
                "the signal session is absent from the authoritative calendar",
                signal_session=signal_session.isoformat(),
                calendar_path=str(self._calendar_path),
            )
        return derive_trading_schedule(
            signal_session=signal_session,
            calendar_dates=dates,
            available_at=available_at,
        )

    def _existing(
        self, repository: EvidenceRepository, evidence_id: str, *, cutoff: datetime
    ) -> object | None:
        try:
            return repository.active_revision(evidence_id, cutoff)
        except EvidenceStoreError as exc:
            if _store_code(exc) != "evidence_not_committed_before_cutoff":
                raise
            return None


__all__ = [
    "OfficialTrialSessionDriver",
    "REGIME_CLASSIFIER_FINGERPRINT",
    "SessionEvidencePublication",
    "TrialSessionDriverError",
]
