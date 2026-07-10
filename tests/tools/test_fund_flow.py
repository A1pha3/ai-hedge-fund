"""资金流多源 dispatcher 测试 — tushare → akshare → ftshare fallback 逻辑。"""

from __future__ import annotations

from unittest.mock import patch

import pandas as pd

from src.tools.fund_flow import fetch_individual_fund_flow, _try_tushare, _try_akshare


def _fake_df(source_tag: str):
    return pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-07-01"]),
            "main_net_inflow": [1_000_000],
            "source": [source_tag],  # 标记来源便于断言
        }
    )


def test_multi_source_uses_tushare_when_available():
    """tushare 返回数据 → 用 tushare, 不调 akshare/ftshare。"""
    with patch("src.tools.fund_flow._try_tushare", return_value=_fake_df("tushare")) as mock_t, patch("src.tools.fund_flow._try_akshare", return_value=_fake_df("akshare")) as mock_a, patch("src.tools.fund_flow._try_ftshare", return_value=_fake_df("ftshare")) as mock_f:
        df = fetch_individual_fund_flow("300502")
    assert len(df) == 1
    assert df.iloc[0]["source"] == "tushare"
    mock_t.assert_called_once()
    mock_a.assert_not_called()  # tushare 命中, 没必要 fallback
    mock_f.assert_not_called()


def test_multi_source_falls_back_to_akshare_when_tushare_empty():
    """tushare 返回空 → fallback 到 akshare。"""
    with patch("src.tools.fund_flow._try_tushare", return_value=pd.DataFrame()), patch("src.tools.fund_flow._try_akshare", return_value=_fake_df("akshare")):
        df = fetch_individual_fund_flow("300502")
    assert len(df) == 1
    assert df.iloc[0]["source"] == "akshare"


def test_multi_source_falls_back_to_ftshare_when_tushare_and_akshare_empty():
    """tushare + akshare 均空 → fallback 到 ftshare (第 3 源)。"""
    with patch("src.tools.fund_flow._try_tushare", return_value=pd.DataFrame()), patch("src.tools.fund_flow._try_akshare", return_value=pd.DataFrame()), patch("src.tools.fund_flow._try_ftshare", return_value=_fake_df("ftshare")):
        df = fetch_individual_fund_flow("300502")
    assert len(df) == 1
    assert df.iloc[0]["source"] == "ftshare"


def test_multi_source_falls_back_on_tushare_exception():
    """tushare 抛异常 → fallback 到 akshare, 不 crash。"""
    with patch("src.tools.fund_flow._try_tushare", side_effect=ConnectionError("tushare down")), patch("src.tools.fund_flow._try_akshare", return_value=_fake_df("akshare")):
        df = fetch_individual_fund_flow("300502")
    assert len(df) == 1
    assert df.iloc[0]["source"] == "akshare"


def test_multi_source_all_fail_returns_empty():
    """三源都空 → 返回空 DataFrame (不抛异常)。"""
    with patch("src.tools.fund_flow._try_tushare", return_value=pd.DataFrame()), patch("src.tools.fund_flow._try_akshare", return_value=pd.DataFrame()), patch("src.tools.fund_flow._try_ftshare", return_value=pd.DataFrame()):
        df = fetch_individual_fund_flow("300502")
    assert len(df) == 0


def test_multi_source_primary_akshare_option():
    """primary='akshare' → 优先 akshare。"""
    with patch("src.tools.fund_flow._try_akshare", return_value=_fake_df("akshare")) as mock_a, patch("src.tools.fund_flow._try_tushare", return_value=_fake_df("tushare")) as mock_t, patch("src.tools.fund_flow._try_ftshare", return_value=_fake_df("ftshare")) as mock_f:
        df = fetch_individual_fund_flow("300502", primary="akshare")
    assert df.iloc[0]["source"] == "akshare"
    mock_a.assert_called_once()
    mock_t.assert_not_called()
    mock_f.assert_not_called()


def test_try_akshare_filters_by_date_range():
    """akshare fallback 时按 start/end_date 过滤 (akshare 原生不支持日期参数)。"""
    fake_full = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-06-01", "2026-06-15", "2026-07-01"]),
            "main_net_inflow": [1, 2, 3],
        }
    )
    with patch("src.tools.akshare_fund_flow.fetch_individual_fund_flow", return_value=fake_full):
        df = _try_akshare("X", start_date="20260610", end_date="20260620")
    assert len(df) == 1  # 只 2026-06-15 在 [0610, 0620] 内
    assert df.iloc[0]["main_net_inflow"] == 2
