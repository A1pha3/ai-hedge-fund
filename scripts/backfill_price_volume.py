"""backfill price_cache 的 volume 列 (tushare daily vol 字段).

背景: OversoldBounce 条件3 (量比>1.5) 因 price_cache 缺 volume 列而静默降级.
本脚本给现有 CSV 补 volume 列 (按 date 对齐 merge), 不破坏已有数据.

幂等: CSV 已有 volume 列则跳过.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pandas as pd

_PRICE_CACHE = Path("data/price_cache/")
_CANDIDATE_POOL = Path("data/snapshots/candidate_pool_20260527_top300.json")


def _load_token() -> str:
    if os.path.exists(".env"):
        for line in Path(".env").read_text(encoding="utf-8").splitlines():
            if line.startswith("TUSHARE_TOKEN="):
                return line.split("=", 1)[1].strip().strip("'\"")
    return os.environ.get("TUSHARE_TOKEN", "")


def _ts_suffix(ticker: str) -> str:
    return ".SZ" if ticker.startswith(("0", "3")) else ".SH"


def backfill_volume(ticker: str, pro=None, sleep: float = 0.12) -> str:
    """给单只 ticker 的 price_cache CSV 补 volume 列.

    Returns: "added" / "skipped_exists" / "failed_no_cache" / "failed_fetch" / "failed_merge"
    """
    cache_file = _PRICE_CACHE / f"{ticker}.csv"
    if not cache_file.exists():
        return "failed_no_cache"

    df = pd.read_csv(cache_file, dtype={"date": str})
    if "volume" in df.columns:
        return "skipped_exists"  # 幂等

    # 拉 tushare daily 全量 (含 vol)
    if pro is None:
        import tushare as ts

        ts.set_token(_load_token())
        pro = ts.pro_api()

    try:
        suffix = _ts_suffix(ticker)
        start = str(df["date"].min()).replace("-", "")
        end = str(df["date"].max()).replace("-", "")
        raw = pro.daily(ts_code=f"{ticker}{suffix}", start_date=start, end_date=end)
        time.sleep(sleep)  # tushare 限频
    except Exception as e:
        print(f"  {ticker}: fetch 失败 {e}")
        return "failed_fetch"

    if raw is None or len(raw) == 0:
        print(f"  {ticker}: tushare 返回空")
        return "failed_fetch"

    # 对齐: tushare trade_date (YYYYMMDD) ↔ CSV date (YYYY-MM-DD)
    raw["date"] = pd.to_datetime(raw["trade_date"], format="%Y%m%d").dt.strftime("%Y-%m-%d")
    vol_map = dict(zip(raw["date"], raw["vol"].astype(float)))
    df["volume"] = df["date"].map(vol_map)

    missing = df["volume"].isna().sum()
    if missing == len(df):
        print(f"  {ticker}: merge 后 volume 全 NaN (date 对齐失败)")
        return "failed_merge"

    df.to_csv(cache_file, index=False)
    miss_pct = missing / len(df) * 100 if len(df) > 0 else 0
    print(f"  {ticker}: volume 已补 ({len(df)-missing}/{len(df)} 行, {miss_pct:.1f}% 缺失)")
    return "added"


def main() -> None:
    pool = json.loads(_CANDIDATE_POOL.read_text(encoding="utf-8"))
    tickers = [d["ticker"] for d in pool if isinstance(d, dict) and d.get("ticker")]
    print(f"候选池: {len(tickers)} ticker")

    import tushare as ts

    ts.set_token(_load_token())
    pro = ts.pro_api()

    counts = {"added": 0, "skipped_exists": 0, "failed_no_cache": 0, "failed_fetch": 0, "failed_merge": 0}
    for i, t in enumerate(tickers, 1):
        result = backfill_volume(t, pro=pro)
        counts[result] = counts.get(result, 0) + 1
        if i % 50 == 0:
            print(f"  进度 {i}/{len(tickers)}: {counts}")

    print(f"\n完成: {counts}")


if __name__ == "__main__":
    main()
