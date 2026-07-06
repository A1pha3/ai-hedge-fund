"""tushare 资金流 fetcher 单元测试 — token 加载 / ts_code 映射 / 单位归一化。"""

from __future__ import annotations

from unittest.mock import patch

import pandas as pd

from src.tools.tushare_fund_flow import _to_ts_code, _load_token, fetch_individual_fund_flow_tushare


def test_to_ts_code_sh():
    assert _to_ts_code("600519") == "600519.SH"
    assert _to_ts_code("688981") == "688981.SH"


def test_to_ts_code_sz():
    assert _to_ts_code("000001") == "000001.SZ"
    assert _to_ts_code("300502") == "300502.SZ"


def test_to_ts_code_bj():
    assert _to_ts_code("830879") == "830879.BJ"


def test_load_token_from_env(monkeypatch):
    monkeypatch.setenv("TUSHARE_TOKEN", "test_token_123")
    # 确保不走 .env 文件
    monkeypatch.setattr("pathlib.Path.exists", lambda self: False)
    assert _load_token() == "test_token_123"


def test_load_token_missing_returns_empty(monkeypatch):
    monkeypatch.delenv("TUSHARE_TOKEN", raising=False)
    monkeypatch.setattr("pathlib.Path.exists", lambda self: False)
    assert _load_token() == ""


def test_fetch_returns_empty_when_no_token(monkeypatch):
    """无 token → 返回空, 不调 tushare。"""
    monkeypatch.delenv("TUSHARE_TOKEN", raising=False)
    monkeypatch.setattr("pathlib.Path.exists", lambda self: False)
    df = fetch_individual_fund_flow_tushare("300502")
    assert len(df) == 0


def test_fetch_unit_conversion_wan_to_yuan():
    """tushare 万元 → 元 归一化 (×10000)。"""
    fake_raw = pd.DataFrame(
        {
            "ts_code": ["300502.SZ"],
            "trade_date": ["20260701"],
            "buy_sm_amount": [0.0],
            "sell_sm_amount": [1.0],
            "buy_md_amount": [10.0],
            "sell_md_amount": [5.0],
            "buy_lg_amount": [20.0],
            "sell_lg_amount": [15.0],
            "buy_elg_amount": [30.0],
            "sell_elg_amount": [25.0],
            "net_mf_amount": [-100.5],  # 万元
            "net_mf_vol": [-1000],
        }
    )
    with patch("src.tools.tushare_fund_flow._load_token", return_value="fake_token"), patch("tushare.pro_api") as mock_pro:
        mock_pro.return_value.moneyflow.return_value = fake_raw
        df = fetch_individual_fund_flow_tushare("300502", start_date="20260701", end_date="20260701")

    assert len(df) == 1
    # net_mf_amount=-100.5 万元 → main_net_inflow=-1005000 元
    assert df.iloc[0]["main_net_inflow"] == -100.5 * 10_000
    # 大单净流入 = (20 - 15) 万元 = 5万元 = 50000 元
    assert df.iloc[0]["big_net_inflow"] == 5 * 10_000
    # 超大单 = (30 - 25) × 10000 = 50000
    assert df.iloc[0]["super_big_net_inflow"] == 5 * 10_000


def test_fetch_handles_tushare_exception():
    """tushare API 抛异常 → 返回空, 不 crash。"""
    with patch("src.tools.tushare_fund_flow._load_token", return_value="fake_token"), patch("tushare.pro_api", side_effect=RuntimeError("api error")):
        df = fetch_individual_fund_flow_tushare("300502")
    assert len(df) == 0
