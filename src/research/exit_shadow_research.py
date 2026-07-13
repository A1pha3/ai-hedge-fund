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
from numbers import Real
from pathlib import Path
from typing import Any

import pandas as pd
import numpy as np

from src.screening.offensive.atr_utils import compute_atr
from src.screening.offensive.execution_adjuster import (
    ExecutionCosts,
    ExecutionStatus,
    FillResult,
    apply_execution_costs,
    classify_open_fill,
    is_limit_up_unbuyable_next_day,
)
from src.screening.offensive.exit_policy import (
    ExitObservation,
    ExitPolicyState,
    evaluate_shadow_exit,
)
from src.tools.ashare_board_utils import limit_up_pct_for_ticker


_BTST_SETUP = "btst_breakout"
_LEGACY_LIMIT_UP_PCT = 9.5
_REALIZED_RE = re.compile(r"(?:^|[;\s])realized=([+-]?\d+(?:\.\d+)?)%")
_RETURN_ROUNDING_TOLERANCE = 0.00005
_FLOAT_COMPARISON_EPSILON = 1e-12
_REQUIRED_PRICE_COLUMNS = frozenset({"date", "open", "high", "low", "close"})
REPLAY_ATR_PERIOD = 14
ATR_METHOD = "Wilder"
MIN_POSITIVE_MFE_COUNT = 10

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
    atr: float | None = None
    volume: float | None = None
    suspended: bool | None = None
    limit_down: float | None = None
    limit_up: float | None = None


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


@dataclass(frozen=True)
class ExitReplayResult:
    """One executable replay leg with raw prices and net economics separated."""

    trade_id: str
    signal_date: str
    ticker: str
    regime: str
    source: str
    entry_date: str
    raw_entry_price: float
    exit_trigger_date: str
    exit_date: str
    raw_exit_price: float
    exit_reason: str
    deferred_exits: tuple[tuple[str, str], ...]
    entry_net_cash_flow: float
    exit_net_cash_flow: float
    net_return: float
    cost_version: str
    holding_sessions: int
    maximum_favorable_excursion: float | None
    trading_session_dates: tuple[str, ...] = ()


@dataclass(frozen=True)
class ReplayArmFailure:
    """One replay arm's structured failure, including every attempted open."""

    reason: str
    deferred_exits: tuple[tuple[str, str], ...] = ()


class ReplayIneligibleError(ValueError):
    """Public replay failure that preserves structured arm audit evidence."""

    def __init__(self, failure: ReplayArmFailure) -> None:
        super().__init__(failure.reason)
        self.failure = failure

    @property
    def reason(self) -> str:
        return self.failure.reason


@dataclass(frozen=True)
class PairedExitExclusion:
    """A common-mask removal with independently auditable arm failures."""

    trade_id: str
    reason: str
    baseline_failure: ReplayArmFailure | None = None
    challenger_failure: ReplayArmFailure | None = None

    @property
    def baseline_reason(self) -> str | None:
        return self.baseline_failure.reason if self.baseline_failure else None

    @property
    def challenger_reason(self) -> str | None:
        return self.challenger_failure.reason if self.challenger_failure else None


@dataclass(frozen=True)
class PairedExitResult:
    """Identically keyed executable baseline and challenger replay rows."""

    baseline: tuple[ExitReplayResult, ...]
    challenger: tuple[ExitReplayResult, ...]
    excluded: tuple[PairedExitExclusion, ...]
    total_paths: int
    common_eligible: int


def _validate_session_calendar(
    values: tuple[str, ...],
    *,
    label: str,
) -> tuple[str, ...]:
    if not isinstance(values, tuple):
        raise ValueError(f"{label} trading-session calendar must be an immutable tuple")
    if not values:
        raise ValueError(f"{label} trading-session calendar must not be empty")
    parsed: list[date] = []
    for value in values:
        try:
            current = datetime.strptime(value, "%Y%m%d")
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"invalid {label} trading-session date: {value!r}"
            ) from exc
        if current.strftime("%Y%m%d") != value:
            raise ValueError(f"invalid {label} trading-session date: {value!r}")
        parsed.append(current.date())
    if any(current <= previous for previous, current in zip(parsed, parsed[1:])):
        raise ValueError(
            f"{label} trading-session calendar must be strictly increasing and unique"
        )
    return values


