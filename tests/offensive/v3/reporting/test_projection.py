"""Plan 05 Task 8 (RED): ``DailyOperatorProjection`` golden 契约 — 19 spec 状态 + 4 额外契约。

覆盖 spec Task 8 Step 1 列的全部 19 状态 (每个一个 golden 测试, stale/unknown
parametrize 合一) + Step 4 的 4 个额外契约。每个 golden 测试构造一个代表该状态
的 ``DailyOperatorProjection`` (直接 dataclass 构造, 纯内存, 不依赖真实 DB),
断言: (a) ``headline_status()`` 标签, (b) 关键字段, (c) ``render_text`` 的关键
文案 / "今日无信号" 抑制契约。

keyed 读取组合契约 (spec Task 8 Step 3 + test_entry_projection.py:7,10-11):
gateway 按 design 是 keyed-only — reporting service 绝不加 portfolio-wide listing,
而是组合 ``active_seal(economic_key)`` + ``entry_state(seal_id)`` 对账。executable
statuses = ``EXECUTABLE_ENTRY_STATUSES`` (test_entry_projection.py:54 同源)。

本文件引用尚未实现的 GREEN 逻辑 — ``headline_status`` / ``render_json`` /
``render_text`` / ``ReportingService.build`` 方法体均
``raise NotImplementedError``; 当前应整体 RED (每个测试至少调一个上述方法 →
失败)。dataclass 字段定义本身是真实契约, 测试依赖其形状。
"""

from __future__ import annotations

import dataclasses
import inspect
from datetime import date, datetime, timezone
from types import SimpleNamespace
from typing import Any

import pytest

from src.screening.offensive.v3.capital.flows import LifecycleState
from src.screening.offensive.v3.contracts import (
    ExitMandateRevisionKind,
    ReconciliationLatchState,
    RiskLatchState,
    RiskSnapshotCompleteness,
    RiskSnapshotFreshness,
)
from src.screening.offensive.v3.kernel.models import BlockReason
from src.screening.offensive.v3.policy.models import RuntimeMode
from src.screening.offensive.v3.reporting import (
    AccountCapitalView,
    CapitalReaderPort,
    DailyOperatorProjection,
    EXECUTABLE_ENTRY_STATUSES,
    FILL_PROVENANCE_BROKER,
    FILL_PROVENANCE_MANUAL,
    FILL_PROVENANCE_PROXY,
    PendingExitView,
    PerformanceView,
    PlannedEntryView,
    ReportingService,
    ShadowDecisionReader,
    ShadowDecisionSummary,
    render_json,
    render_text,
)

UTC = timezone.utc
PORTFOLIO = "paper-v3"
SIGNAL_DATE = date(2026, 8, 5)
AS_OF = datetime(2026, 8, 5, 15, 0, tzinfo=UTC)
ECONOMIC_KEY_A = "prog-1/eline-1/stage-1/trial-1"
SEAL_A = "seal-7"
LINEAGE_A = "lineage-7"
LOT_A = "lot-7"


# --------------------------------------------------------------------------
# 子视图 / projection 构造 helper (纯内存, 不依赖真实 CapitalRiskSnapshot)
# --------------------------------------------------------------------------


def _account_capital_view(**overrides) -> AccountCapitalView:
    values = dict(
        as_observed_nav_cents=10_000_000,
        available_cash_cents=8_000_000,
        restricted_cash_cents=0,
        reserved_cash_cents=500_000,
        unsettled_cash_cents=0,
        total_gross_exposure_cents=2_000_000,
        issued_unit_quanta=10_000_000,
    )
    values.update(overrides)
    return AccountCapitalView(**values)


def _performance_view(**overrides) -> PerformanceView:
    values = dict(
        lifetime_high_water_mark_cents=12_000_000,
        active_epoch_high_water_mark_cents=11_000_000,
        lifetime_drawdown_ppm=160_000,
        active_epoch_drawdown_ppm=90_000,
        mode="DAILY_BAR_PROXY",
    )
    values.update(overrides)
    return PerformanceView(**values)


