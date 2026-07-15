"""Tests for the read-only setup-output panel health check."""

from __future__ import annotations

import math

from scripts.panel_health_check import (
    _cohens_d,
    _returns,
    _verdict,
    check_horizon,
    load_panel,
)


def _row(eligible: bool, horizon: int, value) -> dict:
    return {"plan_eligible": eligible, f"return_t{horizon}": value}


def _rows(eligible_vals: list[float], filtered_vals: list[float], horizon: int = 1) -> list[dict]:
    return [_row(True, horizon, v) for v in eligible_vals] + [_row(False, horizon, v) for v in filtered_vals]


def test_untestable_below_min_n() -> None:
    rows = _rows([3.0, 4.0], [-1.0, -2.0])  # total=4
    block, verdict = check_horizon(rows, 1, min_n=30, min_group=5)
    assert verdict is None
    assert "样本不足" in block


def test_untestable_when_one_group_too_small() -> None:
    rows = _rows([3.0] * 12, [-1.0, -2.0], horizon=1)  # total=14 but filtered=2
    block, verdict = check_horizon(rows, 1, min_n=10, min_group=5)
    assert verdict is None
    assert "某组样本过小" in block


def test_eligible_significantly_better_reports_alpha() -> None:
    elig = [3.0, 4.0, 5.0, 3.5, 4.5, 5.5, 3.2, 4.2]
    filt = [-2.0, -1.0, 0.0, -1.5, -0.5, -2.5, -1.2, -0.8]
    block, verdict = check_horizon(_rows(elig, filt), 1, min_n=10, min_group=5)
    assert verdict is True
    assert "✅" in block
    assert "Welch t-test" in block


def test_overlapping_distributions_not_significant() -> None:
    same = [1.0, -1.0, 2.0, -2.0, 0.5, -0.5, 1.5, -1.5]
    block, verdict = check_horizon(_rows(same, list(same)), 1, min_n=10, min_group=5)
    assert verdict is False
    assert "◻️" in block


def test_reverse_signal_flags_harm() -> None:
    elig = [-2.0, -1.0, 0.0, -1.5, -0.5, -2.5, -1.2, -0.8]
    filt = [3.0, 4.0, 5.0, 3.5, 4.5, 5.5, 3.2, 4.2]
    block, verdict = check_horizon(_rows(elig, filt), 1, min_n=10, min_group=5)
    assert verdict is False
    assert "反向" in block


def test_returns_is_nan_safe() -> None:
    rows = [
        _row(True, 1, 5.0),
        _row(True, 1, None),
        _row(True, 1, "not-a-number"),
        _row(True, 1, float("inf")),
        _row(False, 1, -1.0),
    ]
    assert _returns(rows, 1, eligible=True) == [5.0]
    assert _returns(rows, 1, eligible=False) == [-1.0]


def test_load_panel_missing_and_malformed(tmp_path) -> None:
    assert load_panel(tmp_path / "nope.jsonl") == []
    p = tmp_path / "panel.jsonl"
    p.write_text('{"a": 1}\n\n{bad json}\n{"b": 2}\n', encoding="utf-8")
    assert load_panel(p) == [{"a": 1}, {"b": 2}]


def test_verdict_thresholds() -> None:
    assert "✅" in _verdict(0.01, +2.0)
    assert "反向" in _verdict(0.01, -2.0)
    assert "◻️" in _verdict(0.20, +2.0)


def test_cohens_d_sign_and_small_group() -> None:
    assert _cohens_d([3.0, 4.0, 5.0], [-1.0, -2.0, -3.0]) > 0
    assert math.isnan(_cohens_d([1.0], [2.0]))  # n<2 in a group -> NaN
