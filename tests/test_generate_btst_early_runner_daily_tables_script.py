from __future__ import annotations

import json
from pathlib import Path

from scripts.generate_btst_early_runner_daily_tables import generate_btst_early_runner_daily_tables


def _write_analysis(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "daily_boards": [
                    {
                        "trade_date": "2026-03-24",
                        "gate_action": "tradable",
                        "deployment_mode": "shadow_only",
                        "early_runner_watchlist": [{"ticker": "300001", "pre_score": 0.71, "confirm_score": 0.82, "candidate_source": "catalyst_theme", "hot_theme_board": "AI Agent", "entry_status": "filled"}],
                        "early_runner_priority": [{"ticker": "300001", "pre_score": 0.71, "confirm_score": 0.82, "candidate_source": "catalyst_theme", "hot_theme_board": "AI Agent", "entry_status": "filled"}],
                        "second_entry_reentry": [{"ticker": "300002", "pre_score": 0.51, "confirm_score": 0.42, "candidate_source": "catalyst_theme_shadow", "hot_theme_board": "AI Agent", "entry_status": "not_confirmed"}],
                    }
                ]
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def test_generate_btst_early_runner_daily_tables_writes_trade_date_tables(tmp_path: Path) -> None:
    reports_root = tmp_path / "data" / "reports"
    _write_analysis(reports_root / "btst_early_runner_v1_latest.json")

    result = generate_btst_early_runner_daily_tables(reports_root)

    assert result["status"] == "refreshed"
    assert result["table_count"] == 3
    assert result["latest_trade_date"] == "2026-03-24"
    latest_table_keys = {row["table_key"] for row in result["latest_tables"]}
    assert latest_table_keys == {"early_runner_watchlist", "early_runner_priority", "second_entry_reentry"}
    output_dir = Path(result["output_dir"])
    assert (output_dir / "btst_early_runner_watchlist_2026-03-24.json").exists()
    assert (output_dir / "btst_early_runner_priority_2026-03-24.md").exists()
