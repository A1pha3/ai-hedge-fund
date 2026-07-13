import json
import stat
from pathlib import Path

from src.screening.recommendation_tracker import update_tracking_history_from_payload


def test_tracking_accepts_payload_without_report_file(tmp_path: Path) -> None:
    payload = {
        "date": "20260710",
        "run_id": "run-v2",
        "model_version": "model-v2",
        "recommendations": [
            {"ticker": "000001", "name": "平安银行", "score_b": 0.5, "recommended_price": 10.0}
        ],
    }
    updated = update_tracking_history_from_payload(tmp_path, "20260710", payload, use_data_fetcher=lambda *args: [])
    assert updated == 1
    history = json.loads((tmp_path / "tracking_history.json").read_text(encoding="utf-8"))
    assert history["records"][0]["model_version"] == "model-v2"
    assert history["records"][0]["source_run_id"] == "run-v2"
    assert list(tmp_path.glob("auto_screening_*.json")) == []


def test_payload_tracking_exactly_replaces_same_date_and_preserves_other_dates(
    tmp_path: Path,
) -> None:
    history_path = tmp_path / "tracking_history.json"
    history_path.write_text(
        json.dumps(
            {
                "records": [
                    {
                        "ticker": "600000",
                        "recommended_date": "20260709",
                        "recommendation_score": 0.1,
                    },
                    {
                        "ticker": "000001",
                        "recommended_date": "20260710",
                        "recommendation_score": 0.2,
                        "model_version": "orphan-model",
                        "source_run_id": "orphan-run",
                    },
                    {
                        "ticker": "000002",
                        "recommended_date": "20260710",
                        "recommendation_score": 0.3,
                        "model_version": "orphan-model",
                        "source_run_id": "orphan-run",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    payload = {
        "date": "20260710",
        "run_id": "published-run",
        "model_version": "model-new",
        "recommendations": [
            {
                "ticker": "000001",
                "name": "平安银行",
                "score_b": 0.8,
                "recommended_price": 11.0,
            }
        ],
    }

    update_tracking_history_from_payload(
        tmp_path, "20260710", payload, use_data_fetcher=lambda *args: []
    )

    records = json.loads(history_path.read_text(encoding="utf-8"))["records"]
    assert {(row["ticker"], row["recommended_date"]) for row in records} == {
        ("600000", "20260709"),
        ("000001", "20260710"),
    }
    current = next(row for row in records if row["recommended_date"] == "20260710")
    assert current["recommendation_score"] == 0.8
    assert current["model_version"] == "model-new"
    assert current["source_run_id"] == "published-run"


def test_payload_tracking_preserves_labels_only_for_identical_recommendation_identity(
    tmp_path: Path,
) -> None:
    history_path = tmp_path / "tracking_history.json"
    history_path.write_text(
        json.dumps(
            {
                "records": [
                    {
                        "ticker": "000001",
                        "name": "A",
                        "recommended_date": "20260710",
                        "recommended_price": 10.0,
                        "recommendation_score": 0.5,
                        "model_version": "m1",
                        "next_day_return": 2.0,
                        "return_t1_date": "20260711",
                        "tracking_status": "partial",
                    },
                    {
                        "ticker": "000002",
                        "name": "B",
                        "recommended_date": "20260710",
                        "recommended_price": 20.0,
                        "recommendation_score": 0.4,
                        "model_version": "m1",
                        "next_day_return": 3.0,
                        "return_t1_date": "20260711",
                        "tracking_status": "partial",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    payload = {
        "date": "20260710",
        "run_id": "recovery-run",
        "model_version": "m1",
        "recommendations": [
            {"ticker": "000001", "name": "A", "score_b": 0.5, "recommended_price": 10.0},
            {"ticker": "000002", "name": "B", "score_b": 0.9, "recommended_price": 20.0},
        ],
    }

    update_tracking_history_from_payload(
        tmp_path, "20260710", payload, use_data_fetcher=lambda *args: []
    )

    rows = {
        row["ticker"]: row
        for row in json.loads(history_path.read_text(encoding="utf-8"))["records"]
    }
    assert rows["000001"]["next_day_return"] == 2.0
    assert rows["000001"]["return_t1_date"] == "20260711"
    assert rows["000002"]["next_day_return"] is None
    assert rows["000002"]["return_t1_date"] is None
    assert rows["000001"]["source_run_id"] == "recovery-run"


def test_tracking_save_uses_durable_atomic_primitive_and_preserves_mode(
    tmp_path: Path,
) -> None:
    history_path = tmp_path / "tracking_history.json"
    history_path.write_text('{"records": []}', encoding="utf-8")
    history_path.chmod(0o640)
    payload = {
        "date": "20260710",
        "run_id": "mode-run",
        "model_version": "m1",
        "recommendations": [
            {"ticker": "000001", "score_b": 0.5, "recommended_price": 10.0}
        ],
    }

    update_tracking_history_from_payload(
        tmp_path, "20260710", payload, use_data_fetcher=lambda *args: []
    )

    assert stat.S_IMODE(history_path.stat().st_mode) == 0o640
    assert list(tmp_path.glob(".tracking_history.json.*.tmp")) == []


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
