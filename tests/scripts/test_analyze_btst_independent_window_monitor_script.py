from __future__ import annotations

import json
from pathlib import Path

from scripts.analyze_btst_independent_window_monitor import (
    analyze_btst_independent_window_monitor,
    render_btst_independent_window_monitor_markdown,
)


def _write_snapshot(report_dir: Path, trade_date: str, rows: list[dict]) -> None:
    snapshot_dir = report_dir / "selection_artifacts" / trade_date
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "trade_date": trade_date.replace("-", ""),
        "rows": rows,
    }
    (snapshot_dir / "selection_snapshot.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def test_analyze_btst_independent_window_monitor_tracks_second_window_readiness(tmp_path: Path) -> None:
    reports_root = tmp_path / "data" / "reports"

    window_a = reports_root / "paper_trading_window_20260323_20260326_live_m2_7_dual_target_replay_input_validation_20260329"
    window_b = reports_root / "paper_trading_window_20260327_20260328_live_m2_7_dual_target_replay_input_validation_20260330"

    _write_snapshot(
        window_a,
        "2026-03-24",
        [
            {"ticker": "001309", "candidate_source": "short_trade_boundary", "short_trade": {"decision": "near_miss"}},
            {"ticker": "300113", "candidate_source": "short_trade_boundary", "short_trade": {"decision": "near_miss"}},
        ],
    )
    _write_snapshot(
        window_b,
        "2026-03-27",
        [
            {"ticker": "001309", "candidate_source": "short_trade_boundary", "short_trade": {"decision": "selected"}},
        ],
    )

    analysis = analyze_btst_independent_window_monitor(reports_root)

    rows = {row["ticker"]: row for row in analysis["rows"]}
    assert analysis["report_dir_count"] == 2
    assert analysis["ready_lane_count"] == 1
    assert analysis["waiting_lane_count"] == 1
    assert analysis["no_evidence_lane_count"] == 1

    assert rows["001309"]["readiness"] == "ready_for_reassessment"
    assert rows["001309"]["distinct_window_count"] == 2
    assert rows["001309"]["missing_window_count"] == 0

    assert rows["300113"]["readiness"] == "await_new_independent_window_data"
    assert rows["300113"]["distinct_window_count"] == 1
    assert rows["300113"]["missing_window_count"] == 1

    assert rows["600821"]["readiness"] == "no_short_trade_window_evidence"
    assert rows["600821"]["distinct_window_count"] == 0
    assert rows["600821"]["missing_window_count"] == 2

    markdown = render_btst_independent_window_monitor_markdown(analysis)
    assert "# BTST Independent Window Monitor" in markdown
    assert "001309 Primary Roll Forward: readiness=ready_for_reassessment" in markdown
    assert "300113 Recurring Close Candidate: readiness=await_new_independent_window_data" in markdown
    assert "600821 Recurring Intraday Control: readiness=no_short_trade_window_evidence" in markdown


def test_analyze_btst_independent_window_monitor_counts_corridor_shadow_selected_and_near_miss(tmp_path: Path) -> None:
    reports_root = tmp_path / "data" / "reports"
    window_a = reports_root / "paper_trading_20260406_20260406_live_m2_7_short_trade_only_20260407_today_btst"
    window_b = reports_root / "paper_trading_20260415_20260415_live_m2_7_short_trade_only_20260416_today_btst"

    _write_snapshot(
        window_a,
        "2026-04-06",
        [
            {"ticker": "300720", "candidate_source": "upstream_liquidity_corridor_shadow", "short_trade": {"decision": "near_miss"}},
        ],
    )
    _write_snapshot(
        window_b,
        "2026-04-15",
        [
            {"ticker": "300720", "candidate_source": "post_gate_liquidity_competition_shadow", "short_trade": {"decision": "selected"}},
        ],
    )

    analysis = analyze_btst_independent_window_monitor(
        reports_root,
        tickers=["300720"],
        report_name_contains="paper_trading",
    )

    row = analysis["rows"][0]
    assert row["ticker"] == "300720"
    assert row["readiness"] == "ready_for_reassessment"
    assert row["distinct_window_count"] == 2
    assert row["missing_window_count"] == 0
