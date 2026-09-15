"""Disabled paired-trial entry point and authority-free pure builders.

The official runner has no injected capabilities and always fails closed.
Module-level builders preserve the deterministic target construction for
direct tests; they do not grant forward input authority.
"""

from __future__ import annotations

from typing import Protocol

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone

from pydantic import model_validator

from src.screening.offensive.v3.contracts import CanonicalModel, Sha256
from src.screening.offensive.v3.contracts.btst_candidate import (
    BtstCandidateIndustryState,
    BtstRawCandidatePayload,
)
from src.screening.offensive.v3.contracts.decision import ShadowDecision
from src.screening.offensive.v3.contracts.evidence import (
    EvidenceRecord,
    SignalEvidence,
)
from src.screening.offensive.v3.contracts.regime import RegimeObservation
from src.screening.offensive.v3.contracts.trial import (
    BaselineShadowPolicyBinding,
    ShadowPolicySourceKind,
    TargetShadowPolicyBinding,
    TrialArm,
)
from src.screening.offensive.v3.evidence.session_spine import SessionStatus
from src.screening.offensive.v3.governance.regime_trial import (
    ValidatedRegimeTrialBundle,
)
from src.screening.offensive.v3.kernel.admission import BTST_FAMILY
from src.screening.offensive.v3.contracts.base import ExecutionMode
from src.screening.offensive.v3.kernel.models import (
    FrozenTradingSessionSchedule,
    CandidateEvidenceBinding,
    DeadlineContract,
    NoTradeDecision,
    RawCandidate,
    ShadowCapitalCheckpoint,
    ShadowKernelInput,
    ShadowSharedInput,
)
from src.screening.offensive.v3.kernel.sizing import SizingConfig
from src.screening.offensive.v3.orchestration.trial_store import (
    ArmDecision,
    TrialArmDecisionRecord,
)


class PairedTrialRunnerError(RuntimeError):
    """Fail-closed rejection of a forward paired-trial session."""

    def __init__(self, code: str, message: str, **details: object) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.details = details


@dataclass(frozen=True)
class SignalSessionRequest:
    """One official forward signal-session decision request (R24 解锁).

    会话决策变量全部显式: cutoff/trusted_at/deadlines 是特权 worker 排程
    职责 (宪法 #10 时序由 ``DeadlineContract`` 校验器强制; assemble 内部
    的批授权/完备性由 store 侧 seal 强制 — caller 声明不能替代)。
    """

    trial_id: str
    signal_session: date
    # 解锁字段带默认值: 未填请求在解锁路径被显式拒绝 (deadline/cycle
    # 校验), 无参 runner 也保持 fail-closed — 两层独立。
    decision_cycle_id: str = ""
    trusted_evidence_cutoff: datetime | None = None
    trusted_at: datetime | None = None
    schedule_evidence_id: str = ""
    candidate_evidence_ids: tuple[str, ...] = ()
    deadlines: object | None = None  # DeadlineContract; 由 worker 排程构造


@dataclass(frozen=True)
class MarketSessionAdvanceRequest:
    """One official market-session advance (R25 解锁).

    会话窗口/时间回调/bar 证据记录是 worker 排程职责的声明式注入:
    ``execution_sessions`` 来自冻结排程切片 (排程是权威), ``bar_records``
    是证据时间轴已发布的 per-session bar-set 记录 (经
    ``evidence_backed_bar_for`` 严格验证, 调用方无法喂原始 CSV)。
    """

    trial_id: str
    through_session: date
    execution_sessions: tuple[date, ...] = ()
    bar_records: object = None  # Mapping[date, EvidenceRecord]


@dataclass(frozen=True)
class MarketAdvanceReceipt:
    """Durable outcome of one market-window advance (both arms)."""

    trial_id: str
    through_session: date
    settlements_by_arm: dict
    conservation_ok_by_arm: dict
    open_at_end_by_arm: dict


@dataclass(frozen=True)
class PairedSignalReceipt:
    """The durable outcome of one signal session decision."""

    trial_id: str
    signal_session: date
    pair_key: tuple[str, str, str]
    champion_status: SessionStatus
    challenger_status: SessionStatus
    decision_cycle_id: str
    regime_observation_hash: Sha256


#: The one regime evidence id the paired trial consumes (published by the
#: RegimeObservationPublisher in evidence/regime.py).
REGIME_EVIDENCE_ID: str = "regime:csi300:1.0"


class CommittedBtstCandidate(CanonicalModel):
    """A strict binding value produced after store verification.

    The DTO is not authority by itself. Forward and replay entry points must
    independently prove the record and payload against their authoritative
    Evidence Store before passing it to the pure input builder.
    """

    record: EvidenceRecord[SignalEvidence]
    payload: BtstRawCandidatePayload

    @model_validator(mode="after")
    def validate_binding(self) -> "CommittedBtstCandidate":
        envelope = self.record.evidence
        if envelope.stage.value != "selected":
            raise ValueError("committed candidate requires SELECTED signal evidence")
        if envelope.payload_content_hash != self.payload.content_hash():
            raise ValueError("signal record does not bind the raw candidate payload")
        if envelope.evidence_id != (
            f"{self.payload.candidate_id}:{self.payload.signal_stage.value}"
        ):
            raise ValueError("signal evidence identity does not match raw candidate")
        if envelope.effective_at.date() != self.payload.signal_session:
            raise ValueError("signal evidence session does not match raw candidate")
        return self


