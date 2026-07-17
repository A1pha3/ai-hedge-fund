from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import Mock

import pandas as pd
import pytest


class _ExplodingString:
    def __str__(self):
        raise RuntimeError("cannot stringify")


def _daily_prices(rows: list[dict]) -> pd.DataFrame:
    defaults = {
        "ts_code": "000001.SZ",
        "trade_date": "20260708",
        "open": 10.0,
        "high": 10.5,
        "low": 9.8,
        "close": 10.2,
        "pct_chg": 2.0,
        "vol": 12345.0,
    }
    return pd.DataFrame([{**defaults, **row} for row in rows])


def _history_rows(start: str = "2026-05-20", periods: int = 35) -> pd.DataFrame:
    dates = pd.bdate_range(start, periods=periods)
    # H3 fix: 确保包含 trade_date 20260708 的行
    dates = dates.tolist()
    trade_date = pd.Timestamp("2026-07-08")
    if trade_date not in dates:
        dates.append(trade_date)
    return pd.DataFrame(
        {
            "date": [date.strftime("%Y-%m-%d") for date in dates],
            "close": [10.0 + index * 0.1 for index in range(len(dates))],
            "open": [9.9 + index * 0.1 for index in range(len(dates))],
            "high": [10.2 + index * 0.1 for index in range(len(dates))],
            "low": [9.8 + index * 0.1 for index in range(len(dates))],
            "pct_change": [1.0 for _ in range(len(dates))],
            "volume": [1000.0 + index for index in range(len(dates))],
        }
    )


@pytest.mark.parametrize(
    "malformed_batch",
    (
        [],
        {"ts_code": "000001.SZ"},
        pd.DataFrame(),
        pd.DataFrame({"ts_code": ["000001.SZ"]}),
        _daily_prices([{"trade_date": "not-a-date"}]),
        _daily_prices([{"ts_code": "bad"}]),
        _daily_prices([{"open": True}]),
        _daily_prices([{"close": float("inf")}]),
        _daily_prices([{"open": _ExplodingString()}]),
    ),
)
def test_malformed_daily_batch_returns_exact_key_failed_result(
    tmp_path,
    malformed_batch,
):
    from datetime import date

    from src.screening.offensive.cache_readiness import (
        FundFlowStatus,
        PriceStatus,
        SuspensionEvidence,
    )
    from src.screening.offensive.cache_refresh import refresh_daily_action_caches

    result = refresh_daily_action_caches(
        "20260713",
        price_cache_dir=tmp_path / "price",
        fund_flow_cache_dir=tmp_path / "flow",
        snapshot_dir=tmp_path / "snapshots",
        daily_prices_df=malformed_batch,
        target_tickers=["000001"],
        suspension_loader=lambda _trade_date: SuspensionEvidence.available(
            date(2026, 7, 13), set()
        ),
        refresh_industry_index=False,
        refresh_fund_flow=False,
    )

    assert result.universe_tickers == ("000001",)
    assert tuple(result.outcomes) == ("000001",)
    assert result.daily_batch_fingerprint is None
    assert result.outcomes["000001"].price_status is PriceStatus.FAILED
    assert result.outcomes["000001"].fund_flow_status is FundFlowStatus.NOT_ATTEMPTED
    assert result.outcomes["000001"].evidence_fingerprints == {}


def test_price_evidence_is_bound_to_frame_captured_before_post_write_replacement(
    tmp_path,
    monkeypatch,
):
    from datetime import date
    from pathlib import Path

    from src.screening.offensive import cache_refresh as cr
    from src.screening.offensive.cache_readiness import SuspensionEvidence
    from src.screening.offensive.pit_evidence import canonical_price_fingerprint

    price_cache = tmp_path / "price"
    price_cache.mkdir()
    (price_cache / "000001.csv").write_text(
        "date,close,open,high,low,pct_change,volume\n"
        "2026-07-10,10,9.9,10.2,9.8,1,1000\n",
        encoding="utf-8",
    )
    captured: dict[str, pd.DataFrame] = {}
    original_atomic_write = cr.atomic_write_csv

    def write_then_replace(path, frame):
        captured[Path(path).stem] = frame.copy(deep=True)
        original_atomic_write(path, frame)
        Path(path).write_text(
            "date,close,open,high,low,pct_change,volume\n"
            "2026-07-13,999,999,999,999,999,999\n",
            encoding="utf-8",
        )

    monkeypatch.setattr(cr, "atomic_write_csv", write_then_replace)
    result = cr.refresh_daily_action_caches(
        "20260713",
        price_cache_dir=price_cache,
        fund_flow_cache_dir=tmp_path / "flow",
        snapshot_dir=tmp_path / "snapshots",
        target_tickers=["000001"],
        daily_prices_df=_daily_prices(
            [{"ts_code": "000001.SZ", "trade_date": "20260713", "close": 10.5}]
        ),
        suspension_loader=lambda _trade_date: SuspensionEvidence.available(
            date(2026, 7, 13), set()
        ),
        refresh_industry_index=False,
        refresh_fund_flow=False,
    )

    assert result.outcomes["000001"].evidence_fingerprints["price"] == (
        canonical_price_fingerprint(captured["000001"], "000001", "20260713")
    )
    assert result.outcomes["000001"].price_history_rows == len(captured["000001"])


def test_price_evidence_is_copied_before_writer_mutates_input_frame(
    tmp_path,
    monkeypatch,
):
    from datetime import date

    from src.screening.offensive import cache_refresh as cr
    from src.screening.offensive.cache_readiness import SuspensionEvidence
    from src.screening.offensive.pit_evidence import canonical_price_fingerprint

    price_cache = tmp_path / "price"
    price_cache.mkdir()
    (price_cache / "000001.csv").write_text(
        "date,close,open,high,low,pct_change,volume\n"
        "2026-07-10,10,9.9,10.2,9.8,1,1000\n",
        encoding="utf-8",
    )
    captured_before_write: list[pd.DataFrame] = []
    original_atomic_write = cr.atomic_write_csv

    def write_then_mutate_frame(path, frame):
        captured_before_write.append(frame.copy(deep=True))
        original_atomic_write(path, frame)
        frame.loc[:, "close"] = 999

    monkeypatch.setattr(cr, "atomic_write_csv", write_then_mutate_frame)
    result = cr.refresh_daily_action_caches(
        "20260713",
        price_cache_dir=price_cache,
        fund_flow_cache_dir=tmp_path / "flow",
        snapshot_dir=tmp_path / "snapshots",
        target_tickers=["000001"],
        daily_prices_df=_daily_prices(
            [{"ts_code": "000001.SZ", "trade_date": "20260713", "close": 10.5}]
        ),
        suspension_loader=lambda _trade_date: SuspensionEvidence.available(
            date(2026, 7, 13), set()
        ),
        refresh_industry_index=False,
        refresh_fund_flow=False,
    )

    assert result.outcomes["000001"].evidence_fingerprints["price"] == (
        canonical_price_fingerprint(
            captured_before_write[-1],
            "000001",
            "20260713",
        )
    )


def test_price_refresh_preserves_rows_after_requested_trade_date(tmp_path):
    from datetime import date

    from src.screening.offensive.cache_readiness import SuspensionEvidence
    from src.screening.offensive.cache_refresh import refresh_daily_action_caches

    price_cache = tmp_path / "price"
    price_cache.mkdir()
    path = price_cache / "000001.csv"
    path.write_text(
        "date,close,open,high,low,pct_change,volume\n"
        "2026-07-10,10,9.9,10.2,9.8,1,1000\n"
        "2026-07-14,14,13.9,14.2,13.8,4,1400\n",
        encoding="utf-8",
    )

    result = refresh_daily_action_caches(
        "20260713",
        price_cache_dir=price_cache,
        fund_flow_cache_dir=tmp_path / "flow",
        snapshot_dir=tmp_path / "snapshots",
        target_tickers=["000001"],
        daily_prices_df=_daily_prices(
            [{"ts_code": "000001.SZ", "trade_date": "20260713", "close": 13}]
        ),
        suspension_loader=lambda _trade_date: SuspensionEvidence.available(
            date(2026, 7, 13), set()
        ),
        refresh_industry_index=False,
        refresh_fund_flow=False,
    )

    persisted = pd.read_csv(path, dtype={"date": str})
    assert persisted["date"].tolist() == [
        "2026-07-10",
        "2026-07-13",
        "2026-07-14",
    ]
    assert persisted.loc[persisted["date"] == "2026-07-14", "close"].item() == 14
    assert result.outcomes["000001"].price_history_rows == 2