def _projection(**overrides) -> DailyOperatorProjection:
    """baseline = ``no_signal`` (无 halt/lifecycle block/fence/partial/stale/
    entry/shadow/pending_exit); 各 golden 测试 override 字段命中目标状态。"""
    base: dict[str, Any] = dict(
        portfolio_id=PORTFOLIO,
        as_of=AS_OF,
        signal_session=SIGNAL_DATE,
        runtime_mode=RuntimeMode.SHADOW,
        capital=None,
        capital_read_status="ok",
        lifecycle_state=LifecycleState.ACTIVE,
        risk_halted=False,
        reconciliation_halt=False,
        stage_loss_halted=False,
        open_fence_count=0,
        planned_entries=(),
        pending_exits=(),
        shadow=None,
        account_capital_view=_account_capital_view(),
        performance_view=_performance_view(),
    )
    base.update(overrides)
    return DailyOperatorProjection(**base)


def _entry(
    status: str | None = None,
    *,
    key: str = ECONOMIC_KEY_A,
    seal_id: str | None = SEAL_A,
    executable: bool | None = None,
    reconciled: bool | None = None,
    provenance: str | None = None,
) -> PlannedEntryView:
    if executable is None:
        executable = status in EXECUTABLE_ENTRY_STATUSES
    if reconciled is None:
        reconciled = status is not None
    return PlannedEntryView(
        economic_key=key,
        seal_id=seal_id if status is not None else None,
        entry_status=status,
        reconciled=reconciled,
        executable=executable,
        fill_provenance=provenance,
    )


def _exit(
    mandate_status: str = "PENDING",
    *,
    revision_kind: ExitMandateRevisionKind = ExitMandateRevisionKind.INITIAL,
    reconciliation_pending: bool = False,
    lineage: str = LINEAGE_A,
    lot: str = LOT_A,
) -> PendingExitView:
    return PendingExitView(
        position_lineage_id=lineage,
        economic_lot_id=lot,
        mandate_status=mandate_status,
        reconciliation_pending=reconciliation_pending,
        revision_kind=revision_kind,
    )


def _shadow(
    *, line_count: int = 2, no_trade_reason: BlockReason | None = None
) -> ShadowDecisionSummary:
    return ShadowDecisionSummary(
        execution_authority="none",
        counterfactual_line_count=line_count,
        no_trade_reason=no_trade_reason,
    )


# --------------------------------------------------------------------------
# 鸭子类型 fakes (服务级测试用; golden 测试直接构造 projection)
# --------------------------------------------------------------------------


class FakeCapitalReader:
    """鸭子类型 capital reader — 暴露全部 quiet 读面 (含 lifecycle_state)。

    可注入 ``snapshot`` (``risk_snapshot`` 返回值, 默认 None)、
    ``entry_state_result`` / ``active_seal_result`` 供 build 级守卫测试
    (C-1/M-1)。默认 None 保持与 golden build 测试的向后兼容。
    """

    def __init__(
        self,
        *,
        lifecycle: LifecycleState = LifecycleState.ACTIVE,
        snapshot: Any = None,
        entry_state_result: Any = None,
        active_seal_result: Any = None,
    ) -> None:
        self.lifecycle = lifecycle
        self.snapshot = snapshot
        self.entry_state_result = entry_state_result
        self.active_seal_result = active_seal_result
        self.calls: list[tuple[str, tuple, dict]] = []

    def risk_snapshot(self, portfolio_id: str, as_of: datetime) -> Any:
        self.calls.append(("risk_snapshot", (portfolio_id, as_of), {}))
        return self.snapshot

    def authority_state(self, portfolio_id: str) -> Any:
        self.calls.append(("authority_state", (portfolio_id,), {}))
        return None

    def entry_state(self, seal_id: str) -> Any:
        self.calls.append(("entry_state", (seal_id,), {}))
        return self.entry_state_result

    def active_seal(self, logical_key: Any) -> Any:
        self.calls.append(("active_seal", (logical_key,), {}))
        return self.active_seal_result

    def exit_state(
        self, position_lineage_id: str, economic_lot_id: str
    ) -> Any:
        self.calls.append(
            ("exit_state", (position_lineage_id, economic_lot_id), {})
        )
        return None

    def lifecycle_state(self, portfolio_id: str) -> LifecycleState:
        self.calls.append(("lifecycle_state", (portfolio_id,), {}))
        return self.lifecycle


