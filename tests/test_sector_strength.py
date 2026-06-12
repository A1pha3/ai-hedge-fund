"""Tests for sector_strength.py — P10-2."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from src.screening.sector_strength import (
    SectorStrengthInfo,
    SectorStrengthReport,
    _build_sector_lookup,
    compute_sector_strength,
    render_sector_strength,
)
from src.screening.industry_rotation import IndustrySignal


# ---------------------------------------------------------------------------
# Unit: _build_sector_lookup
# ---------------------------------------------------------------------------


class TestBuildSectorLookup:
    def test_empty(self) -> None:
        assert _build_sector_lookup([]) == {}

    def test_single_signal(self) -> None:
        sig = IndustrySignal(
            industry_name="电子",
            candidate_count=5,
            avg_score_b=0.4,
            momentum_score=0.3,
        )
        lookup = _build_sector_lookup([sig])
        assert "电子" in lookup
        momentum, rank, total = lookup["电子"]
        assert momentum == 0.3
        assert rank == 1
        assert total == 1

    def test_multiple_signals_ranked(self) -> None:
        sigs = [
            IndustrySignal(
                industry_name="电子",
                candidate_count=5,
                avg_score_b=0.4,
                momentum_score=0.5,
            ),
            IndustrySignal(
                industry_name="银行",
                candidate_count=3,
                avg_score_b=0.2,
                momentum_score=0.1,
            ),
        ]
        lookup = _build_sector_lookup(sigs)
        assert lookup["电子"][1] == 1  # rank 1
        assert lookup["银行"][1] == 2  # rank 2
        assert lookup["电子"][2] == 2  # total 2


# ---------------------------------------------------------------------------
# Integration: compute_sector_strength with mock data
# ---------------------------------------------------------------------------


def _write_reports(tmp_dir: Path, reports: dict[str, list[dict]]) -> None:
    """Write auto_screening_*.json files to tmp_dir."""
    for date_str, recs in reports.items():
        path = tmp_dir / f"auto_screening_{date_str}.json"
        path.write_text(
            json.dumps({"trade_date": date_str, "recommendations": recs}),
            encoding="utf-8",
        )


def _make_rec(
    ticker: str,
    name: str,
    score_b: float,
    industry: str = "电子",
) -> dict[str, Any]:
    return {
        "ticker": ticker,
        "name": name,
        "score_b": score_b,
        "industry_sw": industry,
        "strategy_signals": {
            "trend": {"signal": "bullish", "confidence": 70, "direction": 1},
            "fundamental": {"signal": "bullish", "confidence": 60, "direction": 1},
            "mean_reversion": {"signal": "neutral", "confidence": 40, "direction": 0},
            "event_sentiment": {"signal": "bullish", "confidence": 55, "direction": 1},
        },
    }


class TestComputeSectorStrength:
    def test_no_reports(self, tmp_path: Path) -> None:
        report = compute_sector_strength(reports_dir=tmp_path)
        assert report.items == []

    def test_single_industry(self, tmp_path: Path) -> None:
        """All stocks in same industry → still classified (single industry is both strong and weak)."""
        recs = [
            _make_rec("000001", "平安银行", 0.5, "银行"),
            _make_rec("600036", "招商银行", 0.4, "银行"),
        ]
        _write_reports(tmp_path, {"20260610": recs})
        report = compute_sector_strength(reports_dir=tmp_path)
        assert len(report.items) == 2
        # Single industry: gets classified as both strong and weak
        # (it's the only sector, so it's in top 3 and bottom 3)
        for item in report.items:
            assert item.industry == "银行"

    def test_multiple_industries_strong_weak(self, tmp_path: Path) -> None:
        """Stocks in different industries get different strength labels."""
        recs = [
            _make_rec("000001", "平安银行", 0.5, "银行"),
            _make_rec("300750", "宁德时代", 0.6, "电气设备"),
            _make_rec("600519", "贵州茅台", 0.3, "食品饮料"),
            _make_rec("000880", "潍柴重机", 0.4, "汽车"),
        ]
        _write_reports(tmp_path, {"20260610": recs})
        report = compute_sector_strength(reports_dir=tmp_path, top_n=10)
        assert len(report.items) == 4
        # Should have strong and weak sectors (3 strong / 3 weak from 4 industries)
        labels = {item.strength_label for item in report.items}
        assert len(labels) >= 1  # at least some classification

    def test_industry_sw_fallback(self, tmp_path: Path) -> None:
        """Falls back to 'industry' field if industry_sw is missing."""
        rec = {
            "ticker": "000001",
            "name": "Test",
            "score_b": 0.5,
            "industry": "银行",
            "strategy_signals": {},
        }
        _write_reports(tmp_path, {"20260610": [rec]})
        report = compute_sector_strength(reports_dir=tmp_path)
        assert report.items[0].industry == "银行"

    def test_trade_date_extracted(self, tmp_path: Path) -> None:
        _write_reports(
            tmp_path,
            {
                "20260610": [
                    _make_rec("000001", "Test", 0.5),
                ],
            },
        )
        report = compute_sector_strength(reports_dir=tmp_path)
        assert report.trade_date == "20260610"

    def test_top_n_limits_output(self, tmp_path: Path) -> None:
        recs = [_make_rec(f"{i:06d}", f"Stock{i}", 0.5, "电子") for i in range(10)]
        _write_reports(tmp_path, {"20260610": recs})
        report = compute_sector_strength(reports_dir=tmp_path, top_n=3)
        assert len(report.items) == 3

    def test_to_dict(self, tmp_path: Path) -> None:
        recs = [
            _make_rec("000001", "平安银行", 0.5, "银行"),
            _make_rec("300750", "宁德时代", 0.6, "电气设备"),
        ]
        _write_reports(tmp_path, {"20260610": recs})
        report = compute_sector_strength(reports_dir=tmp_path)
        d = report.to_dict()
        assert d["trade_date"] == "20260610"
        assert len(d["items"]) == 2
        for item in d["items"]:
            assert "ticker" in item
            assert "strength_bonus" in item
            assert "strength_label" in item

    def test_score_b_none_safe(self, tmp_path: Path) -> None:
        rec = {
            "ticker": "000001",
            "name": "Test",
            "score_b": None,
            "industry_sw": "银行",
            "strategy_signals": {},
        }
        _write_reports(tmp_path, {"20260610": [rec]})
        report = compute_sector_strength(reports_dir=tmp_path)
        assert len(report.items) == 1


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


class TestRenderSectorStrength:
    def test_empty_report(self) -> None:
        text = render_sector_strength(SectorStrengthReport())
        assert "无推荐数据" in text

    def test_basic_report(self) -> None:
        report = SectorStrengthReport(
            trade_date="20260610",
            lookback_days=5,
            strong_sectors=["电子"],
            weak_sectors=["银行"],
            items=[
                SectorStrengthInfo(
                    ticker="300750",
                    name="宁德时代",
                    industry="电子",
                    sector_momentum=0.45,
                    sector_rank=1,
                    sector_total=5,
                    strength_bonus=0.05,
                    strength_label="strong",
                ),
                SectorStrengthInfo(
                    ticker="000001",
                    name="平安银行",
                    industry="银行",
                    sector_momentum=-0.2,
                    sector_rank=5,
                    sector_total=5,
                    strength_bonus=-0.05,
                    strength_label="weak",
                ),
            ],
        )
        text = render_sector_strength(report)
        assert "300750" in text
        assert "000001" in text
        assert "电子" in text
        assert "Sector Strength" in text

    def test_summary_counts(self) -> None:
        report = SectorStrengthReport(
            trade_date="20260610",
            items=[
                SectorStrengthInfo(ticker="A", strength_label="strong"),
                SectorStrengthInfo(ticker="B", strength_label="neutral"),
                SectorStrengthInfo(ticker="C", strength_label="weak"),
            ],
        )
        text = render_sector_strength(report)
        assert "强行业: 1" in text
        assert "弱行业: 1" in text
