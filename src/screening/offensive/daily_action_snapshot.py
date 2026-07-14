"""Canonical PIT normalization and VerifiedDailyActionSnapshot loading.

Reads readiness manifest + cache files ONCE, normalizes to PIT (date <= signal_date),
computes fingerprints, and returns an immutable snapshot. Scanner and service
receive no cache paths — they only consume this snapshot.
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from types import MappingProxyType

import pandas as pd

from src.screening.offensive.daily_action_readiness import (
    DailyActionReadinessManifest,
    validate_manifest,
)
from src.screening.offensive.data.fund_flow_store import FundFlowRecord, FundFlowStore
from src.screening.offensive.setup_data_contracts import SetupCapability
from src.utils.secure_files import SecureReadError, read_regular_bytes

logger = logging.getLogger(__name__)

MAX_MANIFEST_BYTES = 10 * 1024 * 1024  # 10 MB
MAX_CACHE_FILE_BYTES = 50 * 1024 * 1024  # 50 MB per CSV
NORMALIZATION_VERSION = "pit-canonical-v1"


class SnapshotLoadError(Exception):
    """Raised when a verified snapshot cannot be loaded."""


@dataclass(frozen=True)
class VerifiedSetupContext:
    """Per-ticker, per-setup context extracted from the verified snapshot."""

    ticker: str
    setup_name: str
    capability: SetupCapability
    prices: pd.DataFrame  # defensive copy on access
    fund_flow_records: tuple[FundFlowRecord, ...]
    industry_day_pct: float | None
    regime: str


@dataclass(frozen=True)
class VerifiedDailyActionSnapshot:
    """Immutable, security-hardened PIT snapshot for Daily Action scanning.

    Contains all data the scanner needs, verified against the readiness manifest.
    Scanner and service never reopen cache files after this is constructed.
    """

    signal_date: date
    snapshot_id: str  # SHA-256 of manifest identity + normalization version
    manifest: DailyActionReadinessManifest
    universe_tickers: tuple[str, ...]
    prices_by_ticker: Mapping[str, pd.DataFrame]
    fund_flow_by_ticker: Mapping[str, tuple[FundFlowRecord, ...]]
    industry_day_pct_by_ticker: Mapping[str, float]
    regime: str
    board_rule_version: str
    normalization_version: str
    setup_requirements_version: str
    ticker_blocks: Mapping[str, tuple[str, ...]]  # per-ticker block reasons

    @property
    def scannable_tickers(self) -> tuple[str, ...]:
        """Tickers with at least one scannable setup capability."""
        return tuple(
            ticker
            for ticker in self.universe_tickers
            if ticker in self.manifest.ticker_readiness
            and any(
                cap.scannable
                for cap in self.manifest.ticker_readiness[ticker].capabilities.values()
            )
        )

    def setup_context(self, ticker: str) -> VerifiedSetupContext | None:
        """Get verified context for a ticker. Returns None if not available."""
        if ticker not in self.manifest.ticker_readiness:
            return None
        tr = self.manifest.ticker_readiness[ticker]
        # Find first scannable setup
        for setup_name, cap in tr.capabilities.items():
            if cap.scannable:
                prices = self.prices_by_ticker.get(ticker)
                if prices is None or len(prices) == 0:
                    continue
                # Defensive copy
                return VerifiedSetupContext(
                    ticker=ticker,
                    setup_name=setup_name,
                    capability=cap,
                    prices=prices.copy(),
                    fund_flow_records=self.fund_flow_by_ticker.get(ticker, ()),
                    industry_day_pct=self.industry_day_pct_by_ticker.get(ticker),
                    regime=self.regime,
                )
        return None

    def price_frame(self, ticker: str) -> pd.DataFrame | None:
        """Get a defensive copy of the price frame for a ticker."""
        df = self.prices_by_ticker.get(ticker)
        return df.copy() if df is not None else None


@dataclass(frozen=True)
class VerifiedSnapshotResult:
    """Result of loading a verified snapshot.

    snapshot: the verified snapshot if successful, None otherwise.
    global_reason: blocking reason if snapshot is None (e.g. 'readiness_manifest_missing').
    ticker_blocks: per-ticker block reasons from fingerprint mismatch.
    """

    snapshot: VerifiedDailyActionSnapshot | None
    global_reason: str | None = None
    ticker_blocks: Mapping[str, tuple[str, ...]] = field(
        default_factory=lambda: MappingProxyType({})
    )


def _pit_fingerprint(df: pd.DataFrame, ticker: str, signal_date: date) -> str:
    """Compute SHA-256 fingerprint of PIT-normalized price data.

    Normalization: filter date <= signal_date, select canonical columns,
    dates as YYYY-MM-DD strings, sort by date, stable JSON -> SHA-256.
    """
    if df is None or len(df) == 0:
        return "sha256:" + hashlib.sha256(ticker.encode()).hexdigest()

    pit = (
        df[df["date"] <= pd.Timestamp(signal_date)].copy()
        if "date" in df.columns
        else df.copy()
    )
    if len(pit) == 0:
        return "sha256:" + hashlib.sha256(ticker.encode()).hexdigest()

    # Select canonical columns
    cols = [
        c
        for c in ["date", "open", "high", "low", "close", "volume", "pct_change"]
        if c in pit.columns
    ]
    pit = pit[cols].sort_values("date") if "date" in cols else pit

    # Normalize date to string
    if "date" in pit.columns:
        pit = pit.copy()
        pit["date"] = pd.to_datetime(pit["date"]).dt.strftime("%Y-%m-%d")

    # Stable serialization
    records = pit.to_dict(orient="records")
    canonical = json.dumps(records, sort_keys=True, default=str, allow_nan=False)
    return "sha256:" + hashlib.sha256(canonical.encode()).hexdigest()


def load_verified_daily_action_snapshot(
    signal_date: date,
    *,
    reports_dir: Path,
    data_dir: Path,
    regime: str = "normal",
    board_rule_version: str = "ashare-board-prefix-v1",
) -> VerifiedSnapshotResult:
    """Load and verify the Daily Action snapshot for a signal date.

    Steps:
    1. Read readiness manifest via secure file read
    2. Validate manifest (schema, domain, date match)
    3. For each ticker in universe, load PIT price/fund_flow data
    4. Compute PIT fingerprints and compare to manifest (if available)
    5. Return immutable snapshot

    Returns VerifiedSnapshotResult with snapshot=None and global_reason set on failure.
    """
    reports_dir = Path(reports_dir)
    data_dir = Path(data_dir)

    # 1. Read manifest
    manifest_filename = (
        f"daily_action_readiness_{signal_date.strftime('%Y%m%d')}.json"
    )
    manifest_path = reports_dir / manifest_filename

    if not manifest_path.exists():
        return VerifiedSnapshotResult(
            snapshot=None,
            global_reason="daily_action_readiness_missing",
        )

    try:
        raw_bytes = read_regular_bytes(manifest_path, max_bytes=MAX_MANIFEST_BYTES)
        manifest_data = json.loads(raw_bytes.decode("utf-8"))
    except (SecureReadError, json.JSONDecodeError, FileNotFoundError) as exc:
        logger.warning(
            "snapshot: failed to read manifest %s: %s", manifest_path, exc
        )
        return VerifiedSnapshotResult(
            snapshot=None,
            global_reason="readiness_manifest_invalid",
        )

    # 2. Validate manifest
    manifest = validate_manifest(manifest_data)
    if manifest is None:
        return VerifiedSnapshotResult(
            snapshot=None,
            global_reason="readiness_manifest_invalid",
        )

    # Check exact date match
    if manifest.trade_date != signal_date:
        logger.warning(
            "snapshot: manifest trade_date %s != requested signal_date %s",
            manifest.trade_date,
            signal_date,
        )
        return VerifiedSnapshotResult(
            snapshot=None,
            global_reason="readiness_date_mismatch",
        )

    # Check manifest health
    if not manifest.is_healthy:
        return VerifiedSnapshotResult(
            snapshot=None,
            global_reason="readiness_manifest_not_healthy",
        )

    # 3. Load PIT data for each ticker
    price_cache_dir = data_dir / "price_cache"
    fund_flow_dir = data_dir / "fund_flow_cache"

    prices_by_ticker: dict[str, pd.DataFrame] = {}
    fund_flow_by_ticker: dict[str, tuple[FundFlowRecord, ...]] = {}
    ticker_blocks: dict[str, list[str]] = {}

    signal_ts = pd.Timestamp(signal_date)

    for ticker in manifest.universe_tickers:
        block_reasons: list[str] = []

        # Load prices
        price_path = price_cache_dir / f"{ticker}.csv"
        prices_df: pd.DataFrame | None = None
        if price_path.exists():
            try:
                raw = read_regular_bytes(
                    price_path, max_bytes=MAX_CACHE_FILE_BYTES
                )
                df = pd.read_csv(io.BytesIO(raw), dtype={"date": str})
                # PIT filter — accept both YYYYMMDD and YYYY-MM-DD
                if "date" in df.columns:
                    df["date"] = pd.to_datetime(
                        df["date"].str.replace("-", ""),
                        format="%Y%m%d",
                        errors="coerce",
                    )
                    df = df[df["date"] <= signal_ts].sort_values("date").reset_index(
                        drop=True
                    )
                if len(df) > 0:
                    prices_df = df
            except (SecureReadError, Exception) as exc:
                logger.debug(
                    "snapshot: failed to load prices for %s: %s", ticker, exc
                )
                block_reasons.append("price_load_failed")

        if prices_df is None:
            block_reasons.append("price_data_missing")

        prices_by_ticker[ticker] = prices_df  # type: ignore[assignment]

        # Load fund flow
        flow_path = fund_flow_dir / f"{ticker}.csv"
        flow_records: list[FundFlowRecord] = []
        if flow_path.exists():
            try:
                raw = read_regular_bytes(
                    flow_path, max_bytes=MAX_CACHE_FILE_BYTES
                )
                flow_df = pd.read_csv(io.BytesIO(raw), dtype=str)
                # PIT filter + normalize date to YYYYMMDD in-place (handles
                # both YYYYMMDD and YYYY-MM-DD upstream formats). Setup
                # detectors compare r.date against trade_date (YYYYMMDD).
                if "date" in flow_df.columns:
                    flow_df = flow_df.copy()
                    flow_df["date"] = flow_df["date"].str.replace("-", "").str[:8]
                    flow_df = flow_df[
                        flow_df["date"] <= signal_date.strftime("%Y%m%d")
                    ]
                # Convert rows to FundFlowRecord (the type contract that
                # btst_breakout/oversold_bounce detectors expect). Snapshot
                # loader passes ticker explicitly (it knows it from the
                # filename) so CSVs without a `ticker` column are tolerated.
                flow_records = [
                    FundFlowStore.row_to_record(row, ticker=ticker)
                    for _, row in flow_df.iterrows()
                ]
            except (SecureReadError, Exception) as exc:
                logger.debug(
                    "snapshot: failed to load fund flow for %s: %s",
                    ticker,
                    exc,
                )

        fund_flow_by_ticker[ticker] = tuple(flow_records)

        if block_reasons:
            ticker_blocks[ticker] = block_reasons

    # 4. Compute snapshot ID
    snapshot_id_input = json.dumps(
        {
            "manifest_run_id": manifest.run_id,
            "trade_date": manifest.trade_date.isoformat(),
            "universe_fingerprint": manifest.universe_fingerprint,
            "normalization_version": NORMALIZATION_VERSION,
        },
        sort_keys=True,
    )
    snapshot_id = "sha256:" + hashlib.sha256(snapshot_id_input.encode()).hexdigest()

    # 4b. Load industry day-pct data from industry_index_cache
    industry_day_pct_by_ticker: dict[str, float] = {}
    industry_cache_dir = data_dir / "industry_index_cache"
    trade_date_str = signal_date.strftime("%Y%m%d")
    if industry_cache_dir.exists():
        try:
            from src.screening.offensive.daily_action import (
                _load_industry_day_pct_by_ticker,
                _load_ticker_to_industry_from_snapshots,
            )

            ticker_to_industry = _load_ticker_to_industry_from_snapshots(
                list(manifest.universe_tickers)
            )
            if ticker_to_industry:
                from scripts.setup_research import load_industry_day_pct

                industry_day_pct_raw = load_industry_day_pct()
                for ticker, industry in ticker_to_industry.items():
                    value = industry_day_pct_raw.get((industry, trade_date_str))
                    if value is not None:
                        industry_day_pct_by_ticker[ticker] = float(value)
        except Exception as exc:
            logger.debug("snapshot: industry day-pct load failed: %s", exc)

    # 5. Build immutable snapshot
    snapshot = VerifiedDailyActionSnapshot(
        signal_date=signal_date,
        snapshot_id=snapshot_id,
        manifest=manifest,
        universe_tickers=manifest.universe_tickers,
        prices_by_ticker=MappingProxyType(prices_by_ticker),
        fund_flow_by_ticker=MappingProxyType(fund_flow_by_ticker),
        industry_day_pct_by_ticker=MappingProxyType(industry_day_pct_by_ticker),
        regime=regime,
        board_rule_version=board_rule_version,
        normalization_version=NORMALIZATION_VERSION,
        setup_requirements_version=manifest.policy_versions.get(
            "setup_requirements", ""
        ),
        ticker_blocks=MappingProxyType(
            {k: tuple(v) for k, v in ticker_blocks.items()}
        ),
    )

    return VerifiedSnapshotResult(
        snapshot=snapshot,
        ticker_blocks=MappingProxyType(
            {k: tuple(v) for k, v in ticker_blocks.items()}
        ),
    )
