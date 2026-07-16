from __future__ import annotations

import inspect
import hashlib
import json
from datetime import date
from functools import partial
from pathlib import Path

import pandas as pd
import pytest

from src import main as main_mod
from src.screening import auto_pipeline
from src.screening.offensive.cache_readiness import (
    DailyActionRefreshResult,
    TickerRefreshOutcome,
    derive_stats_from_outcomes,
    universe_fingerprint,
)
from src.screening.offensive.daily_action_readiness import ManifestValidationError
from src.screening.offensive.shared_readiness_evidence import (
    build_shared_readiness_evidence_for_auto,
    capture_shared_readiness_evidence_source,
)

from tests.test_main_auto_cache_refresh import (
    _fake_refresh_result,
)


def _runtime_tree_state() -> dict[str, tuple[int, int, str | None]]:
    root = Path(__file__).resolve().parents[2] / "data"
    state: dict[str, tuple[int, int, str | None]] = {}
    cache_sqlite = root / "cache" / "cache.sqlite"
    hashed = {cache_sqlite, Path(f"{cache_sqlite}-wal"), Path(f"{cache_sqlite}-shm")}
    for path in root.rglob("*"):
        if path.is_file():
            stat = path.stat()
            digest = (
                hashlib.sha256(path.read_bytes()).hexdigest()
                if path in hashed
                else None
            )
            state[str(path)] = (stat.st_mtime_ns, stat.st_size, digest)
    return state


def test_auto_refresh_bridge_requires_explicit_reports_dir() -> None:
    parameter = inspect.signature(
        main_mod._refresh_daily_action_caches_for_auto
    ).parameters["reports_dir"]

    assert parameter.default is inspect.Parameter.empty


def test_auto_refresh_bridge_requires_explicit_data_dir() -> None:
    parameter = inspect.signature(
        main_mod._refresh_daily_action_caches_for_auto
    ).parameters["data_dir"]

    assert parameter.default is inspect.Parameter.empty


def test_frozen_shared_source_is_immune_to_later_repository_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.screening.offensive import daily_action_readiness as readiness_mod
    from src.tools import tushare_api

    refresh_result = _fake_refresh_result()
    stock_rows = [
        {"ts_code": "000001.SZ", "name": "平安银行", "list_status": "L"}
    ]
    sw_mapping = {"000001.SZ": "银行"}
    industry_values = {"银行": 1.25}

    frozen = capture_shared_readiness_evidence_source(
        refresh_result,
        data_dir=tmp_path,
        stock_basic_loader=lambda: stock_rows,
        sw_industry_loader=lambda: sw_mapping,
        industry_day_pct_loader=lambda _date, _industries: industry_values,
    )
    payload = {
        "date": "20260708",
        "market_state": {"regime_gate_level": "normal"},
    }
    before = build_shared_readiness_evidence_for_auto(
        refresh_result, payload, frozen_source=frozen
    )
    monkeypatch.setattr(
        readiness_mod, "new_readiness_run_id", lambda _result: "frozen-run"
    )
    publication_before = main_mod._publish_daily_action_readiness_for_auto(
        refresh_result,
        reports_dir=tmp_path / "before",
        shared_evidence=before,
    )

    stock_rows[0]["list_status"] = "D"
    sw_mapping["000001.SZ"] = "煤炭"
    industry_values["银行"] = -9.9
    monkeypatch.setattr(
        tushare_api,
        "_stock_basic_cache",
        pd.DataFrame(
            [{"ts_code": "000001.SZ", "name": "退市股票", "list_status": "D"}]
        ),
    )
    monkeypatch.setattr(tushare_api, "_sw_industry_cache", {"000001.SZ": "煤炭"})
    monkeypatch.setattr(
        tushare_api,
        "_call_tushare_dataframe_api",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("frozen evidence must never call a provider")
        ),
    )
    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()
    (snapshot_dir / "candidate_pool_20260708.json").write_text(
        json.dumps({"candidates": [{"ticker": "000001", "industry_sw": "煤炭"}]}),
        encoding="utf-8",
    )
    industry_dir = tmp_path / "industry_index_cache"
    industry_dir.mkdir()
    (industry_dir / "_industry_codes.json").write_text(
        json.dumps({"801780.SI": "银行"}, ensure_ascii=False), encoding="utf-8"
    )
    pd.DataFrame([{"trade_date": "20260708", "pct_chg": -9.9}]).to_csv(
        industry_dir / "801780.SI.csv", index=False
    )

    after = build_shared_readiness_evidence_for_auto(
        refresh_result, payload, frozen_source=frozen
    )
    publication_after = main_mod._publish_daily_action_readiness_for_auto(
        refresh_result,
        reports_dir=tmp_path / "after",
        shared_evidence=after,
    )
    assert after.to_dict() == before.to_dict()
    before_manifest = publication_before.manifest.to_dict()
    after_manifest = publication_after.manifest.to_dict()
    for payload_copy in (before_manifest, after_manifest):
        payload_copy.pop("created_at")
        payload_copy.pop("content_fingerprint")
    assert after_manifest == before_manifest