class FakeShadowReader:
    """鸭子类型 ShadowDecision reader — 返回 None (无持久化 shadow)。"""

    def __init__(self, shadow: Any = None) -> None:
        self.shadow = shadow

    def active_shadow(self, portfolio_id: str, signal_session: date) -> Any:
        return self.shadow


# ==========================================================================
# 19 spec 状态 golden 测试
# ==========================================================================


def test_shadow_state_auto_recommendation_authority_none() -> None:
    """spec 状态 #1 shadow: auto recommendation (execution_authority=none)。"""
    projection = _projection(shadow=_shadow(line_count=2))
    assert projection.shadow is not None
    assert projection.shadow.execution_authority == "none"
    assert projection.shadow.counterfactual_line_count == 2
    assert projection.headline_status() == "shadow"
    text = render_text(projection)
    assert "今日无信号" not in text


def test_blocked_state_open_fence() -> None:
    """spec 状态 #2 blocked: open_fence_count > 0 (portfolio-level fence)。"""
    projection = _projection(open_fence_count=2)
    assert projection.open_fence_count == 2
    assert projection.headline_status() == "blocked"
    text = render_text(projection)
    assert "今日无信号" not in text


def test_sealed_state_admitted_not_executable() -> None:
    """spec 状态 #3 sealed: entry 活跃 seal, SEALED 状态, 未 permit (非 executable)。"""
    projection = _projection(
        planned_entries=(_entry("SEALED", executable=False, reconciled=True),)
    )
    assert projection.planned_entries[0].entry_status == "SEALED"
    assert projection.planned_entries[0].executable is False
    assert projection.headline_status() == "sealed"
    text = render_text(projection)
    assert "今日无信号" not in text


def test_permitted_state_executable_entry() -> None:
    """spec 状态 #4 permitted: entry 已 permit, executable。"""
    projection = _projection(planned_entries=(_entry("PERMITTED"),))
    assert projection.planned_entries[0].executable is True
    assert projection.headline_status() == "permitted"
    text = render_text(projection)
    assert "今日无信号" not in text


def test_outbox_durable_state_executable_entry() -> None:
    """spec 状态 #5 outbox_durable: entry durable outbox, executable。"""
    projection = _projection(planned_entries=(_entry("OUTBOX_DURABLE"),))
    assert projection.planned_entries[0].executable is True
    assert projection.headline_status() == "outbox_durable"
    text = render_text(projection)
    assert "今日无信号" not in text


def test_send_claimed_state_executable_entry() -> None:
    """spec 状态 #6 send_claimed: entry send-right claimed, executable。"""
    projection = _projection(planned_entries=(_entry("SEND_CLAIMED"),))
    assert projection.planned_entries[0].executable is True
    assert projection.headline_status() == "send_claimed"
    text = render_text(projection)
    assert "今日无信号" not in text


def test_submission_ambiguous_state_live_send_right() -> None:
    """spec 状态 #7 submission_ambiguous: delivery ambiguous (live send-right,
    非 executable, 但需操作员注意 — tier 6)。"""
    projection = _projection(
        planned_entries=(_entry("SUBMISSION_AMBIGUOUS", executable=False),)
    )
    assert projection.planned_entries[0].entry_status == "SUBMISSION_AMBIGUOUS"
    assert projection.planned_entries[0].executable is False
    assert projection.headline_status() == "submission_ambiguous"
    text = render_text(projection)
    assert "今日无信号" not in text


def test_proxy_fill_state_broker_ack_proxy_provenance() -> None:
    """spec 状态 #8 proxy_fill: BROKER_ACK via proxy execution layer。"""
    projection = _projection(
        planned_entries=(
            _entry("BROKER_ACK", provenance=FILL_PROVENANCE_PROXY),
        )
    )
    assert projection.planned_entries[0].fill_provenance == FILL_PROVENANCE_PROXY
    assert projection.headline_status() == "proxy_fill"
    text = render_text(projection)
    assert "今日无信号" not in text