class ForwardBtstProducerPort(Protocol):
    """The runner's producer contract (Phase 2, 2026-08-20).

    Structural port promoted from the duck-typed ``_CountingProducer`` test rig:
    ``BtstProducerApi`` already satisfies it. ``produce_and_publish`` runs
    exactly once per signal session; ``candidate_payload`` re-verifies the
    record against the store before the raw payload is trusted.

    ``published_at`` (R103) 是信封 available_at 的注入面: 官方前向 Trial
    路径传实际发布时刻 — trusted_evidence_cutoff (成员水位+1s) 必须落在
    seal_creation_deadline (signal_session 16:00 UTC) 内; 缺省 None 保持
    legacy 窗关闭语义 (shadow 流无 deadline 消费面, 行为与历史一致)。
    """

    def produce_and_publish(
        self,
        snapshot: object,
        *,
        published_at: datetime | None = None,
    ) -> tuple[EvidenceRecord, ...]: ...

    def candidate_payload(self, record: EvidenceRecord, *, expected_signal_session: date) -> object: ...


def committed_candidates(
    producer: ForwardBtstProducerPort,
    snapshot: object,
    *,
    expected_signal_session: date,
) -> tuple["CommittedBtstCandidate", ...]:
    """Publish once per session, then bind every SELECTED record to its payload.

    Pure orchestration over the producer port: no store writes beyond the
    producer's own publication, no authority. Binding integrity (SELECTED
    stage, payload hash, evidence identity, session) is enforced by the
    ``CommittedBtstCandidate`` validator — fail-closed on any mismatch.
    """
    records = producer.produce_and_publish(snapshot)
    committed: list[CommittedBtstCandidate] = []
    for record in records:
        payload = producer.candidate_payload(record, expected_signal_session=expected_signal_session)
        committed.append(CommittedBtstCandidate(record=record, payload=payload))
    return tuple(committed)


#: 15:00 国内收盘 = 07:00 UTC; 影子 proxy 的命令时刻由会话日确定性派生
#: (排程显式化留 worker 接线迭代)。模块级单一实现: runner 驱动器与 CLI
#: 前置门 (脚本层镜像) 必须用同一命令时序投影, settled 验证才与原结算同判。
_ADVANCE_COMMAND_TIME_OF_DAY = time(7, 0)


def advance_command_at(session: date) -> datetime:
    return datetime.combine(session, _ADVANCE_COMMAND_TIME_OF_DAY, tzinfo=timezone.utc)


def advance_send_deadline(session: date) -> datetime:
    return advance_command_at(session) + timedelta(minutes=5)


def _published_pre_window_bars_lookup(
    bar_repository: object, session: date, *, cutoff: datetime
) -> dict[str, object] | None:
    """Published bar-set evidence for one pre-window session (gate face).

    cutoff 钳在首个窗口会话的命令时刻: pre-window 入场会话的 bar-set 由
    更早的 advance 发布 (严格早于本夜首个窗口会话), PIT 正确且重放确定性
    (同 cutoff 同判)。未发布 = 不可证明 (None → 保守 unverified); 只吞
    「cutoff 前未提交」这一缺席码, 其余证据错误 propagate (P2-1: 宽吞会
    假装没看到坏记录)。
    """
    from src.screening.offensive.v3.evidence.market_bars import bars_from_record
    from src.screening.offensive.v3.evidence.repository import EvidenceStoreError

    try:
        record = bar_repository.active_revision(  # type: ignore[attr-defined]
            f"market:bars:{session:%Y%m%d}", cutoff
        )
    except EvidenceStoreError as exc:
        if getattr(exc, "code", "") == "evidence_not_committed_before_cutoff":
            return None
        raise
    return bars_from_record(bar_repository, record, expected_session=session)


def _unverified_pre_window_entries(
    entries_by_arm: dict,
    pre_window_sessions: list[date],
    arm_reads: dict,
    *,
    bar_lookup,
) -> list[date]:
    """Which pre-window entry sessions lack a provably terminal settlement.

    一行已终结当且仅当 (a) 臂台账存在该 (lineage, lot) 的 fill 事实
    (position 行, open 或 closed —— fill 是资本事实, no-fill 不留资本
    痕迹), 或 (b) 锁定判定表 ``resolve_open_execution`` 对该会话已发布的
    bar-set 证据重推导出 ``NO_FILL / limit_not_touched`` (任何命令时序下
    都不成交, R220 Op1 核销语义)。其余 (UNKNOWN / 停牌 / 缺证据) 一律
    unverified → 门 fail-closed。双臂逐行核验。
    """
    from src.screening.offensive.v3.execution.lifecycle import (
        REASON_LIMIT_NOT_TOUCHED,
        OpenExecutionVerdict,
        resolve_open_execution,
    )
    from src.screening.offensive.v3.contracts.execution import ExecutionSide

    unverified: set[date] = set()
    bars_cache: dict[date, dict[str, object] | None] = {}
    for arm, entries in entries_by_arm.items():
        reads = arm_reads[arm]
        for entry_session in pre_window_sessions:
            for line in entries.get(entry_session, ()):
                if (
                    reads.position_row(
                        line.position_lineage_id, line.economic_lot_id
                    )
                    is not None
                ):
                    continue  # FILLED: 资本 fill 事实在案
                if entry_session not in bars_cache:
                    bars_cache[entry_session] = bar_lookup(entry_session)
                bars = bars_cache[entry_session]
                bar = bars.get(line.security_id) if bars else None
                resolution = resolve_open_execution(
                    side=ExecutionSide.ENTRY,
                    limit_price_cents=line.limit_price_cents,
                    bar=bar,
                    command_at=advance_command_at(entry_session),
                    send_deadline=advance_send_deadline(entry_session),
                )
                if (
                    resolution.verdict is OpenExecutionVerdict.NO_FILL
                    and resolution.reason == REASON_LIMIT_NOT_TOUCHED
                ):
                    continue  # 可证 no-fill: 任何时序下都不成交
                unverified.add(entry_session)
    return sorted(unverified)


