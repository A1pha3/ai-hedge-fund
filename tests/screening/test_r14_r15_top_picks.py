"""Tests for R14 (sector rotation direction) and R15 (factor attribution) in top_picks."""
from __future__ import annotations

from src.screening.top_picks import (
    _build_industry_momentum_map,
    _collect_pick_industries,
    _momentum_arrow,
    _render_sector_rotation,
    _render_factor_attribution,
)
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


class TestMomentumArrow:
    """R14 helper: map momentum score to display arrow."""

    def test_positive_above_threshold(self) -> None:
        """score > 20 → green ↗."""
        result = _momentum_arrow(25.0)
        assert "↗" in result
        assert Fore.GREEN in result

    def test_negative_below_threshold(self) -> None:
        """score < -20 → red ↘."""
        result = _momentum_arrow(-25.0)
        assert "↘" in result
        assert Fore.RED in result

    def test_neutral_middle(self) -> None:
        """-20 <= score <= 20 → white →."""
        result = _momentum_arrow(0.0)
        assert "→" in result
        assert Fore.WHITE in result

    def test_boundary_positive(self) -> None:
        """score == 20 is NOT > 20, so neutral →."""
        assert "→" in _momentum_arrow(20.0)

    def test_boundary_negative(self) -> None:
        """score == -20 is NOT < -20, so neutral →."""
        assert "→" in _momentum_arrow(-20.0)


class TestCollectPickIndustries:
    """R14 helper: extract valid industries from picks."""

    def test_normal_picks(self) -> None:
        picks = [{"industry_sw": "电子"}, {"industry_sw": "医药"}]
        assert _collect_pick_industries(picks) == ["电子", "医药"]

    def test_empty_and_unknown_excluded(self) -> None:
        picks = [{"industry_sw": "电子"}, {"industry_sw": ""}, {"industry_sw": "未知"}]
        assert _collect_pick_industries(picks) == ["电子"]

    def test_missing_key_treated_as_unknown(self) -> None:
        picks = [{"industry_sw": "电子"}, {}]
        assert _collect_pick_industries(picks) == ["电子"]

    def test_empty_picks(self) -> None:
        assert _collect_pick_industries([]) == []


class TestBuildIndustryMomentumMap:
    """R14 helper: normalize rotation payload to {industry: momentum}."""

    def test_normal_list(self) -> None:
        signals = [
            {"industry_name": "电子", "momentum_score": 0.85},
            {"industry_name": "医药", "momentum_score": -0.3},
        ]
        result = _build_industry_momentum_map(signals)
        assert result == {"电子": 0.85, "医药": -0.3}

    def test_non_list_returns_empty(self) -> None:
        assert _build_industry_momentum_map(None) == {}
        assert _build_industry_momentum_map({}) == {}

    def test_non_dict_signal_skipped(self) -> None:
        signals = [{"industry_name": "电子", "momentum_score": 0.5}, "bad", 42]
        assert _build_industry_momentum_map(signals) == {"电子": 0.5}

    def test_empty_name_skipped(self) -> None:
        signals = [{"industry_name": "", "momentum_score": 0.5}, {"industry_name": "  ", "momentum_score": 0.3}]
        assert _build_industry_momentum_map(signals) == {}

    def test_missing_score_defaults_zero(self) -> None:
        signals = [{"industry_name": "电子"}]
        assert _build_industry_momentum_map(signals) == {"电子": 0.0}
