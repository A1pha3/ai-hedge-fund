"""Tests for dynamic_threshold.py -- P7-2."""

from __future__ import annotations

import json
from pathlib import Path

from src.screening.dynamic_threshold import (
    compute_dynamic_threshold,
    render_dynamic_threshold,
    _load_recent_hit_rate,
)


class TestComputeDynamicThreshold:
    def test_no_data_returns_base_threshold(self) -> None:
        result = compute_dynamic_threshold(
            reports_dir=Path("/nonexistent"),
            base_threshold=0.30,
        )
        assert result["threshold"] == 0.30
        assert result["hit_rate"] is None
        assert "insufficient" in result.get("note", "")

    def test_high_hit_rate_lowers_threshold(self, tmp_path: Path) -> None:
        # Create tracking history with 80% hit rate
        records = []
        for i in range(10):
            records.append({
                "ticker": f"00000{i}",
                "tracking_status": "complete",
                "t_plus_5_return": 0.10 if i < 8 else -0.05,
            })
        (tmp_path / "tracking_history.json").write_text(
            json.dumps({"records": records}), encoding="utf-8"
        )

        result = compute_dynamic_threshold(
            reports_dir=tmp_path,
            base_threshold=0.30,
            target_hit_rate=0.50,
        )
        assert result["hit_rate"] == 0.8
        assert result["threshold"] < 0.30  # Threshold relaxed
        assert result["adjustment"] < 0

    def test_low_hit_rate_raises_threshold(self, tmp_path: Path) -> None:
        # Create tracking history with 20% hit rate
        records = []
        for i in range(10):
            records.append({
                "ticker": f"00000{i}",
                "tracking_status": "complete",
                "t_plus_5_return": 0.10 if i < 2 else -0.05,
            })
        (tmp_path / "tracking_history.json").write_text(
            json.dumps({"records": records}), encoding="utf-8"
        )

        result = compute_dynamic_threshold(
            reports_dir=tmp_path,
            base_threshold=0.30,
            target_hit_rate=0.50,
        )
        assert result["hit_rate"] == 0.2
        assert result["threshold"] > 0.30  # Threshold raised
        assert result["adjustment"] > 0

    def test_threshold_clamped_to_min(self, tmp_path: Path) -> None:
        # 0% hit rate should clamp to min_threshold
        records = [
            {"ticker": f"00000{i}", "tracking_status": "complete", "t_plus_5_return": -0.10}
            for i in range(10)
        ]
        (tmp_path / "tracking_history.json").write_text(
            json.dumps({"records": records}), encoding="utf-8"
        )

        result = compute_dynamic_threshold(
            reports_dir=tmp_path,
            base_threshold=0.30,
            min_threshold=0.15,
            max_threshold=0.60,
        )
        assert result["threshold"] >= 0.15
        assert result["threshold"] <= 0.60

    def test_threshold_clamped_to_max(self, tmp_path: Path) -> None:
        # 100% hit rate should clamp to max_threshold
        records = [
            {"ticker": f"00000{i}", "tracking_status": "complete", "t_plus_5_return": 0.10}
            for i in range(10)
        ]
        (tmp_path / "tracking_history.json").write_text(
            json.dumps({"records": records}), encoding="utf-8"
        )

        result = compute_dynamic_threshold(
            reports_dir=tmp_path,
            base_threshold=0.30,
            min_threshold=0.15,
            max_threshold=0.60,
        )
        assert result["threshold"] >= 0.15

    def test_exactly_target_no_change(self, tmp_path: Path) -> None:
        # 50% hit rate with 50% target → no adjustment
        records = []
        for i in range(10):
            records.append({
                "ticker": f"00000{i}",
                "tracking_status": "complete",
                "t_plus_5_return": 0.10 if i < 5 else -0.05,
            })
        (tmp_path / "tracking_history.json").write_text(
            json.dumps({"records": records}), encoding="utf-8"
        )

        result = compute_dynamic_threshold(
            reports_dir=tmp_path,
            base_threshold=0.30,
            target_hit_rate=0.50,
        )
        assert result["adjustment"] == 0.0
        assert result["threshold"] == 0.30

    def test_too_few_samples_uses_base(self, tmp_path: Path) -> None:
        # Only 3 records (below threshold of 5)
        records = [
            {"ticker": "000001", "tracking_status": "complete", "t_plus_5_return": 0.10}
            for _ in range(3)
        ]
        (tmp_path / "tracking_history.json").write_text(
            json.dumps({"records": records}), encoding="utf-8"
        )

        result = compute_dynamic_threshold(
            reports_dir=tmp_path,
            base_threshold=0.30,
        )
        assert result["threshold"] == 0.30
        assert result["hit_rate"] is None


class TestLoadRecentHitRate:
    def test_no_file(self, tmp_path: Path) -> None:
        hit_rate, size = _load_recent_hit_rate(tmp_path, 30)
        assert hit_rate is None
        assert size == 0

    def test_invalid_json(self, tmp_path: Path) -> None:
        (tmp_path / "tracking_history.json").write_text("not json", encoding="utf-8")
        hit_rate, size = _load_recent_hit_rate(tmp_path, 30)
        assert hit_rate is None
        assert size == 0

    def test_fallback_to_t_plus_3(self, tmp_path: Path) -> None:
        # No t_plus_5, but has t_plus_3
        records = [
            {"ticker": "000001", "tracking_status": "complete", "t_plus_3_return": 0.05}
            for _ in range(6)
        ]
        (tmp_path / "tracking_history.json").write_text(
            json.dumps({"records": records}), encoding="utf-8"
        )
        hit_rate, size = _load_recent_hit_rate(tmp_path, 30)
        assert hit_rate == 1.0
        assert size == 6


class TestRenderDynamicThreshold:
    def test_renders_base_when_no_data(self) -> None:
        result = {"threshold": 0.30, "hit_rate": None, "adjustment": 0.0,
                  "sample_size": 0, "base_threshold": 0.30, "note": "insufficient data"}
        output = render_dynamic_threshold(result)
        assert "0.30" in output
        assert "insufficient" in output

    def test_renders_adjustment(self) -> None:
        result = {"threshold": 0.35, "hit_rate": 0.30, "adjustment": 0.05,
                  "sample_size": 20, "base_threshold": 0.30,
                  "target_hit_rate": 0.50}
        output = render_dynamic_threshold(result)
        assert "stricter" in output
        assert "0.35" in output
