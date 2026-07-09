"""Local scoring feature snapshots for Layer B score_batch.

Public provider calls belong in refresh code.  This store reads only local
CSV/JSON snapshots and returns empty inputs when data is missing or malformed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
from pydantic import ValidationError

from src.data.models import CompanyNews, FinancialMetrics, InsiderTrade
from src.screening.optional_feature_store import OptionalFeatureStore


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


def _parse_trade_date(value: str) -> datetime | None:
    raw = str(value)
    for fmt in ("%Y%m%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw[:10], fmt)
        except ValueError:
            continue
    return None


def _compact_date(value: str) -> str:
    parsed = _parse_trade_date(value)
    return parsed.strftime("%Y%m%d") if parsed else str(value)


def _dashed_date(value: str) -> str:
    parsed = _parse_trade_date(value)
    return parsed.strftime("%Y-%m-%d") if parsed else str(value)


@dataclass
class _QualityTracker:
    candidate_count: int = 0
    requested: dict[str, set[str]] = field(default_factory=dict)
    loaded: dict[str, set[str]] = field(default_factory=dict)
    malformed: dict[str, int] = field(default_factory=dict)
    rows_loaded: dict[str, list[int]] = field(default_factory=dict)
    sources: dict[str, str] = field(default_factory=dict)

    def note_requested(self, family: str, tickers: list[str]) -> None:
        self.requested.setdefault(family, set()).update(_ticker6(ticker) for ticker in tickers)

    def note_loaded(self, family: str, ticker: str, *, rows: int | None = None, source: str = "snapshot") -> None:
        self.loaded.setdefault(family, set()).add(_ticker6(ticker))
        self.sources[family] = source
        if rows is not None:
            self.rows_loaded.setdefault(family, []).append(int(rows))

    def note_malformed(self, family: str) -> None:
        self.malformed[family] = self.malformed.get(family, 0) + 1


@dataclass
class ScoringFeatureStore:
    base_dir: Path | str = Path("data/feature_cache")
    price_cache_dir: Path | str = Path("data/price_cache")
    legacy_snapshot_dir: Path | str = Path("data/snapshots")
    lhb_cache_dir: Path | str = Path("data/lhb_cache")
    max_stale_days: int = 0
    allow_stale: bool = False

    def __post_init__(self) -> None:
        self.base_dir = Path(self.base_dir)
        self.price_cache_dir = Path(self.price_cache_dir)
        self.legacy_snapshot_dir = Path(self.legacy_snapshot_dir)
        self.lhb_cache_dir = Path(self.lhb_cache_dir)
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
            return pd.DataFrame()
        try:
            frame = pd.read_csv(path)
        except (OSError, UnicodeDecodeError, ValueError, pd.errors.ParserError, pd.errors.EmptyDataError):
            self._quality.note_malformed("price_history")
            return pd.DataFrame()
        if frame.empty or "date" not in frame.columns:
            return pd.DataFrame()
        required = {"open", "close", "high", "low", "volume"}
        if not required.issubset(frame.columns):
            self._quality.note_malformed("price_history")
            return pd.DataFrame()
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
            return pd.DataFrame()
        normalized = normalized.set_index("Date")
        self._quality.note_loaded("price_history", ticker6, rows=len(normalized), source="local_price_cache")
        return normalized[["open", "close", "high", "low", "volume"]]

    def load_financial_metrics(self, ticker: str, trade_date: str) -> list[FinancialMetrics]:
        ticker6 = _ticker6(ticker)
        self._quality.note_requested("financial_metrics", [ticker6])
        path = self._resolve_legacy_snapshot_path(ticker6, trade_date, "financials.json")
        if path is None:
            return []
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            rows = payload.get("financial_metrics", []) if isinstance(payload, dict) else []
            metrics = [FinancialMetrics.model_validate(row) for row in rows if isinstance(row, dict)]
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValidationError, TypeError):
            self._quality.note_malformed("financial_metrics")
            return []
        if metrics:
            self._quality.note_loaded("financial_metrics", ticker6, rows=len(metrics), source="snapshot")
        return metrics

    def load_event_inputs(self, ticker: str, trade_date: str) -> tuple[list[CompanyNews], list[InsiderTrade]]:
        ticker6 = _ticker6(ticker)
        self._quality.note_requested("event_inputs", [ticker6])
        news = self._load_company_news(ticker6, trade_date)
        trades = self._load_insider_trades(ticker6, trade_date)
        if news or trades:
            self._quality.note_loaded("event_inputs", ticker6, rows=len(news) + len(trades), source="snapshot")
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
            if result:
                self._quality.note_loaded("industry_pe_medians", "000000", rows=len(result), source="snapshot")
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
        code_column = "ts_code" if "ts_code" in frame.columns else "代码" if "代码" in frame.columns else ""
        if not code_column:
            self._quality.note_malformed("dragon_tiger_bonus")
            return {}
        codes = {_ticker6(code) for code in frame[code_column].dropna().astype(str).tolist()}
        result = {ticker: 1.0 for ticker in sorted(wanted & codes)}
        for ticker in result:
            self._quality.note_loaded("dragon_tiger_bonus", ticker, source="local_lhb_cache")
        return result

    def load_intraday_metrics(self, trade_date: str, tickers: list[str]) -> dict[str, dict[str, Any]]:
        self._quality.note_requested("intraday_short_trade_metrics", tickers)
        rows = self._optional_store.load_intraday_metrics(trade_date, tickers)
        for ticker in rows:
            self._quality.note_loaded("intraday_short_trade_metrics", ticker, source="snapshot")
        return rows

    def load_fund_flow_metrics(self, trade_date: str, tickers: list[str]) -> dict[str, dict[str, Any]]:
        self._quality.note_requested("daily_fund_flow_metrics", tickers)
        rows = self._optional_store.load_fund_flow_metrics(trade_date, tickers)
        for ticker in rows:
            self._quality.note_loaded("daily_fund_flow_metrics", ticker, source="snapshot")
        return rows

    def build_quality_summary(self, trade_date: str, tickers: list[str], requested: dict[str, set[str]] | None = None) -> dict[str, Any]:
        self._quality.candidate_count = len({_ticker6(ticker) for ticker in tickers})
        if requested:
            for family, family_tickers in requested.items():
                self._quality.note_requested(family, list(family_tickers))
        return {
            "scoring_features": {
                family: self._quality_for_family(family, trade_date)
                for family in _FEATURE_FAMILIES
            },
            **self._optional_store.build_quality_summary(trade_date, tickers),
        }

    def _resolve_legacy_snapshot_path(self, ticker: str, trade_date: str, filename: str) -> Path | None:
        exact_dirs = [
            self.legacy_snapshot_dir / ticker / _compact_date(trade_date),
            self.legacy_snapshot_dir / ticker / _dashed_date(trade_date),
        ]
        for directory in exact_dirs:
            path = directory / filename
            if path.exists():
                return path
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
        return best[1] if best else None

    def _load_company_news(self, ticker: str, trade_date: str) -> list[CompanyNews]:
        path = self._resolve_legacy_snapshot_path(ticker, trade_date, "company_news.json")
        if path is None:
            return []
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            rows = payload if isinstance(payload, list) else payload.get("news", []) if isinstance(payload, dict) else []
            return [CompanyNews.model_validate(row) for row in rows if isinstance(row, dict)]
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValidationError, TypeError):
            self._quality.note_malformed("event_inputs")
            return []

    def _load_insider_trades(self, ticker: str, trade_date: str) -> list[InsiderTrade]:
        path = self._resolve_legacy_snapshot_path(ticker, trade_date, "insider_trades.json")
        if path is None:
            return []
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            rows = payload if isinstance(payload, list) else payload.get("insider_trades", []) if isinstance(payload, dict) else []
            return [InsiderTrade.model_validate(row) for row in rows if isinstance(row, dict)]
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValidationError, TypeError):
            self._quality.note_malformed("event_inputs")
            return []

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

    def _quality_for_family(self, family: str, trade_date: str) -> dict[str, Any]:
        requested = self._quality.requested.get(family, set())
        loaded = self._quality.loaded.get(family, set())
        rows = self._quality.rows_loaded.get(family, [])
        source = self._quality.sources.get(family, "snapshot" if loaded else "missing")
        quality: dict[str, Any] = {
            "coverage": round(len(loaded) / len(requested), 4) if requested else 0.0,
            "source": source,
            "trade_date": _compact_date(trade_date),
            "stale": False,
            "candidate_count": int(self._quality.candidate_count),
            "eligible_count": len(requested),
            "requested_count": len(requested),
            "loaded_count": len(loaded),
            "missing_tickers": max(len(requested) - len(loaded), 0),
            "provider_failures": 0,
            "malformed_files": int(self._quality.malformed.get(family, 0)),
        }
        if rows:
            quality["rows_loaded_min"] = min(rows)
        if family == "price_history":
            quality["min_required_rows"] = _PRICE_MIN_REQUIRED_ROWS
        return quality
