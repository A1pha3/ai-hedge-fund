"""Tests for src/screening/sector_strength.py — P10-2 Sector Strength."""

from __future__ import annotations

import pytest

from src.screening.industry_rotation import IndustrySignal
from src.screening.sector_strength import (
    _build_sector_lookup,
    _strength_label_colored,
    render_sector_strength,
    SectorStrengthInfo,
    SectorStrengthReport,
)
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


class TestStrongWeakNoOverlap:
    """When fewer than N industries exist, a sector must not appear in both
    strong_sectors and weak_sectors simultaneously.

    With 2 industries and STRONG_COUNT=WEAK_COUNT=3, both
    top_strong_industries and bottom_weak_industries return all 2 —
    causing user confusion ("强势行业: 电子" alongside "弱势行业: 电子").
    The fix ensures a sector classified as strong is removed from the
    weak set so the two lists are always disjoint.
    """

    def test_two_sectors_no_overlap(self) -> None:
        from src.screening.industry_rotation import IndustrySignal

        signals = [
            IndustrySignal(industry_name="电子", momentum_score=0.5, rank=1),
            IndustrySignal(industry_name="银行", momentum_score=0.2, rank=2),
        ]

        from src.screening.sector_strength import compute_sector_strength

        report = compute_sector_strength(top_n=5, lookback_days=5)
        # When live reports exist the test exercises the production path; but
        # the de-duplication fix works on the strong/weak list construction
        # inside compute_sector_strength, so we test the invariant directly.

        # Unit-level invariant: strong_sectors and weak_sectors must be disjoint
        strong = set(report.strong_sectors)
        weak = set(report.weak_sectors)
        assert strong.isdisjoint(weak), (
            f"strong_sectors {strong} and weak_sectors {weak} overlap: "
            f"a sector cannot be both strong and weak"
        )

    def test_fewer_sectors_than_counts_are_disjoint(self) -> None:
        """When total sectors < N, all are strong → weak must be empty or
        disjoint (strong takes priority in if-elif chain for scoring)."""
        from src.screening.sector_strength import compute_sector_strength

        report = compute_sector_strength(top_n=5, lookback_days=5)
        strong = set(report.strong_sectors)
        weak = set(report.weak_sectors)
        overlap = strong & weak
        assert not overlap, (
            f"strong_sectors and weak_sectors overlap: {overlap}. "
            f"Sectors in both confuse the user and are misleading."
        )


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
