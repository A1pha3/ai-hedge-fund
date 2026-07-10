"""ftshare 源 fetcher 测试 — schema 归一化 + 优雅降级。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from src.tools.ftshare_api import (
    fetch_daily_ohlcv_ftshare,
    fetch_individual_fund_flow_ftshare,
    fetch_macro_snapshot_ftshare,
    _normalise_ohlcv,
    _normalise_fund_flow,
)


# ═══════════════════════════════════════════════════════════════════════════
# ftshare_client 单例 / 降级
# ═══════════════════════════════════════════════════════════════════════════

def test_ftshare_unavailable_returns_empty_price():
    """SDK 未安装 (_get_market 返回 None) → 返回空 DataFrame, 不抛异常。"""
    with patch("src.tools.ftshare_api._get_market", return_value=None):
        df = fetch_daily_ohlcv_ftshare("000001", "20260101", "20260710")
    assert len(df) == 0
    assert "date" in df.columns
    assert "close" in df.columns


def test_ftshare_unavailable_returns_empty_fund_flow():
    """SDK 未安装 → 资金流返回空 DataFrame。"""
    with patch("src.tools.ftshare_api._get_market", return_value=None):
        df = fetch_individual_fund_flow_ftshare("000001", "20260101", "20260710")
    assert len(df) == 0
    assert "date" in df.columns
    assert "main_net_inflow" in df.columns


def test_ftshare_unavailable_returns_empty_macro():
    """SDK 未安装 → 宏观返回空 dict。"""
    with patch("src.tools.ftshare_api._get_market", return_value=None):
        result = fetch_macro_snapshot_ftshare()
    assert result == {}


# ═══════════════════════════════════════════════════════════════════════════
# 日线 OHLCV 归一化
# ═══════════════════════════════════════════════════════════════════════════

def test_normalise_ohlcv_tushare_style_columns():
    """tushare 风格列名 (trade_date/open/close/...) → price_cache schema。"""
    raw = pd.DataFrame(
        {
            "trade_date": ["20260701", "20260702"],
            "open": [9.8, 10.1],
            "high": [10.2, 10.6],
            "low": [9.7, 10.0],
            "close": [10.0, 10.5],
            "vol": [100000, 120000],
            "pct_chg": [2.0, 5.0],
        }
    )
    df = _normalise_ohlcv(raw, "000001")
    assert list(df.columns) == ["date", "close", "open", "high", "low", "pct_change", "volume"]
    assert df.iloc[0]["date"] == "2026-07-01"  # YYYY-MM-DD
    assert df.iloc[1]["pct_change"] == 5.0  # 百分数


def test_normalise_ohlcv_missing_pct_calculates_from_close():
    """缺 pct_chg 列 → 从 close 计算 pct_change。"""
    raw = pd.DataFrame(
        {
            "trade_date": ["20260701", "20260702"],
            "open": [9.8, 10.1],
            "close": [10.0, 10.5],
            "high": [10.2, 10.6],
            "low": [9.7, 10.0],
            "vol": [100000, 120000],
        }
    )
    df = _normalise_ohlcv(raw, "000001")
    assert df.iloc[0]["pct_change"] == 0.0  # 首行无前日
    assert abs(df.iloc[1]["pct_change"] - 5.0) < 0.01  # (10.5/10.0-1)*100 = 5.0


def test_normalise_ohlcv_no_date_column_returns_empty():
    """无日期列 → 返回空。"""
    raw = pd.DataFrame({"close": [10.0], "open": [9.8]})
    df = _normalise_ohlcv(raw, "000001")
    assert len(df) == 0


# ═══════════════════════════════════════════════════════════════════════════
# 资金流归一化
# ═══════════════════════════════════════════════════════════════════════════

def test_normalise_fund_flow_eastmoney_columns():
    """东财风格中文列名 → fund_flow_cache schema。"""
    raw = pd.DataFrame(
        {
            "日期": ["20260701", "20260702"],
            "收盘价": [10.0, 10.5],
            "涨跌幅": [2.0, 5.0],
            "主力净流入-净额": [5000000, -3000000],  # 元
            "主力净流入-净占比": [3.5, -2.1],
            "超大单净流入-净额": [2000000, 1000000],
            "大单净流入-净额": [1000000, -500000],
            "中单净流入-净额": [-500000, 200000],
            "小单净流入-净额": [-100000, -200000],
        }
    )
    df = _normalise_fund_flow(raw, "000001")
    expected_cols = {"date", "close", "pct_change", "main_net_inflow", "main_net_pct",
                     "big_net_inflow", "super_big_net_inflow", "medium_net_inflow", "small_net_inflow"}
    assert expected_cols.issubset(set(df.columns))
    assert df.iloc[0]["main_net_inflow"] == 5000000  # 元, 未被 ×10000 (已 >1e4)
    assert df.iloc[0]["main_net_pct"] == 3.5  # 东财占比保留


def test_normalise_fund_flow_wan_to_yuan_conversion():
    """万元级数据 → 自动 ×10000 转元。"""
    raw = pd.DataFrame(
        {
            "日期": ["20260701"],
            "主力净流入-净额": [500.0],  # 中位数 <1e4 → 判定为万元
            "超大单净流入-净额": [200.0],
            "大单净流入-净额": [100.0],
            "中单净流入-净额": [-50.0],
            "小单净流入-净额": [-10.0],
        }
    )
    df = _normalise_fund_flow(raw, "000001")
    assert df.iloc[0]["main_net_inflow"] == 5000000  # 500万 × 10000 = 500万元→5e6元... wait
    # 500 (万元) × 10000 = 5,000,000 元
    assert df.iloc[0]["super_big_net_inflow"] == 2000000


# ═══════════════════════════════════════════════════════════════════════════
# 宏观指标
# ═══════════════════════════════════════════════════════════════════════════

def test_macro_snapshot_calls_six_endpoints():
    """fetch_macro_snapshot_ftshare 调用 6 个宏观接口。"""
    mock_market = MagicMock()
    mock_market.consumer_price_index_monthly.return_value = pd.DataFrame({"month": ["202606"], "nt_yoy": [2.5]})
    mock_market.consumer_ppi_monthly.return_value = pd.DataFrame({"month": ["202606"], "ppi_yoy": [-1.2]})
    mock_market.consumer_pmi_monthly.return_value = pd.DataFrame({"month": ["202606"], "pmi010000": [49.5]})
    mock_market.consumer_money_supply_monthly.return_value = pd.DataFrame({"month": ["202606"], "m2_yoy": [7.0]})
    mock_market.consumer_credit_monthly.return_value = pd.DataFrame({"month": ["202606"], "inc_month": [50000]})
    mock_market.lpr_monthly.return_value = pd.DataFrame({"date": ["202606"], "1y": [3.45]})

    with patch("src.tools.ftshare_api._get_market", return_value=mock_market):
        result = fetch_macro_snapshot_ftshare()

    assert "cpi" in result
    assert "ppi" in result
    assert "pmi" in result
    assert "m2" in result
    assert "sf" in result
    assert "lpr" in result
    assert result["cpi"]["nt_yoy"] == 2.5
    assert result["lpr"]["1y"] == 3.45


def test_macro_snapshot_partial_failure():
    """部分宏观接口异常 → 只返回成功的。"""
    mock_market = MagicMock()
    mock_market.consumer_price_index_monthly.return_value = pd.DataFrame({"nt_yoy": [2.5]})
    mock_market.consumer_ppi_monthly.side_effect = Exception("PPI down")
    mock_market.consumer_pmi_monthly.return_value = pd.DataFrame()
    mock_market.consumer_money_supply_monthly.return_value = pd.DataFrame({"m2_yoy": [7.0]})
    mock_market.consumer_credit_monthly.return_value = pd.DataFrame()
    mock_market.lpr_monthly.return_value = pd.DataFrame()

    with patch("src.tools.ftshare_api._get_market", return_value=mock_market):
        result = fetch_macro_snapshot_ftshare()

    assert "cpi" in result
    assert "ppi" not in result  # 异常 → 不包含
    assert "pmi" not in result  # 空 → 不包含
    assert "m2" in result
