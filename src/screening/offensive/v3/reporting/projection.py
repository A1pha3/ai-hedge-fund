"""Plan 05 Task 8: ``DailyOperatorProjection`` — 操作员每日状态投影。

一份 ``DailyOperatorProjection`` 是从 v3 各子系统**只读投影**派生出的单一
权威操作员视图, 同时渲染为 JSON (``render_json``) 与中文终端文本
(``render_text``)。两个 renderer **共享同一个 projection 实例**, 绝不独立
查询状态或调用任何 reader — 这是 spec Task 8 Step 4 的核心契约 ("JSON/text
share the same projection object and never independently derive status")。

-------------------------------------------------------------------------------
keyed 读取组合 (无 portfolio-wide listing)
-------------------------------------------------------------------------------
gateway 按 design 是 keyed-only (``test_entry_projection.py:7`` 明示 "exposes
no portfolio-wide listing"): ``active_seal`` 按 economic key 查, ``entry_state``
按 seal id 查。本 projection 的计划入口集**绝不**给 gateway 加 portfolio-wide
listing query; 而是组合 keyed 读取 — 入口集的 keys 来自:

(a) ``ShadowDecision.counterfactual_lines`` 的 planned economic keys (auto
    recommendation 想下什么单), 与
(b) capital snapshot 现有 positions 的 lineage/lot (账户已有敞口),

对每个 key 用 ``active_seal(economic_key)`` + ``entry_state(seal_id)`` 对账,
得到 ``PlannedEntryView`` (是否 reconcile 到活跃 seal、是否 executable)。这
正是 ``test_entry_projection.py:10-11`` 描述的 "operator projection composes
keyed reads"。executable statuses = ``{PERMITTED, OUTBOX_DURABLE,
SEND_CLAIMED, BROKER_ACK}`` (见 ``test_entry_projection.py:54``); spec Task 8
Step 3 约束 1 "Planned entry set equals active executable seals only" — 即
``executable=True`` 当且仅当该 key 有活跃 seal 且 ``entry_status`` 落在
executable 集。

-------------------------------------------------------------------------------
spec Task 8 Step 3 语义约束 (本 dataclass 字段集必须能表达全部)
-------------------------------------------------------------------------------
1. "Planned entry set equals active executable seals only" — 见上文; 由
   ``planned_entries`` + ``PlannedEntryView.executable`` 表达。
2. "Auto recommendation shows execution_authority=none" — ``shadow`` 子视图的
   ``execution_authority`` 恒 ``"none"``; projection 整体的
   ``execution_authority`` 亦恒 ``"none"``。
3. "pending/block/halt must prevent misleading sole output 今日无信号" — 当
   存在 ``pending_exits`` / ``open_fence_count > 0`` (blocked) / 任何 halt 时,
   ``headline_status()`` 绝不返回 ``"no_signal"``; renderer 必须并列展示阻断
   原因。``headline_status`` 的优先级 (见下) 保证 "今日无信号" 只在无任何
   阻断/待处理时出现。
4. "Account capital total and mode-pure performance are distinct labeled
   views" — ``account_capital_view`` (NAV/cash/exposure 账户资本视图) 与
   ``performance_view`` (HWM/drawdown/mode 业绩视图) 是两个**字段集不重叠**
   的独立标注视图, 均从 ``capital`` snapshot 派生但字段集不同、标注不同。
5. "JSON/text share the same projection object" — 见模块首段。

-------------------------------------------------------------------------------
capital_read_status 值域 (读失败 vs 新鲜度)
-------------------------------------------------------------------------------
- ``"ok"``      — ``risk_snapshot`` 读成功, 且 ``freshness`` 为 ``FRESH``。
- ``"failed"``  — ``risk_snapshot`` 读抛异常 (reader 层失败; 记入
                  ``partial_failure``)。
- ``"stale"``   — 读成功但 ``freshness`` 为 ``STALE`` (新鲜度判定, 非读失败)。
- ``"unknown"`` — 读成功但 ``completeness`` 为 ``INCOMPLETE`` 或新鲜度无法判定
                  (对应 ``BlockReason.UNKNOWN_CAPITAL_FRESHNESS``)。stale/unknown
                  都是读成功后的新鲜度判定, 不是读失败。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from types import MappingProxyType
from typing import Literal, Mapping

from src.screening.offensive.v3.capital.flows import LifecycleState
from src.screening.offensive.v3.contracts import (
    CapitalRiskSnapshot,
    ExitMandateRevisionKind,
)
from src.screening.offensive.v3.kernel.models import BlockReason
from src.screening.offensive.v3.policy.models import RuntimeMode

# 入口状态 → 是否携带 live send right (即 executable)。与
# ``test_entry_projection.py:54`` 的 ``_EXECUTABLE_STATUSES`` 同源; GREEN 的
# reporting service 用此集判定 ``PlannedEntryView.executable``。
EXECUTABLE_ENTRY_STATUSES: frozenset[str] = frozenset(
    {"PERMITTED", "OUTBOX_DURABLE", "SEND_CLAIMED", "BROKER_ACK"}
)
"""spec Task 8 Step 3 约束 1 的 executable 判定集。"""

# fill provenance 词表: 一个到达 BROKER_ACK / 已 fill 的 entry 通过哪条路径 fill。
# Plan 04 Task 8 的 proxy+manual execution layer 与 broker ACK 三路径。
FILL_PROVENANCE_PROXY = "proxy"
FILL_PROVENANCE_MANUAL = "manual"
FILL_PROVENANCE_BROKER = "broker"


@dataclass(frozen=True)
class PlannedEntryView:
    """单个计划入口, 经 keyed 对账 (active_seal + entry_state) 后的只读视图。

    GREEN contract: 入口集 universe = ``ShadowDecision.counterfactual_lines``
    的 economic keys ∪ capital snapshot positions 的 lineage/lot; 每个 key
    经 ``active_seal(economic_key)`` → ``seal_id`` (无活跃 seal → ``None``),
    再 ``entry_state(seal_id)`` → ``entry_status`` (无 seal → ``None``)。
    ``reconciled=True`` 当且仅当该 key 同时有 shadow 计划与活跃 seal (shadow
    plan 与 gateway seal 对账一致)。``executable=True`` 当且仅当 ``seal_id``
    非空且 ``entry_status`` ∈ ``EXECUTABLE_ENTRY_STATUSES`` (spec 约束 1:
    executable planned entry = active executable seal only)。

    ``fill_provenance`` 仅在 entry 已 fill (BROKER_ACK 或 execution-layer
    fill revision) 时非空, 取 ``FILL_PROVENANCE_PROXY`` / ``_MANUAL`` /
    ``_BROKER`` 之一, 区分 proxy_fill / manual_fill / broker_fill 三态。
    **当前实现注意**: 在 broker plan (Plan 06+) 开放 BROKER_ACK 路径并给
    ``EntryStateProjection`` (gateway/decisions.py:272-282) 暴露
    ``fill_provenance`` 字段前, ``ReportingService.build`` 对该字段恒产
    ``None`` — 本 plan ``claim_send`` 禁用, BROKER_ACK 经 gateway 不可达,
    故三态在 ``build()`` 路径下当前不可达; golden 测试通过直接构造
    ``PlannedEntryView`` 覆盖 ``_entry_tier_label`` 的 BROKER_ACK 分流。
    """

    economic_key: str
    seal_id: str | None
    entry_status: str | None
    reconciled: bool
    executable: bool
    fill_provenance: str | None


@dataclass(frozen=True)
class PendingExitView:
    """单个 lot 的 exit 义务只读视图 (来自 ``exit_state`` keyed 读)。

    ``mandate_status`` 取 ``ExitLaneProjection.status`` 值 (``PENDING`` /
    ``TERMINAL_LEGAL`` / ``CLOSED``); ``PENDING`` 即 spec 状态 ``pending_exit``。
    ``reconciliation_pending=True`` 表示该 lot 已 schedule reconciliation
    (unknown tradable quantity)。``revision_kind`` 区分 INITIAL /
    QUANTITY_REFRESH / REOPENED_BY_CORRECTION; 后者即 spec 状态
    ``reopened_by_correction``。
    """

    position_lineage_id: str
    economic_lot_id: str
    mandate_status: str
    reconciliation_pending: bool
    revision_kind: ExitMandateRevisionKind


@dataclass(frozen=True)
class ShadowDecisionSummary:
    """ShadowDecision 的只读摘要 (auto recommendation surface)。

    spec 约束 2: ``execution_authority`` 恒 ``"none"`` — auto recommendation
    永不携带执行授权。``counterfactual_line_count`` = 持久化的
    ``ShadowDecision.counterfactual_lines`` 数量 (≥ 1, 见 contracts/decision.py:
    1072 min_length=1); 若 shadow 管线产出 NoTrade (不持久化 ShadowDecision),
    则 summary 仍可携带 ``no_trade_reason`` 且 ``counterfactual_line_count``
    为 0。``no_trade_reason`` 为 kernel typed ``BlockReason`` (区分 NO_SIGNAL /
    STALE_CAPITAL / CAPACITY_EXHAUSTED ...) 或 ``None``。
    """

    execution_authority: Literal["none"]
    counterfactual_line_count: int
    no_trade_reason: BlockReason | None


@dataclass(frozen=True)
class AccountCapitalView:
    """账户资本视图 — spec 约束 4 的两个独立标注视图之一。

    表达"账户里有多少资本 / 敞口多大": NAV、各类现金 (available/restricted/
    reserved/unsettled)、总毛敞口、已发行单位。全部从 ``capital`` snapshot
    派生, 字段集与 ``PerformanceView`` **不重叠**。
    """

    as_observed_nav_cents: int
    available_cash_cents: int
    restricted_cash_cents: int
    reserved_cash_cents: int
    unsettled_cash_cents: int
    total_gross_exposure_cents: int
    issued_unit_quanta: int


@dataclass(frozen=True)
class PerformanceView:
    """业绩视图 — spec 约束 4 的两个独立标注视图之一。

    表达"mode-pure 的业绩度量": lifetime/active-epoch HWM、对应 drawdown_ppm、
    capital ``mode``。全部从 ``capital`` snapshot 派生, 字段集与
    ``AccountCapitalView`` **不重叠**。
    """

    lifetime_high_water_mark_cents: int
    active_epoch_high_water_mark_cents: int
    lifetime_drawdown_ppm: int
    active_epoch_drawdown_ppm: int
    mode: str


@dataclass(frozen=True)
class DailyOperatorProjection:
    """操作员每日状态投影 — 从 v3 各子系统只读投影派生的单一权威视图。

    两个 renderer (``render_json`` / ``render_text``) 共享本实例, 绝不独立查
    状态 (spec Task 8 Step 4)。所有字段在 ``ReportingService.build`` 期间填充;
    本 dataclass 的方法仅做派生 (``headline_status``)。

    字段语义参见模块 docstring 与各子视图 docstring。
    """

    portfolio_id: str
    as_of: datetime
    signal_session: date
    runtime_mode: RuntimeMode
    capital: CapitalRiskSnapshot | None
    capital_read_status: Literal["ok", "failed", "stale", "unknown"]
    lifecycle_state: LifecycleState | None
    risk_halted: bool
    reconciliation_halt: bool
    stage_loss_halted: bool
    open_fence_count: int
    planned_entries: tuple[PlannedEntryView, ...]
    pending_exits: tuple[PendingExitView, ...]
    shadow: ShadowDecisionSummary | None
    account_capital_view: AccountCapitalView
    performance_view: PerformanceView
    partial_failure: Mapping[str, str] = field(
        default_factory=lambda: MappingProxyType({})
    )
    """step → reason; 空 Mapping 表示无部分失败 (spec 状态 partial service
    failure: 各 service 读面抛异常时, reporting service 内 try/except 捕获并
    记入此处, projection 仍构建, 不崩溃)。"""
    discrepancy: Mapping[str, str] = field(
        default_factory=lambda: MappingProxyType({})
    )
    """v2↔v3 计划差异 (key = 归一化 ticker, value = "v2_only"/"v3_only"/...);
    空 Mapping 表示无差异或未对比。"""
    execution_authority: Literal["none"] = "none"
    """projection 整体恒无执行授权 (spec 约束 2, 与 shadow 子视图一致)。"""

    def headline_status(self) -> str:
        """返回单一 headline 标签, 汇总 projection 给操作员看的最重要状态。

        GREEN contract — 优先级 (高 → 低), 返回首个命中状态的标签:

        1. halt 类 (任一为 True):
           - ``risk_halted`` (``self.risk_halted``)
           - ``stage_loss_halted`` (``self.stage_loss_halted``)
           - ``reconciliation_halt`` (``self.reconciliation_halt``)
        2. lifecycle 终结/破产: ``self.lifecycle_state`` ∈
           {TERMINATING, INSOLVENT, TERMINATED} → ``"terminating"`` /
           ``"insolvent"`` (TERMINATED 归入 terminating 文案)。
        3. blocked: ``self.open_fence_count > 0`` → ``"blocked"``。
        4. partial service failure: ``self.partial_failure`` 非空 →
           ``"partial_failure"``。
        5. stale/unknown capital: ``self.capital_read_status`` 为 ``"stale"`` →
           ``"stale_capital"``; 为 ``"unknown"`` → ``"unknown_capital"``。
        6. 有 live send-right entry (任一 ``planned_entry`` 的 ``entry_status``
           落入 executable 集或 ``SUBMISSION_AMBIGUOUS``): 取优先级最高的 entry
           状态返回 ``"submission_ambiguous"`` / ``"permitted"`` /
           ``"outbox_durable"`` / ``"send_claimed"``; ``BROKER_ACK`` 按
           ``fill_provenance`` → ``"proxy_fill"`` / ``"manual_fill"`` /
           ``"broker_fill"``。
        7. shadow sealed (该 tier 内: 有 SEALED entry 优先):
           - 任一 ``planned_entry.entry_status == "SEALED"`` → ``"sealed"``;
           - 否则 ``self.shadow is not None`` → ``"shadow"``。
        8. pending_exit / reopened_by_correction: 任一 ``pending_exit`` 的
           ``mandate_status == "PENDING"`` → ``"pending_exit"``; 若该 mandate
           ``revision_kind == REOPENED_BY_CORRECTION`` 则 →
           ``"reopened_by_correction"`` (reopened 优先于普通 pending)。
        9. fallback: ``"no_signal"``。

        该优先级保证 spec 约束 3: 存在 pending/block/halt 时绝不返回
        ``"no_signal"``, "今日无信号" 只在无任何阻断/待处理时出现。
        """
        # tier 1 — halt 类 (最高优先; 风控/对账/stage-loss 闸门)。
        if self.risk_halted:
            return "risk_halted"
        if self.stage_loss_halted:
            return "stage_loss_halted"
        if self.reconciliation_halt:
            return "reconciliation_halt"
        # tier 2 — lifecycle 终结/破产 (TERMINATED 归入 terminating 文案)。
        if self.lifecycle_state is LifecycleState.INSOLVENT:
            return "insolvent"
        if self.lifecycle_state in (
            LifecycleState.TERMINATING,
            LifecycleState.TERMINATED,
        ):
            return "terminating"
        # tier 3 — blocked (portfolio-level fence 阻断)。
        if self.open_fence_count > 0:
            return "blocked"
        # tier 4 — partial service failure (某 step reader 异常)。
        if self.partial_failure:
            return "partial_failure"
        # tier 5 — stale/unknown capital (读成功但新鲜度判定)。
        if self.capital_read_status == "stale":
            return "stale_capital"
        if self.capital_read_status == "unknown":
            return "unknown_capital"
        # tier 6 — live send-right entry (executable 或 ambiguous); 取最高
        # 优先 entry 状态。BROKER_ACK 按 fill_provenance 分流。
        entry_label = _entry_tier_label(self.planned_entries)
        if entry_label is not None:
            return entry_label
        # tier 7 — shadow sealed (有 SEALED entry 优先于纯 shadow)。
        if any(
            entry.entry_status == "SEALED" for entry in self.planned_entries
        ):
            return "sealed"
        if self.shadow is not None:
            return "shadow"
        # tier 8 — pending_exit / reopened_by_correction (reopened 优先)。
        if any(
            exit_view.mandate_status == "PENDING"
            and exit_view.revision_kind is ExitMandateRevisionKind.REOPENED_BY_CORRECTION
            for exit_view in self.pending_exits
        ):
            return "reopened_by_correction"
        if any(
            exit_view.mandate_status == "PENDING"
            for exit_view in self.pending_exits
        ):
            return "pending_exit"
        # tier 9 — fallback: 唯一允许 "今日无信号" 的状态。
        return "no_signal"


# entry tier 内部优先级: BROKER_ACK(fill 分流) > SEND_CLAIMED > OUTBOX_DURABLE
# > PERMITTED > SUBMISSION_AMBIGUOUS。返回首个命中的 headline 标签或 None。
_ENTRY_TIER_ORDER: tuple[tuple[str, str], ...] = (
    ("BROKER_ACK", "broker_fill"),
    ("SEND_CLAIMED", "send_claimed"),
    ("OUTBOX_DURABLE", "outbox_durable"),
    ("PERMITTED", "permitted"),
    ("SUBMISSION_AMBIGUOUS", "submission_ambiguous"),
)


def _entry_tier_label(
    entries: tuple[PlannedEntryView, ...]
) -> str | None:
    """返回 live send-right entry tier 的 headline 标签 (最高优先 entry 状态)。

    BROKER_ACK 按 ``fill_provenance`` 分流为 proxy_fill / manual_fill /
    broker_fill (默认 broker)。SUBMISSION_AMBIGUOUS 与 executable 同 tier 但
    优先级最低。SEALED 不在此 tier (属 tier 7 shadow sealed)。
    """
    statuses = [entry.entry_status for entry in entries]
    # BROKER_ACK fill provenance 分流 (proxy/manual/broker)。
    for entry in entries:
        if entry.entry_status == "BROKER_ACK":
            if entry.fill_provenance == FILL_PROVENANCE_PROXY:
                return "proxy_fill"
            if entry.fill_provenance == FILL_PROVENANCE_MANUAL:
                return "manual_fill"
            return "broker_fill"
    for status, label in _ENTRY_TIER_ORDER:
        if status == "BROKER_ACK":
            continue
        if status in statuses:
            return label
    return None


__all__ = [
    "AccountCapitalView",
    "DailyOperatorProjection",
    "EXECUTABLE_ENTRY_STATUSES",
    "FILL_PROVENANCE_BROKER",
    "FILL_PROVENANCE_MANUAL",
    "FILL_PROVENANCE_PROXY",
    "PendingExitView",
    "PerformanceView",
    "PlannedEntryView",
    "ShadowDecisionSummary",
]
