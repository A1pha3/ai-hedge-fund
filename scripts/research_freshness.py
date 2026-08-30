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

import pandas as pd

from fetch_lhb_daily import LhbFetchError, expected_session, load_calendar_sessions

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from _btst_court_common import load_regime_history, regime_drift_status  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent

# (名称, 相对 repo-root 路径, 语义) — session: 逐会话文件名精确; bulk: 目录 mtime 日期;
# court: 事件表内 max signal_date (R72; 容差见 COURT_LAG_TOLERANCE)
DATASETS = [
    ("bars", "data/research/btst_court/raw/daily", "session"),
    ("lhb", "data/lhb_cache", "session"),
    ("court", "data/research/btst_court/event_tables/event_table_v1.csv.gz", "court"),
    ("price_cache", "data/price_cache", "bulk"),
    ("fund_flow_cache", "data/fund_flow_cache", "bulk"),
    ("industry_index", "data/industry_index_cache", "bulk"),
]

SESSION_FILE_PREFIXES = {"bars": "daily_", "lhb": ""}
# court 语义: 构建一般可达 T-1; 连续落后 >3 会话才响 (单晚失败次夜自愈不噪音)
COURT_LAG_TOLERANCE = 3


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


def _latest_court_signal(path: Path) -> str | None:
    """court 语义: 事件表内 max signal_date (gz 读取)。缺失/不可读 None。"""
    if not path.is_file():
        return None
    try:
        frame = pd.read_csv(path, usecols=["signal_date"])
    except (OSError, ValueError):  # 文件缺失/损坏等数据面错误 → None (陈旧)
        return None
    if frame.empty:
        return None
    dates = frame["signal_date"].astype(str)
    return dates.max() if len(dates) else None


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
    *, repo_root: Path, calendar_path: Path, today: str,
    regime_history: dict[str, str] | None = None,
) -> dict:
    """返回 {datasets: [...], expected_session}。日历问题抛 LhbFetchError。"""
    expected = expected_session(calendar_path, today)
    # court 容差锚: 期望会话回移 COURT_LAG_TOLERANCE 个会话 (单晚失败次夜自愈)
    sessions = load_calendar_sessions(calendar_path)
    exp_idx = sessions.index(expected)
    court_floor = sessions[max(0, exp_idx - COURT_LAG_TOLERANCE)]
    rows = []
    for name, relpath, semantics in DATASETS:
        path = repo_root / relpath
        if name in SESSION_FILE_PREFIXES:
            latest = _latest_session_file(path, SESSION_FILE_PREFIXES[name])
        elif semantics == "court":
            latest = _latest_court_signal(path)
        else:
            latest = _latest_bulk_mtime_date(path)
        floor = court_floor if semantics == "court" else expected
        row = {
            "dataset": name,
            "path": str(path),
            "semantics": semantics,
            "latest": latest,
            "expected": expected,
            "stale": latest is None or latest < floor,
        }
        if semantics == "court":
            # R73: court 重建消费的 regime 输入 vs 当前 regime_history —
            # 历史标签修订会静默改变评估宇宙; 漂移必须响亮而非沉默.
            manifest_path = path.parent / "manifest_v1.json"
            if manifest_path.is_file():
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                history = (regime_history if regime_history is not None
                           else load_regime_history())
                row["regime_drift"] = regime_drift_status(manifest, history)
            else:
                row["regime_drift"] = {"checked": False, "drift": False,
                                       "changed_sessions": []}
        rows.append(row)
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
