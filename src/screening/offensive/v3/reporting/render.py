"""Plan 05 Task 8: JSON / 中文终端 renderer — 共享同一 projection。

两个 renderer (``render_json`` / ``render_text``) **只从传入的
``DailyOperatorProjection`` 实例读**, 绝不独立查询状态、绝不调用任何 reader /
gateway / capital 句柄 (spec Task 8 Step 4: "JSON/text share the same projection
object and never independently derive status")。所有状态判定已由
``ReportingService.build`` 固化在 projection 字段与 ``headline_status()`` 中;
renderer 只负责呈现。

中文终端契约 (spec Task 8 Step 3 约束 3): 当 ``headline_status()`` 非
``"no_signal"`` 时, ``render_text`` 必须并列展示阻断/待处理原因, **绝不**单独
输出 "今日无信号" 文案误导操作员。仅当 ``headline_status() == "no_signal"`` 时
才展示"今日无信号"。

两个 renderer 的状态标签必须一致 (都来自同一 ``headline_status()``), 由 golden
test ``test_json_and_text_share_one_projection`` 锁定。
"""

from __future__ import annotations

import json
from typing import Any

from src.screening.offensive.v3.reporting.projection import DailyOperatorProjection

# headline_status 标签 → 中文文案。renderer 只用此映射呈现, 状态判定本身
# 全部来自 ``projection.headline_status()`` (绝不独立派生)。
_HEADLINE_ZH: dict[str, str] = {
    "risk_halted": "组合风控熔断 (risk_halted)",
    "stage_loss_halted": "阶段亏损熔断 (stage_loss_halted)",
    "reconciliation_halt": "对账挂起 (reconciliation_halt)",
    "insolvent": "账户无力偿付 (insolvent)",
    "terminating": "账户清算中 (terminating)",
    "blocked": "授权 fence 阻断 (blocked)",
    "partial_failure": "部分服务读取失败 (partial_failure)",
    "stale_capital": "资本快照过期 (stale_capital)",
    "unknown_capital": "资本新鲜度未知 (unknown_capital)",
    "proxy_fill": "代理执行已成交 (proxy_fill)",
    "manual_fill": "人工执行已成交 (manual_fill)",
    "broker_fill": "券商已回报成交 (broker_fill)",
    "send_claimed": "发送权已申领 (send_claimed)",
    "outbox_durable": "发件箱已持久化 (outbox_durable)",
    "permitted": "许可已签发 (permitted)",
    "submission_ambiguous": "提交结果待定 (submission_ambiguous)",
    "sealed": "决策已封存待执行 (sealed)",
    "shadow": "影子决策 (无执行授权)",
    "pending_exit": "有待处理退出义务 (pending_exit)",
    "reopened_by_correction": "退出义务经更正重开 (reopened_by_correction)",
    "no_signal": "今日无信号",
}


def _projection_dict(projection: DailyOperatorProjection) -> dict[str, Any]:
    """把 projection 序列化为 JSON 友好的 dict (含 headline_status)。

    只读 projection 字段 + ``headline_status()``; 绝不独立查状态。两个 renderer
    共享此派生, 保证 JSON 与 text 标签一致 (spec Task 8 Step 4)。
    """
    return {
        "portfolio_id": projection.portfolio_id,
        "as_of": projection.as_of.isoformat(),
        "signal_session": projection.signal_session.isoformat(),
        "runtime_mode": str(projection.runtime_mode),
        "execution_authority": projection.execution_authority,
        "headline_status": projection.headline_status(),
        "capital_read_status": projection.capital_read_status,
        "lifecycle_state": (
            None if projection.lifecycle_state is None
            else str(projection.lifecycle_state)
        ),
        "risk_halted": projection.risk_halted,
        "reconciliation_halt": projection.reconciliation_halt,
        "stage_loss_halted": projection.stage_loss_halted,
        "open_fence_count": projection.open_fence_count,
        "planned_entries": [
            {
                "economic_key": e.economic_key,
                "seal_id": e.seal_id,
                "entry_status": e.entry_status,
                "reconciled": e.reconciled,
                "executable": e.executable,
                "fill_provenance": e.fill_provenance,
            }
            for e in projection.planned_entries
        ],
        "pending_exits": [
            {
                "position_lineage_id": x.position_lineage_id,
                "economic_lot_id": x.economic_lot_id,
                "mandate_status": x.mandate_status,
                "reconciliation_pending": x.reconciliation_pending,
                "revision_kind": str(x.revision_kind),
            }
            for x in projection.pending_exits
        ],
        "shadow": (
            None if projection.shadow is None
            else {
                "execution_authority": projection.shadow.execution_authority,
                "counterfactual_line_count": (
                    projection.shadow.counterfactual_line_count
                ),
                "no_trade_reason": (
                    None if projection.shadow.no_trade_reason is None
                    else str(projection.shadow.no_trade_reason)
                ),
            }
        ),
        "account_capital_view": {
            "as_observed_nav_cents": projection.account_capital_view.as_observed_nav_cents,
            "available_cash_cents": projection.account_capital_view.available_cash_cents,
            "restricted_cash_cents": projection.account_capital_view.restricted_cash_cents,
            "reserved_cash_cents": projection.account_capital_view.reserved_cash_cents,
            "unsettled_cash_cents": projection.account_capital_view.unsettled_cash_cents,
            "total_gross_exposure_cents": projection.account_capital_view.total_gross_exposure_cents,
            "issued_unit_quanta": projection.account_capital_view.issued_unit_quanta,
        },
        "performance_view": {
            "lifetime_high_water_mark_cents": projection.performance_view.lifetime_high_water_mark_cents,
            "active_epoch_high_water_mark_cents": projection.performance_view.active_epoch_high_water_mark_cents,
            "lifetime_drawdown_ppm": projection.performance_view.lifetime_drawdown_ppm,
            "active_epoch_drawdown_ppm": projection.performance_view.active_epoch_drawdown_ppm,
            "mode": projection.performance_view.mode,
        },
        "partial_failure": dict(projection.partial_failure),
        "discrepancy": dict(projection.discrepancy),
    }


