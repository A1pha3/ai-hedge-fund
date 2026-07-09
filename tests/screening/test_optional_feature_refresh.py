from __future__ import annotations

import json
from pathlib import Path

from src.screening.optional_feature_refresh import refresh_optional_features
from src.screening.scoring_feature_refresh import refresh_scoring_features


def test_refresh_optional_features_writes_manifest_without_blocking_on_disabled_providers(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("AUTO_OPTIONAL_FEATURE_REFRESH", "0")

    summary = refresh_optional_features(
        "20260708",
        ["000001", "000002"],
        timeout_seconds=0.1,
        cache_dir=tmp_path,
    )

    manifest_path = tmp_path / "feature_manifest_20260708.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert summary["status"] == "skipped"
    assert manifest["trade_date"] == "20260708"
    assert manifest["candidate_count"] == 2
    assert manifest["features"]["intraday_short_trade_metrics"]["provider_failures"] == 0
    assert manifest["features"]["daily_fund_flow_metrics"]["provider_failures"] == 0


def test_refresh_optional_features_reports_not_implemented_when_enabled(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.delenv("AUTO_OPTIONAL_FEATURE_REFRESH", raising=False)

    summary = refresh_optional_features(
        "20260708",
        ["000001"],
        cache_dir=tmp_path,
    )

    manifest = json.loads((tmp_path / "feature_manifest_20260708.json").read_text(encoding="utf-8"))

    assert summary["status"] == "not_implemented"
    assert manifest["status"] == "not_implemented"
    assert manifest["features"]["intraday_short_trade_metrics"]["source"] == "pending_provider_implementation"
    assert manifest["features"]["daily_fund_flow_metrics"]["source"] == "pending_provider_implementation"


def test_refresh_scoring_features_writes_all_family_manifest(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("AUTO_OPTIONAL_FEATURE_REFRESH", "0")

    summary = refresh_scoring_features(
        "20260708",
        ["000001", "000002", "000001"],
        timeout_seconds=3.0,
        cache_dir=tmp_path,
    )

    manifest = json.loads((tmp_path / "feature_manifest_20260708.json").read_text(encoding="utf-8"))
    assert summary["status"] == "skipped"
    assert manifest["candidate_count"] == 2
    assert set(manifest["features"]) == {
        "price_history",
        "financial_metrics",
        "event_inputs",
        "industry_pe_medians",
        "dragon_tiger_bonus",
        "intraday_short_trade_metrics",
        "daily_fund_flow_metrics",
    }
    assert manifest["features"]["event_inputs"]["rows_written"] == 0


def test_refresh_scoring_features_deduplicates_tickers(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("AUTO_OPTIONAL_FEATURE_REFRESH", "0")

    refresh_scoring_features(
        "20260708",
        ["000001.SZ", "000001", "000002", "000003"],
        timeout_seconds=3.0,
        cache_dir=tmp_path,
    )

    manifest = json.loads((tmp_path / "feature_manifest_20260708.json").read_text(encoding="utf-8"))
    # 000001.SZ and 000001 both normalize to 000001; 000002/000003 stay.
    assert manifest["candidate_count"] == 3