def test_manual_fill_state_broker_ack_manual_provenance() -> None:
    """spec 状态 #9 manual_fill: BROKER_ACK via manual execution layer。"""
    projection = _projection(
        planned_entries=(
            _entry("BROKER_ACK", provenance=FILL_PROVENANCE_MANUAL),
        )
    )
    assert projection.planned_entries[0].fill_provenance == FILL_PROVENANCE_MANUAL
    assert projection.headline_status() == "manual_fill"
    text = render_text(projection)
    assert "今日无信号" not in text


def test_broker_fill_state_broker_ack_broker_provenance() -> None:
    """spec 状态 #10 broker_fill: BROKER_ACK via broker (默认 fill provenance)。"""
    projection = _projection(
        planned_entries=(
            _entry("BROKER_ACK", provenance=FILL_PROVENANCE_BROKER),
        )
    )
    assert projection.planned_entries[0].fill_provenance == FILL_PROVENANCE_BROKER
    assert projection.headline_status() == "broker_fill"
    text = render_text(projection)
    assert "今日无信号" not in text


def test_pending_exit_state_open_mandate() -> None:
    """spec 状态 #11 pending_exit: 一个 OPEN lot 的 PENDING exit mandate。"""
    projection = _projection(pending_exits=(_exit("PENDING"),))
    assert projection.pending_exits[0].mandate_status == "PENDING"
    assert projection.headline_status() == "pending_exit"
    text = render_text(projection)
    assert "今日无信号" not in text


def test_reopened_by_correction_state_exit_revision() -> None:
    """spec 状态 #12 reopened_by_correction: exit mandate 经 execution revision
    重开 (revision_kind=REOPENED_BY_CORRECTION)。"""
    projection = _projection(
        pending_exits=(
            _exit(
                "PENDING",
                revision_kind=ExitMandateRevisionKind.REOPENED_BY_CORRECTION,
            ),
        )
    )
    assert (
        projection.pending_exits[0].revision_kind
        is ExitMandateRevisionKind.REOPENED_BY_CORRECTION
    )
    assert projection.headline_status() == "reopened_by_correction"
    text = render_text(projection)
    assert "今日无信号" not in text


def test_terminating_state_lifecycle() -> None:
    """spec 状态 #13 terminating: ledger lifecycle TERMINATING (settle-only)。"""
    projection = _projection(lifecycle_state=LifecycleState.TERMINATING)
    assert projection.lifecycle_state is LifecycleState.TERMINATING
    assert projection.headline_status() == "terminating"
    text = render_text(projection)
    assert "今日无信号" not in text


def test_insolvent_state_lifecycle() -> None:
    """spec 状态 #14 insolvent: ledger lifecycle INSOLVENT (non-recoverable)。"""
    projection = _projection(lifecycle_state=LifecycleState.INSOLVENT)
    assert projection.lifecycle_state is LifecycleState.INSOLVENT
    assert projection.headline_status() == "insolvent"
    text = render_text(projection)
    assert "今日无信号" not in text


def test_risk_halted_state_risk_latch() -> None:
    """spec 状态 #15 risk_halted: capital risk_latch RISK_HALTED (halt 类最高优先)。"""
    projection = _projection(risk_halted=True)
    assert projection.risk_halted is True
    assert projection.headline_status() == "risk_halted"
    text = render_text(projection)
    assert "今日无信号" not in text


def test_stage_loss_halted_state_latch() -> None:
    """spec 状态 #16 stage_loss_halted: stage loss latch HALTED。"""
    projection = _projection(stage_loss_halted=True)
    assert projection.stage_loss_halted is True
    assert projection.headline_status() == "stage_loss_halted"
    text = render_text(projection)
    assert "今日无信号" not in text


def test_reconciliation_halt_state_latch() -> None:
    """spec 状态 #17 reconciliation_halt: reconciliation latch HALTED。"""
    projection = _projection(reconciliation_halt=True)
    assert projection.reconciliation_halt is True
    assert projection.headline_status() == "reconciliation_halt"
    text = render_text(projection)
    assert "今日无信号" not in text


