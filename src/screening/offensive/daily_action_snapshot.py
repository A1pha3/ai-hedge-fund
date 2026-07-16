"""Security-hardened immutable verified PIT snapshot for Daily Action.

The loader accepts only a schema-v2 readiness manifest, reads each price/fund-flow
cache file exactly once through symlink-resistant secure reads, recomputes the
point-in-time (``date <= signal_date``) fingerprints, and compares the recomputed
per-setup consumed fingerprint against the manifest's authorized value. Any
historical row mutation, deletion, or replacement changes the recomputed
fingerprint and blocks the affected ticker; a future-dated append is filtered out
and leaves the verified snapshot identical.

The snapshot exposes only immutable frozen records. It never re-opens cache files
after verification and never falls back to legacy cache helpers: industry,
security, regime, and policy evidence are all taken from the validated manifest.
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from types import MappingProxyType

import pandas as pd

from src.screening.offensive.daily_action_readiness import (
    DAILY_ACTION_READINESS_SCHEMA_VERSION,
    DailyActionReadinessManifest,
    parse_manifest_v2,
    recompute_setup_consumed_fingerprint,
)
from src.screening.offensive.pit_evidence import (
    PITEvidenceError,
    canonical_flow_fingerprint,
    canonical_price_fingerprint,
)
from src.screening.offensive.setup_data_contracts import SETUP_CONTRACTS, SetupCapability
from src.utils.secure_files import SecureReadError, read_regular_bytes

logger = logging.getLogger(__name__)

MAX_MANIFEST_BYTES = 10 * 1024 * 1024  # 10 MB
MAX_CACHE_FILE_BYTES = 50 * 1024 * 1024  # 50 MB per CSV
NORMALIZATION_VERSION = "pit-canonical-v1"


class SnapshotLoadError(Exception):
    """Raised when a verified snapshot cannot be loaded."""


# ---------------------------------------------------------------------------
# Immutable verified records
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FrozenPriceRow:
    trade_date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal | None
    pct_change: Decimal | None


@dataclass(frozen=True)
class FrozenFlowRow:
    trade_date: date
    close: Decimal | None
    pct_change: Decimal | None
    main_net_inflow: Decimal


@dataclass(frozen=True)
class VerifiedSetupContext:
    """Per-ticker, per-setup context extracted from the verified snapshot."""

    ticker: str
    setup_name: str
    capability: SetupCapability
    prices: tuple[FrozenPriceRow, ...]
    fund_flow_records: tuple[FrozenFlowRow, ...]
    industry_day_pct: float | None
    regime: str
    consumed_fingerprint: str


@dataclass(frozen=True)
class VerifiedDailyActionSnapshot:
    """Immutable, security-hardened PIT snapshot for Daily Action scanning."""

    signal_date: date
    snapshot_id: str
    manifest: DailyActionReadinessManifest
    universe_tickers: tuple[str, ...]
    prices_by_ticker: Mapping[str, tuple[FrozenPriceRow, ...]]
    fund_flow_by_ticker: Mapping[str, tuple[FrozenFlowRow, ...]]
    industry_day_pct_by_ticker: Mapping[str, float]
    regime: str
    board_rule_version: str
    normalization_version: str
    setup_requirements_version: str
    ticker_blocks: Mapping[str, tuple[str, ...]]
    consumed_fingerprint_by_ticker: Mapping[str, Mapping[str, str]]

    @property
    def content_fingerprint(self) -> str:
        return self.manifest.content_fingerprint

    @property
    def input_fingerprint(self) -> str:
        return self.manifest.input_fingerprint

    @property
    def scannable_tickers(self) -> tuple[str, ...]:
        """Tickers with a scannable capability and no verification block."""
        return tuple(
            ticker
            for ticker in self.universe_tickers
            if ticker not in self.ticker_blocks
            and ticker in self.manifest.ticker_readiness
            and any(
                cap.scannable
                for cap in self.manifest.ticker_readiness[ticker].capabilities.values()
            )
        )

    def setup_context(
        self, ticker: str, setup_name: str | None = None
    ) -> VerifiedSetupContext | None:
        """Return verified context for a ticker's setup.

        With ``setup_name`` omitted the first scannable, plan-eligible setup is
        returned. Returns ``None`` when the ticker is blocked, lacks verified
        price rows, or the setup is not plan-eligible.
        """
        if ticker in self.ticker_blocks:
            return None
        if ticker not in self.manifest.ticker_readiness:
            return None
        readiness = self.manifest.ticker_readiness[ticker]
        consumed_for_ticker = self.consumed_fingerprint_by_ticker.get(ticker, {})
        candidate_setups = (
            [setup_name] if setup_name is not None else list(readiness.capabilities)
        )
        prices = self.prices_by_ticker.get(ticker, ())
        if not prices:
            return None
        for name in candidate_setups:
            cap = readiness.capabilities.get(name)
            if cap is None or not cap.scannable:
                continue
            consumed = consumed_for_ticker.get(name)
            if not consumed:
                continue
            return VerifiedSetupContext(
                ticker=ticker,
                setup_name=name,
                capability=cap,
                prices=prices,
                fund_flow_records=self.fund_flow_by_ticker.get(ticker, ()),
                industry_day_pct=self.industry_day_pct_by_ticker.get(ticker),
                regime=self.regime,
                consumed_fingerprint=consumed,
            )
        return None

    def reference_price(self, ticker: str) -> float:
        """Final verified close as float; KeyError when no verified rows exist."""
        rows = self.prices_by_ticker.get(ticker)
        if not rows:
            raise KeyError(ticker)
        return float(rows[-1].close)


@dataclass(frozen=True)
class VerifiedSnapshotResult:
    """Result of loading a verified snapshot.

    snapshot: the verified snapshot if the manifest is valid, healthy, and dated,
        otherwise None.
    global_reason: fail-closed blocking reason when snapshot is None.
    ticker_blocks: per-ticker block reasons (fingerprint mismatch, missing data).
    """

    snapshot: VerifiedDailyActionSnapshot | None
    global_reason: str | None = None
    ticker_blocks: Mapping[str, tuple[str, ...]] = field(
        default_factory=lambda: MappingProxyType({})
    )


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------


def _row_date(value: object) -> date | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    compact = text.replace("-", "")
    if len(compact) >= 8 and compact[:8].isdigit():
        try:
            return datetime.strptime(compact[:8], "%Y%m%d").date()
        except ValueError:
            return None
    try:
        parsed = pd.Timestamp(text)
    except (ValueError, TypeError):
        return None
    if pd.isna(parsed):
        return None
    return parsed.date()


def _decimal_or_none(value: object) -> Decimal | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "nat"}:
        return None
    try:
        parsed = Decimal(text)
    except (InvalidOperation, ValueError):
        return None
    return parsed if parsed.is_finite() else None


def _frozen_price_rows(
    frame: pd.DataFrame, signal_date: date
) -> tuple[FrozenPriceRow, ...]:
    rows: list[FrozenPriceRow] = []
    for record in frame.to_dict(orient="records"):
        row_date = _row_date(record.get("date"))
        if row_date is None or row_date > signal_date:
            continue
        close = _decimal_or_none(record.get("close"))
        if close is None:
            continue
        rows.append(
            FrozenPriceRow(
                trade_date=row_date,
                open=_decimal_or_none(record.get("open")) or close,
                high=_decimal_or_none(record.get("high")) or close,
                low=_decimal_or_none(record.get("low")) or close,
                close=close,
                volume=_decimal_or_none(record.get("volume")),
                pct_change=_decimal_or_none(record.get("pct_change")),
            )
        )
    rows.sort(key=lambda row: row.trade_date)
    return tuple(rows)


def _frozen_flow_rows(
    frame: pd.DataFrame, signal_date: date
) -> tuple[FrozenFlowRow, ...]:
    rows: list[FrozenFlowRow] = []
    for record in frame.to_dict(orient="records"):
        row_date = _row_date(record.get("date"))
        if row_date is None or row_date > signal_date:
            continue
        main_net_inflow = _decimal_or_none(record.get("main_net_inflow"))
        if main_net_inflow is None:
            continue
        rows.append(
            FrozenFlowRow(
                trade_date=row_date,
                close=_decimal_or_none(record.get("close")),
                pct_change=_decimal_or_none(record.get("pct_change")),
                main_net_inflow=main_net_inflow,
            )
        )
    rows.sort(key=lambda row: row.trade_date)
    return tuple(rows)


def _read_csv_frame(path: Path) -> pd.DataFrame | None:
    """Securely read a cache CSV into a string-typed frame, or None if absent."""
    if not path.exists():
        return None
    raw = read_regular_bytes(path, max_bytes=MAX_CACHE_FILE_BYTES)
    if not raw.strip():
        return pd.DataFrame()
    return pd.read_csv(io.BytesIO(raw), dtype=str)


def _extract_regime(regime_row: Mapping[str, object]) -> str:
    for key in ("regime", "regime_label", "label", "state"):
        value = regime_row.get(key)
        if isinstance(value, str) and value:
            return value
    return "normal"


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


def _load_manifest(
    reports_dir: Path, signal_date: date
) -> tuple[DailyActionReadinessManifest | None, str | None]:
    manifest_path = reports_dir / (
        f"daily_action_readiness_{signal_date.strftime('%Y%m%d')}.json"
    )
    if not manifest_path.exists():
        return None, "daily_action_readiness_missing"
    try:
        raw_bytes = read_regular_bytes(manifest_path, max_bytes=MAX_MANIFEST_BYTES)
        manifest_data = json.loads(raw_bytes.decode("utf-8"))
    except (SecureReadError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        logger.warning("snapshot: failed to read manifest %s: %s", manifest_path, exc)
        return None, "readiness_manifest_invalid"
    except FileNotFoundError:
        return None, "daily_action_readiness_missing"
    if not isinstance(manifest_data, Mapping):
        return None, "readiness_manifest_invalid"
    if manifest_data.get("schema_version") != DAILY_ACTION_READINESS_SCHEMA_VERSION:
        return None, "readiness_schema_unsupported"
    try:
        manifest = parse_manifest_v2(manifest_data)
    except (ValueError, TypeError) as exc:
        logger.warning("snapshot: manifest validation failed: %s", exc)
        return None, "readiness_manifest_invalid"
    if manifest.trade_date != signal_date:
        return None, "readiness_date_mismatch"
    if not manifest.is_healthy:
        return None, "readiness_manifest_not_healthy"
    return manifest, None


def load_verified_daily_action_snapshot(
    signal_date: date,
    *,
    reports_dir: Path,
    data_dir: Path,
) -> VerifiedSnapshotResult:
    """Load and verify the immutable Daily Action snapshot for a signal date."""

    reports_dir = Path(reports_dir)
    data_dir = Path(data_dir)

    manifest, global_reason = _load_manifest(reports_dir, signal_date)
    if manifest is None:
        return VerifiedSnapshotResult(snapshot=None, global_reason=global_reason)

    shared = manifest.shared_evidence
    suspension = manifest.suspension_evidence
    price_cache_dir = data_dir / "price_cache"
    fund_flow_dir = data_dir / "fund_flow_cache"

    prices_by_ticker: dict[str, tuple[FrozenPriceRow, ...]] = {}
    fund_flow_by_ticker: dict[str, tuple[FrozenFlowRow, ...]] = {}
    ticker_blocks: dict[str, tuple[str, ...]] = {}
    consumed_by_ticker: dict[str, dict[str, str]] = {}

    for ticker in manifest.universe_tickers:
        readiness = manifest.ticker_readiness.get(ticker)
        block_reasons: list[str] = []
        prices: tuple[FrozenPriceRow, ...] = ()
        flows: tuple[FrozenFlowRow, ...] = ()
        price_fp: str | None = None
        flow_fp: str | None = None

        scannable = readiness is not None and any(
            cap.scannable for cap in readiness.capabilities.values()
        )

        try:
            price_frame = _read_csv_frame(price_cache_dir / f"{ticker}.csv")
        except SecureReadError as exc:
            logger.debug("snapshot: price read failed for %s: %s", ticker, exc)
            block_reasons.append("price_read_failed")
            price_frame = None

        if price_frame is not None and not price_frame.empty:
            prices = _frozen_price_rows(price_frame, signal_date)
            try:
                price_fp = canonical_price_fingerprint(
                    price_frame, ticker, signal_date
                )
            except PITEvidenceError as exc:
                logger.debug("snapshot: price fingerprint failed %s: %s", ticker, exc)
                block_reasons.append("price_evidence_invalid")

        try:
            flow_frame = _read_csv_frame(fund_flow_dir / f"{ticker}.csv")
        except SecureReadError as exc:
            logger.debug("snapshot: flow read failed for %s: %s", ticker, exc)
            flow_frame = None

        if flow_frame is not None and not flow_frame.empty:
            flows = _frozen_flow_rows(flow_frame, signal_date)
            try:
                flow_fp = canonical_flow_fingerprint(flow_frame, ticker, signal_date)
            except PITEvidenceError as exc:
                logger.debug("snapshot: flow fingerprint failed %s: %s", ticker, exc)

        if scannable and not prices:
            block_reasons.append("price_data_missing")

        # Verify every plan-eligible setup's authorized consumed fingerprint.
        verified_setups: dict[str, str] = {}
        if readiness is not None and not block_reasons:
            for setup_name in SETUP_CONTRACTS:
                capability = readiness.capabilities.get(setup_name)
                if capability is None or capability.consumed_fingerprint is None:
                    continue
                recomputed = recompute_setup_consumed_fingerprint(
                    ticker=ticker,
                    setup_name=setup_name,
                    price_fingerprint=price_fp,
                    flow_fingerprint=flow_fp,
                    trade_date=manifest.trade_date,
                    shared_evidence=shared,
                    suspension_evidence=suspension,
                )
                if recomputed != capability.consumed_fingerprint:
                    block_reasons.append("pit_fingerprint_mismatch")
                    break
                verified_setups[setup_name] = recomputed

        prices_by_ticker[ticker] = prices
        fund_flow_by_ticker[ticker] = flows
        if block_reasons:
            # De-duplicate while preserving order.
            ticker_blocks[ticker] = tuple(dict.fromkeys(block_reasons))
        elif verified_setups:
            consumed_by_ticker[ticker] = verified_setups

    all_consumed = sorted(
        fingerprint
        for setups in consumed_by_ticker.values()
        for fingerprint in setups.values()
    )
    snapshot_seed = manifest.content_fingerprint + "\n" + "\n".join(all_consumed)
    snapshot_id = "sha256:" + hashlib.sha256(snapshot_seed.encode("utf-8")).hexdigest()

    industry_day_pct = {
        ticker: float(value)
        for ticker, value in shared.industry_day_pct.items()
    }

    snapshot = VerifiedDailyActionSnapshot(
        signal_date=signal_date,
        snapshot_id=snapshot_id,
        manifest=manifest,
        universe_tickers=tuple(manifest.universe_tickers),
        prices_by_ticker=MappingProxyType(prices_by_ticker),
        fund_flow_by_ticker=MappingProxyType(fund_flow_by_ticker),
        industry_day_pct_by_ticker=MappingProxyType(industry_day_pct),
        regime=_extract_regime(shared.regime_row),
        board_rule_version=shared.board_rule_version,
        normalization_version=shared.normalization_version,
        setup_requirements_version=manifest.policy_versions.get(
            "setup_requirements", ""
        ),
        ticker_blocks=MappingProxyType(dict(ticker_blocks)),
        consumed_fingerprint_by_ticker=MappingProxyType(
            {t: MappingProxyType(dict(s)) for t, s in consumed_by_ticker.items()}
        ),
    )

    return VerifiedSnapshotResult(
        snapshot=snapshot,
        ticker_blocks=MappingProxyType(dict(ticker_blocks)),
    )
