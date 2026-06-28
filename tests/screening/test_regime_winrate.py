"""Tests for src.screening.regime_winrate — R-5.A 按 regime 展示真实历史胜率。

R-5.A: 在 --top-picks footer 按 current regime 展示真实历史 T+30 胜率。
真实回测 (2026-06-24, 91 只真实推荐) 证明: crisis regime (结构性行情, 广度弱)
真实胜率 73% +8%, normal regime (广度强震荡市) 胜率 24% -9%。这让用户看到
当前 regime 的真实期望, 自己决定是否信任推荐 (零行为改变, 只展示)。

R-5.A 多周期扩展: 2026-06-25 基于 Phase 1 多周期数据 (T+5/10/15/20/25/30),
额外披露各 horizon 的 median return, 让用户看到中长周期是否比 T+30 更优。

NS-5 (C234, 2026-06-28): 加 as_of 字段 (数据时点标注) + staleness 检测 (⚠ 距今
>14 天提示数据可能过时). C220 BUY gate horizon T+30→T+5/T+10 后, 当前 T+30
硬编码数据已 stale, 但重算需新模型累积 ≥10 交易日 mature 数据 — 当前只做诚实
披露 (as_of + ⚠), 不假装重算. daily scheduling 重算脚本待数据 mature 后再加.
"""
from __future__ import annotations

from datetime import date

import pytest

from src.screening.regime_winrate import (
    compute_regime_winrate_summary,
    render_regime_winrate_line,
    render_regime_multihorizon_line,
    REGIME_MULTIHORIZON_MEDIANS,
)


class TestComputeRegimeWinrateSummary:
    def test_known_regime_returns_real_stats(self) -> None:
        """crisis regime → 返回扩充后真实历史胜率 (~47%, median -0.93%)。"""
        s = compute_regime_winrate_summary("crisis")
        assert s.regime == "crisis"
        assert s.winrate == pytest.approx(0.468, abs=0.01)
        assert s.median_return == pytest.approx(-0.93, abs=0.1)
        assert s.sample_count >= 100  # 扩充后 ~119
        assert s.has_data is True

    def test_normal_regime_returns_real_stats(self) -> None:
        """normal regime → 返回扩充后真实历史胜率 (~43%, median -4.37%)。"""
        s = compute_regime_winrate_summary("normal")
        assert s.regime == "normal"
        assert s.winrate == pytest.approx(0.434, abs=0.01)
        assert s.median_return == pytest.approx(-4.37, abs=0.1)
        assert s.sample_count >= 50  # 扩充后 ~60
        assert s.has_data is True

    def test_risk_off_regime_now_has_data(self) -> None:
        """risk_off regime → 扩充后有样本 (~30%, median -5.12%)。"""
        s = compute_regime_winrate_summary("risk_off")
        assert s.has_data is True
        assert s.winrate == pytest.approx(0.30, abs=0.02)
        assert s.sample_count >= 10

    def test_unknown_regime_returns_no_data(self) -> None:
        """未知 regime → has_data=False。"""
        s2 = compute_regime_winrate_summary("bogus_regime")
        assert s2.has_data is False


class TestRenderRegimeWinrateLine:
    def test_crisis_regime_renders(self) -> None:
        """crisis regime (~47%) → 含胜率 + 样本数 + 颜色 (黄, 因 30-50%)。"""
        line = render_regime_winrate_line("crisis")
        assert line != ""
        assert "47%" in line
        from src.utils.display import Fore
        # 47% 落在 30-50% → 黄色
        assert Fore.YELLOW in line

    def test_normal_regime_renders(self) -> None:
        """normal regime (~43%) → 含胜率 + 谨慎提示 + 黄色。"""
        line = render_regime_winrate_line("normal")
        assert line != ""
        assert "43%" in line
        assert "谨慎" in line
        from src.utils.display import Fore
        assert Fore.YELLOW in line

    def test_risk_off_regime_renders_caution(self) -> None:
        """risk_off regime (~30%, 三 regime 中最差) → 含胜率 + 空仓/轻仓提示。"""
        line = render_regime_winrate_line("risk_off")
        assert line != ""
        assert "30%" in line
        # risk_off 最差 → 应有强谨慎语义
        assert "空仓" in line or "轻仓" in line or "弱势" in line

    def test_unknown_regime_renders_empty(self) -> None:
        """未知 regime → 空串 (不污染前门)。"""
        assert render_regime_winrate_line("bogus") == ""


