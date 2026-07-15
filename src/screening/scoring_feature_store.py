"""Local scoring feature snapshots for Layer B score_batch.

Public provider calls belong in refresh code.  This store reads only local
CSV/JSON snapshots and returns empty inputs when data is missing or malformed.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from threading import RLock
from typing import Any

import pandas as pd
from pydantic import ValidationError

from src.data.models import CompanyNews, FinancialMetrics, InsiderTrade
from src.screening.optional_feature_store import OptionalFeatureStore
from src.screening.scoring_feature_quality import (
    FEATURE_POLICY_TABLE,
    ObservationStatus,
    ticker_set_fingerprint,
)


_PRICE_MIN_REQUIRED_ROWS = 200
_FEATURE_FAMILIES = (
    "price_history",
    "financial_metrics",
    "event_inputs",
    "industry_pe_medians",
    "dragon_tiger_bonus",
    "intraday_short_trade_metrics",
    "daily_fund_flow_metrics",
)


def _ticker6(ticker: str) -> str:
    return str(ticker).split(".")[0].zfill(6)


def _parse_trade_date(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return datetime(value.year, value.month, value.day)
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time())
    raw = str(value).strip()
    if raw.endswith(".0") and raw[:-2].isdigit():
        raw = raw[:-2]
    for fmt in ("%Y%m%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw[:10], fmt)
        except ValueError:
            continue
    return None


def _compact_date(value: Any) -> str:
    parsed = _parse_trade_date(value)
    return parsed.strftime("%Y%m%d") if parsed else str(value)


def _dashed_date(value: Any) -> str:
    parsed = _parse_trade_date(value)
    return parsed.strftime("%Y-%m-%d") if parsed else str(value)


def _is_on_or_before_trade_date(value: Any, trade_date: str) -> bool:
    item_dt = _parse_trade_date(value)
    trade_dt = _parse_trade_date(trade_date)
    return item_dt is not None and trade_dt is not None and item_dt <= trade_dt


def _row_matches_trade_date(value: Any, trade_date: str) -> bool:
    return _compact_date(value) == _compact_date(trade_date)


def _percent_to_ratio(value: Any) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(numeric):
        return None
    return round(numeric / 100.0, 4)


def _canonical_fingerprint(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
        default=str,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _score_component_value(output: object, component: str) -> object:
    if isinstance(output, Mapping):
        return output.get(component)
    return getattr(output, component, None)


def _finite_score_component_payload(value: object) -> object | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value) if math.isfinite(float(value)) else None
    fields = ("direction", "confidence", "completeness")
    if isinstance(value, Mapping):
        values = [value.get(field) for field in fields]
    else:
        values = [getattr(value, field, None) for field in fields]
    if not all(
        not isinstance(item, bool)
        and isinstance(item, (int, float))
        and math.isfinite(float(item))
        for item in values
    ):
        return None
    return {field: float(item) for field, item in zip(fields, values, strict=True)}


def _validate_score_outputs(
    tickers: list[str], score_outputs: Mapping[str, object]
) -> dict[str, dict[str, object]]:
    if not isinstance(score_outputs, Mapping):
        raise ValueError("score output must be a ticker mapping")
    expected_sequence = [str(ticker) for ticker in tickers]
    expected = set(expected_sequence)
    if len(expected) != len(expected_sequence):
        raise ValueError("score output requested ticker set contains duplicates")
    actual = set(score_outputs)
    if any(not isinstance(ticker, str) for ticker in actual) or actual != expected:
        actual_strings = {str(ticker) for ticker in actual}
        missing = sorted(expected - actual_strings)
        extra = sorted(actual_strings - expected)
        raise ValueError(
            f"score output ticker coverage mismatch: missing={missing}, extra={extra}"
        )

    evidence: dict[str, dict[str, object]] = {}
    for family, policy in FEATURE_POLICY_TABLE.items():
        if not policy.required_score_components:
            continue
        family_outputs: dict[str, dict[str, object]] = {}
        for ticker in sorted(expected):
            output = score_outputs[ticker]
            components: dict[str, object] = {}
            for component in policy.required_score_components:
                value = _score_component_value(output, component)
                component_payload = _finite_score_component_payload(value)
                if component_payload is None:
                    raise ValueError(
                        f"score output for {ticker} has missing or nonfinite "
                        f"component {component!r}"
                    )
                components[component] = component_payload
            family_outputs[ticker] = components
        evidence[family] = {
            "score_output_count": len(family_outputs),
            "score_output_tickers_fingerprint": ticker_set_fingerprint(
                sorted(family_outputs)
            ),
            "score_output_fingerprint": _canonical_fingerprint(family_outputs),
            "required_score_components": list(policy.required_score_components),
        }
    return evidence


@dataclass
class _QualityTracker:
    candidate_count: int = 0
    requested: dict[str, set[str]] = field(default_factory=dict)
    loaded: dict[str, set[str]] = field(default_factory=dict)
    malformed: dict[str, int] = field(default_factory=dict)
    rows_loaded: dict[str, list[int]] = field(default_factory=dict)
    sources: dict[str, str] = field(default_factory=dict)
    # New evidence trackers: distinguish authoritative observation (we got an
    # answer from the source, even if empty) from usable (the answer was
    # non-malformed and could feed the scorer), and record fallbacks / failures
    # honestly so build_quality_summary can emit FeatureEvidence.
    observed: dict[str, set[str]] = field(default_factory=dict)
    usable: dict[str, set[str]] = field(default_factory=dict)
    nonempty: dict[str, set[str]] = field(default_factory=dict)
    stale: dict[str, set[str]] = field(default_factory=dict)
    consumption_failed: dict[str, dict[str, str]] = field(default_factory=dict)
    as_of_max: dict[str, str] = field(default_factory=dict)
    lock: Any = field(default_factory=RLock, repr=False)

    def set_candidate_count(self, count: int) -> None:
        with self.lock:
            self.candidate_count = int(count)

    def note_requested(self, family: str, tickers: list[str]) -> None:
        with self.lock:
            self.requested.setdefault(family, set()).update(_ticker6(ticker) for ticker in tickers)

    def note_loaded(self, family: str, ticker: str, *, rows: int | None = None, source: str = "snapshot") -> None:
        with self.lock:
            self.loaded.setdefault(family, set()).add(_ticker6(ticker))
            current_source = self.sources.get(family)
            self.sources[family] = source if current_source in {None, source} else "mixed"
            if rows is not None:
                self.rows_loaded.setdefault(family, []).append(int(rows))

    def note_malformed(self, family: str) -> None:
        with self.lock:
            self.malformed[family] = self.malformed.get(family, 0) + 1

    def note_observed(self, family: str, ticker: str) -> None:
        """Record that ``ticker`` had an authoritative observation for ``family``.

        An observation is authoritative when the local snapshot was reachable
        and parseable — even if it carried zero rows. This is the consumption
        mirror of the producer's SUCCESS/PARTIAL observation.
        """
        with self.lock:
            self.observed.setdefault(family, set()).add(_ticker6(ticker))

    def note_usable(self, family: str, ticker: str) -> None:
        """Record that ``ticker``'s observation for ``family`` was usable for scoring.

        Usable means: snapshot parsed without raising and produced a value the
        scorer could consume (even an empty list for legal-empty families).
        """
        with self.lock:
            self.usable.setdefault(family, set()).add(_ticker6(ticker))

    def note_nonempty(self, family: str, ticker: str) -> None:
        """Record that ``ticker``'s observation for ``family`` was nonempty."""
        with self.lock:
            self.nonempty.setdefault(family, set()).add(_ticker6(ticker))

    def note_stale(self, family: str, ticker: str) -> None:
        """Record that ``ticker`` for ``family`` actually fell back to stale data."""
        with self.lock:
            self.stale.setdefault(family, set()).add(_ticker6(ticker))

    def note_consumption_failure(self, family: str, ticker: str, reason: str) -> None:
        """Record that scoring could not consume ``family`` for ``ticker``.

        ``reason`` is a short stable code (e.g. ``"malformed_snapshot"``,
        ``"missing_snapshot"``).
        """
        with self.lock:
            self.consumption_failed.setdefault(family, {})[_ticker6(ticker)] = reason

    def note_as_of_max(self, family: str, as_of: str) -> None:
        """Record the max date seen in consumed data for ``family``."""
        with self.lock:
            current = self.as_of_max.get(family)
            if current is None or _compact_date(as_of) > _compact_date(current):
                self.as_of_max[family] = _compact_date(as_of)


