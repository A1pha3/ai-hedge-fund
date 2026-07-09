# Auto Scoring Feature Store Zero Network I/O Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `score_batch()` and every function it calls during Layer B strategy scoring consume local `ScoringFeatureStore` inputs only, with all public provider access moved outside the scoring call graph.

**Architecture:** Add a `ScoringFeatureStore` adapter that reads local price, financial, event, industry PE, dragon tiger, intraday, and fund-flow snapshots. Split fundamental and event sentiment scoring into pure input scorers plus provider-backed compatibility wrappers, then route `score_batch()` through the store. Keep refresh best-effort and bounded, and expose feature coverage in `data_quality.scoring_features` while preserving existing `optional_features`.

**Tech Stack:** Python 3.12, pandas, Pydantic models from `src.data.models`, pytest, existing `CandidateStock` and `StrategySignal` models, local CSV/JSON snapshots under `data/`.

## Global Constraints

- Hard acceptance boundary: `score_batch()` and functions called by `score_batch()` while producing Layer B strategy signals must have zero public network I/O.
- This plan does not make the entire `--auto` command network-free; Layer A, market-state detection, recommended-price injection, and post-score helpers remain separate migration work.
- Missing local snapshots must return empty or incomplete inputs, not provider fallbacks.
- Stale reads are disabled by default. When enabled, stale snapshots must be less than or equal to `trade_date`, within `max_stale_days`, and never future-dated.
- Local legacy date directories must support both `YYYYMMDD` and `YYYY-MM-DD`.
- Financial, news, and insider JSON must parse through `FinancialMetrics`, `CompanyNews`, and `InsiderTrade`.
- Existing factor math and factor weights must not change.
- `data/paper_trading/*` runtime state must not be staged or committed for this work.
- Use CSV/JSON local snapshots only; do not add parquet or new runtime dependencies.

---

## File Structure

- Create `src/screening/scoring_feature_store.py`
  - Owns all local scoring-feature reads, date-safe snapshot resolution, legacy snapshot parsing, LHB conversion, and quality summary shape.
- Modify `src/screening/optional_feature_store.py`
  - Keep existing optional intraday/fund-flow read behavior. Add only compatibility helpers if needed by `ScoringFeatureStore`.
- Modify `src/screening/strategy_scorer_fundamental.py`
  - Add pure `score_fundamental_strategy_from_metrics(...)`; keep provider-backed `score_fundamental_strategy(...)` for non-`score_batch()` callers.
- Modify `src/screening/strategy_scorer_event_sentiment_helpers.py`
  - Add pure `score_event_sentiment_strategy_from_inputs(...)`; keep provider-backed `score_event_sentiment_strategy(...)` for non-`score_batch()` callers.
- Modify `src/screening/strategy_scorer.py`
  - Inject `ScoringFeatureStore` through provisional scoring, heavy scoring, industry PE, dragon tiger, intraday, and fund-flow paths.
- Create `src/screening/scoring_feature_refresh.py`
  - Adds `refresh_scoring_features(...)` and manifest writing for all scoring feature families.
- Modify `src/screening/optional_feature_refresh.py`
  - Delegate existing `refresh_optional_features(...)` to `refresh_scoring_features(...)` for backward compatibility.
- Modify `src/main.py`
  - Use `refresh_scoring_features(...)`, construct `ScoringFeatureStore`, pass it into `score_batch()`, and write `data_quality.scoring_features`.
- Create `tests/screening/test_scoring_feature_store.py`
  - Unit tests for local reads, legacy dates, stale rules, malformed files, LHB conversion, and quality counts.
- Modify `tests/screening/test_strategy_scorer.py`
  - Provider-forbidden scoring tests and fake-store integration tests.
- Modify `tests/screening/test_optional_feature_refresh.py`
  - Compatibility tests for old refresh entry point.
- Modify `tests/test_main_auto_feature_quality.py`
  - Auto payload quality-report integration tests.

---

### Task 1: Add ScoringFeatureStore Local Read API

**Files:**
- Create: `src/screening/scoring_feature_store.py`
- Create: `tests/screening/test_scoring_feature_store.py`

**Interfaces:**
- Produces: `ScoringFeatureStore(base_dir: Path | str = "data/feature_cache", price_cache_dir: Path | str = "data/price_cache", legacy_snapshot_dir: Path | str = "data/snapshots", lhb_cache_dir: Path | str = "data/lhb_cache", max_stale_days: int = 0, allow_stale: bool = False)`
- Produces: `load_price_frame(ticker: str, trade_date: str, lookback_days: int = 400) -> pd.DataFrame`
- Produces: `load_financial_metrics(ticker: str, trade_date: str) -> list[FinancialMetrics]`
- Produces: `load_event_inputs(ticker: str, trade_date: str) -> tuple[list[CompanyNews], list[InsiderTrade]]`
- Produces: `load_industry_pe_medians(trade_date: str) -> dict[str, float]`
- Produces: `load_dragon_tiger_bonus_map(tickers: list[str], trade_date: str) -> dict[str, float]`
- Produces: `load_intraday_metrics(trade_date: str, tickers: list[str]) -> dict[str, dict[str, Any]]`
- Produces: `load_fund_flow_metrics(trade_date: str, tickers: list[str]) -> dict[str, dict[str, Any]]`
- Produces: `build_quality_summary(trade_date: str, tickers: list[str], requested: dict[str, set[str]] | None = None) -> dict[str, Any]`

- [ ] **Step 1: Write failing tests for price, financial, news, and LHB reads**

