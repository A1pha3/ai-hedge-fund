from __future__ import annotations

import json
from datetime import date

from src.screening.offensive.daily_action_snapshot import load_verified_daily_action_snapshot
from tests.offensive.readiness_v2_testkit import count_plan_created_events, run_full_injected_pipeline


def test_schema_v1_is_read_only_and_has_no_new_entry_authority(tmp_path) -> None:
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir(parents=True)
    (reports_dir / "daily_action_readiness_20260713.json").write_text(
        json.dumps({"schema_version": 1, "trade_date": "2026-07-13"}),
        encoding="utf-8",
    )

    result = load_verified_daily_action_snapshot(date(2026, 7, 13), reports_dir=reports_dir, data_dir=tmp_path)

    assert result.snapshot is None
    assert result.global_reason == "readiness_schema_unsupported"


def test_repeat_verified_run_creates_one_plan_event(tmp_path) -> None:
    first = run_full_injected_pipeline(
        tmp_path,
        auto_tickers={"000001"},
        daily_tickers={"000001", "002999"},
        btst_hit="002999",
    )
    second = run_full_injected_pipeline(
        tmp_path,
        auto_tickers={"000001"},
        daily_tickers={"000001", "002999"},
        btst_hit="002999",
    )

    assert first.ledger_trade is not None
    assert second.ledger_trade is not None
    assert first.ledger_trade.trade_id == second.ledger_trade.trade_id
    assert count_plan_created_events(tmp_path, first.ledger_trade.trade_id) == 1