def test_flow_refresh_preserves_rows_after_requested_trade_date(tmp_path):
    from datetime import date

    from src.screening.offensive.cache_readiness import SuspensionEvidence
    from src.screening.offensive.cache_refresh import refresh_daily_action_caches

    price_cache = tmp_path / "price"
    flow_cache = tmp_path / "flow"
    price_cache.mkdir()
    flow_cache.mkdir()
    (price_cache / "000001.csv").write_text(
        "date,close,open,high,low,pct_change,volume\n"
        "2026-07-10,10,9.9,10.2,9.8,1,1000\n",
        encoding="utf-8",
    )
    flow_path = flow_cache / "000001.csv"
    flow_path.write_text(
        "date,ticker,close,pct_change,main_net_inflow,main_net_pct\n"
        "20260710,000001,10,1,1000,2\n"
        "20260714,000001,14,4,1400,5\n",
        encoding="utf-8",
    )

    result = refresh_daily_action_caches(
        "20260713",
        price_cache_dir=price_cache,
        fund_flow_cache_dir=flow_cache,
        snapshot_dir=tmp_path / "snapshots",
        target_tickers=["000001"],
        daily_prices_df=_daily_prices(
            [{"ts_code": "000001.SZ", "trade_date": "20260713", "close": 13}]
        ),
        fund_flow_fetch_fn=lambda *_args, **_kwargs: pd.DataFrame(
            [
                {
                    "date": "20260713",
                    "close": 13,
                    "pct_change": 3,
                    "main_net_inflow": 1300,
                    "main_net_pct": 4,
                }
            ]
        ),
        suspension_loader=lambda _trade_date: SuspensionEvidence.available(
            date(2026, 7, 13), set()
        ),
        refresh_industry_index=False,
        fund_flow_rate_limit_sec=0,
    )

    persisted = pd.read_csv(flow_path, dtype={"date": str, "ticker": str})
    assert persisted["date"].tolist() == ["20260710", "20260713", "20260714"]
    assert persisted.loc[persisted["date"] == "20260714", "close"].item() == 14
    assert result.outcomes["000001"].fund_flow_history_rows == 2


def test_flow_evidence_is_bound_to_frame_captured_before_post_write_replacement(
    tmp_path,
    monkeypatch,
):
    from datetime import date

    from src.screening.offensive.cache_readiness import SuspensionEvidence
    from src.screening.offensive.cache_refresh import refresh_daily_action_caches
    from src.screening.offensive.data.fund_flow_store import FundFlowStore
    from src.screening.offensive.pit_evidence import canonical_flow_fingerprint

    captured: dict[str, pd.DataFrame] = {}
    original_save = FundFlowStore.save

    def save_then_replace(self, ticker, frame, *args, **kwargs):
        saved = original_save(self, ticker, frame, *args, **kwargs)
        path = self._path(ticker)
        captured[ticker] = pd.read_csv(path, dtype={"date": str, "ticker": str})
        path.write_text(
            "date,ticker,close,pct_change,main_net_inflow,main_net_pct\n"
            "20260713,000001,999,999,999,999\n",
            encoding="utf-8",
        )
        return saved

    monkeypatch.setattr(FundFlowStore, "save", save_then_replace)
    result = refresh_daily_action_caches(
        "20260713",
        price_cache_dir=tmp_path / "price",
        fund_flow_cache_dir=tmp_path / "flow",
        snapshot_dir=tmp_path / "snapshots",
        target_tickers=["000001"],
        daily_prices_df=_daily_prices(
            [{"ts_code": "000001.SZ", "trade_date": "20260713"}]
        ),
        backfill_price_history_fn=lambda *_args: _history_rows(
            start="2026-05-26", periods=34
        ),
        fund_flow_fetch_fn=lambda *_args, **_kwargs: pd.DataFrame(
            [
                {
                    "date": "20260713",
                    "close": 10,
                    "pct_change": 1,
                    "main_net_inflow": 1000,
                    "main_net_pct": 2,
                }
            ]
        ),
        suspension_loader=lambda _trade_date: SuspensionEvidence.available(
            date(2026, 7, 13), set()
        ),
        refresh_industry_index=False,
        fund_flow_rate_limit_sec=0,
    )

    assert result.outcomes["000001"].evidence_fingerprints["fund_flow"] == (
        canonical_flow_fingerprint(captured["000001"], "000001", "20260713")
    )
    assert result.outcomes["000001"].fund_flow_history_rows == len(
        captured["000001"]
    )


def test_failed_price_write_does_not_retain_baseline_fingerprint(tmp_path, monkeypatch):
    from datetime import date

    from src.screening.offensive import cache_refresh as cr
    from src.screening.offensive.cache_readiness import PriceStatus, SuspensionEvidence

    price_cache = tmp_path / "price"
    price_cache.mkdir()
    (price_cache / "000001.csv").write_text(
        "date,close,open,high,low,pct_change,volume\n"
        "2026-07-10,10,9.9,10.2,9.8,1,1000\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        cr,
        "atomic_write_csv",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("write failed")),
    )

    result = cr.refresh_daily_action_caches(
        "20260713",
        price_cache_dir=price_cache,
        fund_flow_cache_dir=tmp_path / "flow",
        snapshot_dir=tmp_path / "snapshots",
        target_tickers=["000001"],
        daily_prices_df=_daily_prices(
            [{"ts_code": "000001.SZ", "trade_date": "20260713"}]
        ),
        suspension_loader=lambda _trade_date: SuspensionEvidence.available(
            date(2026, 7, 13), set()
        ),
        refresh_industry_index=False,
        refresh_fund_flow=False,
    )

    assert result.outcomes["000001"].price_status is PriceStatus.FAILED
    assert "price" not in result.outcomes["000001"].evidence_fingerprints


def test_malformed_price_baseline_is_rejected_before_atomic_write(tmp_path):
    from datetime import date

    from src.screening.offensive.cache_readiness import PriceStatus, SuspensionEvidence
    from src.screening.offensive.cache_refresh import refresh_daily_action_caches

    price_cache = tmp_path / "price"
    price_cache.mkdir()
    path = price_cache / "000001.csv"
    path.write_text(
        "date,close,open,low,pct_change,volume\n"
        "2026-07-10,10,9.9,9.8,1,1000\n",
        encoding="utf-8",
    )
    before = path.read_bytes()

    result = refresh_daily_action_caches(
        "20260713",
        price_cache_dir=price_cache,
        fund_flow_cache_dir=tmp_path / "flow",
        snapshot_dir=tmp_path / "snapshots",
        target_tickers=["000001"],
        daily_prices_df=_daily_prices(
            [{"ts_code": "000001.SZ", "trade_date": "20260713"}]
        ),
        suspension_loader=lambda _trade_date: SuspensionEvidence.available(
            date(2026, 7, 13), set()
        ),
        refresh_industry_index=False,
        refresh_fund_flow=False,
    )

    assert path.read_bytes() == before
    assert result.outcomes["000001"].price_status is PriceStatus.FAILED
    assert "price" not in result.outcomes["000001"].evidence_fingerprints


def test_malformed_flow_provider_is_rejected_before_atomic_write(tmp_path):
    from datetime import date

    from src.screening.offensive.cache_readiness import (
        FundFlowStatus,
        SuspensionEvidence,
    )
    from src.screening.offensive.cache_refresh import refresh_daily_action_caches

    price_cache = tmp_path / "price"
    flow_cache = tmp_path / "flow"
    price_cache.mkdir()
    flow_cache.mkdir()
    (price_cache / "000001.csv").write_text(
        "date,close,open,high,low,pct_change,volume\n"
        "2026-07-10,10,9.9,10.2,9.8,1,1000\n",
        encoding="utf-8",
    )
    flow_path = flow_cache / "000001.csv"
    flow_path.write_text(
        "date,ticker,close,pct_change,main_net_inflow,main_net_pct\n"
        "20260710,000001,10,1,1000,2\n",
        encoding="utf-8",
    )
    before = flow_path.read_bytes()

    result = refresh_daily_action_caches(
        "20260713",
        price_cache_dir=price_cache,
        fund_flow_cache_dir=flow_cache,
        snapshot_dir=tmp_path / "snapshots",
        target_tickers=["000001"],
        daily_prices_df=_daily_prices(
            [{"ts_code": "000001.SZ", "trade_date": "20260713"}]
        ),
        fund_flow_fetch_fn=lambda *_args, **_kwargs: pd.DataFrame(
            [{"date": "20260713"}]
        ),
        suspension_loader=lambda _trade_date: SuspensionEvidence.available(
            date(2026, 7, 13), set()
        ),
        refresh_industry_index=False,
        fund_flow_rate_limit_sec=0,
    )

    assert flow_path.read_bytes() == before
    assert result.outcomes["000001"].fund_flow_status is FundFlowStatus.FAILED
    assert "fund_flow" not in result.outcomes["000001"].evidence_fingerprints