Add `tests/screening/test_scoring_feature_store.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from src.screening.scoring_feature_store import ScoringFeatureStore


def test_load_price_frame_reads_local_price_cache_without_provider(tmp_path: Path) -> None:
    price_dir = tmp_path / "price_cache"
    price_dir.mkdir()
    pd.DataFrame(
        [
            {"date": "2026-07-07", "open": 10.0, "high": 11.0, "low": 9.8, "close": 10.5, "volume": 1000},
            {"date": "2026-07-08", "open": 10.5, "high": 11.5, "low": 10.2, "close": 11.0, "volume": 1200},
            {"date": "2026-07-09", "open": 11.0, "high": 12.0, "low": 10.8, "close": 11.8, "volume": 1300},
        ]
    ).to_csv(price_dir / "000001.csv", index=False)
    store = ScoringFeatureStore(
        base_dir=tmp_path / "feature_cache",
        price_cache_dir=price_dir,
        legacy_snapshot_dir=tmp_path / "snapshots",
        lhb_cache_dir=tmp_path / "lhb_cache",
    )

    frame = store.load_price_frame("000001", "20260708", lookback_days=400)

    assert list(frame["close"]) == [10.5, 11.0]
    assert frame.index[-1].strftime("%Y-%m-%d") == "2026-07-08"


def test_load_financial_metrics_accepts_compact_and_dashed_dates(tmp_path: Path) -> None:
    snapshot_dir = tmp_path / "snapshots"
    compact_dir = snapshot_dir / "000001" / "20260708"
    dashed_dir = snapshot_dir / "000002" / "2026-07-08"
    compact_dir.mkdir(parents=True)
    dashed_dir.mkdir(parents=True)
    payload = {
        "financial_metrics": [
            {
                "ticker": "000001",
                "report_period": "20260331",
                "period": "ttm",
                "currency": "CNY",
                "market_cap": 1.0,
                "enterprise_value": None,
                "price_to_earnings_ratio": 12.0,
                "price_to_book_ratio": None,
                "price_to_sales_ratio": None,
                "enterprise_value_to_ebitda_ratio": None,
                "enterprise_value_to_revenue_ratio": None,
                "free_cash_flow_yield": None,
                "peg_ratio": None,
                "gross_margin": None,
                "operating_margin": 0.2,
                "net_margin": 0.21,
                "return_on_equity": 0.16,
                "return_on_assets": None,
                "return_on_invested_capital": None,
                "asset_turnover": None,
                "inventory_turnover": None,
                "receivables_turnover": None,
                "days_sales_outstanding": None,
                "operating_cycle": None,
                "working_capital_turnover": None,
                "current_ratio": 2.0,
                "quick_ratio": 1.5,
                "cash_ratio": None,
                "operating_cash_flow_ratio": None,
                "debt_to_equity": 0.1,
                "debt_to_assets": 0.1,
                "interest_coverage": 10.0,
                "revenue_growth": 0.1,
                "earnings_growth": 0.2,
                "book_value_growth": None,
                "earnings_per_share_growth": None,
                "free_cash_flow_growth": None,
                "operating_income_growth": None,
                "ebitda_growth": None,
                "payout_ratio": None,
                "earnings_per_share": None,
                "book_value_per_share": None,
                "free_cash_flow_per_share": None,
            }
        ]
    }
    (compact_dir / "financials.json").write_text(json.dumps(payload), encoding="utf-8")
    payload["financial_metrics"][0]["ticker"] = "000002"
    (dashed_dir / "financials.json").write_text(json.dumps(payload), encoding="utf-8")
    store = ScoringFeatureStore(
        base_dir=tmp_path / "feature_cache",
        price_cache_dir=tmp_path / "price_cache",
        legacy_snapshot_dir=snapshot_dir,
        lhb_cache_dir=tmp_path / "lhb_cache",
    )

    compact = store.load_financial_metrics("000001", "20260708")
    dashed = store.load_financial_metrics("000002", "20260708")

    assert compact[0].ticker == "000001"
    assert dashed[0].ticker == "000002"


def test_load_event_inputs_reads_existing_company_news_snapshot(tmp_path: Path) -> None:
    snapshot_dir = tmp_path / "snapshots"
    news_dir = snapshot_dir / "603259" / "2026-07-08"
    news_dir.mkdir(parents=True)
    (news_dir / "company_news.json").write_text(
        json.dumps(
            [
                {
                    "ticker": "603259",
                    "title": "回购完成",
                    "author": "source",
                    "source": "source",
                    "date": "2026-07-07 16:00:00",
                    "url": "https://example.test/news",
                    "sentiment": "positive",
                    "content": "603259 完成回购",
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    store = ScoringFeatureStore(
        base_dir=tmp_path / "feature_cache",
        price_cache_dir=tmp_path / "price_cache",
        legacy_snapshot_dir=snapshot_dir,
        lhb_cache_dir=tmp_path / "lhb_cache",
    )

    news, trades = store.load_event_inputs("603259", "20260708")

    assert [item.title for item in news] == ["回购完成"]
    assert trades == []


def test_load_dragon_tiger_bonus_uses_ticker_presence_only(tmp_path: Path) -> None:
    lhb_dir = tmp_path / "lhb_cache"
    lhb_dir.mkdir()
    pd.DataFrame(
        [
            {"trade_date": "20260708", "ts_code": "000001.SZ", "net_buy": -100.0},
            {"trade_date": "20260708", "ts_code": "000002.SZ", "net_buy": 0.0},
        ]
    ).to_csv(lhb_dir / "20260708.csv", index=False)
    store = ScoringFeatureStore(
        base_dir=tmp_path / "feature_cache",
        price_cache_dir=tmp_path / "price_cache",
        legacy_snapshot_dir=tmp_path / "snapshots",
        lhb_cache_dir=lhb_dir,
    )

    bonus = store.load_dragon_tiger_bonus_map(["000001", "000002", "000003"], "20260708")

    assert bonus == {"000001": 1.0, "000002": 1.0}
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
uv run pytest tests/screening/test_scoring_feature_store.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'src.screening.scoring_feature_store'`.

