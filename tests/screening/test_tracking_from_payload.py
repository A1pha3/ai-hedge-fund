import json
from pathlib import Path

from src.screening.recommendation_tracker import update_tracking_history_from_payload


def test_tracking_accepts_payload_without_report_file(tmp_path: Path) -> None:
    payload = {
        "date": "20260710",
        "model_version": "model-v2",
        "recommendations": [
            {"ticker": "000001", "name": "平安银行", "score_b": 0.5, "recommended_price": 10.0}
        ],
    }
    updated = update_tracking_history_from_payload(tmp_path, "20260710", payload, use_data_fetcher=lambda *args: [])
    assert updated == 1
    history = json.loads((tmp_path / "tracking_history.json").read_text(encoding="utf-8"))
    assert history["records"][0]["model_version"] == "model-v2"
    assert list(tmp_path.glob("auto_screening_*.json")) == []


def test_post_publication_enrichment_does_not_track_or_republish(tmp_path: Path, monkeypatch) -> None:
    import src.main as main

    payload = {"date": "20260710", "recommendations": []}
    monkeypatch.setattr(
        main,
        "_save_json_report",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("canonical must not be republished")),
    )
    monkeypatch.setattr(main, "get_tracking_summary", lambda **kwargs: {"total_recommendations": 0})
    monkeypatch.setattr(main, "update_watchlist_from_screening", lambda report: {"scored_count": 0})

    main._enrich_recommendations_with_history(payload, "20260710", tmp_path)

    assert list(tmp_path.glob("auto_screening_*.json")) == []
