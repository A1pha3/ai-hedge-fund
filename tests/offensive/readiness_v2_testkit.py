from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Iterable

import pandas as pd

from src.paper_trading.btst_trade_calendar import TradingSessionCalendar
from src.screening.offensive.cache_refresh import refresh_daily_action_caches
from src.screening.offensive.daily_action import scan_from_verified_snapshot
from src.screening.offensive.daily_action_readiness import DailyActionReadinessPublication, SharedReadinessEvidence, _fingerprint, build_daily_action_readiness, parse_manifest_v2, publish_daily_action_readiness
from src.screening.offensive.daily_action_service import ActionItem, DailyActionService, MarketBar
from src.screening.offensive.daily_action_snapshot import VerifiedDailyActionSnapshot, load_verified_daily_action_snapshot
from src.screening.offensive.execution_adjuster import ExecutionCosts
from src.screening.offensive.ledger_repository import LedgerRepository, LedgerTrade
from src.screening.offensive.pit_evidence import canonical_fingerprint
from src.screening.offensive.setups.base import DetectionResult
from src.screening.offensive.setups.btst_breakout import BtstBreakoutSetup
from src.screening.offensive.trade_lifecycle import TradeState
from src.utils.date_utils import SIGNAL_SESSION_POLICY_VERSION

SIGNAL_DATE = date(2026, 7, 13)
SIGNAL_DATE_TEXT = "20260713"
FIXTURE_UNIVERSE_WITH_BSE = ("000001", "002999", "300001", "830799")
_FIXED_CREATED_AT = "2026-07-13T09:30:00Z"


@dataclass(frozen=True)
class PipelineTestResult:
    publication: DailyActionReadinessPublication | None
    snapshot: VerifiedDailyActionSnapshot | None
    new_plans: tuple[ActionItem, ...]
    completed_exits: tuple[ActionItem, ...]
    ledger_trade: LedgerTrade | None


def _sessions(start: date = SIGNAL_DATE, count: int = 14) -> tuple[date, ...]:
    return tuple(start + timedelta(days=offset) for offset in range(count))


def _write_csv(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)


def _prior_sessions(count: int, *, end: date = SIGNAL_DATE) -> list[date]:
    days: list[date] = []
    cursor = end - timedelta(days=1)
    while len(days) < count:
        if cursor.weekday() < 5:
            days.append(cursor)
        cursor -= timedelta(days=1)
    return list(reversed(days))


def _price_history(ticker: str, *, include_signal: bool = False) -> pd.DataFrame:
    rows = []
    sessions = _prior_sessions(30)
    if include_signal:
        sessions = [*sessions, SIGNAL_DATE]
    for index, session in enumerate(sessions):
        is_signal = session == SIGNAL_DATE
        close = 11.0 if is_signal else 10.0 + index * 0.01
        rows.append(
            {
                "date": session.isoformat(),
                "open": close if not is_signal else 10.0,
                "high": close if not is_signal else 11.0,
                "low": close if not is_signal else 9.9,
                "close": close,
                "pct_change": 10.0 if is_signal else 0.1,
                "volume": 1_000_000 + index,
            }
        )
    return pd.DataFrame(rows)


def _flow_history(ticker: str, *, include_signal: bool = False) -> pd.DataFrame:
    rows = []
    sessions = _prior_sessions(19)
    if include_signal:
        sessions = [*sessions, SIGNAL_DATE]
    for index, session in enumerate(sessions):
        rows.append(
            {
                "date": session.strftime("%Y%m%d"),
                "ticker": ticker,
                "close": 11.0 if session == SIGNAL_DATE else 10.0,
                "pct_change": 10.0 if session == SIGNAL_DATE else 0.1,
                "main_net_inflow": 1_000_000 + index * 10_000,
                "main_net_pct": 3.0,
                "big_net_inflow": 0.0,
                "super_big_net_inflow": 0.0,
                "medium_net_inflow": 0.0,
                "small_net_inflow": 0.0,
            }
        )
    return pd.DataFrame(rows)


def fixture_universe_20260713() -> tuple[str, ...]:
    return FIXTURE_UNIVERSE_WITH_BSE


def fixture_daily_batch_20260713(tickers: Iterable[str] = FIXTURE_UNIVERSE_WITH_BSE) -> pd.DataFrame:
    rows = []
    for ticker in sorted(tickers):
        suffix = "BJ" if ticker.startswith(("8", "4")) else ("SH" if ticker.startswith("6") else "SZ")
        rows.append(
            {
                "ts_code": f"{ticker}.{suffix}",
                "trade_date": SIGNAL_DATE_TEXT,
                "open": 10.0,
                "high": 11.0,
                "low": 9.9,
                "close": 11.0,
                "pct_chg": 10.0,
                "vol": 1_000_000,
            }
        )
    return pd.DataFrame(rows)


