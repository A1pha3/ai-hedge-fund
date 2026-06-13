"""Tests for R14 (sector rotation direction) and R15 (factor attribution) in top_picks."""
from __future__ import annotations

from src.screening.top_picks import _render_sector_rotation, _render_factor_attribution
from src.utils.display import Fore, Style


class TestR14SectorRotation:
    """R14: 行业轮动方向展示。"""

    def test_no_rotation_data(self) -> None:
        """Empty report data returns empty string."""
        result = _render_sector_rotation({}, [{"industry_sw": "电子"}])
        assert result == ""

    def test_rotation_with_positive_momentum(self) -> None:
        """Industry with momentum > 20 shows green arrow."""
        report = {
            "industry_rotation": [
                {"industry_name": "电子", "momentum_score": 45.0},
                {"industry_name": "医药", "momentum_score": -30.0},
            ]
        }
        picks = [
            {"industry_sw": "电子"},
            {"industry_sw": "电子"},
            {"industry_sw": "医药"},
            {"industry_sw": "医药"},
        ]
        result = _render_sector_rotation(report, picks)
        assert "电子" in result
        assert "医药" in result
        assert Fore.GREEN in result  # ↗ for positive
        assert Fore.RED in result  # ↘ for negative

    def test_rotation_stable(self) -> None:
        """Industry with momentum between -20 and 20 shows stable arrow."""
        report = {
            "industry_rotation": [
                {"industry_name": "银行", "momentum_score": 5.0},
            ]
        }
        picks = [{"industry_sw": "银行"}, {"industry_sw": "银行"}]
        result = _render_sector_rotation(report, picks)
        assert "银行" in result
        assert Fore.WHITE in result  # → for stable

    def test_rotation_missing_industry(self) -> None:
        """Industry not in rotation data is skipped."""
        report = {
            "industry_rotation": [
                {"industry_name": "电子", "momentum_score": 30.0},
            ]
        }
        picks = [{"industry_sw": "医药"}, {"industry_sw": "医药"}]
        result = _render_sector_rotation(report, picks)
        assert result == ""  # 医药 not in rotation data

    def test_rotation_no_picks_industry(self) -> None:
        """No valid industries in picks returns empty."""
        report = {
            "industry_rotation": [
                {"industry_name": "电子", "momentum_score": 30.0},
            ]
        }
        picks = [{"industry_sw": ""}, {"industry_sw": "未知"}]
        result = _render_sector_rotation(report, picks)
        assert result == ""


class TestR15FactorAttribution:
    """R15: 因子贡献归因展示。"""

    def test_no_signals(self) -> None:
        """No strategy_signals returns empty string."""
        result = _render_factor_attribution({})
        assert result == ""

    def test_single_positive_factor(self) -> None:
        """Single positive factor shows as top contributor."""
        item = {
            "strategy_signals": {
                "trend": {"direction": 1, "confidence": 80},
                "mean_reversion": {"direction": 0, "confidence": 50},
            }
        }
        result = _render_factor_attribution(item)
        assert "趋势↑" in result
        assert "主因" in result

    def test_two_positive_factors(self) -> None:
        """Two positive factors both shown."""
        item = {
            "strategy_signals": {
                "trend": {"direction": 1, "confidence": 90},
                "mean_reversion": {"direction": 1, "confidence": 70},
            }
        }
        result = _render_factor_attribution(item)
        assert "趋势↑" in result
        assert "反转↑" in result

    def test_negative_factor(self) -> None:
        """Negative factor shows down arrow."""
        item = {
            "strategy_signals": {
                "fundamental": {"direction": -1, "confidence": 60},
            }
        }
        result = _render_factor_attribution(item)
        assert "基本面↓" in result

    def test_top_2_by_strength(self) -> None:
        """Only top 2 strongest factors shown."""
        item = {
            "strategy_signals": {
                "trend": {"direction": 1, "confidence": 90},
                "mean_reversion": {"direction": 1, "confidence": 80},
                "fundamental": {"direction": 1, "confidence": 10},
            }
        }
        result = _render_factor_attribution(item)
        assert "趋势↑" in result
        assert "反转↑" in result
        # 基本面 has lowest strength (1*10=10), should not appear
        assert "基本面" not in result

    def test_all_zero_direction(self) -> None:
        """All zero directions returns empty."""
        item = {
            "strategy_signals": {
                "trend": {"direction": 0, "confidence": 50},
                "mean_reversion": {"direction": 0, "confidence": 50},
            }
        }
        result = _render_factor_attribution(item)
        assert result == ""
