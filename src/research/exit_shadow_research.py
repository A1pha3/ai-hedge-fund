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
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from src.screening.offensive.execution_adjuster import is_limit_up_unbuyable_next_day
from src.tools.ashare_board_utils import limit_up_pct_for_ticker


_BTST_SETUP = "btst_breakout"
_LEGACY_LIMIT_UP_PCT = 9.5
_REALIZED_RE = re.compile(r"(?:^|[;\s])realized=([+-]?\d+(?:\.\d+)?)%")
_RETURN_ROUNDING_TOLERANCE = 0.00005
_FLOAT_COMPARISON_EPSILON = 1e-12
_REQUIRED_PRICE_COLUMNS = frozenset({"date", "open", "high", "low", "close"})

PriceLoader = Callable[[str], object]
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
    buy_line_number: int
    exit_line_number: int
    recorded_entry_price: float | None
    replay_entry_price: float
    sessions: tuple[LegacySession, ...]
    recorded_return: float
    reconstructed_legacy_return: float | None
    recorded_return_mismatch: bool | None
    current_board_rule_mismatch: bool
    board_rule_auditable: bool
    execution_proxy_eligible: bool = True


@dataclass(frozen=True)
class CohortExclusion:
    """An excluded natural key (or physical line) and its exact fail-closed reason."""

    key: str
    reason: str
    recorded_return: float | None = None
    line_numbers: tuple[int, ...] = ()


@dataclass(frozen=True)
class _JournalEvent:
    line_number: int
    record: Mapping[str, Any]


@dataclass(frozen=True)
class _UnreadablePriceData:
    """Internal marker: a cache file exists but could not be decoded or parsed."""


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
    recorded_return_unauditable: int = 0
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
    date = str(record.get("date") or "")
    ticker = str(record.get("ticker") or "")
    setup = str(record.get("setup") or "").strip()
    if (
        re.fullmatch(r"[0-9]{8}", date) is None
        or re.fullmatch(r"[0-9]{6}", ticker) is None
        or not setup
    ):
        return None
    try:
        parsed = datetime.strptime(date, "%Y%m%d")
    except ValueError:
        return None
    if parsed.strftime("%Y%m%d") != date:
        return None
    return date, ticker, setup


def _compatible_btst_holding_period(record: Mapping[str, Any]) -> bool:
    for field in ("horizon", "holding_period", "holding_sessions"):
        if field in record and (type(record[field]) is not int or record[field] != 10):
            return False
    if "time_exit" in record and record["time_exit"] != "T+10":
        return False
    return True


def _default_price_loader(price_cache_dir: Path) -> PriceLoader:
    def load(ticker: str) -> object:
        path = price_cache_dir / f"{ticker}.csv"
        if not path.is_file():
            return None
        try:
            return pd.read_csv(path)
        except (OSError, pd.errors.ParserError, UnicodeError):
            return _UnreadablePriceData()

    return load


def _parse_price_civil_date(raw_date: object) -> pd.Timestamp | None:
    if raw_date is None or isinstance(raw_date, bool):
        return None
    if isinstance(raw_date, datetime):
        if pd.isna(raw_date):
            return None
        return pd.Timestamp(raw_date.date())
    if isinstance(raw_date, date):
        return pd.Timestamp(raw_date)
    if not isinstance(raw_date, str):
        return None

    try:
        if re.fullmatch(r"[0-9]{8}", raw_date):
            parsed = datetime.strptime(raw_date, "%Y%m%d")
        elif re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", raw_date):
            parsed = datetime.strptime(raw_date, "%Y-%m-%d")
        elif re.fullmatch(
            r"[0-9]{4}-[0-9]{2}-[0-9]{2}[ T][0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?",
            raw_date,
        ):
            parsed = datetime.fromisoformat(raw_date)
        else:
            return None
    except (TypeError, ValueError, OverflowError):
        return None
    return pd.Timestamp(parsed.date())


