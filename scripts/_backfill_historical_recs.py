"""Backfill historical tracking records — 跑历史日期 --auto 生成推荐 + 回填 T+30 returns.

服务 winrate>50% 门控决策: 当前 low bucket n=105 bootstrap CI [41%, 60%] 太宽.
本脚本跑历史交易日 (T+30 已 mature) 的 compute_auto_screening_results(top_n=300),
seed 进 tracking_history, 复用 update_tracking_history 的 R164 tushare 路径回填 T+30 returns.

复用现有实现 (不重写):
  - compute_auto_screening_results (main.py:623) — 纯函数跑 --auto
  - update_tracking_history (recommendation_tracker.py:431) — seed + backfill
  - fetch_actual_returns (R164 tushare path) — T+1~T+30 returns

Usage:
  set -a && source .env && set +a && uv run python scripts/_backfill_historical_recs.py [--max-dates N] [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)


def get_mature_trade_dates(days_back: int = 120) -> list[str]:
    """获取 T+30 已 mature 的 A 股交易日 (recommended_date <= today - 45 自然日).

    T+30 需要 30 个交易日后, 30 交易日 ≈ 45 自然日 (含周末).
    用 45 自然日 cutoff 确保 T+30 returns 可回填.
    """
    from src.tools.tushare_api import get_open_trade_dates

    today = datetime.now()
    # T+30 matured: recommended_date <= today - 45 自然日 (确保 30+ 交易日)
    end = (today - timedelta(days=45)).strftime("%Y%m%d")
    start = (today - timedelta(days=days_back)).strftime("%Y%m%d")
    dates = get_open_trade_dates(start, end)
    return sorted(dates)


def get_existing_recommended_dates() -> set[str]:
    """tracking_history 已有的 recommended_date 集合."""
    from src.screening.consecutive_recommendation import (
        load_tracking_history,
        resolve_report_dir,
    )

    records = load_tracking_history(resolve_report_dir())
    return {str(r.get("recommended_date", "")) for r in records if r.get("recommended_date")}


def backfill_one_date(trade_date: str, top_n: int = 300) -> dict:
    """跑单个历史日期: compute_auto_screening → 写报告 → update_tracking_history.

    两阶段 update:
      - 第一次 update_tracking_history(trade_date): Phase 1 seed recommendations
      - 第二次 update_tracking_history(today): Phase 2 回填 T+30 returns
        (Phase 2 用 trade_date 作为 "today", 历史 date 当天还未到 T+6, 会跳过)

    Returns:
        dict with date, n_recs, n_low, elapsed, success
    """
    from src.main import (
        _AUTO_PIPELINE_LOCK_PATH,
        _save_json_report,
        _try_acquire_pipeline_lock,
        compute_auto_screening_results,
    )
    from src.screening.consecutive_recommendation import resolve_report_dir
    from src.screening.recommendation_tracker import update_tracking_history

    report_dir = resolve_report_dir()
    t0 = time.time()

    # c292 pipeline 锁复用: 防与 --auto / 其他 backfill 并发写报告 + tracking_history。
    # backfill 写 auto_screening 报告 + 两阶段 update_tracking_history, 与 --auto 共享
    # 同一套文件; 不持锁则并发 lost-update / 报告互相覆盖 (c292 守 --auto 流程, 本锁
    # 让 backfill 也进同一临界区)。flock 进程退出自动释放 (crash-safe)。
    _lock_fd = _try_acquire_pipeline_lock(_AUTO_PIPELINE_LOCK_PATH)
    if _lock_fd is None:
        logging.warning("backfill %s 跳过: 另一个 --auto/backfill 实例持锁", trade_date)
        return {"date": trade_date, "n_recs": 0, "n_low": 0, "seeded": 0, "updated": 0,
                "elapsed_s": 0.0, "success": False, "skipped": "pipeline_lock_held"}
    try:
        return _backfill_one_date_locked(
            trade_date=trade_date, top_n=top_n, report_dir=report_dir,
            compute_fn=compute_auto_screening_results,
            save_report_fn=_save_json_report,
            update_history_fn=update_tracking_history,
            t0=t0,
        )
    finally:
        try:
            import os as _os
            _os.close(_lock_fd)
        except OSError:
            pass


def _backfill_one_date_locked(
    *, trade_date: str, top_n: int, report_dir: Path,
    compute_fn, save_report_fn, update_history_fn, t0: float,
) -> dict:
    """backfill_one_date 临界区主体 (调用方已持 c292 pipeline 锁)。"""
    # Step 1: 跑历史日期 --auto (纯函数, 不写文件)
    payload = compute_fn(trade_date, top_n=top_n)
    recs = payload.get("recommendations", [])
    n_recs = len(recs)

    # Step 2: 写报告文件 (原子写, 复用 c293 _save_json_report — 此前 backfill 绕过它
    # 直接 write_text, 是 c293 同族不同路径残留; crash mid-write 留半截历史报告污染
    # reconcile/digest)。_save_json_report 内部 tempfile + os.replace + BH-012 sanitize。
    save_report_fn(f"auto_screening_{trade_date}.json", payload)

    # Step 3: 统计 low bucket 数量 (score<0.30)
    scores = [r.get("score_b", r.get("recommendation_score", 0)) for r in recs]
    n_low = sum(1 for s in scores if s < 0.30)

    # Step 4: Phase 1 seed — update_tracking_history(trade_date) seed recommendations
    # (Phase 2 用 trade_date 作为 "today", 历史 date 当天 rec_dt==today_dt, 0 < 6 跳过回填)
    seeded = update_history_fn(reports_dir=report_dir, trade_date=trade_date)

    # Step 5: Phase 2 backfill — 用真实今天日期触发 T+30 回填
    # (Phase 2 会遍历所有 pending records, (today_dt - rec_dt).days > 6 的会回填)
    today_str = datetime.now().strftime("%Y%m%d")
    updated = update_history_fn(reports_dir=report_dir, trade_date=today_str)

    elapsed = time.time() - t0
    return {
        "date": trade_date,
        "n_recs": n_recs,
        "n_low": n_low,
        "seeded": seeded,
        "updated": updated,
        "elapsed_s": round(elapsed, 1),
        "success": True,
    }


def main(max_dates: int = 0, dry_run: bool = False, top_n: int = 300) -> None:
    """主流程: 获取 missing dates → 逐个回填 → 统计 low bucket 增长."""
    from src.screening.consecutive_recommendation import (
        load_tracking_history,
        resolve_report_dir,
    )
    from src.screening.north_star_pnl import compute_bootstrap_ci_from_loaded
    from src.screening.state_type_calibration import _score_bucket

    logging.basicConfig(level=logging.WARNING, format="%(asctime)s [%(levelname)s] %(message)s")

    # 回填前 baseline
    records = load_tracking_history(resolve_report_dir())
    low_before = sum(
        1 for r in records
        if _score_bucket(r.get("recommendation_score", r.get("score_b"))) == "low"
        and r.get("next_30day_return") is not None
    )
    print(f"=== Baseline: {len(records)} records, low bucket mature={low_before} ===")

    # bootstrap CI baseline
    ci_before = compute_bootstrap_ci_from_loaded(records, min_n=20, n_bootstrap=10000, seed=42)
    low_ci_before = next((c for c in ci_before if c.bucket == "low"), None)
    if low_ci_before and low_ci_before.verdict == "ok":
        print(f"  low winrate CI (before): {low_ci_before.point_estimate:.1%} [{low_ci_before.ci_lower:.1%}, {low_ci_before.ci_upper:.1%}] n={low_ci_before.sample_count}")

    # 获取 missing dates
    all_dates = get_mature_trade_dates(days_back=90)
    existing = get_existing_recommended_dates()
    missing = [d for d in all_dates if d not in existing]

    if max_dates > 0:
        missing = missing[:max_dates]

    print(f"\n=== Missing trade dates (T+30 matured, not in tracking_history): {len(missing)} ===")
    if missing:
        print(f"  span: {missing[0]} ~ {missing[-1]}")
        print(f"  est low bucket if run --top {top_n}: ~{len(missing) * top_n * 0.97} (97% low avg)")

    if dry_run:
        print("\n[dry-run] 不执行回填")
        return

    if not missing:
        print("\n无 missing dates, 已全部回填")
        return

    # 逐个回填
    print(f"\n=== 开始回填 {len(missing)} dates (top_n={top_n}) ===")
    total_low_added = 0
    for i, date in enumerate(missing, 1):
        print(f"[{i}/{len(missing)}] {date}...", end=" ", flush=True)
        try:
            result = backfill_one_date(date, top_n=top_n)
            print(f"recs={result['n_recs']}, low={result['n_low']}, updated={result['updated']}, {result['elapsed_s']}s")
        except Exception as exc:
            print(f"FAILED: {type(exc).__name__}: {exc}")
            logger.exception("backfill failed for %s", date)

    # 回填后统计
    records_after = load_tracking_history(resolve_report_dir())
    low_after = sum(
        1 for r in records_after
        if _score_bucket(r.get("recommendation_score", r.get("score_b"))) == "low"
        and r.get("next_30day_return") is not None
    )
    print(f"\n=== After: {len(records_after)} records, low bucket mature={low_after} (+{low_after - low_before}) ===")

    # bootstrap CI after
    ci_after = compute_bootstrap_ci_from_loaded(records_after, min_n=20, n_bootstrap=10000, seed=42)
    low_ci_after = next((c for c in ci_after if c.bucket == "low"), None)
    if low_ci_after and low_ci_after.verdict == "ok":
        print(f"  low winrate CI (after): {low_ci_after.point_estimate:.1%} [{low_ci_after.ci_lower:.1%}, {low_ci_after.ci_upper:.1%}] n={low_ci_after.sample_count}")
        if low_ci_before and low_ci_before.verdict == "ok":
            ci_width_before = low_ci_before.ci_upper - low_ci_before.ci_lower
            ci_width_after = low_ci_after.ci_upper - low_ci_after.ci_lower
            print(f"  CI width: {ci_width_before:.1%} → {ci_width_after:.1%} (收窄 {ci_width_before - ci_width_after:.1%})")
            if low_ci_after.ci_lower >= 0.50:
                print(f"  ✓ CI 下界 {low_ci_after.ci_lower:.1%} >= 50% — 证据已足够支撑门控翻转决策!")
            else:
                print(f"  ⚠ CI 下界 {low_ci_after.ci_lower:.1%} < 50% — 仍需累积")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill historical tracking records")
    parser.add_argument("--max-dates", type=int, default=0, help="最多回填 N 个日期 (0=全部)")
    parser.add_argument("--dry-run", action="store_true", help="只统计不执行")
    parser.add_argument("--top-n", type=int, default=300, help="每日 top N 推荐 (默认 300)")
    args = parser.parse_args()
    main(max_dates=args.max_dates, dry_run=args.dry_run, top_n=args.top_n)
