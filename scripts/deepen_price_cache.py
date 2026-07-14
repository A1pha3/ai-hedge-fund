"""Deepen data/price_cache to 2020 for cross-cycle backtests.

The runtime price_cache is only ~6 months deep, which blocks any full-cycle
(bull/bear) backtest (AGENTS.md: setup_research.py returns n=0). This fetches the
full 2020-01-01 -> today daily history for each existing price_cache ticker via
tushare and writes a SAFE MERGE:

  - only overwrites when the deep fetch is valid (>=200 rows);
  - preserves any recent bars the deep fetch does not cover (e.g. today's
    limit-up-injected signal bar that pro.daily lags by a day) so the live
    --daily-action snapshot is never corrupted;
  - skips tickers already deep (idempotent / resumable);
  - preserves the existing file on any failure.

price_cache is gitignored, so this does not touch version control.

Run:
    uv run python scripts/deepen_price_cache.py
"""

from __future__ import annotations

import glob
import time
from datetime import date
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

load_dotenv()

from src.tools.tushare_api import get_tushare_token  # noqa: E402
from src.tools.ashare_board_utils import is_beijing_exchange_stock  # noqa: E402
from src.utils.atomic_files import atomic_write_csv  # noqa: E402

START = "20200101"
COLUMNS = ["date", "close", "open", "high", "low", "pct_change", "volume"]
ALREADY_DEEP_ON_OR_BEFORE = "20200210"


def _suffix(ticker: str) -> str:
    if ticker.startswith(("43", "83", "87", "92", "8", "4")):
        return ".BJ"
    return ".SZ" if ticker.startswith(("0", "3")) else ".SH"


def _deep_frame(raw: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": pd.to_datetime(raw["trade_date"], format="%Y%m%d").dt.strftime("%Y-%m-%d"),
            "close": raw["close"].astype(float),
            "open": raw["open"].astype(float),
            "high": raw["high"].astype(float),
            "low": raw["low"].astype(float),
            "pct_change": raw["pct_chg"].astype(float),
            "volume": raw["vol"].astype(float),
        }
    )


def deepen_one(pro, path: Path, ticker: str, end: str) -> str:
    existing = None
    if path.exists():
        try:
            existing = pd.read_csv(path)
        except Exception:
            existing = None
    if existing is not None and "date" in existing.columns and len(existing):
        oldest = str(existing["date"].astype(str).min()).replace("-", "")[:8]
        if oldest <= ALREADY_DEEP_ON_OR_BEFORE:
            return "skip"
    try:
        raw = pro.daily(ts_code=f"{ticker}{_suffix(ticker)}", start_date=START, end_date=end)
    except Exception:
        return "fail"
    if raw is None or len(raw) < 200:  # too shallow to trust → keep existing
        return "fail"
    deep = _deep_frame(raw)
    if existing is not None and set(COLUMNS).issubset(existing.columns):
        deep_max = deep["date"].max()
        newer = existing[existing["date"].astype(str) > deep_max][COLUMNS]
        merged = pd.concat([deep[COLUMNS], newer], ignore_index=True)
    else:
        merged = deep[COLUMNS]
    merged = merged.drop_duplicates(subset="date").sort_values("date").reset_index(drop=True)
    atomic_write_csv(path, merged)
    return "deepen"


def main() -> None:
    token = get_tushare_token()
    if not token:
        raise SystemExit("no TUSHARE_TOKEN in environment")
    import tushare as ts

    pro = ts.pro_api(token=token)
    end = date.today().strftime("%Y%m%d")
    files = sorted(glob.glob("data/price_cache/*.csv"))
    tickers = [
        p
        for p in files
        if Path(p).stem.isdigit()
        and len(Path(p).stem) == 6
        and not is_beijing_exchange_stock(symbol=Path(p).stem)
    ]

    counts = {"deepen": 0, "skip": 0, "fail": 0}
    for i, path in enumerate(tickers, 1):
        p = Path(path)
        result = deepen_one(pro, p, p.stem, end)
        counts[result] += 1
        if result == "deepen":
            time.sleep(0.13)  # be gentle on the trade_cal rate limit
        if i % 50 == 0:
            print(f"  {i}/{len(tickers)}  deepen={counts['deepen']} skip={counts['skip']} fail={counts['fail']}")
    print(f"done: deepen={counts['deepen']} skip={counts['skip']} fail={counts['fail']} / {len(tickers)}")


if __name__ == "__main__":
    main()