def render_json(projection: DailyOperatorProjection) -> str:
    """把 ``projection`` 渲染为 JSON 字符串 (机器可读 surface)。

    GREEN contract: 只读 ``projection`` 字段 (含 ``headline_status()``); 序列化
    为稳定的 JSON (字段集覆盖 portfolio_id / as_of / signal_session /
    runtime_mode / capital_read_status / lifecycle_state / 三个 halt 布尔 /
    open_fence_count / planned_entries / pending_exits / shadow /
    account_capital_view / performance_view / partial_failure / discrepancy /
    execution_authority / headline_status)。绝不独立查状态、绝不调用任何 reader。
    """
    return json.dumps(
        _projection_dict(projection),
        ensure_ascii=False,
        sort_keys=True,
    )


def render_text(projection: DailyOperatorProjection) -> str:
    """把 ``projection`` 渲染为中文终端文本 (操作员 surface)。

    GREEN contract: 只读 ``projection`` 字段 (含 ``headline_status()``)。
    headline_status() 非 ``"no_signal"`` 时, **绝不**单独出现 "今日无信号"
    文案 — 必须并列展示 halt / lifecycle / blocked / partial_failure / stale /
    executable entry / sealed / shadow / pending_exit / reopened 等原因 (spec
    约束 3)。仅 headline_status() == "no_signal" 时展示 "今日无信号"。
    ``execution_authority`` 文案恒标注 "无执行授权 (shadow)"。账户资本视图与
    业绩视图分别用独立标注呈现 (spec 约束 4)。绝不独立查状态、绝不调用任何
    reader。
    """
    headline = projection.headline_status()
    lines: list[str] = []
    lines.append(
        f"📋 组合操作员投影 — portfolio={projection.portfolio_id} "
        f"signal={projection.signal_session.isoformat()}"
    )
    # headline 文案 (含标签, 保证 JSON/text 标签一致)。
    lines.append(f"结论：{_HEADLINE_ZH.get(headline, headline)}")
    # execution_authority 恒标注 (spec 约束 2)。
    lines.append("授权：无执行授权 (shadow, execution_authority=none)")
    # 阻断/待处理原因并列展示 (spec 约束 3: headline 非 no_signal 时必须展示)。
    if projection.risk_halted:
        lines.append("⛔ risk_latch=RISK_HALTED")
    if projection.stage_loss_halted:
        lines.append("⛔ stage_loss_latch=STAGE_LOSS_HALTED")
    if projection.reconciliation_halt:
        lines.append("⛔ reconciliation_latch=RECONCILIATION_HALT")
    if projection.lifecycle_state is not None and str(
        projection.lifecycle_state
    ) not in ("ACTIVE", "LifecycleState.ACTIVE"):
        lines.append(f"⚠ lifecycle_state={projection.lifecycle_state}")
    if projection.open_fence_count > 0:
        lines.append(f"⚠ open_fence_count={projection.open_fence_count}")
    if projection.partial_failure:
        for step, reason in projection.partial_failure.items():
            lines.append(f"⚠ partial_failure[{step}]={reason}")
    if projection.capital_read_status not in ("ok",):
        lines.append(
            f"⚠ capital_read_status={projection.capital_read_status}"
        )
    # 计划入口 (active executable seals only)。
    executable = [e for e in projection.planned_entries if e.executable]
    if executable:
        lines.append(
            f"📌 可执行入口 ({len(executable)}): "
            + ", ".join(
                f"{e.economic_key}={e.entry_status}" for e in executable
            )
        )
    sealed = [
        e for e in projection.planned_entries
        if e.entry_status == "SEALED"
    ]
    if sealed:
        lines.append(
            f"影子封存 ({len(sealed)}): "
            + ", ".join(e.economic_key for e in sealed)
        )
    # shadow recommendation (auto surface)。
    if projection.shadow is not None:
        lines.append(
            f"🔮 auto 影子决策: {projection.shadow.counterfactual_line_count} "
            "条 counterfactual (无执行授权)"
        )
    # 待处理退出义务。
    pending = [
        x for x in projection.pending_exits if x.mandate_status == "PENDING"
    ]
    if pending:
        reopened = [
            x for x in pending
            if "REOPENED" in str(x.revision_kind)
        ]
        if reopened:
            lines.append(
                f"🔄 经更正重开的退出义务 ({len(reopened)})"
            )
        lines.append(
            f"📤 待处理退出义务 ({len(pending)}): "
            + ", ".join(
                x.position_lineage_id for x in pending
            )
        )
    # 两个独立标注视图 (spec 约束 4)。
    ac = projection.account_capital_view
    lines.append(
        f"💰 账户资本: NAV={ac.as_observed_nav_cents} "
        f"可用现金={ac.available_cash_cents} "
        f"总毛敞口={ac.total_gross_exposure_cents}"
    )
    pv = projection.performance_view
    lines.append(
        f"📈 业绩 (mode={pv.mode}): "
        f"lifetime_HWM={pv.lifetime_high_water_mark_cents} "
        f"drawdown={pv.lifetime_drawdown_ppm}ppm"
    )
    # v2↔v3 差异 (仅当有差异)。
    if projection.discrepancy:
        lines.append(
            f"🔁 v2↔v3 差异: {dict(projection.discrepancy)}"
        )
    return "\n".join(lines)


__all__ = [
    "render_json",
    "render_text",
]