@dataclass(frozen=True)
class PairedReplayRow:
    """One immutable common-key comparison row used by sensitivity statistics."""

    baseline: ExitReplayResult
    challenger: ExitReplayResult
    legacy_return: float | None = None
    trading_session_dates: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.baseline.trade_id != self.challenger.trade_id:
            raise ValueError("paired replay rows must share one trade_id")
        if self.baseline.signal_date != self.challenger.signal_date:
            raise ValueError("paired replay rows must share one signal_date")
        baseline_dates = _validate_session_calendar(
            self.baseline.trading_session_dates,
            label="baseline",
        )
        challenger_dates = _validate_session_calendar(
            self.challenger.trading_session_dates,
            label="challenger",
        )
        if baseline_dates != challenger_dates:
            raise ValueError("paired replay arm calendars must match exactly")
        if self.trading_session_dates:
            path_dates = _validate_session_calendar(
                self.trading_session_dates,
                label="paired path",
            )
            if path_dates != baseline_dates:
                raise ValueError("paired path calendar must match both replay arms")
        else:
            object.__setattr__(self, "trading_session_dates", baseline_dates)

    @property
    def signal_date(self) -> str:
        return self.baseline.signal_date


@dataclass(frozen=True)
class MovingBlockMeanDifference:
    """Deterministic moving-block distribution over signal-day paired means."""

    block_sessions: int
    draws: int
    seed: int
    signal_day_count: int
    trading_session_count: int
    candidate_block_count: int
    usable_block_count: int
    empty_block_count: int
    sampled_block_counts: tuple[int, ...]
    effective_sample_counts: tuple[int, ...]
    mean_difference: float
    ci_lower: float
    ci_upper: float
    distribution: tuple[float, ...]


@dataclass(frozen=True)
class ExitArmSensitivity:
    """Trade-level sensitivity metrics; no portfolio interpretation is implied."""

    mean_net_return: float
    median_net_return: float
    worst_decile_net_return: float
    downside_decile_mean: float
    mean_holding_sessions: float
    median_holding_sessions: float
    exit_reason_counts: tuple[tuple[str, int], ...]
    mfe_observation_count: int
    positive_mfe_count: int
    mfe_capture_min_count: int
    mfe_capture_mean: float | None
    mean_give_up: float | None
    mfe_is_diagnostic_not_executable: bool = True


@dataclass(frozen=True)
class PairedSensitivityStatistics:
    """Legacy common-mask statistics with an immutable shadow-only gate."""

    trade_count: int
    signal_day_count: int
    nonoverlapping_window_count: int
    mean_difference: float
    median_difference: float
    worst_decile_difference: float
    downside_decile_mean_difference: float
    coverage: float
    covered_group_legacy_mean: float | None
    missing_group_legacy_mean: float | None
    baseline: ExitArmSensitivity
    challenger: ExitArmSensitivity
    block_mean_difference: MovingBlockMeanDifference
    shadow_only: bool = True
    production_eligible: bool = False

    def __post_init__(self) -> None:
        if not self.shadow_only or self.production_eligible:
            raise ValueError("exit sensitivity statistics must remain shadow-only")


def _ineligible(
    reason: str,
    deferred_exits: tuple[tuple[str, str], ...] = (),
) -> ReplayIneligibleError:
    return ReplayIneligibleError(ReplayArmFailure(reason, deferred_exits))


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


def _optional_positive_number(value: object) -> float | None:
    if (
        isinstance(value, bool)
        or not isinstance(value, Real)
        or not math.isfinite(float(value))
        or float(value) <= 0
    ):
        return None
    return float(value)


def _optional_bool(value: object) -> bool | None:
    return bool(value) if isinstance(value, (bool, np.bool_)) else None