def _normalize_prices(value: object) -> tuple[pd.DataFrame | None, str | None]:
    if not isinstance(value, pd.DataFrame):
        return None, "invalid_price_data"
    if value.empty:
        return None, "empty_price_data"
    if not _REQUIRED_PRICE_COLUMNS.issubset(value.columns):
        return None, "invalid_price_data"

    prices = value.copy()
    civil_dates: list[pd.Timestamp] = []
    for raw_date in prices["date"]:
        civil_date = _parse_price_civil_date(raw_date)
        if civil_date is None:
            return None, "price_data_invalid"
        civil_dates.append(civil_date)
    prices["date"] = civil_dates
    if prices["date"].duplicated().any():
        return None, "duplicate_session_date"
    prices = prices.sort_values("date", kind="stable").reset_index(drop=True)

    for column in ("open", "high", "low", "close"):
        prices[column] = pd.to_numeric(prices[column], errors="coerce")
        if prices[column].isna().any():
            return None, "invalid_price_data"
        if (
            not prices[column]
            .map(lambda item: math.isfinite(float(item)) and float(item) > 0)
            .all()
        ):
            return None, "invalid_price_data"
    valid_bars = (
        (prices["high"] >= prices["low"])
        & (prices["low"] <= prices[["open", "close"]].min(axis=1))
        & (prices[["open", "close"]].max(axis=1) <= prices["high"])
    )
    if not valid_bars.all():
        return None, "invalid_ohlc_bar"
    return prices, None


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


