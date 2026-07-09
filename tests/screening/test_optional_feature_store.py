from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from src.screening.optional_feature_store import OptionalFeatureStore


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

    assert result == {
        "000001": {
            "flow_60": 0.12,
            "flow_60_source": "bar_proxy",
            "close_support_30": 0.08,
            "close_support_30_source": "bar_proxy",
            "persist_120": 0.55,
            "persist_120_source": "bar_proxy",
        }
    }


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

    assert result == {
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

    assert result == {}


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
    }
    assert summary["optional_features"]["daily_fund_flow_metrics"]["provider_failures"] == 1
    assert summary["optional_features"]["daily_fund_flow_metrics"]["missing_tickers"] == 2