def _build_sessions(
    prices: pd.DataFrame,
    signal_idx: int,
    ticker: str,
) -> tuple[LegacySession, ...]:
    sessions: list[LegacySession] = []
    limit_pct = limit_up_pct_for_ticker(ticker) / 100.0
    for row_idx in range(signal_idx + 1, len(prices)):
        row = prices.iloc[row_idx]
        prior_close = _optional_positive_number(prices.iloc[row_idx - 1]["close"])
        explicit_limit_down = (
            _optional_positive_number(row.get("limit_down"))
            if "limit_down" in prices.columns
            else None
        )
        explicit_limit_up = (
            _optional_positive_number(row.get("limit_up"))
            if "limit_up" in prices.columns
            else None
        )
        limit_down = (
            explicit_limit_down
            if "limit_down" in prices.columns
            else prior_close * (1.0 - limit_pct)
            if prior_close is not None
            else None
        )
        limit_up = (
            explicit_limit_up
            if "limit_up" in prices.columns
            else prior_close * (1.0 + limit_pct)
            if prior_close is not None
            else None
        )
        volume = (
            _optional_positive_number(row.get("volume"))
            if "volume" in prices.columns
            else None
        )
        explicit_suspended = (
            _optional_bool(row.get("suspended"))
            if "suspended" in prices.columns
            else None
        )
        suspended = (
            explicit_suspended
            if explicit_suspended is not None
            else False
            if volume is not None
            else None
        )
        atr = compute_atr(prices, period=REPLAY_ATR_PERIOD, at_idx=row_idx + 1)
        sessions.append(
            LegacySession(
                date=pd.Timestamp(row["date"]).strftime("%Y%m%d"),
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                atr=_optional_positive_number(atr),
                volume=volume,
                suspended=suspended,
                limit_down=limit_down,
                limit_up=limit_up,
            )
        )
    return tuple(sessions)


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

        sessions = _build_sessions(prices, signal_idx, ticker)
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


def _plain_date(value: str) -> date:
    try:
        return datetime.strptime(value, "%Y%m%d").date()
    except (TypeError, ValueError) as exc:
        raise _ineligible("invalid_session_date") from exc


def _session_execution_status(session: LegacySession) -> ExecutionStatus:
    volume = _optional_positive_number(session.volume)
    suspended = (
        True if session.suspended is True else False if volume is not None else None
    )
    return classify_open_fill(
        session.open,
        session.limit_down,
        session.limit_up,
        suspended,
        high=session.high,
        low=session.low,
    )


def _validate_replay_path(path: LegacyTradePath) -> None:
    if len(path.sessions) < 10:
        raise _ineligible("incomplete_session_10_window")
    dates = tuple(_plain_date(session.date) for session in path.sessions)
    if any(current <= previous for previous, current in zip(dates, dates[1:])):
        raise _ineligible("nonincreasing_session_dates")
    for session in path.sessions[:9]:
        if _optional_positive_number(session.atr) is None:
            raise _ineligible("causal_atr_unavailable")
    entry = path.sessions[0]
    entry_status = _session_execution_status(entry)
    if entry_status is ExecutionStatus.UNKNOWN_QUEUE:
        raise _ineligible("entry_unknown_queue")
    if entry_status is ExecutionStatus.UNEXECUTABLE_PROXY:
        raise _ineligible("entry_unexecutable_proxy")


def _entry_fill(
    path: LegacyTradePath,
    costs: ExecutionCosts,
) -> tuple[FillResult, date]:
    _validate_replay_path(path)
    entry_session = path.sessions[0]
    entry_date = _plain_date(entry_session.date)
    return (
        apply_execution_costs(entry_session.open, 1, "buy", costs),
        entry_date,
    )


def _find_executable_exit(
    path: LegacyTradePath,
    *,
    scheduled_index: int,
) -> tuple[LegacySession, tuple[tuple[str, str], ...]]:
    deferred: list[tuple[str, str]] = []
    for session in path.sessions[scheduled_index:]:
        status = _session_execution_status(session)
        if status is ExecutionStatus.EXECUTABLE_PROXY:
            return session, tuple(deferred)
        reason = (
            "unknown_queue"
            if status is ExecutionStatus.UNKNOWN_QUEUE
            else "unexecutable_proxy"
        )
        deferred.append((session.date, reason))
    raise _ineligible("exit_path_exhausted", tuple(deferred))


