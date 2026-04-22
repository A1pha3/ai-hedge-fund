from __future__ import annotations

import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MERGE_REVIEW_PATH = REPO_ROOT / "data/reports/btst_default_merge_review_latest.json"
DEFAULT_MERGE_RANKING_PATH = REPO_ROOT / "data/reports/btst_continuation_merge_candidate_ranking_latest.json"
READY_FOR_DEFAULT_BTST_MERGE_REVIEW = "ready_for_default_btst_merge_review"
MERGE_REVIEW_READY = "merge_review_ready"
LEGACY_DEFAULT_BTST_MERGE_REVIEW_PENDING = "default_btst_merge_review_pending"
DEFAULT_BTST_MERGE_APPROVED_EXECUTION_ACTIVE = "default_btst_merge_approved_execution_active"


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def is_merge_approved_execution_blocker(value: str | None) -> bool:
    return str(value or "").strip() in {
        LEGACY_DEFAULT_BTST_MERGE_REVIEW_PENDING,
        DEFAULT_BTST_MERGE_APPROVED_EXECUTION_ACTIVE,
    }


def load_merge_approved_tickers(
    *,
    explicit_tickers: set[str] | None = None,
    merge_review_path: str | Path | None = DEFAULT_MERGE_REVIEW_PATH,
    merge_ranking_path: str | Path | None = DEFAULT_MERGE_RANKING_PATH,
) -> set[str]:
    tickers = {str(ticker).strip() for ticker in list(explicit_tickers or set()) if str(ticker).strip()}
    ranking_fallback_allowed = True

    resolved_merge_review_path = Path(merge_review_path).expanduser().resolve() if merge_review_path else DEFAULT_MERGE_REVIEW_PATH
    if resolved_merge_review_path.exists():
        merge_review = _load_json(resolved_merge_review_path)
        focus_ticker = str(merge_review.get("focus_ticker") or "").strip()
        merge_review_verdict = str(merge_review.get("merge_review_verdict") or "").strip()
        if focus_ticker and merge_review_verdict:
            ranking_fallback_allowed = merge_review_verdict == READY_FOR_DEFAULT_BTST_MERGE_REVIEW
        if focus_ticker and merge_review_verdict == READY_FOR_DEFAULT_BTST_MERGE_REVIEW:
            tickers.add(focus_ticker)

    resolved_merge_ranking_path = Path(merge_ranking_path).expanduser().resolve() if merge_ranking_path else DEFAULT_MERGE_RANKING_PATH
    if ranking_fallback_allowed and resolved_merge_ranking_path.exists():
        merge_ranking = _load_json(resolved_merge_ranking_path)
        top_candidate = dict(merge_ranking.get("top_candidate") or {})
        top_ticker = str(top_candidate.get("ticker") or "").strip()
        top_stage = str(top_candidate.get("promotion_path_status") or top_candidate.get("promotion_readiness_verdict") or "").strip()
        if top_ticker and top_stage == MERGE_REVIEW_READY:
            tickers.add(top_ticker)

    return tickers
