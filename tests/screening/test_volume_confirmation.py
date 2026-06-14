"""Tests for src/screening/volume_confirmation.py — P11-2 Volume-Price Confirmation."""

from __future__ import annotations

import pytest

from src.screening.volume_confirmation import (
    VolumeEntry,
    VolumeReport,
    _confirmation_colored,
    _extract_volume_from_rec,
    render_volume_confirmation,
)
from src.utils.display import Fore, Style


# ---------------------------------------------------------------------------
# _extract_volume_from_rec
# ---------------------------------------------------------------------------


class TestExtractVolumeFromRec:
    def test_direct_volume_field(self) -> None:
        assert _extract_volume_from_rec({"volume": 1000.0}) == 1000.0

    def test_direct_volume_int(self) -> None:
        assert _extract_volume_from_rec({"volume": 500}) == 500.0

    def test_volume_from_metrics(self) -> None:
        assert _extract_volume_from_rec({"metrics": {"volume": 2000.0}}) == 2000.0

    def test_volume_from_metrics_vol(self) -> None:
        assert _extract_volume_from_rec({"metrics": {"vol": 3000.0}}) == 3000.0

    def test_volume_from_metrics_turnover(self) -> None:
        assert _extract_volume_from_rec({"metrics": {"turnover": 4000.0}}) == 4000.0

    def test_direct_field_takes_priority(self) -> None:
        assert _extract_volume_from_rec({"volume": 100.0, "metrics": {"volume": 200.0}}) == 100.0

    def test_missing_volume_returns_zero(self) -> None:
        assert _extract_volume_from_rec({"ticker": "000001"}) == 0.0

    def test_empty_dict_returns_zero(self) -> None:
        assert _extract_volume_from_rec({}) == 0.0

    def test_none_volume_returns_zero(self) -> None:
        assert _extract_volume_from_rec({"volume": None}) == 0.0

    def test_non_numeric_volume_returns_zero(self) -> None:
        assert _extract_volume_from_rec({"volume": "high"}) == 0.0

    def test_non_numeric_metrics_returns_zero(self) -> None:
        assert _extract_volume_from_rec({"metrics": {"volume": "huge"}}) == 0.0

    def test_empty_metrics_returns_zero(self) -> None:
        assert _extract_volume_from_rec({"metrics": {}}) == 0.0


# ---------------------------------------------------------------------------
# VolumeEntry / VolumeReport
# ---------------------------------------------------------------------------


class TestVolumeEntry:
    def test_defaults(self) -> None:
        entry = VolumeEntry(ticker="000001")
        assert entry.confirmation == "neutral"
        assert entry.volume_ratio == 1.0
        assert entry.volume_factor == 0.0


class TestVolumeReport:
    def test_empty(self) -> None:
        report = VolumeReport()
        assert report.items == []

    def test_to_dict(self) -> None:
        report = VolumeReport(
            trade_date="2026-01-01",
            lookback_days=5,
            items=[
                VolumeEntry(
                    ticker="000001",
                    name="平安",
                    volume_ratio=1.5,
                    confirmation="confirmed",
                    volume_factor=0.03,
                ),
            ],
        )
        d = report.to_dict()
        assert d["trade_date"] == "2026-01-01"
        assert d["lookback_days"] == 5
        assert d["items"][0]["volume_ratio"] == pytest.approx(1.5)
        assert d["items"][0]["confirmation"] == "confirmed"


# ---------------------------------------------------------------------------
# render_volume_confirmation
# ---------------------------------------------------------------------------


class TestRenderVolumeConfirmation:
    def test_empty(self) -> None:
        result = render_volume_confirmation(VolumeReport())
        assert "无推荐数据" in result

    def test_with_items(self) -> None:
        report = VolumeReport(
            trade_date="2026-01-01",
            items=[
                VolumeEntry(ticker="000001", name="平安", volume_ratio=1.5, confirmation="confirmed", volume_factor=0.03),
                VolumeEntry(ticker="000002", name="万科", volume_ratio=0.7, confirmation="divergence", volume_factor=-0.03),
            ],
        )
        result = render_volume_confirmation(report)
        assert "000001" in result
        assert "量价确认" in result


# ---------------------------------------------------------------------------
# compute_volume_confirmation (end-to-end, no report files → empty)
# ---------------------------------------------------------------------------


class TestComputeVolumeConfirmation:
    def test_no_reports_returns_empty(self, tmp_path) -> None:
        from src.screening.volume_confirmation import compute_volume_confirmation

        report = compute_volume_confirmation(reports_dir=tmp_path)
        assert report.items == []


# ---------------------------------------------------------------------------
# _confirmation_colored (was 0 direct coverage)
# ---------------------------------------------------------------------------


class TestConfirmationColored:
    """_confirmation_colored — color-code a volume confirmation label."""

    def test_confirmed_green(self) -> None:
        result = _confirmation_colored("confirmed")
        assert result.startswith(Fore.GREEN)
        assert "放量确认" in result

    def test_divergence_red(self) -> None:
        result = _confirmation_colored("divergence")
        assert result.startswith(Fore.RED)
        assert "缩量背离" in result

    def test_unknown_label_white_neutral(self) -> None:
        result = _confirmation_colored("flat")
        assert result.startswith(Fore.WHITE)
        assert "中性" in result

    def test_empty_string_white_neutral(self) -> None:
        result = _confirmation_colored("")
        assert result.startswith(Fore.WHITE)

    def test_ends_with_reset(self) -> None:
        assert _confirmation_colored("confirmed").endswith(Style.RESET_ALL)