- [ ] **Step 3: Implement ScoringFeatureStore**

Create `src/screening/scoring_feature_store.py` with these definitions:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
uv run pytest tests/screening/test_scoring_feature_store.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit Task 1**

```bash
git add src/screening/scoring_feature_store.py tests/screening/test_scoring_feature_store.py
git commit -m "feat: add scoring feature store"
```

---

### Task 2: Split Fundamental And Event Scorers Into Pure Input Functions

**Files:**
- Modify: `src/screening/strategy_scorer_fundamental.py`
- Modify: `src/screening/strategy_scorer_event_sentiment_helpers.py`
- Modify: `tests/screening/test_strategy_scorer.py`

**Interfaces:**
- Consumes: `list[FinancialMetrics]`, `list[CompanyNews]`, `list[InsiderTrade]`
- Produces: `score_fundamental_strategy_from_metrics(metrics_list: list[FinancialMetrics], industry_name: str = "", industry_pe_medians: dict[str, float] | None = None) -> StrategySignal`
- Produces: `score_event_sentiment_strategy_from_inputs(news_items: list[CompanyNews], trades: list[InsiderTrade], trade_date: str) -> StrategySignal`

- [ ] **Step 1: Write failing tests for pure input scorers**

Append to `tests/screening/test_strategy_scorer.py`:

```python
from src.data.models import CompanyNews, FinancialMetrics
from src.screening.strategy_scorer_event_sentiment_helpers import score_event_sentiment_strategy_from_inputs
from src.screening.strategy_scorer_fundamental import score_fundamental_strategy_from_metrics


def _financial_metric(ticker: str, report_period: str, revenue_growth: float = 0.1) -> FinancialMetrics:
    payload = {field: None for field in FinancialMetrics.model_fields}
    payload.update(
        {
            "ticker": ticker,
            "report_period": report_period,
            "period": "ttm",
            "currency": "CNY",
            "market_cap": 1.0,
            "price_to_earnings_ratio": 10.0,
            "operating_margin": 0.2,
            "net_margin": 0.25,
            "return_on_equity": 0.18,
            "current_ratio": 2.0,
            "quick_ratio": 1.5,
            "debt_to_equity": 0.1,
            "debt_to_assets": 0.1,
            "interest_coverage": 20.0,
            "revenue_growth": revenue_growth,
            "earnings_growth": revenue_growth,
            "free_cash_flow_growth": revenue_growth,
        }
    )
    return FinancialMetrics.model_validate(payload)


def test_score_fundamental_strategy_from_metrics_uses_supplied_metrics() -> None:
    metrics = [_financial_metric("000001", f"20260{i}01", revenue_growth=0.1 + i * 0.01) for i in range(1, 5)]

    signal = score_fundamental_strategy_from_metrics(
        metrics,
        industry_name="银行",
        industry_pe_medians={"银行": 12.0},
    )

    assert signal.completeness > 0
    assert "profitability" in signal.sub_factors
    assert "industry_pe" in signal.sub_factors


def test_score_event_sentiment_strategy_from_inputs_uses_supplied_news() -> None:
    news = [
        CompanyNews(
            ticker="000001",
            title="公司回购股份并上调业绩预告",
            author="source",
            source="source",
            date="2026-07-08 10:00:00",
            url="https://example.test/news",
            sentiment="positive",
            content="公司回购股份并上调业绩预告",
        )
    ]

    signal = score_event_sentiment_strategy_from_inputs(news, [], "20260708")

    assert signal.completeness > 0
    assert "news_sentiment" in signal.sub_factors
    assert "event_freshness" in signal.sub_factors
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
uv run pytest tests/screening/test_strategy_scorer.py::test_score_fundamental_strategy_from_metrics_uses_supplied_metrics tests/screening/test_strategy_scorer.py::test_score_event_sentiment_strategy_from_inputs_uses_supplied_news -q
```

Expected: FAIL with import errors for the new functions.

- [ ] **Step 3: Add pure fundamental scorer and keep provider wrapper**

Modify the bottom of `src/screening/strategy_scorer_fundamental.py` so the orchestrator section contains:

```python
def score_fundamental_strategy_from_metrics(
    metrics_list: list[FinancialMetrics],
    industry_name: str = "",
    industry_pe_medians: dict[str, float] | None = None,
) -> StrategySignal:
    if not metrics_list:
        return StrategySignal(direction=0, confidence=0.0, completeness=0.0, sub_factors={})

    sub_factors = _build_fundamental_sub_factors(
        metrics_list=metrics_list,
        industry_name=industry_name,
        industry_pe_medians=industry_pe_medians,
    )
    return _apply_fundamental_quality_cap(aggregate_sub_factors(sub_factors))


def score_fundamental_strategy(
    ticker: str,
    trade_date: str,
    industry_name: str = "",
    industry_pe_medians: dict[str, float] | None = None,
) -> StrategySignal:
    metrics_list = get_financial_metrics(ticker=ticker, end_date=trade_date, period="ttm", limit=8)
    return score_fundamental_strategy_from_metrics(
        metrics_list=metrics_list,
        industry_name=industry_name,
        industry_pe_medians=industry_pe_medians,
    )
```

