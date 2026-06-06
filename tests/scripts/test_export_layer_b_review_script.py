from __future__ import annotations

import json
from types import SimpleNamespace

import scripts.export_layer_b_review as export_layer_b_review

from scripts.export_layer_b_review import _load_downstream_map


def test_load_downstream_map_includes_layer_b_filtered_tickers(tmp_path) -> None:
    report_dir = tmp_path / "report"
    report_dir.mkdir()

    payload = {
        "event": "paper_trading_day",
        "trade_date": "20260406",
        "current_plan": {
            "date": "20260406",
            "watchlist": [],
            "buy_orders": [],
            "risk_metrics": {
                "funnel_diagnostics": {
                    "filters": {
                        "watchlist": {"tickers": []},
                        "layer_b": {
                            "tickers": [
                                {
                                    "ticker": "600089",
                                    "reason": "below_fast_score_threshold",
                                    "score_b": 0.2685,
                                    "decision": "neutral",
                                    "rank": 7,
                                }
                            ]
                        },
                    }
                }
            },
        },
    }
    (report_dir / "daily_events.jsonl").write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")

    downstream_map = _load_downstream_map(report_dir)

    assert downstream_map["20260406"]["600089"]["layer_c_status"] == "filtered_after_layer_b"
    assert downstream_map["20260406"]["600089"]["decision_c"] == "neutral"
    assert downstream_map["20260406"]["600089"]["downstream_reason"] == "below_fast_score_threshold"


class _FakeSignal:
    def __init__(self, *, direction: int = 1, confidence: float = 60.0, completeness: float = 1.0) -> None:
        self._payload = {
            "direction": direction,
            "confidence": confidence,
            "completeness": completeness,
        }

    def model_dump(self) -> dict[str, float | int]:
        return dict(self._payload)


def test_build_rows_leaves_layer_c_scores_blank_for_layer_b_filtered_entries(monkeypatch) -> None:
    monkeypatch.setattr(
        export_layer_b_review,
        "build_candidate_pool",
        lambda trade_date, use_cache=True: [
            SimpleNamespace(ticker="600089", name="示例股", industry_sw="银行", market_cap=10.0)
        ],
    )
    monkeypatch.setattr(
        export_layer_b_review,
        "detect_market_state",
        lambda trade_date: SimpleNamespace(state_type="normal", adjusted_weights={}),
    )
    monkeypatch.setattr(export_layer_b_review, "score_batch", lambda candidates, trade_date: candidates)
    monkeypatch.setattr(
        export_layer_b_review,
        "fuse_batch",
        lambda scored, market_state, trade_date: [
            SimpleNamespace(
                ticker="600089",
                score_b=0.2736,
                decision="neutral",
                arbitration_applied=[],
                weights_used={},
                strategy_signals={"trend": _FakeSignal()},
            )
        ],
    )

    rows = export_layer_b_review._build_rows(
        ["20260406"],
        {
            "20260406": {
                "600089": {
                    "layer_c_status": "filtered_after_layer_b",
                    "score_c": None,
                    "score_final": None,
                    "bc_conflict": "",
                    "decision_c": "neutral",
                    "buy_order_entered": False,
                    "downstream_reason": "below_fast_score_threshold",
                }
            }
        },
    )

    assert rows[0]["score_c"] == ""
    assert rows[0]["score_final"] == ""
