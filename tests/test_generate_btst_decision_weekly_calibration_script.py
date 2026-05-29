from __future__ import annotations

import json
from pathlib import Path

from scripts.generate_btst_decision_weekly_calibration import (
    build_weekly_calibration,
    render_weekly_calibration_markdown,
)


def test_build_weekly_calibration_groups_by_grade_and_data_quality(tmp_path: Path) -> None:
    ledger_path = tmp_path / "ledger.json"
    ledger_path.write_text(
        json.dumps(
            {
                "rows": [
                    {
                        "ticker": "002222",
                        "evidence_grade": "B",
                        "data_quality": "fresh",
                        "role": "formal_selected",
                        "entry_mode": "confirm_then_hold_breakout",
                        "review_label": "close_positive",
                    },
                    {
                        "ticker": "002916",
                        "evidence_grade": "C",
                        "data_quality": "usable_with_warning",
                        "role": "formal_selected",
                        "entry_mode": "payoff_reconfirmation_only",
                        "review_label": "close_non_positive",
                    },
                ]
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    result = build_weekly_calibration([ledger_path])

    assert result["total_rows"] == 2
    assert result["by_evidence_grade"]["B"]["row_count"] == 1
    assert result["by_evidence_grade"]["B"]["close_positive_rate"] == 1.0
    assert result["by_data_quality"]["usable_with_warning"]["close_positive_rate"] == 0.0


def test_render_weekly_calibration_markdown() -> None:
    markdown = render_weekly_calibration_markdown(
        {
            "total_rows": 1,
            "by_evidence_grade": {
                "B": {
                    "row_count": 1,
                    "close_positive_count": 1,
                    "close_positive_rate": 1.0,
                }
            },
            "by_data_quality": {
                "fresh": {
                    "row_count": 1,
                    "close_positive_count": 1,
                    "close_positive_rate": 1.0,
                }
            },
            "by_role": {},
            "by_entry_mode": {},
        }
    )

    assert "# BTST Decision Weekly Calibration" in markdown
    assert "| B | 1 | 1 | 100.00% |" in markdown
