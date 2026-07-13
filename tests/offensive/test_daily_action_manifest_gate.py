from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path

import pytest

from src.paper_trading.btst_trade_calendar import TradingSessionCalendar
from src.screening.data_quality_manifest import RunManifest, TickerReadiness
from src.screening.offensive.daily_action_service import (
    DailyActionService,
    MarketBar,
    PlanCandidate,
    load_daily_action_manifest_gate,
)
from src.screening.offensive.execution_adjuster import ExecutionCosts
from src.screening.offensive.ledger_repository import LedgerRepository
from src.screening.offensive.trade_lifecycle import ExecutionMode, FillSource


SIGNAL_DATE = date(2026, 7, 13)


def _readiness(ticker: str, fingerprint: str, *, trade_ready: bool = True) -> TickerReadiness:
    return TickerReadiness(
        ticker=ticker,
        trade_date=SIGNAL_DATE,
        ohlcv_date=SIGNAL_DATE,
        ohlcv_finite=True,
        fund_flow_date=SIGNAL_DATE,
        fund_flow_history_days=20,
        industry_date=SIGNAL_DATE,
        security_status="listed",
        st_status=False,
        board_rule_version="ashare-board-prefix-v1",
        cache_fingerprint=fingerprint,
        trade_ready=trade_ready,
        block_reasons=() if trade_ready else ("fund_flow_history:4<20",),
    )


@pytest.fixture
def candidates() -> tuple[PlanCandidate, PlanCandidate]:
    return (
        PlanCandidate("000001", "btst_breakout", "v2", 0.10, 1),
        PlanCandidate("000002", "btst_breakout", "v2", 0.10, 2),
    )


@pytest.fixture
def healthy_manifest(candidates) -> RunManifest:
    tickers = {
        candidate.ticker: _readiness(candidate.ticker, f"sha256:{candidate.ticker}")
        for candidate in candidates
    }
    return RunManifest(
        run_id="run-20260713",
        trade_date=SIGNAL_DATE,
        status="healthy",
        created_at=datetime(2026, 7, 13, tzinfo=timezone.utc),
        tickers=tickers,
        candidate_tickers=tuple(tickers),
        candidate_set_fingerprint="sha256:candidates",
        input_fingerprint="sha256:inputs",
    )


@pytest.fixture
def service(tmp_path, candidates) -> DailyActionService:
    repository = LedgerRepository(tmp_path / "ledger.sqlite3", "manifest-gate", 100_000)
    repository.initialize()
    sessions = tuple(SIGNAL_DATE + timedelta(days=offset) for offset in range(12))
    fingerprints = {
        candidate.ticker: f"sha256:{candidate.ticker}" for candidate in candidates
    }
    return DailyActionService(
        repository,
        TradingSessionCalendar(sessions),
        lambda _ticker, _as_of: MarketBar(10, 10, 9, 11, False, 10.5, 9.5),
        ExecutionCosts(version="test"),
        cache_fingerprints=lambda ticker, _as_of: fingerprints.get(ticker),
    )


@pytest.fixture
def open_trade(service):
    plan = service.repository.create_plan(
        "000099", "btst_breakout", "v2", SIGNAL_DATE - timedelta(days=1), SIGNAL_DATE, 0.1, 1
    )
    return service.repository.fill_plan(
        plan.trade_id,
        ExecutionMode.PAPER,
        FillSource.SYNTHETIC_OPEN,
        SIGNAL_DATE,
        10.0,
        1_000,
        5.0,
        0.0,
        0.0,
    )


def test_missing_healthy_manifest_blocks_new_plan_but_keeps_open_positions(
    service, open_trade
):
    run = service.run(as_of=open_trade.entry_date, candidates=[], manifest=None)
    assert run.new_plans == ()
    assert run.open_positions[0].trade_id == open_trade.trade_id
    assert run.block_reason == "healthy_manifest_missing"


@pytest.mark.parametrize(
    ("manifest", "reason"),
    [
        (lambda value: replace(value, status="degraded"), "healthy_manifest_missing"),
        (
            lambda value: replace(value, trade_date=SIGNAL_DATE - timedelta(days=1)),
            "manifest_identity_mismatch",
        ),
        (lambda value: replace(value, run_id=""), "manifest_identity_mismatch"),
        (
            lambda value: replace(value, input_fingerprint=None),
            "manifest_identity_mismatch",
        ),
    ],
)
def test_invalid_manifest_identity_blocks_every_new_candidate(
    service, candidates, healthy_manifest, manifest, reason
):
    run = service.run(
        as_of=SIGNAL_DATE,
        candidates=candidates,
        manifest=manifest(healthy_manifest),
    )
    assert run.new_plans == ()
    assert run.blocked_tickers == tuple(candidate.ticker for candidate in candidates)
    assert run.block_reason == reason


