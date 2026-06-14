"""缓存预热器 — 在盘后自动预拉取常用数据，减少 --auto 冷启动延迟。"""

import logging
import time
from concurrent.futures import as_completed, ThreadPoolExecutor
from dataclasses import dataclass, field

import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class PreheatStats:
    """预热结果统计。"""

    tasks_total: int = 0
    tasks_success: int = 0
    tasks_failed: int = 0
    tasks_skipped: int = 0  # 已缓存跳过
    cache_hits: int = 0
    elapsed_seconds: float = 0.0
    details: list[dict] = field(default_factory=list)  # [{task, status, elapsed}]


# ── 可用预热任务定义 ──────────────────────────────────────────────

_PREHEAT_TASK_REGISTRY: list[dict] = [
    {"id": "daily_basic", "description": "全市场每日基本面", "estimated_time": "5s"},
    {"id": "daily_prices", "description": "全市场每日行情", "estimated_time": "8s"},
    {"id": "industry_classify", "description": "申万行业分类", "estimated_time": "2s"},
    {"id": "money_flow", "description": "北向资金/资金流", "estimated_time": "3s"},
    {"id": "financial_metrics", "description": "Top 100 候选财务指标", "estimated_time": "10s"},
]


def get_preheat_tasks() -> list[dict]:
    """返回可用的预热任务列表。"""
    return [dict(t) for t in _PREHEAT_TASK_REGISTRY]


# ── 单个任务执行器 ────────────────────────────────────────────────


def _execute_preheat_task(task_id: str, trade_date: str, force: bool) -> dict:
    """执行单个预热任务，返回 {task, status, elapsed, error?}。

    status: "success" | "skipped" | "failed"
    """
    start = time.monotonic()

    try:
        result = _fetch_task_data(task_id, trade_date, force)
        elapsed = time.monotonic() - start

        if result is None:
            # 数据已缓存且 force=False → skipped
            return {"task": task_id, "status": "skipped", "elapsed": round(elapsed, 2)}

        return {"task": task_id, "status": "success", "elapsed": round(elapsed, 2)}

    except Exception as exc:
        elapsed = time.monotonic() - start
        logger.warning("[Preheat] task %s failed: %s", task_id, exc)
        return {"task": task_id, "status": "failed", "elapsed": round(elapsed, 2), "error": str(exc)}


def _fetch_task_data(task_id: str, trade_date: str, force: bool) -> pd.DataFrame | None:
    """实际拉取数据并写入缓存。

    Returns:
        DataFrame if data was fetched, None if skipped (already cached).
    """
    if task_id == "daily_basic":
        return _fetch_daily_basic(trade_date, force)
    if task_id == "daily_prices":
        return _fetch_daily_prices(trade_date, force)
    if task_id == "industry_classify":
        return _fetch_industry_classify(force)
    if task_id == "money_flow":
        return _fetch_money_flow(trade_date, force)
    if task_id == "financial_metrics":
        return _fetch_financial_metrics(trade_date, force)

    raise ValueError(f"Unknown preheat task: {task_id}")


def _is_cached(cache_key: str) -> bool:
    """检查 EnhancedCache 中是否已有该 key。

    通过 get_enhanced_cache().get() 查询所有层级 (LRU + Redis + Disk)。
    注意: 返回 None 时无法区分 "cached None" vs "not cached",
    但本模块不会缓存 None 值, 所以 None = not cached 是安全的。
    """
    from src.data.enhanced_cache import get_enhanced_cache

    cache = get_enhanced_cache()
    value = cache.get(cache_key)
    return value is not None


