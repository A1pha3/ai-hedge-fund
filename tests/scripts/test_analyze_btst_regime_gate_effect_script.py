from __future__ import annotations

import json
from pathlib import Path

from scripts.analyze_btst_regime_gate_effect import analyze_btst_regime_gate_effect


def _write_json(path: Path, payload: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def test_analyze_btst_regime_gate_effect_derives_gate_from_snapshot_market_state(tmp_path: Path) -> None:
    report_dir = tmp_path / "paper_trading_window_sample"
    _write_json(
        report_dir / "selection_artifacts" / "2026-04-06" / "selection_snapshot.json",
        {
            "trade_date": "2026-04-06",
            "market_state": {
                "breadth_ratio": 0.38,
                "daily_return": -0.002,
                "style_dispersion": 0.51,
                "regime_flip_risk": 0.61,
                "regime_gate_level": "risk_off",
            },
            "universe_summary": {"buy_order_count": 1},
            "target_summary": {"short_trade_selected_count": 1, "short_trade_near_miss_count": 0},
        },
    )
    _write_json(
        report_dir / "selection_artifacts" / "2026-04-07" / "selection_snapshot.json",
        {
            "trade_date": "2026-04-07",
            "market_state": {
                "breadth_ratio": 0.66,
                "daily_return": -0.004,
                "style_dispersion": 0.18,
                "regime_flip_risk": 0.08,
                "regime_gate_level": "normal",
            },
            "universe_summary": {"buy_order_count": 2},
            "target_summary": {"short_trade_selected_count": 2, "short_trade_near_miss_count": 1},
        },
    )

    analysis = analyze_btst_regime_gate_effect(report_dir)

    assert analysis["snapshot_count"] == 2
    assert analysis["gate_counts"] == {"aggressive_trade": 1, "halt": 1}
    assert analysis["by_gate"]["halt"]["buy_order_count"] == 1
    assert analysis["by_gate"]["aggressive_trade"]["short_trade_selected_count"] == 2
    assert analysis["recommendation"] == "shadow_only"


def test_analyze_btst_regime_gate_effect_prefers_explicit_gate_payload_when_present(tmp_path: Path) -> None:
    report_dir = tmp_path / "paper_trading_window_sample"
    _write_json(
        report_dir / "selection_artifacts" / "2026-04-08" / "selection_snapshot.json",
        {
            "trade_date": "2026-04-08",
            "btst_regime_gate": {
                "mode": "shadow",
                "gate": "shadow_only",
                "reason_codes": ["profile_conservative"],
            },
            "market_state": {
                "breadth_ratio": 0.65,
                "daily_return": -0.002,
                "style_dispersion": 0.12,
                "regime_flip_risk": 0.08,
                "regime_gate_level": "normal",
            },
            "universe_summary": {"buy_order_count": 0},
            "target_summary": {"short_trade_selected_count": 0, "short_trade_near_miss_count": 3},
        },
    )

    analysis = analyze_btst_regime_gate_effect(report_dir)

    assert analysis["gate_counts"] == {"shadow_only": 1}
    assert analysis["by_gate"]["shadow_only"]["snapshot_count"] == 1


def test_analyze_btst_regime_gate_effect_falls_back_to_daily_events_market_state(tmp_path: Path) -> None:
    report_dir = tmp_path / "paper_trading_window_sample"
    _write_json(
        report_dir / "selection_artifacts" / "2026-04-09" / "selection_snapshot.json",
        {
            "trade_date": "2026-04-09",
            "universe_summary": {"buy_order_count": 1},
            "target_summary": {"short_trade_selected_count": 1, "short_trade_near_miss_count": 2},
        },
    )
    (report_dir / "daily_events.jsonl").write_text(
        json.dumps(
            {
                "trade_date": "20260409",
                "current_plan": {
                    "market_state": {
                        "breadth_ratio": 0.38,
                        "daily_return": -0.001,
                        "style_dispersion": 0.52,
                        "regime_flip_risk": 0.61,
                        "regime_gate_level": "risk_off",
                    }
                },
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    analysis = analyze_btst_regime_gate_effect(report_dir)

    assert analysis["snapshot_count"] == 1
    assert analysis["gate_counts"] == {"halt": 1}
    assert analysis["mode_counts"] == {"derived": 1}
