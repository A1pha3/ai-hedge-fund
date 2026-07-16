from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal
from types import MappingProxyType

import pytest

from src.paper_trading.btst_trade_calendar import TradingSessionCalendar
from src.screening.offensive.daily_action_readiness import (
    BOARD_RULE_VERSION,
    DAILY_ACTION_READINESS_SCHEMA_VERSION,
    NORMALIZATION_VERSION,
    READINESS_POLICY_VERSION,
    DailyActionReadinessManifest,
    DailyActionTickerReadiness,
    SharedReadinessEvidence,
    SuspensionReadinessEvidence,
    _fingerprint,
)
from src.screening.offensive.daily_action_service import DailyActionService, MarketBar, PlanCandidate, RegimeAuthorization
from src.screening.offensive.daily_action_snapshot import FrozenPriceRow, VerifiedDailyActionSnapshot
from src.screening.offensive.execution_adjuster import ExecutionCosts
from src.screening.offensive.ledger_repository import LedgerRepository
from src.screening.offensive.setup_data_contracts import SETUP_REQUIREMENTS_VERSION, SetupCapability
from src.utils.date_utils import SIGNAL_SESSION_POLICY_VERSION

SIGNAL_DATE = date(2026, 7, 13)
CONSUMED_FP = "sha256:" + "1" * 64
SNAPSHOT_ID = "sha256:" + "2" * 64
CONTENT_FP = "sha256:" + "3" * 64
INPUT_FP = "sha256:" + "4" * 64
UNIVERSE_FP = "sha256:" + "5" * 64
SUSPENSION_FP = "sha256:" + "6" * 64


@pytest.fixture
def repository(tmp_path) -> LedgerRepository:
    repo = LedgerRepository(tmp_path / "ledger.sqlite3", "daily-action-v2", 100_000.0, execution_costs=ExecutionCosts(version="test"))
    repo.initialize()
    return repo


@pytest.fixture
def service(repository) -> DailyActionService:
    sessions = tuple(SIGNAL_DATE + timedelta(days=i) for i in range(12))
    bar = MarketBar(10.0, 10.0, 9.0, 11.0, False, 10.5, 9.5)
    return DailyActionService(repository, TradingSessionCalendar(sessions), lambda _ticker, _date: bar, ExecutionCosts(version="test"))


def _shared() -> SharedReadinessEvidence:
    regime_row = {"trade_date": SIGNAL_DATE.isoformat(), "regime": "normal"}
    industry_by_ticker = {"300001": "software"}
    industry_day_pct = {"300001": 3.0}
    security_status_by_ticker = {"300001": "listed"}
    return SharedReadinessEvidence(
        as_of_date=SIGNAL_DATE,
        regime_row=regime_row,
        industry_by_ticker=industry_by_ticker,
        industry_day_pct=industry_day_pct,
        security_status_by_ticker=security_status_by_ticker,
        regime_fingerprint=_fingerprint({"as_of_date": SIGNAL_DATE.isoformat(), "regime_row": regime_row}),
        industry_fingerprint=_fingerprint({"as_of_date": SIGNAL_DATE.isoformat(), "industry_by_ticker": industry_by_ticker, "industry_day_pct": industry_day_pct}),
        security_fingerprint=_fingerprint({"as_of_date": SIGNAL_DATE.isoformat(), "security_status_by_ticker": security_status_by_ticker}),
        board_rule_version=BOARD_RULE_VERSION,
        normalization_version=NORMALIZATION_VERSION,
        signal_session_policy_version=SIGNAL_SESSION_POLICY_VERSION,
    )


def _capability(*, plan_eligible: bool = True) -> SetupCapability:
    return SetupCapability(
        enabled=True,
        scannable=True,
        plan_eligible=plan_eligible,
        degraded=not plan_eligible,
        block_reasons=() if plan_eligible else ("fund_flow_history_short",),
        warnings=(),
        consumed_fingerprint=CONSUMED_FP,
    )


def _disabled() -> SetupCapability:
    return SetupCapability(False, False, False, False, ("setup_disabled_by_default",), (), None)


