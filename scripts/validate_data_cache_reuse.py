from __future__ import annotations

import argparse
import json

from src.data.enhanced_cache import diff_cache_stats, get_cache_runtime_info, snapshot_cache_stats
from src.tools.tushare_api import get_all_stock_basic, get_daily_basic_batch, get_limit_list, get_stock_details, get_suspend_list


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate cross-process reuse of persisted market-data cache.")
    parser.add_argument("--trade-date", required=True, help="Trade date in YYYYMMDD format")
    parser.add_argument("--ticker", default="000001", help="Ticker used for detail lookup")
    parser.add_argument("--output", default=None, help="Optional path to write JSON payload")
    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    before = snapshot_cache_stats()

    stock_basic = get_all_stock_basic()
    daily_basic = get_daily_basic_batch(args.trade_date)
    limit_list = get_limit_list(args.trade_date)
    suspend_list = get_suspend_list(args.trade_date)
    stock_details = get_stock_details(args.ticker, args.trade_date)

    runtime_info = get_cache_runtime_info()
    payload = {
        "trade_date": args.trade_date,
        "ticker": args.ticker,
        "cache_runtime": runtime_info,
        "session_stats": diff_cache_stats(before, runtime_info.get("stats", {})),
        "result_shapes": {
            "stock_basic_rows": int(len(stock_basic)) if stock_basic is not None else 0,
            "daily_basic_rows": int(len(daily_basic)) if daily_basic is not None else 0,
            "limit_list_rows": int(len(limit_list)) if limit_list is not None else 0,
            "suspend_list_rows": int(len(suspend_list)) if suspend_list is not None else 0,
        },
        "stock_details": stock_details,
    }

    if args.output:
        with open(args.output, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)

    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()