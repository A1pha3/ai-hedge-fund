"""Tests for dynamic_threshold.py -- P7-2."""

from __future__ import annotations

import json
from pathlib import Path

from src.screening.dynamic_threshold import (
    _load_recent_hit_rate,
    compute_dynamic_threshold,
    render_dynamic_threshold,
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
        # NS-18(3): use real schema field ``next_5day_return`` (written by
        # ``recommendation_tracker``), not the stale ``t_plus_5_return`` name.
        records = []
        for i in range(10):
            records.append(
                {
                    "ticker": f"00000{i}",
                    "tracking_status": "complete",
                    "next_5day_return": 0.10 if i < 8 else -0.05,
                }
            )
        (tmp_path / "tracking_history.json").write_text(json.dumps({"records": records}), encoding="utf-8")

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
            records.append(
                {
                    "ticker": f"00000{i}",
                    "tracking_status": "complete",
                    "next_5day_return": 0.10 if i < 2 else -0.05,
                }
            )
        (tmp_path / "tracking_history.json").write_text(json.dumps({"records": records}), encoding="utf-8")

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
        records = [{"ticker": f"00000{i}", "tracking_status": "complete", "next_5day_return": -0.10} for i in range(10)]
        (tmp_path / "tracking_history.json").write_text(json.dumps({"records": records}), encoding="utf-8")

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
        records = [{"ticker": f"00000{i}", "tracking_status": "complete", "next_5day_return": 0.10} for i in range(10)]
        (tmp_path / "tracking_history.json").write_text(json.dumps({"records": records}), encoding="utf-8")

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
            records.append(
                {
                    "ticker": f"00000{i}",
                    "tracking_status": "complete",
                    "next_5day_return": 0.10 if i < 5 else -0.05,
                }
            )
        (tmp_path / "tracking_history.json").write_text(json.dumps({"records": records}), encoding="utf-8")

        result = compute_dynamic_threshold(
            reports_dir=tmp_path,
            base_threshold=0.30,
            target_hit_rate=0.50,
        )
        assert result["adjustment"] == 0.0
        assert result["threshold"] == 0.30

    def test_too_few_samples_uses_base(self, tmp_path: Path) -> None:
        # Only 3 records (below threshold of 5)
        records = [{"ticker": "000001", "tracking_status": "complete", "next_5day_return": 0.10} for _ in range(3)]
        (tmp_path / "tracking_history.json").write_text(json.dumps({"records": records}), encoding="utf-8")

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

    def test_lookback_filters_out_old_records(self, tmp_path: Path) -> None:
        # R160: lookback_days must actually filter by recommended_date.
        # 6 recent records (20260620, within 30d of anchor): 4 hits, 2 miss.
        # 4 old records (20260120, >150d before anchor): all hits — would
        # inflate hit rate to 0.8 if lookback were ignored (the bug).
        # Anchor = latest recommended_date (20260620), data-anchored per R62.
        # NS-18(3): fixtures use real schema field ``next_5day_return``.
        records = [
            # recent (within lookback=30 of anchor 20260620 → cutoff 20260521)
            {"ticker": "000001", "recommended_date": "20260620", "tracking_status": "complete", "next_5day_return": 0.10},
            {"ticker": "000002", "recommended_date": "20260619", "tracking_status": "complete", "next_5day_return": 0.08},
            {"ticker": "000003", "recommended_date": "20260618", "tracking_status": "complete", "next_5day_return": 0.06},
            {"ticker": "000004", "recommended_date": "20260617", "tracking_status": "complete", "next_5day_return": 0.04},
            {"ticker": "000005", "recommended_date": "20260616", "tracking_status": "complete", "next_5day_return": -0.05},
            {"ticker": "000006", "recommended_date": "20260615", "tracking_status": "complete", "next_5day_return": -0.03},
            # old (well outside 30d window) — all hits, must be excluded
            {"ticker": "000007", "recommended_date": "20260120", "tracking_status": "complete", "next_5day_return": 0.20},
            {"ticker": "000008", "recommended_date": "20260119", "tracking_status": "complete", "next_5day_return": 0.15},
            {"ticker": "000009", "recommended_date": "20260118", "tracking_status": "complete", "next_5day_return": 0.12},
            {"ticker": "000010", "recommended_date": "20260117", "tracking_status": "complete", "next_5day_return": 0.10},
        ]
        (tmp_path / "tracking_history.json").write_text(json.dumps({"records": records}), encoding="utf-8")
        hit_rate, size = _load_recent_hit_rate(tmp_path, 30)
        # Only the 6 recent records counted; 4 hits / 6 = 0.6667
        assert size == 6
        assert hit_rate is not None
        assert abs(hit_rate - (4 / 6)) < 1e-6

    def test_lookback_zero_includes_all(self, tmp_path: Path) -> None:
        # lookback_days <= 0 means "no lookback" — include all dated records,
        # even ones far outside any window (≥5 records so hit_rate computes).
        records = [
            {"ticker": "000001", "recommended_date": "20260620", "tracking_status": "complete", "next_5day_return": 0.10},
            {"ticker": "000002", "recommended_date": "20260619", "tracking_status": "complete", "next_5day_return": 0.08},
            {"ticker": "000003", "recommended_date": "20260618", "tracking_status": "complete", "next_5day_return": -0.05},
            {"ticker": "000004", "recommended_date": "20250101", "tracking_status": "complete", "next_5day_return": -0.05},
            {"ticker": "000005", "recommended_date": "20240101", "tracking_status": "complete", "next_5day_return": -0.05},
            {"ticker": "000006", "recommended_date": "20230101", "tracking_status": "complete", "next_5day_return": -0.05},
        ]
        (tmp_path / "tracking_history.json").write_text(json.dumps({"records": records}), encoding="utf-8")
        hit_rate, size = _load_recent_hit_rate(tmp_path, 0)
        assert size == 6
        assert hit_rate == (2 / 6)

    def test_dateless_records_included_when_no_anchor(self, tmp_path: Path) -> None:
        # Backward compat: legacy tracking history with no parseable dates
        # cannot be filtered by lookback — include all (no date anchor).
        records = [{"ticker": f"00000{i}", "tracking_status": "complete", "next_5day_return": 0.10} for i in range(6)]
        (tmp_path / "tracking_history.json").write_text(json.dumps({"records": records}), encoding="utf-8")
        hit_rate, size = _load_recent_hit_rate(tmp_path, 30)
        assert size == 6
        assert hit_rate == 1.0


class TestRenderDynamicThreshold:
    def test_renders_base_when_no_data(self) -> None:
        result = {"threshold": 0.30, "hit_rate": None, "adjustment": 0.0, "sample_size": 0, "base_threshold": 0.30, "note": "insufficient data"}
        output = render_dynamic_threshold(result)
        assert "0.30" in output
        assert "insufficient" in output

    def test_renders_adjustment(self) -> None:
        result = {"threshold": 0.35, "hit_rate": 0.30, "adjustment": 0.05, "sample_size": 20, "base_threshold": 0.30, "target_hit_rate": 0.50}
        output = render_dynamic_threshold(result)
        assert "stricter" in output
        assert "0.35" in output


class TestNS18DynamicThresholdFieldNameStabilization:
    """NS-18(3): _load_recent_hit_rate must read the real tracking_history
    schema field ``next_5day_return`` (written by ``recommendation_tracker``)
    rather than the stale ``t_plus_5_return`` field name that never exists in
    production data. Use single T+5 horizon — no T+3/T+1 fallback, which
    would inflate hit_rate with shorter-horizon noise (per owner backlog
    §三·6 NS-18(3) "混用 T+1/T+3/T+5 horizon 抬高 hit rate → 门槛过低").

    Before this fix the dynamic_threshold feature was silently dead: the
    --decision-flow threshold never adjusted because hit_rate was always None
    (field name mismatch → no record ever matched).
    """

    def test_uses_real_schema_next_5day_return_field(self, tmp_path: Path) -> None:
        # Real tracking_history records use ``next_5day_return`` (written by
        # ``recommendation_tracker``). Stale code read ``t_plus_5_return`` which
        # never exists in production → hit_rate always None → dynamic_threshold
        # always used base threshold (feature dead).
        records = [
            {
                "ticker": f"00000{i}",
                "tracking_status": "complete",
                "next_5day_return": 0.05 if i < 4 else -0.05,
            }
            for i in range(6)
        ]
        (tmp_path / "tracking_history.json").write_text(
            json.dumps({"records": records}), encoding="utf-8"
        )
        hit_rate, size = _load_recent_hit_rate(tmp_path, 30)
        assert hit_rate is not None
        assert abs(hit_rate - (4 / 6)) < 1e-6
        assert size == 6

    def test_single_horizon_no_fallback_to_next_3day_return(self, tmp_path: Path) -> None:
        # NS-18(3): single T+5 horizon — records carrying only
        # ``next_3day_return`` (no ``next_5day_return``) must NOT be counted.
        # Fallback to shorter horizons inflates hit_rate (T+1/T+3 are noisier
        # and more likely positive by chance), lowering the bar for
        # ``--decision-flow`` BUY gate.
        records = [
            {
                "ticker": f"00000{i}",
                "tracking_status": "complete",
                "next_3day_return": 0.05,
            }
            for i in range(6)
        ]
        (tmp_path / "tracking_history.json").write_text(
            json.dumps({"records": records}), encoding="utf-8"
        )
        hit_rate, size = _load_recent_hit_rate(tmp_path, 30)
        # No next_5day_return → records skipped → no outcomes → None
        assert hit_rate is None
        assert size == 0

    def test_single_horizon_no_fallback_to_next_day_return(self, tmp_path: Path) -> None:
        # NS-18(3): same as above but for T+1 — even shorter horizon, more
        # noise. Must not be counted when next_5day_return is absent.
        records = [
            {
                "ticker": f"00000{i}",
                "tracking_status": "complete",
                "next_day_return": 0.05,
            }
            for i in range(6)
        ]
        (tmp_path / "tracking_history.json").write_text(
            json.dumps({"records": records}), encoding="utf-8"
        )
        hit_rate, size = _load_recent_hit_rate(tmp_path, 30)
        assert hit_rate is None
        assert size == 0

    def test_records_with_only_legacy_t_plus_5_return_field_are_skipped(self, tmp_path: Path) -> None:
        # Regression guard: the stale ``t_plus_5_return`` field name must NOT
        # be read, even if present. Production data never carries this field,
        # but if any old test fixture or external writer still uses it, the
        # code must not silently resurrect the old bug.
        records = [
            {
                "ticker": f"00000{i}",
                "tracking_status": "complete",
                "t_plus_5_return": 0.05,
            }
            for i in range(6)
        ]
        (tmp_path / "tracking_history.json").write_text(
            json.dumps({"records": records}), encoding="utf-8"
        )
        hit_rate, size = _load_recent_hit_rate(tmp_path, 30)
        # Legacy field name not read → no outcomes → None
        assert hit_rate is None
        assert size == 0

    def test_mixed_records_only_count_next_5day_return(self, tmp_path: Path) -> None:
        # Mixed fixture: 6 records with next_5day_return (4 hits, 2 miss),
        # 2 records with only next_3day_return (would be hits under old
        # fallback). Single-horizon T+5 → only 6 outcomes counted, 4 hits.
        # Old behavior (if field names were correct): 8 outcomes, 6 hits →
        # inflated hit_rate 0.75. New behavior: 6 outcomes, 4 hits → 0.667.
        # Need ≥5 outcomes to exceed the min-sample threshold.
        records = [
            {"ticker": "000001", "tracking_status": "complete", "next_5day_return": 0.05},
            {"ticker": "000002", "tracking_status": "complete", "next_5day_return": 0.04},
            {"ticker": "000003", "tracking_status": "complete", "next_5day_return": 0.03},
            {"ticker": "000004", "tracking_status": "complete", "next_5day_return": -0.02},
            {"ticker": "000005", "tracking_status": "complete", "next_5day_return": 0.02},
            {"ticker": "000006", "tracking_status": "complete", "next_5day_return": -0.01},
            {"ticker": "000007", "tracking_status": "complete", "next_3day_return": 0.05},
            {"ticker": "000008", "tracking_status": "complete", "next_3day_return": 0.05},
        ]
        (tmp_path / "tracking_history.json").write_text(
            json.dumps({"records": records}), encoding="utf-8"
        )
        hit_rate, size = _load_recent_hit_rate(tmp_path, 30)
        assert hit_rate is not None
        assert abs(hit_rate - (4 / 6)) < 1e-6
        assert size == 6
