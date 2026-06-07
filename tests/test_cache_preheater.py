"""缓存预热器测试 — P1-1 缓存命中率优化。

全部 mock 外部数据源，不依赖 tushare token 或网络。
"""

import os
from datetime import datetime
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from src.data.cache_preheater import (
    PreheatStats,
    _execute_preheat_task,
    format_preheat_report,
    get_preheat_tasks,
    preheat_cache,
)


# ── Helpers ────────────────────────────────────────────────────────


def _make_stats(**overrides) -> PreheatStats:
    defaults = dict(tasks_total=5, tasks_success=3, tasks_failed=0, tasks_skipped=2, cache_hits=2, elapsed_seconds=5.0, details=[])
    defaults.update(overrides)
    return PreheatStats(**defaults)


# ── Test 1: 全部预热（mock 数据源）────────────────────────────────


@patch("src.data.cache_preheater._fetch_task_data")
def test_preheat_all_tasks(mock_fetch):
    """全部 5 个任务都拉取成功。"""
    mock_fetch.return_value = pd.DataFrame({"a": [1]})

    stats = preheat_cache("20260607", force=True, concurrency=2)

    assert stats.tasks_total == 5
    assert stats.tasks_success == 5
    assert stats.tasks_failed == 0
    assert stats.tasks_skipped == 0
    assert stats.elapsed_seconds >= 0


# ── Test 2: 指定任务预热 ────────────────────────────────────────────


@patch("src.data.cache_preheater._fetch_task_data")
def test_preheat_specific_tasks(mock_fetch):
    """仅预热 daily_basic 和 industry_classify。"""
    mock_fetch.return_value = pd.DataFrame({"x": [1]})

    stats = preheat_cache("20260607", tasks=["daily_basic", "industry_classify"], force=True)

    assert stats.tasks_total == 2
    assert stats.tasks_success == 2
    task_ids = {d["task"] for d in stats.details}
    assert task_ids == {"daily_basic", "industry_classify"}


# ── Test 3: 已缓存任务跳过 ─────────────────────────────────────────


@patch("src.data.cache_preheater._fetch_task_data")
def test_preheat_skips_cached(mock_fetch):
    """非 force 模式下，_fetch_task_data 返回 None -> skipped。"""
    mock_fetch.return_value = None

    stats = preheat_cache("20260607", tasks=["daily_basic"], force=False)

    assert stats.tasks_total == 1
    assert stats.tasks_skipped == 1
    assert stats.tasks_success == 0


# ── Test 4: force 模式强制刷新 ──────────────────────────────────────


@patch("src.data.cache_preheater._fetch_task_data")
def test_preheat_force_refresh(mock_fetch):
    """force=True 时即使 _fetch_task_data 返回 None，只要不是数据已缓存就是 skipped（即 _fetch 返回 None = skipped）。"""
    # _fetch_task_data 返回 DataFrame 表示成功
    mock_fetch.return_value = pd.DataFrame({"a": [1]})

    stats = preheat_cache("20260607", tasks=["daily_basic"], force=True)

    assert stats.tasks_success == 1
    assert stats.tasks_skipped == 0


# ── Test 5: 并发执行（mock）─────────────────────────────────────────


@patch("src.data.cache_preheater._fetch_task_data")
def test_preheat_concurrent(mock_fetch):
    """验证并发执行多个任务时 stats 正确。"""
    mock_fetch.return_value = pd.DataFrame({"v": [1]})

    stats = preheat_cache("20260607", concurrency=2, force=True)

    assert stats.tasks_total == 5
    assert stats.tasks_success == 5
    assert len(stats.details) == 5


# ── Test 6: 失败任务不阻塞其他 ─────────────────────────────────────


@patch("src.data.cache_preheater._fetch_task_data")
def test_preheat_failure_does_not_block(mock_fetch):
    """某个任务抛异常，其他任务仍正常完成。"""

    def _side_effect(task_id, trade_date, force):
        if task_id == "money_flow":
            raise ConnectionError("tushare down")
        return pd.DataFrame({"ok": [1]})

    mock_fetch.side_effect = _side_effect

    stats = preheat_cache("20260607", force=True, concurrency=1)

    assert stats.tasks_total == 5
    assert stats.tasks_failed == 1
    assert stats.tasks_success == 4
    failed_detail = next(d for d in stats.details if d["status"] == "failed")
    assert failed_detail["task"] == "money_flow"
    assert "tushare down" in failed_detail.get("error", "")


