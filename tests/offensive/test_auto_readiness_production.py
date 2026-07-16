from __future__ import annotations

import inspect
import json
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from src import main as main_mod
from src.screening import auto_pipeline
from src.screening.auto_pipeline import AutoInputs
from src.screening.offensive.cache_readiness import (
    DailyActionRefreshResult,
    TickerRefreshOutcome,
    derive_stats_from_outcomes,
    universe_fingerprint,
)
from src.screening.offensive.daily_action_readiness import ManifestValidationError

from tests.test_main_auto_cache_refresh import (
    _fake_refresh_result,
)


def test_auto_refresh_bridge_requires_explicit_reports_dir() -> None:
    parameter = inspect.signature(
        main_mod._refresh_daily_action_caches_for_auto
    ).parameters["reports_dir"]

    assert parameter.default is inspect.Parameter.empty


def test_shared_evidence_builder_covers_frozen_ticker_outside_auto_pool() -> None:
    refresh_result = _fake_refresh_result()
    original = refresh_result.outcomes["000001"]
    outside = TickerRefreshOutcome(
        ticker="600000",
        price_status=original.price_status,
        price_history_rows=original.price_history_rows,
        fund_flow_status=original.fund_flow_status,
        fund_flow_history_rows=original.fund_flow_history_rows,
        evidence_fingerprints=dict(original.evidence_fingerprints),
        warnings=original.warnings,
    )
    outcomes = {"000001": original, "600000": outside}
    outside_pool_result = DailyActionRefreshResult(
        trade_date=refresh_result.trade_date,
        universe_tickers=("000001", "600000"),
        universe_fingerprint=universe_fingerprint(("000001", "600000")),
        daily_batch_fingerprint=refresh_result.daily_batch_fingerprint,
        suspension_evidence=refresh_result.suspension_evidence,
        outcomes=outcomes,
        stats=derive_stats_from_outcomes(outcomes),
    )
    payload = {
        "date": "20260708",
        "market_state": {"regime_gate_level": "normal"},
        "candidate_pool_run": {
            "trade_date": "20260708",
            "tickers": ["000001"],
            "candidates": [{"ticker": "000001", "industry_sw": "银行"}],
        },
    }
    stock_basic = pd.DataFrame(
        [
            {"ts_code": "000001.SZ", "name": "平安银行", "list_status": "L"},
            {"ts_code": "600000.SH", "name": "浦发银行", "list_status": "L"},
        ]
    )

    shared = main_mod._build_shared_readiness_evidence_for_auto(
        outside_pool_result,
        payload,
        stock_basic=stock_basic,
        sw_industry_by_ticker={"000001.SZ": "银行", "600000.SH": "银行"},
        industry_day_pct={("银行", "20260708"): 1.25},
    )

    assert shared.as_of_date == date(2026, 7, 8)
    assert set(shared.industry_by_ticker) == {"000001", "600000"}
    assert set(shared.security_status_by_ticker) == {"000001", "600000"}


@pytest.mark.parametrize("regime", ["", "garbage", "NORMAL", None])
def test_shared_evidence_builder_rejects_noncanonical_regime(regime: object) -> None:
    refresh_result = _fake_refresh_result()
    payload = {
        "date": "20260708",
        "market_state": {"regime_gate_level": regime},
    }
    with pytest.raises(ManifestValidationError, match="regime"):
        main_mod._build_shared_readiness_evidence_for_auto(
            refresh_result,
            payload,
            stock_basic=pd.DataFrame(
                [{"ts_code": "000001.SZ", "name": "平安银行", "list_status": "L"}]
            ),
            sw_industry_by_ticker={"000001.SZ": "银行"},
            industry_day_pct={("银行", "20260708"): 1.25},
        )


def test_repository_shared_evidence_uses_only_loaded_and_local_sources(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.tools import tushare_api

    industry_dir = tmp_path / "industry_index_cache"
    industry_dir.mkdir()
    (industry_dir / "_industry_codes.json").write_text(
        json.dumps({"801780.SI": "银行"}, ensure_ascii=False),
        encoding="utf-8",
    )
    pd.DataFrame([{"trade_date": "20260708", "pct_chg": 1.25}]).to_csv(
        industry_dir / "801780.SI.csv", index=False
    )
    monkeypatch.setattr(
        tushare_api,
        "_stock_basic_cache",
        pd.DataFrame(
            [{"ts_code": "000001.SZ", "name": "平安银行", "list_status": "L"}]
        ),
    )
    monkeypatch.setattr(tushare_api, "_sw_industry_cache", {"000001.SZ": "银行"})
    monkeypatch.setattr(
        tushare_api,
        "_call_tushare_dataframe_api",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("shared evidence must not call a network provider")
        ),
    )

    shared = main_mod._build_shared_readiness_evidence_for_auto(
        _fake_refresh_result(),
        {"date": "20260708", "market_state": {"regime_gate_level": "normal"}},
        data_dir=tmp_path,
    )

    assert shared.as_of_date == date(2026, 7, 8)
    assert shared.industry_day_pct == {"000001": 1.25}


