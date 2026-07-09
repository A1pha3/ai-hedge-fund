from __future__ import annotations

from types import SimpleNamespace

import src.main as main_module


def test_build_auto_screening_payload_includes_optional_feature_quality(monkeypatch):
    monkeypatch.setattr(main_module, "_compute_model_version", lambda: "test-sha")
    market_state = SimpleNamespace(model_dump=lambda: {"regime": "mixed"})
    fused = [SimpleNamespace(score_b=0.4)]
    optional_feature_quality = {
        "optional_features": {
            "intraday_short_trade_metrics": {
                "coverage": 0.5,
                "source": "snapshot",
                "trade_date": "20260708",
                "stale": False,
                "provider_failures": 1,
                "missing_tickers": 1,
            }
        }
    }

    payload = main_module._build_auto_screening_payload(
        trade_date="20260708",
        top_n=10,
        market_state=market_state,
        candidates=[object(), object()],
        fused=fused,
        top_results_serializable=[],
        sector_warnings=[],
        consecutive_highlight=0,
        decay_summary={},
        industry_rotation_payload=[],
        batch_fetcher_use_batch=True,
        batch_fetcher_stats={"batch_calls": 1},
        optional_feature_quality=optional_feature_quality,
    )

    assert payload["data_quality"]["optional_features"]["intraday_short_trade_metrics"]["coverage"] == 0.5


def test_compute_auto_screening_results_reports_feature_store_quality(monkeypatch):
    saved: list[tuple[str, dict]] = []
    score_feature_stores: list[object] = []
    events: list[tuple[str, object]] = []
    candidates = [SimpleNamespace(ticker="000001"), SimpleNamespace(ticker="000002")]

    class FakeBatchFetcher:
        use_batch = True
        _max_concurrency = 1

        def reset_stats(self):
            return None

        def stats(self):
            return {"batch_calls": 0}

    class FakeScoringFeatureStore:
        instances: list["FakeScoringFeatureStore"] = []

        def __init__(self):
            self.quality_calls: list[tuple[str, list[str]]] = []
            self.instances.append(self)

        def build_quality_summary(self, trade_date: str, tickers: list[str]) -> dict:
            self.quality_calls.append((trade_date, tickers))
            return {
                "scoring_features": {
                    "price_history": {
                        "coverage": 1.0,
                        "source": "local_price_cache",
                        "trade_date": trade_date,
                        "stale": False,
                        "provider_failures": 0,
                        "missing_tickers": 0,
                    }
                },
                "optional_features": {
                    "intraday_short_trade_metrics": {
                        "coverage": 1.0,
                        "source": "snapshot",
                        "trade_date": trade_date,
                        "stale": False,
                        "provider_failures": 0,
                        "missing_tickers": 0,
                    }
                },
            }

    class FakeFused:
        ticker = "000001"
        score_b = 0.8

        def model_dump(self, mode=None):
            return {"ticker": self.ticker, "name": "Fake", "score_b": self.score_b}

    def fake_score_batch(scoring_candidates, scoring_date, *, feature_store):
        assert scoring_candidates == candidates
        assert scoring_date == "20260708"
        events.append(("score", feature_store))
        score_feature_stores.append(feature_store)
        return {"000001": {}}

    def fake_refresh_scoring_features(scoring_date, tickers, *, timeout_seconds):
        events.append(("refresh", list(tickers)))
        assert scoring_date == "20260708"
        assert list(tickers) == ["000001", "000002"]
        assert timeout_seconds == 0.25
        return {"status": "ready"}

    monkeypatch.setattr(
        "src.screening.batch_data_fetcher.get_global_batch_data_fetcher",
        lambda: FakeBatchFetcher(),
    )
    monkeypatch.setattr("src.screening.scoring_feature_store.ScoringFeatureStore", FakeScoringFeatureStore)
    monkeypatch.setattr(
        "src.screening.scoring_feature_refresh.refresh_scoring_features",
        fake_refresh_scoring_features,
    )
    monkeypatch.setenv("AUTO_OPTIONAL_FEATURE_REFRESH_TIMEOUT_SECONDS", "0.25")
    monkeypatch.setattr(main_module, "_compute_model_version", lambda: "test-sha")
    monkeypatch.setattr(main_module, "build_candidate_pool", lambda trade_date: candidates)
    monkeypatch.setattr(main_module, "score_batch", fake_score_batch)
    monkeypatch.setattr(
        main_module,
        "detect_market_state",
        lambda trade_date: SimpleNamespace(model_dump=lambda: {"regime": "mixed"}),
    )
    monkeypatch.setattr(main_module, "fuse_batch", lambda scored, market_state, trade_date, candidates=None: [FakeFused()])
    monkeypatch.setattr(main_module, "_inject_score_decomposition", lambda ranking_pool, fused_by_ticker: len(ranking_pool))
    monkeypatch.setattr(main_module, "_rank_pool_by_investability", lambda ranking_pool, trade_date: ranking_pool)
    monkeypatch.setattr(main_module, "_check_sector_concentration", lambda results: [])
    monkeypatch.setattr(main_module, "_resolve_consecutive_report_dir", lambda: None)
    monkeypatch.setattr(main_module, "enrich_recommendations_with_history", lambda recommendations, **kwargs: recommendations)
    monkeypatch.setattr(main_module, "_inject_recommended_prices", lambda recommendations, trade_date: recommendations)
    monkeypatch.setattr(main_module, "_attach_signal_decay", lambda recommendations, report_dir, trade_date: {})
    monkeypatch.setattr(main_module, "calculate_industry_rotation", lambda recommendations, trade_date: [])
    monkeypatch.setattr(main_module, "_save_json_report", lambda filename, payload: saved.append((filename, payload)))

    payload = main_module.compute_auto_screening_results("20260708", top_n=1)

    expected_quality = {
        "scoring_features": {
            "price_history": {
                "coverage": 1.0,
                "source": "local_price_cache",
                "trade_date": "20260708",
                "stale": False,
                "provider_failures": 0,
                "missing_tickers": 0,
            }
        },
        "optional_features": {
            "intraday_short_trade_metrics": {
                "coverage": 1.0,
                "source": "snapshot",
                "trade_date": "20260708",
                "stale": False,
                "provider_failures": 0,
                "missing_tickers": 0,
            }
        },
    }
    assert events[0] == ("refresh", ["000001", "000002"])
    assert events[1][0] == "score"
    assert score_feature_stores == FakeScoringFeatureStore.instances
    assert FakeScoringFeatureStore.instances[0].quality_calls == [
        ("20260708", ["000001", "000002"])
    ]
    assert saved[0][1]["data_quality"] == expected_quality
    assert payload["data_quality"] == expected_quality


