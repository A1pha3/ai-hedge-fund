from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from src.paper_trading.btst_trade_calendar import TradingSessionCalendar
from src.screening.offensive.daily_action import (
    DailyActionScan,
    BlockedCandidate,
    render_daily_action_v2,
    run_daily_action_v2,
    _resolve_next_trade_date,
    _price_frame_is_fresh,
    DailyActionV2Run,
)
from src.screening.offensive.daily_action_service import (
    ActionItem,
    DailyActionRun,
    DailyActionService,
    MarketBar,
    PlanCandidate,
    RegimeAuthorization,
)
from src.screening.offensive.execution_adjuster import ExecutionCosts
from src.screening.offensive.ledger_repository import LedgerRepository
from src.cli.dispatcher import _cached_daily_action_market_bar
from src.cli import dispatcher
from src.screening.offensive.ledger_repository import DailyValuation
from src.screening.data_quality_manifest import RunManifest, TickerReadiness


@pytest.fixture
def signal_date() -> date:
    return date(2026, 7, 13)


@pytest.fixture
def repository(tmp_path) -> LedgerRepository:
    repo = LedgerRepository(
        tmp_path / "paper_trading_v2" / "ledger.sqlite3", "daily-action-v2", 100_000
    )
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
        enforce_manifest_gate=False,
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
        (BlockedCandidate("000001", "incomplete_setup_data", 10.0),) if degraded else ()
    )
    candidates = () if degraded else (hit,)
    return DailyActionScan(signal_date, candidates, blocked, (("000001", 10.0),))


def _install_healthy_manifest(monkeypatch, signal_date: date) -> None:
    fingerprint = "sha256:current"
    readiness = TickerReadiness(
        "000001",
        signal_date,
        signal_date,
        True,
        signal_date,
        20,
        signal_date,
        "listed",
        False,
        "ashare-board-prefix-v1",
        fingerprint,
        True,
        (),
    )
    manifest = RunManifest(
        "run-test",
        signal_date,
        "healthy",
        datetime.now(timezone.utc),
        {"000001": readiness},
        candidate_tickers=("000001",),
        candidate_set_fingerprint="sha256:candidates",
        input_fingerprint="sha256:inputs",
    )
    monkeypatch.setattr(
        "src.screening.offensive.daily_action_service.load_daily_action_manifest_gate",
        lambda *_args, **_kwargs: (manifest, {"000001": fingerprint}),
    )


def test_signal_date_creates_plan_not_open_position(service, signal_date):
    run = run_daily_action_v2(service, _scan(signal_date))
    assert len(run.plans) == 1
    assert run.open_positions == ()


def test_degraded_btst_is_displayed_but_never_planned(service, signal_date):
    run = run_daily_action_v2(service, _scan(signal_date, degraded=True))
    assert run.plans == ()
    assert run.blocked_candidates[0].reason == "incomplete_setup_data"


def test_btst_normal_cap_is_ten_percent_and_crisis_cap_is_twelve(
    service, repository, signal_date
):
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


def test_v1_files_are_byte_identical_after_v2_run(
    service, signal_date, tmp_path, monkeypatch
):
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


def test_output_distinguishes_reference_synthetic_and_confirmed_prices(
    service, signal_date
):
    pending = run_daily_action_v2(service, _scan(signal_date))
    # The renderer always discloses all three price/source states, even when a section is empty.
    rendered = render_daily_action_v2(pending)
    assert "参考价" in rendered
    assert "模拟成交" in rendered
    assert "确认成交" in rendered


def test_authoritative_sessions_handle_weekend_and_exchange_holiday(monkeypatch):
    sessions = (date(2026, 9, 25), date(2026, 9, 28), date(2026, 10, 9))
    monkeypatch.setattr(
        "src.screening.offensive.daily_action._load_authoritative_session_dates",
        lambda: sessions,
    )
    assert _resolve_next_trade_date("20260925") == "20260928"
    assert _resolve_next_trade_date("20260928") == "20261009"


def test_missing_authoritative_calendar_fails_closed(monkeypatch):
    monkeypatch.setattr(
        "src.screening.offensive.daily_action._load_authoritative_session_dates",
        lambda: (),
    )
    assert _resolve_next_trade_date("20260925") == ""


def test_cached_market_bar_preserves_unknown_execution_fields(tmp_path):
    cache = tmp_path / "000001.csv"
    cache.write_text(
        "date,open,close,high,low\n2026-07-13,10,10,10.5,9.5\n", encoding="utf-8"
    )
    bar = _cached_daily_action_market_bar(cache, date(2026, 7, 13))
    assert bar is not None
    assert bar.suspended is None
    assert bar.limit_up is None
    assert bar.limit_down is None


@pytest.mark.parametrize(
    "dates",
    [
        ("2026-07-13", "2026-07-13"),
        ("2026-07-13 00:00:00", "2026-07-13"),
    ],
)
def test_cached_market_bar_rejects_duplicate_civil_dates(tmp_path, dates):
    cache = tmp_path / "000001.csv"
    cache.write_text(
        "date,open,close,high,low\n"
        f"{dates[0]},10,10,10.5,9.5\n"
        f"{dates[1]},11,11,11.5,10.5\n",
        encoding="utf-8",
    )

    assert _cached_daily_action_market_bar(cache, date(2026, 7, 13)) is None


