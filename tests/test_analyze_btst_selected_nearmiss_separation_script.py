from __future__ import annotations

import json
from pathlib import Path

from scripts.analyze_btst_selected_nearmiss_separation import (
    analyze_btst_selected_nearmiss_separation,
    main,
)


def _write_json(path: Path, payload: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _selection_target(ticker: str, decision: str, gate: str) -> dict:
    return {
        "ticker": ticker,
        "trade_date": "2026-04-22",
        "btst_regime_gate": gate,
        "short_trade": {
            "decision": decision,
        },
    }


class TestAnalyzeBtstSelectedNearmissSeparation:
    def test_analysis_returns_required_shape_and_recommendation(self, monkeypatch, tmp_path: Path) -> None:
        report_dir = tmp_path / "paper_trading_window_sample"
        _write_json(
            report_dir / "selection_artifacts" / "2026-04-22" / "selection_snapshot.json",
            {
                "trade_date": "2026-04-22",
                "selection_targets": {
                    "000001": _selection_target("000001", "selected", "normal_trade"),
                    "000002": _selection_target("000002", "near_miss", "shadow_only"),
                    "000003": _selection_target("000003", "near_miss", "normal_trade"),
                },
            },
        )

        def fake_generate_realized_prices(*, signal_date: str, tickers: list[str]) -> dict[str, dict[str, object]]:
            assert signal_date == "2026-04-22"
            assert sorted(tickers) == ["000001", "000002", "000003"]
            return {
                "000001": {"data_status": "ok", "next_open_return": -0.005, "next_close_return": 0.01, "max_high_t1_t5_from_open": 0.16},
                "000002": {"data_status": "ok", "next_open_return": 0.002, "next_close_return": -0.01, "max_high_t1_t5_from_open": 0.10},
                "000003": {"data_status": "ok", "next_open_return": 0.001, "next_close_return": 0.02, "max_high_t1_t5_from_open": 0.20},
            }

        monkeypatch.setattr(
            "scripts.analyze_btst_selected_nearmiss_separation.generate_realized_prices",
            fake_generate_realized_prices,
        )

        result = analyze_btst_selected_nearmiss_separation(report_dir)

        assert result["report_type"] == "p4_btst_selected_nearmiss_separation"
        assert result["snapshot_count"] == 1
        assert result["decision_counts"] == {"selected": 1, "near_miss": 2}
        assert result["gate_counts"] == {"normal_trade": 2, "shadow_only": 1}
        assert result["decision_gate_counts"]["selected"] == {"normal_trade": 1}
        assert result["decision_gate_counts"]["near_miss"] == {"normal_trade": 1, "shadow_only": 1}
        assert result["recommendation"] in {"go", "shadow_only", "rollback"}
        assert "decision_outcomes" in result
        assert result["decision_outcomes"]["selected"]["hit_rate_5d_15"] == 1.0
        assert result["decision_outcomes"]["near_miss"]["hit_rate_5d_15"] == 0.5
        assert "decision_gate_outcomes" in result
        assert result["decision_gate_outcomes"]["selected"]["normal_trade"]["hit_rate_5d_15"] == 1.0

    def test_script_writes_required_json_and_markdown_outputs(self, monkeypatch, tmp_path: Path) -> None:
        report_dir = tmp_path / "paper_trading_window_sample"
        output_dir = tmp_path / "reports"
        _write_json(
            report_dir / "selection_artifacts" / "2026-04-22" / "selection_snapshot.json",
            {
                "trade_date": "2026-04-22",
                "selection_targets": {
                    "000001": _selection_target("000001", "selected", "normal_trade"),
                    "000002": _selection_target("000002", "near_miss", "shadow_only"),
                },
            },
        )

        def fake_generate_realized_prices(*, signal_date: str, tickers: list[str]) -> dict[str, dict[str, object]]:
            assert signal_date == "2026-04-22"
            assert sorted(tickers) == ["000001", "000002"]
            return {
                "000001": {"data_status": "ok", "next_open_return": 0.0, "next_close_return": 0.01, "max_high_t1_t5_from_open": 0.15},
                "000002": {"data_status": "ok", "next_open_return": 0.0, "next_close_return": -0.01, "max_high_t1_t5_from_open": 0.10},
            }

        monkeypatch.setattr(
            "scripts.analyze_btst_selected_nearmiss_separation.generate_realized_prices",
            fake_generate_realized_prices,
        )

        main([str(report_dir), "--output-dir", str(output_dir)])

        json_path = output_dir / "p4_btst_selected_nearmiss_separation.json"
        md_path = output_dir / "p4_btst_selected_nearmiss_separation.md"
        assert json_path.exists()
        assert md_path.exists()

        payload = json.loads(json_path.read_text(encoding="utf-8"))
        markdown = md_path.read_text(encoding="utf-8")
        assert payload["report_type"] == "p4_btst_selected_nearmiss_separation"
        assert "recommendation" in payload
        assert "Selected vs Near Miss Separation" in markdown
