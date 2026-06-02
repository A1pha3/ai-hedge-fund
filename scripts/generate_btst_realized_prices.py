from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd

from scripts.btst_data_utils import normalize_price_frame
from src.project_env import load_project_dotenv
from src.tools.akshare_api import get_prices_robust
from src.tools.api import get_price_data, prices_to_df

load_project_dotenv()


def _read_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write_json(path: str | Path, payload: Any) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _normalize_date(value: Any) -> str:
    token = str(value or "").strip()
    if len(token) == 8 and token.isdigit():
        return f"{token[:4]}-{token[4:6]}-{token[6:8]}"
    return token


def _fetch_price_frame(ticker: str, trade_date: str, end_date: str) -> pd.DataFrame:
    try:
        return normalize_price_frame(get_price_data(ticker, trade_date, end_date))
    except Exception:
        try:
            return normalize_price_frame(prices_to_df(get_prices_robust(ticker, trade_date, end_date, use_mock_on_fail=False)))
        except Exception:
            return pd.DataFrame()


def compute_realized_prices_for_ticker(
    *,
    ticker: str,
    signal_date: str,
    price_cache: dict[tuple[str, str], pd.DataFrame],
) -> dict[str, Any]:
    """Compute realized next-day returns for a BTST signal date.

    Semantics:
    - signal_date: the date the signal is generated (T, close known)
    - next-day open/high/close are taken from the first bar strictly after signal_date
    - returns are computed vs T close (trade_close), matching existing ledger fill semantics
    - also surfaces a 5D max-high return vs entry (T+1 open) for BTST objective audits
    """

    normalized_date = _normalize_date(signal_date)
    cache_key = (str(ticker), normalized_date)
    frame = price_cache.get(cache_key)
    if frame is None:
        end_date = (pd.Timestamp(normalized_date) + pd.Timedelta(days=14)).strftime("%Y-%m-%d")
        frame = _fetch_price_frame(str(ticker), normalized_date, end_date)
        price_cache[cache_key] = frame

    if frame.empty:
        return {"data_status": "missing_price_frame"}

    trade_ts = pd.Timestamp(normalized_date).normalize()
    same_day = frame.loc[frame.index == trade_ts]
    next_days = frame.loc[frame.index > trade_ts]

    if same_day.empty:
        return {"data_status": "missing_trade_day_bar"}
    if next_days.empty:
        return {"data_status": "missing_next_trade_day_bar"}

    trade_row = same_day.iloc[0]
    next_row = next_days.iloc[0]

    trade_close = float(trade_row.get("close")) if trade_row.get("close") is not None else None
    next_open = float(next_row.get("open")) if next_row.get("open") is not None else None
    next_high = float(next_row.get("high")) if next_row.get("high") is not None else None
    next_close = float(next_row.get("close")) if next_row.get("close") is not None else None

    if trade_close is None or trade_close <= 0 or next_open is None or next_high is None or next_close is None:
        return {"data_status": "incomplete_price_bar"}

    next_trade_date = next_days.index[0].strftime("%Y-%m-%d")

    horizon = next_days.iloc[:5]
    max_high_from_open = None
    max_high_trade_date = None
    if not horizon.empty and next_open > 0:
        highs = horizon.get("high")
        if highs is not None:
            series = pd.Series(highs).dropna().astype(float)
            if not series.empty:
                max_high_value = float(series.max())
                # use first occurrence for determinism
                max_idx = horizon.loc[horizon["high"].astype(float) == max_high_value].index[0]
                max_high_trade_date = max_idx.strftime("%Y-%m-%d")
                max_high_from_open = round((max_high_value / next_open) - 1.0, 6)

    return {
        "data_status": "ok",
        "signal_date": normalized_date,
        "next_trade_date": next_trade_date,
        "trade_close": round(trade_close, 4),
        "next_open": round(next_open, 4),
        "next_high": round(next_high, 4),
        "next_close": round(next_close, 4),
        "next_open_return": round((next_open / trade_close) - 1.0, 6),
        "next_high_return": round((next_high / trade_close) - 1.0, 6),
        "next_close_return": round((next_close / trade_close) - 1.0, 6),
        "next_open_to_close_return": round((next_close / next_open) - 1.0, 6),
        "max_high_t1_t5_from_open": max_high_from_open,
        "max_high_t1_t5_trade_date": max_high_trade_date,
    }


def generate_realized_prices(*, signal_date: str, tickers: list[str]) -> dict[str, dict[str, Any]]:
    price_cache: dict[tuple[str, str], pd.DataFrame] = {}
    result: dict[str, dict[str, Any]] = {}
    for ticker in tickers:
        ticker_str = str(ticker).strip()
        if not ticker_str:
            continue
        result[ticker_str] = compute_realized_prices_for_ticker(
            ticker=ticker_str,
            signal_date=signal_date,
            price_cache=price_cache,
        )
    return result


def _extract_tickers_from_ledger(payload: dict[str, Any]) -> list[str]:
    rows = payload.get("rows") or []
    if not isinstance(rows, list):
        return []
    tickers: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        t = str(row.get("ticker") or "").strip()
        if t:
            tickers.append(t)
    # stable unique
    seen: set[str] = set()
    out: list[str] = []
    for t in tickers:
        if t in seen:
            continue
        seen.add(t)
        out.append(t)
    return out


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate realized BTST next-day returns for ledger backfill.")
    parser.add_argument("--signal-date", help="Signal date (YYYYMMDD or YYYY-MM-DD). Optional when using --ledger-path.")
    parser.add_argument("--tickers", help="Comma-separated tickers. Optional when using --ledger-path.")
    parser.add_argument("--ledger-path", help="Ledger JSON path to read tickers + signal_date from.")
    parser.add_argument("--output-path", required=True, help="Output realized-prices JSON path")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()

    tickers: list[str] = []
    signal_date: str | None = _normalize_date(args.signal_date) if args.signal_date else None

    if args.ledger_path:
        ledger = _read_json(args.ledger_path)
        if signal_date is None:
            signal_date = _normalize_date(ledger.get("signal_date"))
        tickers = _extract_tickers_from_ledger(ledger)

    if args.tickers:
        tickers = [token.strip() for token in str(args.tickers).split(",") if token.strip()]

    if not signal_date:
        raise SystemExit("Missing --signal-date (or ledger must include signal_date)")
    if not tickers:
        raise SystemExit("No tickers to compute (pass --tickers or --ledger-path with rows[].ticker)")

    payload = generate_realized_prices(signal_date=signal_date, tickers=tickers)
    _write_json(args.output_path, payload)
    print(json.dumps({"status": "ok", "signal_date": signal_date, "tickers": len(payload)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
