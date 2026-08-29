#!/usr/bin/env python3
"""研究数据面新鲜度仪表 (R58, 只读).

对五类研究数据集核对「最新覆盖会话 vs 权威日历期望会话」:
  - bars        data/research/btst_court/raw/daily/daily_YYYYMMDD.csv (逐会话, 文件名精确)
  - lhb         data/lhb_cache/YYYYMMDD.csv (逐会话, 表头空文件计为已覆盖)
  - price_cache     bulk 目录, 以文件 mtime 日期为 as-of (18:01 管道整目录刷新)
  - fund_flow_cache bulk 目录, mtime 日期
  - industry_index  bulk 目录, mtime 日期

期望会话 = 权威日历中**今日之前**的最近已完成交易日 (T-1 语义 — 保证「今晨
睁眼有昨日数据」; 若以今日为期望, 交易日早晨 18:01 管道未跑前必假响)。
日历缺失/不可读/过期 → 类型化拒绝 rc=2 (R57 同款: 分类不可信即运维缺口)。
退出码 = 陈旧数据集数 (0..5, 响亮); 每数据集输出 latest/expected/stale。
只读: 绝不写任何数据面文件。

用法:
    uv run python scripts/research_freshness.py [--json] [--today YYYYMMDD]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import date, datetime
from pathlib import Path

from fetch_lhb_daily import LhbFetchError, expected_session

REPO_ROOT = Path(__file__).resolve().parent.parent

# (名称, 相对 repo-root 路径, 语义) — session: 逐会话文件名精确; bulk: 目录 mtime 日期
DATASETS = [
    ("bars", "data/research/btst_court/raw/daily", "session"),
    ("lhb", "data/lhb_cache", "session"),
    ("price_cache", "data/price_cache", "bulk"),
    ("fund_flow_cache", "data/fund_flow_cache", "bulk"),
    ("industry_index", "data/industry_index_cache", "bulk"),
]

SESSION_FILE_PREFIXES = {"bars": "daily_", "lhb": ""}


def _latest_session_file(directory: Path, prefix: str) -> str | None:
    """逐会话语义: 目录内会话命名文件的最大 YYYYMMDD。"""
    if not directory.is_dir():
        return None
    sessions = []
    for p in directory.iterdir():
        stem = p.stem
        if prefix and not stem.startswith(prefix):
            continue
        token = stem[len(prefix):] if prefix else stem
        if len(token) == 8 and token.isdigit():
            sessions.append(token)
    return max(sessions) if sessions else None


def _latest_bulk_mtime_date(directory: Path) -> str | None:
    """bulk 语义: 目录内文件的最大 mtime 日期 (YYYYMMDD)。空目录 None。"""
    if not directory.is_dir():
        return None
    latest = None
    for p in directory.iterdir():
        if not p.is_file():
            continue
        day = datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y%m%d")
        if latest is None or day > latest:
            latest = day
    return latest


def check_freshness(
    *, repo_root: Path, calendar_path: Path, today: str
) -> dict:
    """返回 {datasets: [...], expected_session}。日历问题抛 LhbFetchError。"""
    expected = expected_session(calendar_path, today)
    rows = []
    for name, relpath, semantics in DATASETS:
        path = repo_root / relpath
        if name in SESSION_FILE_PREFIXES:
            latest = _latest_session_file(path, SESSION_FILE_PREFIXES[name])
        else:
            latest = _latest_bulk_mtime_date(path)
        rows.append({
            "dataset": name,
            "path": str(path),
            "semantics": semantics,
            "latest": latest,
            "expected": expected,
            "stale": latest is None or latest < expected,
        })
    return {"today": today, "expected_session": expected, "datasets": rows}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo-root", default=str(REPO_ROOT))
    parser.add_argument("--calendar", default=None,
                        help="默认 <repo-root>/data/reports/trade_calendar.json")
    parser.add_argument("--today", default=time.strftime("%Y%m%d"))
    parser.add_argument("--json", action="store_true", help="仅输出 JSON")
    args = parser.parse_args()

    calendar = Path(args.calendar or Path(args.repo_root) / "data/reports/trade_calendar.json")
    try:
        report = check_freshness(
            repo_root=Path(args.repo_root),
            calendar_path=calendar,
            today=args.today,
        )
    except LhbFetchError as exc:
        print(json.dumps({"ok": False, "code": exc.code, "details": exc.details},
                         ensure_ascii=False))
        return 2

    stale = [r for r in report["datasets"] if r["stale"]]
    payload = {"ok": len(stale) == 0, "stale_count": len(stale), **report}
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=1))
        return len(stale)

    print(f"期望会话: {report['expected_session']} (today={report['today']})")
    for row in report["datasets"]:
        mark = "陈旧" if row["stale"] else "鲜"
        latest = row["latest"] or "缺失"
        print(f"  [{mark}] {row['dataset']:16s} latest={latest} expected={row['expected']}"
              f" ({row['semantics']})")
    if stale:
        print(f"新鲜度门: {len(stale)} 个数据集陈旧 (rc={len(stale)})", file=sys.stderr)
    else:
        print("新鲜度门: 全部鲜 (rc=0)")
    return len(stale)


if __name__ == "__main__":
    raise SystemExit(main())
