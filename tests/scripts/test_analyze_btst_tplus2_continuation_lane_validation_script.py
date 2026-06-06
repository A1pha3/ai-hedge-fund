from __future__ import annotations

from pathlib import Path

import scripts.analyze_btst_tplus2_continuation_lane_validation as lane_validation


def test_analyze_btst_tplus2_continuation_lane_validation_supports_tplus2_edge(monkeypatch, tmp_path: Path) -> None:
    reports_root = tmp_path / "reports"
    reports_root.mkdir()

    monkeypatch.setattr(
        lane_validation,
        "generate_btst_tplus2_continuation_observation_pool",
        lambda *_args, **_kwargs: {
            "entries": [{"ticker": "600988"}],
        },
    )
    monkeypatch.setattr(
        lane_validation,
        "_collect_rows",
        lambda *_args, **_kwargs: [
            {
                "report_label": "window_a",
                "ticker": "600988",
                "decision": "rejected",
                "next_open_return": 0.01,
                "next_high_return": 0.04,
                "next_close_return": -0.01,
                "next_open_to_close_return": -0.02,
                "t_plus_2_close_return": 0.03,
            },
            {
                "report_label": "window_b",
                "ticker": "600988",
                "decision": "rejected",
                "next_open_return": 0.02,
                "next_high_return": 0.05,
                "next_close_return": 0.01,
                "next_open_to_close_return": -0.01,
                "t_plus_2_close_return": 0.04,
            },
        ],
    )

    analysis = lane_validation.analyze_btst_tplus2_continuation_lane_validation(reports_root)

    assert analysis["lane_row_count"] == 2
    assert analysis["decision_counts"] == {"rejected": 2}
    assert len(analysis["per_window_summaries"]) == 2
    assert analysis["per_window_summaries"][0]["window_verdict"] == "supports_tplus2_lane"
    assert analysis["recommendation"].startswith("Lane validation supports")

    markdown = lane_validation.render_btst_tplus2_continuation_lane_validation_markdown(analysis)
    assert "# BTST T+2 Continuation Lane Validation" in markdown
    assert "window_a" in markdown
