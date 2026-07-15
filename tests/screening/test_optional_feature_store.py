from __future__ import annotations

import json
from dataclasses import FrozenInstanceError
from pathlib import Path

import pandas as pd
import pytest

from src.screening.optional_feature_store import OptionalFeatureStore, OptionalObservation
from src.screening.scoring_feature_quality import ObservationStatus


def test_load_intraday_metrics_reads_snapshot_for_requested_tickers(tmp_path: Path) -> None:
    cache_dir = tmp_path / "feature_cache"
    cache_dir.mkdir()
    pd.DataFrame(
        [
            {
                "ticker": "000001",
                "trade_date": "20260708",
                "flow_60": 0.12,
                "flow_60_source": "bar_proxy",
                "close_support_30": 0.08,
                "close_support_30_source": "bar_proxy",
                "persist_120": 0.55,
                "persist_120_source": "bar_proxy",
            },
            {
                "ticker": "000002",
                "trade_date": "20260708",
                "flow_60": -0.03,
                "flow_60_source": "daily_flow_proxy",
            },
        ]
    ).to_csv(cache_dir / "intraday_short_trade_metrics_20260708.csv", index=False)

    store = OptionalFeatureStore(base_dir=cache_dir)

    result = store.load_intraday_metrics("20260708", ["000001", "000003"])

    assert isinstance(result, OptionalObservation)
    assert result.status is ObservationStatus.SUCCESS
    assert result.values == {
        "000001": {
            "flow_60": 0.12,
            "flow_60_source": "bar_proxy",
            "close_support_30": 0.08,
            "close_support_30_source": "bar_proxy",
            "persist_120": 0.55,
            "persist_120_source": "bar_proxy",
        }
    }
    assert result.source_fingerprint is not None
    assert result.source_fingerprint.startswith("sha256:")
    assert result.get("000001") == result.values["000001"]
    assert dict(result) == result.values

    with pytest.raises(FrozenInstanceError):
        result.status = ObservationStatus.FAILED  # type: ignore[misc]

    with pytest.raises(TypeError):
        result["000001"] = {}  # type: ignore[index]


def test_load_fund_flow_metrics_maps_main_flow_ratio(tmp_path: Path) -> None:
    cache_dir = tmp_path / "feature_cache"
    cache_dir.mkdir()
    pd.DataFrame(
        [
            {
                "ticker": "000001",
                "trade_date": "20260708",
                "main_flow_ratio": 0.15,
                "main_flow_ratio_source": "tushare_snapshot",
            }
        ]
    ).to_csv(cache_dir / "daily_fund_flow_metrics_20260708.csv", index=False)

    store = OptionalFeatureStore(base_dir=cache_dir)

    result = store.load_fund_flow_metrics("20260708", ["000001", "000002"])

    assert result.status is ObservationStatus.SUCCESS
    assert result.values == {
        "000001": {
            "main_flow_ratio": 0.15,
            "main_flow_ratio_source": "tushare_snapshot",
        }
    }


def test_load_intraday_metrics_returns_empty_for_malformed_snapshot(tmp_path: Path) -> None:
    cache_dir = tmp_path / "feature_cache"
    cache_dir.mkdir()
    (cache_dir / "intraday_short_trade_metrics_20260708.csv").write_text(
        'ticker,trade_date,flow_60\n000001,20260708,"unterminated\n',
        encoding="utf-8",
    )

    result = OptionalFeatureStore(base_dir=cache_dir).load_intraday_metrics(
        "20260708",
        ["000001"],
    )

    assert result.status is ObservationStatus.FAILED
    assert result.values == {}
    assert result.source_fingerprint is not None


def test_load_intraday_metrics_treats_valid_empty_snapshot_as_success(tmp_path: Path) -> None:
    cache_dir = tmp_path / "feature_cache"
    cache_dir.mkdir()
    pd.DataFrame(columns=["ticker", "trade_date", "flow_60"]).to_csv(
        cache_dir / "intraday_short_trade_metrics_20260708.csv",
        index=False,
    )

    result = OptionalFeatureStore(base_dir=cache_dir).load_intraday_metrics(
        "20260708",
        ["000001"],
    )

    assert result.status is ObservationStatus.SUCCESS
    assert result.values == {}
    assert result.source_fingerprint is not None


