"""Characterization tests for scripts/monitor_avoid_ratio.py — F4 evaluator.

AutoDev C8/NS-18 gap 4: verifies the AVOID ratio daily monitor computes
verdict distributions correctly, persists to JSONL idempotently, and
honours the honesty-disclosure pattern (warnings on read/parse failures
rather than silent degradation).
"""

from __future__ import annotations

import importlib.util
import json
import logging
from pathlib import Path
from unittest.mock import patch

import pytest

SCRIPT_PATH = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "monitor_avoid_ratio.py"
)


def _load_module() -> object:
    """Load the script as an importable module (scripts/ is not a package)."""
    spec = importlib.util.spec_from_file_location("monitor_avoid_ratio", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# compute_verdict_distribution
# ---------------------------------------------------------------------------


def _make_report(
    *,
    regime: str = "normal",
    recommendations: list[dict] | None = None,
) -> dict:
    return {
        "market_state": {"regime_gate_level": regime},
        "recommendations": recommendations or [],
    }


class TestComputeVerdictDistribution:
    """Verify the verdict counting + ratio math delegates correctly."""

    def test_empty_recommendations(self) -> None:
        mod = _load_module()
        report = _make_report(regime="normal", recommendations=[])
        result = mod.compute_verdict_distribution(report)
        assert result["market_regime"] == "normal"
        assert result["total_recommendations"] == 0
        assert result["verdict_counts"] == {"BUY": 0, "HOLD": 0, "AVOID": 0}
        # Zero total → ratios all 0.0 (no division by zero)
        assert result["verdict_ratios"] == {"BUY": 0.0, "HOLD": 0.0, "AVOID": 0.0}

    def test_mixed_verdicts_ratios_sum_to_one(self) -> None:
        mod = _load_module()
        recs = [
            {"ticker": "A", "decision": "strong_buy"},
            {"ticker": "B", "decision": "buy"},
            {"ticker": "C", "decision": "hold"},
            {"ticker": "D", "decision": "avoid"},
            {"ticker": "E", "decision": "avoid"},
        ]
        report = _make_report(regime="normal", recommendations=recs)

        # Stub build_front_door_verdict to map decision → action deterministically
        def fake_verdict(rec: dict, *, market_regime: str) -> dict:
            decision = rec.get("decision", "")
            if "buy" in decision:
                return {"action": "BUY"}
            if "hold" in decision:
                return {"action": "HOLD"}
            return {"action": "AVOID"}

        # Patch the lazy import inside compute_verdict_distribution
        with patch(
            "src.screening.investability.build_front_door_verdict",
            side_effect=fake_verdict,
        ):
            result = mod.compute_verdict_distribution(report)

        assert result["total_recommendations"] == 5
        assert result["verdict_counts"] == {"BUY": 2, "HOLD": 1, "AVOID": 2}
        assert result["verdict_ratios"]["BUY"] == pytest.approx(0.4)
        assert result["verdict_ratios"]["HOLD"] == pytest.approx(0.2)
        assert result["verdict_ratios"]["AVOID"] == pytest.approx(0.4)
        assert sum(result["verdict_ratios"].values()) == pytest.approx(1.0)

    def test_market_regime_extracted_from_market_state(self) -> None:
        mod = _load_module()
        report = {
            "market_state": {"regime_gate_level": "crisis"},
            "recommendations": [],
        }
        result = mod.compute_verdict_distribution(report)
        assert result["market_regime"] == "crisis"

    def test_missing_market_state_defaults_to_unknown(self) -> None:
        mod = _load_module()
        report = {"recommendations": []}
        result = mod.compute_verdict_distribution(report)
        assert result["market_regime"] == "unknown"

    def test_non_dict_recommendations_skipped(self) -> None:
        """Non-dict entries (stray strings/None) must not crash the loop."""
        mod = _load_module()
        report = _make_report(
            regime="normal",
            recommendations=[
                "not a dict",
                None,
                {"ticker": "A", "decision": "strong_buy"},
            ],
        )
        with patch(
            "src.screening.investability.build_front_door_verdict",
            return_value={"action": "BUY"},
        ):
            result = mod.compute_verdict_distribution(report)
        # Only the one dict entry is counted
        assert result["total_recommendations"] == 1
        assert result["verdict_counts"]["BUY"] == 1


# ---------------------------------------------------------------------------
# _find_latest_report / _find_report_by_date / _list_all_reports
# ---------------------------------------------------------------------------


class TestFindReports:
    def test_find_latest_skips_malformed_filenames(
        self, tmp_path: Path, caplog
    ) -> None:
        mod = _load_module()
        # Malformed: letters in date segment should be skipped
        (tmp_path / "auto_screening_garbage.json").write_text("{}", encoding="utf-8")
        (tmp_path / "auto_screening_20260701.json").write_text("{}", encoding="utf-8")
        (tmp_path / "auto_screening_20260630.json").write_text("{}", encoding="utf-8")

        with caplog.at_level(logging.DEBUG, logger="monitor_avoid_ratio"):
            result = mod._find_latest_report(tmp_path)

        assert result is not None
        assert result.name == "auto_screening_20260701.json"
        # Malformed filename logged at debug
        debug_msgs = [r.getMessage() for r in caplog.records if r.levelno == logging.DEBUG]
        assert any("garbage" in m for m in debug_msgs)

    def test_find_latest_returns_none_when_empty(self, tmp_path: Path) -> None:
        mod = _load_module()
        assert mod._find_latest_report(tmp_path) is None

    def test_find_report_by_date_invalid_format_warns(
        self, tmp_path: Path, caplog
    ) -> None:
        mod = _load_module()
        with caplog.at_level(logging.WARNING, logger="monitor_avoid_ratio"):
            result = mod._find_report_by_date(tmp_path, "not-a-date")
        assert result is None
        warn_msgs = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
        assert any("invalid --report-date" in m for m in warn_msgs)

    def test_find_report_by_date_invalid_calendar_date_warns(
        self, tmp_path: Path, caplog
    ) -> None:
        """20260631 (June has 30 days) must be rejected."""
        mod = _load_module()
        with caplog.at_level(logging.WARNING, logger="monitor_avoid_ratio"):
            result = mod._find_report_by_date(tmp_path, "20260631")
        assert result is None
        warn_msgs = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
        assert any("invalid --report-date" in m for m in warn_msgs)

    def test_find_report_by_date_returns_path_when_exists(self, tmp_path: Path) -> None:
        mod = _load_module()
        (tmp_path / "auto_screening_20260701.json").write_text("{}", encoding="utf-8")
        result = mod._find_report_by_date(tmp_path, "20260701")
        assert result is not None
        assert result.name == "auto_screening_20260701.json"

    def test_list_all_reports_sorted_ascending(self, tmp_path: Path) -> None:
        mod = _load_module()
        (tmp_path / "auto_screening_20260701.json").write_text("{}", encoding="utf-8")
        (tmp_path / "auto_screening_20260615.json").write_text("{}", encoding="utf-8")
        (tmp_path / "auto_screening_20260630.json").write_text("{}", encoding="utf-8")
        # Malformed — must be excluded
        (tmp_path / "auto_screening_garbage.json").write_text("{}", encoding="utf-8")

        reports = mod._list_all_reports(tmp_path)
        dates = [r[0].strftime("%Y%m%d") for r in reports]
        assert dates == ["20260615", "20260630", "20260701"]


# ---------------------------------------------------------------------------
# _load_report — observability of read/parse failures
# ---------------------------------------------------------------------------


class TestLoadReportObservability:
    """Drain pattern: read/parse failures must warn (not silent return None)."""

    def test_read_failure_emits_warning(self, tmp_path: Path, caplog) -> None:
        mod = _load_module()
        path = tmp_path / "auto_screening_20260701.json"
        # Simulate read failure: file does not exist
        with caplog.at_level(logging.WARNING, logger="monitor_avoid_ratio"):
            result = mod._load_report(path)
        assert result is None
        warn_msgs = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
        assert any("report read failed" in m for m in warn_msgs)

    def test_json_parse_failure_emits_warning(
        self, tmp_path: Path, caplog
    ) -> None:
        mod = _load_module()
        path = tmp_path / "auto_screening_20260701.json"
        path.write_text("{not valid json", encoding="utf-8")
        with caplog.at_level(logging.WARNING, logger="monitor_avoid_ratio"):
            result = mod._load_report(path)
        assert result is None
        warn_msgs = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
        assert any("report JSON parse failed" in m for m in warn_msgs)

    def test_valid_json_loads_silently(self, tmp_path: Path, caplog) -> None:
        mod = _load_module()
        path = tmp_path / "auto_screening_20260701.json"
        path.write_text('{"date": "20260701"}', encoding="utf-8")
        with caplog.at_level(logging.WARNING, logger="monitor_avoid_ratio"):
            result = mod._load_report(path)
        assert result == {"date": "20260701"}
        warn_msgs = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
        assert warn_msgs == []


# ---------------------------------------------------------------------------
# _read_existing_dates / _append_entry — JSONL tracking
# ---------------------------------------------------------------------------


class TestTrackingJsonl:
    def test_read_existing_dates_returns_empty_when_no_file(self, tmp_path: Path) -> None:
        mod = _load_module()
        tracking = tmp_path / "does_not_exist.jsonl"
        assert mod._read_existing_dates(tracking) == set()

    def test_read_existing_dates_skips_malformed_lines(
        self, tmp_path: Path, caplog
    ) -> None:
        mod = _load_module()
        tracking = tmp_path / "tracking.jsonl"
        tracking.write_text(
            '{"trade_date": "20260701"}\n'
            "not json at all\n"
            '{"trade_date": "20260630"}\n'
            "\n"  # blank line
            '{"trade_date": "20260629"}\n',
            encoding="utf-8",
        )
        with caplog.at_level(logging.DEBUG, logger="monitor_avoid_ratio"):
            result = mod._read_existing_dates(tracking)
        assert result == {"20260701", "20260630", "20260629"}
        debug_msgs = [r.getMessage() for r in caplog.records if r.levelno == logging.DEBUG]
        assert any("malformed tracking line" in m for m in debug_msgs)

    def test_append_entry_creates_parent_and_appends(self, tmp_path: Path) -> None:
        mod = _load_module()
        tracking = tmp_path / "nested" / "tracking.jsonl"
        entry = {
            "trade_date": "20260701",
            "report_path": "data/reports/auto_screening_20260701.json",
            "market_regime": "normal",
            "total_recommendations": 3,
            "verdict_counts": {"BUY": 1, "HOLD": 1, "AVOID": 1},
            "verdict_ratios": {"BUY": 0.333, "HOLD": 0.333, "AVOID": 0.333},
            "ts": "2026-07-02T08:30:00Z",
        }
        mod._append_entry(tracking, entry)
        assert tracking.exists()
        lines = tracking.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1
        assert json.loads(lines[0])["trade_date"] == "20260701"

        # Second append must not overwrite
        entry2 = dict(entry, trade_date="20260630")
        mod._append_entry(tracking, entry2)
        lines = tracking.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 2


# ---------------------------------------------------------------------------
# _process_report — idempotent backfill dedup
# ---------------------------------------------------------------------------


class TestProcessReportDedup:
    def test_skips_when_already_tracked(self, tmp_path: Path, caplog) -> None:
        mod = _load_module()
        reports_dir = tmp_path / "reports"
        reports_dir.mkdir()
        report_path = reports_dir / "auto_screening_20260701.json"
        report_path.write_text(
            json.dumps(
                {
                    "market_state": {"regime_gate_level": "normal"},
                    "recommendations": [],
                }
            ),
            encoding="utf-8",
        )
        tracking = tmp_path / "tracking.jsonl"
        tracking.write_text(
            json.dumps({"trade_date": "20260701"}) + "\n",
            encoding="utf-8",
        )

        with caplog.at_level(logging.DEBUG, logger="monitor_avoid_ratio"):
            result = mod._process_report(report_path, tracking, force=False)

        assert result is None
        debug_msgs = [r.getMessage() for r in caplog.records if r.levelno == logging.DEBUG]
        assert any("already tracked" in m for m in debug_msgs)

    def test_force_overwrites_existing_entry(self, tmp_path: Path) -> None:
        mod = _load_module()
        reports_dir = tmp_path / "reports"
        reports_dir.mkdir()
        report_path = reports_dir / "auto_screening_20260701.json"
        report_path.write_text(
            json.dumps(
                {
                    "market_state": {"regime_gate_level": "normal"},
                    "recommendations": [],
                }
            ),
            encoding="utf-8",
        )
        tracking = tmp_path / "tracking.jsonl"
        tracking.write_text(
            json.dumps({"trade_date": "20260701"}) + "\n",
            encoding="utf-8",
        )

        # Force=True must append a new line even though 20260701 is already present
        result = mod._process_report(report_path, tracking, force=True)
        assert result is not None
        assert result["trade_date"] == "20260701"
        # Now two lines: the original + the freshly appended
        lines = tracking.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 2

    def test_malformed_filename_skipped_with_warning(
        self, tmp_path: Path, caplog
    ) -> None:
        mod = _load_module()
        reports_dir = tmp_path / "reports"
        reports_dir.mkdir()
        report_path = reports_dir / "auto_screening_garbage.json"
        report_path.write_text("{}", encoding="utf-8")
        tracking = tmp_path / "tracking.jsonl"

        with caplog.at_level(logging.WARNING, logger="monitor_avoid_ratio"):
            result = mod._process_report(report_path, tracking, force=False)

        assert result is None
        warn_msgs = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
        assert any("malformed report filename" in m for m in warn_msgs)


# ---------------------------------------------------------------------------
# render_trend
# ---------------------------------------------------------------------------


class TestRenderTrend:
    def test_empty_entries_returns_placeholder(self) -> None:
        mod = _load_module()
        result = mod.render_trend([], days=7)
        assert "no tracking data" in result

    def test_renders_header_and_rows(self) -> None:
        mod = _load_module()
        entries = [
            {
                "trade_date": "20260629",
                "market_regime": "normal",
                "verdict_counts": {"BUY": 5, "HOLD": 10, "AVOID": 85},
                "verdict_ratios": {"BUY": 0.05, "HOLD": 0.1, "AVOID": 0.85},
            },
            {
                "trade_date": "20260630",
                "market_regime": "normal",
                "verdict_counts": {"BUY": 4, "HOLD": 12, "AVOID": 84},
                "verdict_ratios": {"BUY": 0.04, "HOLD": 0.12, "AVOID": 0.84},
            },
        ]
        result = mod.render_trend(entries, days=7)
        assert "Verdict distribution trend" in result
        assert "20260629" in result
        assert "20260630" in result
        # Header columns present
        assert "AVOID%" in result
        assert "ΔAVOID%" in result

    def test_delta_column_first_row_blank_subsequent_computed(self) -> None:
        mod = _load_module()
        entries = [
            {
                "trade_date": "20260629",
                "market_regime": "normal",
                "verdict_counts": {"BUY": 0, "HOLD": 0, "AVOID": 100},
                "verdict_ratios": {"BUY": 0.0, "HOLD": 0.0, "AVOID": 0.90},
            },
            {
                "trade_date": "20260630",
                "market_regime": "normal",
                "verdict_counts": {"BUY": 0, "HOLD": 0, "AVOID": 100},
                "verdict_ratios": {"BUY": 0.0, "HOLD": 0.0, "AVOID": 0.75},
            },
        ]
        result = mod.render_trend(entries, days=7)
        lines = result.splitlines()
        # render_trend prepends "\n" so splitlines yields:
        #   [0] "" (leading newline)
        #   [1] "  Verdict distribution trend (last 2 days)"
        #   [2] header (trade_date  regime  BUY  HOLD  AVOID  AVOID%  ΔAVOID%)
        #   [3] first data row
        #   [4] second data row
        first_row = lines[3]
        second_row = lines[4]
        # First row: no delta value (blank); AVOID%=90.0%
        assert "90.0%" in first_row
        # Second row: delta = (0.75 - 0.90) * 100 = -15.0
        assert "75.0%" in second_row
        assert "-15.0" in second_row

    def test_days_window_limits_tail(self) -> None:
        mod = _load_module()
        entries = [
            {
                "trade_date": f"202606{d:02d}",
                "market_regime": "normal",
                "verdict_counts": {"BUY": 0, "HOLD": 0, "AVOID": 0},
                "verdict_ratios": {"BUY": 0.0, "HOLD": 0.0, "AVOID": 0.0},
            }
            for d in range(1, 11)  # 10 entries
        ]
        result = mod.render_trend(entries, days=3)
        # Last 3 entries only: 20260608, 20260609, 20260610
        assert "20260608" in result
        assert "20260609" in result
        assert "20260610" in result
        assert "20260607" not in result
        assert "last 3 days" in result


# ---------------------------------------------------------------------------
# CLI main() — end-to-end smoke
# ---------------------------------------------------------------------------


class TestCliMain:
    def _make_reports_dir(self, tmp_path: Path, trade_date: str) -> Path:
        reports_dir = tmp_path / "reports"
        reports_dir.mkdir(exist_ok=True)
        report_path = reports_dir / f"auto_screening_{trade_date}.json"
        report_path.write_text(
            json.dumps(
                {
                    "market_state": {"regime_gate_level": "normal"},
                    "recommendations": [],
                }
            ),
            encoding="utf-8",
        )
        return reports_dir

    def test_trend_mode_empty_tracking_prints_placeholder(
        self, tmp_path: Path, capsys
    ) -> None:
        mod = _load_module()
        tracking = tmp_path / "tracking.jsonl"
        rc = mod.main(["--trend", "--tracking-file", str(tracking)])
        assert rc == 0
        out = capsys.readouterr().out
        assert "no tracking data" in out

    def test_default_mode_appends_latest_report(
        self, tmp_path: Path, capsys
    ) -> None:
        mod = _load_module()
        reports_dir = self._make_reports_dir(tmp_path, "20260701")
        tracking = tmp_path / "tracking.jsonl"

        with patch(
            "src.screening.investability.build_front_door_verdict",
            return_value={"action": "AVOID"},
        ):
            rc = mod.main(
                [
                    "--reports-dir",
                    str(reports_dir),
                    "--tracking-file",
                    str(tracking),
                ]
            )
        assert rc == 0
        out = capsys.readouterr().out
        assert "20260701" in out
        assert "AVOID=" in out
        # Tracking file now has one entry
        lines = tracking.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1
        assert json.loads(lines[0])["trade_date"] == "20260701"

    def test_backfill_mode_idempotent(self, tmp_path: Path) -> None:
        mod = _load_module()
        reports_dir = tmp_path / "reports"
        reports_dir.mkdir()
        for d in ("20260629", "20260630", "20260701"):
            (reports_dir / f"auto_screening_{d}.json").write_text(
                json.dumps(
                    {
                        "market_state": {"regime_gate_level": "normal"},
                        "recommendations": [],
                    }
                ),
                encoding="utf-8",
            )
        tracking = tmp_path / "tracking.jsonl"

        with patch(
            "src.screening.investability.build_front_door_verdict",
            return_value={"action": "AVOID"},
        ):
            rc1 = mod.main(
                ["--backfill", "--reports-dir", str(reports_dir), "--tracking-file", str(tracking)]
            )
            assert rc1 == 0
            first_count = len(tracking.read_text(encoding="utf-8").splitlines())
            assert first_count == 3

            # Second run must not append (idempotent dedup by trade_date)
            rc2 = mod.main(
                ["--backfill", "--reports-dir", str(reports_dir), "--tracking-file", str(tracking)]
            )
            assert rc2 == 0
            second_count = len(tracking.read_text(encoding="utf-8").splitlines())
            assert second_count == first_count

    def test_missing_reports_dir_returns_1(self, tmp_path: Path) -> None:
        mod = _load_module()
        rc = mod.main(["--reports-dir", str(tmp_path / "nonexistent")])
        assert rc == 1

    def test_report_date_not_found_returns_1(self, tmp_path: Path) -> None:
        mod = _load_module()
        reports_dir = tmp_path / "reports"
        reports_dir.mkdir()
        rc = mod.main(
            [
                "--report-date",
                "20260701",
                "--reports-dir",
                str(reports_dir),
            ]
        )
        assert rc == 1
