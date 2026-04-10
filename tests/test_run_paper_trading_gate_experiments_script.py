from __future__ import annotations

import json
from pathlib import Path

from scripts.run_paper_trading_gate_experiments import _build_frozen_gate_margin_scan


def _write_selection_snapshot(root: Path, trade_date: str, payload: dict) -> None:
    day_dir = root / "selection_artifacts" / trade_date
    day_dir.mkdir(parents=True, exist_ok=True)
    (day_dir / "selection_snapshot.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_build_frozen_gate_margin_scan_returns_none_without_selection_artifacts(tmp_path: Path) -> None:
    assert _build_frozen_gate_margin_scan(tmp_path, {"DAILY_PIPELINE_FAST_SCORE_THRESHOLD": "0.375"}) is None


def test_build_frozen_gate_margin_scan_collects_fast_and_watchlist_examples(tmp_path: Path) -> None:
    _write_selection_snapshot(
        tmp_path,
        "2026-02-02",
        {
            "trade_date": "2026-02-02",
            "funnel_diagnostics": {
                "filters": {
                    "layer_b": {
                        "tickers": [
                            {"ticker": "300001", "score_b": 0.377, "decision": "filtered_out", "rank": 3},
                            {"ticker": "300002", "score_b": 0.36, "decision": "filtered_out", "rank": 8},
                            {"ticker": "300003", "score_b": None, "decision": "filtered_out", "rank": 9},
                        ]
                    },
                    "watchlist": {
                        "tickers": [
                            {
                                "ticker": "300010",
                                "score_b": 0.41,
                                "score_c": 0.18,
                                "score_final": 0.195,
                                "decision": "watchlist",
                                "bc_conflict": None,
                                "reasons": ["score_gap"],
                            },
                            {
                                "ticker": "300011",
                                "score_b": 0.42,
                                "score_c": 0.17,
                                "score_final": 0.191,
                                "decision": "avoid",
                                "bc_conflict": "conflict",
                                "reason": "avoid_open_chase_confirmation",
                            },
                            {
                                "ticker": "300012",
                                "score_b": 0.44,
                                "score_c": 0.15,
                                "score_final": 0.205,
                                "decision": "watchlist",
                            },
                        ]
                    },
                }
            },
        },
    )

    scan = _build_frozen_gate_margin_scan(
        tmp_path,
        {
            "DAILY_PIPELINE_FAST_SCORE_THRESHOLD": "0.375",
            "DAILY_PIPELINE_WATCHLIST_SCORE_THRESHOLD": "0.19",
        },
    )

    assert scan is not None
    assert scan["fast_threshold_margin"]["released_count"] == 1
    assert scan["fast_threshold_margin"]["released_examples"] == [
        {
            "trade_date": "2026-02-02",
            "ticker": "300001",
            "score_b": 0.377,
            "decision": "filtered_out",
            "rank": 3,
        }
    ]
    assert scan["watchlist_threshold_margin"]["threshold_only_release_count"] == 1
    assert scan["watchlist_threshold_margin"]["threshold_only_release_examples"] == [
        {
            "trade_date": "2026-02-02",
            "ticker": "300010",
            "score_b": 0.41,
            "score_c": 0.18,
            "score_final": 0.195,
            "decision": "watchlist",
            "bc_conflict": None,
            "reasons": ["score_gap"],
        }
    ]
    assert scan["watchlist_threshold_margin"]["still_avoid_blocked_count"] == 1
    assert scan["watchlist_threshold_margin"]["still_avoid_blocked_examples"] == [
        {
            "trade_date": "2026-02-02",
            "ticker": "300011",
            "score_b": 0.42,
            "score_c": 0.17,
            "score_final": 0.191,
            "decision": "avoid",
            "bc_conflict": "conflict",
            "reasons": ["avoid_open_chase_confirmation"],
        }
    ]