@dataclass
class ScoringFeatureStore:
    base_dir: Path | str = Path("data/feature_cache")
    price_cache_dir: Path | str = Path("data/price_cache")
    legacy_snapshot_dir: Path | str = Path("data/snapshots")
    lhb_cache_dir: Path | str = Path("data/lhb_cache")
    fund_flow_cache_dir: Path | str = Path("data/fund_flow_cache")
    max_stale_days: int = 0
    allow_stale: bool = False

    def __post_init__(self) -> None:
        self.base_dir = Path(self.base_dir)
        self.price_cache_dir = Path(self.price_cache_dir)
        self.legacy_snapshot_dir = Path(self.legacy_snapshot_dir)
        self.lhb_cache_dir = Path(self.lhb_cache_dir)
        self.fund_flow_cache_dir = Path(self.fund_flow_cache_dir)
        self._optional_store = OptionalFeatureStore(
            base_dir=self.base_dir,
            max_stale_days=self.max_stale_days,
            allow_stale=self.allow_stale,
        )
        self._quality = _QualityTracker()

    def load_price_frame(self, ticker: str, trade_date: str, lookback_days: int = 400) -> pd.DataFrame:
        ticker6 = _ticker6(ticker)
        self._quality.note_requested("price_history", [ticker6])
        path = self.price_cache_dir / f"{ticker6}.csv"
        if not path.exists():
            self._quality.note_consumption_failure(
                "price_history", ticker6, "missing_snapshot"
            )
            return pd.DataFrame()
        try:
            frame = pd.read_csv(path, dtype={"date": str})  # M7: 统一 dtype
        except (OSError, UnicodeDecodeError, ValueError, pd.errors.ParserError, pd.errors.EmptyDataError):
            self._quality.note_malformed("price_history")
            self._quality.note_consumption_failure(
                "price_history", ticker6, "malformed_snapshot"
            )
            return pd.DataFrame()
        if frame.empty or "date" not in frame.columns:
            self._quality.note_consumption_failure(
                "price_history", ticker6, "empty_cache"
            )
            return pd.DataFrame()
        required = {"open", "close", "high", "low", "volume"}
        if not required.issubset(frame.columns):
            self._quality.note_malformed("price_history")
            self._quality.note_consumption_failure(
                "price_history", ticker6, "missing_required_columns"
            )
            return pd.DataFrame()
        # Snapshot was reachable and parseable → authoritative observation.
        self._quality.note_observed("price_history", ticker6)
        normalized = frame.copy()
        normalized["Date"] = pd.to_datetime(normalized["date"], errors="coerce")
        normalized = normalized.dropna(subset=["Date"]).sort_values("Date")
        end_dt = _parse_trade_date(trade_date)
        if end_dt is not None:
            start_dt = end_dt - timedelta(days=int(lookback_days))
            normalized = normalized[(normalized["Date"] <= end_dt) & (normalized["Date"] >= start_dt)]
        for column in ("open", "close", "high", "low", "volume"):
            normalized[column] = pd.to_numeric(normalized[column], errors="coerce")
        normalized = normalized.dropna(subset=["open", "close", "high", "low", "volume"])
        if normalized.empty:
            self._quality.note_consumption_failure(
                "price_history", ticker6, "empty_after_lookback"
            )
            return pd.DataFrame()
        normalized = normalized.set_index("Date")
        self._quality.note_loaded("price_history", ticker6, rows=len(normalized), source="local_price_cache")
        self._quality.note_usable("price_history", ticker6)
        self._quality.note_nonempty("price_history", ticker6)
        # Record the max consumed date and flag staleness if the latest bar is
        # older than the requested trade_date (the scorer asked for trade_date
        # but only got older data).
        latest_date = normalized.index.max()
        as_of = latest_date.strftime("%Y%m%d")
        self._quality.note_as_of_max("price_history", as_of)
        if _compact_date(as_of) != _compact_date(trade_date):
            self._quality.note_stale("price_history", ticker6)
        # Keep the required OHLCV columns plus any optional enrichment columns
        # (amount, turnover_rate, pct_change, ...) so downstream scorers degrade
        # naturally rather than silently losing data the cache may grow.
        keep = ["open", "close", "high", "low", "volume"] + [
            col for col in normalized.columns
            if col not in {"open", "close", "high", "low", "volume", "date", "Date"}
        ]
        return normalized[keep]

    def load_financial_metrics(self, ticker: str, trade_date: str) -> list[FinancialMetrics]:
        ticker6 = _ticker6(ticker)
        self._quality.note_requested("financial_metrics", [ticker6])
        resolved = self._resolve_legacy_snapshot_path(ticker6, trade_date, "financials.json")
        if resolved is None:
            self._quality.note_consumption_failure(
                "financial_metrics", ticker6, "missing_snapshot"
            )
            return []
        path, snapshot_date, stale = resolved
        if stale:
            self._quality.note_stale("financial_metrics", ticker6)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            rows = payload.get("financial_metrics", []) if isinstance(payload, dict) else []
            metrics = [FinancialMetrics.model_validate(row) for row in rows if isinstance(row, dict)]
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValidationError, TypeError):
            self._quality.note_malformed("financial_metrics")
            self._quality.note_consumption_failure(
                "financial_metrics", ticker6, "malformed_snapshot"
            )
            return []
        # Snapshot was reachable and parseable → authoritative observation.
        self._quality.note_observed("financial_metrics", ticker6)
        self._quality.note_as_of_max("financial_metrics", snapshot_date)
        if metrics:
            self._quality.note_loaded("financial_metrics", ticker6, rows=len(metrics), source="snapshot")
            self._quality.note_usable("financial_metrics", ticker6)
            self._quality.note_nonempty("financial_metrics", ticker6)
        else:
            # Empty financial snapshot is a consumption failure for an
            # illegal-empty required family, but the observation itself still
            # happened (the file existed and parsed).
            self._quality.note_consumption_failure(
                "financial_metrics", ticker6, "empty_illegal"
            )
        return metrics

    def load_event_inputs(self, ticker: str, trade_date: str) -> tuple[list[CompanyNews], list[InsiderTrade]]:
        ticker6 = _ticker6(ticker)
        self._quality.note_requested("event_inputs", [ticker6])
        news, news_observed, news_stale, news_snapshot_date = self._load_company_news(ticker6, trade_date)
        trades, trades_observed, trades_stale, trades_snapshot_date = self._load_insider_trades(ticker6, trade_date)
        # event_inputs is observed when at least one of the two sources produced
        # an authoritative answer (snapshot reachable + parseable, even if empty).
        if news_observed or trades_observed:
            self._quality.note_observed("event_inputs", ticker6)
        # The family is usable for scoring when at least one source parsed
        # cleanly — scorers can consume an empty list legally here.
        if news_observed or trades_observed:
            self._quality.note_usable("event_inputs", ticker6)
        if news or trades:
            self._quality.note_loaded("event_inputs", ticker6, rows=len(news) + len(trades), source="snapshot")
            self._quality.note_nonempty("event_inputs", ticker6)
        # Stale flag: honest when either source fell back.
        if news_stale or trades_stale:
            self._quality.note_stale("event_inputs", ticker6)
        for candidate_date in (news_snapshot_date, trades_snapshot_date):
            if candidate_date:
                self._quality.note_as_of_max("event_inputs", candidate_date)
        if not news_observed and not trades_observed:
            self._quality.note_consumption_failure(
                "event_inputs", ticker6, "missing_snapshot"
            )
        return news, trades

    def load_industry_pe_medians(self, trade_date: str) -> dict[str, float]:
        self._quality.note_requested("industry_pe_medians", ["000000"])
        for suffix in ("json", "csv"):
            path = self.base_dir / f"industry_pe_medians_{_compact_date(trade_date)}.{suffix}"
            if not path.exists():
                continue
            if suffix == "json":
                result = self._load_industry_pe_json(path)
            else:
                result = self._load_industry_pe_csv(path)
            # Snapshot file existed and parsed → authoritative observation.
            self._quality.note_observed("industry_pe_medians", "000000")
            self._quality.note_as_of_max("industry_pe_medians", trade_date)
            if result:
                self._quality.note_loaded("industry_pe_medians", "000000", rows=len(result), source="snapshot")
                self._quality.note_usable("industry_pe_medians", "000000")
                self._quality.note_nonempty("industry_pe_medians", "000000")
                return result
            # Empty result is legal for industry_pe (always_legal semantics).
            self._quality.note_usable("industry_pe_medians", "000000")
            return result
        return {}

    def load_dragon_tiger_bonus_map(self, tickers: list[str], trade_date: str) -> dict[str, float]:
        wanted = {_ticker6(ticker) for ticker in tickers}
        self._quality.note_requested("dragon_tiger_bonus", list(wanted))
        path = self.lhb_cache_dir / f"{_compact_date(trade_date)}.csv"
        if not path.exists() or not wanted:
            return {}
        try:
            frame = pd.read_csv(path, dtype={"ts_code": str, "代码": str})
        except (OSError, UnicodeDecodeError, ValueError, pd.errors.ParserError, pd.errors.EmptyDataError):
            self._quality.note_malformed("dragon_tiger_bonus")
            return {}
        # Snapshot file existed and parsed → authoritative observation.
        self._quality.note_as_of_max("dragon_tiger_bonus", trade_date)
        if "trade_date" in frame.columns:
            frame = frame[frame["trade_date"].apply(lambda value: _row_matches_trade_date(value, trade_date))]
        code_column = "ts_code" if "ts_code" in frame.columns else "代码" if "代码" in frame.columns else ""
        if not code_column:
            self._quality.note_malformed("dragon_tiger_bonus")
            return {}
        codes = {_ticker6(code) for code in frame[code_column].dropna().astype(str).tolist()}
        result = {ticker: 1.0 for ticker in sorted(wanted & codes)}
        # The family is "observed" when the snapshot was reachable and parseable.
        # An empty result is a legal observation for dragon_tiger_bonus.
        for ticker in wanted:
            self._quality.note_observed("dragon_tiger_bonus", ticker)
            self._quality.note_usable("dragon_tiger_bonus", ticker)
        for ticker in result:
            self._quality.note_loaded("dragon_tiger_bonus", ticker, source="local_lhb_cache")
            self._quality.note_nonempty("dragon_tiger_bonus", ticker)
        return result

    def load_intraday_metrics(self, trade_date: str, tickers: list[str]) -> dict[str, dict[str, Any]]:
        self._quality.note_requested("intraday_short_trade_metrics", tickers)
        rows = self._optional_store.load_intraday_metrics(trade_date, tickers)
        wanted = {_ticker6(ticker) for ticker in tickers}
        for ticker in wanted:
            # Intraday/fund_flow optional store is always "observed" when called:
            # it returned an answer (possibly empty). We don't have file-level
            # visibility here, so we treat the call itself as the observation.
            self._quality.note_observed("intraday_short_trade_metrics", ticker)
            self._quality.note_usable("intraday_short_trade_metrics", ticker)
        self._quality.note_as_of_max("intraday_short_trade_metrics", trade_date)
        for ticker in rows:
            self._quality.note_loaded("intraday_short_trade_metrics", ticker, source="snapshot")
            self._quality.note_nonempty("intraday_short_trade_metrics", ticker)
        return rows

    def load_fund_flow_metrics(self, trade_date: str, tickers: list[str]) -> dict[str, dict[str, Any]]:
        self._quality.note_requested("daily_fund_flow_metrics", tickers)
        rows = self._optional_store.load_fund_flow_metrics(trade_date, tickers)
        wanted = {_ticker6(ticker) for ticker in tickers}
        for ticker in wanted:
            self._quality.note_observed("daily_fund_flow_metrics", ticker)
            self._quality.note_usable("daily_fund_flow_metrics", ticker)
        self._quality.note_as_of_max("daily_fund_flow_metrics", trade_date)
        for ticker in rows:
            self._quality.note_loaded("daily_fund_flow_metrics", ticker, source="snapshot")
            self._quality.note_nonempty("daily_fund_flow_metrics", ticker)
        missing = sorted(wanted - set(rows))
        legacy_rows = self._load_legacy_fund_flow_metrics(trade_date, missing)
        for ticker in legacy_rows:
            self._quality.note_loaded("daily_fund_flow_metrics", ticker, source="fund_flow_cache")
            self._quality.note_nonempty("daily_fund_flow_metrics", ticker)
        rows.update(legacy_rows)
        return rows

    def build_quality_summary(
        self,
        trade_date: str,
        tickers: list[str],
        score_outputs: Mapping[str, object],
        requested: dict[str, set[str]] | None = None,
    ) -> dict[str, Any]:
        score_output_evidence = _validate_score_outputs(tickers, score_outputs)
        self._quality.set_candidate_count(len({_ticker6(ticker) for ticker in tickers}))
        if requested:
            for family, family_tickers in requested.items():
                self._quality.note_requested(family, list(family_tickers))
        manifest = self._load_manifest(trade_date)
        scoring_features = {
            family: self._quality_for_family(family, trade_date, manifest)
            for family in _FEATURE_FAMILIES
        }
        for family, evidence in score_output_evidence.items():
            scoring_features[family].update(evidence)
        # Backward-compatible optional_features block: derive it from the same
        # tracker so intraday/fund_flow numbers cannot diverge from scoring_features
        # (the legacy optional_store path computed coverage over the full candidate
        # set, which contradicted the actual requested subset recorded here).
        optional_features = {
            family: {
                key: scoring_features[family][key]
                for key in ("coverage", "source", "trade_date", "stale", "provider_failures", "missing_tickers")
                if key in scoring_features[family]
            }
            for family in ("intraday_short_trade_metrics", "daily_fund_flow_metrics")
        }
        return {
            "scoring_features": scoring_features,
            "optional_features": optional_features,
        }

    def _resolve_legacy_snapshot_path(
        self, ticker: str, trade_date: str, filename: str
    ) -> tuple[Path, str, bool] | None:
        """Resolve a legacy snapshot path.

        Returns ``(path, snapshot_date_compact, stale)`` where ``snapshot_date``
        is the actual date of the matched snapshot directory (compact
        ``YYYYMMDD``) and ``stale`` is True only when the match came from the
        stale-fallback search (i.e. no exact-trade-date snapshot existed).
        Returns ``None`` when no candidate snapshot exists.
        """
        exact_dirs = [
            self.legacy_snapshot_dir / ticker / _compact_date(trade_date),
            self.legacy_snapshot_dir / ticker / _dashed_date(trade_date),
        ]
        for directory in exact_dirs:
            path = directory / filename
            if path.exists():
                return path, _compact_date(trade_date), False
        if not self.allow_stale or self.max_stale_days <= 0:
            return None
        requested_dt = _parse_trade_date(trade_date)
        if requested_dt is None:
            return None
        best: tuple[datetime, Path] | None = None
        ticker_dir = self.legacy_snapshot_dir / ticker
        if not ticker_dir.exists():
            return None
        for directory in ticker_dir.iterdir():
            if not directory.is_dir():
                continue
            snapshot_dt = _parse_trade_date(directory.name)
            if snapshot_dt is None:
                continue
            stale_days = (requested_dt - snapshot_dt).days
            if stale_days < 0 or stale_days > self.max_stale_days:
                continue
            path = directory / filename
            if not path.exists():
                continue
            if best is None or snapshot_dt > best[0]:
                best = (snapshot_dt, path)
        if best is None:
            return None
        return best[1], best[0].strftime("%Y%m%d"), True

    def _load_company_news(
        self, ticker: str, trade_date: str
    ) -> tuple[list[CompanyNews], bool, bool, str | None]:
        """Returns ``(news, observed, stale, snapshot_date)``.

        ``observed`` is True when the snapshot was reachable and parseable
        (authoritative answer, even if empty). ``stale`` is True only when the
        snapshot came from the stale-fallback search.
        """
        resolved = self._resolve_legacy_snapshot_path(ticker, trade_date, "company_news.json")
        if resolved is None:
            return [], False, False, None
        path, snapshot_date, stale = resolved
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            rows = payload if isinstance(payload, list) else payload.get("news", []) if isinstance(payload, dict) else []
            news = [CompanyNews.model_validate(row) for row in rows if isinstance(row, dict)]
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValidationError, TypeError):
            self._quality.note_malformed("event_inputs")
            return [], False, stale, snapshot_date
        return (
            [item for item in news if _is_on_or_before_trade_date(item.date, trade_date)],
            True,
            stale,
            snapshot_date,
        )

    def _load_insider_trades(
        self, ticker: str, trade_date: str
    ) -> tuple[list[InsiderTrade], bool, bool, str | None]:
        """Returns ``(trades, observed, stale, snapshot_date)``.

        See :meth:`_load_company_news` for the tuple semantics.
        """
        resolved = self._resolve_legacy_snapshot_path(ticker, trade_date, "insider_trades.json")
        if resolved is None:
            return [], False, False, None
        path, snapshot_date, stale = resolved
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            rows = payload if isinstance(payload, list) else payload.get("insider_trades", []) if isinstance(payload, dict) else []
            trades = [InsiderTrade.model_validate(row) for row in rows if isinstance(row, dict)]
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValidationError, TypeError):
            self._quality.note_malformed("event_inputs")
            return [], False, stale, snapshot_date
        return (
            [item for item in trades if self._insider_trade_is_not_future_dated(item, trade_date)],
            True,
            stale,
            snapshot_date,
        )

    def _insider_trade_is_not_future_dated(self, trade: InsiderTrade, trade_date: str) -> bool:
        dated_fields = [trade.filing_date]
        if trade.transaction_date:
            dated_fields.append(trade.transaction_date)
        return all(_is_on_or_before_trade_date(value, trade_date) for value in dated_fields)

    def _load_legacy_fund_flow_metrics(self, trade_date: str, tickers: list[str]) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for ticker in tickers:
            ticker6 = _ticker6(ticker)
            path = self.fund_flow_cache_dir / f"{ticker6}.csv"
            if not path.exists():
                continue
            try:
                frame = pd.read_csv(path, dtype={"date": str, "ticker": str})
            except (OSError, UnicodeDecodeError, ValueError, pd.errors.ParserError, pd.errors.EmptyDataError):
                self._quality.note_malformed("daily_fund_flow_metrics")
                continue
            if frame.empty or "date" not in frame.columns or "main_net_pct" not in frame.columns:
                continue
            matched = frame[frame["date"].apply(lambda value: _row_matches_trade_date(value, trade_date))]
            if matched.empty:
                continue
            ratio = _percent_to_ratio(matched.iloc[-1]["main_net_pct"])
            if ratio is None:
                continue
            result[ticker6] = {
                "main_flow_ratio": ratio,
                "main_flow_ratio_source": "fund_flow_cache",
            }
        return result

    def _load_industry_pe_json(self, path: Path) -> dict[str, float]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            self._quality.note_malformed("industry_pe_medians")
            return {}
        if not isinstance(payload, dict):
            return {}
        result: dict[str, float] = {}
        for industry, value in payload.items():
            try:
                numeric = float(value)
            except (TypeError, ValueError):
                continue
            if industry and numeric > 0:
                result[str(industry)] = numeric
        return result

    def _load_industry_pe_csv(self, path: Path) -> dict[str, float]:
        try:
            frame = pd.read_csv(path)
        except (OSError, UnicodeDecodeError, ValueError, pd.errors.ParserError, pd.errors.EmptyDataError):
            self._quality.note_malformed("industry_pe_medians")
            return {}
        if not {"industry", "pe_median"}.issubset(frame.columns):
            return {}
        result: dict[str, float] = {}
        for _, row in frame.iterrows():
            try:
                numeric = float(row["pe_median"])
            except (TypeError, ValueError):
                continue
            industry = str(row["industry"])
            if industry and numeric > 0:
                result[industry] = numeric
        return result

    def _load_manifest(self, trade_date: str) -> dict[str, Any]:
        return self._optional_store.load_manifest(_compact_date(trade_date))

    def _quality_for_family(self, family: str, trade_date: str, manifest: dict[str, Any]) -> dict[str, Any]:
        with self._quality.lock:
            requested = set(self._quality.requested.get(family, set()))
            loaded = set(self._quality.loaded.get(family, set()))
            observed = set(self._quality.observed.get(family, set()))
            usable = set(self._quality.usable.get(family, set()))
            nonempty = set(self._quality.nonempty.get(family, set()))
            stale_tickers = set(self._quality.stale.get(family, set()))
            consumption_failed = dict(self._quality.consumption_failed.get(family, {}))
            rows = list(self._quality.rows_loaded.get(family, []))
            live_source = self._quality.sources.get(family)
            candidate_count = int(self._quality.candidate_count)
            malformed_files = int(self._quality.malformed.get(family, 0))
            as_of_max = self._quality.as_of_max.get(family)
        feature_manifest = (manifest.get("features") or {}).get(family, {})
        # Refresh-manifest observation evidence (additive; may be 0 when the
        # refresh did not touch this family — e.g. industry_pe_medians is
        # produced by a different pipeline).
        manifest_observed = int(feature_manifest.get("observed_count", 0) or 0)
        manifest_nonempty = int(feature_manifest.get("nonempty_count", 0) or 0)
        manifest_failed = int(feature_manifest.get("failed_count", 0) or 0)
        manifest_parts_succeeded = int(feature_manifest.get("source_parts_succeeded", 0) or 0)
        manifest_parts_total = int(feature_manifest.get("source_parts_total", 0) or 0)
        provider_failures = int(feature_manifest.get("provider_failures", 0) or 0)

        source = live_source or str(feature_manifest.get("source") or ("snapshot" if loaded else "missing"))

        # Consumption-side authoritative counts (preferred over manifest counts
        # because they reflect what the scorer actually consumed).
        requested_count = len(requested)
        observed_count = len(observed)
        usable_count = len(usable)
        nonempty_count = len(nonempty)
        stale_count = len(stale_tickers)
        consumption_failed_count = len(consumption_failed)

        # Derive observation_status from the consumption-side evidence.
        # Conservation: success requires every requested ticker to have been
        # observed AND usable with no consumption failures.
        if requested_count == 0:
            # No scorer asked for this family during this run.
            observation_status = ObservationStatus.UNAVAILABLE
        elif (
            observed_count == requested_count
            and usable_count == requested_count
            and consumption_failed_count == 0
        ):
            observation_status = ObservationStatus.SUCCESS
        elif observed_count == 0 and usable_count == 0:
            # We tried but got nothing authoritative.
            observation_status = ObservationStatus.FAILED
        else:
            observation_status = ObservationStatus.PARTIAL

        # Ticker fingerprints bind the counts to a specific ticker set.
        requested_fingerprint = (
            ticker_set_fingerprint(sorted(requested)) if requested else None
        )
        observed_fingerprint = (
            ticker_set_fingerprint(sorted(observed)) if observed else None
        )
        usable_fingerprint = (
            ticker_set_fingerprint(sorted(usable)) if usable else None
        )

        quality: dict[str, Any] = {
            # --- Legacy fields (preserved for backward compatibility) ---
            "coverage": round(len(loaded) / len(requested), 4) if requested else 0.0,
            "source": source,
            "trade_date": _compact_date(trade_date),
            "stale": stale_count > 0,
            "candidate_count": candidate_count,
            "eligible_count": candidate_count,
            "requested_count": requested_count,
            "loaded_count": len(loaded),
            "missing_tickers": max(requested_count - len(loaded), 0),
            "provider_failures": provider_failures,
            "malformed_files": malformed_files,
            # --- FeatureEvidence fields (consumed by assess_auto_quality) ---
            "observation_status": observation_status.value,
            "attempted_count": requested_count,
            "observed_count": observed_count,
            "usable_count": usable_count,
            "nonempty_count": nonempty_count,
            "stale_count": stale_count,
            "refresh_failed_count": manifest_failed,
            "consumption_failed_count": consumption_failed_count,
            "requested_tickers_fingerprint": requested_fingerprint,
            "observed_tickers_fingerprint": observed_fingerprint,
            "usable_tickers_fingerprint": usable_fingerprint,
            "as_of_max": as_of_max,
        }
        quality["input_fingerprint"] = _canonical_fingerprint(
            {
                "family": family,
                "trade_date": _compact_date(trade_date),
                "requested_tickers": sorted(requested),
                "observed_tickers": sorted(observed),
                "usable_tickers": sorted(usable),
                "rows_loaded": rows,
                "as_of_max": as_of_max,
                "source": source,
            }
        )
        if "rows_written" in feature_manifest:
            quality["rows_written"] = int(feature_manifest.get("rows_written", 0) or 0)
        if rows:
            quality["rows_loaded_min"] = min(rows)
        if family == "price_history":
            quality["min_required_rows"] = _PRICE_MIN_REQUIRED_ROWS
            quality["full_factor_target_rows"] = _PRICE_MIN_REQUIRED_ROWS
            if rows:
                quality["usable_rows_min"] = min(rows)
        return quality
