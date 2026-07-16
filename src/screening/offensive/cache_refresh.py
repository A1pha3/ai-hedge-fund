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
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
from typing import Callable

import pandas as pd

from src.tools.ashare_board_utils import build_beijing_exchange_mask_from_series
from src.tools.ashare_board_utils import is_beijing_exchange_stock
from src.screening.offensive.cache_readiness import (
    DailyActionRefreshResult,
    FundFlowStatus,
    PriceStatus,
    SuspensionEvidence,
    TickerRefreshOutcome,
    derive_stats_from_outcomes,
    universe_fingerprint,
)
from src.screening.offensive.pit_evidence import (
    PITEvidenceError,
    canonical_fingerprint,
    canonical_flow_fingerprint,
    canonical_price_fingerprint,
    validate_price_artifact,
)
from src.tools.ashare_board_utils import is_excluded_ticker
from src.utils.atomic_files import atomic_write_csv
from src.utils.date_utils import latest_open_trade_date_on_or_before

logger = logging.getLogger(__name__)

_DEFAULT_PRICE_CACHE_DIR = Path("data/price_cache")
_DEFAULT_FUND_FLOW_CACHE_DIR = Path("data/fund_flow_cache")
_DEFAULT_INDUSTRY_INDEX_CACHE_DIR = Path("data/industry_index_cache")
_DEFAULT_SNAPSHOT_DIR = Path("data/snapshots")
_DEFAULT_FUND_FLOW_RATE_LIMIT_SEC = 0.2
_DEFAULT_PRICE_HISTORY_LOOKBACK_DAYS = 400
_DEFAULT_MIN_PRICE_HISTORY_ROWS = 31
# 涨停股注入 price_cache 的扫描阈值. 用主板下限 9.5% 故意宽松:
# 它是所有板块涨停的公共下限 (主板 10%, 科创/创业 20%, 北交所 30% 都 ≥9.5%),
# 用 9.5% 保证不漏任何真涨停股 (宁可多注入一些大涨股, 也不漏真涨停).
# 真正的板块自适应涨停判定在 btst_breakout.detect / is_limit_up_unbuyable_next_day
# 里按 ticker 前缀取阈值 (limit_up_pct_for_ticker), 这里只负责把候选注入缓存.
_DEFAULT_LIMIT_UP_PCT = 9.5
_DAILY_BATCH_COLUMNS = (
    "ts_code",
    "trade_date",
    "open",
    "high",
    "low",
    "close",
    "pct_chg",
    "vol",
)


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
    fund_flow_empty: int = 0          # 全源返回空 (真异常: 新上市/退市/源故障)
    fund_flow_bse_unsupported: int = 0  # 北交所 (已知不支持)
    fund_flow_suspended: int = 0      # 当日停牌
    fund_flow_skipped_fresh: int = 0
    fund_flow_failed: int = 0
    industry_index_total: int = 0
    industry_index_failed: int = 0
    # 当日涨停股注入 price_cache 的数量 (BTST 目标标的, 常不在候选池内).
    limit_up_injected: int = 0
    failed_tickers: list[str] = field(default_factory=list)
    fund_flow_empty_tickers: list[str] = field(default_factory=list)

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
        self.fund_flow_bse_unsupported += other.fund_flow_bse_unsupported
        self.fund_flow_suspended += other.fund_flow_suspended
        self.fund_flow_skipped_fresh += other.fund_flow_skipped_fresh
        self.fund_flow_failed += other.fund_flow_failed
        self.industry_index_total += other.industry_index_total
        self.industry_index_failed += other.industry_index_failed
        self.limit_up_injected += other.limit_up_injected
        self.failed_tickers.extend(other.failed_tickers)
        self.fund_flow_empty_tickers.extend(other.fund_flow_empty_tickers)
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
    # 北交所 (4xx/8xx/92xx) 全面排除: 系统不交易北交所, 且 tushare moneyflow 不覆盖
    # 北交所 → 扫它们只会浪费 CPU/内存并制造 degraded 噪声 (与 candidate_pool 一致)。
    # 永久排除票 (退市/数据残缺): 残留 csv 会被 glob 拾起, 在此一并剔除。
    return sorted(
        p.stem
        for p in cache_dir.glob("*.csv")
        if p.stem.isdigit()
        and len(p.stem) == 6
        and not is_beijing_exchange_stock(symbol=p.stem)
        and not is_excluded_ticker(p.stem)
    )


def _is_code6(value: str) -> bool:
    return value.isdigit() and len(value) == 6


def _code6(ts_code: object) -> str:
    text = str(ts_code or "").strip()
    if "." in text:
        text = text.split(".", 1)[0]
    return text.zfill(6) if text.isdigit() else text