def _replay_result(
    path: LegacyTradePath,
    *,
    trigger_index: int,
    reason: str,
    costs: ExecutionCosts,
    entry_fill: FillResult,
    entry_date: date,
) -> ExitReplayResult:
    scheduled_index = trigger_index + 1
    if scheduled_index >= len(path.sessions):
        raise _ineligible("exit_path_exhausted")
    exit_session, deferred = _find_executable_exit(
        path,
        scheduled_index=scheduled_index,
    )
    exit_date = _plain_date(exit_session.date)
    exit_index = next(
        index for index, session in enumerate(path.sessions) if session is exit_session
    )
    exit_fill = apply_execution_costs(
        exit_session.open,
        1,
        "sell",
        costs,
        entry_date=entry_date,
        exit_date=exit_date,
    )
    net_return = exit_fill.net_cash_flow / -entry_fill.net_cash_flow - 1.0
    pre_exit_highs = tuple(
        float(session.high)
        for session in path.sessions[:exit_index]
        if isinstance(session.high, Real)
        and not isinstance(session.high, bool)
        and math.isfinite(float(session.high))
    )
    exit_open = _optional_positive_number(exit_session.open)
    maximum_favorable_excursion = (
        max((*pre_exit_highs, exit_open)) / entry_fill.raw_fill_price - 1.0
        if len(pre_exit_highs) == exit_index and exit_open is not None
        else None
    )
    return ExitReplayResult(
        trade_id=path.trade_id,
        signal_date=path.signal_date,
        ticker=path.ticker,
        regime=path.regime,
        source=path.source,
        entry_date=path.sessions[0].date,
        raw_entry_price=entry_fill.raw_fill_price,
        exit_trigger_date=path.sessions[trigger_index].date,
        exit_date=exit_session.date,
        raw_exit_price=exit_fill.raw_fill_price,
        exit_reason=reason,
        deferred_exits=deferred,
        entry_net_cash_flow=entry_fill.net_cash_flow,
        exit_net_cash_flow=exit_fill.net_cash_flow,
        net_return=net_return,
        cost_version=entry_fill.cost_version,
        holding_sessions=exit_index + 1,
        maximum_favorable_excursion=maximum_favorable_excursion,
        trading_session_dates=tuple(session.date for session in path.sessions),
    )


def replay_fixed_baseline(
    path: LegacyTradePath,
    *,
    costs: ExecutionCosts,
) -> ExitReplayResult:
    """Replay the executable fixed session-10-open baseline."""

    entry_fill, entry_date = _entry_fill(path, costs)
    trigger_index = 8
    trigger = path.sessions[trigger_index]
    decision = evaluate_shadow_exit(
        ExitPolicyState.unarmed(entry_price=path.sessions[0].open),
        ExitObservation(
            trade_date=_plain_date(trigger.date),
            holding_session=9,
            close=trigger.close,
            atr=float(trigger.atr),
        ),
    )
    if not decision.should_exit_next_open:
        raise _ineligible("baseline_trigger_missing")
    return _replay_result(
        path,
        trigger_index=trigger_index,
        reason=decision.reason,
        costs=costs,
        entry_fill=entry_fill,
        entry_date=entry_date,
    )


def replay_shadow_challenger(
    path: LegacyTradePath,
    *,
    costs: ExecutionCosts,
) -> ExitReplayResult:
    """Replay the fixed challenger using only each completed session close."""

    entry_fill, entry_date = _entry_fill(path, costs)
    state = ExitPolicyState.unarmed(entry_price=path.sessions[0].open)
    for index, session in enumerate(path.sessions[:9]):
        decision = evaluate_shadow_exit(
            state,
            ExitObservation(
                trade_date=_plain_date(session.date),
                holding_session=index + 1,
                close=session.close,
                atr=float(session.atr),
            ),
        )
        state = decision.state
        if decision.should_exit_next_open:
            return _replay_result(
                path,
                trigger_index=index,
                reason=decision.reason,
                costs=costs,
                entry_fill=entry_fill,
                entry_date=entry_date,
            )
    raise _ineligible("challenger_trigger_missing")


