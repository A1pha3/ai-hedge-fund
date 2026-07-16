from __future__ import annotations

import inspect
import hashlib
import json
import subprocess
import sys
import textwrap
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
    make_daily_readiness_reference_snapshot,
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


def _reference_snapshot(
    signal_date: date,
    *,
    stock_rows: object | None = None,
    sw_mapping: object | None = None,
    security_observed_on: date | None = None,
    security_effective_from: date | None = None,
    security_effective_through: date | None = None,
    sw_observed_on: date | None = None,
    sw_effective_from: date | None = None,
    sw_effective_through: date | None = None,
):
    return make_daily_readiness_reference_snapshot(
        stock_basic=(
            stock_rows
            if stock_rows is not None
            else [{"ts_code": "000001.SZ", "name": "平安银行", "list_status": "L"}]
        ),
        sw_industry_by_ticker=(
            sw_mapping if sw_mapping is not None else {"000001.SZ": "银行"}
        ),
        security_observed_on=security_observed_on or signal_date,
        security_effective_from=security_effective_from or signal_date,
        security_effective_through=security_effective_through or signal_date,
        security_source="tushare.stock_basic",
        security_version="stock-basic-v1",
        sw_observed_on=sw_observed_on or signal_date,
        sw_effective_from=sw_effective_from or signal_date,
        sw_effective_through=sw_effective_through or signal_date,
        sw_source="tushare.index_classify+index_member",
        sw_version="sw2021-v1",
    )


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
        reference_snapshot_loader=lambda: _reference_snapshot(
            refresh_result.trade_date,
            stock_rows=stock_rows,
            sw_mapping=sw_mapping,
        ),
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
        reference_snapshot_loader=lambda: _reference_snapshot(refresh_result.trade_date),
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
        reference_snapshot_loader=lambda: _reference_snapshot(
            outside_pool_result.trade_date,
            stock_rows=stock_basic,
            sw_mapping={"000001.SZ": "银行", "600000.SH": "银行"},
        ),
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
        reference_snapshot_loader=lambda: _reference_snapshot(refresh_result.trade_date),
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
    snapshot = _reference_snapshot(date(2026, 7, 8))
    monkeypatch.setattr(
        tushare_api,
        "get_daily_readiness_reference_snapshot",
        lambda: snapshot,
    )
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


@pytest.mark.parametrize("signal_date", [date(2026, 7, 8), date(2026, 7, 9)])
def test_undated_reference_tuple_never_authorizes_any_signal_date(
    tmp_path: Path,
    signal_date: date,
) -> None:
    refresh_result = _fake_refresh_result(trade_date=signal_date)
    with pytest.raises(ManifestValidationError, match="typed|dated|reference"):
        capture_shared_readiness_evidence_source(
            refresh_result,
            data_dir=tmp_path,
            reference_snapshot_loader=lambda: (
                pd.DataFrame(
                    [{"ts_code": "000001.SZ", "name": "平安银行", "list_status": "L"}]
                ),
                {"000001.SZ": "银行"},
            ),
            industry_day_pct_loader=lambda _date, _industries: {"银行": 1.25},
        )


@pytest.mark.parametrize("stale_source", ["security", "sw"])
def test_stale_reference_provenance_fails_closed(
    tmp_path: Path,
    stale_source: str,
) -> None:
    signal_date = date(2026, 7, 8)
    kwargs = (
        {"security_observed_on": date(2026, 7, 7)}
        if stale_source == "security"
        else {"sw_observed_on": date(2026, 7, 7)}
    )
    with pytest.raises(ManifestValidationError, match="observed|signal date"):
        capture_shared_readiness_evidence_source(
            _fake_refresh_result(),
            data_dir=tmp_path,
            reference_snapshot_loader=lambda: _reference_snapshot(signal_date, **kwargs),
            industry_day_pct_loader=lambda _date, _industries: {"银行": 1.25},
        )


def test_valid_dated_reference_provenance_is_bound_into_frozen_fingerprint(
    tmp_path: Path,
) -> None:
    refresh_result = _fake_refresh_result()
    snapshot = _reference_snapshot(refresh_result.trade_date)
    frozen = capture_shared_readiness_evidence_source(
        refresh_result,
        data_dir=tmp_path,
        reference_snapshot_loader=lambda: snapshot,
        industry_day_pct_loader=lambda _date, _industries: {"银行": 1.25},
    )

    assert frozen.security_reference.observed_on == refresh_result.trade_date
    assert frozen.sw_reference.effective_from <= refresh_result.trade_date
    assert frozen.sw_reference.effective_through >= refresh_result.trade_date
    assert frozen.security_reference.source_fingerprint.startswith("sha256:")
    assert frozen.sw_reference.source_fingerprint.startswith("sha256:")


