from __future__ import annotations

import pandas as pd


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
