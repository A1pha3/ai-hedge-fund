"""资金流数据获取测试。网络调用全部 mock。"""
from __future__ import annotations

import pandas as pd
from unittest.mock import patch


def test_fetch_individual_fund_flow_normalizes_columns():
    """拉取后列名标准化为英文 snake_case, 日期列为 datetime。"""
    from src.tools.akshare_fund_flow import fetch_individual_fund_flow

    # Mock akshare 返回原始中文列名
    fake_df = pd.DataFrame({
        "日期": ["2026-07-01", "2026-07-02"],
        "收盘价": [10.0, 10.5],
        "涨跌幅": [1.0, 5.0],
        "主力净流入-净额": [1000000, -500000],
        "主力净流入-净占比": [5.0, -2.5],
    })
    with patch("src.tools.akshare_fund_flow.ak.stock_individual_fund_flow", return_value=fake_df):
        result = fetch_individual_fund_flow("300054")

    assert "date" in result.columns
    assert "main_net_inflow" in result.columns
    assert pd.api.types.is_datetime64_any_dtype(result["date"])
    assert len(result) == 2


def test_fetch_individual_fund_flow_market_mapping_sz():
    """深圳 ticker (0/3 开头) → market='sz'。"""
    from src.tools.akshare_fund_flow import _resolve_market

    assert _resolve_market("300054") == "sz"
    assert _resolve_market("000001") == "sz"
    assert _resolve_market("600519") == "sh"
    assert _resolve_market("688981") == "sh"


def test_fetch_individual_fund_flow_returns_empty_on_api_error():
    """akshare 抛异常时返回空 DataFrame, 不 crash。"""
    from src.tools.akshare_fund_flow import fetch_individual_fund_flow

    with patch("src.tools.akshare_fund_flow.ak.stock_individual_fund_flow", side_effect=Exception("network")):
        result = fetch_individual_fund_flow("300054")

    assert isinstance(result, pd.DataFrame)
    assert len(result) == 0
