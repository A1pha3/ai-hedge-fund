from __future__ import annotations

import json
from pathlib import Path

from src.screening.composite_score import CompositeReport
from src.screening.expected_return import ExpectedReturnReport


def _write_context(reports_dir: Path) -> dict:
    payload = {
        "date": "20260710",
        "model_version": "model-v2",
        "recommendations": [{"ticker": "X", "name": "X", "score_b": 0.5}],
    }
    (reports_dir / "auto_screening_20260709.json").write_text(
        json.dumps({"date": "20260709", "recommendations": []}),
        encoding="utf-8",
    )
    (reports_dir / "auto_screening_20260710.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )
    (reports_dir / "tracking_history.json").write_text(
        json.dumps({"records": [{"ticker": "OLD"}]}), encoding="utf-8"
    )
    return payload


def test_main_investability_passes_one_explicit_snapshot(
    tmp_path: Path, monkeypatch
) -> None:
    import src.main as main
    from src.screening import composite_score, expected_return

    payload = _write_context(tmp_path)
    captured: dict[str, dict] = {}
    monkeypatch.setattr(main, "_resolve_consecutive_report_dir", lambda: tmp_path)
    monkeypatch.setattr(main, "_compute_model_version", lambda: "model-v2")
    monkeypatch.setattr(
        composite_score,
        "compute_composite_scores_for_recommendations",
        lambda **kwargs: captured.setdefault("composite", kwargs)
        and CompositeReport(trade_date="20260710"),
    )
    monkeypatch.setattr(
        expected_return,
        "compute_expected_returns",
        lambda **kwargs: captured.setdefault("expected", kwargs)
        and ExpectedReturnReport("20260710", 60, 0),
    )
    monkeypatch.setattr(
        main, "rank_recommendations_by_investability", lambda recs, *_: recs
    )

    main._rank_pool_by_investability(payload["recommendations"], "20260710")

    assert captured["expected"]["as_of"] == "20260710"
    assert captured["expected"]["model_version"] == "model-v2"
    assert captured["expected"]["history_records"] == [{"ticker": "OLD"}]
    assert captured["composite"]["as_of"] == "20260710"
    assert len(captured["composite"]["history_reports"]) == 2
    assert "reports_dir" not in captured["expected"]
    assert "reports_dir" not in captured["composite"]


def test_decision_flow_propagates_report_identity_and_snapshots(
    tmp_path: Path, monkeypatch
) -> None:
    from src.screening import composite_score, expected_return
    from src.screening.decision_flow import run_decision_flow

    _write_context(tmp_path)
    captured: dict[str, dict] = {}
    monkeypatch.setattr(
        expected_return,
        "compute_expected_returns",
        lambda **kwargs: captured.setdefault("expected", kwargs)
        and ExpectedReturnReport("20260710", 5, 0),
    )
    monkeypatch.setattr(
        composite_score,
        "compute_composite_scores_for_recommendations",
        lambda **kwargs: captured.setdefault("composite", kwargs)
        and CompositeReport(trade_date="20260710"),
    )

    run_decision_flow(top_n=1, reports_dir=tmp_path)

    assert captured["expected"]["as_of"] == "20260710"
    assert captured["expected"]["model_version"] == "model-v2"
    assert captured["expected"]["history_records"] == [{"ticker": "OLD"}]
    assert captured["composite"]["trade_date"] == "20260710"
    assert captured["composite"]["as_of"] == "20260710"
    assert "reports_dir" not in captured["expected"]
    assert "reports_dir" not in captured["composite"]


def test_decision_flow_does_not_invent_missing_report_date(
    tmp_path: Path, monkeypatch
) -> None:
    from src.screening import composite_score, expected_return
    from src.screening.decision_flow import run_decision_flow

    (tmp_path / "auto_screening_20260710.json").write_text(
        json.dumps(
            {
                "model_version": "model-v2",
                "recommendations": [{"ticker": "X", "score_b": 0.5}],
            }
        ),
        encoding="utf-8",
    )
    captured: dict[str, dict] = {}
    monkeypatch.setattr(
        expected_return,
        "compute_expected_returns",
        lambda **kwargs: captured.setdefault("expected", kwargs)
        and ExpectedReturnReport("", 5, 0),
    )
    monkeypatch.setattr(
        composite_score,
        "compute_composite_scores_for_recommendations",
        lambda **kwargs: captured.setdefault("composite", kwargs)
        and CompositeReport(),
    )

    run_decision_flow(top_n=1, reports_dir=tmp_path)

    assert captured["expected"]["as_of"] == ""
    assert captured["composite"]["trade_date"] == ""
    assert captured["composite"]["as_of"] == ""


def test_expected_return_cli_passes_exact_report_snapshot(
    tmp_path: Path, monkeypatch
) -> None:
    from src.cli import dispatcher
    from src.screening import consecutive_recommendation, expected_return

    _write_context(tmp_path)
    captured: dict = {}
    monkeypatch.setattr(
        consecutive_recommendation, "resolve_report_dir", lambda: tmp_path
    )
    monkeypatch.setattr(
        expected_return,
        "compute_expected_returns",
        lambda **kwargs: captured.update(kwargs)
        or ExpectedReturnReport("20260710", 60, 0),
    )

    assert dispatcher._resolve_expected_returns(["--expected-returns"]) == 0
    assert captured["as_of"] == "20260710"
    assert captured["model_version"] == "model-v2"
    assert captured["history_records"] == [{"ticker": "OLD"}]
    assert "reports_dir" not in captured


def test_top_picks_ranker_consumes_supplied_snapshots_only(
    tmp_path: Path, monkeypatch
) -> None:
    from src.screening import top_picks

    captured: dict[str, dict] = {}
    monkeypatch.setattr(
        top_picks,
        "compute_composite_scores_for_recommendations",
        lambda **kwargs: captured.setdefault("composite", kwargs)
        and CompositeReport(trade_date="20260710"),
    )
    monkeypatch.setattr(
        top_picks,
        "compute_expected_returns",
        lambda **kwargs: captured.setdefault("expected", kwargs)
        and ExpectedReturnReport("20260710", 60, 0),
    )

    top_picks._build_ranked_candidates(
        [{"ticker": "X", "score_b": 0.5}],
        tmp_path,
        5,
        trade_date="20260710",
        model_version="model-v2",
        history_records=[{"ticker": "OLD"}],
        history_reports=[{"date": "20260709", "recommendations": []}],
    )

    assert captured["expected"]["as_of"] == "20260710"
    assert captured["expected"]["model_version"] == "model-v2"
    assert captured["composite"]["as_of"] == "20260710"
    assert "reports_dir" not in captured["expected"]
    assert "reports_dir" not in captured["composite"]


def test_main_top_display_uses_report_identity_and_supplied_tracking(
    tmp_path: Path, monkeypatch
) -> None:
    import src.main as main
    from src.screening import expected_return, signal_fusion

    captured: dict = {}
    monkeypatch.setattr(
        signal_fusion.FusedScore,
        "model_validate",
        lambda value: object(),
    )
    monkeypatch.setattr(main, "_print_score_decomposition", lambda *args: None)
    monkeypatch.setattr(main, "_print_score_waterfall", lambda *args: None)
    monkeypatch.setattr(
        expected_return,
        "compute_expected_returns",
        lambda **kwargs: captured.update(kwargs)
        or ExpectedReturnReport("20260710", 60, 0),
    )

    main._print_top_score_enhancements(
        [{"ticker": "X", "score_b": 0.5}],
        1,
        tmp_path / "auto_screening_20260710.json",
        trade_date="20260710",
        model_version="model-v2",
        history_records=[{"ticker": "OLD"}],
    )

    assert captured["as_of"] == "20260710"
    assert captured["model_version"] == "model-v2"
    assert captured["history_records"] == [{"ticker": "OLD"}]
    assert "reports_dir" not in captured
