from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from src.data.cache_benchmark import run_cache_reuse_benchmark


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Benchmark cold-vs-warm reuse of the persisted market-data cache.")
    parser.add_argument("--trade-date", required=True, help="Trade date in YYYYMMDD format")
    parser.add_argument("--ticker", default="000001", help="Ticker used for detail lookup")
    parser.add_argument("--clear-first", action="store_true", help="Clear the local cache before the first run to force a cold start")
    parser.add_argument("--output", default=None, help="Optional path to write the benchmark JSON payload")
    parser.add_argument("--markdown-output", default=None, help="Optional path to write a Markdown summary")
    parser.add_argument("--append-markdown-to", default=None, help="Optional existing Markdown report to append the summary to")
    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    payload = run_cache_reuse_benchmark(
        repo_root=repo_root,
        python_executable=sys.executable,
        trade_date=args.trade_date,
        ticker=args.ticker,
        clear_first=args.clear_first,
        output_path=args.output,
        markdown_output_path=args.markdown_output,
        append_markdown_to=args.append_markdown_to,
    )

    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()