from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from src.data.models import FinancialMetrics
from src.screening.scoring_feature_store import ScoringFeatureStore


def test_load_price_frame_reads_local_price_cache_without_provider(tmp_path: Path) -> None:
    price_dir = tmp_path / "price_cache"
    price_dir.mkdir()
    pd.DataFrame(
        [
            {"date": "2026-07-07", "open": 10.0, "high": 11.0, "low": 9.8, "close": 10.5, "volume": 1000},
            {"date": "2026-07-08", "open": 10.5, "high": 11.5, "low": 10.2, "close": 11.0, "volume": 1200},
            {"date": "2026-07-09", "open": 11.0, "high": 12.0, "low": 10.8, "close": 11.8, "volume": 1300},
        ]
    ).to_csv(price_dir / "000001.csv", index=False)
    store = ScoringFeatureStore(
        base_dir=tmp_path / "feature_cache",
        price_cache_dir=price_dir,
        legacy_snapshot_dir=tmp_path / "snapshots",
        lhb_cache_dir=tmp_path / "lhb_cache",
    )

    frame = store.load_price_frame("000001", "20260708", lookback_days=400)

    assert list(frame["close"]) == [10.5, 11.0]
    assert frame.index[-1].strftime("%Y-%m-%d") == "2026-07-08"


def test_load_financial_metrics_accepts_compact_and_dashed_dates(tmp_path: Path) -> None:
    snapshot_dir = tmp_path / "snapshots"
    compact_dir = snapshot_dir / "000001" / "20260708"
    dashed_dir = snapshot_dir / "000002" / "2026-07-08"
    compact_dir.mkdir(parents=True)
    dashed_dir.mkdir(parents=True)
    payload = {
        "financial_metrics": [
            {
                "ticker": "000001",
                "report_period": "20260331",
                "period": "ttm",
                "currency": "CNY",
                "market_cap": 1.0,
                "enterprise_value": None,
                "price_to_earnings_ratio": 12.0,
                "price_to_book_ratio": None,
                "price_to_sales_ratio": None,
                "enterprise_value_to_ebitda_ratio": None,
                "enterprise_value_to_revenue_ratio": None,
                "free_cash_flow_yield": None,
                "peg_ratio": None,
                "gross_margin": None,
                "operating_margin": 0.2,
                "net_margin": 0.21,
                "return_on_equity": 0.16,
                "return_on_assets": None,
                "return_on_invested_capital": None,
                "asset_turnover": None,
                "inventory_turnover": None,
                "receivables_turnover": None,
                "days_sales_outstanding": None,
                "operating_cycle": None,
                "working_capital_turnover": None,
                "current_ratio": 2.0,
                "quick_ratio": 1.5,
                "cash_ratio": None,
                "operating_cash_flow_ratio": None,
                "debt_to_equity": 0.1,
                "debt_to_assets": 0.1,
                "interest_coverage": 10.0,
                "revenue_growth": 0.1,
                "earnings_growth": 0.2,
                "book_value_growth": None,
                "earnings_per_share_growth": None,
                "free_cash_flow_growth": None,
                "operating_income_growth": None,
                "ebitda_growth": None,
                "payout_ratio": None,
                "earnings_per_share": None,
                "book_value_per_share": None,
                "free_cash_flow_per_share": None,
            }
        ]
    }
    (compact_dir / "financials.json").write_text(json.dumps(payload), encoding="utf-8")
    payload["financial_metrics"][0]["ticker"] = "000002"
    (dashed_dir / "financials.json").write_text(json.dumps(payload), encoding="utf-8")
    store = ScoringFeatureStore(
        base_dir=tmp_path / "feature_cache",
        price_cache_dir=tmp_path / "price_cache",
        legacy_snapshot_dir=snapshot_dir,
        lhb_cache_dir=tmp_path / "lhb_cache",
    )

    compact = store.load_financial_metrics("000001", "20260708")
    dashed = store.load_financial_metrics("000002", "20260708")

    assert compact[0].ticker == "000001"
    assert dashed[0].ticker == "000002"