def test_refresh_fetches_daily_batch_once_when_there_are_no_limit_ups(tmp_path):
    from src.screening.offensive.cache_refresh import refresh_daily_action_caches

    fetch = Mock(
        return_value=_daily_prices(
            [{"ts_code": "000001.SZ", "trade_date": "20260713", "pct_chg": 1.0}]
        )
    )

    result = refresh_daily_action_caches(
        "20260713",
        price_cache_dir=tmp_path / "price",
        fund_flow_cache_dir=tmp_path / "flow",
        snapshot_dir=tmp_path / "snapshots",
        fetch_daily_prices_batch=fetch,
        target_tickers=["000001"],
        backfill_price_history_fn=lambda *_args: _history_rows(),
        refresh_industry_index=False,
        refresh_fund_flow=False,
    )

    assert fetch.call_count == 1
    assert result.universe_tickers == ("000001",)


def test_refresh_classifies_suspensions_without_calling_them_missing(tmp_path):
    from datetime import date

    from src.screening.offensive.cache_readiness import (
        FundFlowStatus,
        PriceStatus,
        SuspensionEvidence,
    )
    from src.screening.offensive.cache_refresh import refresh_daily_action_caches

    result = refresh_daily_action_caches(
        "20260713",
        price_cache_dir=tmp_path / "price",
        fund_flow_cache_dir=tmp_path / "flow",
        snapshot_dir=tmp_path / "snapshots",
        daily_prices_df=_daily_prices(
            [{"ts_code": "000001.SZ", "trade_date": "20260713", "pct_chg": 1.0}]
        ),
        target_tickers=["000001", "002677"],
        backfill_price_history_fn=lambda *_args: _history_rows(
            start="2026-05-26", periods=34
        ),
        suspension_loader=lambda _trade_date: SuspensionEvidence.available(
            date(2026, 7, 13), {"002677"}
        ),
        refresh_industry_index=False,
        refresh_fund_flow=False,
    )

    assert result.outcomes["000001"].price_status is PriceStatus.CURRENT
    assert result.outcomes["002677"].price_status is PriceStatus.SUSPENDED
    assert result.outcomes["002677"].fund_flow_status is FundFlowStatus.SUSPENDED
    assert sum(result.stats.price_status_counts.values()) == 2
    assert sum(result.stats.fund_flow_status_counts.values()) == 2


def test_refresh_marks_stale_tickers_beyond_fund_flow_quota_not_attempted(tmp_path):
    from datetime import date

    from src.screening.offensive.cache_readiness import FundFlowStatus, SuspensionEvidence
    from src.screening.offensive.cache_refresh import refresh_daily_action_caches

    price_cache = tmp_path / "price"
    flow_cache = tmp_path / "flow"
    price_cache.mkdir()
    flow_cache.mkdir()
    for ticker in ("000001", "000002", "000003"):
        (price_cache / f"{ticker}.csv").write_text(
            "date,close,open,high,low,pct_change,volume\n"
            "2026-07-10,10,10,10,10,0,1000\n",
            encoding="utf-8",
        )
    (flow_cache / "000001.csv").write_text(
        "date,ticker,close,pct_change,main_net_inflow,main_net_pct\n"
        "20260713,000001,10,1,1000,2\n",
        encoding="utf-8",
    )
    fetched: list[str] = []

    def fetch_flow(ticker: str, **_kwargs) -> pd.DataFrame:
        fetched.append(ticker)
        return pd.DataFrame(
            [{"date": "20260713", "close": 10, "pct_change": 1, "main_net_inflow": 1, "main_net_pct": 1}]
        )

    result = refresh_daily_action_caches(
        "20260713",
        price_cache_dir=price_cache,
        fund_flow_cache_dir=flow_cache,
        snapshot_dir=tmp_path / "snapshots",
        daily_prices_df=_daily_prices(
            [
                {"ts_code": f"{ticker}.SZ", "trade_date": "20260713", "pct_chg": 1.0}
                for ticker in ("000001", "000002", "000003")
            ]
        ),
        suspension_loader=lambda _trade_date: SuspensionEvidence.available(
            date(2026, 7, 13), set()
        ),
        refresh_industry_index=False,
        fund_flow_fetch_fn=fetch_flow,
        fund_flow_rate_limit_sec=0,
        fund_flow_max_tickers=1,
    )

    assert fetched == ["000002"]
    assert result.outcomes["000001"].fund_flow_status is FundFlowStatus.CURRENT
    assert result.outcomes["000002"].fund_flow_status is FundFlowStatus.CURRENT
    assert result.outcomes["000003"].fund_flow_status is FundFlowStatus.NOT_ATTEMPTED
    assert sum(result.stats.fund_flow_status_counts.values()) == 3


def test_refresh_freezes_universe_before_cache_writes_and_keeps_bse_excluded(tmp_path):
    from datetime import date

    from src.screening.offensive.cache_readiness import SuspensionEvidence
    from src.screening.offensive.cache_refresh import refresh_daily_action_caches

    price_cache = tmp_path / "price"

    def mutate_directory(*_args) -> pd.DataFrame:
        price_cache.mkdir(parents=True, exist_ok=True)
        (price_cache / "000999.csv").write_text(
            "date,close\n2026-07-13,99\n",
            encoding="utf-8",
        )
        return _history_rows(start="2026-05-26", periods=34)

    result = refresh_daily_action_caches(
        "20260713",
        price_cache_dir=price_cache,
        fund_flow_cache_dir=tmp_path / "flow",
        snapshot_dir=tmp_path / "snapshots",
        target_tickers=["000001", "920088"],
        daily_prices_df=_daily_prices(
            [{"ts_code": "000001.SZ", "trade_date": "20260713", "pct_chg": 1.0}]
        ),
        backfill_price_history_fn=mutate_directory,
        suspension_loader=lambda _trade_date: SuspensionEvidence.available(
            date(2026, 7, 13), set()
        ),
        refresh_industry_index=False,
        refresh_fund_flow=False,
    )

    assert result.universe_tickers == ("000001",)
    assert tuple(result.outcomes) == ("000001",)


def test_resolve_daily_action_refresh_tickers_includes_candidate_pool(tmp_path):
    from src.screening.offensive.cache_refresh import resolve_daily_action_refresh_tickers

    price_cache = tmp_path / "price_cache"
    price_cache.mkdir()
    (price_cache / "000001.csv").write_text("date,close\n2026-07-08,10\n", encoding="utf-8")

    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()
    (snapshot_dir / "candidate_pool_20260708.json").write_text(
        json.dumps(
            [
                {"ticker": "000002"},
                {"ticker": "bad"},
                {"ts_code": "000003.SZ"},
            ]
        ),
        encoding="utf-8",
    )

    tickers = resolve_daily_action_refresh_tickers(
        "20260708",
        price_cache_dir=price_cache,
        snapshot_dir=snapshot_dir,
    )

    assert tickers == ["000001", "000002", "000003"]


def test_resolve_daily_action_refresh_tickers_excludes_beijing_exchange(tmp_path):
    """北交所 (4xx/8xx/92xx) 不进 --daily-action 宇宙: 不刷缓存、不扫描、不选股。"""
    from src.screening.offensive.cache_refresh import resolve_daily_action_refresh_tickers

    price_cache = tmp_path / "price_cache"
    price_cache.mkdir()
    for code in ("000001", "920088", "830799", "430418"):
        (price_cache / f"{code}.csv").write_text("date,close\n2026-07-08,10\n", encoding="utf-8")

    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()
    (snapshot_dir / "candidate_pool_20260708.json").write_text(
        json.dumps([{"ticker": "000002"}, {"ticker": "920123"}]),
        encoding="utf-8",
    )

    tickers = resolve_daily_action_refresh_tickers(
        "20260708",
        price_cache_dir=price_cache,
        snapshot_dir=snapshot_dir,
    )

    assert tickers == ["000001", "000002"]


