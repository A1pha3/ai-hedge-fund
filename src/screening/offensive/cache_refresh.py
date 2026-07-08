"""Refresh the local caches consumed by ``--daily-action``.

``--daily-action`` scans local CSV caches directly. The post-market ``--auto``
path therefore needs to persist the latest daily price and fund-flow records
into those caches, not only emit ``auto_screening_*.json`` reports.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

import pandas as pd

logger = logging.getLogger(__name__)

_DEFAULT_PRICE_CACHE_DIR = Path("data/price_cache")
_DEFAULT_FUND_FLOW_CACHE_DIR = Path("data/fund_flow_cache")
_DEFAULT_SNAPSHOT_DIR = Path("data/snapshots")
_DEFAULT_FUND_FLOW_RATE_LIMIT_SEC = 0.2
_DEFAULT_PRICE_HISTORY_LOOKBACK_DAYS = 180
_DEFAULT_MIN_PRICE_HISTORY_ROWS = 31


@dataclass
class DailyActionCacheRefreshStats:
    price_total: int = 0
    price_updated: int = 0
    price_backfilled: int = 0
    price_insufficient_history: int = 0
    price_missing: int = 0
    price_failed: int = 0
    fund_flow_total: int = 0
    fund_flow_saved: int = 0
    fund_flow_empty: int = 0
    fund_flow_skipped_fresh: int = 0
    fund_flow_failed: int = 0
    failed_tickers: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    def merge(self, other: "DailyActionCacheRefreshStats") -> "DailyActionCacheRefreshStats":
        self.price_total += other.price_total
        self.price_updated += other.price_updated
        self.price_backfilled += other.price_backfilled
        self.price_insufficient_history += other.price_insufficient_history
        self.price_missing += other.price_missing
        self.price_failed += other.price_failed
        self.fund_flow_total += other.fund_flow_total
        self.fund_flow_saved += other.fund_flow_saved
        self.fund_flow_empty += other.fund_flow_empty
        self.fund_flow_skipped_fresh += other.fund_flow_skipped_fresh
        self.fund_flow_failed += other.fund_flow_failed
        self.failed_tickers.extend(other.failed_tickers)
        return self


def _env_enabled(name: str, *, default: bool = True) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off"}


def _env_int(name: str, *, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning("Invalid integer env %s=%r; using %d", name, raw, default)
        return default


def _env_float(name: str, *, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError:
        logger.warning("Invalid float env %s=%r; using %.3f", name, raw, default)
        return default


def existing_price_cache_tickers(price_cache_dir: Path | str = _DEFAULT_PRICE_CACHE_DIR) -> list[str]:
    cache_dir = Path(price_cache_dir)
    if not cache_dir.exists():
        return []
    return sorted(p.stem for p in cache_dir.glob("*.csv") if p.stem.isdigit() and len(p.stem) == 6)


def _is_code6(value: str) -> bool:
    return value.isdigit() and len(value) == 6


def _code6(ts_code: object) -> str:
    text = str(ts_code or "").strip()
    if "." in text:
        text = text.split(".", 1)[0]
    return text.zfill(6) if text.isdigit() else text


def _price_date(value: object) -> str:
    text = str(value or "").strip()
    if len(text) == 8 and text.isdigit():
        return pd.to_datetime(text, format="%Y%m%d").strftime("%Y-%m-%d")
    return pd.to_datetime(text).strftime("%Y-%m-%d")


def _fund_flow_date(value: object) -> str:
    text = str(value or "").strip()
    if len(text) == 8 and text.isdigit():
        return text
    return pd.to_datetime(text).strftime("%Y%m%d")


def _row_value(row: pd.Series, *names: str, default: float | None = None) -> float | None:
    for name in names:
        if name in row and pd.notna(row[name]):
            return float(row[name])
    return default


def _build_price_row(row: pd.Series, trade_date: str) -> dict:
    if "trade_date" in row and pd.notna(row["trade_date"]):
        date_value = row["trade_date"]
    elif "date" in row and pd.notna(row["date"]):
        date_value = row["date"]
    else:
        date_value = trade_date
    return {
        "date": _price_date(date_value),
        "close": _row_value(row, "close"),
        "open": _row_value(row, "open"),
        "high": _row_value(row, "high"),
        "low": _row_value(row, "low"),
        "pct_change": _row_value(row, "pct_chg", "pct_change", default=0.0),
        "volume": _row_value(row, "vol", "volume", default=0.0),
    }


def _write_price_cache_row(path: Path, row: dict) -> None:
    old = pd.read_csv(path, dtype={"date": str}) if path.exists() else pd.DataFrame()
    combined = pd.concat([old, pd.DataFrame([row])], ignore_index=True)
    combined["date"] = combined["date"].map(_price_date)
    combined = combined.drop_duplicates(subset=["date"], keep="last")
    combined = combined.sort_values("date").reset_index(drop=True)
    combined.to_csv(path, index=False)


def _snapshot_records(payload: object, *, include_shadow: bool) -> list[object]:
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return []

    records: list[object] = []
    for key in ("candidates", "candidate_pool", "selected_candidates", "recommendations", "stocks"):
        value = payload.get(key)
        if isinstance(value, list):
            records.extend(value)
    if include_shadow:
        value = payload.get("shadow_candidates")
        if isinstance(value, list):
            records.extend(value)
    if any(key in payload for key in ("ticker", "ts_code", "code", "symbol")):
        records.append(payload)
    return records


def _extract_snapshot_ticker(record: object) -> str | None:
    if isinstance(record, str):
        ticker = _code6(record)
        return ticker if _is_code6(ticker) else None
    if not isinstance(record, dict):
        return None

    for key in ("ticker", "ts_code", "code", "symbol"):
        value = record.get(key)
        if value is None:
            continue
        ticker = _code6(value)
        if _is_code6(ticker):
            return ticker
    return None


def _load_candidate_pool_tickers(path: Path, *, include_shadow: bool = False) -> set[str]:
    if not path.exists():
        return set()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - bad optional snapshot should not stop cache refresh
        logger.warning("Failed to read candidate snapshot %s: %s", path, exc)
        return set()

    tickers: set[str] = set()
    for record in _snapshot_records(payload, include_shadow=include_shadow):
        ticker = _extract_snapshot_ticker(record)
        if ticker:
            tickers.add(ticker)
    return tickers


def resolve_daily_action_refresh_tickers(
    trade_date: str,
    *,
    price_cache_dir: Path | str = _DEFAULT_PRICE_CACHE_DIR,
    snapshot_dir: Path | str = _DEFAULT_SNAPSHOT_DIR,
    include_shadow: bool = False,
) -> list[str]:
    """Return the ticker universe whose caches must be fresh for ``--daily-action``."""

    tickers = set(existing_price_cache_tickers(price_cache_dir))
    snapshots = Path(snapshot_dir)
    if snapshots.exists():
        for path in sorted(snapshots.glob(f"candidate_pool_{trade_date}*.json")):
            if "shadow" in path.name and not include_shadow:
                continue
            tickers.update(_load_candidate_pool_tickers(path, include_shadow=include_shadow))
    return sorted(ticker for ticker in tickers if _is_code6(ticker))


def _history_start_date(trade_date: str, lookback_days: int = _DEFAULT_PRICE_HISTORY_LOOKBACK_DAYS) -> str:
    end = pd.to_datetime(str(trade_date), format="%Y%m%d")
    start = end - pd.Timedelta(days=max(0, lookback_days - 1))
    return start.strftime("%Y%m%d")


def _normalise_price_history(df: pd.DataFrame | None) -> pd.DataFrame:
    if df is None or len(df) == 0:
        return pd.DataFrame(columns=["date", "close", "open", "high", "low", "pct_change", "volume"])

    rows = [_build_price_row(row, "") for _, row in df.iterrows()]
    history = pd.DataFrame(rows)
    history = history.dropna(subset=["date", "close"])
    if len(history) == 0:
        return history
    history["date"] = history["date"].map(_price_date)
    history = history.drop_duplicates(subset=["date"], keep="last")
    return history.sort_values("date").reset_index(drop=True)


def _fetch_price_history_with_tushare(ticker: str, start_date: str, end_date: str) -> pd.DataFrame:
    from src.tools.tushare_api import get_ashare_prices_with_tushare

    prices = get_ashare_prices_with_tushare(ticker, start_date, end_date)
    rows: list[dict] = []
    previous_close: float | None = None
    for price in sorted(prices, key=lambda item: item.time):
        close = float(price.close)
        pct_change = 0.0 if previous_close in (None, 0) else (close / previous_close - 1.0) * 100.0
        rows.append(
            {
                "date": _price_date(price.time),
                "close": close,
                "open": float(price.open),
                "high": float(price.high),
                "low": float(price.low),
                "pct_change": pct_change,
                "volume": float(price.volume),
            }
        )
        previous_close = close
    return pd.DataFrame(rows)


def refresh_price_cache_from_daily_batch(
    trade_date: str,
    *,
    price_cache_dir: Path | str = _DEFAULT_PRICE_CACHE_DIR,
    daily_prices_df: pd.DataFrame | None = None,
    fetch_daily_prices_batch: Callable[[str], pd.DataFrame | None] | None = None,
    target_tickers: list[str] | set[str] | tuple[str, ...] | None = None,
    backfill_price_history_fn: Callable[[str, str, str], pd.DataFrame | None] | None = None,
    min_history_rows: int = _DEFAULT_MIN_PRICE_HISTORY_ROWS,
    history_start_date: str | None = None,
) -> DailyActionCacheRefreshStats:
    """Append or replace one daily OHLCV row for tickers consumed by ``--daily-action``."""

    cache_dir = Path(price_cache_dir)
    if target_tickers is None:
        tickers = existing_price_cache_tickers(cache_dir)
    else:
        tickers = sorted({_code6(ticker) for ticker in target_tickers if _is_code6(_code6(ticker))})
    stats = DailyActionCacheRefreshStats(price_total=len(tickers))
    if not tickers:
        return stats

    if daily_prices_df is None:
        if fetch_daily_prices_batch is None:
            from src.screening.batch_data_fetcher import get_global_batch_data_fetcher

            fetch_daily_prices_batch = get_global_batch_data_fetcher().fetch_daily_prices_batch
        daily_prices_df = fetch_daily_prices_batch(trade_date)

    if daily_prices_df is None or len(daily_prices_df) == 0:
        stats.price_missing = len(tickers)
        return stats

    by_ticker: dict[str, pd.Series] = {}
    for _, row in daily_prices_df.iterrows():
        ticker = _code6(row.get("ts_code", ""))
        if ticker:
            by_ticker[ticker] = row

    for ticker in tickers:
        row = by_ticker.get(ticker)
        if row is None:
            stats.price_missing += 1
            continue
        try:
            path = cache_dir / f"{ticker}.csv"
            if not path.exists():
                if backfill_price_history_fn is None:
                    backfill_price_history_fn = _fetch_price_history_with_tushare
                start_date = history_start_date or _history_start_date(trade_date)
                history = _normalise_price_history(backfill_price_history_fn(ticker, start_date, trade_date))
                if len(history) < min_history_rows:
                    stats.price_insufficient_history += 1
                    continue
                path.parent.mkdir(parents=True, exist_ok=True)
                history.to_csv(path, index=False)
                stats.price_backfilled += 1
            _write_price_cache_row(cache_dir / f"{ticker}.csv", _build_price_row(row, trade_date))
            stats.price_updated += 1
        except Exception as exc:  # noqa: BLE001 - one bad CSV must not stop the batch
            logger.warning("Failed to refresh price_cache for %s: %s", ticker, exc)
            stats.price_failed += 1
            stats.failed_tickers.append(ticker)
    return stats


def _latest_fund_flow_date(cache_dir: Path, ticker: str) -> str | None:
    path = cache_dir / f"{ticker}.csv"
    if not path.exists():
        return None
    try:
        df = pd.read_csv(path, dtype={"date": str}, usecols=["date"])
    except Exception:
        return None
    if len(df) == 0:
        return None
    return max(_fund_flow_date(value) for value in df["date"].dropna())


def refresh_fund_flow_cache(
    tickers: list[str],
    trade_date: str,
    *,
    fund_flow_cache_dir: Path | str = _DEFAULT_FUND_FLOW_CACHE_DIR,
    fetch_fn: Callable[..., pd.DataFrame] | None = None,
    rate_limit_sec: float = _DEFAULT_FUND_FLOW_RATE_LIMIT_SEC,
    max_tickers: int = 0,
) -> DailyActionCacheRefreshStats:
    """Fetch one trade date of fund-flow data and merge it into per-ticker CSVs."""

    from src.screening.offensive.data.fund_flow_store import FundFlowStore

    if fetch_fn is None:
        from src.tools.fund_flow import fetch_individual_fund_flow

        fetch_fn = fetch_individual_fund_flow

    queue = tickers[:max_tickers] if max_tickers > 0 else list(tickers)
    cache_dir = Path(fund_flow_cache_dir)
    store = FundFlowStore(cache_dir=cache_dir)
    stats = DailyActionCacheRefreshStats(fund_flow_total=len(queue))

    for index, ticker in enumerate(queue, 1):
        try:
            latest = _latest_fund_flow_date(cache_dir, ticker)
            if latest is not None and latest >= trade_date:
                stats.fund_flow_skipped_fresh += 1
                continue

            df = fetch_fn(ticker, start_date=trade_date, end_date=trade_date)
            if df is None or len(df) == 0:
                stats.fund_flow_empty += 1
                continue

            store.save(ticker, df)
            stats.fund_flow_saved += 1
        except Exception as exc:  # noqa: BLE001 - isolate one ticker failure
            logger.warning("Failed to refresh fund_flow_cache for %s: %s", ticker, exc)
            stats.fund_flow_failed += 1
            stats.failed_tickers.append(ticker)

        if rate_limit_sec > 0 and index < len(queue):
            time.sleep(rate_limit_sec)

    return stats


def refresh_daily_action_caches(
    trade_date: str,
    *,
    price_cache_dir: Path | str = _DEFAULT_PRICE_CACHE_DIR,
    fund_flow_cache_dir: Path | str = _DEFAULT_FUND_FLOW_CACHE_DIR,
    snapshot_dir: Path | str = _DEFAULT_SNAPSHOT_DIR,
    daily_prices_df: pd.DataFrame | None = None,
    fetch_daily_prices_batch: Callable[[str], pd.DataFrame | None] | None = None,
    target_tickers: list[str] | set[str] | tuple[str, ...] | None = None,
    backfill_price_history_fn: Callable[[str, str, str], pd.DataFrame | None] | None = None,
    fund_flow_fetch_fn: Callable[..., pd.DataFrame] | None = None,
    refresh_fund_flow: bool | None = None,
    fund_flow_rate_limit_sec: float | None = None,
    fund_flow_max_tickers: int | None = None,
) -> DailyActionCacheRefreshStats:
    """Refresh all cache files needed by the next ``--daily-action`` run."""

    tickers = (
        sorted({_code6(ticker) for ticker in target_tickers if _is_code6(_code6(ticker))})
        if target_tickers is not None
        else resolve_daily_action_refresh_tickers(
            trade_date,
            price_cache_dir=price_cache_dir,
            snapshot_dir=snapshot_dir,
            include_shadow=_env_enabled("DAILY_ACTION_INCLUDE_SHADOW_CANDIDATES", default=False),
        )
    )
    price_stats = refresh_price_cache_from_daily_batch(
        trade_date,
        price_cache_dir=price_cache_dir,
        daily_prices_df=daily_prices_df,
        fetch_daily_prices_batch=fetch_daily_prices_batch,
        target_tickers=tickers,
        backfill_price_history_fn=backfill_price_history_fn,
    )
    stats = DailyActionCacheRefreshStats().merge(price_stats)

    if refresh_fund_flow is None:
        refresh_fund_flow = _env_enabled("DAILY_ACTION_REFRESH_FUND_FLOW", default=True)
    if not refresh_fund_flow:
        return stats

    rate_limit = fund_flow_rate_limit_sec if fund_flow_rate_limit_sec is not None else _env_float("DAILY_ACTION_FUND_FLOW_RATE_LIMIT_SEC", default=_DEFAULT_FUND_FLOW_RATE_LIMIT_SEC)
    max_tickers = fund_flow_max_tickers if fund_flow_max_tickers is not None else _env_int("DAILY_ACTION_FUND_FLOW_MAX_TICKERS", default=0)
    fund_flow_stats = refresh_fund_flow_cache(
        tickers,
        trade_date,
        fund_flow_cache_dir=fund_flow_cache_dir,
        fetch_fn=fund_flow_fetch_fn,
        rate_limit_sec=rate_limit,
        max_tickers=max_tickers,
    )
    return stats.merge(fund_flow_stats)
