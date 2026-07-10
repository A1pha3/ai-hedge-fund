#!/usr/bin/env python3
"""回填 fund_flow_cache 历史资金流数据。

问题: fund_flow_cache 逐日累积, 当前平均仅 ~2.4 天, BTST setup 条件 2 (资金流>20d
均值) 需要 ≥5 天历史才能判定。历史不足时 setup 标 degraded (⚠残缺), 入场过滤
残缺 → 弱突破混入 → 需要更激进的止损补偿。

方案: 用 tushare moneyflow 的全市场批量模式 (trade_date=YYYYMMDD), 每次请求
拉取全市场 ~5000 只票当日资金流, ~0.5s/天。120 个交易日 ≈ 1 分钟即可把 6 个月
历史回填完毕, 使条件 2 对所有候选股立刻生效。

数据流: pro.moneyflow(trade_date) → 万元转元归一化 → 拆分 per-ticker →
FundFlowStore.save (merge+去重, 与运行时写入路径完全一致)。

用法:
    uv run python scripts/backfill_fund_flow_cache.py                    # 默认回填 120 交易日
    uv run python scripts/backfill_fund_flow_cache.py --days 60           # 回填 60 交易日
    uv run python scripts/backfill_fund_flow_cache.py --start 20260101    # 指定起始日
    uv run python scripts/backfill_fund_flow_cache.py --dry-run           # 只打印不写盘
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import random
import sys
import time
from pathlib import Path

import pandas as pd

# 确保项目根目录在 sys.path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from src.tools.tushare_fund_flow import _load_token, _to_ts_code  # noqa: E402
from src.screening.offensive.data.fund_flow_store import FundFlowStore  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# tushare *_amount 字段单位是万元 → 归一化为元 (与 tushare_fund_flow.py 一致)
_WAN_TO_YUAN = 10_000.0

_CACHE_DIR = _PROJECT_ROOT / "data" / "fund_flow_cache"
_REGIME_HISTORY_PATH = _PROJECT_ROOT / "data" / "reports" / "regime_history.json"


def _normalize_batch(raw: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """归一化 moneyflow 批量返回 → per-ticker DataFrame 字典。

    与 tushare_fund_flow.fetch_individual_fund_flow_tushare 的归一化逻辑完全一致:
    - 万元 → 元
    - main_net_inflow = net_mf_amount (tushare 已算好主力净额)
    - big/super_big/medium/small = buy - sell per order size
    - close/pct_change 留空 (moneyflow 不含价格, 价格从 price_cache 另取)
    """
    if raw is None or len(raw) == 0:
        return {}

    df = raw.copy()
    df["main_net_inflow"] = df["net_mf_amount"].astype(float) * _WAN_TO_YUAN
    df["big_net_inflow"] = (df["buy_lg_amount"].astype(float) - df["sell_lg_amount"].astype(float)) * _WAN_TO_YUAN
    df["super_big_net_inflow"] = (df["buy_elg_amount"].astype(float) - df["sell_elg_amount"].astype(float)) * _WAN_TO_YUAN
    df["medium_net_inflow"] = (df["buy_md_amount"].astype(float) - df["sell_md_amount"].astype(float)) * _WAN_TO_YUAN
    df["small_net_inflow"] = (df["buy_sm_amount"].astype(float) - df["sell_sm_amount"].astype(float)) * _WAN_TO_YUAN
    df["main_net_pct"] = 0.0
    df["close"] = float("nan")
    df["pct_change"] = 0.0
    df["date"] = pd.to_datetime(df["trade_date"], format="%Y%m%d", errors="coerce")
    df = df.dropna(subset=["date"])

    # ts_code → 6 位 ticker (必须在 keep 列过滤之前提取, 否则 ts_code 被丢弃)
    df["ticker"] = df["ts_code"].str[:6]

    keep = ["date", "close", "pct_change", "main_net_inflow", "main_net_pct",
            "big_net_inflow", "super_big_net_inflow", "medium_net_inflow", "small_net_inflow"]
    df = df[[c for c in keep if c in df.columns] + ["ticker"]]

    return {ticker: group.drop(columns=["ticker"]) for ticker, group in df.groupby("ticker")}


def _get_trading_days(start_date: str, end_date: str) -> list[str]:
    """获取交易日列表: regime_history (本地, 完整) + trade_cal (补最新几天)。"""
    days: list[str] = []

    # 1. regime_history (本地交易日历, 2020-2026 完整)
    if _REGIME_HISTORY_PATH.exists():
        with open(_REGIME_HISTORY_PATH) as f:
            regime = json.load(f)
        days = sorted(k for k in regime if start_date <= k <= end_date)
        logger.info("regime_history 提供 %d 个交易日 (%s ~ %s)", len(days), days[0] if days else "?", days[-1] if days else "?")

    # 2. trade_cal 补 regime_history 之后的日子 (regime 可能滞后几天)
    try:
        import tushare as ts

        token = _load_token()
        if token:
            ts.set_token(token)
            pro = ts.pro_api(timeout=30)
            cal_start = days[-1] if days else start_date
            cal = pro.trade_cal(exchange="SSE", start_date=cal_start, end_date=end_date, is_open="1")
            cal_days = sorted(cal["cal_date"].tolist())
            new_days = [d for d in cal_days if d not in set(days) and start_date <= d <= end_date]
            if new_days:
                logger.info("trade_cal 补充 %d 个新交易日: %s", len(new_days), new_days)
                days = sorted(set(days) | set(new_days))
    except Exception as exc:
        logger.warning("trade_cal 获取失败 (仅用 regime_history): %s", exc)

    return days


def _moneyflow_batch_with_retry(pro, trade_date: str, max_retries: int = 2) -> pd.DataFrame | None:
    """调用 pro.moneyflow(trade_date=...) 全市场批量, 带瞬时错误重试。"""
    for attempt in range(max_retries + 1):
        try:
            return pro.moneyflow(trade_date=trade_date)
        except Exception as exc:
            exc_name = type(exc).__name__
            if exc_name in ("TypeError", "ValueError", "AttributeError", "KeyError"):
                logger.warning("[%s] 不可重试错误: %s", trade_date, exc)
                return None
            if attempt < max_retries:
                delay = 1.0 * (2**attempt) * (1 + random.random() * 0.3)
                logger.info("[%s] 瞬时错误 (尝试 %d/%d), %.1fs 后重试: %s", trade_date, attempt + 1, max_retries, delay, exc_name)
                time.sleep(delay)
            else:
                logger.warning("[%s] 重试 %d 次仍失败: %s", trade_date, max_retries, exc)
                return None
    return None


def main():
    parser = argparse.ArgumentParser(description="回填 fund_flow_cache 历史资金流")
    parser.add_argument("--days", type=int, default=120, help="回填最近 N 个交易日 (默认 120 ≈ 6 个月)")
    parser.add_argument("--start", type=str, default="", help="起始日 YYYYMMDD (覆盖 --days)")
    parser.add_argument("--end", type=str, default="", help="结束日 YYYYMMDD (默认今天)")
    parser.add_argument("--dry-run", action="store_true", help="只拉取不写盘")
    args = parser.parse_args()

    # --- 初始化 ---
    token = _load_token()
    if not token:
        logger.error("TUSHARE_TOKEN 未配置 (.env 或环境变量), 无法回填")
        sys.exit(1)

    import tushare as ts

    ts.set_token(token)
    pro = ts.pro_api(timeout=60)

    end_date = args.end or pd.Timestamp.now().strftime("%Y%m%d")
    if args.start:
        start_date = args.start
    else:
        all_days = _get_trading_days("20200101", end_date)
        if not all_days:
            logger.error("无法获取交易日历")
            sys.exit(1)
        start_date = all_days[-args.days] if len(all_days) >= args.days else all_days[0]

    logger.info("=" * 60)
    logger.info("回填范围: %s ~ %s", start_date, end_date)
    logger.info("缓存目录: %s", _CACHE_DIR)
    logger.info("模式: %s", "DRY-RUN (不写盘)" if args.dry_run else "写盘")

    # --- 获取交易日列表 ---
    trade_days = _get_trading_days(start_date, end_date)
    if not trade_days:
        logger.error("区间内无交易日")
        sys.exit(1)
    logger.info("待回填交易日: %d 天", len(trade_days))

    # --- 逐日批量拉取 ---
    # 攒一批天数的全市场数据到内存, 再批量写盘, 避免逐 ticker 逐天反复读写
    # 同一文件 (每天 ~5000 ticker × save = 10000 次文件 I/O → 攒批后降到 ~5000 次)。
    BATCH_SIZE = int(os.environ.get("BACKFILL_BATCH_SIZE", "10"))
    total_written = 0
    total_days_ok = 0
    total_days_fail = 0
    t_start = time.time()

    # buffer: ticker → concatenated DataFrame (跨多天攒批)
    buffer: dict[str, pd.DataFrame] = {}

    def _flush_buffer(buf: dict[str, pd.DataFrame]) -> int:
        """把 buffer 里攒的数据批量写入磁盘 (每个 ticker 一次 read-merge-write)。"""
        if not buf:
            return 0
        written = 0
        for ticker, df in buf.items():
            written += FundFlowStore(_CACHE_DIR).save(ticker, df)
        buf.clear()
        return written

    for i, trade_date in enumerate(trade_days):
        t0 = time.time()
        raw = _moneyflow_batch_with_retry(pro, trade_date)
        if raw is None or len(raw) == 0:
            logger.warning("[%d/%d] %s: 数据为空, 跳过", i + 1, len(trade_days), trade_date)
            total_days_fail += 1
            continue

        per_ticker = _normalize_batch(raw)
        if not args.dry_run:
            # 攒进 buffer (同 ticker 跨天 concat)
            for ticker, df in per_ticker.items():
                if ticker in buffer:
                    buffer[ticker] = pd.concat([buffer[ticker], df], ignore_index=True)
                else:
                    buffer[ticker] = df

        total_days_ok += 1
        elapsed = time.time() - t0

        # 每 BATCH_SIZE 天 flush 一次, 或最后一天 flush
        should_flush = (not args.dry_run) and (
            (i + 1) % BATCH_SIZE == 0 or i == len(trade_days) - 1
        )
        flush_msg = ""
        if should_flush:
            batch_written = _flush_buffer(buffer)
            total_written += batch_written
            flush_msg = f" (批量写入 {batch_written} 行)"

        logger.info(
            "[%d/%d] %s: %d 只票, %.1fs%s",
            i + 1, len(trade_days), trade_date, len(per_ticker), elapsed, flush_msg,
        )

    # --- 汇总 ---
    elapsed_total = time.time() - t_start
    logger.info("=" * 60)
    logger.info("回填完成:")
    logger.info("  成功: %d 天, 失败: %d 天", total_days_ok, total_days_fail)
    logger.info("  总写入/合并: %d 行", total_written)
    logger.info("  耗时: %.1fs", elapsed_total)

    if args.dry_run:
        logger.info("DRY-RUN 模式, 未实际写盘")
    else:
        # 验证回填后的缓存深度
        files = list(_CACHE_DIR.glob("*.csv"))
        depths = []
        for f in files:
            try:
                depths.append(len(pd.read_csv(f)))
            except Exception:
                depths.append(0)
        if depths:
            import statistics

            logger.info("=" * 60)
            logger.info("回填后缓存深度分布:")
            logger.info("  文件数: %d", len(depths))
            logger.info("  平均: %.1f 行", statistics.mean(depths))
            logger.info("  中位数: %.0f 行", statistics.median(depths))
            ge5 = sum(1 for d in depths if d >= 5)
            logger.info("  ≥5 天 (条件2生效): %d 只 (%.0f%%)", ge5, 100 * ge5 / len(depths))


if __name__ == "__main__":
    main()
