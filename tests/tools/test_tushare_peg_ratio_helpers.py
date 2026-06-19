"""Characterization test for _build_peg_ratio (PEG = P/E / growth%).

Pins the canonical PEG formula behavior so the redundant ``/100`` then ``*100``
conversion in the implementation can be safely simplified without changing
output. Standard PEG: PE=20, growth=10% -> PEG = 20/10 = 2.0.
"""
from __future__ import annotations

import math

from src.tools.tushare_financial_metrics_helpers import _build_peg_ratio


def _row(netprofit_yoy: float | None) -> dict:
    return {"netprofit_yoy": netprofit_yoy} if netprofit_yoy is not None else {}


# --- canonical PEG formula cases (pin before refactor) ---


def test_peg_canonical_pe20_growth10pct_equals_2() -> None:
    """PE=20, growth=10% -> PEG = 20/10 = 2.0 (textbook Peter Lynch PEG)."""
    assert _build_peg_ratio({"netprofit_yoy": 10.0}, 20.0) == 2.0


def test_peg_canonical_pe15_growth15pct_equals_1() -> None:
    """PE=15, growth=15% -> PEG = 1.0 (Lynch undervalued threshold)."""
    assert _build_peg_ratio({"netprofit_yoy": 15.0}, 15.0) == 1.0


def test_peg_canonical_pe30_growth10pct_equals_3() -> None:
    """PE=30, growth=10% -> PEG = 30/10 = 3.0."""
    assert _build_peg_ratio({"netprofit_yoy": 10.0}, 30.0) == 3.0


# --- guard cases (None / non-positive) ---


def test_peg_none_when_pe_is_none() -> None:
    assert _build_peg_ratio({"netprofit_yoy": 10.0}, None) is None


def test_peg_none_when_pe_zero_or_negative() -> None:
    assert _build_peg_ratio({"netprofit_yoy": 10.0}, 0.0) is None
    assert _build_peg_ratio({"netprofit_yoy": 10.0}, -5.0) is None


def test_peg_none_when_growth_missing_or_nan() -> None:
    assert _build_peg_ratio({}, 20.0) is None
    assert _build_peg_ratio({"netprofit_yoy": float("nan")}, 20.0) is None


def test_peg_none_when_growth_zero_or_negative() -> None:
    assert _build_peg_ratio({"netprofit_yoy": 0.0}, 20.0) is None
    assert _build_peg_ratio({"netprofit_yoy": -5.0}, 20.0) is None


# --- fractional growth preserved (large growth -> small PEG) ---


def test_peg_large_growth_yields_small_peg() -> None:
    """PE=40, growth=80% -> PEG = 40/80 = 0.5 (high-growth cheap on PEG)."""
    result = _build_peg_ratio({"netprofit_yoy": 80.0}, 40.0)
    assert result is not None and math.isclose(result, 0.5)