def fixture_price_history(ticker: str, start_date: str, end_date: str) -> pd.DataFrame:
    return _price_history(ticker)


def fixture_fund_flow(ticker: str, start_date: str, end_date: str) -> pd.DataFrame:
    return _flow_history(ticker, include_signal=True).tail(1).reset_index(drop=True)


def fixture_industry_backfill(**_kwargs: object) -> dict[str, int]:
    return {"fixture": 1}


def _preseed_caches(data_dir: Path, tickers: Iterable[str]) -> None:
    for ticker in tickers:
        if ticker.startswith(("8", "4")):
            continue
        _write_csv(data_dir / "price_cache" / f"{ticker}.csv", _price_history(ticker))
        _write_csv(data_dir / "fund_flow_cache" / f"{ticker}.csv", _flow_history(ticker))


def fixture_shared_evidence(universe: tuple[str, ...]) -> SharedReadinessEvidence:
    regime_row = {"trade_date": SIGNAL_DATE.isoformat(), "regime": "normal"}
    industry_by_ticker = {ticker: "银行" for ticker in universe}
    industry_day_pct = {ticker: 2.5 for ticker in universe}
    security_status_by_ticker = {ticker: "listed" for ticker in universe}
    return SharedReadinessEvidence(
        as_of_date=SIGNAL_DATE,
        regime_row=regime_row,
        industry_by_ticker=industry_by_ticker,
        industry_day_pct=industry_day_pct,
        security_status_by_ticker=security_status_by_ticker,
        regime_fingerprint=_fingerprint({"as_of_date": SIGNAL_DATE.isoformat(), "regime_row": regime_row}),
        industry_fingerprint=_fingerprint({"as_of_date": SIGNAL_DATE.isoformat(), "industry_by_ticker": industry_by_ticker, "industry_day_pct": industry_day_pct}),
        security_fingerprint=_fingerprint({"as_of_date": SIGNAL_DATE.isoformat(), "security_status_by_ticker": security_status_by_ticker}),
        board_rule_version="ashare-board-prefix-v1",
        normalization_version="pit-canonical-v1",
        signal_session_policy_version=SIGNAL_SESSION_POLICY_VERSION,
    )


def _publish_deterministic(refresh_result, reports_dir: Path, *, run_id: str) -> DailyActionReadinessPublication:
    manifest = build_daily_action_readiness(refresh_result, fixture_shared_evidence(refresh_result.universe_tickers), run_id=run_id, oversold_bounce_enabled=False)
    raw = manifest.to_dict(include_content_fingerprint=False)
    raw["created_at"] = _FIXED_CREATED_AT
    raw["content_fingerprint"] = _fingerprint(raw)
    return publish_daily_action_readiness(parse_manifest_v2(raw), reports_dir)


def run_injected_auto_refresh_for_20260713(root: Path) -> DailyActionReadinessPublication:
    data_dir = root / "data"
    reports_dir = data_dir / "reports"
    tickers = fixture_universe_20260713()
    _preseed_caches(data_dir, tickers)
    refresh_result = refresh_daily_action_caches(
        SIGNAL_DATE_TEXT,
        price_cache_dir=data_dir / "price_cache",
        fund_flow_cache_dir=data_dir / "fund_flow_cache",
        snapshot_dir=data_dir / "snapshots",
        daily_prices_df=fixture_daily_batch_20260713(tickers),
        target_tickers=tickers,
        backfill_price_history_fn=fixture_price_history,
        industry_index_backfill_fn=fixture_industry_backfill,
        fund_flow_fetch_fn=fixture_fund_flow,
        refresh_industry_index=False,
        refresh_fund_flow=True,
        fund_flow_rate_limit_sec=0.0,
        suspension_loader=lambda trade_date: __import__("src.screening.offensive.cache_readiness", fromlist=["SuspensionEvidence"]).SuspensionEvidence.available(SIGNAL_DATE, set(), source_fingerprint=canonical_fingerprint("suspension", "*", ())),
    )
    return _publish_deterministic(refresh_result, reports_dir, run_id="fixture-20260713-v2")


def _service(root: Path) -> DailyActionService:
    costs = ExecutionCosts(version="daily-action-v2")
    repository = LedgerRepository(root / "data" / "daily_action_ledger.sqlite3", "daily-action-v2", 100_000.0, execution_costs=costs)
    repository.initialize()
    bar = MarketBar(open=11.0, close=11.0, limit_down=9.9, limit_up=12.1, suspended=False, high=11.2, low=10.8)
    return DailyActionService(repository, TradingSessionCalendar(_sessions()), lambda _ticker, _date: bar, costs, shadow_history=lambda _ticker: None)


