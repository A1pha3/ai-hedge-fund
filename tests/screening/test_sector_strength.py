"""Tests for src/screening/sector_strength.py — P10-2 Sector Strength."""

from __future__ import annotations

import pytest

from src.screening.sector_strength import (
    SectorStrengthInfo,
    SectorStrengthReport,
    _build_sector_lookup,
    _strength_label_colored,
    render_sector_strength,
)
from src.screening.industry_rotation import IndustrySignal
from src.utils.display import Fore, Style


# ---------------------------------------------------------------------------
# _build_sector_lookup
# ---------------------------------------------------------------------------


class TestBuildSectorLookup:
    def test_empty_signals(self) -> None:
        assert _build_sector_lookup([]) == {}

    def test_single_signal(self) -> None:
        signals = [IndustrySignal(industry_name="电子", momentum_score=0.5, rank=1)]
        lookup = _build_sector_lookup(signals)
        assert "电子" in lookup
        momentum, rank, total = lookup["电子"]
        assert momentum == 0.5
        assert rank == 1
        assert total == 1

    def test_multiple_signals(self) -> None:
        signals = [
            IndustrySignal(industry_name="电子", momentum_score=0.5, rank=1),
            IndustrySignal(industry_name="银行", momentum_score=0.2, rank=2),
            IndustrySignal(industry_name="地产", momentum_score=-0.3, rank=3),
        ]
        lookup = _build_sector_lookup(signals)
        assert len(lookup) == 3
        assert lookup["银行"] == (0.2, 2, 3)
        assert lookup["地产"] == (-0.3, 3, 3)


# ---------------------------------------------------------------------------
# SectorStrengthInfo / SectorStrengthReport
# ---------------------------------------------------------------------------


class TestSectorStrengthInfo:
    def test_defaults(self) -> None:
        info = SectorStrengthInfo(ticker="000001")
        assert info.industry == ""
        assert info.strength_label == "neutral"
        assert info.strength_bonus == 0.0


class TestSectorStrengthReport:
    def test_empty(self) -> None:
        report = SectorStrengthReport()
        assert report.items == []
        assert report.strong_sectors == []

    def test_to_dict(self) -> None:
        report = SectorStrengthReport(
            trade_date="2026-01-01",
            strong_sectors=["电子"],
            weak_sectors=["地产"],
            items=[
                SectorStrengthInfo(
                    ticker="000001",
                    industry="电子",
                    strength_bonus=0.05,
                    strength_label="strong",
                ),
            ],
        )
        d = report.to_dict()
        assert d["strong_sectors"] == ["电子"]
        assert d["items"][0]["strength_label"] == "strong"


# ---------------------------------------------------------------------------
# render_sector_strength
# ---------------------------------------------------------------------------


class TestRenderSectorStrength:
    def test_empty(self) -> None:
        result = render_sector_strength(SectorStrengthReport())
        assert "无推荐数据" in result

    def test_with_items(self) -> None:
        report = SectorStrengthReport(
            trade_date="2026-01-01",
            strong_sectors=["电子"],
            weak_sectors=["地产"],
            items=[
                SectorStrengthInfo(ticker="000001", name="平安", industry="电子", strength_label="strong", strength_bonus=0.05),
            ],
        )
        result = render_sector_strength(report)
        assert "000001" in result
        assert "行业动量" in result


# ---------------------------------------------------------------------------
# compute_sector_strength (end-to-end, no report files → empty)
# ---------------------------------------------------------------------------


class TestComputeSectorStrength:
    def test_no_reports_returns_empty(self, tmp_path) -> None:
        from src.screening.sector_strength import compute_sector_strength

        report = compute_sector_strength(reports_dir=tmp_path)
        assert report.items == []


# ---------------------------------------------------------------------------
# _strength_label_colored (imported but never directly tested)
# ---------------------------------------------------------------------------


class TestStrengthLabelColored:
    """_strength_label_colored — color-code a sector strength label."""

    def test_strong_green(self) -> None:
        result = _strength_label_colored("strong")
        assert result.startswith(Fore.GREEN)
        assert "强" in result

    def test_weak_red(self) -> None:
        result = _strength_label_colored("weak")
        assert result.startswith(Fore.RED)
        assert "弱" in result

    def test_neutral_white(self) -> None:
        result = _strength_label_colored("neutral")
        assert result.startswith(Fore.WHITE)
        assert "中性" in result

    def test_unknown_label_white_neutral(self) -> None:
        result = _strength_label_colored("bogus")
        assert result.startswith(Fore.WHITE)
        assert "中性" in result

    def test_ends_with_reset(self) -> None:
        assert _strength_label_colored("strong").endswith(Style.RESET_ALL)
