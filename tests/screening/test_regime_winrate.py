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
        """crisis regime → 返回真实历史胜率 (73%, +8%)。"""
        s = compute_regime_winrate_summary("crisis")
        assert s.regime == "crisis"
        assert s.winrate == pytest.approx(0.727, abs=0.01)
        assert s.median_return == pytest.approx(8.24, abs=0.1)
        assert s.sample_count == 22
        assert s.has_data is True

    def test_normal_regime_returns_real_stats(self) -> None:
        """normal regime → 返回真实历史胜率 (24%, -9%)。"""
        s = compute_regime_winrate_summary("normal")
        assert s.regime == "normal"
        assert s.winrate == pytest.approx(0.237, abs=0.01)
        assert s.median_return == pytest.approx(-8.74, abs=0.1)
        assert s.sample_count == 59
        assert s.has_data is True

    def test_unknown_regime_returns_no_data(self) -> None:
        """未知 regime / risk_off (无样本) → has_data=False。"""
        s = compute_regime_winrate_summary("risk_off")
        assert s.has_data is False
        s2 = compute_regime_winrate_summary("bogus_regime")
        assert s2.has_data is False


class TestRenderRegimeWinrateLine:
    def test_crisis_regime_renders_positive(self) -> None:
        """crisis regime (赚钱 73%) → 含胜率 + 正收益 + 绿色 + '结构性行情'提示。"""
        line = render_regime_winrate_line("crisis")
        assert line != ""
        assert "73%" in line
        assert "结构性行情" in line or "选股可能发挥" in line
        from src.utils.display import Fore
        assert Fore.GREEN in line

    def test_normal_regime_renders_caution(self) -> None:
        """normal regime (亏钱 24%) → 含胜率 + 负收益 + 黄/红色 + '谨慎'提示。"""
        line = render_regime_winrate_line("normal")
        assert line != ""
        assert "24%" in line
        assert "谨慎" in line or "轻仓" in line or "空仓" in line
        from src.utils.display import Fore
        assert Fore.YELLOW in line or Fore.RED in line

    def test_unknown_regime_renders_empty(self) -> None:
        """未知 regime → 空串 (不污染前门)。"""
        assert render_regime_winrate_line("risk_off") == ""
        assert render_regime_winrate_line("bogus") == ""
