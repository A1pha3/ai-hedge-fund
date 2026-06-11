"""BETA-007: 停牌检测 — load_current_prices 跳过 volume=0 的标的。

覆盖场景:
- 正常成交 (volume>0) → 价格包含
- 停牌 (volume=0) → 价格排除
- 数据源缺 volume 列 → 兼容 (按有价格处理)
- 全部停牌 → 返回 None (回测引擎会跳过该日)
"""
from __future__ import annotations

import pandas as pd
import pytest

from src.backtesting.engine_market_data import MarketDataLoader
from src.backtesting.portfolio import Portfolio


def _make_loader(tickers: list[str]) -> MarketDataLoader:
    """构造 MarketDataLoader (exit_reentry_cooldowns 为空 dict)。"""
    portfolio = Portfolio(tickers=tickers, initial_cash=100_000.0, margin_requirement=0.5)
    return MarketDataLoader(
        tickers=tickers,
        start_date="2024-01-01",
        end_date="2024-01-31",
        portfolio=portfolio,
        exit_reentry_cooldowns={},
    )


def _make_price_frame(rows: list[dict]) -> pd.DataFrame:
    """构造单标的 DataFrame, 模拟 tushare 数据格式。"""
    if not rows:
        return pd.DataFrame()
    frame = pd.DataFrame(rows)
    frame["date"] = pd.to_datetime(frame["date"])
    frame.set_index("date", inplace=True)
    return frame


class TestSuspensionHandling:
    """BETA-007: 停牌检测 — volume=0 的标的不可交易。"""

    def test_normal_volume_included(self, monkeypatch) -> None:
        """volume>0 的标的正常包含价格。"""
        loader = _make_loader(["000001"])

        def fake_get_price_data(ticker, start, end, api_key=None):
            return _make_price_frame([
                {"date": "2024-01-15", "close": 10.0, "volume": 1_000_000},
            ])

        monkeypatch.setattr("src.backtesting.engine_market_data.get_price_data", fake_get_price_data)
        prices = loader.load_current_prices(["000001"], "2024-01-01", "2024-01-15")
        assert prices is not None
        assert prices["000001"] == 10.0

    def test_suspended_stock_excluded(self, monkeypatch) -> None:
        """volume=0 (停牌) 的标的被排除。"""
        loader = _make_loader(["000001"])

        def fake_get_price_data(ticker, start, end, api_key=None):
            return _make_price_frame([
                {"date": "2024-01-15", "close": 10.0, "volume": 0},
            ])

        monkeypatch.setattr("src.backtesting.engine_market_data.get_price_data", fake_get_price_data)
        prices = loader.load_current_prices(["000001"], "2024-01-01", "2024-01-15")
        # 唯一标的停牌 → 空价格 → None
        assert prices is None

    def test_mixed_active_and_suspended(self, monkeypatch) -> None:
        """一个停牌一个正常 → 只返回正常标的。"""
        loader = _make_loader(["000001", "000002"])

        def fake_get_price_data(ticker, start, end, api_key=None):
            if ticker == "000001":
                return _make_price_frame([
                    {"date": "2024-01-15", "close": 10.0, "volume": 1_000_000},
                ])
            # 000002 停牌
            return _make_price_frame([
                {"date": "2024-01-15", "close": 20.0, "volume": 0},
            ])

        monkeypatch.setattr("src.backtesting.engine_market_data.get_price_data", fake_get_price_data)
        prices = loader.load_current_prices(["000001", "000002"], "2024-01-01", "2024-01-15")
        assert prices is not None
        assert "000001" in prices
        assert "000002" not in prices

    def test_missing_volume_column_treated_as_tradable(self, monkeypatch) -> None:
        """数据源缺 volume 列 → 兼容, 视为可交易。"""
        loader = _make_loader(["000001"])

        def fake_get_price_data(ticker, start, end, api_key=None):
            # 缺 volume 列
            return _make_price_frame([
                {"date": "2024-01-15", "close": 10.0},
            ])

        monkeypatch.setattr("src.backtesting.engine_market_data.get_price_data", fake_get_price_data)
        prices = loader.load_current_prices(["000001"], "2024-01-01", "2024-01-15")
        assert prices is not None
        assert prices["000001"] == 10.0

    def test_all_suspended_returns_none(self, monkeypatch) -> None:
        """全部停牌 → 返回 None (引擎跳过该日)。"""
        loader = _make_loader(["000001", "000002"])

        def fake_get_price_data(ticker, start, end, api_key=None):
            return _make_price_frame([
                {"date": "2024-01-15", "close": 10.0, "volume": 0},
            ])

        monkeypatch.setattr("src.backtesting.engine_market_data.get_price_data", fake_get_price_data)
        prices = loader.load_current_prices(["000001", "000002"], "2024-01-01", "2024-01-15")
        assert prices is None

    def test_empty_price_data_excluded(self, monkeypatch) -> None:
        """空价格数据 → 排除 (已有行为, 验证不回归)。"""
        loader = _make_loader(["000001"])

        def fake_get_price_data(ticker, start, end, api_key=None):
            return pd.DataFrame()

        monkeypatch.setattr("src.backtesting.engine_market_data.get_price_data", fake_get_price_data)
        prices = loader.load_current_prices(["000001"], "2024-01-01", "2024-01-15")
        assert prices is None
