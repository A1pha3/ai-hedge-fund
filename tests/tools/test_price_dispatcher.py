"""日线行情多源 dispatcher 测试 — tushare → akshare → ftshare fallback。"""

from __future__ import annotations

from unittest.mock import patch

import pandas as pd

from src.tools.price import fetch_daily_ohlcv


def _fake_price_df(source_tag: str) -> pd.DataFrame:
    """构造标准化 price DataFrame, 带 source 列便于断言。"""
    return pd.DataFrame(
        {
            "date": ["2026-07-01", "2026-07-02"],
            "close": [10.0, 10.5],
            "open": [9.8, 10.1],
            "high": [10.2, 10.6],
            "low": [9.7, 10.0],
            "pct_change": [0.0, 5.0],
            "volume": [100000.0, 120000.0],
            "source": [source_tag, source_tag],
        }
    )


def test_price_uses_tushare_when_available():
    """tushare 返回数据 → 用 tushare, 不调 akshare/ftshare。"""
    with patch("src.tools.price._try_tushare", return_value=_fake_price_df("tushare")) as mock_t, patch("src.tools.price._try_akshare", return_value=_fake_price_df("akshare")) as mock_a, patch("src.tools.price._try_ftshare", return_value=_fake_price_df("ftshare")) as mock_f:
        df = fetch_daily_ohlcv("000001", "20260101", "20260710")
    assert len(df) == 2
    assert df.iloc[0]["source"] == "tushare"
    mock_t.assert_called_once()
    mock_a.assert_not_called()
    mock_f.assert_not_called()


def test_price_falls_back_to_akshare_when_tushare_empty():
    """tushare 空 → akshare。"""
    with patch("src.tools.price._try_tushare", return_value=pd.DataFrame()), patch("src.tools.price._try_akshare", return_value=_fake_price_df("akshare")):
        df = fetch_daily_ohlcv("000001", "20260101", "20260710")
    assert df.iloc[0]["source"] == "akshare"


def test_price_falls_back_to_ftshare_when_both_empty():
    """tushare + akshare 空 → ftshare (第 3 源)。"""
    with patch("src.tools.price._try_tushare", return_value=pd.DataFrame()), patch("src.tools.price._try_akshare", return_value=pd.DataFrame()), patch("src.tools.price._try_ftshare", return_value=_fake_price_df("ftshare")):
        df = fetch_daily_ohlcv("000001", "20260101", "20260710")
    assert df.iloc[0]["source"] == "ftshare"


def test_price_falls_back_on_exception():
    """tushare 异常 → akshare, 不 crash。"""
    with patch("src.tools.price._try_tushare", side_effect=TimeoutError("tushare timeout")), patch("src.tools.price._try_akshare", return_value=_fake_price_df("akshare")):
        df = fetch_daily_ohlcv("000001", "20260101", "20260710")
    assert df.iloc[0]["source"] == "akshare"


def test_price_all_fail_returns_empty():
    """三源全空 → 空 DataFrame (不抛异常)。"""
    with patch("src.tools.price._try_tushare", return_value=pd.DataFrame()), patch("src.tools.price._try_akshare", return_value=pd.DataFrame()), patch("src.tools.price._try_ftshare", return_value=pd.DataFrame()):
        df = fetch_daily_ohlcv("000001", "20260101", "20260710")
    assert len(df) == 0
    assert "date" in df.columns
    assert "close" in df.columns


def test_price_schema_columns():
    """返回 DataFrame 必须有 price_cache schema 的 7 列。"""
    with patch("src.tools.price._try_tushare", return_value=_fake_price_df("tushare")):
        df = fetch_daily_ohlcv("000001", "20260101", "20260710")
    expected = {"date", "close", "open", "high", "low", "pct_change", "volume"}
    assert expected.issubset(set(df.columns))


def test_price_akshare_normalisation():
    """akshare 中文列名 → price_cache schema 归一化。"""
    from src.tools.price import _normalise_akshare

    raw = pd.DataFrame(
        {
            "日期": ["2026-07-01", "2026-07-02"],
            "开盘": [9.8, 10.1],
            "收盘": [10.0, 10.5],
            "最高": [10.2, 10.6],
            "最低": [9.7, 10.0],
            "成交量": [100000, 120000],
            "涨跌幅": [2.0, 5.0],
        }
    )
    df = _normalise_akshare(raw)
    assert list(df.columns)[:7] == ["date", "close", "open", "high", "low", "pct_change", "volume"]
    assert df.iloc[0]["date"] == "2026-07-01"
    assert df.iloc[0]["close"] == 10.0
    assert df.iloc[1]["pct_change"] == 5.0  # 百分数, 非小数
