"""Tests for scripts/backfill_fund_flow_history.py — 合并/幂等/续跑/失败月语义."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from scripts.backfill_fund_flow_history import (  # noqa: E402
    group_by_month,
    load_trade_days,
    run_backfill,
)


def _frame(day: str, inflow: float) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": pd.to_datetime([day], format="%Y%m%d"),
            "close": [float("nan")],
            "pct_change": [0.0],
            "main_net_inflow": [inflow],
            "main_net_pct": [float("nan")],
            "big_net_inflow": [inflow],
            "super_big_net_inflow": [inflow],
            "medium_net_inflow": [inflow],
            "small_net_inflow": [inflow],
        }
    )


def test_load_trade_days_filters_range(tmp_path) -> None:
    cal = tmp_path / "cal.json"
    cal.write_text('["20220103","20220104","20220105","20250705"]', encoding="utf-8")
    days = load_trade_days(cal, "20220104", "20250704")
    assert days == ["20220104", "20220105"]


def test_group_by_month() -> None:
    months = group_by_month(["20220104", "20220131", "20220201"])
    assert months == {"202201": ["20220104", "20220131"], "202202": ["20220201"]}


def test_run_backfill_merges_and_is_idempotent(tmp_path) -> None:
    days = ["20220104", "20220105"]
    fetch = lambda day: {"000001": _frame(day, 100.0)}  # noqa: E731
    kwargs = dict(days=days, universe={"000001"}, cache_dir=tmp_path, pace_sec=0.0, fetch_fn=fetch, log=lambda _m: None)

    first = run_backfill(**kwargs)
    assert first["months_done"] == ["202201"]
    df = pd.read_csv(tmp_path / "000001.csv", dtype={"date": str})
    assert sorted(df["date"]) == days

    # 重跑: 月份已在进度文件 → 跳过, 不产生重复行
    second = run_backfill(**kwargs)
    assert second["months_done"] == []
    assert second["months_skipped"] == ["202201"]
    df2 = pd.read_csv(tmp_path / "000001.csv", dtype={"date": str})
    assert len(df2) == 2


def test_run_backfill_failed_day_aborts_month_for_rerun(tmp_path) -> None:
    days = ["20220104", "20220105"]
    calls = {"n": 0}

    def flaky_fetch(day):
        calls["n"] += 1
        return {} if day == "20220105" else {"000001": _frame(day, 1.0)}

    result = run_backfill(
        days=days, universe={"000001"}, cache_dir=tmp_path, pace_sec=0.0, fetch_fn=flaky_fetch, log=lambda _m: None
    )
    # 有一天失败 → 整月不落盘不记进度 (宁可重拉, 不留洞内假象)
    assert result["failed_days"] == ["20220105"]
    assert result["months_done"] == []
    assert not (tmp_path / "000001.csv").exists()


def test_run_backfill_universe_filter(tmp_path) -> None:
    days = ["20220104"]
    fetch = lambda day: {"000001": _frame(day, 1.0), "600519": _frame(day, 2.0)}  # noqa: E731
    run_backfill(days=days, universe={"000001"}, cache_dir=tmp_path, pace_sec=0.0, fetch_fn=fetch, log=lambda _m: None)
    assert (tmp_path / "000001.csv").exists()
    assert not (tmp_path / "600519.csv").exists()
