"""Auditable legacy cohort construction for fixed exit-shadow research.

The legacy journal is sensitivity evidence, not a production-readiness gate.  This
module therefore keeps every eligibility layer explicit and never edits either the
backtest journal or the price cache used to reconstruct trade paths.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import pandas as pd

from src.screening.offensive.execution_adjuster import is_limit_up_unbuyable_next_day
from src.tools.ashare_board_utils import limit_up_pct_for_ticker


_BTST_SETUP = "btst_breakout"
_LEGACY_LIMIT_UP_PCT = 9.5
_REALIZED_RE = re.compile(r"(?:^|[;\s])realized=([+-]?\d+(?:\.\d+)?)%")
_RETURN_ROUNDING_TOLERANCE = 0.00015
_REQUIRED_PRICE_COLUMNS = frozenset({"date", "open", "high", "low", "close"})

PriceLoader = Callable[[str], pd.DataFrame | None]
NaturalKey = tuple[str, str, str]


@dataclass(frozen=True)
class LegacySession:
    """One post-signal trading session in a reconstructable legacy path."""

    date: str
    open: float
    high: float
    low: float
    close: float


@dataclass(frozen=True)
class LegacyTradePath:
    """A paired BTST trade with one common, complete ten-session price path."""

    trade_id: str
    signal_date: str
    ticker: str
    setup: str
    regime: str
    source: str
    entry_price: float
    sessions: tuple[LegacySession, ...]
    recorded_return: float
    reconstructed_legacy_return: float
    recorded_return_mismatch: bool
    current_board_rule_mismatch: bool
    board_rule_auditable: bool
    execution_proxy_eligible: bool = True


@dataclass(frozen=True)
class CohortExclusion:
    """An excluded natural key (or physical line) and its exact fail-closed reason."""

    key: str
    reason: str
    recorded_return: float | None = None


@dataclass(frozen=True)
class CoverageAudit:
    """Layer counts, missingness sensitivity, and immutable promotion status."""

    total: int
    covered: int
    coverage: float
    covered_legacy_mean: float | None
    missing_legacy_mean: float | None
    selection_bias_warning: bool
    production_eligible: bool = False
    total_journal_rows: int = 0
    malformed_rows: int = 0
    total_paired_btst: int = 0
    price_file_present: int = 0
    signal_date_present: int = 0
    complete_session_10_window: int = 0
    execution_proxy_eligible: int = 0
    current_board_rule_mismatches: int = 0
    board_rule_unauditable: int = 0
    recorded_return_mismatches: int = 0
    paired_by_setup: tuple[tuple[str, int], ...] = ()
    included_by_regime: tuple[tuple[str, int], ...] = ()
    included_by_source: tuple[tuple[str, int], ...] = ()


@dataclass(frozen=True)
class LegacyCohort:
    """Included common paths plus every recorded exclusion and layer audit."""

    included: tuple[LegacyTradePath, ...]
    excluded: tuple[CohortExclusion, ...]
    audit: CoverageAudit


def _finite_returns(values: Iterable[float]) -> tuple[float, ...]:
    result: list[float] = []
    for value in values:
        number = float(value)
        if not math.isfinite(number):
            raise ValueError("legacy returns must be finite")
        result.append(number)
    return tuple(result)


def audit_coverage(
    *,
    covered_legacy_returns: Iterable[float],
    missing_legacy_returns: Iterable[float],
    total: int,
) -> CoverageAudit:
    """Compare covered and missing legacy groups without ever allowing promotion.

    ``total`` is the denominator established by the paired natural-key layer.  A
    mismatch between it and the classified groups is retained as uncovered data,
    rather than shrinking the denominator and overstating coverage.
    """

    covered = _finite_returns(covered_legacy_returns)
    missing = _finite_returns(missing_legacy_returns)
    if total < 0:
        raise ValueError("total must be non-negative")
    if len(covered) + len(missing) > total:
        raise ValueError("covered and missing groups cannot exceed total")

    coverage = len(covered) / total if total else 0.0
    covered_mean = sum(covered) / len(covered) if covered else None
    missing_mean = sum(missing) / len(missing) if missing else None
    unclassified_missing = total - len(covered) - len(missing)
    if missing or unclassified_missing:
        selection_bias_warning = (
            covered_mean is None
            or missing_mean is None
            or not math.isclose(covered_mean, missing_mean, rel_tol=0.0, abs_tol=1e-12)
        )
    else:
        selection_bias_warning = False

    return CoverageAudit(
        total=total,
        covered=len(covered),
        coverage=coverage,
        covered_legacy_mean=covered_mean,
        missing_legacy_mean=missing_mean,
        selection_bias_warning=selection_bias_warning,
        production_eligible=False,
    )


def _key_text(key: NaturalKey) -> str:
    return ":".join(key)


def _parse_recorded_return(record: Mapping[str, Any]) -> float | None:
    match = _REALIZED_RE.search(str(record.get("reasoning") or ""))
    if match is None:
        return None
    value = float(match.group(1)) / 100.0
    return value if math.isfinite(value) else None


def _valid_key(record: Mapping[str, Any]) -> NaturalKey | None:
    date = str(record.get("date") or "").strip().replace("-", "")
    ticker = str(record.get("ticker") or "").strip().split(".", 1)[0]
    setup = str(record.get("setup") or "").strip()
    if len(date) != 8 or not date.isdigit() or not ticker or not setup:
        return None
    return date, ticker, setup


def _default_price_loader(price_cache_dir: Path) -> PriceLoader:
    def load(ticker: str) -> pd.DataFrame | None:
        path = price_cache_dir / f"{ticker}.csv"
        if not path.is_file():
            return None
        try:
            return pd.read_csv(path)
        except (OSError, pd.errors.ParserError, UnicodeError):
            return pd.DataFrame()

    return load


def _normalize_prices(value: object) -> pd.DataFrame | None:
    if not isinstance(value, pd.DataFrame) or not _REQUIRED_PRICE_COLUMNS.issubset(value.columns):
        return None
    if value.empty:
        return None

    prices = value.copy()
    parsed_dates = pd.to_datetime(prices["date"], errors="coerce")
    if parsed_dates.isna().any():
        return None
    prices["date"] = parsed_dates
    prices = prices.sort_values("date", kind="stable").reset_index(drop=True)
    if prices["date"].duplicated().any():
        return None

    for column in ("open", "high", "low", "close"):
        prices[column] = pd.to_numeric(prices[column], errors="coerce")
        if prices[column].isna().any():
            return None
        if not prices[column].map(lambda item: math.isfinite(float(item)) and float(item) > 0).all():
            return None
    return prices


def _signal_pct_change(prices: pd.DataFrame, signal_idx: int) -> float | None:
    if "pct_change" in prices.columns:
        try:
            value = float(prices.iloc[signal_idx]["pct_change"])
        except (TypeError, ValueError):
            value = math.nan
        if math.isfinite(value):
            return value
    if signal_idx == 0:
        return None
    previous_close = float(prices.iloc[signal_idx - 1]["close"])
    signal_close = float(prices.iloc[signal_idx]["close"])
    return (signal_close / previous_close - 1.0) * 100.0


def _build_sessions(prices: pd.DataFrame, signal_idx: int) -> tuple[LegacySession, ...]:
    rows = prices.iloc[signal_idx + 1 : signal_idx + 11]
    return tuple(
        LegacySession(
            date=pd.Timestamp(row["date"]).strftime("%Y%m%d"),
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
        )
        for _, row in rows.iterrows()
    )


def _positive_entry_price(buy: Mapping[str, Any], fallback: float) -> float:
    try:
        candidate = float(buy.get("entry_price"))
    except (TypeError, ValueError):
        return fallback
    return candidate if math.isfinite(candidate) and candidate > 0 else fallback


def build_legacy_cohort(
    journal_path: Path | str,
    *,
    price_loader: PriceLoader | None = None,
    price_cache_dir: Path | str = Path("data/price_cache"),
    regimes_by_date: Mapping[str, str] | None = None,
    source: str = "paper_trading_backtest",
) -> LegacyCohort:
    """Build the deterministic paired-BTST common cohort from a legacy journal.

    Natural keys are ``(signal_date, ticker, setup)``.  Duplicate, malformed,
    unmatched, or incomplete evidence fails closed and is preserved in
    ``excluded`` with one exact reason.  Current board-detector mismatches remain
    in the included legacy sensitivity cohort and are exposed as booleans.
    """

    path = Path(journal_path)
    if price_loader is None:
        price_loader = _default_price_loader(Path(price_cache_dir))
    regimes = regimes_by_date or {}

    excluded: list[CohortExclusion] = []
    grouped: dict[NaturalKey, dict[str, list[Mapping[str, Any]]]] = defaultdict(
        lambda: {"BUY": [], "EXIT": []}
    )
    physical_rows = 0
    malformed_rows = 0
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        lines = []

    for line_number, raw_line in enumerate(lines, start=1):
        if not raw_line.strip():
            continue
        physical_rows += 1
        try:
            record = json.loads(raw_line)
        except json.JSONDecodeError:
            malformed_rows += 1
            excluded.append(CohortExclusion(f"line:{line_number}", "malformed_json"))
            continue
        if not isinstance(record, dict):
            malformed_rows += 1
            excluded.append(CohortExclusion(f"line:{line_number}", "malformed_record"))
            continue

        key = _valid_key(record)
        action = str(record.get("action") or "").strip().upper()
        if key is None:
            malformed_rows += 1
            excluded.append(CohortExclusion(f"line:{line_number}", "malformed_natural_key"))
            continue
        if key[2] != _BTST_SETUP or action not in {"BUY", "EXIT"}:
            continue
        grouped[key][action].append(record)

    paired: list[tuple[NaturalKey, Mapping[str, Any], Mapping[str, Any], float]] = []
    paired_key_count = 0
    for key in sorted(grouped):
        buys = grouped[key]["BUY"]
        exits = grouped[key]["EXIT"]
        key_string = _key_text(key)
        if len(buys) > 1:
            excluded.append(CohortExclusion(key_string, "duplicate_buy"))
            continue
        if len(exits) > 1:
            excluded.append(CohortExclusion(key_string, "duplicate_exit"))
            continue
        if not buys:
            recorded = _parse_recorded_return(exits[0]) if exits else None
            excluded.append(CohortExclusion(key_string, "unmatched_buy", recorded))
            continue
        if not exits:
            excluded.append(CohortExclusion(key_string, "unmatched_exit"))
            continue
        paired_key_count += 1
        recorded = _parse_recorded_return(exits[0])
        if recorded is None:
            excluded.append(CohortExclusion(key_string, "invalid_recorded_return"))
            continue
        paired.append((key, buys[0], exits[0], recorded))

    counts = Counter[str]()
    included: list[LegacyTradePath] = []
    missing_returns: list[float] = []
    for key, buy, _exit, recorded in paired:
        signal_date, ticker, setup = key
        key_string = _key_text(key)
        try:
            raw_prices = price_loader(ticker)
        except Exception:
            raw_prices = None
        if raw_prices is None or (isinstance(raw_prices, pd.DataFrame) and raw_prices.empty):
            excluded.append(CohortExclusion(key_string, "price_file_missing", recorded))
            missing_returns.append(recorded)
            continue
        counts["price_file_present"] += 1
        prices = _normalize_prices(raw_prices)
        if prices is None:
            excluded.append(CohortExclusion(key_string, "invalid_price_data", recorded))
            missing_returns.append(recorded)
            continue

        normalized_dates = prices["date"].dt.strftime("%Y%m%d")
        matches = normalized_dates.index[normalized_dates == signal_date].tolist()
        if len(matches) != 1:
            excluded.append(CohortExclusion(key_string, "signal_date_missing", recorded))
            missing_returns.append(recorded)
            continue
        counts["signal_date_present"] += 1
        signal_idx = int(matches[0])
        if signal_idx + 10 >= len(prices):
            excluded.append(CohortExclusion(key_string, "incomplete_session_10_window", recorded))
            missing_returns.append(recorded)
            continue
        counts["complete_session_10_window"] += 1

        signal_pct = _signal_pct_change(prices, signal_idx)
        board_rule_auditable = signal_pct is not None
        current_board_rule_mismatch = bool(
            signal_pct is not None and signal_pct < limit_up_pct_for_ticker(ticker)
        )
        if signal_pct is not None:
            if "pct_change" not in prices.columns:
                prices["pct_change"] = 0.0
            prices.at[signal_idx, "pct_change"] = signal_pct
        if is_limit_up_unbuyable_next_day(prices, signal_idx, ticker):
            excluded.append(CohortExclusion(key_string, "execution_proxy_ineligible", recorded))
            missing_returns.append(recorded)
            continue
        counts["execution_proxy_eligible"] += 1

        sessions = _build_sessions(prices, signal_idx)
        entry_price = _positive_entry_price(buy, sessions[0].open)
        reconstructed = sessions[9].close / entry_price - 1.0
        mismatch = not math.isclose(
            reconstructed,
            recorded,
            rel_tol=0.0,
            abs_tol=_RETURN_ROUNDING_TOLERANCE,
        )
        included.append(
            LegacyTradePath(
                trade_id=key_string,
                signal_date=signal_date,
                ticker=ticker,
                setup=setup,
                regime=str(regimes.get(signal_date) or "unknown"),
                source=str(source or "unknown"),
                entry_price=entry_price,
                sessions=sessions,
                recorded_return=recorded,
                reconstructed_legacy_return=round(reconstructed, 12),
                recorded_return_mismatch=mismatch,
                current_board_rule_mismatch=current_board_rule_mismatch,
                board_rule_auditable=board_rule_auditable,
            )
        )

    covered_returns = [trade.recorded_return for trade in included]
    base_audit = audit_coverage(
        covered_legacy_returns=covered_returns,
        missing_legacy_returns=missing_returns,
        total=paired_key_count,
    )
    included_regimes = Counter(trade.regime for trade in included)
    included_sources = Counter(trade.source for trade in included)
    audit = replace(
        base_audit,
        total_journal_rows=physical_rows,
        malformed_rows=malformed_rows,
        total_paired_btst=paired_key_count,
        price_file_present=counts["price_file_present"],
        signal_date_present=counts["signal_date_present"],
        complete_session_10_window=counts["complete_session_10_window"],
        execution_proxy_eligible=counts["execution_proxy_eligible"],
        current_board_rule_mismatches=sum(trade.current_board_rule_mismatch for trade in included),
        board_rule_unauditable=sum(not trade.board_rule_auditable for trade in included),
        recorded_return_mismatches=sum(trade.recorded_return_mismatch for trade in included),
        paired_by_setup=((_BTST_SETUP, paired_key_count),) if paired_key_count else (),
        included_by_regime=tuple(sorted(included_regimes.items())),
        included_by_source=tuple(sorted(included_sources.items())),
    )
    return LegacyCohort(
        included=tuple(included),
        excluded=tuple(excluded),
        audit=audit,
    )


__all__ = [
    "CohortExclusion",
    "CoverageAudit",
    "LegacyCohort",
    "LegacySession",
    "LegacyTradePath",
    "audit_coverage",
    "build_legacy_cohort",
]