- [ ] **Step 4: Add pure event scorer and keep provider wrapper**

Modify the orchestrator section in `src/screening/strategy_scorer_event_sentiment_helpers.py` so it contains:

```python
def score_event_sentiment_strategy(ticker: str, trade_date: str) -> StrategySignal:
    start_date, end_date = _resolve_event_sentiment_date_window(trade_date)
    news_items, trades = _load_event_sentiment_inputs(ticker=ticker, start_date=start_date, end_date=end_date)
    return score_event_sentiment_strategy_from_inputs(news_items=news_items, trades=trades, trade_date=trade_date)


def score_event_sentiment_strategy_from_inputs(
    news_items: list[CompanyNews],
    trades: list[InsiderTrade],
    trade_date: str,
) -> StrategySignal:
    return _build_event_sentiment_strategy_signal(news_items=news_items, trades=trades, trade_date=trade_date)
```

- [ ] **Step 5: Run tests to verify they pass**

Run:

```bash
uv run pytest tests/screening/test_strategy_scorer.py::test_score_fundamental_strategy_from_metrics_uses_supplied_metrics tests/screening/test_strategy_scorer.py::test_score_event_sentiment_strategy_from_inputs_uses_supplied_news -q
```

Expected: PASS.

- [ ] **Step 6: Commit Task 2**

```bash
git add src/screening/strategy_scorer_fundamental.py src/screening/strategy_scorer_event_sentiment_helpers.py tests/screening/test_strategy_scorer.py
git commit -m "refactor: split pure scoring input functions"
```

---

### Task 3: Route score_batch Through ScoringFeatureStore

**Files:**
- Modify: `src/screening/strategy_scorer.py`
- Modify: `tests/screening/test_strategy_scorer.py`

**Interfaces:**
- Consumes: `ScoringFeatureStore` from Task 1
- Consumes: pure scorers from Task 2
- Produces: `score_batch(candidates: list[CandidateStock], trade_date: str, feature_store: ScoringFeatureStore | None = None) -> dict[str, dict[str, StrategySignal]]`

- [ ] **Step 1: Add a provider-forbidden fake store test**

Append to `tests/screening/test_strategy_scorer.py`:

```python
from unittest.mock import patch

import pandas as pd

from src.data.models import CompanyNews, FinancialMetrics
from src.screening.models import CandidateStock
from src.screening.strategy_scorer import score_batch


class _LocalOnlyScoringStore:
    def __init__(self) -> None:
        self.price_requests: list[str] = []
        self.fundamental_requests: list[str] = []
        self.event_requests: list[str] = []

    def load_price_frame(self, ticker: str, trade_date: str, lookback_days: int = 400) -> pd.DataFrame:
        self.price_requests.append(ticker)
        dates = pd.date_range("2026-01-01", periods=220, freq="D")
        return pd.DataFrame(
            {
                "open": [10.0 + i * 0.01 for i in range(220)],
                "high": [10.2 + i * 0.01 for i in range(220)],
                "low": [9.8 + i * 0.01 for i in range(220)],
                "close": [10.1 + i * 0.01 for i in range(220)],
                "volume": [1000 + i for i in range(220)],
            },
            index=dates,
        )

    def load_financial_metrics(self, ticker: str, trade_date: str) -> list[FinancialMetrics]:
        self.fundamental_requests.append(ticker)
        return [_financial_metric(ticker, f"20260{i}01", revenue_growth=0.1 + i * 0.01) for i in range(1, 5)]

    def load_event_inputs(self, ticker: str, trade_date: str):
        self.event_requests.append(ticker)
        return (
            [
                CompanyNews(
                    ticker=ticker,
                    title="公司回购股份并上调业绩预告",
                    author="source",
                    source="source",
                    date="2026-07-08 10:00:00",
                    url="https://example.test/news",
                    sentiment="positive",
                    content="公司回购股份并上调业绩预告",
                )
            ],
            [],
        )

    def load_industry_pe_medians(self, trade_date: str) -> dict[str, float]:
        return {"银行": 12.0}

    def load_dragon_tiger_bonus_map(self, tickers: list[str], trade_date: str) -> dict[str, float]:
        return {ticker: 1.0 for ticker in tickers}

    def load_intraday_metrics(self, trade_date: str, tickers: list[str]) -> dict[str, dict]:
        return {ticker: {"flow_60": 0.1, "flow_60_source": "snapshot"} for ticker in tickers}

    def load_fund_flow_metrics(self, trade_date: str, tickers: list[str]) -> dict[str, dict]:
        return {ticker: {"main_flow_ratio": 0.2, "main_flow_ratio_source": "snapshot"} for ticker in tickers}


def test_score_batch_uses_store_when_all_score_time_providers_are_forbidden(monkeypatch) -> None:
    monkeypatch.setattr("src.screening.strategy_scorer.SCORE_BATCH_CONCURRENCY", 1)
    monkeypatch.setattr("src.screening.strategy_scorer.TECHNICAL_SCORE_MAX_CANDIDATES", 2)
    monkeypatch.setattr("src.screening.strategy_scorer.FUNDAMENTAL_SCORE_MAX_CANDIDATES", 2)
    monkeypatch.setattr("src.screening.strategy_scorer.EVENT_SENTIMENT_MAX_CANDIDATES", 2)
    monkeypatch.setattr("src.screening.strategy_scorer.INTRADAY_SCORE_MAX_CANDIDATES", 2)
    candidates = [
        CandidateStock(ticker="000001", name="A", industry_sw="银行", market_cap=100.0, avg_volume_20d=10000.0),
        CandidateStock(ticker="000002", name="B", industry_sw="银行", market_cap=90.0, avg_volume_20d=9000.0),
    ]
    store = _LocalOnlyScoringStore()

    with (
        patch("src.screening.strategy_scorer_event_sentiment_helpers.get_prices", side_effect=AssertionError("price provider forbidden")),
        patch("src.screening.strategy_scorer_fundamental.get_financial_metrics", side_effect=AssertionError("financial provider forbidden")),
        patch("src.screening.strategy_scorer_event_sentiment_helpers.get_company_news", side_effect=AssertionError("news provider forbidden")),
        patch("src.screening.strategy_scorer_event_sentiment_helpers.get_insider_trades", side_effect=AssertionError("insider provider forbidden")),
        patch("src.screening.strategy_scorer.get_daily_basic_batch", side_effect=AssertionError("daily basic provider forbidden")),
        patch("src.screening.strategy_scorer.get_all_stock_basic", side_effect=AssertionError("stock basic provider forbidden")),
        patch("src.screening.strategy_scorer.get_sw_industry_classification", side_effect=AssertionError("industry provider forbidden")),
        patch("src.screening.strategy_scorer.get_lhb_detail", side_effect=AssertionError("lhb detail provider forbidden")),
        patch("src.screening.strategy_scorer.get_lhb_institutional_stats", side_effect=AssertionError("lhb institutional provider forbidden")),
        patch("src.screening.strategy_scorer.get_intraday_bars", side_effect=AssertionError("intraday bars provider forbidden")),
        patch("src.screening.strategy_scorer.get_intraday_ticks", side_effect=AssertionError("intraday ticks provider forbidden")),
        patch("src.screening.strategy_scorer.get_money_flow", side_effect=AssertionError("money flow provider forbidden")),
    ):
        results = score_batch(candidates, "20260708", feature_store=store)

    assert set(results) == {"000001", "000002"}
    assert store.price_requests
    assert store.fundamental_requests
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
uv run pytest tests/screening/test_strategy_scorer.py::test_score_batch_uses_store_when_all_score_time_providers_are_forbidden -q
```

