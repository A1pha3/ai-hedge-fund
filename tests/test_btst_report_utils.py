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
from src.paper_trading.btst_reporting_utils import (
    _load_btst_rollout_validation_context,
    _load_json,
    _load_selection_replay_input,
)


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


def test_r101_load_json_corrupt_file_degrades_to_empty_dict(tmp_path: Path) -> None:
    """R101 (R88/BH-017 family): ``_load_json`` previously used bare
    ``json.loads`` and raised ``JSONDecodeError`` on a corrupt sidecar
    (run interruption / partial write / disk error), propagating up through
    callers like ``_load_selection_replay_input`` (which only guards *missing*
    files via ``.exists()``) and crashing the entire BTST reporting path when
    ``reports/`` contained one corrupt sibling. Corrupt -> degrade to empty
    dict (consistent with the missing-file semantics all callers tolerate via
    ``payload.get(...) or {}``) + warning diagnostic. Distinct from
    ``read_outcome_ledger``'s deliberate explicit-validate-raise contract.
    """
    corrupt = tmp_path / "replay_input.json"
    corrupt.write_text("{corrupt not json", encoding="utf-8")

    # _load_json: corrupt -> empty dict, no raise.
    assert _load_json(corrupt) == {}
    # _load_json: valid -> parsed payload (no regression).
    valid = tmp_path / "valid.json"
    valid.write_text('{"k": 1}', encoding="utf-8")
    assert _load_json(valid) == {"k": 1}


def test_r101_load_selection_replay_input_corrupt_sibling_does_not_crash(
    tmp_path: Path, caplog
) -> None:
    """R101 caller-path: corrupt ``selection_target_replay_input.json`` sibling
    of a valid ``selection_snapshot.json`` must NOT crash
    ``_load_selection_replay_input``; degrade to ``{}`` + warning (operator
    can distinguish "no sibling" vs "sibling corrupt")."""
    snap = tmp_path / "selection_snapshot.json"
    snap.write_text("{}", encoding="utf-8")
    replay = tmp_path / "selection_target_replay_input.json"
    replay.write_text("{corrupt", encoding="utf-8")

    with caplog.at_level("WARNING", logger="src.paper_trading.btst_reporting_utils"):
        out = _load_selection_replay_input(snap)
    assert out == {}
    assert any("损坏" in rec.message for rec in caplog.records)