def test_compute_auto_screening_results_falls_back_to_legacy_scoring_when_refresh_not_ready(monkeypatch):
    saved: list[tuple[str, dict]] = []
    events: list[tuple[str, object]] = []
    candidates = [SimpleNamespace(ticker="000001"), SimpleNamespace(ticker="000002")]

    class FakeBatchFetcher:
        use_batch = True
        _max_concurrency = 1

        def reset_stats(self):
            return None

        def stats(self):
            return {"batch_calls": 0}

    class FakeFused:
        ticker = "000001"
        score_b = 0.8

        def model_dump(self, mode=None):
            return {"ticker": self.ticker, "name": "Fake", "score_b": self.score_b}

    def fake_score_batch(scoring_candidates, scoring_date, *, feature_store):
        assert scoring_candidates == candidates
        assert scoring_date == "20260708"
        assert feature_store is None
        events.append(("score", feature_store))
        return {"000001": {}}

    def fake_refresh_scoring_features(scoring_date, tickers, *, timeout_seconds):
        events.append(("refresh", list(tickers)))
        assert scoring_date == "20260708"
        assert list(tickers) == ["000001", "000002"]
        assert timeout_seconds == 0.25
        return {"status": "not_implemented"}

    monkeypatch.setattr(
        "src.screening.batch_data_fetcher.get_global_batch_data_fetcher",
        lambda: FakeBatchFetcher(),
    )
    monkeypatch.setattr(
        "src.screening.scoring_feature_store.ScoringFeatureStore",
        lambda: (_ for _ in ()).throw(AssertionError("feature store should stay disabled")),
    )
    monkeypatch.setattr(
        "src.screening.scoring_feature_refresh.refresh_scoring_features",
        fake_refresh_scoring_features,
    )
    monkeypatch.setenv("AUTO_OPTIONAL_FEATURE_REFRESH_TIMEOUT_SECONDS", "0.25")
    monkeypatch.setattr(main_module, "_compute_model_version", lambda: "test-sha")
    monkeypatch.setattr(main_module, "build_candidate_pool", lambda trade_date: candidates)
    monkeypatch.setattr(main_module, "score_batch", fake_score_batch)
    monkeypatch.setattr(
        main_module,
        "detect_market_state",
        lambda trade_date: SimpleNamespace(model_dump=lambda: {"regime": "mixed"}),
    )
    monkeypatch.setattr(main_module, "fuse_batch", lambda scored, market_state, trade_date, candidates=None: [FakeFused()])
    monkeypatch.setattr(main_module, "_inject_score_decomposition", lambda ranking_pool, fused_by_ticker: len(ranking_pool))
    monkeypatch.setattr(main_module, "_rank_pool_by_investability", lambda ranking_pool, trade_date: ranking_pool)
    monkeypatch.setattr(main_module, "_check_sector_concentration", lambda results: [])
    monkeypatch.setattr(main_module, "_resolve_consecutive_report_dir", lambda: None)
    monkeypatch.setattr(main_module, "enrich_recommendations_with_history", lambda recommendations, **kwargs: recommendations)
    monkeypatch.setattr(main_module, "_inject_recommended_prices", lambda recommendations, trade_date: recommendations)
    monkeypatch.setattr(main_module, "_attach_signal_decay", lambda recommendations, report_dir, trade_date: {})
    monkeypatch.setattr(main_module, "calculate_industry_rotation", lambda recommendations, trade_date: [])
    monkeypatch.setattr(main_module, "_save_json_report", lambda filename, payload: saved.append((filename, payload)))

    payload = main_module.compute_auto_screening_results("20260708", top_n=1)

    assert events[0] == ("refresh", ["000001", "000002"])
    assert events[1] == ("score", None)
    assert saved[0][1]["data_quality"] == {"optional_features": {}}
    assert payload["data_quality"] == {"optional_features": {}}
