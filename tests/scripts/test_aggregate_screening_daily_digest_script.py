from __future__ import annotations

import importlib.util
import json
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "aggregate_screening_daily_digest.py"


def _load_module() -> object:
    spec = importlib.util.spec_from_file_location("aggregate_screening_daily_digest", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_to_iso_normalizes_compact_and_iso_dates() -> None:
    mod = _load_module()
    assert mod._to_iso("20260602") == "2026-06-02"
    assert mod._to_iso("2026-06-02") == "2026-06-02"
    assert mod._to_iso("2026-06-02T10:00:00+08:00") == ""  # ISO with time rejected
    assert mod._to_iso("f0f00ee31a") == ""  # sha-like rejected
    assert mod._to_iso("") == ""
    assert mod._to_iso(None) == ""  # type: ignore[arg-type]
    # Bad month/day segments are rejected
    assert mod._to_iso("2026-13-02") == ""
    assert mod._to_iso("2026-06-32") == ""
    # Whitespace and lowercase variations are accepted when shape is right
    assert mod._to_iso("  20260602  ") == "2026-06-02"


def test_candidate_pool_count_prefers_top300_then_flat(tmp_path: Path) -> None:
    mod = _load_module()
    compact = "20260602"
    top = tmp_path / f"candidate_pool_{compact}_top300.json"
    top.write_text(json.dumps([{"ticker": "1"}, {"ticker": "2"}]), encoding="utf-8")
    flat = tmp_path / f"candidate_pool_{compact}.json"
    flat.write_text(json.dumps([{"ticker": "1"}] * 5), encoding="utf-8")
    assert mod._candidate_pool_count(tmp_path, "2026-06-02") == 2  # top300 wins


def test_candidate_pool_count_handles_shadow_dict_with_tickers_list(tmp_path: Path) -> None:
    mod = _load_module()
    tmp_path.mkdir(exist_ok=True)
    # Shadow-style dict on the flat variant (no top300) — only "tickers" is
    # populated; selected_candidates is empty.
    flat = tmp_path / "candidate_pool_20260602.json"
    flat.write_text(
        json.dumps({"tickers": ["a", "b", "c"], "selected_candidates": []}),
        encoding="utf-8",
    )
    assert mod._candidate_pool_count(tmp_path, "2026-06-02") == 3
    # When the dict has both keys, the code prefers selected_candidates per
    # the source-of-truth ordering in _candidate_pool_count.
    flat2 = tmp_path / "candidate_pool_20260603.json"
    flat2.write_text(
        json.dumps({"selected_candidates": ["x", "y"], "tickers": ["1", "2", "3"]}),
        encoding="utf-8",
    )
    assert mod._candidate_pool_count(tmp_path, "2026-06-03") == 2


def test_candidate_pool_count_returns_none_when_missing(tmp_path: Path) -> None:
    mod = _load_module()
    assert mod._candidate_pool_count(tmp_path, "2026-06-02") is None


def test_collect_trade_dates_reads_artifact_subdirs_and_snapshot_files(tmp_path: Path) -> None:
    mod = _load_module()
    artifact_root = tmp_path / "artifacts"
    snapshot_root = tmp_path / "snapshots"
    snapshot_root.mkdir(parents=True, exist_ok=True)
    (artifact_root / "2026-06-01").mkdir(parents=True)
    (artifact_root / "2026-06-02").mkdir(parents=True)
    (snapshot_root / "candidate_pool_20260603_top300.json").write_text("[]", encoding="utf-8")
    # Shadow file with hash suffix should NOT contribute bogus date
    (snapshot_root / "candidate_pool_20260603_top300_shadow_f0f00ee31a.json").write_text("{}", encoding="utf-8")
    dates = mod._collect_trade_dates(None, None, snapshot_dir=snapshot_root, artifact_dir=artifact_root)
    # The shadow variant has the same prefix as the top300 file, so the date "2026-06-03" only appears once
    assert dates == ["2026-06-01", "2026-06-02", "2026-06-03"]
    # And no bogus "f0f00ee31a" string leaks into the result
    assert not any("f" in d for d in dates)


def test_collect_trade_dates_respects_window(tmp_path: Path) -> None:
    mod = _load_module()
    artifact_root = tmp_path / "artifacts"
    for iso in ("2026-05-30", "2026-06-01", "2026-06-02", "2026-06-10"):
        (artifact_root / iso).mkdir(parents=True)
    dates = mod._collect_trade_dates(
        "2026-06-01",
        "2026-06-05",
        snapshot_dir=tmp_path / "snaps",
        artifact_dir=artifact_root,
    )
    assert dates == ["2026-06-01", "2026-06-02"]


def test_summarize_snapshot_extracts_decision_and_scores() -> None:
    mod = _load_module()
    snapshot = {
        "selected": [
            {"symbol": "000001", "decision": "buy", "score_final": 0.8, "score_b": 0.7, "score_c": 0.9},
            {"symbol": "000002", "decision": "buy", "score_final": 0.6, "score_b": 0.5, "score_c": 0.7},
        ],
        "rejected": [
            {"symbol": "000003", "decision": "sell", "score_final": -0.3, "score_b": -0.4, "score_c": -0.2},
        ],
        "watchlist": [{"ticker": "000099"}],
        "market_state": {"label": "trend"},
        "btst_regime_gate": {"status": "open"},
        "artifact_status": "complete",
        "experiment_id": "exp_test",
    }
    rollup = mod._summarize_snapshot(snapshot)
    assert rollup["selected_size"] == 2
    assert rollup["rejected_size"] == 1
    assert rollup["watchlist_size"] == 1
    assert rollup["avg_score_final"] == 0.3667  # (0.8+0.6-0.3)/3
    assert rollup["market_state"] == "trend"
    assert rollup["regime_gate_status"] == "open"
    assert rollup["decision_counts"] == {"buy": 2, "sell": 1}
    assert "000001" in rollup["top10_tickers"]
    assert "exp=exp_test" in rollup["notes"]


def test_empty_row_marks_missing_snapshot() -> None:
    mod = _load_module()
    row = mod._empty_row("2026-06-02", 250, "no_selection_snapshot")
    assert row["trade_date"] == "2026-06-02"
    assert row["candidate_pool_size"] == 250
    assert row["artifact_status"] == "missing_snapshot"
    assert row["notes"] == "no_selection_snapshot"
    assert row["selected_size"] is None


def test_aggregate_digest_falls_back_to_empty_row_when_snapshot_missing(tmp_path: Path) -> None:
    mod = _load_module()
    digest = mod.aggregate_digest(
        trade_dates=["2026-06-01", "2026-06-02"],
        snapshot_dir=tmp_path,
        artifact_dir=tmp_path / "artifacts",
    )
    assert digest["trade_date_count"] == 2
    assert all(r["artifact_status"] == "missing_snapshot" for r in digest["rows"])


def test_aggregate_digest_includes_pool_size_from_snapshot_only(tmp_path: Path) -> None:
    mod = _load_module()
    artifact_dir = tmp_path / "artifacts"
    snapshot_dir = tmp_path / "snaps"
    artifact_dir.mkdir()
    snapshot_dir.mkdir()
    (snapshot_dir / "candidate_pool_20260601_top300.json").write_text(json.dumps([{"ticker": str(i)} for i in range(100)]), encoding="utf-8")
    snap = artifact_dir / "2026-06-01"
    snap.mkdir()
    (snap / "selection_snapshot.json").write_text(
        json.dumps(
            {
                "selected": [{"symbol": "000001", "score_final": 0.5, "decision": "buy"}],
                "rejected": [],
                "watchlist": [],
            }
        ),
        encoding="utf-8",
    )
    digest = mod.aggregate_digest(
        trade_dates=["2026-06-01"],
        snapshot_dir=snapshot_dir,
        artifact_dir=artifact_dir,
    )
    row = digest["rows"][0]
    assert row["candidate_pool_size"] == 100
    assert row["selected_size"] == 1
    assert row["avg_score_final"] == 0.5


def test_render_csv_has_stable_column_order() -> None:
    mod = _load_module()
    digest = {
        "generated_at": "2026-06-06T00:00:00+00:00",
        "trade_date_count": 1,
        "rows": [
            {
                "trade_date": "2026-06-01",
                "candidate_pool_size": 100,
                "watchlist_size": 0,
                "selected_size": 1,
                "rejected_size": 0,
                "avg_score_final": 0.5,
                "avg_score_b": 0.4,
                "avg_score_c": 0.6,
                "decision_counts": {"buy": 1},
                "market_state": "trend",
                "regime_gate_status": "open",
                "top10_tickers": "000001",
                "artifact_status": "complete",
                "notes": "",
            }
        ],
    }
    csv = mod.render_csv(digest)
    header = csv.splitlines()[0]
    for col in mod.DIGEST_COLUMNS:
        assert col in header, f"missing column {col}"
    # Row includes the JSON-encoded decision_counts. The CSV writer escapes
    # inner double quotes by doubling them, so the literal substring we see
    # in the raw CSV is "{""buy"": 1}".
    assert '"{""buy"": 1}"' in csv


def test_render_markdown_includes_headline_and_table() -> None:
    mod = _load_module()
    digest = {
        "generated_at": "2026-06-06T00:00:00+00:00",
        "trade_date_count": 1,
        "rows": [
            {
                "trade_date": "2026-06-01",
                "candidate_pool_size": 100,
                "watchlist_size": 0,
                "selected_size": 1,
                "rejected_size": 0,
                "avg_score_final": 0.5,
                "avg_score_b": 0.4,
                "avg_score_c": 0.6,
                "decision_counts": {},
                "market_state": "trend",
                "regime_gate_status": "open",
                "top10_tickers": "000001",
                "artifact_status": "complete",
                "notes": "",
            }
        ],
    }
    md = mod.render_markdown(digest)
    assert "# Screening Daily Digest" in md
    assert "## Headline Metrics" in md
    assert "## Per-Day Rollup" in md
    assert "| 2026-06-01 |" in md


def test_main_with_latest_30_days_creates_outputs(tmp_path: Path, capsys, monkeypatch) -> None:
    mod = _load_module()
    output_dir = tmp_path / "digest"
    # Empty data: no artifacts anywhere -> trade_date_count=0
    monkeypatch.setattr(
        "sys.argv",
        [
            "aggregate_screening_daily_digest.py",
            "--latest-30-days",
            "--snapshot-dir",
            str(tmp_path / "snaps"),
            "--artifact-dir",
            str(tmp_path / "artifacts"),
            "--output-dir",
            str(output_dir),
        ],
    )
    rc = mod.main()
    assert rc == 0
    captured = capsys.readouterr().out
    assert "trade_date_count=0" in captured
    # Files still created even if empty
    month_files = list(output_dir.iterdir())
    assert month_files, "expected at least one output file"


def test_main_with_explicit_year_month_creates_outputs(tmp_path: Path, capsys, monkeypatch) -> None:
    mod = _load_module()
    output_dir = tmp_path / "digest"
    artifact_dir = tmp_path / "artifacts"
    (artifact_dir / "2026-06-02").mkdir(parents=True)
    (artifact_dir / "2026-06-02" / "selection_snapshot.json").write_text(
        json.dumps(
            {
                "selected": [{"symbol": "000001", "score_final": 0.7, "decision": "buy"}],
                "rejected": [],
                "watchlist": [],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "aggregate_screening_daily_digest.py",
            "--year",
            "2026",
            "--month",
            "6",
            "--snapshot-dir",
            str(tmp_path / "snaps"),
            "--artifact-dir",
            str(artifact_dir),
            "--output-dir",
            str(output_dir),
        ],
    )
    rc = mod.main()
    assert rc == 0
    captured = capsys.readouterr().out
    assert "trade_date_count=1" in captured
    assert "screening-202606" in captured


def test_main_rejects_missing_args() -> None:
    mod = _load_module()
    rc = mod.main([])
    assert rc == 2