@pytest.mark.parametrize(
    ("read_status", "expected_label"),
    [
        ("stale", "stale_capital"),
        ("unknown", "unknown_capital"),
    ],
)
def test_stale_or_unknown_capital_state(
    read_status: str, expected_label: str
) -> None:
    """spec 状态 #18 stale/unknown: 读成功但 freshness/completeness 判定
    (非读失败)。两个 parametrize case 合覆盖该状态。"""
    projection = _projection(capital_read_status=read_status)
    assert projection.capital_read_status == read_status
    assert projection.headline_status() == expected_label
    text = render_text(projection)
    assert "今日无信号" not in text


def test_partial_service_failure_state() -> None:
    """spec 状态 #19 partial service failure: 某 step reader 抛异常 →
    partial_failure 非空, projection 仍构建。"""
    from types import MappingProxyType

    partial = MappingProxyType({"capital": "RuntimeError: gateway unreadable"})
    projection = _projection(partial_failure=partial)
    assert dict(projection.partial_failure) == {
        "capital": "RuntimeError: gateway unreadable"
    }
    assert projection.headline_status() == "partial_failure"
    text = render_text(projection)
    assert "今日无信号" not in text


def test_no_signal_state_baseline() -> None:
    """baseline ``no_signal`` — 唯一允许展示 "今日无信号" 的状态 (无任何
    阻断/待处理)。"""
    projection = _projection()
    assert projection.shadow is None
    assert projection.planned_entries == ()
    assert projection.pending_exits == ()
    assert projection.headline_status() == "no_signal"
    text = render_text(projection)
    assert "今日无信号" in text


# ==========================================================================
# 4 个额外必测契约 (spec Task 8 Step 4 + 约束 2/3/4)
# ==========================================================================


def test_json_and_text_share_one_projection() -> None:
    """契约: 两个 renderer 只接收同一 projection 实例, 绝不独立查状态
    (spec Task 8 Step 4)。

    signature 守卫 (RED 可验): 两函数都只接受 ``projection`` 一个参数 — 没有
    reader / capital 句柄位置, 从形状上杜绝独立派生。GREEN 进一步要求两输出
    嵌入同一 ``headline_status()`` 标签。
    """
    projection = _projection(risk_halted=True)
    json_params = list(inspect.signature(render_json).parameters)
    text_params = list(inspect.signature(render_text).parameters)
    assert json_params == ["projection"]
    assert text_params == ["projection"]
    json_out = render_json(projection)
    text_out = render_text(projection)
    label = projection.headline_status()
    assert label in json_out
    assert label in text_out


def test_no_signal_suppressed_when_halt_present() -> None:
    """契约 (spec 约束 3): 存在 halt 时 render_text 绝不含孤立 "今日无信号"。"""
    projection = _projection(risk_halted=True, pending_exits=(_exit("PENDING"),))
    assert projection.headline_status() == "risk_halted"
    text = render_text(projection)
    assert "今日无信号" not in text


def test_shadow_shows_execution_authority_none() -> None:
    """契约 (spec 约束 2): projection 整体与 shadow 子视图的
    execution_authority 恒 "none"; render_text 标注 "无执行授权"。"""
    projection = _projection(shadow=_shadow(line_count=3))
    assert projection.execution_authority == "none"
    assert projection.shadow is not None
    assert projection.shadow.execution_authority == "none"
    assert projection.headline_status() == "shadow"
    text = render_text(projection)
    assert "无执行授权" in text


def test_account_capital_and_performance_are_distinct_views() -> None:
    """契约 (spec 约束 4): 账户资本视图与业绩视图字段集不重叠 (NAV/cash vs
    HWM/drawdown/mode); render 同时呈现两视图。"""
    capital_fields = {f.name for f in dataclasses.fields(AccountCapitalView)}
    perf_fields = {f.name for f in dataclasses.fields(PerformanceView)}
    assert capital_fields & perf_fields == set()
    assert "as_observed_nav_cents" in capital_fields
    assert "available_cash_cents" in capital_fields
    assert "total_gross_exposure_cents" in capital_fields
    assert "lifetime_high_water_mark_cents" in perf_fields
    assert "lifetime_drawdown_ppm" in perf_fields
    assert "mode" in perf_fields
    projection = _projection()
    json_out = render_json(projection)
    text_out = render_text(projection)
    assert json_out  # 两视图在 JSON 中呈现
    assert text_out  # 两视图在中文文本中分别标注呈现


