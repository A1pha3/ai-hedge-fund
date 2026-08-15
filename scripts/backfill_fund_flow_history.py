#!/usr/bin/env python
"""fund_flow 历史回填 (2022-01 → 2025-07) — 补齐 regime gate 跨期验证的唯一数据缺口.

设计要点:
- 全市场批量端点 (moneyflow(trade_date=...)), 每个交易日 1 次 API 调用,
  而不是 5400 次逐票调用.
- 月度批次: 每月 ~20 次调用后做一次 per-ticker 合并落盘; 月进度写入进度文件,
  中断重跑自动跳过已完成月 (FundFlowStore.save 按 date 去重, 幂等).
- 只写 [start, end] 内的日期; 与既有缓存 (2025-07-07 起) 不相交, 追加式安全.
- 宇宙默认 = price_cache 的 1594 只 (court 回测宇宙), 不是 fund_flow_cache
  的 5244 只超集 — 节省 3 倍落盘开销; 需要全量时传 --universe-fund-flow-cache.

用法:
    # 先看计划 (不触网)
    .venv/bin/python scripts/backfill_fund_flow_history.py --dry-run
    # 2 天冒烟 (写入 --cache-dir 指定目录)
    .venv/bin/python scripts/backfill_fund_flow_history.py --limit-days 2 --cache-dir /tmp/ff_smoke
    # 全量 (后台, ~1 小时)
    .venv/bin/python scripts/backfill_fund_flow_history.py
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from src.screening.offensive.data.fund_flow_store import FundFlowStore  # noqa: E402

DEFAULT_START = "20220104"  # 2022 首个交易日
DEFAULT_END = "20250704"  # 既有缓存从 2025-07-07 起, 此前最后一个交易日
PROGRESS_NAME = ".backfill_fund_flow_progress.json"
PACE_SEC = 0.6  # 批量端点 ~0.6s/次; 加 0.6s 间隔 → 对 token 礼貌


def load_trade_days(calendar_path: Path, start: str, end: str) -> list[str]:
    days = json.loads(calendar_path.read_text(encoding="utf-8"))
    return [str(d) for d in days if start <= str(d) <= end]


def group_by_month(days: list[str]) -> dict[str, list[str]]:
    months: dict[str, list[str]] = {}
    for day in days:
        months.setdefault(day[:6], []).append(day)
    return months


def merge_month_frames(
    store: FundFlowStore,
    month_frames: dict[str, list[pd.DataFrame]],
    failed_tickers: list[str] | None = None,
) -> int:
    """一个月的所有逐日帧按 ticker 合并落盘; 返回保存票数.

    FundFlowStore.save 按 date 去重 (keep=last) + 排序 + 校验 + 原子写 —
    与既有缓存 (2025-07+ 段) 不相交时为纯追加; 重跑同月为幂等覆盖.
    单票校验/IO 失败隔离记录, 不中断整月 (该票本月段缺失, 重跑可补).
    """
    saved = 0
    for ticker, frames in month_frames.items():
        try:
            store.save(ticker, pd.concat(frames, ignore_index=True))
        except Exception:  # noqa: BLE001 - 隔离单票失败, 汇总到返回值
            if failed_tickers is not None:
                failed_tickers.append(ticker)
            continue
        saved += 1
    return saved


def run_backfill(
    *,
    days: list[str],
    universe: set[str] | None,
    cache_dir: Path,
    pace_sec: float,
    fetch_fn,
    log=print,
) -> dict:
    """按月执行回填; 返回汇总 (完成月/跳过月/失败日). 失败日不记进度, 重跑补齐."""
    progress_path = cache_dir / PROGRESS_NAME
    done_months: set[str] = set()
    if progress_path.exists():
        done_months = set(json.loads(progress_path.read_text(encoding="utf-8")).get("done_months", []))

    store = FundFlowStore(cache_dir=cache_dir)
    summary = {"months_done": [], "months_skipped": sorted(done_months), "failed_days": [], "tickers_saved": 0}
    for month, month_days in group_by_month(days).items():
        if month in done_months:
            continue
        month_frames: dict[str, list[pd.DataFrame]] = {}
        month_failed: list[str] = []
        for day in month_days:
            frames = fetch_fn(day)
            if not frames:
                month_failed.append(day)
                log(f"  [{month}] {day} 批量拉取失败/为空 — 本月不落盘, 待重跑")
                time.sleep(pace_sec)
                continue
            for ticker, frame in frames.items():
                if universe is not None and ticker not in universe:
                    continue
                month_frames.setdefault(ticker, []).append(frame)
            time.sleep(pace_sec)
        if month_failed:
            summary["failed_days"].extend(month_failed)
            continue
        save_failures: list[str] = []
        saved = merge_month_frames(store, month_frames, save_failures)
        if save_failures:
            summary.setdefault("save_failed_tickers", []).extend(save_failures)
            log(f"  [{month}] ⚠️ {len(save_failures)} 只票落盘失败 (隔离, 可重跑): {save_failures[:5]}...")
        summary["tickers_saved"] += saved
        summary["months_done"].append(month)
        done_months.add(month)
        progress_path.write_text(
            json.dumps({"done_months": sorted(done_months)}, ensure_ascii=False),
            encoding="utf-8",
        )
        log(f"  [{month}] 完成: {len(month_days)} 天, {saved} 只票落盘 (累计进度 {len(done_months)} 个月)")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="fund_flow 历史回填 (2022→2025H1, 批量端点, 幂等可续跑)")
    parser.add_argument("--start", default=DEFAULT_START)
    parser.add_argument("--end", default=DEFAULT_END)
    parser.add_argument("--cache-dir", default=str(REPO_ROOT / "data/fund_flow_cache"))
    parser.add_argument("--calendar", default=str(REPO_ROOT / "data/reports/trade_calendar.json"))
    parser.add_argument("--limit-days", type=int, default=0, help="只处理前 N 个交易日 (冒烟用)")
    parser.add_argument("--universe-fund-flow-cache", action="store_true", help="宇宙取 fund_flow_cache 全量 (默认 price_cache)")
    parser.add_argument("--dry-run", action="store_true", help="只打印计划, 不触网不落盘")
    args = parser.parse_args()

    days = load_trade_days(Path(args.calendar), args.start.replace("-", ""), args.end.replace("-", ""))
    if args.limit_days > 0:
        days = days[: args.limit_days]
    months = group_by_month(days)

    if args.universe_fund_flow_cache:
        universe = {p.stem for p in Path(args.cache_dir).glob("*.csv")}
    else:
        universe = {p.stem for p in (REPO_ROOT / "data/price_cache").glob("*.csv")}

    print(f"回填计划: {days[0] if days else '—'} → {days[-1] if days else '—'}, "
          f"{len(days)} 个交易日 / {len(months)} 个月, 宇宙 {len(universe)} 只, "
          f"API 调用 ~{len(days)} 次, 预计 {len(days) * 1.5 / 60:.0f} 分钟 (不含落盘)")
    if args.dry_run:
        return 0
    if not days:
        print("无交易日可回填")
        return 0

    from src.tools.tushare_fund_flow import fetch_batch_fund_flow_tushare

    summary = run_backfill(
        days=days,
        universe=universe,
        cache_dir=Path(args.cache_dir),
        pace_sec=PACE_SEC,
        fetch_fn=fetch_batch_fund_flow_tushare,
    )
    print(f"回填结束: 完成 {len(summary['months_done'])} 个月 (跳过 {len(summary['months_skipped'])} 个已完成), "
          f"落盘 {summary['tickers_saved']} 票次, 失败日 {summary['failed_days'] or '无'}")
    return 0 if not summary["failed_days"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
