"""TDD red test: --top-picks must disclose composite_verified=False to the user.

R39 set ``composite_verified=False`` on items whose composite_score fell back
to a 0.9-discounted score_b (missing-composite path), so they are less likely
to cross the BUY 0.5 gate. But the front-door display layer (_print_pick_entry)
never reads ``composite_verified``, so a user sees a fallback-confidence score
with NO visual distinction from a verified composite score. This is a trust-
calibration gap (R44 / R71-R77 family) that undermines the "更高确信" product
goal: the user cannot tell that one pick's score is a conservative estimate
rather than a fully dimension-adjusted composite.

Fix: when composite_verified is explicitly False, show a marker next to the
grade so the user can calibrate trust. Verified/missing-flag items render
unchanged (behavior preserved).
"""

from __future__ import annotations

from pathlib import Path

from src.screening.top_picks import TopPicksRenderContext, _print_pick_entry


def _context() -> TopPicksRenderContext:
    return TopPicksRenderContext(
        market_regime="normal",
        new_tickers=set(),
        report_dir=Path("/tmp"),
        trade_date="20260101",
    )


def _verified_item() -> dict:
    """A pick whose composite_score came from the verified composite path."""
    return {
        "ticker": "000001",
        "name": "平安银行",
        "composite_score": 0.65,
        "base_score": 0.60,
        "composite_verified": True,
    }


def _fallback_item() -> dict:
    """A pick whose composite_score fell back to a 0.9-discounted score_b (R39)."""
    return {
        "ticker": "000002",
        "name": "万科A",
        "composite_score": 0.495,  # 0.55 * 0.9
        "base_score": 0.55,
        "composite_verified": False,
    }


def test_verified_composite_pick_has_no_estimate_marker(capsys) -> None:
    _print_pick_entry(idx=1, item=_verified_item(), context=_context())
    out = capsys.readouterr().out
    # Verified pick: no estimate marker should appear next to the grade
    assert "估" not in out and "‡" not in out, "verified composite pick must NOT show an estimate marker"


def test_fallback_composite_pick_discloses_estimate_marker(capsys) -> None:
    _print_pick_entry(idx=2, item=_fallback_item(), context=_context())
    out = capsys.readouterr().out
    # Fallback (unverified) pick: must disclose an estimate marker so the user
    # can calibrate trust (composite_verified=False = conservative estimate).
    assert "估" in out or "‡" in out, "composite_verified=False pick must disclose an estimate marker; " "currently the front door shows a fallback score with no visual " "distinction from a verified composite score (trust-calibration gap)"