def test_refresh_price_cache_updates_existing_tickers_only(tmp_path):
    from src.screening.offensive.cache_refresh import refresh_price_cache_from_daily_batch

    price_cache = tmp_path / "price_cache"
    price_cache.mkdir()
    (price_cache / "000001.csv").write_text(
        "date,close,open,high,low,pct_change,volume\n" "2026-07-06,9.8,9.7,9.9,9.6,1.1,1000\n",
        encoding="utf-8",
    )

    stats = refresh_price_cache_from_daily_batch(
        "20260708",
        price_cache_dir=price_cache,
        daily_prices_df=_daily_prices(
            [
                {
                    "ts_code": "000001.SZ",
                    "close": 10.2,
                    "open": 10.0,
                    "high": 10.5,
                    "low": 9.9,
                    "pct_chg": 4.08,
                    "vol": 2345.0,
                },
                {"ts_code": "000002.SZ", "close": 20.0},
            ]
        ),
    )

    updated = pd.read_csv(price_cache / "000001.csv", dtype={"date": str})
    assert list(updated["date"]) == ["2026-07-06", "2026-07-08"]
    latest = updated.iloc[-1]
    assert latest["close"] == 10.2
    assert latest["open"] == 10.0
    assert latest["high"] == 10.5
    assert latest["low"] == 9.9
    assert latest["pct_change"] == 4.08
    assert latest["volume"] == 2345.0
    assert not (price_cache / "000002.csv").exists()
    assert stats.price_total == 1
    assert stats.price_updated == 1
    assert stats.price_missing == 0


def test_refresh_price_cache_rejects_stale_daily_batch_rows(tmp_path):
    from src.screening.offensive.cache_refresh import refresh_price_cache_from_daily_batch

    price_cache = tmp_path / "price_cache"
    price_cache.mkdir()
    (price_cache / "000001.csv").write_text(
        "date,close,open,high,low,pct_change,volume\n" "2026-07-06,9.8,9.7,9.9,9.6,1.1,1000\n",
        encoding="utf-8",
    )

    stats = refresh_price_cache_from_daily_batch(
        "20260708",
        price_cache_dir=price_cache,
        daily_prices_df=_daily_prices(
            [
                {
                    "ts_code": "000001.SZ",
                    "trade_date": "20260706",
                    "close": 10.6,
                    "pct_chg": 8.16,
                    "vol": 3000.0,
                }
            ]
        ),
    )

    updated = pd.read_csv(price_cache / "000001.csv", dtype={"date": str})
    assert list(updated["date"]) == ["2026-07-06"]
    assert updated.iloc[0]["close"] == 9.8
    assert stats.price_updated == 0
    assert stats.price_missing == 1


def test_refresh_price_cache_backfills_new_target_ticker_before_daily_row(tmp_path):
    from src.screening.offensive.cache_refresh import refresh_price_cache_from_daily_batch

    price_cache = tmp_path / "price_cache"
    price_cache.mkdir()
    (price_cache / "000001.csv").write_text(
        "date,close,open,high,low,pct_change,volume\n" "2026-07-06,9.8,9.7,9.9,9.6,1.1,1000\n",
        encoding="utf-8",
    )

    backfilled: list[tuple[str, str, str]] = []

    def backfill_price_history(ticker: str, start_date: str, end_date: str) -> pd.DataFrame:
        backfilled.append((ticker, start_date, end_date))
        assert ticker == "000002"
        assert end_date == "20260708"
        return _history_rows()

    stats = refresh_price_cache_from_daily_batch(
        "20260708",
        price_cache_dir=price_cache,
        target_tickers=["000001", "000002"],
        daily_prices_df=_daily_prices(
            [
                {"ts_code": "000001.SZ", "close": 10.2, "pct_chg": 4.08, "vol": 2345.0},
                {"ts_code": "000002.SZ", "close": 20.0, "pct_chg": 5.0, "vol": 3456.0},
            ]
        ),
        backfill_price_history_fn=backfill_price_history,
    )

    created = pd.read_csv(price_cache / "000002.csv", dtype={"date": str})
    assert backfilled == [("000002", "20250604", "20260708")]  # 400-day lookback from 20260708
    assert len(created) == 36
    assert created.iloc[-1]["date"] == "2026-07-08"
    assert created.iloc[-1]["close"] == 20.0
    assert stats.price_total == 2
    assert stats.price_backfilled == 1
    assert stats.price_updated == 2
    assert stats.price_missing == 0


def test_refresh_price_cache_rejects_new_target_with_insufficient_history(tmp_path):
    from src.screening.offensive.cache_refresh import refresh_price_cache_from_daily_batch

    price_cache = tmp_path / "price_cache"
    price_cache.mkdir()

    stats = refresh_price_cache_from_daily_batch(
        "20260708",
        price_cache_dir=price_cache,
        target_tickers=["000002"],
        daily_prices_df=_daily_prices([{"ts_code": "000002.SZ", "close": 20.0}]),
        backfill_price_history_fn=lambda *_args: _history_rows(periods=5),
    )

    assert not (price_cache / "000002.csv").exists()
    assert stats.price_total == 1
    assert stats.price_backfilled == 0
    assert stats.price_insufficient_history == 1
    assert stats.price_updated == 0


def test_refresh_daily_action_caches_uses_candidate_pool_for_price_and_fund_flow(tmp_path):
    from src.screening.offensive.cache_refresh import refresh_daily_action_caches

    price_cache = tmp_path / "price_cache"
    price_cache.mkdir()
    (price_cache / "000001.csv").write_text(
        "date,close,open,high,low,pct_change,volume\n" "2026-07-06,9.8,9.7,9.9,9.6,1.1,1000\n",
        encoding="utf-8",
    )

    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()
    (snapshot_dir / "candidate_pool_20260708.json").write_text(
        json.dumps([{"ticker": "000002"}]),
        encoding="utf-8",
    )

    fund_flow_tickers: list[str] = []

    def fund_flow_fetch(ticker: str, start_date: str, end_date: str) -> pd.DataFrame:
        fund_flow_tickers.append(ticker)
        return pd.DataFrame(
            [
                {
                    "date": pd.Timestamp("2026-07-08"),
                    "close": 10.2,
                    "pct_change": 2.0,
                    "main_net_inflow": 1000000.0,
                    "main_net_pct": 3.5,
                }
            ]
        )

    stats = refresh_daily_action_caches(
        "20260708",
        price_cache_dir=price_cache,
        fund_flow_cache_dir=tmp_path / "fund_flow_cache",
        snapshot_dir=snapshot_dir,
        daily_prices_df=_daily_prices(
            [
                {"ts_code": "000001.SZ", "close": 10.2},
                {"ts_code": "000002.SZ", "close": 20.0},
            ]
        ),
        backfill_price_history_fn=lambda *_args: _history_rows(),
        fund_flow_fetch_fn=fund_flow_fetch,
        refresh_industry_index=False,
        fund_flow_rate_limit_sec=0,
    )

    assert (price_cache / "000002.csv").exists()
    assert stats.price_total == 2
    assert stats.price_backfilled == 1
    assert stats.fund_flow_total == 2
    assert set(fund_flow_tickers) == {"000001", "000002"}


def test_refresh_daily_action_caches_refreshes_industry_index_for_trade_date(tmp_path):
    from src.screening.offensive.cache_refresh import refresh_daily_action_caches

    calls: list[tuple[str, Path]] = []
    industry_dir = tmp_path / "industry_index_cache"

    stats = refresh_daily_action_caches(
        "20260708",
        price_cache_dir=tmp_path / "price_cache",
        fund_flow_cache_dir=tmp_path / "fund_flow_cache",
        industry_index_cache_dir=industry_dir,
        snapshot_dir=tmp_path / "snapshots",
        daily_prices_df=pd.DataFrame(),
        refresh_fund_flow=False,
        industry_index_backfill_fn=lambda *, end_date, cache_dir: calls.append(
            (end_date, cache_dir)
        )
        or {"农林牧渔": 1502},
    )

    assert calls == [("20260708", industry_dir)]
    assert stats.industry_index_total == 1502
    assert stats.industry_index_failed == 0


