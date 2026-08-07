"""Plan 05 Task 7: DailyActionFlow — --daily-action lifecycle-first 编排。

一次 ``run`` 产出一份 ``DailyActionFlowResult``: 只读资本投影 + lifecycle
义务查询 + 已验证快照加载 + 影子决策 (BTST producer → GrowthKernel → 持久化
``ShadowDecision``) + v2↔v3 对比差异报告。本编排**只生产 ShadowDecision /
discrepancy 报告 / 只读投影 — 绝不产生任何 v3 可执行授权**
(``execution_authority`` 恒 ``"none"``, 镜像 ``ShadowDecision.execution_authority:
Literal["NONE"]``, contracts/decision.py:1077)。

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
"kernel" | "persist" | "shadow_decision" | "v2_comparison"``。
- 异常: ``f"{type(exc).__name__}: {exc}"`` (异常 ``__str__`` 携带稳定 error
  code, 如 ``EvidenceStoreError`` 的 ``evidence_not_committed_before_cutoff``)。
- snapshot 加载失败: ``global_reason`` (为空时 ``"snapshot_unavailable"``)。
- skip: ``"no_capital"`` / ``"no_snapshot"`` / ``"not_shadow_mode"`` (仅
  ``"shadow_decision"`` 键持有 skip reason)。
ok 步无条目; ``"no_signal"`` 不是失败 (合法 NoTrade 形态), 不记条目;
OFF 模式整体无条目。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Literal, Mapping, Protocol

from src.screening.offensive.daily_action_snapshot import (
    load_verified_daily_action_snapshot,
    VerifiedDailyActionSnapshot,
    VerifiedSnapshotResult,
)
from src.screening.offensive.v3.contracts import (
    ArtifactKind,
    ExecutionMode,
)
from src.screening.offensive.v3.contracts.base import SignalStage
from src.screening.offensive.v3.contracts.capital import CapitalRiskSnapshot
from src.screening.offensive.v3.contracts.decision import (
    CounterfactualDecisionKey,
    ShadowDecision,
    ShadowIssuerBinding,
    ShadowOrderLine,
    ShadowStageBinding,
)
from src.screening.offensive.v3.contracts.evidence import (
    EvidenceRecord,
    SignalEvidence,
)
from src.screening.offensive.v3.kernel.models import (
    BlockReason,
    KernelInput,
    NoTradeDecision,
    PortfolioDecision,
    PortfolioDecisionLine,
    RawCandidate,
)
from src.screening.offensive.v3.kernel.sizing import LOT_UNITS, MICROS_PER_CENT
from src.screening.offensive.v3.policy.models import RuntimeMode

_SECURITY_SUFFIXES = (".SH", ".SZ", ".BJ")
"""v2 ticker 归一化: 去掉 v3 security_id 的交易所后缀再与 v2 6 位 ticker 比较。"""

_INDUSTRY_UNKNOWN = "unknown"
"""快照无行业标识符 (只有 industry_day_pct float) 时的保守共享 industry 桶。

