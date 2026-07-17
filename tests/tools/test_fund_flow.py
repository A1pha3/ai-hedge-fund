"""资金流多源 dispatcher 测试 — tushare → akshare → ftshare fallback 逻辑 + ftshare 列级补全。"""

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


# ── ftshare 列级补全 (enrich) ──────────────────────────────────────────────
# 见 fund_flow.py 模块 docstring: tushare moneyflow 不含 close / main_net_pct,
# 旧实现只做整源替换, tushare 一旦非空就立即返回, 永远不会调到 ftshare —
# 这两列恒为 NaN, 被 pit_evidence.validate_flow_artifact fail-closed 拒掉整票。
# fix: tushare 获胜后用 ftshare 按日期补这两列, 保留金额字段不动。


def _tushare_like_df_with_nan_gaps():
    """模拟 tushare 返回: 金额列有值, close/main_net_pct 全 NaN (真实 schema 缺陷)。"""
    return pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-07-14", "2026-07-15"]),
            "close": [float("nan"), float("nan")],
            "pct_change": [0.0, 0.0],
            "main_net_inflow": [6_386_000.0, -24_061_900.0],
            "main_net_pct": [float("nan"), float("nan")],
            "big_net_inflow": [-1_444_800.0, -8_718_900.0],
        }
    )


def _ftshare_like_df():
    """模拟 ftshare 返回: 同日期, 提供 close / main_net_pct (东财源核心优势)。"""
    return pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-07-14", "2026-07-15"]),
            "close": [10.5, 9.8],
            "pct_change": [1.2, -0.5],
            "main_net_inflow": [9_999_999.0, -9_999_999.0],  # 不同值! 必须不被采纳
            "main_net_pct": [3.5, -2.1],
            "big_net_inflow": [123.0, 456.0],
        }
    )


def test_tushare_nan_close_and_main_net_pct_enriched_from_ftshare():
    """tushare 返回 NaN close/main_net_pct → ftshare 按日期补全, 金额列保持 tushare 原值。"""
    with patch("src.tools.fund_flow._try_tushare", return_value=_tushare_like_df_with_nan_gaps()), patch(
        "src.tools.ftshare_api.fetch_individual_fund_flow_ftshare",
        return_value=_ftshare_like_df(),
    ) as mock_ftshare_call, patch("src.tools.fund_flow._try_akshare") as mock_akshare_call:
        df = fetch_individual_fund_flow("000504", start_date="20260701", end_date="20260716")

    assert len(df) == 2
    # close / main_net_pct 被补上 (来自 ftshare)
    assert df["close"].tolist() == [10.5, 9.8]
    assert df["main_net_pct"].tolist() == [3.5, -2.1]
    # 金额列保持 tushare 原值, ftshare 的值没被采纳
    assert df["main_net_inflow"].tolist() == [6_386_000.0, -24_061_900.0]
    assert df["big_net_inflow"].tolist() == [-1_444_800.0, -8_718_900.0]
    # ftshare 命中, akshare 不再被试
    mock_ftshare_call.assert_called_once_with("000504", "20260701", "20260716")
    mock_akshare_call.assert_not_called()


def test_enrich_skipped_when_base_already_complete():
    """主源返回的 close/main_net_pct 都无 NaN → 补全源都不被调用 (零开销快路径)。"""
    complete_df = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-07-14"]),
            "close": [10.5],
            "pct_change": [1.2],
            "main_net_inflow": [6_386_000.0],
            "main_net_pct": [3.5],
            "big_net_inflow": [-1_444_800.0],
        }
    )
    with patch("src.tools.fund_flow._try_tushare", return_value=complete_df), patch(
        "src.tools.ftshare_api.fetch_individual_fund_flow_ftshare",
    ) as mock_ftshare_call, patch("src.tools.fund_flow._try_akshare") as mock_akshare_call:
        df = fetch_individual_fund_flow("000504", start_date="20260701", end_date="20260716")

    assert len(df) == 1
    assert df["close"].tolist() == [10.5]
    assert df["main_net_pct"].tolist() == [3.5]
    # 快路径: base 已完整, 两个补全源都不调
    mock_ftshare_call.assert_not_called()
    mock_akshare_call.assert_not_called()


