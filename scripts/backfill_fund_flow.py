"""资金流历史数据 backfill 脚本 — Phase 0 数据积累。

从最新 auto_screening 报告加载候选 ticker, 循环调 fetch_individual_fund_flow
+ store.save 落盘。支持:
- 断点续传 (已有近期数据的 ticker 跳过)
- 速率限制 (避免 akshare/eastmoney 封 IP)
- 错误隔离 (单只失败不中断整批)
- 进度 + 统计输出

CLI:
    python scripts/backfill_fund_flow.py [--max 50] [--rate-limit 0.5] [--cache-dir data/fund_flow_cache/]
"""

from __future__ import annotations

import argparse
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

# 默认参数
_DEFAULT_CACHE_DIR = "data/fund_flow_cache/"
_DEFAULT_RATE_LIMIT_SEC = 0.5  # 每 ticker 间隔 0.5s (akshare/eastmoney 友好)
_DEFAULT_MAX_TICKERS = 0  # 0 = 不限
# resume: ticker CSV 最大日期距今 ≤ N 天则跳过
_RESUME_FRESH_DAYS = 3


@dataclass
class BackfillStats:
    """backfill 一批 ticker 的统计结果。"""

    total: int = 0
    saved: int = 0
    skipped_fresh: int = 0  # 已有近期数据, 跳过
    failed: int = 0
    failed_tickers: list[str] = field(default_factory=list)

    def summary(self) -> str:
        return f"total={self.total}  saved={self.saved}  " f"skipped_fresh={self.skipped_fresh}  failed={self.failed}"


def load_candidate_tickers(report_path: Path | str | None = None) -> list[str]:
    """从最新 auto_screening 报告加载候选 ticker (去重保序)。

    Args:
        report_path: 报告路径; None = 自动找最新

    Returns:
        6 位 ticker 列表 (去重保序)
    """
    if report_path is None:
        from src.screening.consecutive_recommendation import resolve_report_dir
        from src.screening.data_quality_audit import _find_latest_report

        report_dir = resolve_report_dir()
        latest = _find_latest_report(report_dir)
        if latest is None:
            return []
        report_path = latest

    report_path = Path(report_path)
    if not report_path.exists():
        return []

    with open(report_path, encoding="utf-8") as f:
        report = json.loads(f.read())

    tickers: list[str] = []
    seen: set[str] = set()
    for rec in report.get("recommendations", []):
        t = str(rec.get("ticker", "")).strip()
        if t and t not in seen:
            seen.add(t)
            tickers.append(t)
    return tickers


def load_journal_tickers(journal_path: Path | str = "data/paper_trading_backtest/journal.jsonl") -> list[str]:
    """从 paper_trading_backtest journal 加载所有 BUY 过的 ticker (去重保序).

    C-TRIGGER-STRENGTH unblock (20260710): 默认 ``load_candidate_tickers`` 只取最新
    auto_screening 报告的 ~30 只, 不覆盖历史 BUY 的 146 只 → 历史 fund_flow 缺失
    (0/146 BUY 日有资金流) → trigger_strength→return 验证被 data-block. 本函数从
    journal 真值取全量历史 BUY ticker, 配合 ``--fresh-days 0`` 强制重拉全历史即可
    恢复 BUY 日资金流 (store.save 是 merge 语义, 不会覆盖已有数据).

    同时支持 live journal ``data/paper_trading/journal.jsonl`` (传入即可).
    """
    journal_path = Path(journal_path)
    if not journal_path.exists():
        return []
    tickers: list[str] = []
    seen: set[str] = set()
    for line in journal_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if rec.get("action") != "BUY":
            continue
        t = str(rec.get("ticker", "")).strip()
        if t and t not in seen:
            seen.add(t)
            tickers.append(t)
    return tickers


def _latest_date_in_store(store_cache_dir: Path, ticker: str) -> str | None:
    """读 ticker CSV 的最大日期; 无文件返回 None。"""
    path = store_cache_dir / f"{ticker}.csv"
    if not path.exists():
        return None
    try:
        df = pd.read_csv(path, dtype={"date": str}, usecols=["date"])
        return str(df["date"].max()) if len(df) > 0 else None
    except Exception:
        return None


def _is_fresh(latest_date: str | None, today: str, fresh_days: int = _RESUME_FRESH_DAYS) -> bool:
    """latest_date 距 today ≤ fresh_days → True (近期, 可跳过)。"""
    if latest_date is None:
        return False
    try:
        latest_dt = pd.to_datetime(latest_date, format="%Y%m%d")
        today_dt = pd.to_datetime(today, format="%Y%m%d")
        return (today_dt - latest_dt).days <= fresh_days
    except Exception:
        return False


