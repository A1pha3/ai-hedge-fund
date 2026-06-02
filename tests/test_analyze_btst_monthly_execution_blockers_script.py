from __future__ import annotations

import json
from pathlib import Path

import scripts.analyze_btst_monthly_execution_blockers as blk


def test_analyze_btst_monthly_execution_blockers_counts_flags(tmp_path: Path) -> None:
    reports_dir = tmp_path / "data" / "reports"
    reports_dir.mkdir(parents=True)

    plan_dir = reports_dir / "paper_trading_20260506_20260506_live_test_short_trade_only_20260506_plan"
    plan_dir.mkdir(parents=True)

    snap = plan_dir / "selection_snapshot.json"
    snap.write_text(
        json.dumps(
            {
                "market_state": {"regime_gate_level": "risk_off"},
                "selection_targets": {
                    "000001": {
                        "ticker": "000001",
                        "short_trade": {"decision": "selected", "p2_execution_blocked": True},
                        "p2_execution_block_reason": "p2_regime_gate_enforce:halt",
                    },
                    "000002": {"ticker": "000002", "short_trade": {"decision": "near_miss"}, "p5_execution_blocked": True},
                    "000003": {"ticker": "000003", "short_trade": {"decision": "rejected"}, "p2_execution_blocked": True},
                },
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    (plan_dir / "btst_next_day_trade_brief_latest.json").write_text(
        json.dumps(
            {
                "trade_date": "20260506",
                "selected_entries": [],
                "snapshot_path": str(snap),
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    analysis = blk.analyze_btst_monthly_execution_blockers(month="202605", reports_dir=reports_dir)
    overall = analysis["overall"]

    assert overall["blocked_row_count"] == 2
    assert overall["by_block_flag"]["p2_execution_blocked"] == 1
    assert overall["by_block_flag"]["p5_execution_blocked"] == 1
    assert overall["by_p2_block_reason"]["p2_regime_gate_enforce:halt"] == 1

    md = blk.render_btst_monthly_execution_blockers_markdown(analysis)
    assert "BTST Monthly Execution Blockers 202605" in md
    assert "Block flags" in md
    assert "P2 block reasons" in md