def test_enrich_tolerates_both_sources_failure():
    """ftshare 抛异常 + akshare 也空 → 返回主源原样 (含 NaN), 不 crash。

    落盘层 (pit_evidence) 会决定是否拒掉含 NaN 的行; fetch 层不该替它决定填 0 还是抛错。
    """
    base_with_nan = _tushare_like_df_with_nan_gaps()
    with patch("src.tools.fund_flow._try_tushare", return_value=base_with_nan.copy()), patch(
        "src.tools.ftshare_api.fetch_individual_fund_flow_ftshare",
        side_effect=RuntimeError("ftshare offline"),
    ), patch("src.tools.fund_flow._try_akshare", return_value=pd.DataFrame()):
        df = fetch_individual_fund_flow("000504", start_date="20260701", end_date="20260716")

    assert len(df) == 2
    # 两个补全源都没了, 主源原样返回 (close/main_net_pct 仍是 NaN)
    assert df["main_net_inflow"].tolist() == [6_386_000.0, -24_061_900.0]
    assert pd.isna(df["close"].iloc[0])
    assert pd.isna(df["main_net_pct"].iloc[0])


def test_enrich_falls_back_to_akshare_when_ftshare_unavailable():
    """ftshare 未安装/空 → akshare 兜底补全 (这是生产环境的主路径, ftshare 常未装)。"""
    with patch("src.tools.fund_flow._try_tushare", return_value=_tushare_like_df_with_nan_gaps()), patch(
        "src.tools.ftshare_api.fetch_individual_fund_flow_ftshare",
        return_value=pd.DataFrame(),  # 模拟 ftshare 未安装 → 空 df
    ) as mock_ftshare_call, patch(
        "src.tools.fund_flow._try_akshare",
        return_value=_ftshare_like_df(),  # akshare 提供同样的 schema
    ) as mock_akshare_call:
        df = fetch_individual_fund_flow("000504", start_date="20260701", end_date="20260716")

    assert len(df) == 2
    # close / main_net_pct 被 akshare 补上
    assert df["close"].tolist() == [10.5, 9.8]
    assert df["main_net_pct"].tolist() == [3.5, -2.1]
    # 金额列保持 tushare 原值
    assert df["main_net_inflow"].tolist() == [6_386_000.0, -24_061_900.0]
    # ftshare 先被试, akshare 作为兜底被调
    mock_ftshare_call.assert_called_once()
    mock_akshare_call.assert_called_once()


def test_enrich_preserves_base_rows_when_supplement_has_extra_dates():
    """补全源返回了 base 没有的日期 → 不能追加到 base, base 行数不变 (不污染行集)。"""
    base = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-07-14"]),
            "close": [float("nan")],
            "pct_change": [0.0],
            "main_net_inflow": [6_386_000.0],
            "main_net_pct": [float("nan")],
            "big_net_inflow": [-1_444_800.0],
        }
    )
    # 补全源多了 07-13 和 07-16 两天, base 只有 07-14
    supp = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-07-13", "2026-07-14", "2026-07-16"]),
            "close": [11.0, 10.5, 9.0],
            "pct_change": [0.5, 1.2, -1.0],
            "main_net_inflow": [1.0, 2.0, 3.0],
            "main_net_pct": [1.0, 3.5, -3.0],
            "big_net_inflow": [10.0, 20.0, 30.0],
        }
    )
    with patch("src.tools.fund_flow._try_tushare", return_value=base), patch(
        "src.tools.ftshare_api.fetch_individual_fund_flow_ftshare",
        return_value=supp,
    ):
        df = fetch_individual_fund_flow("000504", start_date="20260701", end_date="20260716")

    assert len(df) == 1  # base 行数不变, 没追加 07-13/07-16
    assert df["close"].tolist() == [10.5]  # 07-14 的 NaN 被补上
    assert df["main_net_pct"].tolist() == [3.5]
    assert df["main_net_inflow"].tolist() == [6_386_000.0]  # 金额列保留 base 原值