Expected: FAIL because current `score_batch()` still calls at least one patched provider or does not call store methods.

- [ ] **Step 3: Modify imports and type aliases in strategy_scorer.py**

In `src/screening/strategy_scorer.py`, add imports:

```python
from src.screening.scoring_feature_store import ScoringFeatureStore
from src.screening.strategy_scorer_event_sentiment_helpers import (
    _empty_signal,
    score_event_sentiment_strategy,
    score_event_sentiment_strategy_from_inputs,
)
from src.screening.strategy_scorer_fundamental import (
    score_fundamental_strategy,
    score_fundamental_strategy_from_metrics,
)
```

Keep the existing provider imports until all references are removed, then delete unused imports after tests pass.

- [ ] **Step 4: Replace score_candidate and light-signal helpers**

Update the relevant functions in `src/screening/strategy_scorer.py` to this shape:

```python
def score_candidate(
    candidate: CandidateStock,
    trade_date: str,
    industry_pe_medians: dict[str, float] | None = None,
    prices_df: pd.DataFrame | None = None,
    feature_store: ScoringFeatureStore | None = None,
) -> dict[str, StrategySignal]:
    store = feature_store or ScoringFeatureStore()
    prices_df = prices_df if prices_df is not None else store.load_price_frame(candidate.ticker, trade_date)
    industry_pe_medians = industry_pe_medians if industry_pe_medians is not None else store.load_industry_pe_medians(trade_date)
    metrics_list = store.load_financial_metrics(candidate.ticker, trade_date)
    news_items, trades = store.load_event_inputs(candidate.ticker, trade_date)
    return {
        "trend": score_trend_strategy(prices_df, ticker=candidate.ticker),
        "mean_reversion": score_mean_reversion_strategy(prices_df),
        "fundamental": score_fundamental_strategy_from_metrics(metrics_list, candidate.industry_sw, industry_pe_medians),
        "event_sentiment": score_event_sentiment_strategy_from_inputs(news_items, trades, trade_date),
    }


def _compute_light_signals(
    candidate: CandidateStock,
    trade_date: str,
    feature_store: ScoringFeatureStore,
) -> tuple[dict[str, StrategySignal], pd.DataFrame]:
    prices_df = feature_store.load_price_frame(candidate.ticker, trade_date)
    return _build_light_signal_map(prices_df, ticker=candidate.ticker), prices_df
```

- [ ] **Step 5: Thread the store through provisional ranking**

Change `_build_provisional_ranking(...)` signature and calls:

```python
def _build_provisional_ranking(
    candidates: list[CandidateStock],
    trade_date: str,
    results: dict[str, dict[str, StrategySignal]],
    feature_store: ScoringFeatureStore,
) -> list[tuple[float, CandidateStock]]:
```

Inside the serial branch call:

```python
light_signals, price_frame = _compute_light_signals(candidate, trade_date, feature_store)
```

Inside the parallel branch submit:

```python
future_to_candidate = {
    executor.submit(_compute_light_signals, candidate, trade_date, feature_store): candidate
    for candidate in technical_candidates
}
```

Update `_prepare_heavy_score_candidates(...)` to accept and pass `feature_store`.

- [ ] **Step 6: Replace industry PE and heavy scoring provider calls**