def _fetch_daily_basic(trade_date: str, force: bool) -> pd.DataFrame | None:
    """预热 daily_basic（全市场每日基本面）。

    直接通过 BatchDataFetcher 拉取并写入其内部 BatchDataCache，
    下游 candidate_pool / screening 走 fetch_daily_basic_batch 时会命中。
    """
    from src.screening.batch_data_fetcher import get_global_batch_data_fetcher

    fetcher = get_global_batch_data_fetcher()
    cache_key = f"daily_basic_batch:{trade_date}"
    if not force and fetcher.has_cached(cache_key):
        return None

    df = fetcher.fetch_daily_basic_batch(trade_date)
    if df is not None and not df.empty:
        return df
    return None


def _fetch_daily_prices(trade_date: str, force: bool) -> pd.DataFrame | None:
    """预热 daily（全市场每日行情）。

    直接通过 BatchDataFetcher 拉取并写入其内部 BatchDataCache，
    下游 candidate_pool / screening 走 fetch_daily_prices_batch 时会命中。
    """
    from src.screening.batch_data_fetcher import get_global_batch_data_fetcher

    fetcher = get_global_batch_data_fetcher()
    cache_key = f"daily_price_batch:{trade_date}"
    if not force and fetcher.has_cached(cache_key):
        return None

    df = fetcher.fetch_daily_prices_batch(trade_date)
    if df is not None and not df.empty:
        return df
    return None


def _fetch_industry_classify(force: bool) -> pd.DataFrame | None:
    """预热申万行业分类。

    调用 get_sw_industry_classification() 会填充 tushare 持久层 (tushare_df:index_classify)
    和进程级 _sw_industry_cache；preheat:industry_classify 仅作为"已预热"标记避免重复拉取。
    """
    from src.tools.tushare_api import get_sw_industry_classification

    cache_key = "preheat:industry_classify"
    if not force and _is_cached(cache_key):
        return None

    mapping = get_sw_industry_classification()
    if mapping:
        from src.data.enhanced_cache import get_enhanced_cache

        get_enhanced_cache().set(cache_key, mapping, ttl=7 * 86400)
        return pd.DataFrame(list(mapping.items()), columns=["ts_code", "industry"])
    return None


def _fetch_money_flow(trade_date: str, force: bool) -> pd.DataFrame | None:
    """预热北向资金/资金流。

    调用 get_northbound_flow() 会填充 tushare 持久层 (tushare_df:moneyflow_hsgt)
    和 northbound_* 内存缓存；preheat:money_flow:{date} 仅作为"已预热"标记。
    """
    from src.tools.tushare_api import get_northbound_flow

    cache_key = f"preheat:money_flow:{trade_date}"
    if not force and _is_cached(cache_key):
        return None

    df = get_northbound_flow(trade_date=trade_date)
    if df is not None and not df.empty:
        from src.data.enhanced_cache import get_enhanced_cache

        get_enhanced_cache().set(cache_key, df, ttl=6 * 3600)
        return df
    return None


def _fetch_financial_metrics(trade_date: str, force: bool) -> pd.DataFrame | None:
    """预热 Top 100 候选标的财务指标。

    调用 get_ashare_financial_metrics_with_tushare() 走 tushare 持久层缓存
    (tushare_df:fina_indicator 等)；preheat:financial_metrics:{date} 仅作为"已预热"标记。
    """
    from src.tools.tushare_api import (
        get_all_stock_basic,
        get_ashare_financial_metrics_with_tushare,
    )

    cache_key = f"preheat:financial_metrics:{trade_date}"
    if not force and _is_cached(cache_key):
        return None

    df_basic = get_all_stock_basic()
    if df_basic is None or df_basic.empty:
        return None

    # 取前 100 只（按 ts_code 排序）
    tickers = df_basic.head(100)["ts_code"].tolist()
    results: list[dict] = []
    for ts_code in tickers[:20]:  # 限制拉取数量避免频率限制
        try:
            metrics = get_ashare_financial_metrics_with_tushare(ts_code[:6], trade_date, limit=1)
            if metrics:
                results.append({"ticker": ts_code, "count": len(metrics)})
        except Exception:
            pass

    if results:
        from src.data.enhanced_cache import get_enhanced_cache

        get_enhanced_cache().set(cache_key, results, ttl=24 * 3600)
        return pd.DataFrame(results)
    return None