def _provider_code6(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("provider ticker must be a string")
    text = value.strip()
    parts = text.split(".")
    if len(parts) > 2 or (len(parts) == 2 and parts[1] not in {"SZ", "SH", "BJ"}):
        raise ValueError("invalid provider ticker suffix")
    ticker = parts[0]
    if len(ticker) != 6 or not ticker.isdigit():
        raise ValueError("invalid provider ticker identity")
    return ticker


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


def _trade_date_value(value: object) -> date:
    return pd.to_datetime(_fund_flow_date(value), format="%Y%m%d").date()


def _normalize_daily_batch(payload: object) -> pd.DataFrame:
    """Validate and detach one provider batch before any downstream use."""

    if not isinstance(payload, pd.DataFrame):
        raise PITEvidenceError("daily batch must be a DataFrame")
    missing = set(_DAILY_BATCH_COLUMNS) - set(payload.columns)
    if missing:
        raise PITEvidenceError(
            "daily batch missing required columns: " + ", ".join(sorted(missing))
        )
    normalized = payload.copy(deep=True)
    for _, row in normalized.iterrows():
        ticker = _provider_code6(row["ts_code"])
        canonical_price_fingerprint(
            pd.DataFrame(
                [
                    {
                        "date": row["trade_date"],
                        "open": row["open"],
                        "high": row["high"],
                        "low": row["low"],
                        "close": row["close"],
                        "pct_change": row["pct_chg"],
                        "volume": row["vol"],
                    }
                ]
            ),
            ticker,
            row["trade_date"],
        )
    return normalized


def _row_value(row: pd.Series, *names: str, default: float | None = None) -> float | None:
    for name in names:
        if name in row and pd.notna(row[name]):
            return float(row[name])
    return default


def _extract_limit_up_tickers(
    daily_prices_df: pd.DataFrame | None,
    trade_date: str,
    *,
    limit_up_pct: float = _DEFAULT_LIMIT_UP_PCT,
) -> list[str]:
    """从全市场 daily batch DataFrame 中提取当日涨停股的 6 位代码列表.

    BTST setup 只在涨停日 (pct>=9.5%) 触发, 但涨停小盘股常被 --auto 候选池的
    流动性筛选排除, 永远不会进入 price_cache 的 ticker 集合 → --daily-action
    永远扫不到它们. 本 helper 从 batch fetcher 返回的全市场 DataFrame 中过滤
    涨停行, 让缓存刷新能主动把它们注入 price_cache.

    batch DataFrame 已含 ``pct_chg`` 列 (tushare daily 接口字段), 无需额外 API 调用.

    Args:
        daily_prices_df: ``fetch_daily_prices_batch`` 返回的全市场 DataFrame;
            None / 空 / 缺列时返回空列表 (绝不抛异常).
        trade_date: 请求的交易日 (8 位 YYYYMMDD); 不匹配的行被忽略
            (与 ``refresh_price_cache_from_daily_batch`` 的过期数据拒绝逻辑一致).
        limit_up_pct: 涨停阈值, 默认 9.5 (与 ``btst_breakout._LIMIT_UP_PCT`` 一致).

    Returns:
        去重排序的 6 位代码列表.
    """
    if daily_prices_df is None or not hasattr(daily_prices_df, "columns") or daily_prices_df.empty:
        return []
    if "pct_chg" not in daily_prices_df.columns or "ts_code" not in daily_prices_df.columns:
        return []
    requested = _fund_flow_date(trade_date)
    df = daily_prices_df
    # 仅取请求交易日的行 (过期数据拒绝, 与 refresh_price_cache_from_daily_batch:317 一致)
    if "trade_date" in df.columns:
        df = df[df["trade_date"].apply(lambda value: _fund_flow_date(value) == requested)]
    # 涨停过滤: 板块自适应阈值 (主板 9.5%, 科创/创业 19.5%, 北交所 29.0%).
    # Bug fix (H5): 旧逻辑用固定 9.5%, 把科创/创业的非涨停大涨 (+9.5~19.4%) 误注入,
    # 浪费 fund_flow API 配额且可能挤占真正的涨停股.
    from src.tools.ashare_board_utils import limit_up_pct_for_ticker

    # 逐行按板块判定涨停
    is_limit_up = df.apply(
        lambda row: pd.to_numeric(row.get("pct_chg", 0), errors="coerce") >= limit_up_pct_for_ticker(_code6(row.get("ts_code", ""))),
        axis=1,
    )
    limit_up_rows = df[is_limit_up]
    # 排除北交所: tushare moneyflow 不覆盖北交所 (全市场 5194 只含 0 只 .BJ),
    # 注入北交所涨停股会导致 refresh_fund_flow_cache 对每只 920xxx 都双源均失败。
    # 与 build_candidate_pool 的北交所过滤保持一致 (candidate_pool.py:7)。
    bj_mask = build_beijing_exchange_mask_from_series(limit_up_rows["ts_code"])
    limit_up_rows = limit_up_rows[~bj_mask]
    tickers = sorted({_code6(code) for code in limit_up_rows["ts_code"].tolist() if _is_code6(_code6(code))})
    return tickers


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


def _write_price_cache_row(
    path: Path,
    row: dict,
    *,
    existing_frame: pd.DataFrame | None = None,
    artifact_sink: Callable[[pd.DataFrame], None] | None = None,
) -> pd.DataFrame:
    old = (
        existing_frame.copy(deep=True)
        if existing_frame is not None
        else (
            pd.read_csv(path, dtype={"date": str})
            if path.exists()
            else pd.DataFrame()
        )
    )
    combined = pd.concat([old, pd.DataFrame([row])], ignore_index=True)
    combined["date"] = combined["date"].map(_price_date)
    combined = combined.drop_duplicates(subset=["date"], keep="last")
    combined = combined.sort_values("date").reset_index(drop=True)
    validate_price_artifact(combined, path.stem)
    if artifact_sink is not None:
        artifact_sink(combined.copy(deep=True))
    atomic_write_csv(path, combined)
    return combined.copy(deep=True)


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
    # 北交所全面排除 (数据获取 + 选股): 覆盖 price_cache 已有文件与候选池残留。
    # 永久排除票 (退市/数据残缺) 同步剔除。
    return sorted(
        ticker
        for ticker in tickers
        if _is_code6(ticker)
        and not is_beijing_exchange_stock(symbol=ticker)
        and not is_excluded_ticker(ticker)
    )


def _history_start_date(trade_date: str, lookback_days: int = _DEFAULT_PRICE_HISTORY_LOOKBACK_DAYS) -> str:
    end = pd.to_datetime(str(trade_date), format="%Y%m%d")
    start = end - pd.Timedelta(days=max(0, lookback_days - 1))
    return start.strftime("%Y%m%d")


def _resolve_effective_market_date(trade_date: str, *, lookback_days: int = 14) -> str:
    requested = _fund_flow_date(trade_date)
    effective = latest_open_trade_date_on_or_before(requested, lookback_days=lookback_days)
    if effective != requested:
        logger.info("[cache_refresh] %s 非交易日或未开市, 回退到最近开市日 %s 刷新缓存", requested, effective)
    return effective


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
    initial_frames: Mapping[str, pd.DataFrame] | None = None,
    initial_existing_tickers: frozenset[str] | set[str] | None = None,
    unreadable_tickers: frozenset[str] | set[str] = frozenset(),
    evidence_collector: dict[str, pd.DataFrame] | None = None,
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
    requested_trade_date = _fund_flow_date(trade_date)
    for _, row in daily_prices_df.iterrows():
        row_trade_date = _fund_flow_date(row.get("trade_date", requested_trade_date))
        if row_trade_date != requested_trade_date:
            continue
        ticker = _code6(row.get("ts_code", ""))
        if ticker:
            by_ticker[ticker] = row

    for ticker in tickers:
        if ticker in unreadable_tickers:
            stats.price_failed += 1
            stats.failed_tickers.append(ticker)
            if evidence_collector is not None:
                evidence_collector.pop(ticker, None)
            continue
        row = by_ticker.get(ticker)
        if row is None:
            stats.price_missing += 1
            continue
        try:
            path = cache_dir / f"{ticker}.csv"
            existed_at_capture = (
                ticker in initial_existing_tickers
                if initial_existing_tickers is not None
                else path.exists()
            )
            base_frame = (
                initial_frames[ticker].copy(deep=True)
                if initial_frames is not None and ticker in initial_frames
                else None
            )
            if not existed_at_capture:
                if backfill_price_history_fn is None:
                    from src.tools.price import fetch_daily_ohlcv

                    backfill_price_history_fn = fetch_daily_ohlcv
                start_date = history_start_date or _history_start_date(trade_date)
                history = _normalise_price_history(backfill_price_history_fn(ticker, start_date, trade_date))
                if len(history) < min_history_rows:
                    stats.price_insufficient_history += 1
                    continue
                # The retained daily batch row itself proves current-session
                # coverage. History is expected to end on the prior session and
                # is appended with that row below.
                base_frame = history
                stats.price_backfilled += 1
            path.parent.mkdir(parents=True, exist_ok=True)
            captured: list[pd.DataFrame] = []
            _write_price_cache_row(
                path,
                _build_price_row(row, trade_date),
                existing_frame=base_frame,
                artifact_sink=lambda frame: captured.append(frame),
            )
            if not captured:
                raise RuntimeError("price cache writer did not expose written artifact")
            if evidence_collector is not None:
                evidence_collector[ticker] = captured[-1].copy(deep=True)
            stats.price_updated += 1
        except Exception as exc:  # noqa: BLE001 - one bad CSV must not stop the batch
            logger.warning("Failed to refresh price_cache for %s: %s", ticker, exc)
            stats.price_failed += 1
            stats.failed_tickers.append(ticker)
            if evidence_collector is not None:
                evidence_collector.pop(ticker, None)
    return stats


def _latest_fund_flow_date(cache_dir: Path, ticker: str) -> str | None:
    path = cache_dir / f"{ticker}.csv"
    if not path.exists():
        return None
    try:
        df = pd.read_csv(path, dtype={"date": str}, usecols=["date"])
    except Exception:
        logger.warning("cache_refresh: failed to read fund flow cache %s, will re-fetch", path, exc_info=True)
        return None
    if len(df) == 0:
        return None
    return max(_fund_flow_date(value) for value in df["date"].dropna())


def load_suspension_evidence(
    trade_date: str,
    *,
    fetch_fn: Callable[[str], object] | None = None,
) -> SuspensionEvidence:
    """Load one authoritative suspension snapshot without conflating failure and empty."""

    trade_date_dt = _trade_date_value(trade_date)
    if fetch_fn is None:
        from src.tools.tushare_api import get_suspend_list

        fetch_fn = get_suspend_list
    try:
        df = fetch_fn(trade_date)
        if not isinstance(df, pd.DataFrame) or "ts_code" not in df.columns:
            raise ValueError("suspension snapshot must be a DataFrame with ts_code")
        if len(df) == 0:
            return SuspensionEvidence.available(
                trade_date_dt,
                set(),
                source_fingerprint=canonical_fingerprint(
                    "suspension",
                    "*",
                    (),
                ),
            )
        tickers: set[str] = set()
        for code in df["ts_code"]:
            if pd.isna(code):
                raise ValueError("suspension snapshot contains null ticker identity")
            tickers.add(_provider_code6(code))
        rows = [
            {"date": trade_date_dt.isoformat(), "ticker": ticker}
            for ticker in sorted(tickers)
        ]
        return SuspensionEvidence.available(
            trade_date_dt,
            tickers,
            source_fingerprint=canonical_fingerprint("suspension", "*", rows),
        )
    except Exception:  # noqa: BLE001 - unavailable is explicit evidence state
        logger.debug("[cache_refresh] 停牌列表获取失败, 资金流空返回将无法区分停牌", exc_info=True)
        return SuspensionEvidence.unavailable(trade_date_dt)


def _load_suspended_codes(trade_date: str) -> set[str]:
    """Backward-compatible suspension-code helper for direct fund-flow refreshes."""

    return set(load_suspension_evidence(trade_date).tickers)


def _check_tushare_available() -> bool:
    """快速检查 tushare 是否可用 (token 配置且 init 成功)."""
    try:
        from src.tools.tushare_api import _get_pro

        return _get_pro() is not None
    except Exception:
        return False


def refresh_fund_flow_cache(
    tickers: list[str],
    trade_date: str,
    *,
    fund_flow_cache_dir: Path | str = _DEFAULT_FUND_FLOW_CACHE_DIR,
    fetch_fn: Callable[..., pd.DataFrame] | None = None,
    rate_limit_sec: float = _DEFAULT_FUND_FLOW_RATE_LIMIT_SEC,
    max_tickers: int = 0,
    suspension_evidence: SuspensionEvidence | None = None,
    initial_frames: Mapping[str, pd.DataFrame] | None = None,
    unreadable_tickers: frozenset[str] | set[str] = frozenset(),
    evidence_collector: dict[str, pd.DataFrame] | None = None,
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

    # 一次性拉取当日停牌列表 (单次 API 调用, 不按 ticker 重复).
    # 资金流为空时用此集合区分「停牌」(预期行为, DEBUG) 与「数据异常」(WARNING).
    suspended_codes = (
        set(suspension_evidence.tickers)
        if suspension_evidence is not None
        else _load_suspended_codes(trade_date)
    )
    # H4 fix: 如果 suspended_codes 为空且 tushare 也不可用, 说明是基础设施故障而非无停牌
    tushare_ok = _check_tushare_available()

    for index, ticker in enumerate(queue, 1):
        if ticker in unreadable_tickers:
            stats.fund_flow_failed += 1
            stats.failed_tickers.append(ticker)
            if evidence_collector is not None:
                evidence_collector.pop(ticker, None)
            continue
        try:
            if initial_frames is not None and ticker in initial_frames:
                initial_frame = initial_frames[ticker]
                latest = (
                    max(_fund_flow_date(value) for value in initial_frame["date"])
                    if not initial_frame.empty and "date" in initial_frame.columns
                    else None
                )
            else:
                initial_frame = None
                latest = _latest_fund_flow_date(cache_dir, ticker)
            # Bug fix (H1): 旧逻辑用 >=, 未来日期行会永久冻结缓存.
            # 改为 ==: 只在缓存已有本交易日数据时跳过.
            if latest is not None and latest == trade_date:
                stats.fund_flow_skipped_fresh += 1
                continue

            # 北交所股票 tushare/akshare/ftshare 均不覆盖资金流,
            # 在 fetch 前跳过以避免无谓 WARNING 和 rate-limit 等待.
            if is_beijing_exchange_stock(symbol=ticker):
                stats.fund_flow_bse_unsupported += 1
                logger.debug("[资金流] %s 北交所股票, 资金流不支持, 跳过", ticker)
                continue

            # 停牌股票无资金流, 在 fetch 前跳过以避免 _multi_source 的全源 WARNING.
            if ticker in suspended_codes:
                stats.fund_flow_suspended += 1
                logger.debug("[资金流] %s 当日停牌, 跳过 (预期行为)", ticker)
                continue

            df = fetch_fn(ticker, start_date=trade_date, end_date=trade_date)
            if df is None or len(df) == 0:
                stats.fund_flow_empty += 1
                stats.fund_flow_empty_tickers.append(ticker)
                # H4 fix: 区分基础设施故障 (tushare 不可用且停牌列表也为空) vs 数据本身缺失
                if not tushare_ok and not suspended_codes:
                    logger.warning(
                        "[资金流] %s 全源返回空 — 可能是 tushare token 失效/网络故障 (停牌列表也为空)",
                        ticker,
                    )
                else:
                    logger.debug("[资金流] %s 全源返回空 — 新上市/退市/当日无交易", ticker)
                continue

            captured: list[pd.DataFrame] = []
            store.save(
                ticker,
                df,
                existing_frame=initial_frame,
                artifact_sink=lambda frame: captured.append(frame),
            )
            if not captured:
                raise RuntimeError("fund-flow store did not expose written artifact")
            if evidence_collector is not None:
                evidence_collector[ticker] = captured[-1].copy(deep=True)
            stats.fund_flow_saved += 1
        except Exception as exc:  # noqa: BLE001 - isolate one ticker failure
            logger.warning("Failed to refresh fund_flow_cache for %s: %s", ticker, exc)
            stats.fund_flow_failed += 1
            stats.failed_tickers.append(ticker)
            if evidence_collector is not None:
                evidence_collector.pop(ticker, None)

        if rate_limit_sec > 0 and index < len(queue):
            time.sleep(rate_limit_sec)

    return stats


def refresh_industry_index_cache(
    trade_date: str,
    *,
    cache_dir: Path | str,
    backfill_fn: Callable[..., dict[str, int]] | None = None,
) -> DailyActionCacheRefreshStats:
    """Refresh SW L1 industry index cache used by BTST industry confirmation."""

    stats = DailyActionCacheRefreshStats()
    if backfill_fn is None:
        from scripts.backfill_industry_index import backfill

        backfill_fn = backfill
    try:
        result = backfill_fn(end_date=trade_date, cache_dir=Path(cache_dir))
        stats.industry_index_total = sum(int(count) for count in (result or {}).values())
    except Exception as exc:  # noqa: BLE001 - industry cache must not abort --auto
        logger.warning("Failed to refresh industry_index_cache for %s: %s", trade_date, exc)
        stats.industry_index_failed = 1
    return stats


def _daily_batch_evidence_fingerprint(
    daily_prices_df: pd.DataFrame,
    trade_date: str,
) -> str:
    rows: list[dict[str, str]] = []
    requested = _fund_flow_date(trade_date)
    for _, row in daily_prices_df.iterrows():
        row_date = _fund_flow_date(row.get("trade_date", requested))
        if row_date != requested:
            continue
        ticker = _code6(row.get("ts_code", ""))
        if not _is_code6(ticker):
            continue
        price_row = _build_price_row(row, trade_date)
        rows.append(
            {
                "ticker": ticker,
                "price_fingerprint": canonical_price_fingerprint(
                    pd.DataFrame([price_row]),
                    ticker,
                    trade_date,
                ),
            }
        )
    return canonical_fingerprint("daily_price_batch", "*", rows)


def _project_pit_frame(frame: pd.DataFrame, trade_date: str) -> pd.DataFrame:
    """Return a detached point-in-time projection without changing the baseline."""

    if "date" not in frame.columns:
        raise ValueError("cache frame must contain date")
    requested = _fund_flow_date(trade_date)
    normalized_dates = frame["date"].map(_fund_flow_date)
    return frame[normalized_dates <= requested].copy(deep=True).reset_index(drop=True)


def _read_cache_baseline(
    path: Path,
    trade_date: str,
) -> tuple[pd.DataFrame, pd.DataFrame, bool, bool]:
    """Return full baseline, PIT projection, current presence, and read failure."""

    if not path.exists():
        empty = pd.DataFrame()
        return empty, empty.copy(), False, False
    try:
        full_frame = pd.read_csv(path, dtype={"date": str, "ticker": str})
        if "date" not in full_frame.columns:
            return full_frame, full_frame.iloc[0:0], False, True
        requested = _fund_flow_date(trade_date)
        normalized_dates = full_frame["date"].map(_fund_flow_date)
        pit_frame = _project_pit_frame(full_frame, trade_date)
        return (
            full_frame.copy(deep=True),
            pit_frame,
            bool((normalized_dates == requested).any()),
            False,
        )
    except Exception:  # noqa: BLE001 - failed evidence is represented in the outcome
        logger.debug("[cache_refresh] failed to read PIT cache %s", path, exc_info=True)
        empty = pd.DataFrame()
        return empty, empty.copy(), False, True


def _read_pit_cache(path: Path, trade_date: str) -> tuple[pd.DataFrame, bool, bool]:
    """Backward-compatible PIT-only cache reader."""

    _, pit_frame, is_current, failed = _read_cache_baseline(path, trade_date)
    return pit_frame, is_current, failed


def _frame_has_current_row(frame: pd.DataFrame, trade_date: str) -> bool:
    if frame.empty or "date" not in frame.columns:
        return False
    requested = _fund_flow_date(trade_date)
    return any(_fund_flow_date(value) == requested for value in frame["date"])


def refresh_daily_action_caches(
    trade_date: str,
    *,
    price_cache_dir: Path | str = _DEFAULT_PRICE_CACHE_DIR,
    fund_flow_cache_dir: Path | str = _DEFAULT_FUND_FLOW_CACHE_DIR,
    industry_index_cache_dir: Path | str = _DEFAULT_INDUSTRY_INDEX_CACHE_DIR,
    snapshot_dir: Path | str = _DEFAULT_SNAPSHOT_DIR,
    daily_prices_df: pd.DataFrame | None = None,
    fetch_daily_prices_batch: Callable[[str], pd.DataFrame | None] | None = None,
    target_tickers: list[str] | set[str] | tuple[str, ...] | None = None,
    backfill_price_history_fn: Callable[[str, str, str], pd.DataFrame | None] | None = None,
    industry_index_backfill_fn: Callable[..., dict[str, int]] | None = None,
    fund_flow_fetch_fn: Callable[..., pd.DataFrame] | None = None,
    refresh_industry_index: bool | None = None,
    refresh_fund_flow: bool | None = None,
    fund_flow_rate_limit_sec: float | None = None,
    fund_flow_max_tickers: int | None = None,
    suspension_loader: Callable[[str], SuspensionEvidence] | None = None,
) -> DailyActionRefreshResult:
    """Refresh and return one immutable, conserved Daily Action evidence result."""

    effective_trade_date = trade_date
    trade_date_dt = _trade_date_value(effective_trade_date)

    base_tickers = (
        sorted(
            {
                _code6(ticker)
                for ticker in target_tickers
                if _is_code6(_code6(ticker))
                and not is_beijing_exchange_stock(symbol=_code6(ticker))
            }
        )
        if target_tickers is not None
        else resolve_daily_action_refresh_tickers(
            trade_date,
            price_cache_dir=price_cache_dir,
            snapshot_dir=snapshot_dir,
            include_shadow=_env_enabled("DAILY_ACTION_INCLUDE_SHADOW_CANDIDATES", default=False),
        )
    )

    # Resolve the full-market batch exactly once and retain that same object for
    # limit-up extraction, price writes, and the result fingerprint.
    raw_daily_prices: object = daily_prices_df
    daily_batch_fetch_failed = False
    if raw_daily_prices is None:
        resolved_fetch = fetch_daily_prices_batch
        if resolved_fetch is None:
            from src.screening.batch_data_fetcher import get_global_batch_data_fetcher

            resolved_fetch = get_global_batch_data_fetcher().fetch_daily_prices_batch
        try:
            raw_daily_prices = resolved_fetch(effective_trade_date)
        except Exception as exc:  # noqa: BLE001 - absence is represented in outcomes
            logger.warning("[cache_refresh] daily batch unavailable: %s", exc)
            raw_daily_prices = None
            daily_batch_fetch_failed = True

    daily_batch_malformed = False
    try:
        if daily_batch_fetch_failed:
            raise PITEvidenceError("daily batch fetch failed")
        resolved_daily_prices = _normalize_daily_batch(raw_daily_prices)
        daily_batch_available = True
    except Exception as exc:  # noqa: BLE001 - malformed provider batches fail closed
        if not daily_batch_fetch_failed:
            logger.warning("[cache_refresh] malformed daily batch: %s", exc)
            daily_batch_malformed = True
        resolved_daily_prices = pd.DataFrame(columns=_DAILY_BATCH_COLUMNS)
        daily_batch_available = False

    daily_batch_fingerprint: str | None = None
    if daily_batch_available:
        try:
            daily_batch_fingerprint = _daily_batch_evidence_fingerprint(
                resolved_daily_prices,
                effective_trade_date,
            )
        except Exception as exc:  # noqa: BLE001 - malformed evidence must fail closed
            logger.warning("[cache_refresh] daily batch fingerprint failed: %s", exc)
            daily_batch_malformed = True
            daily_batch_available = False
            resolved_daily_prices = pd.DataFrame(columns=_DAILY_BATCH_COLUMNS)

    limit_up_tickers: list[str] = []
    if _env_enabled("DAILY_ACTION_INCLUDE_LIMIT_UPS", default=True):
        try:
            limit_up_tickers = _extract_limit_up_tickers(
                resolved_daily_prices,
                effective_trade_date,
            )
        except Exception as exc:  # noqa: BLE001 - conserve result on bad provider rows
            logger.warning("[cache_refresh] limit-up extraction failed: %s", exc)
            daily_batch_malformed = True
            daily_batch_available = False
            daily_batch_fingerprint = None
            resolved_daily_prices = pd.DataFrame(columns=_DAILY_BATCH_COLUMNS)
    injected = sorted(set(limit_up_tickers) - set(base_tickers))
    frozen_universe = tuple(sorted(set(base_tickers) | set(limit_up_tickers)))

    # Capture every baseline once after the universe is frozen and before any
    # cache write. These detached frames are the only baseline evidence used by
    # the result and by refresh writers in this run.
    price_dir = Path(price_cache_dir)
    flow_dir = Path(fund_flow_cache_dir)
    price_frames: dict[str, pd.DataFrame] = {}
    flow_frames: dict[str, pd.DataFrame] = {}
    price_full_frames: dict[str, pd.DataFrame] = {}
    flow_full_frames: dict[str, pd.DataFrame] = {}
    price_current: dict[str, bool] = {}
    flow_current: dict[str, bool] = {}
    price_read_failures: set[str] = set()
    flow_read_failures: set[str] = set()
    existing_price_tickers: set[str] = set()
    for ticker in frozen_universe:
        price_path = price_dir / f"{ticker}.csv"
        flow_path = flow_dir / f"{ticker}.csv"
        if price_path.exists():
            existing_price_tickers.add(ticker)
        full_price, captured_price, is_price_current, price_failed = _read_cache_baseline(
            price_path,
            effective_trade_date,
        )
        full_flow, captured_flow, is_flow_current, flow_failed = _read_cache_baseline(
            flow_path,
            effective_trade_date,
        )
        price_current[ticker] = is_price_current
        flow_current[ticker] = is_flow_current
        if price_failed:
            price_read_failures.add(ticker)
        else:
            price_full_frames[ticker] = full_price.copy(deep=True)
            price_frames[ticker] = captured_price.copy(deep=True)
        if flow_failed:
            flow_read_failures.add(ticker)
        else:
            flow_full_frames[ticker] = full_flow.copy(deep=True)
            flow_frames[ticker] = captured_flow.copy(deep=True)
    if injected:
        logger.info(
            "[cache_refresh] 涨停注入 %d 只: %s",
            len(injected),
            ", ".join(injected[:5]),
        )

    if suspension_loader is None:
        suspension_loader = load_suspension_evidence
    try:
        suspension_evidence = suspension_loader(effective_trade_date)
        if suspension_evidence.trade_date != trade_date_dt:
            raise ValueError("suspension evidence trade date mismatch")
    except Exception:  # noqa: BLE001 - unavailable remains distinct from empty
        logger.warning("[cache_refresh] suspension evidence unavailable", exc_info=True)
        suspension_evidence = SuspensionEvidence.unavailable(trade_date_dt)

    if refresh_industry_index is None:
        refresh_industry_index = _env_enabled("DAILY_ACTION_REFRESH_INDUSTRY_INDEX", default=True)
    industry_stats = DailyActionCacheRefreshStats()
    if refresh_industry_index:
        industry_stats = refresh_industry_index_cache(
            effective_trade_date,
            cache_dir=industry_index_cache_dir,
            backfill_fn=industry_index_backfill_fn,
        )

    written_price_frames: dict[str, pd.DataFrame] = {}
    price_stats = refresh_price_cache_from_daily_batch(
        effective_trade_date,
        price_cache_dir=price_cache_dir,
        daily_prices_df=resolved_daily_prices,
        target_tickers=frozen_universe,
        backfill_price_history_fn=backfill_price_history_fn,
        initial_frames=price_full_frames,
        initial_existing_tickers=existing_price_tickers,
        unreadable_tickers=price_read_failures,
        evidence_collector=written_price_frames,
    )
    for ticker, frame in written_price_frames.items():
        price_frames[ticker] = _project_pit_frame(frame, effective_trade_date)
        price_current[ticker] = _frame_has_current_row(
            price_frames[ticker], effective_trade_date
        )
    for ticker in price_stats.failed_tickers:
        price_frames.pop(ticker, None)
        price_current[ticker] = False

    if refresh_fund_flow is None:
        refresh_fund_flow = _env_enabled("DAILY_ACTION_REFRESH_FUND_FLOW", default=True)
    rate_limit = (
        fund_flow_rate_limit_sec
        if fund_flow_rate_limit_sec is not None
        else _env_float(
            "DAILY_ACTION_FUND_FLOW_RATE_LIMIT_SEC",
            default=_DEFAULT_FUND_FLOW_RATE_LIMIT_SEC,
        )
    )
    max_tickers = (
        fund_flow_max_tickers
        if fund_flow_max_tickers is not None
        else _env_int("DAILY_ACTION_FUND_FLOW_MAX_TICKERS", default=0)
    )

    priority = [ticker for ticker in sorted(set(limit_up_tickers)) if ticker in frozen_universe]
    priority.extend(ticker for ticker in frozen_universe if ticker not in set(priority))
    stale_flow_tickers: list[str] = []
    for ticker in priority:
        if ticker in suspension_evidence.tickers:
            continue
        if ticker in flow_read_failures:
            continue
        if not flow_current[ticker]:
            stale_flow_tickers.append(ticker)

    selected_flow_tickers = list(stale_flow_tickers)
    quota_omitted: set[str] = set()
    if max_tickers > 0:
        selected_flow_tickers = stale_flow_tickers[:max_tickers]
        quota_omitted = set(stale_flow_tickers[max_tickers:])

    fund_flow_stats = DailyActionCacheRefreshStats()
    written_flow_frames: dict[str, pd.DataFrame] = {}
    if refresh_fund_flow and selected_flow_tickers:
        fund_flow_stats = refresh_fund_flow_cache(
            selected_flow_tickers,
            effective_trade_date,
            fund_flow_cache_dir=fund_flow_cache_dir,
            fetch_fn=fund_flow_fetch_fn,
            rate_limit_sec=rate_limit,
            max_tickers=0,
            suspension_evidence=suspension_evidence,
            initial_frames=flow_full_frames,
            unreadable_tickers=flow_read_failures,
            evidence_collector=written_flow_frames,
        )
    for ticker, frame in written_flow_frames.items():
        flow_frames[ticker] = _project_pit_frame(frame, effective_trade_date)
        flow_current[ticker] = _frame_has_current_row(
            flow_frames[ticker], effective_trade_date
        )
    for ticker in fund_flow_stats.failed_tickers:
        flow_frames.pop(ticker, None)
        flow_current[ticker] = False

    outcomes: dict[str, TickerRefreshOutcome] = {}
    price_failed = set(price_stats.failed_tickers)
    flow_failed = set(fund_flow_stats.failed_tickers)
    suspension_warning = (
        ("suspension_evidence_unavailable",)
        if suspension_evidence.status.value == "unavailable"
        else ()
    )
    for ticker in frozen_universe:
        price_frame = price_frames.get(ticker, pd.DataFrame())
        flow_frame = flow_frames.get(ticker, pd.DataFrame())
        price_evidence_invalid = False
        flow_evidence_invalid = False
        evidence_fingerprints: dict[str, str] = {}
        if not price_frame.empty:
            try:
                evidence_fingerprints["price"] = canonical_price_fingerprint(
                    price_frame,
                    ticker,
                    effective_trade_date,
                )
            except PITEvidenceError:
                price_evidence_invalid = True
        if not flow_frame.empty:
            try:
                evidence_fingerprints["fund_flow"] = canonical_flow_fingerprint(
                    flow_frame,
                    ticker,
                    effective_trade_date,
                )
            except PITEvidenceError:
                flow_evidence_invalid = True

        if ticker in suspension_evidence.tickers:
            price_status = PriceStatus.SUSPENDED
            flow_status = FundFlowStatus.SUSPENDED
        else:
            if daily_batch_malformed:
                price_status = PriceStatus.FAILED
            elif (
                ticker in price_read_failures
                or ticker in price_failed
                or price_evidence_invalid
            ):
                price_status = PriceStatus.FAILED
            elif price_current[ticker]:
                price_status = PriceStatus.CURRENT
            else:
                price_status = PriceStatus.MISSING_UNEXPLAINED

            if (
                ticker in flow_read_failures
                or ticker in flow_failed
                or flow_evidence_invalid
            ):
                flow_status = FundFlowStatus.FAILED
            elif flow_current[ticker]:
                flow_status = FundFlowStatus.CURRENT
            elif not refresh_fund_flow or ticker in quota_omitted:
                flow_status = FundFlowStatus.NOT_ATTEMPTED
            else:
                flow_status = FundFlowStatus.MISSING_UNEXPLAINED

        if price_status is PriceStatus.FAILED:
            evidence_fingerprints.pop("price", None)
        if flow_status is FundFlowStatus.FAILED:
            evidence_fingerprints.pop("fund_flow", None)

        outcomes[ticker] = TickerRefreshOutcome(
            ticker=ticker,
            price_status=price_status,
            price_history_rows=len(price_frame),
            fund_flow_status=flow_status,
            fund_flow_history_rows=len(flow_frame),
            evidence_fingerprints=evidence_fingerprints,
            warnings=suspension_warning,
        )

    legacy_stats = DailyActionCacheRefreshStats(limit_up_injected=len(injected))
    legacy_stats.merge(industry_stats).merge(price_stats).merge(fund_flow_stats)
    return DailyActionRefreshResult(
        trade_date=trade_date_dt,
        universe_tickers=frozen_universe,
        universe_fingerprint=universe_fingerprint(frozen_universe),
        daily_batch_fingerprint=daily_batch_fingerprint,
        suspension_evidence=suspension_evidence,
        outcomes=outcomes,
        stats=derive_stats_from_outcomes(
            outcomes,
            industry_index_total=industry_stats.industry_index_total,
            industry_index_failed=industry_stats.industry_index_failed,
            limit_up_injected=len(injected),
        ),
        _refresh_counters=legacy_stats.to_dict(),
    )