def test_refresh_daily_action_caches_uses_passed_trade_date_directly(tmp_path, monkeypatch):
    """H2 fix: refresh_daily_action_caches 直接使用传入的 trade_date, 不二次归一化.
    调用方 (run_auto_screening) 负责传入有效的交易日."""
    from src.screening.offensive import cache_refresh as cr

    price_cache = tmp_path / "price_cache"
    price_cache.mkdir()
    (price_cache / "000001.csv").write_text(
        "date,close,open,high,low,pct_change,volume\n2026-07-09,9.8,9.7,9.9,9.6,1.1,1000\n",
        encoding="utf-8",
    )

    fund_flow_dates: list[tuple[str, str, str]] = []

    def fund_flow_fetch(ticker: str, start_date: str, end_date: str) -> pd.DataFrame:
        fund_flow_dates.append((ticker, start_date, end_date))
        return pd.DataFrame(
            [
                {
                    "date": pd.Timestamp("2026-07-10"),
                    "close": 10.2,
                    "pct_change": 2.0,
                    "main_net_inflow": 1000000.0,
                    "main_net_pct": 3.5,
                }
            ]
        )

    stats = cr.refresh_daily_action_caches(
        "20260710",  # 直接传入有效交易日 (不再内部归一化)
        price_cache_dir=price_cache,
        fund_flow_cache_dir=tmp_path / "fund_flow_cache",
        snapshot_dir=tmp_path / "snapshots",
        target_tickers=["000001"],
        daily_prices_df=_daily_prices(
            [
                {
                    "ts_code": "000001.SZ",
                    "trade_date": "20260710",
                    "close": 10.2,
                    "pct_chg": 4.08,
                    "vol": 2345.0,
                }
            ]
        ),
        fund_flow_fetch_fn=fund_flow_fetch,
        refresh_industry_index=False,
        fund_flow_rate_limit_sec=0,
    )

    updated = pd.read_csv(price_cache / "000001.csv", dtype={"date": str})
    assert list(updated["date"])[-1] == "2026-07-10"
    assert stats.price_updated == 1
    assert stats.price_missing == 0
    assert stats.fund_flow_saved == 1
    assert fund_flow_dates == [("000001", "20260710", "20260710")]


def test_refresh_price_cache_is_idempotent_for_same_trade_date(tmp_path):
    from src.screening.offensive.cache_refresh import refresh_price_cache_from_daily_batch

    price_cache = tmp_path / "price_cache"
    price_cache.mkdir()
    (price_cache / "000001.csv").write_text(
        "date,close,open,high,low,pct_change,volume\n" "2026-07-08,9.8,9.7,9.9,9.6,1.1,1000\n",
        encoding="utf-8",
    )

    stats = refresh_price_cache_from_daily_batch(
        "20260708",
        price_cache_dir=price_cache,
        daily_prices_df=_daily_prices(
            [
                {
                    "ts_code": "000001.SZ",
                    "close": 10.6,
                    "pct_chg": 8.16,
                    "vol": 3000.0,
                }
            ]
        ),
    )

    updated = pd.read_csv(price_cache / "000001.csv", dtype={"date": str})
    assert list(updated["date"]) == ["2026-07-08"]
    assert updated.iloc[0]["close"] == 10.6
    assert updated.iloc[0]["pct_change"] == 8.16
    assert updated.iloc[0]["volume"] == 3000.0
    assert stats.price_updated == 1


def test_refresh_fund_flow_cache_saves_each_existing_ticker(tmp_path):
    from src.screening.offensive.cache_refresh import refresh_fund_flow_cache

    def fake_fetch(ticker: str, start_date: str, end_date: str) -> pd.DataFrame:
        if ticker == "000002":
            return pd.DataFrame()
        return pd.DataFrame(
            [
                {
                    "date": pd.Timestamp("2026-07-08"),
                    "close": 10.2,
                    "pct_change": 2.0,
                    "main_net_inflow": 1000000.0,
                    "main_net_pct": 3.5,
                }
            ]
        )

    fund_flow_cache = tmp_path / "fund_flow_cache"
    stats = refresh_fund_flow_cache(
        ["000001", "000002"],
        "20260708",
        fund_flow_cache_dir=fund_flow_cache,
        fetch_fn=fake_fetch,
        rate_limit_sec=0,
    )

    saved = pd.read_csv(fund_flow_cache / "000001.csv", dtype={"date": str, "ticker": str})
    assert saved.iloc[0]["date"] == "20260708"
    assert saved.iloc[0]["ticker"] == "000001"
    assert saved.iloc[0]["main_net_inflow"] == 1000000.0
    assert not (fund_flow_cache / "000002.csv").exists()
    assert stats.fund_flow_total == 2
    assert stats.fund_flow_saved == 1
    assert stats.fund_flow_empty == 1
    assert stats.fund_flow_failed == 0


def test_refresh_fund_flow_cache_distinguishes_suspended_from_data_anomaly(tmp_path, monkeypatch):
    """停牌股票在 fetch 前跳过 (fund_flow_suspended), 非停牌空返回标 fund_flow_empty."""
    from src.screening.offensive import cache_refresh as cr

    # mock 停牌列表: 000001 停牌, 000002 未停牌
    monkeypatch.setattr(
        cr,
        "_load_suspended_codes",
        lambda trade_date: {"000001"},
    )

    fetched: list[str] = []

    def fake_fetch(ticker: str, start_date: str, end_date: str) -> pd.DataFrame:
        fetched.append(ticker)
        return pd.DataFrame()  # 000002 返回空 (数据异常)

    stats = cr.refresh_fund_flow_cache(
        ["000001", "000002"],
        "20260708",
        fund_flow_cache_dir=tmp_path / "fund_flow_cache",
        fetch_fn=fake_fetch,
        rate_limit_sec=0,
    )

    assert stats.fund_flow_suspended == 1  # 000001 停牌, 未 fetch
    assert stats.fund_flow_empty == 1      # 000002 非停牌 (数据异常)
    assert stats.fund_flow_saved == 0
    assert stats.fund_flow_failed == 0
    assert fetched == ["000002"]  # 停牌股 000001 未被 fetch


def test_refresh_fund_flow_cache_suspension_check_failure_falls_back_to_empty(tmp_path, monkeypatch):
    """停牌列表 API 失败时, 所有空返回归 fund_flow_empty (保守, 不静默)."""
    from src.screening.offensive import cache_refresh as cr

    monkeypatch.setattr(
        cr,
        "_load_suspended_codes",
        lambda trade_date: set(),  # 模拟 API 失败返回空集
    )

    def fake_fetch(ticker: str, start_date: str, end_date: str) -> pd.DataFrame:
        return pd.DataFrame()

    stats = cr.refresh_fund_flow_cache(
        ["000001"],
        "20260708",
        fund_flow_cache_dir=tmp_path / "fund_flow_cache",
        fetch_fn=fake_fetch,
        rate_limit_sec=0,
    )

    assert stats.fund_flow_suspended == 0
    assert stats.fund_flow_empty == 1


def test_refresh_fund_flow_cache_skips_beijing_exchange_before_fetch(tmp_path, monkeypatch):
    """北交所 (920xxx/8xxxxx/4xxxxx) 股票在 fetch 前跳过 — tushare/akshare/ftshare 均不覆盖."""
    from src.screening.offensive import cache_refresh as cr

    monkeypatch.setattr(cr, "_load_suspended_codes", lambda trade_date: set())

    fetched: list[str] = []

    def fake_fetch(ticker: str, start_date: str, end_date: str) -> pd.DataFrame:
        fetched.append(ticker)
        return pd.DataFrame()

    stats = cr.refresh_fund_flow_cache(
        ["920088", "830879", "000001"],
        "20260708",
        fund_flow_cache_dir=tmp_path / "fund_flow_cache",
        fetch_fn=fake_fetch,
        rate_limit_sec=0,
    )

    # 920088 / 830879 是北交所, 跳过不 fetch; 000001 正常 fetch (但返回空)
    assert fetched == ["000001"]
    assert stats.fund_flow_bse_unsupported == 2  # 北交所单独计数
    assert stats.fund_flow_empty == 1            # 000001 是真异常
    assert "000001" in stats.fund_flow_empty_tickers
    assert stats.fund_flow_suspended == 0
    assert stats.fund_flow_failed == 0


def test_fund_flow_store_preserves_zero_padded_ticker(tmp_path):
    from src.screening.offensive.data.fund_flow_store import FundFlowStore

    store = FundFlowStore(cache_dir=tmp_path / "fund_flow_cache")
    store.save(
        "000001",
        pd.DataFrame(
            [
                {
                    "date": pd.Timestamp("2026-07-08"),
                    "close": 10.2,
                    "pct_change": 2.0,
                    "main_net_inflow": 1000000.0,
                    "main_net_pct": 3.5,
                }
            ]
        ),
    )

    records = store.get_range("000001", "20260708", "20260708")

    assert len(records) == 1
    assert records[0].ticker == "000001"


def test_extract_limit_up_tickers_filters_by_pct_and_date():
    """涨停股提取: 只取 pct>=9.5 且 trade_date 匹配的行."""
    from src.screening.offensive.cache_refresh import _extract_limit_up_tickers

    df = _daily_prices(
        [
            {"ts_code": "000001.SZ", "pct_chg": 2.0},   # 非涨停
            {"ts_code": "000002.SZ", "pct_chg": 9.5},   # 涨停 (边界)
            {"ts_code": "000003.SZ", "pct_chg": 10.0},  # 涨停
            {"ts_code": "000004.SZ", "pct_chg": 20.0, "trade_date": "20260706"},  # 涨停但日期不匹配
            {"ts_code": "000005.SZ", "pct_chg": -3.0},  # 跌
        ]
    )
    tickers = _extract_limit_up_tickers(df, "20260708")
    assert tickers == ["000002", "000003"]


