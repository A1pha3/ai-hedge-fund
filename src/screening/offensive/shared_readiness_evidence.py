"""Frozen, exact-date shared evidence for Daily Action readiness."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from types import MappingProxyType
from typing import Callable, Mapping

import pandas as pd

from src.screening.offensive.cache_readiness import DailyActionRefreshResult
from src.screening.offensive.daily_action_readiness import (
    BOARD_RULE_VERSION,
    DAILY_ACTION_REGIMES,
    NORMALIZATION_VERSION,
    ManifestValidationError,
    SharedReadinessEvidence,
)
from src.screening.offensive.readiness_reference import (
    DailyReadinessReferenceSnapshot,
    ReferenceProvenance,
    SECURITY_REFERENCE_SOURCES,
    SW_REFERENCE_SOURCES,
    make_daily_readiness_reference_snapshot as _make_reference_snapshot,
    validate_reference_for_session,
)
from src.utils.date_utils import SIGNAL_SESSION_POLICY_VERSION


def _fingerprint(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def make_daily_readiness_reference_snapshot(**kwargs: object) -> DailyReadinessReferenceSnapshot:
    """Compatibility boundary that normalizes low-level validation failures."""

    try:
        return _make_reference_snapshot(**kwargs)  # type: ignore[arg-type]
    except ValueError as exc:
        raise ManifestValidationError(str(exc)) from exc


@dataclass(frozen=True)
class FrozenSecurityRow:
    ticker: str
    name: str
    list_status: str


@dataclass(frozen=True)
class FrozenSharedReadinessSource:
    """Detached repository inputs captured once at the Auto compute boundary."""

    signal_date: date
    universe_tickers: tuple[str, ...]
    security_rows: tuple[FrozenSecurityRow, ...]
    sw_industry_by_ticker: Mapping[str, str]
    industry_day_pct: Mapping[str, float]
    security_reference: ReferenceProvenance
    sw_reference: ReferenceProvenance
    source_fingerprints: Mapping[str, str]
    source_fingerprint: str

    def __post_init__(self) -> None:
        if type(self.signal_date) is not date:
            raise ManifestValidationError("frozen source signal_date must be exact")
        universe = tuple(sorted(self.universe_tickers))
        if universe != self.universe_tickers or len(set(universe)) != len(universe):
            raise ManifestValidationError("frozen source universe must be canonical")
        if any(len(ticker) != 6 or not ticker.isdigit() for ticker in universe):
            raise ManifestValidationError("frozen source universe is malformed")
        try:
            validate_reference_for_session(
                self.security_reference,
                self.signal_date,
                label="security",
                known_sources=SECURITY_REFERENCE_SOURCES,
            )
            validate_reference_for_session(
                self.sw_reference,
                self.signal_date,
                label="SW",
                known_sources=SW_REFERENCE_SOURCES,
            )
        except ValueError as exc:
            raise ManifestValidationError(str(exc)) from exc

        rows = tuple(self.security_rows)
        if {row.ticker for row in rows} != set(universe) or len(rows) != len(universe):
            raise ManifestValidationError("security rows must exactly cover frozen universe")
        sw = dict(self.sw_industry_by_ticker)
        if set(sw) != set(universe) or any(not value.strip() for value in sw.values()):
            raise ManifestValidationError("SW mapping must exactly cover frozen universe")
        pct = {key: float(value) for key, value in self.industry_day_pct.items()}
        if set(pct) != set(sw.values()) or any(not math.isfinite(v) for v in pct.values()):
            raise ManifestValidationError("industry values must exactly cover frozen industries")

        fingerprints = dict(self.source_fingerprints)
        if set(fingerprints) != {"stock_basic", "sw_industry", "industry_day_pct"}:
            raise ManifestValidationError("frozen source fingerprints are incomplete")
        if fingerprints["stock_basic"] != self.security_reference.source_fingerprint:
            raise ManifestValidationError("security source fingerprint is not bound")
        if fingerprints["sw_industry"] != self.sw_reference.source_fingerprint:
            raise ManifestValidationError("SW source fingerprint is not bound")
        canonical = {
            "signal_date": self.signal_date.isoformat(),
            "universe_tickers": list(universe),
            "security_rows": [
                {"ticker": row.ticker, "name": row.name, "list_status": row.list_status}
                for row in rows
            ],
            "sw_industry_by_ticker": sw,
            "industry_day_pct": pct,
            "security_reference": self.security_reference.to_dict(),
            "sw_reference": self.sw_reference.to_dict(),
            "source_fingerprints": fingerprints,
        }
        if self.source_fingerprint != _fingerprint(canonical):
            raise ManifestValidationError("frozen source fingerprint mismatch")
        object.__setattr__(self, "universe_tickers", universe)
        object.__setattr__(self, "security_rows", rows)
        object.__setattr__(self, "sw_industry_by_ticker", MappingProxyType(sw))
        object.__setattr__(self, "industry_day_pct", MappingProxyType(pct))
        object.__setattr__(self, "source_fingerprints", MappingProxyType(fingerprints))


def _load_exact_industry_pct(
    data_dir: Path, signal_date: date, industries: tuple[str, ...]
) -> dict[str, float]:
    cache_dir = data_dir / "industry_index_cache"
    try:
        codes = json.loads(
            (cache_dir / "_industry_codes.json").read_text(encoding="utf-8")
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ManifestValidationError("industry code evidence unavailable") from exc
    if not isinstance(codes, dict):
        raise ManifestValidationError("industry code evidence malformed")

    wanted = set(industries)
    result: dict[str, float] = {}
    expected_date = signal_date.strftime("%Y%m%d")
    for index_code, industry in codes.items():
        if type(index_code) is not str or type(industry) is not str or industry not in wanted:
            continue
        try:
            frame = pd.read_csv(cache_dir / f"{index_code}.csv", dtype={"trade_date": str})
        except (OSError, UnicodeDecodeError, pd.errors.ParserError):
            continue
        if not {"trade_date", "pct_chg"}.issubset(frame.columns):
            continue
        matching = frame[
            frame["trade_date"].astype(str).str.replace("-", "", regex=False)
            == expected_date
        ]
        if len(matching) != 1:
            continue
        value = matching.iloc[0]["pct_chg"]
        if isinstance(value, bool):
            continue
        try:
            normalized = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(normalized):
            result[industry] = normalized
    return result


def _default_reference_loader() -> object:
    from src.tools.tushare_api import get_daily_readiness_reference_snapshot

    return get_daily_readiness_reference_snapshot()


def _validate_reference_for_signal_date(
    reference: ReferenceProvenance,
    signal_date: date,
    label: str,
) -> None:
    known_sources = (
        SECURITY_REFERENCE_SOURCES if label == "security" else SW_REFERENCE_SOURCES
    )
    try:
        validate_reference_for_session(
            reference,
            signal_date,
            label=label,
            known_sources=known_sources,
        )
    except ValueError as exc:
        raise ManifestValidationError(str(exc)) from exc


def capture_shared_readiness_evidence_source(
    refresh_result: DailyActionRefreshResult,
    *,
    data_dir: Path,
    reference_snapshot_loader: Callable[[], object] | None = None,
    industry_day_pct_loader: Callable[[date, tuple[str, ...]], object] | None = None,
) -> FrozenSharedReadinessSource:
    """Capture and detach every repository source exactly once; never uses network."""

    if type(refresh_result) is not DailyActionRefreshResult:
        raise ManifestValidationError("frozen source requires exact refresh result")
    raw_snapshot = (
        reference_snapshot_loader()
        if reference_snapshot_loader is not None
        else _default_reference_loader()
    )
    if type(raw_snapshot) is not DailyReadinessReferenceSnapshot:
        raise ManifestValidationError("typed dated reference snapshot is required")
    if raw_snapshot.effective_as_of != refresh_result.trade_date:
        raise ManifestValidationError(
            "reference effective_as_of must equal refresh signal date"
        )
    _validate_reference_for_signal_date(
        raw_snapshot.security_reference,
        refresh_result.trade_date,
        "security",
    )
    _validate_reference_for_signal_date(
        raw_snapshot.sw_reference,
        refresh_result.trade_date,
        "SW",
    )
    stock_records = [dict(row) for row in raw_snapshot.stock_basic_rows]
    sw_raw = raw_snapshot.sw_industry_by_ticker

    universe = refresh_result.universe_tickers
    rows_by_ticker: dict[str, FrozenSecurityRow] = {}
    for raw in stock_records:
        if not isinstance(raw, Mapping):
            raise ManifestValidationError("stock_basic evidence malformed")
        code, name, status = raw.get("ts_code"), raw.get("name"), raw.get("list_status")
        if type(code) is not str or type(name) is not str or type(status) is not str:
            raise ManifestValidationError("stock_basic evidence malformed")
        ticker = code.split(".", 1)[0]
        if ticker not in universe:
            continue
        if ticker in rows_by_ticker:
            raise ManifestValidationError("stock_basic ticker identity is duplicated")
        rows_by_ticker[ticker] = FrozenSecurityRow(ticker, name, status)
    if set(rows_by_ticker) != set(universe):
        raise ManifestValidationError("security rows must exactly cover frozen universe")

    sw: dict[str, str] = {}
    for code, raw_industry in sw_raw.items():
        if type(code) is not str or type(raw_industry) is not str:
            raise ManifestValidationError("SW industry evidence malformed")
        ticker = code.split(".", 1)[0]
        industry = raw_industry.strip()
        if ticker in universe and industry:
            if ticker in sw and sw[ticker] != industry:
                raise ManifestValidationError("SW industry identity is ambiguous")
            sw[ticker] = industry
    if set(sw) != set(universe):
        raise ManifestValidationError("SW mapping must exactly cover frozen universe")

    industries = tuple(sorted(set(sw.values())))
    pct_raw = (
        industry_day_pct_loader(refresh_result.trade_date, industries)
        if industry_day_pct_loader
        else _load_exact_industry_pct(Path(data_dir), refresh_result.trade_date, industries)
    )
    if not isinstance(pct_raw, Mapping):
        raise ManifestValidationError("industry day pct evidence malformed")
    pct: dict[str, float] = {}
    for industry in industries:
        value = pct_raw.get(industry)
        if isinstance(value, bool) or type(value) not in (int, float):
            raise ManifestValidationError("industry day pct must exactly cover signal date")
        normalized = float(value)
        if not math.isfinite(normalized):
            raise ManifestValidationError("industry day pct must be finite")
        pct[industry] = normalized

    rows = tuple(rows_by_ticker[ticker] for ticker in universe)
    fingerprints = {
        "stock_basic": raw_snapshot.security_reference.source_fingerprint,
        "sw_industry": raw_snapshot.sw_reference.source_fingerprint,
        "industry_day_pct": _fingerprint(
            {"trade_date": refresh_result.trade_date.isoformat(), "values": pct}
        ),
    }
    canonical = {
        "signal_date": refresh_result.trade_date.isoformat(),
        "universe_tickers": list(universe),
        "security_rows": [row.__dict__ for row in rows],
        "sw_industry_by_ticker": sw,
        "industry_day_pct": pct,
        "security_reference": raw_snapshot.security_reference.to_dict(),
        "sw_reference": raw_snapshot.sw_reference.to_dict(),
        "source_fingerprints": fingerprints,
    }
    return FrozenSharedReadinessSource(
        signal_date=refresh_result.trade_date,
        universe_tickers=universe,
        security_rows=rows,
        sw_industry_by_ticker=sw,
        industry_day_pct=pct,
        security_reference=raw_snapshot.security_reference,
        sw_reference=raw_snapshot.sw_reference,
        source_fingerprints=fingerprints,
        source_fingerprint=_fingerprint(canonical),
    )


def build_shared_readiness_evidence_for_auto(
    refresh_result: DailyActionRefreshResult,
    report_payload: dict,
    *,
    frozen_source: FrozenSharedReadinessSource,
) -> SharedReadinessEvidence:
    """Pure construction from one refresh result, one report, and one frozen source."""

    if type(refresh_result) is not DailyActionRefreshResult:
        raise ManifestValidationError("shared evidence requires exact refresh result")
    if type(frozen_source) is not FrozenSharedReadinessSource:
        raise ManifestValidationError("shared evidence requires exact frozen source")
    if (
        frozen_source.signal_date != refresh_result.trade_date
        or frozen_source.universe_tickers != refresh_result.universe_tickers
    ):
        raise ManifestValidationError("frozen source does not match refresh result")
    expected_date = refresh_result.trade_date.strftime("%Y%m%d")
    if report_payload.get("date") != expected_date:
        raise ManifestValidationError("Auto payload date does not match refresh result")
    market_state = report_payload.get("market_state")
    regime = market_state.get("regime_gate_level") if isinstance(market_state, dict) else None
    if type(regime) is not str or regime not in DAILY_ACTION_REGIMES:
        raise ManifestValidationError("regime evidence is not canonical")

    security: dict[str, str] = {}
    for row in frozen_source.security_rows:
        if row.list_status != "L":
            raise ManifestValidationError("frozen universe contains unlisted security")
        name = row.name.strip().upper()
        security[row.ticker] = "st" if name.startswith(("ST", "*ST", "S*ST", "SST")) else "listed"
    sw = dict(frozen_source.sw_industry_by_ticker)
    pct_by_ticker = {
        ticker: frozen_source.industry_day_pct[industry]
        for ticker, industry in sw.items()
    }
    as_of = refresh_result.trade_date.isoformat()
    regime_row = {"trade_date": as_of, "regime": regime}
    return SharedReadinessEvidence(
        as_of_date=refresh_result.trade_date,
        regime_row=regime_row,
        industry_by_ticker=sw,
        industry_day_pct=pct_by_ticker,
        security_status_by_ticker=security,
        regime_fingerprint=_fingerprint({"as_of_date": as_of, "regime_row": regime_row}),
        industry_fingerprint=_fingerprint(
            {"as_of_date": as_of, "industry_by_ticker": sw, "industry_day_pct": pct_by_ticker}
        ),
        security_fingerprint=_fingerprint(
            {"as_of_date": as_of, "security_status_by_ticker": security}
        ),
        security_reference=frozen_source.security_reference,
        sw_reference=frozen_source.sw_reference,
        frozen_source_fingerprint=frozen_source.source_fingerprint,
        board_rule_version=BOARD_RULE_VERSION,
        normalization_version=NORMALIZATION_VERSION,
        signal_session_policy_version=SIGNAL_SESSION_POLICY_VERSION,
    )
