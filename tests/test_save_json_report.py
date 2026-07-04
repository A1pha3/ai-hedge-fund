"""BH-012: persist layer must not write NaN/Inf as literal JSON tokens.

``json.dump`` defaults to ``allow_nan=True``, which writes the non-standard
``NaN``/``Infinity`` literals. Python ``json.loads`` accepts them on read-back,
so a corrupt ``score_b`` survives a round-trip and re-poisons ranking (see
``composite_score.py`` BH-012 + ``signal_momentum.py`` BH-012-drain). The
``_save_json_report`` / ``_sanitize_nonfinite`` guards sanitize non-finite
floats to ``None`` so the on-disk report is always strict JSON and readers
coerce ``None`` to ``0.0``.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from src.main import _sanitize_nonfinite, _save_json_report


class TestSanitizeNonfinite:
    def test_finite_float_unchanged(self) -> None:
        assert _sanitize_nonfinite(0.5) == 0.5
        assert _sanitize_nonfinite(-1.0) == -1.0
        assert _sanitize_nonfinite(0.0) == 0.0

    @pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
    def test_non_finite_float_becomes_none(self, bad: float) -> None:
        assert _sanitize_nonfinite(bad) is None

    def test_int_unchanged(self) -> None:
        assert _sanitize_nonfinite(42) == 42
        assert _sanitize_nonfinite(0) == 0

    def test_string_unchanged(self) -> None:
        assert _sanitize_nonfinite("平安银行") == "平安银行"
        assert _sanitize_nonfinite("0.5") == "0.5"

    def test_none_unchanged(self) -> None:
        assert _sanitize_nonfinite(None) is None

    def test_nested_dict_sanitized(self) -> None:
        payload = {
            "ticker": "000001",
            "score_b": float("nan"),
            "nested": {"deep_inf": float("inf"), "ok": 0.3},
        }
        out = _sanitize_nonfinite(payload)
        assert out["ticker"] == "000001"
        assert out["score_b"] is None
        assert out["nested"]["deep_inf"] is None
        assert out["nested"]["ok"] == 0.3

    def test_list_sanitized(self) -> None:
        payload = [0.5, float("nan"), {"inner": float("inf")}, "text"]
        out = _sanitize_nonfinite(payload)
        assert out == [0.5, None, {"inner": None}, "text"]

    def test_recommendations_shape_sanitized(self) -> None:
        """Front-door recommendations list with a corrupt entry."""
        payload = {
            "recommendations": [
                {"ticker": "GOOD", "score_b": 0.8},
                {"ticker": "CORRUPT", "score_b": float("nan"), "name": "坏"},
            ],
        }
        out = _sanitize_nonfinite(payload)
        assert out["recommendations"][0]["score_b"] == 0.8
        assert out["recommendations"][1]["score_b"] is None
        assert out["recommendations"][1]["name"] == "坏"


class TestSaveJsonReportPersist:
    def test_nan_not_persisted_as_literal(self, tmp_path: Path, monkeypatch) -> None:
        """On-disk file must contain no NaN/Infinity literal tokens."""
        monkeypatch.setattr(
            "src.main.Path",
            _make_repo_root_path_shim(tmp_path),
        )
        payload = {
            "recommendations": [
                {"ticker": "GOOD", "score_b": 0.5},
                {"ticker": "BAD", "score_b": float("nan")},
            ],
            "deep": {"inf": float("inf")},
        }
        out = _save_json_report("test_nan.json", payload)
        raw = out.read_text(encoding="utf-8")
        assert "NaN" not in raw
        assert "Infinity" not in raw
        # Strict JSON parse rejects non-standard constants.
        parsed = json.loads(raw, parse_constant=_reject_nonstandard_token)
        recs = {r["ticker"]: r["score_b"] for r in parsed["recommendations"]}
        assert recs["GOOD"] == 0.5
        assert recs["BAD"] is None
        assert parsed["deep"]["inf"] is None

    def test_normal_payload_round_trips(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setattr(
            "src.main.Path",
            _make_repo_root_path_shim(tmp_path),
        )
        payload = {"ticker": "000001", "score_b": 0.8, "name": "平安银行"}
        out = _save_json_report("test_ok.json", payload)
        assert json.loads(out.read_text(encoding="utf-8")) == payload


def _reject_nonstandard_token(token: str):
    """json.loads parse_constant hook: any NaN/Infinity/-Infinity is an error."""
    raise ValueError(f"non-standard JSON token persisted: {token}")


def _make_repo_root_path_shim(tmp_path: Path):
    """Patch ``src.main.Path`` so reports land under *tmp_path*/data/reports.

    ``_save_json_report`` resolves ``Path(__file__).resolve().parents[1] /
    "data" / "reports"``. We redirect ``parents[1]`` access by returning a path
    whose ``__file__``-style resolution lands under the tmp dir.
    """

    class _ShimmedPath(type(tmp_path)):  # type: ignore[misc]
        def resolve(self, *args, **kwargs):  # noqa: D401, ARG002
            return self

        @property
        def parents(self):  # noqa: D401
            class _Parents:
                def __getitem__(_self, idx):  # noqa: ARG002
                    return tmp_path

            return _Parents()

    return _ShimmedPath


class TestSaveJsonReportAtomicity:
    """R93 same-family drain (R88 corrupt-report CRASH vector): ``_save_json_report``
    must write atomically so a crash mid-serialization leaves the previous file intact.

    c292 (flock) prevents CONCURRENT-write corruption of ``auto_screening_{date}.json``;
    atomic write prevents CRASH-mid-write corruption (Ctrl-C / OOM / ``kill`` during
    ``json.dump``). Together they fully guard the R88 corrupt-report root cause from
    both vectors. The auto_screening report is the must-win daily output consumed by
    ``--top-picks`` / ``--decision-flow`` / ``--signal-consistency`` / composite scoring.
    """

    def test_crash_mid_write_preserves_prior_report(self, tmp_path: Path, monkeypatch) -> None:
        """A crash during json.dump must leave the existing report intact, not truncated."""
        monkeypatch.setattr("src.main.Path", _make_repo_root_path_shim(tmp_path))
        prior = {"ticker": "PRIOR", "score_b": 0.9, "version": "v1"}
        _save_json_report("atomic_test.json", prior)

        # Simulate a crash mid-serialization (Ctrl-C / OOM after the write started).
        from unittest.mock import patch

        with patch("src.main.json.dump", side_effect=RuntimeError("simulated crash mid-write")):
            with pytest.raises(RuntimeError, match="simulated crash"):
                _save_json_report("atomic_test.json", {"ticker": "NEW", "score_b": 0.5})

        report_dir = tmp_path / "data" / "reports"
        raw = (report_dir / "atomic_test.json").read_text(encoding="utf-8")
        parsed = json.loads(raw)  # must parse cleanly (no half-written truncated file)
        assert parsed == prior, "prior report must survive a crashed write — non-atomic open('w') truncates " "immediately, so a crash mid-dump leaves the must-win report corrupt (R88 root cause)"

    def test_crashed_write_leaves_no_temp_residue(self, tmp_path: Path, monkeypatch) -> None:
        """A crashed atomic write must clean up its temp file (no .tmp leaked to reports/)."""
        monkeypatch.setattr("src.main.Path", _make_repo_root_path_shim(tmp_path))
        from unittest.mock import patch

        _save_json_report("cleanup_test.json", {"v": 1})
        with patch("src.main.json.dump", side_effect=RuntimeError("boom")):
            with pytest.raises(RuntimeError):
                _save_json_report("cleanup_test.json", {"v": 2})

        report_dir = tmp_path / "data" / "reports"
        leftover = list(report_dir.glob(".*.tmp")) + list(report_dir.glob("*.tmp"))
        assert leftover == [], f"temp file leaked after crashed write: {[str(p) for p in leftover]}"