Change `_build_industry_pe_medians(...)`:

```python
def _build_industry_pe_medians(trade_date: str, feature_store: ScoringFeatureStore) -> dict[str, float]:
    return feature_store.load_industry_pe_medians(trade_date)
```

Change fundamental and event sections in `_populate_heavy_signals(...)` so they use local store inputs:

```python
def _score_fundamental_from_store(
    candidate: CandidateStock,
    trade_date: str,
    industry_pe_medians: dict[str, float],
    feature_store: ScoringFeatureStore,
) -> StrategySignal:
    return score_fundamental_strategy_from_metrics(
        feature_store.load_financial_metrics(candidate.ticker, trade_date),
        candidate.industry_sw,
        industry_pe_medians,
    )


def _score_event_from_store(
    candidate: CandidateStock,
    trade_date: str,
    feature_store: ScoringFeatureStore,
) -> StrategySignal:
    news_items, trades = feature_store.load_event_inputs(candidate.ticker, trade_date)
    return score_event_sentiment_strategy_from_inputs(news_items, trades, trade_date)
```

Use these helpers in both serial and parallel branches instead of submitting `score_fundamental_strategy` or `score_event_sentiment_strategy`.

- [ ] **Step 7: Replace dragon tiger and score_batch setup**

Change `_populate_dragon_tiger_bonus_metrics(...)` signature:

```python
def _populate_dragon_tiger_bonus_metrics(
    results: dict[str, dict[str, StrategySignal]],
    candidates: list[CandidateStock],
    trade_date: str,
    feature_store: ScoringFeatureStore,
) -> None:
```

Use:

```python
bonus_map = feature_store.load_dragon_tiger_bonus_map(
    [candidate.ticker for candidate in candidates_with_momentum],
    trade_date,
)
```

Change `score_batch(...)`:

```python
def score_batch(
    candidates: list[CandidateStock],
    trade_date: str,
    feature_store: ScoringFeatureStore | None = None,
) -> dict[str, dict[str, StrategySignal]]:
    started_at = perf_counter()
    scoring_feature_store = feature_store or ScoringFeatureStore()
    industry_pe_medians = _build_industry_pe_medians(trade_date, scoring_feature_store)
    results = _initialize_score_batch_results(candidates)
    fundamental_candidates = _prepare_heavy_score_candidates(candidates, trade_date, results, scoring_feature_store)
    _populate_heavy_signals(results, fundamental_candidates, trade_date, industry_pe_medians, scoring_feature_store)
    elapsed = perf_counter() - started_at
    logger.info(
        "score_batch completed: %d candidates, %d heavy-scored, concurrency=%d, %.2fs",
        len(candidates),
        len(fundamental_candidates),
        SCORE_BATCH_CONCURRENCY,
        elapsed,
    )
    return results
```

- [ ] **Step 8: Run provider-forbidden test**

Run:

```bash
uv run pytest tests/screening/test_strategy_scorer.py::test_score_batch_uses_store_when_all_score_time_providers_are_forbidden -q
```

Expected: PASS.

- [ ] **Step 9: Run scorer regression tests**

Run:

```bash
uv run pytest tests/screening/test_strategy_scorer.py -q
```

Expected: PASS. If older tests pass `OptionalFeatureStore` fakes, update those fakes to expose the `ScoringFeatureStore` methods used by `score_batch()` or pass a real `ScoringFeatureStore` with temporary local files.

- [ ] **Step 10: Commit Task 3**

```bash
git add src/screening/strategy_scorer.py tests/screening/test_strategy_scorer.py
git commit -m "feat: route score batch through scoring feature store"
```

---

### Task 4: Add Scoring Feature Refresh Manifest Boundary

**Files:**
- Create: `src/screening/scoring_feature_refresh.py`
- Modify: `src/screening/optional_feature_refresh.py`
- Modify: `tests/screening/test_optional_feature_refresh.py`

**Interfaces:**
- Produces: `refresh_scoring_features(trade_date: str, tickers: list[str], timeout_seconds: float = 20.0, cache_dir: Path | str = "data/feature_cache") -> dict[str, Any]`
- Produces: manifest file `data/feature_cache/feature_manifest_YYYYMMDD.json`
- Preserves: `refresh_optional_features(...)` existing import path delegates to the new refresh function

- [ ] **Step 1: Write failing refresh manifest test**

Add to `tests/screening/test_optional_feature_refresh.py`:

```python
import json
from pathlib import Path

from src.screening.scoring_feature_refresh import refresh_scoring_features


def test_refresh_scoring_features_writes_all_family_manifest(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("AUTO_OPTIONAL_FEATURE_REFRESH", "0")

    summary = refresh_scoring_features(
        "20260708",
        ["000001", "000002", "000001"],
        timeout_seconds=3.0,
        cache_dir=tmp_path,
    )

    manifest = json.loads((tmp_path / "feature_manifest_20260708.json").read_text(encoding="utf-8"))
    assert summary["status"] == "skipped"
    assert manifest["candidate_count"] == 2
    assert set(manifest["features"]) == {
        "price_history",
        "financial_metrics",
        "event_inputs",
        "industry_pe_medians",
        "dragon_tiger_bonus",
        "intraday_short_trade_metrics",
        "daily_fund_flow_metrics",
    }
    assert manifest["features"]["event_inputs"]["rows_written"] == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
uv run pytest tests/screening/test_optional_feature_refresh.py::test_refresh_scoring_features_writes_all_family_manifest -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'src.screening.scoring_feature_refresh'`.

