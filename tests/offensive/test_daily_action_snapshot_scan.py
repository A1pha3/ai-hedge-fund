from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from types import MappingProxyType
from unittest.mock import Mock

import pytest

from src.screening.offensive.daily_action import DailyActionScan, scan_from_verified_snapshot
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
from src.screening.offensive.daily_action_snapshot import FrozenFlowRow, FrozenPriceRow, VerifiedDailyActionSnapshot
from src.screening.offensive.readiness_reference import ReferenceProvenance
from src.screening.offensive.setups.base import DetectionResult
from src.screening.offensive.setups.btst_breakout import BtstBreakoutSetup
from src.screening.offensive.setup_data_contracts import SETUP_REQUIREMENTS_VERSION, SetupCapability
from src.utils.date_utils import SIGNAL_SESSION_POLICY_VERSION

SIGNAL_DATE = date(2026, 7, 13)
CONSUMED_FP = "sha256:" + "a" * 64
SNAPSHOT_ID = "sha256:" + "b" * 64
CONTENT_FP = "sha256:" + "c" * 64
INPUT_FP = "sha256:" + "d" * 64
UNIVERSE_FP = "sha256:" + "e" * 64
SUSPENSION_FP = "sha256:" + "f" * 64


def _shared_evidence(ticker: str = "300001") -> SharedReadinessEvidence:
    regime_row = {"trade_date": SIGNAL_DATE.isoformat(), "regime": "normal"}
    industry_by_ticker = {ticker: "software"}
    industry_day_pct = {ticker: 3.2}
    security_status_by_ticker = {ticker: "listed"}
    security_reference = ReferenceProvenance.create(
        observed_on=SIGNAL_DATE,
        effective_from=SIGNAL_DATE,
        effective_through=SIGNAL_DATE,
        source="tushare.stock_basic",
        version="test-stock-basic-v1",
        content_fingerprint=_fingerprint({"security": ticker}),
    )
    sw_reference = ReferenceProvenance.create(
        observed_on=SIGNAL_DATE,
        effective_from=SIGNAL_DATE,
        effective_through=SIGNAL_DATE,
        source="tushare.index_classify+index_member",
        version="test-sw-v1",
        content_fingerprint=_fingerprint({"sw": ticker}),
    )
    return SharedReadinessEvidence(
        as_of_date=SIGNAL_DATE,
        regime_row=regime_row,
        industry_by_ticker=industry_by_ticker,
        industry_day_pct=industry_day_pct,
        security_status_by_ticker=security_status_by_ticker,
        regime_fingerprint=_fingerprint({"as_of_date": SIGNAL_DATE.isoformat(), "regime_row": regime_row}),
        industry_fingerprint=_fingerprint({"as_of_date": SIGNAL_DATE.isoformat(), "industry_by_ticker": industry_by_ticker, "industry_day_pct": industry_day_pct}),
        security_fingerprint=_fingerprint({"as_of_date": SIGNAL_DATE.isoformat(), "security_status_by_ticker": security_status_by_ticker}),
        security_reference=security_reference,
        sw_reference=sw_reference,
        frozen_source_fingerprint=_fingerprint({"frozen": ticker}),
        board_rule_version=BOARD_RULE_VERSION,
        normalization_version=NORMALIZATION_VERSION,
        signal_session_policy_version=SIGNAL_SESSION_POLICY_VERSION,
    )


def _capability(*, plan_eligible: bool = True, degraded: bool = False, warnings: tuple[str, ...] = ()) -> SetupCapability:
    return SetupCapability(
        enabled=True,
        scannable=True,
        plan_eligible=plan_eligible,
        degraded=degraded,
        block_reasons=() if plan_eligible else ("fund_flow_history_short",),
        warnings=warnings,
        consumed_fingerprint=CONSUMED_FP,
    )


def _disabled_capability() -> SetupCapability:
    return SetupCapability(
        enabled=False,
        scannable=False,
        plan_eligible=False,
        degraded=False,
        block_reasons=("setup_disabled_by_default",),
        warnings=(),
        consumed_fingerprint=None,
    )


