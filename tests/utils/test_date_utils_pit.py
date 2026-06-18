"""R74-refactor: shared point-in-time ``ann_date`` comparison helper.

R41 (fina_indicator metrics path) and R74 (balancesheet/cashflow/income
line_items path) each carried a verbatim copy of the same ann_date PIT gate:
"return True if a report with ``ann_date`` was announced strictly after
``as_of`` (look-ahead), else False; missing/malformed → False (live fallback)".
This test locks the single shared helper that replaces both copies, so both
data paths can no longer drift.
"""

from __future__ import annotations

from src.utils.date_utils import is_announced_after_as_of


class TestIsAnnouncedAfterAsOf:
    def test_strictly_after_is_lookahead(self) -> None:
        assert is_announced_after_as_of("20240430", "20240215") is True

    def test_strictly_before_is_not_lookahead(self) -> None:
        assert is_announced_after_as_of("20240110", "20240215") is False

    def test_exact_boundary_is_not_lookahead(self) -> None:
        """announced exactly on as_of → legitimate (inclusive on boundary)."""
        assert is_announced_after_as_of("20240215", "20240215") is False

    def test_dashed_dates_normalized(self) -> None:
        assert is_announced_after_as_of("2024-04-30", "2024-02-15") is True
        assert is_announced_after_as_of("2024-01-10", "2024-02-15") is False

    def test_missing_ann_date_is_not_lookahead(self) -> None:
        """No ann_date → cannot prove lookahead → live fallback (False)."""
        assert is_announced_after_as_of(None, "20240215") is False
        assert is_announced_after_as_of("", "20240215") is False

    def test_missing_as_of_is_not_lookahead(self) -> None:
        """No as_of → live mode → no PIT filter (False)."""
        assert is_announced_after_as_of("20240430", None) is False

    def test_malformed_ann_date_is_not_lookahead(self) -> None:
        """Malformed (non-digit / wrong length) → robustness fallback (False)."""
        assert is_announced_after_as_of("not-a-date", "20240215") is False
        assert is_announced_after_as_of("2024043", "20240215") is False  # too short

    def test_malformed_as_of_is_not_lookahead(self) -> None:
        assert is_announced_after_as_of("20240430", "not-a-date") is False
