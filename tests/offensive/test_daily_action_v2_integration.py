from __future__ import annotations

from datetime import date, timedelta

import pytest

from src.paper_trading.btst_trade_calendar import TradingSessionCalendar
from src.screening.offensive.daily_action import (
    DailyActionScan,
    BlockedCandidate,
    render_daily_action_v2,
    run_daily_action_v2,
)
from src.screening.offensive.daily_action_service import (
    DailyActionService,
    MarketBar,
    PlanCandidate,
    RegimeAuthorization,
)
from src.screening.offensive.execution_adjuster import ExecutionCosts
from src.screening.offensive.ledger_repository import LedgerRepository


@pytest.fixture
def signal_date() -> date:
    return date(2026, 7, 13)


@pytest.fixture
def repository(tmp_path) -> LedgerRepository:
    repo = LedgerRepository(tmp_path / "paper_trading_v2" / "ledger.sqlite3", "daily-action-v2", 100_000)
    repo.initialize()
    return repo


@pytest.fixture
def service(repository, signal_date) -> DailyActionService:
    sessions = tuple(signal_date + timedelta(days=i) for i in range(12))
    bar = MarketBar(10.0, 10.0, 9.0, 11.0, False, 10.5, 9.5)
    return DailyActionService(
        repository,
        TradingSessionCalendar(sessions),
        lambda _ticker, _date: bar,
        ExecutionCosts(version="test"),
    )


def _scan(signal_date, *, degraded=False, regime="normal") -> DailyActionScan:
    authorization = (
        RegimeAuthorization.BTST_CRISIS
        if regime == "crisis"
        else RegimeAuthorization.NORMAL
    )
    hit = PlanCandidate(
        ticker="000001",
        setup="btst_breakout",
        setup_version="v2",
        target_weight=0.12,
        priority=1,
        authorization=authorization,
    )
    blocked = (
        (BlockedCandidate("000001", "incomplete_setup_data", 10.0),)
        if degraded
        else ()
    )
    candidates = () if degraded else (hit,)
    return DailyActionScan(signal_date, candidates, blocked, (("000001", 10.0),))


def test_signal_date_creates_plan_not_open_position(service, signal_date):
    run = run_daily_action_v2(service, _scan(signal_date))
    assert len(run.plans) == 1
    assert run.open_positions == ()


def test_degraded_btst_is_displayed_but_never_planned(service, signal_date):
    run = run_daily_action_v2(service, _scan(signal_date, degraded=True))
    assert run.plans == ()
    assert run.blocked_candidates[0].reason == "incomplete_setup_data"


def test_btst_normal_cap_is_ten_percent_and_crisis_cap_is_twelve(service, repository, signal_date):
    normal_run = run_daily_action_v2(service, _scan(signal_date))
    normal_weight = repository.get_trade(normal_run.plans[0].trade_id).planned_weight

    crisis_scan = DailyActionScan(
        signal_date,
        (
            PlanCandidate(
                "000002",
                "btst_breakout",
                "v2",
                0.12,
                2,
                RegimeAuthorization.BTST_CRISIS,
            ),
        ),
        (),
        (("000002", 10.0),),
    )
    crisis_run = run_daily_action_v2(service, crisis_scan)
    crisis_weight = repository.get_trade(crisis_run.plans[0].trade_id).planned_weight
    assert normal_weight == pytest.approx(0.10)
    assert crisis_weight == pytest.approx(0.12)


def test_repeat_cli_run_is_idempotent(service, repository, signal_date):
    first = run_daily_action_v2(service, _scan(signal_date))
    second = run_daily_action_v2(service, _scan(signal_date))
    assert first.plans[0].trade_id == second.plans[0].trade_id
    assert repository.count_events(first.plans[0].trade_id, "PLAN_CREATED") == 1


def test_v1_files_are_byte_identical_after_v2_run(service, signal_date, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    artifacts = {
        tmp_path / "data/paper_trading/journal.jsonl": b"runtime-v1\n",
        tmp_path / "data/paper_trading_backtest/journal.jsonl": b"backtest-v1\n",
    }
    for path, content in artifacts.items():
        path.parent.mkdir(parents=True)
        path.write_bytes(content)

    run_daily_action_v2(service, _scan(signal_date))

    assert {path: path.read_bytes() for path in artifacts} == artifacts


def test_output_distinguishes_reference_synthetic_and_confirmed_prices(service, signal_date):
    pending = run_daily_action_v2(service, _scan(signal_date))
    # The renderer always discloses all three price/source states, even when a section is empty.
    rendered = render_daily_action_v2(pending)
    assert "参考价" in rendered
    assert "模拟成交" in rendered
    assert "确认成交" in rendered