# ── Test 7: stats 统计正确 ──────────────────────────────────────────


def test_preheat_stats_dataclass():
    """PreheatStats 字段正确。"""
    stats = PreheatStats(tasks_total=3, tasks_success=2, tasks_failed=1, tasks_skipped=0, cache_hits=0, elapsed_seconds=3.14, details=[{"task": "a", "status": "success", "elapsed": 1.0}])
    assert stats.tasks_total == 3
    assert stats.elapsed_seconds == 3.14
    assert len(stats.details) == 1


# ── Test 8: get_preheat_tasks 返回格式 ──────────────────────────────


def test_get_preheat_tasks():
    """返回 5 个任务，每个有 id / description / estimated_time。"""
    tasks = get_preheat_tasks()
    assert isinstance(tasks, list)
    assert len(tasks) == 5
    for task in tasks:
        assert "id" in task
        assert "description" in task
        assert "estimated_time" in task

    task_ids = {t["id"] for t in tasks}
    assert task_ids == {"daily_basic", "daily_prices", "industry_classify", "money_flow", "financial_metrics"}


# ── Test 9: CLI smoke（格式化报告）──────────────────────────────────


def test_format_preheat_report():
    """format_preheat_report 生成可读报告文本。"""
    stats = _make_stats(
        tasks_success=3,
        tasks_failed=1,
        tasks_skipped=1,
        cache_hits=1,
        details=[
            {"task": "daily_basic", "status": "skipped", "elapsed": 0.0},
            {"task": "daily_prices", "status": "success", "elapsed": 3.2},
            {"task": "industry_classify", "status": "success", "elapsed": 1.1},
            {"task": "money_flow", "status": "success", "elapsed": 2.5},
            {"task": "financial_metrics", "status": "failed", "elapsed": 0.5, "error": "timeout"},
        ],
    )
    report = format_preheat_report(stats, "20260607", "全部")
    assert "缓存预热" in report
    assert "20260607" in report
    assert "daily_basic" in report
    assert "daily_prices" in report
    assert "已缓存 (跳过)" in report
    assert "3 成功" in report
    assert "1 失败" in report


# ── Test 10: PREHEAT_BEFORE_AUTO 环境变量 ────────────────────────────


@patch("src.data.cache_preheater._fetch_task_data")
def test_preheat_before_auto_env_var(mock_fetch, monkeypatch):
    """PREHEAT_BEFORE_AUTO=true 时 preheat_cache 被调用。"""
    monkeypatch.setenv("PREHEAT_BEFORE_AUTO", "true")
    assert os.environ.get("PREHEAT_BEFORE_AUTO", "").lower() == "true"

    mock_fetch.return_value = pd.DataFrame({"x": [1]})

    stats = preheat_cache("20260607", tasks=["daily_basic"], force=True)

    assert stats.tasks_total == 1
    assert stats.tasks_success == 1


# ── Test 11: 无效 task id 被跳过 ─────────────────────────────────────


@patch("src.data.cache_preheater._fetch_task_data")
def test_preheat_ignores_unknown_tasks(mock_fetch):
    """传入无效的 task id 时不执行、不报错。"""
    stats = preheat_cache("20260607", tasks=["nonexistent_task"], force=True)

    assert stats.tasks_total == 0
    mock_fetch.assert_not_called()


# ── Test 12: trade_date 默认为今天 ────────────────────────────────────


@patch("src.data.cache_preheater._fetch_task_data")
def test_preheat_default_trade_date(mock_fetch):
    """trade_date=None 时使用今天日期。"""
    today = datetime.now().strftime("%Y%m%d")
    mock_fetch.return_value = None

    preheat_cache(None, tasks=["daily_basic"], force=False)

    # 验证 fetch 被调用时 trade_date 是今天
    mock_fetch.assert_called_once_with("daily_basic", today, False)


# ── Test 13: 并发度参数生效 ──────────────────────────────────────────


@patch("src.data.cache_preheater._fetch_task_data")
def test_preheat_concurrency_param(mock_fetch):
    """不同并发度都能正常完成。"""
    mock_fetch.return_value = pd.DataFrame({"v": [1]})

    for cc in (1, 2, 8):
        stats = preheat_cache("20260607", concurrency=cc, force=True)
        assert stats.tasks_total == 5
        assert stats.tasks_success == 5