def test_extract_limit_up_tickers_handles_empty_and_missing_columns():
    """容错: None / 空 df / 缺列 都返回空列表, 绝不抛异常."""
    from src.screening.offensive.cache_refresh import _extract_limit_up_tickers

    assert _extract_limit_up_tickers(None, "20260708") == []
    assert _extract_limit_up_tickers(pd.DataFrame(), "20260708") == []
    assert _extract_limit_up_tickers(pd.DataFrame({"ts_code": ["000001.SZ"]}), "20260708") == []
    assert _extract_limit_up_tickers(pd.DataFrame({"pct_chg": [10.0]}), "20260708") == []


def test_extract_limit_up_tickers_excludes_beijing_exchange():
    """北交所涨停股 (920xxx/8xxxxx/4xxxxx) 应被过滤: tushare moneyflow 不覆盖北交所.
    板块自适应阈值: 主板≥9.5%, 科创/创业≥19.5%, 北交所≥29.0%."""
    from src.screening.offensive.cache_refresh import _extract_limit_up_tickers

    df = _daily_prices(
        [
            {"ts_code": "688368.SH", "pct_chg": 20.0},   # 科创板真涨停 (≥19.5%) → 保留
            {"ts_code": "000003.SZ", "pct_chg": 10.0},   # 深市主板涨停 (≥9.5%) → 保留
            {"ts_code": "920088.BJ", "pct_chg": 15.0},   # 北交所非涨停 (<29%) → 过滤
            {"ts_code": "920090.BJ", "pct_chg": 12.0},   # 北交所非涨停 (<29%) → 过滤
            {"ts_code": "830879.BJ", "pct_chg": 20.0},   # 北交所非涨停 (<29%) → 过滤
            {"ts_code": "688999.SH", "pct_chg": 10.0},   # 科创板非涨停 (<19.5%) → 过滤
        ]
    )
    tickers = _extract_limit_up_tickers(df, "20260708")
    assert "688368" in tickers   # 科创板 20% 真涨停
    assert "000003" in tickers   # 主板 10% 真涨停
    assert "920088" not in tickers
    assert "920090" not in tickers
    assert "830879" not in tickers
    assert "688999" not in tickers  # 科创板 10% 不是涨停
    assert "830879" not in tickers


def test_refresh_daily_action_caches_injects_limit_up_tickers(tmp_path):
    """P0 修复核心: 涨停股 (不在候选池/缓存内) 应被注入 price_cache + fund_flow."""
    from src.screening.offensive.cache_refresh import refresh_daily_action_caches

    price_cache = tmp_path / "price_cache"
    price_cache.mkdir()
    (price_cache / "000001.csv").write_text(
        "date,close,open,high,low,pct_change,volume\n2026-07-06,9.8,9.7,9.9,9.6,1.1,1000\n",
        encoding="utf-8",
    )
    # candidate_pool 只含 000001 (已在缓存), 不含 000002/000003 (待注入的涨停股)
    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()
    (snapshot_dir / "candidate_pool_20260708.json").write_text(
        json.dumps([{"ticker": "000001"}]),
        encoding="utf-8",
    )

    fund_flow_tickers: list[str] = []

    def fund_flow_fetch(ticker: str, start_date: str, end_date: str) -> pd.DataFrame:
        fund_flow_tickers.append(ticker)
        return pd.DataFrame(
            [
                {
                    "date": pd.Timestamp("2026-07-08"),
                    "close": 10.2,
                    "pct_change": 2.0,
                    "main_net_inflow": 1000000.0,
                    "main_net_pct": 3.5,
                }
            ]
        )

    # batch df: 000001 非涨停, 000002/000003 涨停 (模拟不在候选池的涨停小盘股)
    daily_df = _daily_prices(
        [
            {"ts_code": "000001.SZ", "pct_chg": 2.0, "close": 10.2},
            {"ts_code": "000002.SZ", "pct_chg": 9.5, "close": 20.0},
            {"ts_code": "000003.SZ", "pct_chg": 10.0, "close": 30.0},
        ]
    )

    stats = refresh_daily_action_caches(
        "20260708",
        price_cache_dir=price_cache,
        fund_flow_cache_dir=tmp_path / "fund_flow_cache",
        snapshot_dir=snapshot_dir,
        daily_prices_df=daily_df,
        backfill_price_history_fn=lambda *_args: _history_rows(),
        fund_flow_fetch_fn=fund_flow_fetch,
        refresh_industry_index=False,
        fund_flow_rate_limit_sec=0,
    )

    # 涨停股被注入并创建缓存文件
    assert (price_cache / "000002.csv").exists()
    assert (price_cache / "000003.csv").exists()
    assert stats.limit_up_injected == 2
    # price_total 包含原候选 (000001) + 注入涨停 (000002, 000003)
    assert stats.price_total == 3
    assert stats.price_backfilled == 2  # 000002/000003 是新票需 backfill
    # fund_flow 也覆盖了注入的涨停股
    assert set(fund_flow_tickers) == {"000001", "000002", "000003"}


def test_refresh_daily_action_caches_limit_up_injection_disabled(tmp_path, monkeypatch):
    """env DAILY_ACTION_INCLUDE_LIMIT_UPS=false 时涨停股不注入."""
    from src.screening.offensive.cache_refresh import refresh_daily_action_caches

    monkeypatch.setenv("DAILY_ACTION_INCLUDE_LIMIT_UPS", "false")

    price_cache = tmp_path / "price_cache"
    price_cache.mkdir()
    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()
    (snapshot_dir / "candidate_pool_20260708.json").write_text(
        json.dumps([{"ticker": "000001"}]),
        encoding="utf-8",
    )

    daily_df = _daily_prices(
        [
            {"ts_code": "000001.SZ", "pct_chg": 2.0, "close": 10.2},
            {"ts_code": "000002.SZ", "pct_chg": 10.0, "close": 20.0},  # 涨停但应被忽略
        ]
    )

    stats = refresh_daily_action_caches(
        "20260708",
        price_cache_dir=price_cache,
        fund_flow_cache_dir=tmp_path / "fund_flow_cache",
        snapshot_dir=snapshot_dir,
        daily_prices_df=daily_df,
        backfill_price_history_fn=lambda *_args: _history_rows(),
        fund_flow_fetch_fn=lambda *_a: pd.DataFrame(),
        refresh_industry_index=False,
        fund_flow_rate_limit_sec=0,
    )

    assert stats.limit_up_injected == 0
    assert not (price_cache / "000002.csv").exists()


def test_refresh_daily_action_caches_limit_up_not_double_counted_when_in_cache(tmp_path):
    """涨停股若已在 price_cache, limit_up_injected 不重复计数."""
    from src.screening.offensive.cache_refresh import refresh_daily_action_caches

    price_cache = tmp_path / "price_cache"
    price_cache.mkdir()
    # 000001 既是候选又在缓存; 000002 涨停但已在缓存
    (price_cache / "000001.csv").write_text(
        "date,close,open,high,low,pct_change,volume\n2026-07-06,9.8,9.7,9.9,9.6,1.1,1000\n",
        encoding="utf-8",
    )
    (price_cache / "000002.csv").write_text(
        "date,close,open,high,low,pct_change,volume\n2026-07-06,19.8,19.7,19.9,19.6,1.1,1000\n",
        encoding="utf-8",
    )
    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()

    daily_df = _daily_prices(
        [
            {"ts_code": "000001.SZ", "pct_chg": 2.0},
            {"ts_code": "000002.SZ", "pct_chg": 10.0},  # 涨停但已在缓存
        ]
    )

    stats = refresh_daily_action_caches(
        "20260708",
        price_cache_dir=price_cache,
        fund_flow_cache_dir=tmp_path / "fund_flow_cache",
        snapshot_dir=snapshot_dir,
        daily_prices_df=daily_df,
        backfill_price_history_fn=lambda *_args: _history_rows(),
        fund_flow_fetch_fn=lambda *_a: pd.DataFrame(),
        refresh_industry_index=False,
        fund_flow_rate_limit_sec=0,
    )

    # 000002 涨停但已在 existing cache, 不算新注入
    assert stats.limit_up_injected == 0
    assert stats.price_total == 2


