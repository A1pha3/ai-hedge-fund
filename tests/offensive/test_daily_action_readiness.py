"""Tests for Daily Action readiness manifest: model, serialization, publication."""

from __future__ import annotations

import json
import hashlib
from datetime import date
from pathlib import Path

import pytest

from src.screening.offensive.cache_readiness import (
    DailyActionRefreshResult,
    FundFlowStatus,
    PriceStatus,
    SuspensionEvidence,
    TickerRefreshOutcome,
    derive_stats_from_outcomes,
    universe_fingerprint,
)
from src.screening.offensive.daily_action_readiness import (
    DAILY_ACTION_READINESS_SCHEMA_VERSION,
    DailyActionReadinessManifest,
    DailyActionTickerReadiness,
    SharedReadinessEvidence,
    build_daily_action_readiness,
    build_ticker_readiness,
    publish_daily_action_readiness,
    validate_manifest,
)
from src.screening.offensive.pit_evidence import canonical_fingerprint
from src.screening.offensive.setup_data_contracts import SetupCapability
from src.utils.date_utils import SIGNAL_SESSION_POLICY_VERSION


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _outcome(
    ticker: str,
    price: PriceStatus = PriceStatus.CURRENT,
    flow: FundFlowStatus = FundFlowStatus.CURRENT,
    price_rows: int = 100,
    flow_rows: int = 100,
    warnings: tuple[str, ...] = (),
) -> TickerRefreshOutcome:
    return TickerRefreshOutcome(
        ticker=ticker,
        price_status=price,
        price_history_rows=price_rows,
        fund_flow_status=flow,
        fund_flow_history_rows=flow_rows,
        evidence_fingerprints={
            "price": _fingerprint({"price": ticker}),
            "fund_flow": _fingerprint({"fund_flow": ticker}),
        },
        warnings=warnings,
    )