def replay_paired(
    paths: Iterable[LegacyTradePath],
    *,
    costs: ExecutionCosts,
) -> PairedExitResult:
    """Replay both arms and retain only their identical executable common mask."""

    baseline: list[ExitReplayResult] = []
    challenger: list[ExitReplayResult] = []
    excluded: list[PairedExitExclusion] = []
    total_paths = 0
    for path in paths:
        total_paths += 1
        try:
            _validate_replay_path(path)
        except ReplayIneligibleError as exc:
            excluded.append(PairedExitExclusion(path.trade_id, exc.reason))
            continue

        baseline_row: ExitReplayResult | None = None
        challenger_row: ExitReplayResult | None = None
        baseline_failure: ReplayArmFailure | None = None
        challenger_failure: ReplayArmFailure | None = None
        try:
            baseline_row = replay_fixed_baseline(path, costs=costs)
        except ReplayIneligibleError as exc:
            baseline_failure = exc.failure
        try:
            challenger_row = replay_shadow_challenger(path, costs=costs)
        except ReplayIneligibleError as exc:
            challenger_failure = exc.failure

        if baseline_row is None or challenger_row is None:
            if baseline_failure and challenger_failure:
                reason = "both_exits_not_executable"
            elif baseline_failure:
                reason = "baseline_exit_not_executable"
            else:
                reason = "challenger_exit_not_executable"
            excluded.append(
                PairedExitExclusion(
                    path.trade_id,
                    reason,
                    baseline_failure,
                    challenger_failure,
                )
            )
            continue
        baseline.append(baseline_row)
        challenger.append(challenger_row)

    return PairedExitResult(
        baseline=tuple(baseline),
        challenger=tuple(challenger),
        excluded=tuple(excluded),
        total_paths=total_paths,
        common_eligible=len(baseline),
    )


def _stat_date(value: str) -> date:
    try:
        parsed = datetime.strptime(value, "%Y%m%d")
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid statistics trading date: {value!r}") from exc
    if parsed.strftime("%Y%m%d") != value:
        raise ValueError(f"invalid statistics trading date: {value!r}")
    return parsed.date()


def _validated_paired_rows(
    rows: Iterable[PairedReplayRow],
) -> tuple[PairedReplayRow, ...]:
    paired = tuple(rows)
    if not paired:
        raise ValueError("paired rows must not be empty")
    trade_ids: set[str] = set()
    for row in paired:
        if not isinstance(row, PairedReplayRow):
            raise TypeError("rows must contain PairedReplayRow values")
        if row.baseline.trade_id in trade_ids:
            raise ValueError("paired rows must have unique trade_ids")
        trade_ids.add(row.baseline.trade_id)
        _stat_date(row.signal_date)
        for session_date in row.trading_session_dates:
            _stat_date(session_date)
        for result in (row.baseline, row.challenger):
            if not math.isfinite(result.net_return):
                raise ValueError("paired net returns must be finite")
            if result.holding_sessions < 1:
                raise ValueError("holding_sessions must be positive")
    return paired


def _signal_day_differences(
    rows: tuple[PairedReplayRow, ...],
) -> dict[str, float]:
    grouped: defaultdict[str, list[float]] = defaultdict(list)
    for row in rows:
        grouped[row.signal_date].append(
            row.challenger.net_return - row.baseline.net_return
        )
    return {
        signal_date: float(np.mean(values)) for signal_date, values in grouped.items()
    }


