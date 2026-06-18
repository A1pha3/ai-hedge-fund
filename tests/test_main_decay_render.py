"""R53: surface ``days_since_peak`` in the top-picks decay tag.

``DecayInfo.days_since_peak`` (how many days since the ticker's score peaked)
is computed by ``signal_decay_detector`` and serialized into the report, but
the ``--top`` / ``--auto`` table renderers showed only ``change_pct``. R53
appends the days-since-peak so the user can distinguish early decay (↓20% at
1d) from late decay (↓20% at 5d) — a meaningful trajectory signal for the
"is this BUY still valid?" decision.
"""

from __future__ import annotations

from src.main import _build_top_table_row


def _make_rec(decay: dict | None = None, **overrides) -> dict:
    rec = {
        "ticker": "000001",
        "name": "测试",
        "industry_sw": "银行",
        "score_b": 0.5,
        "decision": "watch",
        "consecutive_days": 1,
    }
    if decay is not None:
        rec["decay"] = decay
    rec.update(overrides)
    return rec


def test_decay_tag_shows_days_since_peak() -> None:
    """R53: a decaying pick must surface days_since_peak in the decay cell."""
    rec = _make_rec(decay={"level": "moderate", "change_pct": -20.0, "days_since_peak": 5})
    row = _build_top_table_row(idx=1, rec=rec)
    decay_cell = row[-1]
    assert "(5d)" in decay_cell, f"Expected '(5d)' days-since-peak in decay cell, got: {decay_cell!r}"


def test_decay_tag_omits_days_when_at_peak() -> None:
    """R53: days_since_peak=0 (today IS the peak) must not append a days tag."""
    rec = _make_rec(decay={"level": "moderate", "change_pct": -5.0, "days_since_peak": 0})
    row = _build_top_table_row(idx=1, rec=rec)
    decay_cell = row[-1]
    assert "(0d)" not in decay_cell, f"Should not show '(0d)' at peak, got: {decay_cell!r}"
    # The change_pct must still be present.
    assert "5" in decay_cell


def test_decay_none_shows_dash() -> None:
    """No decay → dash, no days tag."""
    rec = _make_rec(decay={"level": "none", "change_pct": None, "days_since_peak": 0})
    row = _build_top_table_row(idx=1, rec=rec)
    decay_cell = row[-1]
    assert "↓" not in decay_cell
    assert "—" in decay_cell


def test_top_table_row_resilient_to_null_score_b() -> None:
    """``score_b: null`` (JSON null) must not crash ``--top`` rendering.

    ``_build_top_table_row`` used a bare ``float(rec.get("score_b", 0.0))`` which
    raises ``TypeError`` when the key is present with value ``None`` (the default
    arg only fires when the key is *absent*). Sibling renderers (``--top-picks``,
    ``--daily-brief``) already use the shared ``safe_float`` helper; this brings
    ``--top`` to the same resilience so one malformed recommendation does not
    take down the whole table. Falls back to 0.0.
    """
    rec = _make_rec(score_b=None)
    row = _build_top_table_row(idx=1, rec=rec)  # must not raise
    # score column renders 0.0 (signed format +0.0000); stringify cells since
    # idx column is an int (the row is a heterogeneous list).
    assert any("0.0000" in str(cell) for cell in row)


def test_top_table_row_resilient_to_non_numeric_score_b() -> None:
    """A non-numeric ``score_b`` string must degrade to 0.0, not crash."""
    rec = _make_rec(score_b="abc")
    row = _build_top_table_row(idx=1, rec=rec)  # must not raise
    assert any("0.0000" in str(cell) for cell in row)
