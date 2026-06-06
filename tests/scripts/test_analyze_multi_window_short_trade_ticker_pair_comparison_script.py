from __future__ import annotations

import json

from scripts.analyze_multi_window_short_trade_ticker_pair_comparison import analyze_multi_window_short_trade_ticker_pair_comparison


def test_analyze_multi_window_short_trade_ticker_pair_comparison_prefers_close_continuation_sample(tmp_path):
    left = tmp_path / "left.json"
    right = tmp_path / "right.json"
    left.write_text(
        json.dumps({"dossier": {"ticker": "001309", "next_high_return_mean": 0.04, "next_close_return_mean": 0.02, "next_close_positive_rate": 0.6667, "short_trade_trade_date_count": 3, "distinct_report_count": 2}}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    right.write_text(
        json.dumps({"dossier": {"ticker": "300620", "next_high_return_mean": 0.05, "next_close_return_mean": 0.0, "next_close_positive_rate": 0.3333, "short_trade_trade_date_count": 3, "distinct_report_count": 2}}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    analysis = analyze_multi_window_short_trade_ticker_pair_comparison(left, right)

    assert analysis["left_ticker"] == "001309"
    assert "close-continuation 优先样本" in analysis["recommendation"]