"""TDD red test: falsy-zero `or` bug in digest min_recurrence header display.

R68/R69/R96/R107 falsy-zero `or` family residue on the digest report header.
The ALPHA-R20.11 comment (digest.py:516-517) explicitly intends the header to
reflect a user-supplied non-default min_recurrence, but the implementation uses
`int(s.get("min_recurrence", 5) or 5)`, which silently overrides an explicit
min_recurrence=0 ("show tickers recurring >= 0 days = all tickers") back to 5.

Result: the rendered digest table header reads "Recurring tickers (>= 5d)" while
the underlying recurring_tickers list was actually filtered at >= 0d — the header
label contradicts the data shown to the user. A display-path data/label mismatch
that corrupts the digest's "higher-confidence" value.
"""

from __future__ import annotations

from src.research.digest import DigestResult, format_digest_markdown


def _result(**summary_overrides) -> DigestResult:
    summary = {
        "total_days": 5,
        "days_with_data": 5,
        "trading_days_in_range": 5,
        "data_coverage_pct": 100.0,
        "avg_candidates": 10,
        "avg_top_score": 0.5,
        "score_std": 0.1,
        "unique_tickers_total": 30,
        "recurring_tickers": ["000001", "000002"],
        "min_recurrence": 5,
    }
    summary.update(summary_overrides)
    return DigestResult(
        period_start="20260101",
        period_end="20260105",
        total_days=5,
        days_with_data=5,
        summary=summary,
    )


def test_explicit_zero_min_recurrence_is_reflected_in_header_not_overridden() -> None:
    """Explicit min_recurrence=0 must render '>= 0d' header, not silently fall back to 5."""
    rendered = format_digest_markdown(_result(min_recurrence=0))
    assert ">= 0d" in rendered, "explicit min_recurrence=0 must render '>= 0d' header; " "falsy-zero `or 5` silently overrode to 5 (display/label mismatch with data)"


def test_default_min_recurrence_still_shows_5() -> None:
    """Missing min_recurrence key still falls back to default 5 (behavior preserved)."""
    result = _result()
    del result.summary["min_recurrence"]
    rendered = format_digest_markdown(result)
    assert ">= 5d" in rendered
