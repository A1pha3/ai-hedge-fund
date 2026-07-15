"""资金流数据存储测试。用 tmp_path 隔离缓存。"""

from __future__ import annotations

import pandas as pd
import pytest

from src.screening.offensive.data.fund_flow_store import FundFlowStore
from src.screening.offensive.pit_evidence import PITEvidenceError


def _sample_df():
    return pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-07-01", "2026-07-02", "2026-07-03"]),
            "close": [10.0, 10.5, 10.2],
            "pct_change": [1.0, 5.0, -2.86],
            "main_net_inflow": [1_000_000, -500_000, 200_000],
            "main_net_pct": [5.0, -2.5, 1.0],
        }
    )


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


def test_save_imputes_wholly_absent_ticker_for_legacy_generic_cache(tmp_path):
    path = tmp_path / "X.csv"
    path.write_text(
        "date,close,pct_change,main_net_inflow,main_net_pct\n"
        "20260701,10,1,1000,2\n",
        encoding="utf-8",
    )
    store = FundFlowStore(cache_dir=tmp_path)

    count = store.save(
        "X",
        pd.DataFrame(
            {
                "date": pd.to_datetime(["2026-07-02"]),
                "close": [11],
                "pct_change": [2],
                "main_net_inflow": [2000],
                "main_net_pct": [3],
            }
        ),
    )

    persisted = pd.read_csv(path, dtype={"date": str, "ticker": str})
    assert count == 2
    assert persisted["date"].tolist() == ["20260701", "20260702"]
    assert persisted["ticker"].tolist() == ["X", "X"]
    assert persisted["main_net_inflow"].tolist() == [1000, 2000]


def test_save_rejects_explicit_legacy_ticker_mismatch_without_write(tmp_path):
    path = tmp_path / "X.csv"
    path.write_text(
        "date,ticker,close,pct_change,main_net_inflow,main_net_pct\n"
        "20260701,Y,10,1,1000,2\n",
        encoding="utf-8",
    )
    before = path.read_bytes()
    store = FundFlowStore(cache_dir=tmp_path)

    with pytest.raises(PITEvidenceError, match="ticker identity mismatch"):
        store.save(
            "X",
            pd.DataFrame(
                {
                    "date": pd.to_datetime(["2026-07-02"]),
                    "close": [11],
                    "pct_change": [2],
                    "main_net_inflow": [2000],
                    "main_net_pct": [3],
                }
            ),
        )

    assert path.read_bytes() == before
