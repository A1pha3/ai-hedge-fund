"""Plan 05 Task 7: lifecycle-first ``--daily-action`` shadow observer.

Current safety state: capital/lifecycle/snapshot reads remain available, but
the shadow-decision pipeline fails before evidence, producer, kernel or
persister calls with ``economic_input_authority_unavailable``.  It stays
disabled until a store-owned exchange schedule and complete
``ShadowKernelInput`` are wired to ``decide_shadow``.  This module does not
construct ``ShadowDecision`` and cannot publish a current v4 artifact.

The detailed pipeline description below is retained as historical Plan 05
context only; the fail-closed state above is authoritative.

-------------------------------------------------------------------------------
status 值域 (每步独立)
-------------------------------------------------------------------------------
- ``"ok"``      — 该步被尝试且未抛异常 (lifecycle: 全部 exit_state 查询返回,
                  含 None 结果 — 无 mandate 不是失败; capital: 只读投影读取成功,
                  含 stale snapshot — 新鲜度是 kernel 层判定, 不是读失败;
                  snapshot: ``result.snapshot is not None``)。
- ``"failed"``  — 该步被尝试但抛异常 (snapshot 另有 loader 返回 None 的失败形态)。
- ``"skipped"`` — 该步未被尝试: OFF 模式 (四步全 skipped), 或前置输入缺失
                  (lifecycle 缺 capital → ``"no_capital"``; shadow 管线缺
                  snapshot/capital → ``"no_snapshot"`` / ``"no_capital"``;
                  投影 mode 非 SHADOW → ``"not_shadow_mode"``)。
- ``shadow_decision_status`` 额外值 ``"no_signal"`` — shadow 管线完整运行,
  但 kernel 返回 ``NoTradeDecision`` (含 no-candidates 的 ``NO_SIGNAL`` /
  stale capital 的 ``STALE_CAPITAL`` 等), **不构造空 ShadowDecision**
  (``ShadowDecision.counterfactual_lines`` min_length=1, contracts/decision.py:
  1072 — 空行不合法), 不调用 persister。

``no_signal`` vs no_trade 语义: ``shadow_decision_status == "no_signal"`` 统一
表示 NoTrade 形态; ``no_trade_reason: BlockReason | None`` 携带 kernel 返回的
typed reason (``NO_SIGNAL`` / ``STALE_CAPITAL`` / ``CAPACITY_EXHAUSTED`` ...),
以区分"扫描无候选"与"资本失效被拒"。持久化成功 (status "ok") 时
``no_trade_reason`` 恒 ``None``。

-------------------------------------------------------------------------------
run() 步序与依赖 (完整语义见 run() docstring)
-------------------------------------------------------------------------------
1. ``mode = mode_provider()``; OFF → 四步全 ``"skipped"``、零调用。
2. 非 OFF → 依序独立执行 (每步 try/except, 前步失败不阻止后步, 后步失败不回填
   前步):
   a. ``capital``  — 只读资本投影 ``capital_reader.risk_snapshot(portfolio_id,
      as_of)``, ``as_of = datetime.combine(signal_date, time(15, 0),
      tzinfo=timezone.utc)`` (AutoFlow outcome 同款约定)。成功 →
      ``capital_projection`` 记录该快照; 失败 → ``"failed"``,
      ``capital_projection`` 为 None。**只读**: 绝不调用
      ``confirm_observed_nav`` 等任何写面 (capital 投影是 quiet 读)。
   b. ``lifecycle`` — 第一步状态步, 恒在 snapshot 加载/BTST scan **之前**:
      对 capital snapshot 的每个 position 调
      ``lifecycle_reader.exit_state(position_lineage_id, economic_lot_id)``
      (scheduler/lifecycle call before snapshot/scan 契约)。positions 为空 →
      ``"ok"`` 且零调用。capital 失败 → ``"skipped"`` + reason ``"no_capital"``。
   c. ``snapshot``  — ``snapshot_loader(signal_date, reports_dir=, data_dir=)``
      同 AutoFlow 签名; ``result.snapshot is None`` → ``"failed"`` + reason =
      ``global_reason`` (为空时 ``"snapshot_unavailable"``); 异常 →
      ``"failed"`` + ``f"{type(exc).__name__}: {exc}"``。独立于 capital。
3. shadow 管线 (仅 ``RuntimeMode.SHADOW``; 其他非 OFF 模式 → ``"skipped"`` +
   reason ``"not_shadow_mode"``, 不调用 producer/kernel/persister/v2):
   前置条件 = snapshot 与 capital 均可用; snapshot 缺失 → ``"skipped"`` +
   ``"no_snapshot"``; 否则 capital 缺失 → ``"skipped"`` + ``"no_capital"``。
   管线内部依序 (spec Step 3 顺序):
   a. ``evidence`` — frozen evidence 加载: 对 ``evidence_ids`` 每个 id 调
      ``evidence_store.active_revision(evidence_id, cutoff=trusted_evidence_cutoff)``。
      ``EvidenceStoreError`` (含 ``evidence_not_committed_before_cutoff``,
      repository.py:609 missed window) → ``failure_reason["evidence"]`` 记录
      ``f"{type(exc).__name__}: {exc}"``, **管线继续** (kernel 无该证据输入);
      返回 ``None`` → benign miss (宽容读, 不记失败); 其他异常同前者处理。
      任何证据失败都不改变 shadow_decision_status。
   b. ``producer`` — ``btst_producer.produce_and_publish(snapshot)`` → records;
      异常 → ``shadow_decision_status "failed"`` + ``failure_reason["producer"]``;
      空 tuple 合法 (kernel 是 no-signal 的唯一权威, flow 层不做空候选短路)。
   c. ``kernel``   — 构造 ``KernelInput`` (portfolio_id / signal_session=
      signal_date / decision_cycle_id 确定性 / mode=policy_activation.mode /
      policy_activation / envelope / capital / deadlines /
      trusted_evidence_cutoff / raw_candidates + price/industry 由 GREEN 从
      producer records 与 snapshot 派生), 调 ``kernel.decide(kernel_input,
      trusted_at=trusted_at)``。异常 → ``"failed"`` + ``failure_reason["kernel"]``。
      ``NoTradeDecision`` → ``"no_signal"`` + ``no_trade_reason``; 不 persist。
      ``PortfolioDecision`` → 构造 ``ShadowDecision`` (确定性
      ``shadow_decision_id``, 见下)。
   d. ``persist``  — ``shadow_persister.publish_shadow_decision(decision)`` →
      str; 异常 → ``"failed"`` + ``failure_reason["persist"]``; 成功 →
      ``"ok"`` + ``shadow_decision_id`` = 返回的 id。
4. ``v2_comparison`` — 仅当 ShadowDecision 已产生 且 ``v2_plans_reader`` 注入:
   对比 v3 shadow lines vs v2 plans (ticker 匹配, 见 discrepancy 形状); 异常 →
   ``failure_reason["v2_comparison"]`` + ``discrepancy`` 为空。无 shadow decision
   或无 reader → 不对比, ``discrepancy`` 为空, 不记 reason。

-------------------------------------------------------------------------------
确定性契约 (repeat run 幂等, test 7)
-------------------------------------------------------------------------------
- ``decision_cycle_id = f"daily-action-{signal_date.isoformat()}"`` (kernel input
  与 counterfactual 共享)。
- ``shadow_decision_id = f"shadow-{decision_cycle_id}"`` — 同 signal_date 二次
  run 产出同一 id (确定性, 不依赖 store 序列); persister 返回的 id 即为
  result 的 ``shadow_decision_id``。

-------------------------------------------------------------------------------
discrepancy 形状 (v2↔v3 对比)
-------------------------------------------------------------------------------
``Mapping[str, str]``, key = 归一化 ticker: v3 ``security_id`` 去掉交易所后缀
(``.SH`` / ``.SZ`` / ``.BJ``) 后与 v2 6 位 ticker 比较。value:
- ``"v2_only"`` — v2 有 entry_planned 计划 (ticker) 但 v3 shadow lines 无对应;
- ``"v3_only"`` — v3 shadow line 有 security_id 但 v2 plans 无对应。
(本 plan 的 v2 对比面是 ``ActionItem(trade_id/ticker/reason/...)``, 无数量字段,
故不比较数量; 形状是 ``Mapping[str, str]``, GREEN 可扩展值域。)

v2 plans 注入: ``v2_plans_reader: Callable[[date], tuple[Any, ...]] | None`` —
返回当日 v2 计划对象 (只需暴露 ``.ticker`` 属性; 真实 ``ActionItem`` /
``DailyActionV2Run.plans`` 均满足)。``None`` → 不对比。

-------------------------------------------------------------------------------
byte-identical 契约 (v2 ledger 零写)
-------------------------------------------------------------------------------
本编排**绝不写 v2 ledger** (``data/paper_trading_v2/ledger.sqlite3`` 只由
``LedgerRepository`` 写): 全流程唯一的持久化出口是注入的
``shadow_persister`` (v3 evidence DB); capital 读取是 quiet 读, snapshot 加载
是只读校验, lifecycle 查询是只读 query。``data_dir`` 目录下除调用方自建文件外
不被本 flow 触碰。

-------------------------------------------------------------------------------
failure_reason keys 与值格式
-------------------------------------------------------------------------------
key = 步名: ``"lifecycle" | "capital" | "snapshot" | "evidence" | "producer" |
"kernel" | "persist" | "shadow_decision" | "v2_comparison" |
"economic_input_authority"``。当前 fail-closed shadow 管线只写
``"economic_input_authority"`` (值为 ``economic_input_authority_unavailable:
...``); 其余步名是历史 Plan 05 管线重新接线后才会再次出现的键。
- 异常: ``f"{type(exc).__name__}: {exc}"`` (异常 ``__str__`` 携带稳定 error
  code, 如 ``EvidenceStoreError`` 的 ``evidence_not_committed_before_cutoff``)。
- snapshot 加载失败: ``global_reason`` (为空时 ``"snapshot_unavailable"``)。
- skip: ``"no_capital"`` / ``"no_snapshot"`` / ``"not_shadow_mode"`` (仅
  ``"shadow_decision"`` 键持有 skip reason)。
ok 步无条目; ``"no_signal"`` 不是失败 (合法 NoTrade 形态), 不记条目;
OFF 模式整体无条目。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timezone
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Literal, Mapping, Protocol

from src.screening.offensive.daily_action_snapshot import (
    load_verified_daily_action_snapshot,
    VerifiedDailyActionSnapshot,
    VerifiedSnapshotResult,
)
from src.screening.offensive.v3.contracts import ExecutionMode
from src.screening.offensive.v3.contracts.capital import CapitalRiskSnapshot
from src.screening.offensive.v3.contracts.evidence import (
    EvidenceRecord,
    SignalEvidence,
)
from src.screening.offensive.v3.kernel.models import (
    BlockReason,
    KernelInput,
)
from src.screening.offensive.v3.policy.models import RuntimeMode


class LifecycleReaderPort(Protocol):
    """鸭子类型 lifecycle reader — 只读 query, 不驱动 lifecycle。

    真实实现 ``LifecycleScheduler.exit_state`` (services/lifecycle_scheduler.py
    :420) 或 ``CapitalGatewayApi.exit_state``; 无 mandate 返回 None。
    """

    def exit_state(
        self, position_lineage_id: str, economic_lot_id: str
    ) -> Any: ...


class CapitalReaderPort(Protocol):
    """鸭子类型只读资本 reader — ``CapitalGatewayApi.risk_snapshot`` 同签名。

    quiet 读: 绝不增长 stream/capital version; 本 flow 也绝不调用任何写面。
    """

    def risk_snapshot(self, portfolio_id: str, as_of: datetime) -> CapitalRiskSnapshot: ...


class SnapshotLoaderPort(Protocol):
    """注入的快照加载器 — 与 ``load_verified_daily_action_snapshot`` 同签名。"""

    def __call__(
        self, signal_date: date, *, reports_dir: Path, data_dir: Path
    ) -> VerifiedSnapshotResult: ...


class BtstProducerPort(Protocol):
    """鸭子类型 BTST producer — flow 只调用 ``produce_and_publish``。

    真实实现 ``BtstProducerApi``; 测试注入轻量 fake 控制成功/失败/空产出。
    """

    def produce_and_publish(
        self, snapshot: VerifiedDailyActionSnapshot
    ) -> tuple[EvidenceRecord[SignalEvidence], ...]: ...


class EvidenceStorePort(Protocol):
    """鸭子类型 PIT 证据读取器 — ``active_revision`` 宽容读。

    真实实现 ``EvidenceRepository.active_revision`` (repository.py:596) 对
    missed window 抛 ``EvidenceStoreError("evidence_not_committed_before_cutoff")``;
    ``BtstProducerApi.active_signal`` (btst_producer_api.py:106) 示范宽容封装
    (抛错 → None)。flow 对两者都容忍: None = benign miss, 异常 = 记 reason 继续。
    """

    def active_revision(self, evidence_id: str, cutoff: datetime) -> Any: ...


class KernelPort(Protocol):
    """鸭子类型 kernel — flow 只调用 ``decide``。

    真实实现 ``GrowthKernel.decide`` (kernel/decide.py:46, 纯函数)。
    """

    def decide(
        self, kernel_input: KernelInput, *, trusted_at: datetime
    ) -> Any: ...


class ShadowPersisterPort(Protocol):
    """鸭子类型 ShadowDecision 持久化器 — 返回持久化后的 id (str)。"""

    def publish_shadow_decision(self, decision: Any) -> str: ...


@dataclass(frozen=True)
class DailyActionFlowResult:
    """一次 ``DailyActionFlow.run`` 的四步独立结果汇总。

    字段:
    - ``lifecycle_status`` / ``snapshot_status`` / ``capital_status`` /
      ``shadow_decision_status``: 值域与语义见模块 docstring;
      ``shadow_decision_status`` 额外含 ``"no_signal"`` (NoTrade 形态)。
    - ``execution_authority``: 恒 ``"none"`` — 本编排永不产生授权。
    - ``shadow_decision_id``: 持久化成功时 persister 返回的 id, 否则 None。
    - ``no_trade_reason``: status == "no_signal" 时 kernel 的 typed
      ``BlockReason`` (区分 NO_SIGNAL / STALE_CAPITAL / ...), 否则 None。
    - ``discrepancy``: v2↔v3 对比差异 (形状见模块 docstring)。
    - ``capital_projection``: 只读资本投影快照 (读成功时), 否则 None。
    - ``failure_reason``: 失败/跳过步的机器可读原因 (key = 步名)。
    """

    lifecycle_status: Literal["ok", "failed", "skipped"]
    snapshot_status: Literal["ok", "failed", "skipped"]
    capital_status: Literal["ok", "failed", "skipped"]
    shadow_decision_status: Literal["ok", "failed", "no_signal", "skipped"]
    execution_authority: Literal["none"] = "none"
    shadow_decision_id: str | None = None
    no_trade_reason: BlockReason | None = None
    discrepancy: Mapping[str, str] = field(
        default_factory=lambda: MappingProxyType({})
    )
    capital_projection: CapitalRiskSnapshot | None = None
    failure_reason: Mapping[str, str] = field(
        default_factory=lambda: MappingProxyType({})
    )


class DailyActionFlow:
    """--daily-action lifecycle-first 编排: 只读投影 + 影子决策 + v2 对比。"""

    def __init__(
        self,
        *,
        lifecycle_reader: LifecycleReaderPort,
        capital_reader: CapitalReaderPort,
        snapshot_loader: SnapshotLoaderPort | None = None,
        btst_producer: BtstProducerPort,
        evidence_store: EvidenceStorePort,
        kernel: KernelPort,
        shadow_persister: ShadowPersisterPort,
        mode_provider: Callable[[], RuntimeMode],
        policy_activation: Any,
        policy_snapshot: Any,
        envelope: Any,
        portfolio_id: str,
        deadlines: Any,
        trusted_evidence_cutoff: datetime,
        evidence_ids: tuple[str, ...] = (),
        v2_plans_reader: Callable[[date], tuple[Any, ...]] | None = None,
        program: str = "daily-action",
    ) -> None:
        """构造 DailyActionFlow (完整语义见模块 docstring)。

        Args:
            lifecycle_reader: 鸭子类型 exit 义务 reader (只读 query)。
            capital_reader: 鸭子类型只读资本 reader (quiet 读)。
            snapshot_loader: 快照加载器 (同 ``load_verified_daily_action_snapshot``
                签名); 默认 ``None`` → 使用真实函数。
            btst_producer: 鸭子类型 BTST producer (只调用
                ``produce_and_publish``)。
            evidence_store: 鸭子类型 PIT 证据读取器 (``active_revision``
                宽容读)。
            kernel: 鸭子类型 kernel (只调用 ``decide``; 真实
                ``GrowthKernel(sizing_config)``)。
            shadow_persister: 鸭子类型 ShadowDecision 持久化器
                (``publish_shadow_decision(decision) -> str``)。
            mode_provider: 每次 ``run`` 最先读取的 runtime_mode 投影。
            policy_activation: 传给 kernel 的 ``PolicyActivation`` (来自
                policy snapshot)。
            policy_snapshot: 传给 kernel 的显式 ``PolicySnapshot`` (Step 5:
                可执行路径验证 ``policy_activation.policy_snapshot_hash ==
                policy_snapshot.content_hash()`` 后才映射 constraints)。
            envelope: 传给 kernel 的 ``CapitalAuthorizationEnvelope``。
            portfolio_id: 本 flow 治理的 portfolio。
            deadlines: 传给 kernel 的 ``DeadlineContract`` (kernel input)。
            trusted_evidence_cutoff: kernel input 的 PIT 证据截止时刻; 同时是
                ``evidence_store.active_revision`` 的 cutoff。
            evidence_ids: 本次运行要加载的 frozen evidence ids (通常来自
                快照的候选证据, 由调用方注入)。
            v2_plans_reader: 返回当日 v2 计划对象 tuple 的只读 reader
                (元素只需 ``.ticker``; ``None`` → 不对比)。
            program: 本 flow 的 program 标签, 默认 ``"daily-action"``。
        """
        self._lifecycle_reader = lifecycle_reader
        self._capital_reader = capital_reader
        self._snapshot_loader = (
            snapshot_loader or load_verified_daily_action_snapshot
        )
        self._btst_producer = btst_producer
        self._evidence_store = evidence_store
        self._kernel = kernel
        self._shadow_persister = shadow_persister
        self._mode_provider = mode_provider
        self._policy_activation = policy_activation
        self._policy_snapshot = policy_snapshot
        self._envelope = envelope
        self._portfolio_id = portfolio_id
        self._deadlines = deadlines
        self._trusted_evidence_cutoff = trusted_evidence_cutoff
        self._evidence_ids = evidence_ids
        self._v2_plans_reader = v2_plans_reader
        self._program = program

    def run(
        self,
        *,
        signal_date: date,
        reports_dir: Path,
        data_dir: Path,
        trusted_at: datetime,
    ) -> DailyActionFlowResult:
        """按投影 mode 依序独立执行 (完整语义见模块 docstring)。

        1. ``mode = mode_provider()``; ``OFF`` → 返回四步全 ``"skipped"``、
           ``failure_reason`` 为空、零调用的结果。
        2. 非 OFF → 依序独立执行:
           - ``capital``: ``capital_reader.risk_snapshot(portfolio_id, as_of)``,
             ``as_of = datetime.combine(signal_date, time(15, 0),
             tzinfo=timezone.utc)``; 成功 → ``capital_projection`` 记录快照;
             异常 → ``"failed"``。只读, 绝不调用任何写面。
           - ``lifecycle``: 对 capital snapshot 的每个 position 调
             ``lifecycle_reader.exit_state(lineage, lot)`` (第一步状态步,
             恒在 snapshot 加载/BTST scan 之前); capital 失败 → ``"skipped"``
             + reason ``"no_capital"``。
           - ``snapshot``: ``snapshot_loader(signal_date, reports_dir=,
             data_dir=)``; ``snapshot is None`` → ``"failed"`` + ``global_reason``;
             异常 → ``"failed"``。
           - shadow 管线 (仅 ``SHADOW`` 模式): 前置 = snapshot 与 capital 均
             可用 (缺失 → ``"skipped"`` + ``"no_snapshot"`` / ``"no_capital"``)。
             依序: frozen evidence 加载 (失败记 reason, 管线继续) →
             ``btst_producer.produce_and_publish(snapshot)`` (失败 → ``"failed"``
             + reason) → 构造 ``KernelInput`` 并 ``kernel.decide(kernel_input,
             trusted_at=trusted_at)`` (``NoTradeDecision`` → ``"no_signal"`` +
             ``no_trade_reason``, 不构造空 ShadowDecision; ``PortfolioDecision``
             → 构造确定性 ``ShadowDecision``) →
             ``shadow_persister.publish_shadow_decision(decision)`` (成功 →
             ``"ok"`` + id)。
           - ``v2_comparison``: 仅当 ShadowDecision 已产生且注入
             ``v2_plans_reader`` 时对比 (归一化 ticker; 差异形状见模块
             docstring); 异常 → ``failure_reason["v2_comparison"]``。
        3. 其他非 OFF 模式 (``BTST_CANARY`` / ``AUTHORITATIVE``):
           capital/lifecycle/snapshot 照常执行 (只读观测), shadow 管线
           ``"skipped"`` + reason ``"not_shadow_mode"``。
        4. 各步之间无任何回滚; ``execution_authority`` 恒 ``"none"``;
           绝不写 v2 ledger (byte-identical 契约)。
        """
        mode = self._mode_provider()
        if mode is RuntimeMode.OFF:
            return DailyActionFlowResult(
                lifecycle_status="skipped",
                snapshot_status="skipped",
                capital_status="skipped",
                shadow_decision_status="skipped",
            )
        reasons: dict[str, str] = {}
        lifecycle_status: Literal["ok", "failed", "skipped"]
        snapshot_status: Literal["ok", "failed", "skipped"]
        capital_status: Literal["ok", "failed", "skipped"]
        shadow_decision_status: Literal[
            "ok", "failed", "no_signal", "skipped"
        ]

        # -- a. capital 只读投影 (quiet 读, 不增长 version) -------------------
        capital: CapitalRiskSnapshot | None = None
        as_of = datetime.combine(signal_date, time(15, 0), tzinfo=timezone.utc)
        try:
            capital = self._capital_reader.risk_snapshot(
                self._portfolio_id, as_of
            )
        except Exception as exc:
            capital_status = "failed"
            reasons["capital"] = f"{type(exc).__name__}: {exc}"
        else:
            capital_status = "ok"

        # -- b. lifecycle 义务查询 (第一步状态步, 恒先于 snapshot/scan) -------
        if capital is None:
            lifecycle_status = "skipped"
            reasons["lifecycle"] = "no_capital"
        else:
            try:
                for position in capital.positions:
                    self._lifecycle_reader.exit_state(
                        position.position_lineage_id,
                        position.economic_lot_id,
                    )
            except Exception as exc:
                lifecycle_status = "failed"
                reasons["lifecycle"] = f"{type(exc).__name__}: {exc}"
            else:
                lifecycle_status = "ok"

        # -- c. snapshot 加载 (独立于 capital) --------------------------------
        snapshot: VerifiedDailyActionSnapshot | None = None
        try:
            loaded = self._snapshot_loader(
                signal_date, reports_dir=reports_dir, data_dir=data_dir
            )
        except Exception as exc:
            snapshot_status = "failed"
            reasons["snapshot"] = f"{type(exc).__name__}: {exc}"
        else:
            if loaded.snapshot is None:
                snapshot_status = "failed"
                reasons["snapshot"] = (
                    loaded.global_reason or "snapshot_unavailable"
                )
            else:
                snapshot_status = "ok"
                snapshot = loaded.snapshot

        # -- shadow 管线 (仅 SHADOW 模式; 每步独立, 无回滚) -------------------
        shadow_decision_id: str | None = None
        no_trade_reason: BlockReason | None = None
        discrepancy: Mapping[str, str] = MappingProxyType({})
        decision_cycle_id = f"daily-action-{signal_date.isoformat()}"
        if mode is not RuntimeMode.SHADOW:
            shadow_decision_status = "skipped"
            reasons["shadow_decision"] = "not_shadow_mode"
        elif snapshot is None:
            shadow_decision_status = "skipped"
            reasons["shadow_decision"] = "no_snapshot"
        elif capital is None:
            shadow_decision_status = "skipped"
            reasons["shadow_decision"] = "no_capital"
        else:
            shadow_decision_status, shadow_decision_id, no_trade_reason, discrepancy = (
                self._run_shadow_pipeline(
                    snapshot=snapshot,
                    capital=capital,
                    decision_cycle_id=decision_cycle_id,
                    trusted_at=trusted_at,
                    reasons=reasons,
                    signal_date=signal_date,
                )
            )

        return DailyActionFlowResult(
            lifecycle_status=lifecycle_status,
            snapshot_status=snapshot_status,
            capital_status=capital_status,
            shadow_decision_status=shadow_decision_status,
            shadow_decision_id=shadow_decision_id,
            no_trade_reason=no_trade_reason,
            discrepancy=discrepancy,
            capital_projection=capital,
            failure_reason=MappingProxyType(reasons),
        )

    # -- 私有管线 ------------------------------------------------ ------------

    def _run_shadow_pipeline(
        self,
        *,
        snapshot: VerifiedDailyActionSnapshot,
        capital: CapitalRiskSnapshot,
        decision_cycle_id: str,
        trusted_at: datetime,
        reasons: dict[str, str],
        signal_date: date,
    ) -> tuple[
        Literal["ok", "failed", "no_signal", "skipped"],
        str | None,
        BlockReason | None,
        Mapping[str, str],
    ]:
        """Fail closed until a store-owned schedule can feed ``decide_shadow``.

        The legacy path projected an executable ``PortfolioDecision`` into a
        shadow artifact with natural calendar arithmetic.  It must not publish
        evidence or call the producer/kernel/persister while the authoritative
        schedule and ``ShadowKernelInput`` wiring are unavailable.
        """
        reasons["economic_input_authority"] = (
            "economic_input_authority_unavailable: store-owned trading schedule "
            "and decide_shadow wiring are not implemented"
        )
        return "failed", None, None, MappingProxyType({})

    def _authorized_grant(self) -> Any:
        """Envelope 中第一个 btst 授权 grant (admission 的匹配主体)。

        与 ``admit_candidates`` 的 ADMITTED 判定同源 (subject_producer=btst
        且 family 匹配); 无 btst grant 时取 grants[0] 兜底。kernel 候选与
        ShadowDecision header/line 共享同一 grant, 保证 provenance 一致。
        """
        for grant in self._envelope.lineage_grants:
            if grant.subject_producer == "btst":
                return grant
        return self._envelope.lineage_grants[0]


__all__ = ["DailyActionFlow", "DailyActionFlowResult"]