# ---------------------------------------------------------------------------
# R-5.A 多周期扩展
# ---------------------------------------------------------------------------


class TestRegimeMultihorizonMedians:
    """REGIME_MULTIHORIZON_MEDIANS — per-regime multi-horizon median data."""

    def test_crisis_regime_has_all_6_horizons(self) -> None:
        data = REGIME_MULTIHORIZON_MEDIANS.get("crisis", {})
        for h in ("t5", "t10", "t15", "t20", "t25", "t30"):
            assert h in data, f"crisis 缺 horizon {h}"
            assert "median" in data[h]
            assert data[h]["n"] > 100  # crisis 样本最大

    def test_normal_regime_has_all_6_horizons(self) -> None:
        data = REGIME_MULTIHORIZON_MEDIANS.get("normal", {})
        for h in ("t5", "t10", "t15", "t20", "t25", "t30"):
            assert h in data, f"normal 缺 horizon {h}"
            assert "median" in data[h]
            assert data[h]["n"] >= 80

    def test_risk_off_regime_has_all_6_horizons(self) -> None:
        data = REGIME_MULTIHORIZON_MEDIANS.get("risk_off", {})
        for h in ("t5", "t10", "t15", "t20", "t25", "t30"):
            assert h in data, f"risk_off 缺 horizon {h}"
            assert "median" in data[h]
            assert data[h]["n"] >= 10  # risk_off 样本小


class TestRenderRegimeMultihorizonLine:
    """render_regime_multihorizon_line — 渲染一行多周期 median 速览."""

    def test_crisis_renders_t20_t25_positive(self) -> None:
        """crisis regime: T+20/T+25 median 为正 → 展示 + 绿色。"""
        line = render_regime_multihorizon_line("crisis")
        assert line != ""
        # T+20 median +0.8% / T+25 +1.5% — should be shown in green
        assert "T+20" in line or "T+25" in line
        # 有正 median → green
        from src.utils.display import Fore
        assert Fore.GREEN in line

    def test_normal_renders_caution(self) -> None:
        """normal regime: 所有 horizon median 都负 → 谨慎展示。"""
        line = render_regime_multihorizon_line("normal")
        assert line != ""
        # normal 所有 median < 0 → yellow caution
        from src.utils.display import Fore
        assert Fore.YELLOW in line

    def test_risk_off_renders_caution_color(self) -> None:
        """risk_off regime: 所有 median 都负 → 黄色 + 含 n=20 小样本提示。"""
        line = render_regime_multihorizon_line("risk_off")
        assert line != ""
        # 所有 median 都负 → 黄色
        from src.utils.display import Fore
        assert Fore.YELLOW in line
        # 诚实披露 n=20 小样本
        assert "n=20" in line

    def test_unknown_regime_renders_empty(self) -> None:
        """未知 regime → 空串。"""
        assert render_regime_multihorizon_line("bogus") == ""

    def test_includes_sample_count_in_hint(self) -> None:
        """渲染结果应包含 n= 样本数提示 (诚实披露小样本风险)。"""
        line = render_regime_multihorizon_line("crisis")
        assert "n=" in line


# ---------------------------------------------------------------------------
# NS-5 (C234, 2026-06-28): as_of 数据时点标注 + staleness 检测
# ---------------------------------------------------------------------------


