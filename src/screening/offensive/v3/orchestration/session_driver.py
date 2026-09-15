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

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime

from src.screening.offensive.v3.capital.fills import FillAttribution
from src.screening.offensive.v3.capital.repository import CapitalRepository
from src.screening.offensive.v3.contracts.execution import ExecutionSide
from src.screening.offensive.v3.execution.lifecycle import DailyBar
from src.screening.offensive.v3.execution.proxy_core import (
    ProxyCostScenario,
    ProxyOpenSettlement,
)
from src.screening.offensive.v3.capital.nav import ValuationMarkInput, ValuationRequest
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
    """One arm, one scenario, one session sequence — the minimal trial loop.

    ``bar_for`` source contract (final review P3-a, 2026-08-20): the driver is
    mechanism only — it accepts any lookup callable and cannot see where bars
    come from, so the contract lives here in prose. Official wiring MUST
    source every bar from the evidence timeline: per-session bar-set
    evidence records (``MarketBarSetPublisher``) decoded through
    ``bars_from_record`` / ``assemble_replay_session_facts`` before they
    reach this driver — the blessed junction is
    ``replay_assembly.evidence_backed_bar_for`` (signature accepts only the
    evidence repository and published records). A caller that feeds court
    CSVs, price_cache or any seeding source straight into ``bar_for``
    bypasses the Phase 5a data-surface adjudication, and its run is not an
    official replay.
    """

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
        bar_for: Callable[[date, str], "DailyBar | None"],
        initial_holdings: Mapping[str, OpenLine] | None = None,
    ) -> None:
        if not sessions:
            # R216: 单会话窗口 (signal==through 的自然日度调用形态) 合法 —
            # 结算该会话的到期入场 + 收盘估值即可; 出场与 UNKNOWN 顺延需要
            # 跨会话时由后续窗口覆盖 (覆盖性由 runner 的
            # advance_entry_window_skipped 门强制)。空窗口仍 fail-closed。
            raise SessionDriverError("sessions_too_short", "need at least one session")
        self._repository = repository
        self._arm = arm
        self._scenario = scenario
        self._sessions = sessions
        self._entries = entries_by_session
        self._attribution = attribution
        self._command_at = command_at
        self._send_deadline = send_deadline
        self._bar_for = bar_for
        # R224 continuation 窗口: 窗口起点前已开仓的持仓由 runner 从臂台账
        # open lots 种子传入 (身份经 pair 记录确定性重推导) — 没有种子, 窗口
        # 对窗口前持仓结构性失明 (marks/出场义务全丢), 这是 R216 覆盖门
        # 严格性的机制根源。种子持仓的出场同样走 ① 的 >= 顺延语义。
        self._initial_holdings = dict(initial_holdings or {})
        # R224: 窗口起步的「上次已知收盘」取自臂台账最新 as-observed 估值
        # (而非窗口局部记忆) —— 种子持仓的停牌顺延语义因此跨窗口成立, 重驱
        # 动会话的估值跳过 (首次观测为准) 也不再丢失顺延锚点。
        self._last_close: dict[str, int] = {}
        latest_valuation = ArmLedgerQuietReads(repository).latest_valuation_event()
        if latest_valuation is not None:
            _event_id, marks = latest_valuation
            self._last_close = {
                security_id: micros // 10_000
                for security_id, micros in marks.items()
            }

    def run(self) -> SessionDriverResult:
        result = SessionDriverResult()
        holdings: dict[str, _Holding] = {
            security: _Holding(line=line, entry_session_index=-1)
            for security, line in self._initial_holdings.items()
        }
        index_of = {s: i for i, s in enumerate(self._sessions)}
        result.held_by_session = {}  # 驱动器自记: 每会话结算后的持仓集 (marks 过滤事实源)
        for session in self._sessions:
            # ① 到期出场先于入场 (T+10 位 = 入场结算位 + 10)
            for security in sorted(holdings):
                holding = holdings[security]
                # >= 而非 ==: 出场日停牌/一字 UNKNOWN 时持仓保留, 下一会话
                # 继续重试 — 退出义务持续到成交 (宪法 #9 顺延语义; 审查
                # 2026-08-20: == 会把 UNKNOWN 后的仓位永久搁浅).
                if session >= holding.line.exit_session:
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
            # ③ 每会话收盘估值: mark-only VALUATION 事件 + AS_OBSERVED NAV
            # (close_valuation 权威原语; marks=当期持仓集的收盘价, 与 bars 同源
            # — marks/NAV 驱动属主审查 2026-08-20 的裁决落地)。R224: 首次
            # 观测为准 —— re-driven 会话已记录估值即跳过 (跨窗口重驱动的持仓
            # 集可能与首驱动不同: 跨窗口边界的 lot 已在别处平仓/开仓; 用当下
            # 持仓重写历史估值 = 回填伪造, 冲突拒收 = 每夜确定性崩溃; 台账
            # 自身的 empty-marks 重放同一 PIT 原则, 本处推广到非空 marks)。
            valuation_key = f"{self._arm}:valuation:{session:%Y%m%d}"
            if not valuation_already_recorded(
                ArmLedgerQuietReads(self._repository), valuation_key
            ):
                marks = []
                for security in sorted(holdings):
                    bar = self._bar_for(session, security)
                    if bar is not None and not bar.suspended:
                        self._last_close[security] = bar.close_cents
                    # 停牌日顺延上次已知收盘 (持仓不可交易, NAV 用最后可观测价);
                    # 从未见过 bar 的持仓不可能存在 (入场成交必先有 bar).
                    last = self._last_close.get(security)
                    if last is None:
                        raise SessionDriverError(
                            "held_security_never_marked",
                            f"{security} held at {session} with no observable close ever",
                        )
                    marks.append(
                        ValuationMarkInput(security_id=security, price_micros=last * 10_000)
                    )
                self._repository.close_valuation(
                    ValuationRequest(
                        idempotency_key=valuation_key,
                        source_authority="daily-bar-proxy.trial",
                        effective_at=self._command_at(session),
                        as_of=self._command_at(session),
                        expected_stream_version=self._repository.stream_version(),
                        marks=tuple(marks),
                    )
                )
        result.open_at_end = {sec: h.line.decision_id for sec, h in holdings.items()}
        result.conservation_ok, details = self._repository.rebuild_projections()
        result.conservation_details = tuple(details)
        return result


