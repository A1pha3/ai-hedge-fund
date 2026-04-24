from __future__ import annotations

import json
from pathlib import Path

from scripts.analyze_btst_prior_shrinkage_eval import (
    analyze_btst_prior_shrinkage_eval,
    main,
)


def _write_json(path: Path, payload: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _selection_target(ticker: str, decision: str, evaluable_count: int, sample_reliability: float, raw_high: float, shrunk_high: float, raw_close: float, shrunk_close: float) -> dict:
    return {
        "ticker": ticker,
        "trade_date": "2026-04-22",
        "short_trade": {
            "decision": decision,
            "metrics_payload": {
                "historical_prior": {
                    "evaluable_count": evaluable_count,
                    "sample_reliability": sample_reliability,
                    "raw_next_high_hit_rate_at_threshold": raw_high,
                    "shrunk_high_hit_rate": shrunk_high,
                    "raw_next_close_positive_rate": raw_close,
                    "shrunk_close_positive_rate": shrunk_close,
                }
            },
        },
    }


class TestAnalyzeBtstPriorShrinkageEval:
    def test_analysis_returns_required_top_level_keys(self, tmp_path: Path) -> None:
        report_dir = tmp_path / "paper_trading_window_sample"
        _write_json(
            report_dir / "selection_artifacts" / "2026-04-22" / "selection_snapshot.json",
            {
                "trade_date": "2026-04-22",
                "selection_targets": {
                    "000001": _selection_target("000001", "selected", 2, 0.2, 1.0, 0.72, 1.0, 0.66),
                    "000002": _selection_target("000002", "near_miss", 12, 0.75, 0.8, 0.78, 0.76, 0.74),
                },
            },
        )

        result = analyze_btst_prior_shrinkage_eval(report_dir)

        assert result["report_type"] == "p4_btst_prior_shrinkage_eval"
        assert result["snapshot_count"] == 1
        assert "comparison_summary" in result
        assert "raw_vs_shrunk_comparison_samples" in result
        assert result["raw_vs_shrunk_comparison_samples"]

    def test_script_writes_required_json_and_markdown_outputs(self, tmp_path: Path) -> None:
        report_dir = tmp_path / "paper_trading_window_sample"
        output_dir = tmp_path / "reports"
        _write_json(
            report_dir / "selection_artifacts" / "2026-04-22" / "selection_snapshot.json",
            {
                "trade_date": "2026-04-22",
                "selection_targets": {
                    "000001": _selection_target("000001", "selected", 2, 0.2, 1.0, 0.72, 1.0, 0.66),
                },
            },
        )

        main([str(report_dir), "--output-dir", str(output_dir)])

        json_path = output_dir / "p4_btst_prior_shrinkage_eval.json"
        md_path = output_dir / "p4_btst_prior_shrinkage_eval.md"
        assert json_path.exists()
        assert md_path.exists()
        payload = json.loads(json_path.read_text(encoding="utf-8"))
        markdown = md_path.read_text(encoding="utf-8")
        assert payload["report_type"] == "p4_btst_prior_shrinkage_eval"
        assert "raw_vs_shrunk_comparison_samples" in payload
        assert "Raw vs Shrunk Comparison Samples" in markdown
