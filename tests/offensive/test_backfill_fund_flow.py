"""资金流 backfill 脚本测试 — resume/batch/error 隔离逻辑。"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from scripts.backfill_fund_flow import (
    BackfillStats,
    load_candidate_tickers,
    backfill_ticker,
    backfill_batch,
    _is_fresh,
    _latest_date_in_store,
)
from src.screening.offensive.data.fund_flow_store import FundFlowStore


def _fake_fetch_returns_data(ticker):
    return pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-06-01", "2026-06-02"]),
            "close": [10.0, 10.5],
            "pct_change": [1.0, 5.0],
            "main_net_inflow": [1_000_000, -500_000],
            "main_net_pct": [5.0, -2.5],
        }
    )


def _fake_fetch_raises(ticker):
    raise ConnectionError("network down")


def _fake_fetch_returns_empty(ticker):
    return pd.DataFrame()


# ---- load_candidate_tickers ----


def test_load_candidate_tickers_from_report(tmp_path):
    report = tmp_path / "auto_screening_20260706.json"
    report.write_text(
        json.dumps(
            {
                "recommendations": [
                    {"ticker": "300054"},
                    {"ticker": "000001"},
                    {"ticker": "300054"},  # 重复
                    {"ticker": ""},
                    {"name": "no ticker"},
                ]
            }
        ),
        encoding="utf-8",
    )
    result = load_candidate_tickers(report)
    assert result == ["300054", "000001"]  # 去重保序, 排除空/缺失


def test_load_candidate_tickers_missing_file(tmp_path):
    assert load_candidate_tickers(tmp_path / "nonexistent.json") == []


# ---- _is_fresh ----


def test_is_fresh_true_within_threshold():
    assert _is_fresh("20260701", "20260703", fresh_days=3) is True


def test_is_fresh_false_beyond_threshold():
    assert _is_fresh("20260601", "20260706", fresh_days=3) is False


def test_is_fresh_none_date():
    assert _is_fresh(None, "20260706") is False


# ---- _latest_date_in_store ----


def test_latest_date_in_store_reads_max(tmp_path):
    store = FundFlowStore(cache_dir=tmp_path)
    store.save(
        "X",
        pd.DataFrame(
            {
                "date": pd.to_datetime(["2026-06-01", "2026-06-05", "2026-06-03"]),
                "close": [10, 11, 10.5],
                "pct_change": [0, 10, -4.5],
                "main_net_inflow": [1, 2, 3],
                "main_net_pct": [0.1, 0.2, 0.3],
            }
        ),
    )
    latest = _latest_date_in_store(tmp_path, "X")
    assert latest == "20260605"


def test_latest_date_in_store_missing_file(tmp_path):
    assert _latest_date_in_store(tmp_path, "MISSING") is None


# ---- backfill_ticker ----


def test_backfill_ticker_saves_new(tmp_path):
    store = FundFlowStore(cache_dir=tmp_path)
    result = backfill_ticker(store, "X", _fake_fetch_returns_data, today="20260706", fresh_days=3)
    assert result == "saved"
    assert store.get("X", "20260601") is not None  # 真落盘


def test_backfill_ticker_skips_fresh(tmp_path):
    """已有近期数据 → skipped_fresh。"""
    store = FundFlowStore(cache_dir=tmp_path)
    # 先存一份 2026-07-05 的数据 (距今 1 天)
    store.save(
        "X",
        pd.DataFrame(
            {
                "date": pd.to_datetime(["2026-07-05"]),
                "close": [10],
                "pct_change": [0],
                "main_net_inflow": [1],
                "main_net_pct": [0.1],
            }
        ),
    )
    calls = []

    def _tracking_fetch(t):
        calls.append(t)
        return _fake_fetch_returns_data(t)

    result = backfill_ticker(store, "X", _tracking_fetch, today="20260706", fresh_days=3)
    assert result == "skipped_fresh"
    assert calls == []  # 没调 fetch (resume 生效)


def test_backfill_ticker_handles_fetch_error(tmp_path):
    store = FundFlowStore(cache_dir=tmp_path)
    result = backfill_ticker(store, "X", _fake_fetch_raises, today="20260706", fresh_days=3)
    assert result == "failed"


def test_backfill_ticker_handles_empty_result(tmp_path):
    store = FundFlowStore(cache_dir=tmp_path)
    result = backfill_ticker(store, "X", _fake_fetch_returns_empty, today="20260706", fresh_days=3)
    assert result == "failed"


# ---- backfill_batch ----


def test_backfill_batch_aggregates_stats(tmp_path):
    """3 只: 1 正常 + 1 fetch 异常 + 1 空数据 → saved=1 failed=2。"""
    fetch_map = {
        "OK": _fake_fetch_returns_data,
        "FAIL": _fake_fetch_raises,
        "EMPTY": _fake_fetch_returns_empty,
    }

    def _dispatch_fetch(t):
        return fetch_map[t](t)

    stats = backfill_batch(
        tickers=["OK", "FAIL", "EMPTY"],
        cache_dir=tmp_path,
        rate_limit_sec=0,  # 测试不等
        fetch_fn=_dispatch_fetch,
        today="20260706",
    )
    assert stats.total == 3
    assert stats.saved == 1
    assert stats.failed == 2
    assert "FAIL" in stats.failed_tickers
    assert "EMPTY" in stats.failed_tickers


def test_backfill_batch_max_tickers_limits_queue(tmp_path):
    stats = backfill_batch(
        tickers=["A", "B", "C", "D"],
        cache_dir=tmp_path,
        rate_limit_sec=0,
        max_tickers=2,
        fetch_fn=_fake_fetch_returns_data,
        today="20260706",
    )
    assert stats.total == 2  # 只处理前 2 只


def test_backfill_batch_resumes_on_second_run(tmp_path):
    """第一次 backfill 后, 第二次跑同 ticker → skipped_fresh。"""

    # 第一次: 存数据 (用 2026-07-05 近期日期)
    def _fetch_with_recent_date(t):
        return pd.DataFrame(
            {
                "date": pd.to_datetime(["2026-07-05"]),
                "close": [10],
                "pct_change": [0],
                "main_net_inflow": [1],
                "main_net_pct": [0.1],
            }
        )

    stats1 = backfill_batch(
        tickers=["X"],
        cache_dir=tmp_path,
        rate_limit_sec=0,
        fetch_fn=_fetch_with_recent_date,
        today="20260706",
        fresh_days=3,
    )
    assert stats1.saved == 1

    # 第二次: 应 skip
    stats2 = backfill_batch(
        tickers=["X"],
        cache_dir=tmp_path,
        rate_limit_sec=0,
        fetch_fn=_fetch_with_recent_date,
        today="20260706",
        fresh_days=3,
    )
    assert stats2.skipped_fresh == 1
    assert stats2.saved == 0