def test_build_quality_summary_reports_coverage_and_manifest_failures(tmp_path: Path) -> None:
    cache_dir = tmp_path / "feature_cache"
    cache_dir.mkdir()
    pd.DataFrame([{"ticker": "000001", "trade_date": "20260708", "flow_60": 0.2}]).to_csv(
        cache_dir / "intraday_short_trade_metrics_20260708.csv",
        index=False,
    )
    pd.DataFrame([{"ticker": "000002", "trade_date": "20260708", "main_flow_ratio": -0.1}]).to_csv(
        cache_dir / "daily_fund_flow_metrics_20260708.csv",
        index=False,
    )
    (cache_dir / "feature_manifest_20260708.json").write_text(
        json.dumps(
            {
                "features": {
                    "intraday_short_trade_metrics": {"provider_failures": 3},
                    "daily_fund_flow_metrics": {"provider_failures": 1},
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    summary = OptionalFeatureStore(base_dir=cache_dir).build_quality_summary(
        "20260708",
        ["000001", "000002", "000003"],
    )

    assert summary["optional_features"]["intraday_short_trade_metrics"] == {
        "coverage": 0.3333,
        "source": "snapshot",
        "trade_date": "20260708",
        "stale": False,
        "provider_failures": 3,
        "missing_tickers": 2,
        "observation_status": "success",
    }
    assert summary["optional_features"]["daily_fund_flow_metrics"]["provider_failures"] == 1
    assert summary["optional_features"]["daily_fund_flow_metrics"]["missing_tickers"] == 2


def test_build_quality_summary_ignores_malformed_manifest(tmp_path: Path) -> None:
    cache_dir = tmp_path / "feature_cache"
    cache_dir.mkdir()
    (cache_dir / "feature_manifest_20260708.json").write_text(
        "{bad json",
        encoding="utf-8",
    )

    summary = OptionalFeatureStore(base_dir=cache_dir).build_quality_summary(
        "20260708",
        ["000001"],
    )

    assert summary["optional_features"]["intraday_short_trade_metrics"]["provider_failures"] == 0
    assert summary["optional_features"]["daily_fund_flow_metrics"]["provider_failures"] == 0


def test_load_intraday_metrics_uses_recent_stale_snapshot_when_allowed(tmp_path: Path) -> None:
    cache_dir = tmp_path / "feature_cache"
    cache_dir.mkdir()
    pd.DataFrame(
        [
            {
                "ticker": "000001",
                "trade_date": "20260707",
                "flow_60": 0.09,
                "flow_60_source": "snapshot",
            }
        ]
    ).to_csv(cache_dir / "intraday_short_trade_metrics_20260707.csv", index=False)

    store = OptionalFeatureStore(base_dir=cache_dir, allow_stale=True, max_stale_days=1)

    result = store.load_intraday_metrics("20260708", ["000001"])

    assert result.status is ObservationStatus.SUCCESS
    assert result.values == {
        "000001": {"flow_60": 0.09, "flow_60_source": "snapshot"}
    }


def test_build_quality_summary_marks_recent_stale_snapshot(tmp_path: Path) -> None:
    cache_dir = tmp_path / "feature_cache"
    cache_dir.mkdir()
    pd.DataFrame([{"ticker": "000001", "trade_date": "20260707", "flow_60": 0.09}]).to_csv(
        cache_dir / "intraday_short_trade_metrics_20260707.csv",
        index=False,
    )

    summary = OptionalFeatureStore(base_dir=cache_dir, allow_stale=True, max_stale_days=1).build_quality_summary(
        "20260708",
        ["000001", "000002"],
    )

    assert summary["optional_features"]["intraday_short_trade_metrics"] == {
        "coverage": 0.5,
        "source": "snapshot",
        "trade_date": "20260708",
        "stale": True,
        "provider_failures": 0,
        "missing_tickers": 1,
        "observation_status": "success",
        "snapshot_date": "20260707",
    }


def test_load_intraday_metrics_ignores_stale_snapshot_outside_window(tmp_path: Path) -> None:
    cache_dir = tmp_path / "feature_cache"
    cache_dir.mkdir()
    pd.DataFrame([{"ticker": "000001", "trade_date": "20260706", "flow_60": 0.09}]).to_csv(
        cache_dir / "intraday_short_trade_metrics_20260706.csv",
        index=False,
    )

    result = OptionalFeatureStore(base_dir=cache_dir, allow_stale=True, max_stale_days=1).load_intraday_metrics(
        "20260708",
        ["000001"],
    )

    assert result.status is ObservationStatus.UNAVAILABLE
    assert result.values == {}
    assert result.source_fingerprint is None


def test_missing_optional_snapshot_is_unavailable_not_observed_empty(tmp_path: Path) -> None:
    quality = OptionalFeatureStore(base_dir=tmp_path).build_quality_summary(
        "20260713", ["000001"]
    )

    assert (
        quality["optional_features"]["intraday_short_trade_metrics"][
            "observation_status"
        ]
        == "unavailable"
    )


def test_malformed_optional_snapshot_is_failed_in_quality_summary(tmp_path: Path) -> None:
    (tmp_path / "intraday_short_trade_metrics_20260713.csv").write_text(
        'ticker,trade_date,flow_60\n000001,20260713,"unterminated\n',
        encoding="utf-8",
    )

    quality = OptionalFeatureStore(base_dir=tmp_path).build_quality_summary(
        "20260713", ["000001"]
    )

    assert (
        quality["optional_features"]["intraday_short_trade_metrics"][
            "observation_status"
        ]
        == "failed"
    )