class TestRegimeWinrateAsOf:
    """NS-5: RegimeWinrateSummary 加 as_of 字段 (数据时点标注)."""

    def test_known_regime_summary_has_as_of_date(self) -> None:
        """crisis regime → summary.as_of 是 date 实例 (非 None)."""
        from src.screening.regime_winrate import REGIME_HISTORICAL_DATA_AS_OF

        s = compute_regime_winrate_summary("crisis")
        assert s.has_data is True
        assert s.as_of is not None
        assert isinstance(s.as_of, date)
        assert s.as_of == REGIME_HISTORICAL_DATA_AS_OF

    def test_normal_regime_summary_has_as_of_date(self) -> None:
        """normal regime → summary.as_of 同样填充."""
        s = compute_regime_winrate_summary("normal")
        assert s.has_data is True
        assert s.as_of is not None
        assert isinstance(s.as_of, date)

    def test_unknown_regime_has_no_as_of(self) -> None:
        """未知 regime → has_data=False → as_of=None (不应有时点)."""
        s = compute_regime_winrate_summary("bogus")
        assert s.has_data is False
        assert s.as_of is None

    def test_data_as_of_is_june_2026(self) -> None:
        """REGIME_HISTORICAL_DATA_AS_OF 是 2026-06-25 (v2 扩样本 + 多周期扩展时点)."""
        from src.screening.regime_winrate import REGIME_HISTORICAL_DATA_AS_OF

        assert REGIME_HISTORICAL_DATA_AS_OF == date(2026, 6, 25)


class TestRegimeWinrateStaleness:
    """NS-5: staleness 检测 — as_of 距今 >14 天 → stale."""

    def test_is_stale_when_as_of_old(self) -> None:
        """as_of 距今 >14 天 → is_regime_data_stale=True."""
        from src.screening.regime_winrate import is_regime_data_stale

        old = date(2026, 6, 24)
        today = date(2026, 7, 15)  # 21 天后
        assert is_regime_data_stale(old, today=today) is True

    def test_is_not_stale_when_fresh(self) -> None:
        """as_of 距今 ≤14 天 → is_regime_data_stale=False."""
        from src.screening.regime_winrate import is_regime_data_stale

        fresh = date(2026, 7, 10)
        today = date(2026, 7, 15)  # 5 天后
        assert is_regime_data_stale(fresh, today=today) is False

    def test_boundary_14_days_not_stale(self) -> None:
        """as_of 距今 恰好 14 天 → not stale (>14 才算 stale)."""
        from src.screening.regime_winrate import is_regime_data_stale

        as_of = date(2026, 7, 1)
        today = date(2026, 7, 15)  # 恰好 14 天
        assert is_regime_data_stale(as_of, today=today) is False

    def test_boundary_15_days_is_stale(self) -> None:
        """as_of 距今 15 天 → stale (越过 14 天阈值)."""
        from src.screening.regime_winrate import is_regime_data_stale

        as_of = date(2026, 6, 30)
        today = date(2026, 7, 15)  # 15 天
        assert is_regime_data_stale(as_of, today=today) is True

    def test_none_as_of_treated_as_stale(self) -> None:
        """as_of=None → stale=True (保守: 无时点视为不可信)."""
        from src.screening.regime_winrate import is_regime_data_stale

        assert is_regime_data_stale(None, today=date(2026, 7, 15)) is True

    def test_default_threshold_is_14_days(self) -> None:
        """REGIME_STALENESS_THRESHOLD_DAYS 默认 14 天."""
        from src.screening.regime_winrate import REGIME_STALENESS_THRESHOLD_DAYS

        assert REGIME_STALENESS_THRESHOLD_DAYS == 14

    def test_custom_threshold_override(self) -> None:
        """可传 threshold_days 覆盖默认阈值 (允许更严格/宽松)."""
        from src.screening.regime_winrate import is_regime_data_stale

        as_of = date(2026, 7, 10)
        today = date(2026, 7, 15)  # 5 天
        # 默认 14 天 → not stale
        assert is_regime_data_stale(as_of, today=today) is False
        # 阈值 3 天 → stale
        assert is_regime_data_stale(as_of, today=today, threshold_days=3) is True


