from __future__ import annotations

import json

from src.execution.merge_approved_loader import load_merge_approved_tickers


def test_load_merge_approved_tickers_unions_explicit_and_ready_artifacts(tmp_path) -> None:
    merge_review_path = tmp_path / "btst_default_merge_review_latest.json"
    merge_review_path.write_text(
        json.dumps(
            {
                "focus_ticker": "300720",
                "merge_review_verdict": "ready_for_default_btst_merge_review",
            }
        ),
        encoding="utf-8",
    )
    merge_ranking_path = tmp_path / "btst_continuation_merge_candidate_ranking_latest.json"
    merge_ranking_path.write_text(
        json.dumps(
            {
                "top_candidate": {
                    "ticker": "300720",
                    "promotion_path_status": "merge_review_ready",
                }
            }
        ),
        encoding="utf-8",
    )

    tickers = load_merge_approved_tickers(
        explicit_tickers={"300505"},
        merge_review_path=merge_review_path,
        merge_ranking_path=merge_ranking_path,
    )

    assert tickers == {"300505", "300720"}
