"""gap 影子记录 CLI (R199 Op1) — 从生产 v2 台账回填影子归属事实。

生产 --daily-action 的计划台账在 paper_trading_v2/ledger.sqlite3 (legacy
paper journal 已不被生产写入); 本 CLI 把尚无影子记录的 v2 计划落成 T+1
gap 归属事实 (append-only, 幂等键 (signal_date, ticker) 跨源首观察赢),
夜刷链在 gap_shadow_pack 之前运行 (先记录后读数)。

使用纪律: 纯披露 (宪法 #2) — 只记录 T+1 开盘 gap 事实, 零买卖行为变化。
缺文件/损坏 → 类型化错误 rc=2 (fail-closed, 夜刷链 fail-open 消费)。

用法::

    uv run python scripts/gap_shadow_record.py [--journal-dir data/paper_trading]
        [--ledger data/paper_trading_v2/ledger.sqlite3] [--as-of YYYYMMDD]
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.screening.offensive.gap_shadow import (  # noqa: E402
    GAP_SHADOW_FILENAME,
    GapShadowLedgerError,
    append_shadow_records,
    build_shadow_records_from_ledger,
    load_shadow_entries,
    read_ledger_trades,
    shadow_keys,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--journal-dir", default="data/paper_trading")
    parser.add_argument("--ledger", default="data/paper_trading_v2/ledger.sqlite3")
    parser.add_argument("--as-of", default="", help="观测基准日 (缺省 = 今天, 无墙钟进内容)")
    parser.add_argument("--price-cache-dir", default="data/price_cache")
    args = parser.parse_args()

    journal_dir = Path(args.journal_dir)
    if not journal_dir.is_absolute():
        journal_dir = _PROJECT_ROOT / journal_dir
    ledger = Path(args.ledger)
    if not ledger.is_absolute():
        ledger = _PROJECT_ROOT / ledger
    as_of = args.as_of.replace("-", "") or date.today().strftime("%Y%m%d")

    from src.screening.offensive.daily_action import _load_prices_for_ticker

    entries = load_shadow_entries(journal_dir / GAP_SHADOW_FILENAME)
    trades = read_ledger_trades(ledger)
    records, summary = build_shadow_records_from_ledger(
        trades,
        shadow_keys(entries),
        as_of,
        _load_prices_for_ticker,
    )
    summary["appended"] = append_shadow_records(journal_dir / GAP_SHADOW_FILENAME, records) if records else 0
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except GapShadowLedgerError as exc:
        print(f"gap_shadow_record: {exc}", file=sys.stderr)
        raise SystemExit(2)
