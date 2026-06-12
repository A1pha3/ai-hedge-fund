"""Tests for volume_confirmation.py — P11-2."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from src.screening.volume_confirmation import (
    VolumeEntry,
    VolumeReport,
    _extract_volume_from_rec,
    compute_volume_confirmation,
    render_volume_confirmation,
)


def _write_reports(tmp_dir: Path, reports: dict[str, list[dict]]) -> None:
    for date_str, recs in reports.items():
        path = tmp_dir / f"auto_screening_{date_str}.json"
        path.write_text(
            json.dumps({"trade_date": date_str, "recommendations": recs}),
            encoding="utf-8",
        )


def _make_vol_rec(
    ticker: str,
    name: str,
    score_b: float,
    volume: float = 1000.0,
) -> dict[str, Any]:
    return {
        "ticker": ticker,
        "name": name,
        "score_b": score_b,
        "volume": volume,
        "metrics": {"volume": volume},
    }


class TestExtractVolume:
    def test_direct_volume(self) -> None:
        assert _extract_volume_from_rec({"volume": 500}) == 500.0

    def test_metrics_volume(self) -> None:
        assert _extract_volume_from_rec({"metrics": {"volume": 300}}) == 300.0

    def test_no_volume(self) -> None:
        assert _extract_volume_from_rec({}) == 0.0

    def test_invalid_volume(self) -> None:
        assert _extract_volume_from_rec({"volume": "abc"}) == 0.0

    def test_none_volume(self) -> None:
        assert _extract_volume_from_rec({"volume": None}) == 0.0


class TestComputeVolumeConfirmation:
    def test_no_reports(self, tmp_path: Path) -> None:
        report = compute_volume_confirmation(reports_dir=tmp_path)
        assert report.items == []

    def test_single_report(self, tmp_path: Path) -> None:
        """Single day → no average to compare → neutral."""
        _write_reports(
            tmp_path,
            {"20260610": [_make_vol_rec("000001", "Test", 0.5, 1000)]},
        )
        report = compute_volume_confirmation(reports_dir=tmp_path)
        assert len(report.items) == 1
        assert report.items[0].confirmation == "neutral"

    def test_confirmed_increasing(self, tmp_path: Path) -> None:
        """Volume increasing → confirmed."""
        _write_reports(
            tmp_path,
            {
                "20260608": [_make_vol_rec("000001", "Test", 0.3, 500)],
                "20260609": [_make_vol_rec("000001", "Test", 0.4, 600)],
                "20260610": [_make_vol_rec("000001", "Test", 0.5, 1500)],  # 1500/550 ≈ 2.7x
            },
        )
        report = compute_volume_confirmation(reports_dir=tmp_path, lookback_days=5)
        item = report.items[0]
        assert item.confirmation == "confirmed"
        assert item.volume_factor > 0
        assert item.volume_ratio > 1.2

    def test_divergence_decreasing(self, tmp_path: Path) -> None:
        """Volume decreasing → divergence."""
        _write_reports(
            tmp_path,
            {
                "20260608": [_make_vol_rec("000001", "Test", 0.3, 2000)],
                "20260609": [_make_vol_rec("000001", "Test", 0.4, 1800)],
                "20260610": [_make_vol_rec("000001", "Test", 0.5, 500)],  # 500/1900 ≈ 0.26x
            },
        )
        report = compute_volume_confirmation(reports_dir=tmp_path, lookback_days=5)
        item = report.items[0]
        assert item.confirmation == "divergence"
        assert item.volume_factor < 0

    def test_neutral_range(self, tmp_path: Path) -> None:
        """Volume near average → neutral."""
        _write_reports(
            tmp_path,
            {
                "20260609": [_make_vol_rec("000001", "Test", 0.4, 1000)],
                "20260610": [_make_vol_rec("000001", "Test", 0.5, 1050)],  # 1050/1000 = 1.05x
            },
        )
        report = compute_volume_confirmation(reports_dir=tmp_path)
        item = report.items[0]
        assert item.confirmation == "neutral"
        assert item.volume_factor == 0.0

    def test_top_n_limits(self, tmp_path: Path) -> None:
        recs = [_make_vol_rec(f"{i:06d}", f"S{i}", 0.5, 1000) for i in range(10)]
        _write_reports(tmp_path, {"20260610": recs})
        report = compute_volume_confirmation(reports_dir=tmp_path, top_n=3)
        assert len(report.items) == 3

    def test_trade_date(self, tmp_path: Path) -> None:
        _write_reports(
            tmp_path,
            {"20260610": [_make_vol_rec("000001", "T", 0.5)]},
        )
        report = compute_volume_confirmation(reports_dir=tmp_path)
        assert report.trade_date == "20260610"

    def test_to_dict(self, tmp_path: Path) -> None:
        _write_reports(
            tmp_path,
            {"20260610": [_make_vol_rec("000001", "T", 0.5, 1000)]},
        )
        report = compute_volume_confirmation(reports_dir=tmp_path)
        d = report.to_dict()
        assert "items" in d
        assert d["items"][0]["ticker"] == "000001"

    def test_multiple_tickers(self, tmp_path: Path) -> None:
        _write_reports(
            tmp_path,
            {
                "20260609": [
                    _make_vol_rec("000001", "A", 0.4, 500),
                    _make_vol_rec("000002", "B", 0.6, 2000),
                ],
                "20260610": [
                    _make_vol_rec("000001", "A", 0.5, 1500),  # confirmed
                    _make_vol_rec("000002", "B", 0.5, 800),   # divergence
                ],
            },
        )
        report = compute_volume_confirmation(reports_dir=tmp_path)
        items = {i.ticker: i for i in report.items}
        assert items["000001"].confirmation == "confirmed"
        assert items["000002"].confirmation == "divergence"


class TestRenderVolumeConfirmation:
    def test_empty(self) -> None:
        text = render_volume_confirmation(VolumeReport())
        assert "无推荐数据" in text

    def test_basic(self) -> None:
        report = VolumeReport(
            trade_date="20260610",
            items=[
                VolumeEntry(
                    ticker="000001",
                    name="Test",
                    volume_ratio=1.5,
                    confirmation="confirmed",
                    volume_factor=0.03,
                ),
            ],
        )
        text = render_volume_confirmation(report)
        assert "000001" in text
        assert "Volume Confirmation" in text

    def test_summary_counts(self) -> None:
        report = VolumeReport(
            items=[
                VolumeEntry(ticker="A", confirmation="confirmed", volume_factor=0.03),
                VolumeEntry(ticker="B", confirmation="neutral", volume_factor=0.0),
                VolumeEntry(ticker="C", confirmation="divergence", volume_factor=-0.03),
            ],
        )
        text = render_volume_confirmation(report)
        assert "放量确认: 1" in text
        assert "缩量背离: 1" in text