# ==========================================================================
# 服务级 RED 守卫 (build raise; fakes 满足 Protocol 形状)
# ==========================================================================


def test_build_returns_projection_and_fakes_satisfy_ports() -> None:
    """ReportingService.build GREEN 契约: 组合 keyed 读派生 projection; RED
    当前 raise NotImplementedError。fakes 暴露全部 quiet 读面 (含
    lifecycle_state) → 满足 ``CapitalReaderPort`` / ``ShadowDecisionReader``。"""
    capital_reader = FakeCapitalReader(lifecycle=LifecycleState.ACTIVE)
    shadow_reader = FakeShadowReader()
    # Protocol 形状守卫 (runtime_checkable, RED 可验):
    assert isinstance(capital_reader, CapitalReaderPort)
    assert isinstance(shadow_reader, ShadowDecisionReader)
    service = ReportingService(
        capital_reader=capital_reader,
        shadow_reader=shadow_reader,
        mode_provider=lambda: RuntimeMode.SHADOW,
        v2_plans_reader=None,
    )
    projection = service.build(
        portfolio_id=PORTFOLIO, signal_session=SIGNAL_DATE, as_of=AS_OF
    )
    assert isinstance(projection, DailyOperatorProjection)
    assert projection.execution_authority == "none"


# ==========================================================================
# 独立审查回归守卫 (C-1 / M-1 / m-2)
# ==========================================================================


def _stub_snapshot(
    *,
    freshness: RiskSnapshotFreshness,
    completeness: RiskSnapshotCompleteness,
) -> Any:
    """轻量 capital snapshot stub — 提供 ``service.build()`` 在 capital 非 None
    时访问的全部属性 (freshness/completeness/latch/视图字段/positions)。用真实
    enum 值以便 ``is`` 比较生效; 纯内存, 不构造完整 ``CapitalRiskSnapshot``。"""
    return SimpleNamespace(
        freshness=freshness,
        completeness=completeness,
        risk_latch=RiskLatchState.CLEAR,
        reconciliation_latch=ReconciliationLatchState.CLEAR,
        stage_loss_latches=(),
        as_observed_nav_cents=0,
        available_cash_cents=0,
        restricted_cash_cents=0,
        reserved_cash_cents=0,
        unsettled_cash_cents=0,
        total_gross_exposure_cents=0,
        issued_unit_quanta=0,
        lifetime_high_water_mark_cents=0,
        active_epoch_high_water_mark_cents=0,
        lifetime_drawdown_ppm=0,
        active_epoch_drawdown_ppm=0,
        mode="DAILY_BAR_PROXY",
        positions=(),
    )


@pytest.mark.parametrize(
    "freshness, completeness, expected",
    [
        (RiskSnapshotFreshness.FRESH, RiskSnapshotCompleteness.COMPLETE, "ok"),
        (RiskSnapshotFreshness.STALE, RiskSnapshotCompleteness.COMPLETE, "stale"),
        (RiskSnapshotFreshness.UNKNOWN, RiskSnapshotCompleteness.COMPLETE, "unknown"),
        (RiskSnapshotFreshness.FRESH, RiskSnapshotCompleteness.INCOMPLETE, "unknown"),
        (RiskSnapshotFreshness.FRESH, RiskSnapshotCompleteness.UNKNOWN, "unknown"),
        (RiskSnapshotFreshness.UNKNOWN, RiskSnapshotCompleteness.UNKNOWN, "unknown"),
    ],
)
def test_build_capital_read_status_aligns_with_kernel_block_semantics(
    freshness: RiskSnapshotFreshness,
    completeness: RiskSnapshotCompleteness,
    expected: str,
) -> None:
    """C-1 回归守卫: ``build()`` 的 ``capital_read_status`` 派生必须与 kernel
    BLOCK 语义对齐 (kernel/risk.py:78-85)。``freshness=UNKNOWN`` (无论
    completeness) 与 ``completeness≠COMPLETE`` (当 freshness 非 STALE) 绝不可被
    投影成 ``"ok"`` — 否则操作员看到 "今日无信号" 而 kernel 实际拒绝交易
    (UNKNOWN_CAPITAL_FRESHNESS / UNKNOWN_EXPOSURE)。修复前这两类落入 else →
    ``"ok"`` (活跃误导缺陷)。"""
    reader = FakeCapitalReader(
        snapshot=_stub_snapshot(freshness=freshness, completeness=completeness)
    )
    service = ReportingService(
        capital_reader=reader,
        shadow_reader=FakeShadowReader(),
        mode_provider=lambda: RuntimeMode.SHADOW,
        v2_plans_reader=None,
    )
    projection = service.build(
        portfolio_id=PORTFOLIO, signal_session=SIGNAL_DATE, as_of=AS_OF
    )
    assert projection.capital_read_status == expected


