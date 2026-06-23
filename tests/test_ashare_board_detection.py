import sys
from types import SimpleNamespace

import pandas as pd

import src.tools.ashare_data_sources as ashare_data_sources
import src.tools.tushare_api as tushare_api
from src.data.providers.akshare_provider import AKShareProvider
from src.data.providers.tushare_provider import TushareProvider
from src.tools.akshare_api import AShareTicker
from src.tools.ashare_board_utils import (
    build_beijing_exchange_mask,
    build_beijing_exchange_mask_from_series,
    detect_ashare_exchange,
    to_baostock_code,
    to_tushare_code,
)
from src.tools.tushare_api import _to_ts_code


def test_ashare_ticker_keeps_star_market_and_maps_beijing_92_prefix() -> None:
    star_market = AShareTicker.from_symbol("688001")
    beijing_exchange = AShareTicker.from_symbol("920001")

    assert star_market.exchange == "sh"
    assert star_market.full_code == "sh688001"
    assert beijing_exchange.exchange == "bj"
    assert beijing_exchange.full_code == "bj920001"


def test_tushare_code_conversion_maps_beijing_92_prefix() -> None:
    assert _to_ts_code("688001") == "688001.SH"
    assert _to_ts_code("920001") == "920001.BJ"
    assert _to_ts_code("bj920001") == "920001.BJ"


def test_shared_board_helper_detects_market_and_masks() -> None:
    stock_df = pd.DataFrame(
        [
            {"ts_code": "688001.SH", "symbol": "688001", "market": "科创板"},
            {"ts_code": "920001.BJ", "symbol": "920001", "market": "北交所"},
            {"ts_code": "000001.SZ", "symbol": "000001", "market": "主板"},
        ]
    )

    assert detect_ashare_exchange("688001") == "sh"
    assert detect_ashare_exchange("920001") == "bj"
    assert to_tushare_code("920001") == "920001.BJ"
    assert to_baostock_code("920001") == "bj.920001"
    assert build_beijing_exchange_mask(stock_df).tolist() == [False, True, False]
    assert build_beijing_exchange_mask_from_series(stock_df["ts_code"]).tolist() == [False, True, False]


def test_tushare_provider_maps_beijing_92_prefix() -> None:
    provider = object.__new__(TushareProvider)

    assert provider._to_ts_code("920001") == "920001.BJ"


def test_akshare_provider_maps_beijing_92_prefix() -> None:
    provider = object.__new__(AKShareProvider)

    assert provider._get_exchange("920001") == "bj"
    assert provider._to_ashare_symbol("bj920001") == "920001"


def test_tushare_data_source_routes_beijing_92_to_bj(monkeypatch) -> None:
    captured: dict[str, object] = {}

    monkeypatch.setattr(ashare_data_sources.TushareDataSource, "_init_tushare", classmethod(lambda cls: True))
    monkeypatch.setattr(ashare_data_sources.TushareDataSource, "_pro", object())

    def _fake_cached_tushare_dataframe_call(_pro, _api_name, **kwargs):
        captured.update(kwargs)
        return pd.DataFrame([{"trade_date": "20260401", "open": 10.0, "high": 10.5, "low": 9.8, "close": 10.2, "vol": 12345}])

    monkeypatch.setattr(tushare_api, "_cached_tushare_dataframe_call", _fake_cached_tushare_dataframe_call)

    prices = ashare_data_sources.TushareDataSource.get_prices("920001", "2026-04-01", "2026-04-02")

    assert captured["ts_code"] == "920001.BJ"
    assert prices[0].time == "2026-04-01"