def moving_block_mean_difference(
    rows: Iterable[PairedReplayRow],
    block_sessions: int = 10,
    draws: int = 10_000,
    seed: int = 0,
) -> MovingBlockMeanDifference:
    """Bootstrap paired mean differences on the supplied real-session calendar.

    Trade differences are first collapsed to one equal-weighted observation per signal
    date.  A block is exactly ``block_sessions`` consecutive entries from the sorted
    union of signal dates and audited session dates carried by the common-mask rows.
    """

    if type(block_sessions) is not int or block_sessions < 10:
        raise ValueError("block_sessions must be an integer of at least 10")
    if type(draws) is not int or draws < 1:
        raise ValueError("draws must be a positive integer")
    if type(seed) is not int:
        raise ValueError("seed must be an integer")
    paired = _validated_paired_rows(rows)
    signal_means = _signal_day_differences(paired)
    if len(signal_means) < 2:
        raise ValueError("at least two unique signal days are required")

    calendar = sorted(
        {row.signal_date for row in paired}.union(
            *(set(row.trading_session_dates) for row in paired)
        )
    )
    if len(calendar) < block_sessions:
        raise ValueError("real trading-session calendar is shorter than one block")

    blocks: list[tuple[float, ...]] = []
    candidate_count = len(calendar) - block_sessions + 1
    for start_index in range(candidate_count):
        window = calendar[start_index : start_index + block_sessions]
        values = [
            signal_means[session_date]
            for session_date in window
            if session_date in signal_means
        ]
        if values:
            blocks.append(tuple(values))
    empty_count = candidate_count - len(blocks)
    if len(blocks) < 2:
        raise ValueError("fewer than two non-empty moving blocks are available")

    generator = np.random.default_rng(seed)
    target_count = len(signal_means)
    distribution: list[float] = []
    sampled_block_counts: list[int] = []
    effective_sample_counts: list[int] = []
    for _ in range(draws):
        sampled_values: list[float] = []
        block_count = 0
        while len(sampled_values) < target_count:
            block_index = int(generator.integers(0, len(blocks)))
            sampled_values.extend(blocks[block_index])
            block_count += 1
        effective_values = sampled_values[:target_count]
        distribution.append(float(np.mean(effective_values)))
        sampled_block_counts.append(block_count)
        effective_sample_counts.append(len(effective_values))
    distribution_array = np.asarray(distribution, dtype=float)
    observed_mean = float(np.mean(tuple(signal_means.values())))
    ci_lower, ci_upper = np.quantile(distribution_array, (0.025, 0.975))
    return MovingBlockMeanDifference(
        block_sessions=block_sessions,
        draws=draws,
        seed=seed,
        signal_day_count=len(signal_means),
        trading_session_count=len(calendar),
        candidate_block_count=candidate_count,
        usable_block_count=len(blocks),
        empty_block_count=empty_count,
        sampled_block_counts=tuple(sampled_block_counts),
        effective_sample_counts=tuple(effective_sample_counts),
        mean_difference=observed_mean,
        ci_lower=float(ci_lower),
        ci_upper=float(ci_upper),
        distribution=tuple(float(value) for value in distribution_array),
    )


def _downside_statistics(values: Iterable[float]) -> tuple[float, float, float, float]:
    array = np.asarray(tuple(values), dtype=float)
    mean = float(np.mean(array))
    median = float(np.median(array))
    decile = float(np.quantile(array, 0.10))
    tail_mean = float(np.mean(array[array <= decile]))
    return mean, median, decile, tail_mean


def _arm_sensitivity(
    results: tuple[ExitReplayResult, ...],
) -> ExitArmSensitivity:
    mean, median, decile, tail_mean = _downside_statistics(
        result.net_return for result in results
    )
    holdings = np.asarray([result.holding_sessions for result in results], dtype=float)
    valid_mfe = [
        (float(result.maximum_favorable_excursion), result.net_return)
        for result in results
        if result.maximum_favorable_excursion is not None
        and math.isfinite(float(result.maximum_favorable_excursion))
    ]
    positive_mfe = [(mfe, net_return) for mfe, net_return in valid_mfe if mfe > 0.0]
    capture_mean = (
        float(np.mean([net_return / mfe for mfe, net_return in positive_mfe]))
        if len(positive_mfe) >= MIN_POSITIVE_MFE_COUNT
        else None
    )
    give_up_mean = (
        float(np.mean([mfe - net_return for mfe, net_return in valid_mfe]))
        if valid_mfe
        else None
    )
    return ExitArmSensitivity(
        mean_net_return=mean,
        median_net_return=median,
        worst_decile_net_return=decile,
        downside_decile_mean=tail_mean,
        mean_holding_sessions=float(np.mean(holdings)),
        median_holding_sessions=float(np.median(holdings)),
        exit_reason_counts=tuple(
            sorted(Counter(r.exit_reason for r in results).items())
        ),
        mfe_observation_count=len(valid_mfe),
        positive_mfe_count=len(positive_mfe),
        mfe_capture_min_count=MIN_POSITIVE_MFE_COUNT,
        mfe_capture_mean=capture_mean,
        mean_give_up=give_up_mean,
    )


