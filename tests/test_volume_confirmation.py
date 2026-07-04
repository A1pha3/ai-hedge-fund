"""Tests for volume_confirmation.py — P11-2."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from src.screening.volume_confirmation import (
    _extract_volume_from_rec,
    compute_volume_confirmation,
    render_volume_confirmation,
    VolumeEntry,
    VolumeReport,
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


def _make_real_metrics_rec(
    ticker: str,
    name: str,
    score_b: float,
    amount_ratio_5: float,
) -> dict[str, Any]:
    """模拟真实 FusedScore.metrics 结构 (无 volume/vol/turnover 键).

    NS-12: 真实 rec 只带 amount_ratio_5/turnover_ratio_20 等 ratio 指标,
    不带原始 volume 字段 — 这是死信号的根因。
    """
    return {
        "ticker": ticker,
        "name": name,
        "score_b": score_b,
        "metrics": {
            "attack_slope_258": 0.45,
            "breakout_quality_20_atr": 1.2,
            "close_structure": 0.65,
            "retention_proxy": 0.72,
            "supply_pressure_60": -0.15,
            "amount_ratio_5": amount_ratio_5,
            "turnover_ratio_20": amount_ratio_5 * 0.9,
            "limit_up_memory_259": 0.0,
            "ret_2d": 0.03,
            "ret_5d": 0.05,
            "failed_breakout_10": 0.0,
        },
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

    # NS-12: 真实 FusedScore.metrics 键识别 (RED — 当前实现返回 0.0)
    def test_ns12_amount_ratio_5(self) -> None:
        """真实 FusedScore.metrics 含 amount_ratio_5 (5日量比), 应被识别."""
        rec = {"ticker": "000001", "metrics": {"amount_ratio_5": 1.5}}
        assert _extract_volume_from_rec(rec) == 1.5

    def test_ns12_turnover_ratio_20_fallback(self) -> None:
        """无 amount_ratio_5 时, turnover_ratio_20 (20日换手率比) 应作 fallback."""
        rec = {"ticker": "000001", "metrics": {"turnover_ratio_20": 2.0}}
        assert _extract_volume_from_rec(rec) == 2.0

    def test_ns12_amount_ratio_5_priority_over_turnover(self) -> None:
        """两者都存在时, amount_ratio_5 优先 (更接近单日量比语义)."""
        rec = {
            "ticker": "000001",
            "metrics": {"amount_ratio_5": 1.5, "turnover_ratio_20": 2.5},
        }
        assert _extract_volume_from_rec(rec) == 1.5

    def test_ns12_invalid_amount_ratio_5_falls_to_turnover(self) -> None:
        """amount_ratio_5 无效时, 应尝试 turnover_ratio_20."""
        rec = {
            "ticker": "000001",
            "metrics": {"amount_ratio_5": "abc", "turnover_ratio_20": 1.8},
        }
        assert _extract_volume_from_rec(rec) == 1.8

    def test_ns12_real_fused_score_metrics(self) -> None:
        """真实 FusedScore.metrics (无 volume/vol/turnover 键) 应能读到非零值."""
        rec = {
            "ticker": "000001",
            "name": "平安银行",
            "score_b": 0.62,
            "metrics": {
                "attack_slope_258": 0.45,
                "breakout_quality_20_atr": 1.2,
                "close_structure": 0.65,
                "retention_proxy": 0.72,
                "supply_pressure_60": -0.15,
                "amount_ratio_5": 1.45,
                "turnover_ratio_20": 1.30,
                "limit_up_memory_259": 0.0,
                "ret_2d": 0.03,
                "ret_5d": 0.05,
                "failed_breakout_10": 0.0,
            },
        }
        # 当前 RED: 返回 0.0 (无 volume/vol/turnover 键)
        # 期望 GREEN: 返回 1.45 (amount_ratio_5)
        assert _extract_volume_from_rec(rec) == 1.45


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
                    _make_vol_rec("000002", "B", 0.5, 800),  # divergence
                ],
            },
        )
        report = compute_volume_confirmation(reports_dir=tmp_path)
        items = {i.ticker: i for i in report.items}
        assert items["000001"].confirmation == "confirmed"
        assert items["000002"].confirmation == "divergence"

    # NS-12: 真实 FusedScore.metrics 集成测试 (RED — 当前 volume_factor 永远 0.0)
    def test_ns12_real_metrics_confirmed(self, tmp_path: Path) -> None:
        """真实 FusedScore.metrics (amount_ratio_5) 增加 → confirmed."""
        _write_reports(
            tmp_path,
            {
                "20260608": [_make_real_metrics_rec("000001", "Test", 0.3, 0.8)],
                "20260609": [_make_real_metrics_rec("000001", "Test", 0.4, 0.9)],
                "20260610": [_make_real_metrics_rec("000001", "Test", 0.5, 1.8)],  # 1.8/0.85 ≈ 2.1x
            },
        )
        report = compute_volume_confirmation(reports_dir=tmp_path, lookback_days=5)
        item = report.items[0]
        # 当前 RED: confirmation="neutral" factor=0.0 (因 _extract_volume_from_rec 返回 0.0)
        # 期望 GREEN: confirmation="confirmed" factor>0
        assert item.confirmation == "confirmed"
        assert item.volume_factor > 0
        assert item.volume_ratio > 1.2

    def test_ns12_real_metrics_divergence(self, tmp_path: Path) -> None:
        """真实 FusedScore.metrics (amount_ratio_5) 减少 → divergence."""
        _write_reports(
            tmp_path,
            {
                "20260608": [_make_real_metrics_rec("000001", "Test", 0.3, 1.8)],
                "20260609": [_make_real_metrics_rec("000001", "Test", 0.4, 1.6)],
                "20260610": [_make_real_metrics_rec("000001", "Test", 0.5, 0.4)],  # 0.4/1.7 ≈ 0.24x
            },
        )
        report = compute_volume_confirmation(reports_dir=tmp_path, lookback_days=5)
        item = report.items[0]
        # 当前 RED: confirmation="neutral" (无数据)
        # 期望 GREEN: confirmation="divergence" factor<0
        assert item.confirmation == "divergence"
        assert item.volume_factor < 0


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
