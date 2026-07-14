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


def test_load_event_inputs_rejects_future_dated_rows(tmp_path: Path) -> None:
    snapshot_dir = tmp_path / "snapshots"
    event_dir = snapshot_dir / "603259" / "20260708"
    event_dir.mkdir(parents=True)
    (event_dir / "company_news.json").write_text(
        json.dumps(
            [
                {
                    "ticker": "603259",
                    "title": "usable same-day news",
                    "author": "source",
                    "source": "source",
                    "date": "2026-07-08 09:30:00",
                    "url": "https://example.test/same-day",
                    "sentiment": "positive",
                    "content": "usable",
                },
                {
                    "ticker": "603259",
                    "title": "future news",
                    "author": "source",
                    "source": "source",
                    "date": "2026-07-09 09:30:00",
                    "url": "https://example.test/future",
                    "sentiment": "positive",
                    "content": "future",
                },
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (event_dir / "insider_trades.json").write_text(
        json.dumps(
            [
                {
                    "ticker": "603259",
                    "issuer": None,
                    "name": "same-day",
                    "title": None,
                    "is_board_director": None,
                    "transaction_date": "2026-07-08",
                    "transaction_shares": 100.0,
                    "transaction_price_per_share": 1.0,
                    "transaction_value": 100.0,
                    "shares_owned_before_transaction": None,
                    "shares_owned_after_transaction": None,
                    "security_title": None,
                    "filing_date": "2026-07-08",
                },
                {
                    "ticker": "603259",
                    "issuer": None,
                    "name": "future",
                    "title": None,
                    "is_board_director": None,
                    "transaction_date": "2026-07-09",
                    "transaction_shares": 100.0,
                    "transaction_price_per_share": 1.0,
                    "transaction_value": 100.0,
                    "shares_owned_before_transaction": None,
                    "shares_owned_after_transaction": None,
                    "security_title": None,
                    "filing_date": "2026-07-09",
                },
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    store = ScoringFeatureStore(
        base_dir=tmp_path / "feature_cache",
        legacy_snapshot_dir=snapshot_dir,
    )

    news, trades = store.load_event_inputs("603259", "20260708")

    assert [item.title for item in news] == ["usable same-day news"]
    assert [item.name for item in trades] == ["same-day"]


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


def test_load_dragon_tiger_bonus_filters_mixed_trade_date_rows(tmp_path: Path) -> None:
    lhb_dir = tmp_path / "lhb_cache"
    lhb_dir.mkdir()
    pd.DataFrame(
        [
            {"trade_date": "20260708", "ts_code": "000001.SZ", "net_buy": -100.0},
            {"trade_date": "20260709", "ts_code": "000002.SZ", "net_buy": 100.0},
        ]
    ).to_csv(lhb_dir / "20260708.csv", index=False)
    store = ScoringFeatureStore(
        base_dir=tmp_path / "feature_cache",
        lhb_cache_dir=lhb_dir,
    )

    bonus = store.load_dragon_tiger_bonus_map(["000001", "000002"], "20260708")

    assert bonus == {"000001": 1.0}


def test_load_fund_flow_metrics_reads_legacy_fund_flow_cache(tmp_path: Path) -> None:
    fund_flow_dir = tmp_path / "fund_flow_cache"
    fund_flow_dir.mkdir()
    pd.DataFrame(
        [
            {"date": "20260708", "ticker": "000001", "main_net_pct": 2.5, "main_net_inflow": 1000.0},
            {"date": "20260709", "ticker": "000001", "main_net_pct": 9.9, "main_net_inflow": 2000.0},
        ]
    ).to_csv(fund_flow_dir / "000001.csv", index=False)
    store = ScoringFeatureStore(
        base_dir=tmp_path / "feature_cache",
        fund_flow_cache_dir=fund_flow_dir,
    )

    rows = store.load_fund_flow_metrics("20260708", ["000001", "000002"])

    assert rows == {
        "000001": {
            "main_flow_ratio": 0.025,
            "main_flow_ratio_source": "fund_flow_cache",
        }
    }


def test_load_price_frame_returns_empty_when_missing(tmp_path: Path) -> None:
    store = ScoringFeatureStore(
        base_dir=tmp_path / "feature_cache",
        price_cache_dir=tmp_path / "price_cache",
        legacy_snapshot_dir=tmp_path / "snapshots",
        lhb_cache_dir=tmp_path / "lhb_cache",
    )

    assert store.load_price_frame("999999", "20260708").empty


def test_load_price_frame_preserves_optional_enrichment_columns(tmp_path: Path) -> None:
    """Cache may carry amount/turnover_rate/pct_change. Store must forward them so
    downstream scorers degrade naturally instead of silently losing columns the
    cache may grow (parity with prices_to_df, which keeps all Price fields)."""
    price_dir = tmp_path / "price_cache"
    price_dir.mkdir()
    pd.DataFrame(
        [
            {"date": "2026-07-07", "open": 10.0, "high": 11.0, "low": 9.8, "close": 10.5, "volume": 1000, "amount": 10500.0, "pct_change": 0.05, "turnover_rate": 1.2},
            {"date": "2026-07-08", "open": 10.5, "high": 11.5, "low": 10.2, "close": 11.0, "volume": 1200, "amount": 13200.0, "pct_change": 0.048, "turnover_rate": 1.4},
        ]
    ).to_csv(price_dir / "000001.csv", index=False)
    store = ScoringFeatureStore(
        base_dir=tmp_path / "feature_cache",
        price_cache_dir=price_dir,
        legacy_snapshot_dir=tmp_path / "snapshots",
        lhb_cache_dir=tmp_path / "lhb_cache",
    )

    frame = store.load_price_frame("000001", "20260708")

    assert {"open", "close", "high", "low", "volume", "amount", "pct_change", "turnover_rate"}.issubset(frame.columns)
    assert "date" not in frame.columns  # internal helper column must not leak


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


def test_build_quality_summary_optional_block_matches_scoring_block(tmp_path: Path) -> None:
    """Regression guard: intraday/fund_flow coverage reported in the backward-
    compatible optional_features block must equal the scoring_features block.
    Previously the optional block recomputed coverage over the full candidate set
    (300) while scoring recorded only the requested subset (e.g. 12), producing
    contradictory missing_tickers in the same report."""
    store = ScoringFeatureStore(base_dir=tmp_path / "feature_cache")

    # Simulate score_batch requesting intraday for only a 2-ticker subset while
    # the candidate set is 5; only one ticker has a snapshot.
    store.load_intraday_metrics("20260708", ["000001", "000002"])
    summary = store.build_quality_summary("20260708", ["000001", "000002", "000003", "000004", "000005"])

    for family in ("intraday_short_trade_metrics", "daily_fund_flow_metrics"):
        sf = summary["scoring_features"][family]
        of = summary["optional_features"][family]
        assert of["coverage"] == sf["coverage"]
        assert of["missing_tickers"] == sf["missing_tickers"]
        assert of["source"] == sf["source"]


def test_build_quality_summary_merges_refresh_manifest_failures(tmp_path: Path) -> None:
    feature_dir = tmp_path / "feature_cache"
    feature_dir.mkdir()
    (feature_dir / "feature_manifest_20260708.json").write_text(
        json.dumps(
            {
                "trade_date": "20260708",
                "features": {
                    "daily_fund_flow_metrics": {
                        "provider_failures": 3,
                        "rows_written": 7,
                        "source": "akshare_refresh",
                    }
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    store = ScoringFeatureStore(base_dir=feature_dir)

    summary = store.build_quality_summary("20260708", ["000001"])

    quality = summary["scoring_features"]["daily_fund_flow_metrics"]
    assert quality["provider_failures"] == 3
    assert quality["rows_written"] == 7
    assert quality["source"] == "akshare_refresh"


# ---------------------------------------------------------------------------
# Task 3: per-family observation evidence (FeatureEvidence format)
# ---------------------------------------------------------------------------


def test_build_quality_summary_reports_stale_count_when_stale_fallback_used(tmp_path: Path) -> None:
    """A stale financial snapshot must surface stale_count=1 honestly.

    When allow_stale falls back to an older snapshot, the consumer tracker
    must record that the scorer actually consumed stale data — not silently
    mask it as fresh. ``assess_auto_quality`` blocks required features with
    stale_count > 0.
    """
    snapshot_dir = tmp_path / "snapshots"
    stale_dir = snapshot_dir / "000001" / "20260701"
    stale_dir.mkdir(parents=True)
    (stale_dir / "financials.json").write_text(
        json.dumps(_full_financial_payload("000001")), encoding="utf-8"
    )
    store = ScoringFeatureStore(
        base_dir=tmp_path / "feature_cache",
        legacy_snapshot_dir=snapshot_dir,
        max_stale_days=10,
        allow_stale=True,
    )

    # Consume: this falls back to the 20260701 snapshot (stale).
    store.load_financial_metrics("000001", "20260708")
    summary = store.build_quality_summary("20260708", ["000001"])

    fin = summary["scoring_features"]["financial_metrics"]
    assert fin["stale_count"] == 1
    assert fin["stale"] is True
    # Observed + usable because the snapshot was reachable, parseable, nonempty.
    assert fin["observed_count"] == 1
    assert fin["usable_count"] == 1
    assert fin["nonempty_count"] == 1


def test_build_quality_summary_reports_legal_empty_event_observation(tmp_path: Path) -> None:
    """event_inputs with a reachable-but-empty snapshot → observed_count=1, nonempty=0.

    event_inputs has legal-when-observed empty semantics: a snapshot that
    exists and parses cleanly but contains zero rows is an authoritative
    observation, not a failure. The summary must record observed_count=1
    and nonempty_count=0 so ``assess_auto_quality`` can accept the legal
    empty rather than blocking on a phantom missing-feature.
    """
    snapshot_dir = tmp_path / "snapshots"
    event_dir = snapshot_dir / "000001" / "20260708"
    event_dir.mkdir(parents=True)
    # Empty news + trades snapshots — both reachable, both parseable, both empty.
    (event_dir / "company_news.json").write_text("[]", encoding="utf-8")
    (event_dir / "insider_trades.json").write_text("[]", encoding="utf-8")
    store = ScoringFeatureStore(
        base_dir=tmp_path / "feature_cache",
        legacy_snapshot_dir=snapshot_dir,
    )

    store.load_event_inputs("000001", "20260708")
    summary = store.build_quality_summary("20260708", ["000001"])

    events = summary["scoring_features"]["event_inputs"]
    assert events["observed_count"] == 1
    assert events["nonempty_count"] == 0
    # Legal empty observation is still a SUCCESS — no stale, no consumption failure.
    assert events["stale_count"] == 0
    assert events["consumption_failed_count"] == 0
    assert events["observation_status"] == "success"


def test_build_quality_summary_emits_feature_evidence_schema(tmp_path: Path) -> None:
    """Each scoring_features family entry must parse via FeatureEvidence.from_mapping.

    This is the contract ``assess_auto_quality`` relies on: every family the
    scorer consumed must produce a mapping that ``FeatureEvidence.from_mapping``
    accepts without raising. Validates that observation_status, the integer
    counts, and the fingerprints are all well-formed.
    """
    from src.screening.scoring_feature_quality import FeatureEvidence

    snapshot_dir = tmp_path / "snapshots"
    fin_dir = snapshot_dir / "000001" / "20260708"
    fin_dir.mkdir(parents=True)
    (fin_dir / "financials.json").write_text(
        json.dumps(_full_financial_payload("000001")), encoding="utf-8"
    )
    (fin_dir / "company_news.json").write_text("[]", encoding="utf-8")
    (fin_dir / "insider_trades.json").write_text("[]", encoding="utf-8")
    store = ScoringFeatureStore(
        base_dir=tmp_path / "feature_cache",
        legacy_snapshot_dir=snapshot_dir,
    )

    store.load_financial_metrics("000001", "20260708")
    store.load_event_inputs("000001", "20260708")
    summary = store.build_quality_summary("20260708", ["000001"])

    scoring = summary["scoring_features"]
    for family, raw in scoring.items():
        # Every family must be parseable by the evidence schema. This guards
        # against regressions where a family is missing observation_status or
        # carries a bool/negative count.
        evidence = FeatureEvidence.from_mapping(family, raw)
        assert evidence.family == family


def test_build_quality_summary_financial_metrics_partial_when_one_of_two_requested_missing(
    tmp_path: Path,
) -> None:
    """Requested 2 tickers, only 1 has a snapshot → observation_status=partial.

    Conservation: partial means a strict subset of requested tickers received
    an authoritative answer. The missing ticker is a consumption failure.
    """
    snapshot_dir = tmp_path / "snapshots"
    fin_dir = snapshot_dir / "000001" / "20260708"
    fin_dir.mkdir(parents=True)
    (fin_dir / "financials.json").write_text(
        json.dumps(_full_financial_payload("000001")), encoding="utf-8"
    )
    store = ScoringFeatureStore(
        base_dir=tmp_path / "feature_cache",
        legacy_snapshot_dir=snapshot_dir,
    )

    store.load_financial_metrics("000001", "20260708")
    store.load_financial_metrics("000002", "20260708")  # no snapshot → failure
    summary = store.build_quality_summary("20260708", ["000001", "000002"])

    fin = summary["scoring_features"]["financial_metrics"]
    assert fin["observation_status"] == "partial"
    assert fin["observed_count"] == 1
    assert fin["requested_count"] == 2
    assert fin["consumption_failed_count"] == 1
