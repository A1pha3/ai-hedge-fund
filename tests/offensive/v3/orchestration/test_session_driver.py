"""SessionLifecycleDriver — Phase 6 (2026-08-20).

锁定: 出场先于入场 / T+10 位出场时点 / 持仓集逐会话演化记录 (marks 过滤
事实源) / 窗口末端持仓披露不强制平仓 / 全程守恒重验 / 双情景独立运行。
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.screening.offensive.v3.capital.flows import GenesisRequest
from src.screening.offensive.v3.capital.fills import FillAttribution
from src.screening.offensive.v3.capital.identity import AccountBinding
from src.screening.offensive.v3.capital.repository import CapitalRepository
from src.screening.offensive.v3.contracts.base import ExecutionMode
from src.screening.offensive.v3.execution.lifecycle import DailyBar, OpenExecutionVerdict
from src.screening.offensive.v3.orchestration.arm_lifecycle import (
    CURRENT_COST_SCENARIO,
    DOUBLE_SLIPPAGE_SCENARIO,
)
from src.screening.offensive.v3.orchestration.session_driver import (
    EXIT_SESSION_OFFSET,
    OpenLine,
    SessionDriverError,
    SessionLifecycleDriver,
)

UTC = timezone.utc
ATTR = FillAttribution(
    producer_namespace="btst", research_program_id="prog-1",
    economic_lineage_id="eline-1", stage_id="stage-1",
)


def _sessions(n: int = 13) -> tuple[date, ...]:
    start = date(2026, 8, 20)
    return tuple(start + timedelta(days=i) for i in range(n))  # 周末无关紧要: 时序按位


def _repo(tmp_path: Path, name: str) -> CapitalRepository:
    t = datetime(2026, 8, 20, 9, 30, tzinfo=UTC)
    repository = CapitalRepository.initialize(tmp_path / f"{name}.sqlite3")
    repository.initialize_genesis(
        GenesisRequest(
            idempotency_key=f"genesis-{name}",
            account_binding=AccountBinding(
                portfolio_id="trial-portfolio", mode=ExecutionMode.DAILY_BAR_PROXY,
                broker_account_id=None, base_currency="CNY", environment_fingerprint=None,
            ),
            unit_quanta=10_000, unit_price_numerator=1_000, unit_price_denominator=1,
            source_authority="test.seed", authorization_reference="auth-1",
            effective_at=t, as_of=t,
        )
    )
    return repository


def _bar(session: date, sec: str, open_c: int = 1000) -> DailyBar:
    return DailyBar(
        security_id=sec, session=session, open_cents=open_c, high_cents=open_c + 20,
        low_cents=open_c - 20, close_cents=open_c + 5, limit_up_cents=1100,
        limit_down_cents=900,
    )


def _driver(repo, sessions, entries, scenario=CURRENT_COST_SCENARIO):
    return SessionLifecycleDriver(
        repository=repo, arm="champion", scenario=scenario, sessions=sessions,
        entries_by_session=entries, attribution=ATTR,
        command_at=lambda s: datetime(s.year, s.month, s.day, 9, 30, tzinfo=UTC),
        send_deadline=lambda s: datetime(s.year, s.month, s.day, 10, 0, tzinfo=UTC),
        bar_for=lambda s, sec: _bar(s, sec),
    )


def _line(sec: str, decision: str, limit: int = 1050, exit_limit: int = 900,
           exit_session: date | None = None, sessions=None) -> OpenLine:
    return OpenLine(
        decision_id=decision, security_id=sec, quantity=100, limit_price_cents=limit,
        exit_limit_price_cents=exit_limit,
        exit_session=exit_session or sessions[1 + EXIT_SESSION_OFFSET],
        position_lineage_id=f"lin-{sec}", economic_lot_id=f"lot-{sec}",
    )


def test_full_cycle_entry_exit_conservation(tmp_path):
    sessions = _sessions(13)
    entry_session = sessions[1]  # T+1
    entries = {entry_session: (_line("600000.SH", "cyc-1", sessions=sessions),)}
    result = _driver(_repo(tmp_path, "full"), sessions, entries).run()
    exit_session = sessions[1 + EXIT_SESSION_OFFSET]  # T+11 位 = 入场 + 10 位
    entry = result.settlements[(entry_session, "600000.SH", "entry")]
    exit_s = result.settlements[(exit_session, "600000.SH", "exit")]
    assert entry.verdict is OpenExecutionVerdict.FILLED and entry.fee_receipt is not None
    assert exit_s.verdict is OpenExecutionVerdict.FILLED
    assert result.open_at_end == {}  # 全周期平仓
    # 持仓集演化: 入场前空, 持有期含标的, 出场后复空 (marks 过滤事实源)
    assert "600000.SH" not in result.held_by_session[sessions[0]]
    assert "600000.SH" in result.held_by_session[sessions[5]]
    assert "600000.SH" not in result.held_by_session[exit_session]
    assert result.conservation_ok, result.conservation_details


def test_open_at_end_disclosed_not_force_closed(tmp_path):
    sessions = _sessions(5)  # 窗口不足 T+10
    entries = {sessions[1]: (_line("600000.SH", "cyc-1", exit_session=sessions[99] if len(sessions) > 99 else date(2027, 1, 1), sessions=sessions),)}
    result = _driver(_repo(tmp_path, "open"), sessions, entries).run()
    assert result.open_at_end == {"600000.SH": "cyc-1"}
    assert "exit" not in [k[2] for k in result.settlements]
    assert result.conservation_ok


def test_duplicate_holding_rejected_and_scenarios_independent(tmp_path):
    sessions = _sessions(4)
    far = date(2027, 1, 1)
    entries = {sessions[1]: (_line("600000.SH", "cyc-1", exit_session=far),), sessions[2]: (_line("600000.SH", "cyc-2", exit_session=far),)}
    with pytest.raises(SessionDriverError) as ei:
        _driver(_repo(tmp_path, "dup"), sessions, entries).run()
    assert ei.value.code == "duplicate_holding"
    # 双情景各自独立台账运行
    long_sessions = _sessions(13)
    r30 = _driver(_repo(tmp_path, "s30"), long_sessions,
                  {long_sessions[1]: (_line("600000.SH", "cyc-1", sessions=long_sessions),)}).run()
    r60 = _driver(
        _repo(tmp_path, "s60"), long_sessions,
        {long_sessions[1]: (_line("600000.SH", "cyc-1", sessions=long_sessions),)},
        scenario=DOUBLE_SLIPPAGE_SCENARIO,
    ).run()
    e30 = r30.settlements[(long_sessions[1], "600000.SH", "entry")].fill_price_cents
    e60 = r60.settlements[(long_sessions[1], "600000.SH", "entry")].fill_price_cents
    assert e60 > e30  # 60bps 买入更不利
    assert r30.conservation_ok and r60.conservation_ok


def test_open_line_from_shadow_line_mapping():
    """kernel 行 → OpenLine: 身份/量/限价/日期逐字段映射, 无条件出场=1分下限."""
    from src.screening.offensive.v3.contracts.decision import ShadowOrderLine
    from src.screening.offensive.v3.orchestration.session_driver import (
        UNCONDITIONAL_EXIT_LIMIT_CENTS,
        open_line_from_shadow_line,
    )

    H = "a" * 64
    line = ShadowOrderLine(
        shadow_line_id="shadow-1", security_id="600000.SH", producer_namespace="btst",
        family_id="btst.limit-up-breakout", economic_lineage_id="eline-1",
        research_program_id="prog-1", stage_id="stage-1", trial_id="trial-1",
        stage_manifest_hash=H, evidence_id="btst:snap:1", evidence_artifact_hash=H,
        evidence_payload_hash=H, target_quantity_units=200, lot_size_units=100,
        lot_rule_version="lots.v1", order_type="limit", limit_price_cents=1100,
        worst_case_price_cents=1100, price_boundary_version="pb.v1",
        time_in_force="DAY", exit_session_ordinal=10, estimated_fee_cents=60,
        estimated_cash_reserve_cents=220_060, cost_assumption_version="cn.v1",
        execution_assumption_version="t1-open-t10-open.v1",
        target_exit_session=date(2026, 9, 3),
    )
    o = open_line_from_shadow_line(line, entry_session=date(2026, 8, 21))
    assert o.decision_id == "shadow-1" and o.security_id == "600000.SH"
    assert o.quantity == 200 and o.limit_price_cents == 1100  # 买上限
    assert o.exit_limit_price_cents == UNCONDITIONAL_EXIT_LIMIT_CENTS  # 无条件卖
    assert o.exit_session == date(2026, 9, 3)  # kernel 冻结排程日期是权威
    assert o.economic_lot_id == "lot:shadow-1"  # 确定性资本身份


def test_suspended_exit_defers_to_next_session(tmp_path):
    """出场日停牌 → 义务顺延: 下一会话可成交时出场, 不搁浅不丢弃."""
    sessions = _sessions(13)
    line = _line("600000.SH", "cyc-1", sessions=sessions)
    exit_session = line.exit_session
    bars = {}

    def bar_for(s, sec):
        if s == exit_session:
            return DailyBar(security_id=sec, session=s, open_cents=1000, high_cents=1000,
                            low_cents=1000, close_cents=1000, limit_up_cents=1100,
                            limit_down_cents=900, suspended=True)  # 停牌日
        return _bar(s, sec)

    driver = SessionLifecycleDriver(
        repository=_repo(tmp_path, "defer"), arm="champion",
        scenario=CURRENT_COST_SCENARIO, sessions=sessions,
        entries_by_session={sessions[1]: (line,)}, attribution=ATTR,
        command_at=lambda s: datetime(s.year, s.month, s.day, 9, 30, tzinfo=UTC),
        send_deadline=lambda s: datetime(s.year, s.month, s.day, 10, 0, tzinfo=UTC),
        bar_for=bar_for,
    )
    result = driver.run()
    suspended_try = result.settlements[(exit_session, "600000.SH", "exit")]
    assert suspended_try.verdict is OpenExecutionVerdict.UNKNOWN  # 停牌日零成交
    deferred = result.settlements[(sessions[12], "600000.SH", "exit")]  # 窗口末会话补出场
    assert deferred.verdict is OpenExecutionVerdict.FILLED
    assert result.open_at_end == {}
    assert result.conservation_ok