kernel sizing 按 industry key 聚合执行 per_industry_gross_cap; 快照不携带
行业标识, 若用 float pct 当 key 会把每个候选分成独立桶、静默绕过该 cap。
共享桶使 per_industry cap 保守地作用于全体候选 (等效于最严约束)。"""


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
        """SHADOW 模式下的证据加载 → BTST scan → kernel → ShadowDecision 持久化。

        依序执行, 每步独立 try/except: evidence 失败记 reason 后管线继续,
        producer/kernel/persist 失败则中止后续步 (status "failed")。
        """
        # a. frozen evidence 加载 (宽容: None = benign miss, 异常 = 记 reason 继续)
        for evidence_id in self._evidence_ids:
            try:
                self._evidence_store.active_revision(
                    evidence_id, self._trusted_evidence_cutoff
                )
            except Exception as exc:
                reasons["evidence"] = f"{type(exc).__name__}: {exc}"

        # b. BTST producer (kernel 是 no-signal 的唯一权威, 空候选也照送)
        try:
            records = self._btst_producer.produce_and_publish(snapshot)
        except Exception as exc:
            reasons["producer"] = f"{type(exc).__name__}: {exc}"
            return "failed", None, None, MappingProxyType({})

        # c. kernel 决策 (含 KernelInput 与 ShadowDecision 构造, 同属一步)
        try:
            kernel_input = self._build_kernel_input(
                snapshot=snapshot,
                capital=capital,
                decision_cycle_id=decision_cycle_id,
                records=records,
            )
            decision = self._kernel.decide(
                kernel_input, trusted_at=trusted_at
            )
            if isinstance(decision, NoTradeDecision):
                # NoTrade 形态: 绝不构造/持久化空 ShadowDecision
                # (min_length=1 契约), 不调用 persister。
                return (
                    "no_signal",
                    None,
                    decision.reason,
                    MappingProxyType({}),
                )
            # 确定性 id: 同 signal_date 二次 run 产出同一 id (不依赖 store 序列)。
            shadow_decision_id = f"shadow-{decision_cycle_id}"
            shadow_decision = self._build_shadow_decision(
                decision=decision,
                snapshot=snapshot,
                decision_cycle_id=decision_cycle_id,
                shadow_decision_id=shadow_decision_id,
                trusted_at=trusted_at,
                capital=capital,
            )
        except Exception as exc:
            reasons["kernel"] = f"{type(exc).__name__}: {exc}"
            return "failed", None, None, MappingProxyType({})

        # d. ShadowDecision 持久化
        try:
            persisted = self._shadow_persister.publish_shadow_decision(
                shadow_decision
            )
        except Exception as exc:
            reasons["persist"] = f"{type(exc).__name__}: {exc}"
            return "failed", None, None, MappingProxyType({})

        # e. v2 对比 (仅当注入 v2 plans reader 时)
        discrepancy: Mapping[str, str] = MappingProxyType({})
        if self._v2_plans_reader is not None:
            try:
                v2_plans = self._v2_plans_reader(signal_date)
                discrepancy = MappingProxyType(
                    self._compare_v2_plans(
                        v2_plans,
                        decision.lines,
                    )
                )
            except Exception as exc:
                reasons["v2_comparison"] = (
                    f"{type(exc).__name__}: {exc}"
                )
                discrepancy = MappingProxyType({})
        return "ok", persisted, None, discrepancy

    def _build_kernel_input(
        self,
        *,
        snapshot: VerifiedDailyActionSnapshot,
        capital: CapitalRiskSnapshot,
        decision_cycle_id: str,
        records: tuple[EvidenceRecord[SignalEvidence], ...],
    ) -> KernelInput:
        """从 producer records 与 snapshot 派生 kernel 冻结输入。

        records 为空的合法路径: kernel 返回 NoTrade(NO_SIGNAL), 是 no-signal
        的唯一权威。候选 identity 采用 ``btst:snapshot_id:ticker`` 确定性
        构造 (GREEN 派生, 无现成 mapping)。lineage/stage/program 取 policy
        envelope 的授权 grant (admission 契约: grant.subject_producer=btst
        且 family 匹配时才 ADMITTED)。"""
        ticker_by_candidate: dict[str, str] = {}
        raw_candidates: list[RawCandidate] = []
        for record in records:
            envelope = record.evidence
            if envelope.stage != SignalStage.SELECTED:
                continue
            ticker = _evidence_ticker(envelope.evidence_id)
            candidate_id = f"btst:{snapshot.snapshot_id}:{ticker}"
            ticker_by_candidate[candidate_id] = ticker
            grant = self._authorized_grant()
            raw_candidates.append(
                RawCandidate(
                    candidate_id=candidate_id,
                    producer_namespace=envelope.subject_producer,
                    family_id=envelope.family_id or "",
                    economic_lineage_id=grant.economic_lineage_id,
                    research_program_id=grant.research_program_id,
                    stage_id=grant.stage_id,
                    security_id=_security_id(ticker),
                    direction="LONG",
                    unscaled_target_gross_cents=_unscaled_target(capital),
                    behavior_fingerprint=envelope.behavior_fingerprint,
                    execution_version=envelope.execution_version,
                    cost_version=envelope.cost_version,
                    evidence_ids=(),
                )
            )
        return KernelInput(
            portfolio_id=self._portfolio_id,
            signal_session=snapshot.signal_date,
            decision_cycle_id=decision_cycle_id,
            mode=self._policy_activation.mode,
            policy_activation=self._policy_activation,
            envelope=self._envelope,
            capital=capital,
            deadlines=self._deadlines,
            trusted_evidence_cutoff=self._trusted_evidence_cutoff,
            raw_candidates=tuple(raw_candidates),
            price_micros_by_candidate=tuple(
                (
                    candidate_id,
                    _price_micros(
                        snapshot.prices_by_ticker.get(ticker),
                    ),
                )
                for candidate_id, ticker in ticker_by_candidate.items()
            ),
            industry_by_candidate=tuple(
                (
                    candidate_id,
                    _INDUSTRY_UNKNOWN,
                )
                for candidate_id in ticker_by_candidate
            ),
        )

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

    def _build_shadow_decision(
        self,
        *,
        decision: PortfolioDecision,
        snapshot: VerifiedDailyActionSnapshot,
        decision_cycle_id: str,
        shadow_decision_id: str,
        trusted_at: datetime,
        capital: CapitalRiskSnapshot,
    ) -> ShadowDecision:
        """构造确定性 ShadowDecision: 恒无执行授权 + 非空 counterfactual_lines。

        target_entry_session = signal_date 次日 (shadow 恒不产生可执行授权;
        line 的 economics 由 kernel sizing 输出派生, 完全 counterfactual)。
        """
        grant = self._authorized_grant()
        family_id = f"btst:{snapshot.snapshot_id}"
        binding = ShadowStageBinding(
            research_program_id=grant.research_program_id,
            economic_lineage_id=grant.economic_lineage_id,
            stage_id=grant.stage_id,
            trial_id=grant.trial_id,
            stage_manifest_hash=grant.stage_manifest_hash,
        )
        lines = tuple(
            self._build_shadow_line(
                decision_line=line,
                grant=grant,
                family_id=family_id,
            )
            for line in decision.lines
            if line.status == "ENTRY_PLANNED"
        )
        # ShadowDecision 校验要求 counterfactual_lines 按 shadow_line_id
        # 字典序 (canonical order); kernel 输出是 rank 顺序, 与 candidate_id
        # 字典序不一定一致, 必须显式排序 (确定性契约)。
        lines = tuple(
            sorted(
                lines,
                key=lambda line: line.shadow_line_id,
            )
        )
        return ShadowDecision(
            artifact_kind=ArtifactKind.SHADOW_DECISION,
            artifact_namespace="growth-kernel.shadow.v1",
            schema_major=2,
            shadow_decision_id=shadow_decision_id,
            counterfactual_key=CounterfactualDecisionKey(
                portfolio_id=self._portfolio_id,
                signal_session=snapshot.signal_date,
                counterfactual_cycle_id=decision_cycle_id,
            ),
            portfolio_id=self._portfolio_id,
            mode=self._policy_activation.mode,
            target_entry_session=snapshot.signal_date
            + timedelta(days=1),
            producer_namespace="btst",
            family_id=family_id,
            research_program_id=grant.research_program_id,
            economic_lineage_id=grant.economic_lineage_id,
            stage_id=grant.stage_id,
            trial_id=grant.trial_id,
            policy_activation_hash=self._policy_activation.artifact_hash(),
            policy_epoch=self._policy_activation.policy_epoch,
            evidence_set_merkle_root=capital.policy_activation_hash,
            shadow_stage_binding=binding,
            counterfactual_lines=lines,
            cost_assumption_version=grant.cost_version,
            execution_assumption_version=grant.execution_version,
            created_at=trusted_at,
            available_at=trusted_at,
            execution_authority="NONE",
            issuer_binding=self._shadow_issuer_binding(trusted_at),
        )

    def _build_shadow_line(
        self,
        *,
        decision_line: PortfolioDecisionLine,
        grant: Any,
        family_id: str,
    ) -> ShadowOrderLine:
        """一条 counterfactual 入口 line: 由 kernel sizing 输出派生 economics。

        价格 = ``limit_price_micros`` 按 ``MICROS_PER_CENT`` (10_000) 换算为
        cents (micros 是 micro-yuan, 不是 cents — 除 1_000_000 得 yuan, 错);
        fee 从 kernel 决策行的 ``worst_case_reserve_cents`` 反推 (kernel 已按
        其 ``SizingConfig.worst_case_fee_ppm`` 计入 reserve), 与 kernel 口径
        一致而非本 flow 硬编码 ppm。reserve = limit_price_cents × qty + fee
        自洽以满足 ``ShadowOrderLine`` 校验。T+10 ordinal 恒为原生整数 10。
        """
        quantity = max(decision_line.quantity_units, LOT_UNITS)
        # micro-yuan → cents (MICROS_PER_CENT = 10_000; 非 1_000_000)。
        limit_price_cents = max(
            decision_line.limit_price_micros // MICROS_PER_CENT,
            1,
        )
        # kernel 实际 gross 与 reserve (与其 fee_ppm 一致): gross = qty ×
        # micros // MICROS_PER_CENT, fee = reserve - gross。
        kernel_gross = (
            decision_line.quantity_units
            * decision_line.limit_price_micros
            // MICROS_PER_CENT
        )
        fee = max(
            decision_line.worst_case_reserve_cents - kernel_gross,
            0,
        )
        shadow_gross = limit_price_cents * quantity
        return ShadowOrderLine(
            shadow_line_id=f"shadow-line-{decision_line.candidate_id}",
            security_id=decision_line.security_id,
            producer_namespace="btst",
            family_id=family_id,
            economic_lineage_id=grant.economic_lineage_id,
            research_program_id=grant.research_program_id,
            stage_id=grant.stage_id,
            trial_id=grant.trial_id,
            stage_manifest_hash=grant.stage_manifest_hash,
            evidence_id=f"btst:shadow:{decision_line.candidate_id}",
            evidence_artifact_hash=_sha256_hex(decision_line.candidate_id),
            evidence_payload_hash=_sha256_hex(
                f"{decision_line.candidate_id}:{decision_line.quantity_units}"
            ),
            target_quantity_units=quantity,
            lot_size_units=LOT_UNITS,
            lot_rule_version="cn-a-share-lot.v1",
            order_type="LIMIT",
            limit_price_cents=limit_price_cents,
            worst_case_price_cents=limit_price_cents,
            price_boundary_version="cn-price-limit.v1",
            time_in_force="OPEN_AUCTION",
            exit_session_ordinal=10,
            estimated_fee_cents=fee,
            estimated_cash_reserve_cents=shadow_gross + fee,
            cost_assumption_version=grant.cost_version,
            execution_assumption_version=grant.execution_version,
        )

    def _shadow_issuer_binding(self, trusted_at: datetime) -> ShadowIssuerBinding:
        """SHADOW 能力 issuer 绑定: 恒 VALID 且能力覆盖 created_at。"""
        return ShadowIssuerBinding(
            issuer_id="growth-kernel.shadow.service",
            key_id="shadow-key-1",
            capability_artifact_kind=ArtifactKind.SHADOW_DECISION,
            capability_namespace="growth-kernel.shadow.v1",
            capability_mode=self._policy_activation.mode,
            capability_schema_major=2,
            capability_version="growth-kernel-shadow.v1",
            capability_scope=f"portfolio:{self._portfolio_id}",
            verification_result="VALID",
            verified_at=trusted_at,
            valid_until=trusted_at + timedelta(days=1),
            trust_bundle_hash=self._policy_activation.trust_bundle_hash,
            registry_epoch=self._policy_activation.registry_epoch,
        )

    def _compare_v2_plans(
        self,
        v2_plans: tuple[Any, ...],
        lines: tuple[PortfolioDecisionLine, ...],
    ) -> dict[str, str]:
        """归一化 ticker 对比: v2 有计划但 v3 无 → "v2_only", 反之 "v3_only"。"""
        v3_tickers = {
            _normalize_ticker(line.security_id)
            for line in lines
            if line.status == "ENTRY_PLANNED"
        }
        v2_tickers = {
            _normalize_ticker(plan.ticker)
            for plan in v2_plans
        }
        discrepancy: dict[str, str] = {}
        for ticker in sorted(v2_tickers - v3_tickers):
            discrepancy[ticker] = "v2_only"
        for ticker in sorted(v3_tickers - v2_tickers):
            discrepancy[ticker] = "v3_only"
        return discrepancy


def _normalize_ticker(value: str) -> str:
    """归一化 ticker: 去掉 v3 security_id 的交易所后缀 (.SH/.SZ/.BJ)。"""
    for suffix in _SECURITY_SUFFIXES:
        if value.endswith(suffix):
            return value[: -len(suffix)]
    return value


def _security_id(ticker: str) -> str:
    """v2 6 位 ticker → v3 security_id (默认深市 .SZ; A-share 统一形态)。"""
    return f"{ticker}.SZ"


def _evidence_ticker(evidence_id: str) -> str:
    """从 ``btst:snapshot_id:ticker:setup:stage`` 提取 ticker (第 3 段)。"""
    return evidence_id.split(":")[2]


def _unscaled_target(capital: CapitalRiskSnapshot) -> int:
    """GREEN 派生: 按 NAV 的 1/4 取整的 counterfactual 目标 (cents)。

    信封只有原始候选字段 (raw targets 契约), 无 explicit sizing 字段;
    kernel 以 grant lineage cap × NAV 为上限, 该派生值只被 clamp DOWN,
    不会提升至授权上限之外。"""
    return max(int(capital.as_observed_nav_cents // 4), 100_000)


def _price_micros(
    prices: tuple[Any, ...] | None,
) -> int:
    """快照最后交易日收盘价 → micros; 无价时用 1000 万元微元 (1 元) 兜底。

    prices 列为 (trade_date, open, high, low, close, volume, pct_change)
    FrozenPriceRow; 取最后一行的 close (Decimal) 换算 micros。"""
    if not prices:
        return 10_000_000
    row = prices[-1]
    return int(float(row.close) * 1_000_000)


def _sha256_hex(value: str) -> str:
    """64 位十六进制哈希 (evidence 引用字段契约)。"""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


__all__ = ["DailyActionFlow", "DailyActionFlowResult"]
