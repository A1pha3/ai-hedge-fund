"""P2-9 宏观数据集成测试。

覆盖:
  1. MacroSnapshot 默认值
  2. inflation_pressure 判定
  3. monetary_stance 判定
  4. economic_momentum 判定
  5. PMI 边界 (49, 50, 51)
  6. CPI 边界
  7. None 字段不影响 regime 计算
  8. render 输出
  9. CLI smoke (mock tushare)
  10. 缓存命中/未命中
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from src.data.macro_data import (
    compute_macro_regime,
    fetch_macro_snapshot,
    MacroSnapshot,
    render_macro_snapshot,
    run_macro_cli,
)

# ---------------------------------------------------------------------------
# 1. MacroSnapshot 默认值
# ---------------------------------------------------------------------------


class TestMacroSnapshotDefaults:
    def test_all_none_by_default(self):
        snap = MacroSnapshot()
        assert snap.date == ""
        assert snap.cpi_yoy is None
        assert snap.ppi_yoy is None
        assert snap.pmi_manufacturing is None
        assert snap.pmi_non_manufacturing is None
        assert snap.m2_yoy is None
        assert snap.social_financing is None
        assert snap.interest_rate_lpr_1y is None
        assert snap.inflation_pressure == ""
        assert snap.monetary_stance == ""
        assert snap.economic_momentum == ""

    def test_explicit_values(self):
        snap = MacroSnapshot(date="202605", cpi_yoy=2.1, ppi_yoy=-1.2, pmi_manufacturing=50.8)
        assert snap.date == "202605"
        assert snap.cpi_yoy == 2.1
        assert snap.ppi_yoy == -1.2
        assert snap.pmi_manufacturing == 50.8
        assert snap.pmi_non_manufacturing is None


# ---------------------------------------------------------------------------
# 2. inflation_pressure 判定
# ---------------------------------------------------------------------------


class TestInflationPressure:
    def test_low_inflation(self):
        snap = MacroSnapshot(cpi_yoy=0.5)
        regime = compute_macro_regime(snap)
        assert regime["inflation_pressure"] == "low"

    def test_moderate_inflation(self):
        snap = MacroSnapshot(cpi_yoy=2.1)
        regime = compute_macro_regime(snap)
        assert regime["inflation_pressure"] == "moderate"

    def test_high_inflation(self):
        snap = MacroSnapshot(cpi_yoy=3.5)
        regime = compute_macro_regime(snap)
        assert regime["inflation_pressure"] == "high"

    def test_unknown_when_none(self):
        snap = MacroSnapshot()
        regime = compute_macro_regime(snap)
        assert regime["inflation_pressure"] == "unknown"


# ---------------------------------------------------------------------------
# 3. monetary_stance 判定
# ---------------------------------------------------------------------------


class TestMonetaryStance:
    def test_loose_m2_high(self):
        snap = MacroSnapshot(m2_yoy=11.5)
        regime = compute_macro_regime(snap)
        assert regime["monetary_stance"] == "loose"

    def test_tight_m2_low(self):
        snap = MacroSnapshot(m2_yoy=7.0)
        regime = compute_macro_regime(snap)
        assert regime["monetary_stance"] == "tight"

    def test_neutral_m2_mid(self):
        snap = MacroSnapshot(m2_yoy=9.0)
        regime = compute_macro_regime(snap)
        assert regime["monetary_stance"] == "neutral"

    def test_loose_with_lpr_only(self):
        # LPR alone (no M2) → neutral (no trend data)
        snap = MacroSnapshot(interest_rate_lpr_1y=3.45)
        regime = compute_macro_regime(snap)
        assert regime["monetary_stance"] == "neutral"

    def test_unknown_when_all_none(self):
        snap = MacroSnapshot()
        regime = compute_macro_regime(snap)
        assert regime["monetary_stance"] == "unknown"


# ---------------------------------------------------------------------------
# 4. economic_momentum 判定
# ---------------------------------------------------------------------------


class TestEconomicMomentum:
    def test_expanding(self):
        snap = MacroSnapshot(pmi_manufacturing=52.0)
        regime = compute_macro_regime(snap)
        assert regime["economic_momentum"] == "expanding"

    def test_contracting(self):
        snap = MacroSnapshot(pmi_manufacturing=48.0)
        regime = compute_macro_regime(snap)
        assert regime["economic_momentum"] == "contracting"

    def test_stable(self):
        snap = MacroSnapshot(pmi_manufacturing=50.0)
        regime = compute_macro_regime(snap)
        assert regime["economic_momentum"] == "stable"

    def test_unknown_when_none(self):
        snap = MacroSnapshot()
        regime = compute_macro_regime(snap)
        assert regime["economic_momentum"] == "unknown"


# ---------------------------------------------------------------------------
# 5. PMI 边界值
# ---------------------------------------------------------------------------


class TestPMIBoundaries:
    @pytest.mark.parametrize(
        "pmi,expected",
        [
            (49.0, "stable"),  # 边界: 49.0 >= 49 → stable
            (49.1, "stable"),
            (50.0, "stable"),
            (50.9, "stable"),
            (51.0, "stable"),  # 51.0 不 > 51.0, 所以 stable
            (51.1, "expanding"),
            (48.9, "contracting"),
        ],
    )
    def test_pmi_boundary(self, pmi, expected):
        snap = MacroSnapshot(pmi_manufacturing=pmi)
        regime = compute_macro_regime(snap)
        assert regime["economic_momentum"] == expected


# ---------------------------------------------------------------------------
# 6. CPI 边界值
# ---------------------------------------------------------------------------


class TestCPIBoundaries:
    @pytest.mark.parametrize(
        "cpi,expected",
        [
            (0.0, "low"),
            (0.99, "low"),
            (1.0, "moderate"),  # 边界: 1.0 >= 1 → moderate
            (1.5, "moderate"),
            (2.99, "moderate"),
            (3.0, "moderate"),  # 边界: 3.0 <= 3.0 → moderate
            (3.01, "high"),
            (5.0, "high"),
        ],
    )
    def test_cpi_boundary(self, cpi, expected):
        snap = MacroSnapshot(cpi_yoy=cpi)
        regime = compute_macro_regime(snap)
        assert regime["inflation_pressure"] == expected


# ---------------------------------------------------------------------------
# 7. None 字段不影响 regime 计算
# ---------------------------------------------------------------------------


class TestNoneFieldHandling:
    def test_partial_data_cpi_only(self):
        snap = MacroSnapshot(cpi_yoy=2.5)
        regime = compute_macro_regime(snap)
        assert regime["inflation_pressure"] == "moderate"
        assert regime["monetary_stance"] == "unknown"
        assert regime["economic_momentum"] == "unknown"
        assert "summary" in regime

    def test_partial_data_pmi_and_m2(self):
        snap = MacroSnapshot(pmi_manufacturing=53.0, m2_yoy=11.0)
        regime = compute_macro_regime(snap)
        assert regime["inflation_pressure"] == "unknown"
        assert regime["monetary_stance"] == "loose"
        assert regime["economic_momentum"] == "expanding"

    def test_all_none_yields_unknown(self):
        snap = MacroSnapshot()
        regime = compute_macro_regime(snap)
        assert regime["inflation_pressure"] == "unknown"
        assert regime["monetary_stance"] == "unknown"
        assert regime["economic_momentum"] == "unknown"

    def test_regime_summary_present(self):
        snap = MacroSnapshot(cpi_yoy=2.0, m2_yoy=9.5, pmi_manufacturing=50.5)
        regime = compute_macro_regime(snap)
        assert "summary" in regime
        assert "温和" in regime["summary"]
        assert "中性" in regime["summary"]
        assert "平稳" in regime["summary"]


# ---------------------------------------------------------------------------
# 8. render 输出
# ---------------------------------------------------------------------------


class TestRenderOutput:
    def test_full_data_render(self):
        snap = MacroSnapshot(
            date="202605",
            cpi_yoy=2.1,
            ppi_yoy=-1.2,
            pmi_manufacturing=50.8,
            pmi_non_manufacturing=53.2,
            m2_yoy=10.5,
            social_financing=22000.0,
            interest_rate_lpr_1y=3.45,
        )
        regime = compute_macro_regime(snap)
        output = render_macro_snapshot(snap, regime)
        assert "宏观经济面板" in output
        assert "CPI: 2.1%" in output
        assert "PPI: -1.2%" in output
        assert "PMI 制造业: 50.8" in output
        assert "PMI 非制造业: 53.2" in output
        assert "M2: 10.5%" in output
        assert "社融: 22000亿" in output
        assert "LPR 1Y: 3.45%" in output
        assert "温和" in output
        assert "宽松" in output
        assert "平稳" in output

    def test_none_data_render_dashes(self):
        snap = MacroSnapshot()
        regime = compute_macro_regime(snap)
        output = render_macro_snapshot(snap, regime)
        assert "CPI: —" in output
        assert "PPI: —" in output
        assert "PMI 制造业: —" in output
        assert "M2: —" in output
        assert "LPR 1Y: —" in output

    def test_render_partial_data(self):
        snap = MacroSnapshot(cpi_yoy=0.8, pmi_manufacturing=48.5)
        regime = compute_macro_regime(snap)
        output = render_macro_snapshot(snap, regime)
        assert "CPI: 0.8%" in output
        assert "低通胀" in output
        assert "收缩" in output


# ---------------------------------------------------------------------------
# 9. CLI smoke test (mock tushare)
# ---------------------------------------------------------------------------


class TestCLISmoke:
    @patch("src.data.macro_data._get_pro")
    def test_cli_no_tushare_returns_1(self, mock_get_pro, capsys):
        """tushare 不可用时返回 1 但不崩溃。"""
        mock_get_pro.return_value = None
        rc = run_macro_cli()
        assert rc == 1
        captured = capsys.readouterr()
        assert "不可用" in captured.out or "数据获取失败" in captured.out or "失败" in captured.out

    @patch("src.data.macro_data._get_pro")
    def test_cli_with_mock_data_returns_0(self, mock_get_pro, capsys):
        """mock tushare 返回 CPI 数据时 CLI 正常输出。"""
        import pandas as pd

        mock_pro = MagicMock()
        mock_get_pro.return_value = mock_pro

        # Mock _cached_tushare_dataframe_call to return minimal DataFrames
        cpi_df = pd.DataFrame({"month": ["202605"], "nt_yoy": [2.1]})
        ppi_df = pd.DataFrame({"month": ["202605"], "yoy": [-1.2]})

        call_count = [0]

        def mock_cached_call(pro, api_name, **kwargs):
            call_count[0] += 1
            if api_name == "cn_cpi":
                return cpi_df
            if api_name == "cn_ppi":
                return ppi_df
            return None  # 其他接口返回 None

        with patch("src.data.macro_data._cached_tushare_dataframe_call", side_effect=mock_cached_call):
            rc = run_macro_cli()

        assert rc == 0
        captured = capsys.readouterr()
        assert "宏观经济面板" in captured.out
        assert "CPI: 2.1%" in captured.out

    @patch("src.data.macro_data._get_pro")
    def test_cli_all_none_data_returns_1(self, mock_get_pro, capsys):
        """所有接口返回 None 时 CLI 返回 1。"""
        mock_pro = MagicMock()
        mock_get_pro.return_value = mock_pro

        with patch("src.data.macro_data._cached_tushare_dataframe_call", return_value=None):
            rc = run_macro_cli()

        assert rc == 1


# ---------------------------------------------------------------------------
# 10. 缓存命中/未命中
# ---------------------------------------------------------------------------


class TestCacheBehavior:
    @patch("src.data.macro_data._get_pro")
    def test_fetch_calls_cached_dataframe_call(self, mock_get_pro):
        """验证 fetch_macro_snapshot 使用 _cached_tushare_dataframe_call。"""
        mock_pro = MagicMock()
        mock_get_pro.return_value = mock_pro

        with patch("src.data.macro_data._cached_tushare_dataframe_call", return_value=None) as mock_call:
            snap = fetch_macro_snapshot()
            # 应该为每个指标调用一次 (CPI, PPI, PMI, M2, SF, LPR)
            assert mock_call.call_count >= 6
            # 所有字段为 None
            assert snap.cpi_yoy is None
            assert snap.ppi_yoy is None

    @patch("src.data.macro_data._get_pro")
    def test_fetch_with_cpi_data(self, mock_get_pro):
        """CPI 数据可用时正确解析。"""
        import pandas as pd

        mock_pro = MagicMock()
        mock_get_pro.return_value = mock_pro

        cpi_df = pd.DataFrame({"month": ["202605", "202604"], "nt_yoy": [2.1, 1.8]})

        def mock_cached_call(pro, api_name, **kwargs):
            if api_name == "cn_cpi":
                return cpi_df
            return None

        with patch("src.data.macro_data._cached_tushare_dataframe_call", side_effect=mock_cached_call):
            snap = fetch_macro_snapshot()

        assert snap.cpi_yoy == 2.1  # 取最新月份
        assert snap.date == "202605"

    @patch("src.data.macro_data._get_pro")
    def test_fetch_no_tushare_returns_empty_snapshot(self, mock_get_pro):
        """tushare 不可用时返回空快照。"""
        mock_get_pro.return_value = None
        snap = fetch_macro_snapshot()
        assert snap.cpi_yoy is None
        assert snap.pmi_manufacturing is None
        assert snap.date == ""

    @patch("src.data.macro_data._get_pro")
    def test_fetch_handles_exception_gracefully(self, mock_get_pro):
        """单个接口异常不影响其他指标。"""
        import pandas as pd

        mock_pro = MagicMock()
        mock_get_pro.return_value = mock_pro

        cpi_df = pd.DataFrame({"month": ["202605"], "nt_yoy": [1.5]})
        call_count = [0]

        def mock_cached_call(pro, api_name, **kwargs):
            call_count[0] += 1
            if api_name == "cn_cpi":
                return cpi_df
            if api_name == "cn_ppi":
                raise RuntimeError("ppi 接口异常")
            return None

        with patch("src.data.macro_data._cached_tushare_dataframe_call", side_effect=mock_cached_call):
            snap = fetch_macro_snapshot()

        # CPI 应该成功
        assert snap.cpi_yoy == 1.5
        # PPI 应该为 None (不崩溃)
        assert snap.ppi_yoy is None


# ---------------------------------------------------------------------------
# 11. R16 BUG — _extract_latest_pmi 未知列名不崩溃
# ---------------------------------------------------------------------------


class TestExtractLatestPMIEdgeCases:
    """R16: _extract_latest_pmi 应安全处理不认识的列名。"""

    @patch("src.data.macro_data._get_pro")
    def test_pmi_with_unexpected_columns(self, mock_get_pro):
        """PMI DataFrame 列名不匹配时返回 None, 不崩溃。"""
        import pandas as pd

        mock_pro = MagicMock()
        mock_get_pro.return_value = mock_pro

        pmi_df = pd.DataFrame({"month": ["202605", "202604"], "unknown_col": [50.0, 51.0]})

        def mock_cached_call(pro, api_name, **kwargs):
            if api_name == "cn_pmi":
                return pmi_df
            return None

        with patch("src.data.macro_data._cached_tushare_dataframe_call", side_effect=mock_cached_call):
            snap = fetch_macro_snapshot()

        # PMI 字段应为 None (列名不匹配), 不崩溃
        assert snap.pmi_manufacturing is None
        assert snap.pmi_non_manufacturing is None

    @patch("src.data.macro_data._get_pro")
    def test_pmi_with_standard_columns(self, mock_get_pro):
        """PMI DataFrame 含 pmi_make / pmi_service 时正确解析。"""
        import pandas as pd

        mock_pro = MagicMock()
        mock_get_pro.return_value = mock_pro

        pmi_df = pd.DataFrame(
            {
                "month": ["202605", "202604"],
                "pmi_make": [50.8, 49.5],
                "pmi_service": [53.2, 52.1],
            }
        )

        def mock_cached_call(pro, api_name, **kwargs):
            if api_name == "cn_pmi":
                return pmi_df
            return None

        with patch("src.data.macro_data._cached_tushare_dataframe_call", side_effect=mock_cached_call):
            snap = fetch_macro_snapshot()

        assert snap.pmi_manufacturing == 50.8
        assert snap.pmi_non_manufacturing == 53.2


# ---------------------------------------------------------------------------
# 12. R40 — as_of point-in-time filter (no look-ahead in backtest/replay)
# ---------------------------------------------------------------------------


class TestFetchMacroSnapshotAsOf:
    """R40: ``fetch_macro_snapshot(as_of=...)`` must exclude macro readings whose
    reporting period is later than the as_of anchor. Without this filter, a
    backtest/replay reading the macro panel on e.g. 2026-03-01 would see the
    April 2026 CPI (released mid-April), a point-in-time look-ahead.

    Although the regime label is informational-only today (no decision consumes
    it), the filter removes the latent look-ahead so the panel can never show
    future data once a backtest consumer is wired in."""

    @patch("src.data.macro_data._get_pro")
    def test_as_of_excludes_future_months(self, mock_get_pro):
        """CPI for months 202603/202604/202605 available; as_of=2026-04-15 must
        return the 202604 reading (the latest month <= as_of), never 202605."""
        import pandas as pd

        mock_pro = MagicMock()
        mock_get_pro.return_value = mock_pro

        cpi_df = pd.DataFrame(
            {
                "month": ["202603", "202604", "202605"],
                "nt_yoy": [1.5, 2.1, 3.0],
            }
        )

        with patch("src.data.macro_data._cached_tushare_dataframe_call", side_effect=lambda pro, api_name, **kw: cpi_df if api_name == "cn_cpi" else None):
            snap = fetch_macro_snapshot(as_of="2026-04-15")

        # 202605 is future relative to 2026-04-15 → must be excluded
        assert snap.cpi_yoy == 2.1, f"expected 2.1 (202604), got {snap.cpi_yoy}"
        assert snap.date == "202604"

    @patch("src.data.macro_data._get_pro")
    def test_as_of_none_returns_latest_default_behavior(self, mock_get_pro):
        """as_of=None (default) preserves the original 'latest' behavior so live
        runs are unaffected — R40 must not change the default path."""
        import pandas as pd

        mock_pro = MagicMock()
        mock_get_pro.return_value = mock_pro

        cpi_df = pd.DataFrame(
            {
                "month": ["202603", "202604", "202605"],
                "nt_yoy": [1.5, 2.1, 3.0],
            }
        )

        with patch("src.data.macro_data._cached_tushare_dataframe_call", side_effect=lambda pro, api_name, **kw: cpi_df if api_name == "cn_cpi" else None):
            snap = fetch_macro_snapshot()

        assert snap.cpi_yoy == 3.0, f"default path must return latest (202605=3.0), got {snap.cpi_yoy}"

    @patch("src.data.macro_data._get_pro")
    def test_as_of_before_all_data_returns_none(self, mock_get_pro):
        """If as_of predates all available months, no CPI is point-in-time
        available → cpi_yoy must be None (not a future value)."""
        import pandas as pd

        mock_pro = MagicMock()
        mock_get_pro.return_value = mock_pro

        cpi_df = pd.DataFrame({"month": ["202603", "202604"], "nt_yoy": [1.5, 2.1]})

        with patch("src.data.macro_data._cached_tushare_dataframe_call", side_effect=lambda pro, api_name, **kw: cpi_df if api_name == "cn_cpi" else None):
            snap = fetch_macro_snapshot(as_of="2026-01-01")

        assert snap.cpi_yoy is None
