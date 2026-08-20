#!/usr/bin/env python3
"""市场事实播种器 — 前向 Trial Phase 5b (2026-08-20).

把播种源 (court raw 日快照 CSV) 的行情发布为 bar-set 证据 (Phase 5a 的
MarketBarSetPublisher + 离线 ephemeral rig)。重放组装器只查证据库 —
本脚本是把研究面数据搬上证据时间轴的唯一入口 (宪法 12: cutoff 可证).

价格换算: 源文件元价格 → 分 (×100 round); 围栏 = 前收 × 板块幅度
(limit_up_cap_pct_for_ticker, 脚本层可用 v2 工具 — 证据层不用).

离线 primitive: ephemeral signer 非生产身份; 不启动 Trial, 不构成权限.

用法:
    uv run python scripts/v3_seed_market_bars.py --source data/research/btst_court/raw/daily \\
        --evidence PATH --start 20250702 --end 20260818 [--namespace market-bars]
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

import pandas as pd

from src.screening.offensive.v3.evidence.offline_rig import build_offline_evidence_rig
from src.screening.offensive.v3.execution.lifecycle import DailyBar
from src.tools.ashare_board_utils import limit_up_cap_pct_for_ticker


def bars_from_court_csv(csv_path: Path, session: date) -> dict[str, DailyBar]:
    df = pd.read_csv(csv_path, dtype={"trade_date": str})
    out: dict[str, DailyBar] = {}
    for row in df.itertuples(index=False):
        ts_code = str(row.ts_code)
        symbol = ts_code.split(".")[0]
        open_c = round(float(row.open) * 100)
        high_c = round(float(row.high) * 100)
        low_c = round(float(row.low) * 100)
        close_c = round(float(row.close) * 100)
        pre_c = round(float(row.pre_close) * 100)
        cap = limit_up_cap_pct_for_ticker(symbol)
        out[ts_code] = DailyBar(
            security_id=ts_code, session=session,
            open_cents=open_c, high_cents=high_c, low_cents=low_c, close_cents=close_c,
            limit_up_cents=round(pre_c * (1 + cap / 100)),
            limit_down_cents=round(pre_c * (1 - cap / 100)),
        )
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Seed market bar-set evidence from court raw snapshots")
    ap.add_argument("--source", required=True, type=Path, help="court raw daily 目录 (daily_YYYYMMDD.csv)")
    ap.add_argument("--evidence", required=True, type=Path, help="目标 evidence sqlite 路径")
    ap.add_argument("--start", required=True, type=lambda s: date(int(s[:4]), int(s[4:6]), int(s[6:8])))
    ap.add_argument("--end", required=True, type=lambda s: date(int(s[:4]), int(s[4:6]), int(s[6:8])))
    ap.add_argument("--namespace", default="market-bars")
    ap.add_argument("--max-sessions", type=int, default=0, help=">0 时只播前 N 个会话 (增量调试用)")
    args = ap.parse_args(argv)

    if not args.source.is_dir():
        print(json.dumps({"error": "source_missing", "path": str(args.source)}), file=sys.stderr)
        return 2
    args.evidence.parent.mkdir(parents=True, exist_ok=True)
    rig = build_offline_evidence_rig(
        database_path=args.evidence, blobs_dir=args.evidence.parent / "blobs",
        namespace=args.namespace,
    )

    files = sorted(args.source.glob("daily_*.csv"))
    published = skipped = 0
    for f in files:
        stem = f.stem.split("_")[1]
        if not (args.start.strftime("%Y%m%d") <= stem <= args.end.strftime("%Y%m%d")):
            continue
        session = date(int(stem[:4]), int(stem[4:6]), int(stem[6:8]))
        bars = bars_from_court_csv(f, session)
        if not bars:
            skipped += 1
            continue
        rig.bar_publisher.publish(session=session, bars=bars)
        published += 1
        if args.max_sessions and published >= args.max_sessions:
            break
    print(json.dumps({"published_sessions": published, "skipped_empty": skipped,
                      "evidence": str(args.evidence)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