def _seed_initial_holdings(repository, entries_by_arm: dict, *, window_start) -> dict:
    """窗口起步持仓种子 (R224): 臂台账 open lots → 驱动器可见持仓.

    窗口起步 ``holdings={}`` 是 R216 覆盖门严格性的机制根源 —— continuation
    窗口必须携带窗口前开仓的持仓 (marks/出场义务), 身份经 pair 记录确定性
    重推导并交叉核对 (lineage→line, lot/security/quantity 全对齐); 不可
    解析即类型化拒绝 (fail-closed: 绝不静默丢弃持仓义务, 也绝不冒充身份)。
    只携带窗口前入场的 lot: 入场会话在本窗口内的 open lot 由窗口内幂等
    重结算处理 (同 execution_id 收敛), 种子携带反而 duplicate_holding 崩溃
    (crash-resume 同窗口重放实录)。repository 是暴露 open_position_rows()
    的读面 (CapitalRepository 或 ArmLedgerQuietReads 视图)。
    """
    lines_by_lineage = {
        line.position_lineage_id: line
        for lines in entries_by_arm.values()
        for line in lines
    }
    pre_window_lines = {
        line.position_lineage_id: line
        for entry_session, lines in entries_by_arm.items()
        if entry_session < window_start
        for line in lines
    }
    seeded: dict[str, object] = {}
    for row in repository.open_position_rows():
        lineage = str(row.position_lineage_id)
        line = pre_window_lines.get(lineage)
        if line is None:
            if lineage in lines_by_lineage:
                continue  # 窗口内入场的 lot: 由窗口内重结算幂等处理
            raise PairedTrialRunnerError(
                "seed_lot_identity_unresolved",
                "an open capital lot cannot be resolved to a committed pair"
                " line; carrying it would invent identity, dropping it would"
                " strand its exit obligation",
                position_lineage_id=lineage,
                economic_lot_id=str(row.economic_lot_id),
            )
        if (
            line.economic_lot_id != str(row.economic_lot_id)
            or line.security_id != str(row.security_id)
            or line.quantity != int(row.settled_quantity_units or 0)
        ):
            raise PairedTrialRunnerError(
                "seed_lot_identity_unresolved",
                "an open capital lot does not match its committed pair line"
                " (lot id / security / quantity divergence)",
                position_lineage_id=lineage,
                economic_lot_id=str(row.economic_lot_id),
            )
        if line.security_id in seeded:
            raise PairedTrialRunnerError(
                "seed_security_conflict",
                "two open lots map to one security; the driver holds one"
                " holding per security",
                security_id=line.security_id,
            )
        seeded[line.security_id] = line
    return seeded


def classify_pair_session(
    champion: ArmDecision | None,
    challenger: ArmDecision | None,
    *,
    shared_candidate_count: int,
) -> SessionStatus:
    """The pure session-status classification for one committed pair.

    - shared empty candidates (or a NO_SIGNAL no-trade on both arms) →
      ``NO_SIGNAL``;
    - a common capital/risk/integrity block (the same non-NO_SIGNAL no-trade
      reason on both arms) → ``BLOCKED``;
    - no pair at all after the decision cutoff → ``NO_RUN``;
    - otherwise the session ran (a Champion trade with a regime-blocked
      Challenger is a normal paired run) → ``RUN``.
    """

    if champion is None or challenger is None:
        return SessionStatus.NO_RUN
    if shared_candidate_count == 0:
        return SessionStatus.NO_SIGNAL
    champion_block = (
        champion.reason if isinstance(champion, NoTradeDecision) else None
    )
    challenger_block = (
        challenger.reason if isinstance(challenger, NoTradeDecision) else None
    )
    if (
        champion_block is not None
        and challenger_block is not None
        and champion_block == challenger_block
        and champion_block.value != "NO_SIGNAL"
    ):
        return SessionStatus.BLOCKED
    return SessionStatus.RUN


