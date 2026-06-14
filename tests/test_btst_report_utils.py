from __future__ import annotations

import json
from pathlib import Path

from scripts.btst_report_utils import (
    discover_nested_report_dirs,
    discover_report_dirs,
    load_json,
    normalize_trade_date,
    safe_load_json,
)
from src.paper_trading.btst_reporting_utils import _load_btst_rollout_validation_context


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def test_btst_report_utils_json_helpers_and_trade_date_normalization(tmp_path: Path) -> None:
    payload_path = tmp_path / "payload.json"
    _write_json(payload_path, {"trade_date": "20260330"})

    assert load_json(payload_path) == {"trade_date": "20260330"}
    assert safe_load_json(payload_path) == {"trade_date": "20260330"}
    assert safe_load_json(tmp_path / "missing.json") == {}
    assert normalize_trade_date("20260330") == "2026-03-30"
    assert normalize_trade_date("2026-03-30") == "2026-03-30"
    assert normalize_trade_date("bad-token") is None


def test_btst_report_utils_discover_report_dirs_supports_report_dir_and_root_filter(tmp_path: Path) -> None:
    report_root = tmp_path / "reports"
    matching_report = report_root / "paper_trading_window_foo"
    ignored_report = report_root / "other_report"

    for report_dir in (matching_report, ignored_report):
        trade_dir = report_dir / "selection_artifacts" / "2026-03-23"
        trade_dir.mkdir(parents=True)
        (report_dir / "session_summary.json").write_text("{}\n", encoding="utf-8")
        (trade_dir / "selection_snapshot.json").write_text("{}\n", encoding="utf-8")

    assert discover_report_dirs(matching_report) == [matching_report.resolve()]
    assert discover_report_dirs(report_root, report_name_contains="paper_trading_window_") == [matching_report.resolve()]


def test_btst_report_utils_discover_nested_report_dirs_scans_recursively_without_session_summary(tmp_path: Path) -> None:
    report_root = tmp_path / "nested" / "reports"
    matching_report = report_root / "paper_trading_window_bar"
    ignored_report = report_root / "other_report"

    for report_dir in (matching_report, ignored_report):
        trade_dir = report_dir / "selection_artifacts" / "2026-03-24"
        trade_dir.mkdir(parents=True)
        (trade_dir / "selection_snapshot.json").write_text("{}\n", encoding="utf-8")

    assert discover_nested_report_dirs([tmp_path], report_name_contains="paper_trading_window_") == [matching_report.resolve()]


def test_load_btst_rollout_validation_context_prefers_latest_report(tmp_path: Path) -> None:
    reports_root = tmp_path / "data" / "reports"
    reports_root.mkdir(parents=True)
    older = reports_root / "btst_layer_c_rollout_validation_20260518_20260522.json"
    newer = reports_root / "btst_layer_c_rollout_validation_20260506_20260522.json"
    _write_json(older, {"recommendation": {"status": "hold_for_more_validation"}})
    _write_json(
        newer,
        {
            "payoff_summary": {
                "selected_hit_rate_15pct": 0.3077,
                "shadow_hit_rate_15pct": 0.3333,
            },
            "replay_summary": {
                "selected_count_delta": -5,
                "execution_eligible_delta": -3,
                "buy_order_delta": -3,
            },
            "recommendation": {
                "status": "governed_shadow_ready",
                "primary_lane": "layer_c_formal_precision_tightening",
                "summary": "先收 formal buy。",
            },
        },
    )

    context = _load_btst_rollout_validation_context(report_dir=reports_root / "paper_trading_20260522_foo")

    assert context["status"] == "governed_shadow_ready"
    assert context["source_json_path"] == newer.resolve().as_posix()
    assert context["shadow_hit_rate_15pct"] == 0.3333
    assert context["execution_eligible_delta"] == -3