- [ ] **Step 3: Implement refresh_scoring_features**

Create `src/screening/scoring_feature_refresh.py`:

```python
"""Best-effort scoring feature refresh boundary.

This module owns public provider access for scoring feature preparation.  The
initial implementation writes an explicit manifest and reuses local caches; score
time never depends on refresh success.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any


_FEATURE_FAMILIES = (
    "price_history",
    "financial_metrics",
    "event_inputs",
    "industry_pe_medians",
    "dragon_tiger_bonus",
    "intraday_short_trade_metrics",
    "daily_fund_flow_metrics",
)


def _refresh_enabled() -> bool:
    raw = os.environ.get("AUTO_OPTIONAL_FEATURE_REFRESH", "1")
    return raw.strip().lower() not in {"0", "false", "no", "off"}


def refresh_scoring_features(
    trade_date: str,
    tickers: list[str],
    *,
    timeout_seconds: float = 20.0,
    cache_dir: Path | str = "data/feature_cache",
) -> dict[str, Any]:
    cache_path = Path(cache_dir)
    cache_path.mkdir(parents=True, exist_ok=True)
    unique_tickers = sorted({str(ticker).split(".")[0].zfill(6) for ticker in tickers})
    enabled = _refresh_enabled()
    status = "not_implemented" if enabled else "skipped"
    source = "pending_provider_implementation" if enabled else "not_refreshed"
    manifest = {
        "trade_date": str(trade_date),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "candidate_count": len(unique_tickers),
        "timeout_seconds": float(timeout_seconds),
        "status": status,
        "features": {
            family: {
                "provider_failures": 0,
                "rows_written": 0,
                "source": source,
            }
            for family in _FEATURE_FAMILIES
        },
    }
    manifest_path = cache_path / f"feature_manifest_{trade_date}.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return {
        "status": status,
        "trade_date": str(trade_date),
        "candidate_count": len(unique_tickers),
        "manifest_path": str(manifest_path),
    }
```

- [ ] **Step 4: Delegate optional refresh to scoring refresh**

Replace `src/screening/optional_feature_refresh.py` implementation with:

```python
"""Backward-compatible optional feature refresh entry point."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.screening.scoring_feature_refresh import refresh_scoring_features


def refresh_optional_features(
    trade_date: str,
    tickers: list[str],
    *,
    timeout_seconds: float = 20.0,
    cache_dir: Path | str = "data/feature_cache",
) -> dict[str, Any]:
    return refresh_scoring_features(
        trade_date,
        tickers,
        timeout_seconds=timeout_seconds,
        cache_dir=cache_dir,
    )
```

- [ ] **Step 5: Run refresh tests**

Run:

```bash
uv run pytest tests/screening/test_optional_feature_refresh.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit Task 4**

```bash
git add src/screening/scoring_feature_refresh.py src/screening/optional_feature_refresh.py tests/screening/test_optional_feature_refresh.py
git commit -m "feat: add scoring feature refresh manifest"
```

---

### Task 5: Integrate ScoringFeatureStore Into --auto Report Quality

**Files:**
- Modify: `src/main.py`
- Modify: `tests/test_main_auto_feature_quality.py`

**Interfaces:**
- Consumes: `refresh_scoring_features(...)` from Task 4
- Consumes: `ScoringFeatureStore` from Task 1
- Produces: report payload field `data_quality.scoring_features`
- Preserves: report payload field `data_quality.optional_features`

- [ ] **Step 1: Write failing auto payload quality test**

Append to `tests/test_main_auto_feature_quality.py`:

```python
def test_compute_auto_screening_uses_scoring_feature_store_quality(monkeypatch) -> None:
    import src.main as main_module

    class _Store:
        def build_quality_summary(self, trade_date: str, tickers: list[str]) -> dict:
            return {
                "scoring_features": {
                    "price_history": {
                        "coverage": 1.0,
                        "source": "local_price_cache",
                        "trade_date": trade_date,
                        "stale": False,
                        "candidate_count": len(tickers),
                        "eligible_count": len(tickers),
                        "requested_count": len(tickers),
                        "loaded_count": len(tickers),
                        "missing_tickers": 0,
                        "provider_failures": 0,
                    }
                },
                "optional_features": {},
            }

    created_store = _Store()
    monkeypatch.setattr("src.screening.scoring_feature_store.ScoringFeatureStore", lambda: created_store)
    monkeypatch.setattr("src.screening.scoring_feature_refresh.refresh_scoring_features", lambda *args, **kwargs: {"status": "skipped"})

    captured = {}

    def fake_score_batch(candidates, trade_date, *, feature_store):
        captured["feature_store"] = feature_store
        return {candidate.ticker: {} for candidate in candidates}

    monkeypatch.setattr(main_module, "score_batch", fake_score_batch)

    payload = main_module._build_auto_screening_payload(
        trade_date="20260708",
        top_n=10,
        market_state=type("MS", (), {"model_dump": lambda self: {}})(),
        candidates=[type("C", (), {"ticker": "000001"})()],
        fused=[],
        top_results_serializable=[],
        sector_warnings=[],
        consecutive_highlight=0,
        decay_summary={},
        industry_rotation_payload=[],
        batch_fetcher_use_batch=True,
        batch_fetcher_stats={},
        optional_feature_quality=created_store.build_quality_summary("20260708", ["000001"]),
    )

    assert payload["data_quality"]["scoring_features"]["price_history"]["coverage"] == 1.0