def snapshot(*, plan_eligible: bool = True) -> VerifiedDailyActionSnapshot:
    manifest = DailyActionReadinessManifest(
        schema_version=DAILY_ACTION_READINESS_SCHEMA_VERSION,
        domain="daily_action",
        run_id="task7service",
        trade_date=SIGNAL_DATE,
        created_at="2026-07-13T12:00:00+00:00",
        status="healthy",
        universe_kind="resolved_refresh_universe",
        universe_tickers=("300001",),
        universe_fingerprint=UNIVERSE_FP,
        input_fingerprint=INPUT_FP,
        suspension_evidence=SuspensionReadinessEvidence("available_empty", (), SUSPENSION_FP),
        ticker_readiness=MappingProxyType(
            {
                "300001": DailyActionTickerReadiness(
                    "verified",
                    MappingProxyType({"btst_breakout": _capability(plan_eligible=plan_eligible), "oversold_bounce": _disabled()}),
                )
            }
        ),
        warnings=(),
        shared_evidence=_shared(),
        policy_versions=MappingProxyType(
            {
                "readiness_policy": READINESS_POLICY_VERSION,
                "normalization": NORMALIZATION_VERSION,
                "board_rule": BOARD_RULE_VERSION,
                "setup_requirements": SETUP_REQUIREMENTS_VERSION,
                "signal_session_cutoff": SIGNAL_SESSION_POLICY_VERSION,
            }
        ),
        content_fingerprint=CONTENT_FP,
    )
    prices = (
        FrozenPriceRow(SIGNAL_DATE - timedelta(days=1), Decimal("10"), Decimal("10"), Decimal("10"), Decimal("10"), Decimal("1"), Decimal("0")),
        FrozenPriceRow(SIGNAL_DATE, Decimal("11"), Decimal("11"), Decimal("11"), Decimal("11"), Decimal("1"), Decimal("10")),
    )
    return VerifiedDailyActionSnapshot(
        signal_date=SIGNAL_DATE,
        snapshot_id=SNAPSHOT_ID,
        manifest=manifest,
        universe_tickers=("300001",),
        prices_by_ticker=MappingProxyType({"300001": prices}),
        fund_flow_by_ticker=MappingProxyType({}),
        industry_day_pct_by_ticker=MappingProxyType({"300001": 3.0}),
        regime="normal",
        board_rule_version=BOARD_RULE_VERSION,
        normalization_version=NORMALIZATION_VERSION,
        setup_requirements_version=SETUP_REQUIREMENTS_VERSION,
        ticker_blocks=MappingProxyType({}),
        consumed_fingerprint_by_ticker=MappingProxyType({"300001": MappingProxyType({"btst_breakout": CONSUMED_FP})}),
    )


@pytest.fixture
def valid_candidate() -> PlanCandidate:
    return PlanCandidate(
        ticker="300001",
        setup="btst_breakout",
        setup_version="v2",
        signal_date=SIGNAL_DATE,
        target_weight=0.10,
        priority=1,
        snapshot_id=SNAPSHOT_ID,
        setup_consumed_fingerprint=CONSUMED_FP,
        detector_degraded=False,
        authorization=RegimeAuthorization.BTST_CRISIS,
    )


def test_candidate_snapshot_mismatch_is_blocked(service, valid_candidate) -> None:
    forged = replace(valid_candidate, snapshot_id="sha256:" + "9" * 64)

    run = service.run_from_snapshot(snapshot(), (forged,))

    assert run.new_plans == ()
    assert run.ticker_gate_blocks[0].reasons == ("candidate_snapshot_mismatch",)


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("signal_date", SIGNAL_DATE - timedelta(days=1), "candidate_date_mismatch"),
        ("setup", "oversold_bounce", "candidate_setup_mismatch"),
        ("setup_consumed_fingerprint", "sha256:" + "8" * 64, "candidate_consumed_fingerprint_mismatch"),
        ("detector_degraded", True, "candidate_not_plan_eligible"),
    ],
)
def test_candidate_identity_mismatch_is_blocked(service, valid_candidate, field, value, reason) -> None:
    forged = replace(valid_candidate)
    object.__setattr__(forged, field, value)

    run = service.run_from_snapshot(snapshot(), (forged,))

    assert run.new_plans == ()
    assert run.ticker_gate_blocks[0].reasons == (reason,)


def test_candidate_plan_ineligible_context_is_blocked(service, valid_candidate) -> None:
    run = service.run_from_snapshot(snapshot(plan_eligible=False), (valid_candidate,))

    assert run.new_plans == ()
    assert run.ticker_gate_blocks[0].reasons == ("candidate_not_plan_eligible",)


def test_snapshot_plan_persists_verified_provenance(service, repository, valid_candidate) -> None:
    snap = snapshot()

    run = service.run_from_snapshot(snap, (valid_candidate,))

    assert len(run.new_plans) == 1
    trade = repository.get_trade(run.new_plans[0].trade_id)
    assert trade.provenance.verification_status == "verified"
    assert trade.provenance.source_run_id == snap.manifest.run_id
    assert trade.provenance.manifest_fingerprint == snap.manifest.content_fingerprint
    assert trade.provenance.input_fingerprint == snap.manifest.input_fingerprint
    assert trade.provenance.ticker_cache_fingerprint == valid_candidate.setup_consumed_fingerprint
    assert trade.provenance.snapshot_id == snap.snapshot_id
    assert trade.provenance.setup_consumed_fingerprint == valid_candidate.setup_consumed_fingerprint
    assert trade.provenance.reference_price == 11.0
    assert trade.provenance.authorization == RegimeAuthorization.NORMAL.value
    assert trade.planned_weight == pytest.approx(0.10)