def run_full_injected_pipeline(root: Path, *, auto_tickers: set[str], daily_tickers: set[str], btst_hit: str) -> PipelineTestResult:
    data_dir = root / "data"
    reports_dir = data_dir / "reports"
    _preseed_caches(data_dir, daily_tickers)
    refresh_result = refresh_daily_action_caches(
        SIGNAL_DATE_TEXT,
        price_cache_dir=data_dir / "price_cache",
        fund_flow_cache_dir=data_dir / "fund_flow_cache",
        snapshot_dir=data_dir / "snapshots",
        daily_prices_df=fixture_daily_batch_20260713(daily_tickers | auto_tickers),
        target_tickers=daily_tickers,
        backfill_price_history_fn=fixture_price_history,
        fund_flow_fetch_fn=fixture_fund_flow,
        refresh_industry_index=False,
        refresh_fund_flow=True,
        fund_flow_rate_limit_sec=0.0,
        suspension_loader=lambda trade_date: __import__("src.screening.offensive.cache_readiness", fromlist=["SuspensionEvidence"]).SuspensionEvidence.available(SIGNAL_DATE, set(), source_fingerprint=canonical_fingerprint("suspension", "*", ())),
    )
    publication = _publish_deterministic(refresh_result, reports_dir, run_id="fixture-pipeline-v2")
    loaded = load_verified_daily_action_snapshot(SIGNAL_DATE, reports_dir=reports_dir, data_dir=data_dir)
    snapshot = loaded.snapshot
    assert snapshot is not None

    original_detect = BtstBreakoutSetup.detect

    def injected_detect(self, ticker, trade_date, context):
        return DetectionResult(
            hit=ticker == btst_hit,
            ticker=ticker,
            trade_date=trade_date,
            trigger_strength=1.0 if ticker == btst_hit else 0.0,
            invalidation_condition="fixture invalidation",
            metadata={"range_based_stop_pct": -0.08},
            degraded=False,
            degradation_reason="",
        )

    try:
        BtstBreakoutSetup.detect = injected_detect
        scan = scan_from_verified_snapshot(snapshot)
    finally:
        BtstBreakoutSetup.detect = original_detect

    service = _service(root)
    context = service.advance_lifecycle(SIGNAL_DATE)
    run = service.complete_run(context, snapshot=snapshot, candidates=scan.candidates)
    if run.new_plans:
        ledger_trade = service.repository.get_trade(run.new_plans[0].trade_id)
    else:
        planned = [trade for trade in service.repository.planned_trades() if trade.ticker == btst_hit]
        ledger_trade = planned[0] if planned else None
    return PipelineTestResult(publication, snapshot, run.new_plans, run.completed_exits, ledger_trade)


def run_pipeline_without_readiness_with_due_exit(root: Path) -> PipelineTestResult:
    costs = ExecutionCosts(version="daily-action-v2")
    repository = LedgerRepository(root / "data" / "daily_action_ledger.sqlite3", "daily-action-v2", 100_000.0, execution_costs=costs)
    repository.initialize()
    sessions = tuple(date(2026, 7, 3) + timedelta(days=offset) for offset in range(20))
    bar = MarketBar(open=12.0, close=12.0, limit_down=10.8, limit_up=13.2, suspended=False, high=12.2, low=11.8)
    service = DailyActionService(repository, TradingSessionCalendar(sessions), lambda _ticker, _date: bar, costs, shadow_history=lambda _ticker: None)
    plan = repository.create_plan("000777", "btst_breakout", "v2", sessions[0], sessions[1], 0.10, 1)
    trade = repository.settle_plan_at_open(plan.trade_id, sessions[1], 10.0, 9.0, 11.0, False, 10.5, 9.5)[0]
    repository.mark_exit_pending(trade.trade_id, sessions[9], forced_exit_target_date=SIGNAL_DATE)

    context = service.advance_lifecycle(SIGNAL_DATE)
    run = service.complete_run(context, snapshot=None, candidates=(), new_entry_block="readiness_schema_unsupported")
    ledger_trade = repository.get_trade(trade.trade_id)
    assert ledger_trade.state is TradeState.CLOSED
    return PipelineTestResult(None, None, run.new_plans, run.completed_exits, ledger_trade)


def count_plan_created_events(root: Path, trade_id: str) -> int:
    with sqlite3.connect(root / "data" / "daily_action_ledger.sqlite3") as conn:
        return int(conn.execute("SELECT COUNT(*) FROM trade_events WHERE trade_id=? AND event_type='PLAN_CREATED'", (trade_id,)).fetchone()[0])