def test_ticker_fingerprint_mismatch_blocks_only_that_candidate(
    service, healthy_manifest, candidates
):
    stale = replace(
        healthy_manifest.tickers[candidates[0].ticker],
        cache_fingerprint="sha256:stale",
    )
    manifest = replace(
        healthy_manifest,
        tickers={**healthy_manifest.tickers, candidates[0].ticker: stale},
    )
    run = service.run(
        as_of=manifest.trade_date,
        candidates=candidates,
        manifest=manifest,
    )
    assert candidates[0].ticker in run.blocked_tickers
    assert candidates[1].ticker not in run.blocked_tickers
    assert tuple(plan.ticker for plan in run.new_plans) == (candidates[1].ticker,)


def test_nonrecommended_layer_a_ticker_is_blocked_by_its_exact_readiness(
    service, healthy_manifest, candidates
):
    blocked = replace(
        healthy_manifest.tickers[candidates[1].ticker],
        trade_ready=False,
        block_reasons=("fund_flow_history:4<20",),
    )
    manifest = replace(
        healthy_manifest,
        tickers={**healthy_manifest.tickers, candidates[1].ticker: blocked},
    )
    run = service.run(SIGNAL_DATE, candidates, manifest=manifest)
    assert run.blocked_tickers == (candidates[1].ticker,)
    assert tuple(plan.ticker for plan in run.new_plans) == (candidates[0].ticker,)


def test_manifest_ticker_mapping_remains_immutable_after_candidate_gate(
    service, healthy_manifest, candidates
):
    service.run(SIGNAL_DATE, candidates, manifest=healthy_manifest)
    with pytest.raises(TypeError):
        healthy_manifest.tickers["000003"] = _readiness("000003", "sha256:000003")


def _canonical_payload(manifest: RunManifest) -> dict:
    from src.screening.auto_pipeline import _manifest_payload

    return {
        "date": manifest.trade_date.strftime("%Y%m%d"),
        "run_id": manifest.run_id,
        "status": "healthy",
        "candidate_pool_run": {
            "trade_date": manifest.trade_date.strftime("%Y%m%d"),
            "tickers": list(manifest.candidate_tickers),
            "candidates": [
                {"ticker": ticker, "industry_sw": "银行"}
                for ticker in manifest.candidate_tickers
            ],
        },
        "manifest": _manifest_payload(manifest),
    }


def test_canonical_manifest_round_trip_is_immutable(
    tmp_path: Path, healthy_manifest
):
    reports = tmp_path / "data" / "reports"
    reports.mkdir(parents=True)
    payload = _canonical_payload(healthy_manifest)
    # A serialized canonical must carry the exact candidate-set identity.
    from src.screening.auto_pipeline import _canonical_fingerprint

    payload["manifest"]["candidate_set_fingerprint"] = _canonical_fingerprint(
        list(healthy_manifest.candidate_tickers)
    )
    (reports / "auto_screening_20260713.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )

    manifest, _fingerprints = load_daily_action_manifest_gate(
        SIGNAL_DATE, reports_dir=reports
    )

    assert manifest is not None
    assert manifest.run_id == healthy_manifest.run_id
    assert manifest.trade_date == SIGNAL_DATE
    with pytest.raises(TypeError):
        manifest.tickers["000003"] = _readiness("000003", "sha256:000003")


@pytest.mark.parametrize(
    "mutate",
    [
        lambda payload: payload.update(run_id="other-run"),
        lambda payload: payload["manifest"].update(trade_date="20260712"),
        lambda payload: payload["manifest"].update(input_fingerprint=""),
        lambda payload: payload["manifest"].update(
            candidate_set_fingerprint="sha256:wrong"
        ),
        lambda payload: payload["manifest"].update(is_healthy=1),
    ],
)
def test_mismatched_or_corrupt_canonical_fails_closed(
    tmp_path: Path, healthy_manifest, mutate
):
    reports = tmp_path / "data" / "reports"
    reports.mkdir(parents=True)
    payload = _canonical_payload(healthy_manifest)
    from src.screening.auto_pipeline import _canonical_fingerprint

    payload["manifest"]["candidate_set_fingerprint"] = _canonical_fingerprint(
        list(healthy_manifest.candidate_tickers)
    )
    mutate(payload)
    (reports / "auto_screening_20260713.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )

    assert load_daily_action_manifest_gate(SIGNAL_DATE, reports_dir=reports) == (
        None,
        {},
    )


def test_stale_canonical_is_not_used_for_new_signal_date(
    tmp_path: Path, healthy_manifest
):
    reports = tmp_path / "data" / "reports"
    reports.mkdir(parents=True)
    (reports / "auto_screening_20260712.json").write_text(
        json.dumps(_canonical_payload(healthy_manifest)), encoding="utf-8"
    )

    assert load_daily_action_manifest_gate(SIGNAL_DATE, reports_dir=reports) == (
        None,
        {},
    )