def backfill_ticker(
    store,
    ticker: str,
    fetch_fn,
    today: str,
    fresh_days: int = _RESUME_FRESH_DAYS,
) -> str:
    """backfill 单只 ticker。

    Args:
        store: FundFlowStore
        ticker: 6 位代码
        fetch_fn: callable(ticker) -> DataFrame (注入便于测试)
        today: YYYYMMDD
        fresh_days: 近期阈值

    Returns:
        "saved" / "skipped_fresh" / "failed"
    """
    # resume 检查
    latest = _latest_date_in_store(Path(store.cache_dir), ticker)
    if _is_fresh(latest, today, fresh_days):
        logger.info("[skip] %s 已有近期数据 (最新 %s)", ticker, latest)
        return "skipped_fresh"

    try:
        df = fetch_fn(ticker)
    except Exception as exc:
        logger.warning("[fail] %s 拉取异常: %s", ticker, exc)
        return "failed"

    if df is None or len(df) == 0:
        logger.warning("[fail] %s 返回空数据", ticker)
        return "failed"

    n = store.save(ticker, df)
    logger.info("[save] %s +%d 行 (累计)", ticker, n)
    return "saved"


def backfill_batch(
    tickers: list[str],
    cache_dir: Path | str = _DEFAULT_CACHE_DIR,
    rate_limit_sec: float = _DEFAULT_RATE_LIMIT_SEC,
    max_tickers: int = _DEFAULT_MAX_TICKERS,
    today: str | None = None,
    fresh_days: int = _RESUME_FRESH_DAYS,
    fetch_fn=None,
) -> BackfillStats:
    """backfill 一批 ticker。

    Args:
        tickers: 候选列表
        cache_dir: 资金流缓存目录
        rate_limit_sec: 每只间隔秒数 (避免封 IP)
        max_tickers: 最多处理几只 (0 = 不限)
        today: YYYYMMDD (None = 自动今天)
        fresh_days: resume 近期阈值
        fetch_fn: 注入 fetch 函数 (None = 用真实 fetch_individual_fund_flow)

    Returns:
        BackfillStats
    """
    from src.screening.offensive.data.fund_flow_store import FundFlowStore

    if fetch_fn is None:
        # 双源 dispatcher (tushare 主 + akshare fallback) — 项目架构约定
        from src.tools.fund_flow import fetch_individual_fund_flow

        fetch_fn = fetch_individual_fund_flow

    if today is None:
        today = pd.Timestamp.now().strftime("%Y%m%d")

    store = FundFlowStore(cache_dir=cache_dir)
    stats = BackfillStats()
    queue = tickers[:max_tickers] if max_tickers > 0 else tickers
    stats.total = len(queue)

    for i, ticker in enumerate(queue, 1):
        result = backfill_ticker(store, ticker, fetch_fn, today, fresh_days)
        if result == "saved":
            stats.saved += 1
        elif result == "skipped_fresh":
            stats.skipped_fresh += 1
        else:
            stats.failed += 1
            stats.failed_tickers.append(ticker)

        # 速率限制 (最后一只不用等)
        if rate_limit_sec > 0 and i < len(queue):
            time.sleep(rate_limit_sec)

        # 进度日志 (每 10 只)
        if i % 10 == 0 or i == len(queue):
            logger.info("进度 %d/%d — %s", i, len(queue), stats.summary())

    return stats


def main():
    parser = argparse.ArgumentParser(description="资金流历史 backfill (Phase 0 数据积累)")
    parser.add_argument("--report", default=None, help="auto_screening 报告路径 (默认最新)")
    parser.add_argument(
        "--from-journal",
        default=None,
        help="从 paper_trading journal 加载历史 BUY ticker (恢复历史 fund_flow). "
        "传 journal 路径 (如 data/paper_trading_backtest/journal.jsonl) 或 'backtest'/'live' 简写.",
    )
    parser.add_argument("--cache-dir", default=_DEFAULT_CACHE_DIR, help="资金流缓存目录")
    parser.add_argument("--rate-limit", type=float, default=_DEFAULT_RATE_LIMIT_SEC, help="每只间隔秒数")
    parser.add_argument("--max", type=int, default=_DEFAULT_MAX_TICKERS, help="最多处理几只 (0=不限)")
    parser.add_argument("--fresh-days", type=int, default=_RESUME_FRESH_DAYS, help="resume 近期阈值 (天); 恢复历史数据用 0 强制全拉")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
    )

    if args.from_journal:
        jp = args.from_journal
        if jp == "backtest":
            jp = "data/paper_trading_backtest/journal.jsonl"
        elif jp == "live":
            jp = "data/paper_trading/journal.jsonl"
        tickers = load_journal_tickers(jp)
        logger.info("从 journal %s 加载 %d 只历史 BUY ticker", jp, len(tickers))
    else:
        tickers = load_candidate_tickers(args.report)
    if not tickers:
        logger.error("无候选 ticker — 请先跑 --auto 生成报告, 或指定 --from-journal backtest")
        return 1

    logger.info("候选 %d 只 ticker, 开始 backfill (rate_limit=%.2fs, fresh_days=%d)", len(tickers), args.rate_limit, args.fresh_days)
    stats = backfill_batch(
        tickers=tickers,
        cache_dir=args.cache_dir,
        rate_limit_sec=args.rate_limit,
        max_tickers=args.max,
        fresh_days=args.fresh_days,
    )
    logger.info("完成: %s", stats.summary())
    if stats.failed_tickers:
        logger.info("失败 ticker: %s", stats.failed_tickers[:20])
    return 0


if __name__ == "__main__":
    main()