def _manifest(ticker: str = "300001", *, capability: SetupCapability | None = None) -> DailyActionReadinessManifest:
    return DailyActionReadinessManifest(
        schema_version=DAILY_ACTION_READINESS_SCHEMA_VERSION,
        domain="daily_action",
        run_id="task7test",
        trade_date=SIGNAL_DATE,
        created_at="2026-07-13T12:00:00+00:00",
        status="healthy",
        universe_kind="resolved_refresh_universe",
        universe_tickers=(ticker,),
        universe_fingerprint=UNIVERSE_FP,
        input_fingerprint=INPUT_FP,
        suspension_evidence=SuspensionReadinessEvidence("available_empty", (), SUSPENSION_FP),
        ticker_readiness=MappingProxyType(
            {
                ticker: DailyActionTickerReadiness(
                    evidence_status="verified",
                    capabilities=MappingProxyType(
                        {
                            "btst_breakout": capability or _capability(),
                            "oversold_bounce": _disabled_capability(),
                        }
                    ),
                )
            }
        ),
        warnings=(),
        shared_evidence=_shared_evidence(ticker),
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


def _prices() -> tuple[FrozenPriceRow, ...]:
    rows: list[FrozenPriceRow] = []
    for index in range(22):
        session = SIGNAL_DATE - timedelta(days=21 - index)
        close = Decimal("10")
        pct = Decimal("0")
        if index == 16:
            close = Decimal("10.5")
        if index == 21:
            close = Decimal("11")
            pct = Decimal("10")
        rows.append(
            FrozenPriceRow(
                trade_date=session,
                open=close,
                high=close,
                low=close,
                close=close,
                volume=Decimal("1000000"),
                pct_change=pct,
            )
        )
    return tuple(rows)


def _flows() -> tuple[FrozenFlowRow, ...]:
    return tuple(
        FrozenFlowRow(
            trade_date=SIGNAL_DATE - timedelta(days=offset),
            close=Decimal("11"),
            pct_change=Decimal("0"),
            main_net_inflow=Decimal("1000000"),
        )
        for offset in range(3)
    )


def _snapshot(ticker: str = "300001", *, capability: SetupCapability | None = None, ticker_blocks: dict[str, tuple[str, ...]] | None = None) -> VerifiedDailyActionSnapshot:
    manifest = _manifest(ticker, capability=capability)
    return VerifiedDailyActionSnapshot(
        signal_date=SIGNAL_DATE,
        snapshot_id=SNAPSHOT_ID,
        manifest=manifest,
        universe_tickers=(ticker,),
        prices_by_ticker=MappingProxyType({ticker: _prices()}),
        fund_flow_by_ticker=MappingProxyType({ticker: _flows()}),
        industry_day_pct_by_ticker=MappingProxyType({ticker: 3.2}),
        regime="normal",
        board_rule_version=BOARD_RULE_VERSION,
        normalization_version=NORMALIZATION_VERSION,
        setup_requirements_version=SETUP_REQUIREMENTS_VERSION,
        ticker_blocks=MappingProxyType(ticker_blocks or {}),
        consumed_fingerprint_by_ticker=MappingProxyType({ticker: MappingProxyType({"btst_breakout": CONSUMED_FP})}),
    )


def hit_result(*, degraded: bool = False) -> DetectionResult:
    return DetectionResult(
        hit=True,
        ticker="300001",
        trade_date=SIGNAL_DATE.strftime("%Y%m%d"),
        trigger_strength=0.90,
        invalidation_condition="price below trigger close",
        metadata={"range_based_stop_pct": -0.08},
        degraded=degraded,
        degradation_reason="detector skipped a required condition" if degraded else "",
    )


def test_empty_snapshot_returns_empty_scan() -> None:
    snapshot = _snapshot(ticker_blocks={"300001": ("fingerprint_mismatch",)})

    scan = scan_from_verified_snapshot(snapshot)

    assert isinstance(scan, DailyActionScan)
    assert scan.signal_date == SIGNAL_DATE
    assert scan.candidates == ()
    assert scan.blocked_candidates == ()


def test_manifest_degraded_capability_is_display_only_before_detector(monkeypatch) -> None:
    detector = Mock(return_value=hit_result())
    monkeypatch.setattr(BtstBreakoutSetup, "detect", detector)
    capability = _capability(plan_eligible=False, degraded=True, warnings=("fund_flow_history_short",))

    scan = scan_from_verified_snapshot(_snapshot(capability=capability))

    assert scan.candidates == ()
    assert len(scan.blocked_candidates) == 1
    assert scan.blocked_candidates[0].ticker == "300001"
    assert scan.blocked_candidates[0].reason == "candidate_not_plan_eligible"
    detector.assert_not_called()


def test_detector_degraded_hit_is_display_only(monkeypatch) -> None:
    monkeypatch.setattr(BtstBreakoutSetup, "detect", lambda self, ticker, trade_date, context: hit_result(degraded=True))

    scan = scan_from_verified_snapshot(_snapshot())

    assert scan.candidates == ()
    assert len(scan.blocked_candidates) == 1
    assert scan.blocked_candidates[0].reason == "detector_degraded"


def test_candidate_carries_structured_snapshot_provenance(monkeypatch) -> None:
    monkeypatch.setattr(BtstBreakoutSetup, "detect", lambda self, ticker, trade_date, context: hit_result())

    scan = scan_from_verified_snapshot(_snapshot())

    assert len(scan.candidates) == 1
    candidate = scan.candidates[0]
    assert candidate.signal_date == SIGNAL_DATE
    assert candidate.snapshot_id == SNAPSHOT_ID
    assert candidate.setup_consumed_fingerprint == CONSUMED_FP
    assert candidate.detector_degraded is False
    assert candidate.target_weight == pytest.approx(0.09)
    assert scan.reference_prices == (("300001", 11.0),)


def test_scanner_never_reopens_cache_files(monkeypatch) -> None:
    monkeypatch.setattr(BtstBreakoutSetup, "detect", lambda self, ticker, trade_date, context: hit_result())
    monkeypatch.setattr("pandas.read_csv", Mock(side_effect=AssertionError("scanner reopened cache file")))

    scan = scan_from_verified_snapshot(_snapshot())

    assert len(scan.candidates) == 1


def test_scanner_is_deterministic_after_runtime_setup_env_changes(monkeypatch) -> None:
    monkeypatch.setattr(
        BtstBreakoutSetup,
        "detect",
        lambda self, ticker, trade_date, context: hit_result(),
    )
    snapshot = _snapshot()

    monkeypatch.setenv("DAILY_ACTION_DISABLED_SETUPS", "btst_breakout")
    disabled_scan = scan_from_verified_snapshot(snapshot)
    monkeypatch.setenv("DAILY_ACTION_DISABLED_SETUPS", "none")
    enabled_scan = scan_from_verified_snapshot(snapshot)

    assert disabled_scan == enabled_scan
    assert len(disabled_scan.candidates) == 1