def test_load_event_inputs_reads_existing_company_news_snapshot(tmp_path: Path) -> None:
    snapshot_dir = tmp_path / "snapshots"
    news_dir = snapshot_dir / "603259" / "2026-07-08"
    news_dir.mkdir(parents=True)
    (news_dir / "company_news.json").write_text(
        json.dumps(
            [
                {
                    "ticker": "603259",
                    "title": "回购完成",
                    "author": "source",
                    "source": "source",
                    "date": "2026-07-07 16:00:00",
                    "url": "https://example.test/news",
                    "sentiment": "positive",
                    "content": "603259 完成回购",
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    store = ScoringFeatureStore(
        base_dir=tmp_path / "feature_cache",
        price_cache_dir=tmp_path / "price_cache",
        legacy_snapshot_dir=snapshot_dir,
        lhb_cache_dir=tmp_path / "lhb_cache",
    )

    news, trades = store.load_event_inputs("603259", "20260708")

    assert [item.title for item in news] == ["回购完成"]
    assert trades == []


def test_load_dragon_tiger_bonus_uses_ticker_presence_only(tmp_path: Path) -> None:
    lhb_dir = tmp_path / "lhb_cache"
    lhb_dir.mkdir()
    pd.DataFrame(
        [
            {"trade_date": "20260708", "ts_code": "000001.SZ", "net_buy": -100.0},
            {"trade_date": "20260708", "ts_code": "000002.SZ", "net_buy": 0.0},
        ]
    ).to_csv(lhb_dir / "20260708.csv", index=False)
    store = ScoringFeatureStore(
        base_dir=tmp_path / "feature_cache",
        price_cache_dir=tmp_path / "price_cache",
        legacy_snapshot_dir=tmp_path / "snapshots",
        lhb_cache_dir=lhb_dir,
    )

    bonus = store.load_dragon_tiger_bonus_map(["000001", "000002", "000003"], "20260708")

    assert bonus == {"000001": 1.0, "000002": 1.0}


def test_load_price_frame_returns_empty_when_missing(tmp_path: Path) -> None:
    store = ScoringFeatureStore(
        base_dir=tmp_path / "feature_cache",
        price_cache_dir=tmp_path / "price_cache",
        legacy_snapshot_dir=tmp_path / "snapshots",
        lhb_cache_dir=tmp_path / "lhb_cache",
    )

    assert store.load_price_frame("999999", "20260708").empty


def _full_financial_payload(ticker: str, report_period: str = "20260630") -> dict:
    base = {field: None for field in FinancialMetrics.model_fields}
    base.update(
        {
            "ticker": ticker,
            "report_period": report_period,
            "period": "ttm",
            "currency": "CNY",
            "market_cap": 1.0,
            "enterprise_value": 1.0,
            "price_to_earnings_ratio": 12.0,
        }
    )
    return {"financial_metrics": [base]}


def test_stale_snapshots_rejected_by_default_and_accepted_when_enabled(tmp_path: Path) -> None:
    snapshot_dir = tmp_path / "snapshots"
    stale_dir = snapshot_dir / "000001" / "20260701"
    stale_dir.mkdir(parents=True)
    (stale_dir / "financials.json").write_text(
        json.dumps(_full_financial_payload("000001")), encoding="utf-8"
    )
    store_strict = ScoringFeatureStore(
        base_dir=tmp_path / "feature_cache",
        legacy_snapshot_dir=snapshot_dir,
    )

    assert store_strict.load_financial_metrics("000001", "20260708") == []

    store_stale = ScoringFeatureStore(
        base_dir=tmp_path / "feature_cache",
        legacy_snapshot_dir=snapshot_dir,
        max_stale_days=10,
        allow_stale=True,
    )

    assert store_stale.load_financial_metrics("000001", "20260708")[0].ticker == "000001"


def test_future_dated_snapshot_never_used_as_stale_fallback(tmp_path: Path) -> None:
    snapshot_dir = tmp_path / "snapshots"
    future_dir = snapshot_dir / "000001" / "20260715"
    future_dir.mkdir(parents=True)
    (future_dir / "financials.json").write_text(
        json.dumps(_full_financial_payload("000001")), encoding="utf-8"
    )
    store = ScoringFeatureStore(
        base_dir=tmp_path / "feature_cache",
        legacy_snapshot_dir=snapshot_dir,
        max_stale_days=30,
        allow_stale=True,
    )

    assert store.load_financial_metrics("000001", "20260708") == []


def test_malformed_financial_snapshot_returns_empty(tmp_path: Path) -> None:
    snapshot_dir = tmp_path / "snapshots"
    malformed_dir = snapshot_dir / "000001" / "20260708"
    malformed_dir.mkdir(parents=True)
    (malformed_dir / "financials.json").write_text("{not valid json", encoding="utf-8")
    store = ScoringFeatureStore(
        base_dir=tmp_path / "feature_cache",
        legacy_snapshot_dir=snapshot_dir,
    )

    assert store.load_financial_metrics("000001", "20260708") == []


def test_build_quality_summary_reports_family_coverage(tmp_path: Path) -> None:
    store = ScoringFeatureStore(
        base_dir=tmp_path / "feature_cache",
        price_cache_dir=tmp_path / "price_cache",
        legacy_snapshot_dir=tmp_path / "snapshots",
        lhb_cache_dir=tmp_path / "lhb_cache",
    )

    store.load_price_frame("000001", "20260708")
    summary = store.build_quality_summary("20260708", ["000001", "000002"])

    scoring = summary["scoring_features"]
    assert "price_history" in scoring
    assert scoring["price_history"]["candidate_count"] == 2
    assert scoring["price_history"]["requested_count"] == 1
    assert scoring["price_history"]["loaded_count"] == 0  # no file, so not loaded
    assert scoring["price_history"]["min_required_rows"] == 200
    assert "optional_features" in summary
