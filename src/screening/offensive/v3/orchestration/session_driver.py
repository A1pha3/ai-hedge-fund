"""Sequential session lifecycle driver — Phase 6 (2026-08-20).

Wires the Phase 5 primitives into the per-session trial loop: for each session
in order — settle due exits first (freeing cash), then due entries; assemble
that session's facts lazily with the CURRENT held set (the marks discipline
requires it: a mark for a flat security is a conflict, and holdings evolve
during the run — facts cannot be pre-frozen); settle through
``drive_open_settlement`` (locked judgment + scenario slippage + fee +
reserve); verify capital conservation at the end.

Exit timing mirrors the T+10 schedule contract: the exit settles ten session
positions after the entry settlement session. Positions still open at the end
of the window are disclosed, never force-closed.

Offline primitive: drives restored/offline arm ledgers only; no kernel, no
authority, not an activation of anything.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime

from src.screening.offensive.v3.capital.fills import FillAttribution
from src.screening.offensive.v3.capital.repository import CapitalRepository
from src.screening.offensive.v3.contracts.execution import ExecutionSide
from src.screening.offensive.v3.execution.proxy_core import (
    ProxyCostScenario,
    ProxyOpenSettlement,
)
from src.screening.offensive.v3.orchestration.arm_lifecycle import drive_open_settlement

EXIT_SESSION_OFFSET = 10  # T+10 open exit (the fixed executable contract)


class SessionDriverError(RuntimeError):
    def __init__(self, code: str, message: str, **details: object) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.details = details


@dataclass(frozen=True)
class OpenLine:
    """One caller-derived executable line settling at a given session."""

    decision_id: str
    security_id: str
    quantity: int
    #: 入场限价 = 买入上限; 出场限价 = 卖出下限 — 两个方向语义, 必须显式分开
    #: (审查 2026-08-20: 出场复用入场限价把买上限当卖下限, 永不触及).
    limit_price_cents: int
    exit_limit_price_cents: int
    #: 出场会话由冻结排程日期驱动 (kernel 行的 target_exit_session) — 排程是
    #: 权威, 驱动器不做位次算术 (kernel 接线审查 2026-08-20).
    exit_session: date
    position_lineage_id: str
    economic_lot_id: str


@dataclass
class _Holding:
    line: OpenLine
    entry_session_index: int


@dataclass
class SessionDriverResult:
    settlements: dict[tuple[date, str, str], ProxyOpenSettlement] = field(default_factory=dict)
    open_at_end: dict[str, str] = field(default_factory=dict)  # security -> decision_id
    held_by_session: dict[date, frozenset[str]] = field(default_factory=dict)
    conservation_ok: bool = False
    conservation_details: tuple[str, ...] = ()


class SessionLifecycleDriver:
    """One arm, one scenario, one session sequence — the minimal trial loop."""

    def __init__(
        self,
        *,
        repository: CapitalRepository,
        arm: str,
        scenario: ProxyCostScenario,
        sessions: tuple[date, ...],
        entries_by_session: dict[date, tuple[OpenLine, ...]],
        attribution: FillAttribution,
        command_at: Callable[[date], datetime],
        send_deadline: Callable[[date], datetime],
        bar_for: Callable[[date, str], "object | None"],
    ) -> None:
        if len(sessions) < 2:
            raise SessionDriverError("sessions_too_short", "need at least two sessions")
        self._repository = repository
        self._arm = arm
        self._scenario = scenario
        self._sessions = sessions
        self._entries = entries_by_session
        self._attribution = attribution
        self._command_at = command_at
        self._send_deadline = send_deadline
        self._bar_for = bar_for

    def run(self) -> SessionDriverResult:
        result = SessionDriverResult()
        holdings: dict[str, _Holding] = {}
        index_of = {s: i for i, s in enumerate(self._sessions)}
        result.held_by_session = {}  # 驱动器自记: 每会话结算后的持仓集 (marks 过滤事实源)
        for session in self._sessions:
            # ① 到期出场先于入场 (T+10 位 = 入场结算位 + 10)
            for security in sorted(holdings):
                holding = holdings[security]
                if session == holding.line.exit_session:
                    settlement = drive_open_settlement(
                        self._repository,
                        arm=self._arm,
                        decision_id=holding.line.decision_id,
                        side=ExecutionSide.EXIT,
                        security_id=security,
                        position_lineage_id=holding.line.position_lineage_id,
                        economic_lot_id=holding.line.economic_lot_id,
                        limit_price_cents=holding.line.exit_limit_price_cents,
                        quantity=holding.line.quantity,
                        bar=self._bar_for(session, security),
                        command_at=self._command_at(session),
                        send_deadline=self._send_deadline(session),
                        attribution=self._attribution,
                        scenario=self._scenario,
                    )
                    result.settlements[(session, security, "exit")] = settlement
                    if settlement.fill_receipt is not None:
                        del holdings[security]
            # ② 当日入场
            for line in self._entries.get(session, ()):
                if line.security_id in holdings:
                    raise SessionDriverError(
                        "duplicate_holding",
                        f"{line.security_id} already held at {session}",
                    )
                settlement = drive_open_settlement(
                    self._repository,
                    arm=self._arm,
                    decision_id=line.decision_id,
                    side=ExecutionSide.ENTRY,
                    security_id=line.security_id,
                    position_lineage_id=line.position_lineage_id,
                    economic_lot_id=line.economic_lot_id,
                    limit_price_cents=line.limit_price_cents,
                    quantity=line.quantity,
                    bar=self._bar_for(session, line.security_id),
                    command_at=self._command_at(session),
                    send_deadline=self._send_deadline(session),
                    attribution=self._attribution,
                    scenario=self._scenario,
                )
                result.settlements[(session, line.security_id, "entry")] = settlement
                if settlement.fill_receipt is not None:
                    holdings[line.security_id] = _Holding(line=line, entry_session_index=index_of[session])
            result.held_by_session[session] = frozenset(holdings)
        result.open_at_end = {sec: h.line.decision_id for sec, h in holdings.items()}
        result.conservation_ok, details = self._repository.rebuild_projections()
        result.conservation_details = tuple(details)
        return result


#: T+10 无条件开盘卖出的限价表达: 卖出下限取 1 分 = 恒触及、按开盘价成交
#: (执行合约: 到期无条件卖出 — 映射审查 2026-08-20).
UNCONDITIONAL_EXIT_LIMIT_CENTS: int = 1


def open_line_from_shadow_line(line, *, entry_session: date) -> OpenLine:
    """Map one kernel ``ShadowOrderLine`` to a driver ``OpenLine``.

    Kernel line is authority for identity/quantity/limits/dates; lot and
    lineage ids derive deterministically from the shadow line id so replays
    reproduce identical capital identities. Entry limit = the line's buy
    ceiling; exit = the frozen ``target_exit_session`` at an unconditional
    open sell (1-cent floor fills at open).
    """
    return OpenLine(
        decision_id=line.shadow_line_id,
        security_id=line.security_id,
        quantity=int(line.target_quantity_units),
        limit_price_cents=int(line.limit_price_cents),
        exit_limit_price_cents=UNCONDITIONAL_EXIT_LIMIT_CENTS,
        exit_session=line.target_exit_session,
        position_lineage_id=f"shadow:{line.shadow_line_id}",
        economic_lot_id=f"lot:{line.shadow_line_id}",
    )


__all__ = [
    "EXIT_SESSION_OFFSET",
    "OpenLine",
    "SessionDriverError",
    "SessionDriverResult",
    "SessionLifecycleDriver",
    "UNCONDITIONAL_EXIT_LIMIT_CENTS",
    "open_line_from_shadow_line",
]
