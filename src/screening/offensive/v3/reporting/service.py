"""Plan 05 Task 8: ``ReportingService`` — 从 v3 子系统只读投影派生 ``DailyOperatorProjection``。

reporting service 是一个**纯只读组合器**: 它**绝不**给 gateway 加 portfolio-wide
listing query (gateway 按 design 是 keyed-only, ``test_entry_projection.py:7``),
而是组合 keyed 读取派生 projection — **计划入口集** (``planned_entries``) 的
universe = ``ShadowDecision.counterfactual_lines`` (auto recommendation 想下什么
单); capital snapshot 现有 positions 的 lot **不**入计划入口集 (持仓属退出侧,
由 ``pending_exits`` 覆盖), 避免既有敞口被误报为"今日计划入口"。对每个
shadow line 用决策级 ``DecisionLogicalKey`` 经 ``active_seal`` + ``entry_state``
对账 (``test_entry_projection.py:10-11`` "operator projection composes keyed
reads")。

-------------------------------------------------------------------------------
注入端口 (全部鸭子类型 / Protocol; 真实实现不在本任务)
-------------------------------------------------------------------------------
- ``capital_reader`` — ``CapitalGatewayApi`` 鸭子类型, 暴露 quiet 读面
  ``risk_snapshot`` / ``authority_state`` / ``entry_state`` / ``active_seal`` /
  ``exit_state`` / ``lifecycle_state`` (后者的真实透传见
  ``services/capital_gateway_api.py``)。本任务内 ``lifecycle_state`` 是新增的
  quiet 读方法 (透传 ``CapitalRepository.lifecycle_state``, capital/repository.py:
  5811)。
- ``shadow_reader`` — ``ShadowDecisionReader`` Protocol (本模块定义); 读回持久化
  的 ``ShadowDecision``。当前 ``ShadowPersisterPort`` (orchestration/
  daily_action_flow.py:252) 只写不读, 真实读实现不在本任务 (Task 9 集成); 测试
  用 fake 注入。
- ``mode_provider`` — ``Callable[[], RuntimeMode]``, 每次 build 最先读。
- ``v2_plans_reader`` — ``Callable[[date], tuple] | None``; 注入则对比 v2↔v3
  (discrepancy), ``None`` → 不对比。

-------------------------------------------------------------------------------
对账逻辑 (GREEN contract)
-------------------------------------------------------------------------------
``build(portfolio_id, signal_session, as_of)`` 依序:

1. ``mode = mode_provider()``。
2. capital: ``risk_snapshot(portfolio_id, as_of)`` try/except — 异常 →
   ``capital_read_status="failed"`` + ``partial_failure["capital"]``; 成功 →
   按 freshness/completeness 派生 ``"ok"``/``"stale"``/``"unknown"``。从 snapshot
   派生 ``risk_halted`` / ``reconciliation_halt`` / ``stage_loss_halted`` /
   ``account_capital_view`` / ``performance_view``。
3. lifecycle: ``lifecycle_state(portfolio_id)`` try/except — 异常 → None +
   ``partial_failure["lifecycle"]``。
4. authority: ``authority_state(portfolio_id)`` → ``open_fence_count`` (blocked).
5. shadow: ``shadow_reader.active_shadow(portfolio_id, signal_session)``
   try/except — 异常 → ``partial_failure["shadow"]``; 返回 ``ShadowDecision``
   则派生 ``ShadowDecisionSummary`` (恒 ``execution_authority="none"``)。
6. planned entries: 入口集 universe = shadow counterfactual lines; 所有
   line 共享同一决策级 ``DecisionLogicalKey`` (一个决策一个 seal):
   ``active_seal(key)`` → seal_id; ``entry_state(seal_id)`` → status; 每
   line 派生一个 ``PlannedEntryView`` (reconciled / executable per
   ``EXECUTABLE_ENTRY_STATUSES``)。capital positions 的 lot 不入此集 (由
   step 7 ``pending_exits`` 覆盖)。
7. pending exits: 对 capital positions 每个 lot ``exit_state(lineage, lot)``
   → ``PendingExitView`` (status PENDING/TERMINAL_LEGAL/CLOSED + revision_kind);
   PENDING 即 pending_exit。
8. discrepancy: ``v2_plans_reader(signal_session)`` vs shadow counterfactual
   (归一化 ticker 对比, 同 daily_action_flow); 异常 →
   ``partial_failure["v2_comparison"]``。

任一 step 的部分失败不阻止其余 step; projection 恒构建。最终返回不可变
``DailyOperatorProjection``。
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Callable, Protocol, runtime_checkable

from src.screening.offensive.v3.policy.models import RuntimeMode
from src.screening.offensive.v3.reporting.projection import (
    AccountCapitalView,
    DailyOperatorProjection,
    EXECUTABLE_ENTRY_STATUSES,
    PendingExitView,
    PerformanceView,
    PlannedEntryView,
    ShadowDecisionSummary,
)


@runtime_checkable
class ShadowDecisionReader(Protocol):
    """鸭子类型只读 ShadowDecision reader — 读回持久化的 ShadowDecision。

    真实实现不在本任务 (Task 9 集成): 当前 ``ShadowPersisterPort``
    (orchestration/daily_action_flow.py:252) 只写不读。返回 ``None`` 表示该
    signal_session 无持久化的 shadow decision (合法, 非失败)。reporting service
    对异常 try/except 记入 ``partial_failure["shadow"]``。
    """

    def active_shadow(
        self, portfolio_id: str, signal_session: date
    ) -> Any: ...


@runtime_checkable
class CapitalReaderPort(Protocol):
    """鸭子类型只读 capital reader — ``CapitalGatewayApi`` 的 quiet 读面子集。

    暴露 ``risk_snapshot`` / ``authority_state`` / ``entry_state`` /
    ``active_seal`` / ``exit_state`` / ``lifecycle_state``。真实实现
    ``CapitalGatewayApi`` (services/capital_gateway_api.py); 测试注入 fake
    (``FakeCapitalReader``)。全部 quiet 读 — 绝不增长 stream/capital version。
    """

    def risk_snapshot(self, portfolio_id: str, as_of: datetime) -> Any: ...

    def authority_state(self, portfolio_id: str) -> Any: ...

    def entry_state(self, seal_id: str) -> Any: ...

    def active_seal(self, logical_key: Any) -> Any: ...

    def exit_state(
        self, position_lineage_id: str, economic_lot_id: str
    ) -> Any: ...

    def lifecycle_state(self, portfolio_id: str) -> Any: ...


class ReportingService:
    """只读组合器: 从 v3 子系统只读投影派生 ``DailyOperatorProjection``。

    构造器注入 ``capital_reader`` (``CapitalGatewayApi`` 鸭子类型)、
    ``shadow_reader`` (``ShadowDecisionReader``)、``mode_provider`` 与可选的
    ``v2_plans_reader``。``build`` 不调用任何写面; 任一 step 部分失败记入
    projection.partial_failure, projection 仍构建。
    """

    def __init__(
        self,
        *,
        capital_reader: CapitalReaderPort,
        shadow_reader: ShadowDecisionReader,
        mode_provider: Callable[[], RuntimeMode],
        v2_plans_reader: Callable[[date], tuple[Any, ...]] | None = None,
    ) -> None:
        """构造只读 reporting service (完整语义见模块 docstring)。

        Args:
            capital_reader: ``CapitalGatewayApi`` 鸭子类型 quiet 读面 (含
                ``lifecycle_state``)。
            shadow_reader: 只读 ShadowDecision reader Protocol; 真实实现 Task 9。
            mode_provider: 每次 ``build`` 最先读取的 runtime_mode 投影。
            v2_plans_reader: 返回当日 v2 计划 tuple 的只读 reader (元素只需
                ``.ticker``); ``None`` → 不对比 v2↔v3。
        """
        self._capital_reader = capital_reader
        self._shadow_reader = shadow_reader
        self._mode_provider = mode_provider
        self._v2_plans_reader = v2_plans_reader

    def build(
        self,
        *,
        portfolio_id: str,
        signal_session: date,
        as_of: datetime,
    ) -> DailyOperatorProjection:
        """派生一份 ``DailyOperatorProjection`` (keyed 读组合, 只读, 不崩溃)。

        GREEN contract 见模块 docstring "对账逻辑"。任一 step 部分失败 →
        ``partial_failure``, 但 projection 仍构建并返回。两个 renderer 共享返回
        的同一实例, 绝不独立查状态。
        """
        from types import MappingProxyType

        from src.screening.offensive.v3.contracts.capital import (
            ReconciliationLatchState,
            RiskLatchState,
            RiskSnapshotCompleteness,
            RiskSnapshotFreshness,
            StageLossLatchState,
        )
        from src.screening.offensive.v3.kernel.models import BlockReason

        reasons: dict[str, str] = {}
        mode = self._mode_provider()

        # 2. capital (risk_snapshot try/except; 派生 halt/视图/新鲜度)。
        capital = None
        capital_read_status = "ok"
        try:
            capital = self._capital_reader.risk_snapshot(portfolio_id, as_of)
        except Exception as exc:
            capital_read_status = "failed"
            reasons["capital"] = f"{type(exc).__name__}: {exc}"
        risk_halted = False
        reconciliation_halt = False
        stage_loss_halted = False
        account_view = AccountCapitalView(
            as_observed_nav_cents=0,
            available_cash_cents=0,
            restricted_cash_cents=0,
            reserved_cash_cents=0,
            unsettled_cash_cents=0,
            total_gross_exposure_cents=0,
            issued_unit_quanta=0,
        )
        performance_view = PerformanceView(
            lifetime_high_water_mark_cents=0,
            active_epoch_high_water_mark_cents=0,
            lifetime_drawdown_ppm=0,
            active_epoch_drawdown_ppm=0,
            mode="",
        )
        if capital is not None:
            risk_halted = capital.risk_latch is RiskLatchState.RISK_HALTED
            reconciliation_halt = (
                capital.reconciliation_latch
                is ReconciliationLatchState.RECONCILIATION_HALT
            )
            stage_loss_halted = any(
                latch.state is StageLossLatchState.STAGE_LOSS_HALTED
                for latch in capital.stage_loss_latches
            )
            if capital_read_status != "failed":
                # 派生与 kernel BLOCK 语义对齐 (kernel/risk.py:78-85): kernel 对
                # freshness=UNKNOWN (UNKNOWN_CAPITAL_FRESHNESS) 与 completeness
                # ≠COMPLETE (UNKNOWN_EXPOSURE) 均直接 BLOCK。reporting 须把这两类
                # 投影为 "unknown", 而非误判 "ok" 否则操作员看到 "今日无信号" 而
                # kernel 实际拒绝交易。仅 freshness=FRESH 且 completeness=COMPLETE
                # 才 "ok"; STALE 单独标 "stale"。
                if capital.freshness is RiskSnapshotFreshness.STALE:
                    capital_read_status = "stale"
                elif capital.freshness is RiskSnapshotFreshness.UNKNOWN:
                    capital_read_status = "unknown"
                elif (
                    capital.completeness
                    is RiskSnapshotCompleteness.COMPLETE
                ):
                    capital_read_status = "ok"
                else:
                    capital_read_status = "unknown"
            account_view = AccountCapitalView(
                as_observed_nav_cents=capital.as_observed_nav_cents,
                available_cash_cents=capital.available_cash_cents,
                restricted_cash_cents=capital.restricted_cash_cents,
                reserved_cash_cents=capital.reserved_cash_cents,
                unsettled_cash_cents=capital.unsettled_cash_cents,
                total_gross_exposure_cents=capital.total_gross_exposure_cents,
                issued_unit_quanta=capital.issued_unit_quanta,
            )
            performance_view = PerformanceView(
                lifetime_high_water_mark_cents=(
                    capital.lifetime_high_water_mark_cents
                ),
                active_epoch_high_water_mark_cents=(
                    capital.active_epoch_high_water_mark_cents
                ),
                lifetime_drawdown_ppm=capital.lifetime_drawdown_ppm,
                active_epoch_drawdown_ppm=capital.active_epoch_drawdown_ppm,
                mode=str(capital.mode),
            )

        # 3. lifecycle (lifecycle_state try/except)。
        lifecycle_state = None
        try:
            lifecycle_state = self._capital_reader.lifecycle_state(
                portfolio_id
            )
        except Exception as exc:
            reasons["lifecycle"] = f"{type(exc).__name__}: {exc}"

        # 4. authority (open_fence_count)。
        open_fence_count = 0
        try:
            authority = self._capital_reader.authority_state(portfolio_id)
            if authority is not None:
                open_fence_count = int(authority.open_fence_count)
        except Exception as exc:
            reasons["authority"] = f"{type(exc).__name__}: {exc}"

        # 5. shadow (active_shadow try/except)。
        shadow_summary: ShadowDecisionSummary | None = None
        shadow_lines: tuple = ()
        decision_cycle_id = ""
        try:
            shadow_decision = self._shadow_reader.active_shadow(
                portfolio_id, signal_session
            )
            if shadow_decision is not None:
                shadow_lines = tuple(
                    shadow_decision.counterfactual_lines
                )
                decision_cycle_id = (
                    shadow_decision.counterfactual_key.counterfactual_cycle_id
                )
                shadow_summary = ShadowDecisionSummary(
                    execution_authority="none",
                    counterfactual_line_count=len(shadow_lines),
                    no_trade_reason=None,
                )
        except Exception as exc:
            reasons["shadow"] = f"{type(exc).__name__}: {exc}"

        # 6. planned entries (keyed 对账: shadow economic keys; 每 key
        # active_seal + entry_state)。外层 try 兑现模块 docstring "任一 step
        # 部分失败不阻止其余 step; projection 恒构建"。
        try:
            planned_entries = self._reconcile_planned_entries(
                portfolio_id=portfolio_id,
                signal_session=signal_session,
                decision_cycle_id=decision_cycle_id,
                shadow_lines=shadow_lines,
                reasons=reasons,
            )
        except Exception as exc:
            reasons["planned_entries"] = f"{type(exc).__name__}: {exc}"
            planned_entries = ()

        # 7. pending exits (capital positions 每 lot exit_state)。外层 try 同上。
        try:
            pending_exits = self._collect_pending_exits(capital, reasons)
        except Exception as exc:
            reasons["pending_exits"] = f"{type(exc).__name__}: {exc}"
            pending_exits = ()

        # 8. discrepancy (v2↔v3; 仅当 v2_plans_reader 注入)。
        discrepancy: dict[str, str] = {}
        if self._v2_plans_reader is not None:
            try:
                discrepancy = self._compare_v2(
                    self._v2_plans_reader(signal_session), shadow_lines
                )
            except Exception as exc:
                reasons["v2_comparison"] = f"{type(exc).__name__}: {exc}"

        return DailyOperatorProjection(
            portfolio_id=portfolio_id,
            as_of=as_of,
            signal_session=signal_session,
            runtime_mode=mode,
            capital=capital,
            capital_read_status=capital_read_status,
            lifecycle_state=lifecycle_state,
            risk_halted=risk_halted,
            reconciliation_halt=reconciliation_halt,
            stage_loss_halted=stage_loss_halted,
            open_fence_count=open_fence_count,
            planned_entries=planned_entries,
            pending_exits=pending_exits,
            shadow=shadow_summary,
            account_capital_view=account_view,
            performance_view=performance_view,
            partial_failure=MappingProxyType(reasons),
            discrepancy=MappingProxyType(discrepancy),
        )

    def _reconcile_planned_entries(
        self,
        *,
        portfolio_id: str,
        signal_session,
        decision_cycle_id: str,
        shadow_lines: tuple,
        reasons: dict[str, str],
    ) -> tuple[PlannedEntryView, ...]:
        """keyed 对账入口集: shadow counterfactual economic keys; 每 key 用
        决策级 ``DecisionLogicalKey`` 经 ``active_seal`` + ``entry_state`` 对账
        → ``PlannedEntryView``。所有 line 共享同一决策 logical key (一个决策
        一个 seal); 经济差异由 ``economic_lineage_id`` 区分。"""
        from src.screening.offensive.v3.contracts.decision import (
            DecisionLogicalKey,
        )

        if not shadow_lines or not decision_cycle_id:
            return ()
        logical_key = DecisionLogicalKey(
            portfolio_id=portfolio_id,
            signal_session=signal_session,
            decision_cycle_id=decision_cycle_id,
        )
        seal_id = None
        entry_status = None
        fill_provenance = None
        try:
            active = self._capital_reader.active_seal(logical_key)
            if active is not None:
                seal_id = active[0]
        except Exception as exc:
            reasons["active_seal"] = f"{type(exc).__name__}: {exc}"
        if seal_id is not None:
            try:
                entry = self._capital_reader.entry_state(seal_id)
                if entry is not None:
                    entry_status = entry.status
                    # fill_provenance 从 entry_state 读; broker plan 接通
                    # ``EntryStateProjection.fill_provenance`` 字段后自动生效。
                    # 当前该字段不存在 (decisions.py:272-282) → 恒 None, 且
                    # BROKER_ACK 经 gateway 在本 plan 不可达 (claim_send 禁用),
                    # 故 proxy_fill/manual_fill/broker_fill 三态在 build() 路径
                    # 下当前不可达; 见 ``PlannedEntryView.fill_provenance`` docstring。
                    fill_provenance = getattr(entry, "fill_provenance", None)
            except Exception as exc:
                reasons["entry_state"] = f"{type(exc).__name__}: {exc}"
        return tuple(
            PlannedEntryView(
                economic_key=line.economic_lineage_id,
                seal_id=seal_id,
                entry_status=entry_status,
                reconciled=seal_id is not None,
                executable=entry_status in EXECUTABLE_ENTRY_STATUSES,
                fill_provenance=fill_provenance,
            )
            for line in shadow_lines
        )

    def _collect_pending_exits(
        self, capital, reasons: dict[str, str]
    ) -> tuple[PendingExitView, ...]:
        """对 capital positions 每 lot 调 exit_state → PendingExitView。"""
        if capital is None:
            return ()
        views: list[PendingExitView] = []
        for position in capital.positions:
            try:
                exit_view = self._capital_reader.exit_state(
                    position.position_lineage_id,
                    position.economic_lot_id,
                )
            except Exception as exc:
                reasons["exit_state"] = f"{type(exc).__name__}: {exc}"
                continue
            if exit_view is None:
                continue
            views.append(
                PendingExitView(
                    position_lineage_id=position.position_lineage_id,
                    economic_lot_id=position.economic_lot_id,
                    mandate_status=exit_view.status,
                    reconciliation_pending=exit_view.reconciliation_pending,
                    revision_kind=exit_view.revision_kind,
                )
            )
        return tuple(views)

    def _compare_v2(
        self, v2_plans: tuple, shadow_lines: tuple
    ) -> dict[str, str]:
        """归一化 ticker 对比 v2 plans vs shadow counterfactual lines。"""
        from src.screening.offensive.v3.orchestration.daily_action_flow import (
            _normalize_ticker,
        )

        v3_tickers = {
            _normalize_ticker(line.security_id)
            for line in shadow_lines
        }
        v2_tickers = {
            _normalize_ticker(plan.ticker) for plan in v2_plans
        }
        discrepancy: dict[str, str] = {}
        for ticker in sorted(v2_tickers - v3_tickers):
            discrepancy[ticker] = "v2_only"
        for ticker in sorted(v3_tickers - v2_tickers):
            discrepancy[ticker] = "v3_only"
        return discrepancy


__all__ = [
    "CapitalReaderPort",
    "ReportingService",
    "ShadowDecisionReader",
]