class ArmLedgerQuietReads:
    """CapitalRepository 的 quiet 读视图 (R224).

    open lots / position 行 / 最新 as-observed 估值 marks / 观察行存在性
    等读面在 ``GatewayTransactionContext`` 上; 本视图按
    ``capital_risk_snapshot`` 同款 quiet-read 惯例 (只读连接 + context)
    暴露 continuation 窗口所需的四个读面, 不增长 stream/capital version。
    """

    def __init__(self, repository: CapitalRepository) -> None:
        self._repository = repository

    def _context(self, conn):
        from src.screening.offensive.v3.capital.repository import (
            GatewayTransactionContext,
        )

        return GatewayTransactionContext(self._repository, conn)

    def position_row(self, position_lineage_id: str, economic_lot_id: str):
        with self._repository.engine.connect() as conn:
            return self._context(conn).position_row(position_lineage_id, economic_lot_id)

    def open_position_rows(self) -> tuple:
        with self._repository.engine.connect() as conn:
            return self._context(conn).open_position_rows()

    def latest_valuation_event(self):
        with self._repository.engine.connect() as conn:
            return self._context(conn).latest_valuation_event()

    def observation_row_for_event(self, kind, event_id):
        with self._repository.engine.connect() as conn:
            return self._context(conn).observation_row_for_event(kind, event_id)


def valuation_already_recorded(repository: CapitalRepository, valuation_key: str) -> bool:
    """首次观测为准 (R224): 该估值幂等键的 AS_OBSERVED 观察行是否已在案.

    re-driven 会话的持仓集可能与首驱动不同 (跨窗口边界的 lot 已在别处
    平仓/开仓), 重算 marks 要么回填伪造历史、要么幂等冲突崩链; 已记录即
    跳过 —— 与台账 empty-marks 重放路径同一 PIT 原则, 推广到非空 marks。
    """
    from src.screening.offensive.v3.capital.nav import ObservationKind
    from src.screening.offensive.v3.storage.metadata import derive_event_id

    return (
        repository.observation_row_for_event(
            ObservationKind.AS_OBSERVED, derive_event_id(valuation_key)
        )
        is not None
    )


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
