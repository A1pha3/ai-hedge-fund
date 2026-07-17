"""tushare 资金流 fetcher 单元测试 — ts_code 映射 / 单位归一化 / 重试逻辑。

token 加载已收编到 src.tools.tushare_api.get_tushare_token (commit 435cc495),
其测试见 tests/tools/test_tushare_token.py; 本文件不再重复覆盖。
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pandas as pd

from src.tools.tushare_fund_flow import _to_ts_code, fetch_individual_fund_flow_tushare


def test_to_ts_code_sh():
    assert _to_ts_code("600519") == "600519.SH"
    assert _to_ts_code("688981") == "688981.SH"


def test_to_ts_code_sz():
    assert _to_ts_code("000001") == "000001.SZ"
    assert _to_ts_code("300502") == "300502.SZ"


def test_to_ts_code_bj():
    assert _to_ts_code("830879") == "830879.BJ"


def test_fetch_returns_empty_when_no_token():
    """无 token → 返回空, 不调 tushare。"""
    with patch("src.tools.tushare_fund_flow.get_tushare_token", return_value=""):
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
    with patch("src.tools.tushare_fund_flow.get_tushare_token", return_value="fake_token"), patch("tushare.pro_api") as mock_pro:
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
    with patch("src.tools.tushare_fund_flow.get_tushare_token", return_value="fake_token"), patch("tushare.pro_api", side_effect=RuntimeError("api error")):
        df = fetch_individual_fund_flow_tushare("300502")
    assert len(df) == 0


# ---------------------------------------------------------------------------
# 重试逻辑测试 — 网络抖动 (瞬时错误) 是资金流 tushare 返回空的主因:
# 无重试时退化到不稳定的 akshare push2his, 导致双源全空。
# ---------------------------------------------------------------------------


def _make_fake_raw() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "ts_code": ["300502.SZ"],
            "trade_date": ["20260701"],
            "buy_sm_amount": [0.0],
            "sell_sm_amount": [0.0],
            "buy_md_amount": [0.0],
            "sell_md_amount": [0.0],
            "buy_lg_amount": [0.0],
            "sell_lg_amount": [0.0],
            "buy_elg_amount": [0.0],
            "sell_elg_amount": [0.0],
            "net_mf_amount": [100.0],
            "net_mf_vol": [0.0],
        }
    )


def test_retry_succeeds_after_transient_errors(monkeypatch):
    """瞬时错误 (超时/连接中断) 重试后应成功, 不退化到 akshare。"""
    monkeypatch.setenv("TUSHARE_MAX_RETRIES", "2")
    monkeypatch.setenv("TUSHARE_RETRY_BASE_DELAY", "0.01")

    fake_raw = _make_fake_raw()
    mock_pro = MagicMock()
    # 前两次网络错误, 第三次成功
    mock_pro.moneyflow.side_effect = [ConnectionError("timeout"), ConnectionError("reset"), fake_raw]

    with patch("src.tools.tushare_fund_flow.get_tushare_token", return_value="fake_token"), patch("tushare.pro_api", return_value=mock_pro):
        df = fetch_individual_fund_flow_tushare("300502", start_date="20260701", end_date="20260701")

    assert mock_pro.moneyflow.call_count == 3  # 1 初试 + 2 重试
    assert len(df) == 1


def test_no_retry_for_non_retryable_error(monkeypatch):
    """参数/权限类错误 (ValueError 等) 不重试, 直接返回空。"""
    monkeypatch.setenv("TUSHARE_MAX_RETRIES", "2")

    mock_pro = MagicMock()
    mock_pro.moneyflow.side_effect = ValueError("bad param")

    with patch("src.tools.tushare_fund_flow.get_tushare_token", return_value="fake_token"), patch("tushare.pro_api", return_value=mock_pro):
        df = fetch_individual_fund_flow_tushare("300502")

    assert mock_pro.moneyflow.call_count == 1  # 不可重试 → 只调一次
    assert len(df) == 0


def test_retry_exhausted_returns_empty(monkeypatch):
    """持续网络错误 → 重试 MAX_RETRIES 次后返回空。"""
    monkeypatch.setenv("TUSHARE_MAX_RETRIES", "2")
    monkeypatch.setenv("TUSHARE_RETRY_BASE_DELAY", "0.01")

    mock_pro = MagicMock()
    mock_pro.moneyflow.side_effect = ConnectionError("persistent timeout")

    with patch("src.tools.tushare_fund_flow.get_tushare_token", return_value="fake_token"), patch("tushare.pro_api", return_value=mock_pro):
        df = fetch_individual_fund_flow_tushare("300502")

    assert mock_pro.moneyflow.call_count == 3  # 1 初试 + 2 重试
    assert len(df) == 0


def test_no_retry_for_permission_error(monkeypatch):
    """'请指定正确的接口名' = 无权限, 不重试。"""
    monkeypatch.setenv("TUSHARE_MAX_RETRIES", "2")

    mock_pro = MagicMock()
    mock_pro.moneyflow.side_effect = RuntimeError("请指定正确的接口名")

    with patch("src.tools.tushare_fund_flow.get_tushare_token", return_value="fake_token"), patch("tushare.pro_api", return_value=mock_pro):
        df = fetch_individual_fund_flow_tushare("300502")

    assert mock_pro.moneyflow.call_count == 1
    assert len(df) == 0