def test_renderer_includes_real_lifecycle_reasons(service, signal_date):
    run = run_daily_action_v2(service, _scan(signal_date))
    rendered = render_daily_action_v2(run)
    assert "entry_planned" in rendered
    assert "execution=pending" in rendered
    assert "source=pending" in rendered


def test_ticker_terminal_bar_must_equal_authoritative_signal_session():
    import pandas as pd

    fresh = pd.DataFrame([{"date": "2026-07-13", "close": 10.0}])
    stale = pd.DataFrame([{"date": "2026-07-10", "close": 10.0}])
    assert _price_frame_is_fresh(fresh, "20260713")
    assert not _price_frame_is_fresh(stale, "20260713")


def test_renderer_surfaces_every_lifecycle_collection(signal_date):
    def item(reason, execution, source):
        return ActionItem("t", "000001", reason, execution, source)

    view = DailyActionRun(
        signal_date,
        DailyValuation(signal_date, 100_000, 0, 100_000, 100_000, 0, ()),
        (),
        (),
        (item("portfolio_capacity", "pending", "pending"),),
        (item("maximum_holding_session", "paper", "synthetic_open"),),
        (item("unknown_queue", "paper", "synthetic_open"),),
        (item("exit_filled", "paper", "synthetic_open"),),
        0,
        0,
        "calendar_unavailable",
    )
    rendered = render_daily_action_v2(DailyActionV2Run(view, (), (), (), ()))
    for expected in (
        "portfolio_capacity",
        "maximum_holding_session",
        "unknown_queue",
        "exit_filled",
        "calendar_unavailable",
        "execution=paper",
        "source=synthetic_open",
    ):
        assert expected in rendered


def test_actual_cli_is_idempotent_and_preserves_recursive_legacy_artifacts(
    tmp_path, monkeypatch, signal_date
):
    runtime = tmp_path / "data/paper_trading"
    backtest = tmp_path / "data/paper_trading_backtest"
    for root, payload in ((runtime, b"runtime"), (backtest, b"backtest")):
        (root / "nested").mkdir(parents=True)
        (root / "journal.jsonl").write_bytes(payload)
        (root / "nested/state.bin").write_bytes(payload + b"-state")
    snapshot = {
        path.relative_to(tmp_path): path.read_bytes()
        for root in (runtime, backtest)
        for path in root.rglob("*")
        if path.is_file()
    }
    scan = _scan(signal_date)
    price_cache = tmp_path / "data/price_cache"
    price_cache.mkdir(parents=True)
    (price_cache / "000001.csv").write_text(
        "date,open,high,low,close,limit_down,limit_up,suspended\n"
        "2026-07-13,10,10.5,9.5,10,9,11,False\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "src.screening.offensive.daily_action.scan_daily_action_candidates",
        lambda **_kwargs: scan,
    )
    _install_healthy_manifest(monkeypatch, signal_date)
    ledger = tmp_path / "isolated-v2/ledger.sqlite3"
    sessions = tuple(signal_date + timedelta(days=i) for i in range(11))
    dispatcher._resolve_daily_action(
        ["--daily-action"], open_sessions=sessions, ledger_path=ledger
    )
    dispatcher._resolve_daily_action(
        ["--daily-action"], open_sessions=sessions, ledger_path=ledger
    )
    after = {
        path.relative_to(tmp_path): path.read_bytes()
        for root in (runtime, backtest)
        for path in root.rglob("*")
        if path.is_file()
    }
    assert after == snapshot
    repo = LedgerRepository(ledger, "daily-action-v2", 100_000)
    plans = repo.planned_trades()
    assert len(plans) == 1
    assert repo.count_events(plans[0].trade_id, "PLAN_CREATED") == 1


def test_actual_cli_missing_calendar_renders_block_and_creates_no_plan(
    tmp_path, monkeypatch, signal_date, capsys
):
    monkeypatch.setattr(
        "src.screening.offensive.daily_action.scan_daily_action_candidates",
        lambda **_kwargs: _scan(signal_date),
    )
    _install_healthy_manifest(monkeypatch, signal_date)
    ledger = tmp_path / "blocked.sqlite3"
    dispatcher._resolve_daily_action(
        ["--daily-action"], open_sessions=(), ledger_path=ledger
    )
    assert "calendar_unavailable" in capsys.readouterr().out
    assert LedgerRepository(ledger, "daily-action-v2", 100_000).planned_trades() == []


def test_actual_cli_two_session_calendar_blocks_btst_horizon(
    tmp_path, monkeypatch, signal_date, capsys
):
    monkeypatch.setattr(
        "src.screening.offensive.daily_action.scan_daily_action_candidates",
        lambda **_kwargs: _scan(signal_date),
    )
    _install_healthy_manifest(monkeypatch, signal_date)
    ledger = tmp_path / "two-session.sqlite3"
    dispatcher._resolve_daily_action(
        ["--daily-action"],
        open_sessions=(signal_date, signal_date + timedelta(days=1)),
        ledger_path=ledger,
    )
    assert "calendar_unavailable" in capsys.readouterr().out
    assert LedgerRepository(ledger, "daily-action-v2", 100_000).planned_trades() == []
