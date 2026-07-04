"""Characterization tests for CLI wrapper entry points (run_xxx).

The core compute_* logic is covered in per-module test files
(test_composite_score.py, test_strategy_report.py, test_trend_resonance.py,
test_outlier_detect). These tests lock down the CLI argument-parsing and
exit-code contract for the 4 screening run_xxx entry points that had zero
direct coverage (same gap pattern as run_position_check, fixed in the
prior session).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.screening.composite_score import run_composite_score
from src.screening.outlier_detect import run_outlier_detect
from src.screening.strategy_report import run_strategy_report
from src.screening.trend_resonance import run_trend_resonance

# (label, callable, monkeypatch target for resolve_report_dir, supported args)
WRAPPERS = [
    pytest.param(
        run_composite_score,
        "src.screening.composite_score.resolve_report_dir",
        ["--top-n=5", "--lookback=10"],
        id="composite_score",
    ),
    pytest.param(
        run_strategy_report,
        "src.screening.strategy_report.resolve_report_dir",
        ["--lookback=10"],
        id="strategy_report",
    ),
    pytest.param(
        run_trend_resonance,
        "src.screening.trend_resonance.resolve_report_dir",
        ["--top-n=5"],
        id="trend_resonance",
    ),
    pytest.param(
        run_outlier_detect,
        "src.screening.outlier_detect.resolve_report_dir",
        ["--top-n=5", "--threshold=1.5"],
        id="outlier_detect",
    ),
]


@pytest.mark.parametrize("func,patch_target,_supported", WRAPPERS)
def test_returns_zero_with_none_argv(func, patch_target, _supported, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """argv=None → uses defaults, returns 0."""
    monkeypatch.setattr(patch_target, lambda: tmp_path)
    assert func(None) == 0


@pytest.mark.parametrize("func,patch_target,_supported", WRAPPERS)
def test_returns_zero_with_empty_argv(func, patch_target, _supported, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """argv=[] → uses defaults, returns 0."""
    monkeypatch.setattr(patch_target, lambda: tmp_path)
    assert func([]) == 0


@pytest.mark.parametrize("func,patch_target,supported", WRAPPERS)
def test_supported_args_parsed(func, patch_target, supported, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Each wrapper's supported args parse without error, returns 0."""
    monkeypatch.setattr(patch_target, lambda: tmp_path)
    assert func(supported) == 0


@pytest.mark.parametrize("func,patch_target,_supported", WRAPPERS)
def test_invalid_int_arg_falls_back_silently(func, patch_target, _supported, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Non-numeric --top-n=abc → no crash, returns 0 (uses default)."""
    monkeypatch.setattr(patch_target, lambda: tmp_path)
    assert func(["--top-n=abc"]) == 0


@pytest.mark.parametrize("func,patch_target,_supported", WRAPPERS)
def test_unknown_arg_ignored(func, patch_target, _supported, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Unrecognized args are silently ignored, returns 0."""
    monkeypatch.setattr(patch_target, lambda: tmp_path)
    assert func(["--unknown-flag=x"]) == 0