def test_default_auto_orchestration_publishes_and_captures_real_readiness(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    refresh_result = _fake_refresh_result()
    payload = {
        "date": "20260708",
        "market_state": {"regime_gate_level": "normal"},
        "candidate_pool_run": {
            "trade_date": "20260708",
            "tickers": ["000001"],
            "candidates": [{"ticker": "000001", "industry_sw": "银行"}],
        },
        "recommendations": [],
    }
    captured_refresh_results: list[object] = []
    real_publish = main_mod._publish_daily_action_readiness_for_auto
    real_builder = main_mod._build_shared_readiness_evidence_for_auto

    monkeypatch.setattr(
        "src.screening.offensive.cache_refresh.refresh_daily_action_caches",
        lambda _trade_date: refresh_result,
    )
    monkeypatch.setattr(
        "src.screening.offensive.daily_action.refresh_authoritative_trade_calendar",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(
        "scripts.join_setup_outputs_with_returns.backfill_panel",
        lambda **_kwargs: ([], {"records": 0, "realized": 0}),
    )
    monkeypatch.setattr(
        "scripts.panel_health_check.panel_health_oneline", lambda *_args: "insufficient"
    )
    monkeypatch.setattr(main_mod, "compute_auto_screening_results", lambda *_args: dict(payload))
    def capture_builder(exact_result, exact_payload, **_kwargs):
        captured_refresh_results.append(exact_result)
        return real_builder(
            exact_result,
            exact_payload,
            stock_basic=pd.DataFrame(
                [
                    {
                        "ts_code": "000001.SZ",
                        "name": "平安银行",
                        "list_status": "L",
                    }
                ]
            ),
            sw_industry_by_ticker={"000001.SZ": "银行"},
            industry_day_pct={("银行", "20260708"): 1.25},
        )

    monkeypatch.setattr(
        main_mod,
        "_build_shared_readiness_evidence_for_auto",
        capture_builder,
    )

    def capture_publish(exact_result, **kwargs):
        captured_refresh_results.append(exact_result)
        return real_publish(exact_result, **kwargs)

    monkeypatch.setattr(main_mod, "_publish_daily_action_readiness_for_auto", capture_publish)
    monkeypatch.setattr(
        auto_pipeline,
        "_capture_input_snapshot",
        lambda trade_date, **kwargs: AutoInputs(
            trade_date=trade_date,
            prepared_at=auto_pipeline.datetime.now(auto_pipeline.timezone.utc),
            reports_dir=reports_dir,
            tickers={},
            industries={},
            ticker_industries={},
            cache_refresh_summary=kwargs.get("cache_refresh_summary", {}),
            baseline_tickers={},
            baseline_industries={},
            baseline_fingerprint="sha256:" + "0" * 64,
            baseline_consistent=True,
            industry_content_fingerprint="sha256:" + "0" * 64,
        ),
    )

    dependencies = auto_pipeline._default_dependencies(reports_dir, "run-20260708")
    inputs = dependencies.prepare_inputs("20260708")
    result_payload = dependencies.compute_report(inputs, 10)
    publication = dependencies.get_daily_readiness_publication()

    assert captured_refresh_results == [refresh_result, refresh_result]
    assert publication is not None
    assert publication.status == "healthy"
    assert publication.artifact_path == reports_dir / "daily_action_readiness_20260708.json"
    assert result_payload["daily_action_readiness"]["status"] == "healthy"
    assert result_payload["daily_action_readiness"]["universe_count"] == 1
    assert result_payload["daily_action_readiness"]["scannable_count"] == 1


def test_shared_evidence_build_failure_writes_attempt_and_preserves_canonical(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    canonical = tmp_path / "daily_action_readiness_20260708.json"
    canonical.write_bytes(b'{"existing":true}')
    refresh_result = _fake_refresh_result()

    publication = main_mod._complete_daily_action_readiness_for_auto(
        refresh_result,
        {"date": "20260708", "market_state": {"regime_gate_level": "garbage"}},
        reports_dir=tmp_path,
        shared_evidence_builder=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            ManifestValidationError("garbage regime")
        ),
    )

    assert publication.status == "degraded"
    assert "attempt" in publication.artifact_path.name
    assert canonical.read_bytes() == b'{"existing":true}'
