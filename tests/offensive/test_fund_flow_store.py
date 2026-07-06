"""资金流数据存储测试。用 tmp_path 隔离缓存。"""
from __future__ import annotations

import pandas as pd

from src.screening.offensive.data.fund_flow_store import FundFlowStore, FundFlowRecord


def _sample_df():
    return pd.DataFrame({
        "date": pd.to_datetime(["2026-07-01", "2026-07-02", "2026-07-03"]),
        "close": [10.0, 10.5, 10.2],
        "pct_change": [1.0, 5.0, -2.86],
        "main_net_inflow": [1_000_000, -500_000, 200_000],
        "main_net_pct": [5.0, -2.5, 1.0],
    })


def test_save_and_get_roundtrip(tmp_path):
    store = FundFlowStore(cache_dir=tmp_path)
    n = store.save("300054", _sample_df())
    assert n == 3

    rec = store.get("300054", "20260701")
    assert rec is not None
    assert rec.ticker == "300054"
    assert rec.date == "20260701"
    assert rec.main_net_inflow == 1_000_000


def test_get_missing_returns_none(tmp_path):
    store = FundFlowStore(cache_dir=tmp_path)
    assert store.get("300054", "20260701") is None


def test_get_range_filters_by_date(tmp_path):
    store = FundFlowStore(cache_dir=tmp_path)
    store.save("300054", _sample_df())
    rng = store.get_range("300054", "20260702", "20260703")
    assert len(rng) == 2
    assert rng[0].date == "20260702"
    assert rng[1].date == "20260703"


def test_save_overwrites_idempotent(tmp_path):
    """重复 save 同一 ticker 不重复, 不报错。"""
    store = FundFlowStore(cache_dir=tmp_path)
    store.save("300054", _sample_df())
    n2 = store.save("300054", _sample_df())  # 同数据再存
    assert n2 == 3
    rng = store.get_range("300054", "20260701", "20260703")
    assert len(rng) == 3  # 不重复
