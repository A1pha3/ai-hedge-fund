"""资金流数据获取测试。网络调用全部 mock。"""
from __future__ import annotations

import pandas as pd
import pytest
import requests
from unittest.mock import patch

import src.tools.akshare_fund_flow as aff


@pytest.fixture(autouse=True)
def _reset_circuit_breaker():
    """熔断器是模块级状态, 每个测试前后复位, 避免跨测试/跨模块污染。"""
    aff._reset_circuit_breaker()
    aff._network_error_counts.clear()
    yield
    aff._reset_circuit_breaker()
    aff._network_error_counts.clear()


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


# ── 熔断器 ────────────────────────────────────────────────────────────────
# 东财 WAF 封禁期 (2026-07-17 实测本机 IP 对 push2his /api/qt/* 100% 断连)
# 逐票重试纯属浪费: 连续网络失败 _BREAKER_THRESHOLD 次后熔断,
# 冷却期零网络调用, 后半开试探, 成功即复位。


def test_circuit_breaker_trips_and_skips_http():
    """连续网络失败达到阈值 → 熔断; 熔断后的调用不再发 HTTP 请求。"""
    with patch.object(aff.ak, "stock_individual_fund_flow", side_effect=requests.exceptions.ProxyError("boom")) as mock_ak:
        for _ in range(aff._BREAKER_THRESHOLD):
            aff.fetch_individual_fund_flow("000504")
        assert aff.circuit_breaker_open() is True
        calls_at_trip = mock_ak.call_count

        result = aff.fetch_individual_fund_flow("000504")
        assert mock_ak.call_count == calls_at_trip  # 熔断后零网络调用
        assert len(result) == 0


def test_circuit_breaker_ignores_non_network_errors():
    """非网络异常 (如解析 bug) 不喂熔断器。"""
    with patch.object(aff.ak, "stock_individual_fund_flow", side_effect=ValueError("parse bug")):
        for _ in range(aff._BREAKER_THRESHOLD + 2):
            aff.fetch_individual_fund_flow("000504")
    assert aff.circuit_breaker_open() is False


def test_circuit_breaker_half_open_recovers_on_success():
    """冷却期过 → 半开试探; 成功即复位, 后续调用正常。"""
    fake_df = pd.DataFrame({
        "日期": ["2026-07-01"],
        "收盘价": [10.0],
        "主力净流入-净额": [1000000],
    })
    with patch.object(aff, "_BREAKER_COOLDOWN_SEC", 0.0):
        with patch.object(aff.ak, "stock_individual_fund_flow", side_effect=requests.exceptions.ProxyError("boom")):
            for _ in range(aff._BREAKER_THRESHOLD):
                aff.fetch_individual_fund_flow("000504")
            assert aff.circuit_breaker_open() is False  # cooldown=0 → 立即半开
        with patch.object(aff.ak, "stock_individual_fund_flow", return_value=fake_df):
            result = aff.fetch_individual_fund_flow("000504")
    assert len(result) == 1
    assert aff._breaker_opened_at is None
    assert aff._breaker_failures == 0


def test_circuit_breaker_half_open_failure_restarts_cooldown():
    """半开试探失败 → 冷却重新计时, 熔断保持。"""
    with patch.object(aff, "_BREAKER_COOLDOWN_SEC", 0.0):
        with patch.object(aff.ak, "stock_individual_fund_flow", side_effect=requests.exceptions.ProxyError("boom")):
            for _ in range(aff._BREAKER_THRESHOLD):
                aff.fetch_individual_fund_flow("000504")
            aff.fetch_individual_fund_flow("000504")  # 半开试探, 再失败
    # 恢复真实 cooldown 后, 熔断应保持打开 (冷却从上一次失败重新计时)
    assert aff.circuit_breaker_open() is True