def test_shared_builder_requires_exact_frozen_universe(tmp_path: Path) -> None:
    refresh_result = _fake_refresh_result()
    frozen = capture_shared_readiness_evidence_source(
        refresh_result,
        data_dir=tmp_path,
        stock_basic_loader=lambda: [
            {"ts_code": "000001.SZ", "name": "平安银行", "list_status": "L"}
        ],
        sw_industry_loader=lambda: {"000001.SZ": "银行"},
        industry_day_pct_loader=lambda _date, _industries: {"银行": 1.25},
    )
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
    different = DailyActionRefreshResult(
        trade_date=refresh_result.trade_date,
        universe_tickers=("000001", "600000"),
        universe_fingerprint=universe_fingerprint(("000001", "600000")),
        daily_batch_fingerprint=refresh_result.daily_batch_fingerprint,
        suspension_evidence=refresh_result.suspension_evidence,
        outcomes=outcomes,
        stats=derive_stats_from_outcomes(outcomes),
    )
    with pytest.raises(ManifestValidationError, match="frozen source"):
        build_shared_readiness_evidence_for_auto(
            different,
            {"date": "20260708", "market_state": {"regime_gate_level": "normal"}},
            frozen_source=frozen,
        )


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

    frozen = capture_shared_readiness_evidence_source(
        outside_pool_result,
        data_dir=Path("unused"),
        stock_basic_loader=lambda: stock_basic,
        sw_industry_loader=lambda: {"000001.SZ": "银行", "600000.SH": "银行"},
        industry_day_pct_loader=lambda _date, _industries: {"银行": 1.25},
    )
    shared = main_mod._build_shared_readiness_evidence_for_auto(
        outside_pool_result, payload, frozen_source=frozen
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
    frozen = capture_shared_readiness_evidence_source(
        refresh_result,
        data_dir=Path("unused"),
        stock_basic_loader=lambda: [
            {"ts_code": "000001.SZ", "name": "平安银行", "list_status": "L"}
        ],
        sw_industry_loader=lambda: {"000001.SZ": "银行"},
        industry_day_pct_loader=lambda _date, _industries: {"银行": 1.25},
    )
    with pytest.raises(ManifestValidationError, match="regime"):
        main_mod._build_shared_readiness_evidence_for_auto(
            refresh_result,
            payload,
            frozen_source=frozen,
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

    refresh_result = _fake_refresh_result()
    frozen = main_mod._capture_shared_readiness_evidence_source_for_auto(
        refresh_result,
        data_dir=tmp_path,
    )
    shared = main_mod._build_shared_readiness_evidence_for_auto(
        refresh_result,
        {"date": "20260708", "market_state": {"regime_gate_level": "normal"}},
        frozen_source=frozen,
    )

    assert shared.as_of_date == date(2026, 7, 8)
    assert shared.industry_day_pct == {"000001": 1.25}


def test_default_auto_orchestration_publishes_and_captures_real_readiness(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.screening.offensive.cache_readiness import SuspensionEvidence
    from src.screening.offensive.cache_refresh import refresh_daily_action_caches
    from src.screening.offensive.pit_evidence import canonical_fingerprint
    from src.tools import tushare_api
    from tests.offensive.readiness_v2_testkit import (
        SIGNAL_DATE,
        SIGNAL_DATE_TEXT,
        _preseed_caches,
        fixture_daily_batch_20260713,
        fixture_fund_flow,
        fixture_price_history,
    )

    workspace_before = _runtime_tree_state()
    data_dir = tmp_path / "data"
    reports_dir = data_dir / "reports"
    reports_dir.mkdir(parents=True)
    _preseed_caches(data_dir, ("000001",))
    (data_dir / "snapshots").mkdir()
    (data_dir / "snapshots" / f"candidate_pool_{SIGNAL_DATE_TEXT}.json").write_text(
        "[]", encoding="utf-8"
    )
    industry_dir = data_dir / "industry_index_cache"
    industry_dir.mkdir()
    (industry_dir / "_industry_codes.json").write_text(
        json.dumps({"801780.SI": "银行"}, ensure_ascii=False), encoding="utf-8"
    )
    pd.DataFrame([{"trade_date": SIGNAL_DATE_TEXT, "pct_chg": 1.25}]).to_csv(
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
    payload = {
        "date": SIGNAL_DATE_TEXT,
        "market_state": {"regime_gate_level": "normal"},
        "candidate_pool_run": {
            "trade_date": SIGNAL_DATE_TEXT,
            "tickers": [],
            "candidates": [],
        },
        "recommendations": [],
    }
    monkeypatch.setattr(main_mod, "compute_auto_screening_results", lambda *_args: dict(payload))
    monkeypatch.setattr(main_mod, "_attach_freshness_check", lambda *_args: None)
    actual_refresh = partial(
        refresh_daily_action_caches,
        daily_prices_df=fixture_daily_batch_20260713(("000001",)),
        target_tickers=("000001",),
        backfill_price_history_fn=fixture_price_history,
        fund_flow_fetch_fn=fixture_fund_flow,
        refresh_industry_index=False,
        refresh_fund_flow=True,
        fund_flow_rate_limit_sec=0.0,
        suspension_loader=lambda _trade_date: SuspensionEvidence.available(
            SIGNAL_DATE,
            set(),
            source_fingerprint=canonical_fingerprint("suspension", "*", ()),
        ),
    )
    monkeypatch.setenv("DAILY_ACTION_DISABLED_SETUPS", "none")
    dependencies = auto_pipeline._default_dependencies(
        reports_dir,
        data_dir,
        "run-20260713",
        refresh_fn=actual_refresh,
        calendar_refresh_fn=lambda **_kwargs: None,
        panel_backfill_fn=lambda **_kwargs: ([], {"records": 0, "realized": 0}),
        panel_health_fn=lambda *_args: "insufficient",
    )
    # Runtime policy is part of the orchestration snapshot. A later mutation
    # must not change what the publisher authorizes for this run.
    monkeypatch.setenv("DAILY_ACTION_DISABLED_SETUPS", "oversold_bounce")
    inputs = dependencies.prepare_inputs(SIGNAL_DATE_TEXT)
    result_payload = dependencies.compute_report(inputs, 10)
    publication = dependencies.get_daily_readiness_publication()

    assert publication is not None
    assert publication.status == "healthy"
    assert publication.artifact_path == reports_dir / "daily_action_readiness_20260713.json"
    assert result_payload["daily_action_readiness"]["status"] == "healthy"
    assert result_payload["daily_action_readiness"]["universe_count"] == 1
    assert result_payload["daily_action_readiness"]["scannable_count"] == 1
    assert publication.manifest.ticker_readiness["000001"].capabilities[
        "oversold_bounce"
    ].enabled is True
    workspace_after = _runtime_tree_state()
    workspace_data = Path(__file__).resolve().parents[2] / "data"
    for suffix in ("", "-wal", "-shm"):
        cache_file = str(workspace_data / "cache" / f"cache.sqlite{suffix}")
        assert workspace_after.get(cache_file) == workspace_before.get(cache_file)
    assert workspace_after == workspace_before


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
        frozen_source=object(),
        shared_evidence_builder=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            ManifestValidationError("garbage regime")
        ),
    )

    assert publication.status == "degraded"
    assert "attempt" in publication.artifact_path.name
    assert canonical.read_bytes() == b'{"existing":true}'
