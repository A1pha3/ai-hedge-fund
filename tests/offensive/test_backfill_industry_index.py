from __future__ import annotations

import pandas as pd


def _industry_cache(rows: int, latest_trade_date: str) -> pd.DataFrame:
    dates = pd.date_range("2020-01-01", periods=rows - 1).strftime("%Y%m%d").tolist()
    dates.append(latest_trade_date)
    return pd.DataFrame(
        {
            "ts_code": ["801010.SI"] * rows,
            "trade_date": dates,
            "close": [1000.0] * rows,
            "pct_chg": [1.0] * rows,
        }
    )


def test_backfill_refetches_existing_cache_when_latest_is_before_end_date(tmp_path, monkeypatch):
    from scripts import backfill_industry_index as mod

    cache_dir = tmp_path / "industry_index_cache"
    cache_dir.mkdir()
    _industry_cache(1501, "20260707").to_csv(cache_dir / "801010.SI.csv", index=False)

    calls: list[tuple[str, str]] = []

    def fetch_daily(index_code: str, end_date: str) -> pd.DataFrame:
        calls.append((index_code, end_date))
        return _industry_cache(1502, "20260708")

    monkeypatch.setattr(mod, "_fetch_industry_codes", lambda: [("801010.SI", "农林牧渔")])
    monkeypatch.setattr(mod, "_fetch_industry_daily", fetch_daily)

    result = mod.backfill(end_date="20260708", cache_dir=cache_dir)

    refreshed = pd.read_csv(cache_dir / "801010.SI.csv", dtype={"trade_date": str})
    assert calls == [("801010.SI", "20260708")]
    assert refreshed["trade_date"].max() == "20260708"
    assert result == {"农林牧渔": 1502}


def test_backfill_skips_existing_cache_when_latest_covers_end_date(tmp_path, monkeypatch):
    from scripts import backfill_industry_index as mod

    cache_dir = tmp_path / "industry_index_cache"
    cache_dir.mkdir()
    _industry_cache(1501, "20260708").to_csv(cache_dir / "801010.SI.csv", index=False)

    def fetch_daily(_index_code: str, _end_date: str) -> pd.DataFrame:
        raise AssertionError("fresh industry cache should not be refetched")

    monkeypatch.setattr(mod, "_fetch_industry_codes", lambda: [("801010.SI", "农林牧渔")])
    monkeypatch.setattr(mod, "_fetch_industry_daily", fetch_daily)

    result = mod.backfill(end_date="20260708", cache_dir=cache_dir)

    assert result == {"农林牧渔": 1501}