def _greedy_nonoverlapping_window_count(
    rows: tuple[PairedReplayRow, ...],
) -> int:
    interval_ends: dict[str, date] = {}
    for row in rows:
        start = _stat_date(row.signal_date)
        end = max(
            _stat_date(row.baseline.exit_date), _stat_date(row.challenger.exit_date)
        )
        if end < start:
            raise ValueError("paired exit date cannot precede signal date")
        interval_ends[row.signal_date] = max(
            interval_ends.get(row.signal_date, end), end
        )
    intervals = [
        (end, _stat_date(signal_date), signal_date)
        for signal_date, end in interval_ends.items()
    ]
    count = 0
    previous_end: date | None = None
    for end, start, _ in sorted(intervals):
        if previous_end is None or start > previous_end:
            count += 1
            previous_end = end
    return count


def summarize_paired_results(
    rows: Iterable[PairedReplayRow],
    *,
    total_trade_count: int | None = None,
    missing_legacy_returns: Iterable[float] = (),
    block_sessions: int = 10,
    draws: int = 10_000,
    seed: int = 0,
) -> PairedSensitivityStatistics:
    """Summarize approved common-mask rows as legacy sensitivity only."""

    paired = _validated_paired_rows(rows)
    total = len(paired) if total_trade_count is None else total_trade_count
    if type(total) is not int or total < len(paired):
        raise ValueError("total_trade_count cannot be smaller than paired trade count")
    missing = _finite_returns(missing_legacy_returns)
    if len(missing) > total - len(paired):
        raise ValueError("missing legacy group exceeds uncovered trade count")
    covered = _finite_returns(
        row.legacy_return for row in paired if row.legacy_return is not None
    )
    differences = tuple(_signal_day_differences(paired).values())
    mean, median, decile, tail_mean = _downside_statistics(differences)
    block = moving_block_mean_difference(
        paired,
        block_sessions=block_sessions,
        draws=draws,
        seed=seed,
    )
    return PairedSensitivityStatistics(
        trade_count=len(paired),
        signal_day_count=len({row.signal_date for row in paired}),
        nonoverlapping_window_count=_greedy_nonoverlapping_window_count(paired),
        mean_difference=mean,
        median_difference=median,
        worst_decile_difference=decile,
        downside_decile_mean_difference=tail_mean,
        coverage=len(paired) / total if total else 0.0,
        covered_group_legacy_mean=float(np.mean(covered)) if covered else None,
        missing_group_legacy_mean=float(np.mean(missing)) if missing else None,
        baseline=_arm_sensitivity(tuple(row.baseline for row in paired)),
        challenger=_arm_sensitivity(tuple(row.challenger for row in paired)),
        block_mean_difference=block,
    )


__all__ = [
    "ATR_METHOD",
    "CohortExclusion",
    "CoverageAudit",
    "LegacyCohort",
    "LegacySession",
    "LegacyTradePath",
    "ExitReplayResult",
    "ExitArmSensitivity",
    "MIN_POSITIVE_MFE_COUNT",
    "MovingBlockMeanDifference",
    "PairedExitExclusion",
    "PairedExitResult",
    "PairedReplayRow",
    "PairedSensitivityStatistics",
    "ReplayArmFailure",
    "ReplayIneligibleError",
    "REPLAY_ATR_PERIOD",
    "audit_coverage",
    "build_legacy_cohort",
    "moving_block_mean_difference",
    "replay_fixed_baseline",
    "replay_paired",
    "replay_shadow_challenger",
    "summarize_paired_results",
]
