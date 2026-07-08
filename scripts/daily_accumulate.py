"""Daily auto_screening accumulation — 加速数据累积到 power threshold (n=317).

M8 证明 high bucket n=38 不足以判断模型好坏 (需 ~317). M1 decomposition 已就位但
旧 records 无 decomposition → 需累积新数据. 本脚本:
  1. 获取今日 A 股交易日 (trade_cal)
  2. 运行 --auto 生成报告 (含 score_decomposition)
  3. 追踪累积进度 (total/decomposition/high-bucket/到 317 还需几天)

Usage:
  python scripts/daily_accumulate.py [--dry-run]
  # owner cron: 0 18 * * 1-5 cd /repo && python scripts/daily_accumulate.py
"""

from __future__ import annotations

import argparse
import logging
import subprocess
import sys
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

POWER_THRESHOLD = 317  # M8: 检测 11pp 差异 (80% power) 需 ~317/组


def get_trade_date() -> str | None:
    """获取 A 股交易日 (17:00 阈值: 未过17点取前一天作为基准).

    资金流数据约 17:00 后才完成入库。凌晨/盘中跑时今日数据不存在,
    用 _resolve_default_end_date 的 17:00 阈值取正确基准日, 再用
    get_open_trade_dates 校验是否交易日。
    """
    try:
        from src.tools.tushare_api import get_open_trade_dates

        # 17:00 阈值: 未过17点回退一天 (与 CLI --auto 的 _resolve_default_end_date 一致)
        from src.cli.input import _resolve_default_end_date

        base_date = _resolve_default_end_date().replace("-", "")
        dates = get_open_trade_dates(base_date, base_date)
        return dates[0] if dates else None
    except Exception as exc:
        logger.warning("get_trade_date failed: %s", exc)
        return None


def get_accumulation_progress() -> dict:
    """追踪 tracking_history 累积进度 (纯函数, 可测试).

    Returns dict with:
      - total_records: 总 tracking records
      - with_decomposition: 含 score_decomposition 的 records (M1 激活前提)
      - high_bucket_matured: high bucket (score>=0.50) 且 T+30 成熟的 records
      - target: M8 power threshold (317)
      - high_bucket_pct: high bucket 达标百分比
    """
    from src.screening.consecutive_recommendation import (
        load_tracking_history,
        resolve_report_dir,
    )
    from src.screening.state_type_calibration import _score_bucket

    report_dir = resolve_report_dir()
    records = load_tracking_history(report_dir)

    total = len(records)
    with_decomp = sum(1 for r in records if r.get("score_decomposition"))
    high_matured = sum(1 for r in records if _score_bucket(r.get("recommendation_score", r.get("score_b"))) == "high" and r.get("next_30day_return") is not None)

    return {
        "total_records": total,
        "with_decomposition": with_decomp,
        "high_bucket_matured": high_matured,
        "target": POWER_THRESHOLD,
        "high_bucket_pct": round(high_matured / POWER_THRESHOLD * 100, 1) if POWER_THRESHOLD else 0,
    }


def run_auto_screening(trade_date: str) -> bool:
    """运行 --auto 生成报告 (subprocess)."""
    cmd = [sys.executable, "src/main.py", "--auto", "--end-date", trade_date]
    logger.info("运行: %s", " ".join(cmd))
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if result.returncode != 0:
            logger.error("--auto 失败 (exit %d): %s", result.returncode, result.stderr[:500])
            return False
        return True
    except subprocess.TimeoutExpired:
        logger.error("--auto 超时 (600s)")
        return False
    except Exception as exc:
        logger.error("--auto 异常: %s", exc)
        return False


def main(dry_run: bool = False) -> None:
    """主流程: 获取交易日 → 追踪进度 → (可选) 运行 --auto → 追踪完成后进度."""
    trade_date = get_trade_date()
    if not trade_date:
        print("今天非 A 股交易日, 跳过")
        return

    progress = get_accumulation_progress()
    print(f"累积进度: {progress['total_records']} records, " f"{progress['with_decomposition']} 有 decomposition, " f"high bucket matured={progress['high_bucket_matured']}/{progress['target']} " f"({progress['high_bucket_pct']}%)")

    if dry_run:
        print("dry-run, 不跑 --auto")
        return

    if not run_auto_screening(trade_date):
        print("--auto 失败, 退出")
        return

    progress2 = get_accumulation_progress()
    delta_total = progress2["total_records"] - progress["total_records"]
    delta_decomp = progress2["with_decomposition"] - progress["with_decomposition"]
    print(f"完成后: {progress2['total_records']} records (+{delta_total}), " f"{progress2['with_decomposition']} 有 decomposition (+{delta_decomp})")
    print(f"high bucket: {progress2['high_bucket_matured']}/{progress2['target']} " f"({progress2['high_bucket_pct']}%)")

    if progress2["high_bucket_matured"] >= progress2["target"]:
        print("✓ high bucket 达到 power threshold! M1 因子归因可可靠运行")
    else:
        remaining = progress2["target"] - progress2["high_bucket_matured"]
        daily_rate = max(delta_total, 1)
        est_days = remaining / daily_rate
        print(f"预计还需 ~{est_days:.0f} 个交易日达到 threshold (每天 +{daily_rate} records)")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    parser = argparse.ArgumentParser(description="Daily auto_screening accumulation")
    parser.add_argument("--dry-run", action="store_true", help="只追踪进度, 不跑 --auto")
    args = parser.parse_args()
    main(dry_run=args.dry_run)
