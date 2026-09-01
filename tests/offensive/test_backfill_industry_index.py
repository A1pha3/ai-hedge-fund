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


def _raw_sw_daily_frame() -> pd.DataFrame:
    # 2026-09-01 真实回包形状 (801010.SI): 官方 pct_change 只发布 2 位小数
    return pd.DataFrame(
        {
            "ts_code": ["801010.SI", "801010.SI"],
            "trade_date": ["20260901", "20260831"],
            "name": ["农林牧渔", "农林牧渔"],
            "open": [2590.50, 2605.00],
            "low": [2590.50, 2593.00],
            "high": [2675.75, 2610.00],
            "close": [2659.05, 2594.77],
            "change": [64.28, -13.10],
            "pct_change": [2.48, -0.50],
            "vol": [464904.0, 400000.0],
            "amount": [3773944.0, 3000000.0],
            "pe": [85.1, 84.0],
            "pb": [2.53, 2.5],
            "float_mv": [60632784.0, 60000000.0],
            "total_mv": [129314660.0, 129000000.0],
        }
    )


def test_normalize_sw_daily_frame_matches_legacy_csv_contract():
    from scripts.backfill_industry_index import _LEGACY_CSV_COLUMNS, _normalize_sw_daily_frame

    out = _normalize_sw_daily_frame(_raw_sw_daily_frame())

    assert list(out.columns) == list(_LEGACY_CSV_COLUMNS)
    row = out[out["trade_date"] == "20260901"].iloc[0]
    # pre_close = close - change (与前一交易日 close 精确吻合)
    assert row["pre_close"] == 2594.77
    # pct_chg 重算 4 位小数, 不采用官方 2 位的 pct_change
    assert row["pct_chg"] == round(64.28 / 2594.77 * 100, 4)
    assert row["pct_chg"] != 2.48


def test_normalize_sw_daily_frame_drops_malformed_rows():
    from scripts.backfill_industry_index import _normalize_sw_daily_frame

    assert _normalize_sw_daily_frame(None).empty
    assert _normalize_sw_daily_frame(pd.DataFrame()).empty

    raw = _raw_sw_daily_frame()
    raw.loc[1, "change"] = float("nan")  # 缺 change 的行整行丢弃
    out = _normalize_sw_daily_frame(raw)
    assert list(out["trade_date"]) == ["20260901"]


def test_fetch_industry_daily_uses_sw_daily_source(monkeypatch):
    from scripts import backfill_industry_index as mod

    class _FakePro:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict]] = []

        def sw_daily(self, **kwargs):
            self.calls.append(("sw_daily", kwargs))
            return _raw_sw_daily_frame()

        def index_daily(self, **kwargs):  # pragma: no cover - 断言不该到达
            raise AssertionError("index_daily 对 SW 指数已停服, 不应再被调用")

    fake = _FakePro()
    monkeypatch.setattr("src.tools.tushare_api._get_pro", lambda: fake)

    df = mod._fetch_industry_daily("801010.SI", "20260901")

    assert [name for name, _ in fake.calls] == ["sw_daily"]
    assert fake.calls[0][1]["ts_code"] == "801010.SI"
    assert "pct_chg" in df.columns and "pre_close" in df.columns