# ── 幂等跳写 + 向量化日期 (2026-07-17 性能优化) ────────────────────────────
# 背景: 每次 --auto 对 ~800 票 x 1583 行全历史做读取/逐值日期解析/全量校验/
# 深拷贝/原子重写, 实测缓存刷新阶段 ~408s, 而真正的新数据只有每票 1 行。
# 优化: 当日行已存在且值一致 → 跳过校验+重写 (证据照采); 日期处理向量化。
# fail-closed 不变: 任何真实变化仍走 validate_price_artifact 全量校验 + 写盘。


def test_vectorized_date_helpers_match_scalar_versions():
    """_fund_flow_dates/_price_dates (向量化) 与逐值版在所有合法格式上等价。"""
    from src.screening.offensive.cache_refresh import (
        _fund_flow_date,
        _fund_flow_dates,
        _price_date,
        _price_dates,
    )

    values = pd.Series(
        ["20260716", "2026-07-16", "2026-07-16 00:00:00", " 20260715 ", "2020-01-02"]
    )
    assert list(_fund_flow_dates(values)) == [_fund_flow_date(v) for v in values]
    assert list(_price_dates(values)) == [_price_date(v) for v in values]


def test_price_frame_unchanged_guards():
    """行数不同 / 缺 date 列 / 值不同 → False (回落全量校验+写盘, fail-closed 方向)。"""
    from src.screening.offensive.cache_refresh import _price_frame_unchanged

    base = pd.DataFrame(
        {
            "date": ["2026-07-10", "2026-07-13"],
            "close": [10.0, 10.5],
            "open": [9.9, 10.0],
            "high": [10.2, 10.6],
            "low": [9.8, 9.9],
            "pct_change": [1.0, 1.0],
            "volume": [1000.0, 1100.0],
        }
    )
    assert _price_frame_unchanged(base, base.copy()) is True
    assert _price_frame_unchanged(base, base.iloc[:-1]) is False  # 行数不同
    changed = base.copy()
    changed.loc[1, "close"] = 11.0
    assert _price_frame_unchanged(base, changed) is False  # 值不同
    assert _price_frame_unchanged(base, base.drop(columns=["date"])) is False
    assert _price_frame_unchanged(base, pd.DataFrame()) is False


def test_write_price_cache_row_skips_unchanged_rewrite(tmp_path, monkeypatch):
    """幂等: 当日行已存在且值一致 → 跳过写盘 (wrote=False), 证据照采且内容一致。"""
    from src.screening.offensive import cache_refresh as cr

    path = tmp_path / "000001.csv"
    row = {
        "date": "2026-07-13",
        "close": 10.5,
        "open": 10.0,
        "high": 10.6,
        "low": 9.9,
        "pct_change": 1.0,
        "volume": 1000.0,
    }
    writes: list[Path] = []
    real_write = cr.atomic_write_csv
    monkeypatch.setattr(
        cr, "atomic_write_csv", lambda p, f: (writes.append(p), real_write(p, f))
    )

    frame1, wrote1 = cr._write_price_cache_row(path, row)
    assert wrote1 is True
    assert len(writes) == 1

    sunk: list[pd.DataFrame] = []
    frame2, wrote2 = cr._write_price_cache_row(path, row, artifact_sink=sunk.append)
    assert wrote2 is False
    assert len(writes) == 1  # 没有第二次写盘
    assert len(sunk) == 1  # 证据照采
    assert sunk[0].equals(frame1)  # 证据内容与首次写入一致


def test_write_price_cache_row_rewrites_when_value_changed(tmp_path, monkeypatch):
    """值变化 → 正常校验+写盘 (wrote=True)。"""
    from src.screening.offensive import cache_refresh as cr

    path = tmp_path / "000001.csv"
    row = {
        "date": "2026-07-13",
        "close": 10.5,
        "open": 10.0,
        "high": 10.6,
        "low": 9.9,
        "pct_change": 1.0,
        "volume": 1000.0,
    }
    writes: list[Path] = []
    real_write = cr.atomic_write_csv
    monkeypatch.setattr(
        cr, "atomic_write_csv", lambda p, f: (writes.append(p), real_write(p, f))
    )

    cr._write_price_cache_row(path, row)
    changed = dict(row, close=11.0)
    frame2, wrote2 = cr._write_price_cache_row(path, changed)
    assert wrote2 is True
    assert len(writes) == 2
    # 磁盘上是新值
    on_disk = pd.read_csv(path)
    assert on_disk.iloc[-1]["close"] == 11.0


def test_price_refresh_second_run_skips_unchanged_writes(tmp_path):
    """端到端: 第二轮相同 batch → 全部幂等跳过, 证据指纹与首轮一致。

    这是 --auto 一天跑多次时的主路径: 缓存已最新时不应再空转写盘,
    但 readiness 证据 (fingerprint) 必须照常产出且逐轮稳定。
    """
    from datetime import date

    from src.screening.offensive import cache_refresh as cr
    from src.screening.offensive.cache_readiness import SuspensionEvidence

    price_cache = tmp_path / "price"
    price_cache.mkdir()
    (price_cache / "000001.csv").write_text(
        "date,close,open,high,low,pct_change,volume\n"
        "2026-07-10,10,9.9,10.2,9.8,1,1000\n",
        encoding="utf-8",
    )

    def run():
        return cr.refresh_daily_action_caches(
            "20260713",
            price_cache_dir=price_cache,
            fund_flow_cache_dir=tmp_path / "flow",
            snapshot_dir=tmp_path / "snapshots",
            target_tickers=["000001"],
            daily_prices_df=_daily_prices(
                [{"ts_code": "000001.SZ", "trade_date": "20260713", "close": 10.5}]
            ),
            suspension_loader=lambda _trade_date: SuspensionEvidence.available(
                date(2026, 7, 13), set()
            ),
            refresh_industry_index=False,
            refresh_fund_flow=False,
        )

    first = run()
    assert first._refresh_counters["price_updated"] == 1
    assert first._refresh_counters["price_skipped_current"] == 0

    second = run()
    assert second._refresh_counters["price_updated"] == 0
    assert second._refresh_counters["price_skipped_current"] == 1
    # 幂等跳过路径下证据指纹仍产出且逐轮稳定
    assert (
        second.outcomes["000001"].evidence_fingerprints["price"]
        == first.outcomes["000001"].evidence_fingerprints["price"]
    )


def _batch_flow_frame() -> pd.DataFrame:
    """tushare 批量 moneyflow 拆出的单票当日帧 (close/main_net_pct 为 NaN)。"""
    return pd.DataFrame(
        [
            {
                "date": pd.Timestamp("2026-07-13"),
                "close": float("nan"),
                "pct_change": 0.0,
                "main_net_inflow": 1000000.0,
                "main_net_pct": float("nan"),
                "big_net_inflow": 500000.0,
                "super_big_net_inflow": 500000.0,
                "medium_net_inflow": -200000.0,
                "small_net_inflow": -300000.0,
            }
        ]
    )


def test_fund_flow_prefetched_skips_network_fetch(tmp_path, monkeypatch):
    """批量预取命中的票: 不调 fetch_fn、不 rate-limit 等待; 未命中票回落逐票。"""
    from src.screening.offensive import cache_refresh as cr
    from src.screening.offensive.cache_refresh import refresh_fund_flow_cache

    fetched: list[str] = []
    sleeps: list[float] = []
    monkeypatch.setattr(cr.time, "sleep", lambda sec: sleeps.append(sec))

    def fake_fetch(ticker: str, start_date: str, end_date: str) -> pd.DataFrame:
        fetched.append(ticker)
        return pd.DataFrame(
            [
                {
                    "date": pd.Timestamp("2026-07-13"),
                    "close": 10.2,
                    "pct_change": 2.0,
                    "main_net_inflow": 2000000.0,
                    "main_net_pct": 3.5,
                }
            ]
        )

    stats = refresh_fund_flow_cache(
        ["000001", "000002", "000003"],
        "20260713",
        fund_flow_cache_dir=tmp_path / "flow",
        fetch_fn=fake_fetch,
        rate_limit_sec=5.0,  # 若 prefetched 票错误地走网络路径, sleep 会被记录
        prefetched_frames={"000001": _batch_flow_frame()},
    )

    # 000001 走预取 (无网络), 000002/000003 回落逐票; sleep 只发生在非末票的网络拉取后
    assert fetched == ["000002", "000003"]
    assert len(sleeps) == 1  # 仅 000002 (非末票) 触发 rate-limit
    assert stats.fund_flow_saved == 3
    assert stats.fund_flow_prefetched == 1
    saved = pd.read_csv(tmp_path / "flow" / "000001.csv", dtype={"date": str, "ticker": str})
    assert saved.iloc[0]["main_net_inflow"] == 1000000.0


