"""Tests for src.screening.regime_winrate — R-5.A 按 regime 展示真实历史胜率。

R-5.A: 在 --top-picks footer 按 current regime 展示真实历史 T+30 胜率。
真实回测 (2026-06-24, 91 只真实推荐) 证明: crisis regime (结构性行情, 广度弱)
真实胜率 73% +8%, normal regime (广度强震荡市) 胜率 24% -9%。这让用户看到
当前 regime 的真实期望, 自己决定是否信任推荐 (零行为改变, 只展示)。
"""
from __future__ import annotations

import pytest

from src.screening.regime_winrate import (
    compute_regime_winrate_summary,
    render_regime_winrate_line,
    REGIME_HISTORICAL_WINRATES,
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
