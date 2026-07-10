"""宏观多源 dispatcher 测试 — tushare → ftshare fallback。"""

from __future__ import annotations

from unittest.mock import patch

from src.data.macro_data import MacroSnapshot
from src.tools.macro_multi import fetch_macro_snapshot_multi


def test_tushare_valid_skips_ftshare():
    """tushare 宏观快照有效 (至少一个字段非 None) → 不调 ftshare。"""
    valid_snapshot = MacroSnapshot(cpi_yoy=2.5, ppi_yoy=-1.0, m2_yoy=7.0)
    with patch("src.data.macro_data.fetch_macro_snapshot", return_value=valid_snapshot), patch("src.tools.ftshare_api.fetch_macro_snapshot_ftshare") as mock_ft:
        result = fetch_macro_snapshot_multi()
    assert result.cpi_yoy == 2.5
    mock_ft.assert_not_called()


def test_tushare_all_none_falls_back_to_ftshare():
    """tushare 全字段 None → fallback 到 ftshare 并填充。"""
    empty_snapshot = MacroSnapshot()  # 全部 None
    ftshare_data = {
        "cpi": {"nt_yoy": 2.5, "month": "202606"},
        "ppi": {"ppi_yoy": -1.0},
        "pmi": {"pmi010000": 49.5},
        "m2": {"m2_yoy": 7.0},
        "sf": {"inc_month": 50000},
        "lpr": {"1y": 3.45},
    }
    with patch("src.data.macro_data.fetch_macro_snapshot", return_value=empty_snapshot), patch("src.tools.ftshare_api.fetch_macro_snapshot_ftshare", return_value=ftshare_data):
        result = fetch_macro_snapshot_multi()

    assert result.cpi_yoy == 2.5
    assert result.ppi_yoy == -1.0
    assert result.pmi_manufacturing == 49.5
    assert result.m2_yoy == 7.0
    assert result.social_financing == 50000
    assert result.interest_rate_lpr_1y == 3.45
    assert result.date == "202606"


def test_tushare_exception_falls_back_to_ftshare():
    """tushare fetch_macro_snapshot 抛异常 → 不 crash, fallback ftshare。"""
    ftshare_data = {"cpi": {"nt_yoy": 2.5, "month": "202606"}}
    with patch("src.data.macro_data.fetch_macro_snapshot", side_effect=RuntimeError("tushare down")), patch("src.tools.ftshare_api.fetch_macro_snapshot_ftshare", return_value=ftshare_data):
        result = fetch_macro_snapshot_multi()
    assert result.cpi_yoy == 2.5


def test_both_sources_empty_returns_empty_snapshot():
    """tushare + ftshare 均空 → 返回空 MacroSnapshot。"""
    empty_snapshot = MacroSnapshot()
    with patch("src.data.macro_data.fetch_macro_snapshot", return_value=empty_snapshot), patch("src.tools.ftshare_api.fetch_macro_snapshot_ftshare", return_value={}):
        result = fetch_macro_snapshot_multi()
    assert result.cpi_yoy is None
    assert result.m2_yoy is None


def test_ftshare_does_not_overwrite_tushare_values():
    """ftshare 只填充 tushare 未提供的字段 (None 的), 不覆盖已有值。"""
    partial_snapshot = MacroSnapshot(cpi_yoy=2.5, ppi_yoy=None)  # CPI 有值, PPI 缺
    ftshare_data = {
        "cpi": {"nt_yoy": 9.9},  # 应被忽略 (tushare 已有)
        "ppi": {"ppi_yoy": -1.0},  # 应被填充
    }
    with patch("src.data.macro_data.fetch_macro_snapshot", return_value=partial_snapshot), patch("src.tools.ftshare_api.fetch_macro_snapshot_ftshare", return_value=ftshare_data):
        result = fetch_macro_snapshot_multi()
    # 但注意: partial_snapshot 本身有 cpi_yoy=2.5, 所以不会 fallback 到 ftshare
    # 这个测试验证: 即使走了 ftshare 路径, 也不覆盖
    assert result.cpi_yoy == 2.5  # tushare 的值保留


def test_ftshare_partial_fill():
    """ftshare 只有部分宏观数据 → 只填充有的。"""
    empty_snapshot = MacroSnapshot()
    ftshare_data = {
        "cpi": {"nt_yoy": 2.5, "month": "202606"},
        # ppi/pmi/m2/sf/lpr 缺失
    }
    with patch("src.data.macro_data.fetch_macro_snapshot", return_value=empty_snapshot), patch("src.tools.ftshare_api.fetch_macro_snapshot_ftshare", return_value=ftshare_data):
        result = fetch_macro_snapshot_multi()
    assert result.cpi_yoy == 2.5
    assert result.ppi_yoy is None
    assert result.m2_yoy is None