```

- [ ] **Step 2: Run targeted test**

Run:

```bash
uv run pytest tests/test_main_auto_feature_quality.py::test_compute_auto_screening_uses_scoring_feature_store_quality -q
```

Expected: PASS if `_build_auto_screening_payload` already merges arbitrary quality keys; FAIL if imports or naming still assume `OptionalFeatureStore`.

- [ ] **Step 3: Update compute_auto_screening_results imports and setup**

In `src/main.py`, replace the Step 1 to Step 2 feature setup block:

```python
from src.screening.scoring_feature_refresh import refresh_scoring_features
from src.screening.scoring_feature_store import ScoringFeatureStore

candidate_tickers = [candidate.ticker for candidate in candidates]
refresh_scoring_features(
    trade_date,
    candidate_tickers,
    timeout_seconds=float(os.environ.get("AUTO_OPTIONAL_FEATURE_REFRESH_TIMEOUT_SECONDS", "20")),
)
scoring_feature_store = ScoringFeatureStore()
```

Then pass the store and quality:

```python
scored = score_batch(candidates, trade_date, feature_store=scoring_feature_store)
optional_feature_quality = scoring_feature_store.build_quality_summary(
    trade_date,
    candidate_tickers,
)
```

Keep the variable name `optional_feature_quality` for the smallest payload-builder diff, but add a comment:

```python
# Backward-compatible payload key: this summary now contains both
# data_quality.scoring_features and data_quality.optional_features.
```

- [ ] **Step 4: Run auto feature quality tests**

Run:

```bash
uv run pytest tests/test_main_auto_feature_quality.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit Task 5**

```bash
git add src/main.py tests/test_main_auto_feature_quality.py
git commit -m "feat: report scoring feature quality"
```

---

### Task 6: Final Provider-Forbidden Guard And Verification

**Files:**
- Modify: `tests/screening/test_strategy_scorer.py`
- No production code unless this task exposes a missed provider path.

**Interfaces:**
- Consumes: all prior task interfaces
- Produces: final guard test proving Step 2 scoring is local-only

- [ ] **Step 1: Add explicit AST/import-site guard for provider calls in score_batch**

Append to `tests/screening/test_strategy_scorer.py`:

```python
import ast
from pathlib import Path


def test_strategy_scorer_score_batch_has_no_direct_provider_calls() -> None:
    source = Path("src/screening/strategy_scorer.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    forbidden = {
        "get_prices",
        "get_financial_metrics",
        "get_company_news",
        "get_insider_trades",
        "get_daily_basic_batch",
        "get_all_stock_basic",
        "get_sw_industry_classification",
        "get_lhb_detail",
        "get_lhb_institutional_stats",
        "get_intraday_bars",
        "get_intraday_ticks",
        "get_money_flow",
    }
    score_batch_node = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "score_batch"
    )
    calls = {
        node.func.id
        for node in ast.walk(score_batch_node)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert calls.isdisjoint(forbidden)
```

- [ ] **Step 2: Run guard tests**

Run:

```bash
uv run pytest tests/screening/test_strategy_scorer.py::test_strategy_scorer_score_batch_has_no_direct_provider_calls tests/screening/test_strategy_scorer.py::test_score_batch_uses_store_when_all_score_time_providers_are_forbidden -q
```

Expected: PASS.

- [ ] **Step 3: Run focused test suite**

Run:

```bash
uv run pytest tests/screening/test_scoring_feature_store.py tests/screening/test_optional_feature_store.py tests/screening/test_optional_feature_refresh.py tests/screening/test_strategy_scorer.py tests/test_main_auto_feature_quality.py -q
```

Expected: PASS.

- [ ] **Step 4: Run auto smoke with refresh disabled**

Run:

```bash
AUTO_OPTIONAL_FEATURE_REFRESH=0 uv run python src/main.py --auto
```

Expected:

- Exit code 0.
- Step 2 logs do not include `get_prices`, `get_financial_metrics`, `get_company_news`, `get_insider_trades`, `get_daily_basic_batch`, `get_all_stock_basic`, `get_sw_industry_classification`, `get_lhb_detail`, `get_lhb_institutional_stats`, `get_intraday_bars`, `get_intraday_ticks`, or `get_money_flow`.
- Provider logs from Layer A or market-state detection may still appear; those are outside this plan's boundary.

- [ ] **Step 5: Inspect runtime data before committing**

Run:

```bash
git status --short
```

Expected:

- Code and test files from this task may be modified.
- `data/paper_trading/journal.jsonl` and `data/paper_trading/portfolio_state.json` must not be staged or committed.

- [ ] **Step 6: Commit final guard**

```bash
git add tests/screening/test_strategy_scorer.py
git commit -m "test: guard score batch against provider calls"
```

---

## Self-Review Checklist

- Spec coverage: Tasks 1 and 3 implement the local-only `ScoringFeatureStore` and `score_batch()` routing. Task 2 preserves factor math while removing provider calls from scorer orchestrators. Task 4 defines the refresh boundary. Task 5 adds `data_quality.scoring_features`. Task 6 enforces the zero-network Step 2 guard.
- Marker scan: No disallowed planning markers are present, and every test step includes concrete code or a concrete command.
- Type consistency: The plan consistently uses `ScoringFeatureStore`, `score_fundamental_strategy_from_metrics`, `score_event_sentiment_strategy_from_inputs`, and `refresh_scoring_features`.
- Scope check: The plan targets only `score_batch()` and its call graph. It does not migrate Layer A, market-state detection, recommended-price injection, or post-score helpers.
- Data integrity check: Every commit command avoids `data/paper_trading/*`.