# ── 主入口 ────────────────────────────────────────────────────────


def preheat_cache(
    trade_date: str | None = None,
    *,
    tasks: list[str] | None = None,
    force: bool = False,
    concurrency: int = 4,
) -> PreheatStats:
    """预热缓存。

    Args:
        trade_date: 交易日期 YYYYMMDD，None = 今天。
        tasks: 指定预热任务 ID 列表，None = 全部。
        force: 强制刷新（忽略已有缓存）。
        concurrency: 并发线程数。

    Returns:
        PreheatStats 包含各任务结果。
    """
    if trade_date is None:
        from datetime import datetime

        trade_date = datetime.now().strftime("%Y%m%d")

    # 解析任务列表
    all_task_ids = [t["id"] for t in _PREHEAT_TASK_REGISTRY]
    if tasks is None:
        selected_tasks = all_task_ids
    else:
        # 过滤无效 task id
        selected_tasks = [t for t in tasks if t in all_task_ids]
        unknown = set(tasks) - set(selected_tasks)
        if unknown:
            logger.warning("[Preheat] unknown tasks skipped: %s", unknown)

    if not selected_tasks:
        return PreheatStats(elapsed_seconds=0.0)

    stats = PreheatStats(tasks_total=len(selected_tasks))
    overall_start = time.monotonic()

    # 并发执行
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = {executor.submit(_execute_preheat_task, tid, trade_date, force): tid for tid in selected_tasks}

        for future in as_completed(futures):
            try:
                result = future.result()
            except Exception as exc:
                tid = futures[future]
                result = {"task": tid, "status": "failed", "elapsed": 0.0, "error": str(exc)}

            stats.details.append(result)
            status = result.get("status", "failed")
            if status == "success":
                stats.tasks_success += 1
            elif status == "skipped":
                stats.tasks_skipped += 1
                stats.cache_hits += 1
            else:
                stats.tasks_failed += 1

    stats.elapsed_seconds = round(time.monotonic() - overall_start, 2)

    # 按 task 原始顺序排序 details
    task_order = {tid: idx for idx, tid in enumerate(selected_tasks)}
    stats.details.sort(key=lambda d: task_order.get(d.get("task", ""), 999))

    return stats


# ── CLI 格式化输出 ────────────────────────────────────────────────


def format_preheat_report(stats: PreheatStats, trade_date: str, task_label: str) -> str:
    """格式化预热报告文本。"""
    from colorama import Fore, Style

    lines: list[str] = []
    lines.append(f"\n{Fore.CYAN}{Style.BRIGHT}━━━ 缓存预热 · {trade_date} ━━━{Style.RESET_ALL}")
    lines.append(f"预热任务: {stats.tasks_total} 个 ({task_label})")
    lines.append("并发度: 4")
    lines.append("")

    for idx, detail in enumerate(stats.details, 1):
        task_id = detail.get("task", "?")
        status = detail.get("status", "unknown")
        elapsed = detail.get("elapsed", 0.0)
        error = detail.get("error")

        if status == "skipped":
            status_str = f"{Fore.GREEN}已缓存 (跳过){Style.RESET_ALL}"
        elif status == "success":
            status_str = f"{Fore.YELLOW}拉取中 ({elapsed:.1f}s){Style.RESET_ALL}"
        else:
            err_msg = f" — {error}" if error else ""
            status_str = f"{Fore.RED}失败{err_msg}{Style.RESET_ALL}"

        lines.append(f"[{idx}/{stats.tasks_total}] {task_id:<22s} ... {status_str}")

    lines.append("")
    lines.append(f"完成: {stats.tasks_success} 成功, {stats.tasks_failed} 失败, {stats.tasks_skipped} 跳过")
    lines.append(f"耗时: {stats.elapsed_seconds:.1f}s (并发)")
    lines.append("")
    return "\n".join(lines)
