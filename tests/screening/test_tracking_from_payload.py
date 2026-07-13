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


def test_auto_enrichment_tracks_the_exact_in_memory_payload(tmp_path: Path, monkeypatch) -> None:
    import src.main as main

    payload = {"date": "20260710", "recommendations": []}
    received: dict = {}

    def track_from_payload(reports_dir, trade_date, report_payload):
        received.update(
            reports_dir=reports_dir,
            trade_date=trade_date,
            report_payload=report_payload,
        )
        return 0

    monkeypatch.setattr(main, "update_tracking_history_from_payload", track_from_payload)
    monkeypatch.setattr(main, "get_tracking_summary", lambda **kwargs: {"total_recommendations": 0})
    monkeypatch.setattr(main, "update_watchlist_from_screening", lambda report: {"scored_count": 0})

    main._enrich_recommendations_with_history(payload, "20260710", tmp_path)

    assert received == {
        "reports_dir": tmp_path,
        "trade_date": "20260710",
        "report_payload": payload,
    }
    assert list(tmp_path.glob("auto_screening_*.json")) == []