def test_build_fill_provenance_none_until_broker_plan() -> None:
    """M-1 回归守卫: ``build()`` 对 planned entry 恒产
    ``fill_provenance=None``。根因: ``EntryStateProjection``
    (gateway/decisions.py:272-282) 未暴露 ``fill_provenance`` 字段, 且本 plan
    ``claim_send`` 禁用 → BROKER_ACK 经 gateway 不可达。故 proxy_fill /
    manual_fill / broker_fill 三态在 ``build()`` 路径下当前不可达 (golden 测试
    直接构造 ``PlannedEntryView`` 覆盖 ``_entry_tier_label`` 的 BROKER_ACK
    分流)。broker plan (Plan 06+) 给 ``EntryStateProjection`` 加
    ``fill_provenance`` 字段后, ``service`` 经 ``getattr`` 自动接通; 届时此守卫
    需更新。"""
    shadow_line = SimpleNamespace(
        economic_lineage_id=ECONOMIC_KEY_A, security_id="000001.SZ"
    )
    shadow = SimpleNamespace(
        counterfactual_lines=(shadow_line,),
        counterfactual_key=SimpleNamespace(
            counterfactual_cycle_id="daily-action-2026-08-05"
        ),
    )
    # 即便注入 entry_state.status="BROKER_ACK", service 取不到 fill_provenance
    # 字段 → getattr 默认 None。
    reader = FakeCapitalReader(
        active_seal_result=(SEAL_A, 1),
        entry_state_result=SimpleNamespace(status="BROKER_ACK"),
    )
    service = ReportingService(
        capital_reader=reader,
        shadow_reader=FakeShadowReader(shadow=shadow),
        mode_provider=lambda: RuntimeMode.SHADOW,
        v2_plans_reader=None,
    )
    projection = service.build(
        portfolio_id=PORTFOLIO, signal_session=SIGNAL_DATE, as_of=AS_OF
    )
    assert len(projection.planned_entries) == 1
    assert projection.planned_entries[0].fill_provenance is None
    assert projection.planned_entries[0].entry_status == "BROKER_ACK"
    assert projection.planned_entries[0].seal_id == SEAL_A


def test_build_step6_outer_try_preserves_projection_on_reconcile_failure() -> None:
    """m-2 回归守卫: ``_reconcile_planned_entries`` 内部异常 (此处
    ``DecisionLogicalKey`` 对空 portfolio_id 校验失败) 被 step 6 外层 try 捕获,
    projection 仍构建并记入 ``partial_failure["planned_entries"]``。兑现模块
    docstring "任一 step 部分失败不阻止其余 step; projection 恒构建" 防御契约。"""
    shadow = SimpleNamespace(
        counterfactual_lines=(
            SimpleNamespace(
                economic_lineage_id=ECONOMIC_KEY_A, security_id="000001.SZ"
            ),
        ),
        counterfactual_key=SimpleNamespace(
            counterfactual_cycle_id="daily-action-2026-08-05"
        ),
    )
    service = ReportingService(
        capital_reader=FakeCapitalReader(),
        shadow_reader=FakeShadowReader(shadow=shadow),
        mode_provider=lambda: RuntimeMode.SHADOW,
        v2_plans_reader=None,
    )
    projection = service.build(
        portfolio_id="", signal_session=SIGNAL_DATE, as_of=AS_OF
    )
    assert isinstance(projection, DailyOperatorProjection)
    assert projection.planned_entries == ()  # step 6 外层 try 兜底
    assert "planned_entries" in projection.partial_failure