def _fingerprint(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _shared_evidence(tickers: tuple[str, ...]) -> SharedReadinessEvidence:
    regime_row = {"regime": "normal"}
    industry_by_ticker = {ticker: "银行" for ticker in tickers}
    industry_day_pct = {ticker: 1.0 for ticker in tickers}
    security_status_by_ticker = {ticker: "listed" for ticker in tickers}
    return SharedReadinessEvidence(
        regime_row=regime_row,
        industry_by_ticker=industry_by_ticker,
        industry_day_pct=industry_day_pct,
        security_status_by_ticker=security_status_by_ticker,
        regime_fingerprint=_fingerprint({"regime_row": regime_row}),
        industry_fingerprint=_fingerprint(
            {
                "industry_by_ticker": industry_by_ticker,
                "industry_day_pct": industry_day_pct,
            }
        ),
        security_fingerprint=_fingerprint(
            {"security_status_by_ticker": security_status_by_ticker}
        ),
        board_rule_version="ashare-board-prefix-v1",
        normalization_version="pit-canonical-v1",
        signal_session_policy_version=SIGNAL_SESSION_POLICY_VERSION,
    )


def _refresh_result(
    tickers_with_outcomes: dict[str, TickerRefreshOutcome],
    *,
    trade_date: date = date(2026, 7, 13),
) -> DailyActionRefreshResult:
    universe = tuple(tickers_with_outcomes.keys())
    stats = derive_stats_from_outcomes(tickers_with_outcomes)
    return DailyActionRefreshResult(
        trade_date=trade_date,
        universe_tickers=universe,
        universe_fingerprint=universe_fingerprint(universe),
        daily_batch_fingerprint=_fingerprint({"batch": trade_date.isoformat()}),
        suspension_evidence=SuspensionEvidence.available(
            trade_date,
            set(),
            source_fingerprint=canonical_fingerprint("suspension", "*", []),
        ),
        outcomes=tickers_with_outcomes,
        stats=stats,
    )


def _manifest(
    tickers: dict[str, TickerRefreshOutcome] | None = None,
    *,
    oversold_bounce_enabled: bool = False,
    st_tickers: frozenset[str] | None = None,
    warnings: tuple[str, ...] = (),
) -> DailyActionReadinessManifest:
    if tickers is None:
        # Default: 3 healthy tickers (deliberately not 300 — separate from Auto)
        tickers = {
            "000001": _outcome("000001"),
            "000002": _outcome("000002"),
            "000003": _outcome("000003"),
        }
    refresh = _refresh_result(tickers)
    return build_daily_action_readiness(
        refresh,
        _shared_evidence(refresh.universe_tickers),
        run_id="run-test-001",
        oversold_bounce_enabled=oversold_bounce_enabled,
        st_tickers=st_tickers,
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# Universe / structural tests
# ---------------------------------------------------------------------------


class TestUniverseIsRefreshUniverse:
    def test_readiness_universe_is_refresh_universe_not_auto_300(self):
        """Manifest universe must mirror the refresh universe, not Auto's 300."""
        # Build a refresh result with a deliberately small, non-300 universe.
        tickers = {
            "600001": _outcome("600001"),
            "600002": _outcome("600002"),
        }
        manifest = _manifest(tickers)
        assert len(manifest.universe_tickers) == 2
        assert set(manifest.universe_tickers) == {"600001", "600002"}
        # Universe fingerprint is the refresh universe fingerprint, not a fixed one
        assert manifest.universe_fingerprint == universe_fingerprint(
            ("600001", "600002")
        )
        assert manifest.universe_kind == "resolved_refresh_universe"

    def test_manifest_carries_input_fingerprint(self):
        manifest = _manifest()
        assert manifest.input_fingerprint == _fingerprint(
            {"batch": date(2026, 7, 13).isoformat()}
        )


class TestStructuralHealth:
    def test_all_tickers_blocked_can_still_be_structurally_healthy(self):
        """All-suspended universe → manifest is_healthy True (structural health)."""
        tickers = {
            "000001": _outcome(
                "000001",
                price=PriceStatus.SUSPENDED,
                flow=FundFlowStatus.SUSPENDED,
                price_rows=0,
                flow_rows=0,
            ),
            "000002": _outcome(
                "000002",
                price=PriceStatus.SUSPENDED,
                flow=FundFlowStatus.SUSPENDED,
                price_rows=0,
                flow_rows=0,
            ),
        }
        manifest = _manifest(tickers)
        # Structural health is independent of per-ticker tradeability.
        assert manifest.is_healthy is True
        assert manifest.status == "healthy"
        # But every ticker is blocked.
        for tr in manifest.ticker_readiness.values():
            assert tr.evidence_status == "blocked"
            for cap in tr.capabilities.values():
                assert cap.scannable is False
                assert cap.plan_eligible is False

    def test_schema_version_constant(self):
        assert DAILY_ACTION_READINESS_SCHEMA_VERSION == 2

    def test_domain_is_daily_action(self):
        manifest = _manifest()
        assert manifest.domain == "daily_action"


# ---------------------------------------------------------------------------
# Capability evaluation
# ---------------------------------------------------------------------------


class TestCapabilityEvaluation:
    def test_shallow_btst_is_scannable_but_not_plan_eligible(self):
        """Fund flow 0-4 days → scannable (degraded), not plan_eligible."""
        tickers = {
            "000001": _outcome("000001", flow_rows=4),
        }
        manifest = _manifest(tickers)
        btst = manifest.ticker_readiness["000001"].capabilities["btst_breakout"]
        assert btst.scannable is True
        assert btst.degraded is True
        assert btst.plan_eligible is False

    def test_full_data_btst_is_plan_eligible(self):
        tickers = {"000001": _outcome("000001", flow_rows=25)}
        manifest = _manifest(tickers)
        btst = manifest.ticker_readiness["000001"].capabilities["btst_breakout"]
        assert btst.scannable is True
        assert btst.plan_eligible is True
        assert btst.degraded is False

    def test_st_ticker_is_blocked(self):
        tickers = {"000001": _outcome("000001")}
        manifest = _manifest(tickers, st_tickers=frozenset({"000001"}))
        btst = manifest.ticker_readiness["000001"].capabilities["btst_breakout"]
        assert btst.scannable is False
        assert "st_stock" in btst.block_reasons
        assert manifest.ticker_readiness["000001"].evidence_status == "blocked"

    def test_oversold_bounce_disabled_by_default(self):
        tickers = {"000001": _outcome("000001")}
        manifest = _manifest(tickers)
        ob = manifest.ticker_readiness["000001"].capabilities["oversold_bounce"]
        assert ob.enabled is False
        assert ob.scannable is False

    def test_oversold_bounce_enabled_full_data(self):
        tickers = {"000001": _outcome("000001", flow_rows=50)}
        manifest = _manifest(tickers, oversold_bounce_enabled=True)
        ob = manifest.ticker_readiness["000001"].capabilities["oversold_bounce"]
        assert ob.enabled is True
        assert ob.scannable is True
        assert ob.plan_eligible is True

    def test_industry_warning_marks_btst_degraded(self):
        tickers = {
            "000001": _outcome("000001")
        }
        regime_row = {"regime": "normal"}
        security = {"000001": "listed"}
        shared = SharedReadinessEvidence(
            regime_row=regime_row,
            industry_by_ticker={},
            industry_day_pct={},
            security_status_by_ticker=security,
            regime_fingerprint=_fingerprint({"regime_row": regime_row}),
            industry_fingerprint=_fingerprint(
                {"industry_by_ticker": {}, "industry_day_pct": {}}
            ),
            security_fingerprint=_fingerprint(
                {"security_status_by_ticker": security}
            ),
            board_rule_version="ashare-board-prefix-v1",
            normalization_version="pit-canonical-v1",
            signal_session_policy_version=SIGNAL_SESSION_POLICY_VERSION,
        )
        manifest = build_daily_action_readiness(
            _refresh_result(tickers), shared, run_id="missing-industry"
        )
        btst = manifest.ticker_readiness["000001"].capabilities["btst_breakout"]
        # Industry missing → degraded, not plan_eligible
        assert btst.degraded is True
        assert btst.plan_eligible is False


class TestAggregates:
    def test_scannable_and_plan_eligible_counts(self):
        tickers = {
            "000001": _outcome("000001", flow_rows=25),  # full → scannable + eligible
            "000002": _outcome("000002", flow_rows=4),   # shallow → scannable, not eligible
            "000003": _outcome(
                "000003",
                price=PriceStatus.SUSPENDED,
                flow=FundFlowStatus.SUSPENDED,
                price_rows=0,
                flow_rows=0,
            ),  # blocked
        }
        manifest = _manifest(tickers)
        # BTST scannable: 000001, 000002 (2). OB disabled so 0 scannable there.
        # Total scannable across capabilities: btst 2 + ob 0 = 2
        assert manifest.scannable_count == 2
        # plan_eligible: only 000001's btst
        assert manifest.plan_eligible_count == 1


# ---------------------------------------------------------------------------
# Serialization roundtrip
# ---------------------------------------------------------------------------


class TestSerialization:
    def test_manifest_serialization_roundtrip(self):
        manifest = _manifest()
        payload = manifest.to_dict()
        restored = validate_manifest(payload)
        assert restored is not None
        assert restored.schema_version == manifest.schema_version
        assert restored.domain == manifest.domain
        assert restored.run_id == manifest.run_id
        assert restored.trade_date == manifest.trade_date
        assert restored.created_at == manifest.created_at
        assert restored.status == manifest.status
        assert restored.universe_kind == manifest.universe_kind
        assert restored.universe_tickers == manifest.universe_tickers
        assert restored.universe_fingerprint == manifest.universe_fingerprint
        assert restored.input_fingerprint == manifest.input_fingerprint
        assert restored.warnings == manifest.warnings
        # Ticker readiness preserved
        assert set(restored.ticker_readiness) == set(manifest.ticker_readiness)
        for ticker in manifest.ticker_readiness:
            orig = manifest.ticker_readiness[ticker]
            got = restored.ticker_readiness[ticker]
            assert got.evidence_status == orig.evidence_status
            for setup in orig.capabilities:
                assert (
                    got.capabilities[setup].scannable
                    == orig.capabilities[setup].scannable
                )
                assert (
                    got.capabilities[setup].plan_eligible
                    == orig.capabilities[setup].plan_eligible
                )
                assert (
                    got.capabilities[setup].block_reasons
                    == orig.capabilities[setup].block_reasons
                )
        # Shared evidence preserved
        assert (
            restored.shared_evidence.regime_fingerprint
            == manifest.shared_evidence.regime_fingerprint
        )
        assert (
            restored.shared_evidence.board_rule_version
            == manifest.shared_evidence.board_rule_version
        )
        # Policy versions preserved
        assert restored.policy_versions == manifest.policy_versions

    def test_to_dict_is_json_serializable(self):
        manifest = _manifest()
        payload = manifest.to_dict()
        # Must round-trip through JSON without error (no NaN, no sets, etc.)
        text = json.dumps(payload, ensure_ascii=False, allow_nan=False)
        back = json.loads(text)
        assert back["domain"] == "daily_action"


# ---------------------------------------------------------------------------
# Validation rejection paths
# ---------------------------------------------------------------------------


class TestValidationRejection:
    def test_unknown_schema_version_rejected(self):
        manifest = _manifest()
        payload = manifest.to_dict()
        payload["schema_version"] = 999
        assert validate_manifest(payload) is None

    def test_missing_schema_version_rejected(self):
        manifest = _manifest()
        payload = manifest.to_dict()
        del payload["schema_version"]
        assert validate_manifest(payload) is None

    def test_wrong_domain_rejected(self):
        manifest = _manifest()
        payload = manifest.to_dict()
        payload["domain"] = "auto"
        assert validate_manifest(payload) is None

    def test_auto_domain_rejected(self):
        """An Auto canonical payload must not validate as daily_action."""
        manifest = _manifest()
        payload = manifest.to_dict()
        payload["domain"] = "auto_screening"
        assert validate_manifest(payload) is None

    def test_malformed_trade_date_rejected(self):
        manifest = _manifest()
        payload = manifest.to_dict()
        payload["trade_date"] = "not-a-date"
        assert validate_manifest(payload) is None


# ---------------------------------------------------------------------------
# Atomic publication
# ---------------------------------------------------------------------------


class TestPublication:
    def test_atomic_publication_creates_file_with_matching_content(
        self, tmp_path: Path
    ):
        manifest = _manifest()
        publication = publish_daily_action_readiness(manifest, tmp_path)
        assert publication.status == "healthy"
        assert publication.artifact_path.exists()
        # Filename matches the date convention
        expected_name = "daily_action_readiness_20260713.json"
        assert publication.artifact_path.name == expected_name
        # Content matches manifest payload
        written = json.loads(publication.artifact_path.read_text(encoding="utf-8"))
        assert written["domain"] == "daily_action"
        assert written["run_id"] == manifest.run_id
        assert written["universe_tickers"] == list(manifest.universe_tickers)
        # Round-trip back through validation
        restored = validate_manifest(written)
        assert restored is not None
        assert restored.run_id == manifest.run_id

    def test_publication_summary_has_correct_counts(self, tmp_path: Path):
        tickers = {
            "000001": _outcome("000001", flow_rows=25),  # full → eligible
            "000002": _outcome("000002", flow_rows=4),   # shallow → scannable only
            "000003": _outcome(
                "000003",
                price=PriceStatus.SUSPENDED,
                flow=FundFlowStatus.SUSPENDED,
                price_rows=0,
                flow_rows=0,
            ),  # blocked
        }
        manifest = _manifest(tickers)
        publication = publish_daily_action_readiness(manifest, tmp_path)
        summary = publication.summary
        assert summary["universe"]["total"] == 3
        assert summary["btst"]["scannable"] == 2
        assert summary["btst"]["plan_eligible"] == 1

    def test_publication_creates_reports_dir_if_missing(self, tmp_path: Path):
        manifest = _manifest()
        nested = tmp_path / "data" / "reports"
        assert not nested.exists()
        publication = publish_daily_action_readiness(manifest, nested)
        assert nested.exists()
        assert publication.artifact_path.exists()

    def test_publication_overwrites_existing_file(self, tmp_path: Path):
        manifest = _manifest()
        publish_daily_action_readiness(manifest, tmp_path)
        # Publish a second time with a different run_id
        tickers = {
            "000001": _outcome("000001"),
        }
        manifest2 = _manifest(tickers)
        manifest2 = build_daily_action_readiness(
            _refresh_result(tickers),
            _shared_evidence(tuple(tickers)),
            run_id="run-test-002",
        )
        publication = publish_daily_action_readiness(manifest2, tmp_path)
        written = json.loads(publication.artifact_path.read_text(encoding="utf-8"))
        assert written["run_id"] == "run-test-002"
        # No leftover temp files
        leftovers = list(tmp_path.glob(".daily_readiness_*.tmp"))
        assert leftovers == []

    def test_publication_no_tempfile_leak_on_success(self, tmp_path: Path):
        manifest = _manifest()
        publish_daily_action_readiness(manifest, tmp_path)
        leftovers = list(tmp_path.glob(".daily_readiness_*.tmp"))
        assert leftovers == []


# ---------------------------------------------------------------------------
# Independence from Auto canonical
# ---------------------------------------------------------------------------


class TestIndependence:
    def test_does_not_import_auto_pipeline(self):
        """Module must not depend on auto_pipeline."""
        import src.screening.offensive.daily_action_readiness as mod

        # No auto_pipeline attribute leaked into module namespace
        assert not hasattr(mod, "auto_pipeline")
        assert not hasattr(mod, "RunManifest")

    def test_policy_versions_include_setup_requirements(self):
        manifest = _manifest()
        assert "setup_requirements" in manifest.policy_versions
        assert manifest.policy_versions["setup_requirements"].startswith(
            "daily-action-setups"
        )

    def test_policy_versions_include_signal_session(self):
        manifest = _manifest()
        assert (
            manifest.policy_versions["signal_session_cutoff"]
            == SIGNAL_SESSION_POLICY_VERSION
        )