def test_prefetch_fund_flow_batch_branches(tmp_path, monkeypatch):
    """helper 各分支: env 关闭 / 注入逐票 / 拉取失败 / 空结果 / 缺价格行 → None 或回落。"""
    from src.screening.offensive import cache_refresh as cr

    prices = _daily_prices([{"ts_code": "000001.SZ", "trade_date": "20260713"}])
    calls: list[str] = []

    def batch_fn(trade_date: str):
        calls.append(trade_date)
        return {"000001": _batch_flow_frame()}

    base_kwargs = dict(
        resolved_daily_prices=prices,
        daily_batch_available=True,
        per_ticker_fetch_injected=False,
        batch_fetch_fn=batch_fn,
    )

    # 命中: close/pct_change 从 daily batch 填入
    result = cr._prefetch_fund_flow_batch(["000001"], "20260713", **base_kwargs)
    assert result is not None and "000001" in result
    filled = result["000001"].iloc[0]
    assert filled["close"] == 10.2
    assert filled["pct_change"] == 2.0
    assert pd.isna(filled["main_net_pct"])  # 留 NaN, store 落盘补 0.0

    # 批量未覆盖的票 → 不在结果中 (回落逐票)
    result = cr._prefetch_fund_flow_batch(["000002"], "20260713", **base_kwargs)
    assert result is None

    # daily batch 缺该票价格行 → 不预取
    result = cr._prefetch_fund_flow_batch(
        ["000001"],
        "20260713",
        resolved_daily_prices=_daily_prices(
            [{"ts_code": "000003.SZ", "trade_date": "20260713"}]
        ),
        daily_batch_available=True,
        per_ticker_fetch_injected=False,
        batch_fetch_fn=batch_fn,
    )
    assert result is None

    # 注入逐票 fetch → 直接 None (不调批量)
    calls.clear()
    assert (
        cr._prefetch_fund_flow_batch(["000001"], "20260713", **{**base_kwargs, "per_ticker_fetch_injected": True})
        is None
    )
    assert calls == []

    # env 关闭 → None (不调批量)
    monkeypatch.setenv("DAILY_ACTION_FUND_FLOW_BATCH", "0")
    assert cr._prefetch_fund_flow_batch(["000001"], "20260713", **base_kwargs) is None
    assert calls == []
    monkeypatch.delenv("DAILY_ACTION_FUND_FLOW_BATCH")

    # 批量抛异常 → None (回落逐票)
    def raising_fn(_trade_date: str):
        raise RuntimeError("api down")

    assert (
        cr._prefetch_fund_flow_batch(["000001"], "20260713", **{**base_kwargs, "batch_fetch_fn": raising_fn})
        is None
    )

    # 批量返回空 → None
    assert (
        cr._prefetch_fund_flow_batch(["000001"], "20260713", **{**base_kwargs, "batch_fetch_fn": lambda _d: {}})
        is None
    )


def test_refresh_daily_action_caches_fund_flow_batch_end_to_end(tmp_path):
    """端到端: 批量预取命中 → 落盘 + 状态 CURRENT + 证据指纹产出, 无逐票网络路径。"""
    from datetime import date

    from src.screening.offensive import cache_refresh as cr
    from src.screening.offensive.cache_readiness import SuspensionEvidence

    price_cache = tmp_path / "price"
    price_cache.mkdir()
    (price_cache / "000001.csv").write_text(
        "date,close,open,high,low,pct_change,volume\n"
        "2026-07-10,10,9.9,10.2,9.8,1,1000\n",
        encoding="utf-8",
    )
    batch_calls: list[str] = []

    def batch_fn(trade_date: str):
        batch_calls.append(trade_date)
        return {"000001": _batch_flow_frame()}

    result = cr.refresh_daily_action_caches(
        "20260713",
        price_cache_dir=price_cache,
        fund_flow_cache_dir=tmp_path / "flow",
        snapshot_dir=tmp_path / "snapshots",
        target_tickers=["000001"],
        daily_prices_df=_daily_prices(
            [{"ts_code": "000001.SZ", "trade_date": "20260713", "close": 10.5}]
        ),
        suspension_loader=lambda _trade_date: SuspensionEvidence.available(
            date(2026, 7, 13), set()
        ),
        fund_flow_batch_fetch_fn=batch_fn,
        refresh_industry_index=False,
        # 注意: 不传 fund_flow_fetch_fn — 若批量失效会走真实网络, 测试环境即失败
    )

    assert batch_calls == ["20260713"]
    outcome = result.outcomes["000001"]
    assert outcome.fund_flow_status.name == "CURRENT"
    assert "fund_flow" in outcome.evidence_fingerprints
    assert result._refresh_counters["fund_flow_prefetched"] == 1
    assert result._refresh_counters["fund_flow_saved"] == 1

    saved = pd.read_csv(tmp_path / "flow" / "000001.csv", dtype={"date": str, "ticker": str})
    row = saved.iloc[0]
    assert row["date"] == "20260713"
    assert row["main_net_inflow"] == 1000000.0
    assert row["close"] == 10.5  # 来自 daily batch
    assert row["main_net_pct"] == 0.0  # NaN 按 store 惯例补 0.0 (同逐票 tushare 路径)

    # 第二轮: 缓存已新鲜 → 不再调批量, 状态仍 CURRENT
    batch_calls.clear()
    second = cr.refresh_daily_action_caches(
        "20260713",
        price_cache_dir=price_cache,
        fund_flow_cache_dir=tmp_path / "flow",
        snapshot_dir=tmp_path / "snapshots",
        target_tickers=["000001"],
        daily_prices_df=_daily_prices(
            [{"ts_code": "000001.SZ", "trade_date": "20260713", "close": 10.5}]
        ),
        suspension_loader=lambda _trade_date: SuspensionEvidence.available(
            date(2026, 7, 13), set()
        ),
        fund_flow_batch_fetch_fn=batch_fn,
        refresh_industry_index=False,
    )
    assert batch_calls == []
    assert second.outcomes["000001"].fund_flow_status.name == "CURRENT"
    assert (
        second.outcomes["000001"].evidence_fingerprints["fund_flow"]
        == outcome.evidence_fingerprints["fund_flow"]
    )


def test_fund_flow_rate_limit_survives_fetch_exception(tmp_path, monkeypatch):
    """对抗性审查回归: fetch_fn 抛异常也算发起网络请求, rate-limit 退避必须生效。

    修复前 fetched_via_network 在 fetch_fn 返回后才置位 — 异常路径丢失退避,
    持续故障时重试循环会全速 hammer API。
    """
    from src.screening.offensive import cache_refresh as cr
    from src.screening.offensive.cache_refresh import refresh_fund_flow_cache

    sleeps: list[float] = []
    monkeypatch.setattr(cr.time, "sleep", lambda sec: sleeps.append(sec))

    def raising_fetch(ticker: str, start_date: str, end_date: str) -> pd.DataFrame:
        raise ConnectionError("api down")

    stats = refresh_fund_flow_cache(
        ["000001", "000002", "000003"],
        "20260713",
        fund_flow_cache_dir=tmp_path / "flow",
        fetch_fn=raising_fetch,
        rate_limit_sec=5.0,
    )

    assert stats.fund_flow_failed == 3
    # 非末票的两次异常拉取后都必须退避 (末票不 sleep 是既有语义)
    assert sleeps == [5.0, 5.0]


def test_write_price_cache_row_skip_path_evidence_is_detached(tmp_path):
    """对抗性审查回归: 幂等跳写路径的证据必须是独立副本, 与写盘路径防御对称。"""
    from src.screening.offensive import cache_refresh as cr

    path = tmp_path / "000001.csv"
    row = {
        "date": "2026-07-13",
        "close": 10.5,
        "open": 10.0,
        "high": 10.6,
        "low": 9.9,
        "pct_change": 1.0,
        "volume": 1000.0,
    }
    # 首轮: 写盘, 建立缓存
    cr._write_price_cache_row(path, row)
    # 次轮: 相同行 → 幂等跳写
    captured: list[pd.DataFrame] = []
    combined, wrote = cr._write_price_cache_row(
        path, dict(row), artifact_sink=lambda frame: captured.append(frame)
    )
    assert wrote is False
    assert len(captured) == 1
    evidence = captured[0]
    assert evidence is not combined  # 独立副本
    # 调用方后续原地修改 combined 不得污染已采集证据
    original_close = float(evidence.iloc[-1]["close"])
    combined.loc[combined.index[-1], "close"] = -999.0
    assert float(evidence.iloc[-1]["close"]) == original_close