def _recorded_entry_price(buy: Mapping[str, Any]) -> float | None:
    raw_entry_price = buy.get("entry_price")
    if isinstance(raw_entry_price, bool) or not isinstance(
        raw_entry_price, (int, float)
    ):
        return None
    candidate = float(raw_entry_price)
    return candidate if math.isfinite(candidate) and candidate > 0 else None


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
    grouped: dict[NaturalKey, dict[str, list[_JournalEvent]]] = defaultdict(
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
            excluded.append(
                CohortExclusion(
                    f"line:{line_number}", "malformed_json", line_numbers=(line_number,)
                )
            )
            continue
        if not isinstance(record, dict):
            malformed_rows += 1
            excluded.append(
                CohortExclusion(
                    f"line:{line_number}",
                    "malformed_record",
                    line_numbers=(line_number,),
                )
            )
            continue

        key = _valid_key(record)
        action = record.get("action")
        if key is None:
            malformed_rows += 1
            excluded.append(
                CohortExclusion(
                    f"line:{line_number}",
                    "malformed_natural_key",
                    line_numbers=(line_number,),
                )
            )
            continue
        if key[2] != _BTST_SETUP:
            continue
        if action not in {"BUY", "EXIT"}:
            malformed_rows += 1
            excluded.append(
                CohortExclusion(
                    f"line:{line_number}",
                    "unknown_btst_action",
                    line_numbers=(line_number,),
                )
            )
            continue
        grouped[key][action].append(_JournalEvent(line_number, record))

    paired: list[tuple[NaturalKey, _JournalEvent, _JournalEvent, float]] = []
    paired_key_count = 0
    pre_price_missing_returns: list[float] = []
    for key in sorted(grouped):
        buys = grouped[key]["BUY"]
        exits = grouped[key]["EXIT"]
        key_string = _key_text(key)
        if len(buys) > 1:
            excluded.append(
                CohortExclusion(
                    key_string,
                    "duplicate_buy",
                    line_numbers=tuple(row.line_number for row in buys),
                )
            )
            continue
        if len(exits) > 1:
            excluded.append(
                CohortExclusion(
                    key_string,
                    "duplicate_exit",
                    line_numbers=tuple(row.line_number for row in exits),
                )
            )
            continue
        if not buys:
            recorded = _parse_recorded_return(exits[0].record) if exits else None
            excluded.append(
                CohortExclusion(
                    key_string,
                    "unmatched_buy",
                    recorded,
                    tuple(row.line_number for row in exits),
                )
            )
            continue
        if not exits:
            excluded.append(
                CohortExclusion(
                    key_string, "unmatched_exit", line_numbers=(buys[0].line_number,)
                )
            )
            continue
        paired_key_count += 1
        buy = buys[0]
        exit_event = exits[0]
        pair_lines = (buy.line_number, exit_event.line_number)
        recorded = _parse_recorded_return(exit_event.record)
        if exit_event.line_number <= buy.line_number:
            excluded.append(
                CohortExclusion(
                    key_string,
                    "exit_not_after_buy",
                    recorded,
                    line_numbers=tuple(sorted(pair_lines)),
                )
            )
            if recorded is not None:
                pre_price_missing_returns.append(recorded)
            continue
        incompatible_events = [
            event
            for event in (buy, exit_event)
            if not _compatible_btst_holding_period(event.record)
        ]
        if incompatible_events:
            malformed_rows += len(incompatible_events)
            excluded.append(
                CohortExclusion(
                    key_string,
                    "incompatible_btst_holding_period",
                    recorded,
                    line_numbers=tuple(
                        event.line_number for event in incompatible_events
                    ),
                )
            )
            if recorded is not None:
                pre_price_missing_returns.append(recorded)
            continue
        if recorded is None:
            excluded.append(
                CohortExclusion(
                    key_string, "invalid_recorded_return", line_numbers=pair_lines
                )
            )
            continue
        paired.append((key, buy, exit_event, recorded))

    counts = Counter[str]()
    included: list[LegacyTradePath] = []
    missing_returns: list[float] = list(pre_price_missing_returns)
    for key, buy_event, exit_event, recorded in paired:
        buy = buy_event.record
        pair_lines = (buy_event.line_number, exit_event.line_number)
        signal_date, ticker, setup = key
        key_string = _key_text(key)
        try:
            raw_prices = price_loader(ticker)
        except Exception:
            excluded.append(
                CohortExclusion(key_string, "price_loader_error", recorded, pair_lines)
            )
            missing_returns.append(recorded)
            continue
        if raw_prices is None:
            excluded.append(
                CohortExclusion(key_string, "price_file_missing", recorded, pair_lines)
            )
            missing_returns.append(recorded)
            continue
        counts["price_file_present"] += 1
        if isinstance(raw_prices, _UnreadablePriceData):
            excluded.append(
                CohortExclusion(
                    key_string, "unreadable_price_data", recorded, pair_lines
                )
            )
            missing_returns.append(recorded)
            continue
        prices, price_error = _normalize_prices(raw_prices)
        if prices is None:
            excluded.append(
                CohortExclusion(
                    key_string,
                    price_error or "invalid_price_data",
                    recorded,
                    pair_lines,
                )
            )
            missing_returns.append(recorded)
            continue

        normalized_dates = prices["date"].dt.strftime("%Y%m%d")
        matches = normalized_dates.index[normalized_dates == signal_date].tolist()
        if len(matches) != 1:
            excluded.append(
                CohortExclusion(key_string, "signal_date_missing", recorded, pair_lines)
            )
            missing_returns.append(recorded)
            continue
        counts["signal_date_present"] += 1
        signal_idx = int(matches[0])
        if signal_idx + 10 >= len(prices):
            excluded.append(
                CohortExclusion(
                    key_string, "incomplete_session_10_window", recorded, pair_lines
                )
            )
            missing_returns.append(recorded)
            continue
        counts["complete_session_10_window"] += 1

        signal_pct = _signal_pct_change(prices, signal_idx)
        board_rule_auditable = signal_pct is not None
        current_board_rule_mismatch = bool(
            signal_pct is not None
            and (signal_pct >= _LEGACY_LIMIT_UP_PCT)
            != (signal_pct >= limit_up_pct_for_ticker(ticker))
        )
        if signal_pct is not None:
            if "pct_change" not in prices.columns:
                prices["pct_change"] = 0.0
            prices.at[signal_idx, "pct_change"] = signal_pct
        if is_limit_up_unbuyable_next_day(prices, signal_idx, ticker):
            excluded.append(
                CohortExclusion(
                    key_string, "execution_proxy_ineligible", recorded, pair_lines
                )
            )
            missing_returns.append(recorded)
            continue
        counts["execution_proxy_eligible"] += 1

        sessions = _build_sessions(prices, signal_idx)
        recorded_entry_price = _recorded_entry_price(buy)
        replay_entry_price = sessions[0].open
        if recorded_entry_price is None:
            reconstructed = None
            mismatch = None
        else:
            reconstructed = sessions[9].close / recorded_entry_price - 1.0
            mismatch = not math.isclose(
                reconstructed,
                recorded,
                rel_tol=0.0,
                abs_tol=_RETURN_ROUNDING_TOLERANCE + _FLOAT_COMPARISON_EPSILON,
            )
        included.append(
            LegacyTradePath(
                trade_id=key_string,
                signal_date=signal_date,
                ticker=ticker,
                setup=setup,
                regime=str(regimes.get(signal_date) or "unknown"),
                source=str(source or "unknown"),
                buy_line_number=buy_event.line_number,
                exit_line_number=exit_event.line_number,
                recorded_entry_price=recorded_entry_price,
                replay_entry_price=replay_entry_price,
                sessions=sessions,
                recorded_return=recorded,
                reconstructed_legacy_return=round(reconstructed, 12)
                if reconstructed is not None
                else None,
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
        current_board_rule_mismatches=sum(
            trade.current_board_rule_mismatch for trade in included
        ),
        board_rule_unauditable=sum(
            not trade.board_rule_auditable for trade in included
        ),
        recorded_return_mismatches=sum(
            trade.recorded_return_mismatch is True for trade in included
        ),
        recorded_return_unauditable=sum(
            trade.recorded_return_mismatch is None for trade in included
        ),
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