def test_baostock_data_source_routes_beijing_92_to_bj(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class _FakeResult:
        error_code = "0"

        def __init__(self) -> None:
            self._rows = iter(
                [
                    ["2026-04-01", "10.0", "10.5", "9.8", "10.2", "12345"],
                ]
            )
            self._current: list[str] | None = None

        def next(self) -> bool:
            self._current = next(self._rows, None)
            return self._current is not None

        def get_row_data(self) -> list[str]:
            return self._current or []

    def _fake_query_history_k_data_plus(code, *_args, **_kwargs):
        captured["code"] = code
        return _FakeResult()

    fake_bs = SimpleNamespace(
        login=lambda: SimpleNamespace(error_code="0", error_msg=""),
        logout=lambda: None,
        query_history_k_data_plus=_fake_query_history_k_data_plus,
    )

    monkeypatch.setattr(ashare_data_sources.BaoStockDataSource, "_init_baostock", classmethod(lambda cls: True))
    monkeypatch.setitem(sys.modules, "baostock", fake_bs)

    prices = ashare_data_sources.BaoStockDataSource.get_prices("920001", "2026-04-01", "2026-04-02")

    assert captured["code"] == "bj.920001"
    assert prices[0].close == 10.2


def test_daily_pipeline_price_lookup_routes_beijing_92_to_bj() -> None:
    from src.execution.daily_pipeline import _to_ts_code_for_price_lookup

    assert _to_ts_code_for_price_lookup("920001") == "920001.BJ"


def test_tushare_data_source_skips_nan_volume_row(monkeypatch) -> None:
    """R133 (R132/R83 same-class drain residue): TushareDataSource.get_prices is
    a THIRD sibling df→Price converter (besides AKShareProvider R83 and
    build_prices_from_dataframe R132) that lacks the pd.notna NaN-row skip guard.
    ``int(row["vol"])`` on a NaN volume (halted/illiquid day in tushare daily)
    raises ValueError, caught by the outer ``except Exception`` and re-raised as
    DataSourceError — dropping the whole ticker's price series on one bad row.
    A single NaN-volume row must be skipped, not fail the whole fetch.
    """
    monkeypatch.setattr(ashare_data_sources.TushareDataSource, "_init_tushare", classmethod(lambda cls: True))
    monkeypatch.setattr(ashare_data_sources.TushareDataSource, "_pro", object())

    def _fake_cached(_pro, _api_name, **kwargs):
        return pd.DataFrame(
            [
                {"trade_date": "20260401", "open": 10.0, "high": 10.5, "low": 9.8, "close": 10.2, "vol": 12345},
                {"trade_date": "20260402", "open": 10.2, "high": 10.6, "low": 10.0, "close": 10.4, "vol": float("nan")},
                {"trade_date": "20260403", "open": 10.4, "high": 10.8, "low": 10.3, "close": 10.7, "vol": 13000},
            ]
        )

    monkeypatch.setattr(tushare_api, "_cached_tushare_dataframe_call", _fake_cached)

    prices = ashare_data_sources.TushareDataSource.get_prices("920001", "2026-04-01", "2026-04-03")

    # NaN-volume row skipped (not crash/fail); valid rows preserved (reversed to chronological)
    times = [p.time for p in prices]
    assert "2026-04-02" not in times
    assert len(prices) == 2
    assert prices[0].volume in (12345, 13000)


def test_baostock_data_source_skips_row_with_empty_volume(monkeypatch) -> None:
    """R134 (R83/R132/R133 same-class drain residue): ``BaoStockDataSource.get_prices``
    is a SIXTH sibling df→Price converter. Its existing guard only skips when the
    OPEN cell is empty (``if row[1] == "": continue``), but BaoStock can return a
    non-empty open with an empty volume/other cell on a halted day.
    ``int(float(row[5]))`` on ``""`` raises ValueError, dropping the whole
    ticker's price series. The guard must cover ALL OHLC/volume cells.
    """
    import baostock as bs

    monkeypatch.setattr(ashare_data_sources.BaoStockDataSource, "_init_baostock", classmethod(lambda cls: True))

    class _Rs:
        error_code = "0"

        def __init__(self):
            self._rows = [
                ["2026-04-01", "10.0", "10.5", "9.8", "10.2", "1000"],
                ["2026-04-02", "10.2", "10.6", "10.0", "10.4", ""],  # halted day: open present, volume empty
                ["2026-04-03", "10.4", "10.8", "10.3", "10.7", "1200"],
            ]
            self._i = -1

        def next(self):
            self._i += 1
            return self._i < len(self._rows)

        def get_row_data(self):
            return self._rows[self._i]

    monkeypatch.setattr(bs, "login", lambda: SimpleNamespace(error_code="0", error_msg=""))
    monkeypatch.setattr(bs, "logout", lambda: None)
    monkeypatch.setattr(bs, "query_history_k_data_plus", lambda *a, **k: _Rs())

    prices = ashare_data_sources.BaoStockDataSource.get_prices("000001", "2026-04-01", "2026-04-03")

    times = [p.time for p in prices]
    assert "2026-04-02" not in times
    assert len(prices) == 2
    assert prices[0].time == "2026-04-01"


# ---------------------------------------------------------------------------
# R163: to_tushare_code / split_ashare_exchange_prefix must handle .SH/.SZ/.BJ
# SUFFIX format (tushare standard ts_code) — not just bare codes + sh/sz prefix.
# Before fix: to_tushare_code("600000.SH") → "600000.sh.SH" (double-suffix).
# ---------------------------------------------------------------------------


def test_to_tushare_code_suffix_format_idempotent() -> None:
    """R163: .SH/.SZ/.BJ suffix input must round-trip, not double-suffix."""
    from src.tools.ashare_board_utils import to_tushare_code

    assert to_tushare_code("600000.SH") == "600000.SH"
    assert to_tushare_code("000001.SZ") == "000001.SZ"
    assert to_tushare_code("920001.BJ") == "920001.BJ"
    assert to_tushare_code("688766.SH") == "688766.SH"


def test_split_ashare_exchange_prefix_suffix_format() -> None:
    """R163: split must recognize .SH/.SZ/.BJ suffix and extract clean symbol."""
    from src.tools.ashare_board_utils import split_ashare_exchange_prefix

    assert split_ashare_exchange_prefix("600000.SH") == ("sh", "600000")
    assert split_ashare_exchange_prefix("000001.SZ") == ("sz", "000001")
    assert split_ashare_exchange_prefix("920001.BJ") == ("bj", "920001")
    # lowercase suffix too
    assert split_ashare_exchange_prefix("688766.sh") == ("sh", "688766")


def test_split_ashare_exchange_prefix_prefix_format_unchanged() -> None:
    """R163 regression: sh/sz PREFIX format still works."""
    from src.tools.ashare_board_utils import split_ashare_exchange_prefix

    assert split_ashare_exchange_prefix("sh600000") == ("sh", "600000")
    assert split_ashare_exchange_prefix("sz000001") == ("sz", "000001")


def test_split_ashare_exchange_prefix_bare_unchanged() -> None:
    """R163 regression: bare code still returns (None, code)."""
    from src.tools.ashare_board_utils import split_ashare_exchange_prefix

    assert split_ashare_exchange_prefix("600000") == (None, "600000")