class ForwardPairedTrialRunner:
    """Official forward entry point — decide unlocked (R24, owner 在场).

    解锁依据 (docstring 原条件的落地): Evidence Store 已持有会话批授权
    (``SessionBatchSealer`` 三段式 + 完备性), 治理已封存决策窗口 (签发
    回执 + 归档 + 持久身份), 组装面带消费侧防御断言 (R9), 两臂资本走
    arm_layout 约定路径 (R21/R23)。``decide_signal_session`` 的每个 mutating
    能力都经注入依赖显式到达, 无 ambient 权限。

    ``advance_market_session``/``finalize_missed_sessions`` 仍 fail-closed
    (市场会话推进 = SessionLifecycleDriver 产品化, 排程接线下轮解锁)。
    """

    def __init__(
        self,
        *,
        assembler: object = None,
        capital_trial_root: object = None,
        portfolio_id: str | None = None,
        sizing_config: SizingConfig | None = None,
        decision_store: object = None,
        kernel_decider: object | None = None,
        bar_repository: object = None,
        market_scenario: object = None,
        trial_attribution: object = None,
        session_spine: object = None,
        research_program_id: str | None = None,
        trial_id: str | None = None,
    ) -> None:
        # 无参实例 = 未注入 authority, decide 保持 fail-closed (旧 disabled
        # 语义的延续: 权限只来自显式注入的依赖链, 无 ambient 能力)。
        self._assembler = assembler
        self._capital_trial_root = capital_trial_root
        self._portfolio_id = portfolio_id
        self._sizing = sizing_config
        self._store = decision_store
        self._decider = kernel_decider
        self._bar_repository = bar_repository
        self._market_scenario = market_scenario
        self._trial_attribution = trial_attribution
        self._session_spine = session_spine
        self._research_program_id = research_program_id
        self._trial_id = trial_id

    def _kernel(self) -> object:
        if self._decider is not None:
            return self._decider
        from src.screening.offensive.v3.kernel.decide import GrowthKernel

        return GrowthKernel(self._sizing)

    def _require_unlocked(self) -> None:
        if (
            self._assembler is None
            or self._capital_trial_root is None
            or self._portfolio_id is None
            or self._sizing is None
            or self._store is None
        ):
            raise PairedTrialRunnerError(
                "forward_input_authority_unavailable",
                "official forward authority requires the full injected"
                " dependency chain (assembler/capital root/store/sizing)",
            )

    def decide_signal_session(
        self, request: SignalSessionRequest
    ) -> PairedSignalReceipt:
        """Official session decision: assemble → dual-arm capital → kernel → pair commit.

        恰等重放幂等由 ``commit_pair`` 保证 (同键同内容返回原 receipt);
        批授权/完备性/防御断言在 assemble 内部强制。
        """
        from src.screening.offensive.v3.contracts.trial import TrialArm
        from src.screening.offensive.v3.orchestration.arm_layout import (
            arm_session_checkpoint,
        )

        self._require_unlocked()
        # R45 守卫: 会话真相前向唯序。spine 已带终态 NO_RUN 的会话是证据
        # 时间轴的"本会话无运行"事实 —— 其后再提交 pair 会制造决策库与
        # 证据时间轴的分歧; 错过会话的唯一官方出口是 finalize-missed。
        # 仅在 spine+program 均注入且恰好命中 NO_RUN 时拒绝(零副作用,
        # 先于 deadline/assemble 消费); 未注入或非终态形态不拦, 既有
        # fail-closed 与幂等重放语义逐字节不变。RUN/BLOCKED/NO_SIGNAL
        # 不在此拒: 同会话重放由 commit_pair 恰等幂等收敛 (R44 处置表)。
        if (
            self._session_spine is not None
            and self._research_program_id is not None
            and self._session_spine.status(
                self._research_program_id, request.signal_session
            )
            is SessionStatus.NO_RUN
        ):
            raise PairedTrialRunnerError(
                "terminal_no_run_forbids_pair_creation",
                "the session spine carries a terminal NO_RUN status; a"
                " forward trial never creates pairs behind its own"
                " evidence timeline",
                signal_session=request.signal_session.isoformat(),
            )
        if request.deadlines is None:
            raise PairedTrialRunnerError(
                "deadline_contract_required",
                "the session request must carry the worker-built"
                " DeadlineContract (constitution #10)",
            )
        assembled = self._assembler.assemble(
            session=request.signal_session,
            cutoff=request.trusted_evidence_cutoff,
            cycle_id=request.decision_cycle_id,
            trusted_at=request.trusted_at,
            schedule_evidence_id=request.schedule_evidence_id,
            candidate_evidence_ids=request.candidate_evidence_ids,
        )
        checkpoints = {}
        for arm in (TrialArm.CHAMPION, TrialArm.CHALLENGER):
            checkpoints[arm] = arm_session_checkpoint(
                self._capital_trial_root,
                trial_id=request.trial_id,
                arm=arm,
                portfolio_id=self._portfolio_id,
                mode=assembled.shared_input.mode,
                as_of=request.trusted_at,
                capital_store_id=(
                    f"{request.trial_id}:{arm.value.lower()}:capital"
                ),
            )
        champion_input, challenger_input = build_arm_kernel_inputs(
            validated=assembled.validated_bundle,
            shared_input=assembled.shared_input,
            candidates=assembled.candidates,
            champion_capital_checkpoint=checkpoints[TrialArm.CHAMPION],
            challenger_capital_checkpoint=checkpoints[TrialArm.CHALLENGER],
            deadlines=request.deadlines,
            sizing_config=self._sizing,
        )
        kernel = self._kernel()
        champion = kernel.decide_shadow(champion_input)
        challenger = kernel.decide_shadow(challenger_input)
        records = build_pair_records(
            trial_id=request.trial_id,
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
        self._store.commit_pair(*records)
        status = classify_pair_session(
            champion, challenger, shared_candidate_count=len(assembled.candidates)
        )
        # 配对试验的会话状态是 pair 级事实 (两臂同会话), 两字段填同一分类 —
        # per-arm 分化不存在于配对语义。
        return PairedSignalReceipt(
            trial_id=request.trial_id,
            signal_session=request.signal_session,
            pair_key=(
                request.trial_id,
                request.signal_session.isoformat(),
                request.decision_cycle_id,
            ),
            champion_status=status,
            challenger_status=status,
            decision_cycle_id=request.decision_cycle_id,
            regime_observation_hash=assembled.regime.observation_hash,
        )

    # ===================================================================
    # forward market-session advance (exit run-out through finality)
    # ===================================================================

    def advance_market_session(
        self, request: MarketSessionAdvanceRequest | SignalSessionRequest
    ) -> MarketAdvanceReceipt:
        """Official market-window advance: pair lines → dual-arm lifecycle drive.

        形态 = 对 [窗口起点 … through_session] 的全生命周期重放: append-only
        台账 + 幂等结算使重放收敛 (重复 advance 同窗口返回等价结果, 资本
        副作用幂等)。出场先于入场/停牌顺延/守恒重验由 ``SessionLifecycleDriver``
        强制; bar 源经 ``evidence_backed_bar_for`` (证据时间轴唯一入口)。
        """
        from collections.abc import Mapping as _Mapping

        from src.screening.offensive.v3.contracts.trial import TrialArm
        from src.screening.offensive.v3.orchestration.arm_layout import (
            open_arm_capital_repository,
        )
        from src.screening.offensive.v3.orchestration.replay_assembly import (
            evidence_backed_bar_for,
        )
        from src.screening.offensive.v3.orchestration.session_driver import (
            ArmLedgerQuietReads,
            SessionLifecycleDriver,
            open_line_from_shadow_line,
        )

        self._require_unlocked()
        if (
            self._bar_repository is None
            or self._market_scenario is None
            or self._trial_attribution is None
        ):
            raise PairedTrialRunnerError(
                "market_advance_authority_unavailable",
                "market advance requires injected bar repository, cost"
                " scenario and fill attribution",
            )
        if not isinstance(request, MarketSessionAdvanceRequest):
            raise PairedTrialRunnerError(
                "advance_request_invalid",
                "advance requires a MarketSessionAdvanceRequest",
            )
        sessions = tuple(request.execution_sessions)
        if not sessions or sessions[-1] != request.through_session:
            raise PairedTrialRunnerError(
                "advance_window_invalid",
                "execution_sessions must be non-empty and end at"
                " through_session (schedule slice is authoritative)",
            )
        if list(sessions) != sorted(sessions):
            raise PairedTrialRunnerError(
                "advance_window_invalid",
                "execution_sessions must be strictly ordered",
            )
        bar_records = request.bar_records
        if not isinstance(bar_records, _Mapping):
            raise PairedTrialRunnerError(
                "advance_bar_records_required",
                "worker must supply the published per-session bar-set records",
            )
        missing_bars = [s for s in sessions if s not in bar_records]
        if missing_bars:
            raise PairedTrialRunnerError(
                "advance_bar_records_required",
                "every execution session needs a published bar-set record",
                missing=sorted(missing_bars)[:5],
            )

        # 已 commit 的 pairs → 双臂入场计划 (kernel 行是身份/量/日期权威)
        entries_by_arm: dict = {TrialArm.CHAMPION: {}, TrialArm.CHALLENGER: {}}
        for key in self._store.pair_keys(request.trial_id):
            champion_record, challenger_record = self._store.pair(key)
            for arm, record in (
                (TrialArm.CHAMPION, champion_record),
                (TrialArm.CHALLENGER, challenger_record),
            ):
                decision = record.decision
                if isinstance(decision, NoTradeDecision):
                    # No-trade 会话 (零候选/regime 阻断/容量阻断) 无入场计划 —
                    # 该臂该会话保持空仓, 生命周期照常推进 (marks/出场义务)。
                    # 影子前向试验的常态路径; 修复前这里无条件访问
                    # ``target_entry_session`` 使任何 no-trade 会话的窗口推进
                    # 崩溃 (R36 首次真实消费暴露)。
                    continue
                entry_session = decision.target_entry_session
                lines = tuple(
                    open_line_from_shadow_line(line, entry_session=entry_session)
                    for line in decision.counterfactual_lines
                )
                entries_by_arm[arm].setdefault(entry_session, ())
                entries_by_arm[arm][entry_session] = (
                    entries_by_arm[arm][entry_session] + lines
                )

        # 窗口覆盖完备性门 (R216, R224 放宽为验证式): 入场结算只发生在
        # entry_session 的精确会话匹配上 (无出场那样的 >= 顺延语义), 且跨
        # run 持仓重建依赖覆盖入场会话的全量重放 —— 窗口起点越过已决策入场
        # 会话时, 该行的结算必须已被证明终结 (资本 fill 记录在案, 或锁定
        # 判定表对已发布 bar-set 证据重推导出可证 no-fill), 否则窗口起点
        # 之前的入场行会永久失去结算机会且不留台账痕迹 (与合法 no-fill 不可
        # 区分, R215 审计 unmatched 双臂发现的根因族)。fail-closed: 不可
        # 证明即拒绝 (UNKNOWN/缺 bar 证据/无 fill 记录一律不算已终结);
        # entry_session > through_session 不拦 (未来窗口的合法结算)。
        pre_window_sessions = sorted(
            {
                entry_session
                for entries in entries_by_arm.values()
                for entry_session in entries
                if entry_session < sessions[0]
            }
        )
        arm_repositories: dict = {}
        if pre_window_sessions:
            arm_repositories = {
                arm: open_arm_capital_repository(self._capital_trial_root, arm)
                for arm in (TrialArm.CHAMPION, TrialArm.CHALLENGER)
            }
            unverified_entry_sessions = _unverified_pre_window_entries(
                entries_by_arm,
                pre_window_sessions,
                {
                    arm: ArmLedgerQuietReads(repository)
                    for arm, repository in arm_repositories.items()
                },
                bar_lookup=lambda session: _published_pre_window_bars_lookup(
                    self._bar_repository,
                    session,
                    cutoff=advance_command_at(sessions[0]),
                ),
            )
            if unverified_entry_sessions:
                lines_affected = sum(
                    len(entries[entry_session])
                    for entries in entries_by_arm.values()
                    for entry_session in unverified_entry_sessions
                    if entry_session in entries
                )
                raise PairedTrialRunnerError(
                    "advance_entry_window_skipped",
                    "the advance window starts after a decided entry session"
                    " whose settlement is not provably terminal (no capital"
                    " fill record and no provable no-fill under the locked"
                    " decision table); entry settlements have no catch-up"
                    " semantics, so the replay window must cover every"
                    " unverified entry session",
                    window_start=sessions[0].isoformat(),
                    unverified_entry_sessions=[
                        s.isoformat() for s in unverified_entry_sessions
                    ],
                    earliest_entry_session=unverified_entry_sessions[0].isoformat(),
                    lines_affected=lines_affected,
                )

        bar_for = evidence_backed_bar_for(self._bar_repository, bar_records)
        receipts: dict = {}
        for arm in (TrialArm.CHAMPION, TrialArm.CHALLENGER):
            repository = arm_repositories.get(arm) or open_arm_capital_repository(
                self._capital_trial_root, arm
            )
            initial_holdings = _seed_initial_holdings(
                ArmLedgerQuietReads(repository),
                entries_by_arm[arm],
                window_start=sessions[0],
            )
            driver = SessionLifecycleDriver(
                repository=repository,
                arm=arm.value.lower(),
                scenario=self._market_scenario,
                sessions=sessions,
                entries_by_session=entries_by_arm[arm],
                attribution=self._trial_attribution,
                command_at=advance_command_at,
                send_deadline=advance_send_deadline,
                bar_for=bar_for,
                initial_holdings=initial_holdings,
            )
            result = driver.run()
            if not result.conservation_ok:
                raise PairedTrialRunnerError(
                    "advance_conservation_violation",
                    "the arm ledger failed conservation re-verification",
                    arm=arm.value,
                    details=result.conservation_details[:5],
                )
            receipts[arm] = result

        return MarketAdvanceReceipt(
            trial_id=request.trial_id,
            through_session=request.through_session,
            settlements_by_arm={
                arm.value: len(result.settlements)
                for arm, result in receipts.items()
            },
            conservation_ok_by_arm={
                arm.value: result.conservation_ok
                for arm, result in receipts.items()
            },
            open_at_end_by_arm={
                arm.value: dict(result.open_at_end)
                for arm, result in receipts.items()
            },
        )

    def finalize_missed_sessions(self, trusted_at: datetime) -> tuple[date, ...]:
        """Finalize enrolled-but-undecided sessions as NO_RUN (R26 解锁).

        补记语义: 评估窗口 (enrollment 的 assessment_date) 已过、该 trial
        无决策 pair、spine 无终态的会话 → ``mark_no_run``。幂等: 已有
        终态的会话跳过 (append-only spine 不重复追加)。
        """
        from src.screening.offensive.v3.evidence.session_spine import (
            SessionStatus,
        )

        self._require_unlocked()
        if self._session_spine is None or self._research_program_id is None:
            raise PairedTrialRunnerError(
                "finalize_authority_unavailable",
                "finalize requires the injected session spine and program id",
            )
        if self._trial_id is None:
            # 已决策会话的排除依赖 per-trial pair 查询; 未绑定 trial 的 runner
            # 无法证明任何会话已决策 — fail-closed, 而不是把决策过的会话也
            # 补记 NO_RUN (R36 修复: 此前以 program 查 pair_keys 恒空, 决策
            # 过的会话被静默误标)。
            raise PairedTrialRunnerError(
                "finalize_trial_unbound",
                "finalize requires the runner to be bound to one trial id",
            )
        decided_sessions = {key[1] for key in self._store.pair_keys(self._trial_id)}
        finalized: list[date] = []
        for enrollment in self._session_spine.enrolled_sessions(
            self._research_program_id
        ):
            if enrollment.assessment_date > trusted_at.date():
                continue  # 评估窗口未过 — 不是 missed
            if str(enrollment.signal_session) in decided_sessions:
                continue  # 已有决策 pair
            current = self._session_spine.status(
                self._research_program_id, enrollment.signal_session
            )
            if current is not None and current is not SessionStatus.DATA_UNKNOWN:
                continue  # 已有终态 (含既往 NO_RUN) — 幂等跳过
            self._session_spine.mark_no_run(
                self._research_program_id, enrollment.signal_session
            )
            finalized.append(enrollment.signal_session)
        return tuple(finalized)


def freeze_shared_input(
    *,
    validated: ValidatedRegimeTrialBundle,
    session: date,
    cycle_id: str,
    regime: RegimeObservation,
    trusted_at: datetime,
    trading_schedule: "FrozenTradingSessionSchedule",
    evidence_set_merkle_root: str,
    stage_id: str,
    stage_manifest_hash: str,
    registry_epoch: int,
    trusted_evidence_cutoff: datetime,
) -> ShadowSharedInput:
    """One frozen shared input, identical for both arms (official + replay).

    The single construction is shared by the forward runner and the Task 12
    replay engine so a current-cost replay reproduces the official decision
    bytes exactly.
    """

    return ShadowSharedInput(
        signal_session=session,
        decision_cycle_id=cycle_id,
        trial_manifest_hash=validated.trial_manifest.content_hash(),
        sap_manifest_hash=validated.sap_manifest.content_hash(),
        mode=ExecutionMode.DAILY_BAR_PROXY,
        trusted_evidence_cutoff=trusted_evidence_cutoff,
        evidence_set_merkle_root=evidence_set_merkle_root,
        regime_observation=regime,
        trial_id=validated.trial_manifest.trial_id,
        research_program_id=validated.trial_manifest.research_program_id,
        economic_lineage_id=validated.trial_manifest.economic_lineage_id,
        stage_id=stage_id,
        stage_manifest_hash=stage_manifest_hash,
        trust_bundle_hash=validated.trial_manifest.trust_bundle_hash,
        registry_epoch=registry_epoch,
        trusted_at=trusted_at,
        trading_session_schedule=trading_schedule,
    )


def build_arm_kernel_inputs(
    *,
    validated: ValidatedRegimeTrialBundle,
    shared_input: ShadowSharedInput,
    candidates: tuple[CommittedBtstCandidate, ...],
    champion_capital_checkpoint: ShadowCapitalCheckpoint,
    challenger_capital_checkpoint: ShadowCapitalCheckpoint,
    deadlines: DeadlineContract,
    sizing_config: SizingConfig,
) -> tuple[ShadowKernelInput, ShadowKernelInput]:
    """Build two arm inputs from two independently verified checkpoints.

    Candidates are built exclusively from the producer's SELECTED records;
    every binding is frozen from the record, never synthesized.  Economic
    inputs are explicit: the builder has no single-snapshot shortcut and does
    not manufacture a schedule, deadline or sizing configuration.
    """

    trial = validated.trial_manifest
    raw_candidate_specs: list[tuple[CommittedBtstCandidate, str]] = []
    evidence_bindings: list[CandidateEvidenceBinding] = []
    prices: list[tuple[str, int]] = []
    industries: list[tuple[str, str]] = []
    for committed in candidates:
        record = committed.record
        envelope = record.evidence
        payload = committed.payload
        candidate_id = payload.candidate_id
        raw_candidate_specs.append((committed, candidate_id))
        evidence_bindings.append(
            CandidateEvidenceBinding(
                candidate_id=candidate_id,
                evidence_id=envelope.evidence_id,
                evidence_artifact_hash=record.artifact_hash(),
                evidence_payload_hash=envelope.payload_content_hash,
            )
        )
        prices.append((candidate_id, payload.entry_price_micros))
        if payload.industry_state is BtstCandidateIndustryState.KNOWN:
            assert payload.industry is not None
            industries.append((candidate_id, payload.industry))

    def raw_candidates_for(
        checkpoint: ShadowCapitalCheckpoint,
    ) -> tuple[RawCandidate, ...]:
        snapshot = checkpoint.capital_snapshot
        return tuple(
            RawCandidate(
                candidate_id=candidate_id,
                producer_namespace=committed.record.evidence.subject_producer,
                family_id=BTST_FAMILY,
                economic_lineage_id=trial.economic_lineage_id,
                research_program_id=trial.research_program_id,
                stage_id="stage-1",
                security_id=committed.payload.security_id,
                direction="LONG",
                unscaled_target_gross_cents=(
                    snapshot.as_observed_nav_cents
                    * committed.payload.target_weight_ppm
                    // 1_000_000
                ),
                behavior_fingerprint=(
                    committed.record.evidence.behavior_fingerprint
                ),
                execution_version=committed.record.evidence.execution_version,
                cost_version=committed.record.evidence.cost_version,
                evidence_ids=(),
            )
            for committed, candidate_id in raw_candidate_specs
        )

    champion_raw_candidates = raw_candidates_for(champion_capital_checkpoint)
    challenger_raw_candidates = raw_candidates_for(challenger_capital_checkpoint)
    champion_binding = BaselineShadowPolicyBinding(
        source_kind=ShadowPolicySourceKind.BASELINE_POLICY_ACTIVATION,
        baseline_policy_activation_hash=trial.baseline_policy_activation_hash,
        policy_snapshot_hash=validated.baseline_policy.content_hash(),
        policy_fingerprint=validated.baseline_policy.policy_fingerprint,
    )
    challenger_binding = TargetShadowPolicyBinding(
        source_kind=ShadowPolicySourceKind.TARGET_POLICY_REGISTRATION,
        target_policy_registration_hash=trial.target_policy_snapshot_registration_hash,
        policy_snapshot_hash=validated.target_policy.content_hash(),
        policy_fingerprint=validated.target_policy.policy_fingerprint,
    )
    champion_input = ShadowKernelInput(
        portfolio_id=champion_capital_checkpoint.portfolio_id,
        arm=TrialArm.CHAMPION,
        shared=shared_input,
        policy_snapshot=validated.baseline_policy,
        shadow_policy_binding=champion_binding,
        capital_checkpoint=champion_capital_checkpoint,
        deadlines=deadlines,
        sizing_config=sizing_config,
        candidate_evidence_bindings=tuple(evidence_bindings),
        raw_candidates=champion_raw_candidates,
        price_micros_by_candidate=tuple(prices),
        industry_by_candidate=tuple(industries),
    )
    challenger_input = ShadowKernelInput(
        portfolio_id=challenger_capital_checkpoint.portfolio_id,
        arm=TrialArm.CHALLENGER,
        shared=shared_input,
        policy_snapshot=validated.target_policy,
        shadow_policy_binding=challenger_binding,
        capital_checkpoint=challenger_capital_checkpoint,
        deadlines=deadlines,
        sizing_config=sizing_config,
        candidate_evidence_bindings=tuple(evidence_bindings),
        raw_candidates=challenger_raw_candidates,
        price_micros_by_candidate=tuple(prices),
        industry_by_candidate=tuple(industries),
    )
    return champion_input, challenger_input


def build_pair_records(
    *,
    trial_id: str,
    session: date,
    cycle_id: str,
    shared_input: ShadowSharedInput,
    regime_hash: str,
    champion: ArmDecision,
    challenger: ArmDecision,
    trusted_at: datetime,
    champion_input: ShadowKernelInput,
    challenger_input: ShadowKernelInput,
) -> tuple[TrialArmDecisionRecord, TrialArmDecisionRecord]:
    """The two immutable arm records of one committed pair (official + replay).

    ``created_at`` freezes the same trusted instant both paths consume so a
    current-cost replay reproduces the official rows byte-for-byte.
    """

    for expected_arm, kernel_input, decision in (
        (TrialArm.CHAMPION, champion_input, champion),
        (TrialArm.CHALLENGER, challenger_input, challenger),
    ):
        checkpoint = kernel_input.capital_checkpoint
        if kernel_input.arm is not expected_arm:
            raise PairedTrialRunnerError(
                "economic_input_authority_unavailable",
                "kernel input is bound to the wrong trial arm",
            )
        if kernel_input.shared.content_hash() != shared_input.content_hash():
            raise PairedTrialRunnerError(
                "economic_input_authority_unavailable",
                "kernel input does not bind the committed shared external facts",
            )
        if checkpoint.arm is not expected_arm:
            raise PairedTrialRunnerError(
                "economic_input_authority_unavailable",
                "arm capital checkpoint is bound to the wrong trial arm",
            )
        if (
            checkpoint.trial_id != shared_input.trial_id
            or checkpoint.portfolio_id != kernel_input.portfolio_id
            or checkpoint.mode is not shared_input.mode
        ):
            raise PairedTrialRunnerError(
                "economic_input_authority_unavailable",
                "arm capital checkpoint does not match the shared trial identity",
            )
        if decision.kernel_input_hash != kernel_input.content_hash():
            raise PairedTrialRunnerError(
                "economic_input_authority_unavailable",
                "decision does not bind the exact arm kernel input",
            )

    shared_hash = shared_input.content_hash()
    return (
        TrialArmDecisionRecord(
            trial_id=trial_id,
            signal_session=session,
            decision_cycle_id=cycle_id,
            arm=TrialArm.CHAMPION,
            shared_input_hash=shared_hash,
            arm_policy_fingerprint=(
                champion.shadow_policy_binding.policy_fingerprint
                if isinstance(champion, ShadowDecision)
                else None
            ),
            arm_capital_checkpoint_hash=(
                champion_input.capital_checkpoint.content_hash()
            ),
            regime_observation_hash=regime_hash,
            decision=champion,
            created_at=trusted_at,
            artifact_hash=champion.content_hash(),
        ),
        TrialArmDecisionRecord(
            trial_id=trial_id,
            signal_session=session,
            decision_cycle_id=cycle_id,
            arm=TrialArm.CHALLENGER,
            shared_input_hash=shared_hash,
            arm_policy_fingerprint=(
                challenger.shadow_policy_binding.policy_fingerprint
                if isinstance(challenger, ShadowDecision)
                else None
            ),
            arm_capital_checkpoint_hash=(
                challenger_input.capital_checkpoint.content_hash()
            ),
            regime_observation_hash=regime_hash,
            decision=challenger,
            created_at=trusted_at,
            artifact_hash=challenger.content_hash(),
        ),
    )


__all__ = [
    "CommittedBtstCandidate",
    "ForwardPairedTrialRunner",
    "PairedSignalReceipt",
    "PairedTrialRunnerError",
    "REGIME_EVIDENCE_ID",
    "SignalSessionRequest",
    "build_arm_kernel_inputs",
    "build_pair_records",
    "classify_pair_session",
    "freeze_shared_input",
]