def test_reference_version_changes_shared_and_manifest_fingerprints(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    refresh_result = _fake_refresh_result()
    payload = {
        "date": "20260708",
        "market_state": {"regime_gate_level": "normal"},
    }

    def build(version: str, output_dir: Path):
        snapshot = make_daily_readiness_reference_snapshot(
            stock_basic=[
                {"ts_code": "000001.SZ", "name": "平安银行", "list_status": "L"}
            ],
            sw_industry_by_ticker={"000001.SZ": "银行"},
            security_observed_on=refresh_result.trade_date,
            security_effective_from=refresh_result.trade_date,
            security_effective_through=refresh_result.trade_date,
            security_source="tushare.stock_basic",
            security_version=version,
            sw_observed_on=refresh_result.trade_date,
            sw_effective_from=refresh_result.trade_date,
            sw_effective_through=refresh_result.trade_date,
            sw_source="tushare.index_classify+index_member",
            sw_version="sw2021-v1",
        )
        frozen = capture_shared_readiness_evidence_source(
            refresh_result,
            data_dir=tmp_path,
            reference_snapshot_loader=lambda: snapshot,
            industry_day_pct_loader=lambda _date, _industries: {"银行": 1.25},
        )
        shared = build_shared_readiness_evidence_for_auto(
            refresh_result, payload, frozen_source=frozen
        )
        monkeypatch.setattr(
            "src.screening.offensive.daily_action_readiness.new_readiness_run_id",
            lambda _result: "reference-version-test",
        )
        publication = main_mod._publish_daily_action_readiness_for_auto(
            refresh_result,
            reports_dir=output_dir,
            shared_evidence=shared,
        )
        return shared, publication.manifest

    first_shared, first_manifest = build("stock-basic-v1", tmp_path / "first")
    second_shared, second_manifest = build("stock-basic-v2", tmp_path / "second")

    assert first_shared.security_reference.version == "stock-basic-v1"
    assert second_shared.security_reference.version == "stock-basic-v2"
    assert first_shared.evidence_fingerprint != second_shared.evidence_fingerprint
    assert first_manifest.content_fingerprint != second_manifest.content_fingerprint
    assert (
        first_manifest.to_dict()["shared_evidence"]["security_reference"]
        != second_manifest.to_dict()["shared_evidence"]["security_reference"]
    )


def test_default_auto_orchestration_publishes_and_captures_real_readiness(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.screening.offensive.cache_readiness import SuspensionEvidence
    from src.screening.offensive.cache_refresh import refresh_daily_action_caches
    from src.screening.offensive.pit_evidence import canonical_fingerprint
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

    def temp_industry_backfill(*, end_date: str, cache_dir: Path) -> dict[str, int]:
        assert end_date == SIGNAL_DATE_TEXT
        assert cache_dir == industry_dir
        cache_dir.mkdir(parents=True, exist_ok=True)
        (cache_dir / "_industry_codes.json").write_text(
            json.dumps({"801780.SI": "银行"}, ensure_ascii=False), encoding="utf-8"
        )
        pd.DataFrame([{"trade_date": end_date, "pct_chg": 1.25}]).to_csv(
            cache_dir / "801780.SI.csv", index=False
        )
        return {"银行": 1}
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
        industry_index_backfill_fn=temp_industry_backfill,
        fund_flow_fetch_fn=fixture_fund_flow,
        refresh_industry_index=True,
        refresh_fund_flow=True,
        fund_flow_rate_limit_sec=0.0,
        suspension_loader=lambda _trade_date: SuspensionEvidence.available(
            SIGNAL_DATE,
            set(),
            source_fingerprint=canonical_fingerprint("suspension", "*", ()),
        ),
    )
    monkeypatch.setenv("DAILY_ACTION_DISABLED_SETUPS", "none")
    monkeypatch.setenv("PREHEAT_BEFORE_AUTO", "true")
    monkeypatch.setattr(
        "src.data.cache_preheater.preheat_cache",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("default temp-root dependencies must not preheat global cache")
        ),
    )
    dependencies = auto_pipeline._default_dependencies(
        reports_dir,
        data_dir,
        "run-20260713",
        refresh_fn=actual_refresh,
        calendar_refresh_fn=lambda **_kwargs: None,
        panel_backfill_fn=lambda **_kwargs: ([], {"records": 0, "realized": 0}),
        panel_health_fn=lambda *_args: "insufficient",
        reference_snapshot_loader=lambda: _reference_snapshot(SIGNAL_DATE),
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


def test_cold_start_default_reference_capture_is_rooted_under_tmp(
    tmp_path: Path,
) -> None:
    workspace_before = _runtime_tree_state()
    script = textwrap.dedent(
        """
        import json
        import os
        import sys
        from datetime import date
        from functools import partial
        from pathlib import Path

        root = Path(sys.argv[1])
        data_dir = root / "data"
        reports_dir = data_dir / "reports"
        os.environ["DISK_CACHE_PATH"] = str(data_dir / "cache" / "cache.sqlite")
        os.environ["PREHEAT_BEFORE_AUTO"] = "true"

        import pandas as pd
        from src import main
        from src.screening import auto_pipeline
        from src.screening.offensive.cache_readiness import SuspensionEvidence
        from src.screening.offensive.cache_refresh import refresh_daily_action_caches
        from src.screening.offensive.pit_evidence import canonical_fingerprint
        from src.tools import tushare_api

        signal = date.today()
        signal_text = signal.strftime("%Y%m%d")
        reports_dir.mkdir(parents=True)
        (data_dir / "snapshots").mkdir()
        dates = pd.date_range(end=signal, periods=40, freq="D")
        price = pd.DataFrame({
            "ticker": ["000001"] * len(dates),
            "date": dates.strftime("%Y-%m-%d"),
            "open": [10.0] * len(dates),
            "high": [11.0] * len(dates),
            "low": [9.8] * len(dates),
            "close": [10.5] * len(dates),
            "pct_change": [1.0] * len(dates),
            "volume": [1000000.0] * len(dates),
        })
        flow = pd.DataFrame({
            "ticker": ["000001"] * 20,
            "date": dates[-20:].strftime("%Y-%m-%d"),
            "close": [10.5] * 20,
            "pct_change": [1.0] * 20,
            "main_net_inflow": [1000.0] * 20,
            "main_net_pct": [1.0] * 20,
        })
        for directory, frame in (
            (data_dir / "price_cache", price),
            (data_dir / "fund_flow_cache", flow),
        ):
            directory.mkdir(parents=True)
            frame.to_csv(directory / "000001.csv", index=False)

        daily = pd.DataFrame([{
            "ts_code": "000001.SZ", "trade_date": signal_text,
            "open": 10.0, "high": 11.0, "low": 9.8, "close": 10.5,
            "pct_chg": 1.0, "vol": 1000000.0,
        }])

        def industry_backfill(*, end_date, cache_dir):
            cache_dir.mkdir(parents=True, exist_ok=True)
            (cache_dir / "_industry_codes.json").write_text(
                json.dumps({"801780.SI": "银行"}, ensure_ascii=False),
                encoding="utf-8",
            )
            pd.DataFrame([{"trade_date": end_date, "pct_chg": 1.25}]).to_csv(
                cache_dir / "801780.SI.csv", index=False
            )
            return {"银行": 1}

        actual_refresh = partial(
            refresh_daily_action_caches,
            daily_prices_df=daily,
            target_tickers=("000001",),
            backfill_price_history_fn=lambda *_args: price,
            industry_index_backfill_fn=industry_backfill,
            fund_flow_fetch_fn=lambda *_args, **_kwargs: flow.tail(1),
            refresh_industry_index=True,
            refresh_fund_flow=True,
            fund_flow_rate_limit_sec=0.0,
            suspension_loader=lambda _trade_date: SuspensionEvidence.available(
                signal, set(),
                source_fingerprint=canonical_fingerprint("suspension", "*", ()),
            ),
        )

        tushare_api._get_pro = lambda: object()
        def provider(_pro, api_name, **_kwargs):
            if api_name == "stock_basic":
                return pd.DataFrame([{
                    "ts_code": "000001.SZ", "name": "平安银行", "list_status": "L"
                }])
            if api_name == "index_classify":
                return pd.DataFrame([{
                    "index_code": "801780.SI", "industry_name": "银行"
                }])
            if api_name == "index_member":
                return pd.DataFrame([{
                    "con_code": "000001.SZ", "in_date": "20000101", "out_date": None
                }])
            raise AssertionError(api_name)
        tushare_api._call_tushare_dataframe_api = provider

        def compute(_trade_date, _top_n):
            assert tushare_api.get_all_stock_basic() is not None
            assert tushare_api.get_sw_industry_classification() == {"000001.SZ": "银行"}
            return {
                "date": signal_text,
                "market_state": {"regime_gate_level": "normal"},
                "candidate_pool_run": {
                    "trade_date": signal_text, "tickers": [], "candidates": []
                },
                "recommendations": [],
            }
        main.compute_auto_screening_results = compute
        main._attach_freshness_check = lambda *_args: None

        dependencies = auto_pipeline._default_dependencies(
            reports_dir,
            data_dir,
            "cold-start",
            refresh_fn=actual_refresh,
            calendar_refresh_fn=lambda **_kwargs: None,
            panel_backfill_fn=lambda **_kwargs: ([], {"records": 0, "realized": 0}),
            panel_health_fn=lambda *_args: "insufficient",
        )
        inputs = dependencies.prepare_inputs(signal_text)
        payload = dependencies.compute_report(inputs, 10)
        publication = dependencies.get_daily_readiness_publication()
        assert publication.status == "healthy"
        assert payload["daily_action_readiness"]["status"] == "healthy"
        assert publication.manifest.universe_tickers == ("000001",)
        print(json.dumps({"status": publication.status}))
        """
    )
    completed = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path)],
        cwd=Path(__file__).resolve().parents[2],
        text=True,
        capture_output=True,
        check=False,
        timeout=120,
    )
    assert completed.returncode == 0, completed.stderr + completed.stdout
    assert json.loads(completed.stdout.splitlines()[-1]) == {"status": "healthy"}
    assert _runtime_tree_state() == workspace_before


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
