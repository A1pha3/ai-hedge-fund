import sys
from types import SimpleNamespace

import pandas as pd

from src.data.providers.akshare_provider import AKShareProvider
from src.data.providers.tushare_provider import TushareProvider
import src.tools.ashare_data_sources as ashare_data_sources
from src.tools.ashare_board_utils import build_beijing_exchange_mask, build_beijing_exchange_mask_from_series, detect_ashare_exchange, to_baostock_code, to_tushare_code
from src.tools.akshare_api import AShareTicker
import src.tools.tushare_api as tushare_api
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
        return pd.DataFrame(
            [
                {"trade_date": "20260401", "open": 10.0, "high": 10.5, "low": 9.8, "close": 10.2, "vol": 12345}
            ]
        )

    monkeypatch.setattr(tushare_api, "_cached_tushare_dataframe_call", _fake_cached_tushare_dataframe_call)

    prices = ashare_data_sources.TushareDataSource.get_prices("920001", "2026-04-01", "2026-04-02")

    assert captured["ts_code"] == "920001.BJ"
    assert prices[0].time == "2026-04-01"


def test_baostock_data_source_routes_beijing_92_to_bj(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class _FakeResult:
        error_code = "0"

        def __init__(self) -> None:
            self._rows = iter([
                ["2026-04-01", "10.0", "10.5", "9.8", "10.2", "12345"],
            ])
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