class TestStalenessWarningFormat:
    """NS-5: _format_staleness_warning 格式化输出."""

    def test_stale_warning_contains_warning_marker(self) -> None:
        """stale 时输出含 ⚠ 标记 + '过时'/'stale' 字样."""
        from src.screening.regime_winrate import _format_staleness_warning

        old = date(2026, 6, 24)
        today = date(2026, 7, 15)
        warning = _format_staleness_warning(old, today=today)
        assert "⚠" in warning
        assert "过时" in warning or "stale" in warning.lower()

    def test_stale_warning_contains_days_old(self) -> None:
        """stale 警告含距今天数 (让 owner 知道 stale 多久了)."""
        from src.screening.regime_winrate import _format_staleness_warning

        old = date(2026, 6, 24)
        today = date(2026, 7, 15)
        warning = _format_staleness_warning(old, today=today)
        assert "21" in warning  # 21 天

    def test_fresh_warning_is_empty(self) -> None:
        """fresh 时 warning 是空串 (不污染渲染)."""
        from src.screening.regime_winrate import _format_staleness_warning

        fresh = date(2026, 7, 10)
        today = date(2026, 7, 15)
        warning = _format_staleness_warning(fresh, today=today)
        assert warning == ""

    def test_none_as_of_warning_is_present(self) -> None:
        """as_of=None → warning 提示无时点 (而非崩溃)."""
        from src.screening.regime_winrate import _format_staleness_warning

        warning = _format_staleness_warning(None, today=date(2026, 7, 15))
        assert "⚠" in warning
        # 未知时点也算 stale
        assert "过时" in warning or "无时点" in warning or "stale" in warning.lower()


class TestRenderRegimeWinrateLineAsOf:
    """NS-5: render_regime_winrate_line 输出含数据时点 + staleness ⚠."""

    def test_render_includes_as_of_date(self) -> None:
        """渲染输出含 '数据时点' 标注 + iso 日期."""
        line = render_regime_winrate_line("crisis")
        assert "数据时点" in line
        assert "2026-06-25" in line

    def test_render_includes_stale_warning(self) -> None:
        """数据 stale 时 (today=2026-07-15, as_of=2026-06-25 → 21 天) → 含 ⚠ 提示."""
        line = render_regime_winrate_line("crisis", today=date(2026, 7, 15))
        assert "⚠" in line
        assert "过时" in line or "stale" in line.lower()

    def test_render_no_stale_warning_when_fresh(self) -> None:
        """数据 fresh 时 (today=2026-06-30, as_of=2026-06-25 → 5 天) 渲染无 ⚠."""
        line = render_regime_winrate_line("crisis", today=date(2026, 6, 30))
        # 5 天 → not stale → 无 ⚠ 过时提示
        assert "过时" not in line

    def test_render_today_defaults_to_date_today(self) -> None:
        """不传 today 时使用 date.today() (向后兼容 top_picks.py 调用)."""
        # 不传 today — 用真实 today; 主要验证不崩溃 + 含数据时点
        line = render_regime_winrate_line("crisis")
        assert "数据时点" in line


class TestRenderRegimeMultihorizonLineAsOf:
    """NS-5: render_regime_multihorizon_line 也加数据时点 + staleness ⚠."""

    def test_multihorizon_render_includes_as_of_date(self) -> None:
        """多周期渲染输出含 '数据时点' 标注."""
        line = render_regime_multihorizon_line("crisis")
        assert "数据时点" in line
        assert "2026-06-25" in line

    def test_multihorizon_render_includes_stale_warning(self) -> None:
        """数据 stale 时多周期渲染含 ⚠."""
        line = render_regime_multihorizon_line("crisis", today=date(2026, 7, 15))
        assert "⚠" in line

    def test_multihorizon_render_no_stale_warning_when_fresh(self) -> None:
        """数据 fresh 时多周期渲染无 ⚠."""
        line = render_regime_multihorizon_line("crisis", today=date(2026, 6, 30))
        assert "过时" not in line
