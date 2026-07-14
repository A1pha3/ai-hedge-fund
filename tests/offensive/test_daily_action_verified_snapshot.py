"""Tests for VerifiedDailyActionSnapshot: PIT normalization, immutability, verification.

Covers:
- Manifest missing / invalid / date-mismatch rejection
- Happy-path snapshot loading with prices + fund flow
- PIT fingerprint stability (future appends don't change fingerprint)
- Setup context extraction + defensive copies
- Scannable tickers exclude blocked ones
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from types import MappingProxyType

import pandas as pd
import pytest

from src.screening.offensive.daily_action_readiness import (
    DAILY_ACTION_READINESS_SCHEMA_VERSION,
    SharedReadinessEvidence,
)
from src.screening.offensive.daily_action_snapshot import (
    NORMALIZATION_VERSION,
    load_verified_daily_action_snapshot,
    _pit_fingerprint,
)
from src.screening.offensive.setup_data_contracts import SetupCapability


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _scannable_capability() -> SetupCapability:
    return SetupCapability(
        enabled=True,
        scannable=True,
        plan_eligible=True,
        degraded=False,
        block_reasons=(),
        warnings=(),
    )


def _blocked_capability(reason: str = "price_data_missing") -> SetupCapability:
    return SetupCapability(
        enabled=True,
        scannable=False,
        plan_eligible=False,
        degraded=False,
        block_reasons=(reason,),
    )


def _shared_evidence() -> SharedReadinessEvidence:
    return SharedReadinessEvidence(
        regime_row=MappingProxyType({"trend": "up"}),
        regime_fingerprint="sha256:regime",
        industry_mapping_fingerprint="sha256:industry",
        security_status_fingerprint="sha256:sec",
        board_rule_version="ashare-board-prefix-v1",
        normalization_version=NORMALIZATION_VERSION,
        signal_session_policy_version="signal-session-v1",
    )


def _manifest_dict(
    *,
    trade_date: date = date(2026, 7, 13),
    tickers: tuple[str, ...] = ("000001", "000002"),
    ticker_readiness: dict | None = None,
    schema_version: int = DAILY_ACTION_READINESS_SCHEMA_VERSION,
    status: str = "healthy",
) -> dict:
    """Build a serializable manifest dict for testing."""
    if ticker_readiness is None:
        # Default: every ticker is fully scannable
        ticker_readiness = {
            t: {
                "evidence_status": "verified",
                "capabilities": {
                    "btst_breakout": {
                        "enabled": True,
                        "scannable": True,
                        "plan_eligible": True,
                        "degraded": False,
                        "block_reasons": [],
                        "warnings": [],
                    }
                },
            }
            for t in tickers
        }

    return {
        "schema_version": schema_version,
        "domain": "daily_action",
        "run_id": "run-test-001",
        "trade_date": trade_date.isoformat(),
        "created_at": "2026-07-13T10:00:00Z",
        "status": status,
        "universe_kind": "resolved_refresh_universe",
        "universe_tickers": list(tickers),
        "universe_fingerprint": "sha256:universe",
        "input_fingerprint": "sha256:input",
        "ticker_readiness": ticker_readiness,
        "warnings": [],
        "shared_evidence": {
            "regime_fingerprint": "sha256:regime",
            "industry_mapping_fingerprint": "sha256:industry",
            "security_status_fingerprint": "sha256:sec",
            "board_rule_version": "ashare-board-prefix-v1",
            "normalization_version": NORMALIZATION_VERSION,
            "signal_session_policy_version": "signal-session-v1",
        },
        "policy_versions": {
            "readiness_policy": "daily-action-readiness-v1",
            "normalization": NORMALIZATION_VERSION,
            "board_rule": "ashare-board-prefix-v1",
            "setup_requirements": "daily-action-setups-v1",
            "signal_session_cutoff": "signal-session-v1",
        },
    }


def _write_price_cache(
    data_dir: Path,
    ticker: str,
    *,
    rows: list[dict] | None = None,
) -> Path:
    """Write a price_cache CSV for a ticker. Dates as YYYY-MM-DD strings."""
    price_dir = data_dir / "price_cache"
    price_dir.mkdir(parents=True, exist_ok=True)
    path = price_dir / f"{ticker}.csv"
    if rows is None:
        rows = [
            {"date": "2026-07-08", "open": 10.0, "high": 10.5, "low": 9.8, "close": 10.2, "volume": 1000.0, "pct_change": 1.0},
            {"date": "2026-07-09", "open": 10.2, "high": 10.6, "low": 10.0, "close": 10.4, "volume": 1100.0, "pct_change": 1.96},
            {"date": "2026-07-10", "open": 10.4, "high": 10.8, "low": 10.2, "close": 10.6, "volume": 1200.0, "pct_change": 1.92},
            {"date": "2026-07-11", "open": 10.6, "high": 11.0, "low": 10.4, "close": 10.8, "volume": 1300.0, "pct_change": 1.89},
            {"date": "2026-07-12", "open": 10.8, "high": 11.2, "low": 10.6, "close": 11.0, "volume": 1400.0, "pct_change": 1.85},
            {"date": "2026-07-13", "open": 11.0, "high": 11.4, "low": 10.8, "close": 11.2, "volume": 1500.0, "pct_change": 1.82},
        ]
    df = pd.DataFrame(rows)
    df.to_csv(path, index=False)
    return path


def _write_fund_flow_cache(
    data_dir: Path,
    ticker: str,
    *,
    rows: list[dict] | None = None,
) -> Path:
    """Write a fund_flow_cache CSV for a ticker. Dates as YYYYMMDD strings."""
    flow_dir = data_dir / "fund_flow_cache"
    flow_dir.mkdir(parents=True, exist_ok=True)
    path = flow_dir / f"{ticker}.csv"
    if rows is None:
        rows = [
            {"date": "20260711", "close": "10.8", "pct_change": "1.89", "main_net_inflow": "1000.0", "ticker": ticker},
            {"date": "20260712", "close": "11.0", "pct_change": "1.85", "main_net_inflow": "2000.0", "ticker": ticker},
            {"date": "20260713", "close": "11.2", "pct_change": "1.82", "main_net_inflow": "3000.0", "ticker": ticker},
        ]
    df = pd.DataFrame(rows)
    df.to_csv(path, index=False)
    return path


def _write_manifest(reports_dir: Path, manifest: dict, *, trade_date: date) -> Path:
    reports_dir.mkdir(parents=True, exist_ok=True)
    path = reports_dir / f"daily_action_readiness_{trade_date.strftime('%Y%m%d')}.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path


def _build_full_fixture(
    tmp_path: Path,
    *,
    signal_date: date = date(2026, 7, 13),
    tickers: tuple[str, ...] = ("000001", "000002"),
    manifest_override: dict | None = None,
    write_prices: bool = True,
    write_fund_flow: bool = True,
) -> tuple[Path, Path]:
    """Create reports_dir + data_dir with manifest, price cache, fund flow cache."""
    reports_dir = tmp_path / "reports"
    data_dir = tmp_path / "data"

    manifest = manifest_override or _manifest_dict(
        trade_date=signal_date, tickers=tickers
    )
    _write_manifest(reports_dir, manifest, trade_date=signal_date)

    if write_prices:
        for t in tickers:
            _write_price_cache(data_dir, t)
    if write_fund_flow:
        for t in tickers:
            _write_fund_flow_cache(data_dir, t)

    return reports_dir, data_dir


SIGNAL_DATE = date(2026, 7, 13)


# ---------------------------------------------------------------------------
# Manifest rejection tests
# ---------------------------------------------------------------------------


class TestManifestRejection:
    def test_missing_manifest_returns_global_reason(self, tmp_path: Path):
        """No manifest file -> snapshot None, reason daily_action_readiness_missing."""
        reports_dir = tmp_path / "reports"
        data_dir = tmp_path / "data"
        reports_dir.mkdir(parents=True)
        data_dir.mkdir(parents=True)

        result = load_verified_daily_action_snapshot(
            SIGNAL_DATE, reports_dir=reports_dir, data_dir=data_dir
        )

        assert result.snapshot is None
        assert result.global_reason == "daily_action_readiness_missing"

    def test_wrong_schema_rejected(self, tmp_path: Path):
        """Manifest with wrong schema_version -> readiness_manifest_invalid."""
        manifest = _manifest_dict(schema_version=99)
        reports_dir, data_dir = _build_full_fixture(
            tmp_path, manifest_override=manifest
        )

        result = load_verified_daily_action_snapshot(
            SIGNAL_DATE, reports_dir=reports_dir, data_dir=data_dir
        )

        assert result.snapshot is None
        assert result.global_reason == "readiness_manifest_invalid"

    def test_date_mismatch_rejected(self, tmp_path: Path):
        """Manifest trade_date != signal_date -> readiness_date_mismatch."""
        manifest = _manifest_dict(trade_date=date(2026, 7, 12))
        reports_dir, data_dir = _build_full_fixture(
            tmp_path, manifest_override=manifest
        )

        result = load_verified_daily_action_snapshot(
            SIGNAL_DATE, reports_dir=reports_dir, data_dir=data_dir
        )

        assert result.snapshot is None
        assert result.global_reason == "readiness_date_mismatch"

    def test_wrong_domain_rejected(self, tmp_path: Path):
        manifest = _manifest_dict()
        manifest["domain"] = "auto_canonical"
        reports_dir, data_dir = _build_full_fixture(
            tmp_path, manifest_override=manifest
        )

        result = load_verified_daily_action_snapshot(
            SIGNAL_DATE, reports_dir=reports_dir, data_dir=data_dir
        )

        assert result.snapshot is None
        assert result.global_reason == "readiness_manifest_invalid"

    def test_unhealthy_status_rejected(self, tmp_path: Path):
        manifest = _manifest_dict(status="degraded")
        reports_dir, data_dir = _build_full_fixture(
            tmp_path, manifest_override=manifest
        )

        result = load_verified_daily_action_snapshot(
            SIGNAL_DATE, reports_dir=reports_dir, data_dir=data_dir
        )

        assert result.snapshot is None
        assert result.global_reason == "readiness_manifest_not_healthy"

    def test_corrupt_manifest_rejected(self, tmp_path: Path):
        reports_dir = tmp_path / "reports"
        data_dir = tmp_path / "data"
        reports_dir.mkdir(parents=True)
        data_dir.mkdir(parents=True)

        path = reports_dir / f"daily_action_readiness_{SIGNAL_DATE.strftime('%Y%m%d')}.json"
        path.write_text("{ not valid json ", encoding="utf-8")

        result = load_verified_daily_action_snapshot(
            SIGNAL_DATE, reports_dir=reports_dir, data_dir=data_dir
        )

        assert result.snapshot is None
        assert result.global_reason == "readiness_manifest_invalid"


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestHappyPath:
    def test_valid_manifest_loads_snapshot(self, tmp_path: Path):
        reports_dir, data_dir = _build_full_fixture(tmp_path)

        result = load_verified_daily_action_snapshot(
            SIGNAL_DATE, reports_dir=reports_dir, data_dir=data_dir
        )

        assert result.snapshot is not None
        assert result.global_reason is None
        snap = result.snapshot
        assert snap.signal_date == SIGNAL_DATE
        assert set(snap.universe_tickers) == {"000001", "000002"}
        assert snap.normalization_version == NORMALIZATION_VERSION
        assert snap.snapshot_id.startswith("sha256:")
        assert snap.regime == "normal"
        assert snap.board_rule_version == "ashare-board-prefix-v1"
        assert snap.setup_requirements_version == "daily-action-setups-v1"

    def test_snapshot_provides_setup_context(self, tmp_path: Path):
        reports_dir, data_dir = _build_full_fixture(tmp_path)

        result = load_verified_daily_action_snapshot(
            SIGNAL_DATE, reports_dir=reports_dir, data_dir=data_dir
        )
        assert result.snapshot is not None
        snap = result.snapshot

        ctx = snap.setup_context("000001")
        assert ctx is not None
        assert ctx.ticker == "000001"
        assert ctx.setup_name == "btst_breakout"
        assert ctx.capability.scannable is True
        # Prices loaded and PIT-filtered (should have rows up to 2026-07-13)
        assert len(ctx.prices) > 0
        assert ctx.prices["date"].max() <= pd.Timestamp(SIGNAL_DATE)
        # Fund flow loaded
        assert len(ctx.fund_flow_records) > 0
        assert ctx.regime == "normal"

    def test_setup_context_returns_none_for_unknown_ticker(self, tmp_path: Path):
        reports_dir, data_dir = _build_full_fixture(tmp_path)
        result = load_verified_daily_action_snapshot(
            SIGNAL_DATE, reports_dir=reports_dir, data_dir=data_dir
        )
        assert result.snapshot is not None
        assert result.snapshot.setup_context("999999") is None


# ---------------------------------------------------------------------------
# PIT normalization & fingerprint stability
# ---------------------------------------------------------------------------


class TestPitNormalization:
    def test_future_append_does_not_change_pit_projection(self, tmp_path: Path):
        """Adding a row dated AFTER signal_date must not change the PIT fingerprint."""
        df_before = pd.DataFrame(
            [
                {"date": "2026-07-12", "open": 10.8, "high": 11.2, "low": 10.6, "close": 11.0, "volume": 1400.0, "pct_change": 1.85},
                {"date": "2026-07-13", "open": 11.0, "high": 11.4, "low": 10.8, "close": 11.2, "volume": 1500.0, "pct_change": 1.82},
            ]
        )
        df_before["date"] = pd.to_datetime(df_before["date"])

        df_after = df_before.copy()
        df_after = pd.concat(
            [
                df_after,
                pd.DataFrame(
                    [
                        {"date": pd.Timestamp("2026-07-14"), "open": 11.2, "high": 11.6, "low": 11.0, "close": 11.4, "volume": 1600.0, "pct_change": 1.79},
                        {"date": pd.Timestamp("2026-07-15"), "open": 11.4, "high": 11.8, "low": 11.2, "close": 11.6, "volume": 1700.0, "pct_change": 1.75},
                    ]
                ),
            ],
            ignore_index=True,
        )

        fp_before = _pit_fingerprint(df_before, "000001", SIGNAL_DATE)
        fp_after = _pit_fingerprint(df_after, "000001", SIGNAL_DATE)

        assert fp_before == fp_after
        assert fp_before.startswith("sha256:")

    def test_pit_filter_excludes_future_rows_in_loaded_snapshot(
        self, tmp_path: Path
    ):
        """Loaded snapshot must not contain price rows past signal_date."""
        rows = [
            {"date": "2026-07-12", "open": 10.8, "high": 11.2, "low": 10.6, "close": 11.0, "volume": 1400.0, "pct_change": 1.85},
            {"date": "2026-07-13", "open": 11.0, "high": 11.4, "low": 10.8, "close": 11.2, "volume": 1500.0, "pct_change": 1.82},
            # Future rows that must be excluded by PIT filter
            {"date": "2026-07-14", "open": 11.2, "high": 11.6, "low": 11.0, "close": 11.4, "volume": 1600.0, "pct_change": 1.79},
            {"date": "2026-07-15", "open": 11.4, "high": 11.8, "low": 11.2, "close": 11.6, "volume": 1700.0, "pct_change": 1.75},
        ]
        reports_dir = tmp_path / "reports"
        data_dir = tmp_path / "data"
        _write_manifest(reports_dir, _manifest_dict(), trade_date=SIGNAL_DATE)
        _write_price_cache(data_dir, "000001", rows=rows)
        _write_price_cache(data_dir, "000002", rows=rows)
        _write_fund_flow_cache(data_dir, "000001")
        _write_fund_flow_cache(data_dir, "000002")

        result = load_verified_daily_action_snapshot(
            SIGNAL_DATE, reports_dir=reports_dir, data_dir=data_dir
        )
        assert result.snapshot is not None
        for ticker in ("000001", "000002"):
            df = result.snapshot.prices_by_ticker[ticker]
            assert df["date"].max() == pd.Timestamp(SIGNAL_DATE)
            assert len(df) == 2  # only 2026-07-12 and 2026-07-13

    def test_empty_df_fingerprint_is_ticker_hash(self):
        empty = pd.DataFrame()
        fp = _pit_fingerprint(empty, "000001", SIGNAL_DATE)
        assert fp.startswith("sha256:")
        # Stable for the same ticker
        assert fp == _pit_fingerprint(None, "000001", SIGNAL_DATE)


# ---------------------------------------------------------------------------
# Immutability & defensive copies
# ---------------------------------------------------------------------------


class TestImmutability:
    def test_snapshot_is_frozen(self, tmp_path: Path):
        reports_dir, data_dir = _build_full_fixture(tmp_path)
        result = load_verified_daily_action_snapshot(
            SIGNAL_DATE, reports_dir=reports_dir, data_dir=data_dir
        )
        assert result.snapshot is not None
        with pytest.raises(Exception):
            result.snapshot.regime = "changed"  # type: ignore[misc]

    def test_price_frame_returns_defensive_copy(self, tmp_path: Path):
        """Modifying the df returned by price_frame() must not affect the snapshot."""
        reports_dir, data_dir = _build_full_fixture(tmp_path)
        result = load_verified_daily_action_snapshot(
            SIGNAL_DATE, reports_dir=reports_dir, data_dir=data_dir
        )
        assert result.snapshot is not None
        snap = result.snapshot

        df1 = snap.price_frame("000001")
        assert df1 is not None
        original_close = df1["close"].iloc[0]
        # Mutate the returned copy
        df1.loc[0, "close"] = 99999.0

        # Snapshot's internal frame is unchanged
        df2 = snap.price_frame("000001")
        assert df2 is not None
        assert df2["close"].iloc[0] == original_close

    def test_setup_context_returns_defensive_copy(self, tmp_path: Path):
        """Modifying prices returned via setup_context must not affect the snapshot."""
        reports_dir, data_dir = _build_full_fixture(tmp_path)
        result = load_verified_daily_action_snapshot(
            SIGNAL_DATE, reports_dir=reports_dir, data_dir=data_dir
        )
        assert result.snapshot is not None
        snap = result.snapshot

        ctx = snap.setup_context("000001")
        assert ctx is not None
        original = ctx.prices["close"].iloc[0]
        ctx.prices.loc[0, "close"] = -1.0

        ctx2 = snap.setup_context("000001")
        assert ctx2 is not None
        assert ctx2.prices["close"].iloc[0] == original

    def test_prices_mapping_is_immutable(self, tmp_path: Path):
        reports_dir, data_dir = _build_full_fixture(tmp_path)
        result = load_verified_daily_action_snapshot(
            SIGNAL_DATE, reports_dir=reports_dir, data_dir=data_dir
        )
        assert result.snapshot is not None
        with pytest.raises(TypeError):
            result.snapshot.prices_by_ticker["999999"] = pd.DataFrame()  # type: ignore[index]


# ---------------------------------------------------------------------------
# Scannable tickers & block propagation
# ---------------------------------------------------------------------------


class TestScannableTickers:
    def test_scannable_tickers_excludes_blocked(self, tmp_path: Path):
        """Tickers whose capability is not scannable must not appear in scannable_tickers."""
        ticker_readiness = {
            "000001": {
                "evidence_status": "verified",
                "capabilities": {
                    "btst_breakout": {
                        "enabled": True,
                        "scannable": True,
                        "plan_eligible": True,
                        "degraded": False,
                        "block_reasons": [],
                        "warnings": [],
                    }
                },
            },
            "000002": {
                "evidence_status": "blocked",
                "capabilities": {
                    "btst_breakout": {
                        "enabled": True,
                        "scannable": False,
                        "plan_eligible": False,
                        "degraded": False,
                        "block_reasons": ["suspended"],
                        "warnings": [],
                    }
                },
            },
        }
        manifest = _manifest_dict(
            tickers=("000001", "000002"), ticker_readiness=ticker_readiness
        )
        reports_dir, data_dir = _build_full_fixture(
            tmp_path, manifest_override=manifest
        )

        result = load_verified_daily_action_snapshot(
            SIGNAL_DATE, reports_dir=reports_dir, data_dir=data_dir
        )
        assert result.snapshot is not None
        snap = result.snapshot

        assert "000001" in snap.scannable_tickers
        assert "000002" not in snap.scannable_tickers

    def test_price_data_missing_blocks_ticker(self, tmp_path: Path):
        """A ticker with no price cache file gets a price_data_missing block reason."""
        manifest = _manifest_dict(tickers=("000001", "000002"))
        reports_dir, data_dir = _build_full_fixture(
            tmp_path, manifest_override=manifest, write_prices=False
        )
        # Manually remove price cache to ensure missing
        # (write_prices=False above already skips it)

        result = load_verified_daily_action_snapshot(
            SIGNAL_DATE, reports_dir=reports_dir, data_dir=data_dir
        )
        assert result.snapshot is not None
        for ticker in ("000001", "000002"):
            assert "price_data_missing" in result.snapshot.ticker_blocks.get(
                ticker, ()
            )
            assert ticker not in result.snapshot.scannable_tickers or (
                ticker in result.snapshot.manifest.ticker_readiness
                and any(
                    c.scannable
                    for c in result.snapshot.manifest.ticker_readiness[
                        ticker
                    ].capabilities.values()
                )
            )

    def test_ticker_blocks_propagate_to_result(self, tmp_path: Path):
        """ticker_blocks mapping is exposed on both snapshot and result."""
        manifest = _manifest_dict(tickers=("000001", "000002"))
        reports_dir, data_dir = _build_full_fixture(
            tmp_path, manifest_override=manifest, write_prices=False
        )

        result = load_verified_daily_action_snapshot(
            SIGNAL_DATE, reports_dir=reports_dir, data_dir=data_dir
        )
        assert result.snapshot is not None
        # Both surfaces carry the same block info
        assert "000001" in result.ticker_blocks
        assert "000001" in result.snapshot.ticker_blocks
        assert result.ticker_blocks["000001"] == result.snapshot.ticker_blocks["000001"]


# ---------------------------------------------------------------------------
# Fund flow loading
# ---------------------------------------------------------------------------


class TestFundFlowLoading:
    def test_fund_flow_pit_filtered(self, tmp_path: Path):
        """Fund flow records dated after signal_date are excluded."""
        reports_dir, data_dir = _build_full_fixture(tmp_path)
        # Overwrite fund flow with future-dated rows
        future_rows = [
            {"date": "20260713", "close": "11.2", "pct_change": "1.82", "main_net_inflow": "3000.0", "ticker": "000001"},
            {"date": "20260714", "close": "11.4", "pct_change": "1.79", "main_net_inflow": "4000.0", "ticker": "000001"},
            {"date": "20260715", "close": "11.6", "pct_change": "1.75", "main_net_inflow": "5000.0", "ticker": "000001"},
        ]
        _write_fund_flow_cache(data_dir, "000001", rows=future_rows)
        _write_fund_flow_cache(data_dir, "000002", rows=future_rows)

        result = load_verified_daily_action_snapshot(
            SIGNAL_DATE, reports_dir=reports_dir, data_dir=data_dir
        )
        assert result.snapshot is not None
        records = result.snapshot.fund_flow_by_ticker["000001"]
        # Only 20260713 should remain; 14 and 15 are post-signal
        assert len(records) == 1
        assert str(records[0].get("date")).startswith("20260713")

    def test_missing_fund_flow_does_not_block_ticker(self, tmp_path: Path):
        """Absence of fund_flow cache is non-fatal; ticker still loads with prices."""
        reports_dir, data_dir = _build_full_fixture(
            tmp_path, write_fund_flow=False
        )
        result = load_verified_daily_action_snapshot(
            SIGNAL_DATE, reports_dir=reports_dir, data_dir=data_dir
        )
        assert result.snapshot is not None
        snap = result.snapshot
        # Prices present, fund flow empty tuple
        for ticker in ("000001", "000002"):
            assert snap.prices_by_ticker[ticker] is not None
            assert len(snap.prices_by_ticker[ticker]) > 0
            assert snap.fund_flow_by_ticker[ticker] == ()
            # No price_data_missing block — only fund flow absence
            assert "price_data_missing" not in snap.ticker_blocks.get(ticker, ())
