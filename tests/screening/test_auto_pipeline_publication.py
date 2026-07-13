from __future__ import annotations

import json
import math
import shutil
from dataclasses import dataclass, replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from src.screening.auto_pipeline import (
    AutoPipelineDependencies,
    AutoRunStatus,
    _build_default_manifest,
    _canonical_fingerprint,
    _candidate_records,
    _capture_input_snapshot,
    _finalize_inputs_after_compute,
    _input_snapshot_is_current,
    _pending_state_checksum,
    _quality_is_healthy,
    run_auto_pipeline,
)
from src.utils.atomic_files import atomic_write_json


class _InjectedCrash(BaseException):
    pass


@dataclass(frozen=True)
class _FakeAutoDependenciesFactory:
    reports_dir: Path
    events: list[tuple[str, object]]

    def healthy(self) -> AutoPipelineDependencies:
        return self._dependencies(is_healthy=True, run_id="healthy-run")

    def degraded(self) -> AutoPipelineDependencies:
        return self._dependencies(is_healthy=False, run_id="degraded-run")

    def fatal(self, message: str = "compute exploded") -> AutoPipelineDependencies:
        dependencies = self._dependencies(is_healthy=True, run_id="fatal-run")

        def fail_compute(_inputs: object, _top_n: int) -> dict[str, Any]:
            raise RuntimeError(message)

        return replace(dependencies, compute_report=fail_compute)

    def _dependencies(
        self, *, is_healthy: bool, run_id: str
    ) -> AutoPipelineDependencies:
        payload = {
            "date": "20260710",
            "mode": "auto_screening",
            "recommendations": [{"ticker": "000001", "score_b": 0.5}],
        }
        manifest = SimpleNamespace(
            run_id=run_id,
            is_healthy=is_healthy,
            tickers={
                "000001": SimpleNamespace(
                    trade_ready=True,
                    cache_fingerprint="sha256:test",
                )
            },
        )

        def prepare_inputs(trade_date: str) -> dict[str, str]:
            self.events.append(("prepare", trade_date))
            return {"trade_date": trade_date}

        def compute_report(inputs: object, top_n: int) -> dict[str, Any]:
            self.events.append(("compute", top_n))
            return payload

        def build_manifest(inputs: object, report_payload: dict[str, Any]) -> object:
            self.events.append(("manifest", report_payload))
            return manifest

        def publish_canonical(
            report_payload: dict[str, Any], run_manifest: object
        ) -> Path:
            self.events.append(("canonical", report_payload))
            path = self.reports_dir / "auto_screening_20260710.json"
            atomic_write_json(
                path,
                {**report_payload, "status": "healthy", "run_id": run_manifest.run_id},
            )
            return path

        def publish_attempt(
            report_payload: dict[str, Any], run_manifest: object
        ) -> Path:
            self.events.append(("attempt", report_payload))
            path = (
                self.reports_dir / f"auto_attempt_20260710_{run_manifest.run_id}.json"
            )
            atomic_write_json(
                path,
                {**report_payload, "status": "degraded", "run_id": run_manifest.run_id},
            )
            return path

        def update_tracking(report_payload: dict[str, Any]) -> int:
            self.events.append(("tracking", report_payload))
            return 1

        return AutoPipelineDependencies(
            prepare_inputs=prepare_inputs,
            compute_report=compute_report,
            build_manifest=build_manifest,
            publish_canonical=publish_canonical,
            publish_attempt=publish_attempt,
            update_tracking=update_tracking,
        )


@pytest.fixture
def fake_auto_dependencies(tmp_path: Path) -> _FakeAutoDependenciesFactory:
    return _FakeAutoDependenciesFactory(tmp_path, [])


def test_default_quality_requires_positive_freshness_evidence() -> None:
    assert _quality_is_healthy({"data_quality": {}}) is False
    assert (
        _quality_is_healthy({"data_freshness": {"fresh": None}, "data_quality": {}})
        is False
    )


@pytest.mark.parametrize(
    "quality",
    [
        {},
        {"scoring_features": "bad"},
        {"scoring_features": {}},
        {"scoring_features": {"price_history": "bad"}},
    ],
)
def test_default_quality_rejects_empty_or_malformed_evidence(quality: object) -> None:
    assert (
        _quality_is_healthy(
            {"data_freshness": {"fresh": True}, "data_quality": quality}
        )
        is False
    )


def test_failed_cache_refresh_is_degraded() -> None:
    payload = {
        "data_freshness": {"fresh": True},
        "data_quality": {},
        "daily_action_cache_refresh": {"status": "failed"},
    }
    assert _quality_is_healthy(payload) is False


@pytest.mark.parametrize(
    "cache_refresh",
    [
        {"price_failed": 1, "fund_flow_failed": 0, "industry_index_failed": 0},
        {"price_failed": 0, "fund_flow_failed": 1, "industry_index_failed": 0},
        {"price_failed": 0, "fund_flow_failed": 0, "industry_index_failed": 1},
        {"price_failed": 0, "fund_flow_failed": 0},
    ],
)
def test_partial_or_ambiguous_cache_refresh_is_degraded(
    cache_refresh: dict[str, int],
) -> None:
    payload = {
        "data_freshness": {"fresh": True},
        "data_quality": {
            "scoring_features": {
                "price_history": {
                    "coverage": 1.0,
                    "stale": False,
                    "provider_failures": 0,
                }
            }
        },
        "daily_action_cache_refresh": cache_refresh,
    }
    assert _quality_is_healthy(payload) is False


def _strict_healthy_quality_payload() -> dict[str, Any]:
    return {
        "data_freshness": {"fresh": True},
        "data_quality": {
            "scoring_features": {
                "price_history": {
                    "coverage": 1.0,
                    "stale": False,
                    "provider_failures": 0,
                }
            }
        },
        "daily_action_cache_refresh": {
            "status": "success",
            "price_failed": 0,
            "price_missing": 0,
            "price_insufficient_history": 0,
            "fund_flow_failed": 0,
            "fund_flow_empty": 0,
            "industry_index_failed": 0,
        },
    }


@pytest.mark.parametrize("bad_value", [None, True, 0.0, "0"])
def test_quality_requires_provider_failures_present_exact_int_zero(
    bad_value: object,
) -> None:
    payload = _strict_healthy_quality_payload()
    evidence = payload["data_quality"]["scoring_features"]["price_history"]
    if bad_value is None:
        evidence.pop("provider_failures")
    else:
        evidence["provider_failures"] = bad_value

    assert _quality_is_healthy(payload) is False


@pytest.mark.parametrize("bad_status", [None, "ready", "partial", True, 1])
def test_quality_requires_exact_supported_cache_success_status(
    bad_status: object,
) -> None:
    payload = _strict_healthy_quality_payload()
    if bad_status is None:
        payload["daily_action_cache_refresh"].pop("status")
    else:
        payload["daily_action_cache_refresh"]["status"] = bad_status

    assert _quality_is_healthy(payload) is False


@pytest.mark.parametrize(
    "field",
    [
        "price_failed",
        "price_missing",
        "price_insufficient_history",
        "fund_flow_failed",
        "fund_flow_empty",
        "industry_index_failed",
    ],
)
@pytest.mark.parametrize("bad_value", [None, True, 1, "0"])
def test_quality_requires_all_partial_and_missing_counters_exact_zero(
    field: str,
    bad_value: object,
) -> None:
    payload = _strict_healthy_quality_payload()
    if bad_value is None:
        payload["daily_action_cache_refresh"].pop(field)
    else:
        payload["daily_action_cache_refresh"][field] = bad_value

    assert _quality_is_healthy(payload) is False


def test_quality_accepts_complete_explicit_evidence() -> None:
    assert _quality_is_healthy(_strict_healthy_quality_payload()) is True


def test_default_manifest_uses_immutable_run_bound_cache_snapshot(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data"
    reports_dir = data_dir / "reports"
    price_dir = data_dir / "price_cache"
    fund_dir = data_dir / "fund_flow_cache"
    industry_dir = data_dir / "industry_index_cache"
    reports_dir.mkdir(parents=True)
    price_dir.mkdir()
    fund_dir.mkdir()
    industry_dir.mkdir()
    (price_dir / "000001.csv").write_text(
        "date,close,open,high,low,volume\n2026-07-10,10,9,11,8,1000\n",
        encoding="utf-8",
    )
    (price_dir / "000002.csv").write_text(
        "date,close,open,high,low,volume\n2026-07-10,20,19,21,18,2000\n",
        encoding="utf-8",
    )
    fund_rows = "".join(f"2026-06-{day:02d},000001,1\n" for day in range(11, 30))
    (fund_dir / "000001.csv").write_text(
        "date,ticker,main_net_pct\n" + fund_rows + "2026-07-10,000001,1\n",
        encoding="utf-8",
    )
    (fund_dir / "000002.csv").write_text(
        "date,ticker,main_net_pct\n2026-07-10,000002,1\n",
        encoding="utf-8",
    )
    (industry_dir / "_industry_codes.json").write_text(
        '{"801780.SI":"银行","801080.SI":"电子"}', encoding="utf-8"
    )
    (industry_dir / "801780.SI.csv").write_text(
        "ts_code,trade_date,close\n801780.SI,20260710,3800\n",
        encoding="utf-8",
    )
    (industry_dir / "801080.SI.csv").write_text(
        "ts_code,trade_date,close\n801080.SI,20260710,2800\n",
        encoding="utf-8",
    )
    snapshots_dir = data_dir / "snapshots"
    snapshots_dir.mkdir()
    candidates = [
        {"ticker": "000001", "industry": "银行"},
        {"ticker": "000002", "industry": "电子"},
    ]
    (snapshots_dir / "candidate_pool_20260710.json").write_text(
        json.dumps(candidates), encoding="utf-8"
    )
    prepared = _capture_input_snapshot(
        "20260710",
        reports_dir=reports_dir,
        cache_refresh_summary={
            "status": "success",
            "price_failed": 0,
            "price_missing": 0,
            "price_insufficient_history": 0,
            "fund_flow_failed": 0,
            "fund_flow_empty": 0,
            "industry_index_failed": 0,
        },
    )
    inputs = _finalize_inputs_after_compute(
        prepared,
        {
            "candidate_pool_run": {
                "trade_date": "20260710",
                "tickers": ["000001", "000002"],
                "candidates": candidates,
            }
        },
        run_id="run-1",
    )
    payload = {
        "date": "20260710",
        "data_freshness": {"fresh": True},
        "data_quality": {
            "scoring_features": {
                "price_history": {
                    "coverage": 1.0,
                    "stale": False,
                    "provider_failures": 0,
                }
            }
        },
        "daily_action_cache_refresh": dict(inputs.cache_refresh_summary),
        "recommendations": [
            {
                "ticker": "000001",
                "industry_sw": "银行",
                "security_status": "listed",
                "st_status": False,
                "board_rule_version": "ashare-board-prefix-v1",
            }
        ],
    }

    manifest = _build_default_manifest(inputs, payload, run_id="run-1")

    assert manifest.is_healthy is True
    assert manifest.tickers["000001"].trade_ready is True
    assert manifest.tickers["000001"].cache_fingerprint.startswith("sha256:")
    assert manifest.tickers["000002"].trade_ready is False
    assert manifest.candidate_tickers == ("000001", "000002")
    assert manifest.candidate_set_fingerprint == inputs.candidate_set_fingerprint
    assert manifest.candidate_snapshot_fingerprint == inputs.candidate_snapshot_fingerprint
    assert manifest.input_fingerprint.startswith("sha256:")

    with pytest.raises(ValueError, match="manifest run_id does not match"):
        _build_default_manifest(inputs, payload, run_id="different-run")


def test_finalize_inputs_uses_exact_same_run_layer_a_tickers_not_price_cache(
    tmp_path: Path,
) -> None:
    reports_dir = tmp_path / "data" / "reports"
    snapshots_dir = tmp_path / "data" / "snapshots"
    price_dir = tmp_path / "data" / "price_cache"
    reports_dir.mkdir(parents=True)
    snapshots_dir.mkdir()
    price_dir.mkdir()
    (price_dir / "000001.csv").write_text(
        "date,open,high,low,close,volume\n2026-07-10,9,11,8,10,1000\n",
        encoding="utf-8",
    )
    candidates = [
        {"ticker": "000001", "industry": "银行"},
        {"ticker": "300999", "industry": "电子"},
    ]
    (snapshots_dir / "candidate_pool_20260710.json").write_text(
        json.dumps(candidates), encoding="utf-8"
    )
    prepared = _capture_input_snapshot(
        "20260710", reports_dir=reports_dir, cache_refresh_summary={}
    )
    payload = {
        "date": "20260710",
        "candidate_pool_run": {
            "trade_date": "20260710",
            "tickers": ["000001", "300999"],
            "candidates": candidates,
        },
    }

    finalized = _finalize_inputs_after_compute(prepared, payload, run_id="run-1")

    assert set(finalized.tickers) == {"000001", "300999"}
    assert finalized.candidate_tickers == ("000001", "300999")
    assert finalized.run_id == "run-1"
    assert finalized.candidate_set_fingerprint.startswith("sha256:")
    assert finalized.candidate_snapshot_fingerprint.startswith("sha256:")


def test_stale_candidate_snapshot_cannot_substitute_for_current_compute(
    tmp_path: Path,
) -> None:
    reports_dir = tmp_path / "data" / "reports"
    snapshots_dir = tmp_path / "data" / "snapshots"
    reports_dir.mkdir(parents=True)
    snapshots_dir.mkdir()
    (snapshots_dir / "candidate_pool_20260710.json").write_text(
        json.dumps([{"ticker": "000999", "industry": "旧行业"}]),
        encoding="utf-8",
    )
    prepared = _capture_input_snapshot(
        "20260710", reports_dir=reports_dir, cache_refresh_summary={}
    )
    payload = {
        "date": "20260710",
        "candidate_pool_run": {
            "trade_date": "20260710",
            "tickers": ["000001"],
            "candidates": [{"ticker": "000001", "industry": "银行"}],
        },
    }

    with pytest.raises(ValueError, match="candidate snapshot does not match"):
        _finalize_inputs_after_compute(prepared, payload, run_id="run-2")


@pytest.mark.parametrize("cache_existed_before", [True, False])
def test_candidate_cache_must_exist_unchanged_in_precompute_baseline(
    tmp_path: Path,
    cache_existed_before: bool,
) -> None:
    data_dir = tmp_path / "data"
    reports_dir = data_dir / "reports"
    price_dir = data_dir / "price_cache"
    snapshots_dir = data_dir / "snapshots"
    reports_dir.mkdir(parents=True)
    price_dir.mkdir()
    snapshots_dir.mkdir()
    price_path = price_dir / "000001.csv"
    if cache_existed_before:
        price_path.write_text(
            "date,open,high,low,close,volume\n2026-07-10,9,11,8,10,1000\n",
            encoding="utf-8",
        )
    prepared = _capture_input_snapshot(
        "20260710", reports_dir=reports_dir, cache_refresh_summary={}
    )
    price_path.write_text(
        "date,open,high,low,close,volume\n2026-07-10,9,12,8,11,2000\n",
        encoding="utf-8",
    )
    candidates = [{"ticker": "000001", "industry_sw": "银行"}]
    (snapshots_dir / "candidate_pool_20260710.json").write_text(
        json.dumps(candidates), encoding="utf-8"
    )

    finalized = _finalize_inputs_after_compute(
        prepared,
        {
            "candidate_pool_run": {
                "trade_date": "20260710",
                "tickers": ["000001"],
                "candidates": candidates,
            }
        },
        run_id="baseline-run",
    )

    assert finalized.baseline_consistent is False


def test_industry_content_mutation_changes_bound_input_identity(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    reports_dir = data_dir / "reports"
    industry_dir = data_dir / "industry_index_cache"
    snapshots_dir = data_dir / "snapshots"
    reports_dir.mkdir(parents=True)
    industry_dir.mkdir()
    snapshots_dir.mkdir()
    (industry_dir / "_industry_codes.json").write_text(
        '{"801780.SI":"银行"}', encoding="utf-8"
    )
    industry_path = industry_dir / "801780.SI.csv"
    industry_path.write_text(
        "ts_code,trade_date,close\n801780.SI,20260710,3800\n",
        encoding="utf-8",
    )
    prepared = _capture_input_snapshot(
        "20260710", reports_dir=reports_dir, cache_refresh_summary={}
    )
    industry_path.write_text(
        "ts_code,trade_date,close\n801780.SI,20260710,3900\n",
        encoding="utf-8",
    )
    candidates = [{"ticker": "000001", "industry_sw": "银行"}]
    (snapshots_dir / "candidate_pool_20260710.json").write_text(
        json.dumps(candidates), encoding="utf-8"
    )

    finalized = _finalize_inputs_after_compute(
        prepared,
        {
            "candidate_pool_run": {
                "trade_date": "20260710",
                "tickers": ["000001"],
                "candidates": candidates,
            }
        },
        run_id="industry-run",
    )

    assert finalized.baseline_consistent is False
    assert finalized.industry_content_fingerprint.startswith("sha256:")


def test_same_tickers_with_different_admission_metadata_are_rejected(
    tmp_path: Path,
) -> None:
    reports_dir = tmp_path / "data" / "reports"
    snapshots_dir = tmp_path / "data" / "snapshots"
    reports_dir.mkdir(parents=True)
    snapshots_dir.mkdir()
    (snapshots_dir / "candidate_pool_20260710.json").write_text(
        json.dumps(
            [
                {
                    "ticker": "000001",
                    "name": "*ST旧名",
                    "industry_sw": "旧行业",
                    "listing_date": "20200101",
                }
            ]
        ),
        encoding="utf-8",
    )
    prepared = _capture_input_snapshot(
        "20260710", reports_dir=reports_dir, cache_refresh_summary={}
    )

    with pytest.raises(ValueError, match="admission evidence does not match"):
        _finalize_inputs_after_compute(
            prepared,
            {
                "candidate_pool_run": {
                    "trade_date": "20260710",
                    "tickers": ["000001"],
                    "candidates": [
                        {
                            "ticker": "000001",
                            "name": "平安银行",
                            "industry_sw": "银行",
                            "listing_date": "19910403",
                        }
                    ],
                }
            },
            run_id="metadata-run",
        )


def test_pipeline_finalizes_layer_a_inputs_after_compute_writes_snapshot(
    tmp_path: Path,
    fake_auto_dependencies: _FakeAutoDependenciesFactory,
) -> None:
    reports_dir = tmp_path / "data" / "reports"
    snapshots_dir = tmp_path / "data" / "snapshots"
    reports_dir.mkdir(parents=True)
    snapshots_dir.mkdir()
    prepared = _capture_input_snapshot(
        "20260710", reports_dir=reports_dir, cache_refresh_summary={}
    )
    dependencies = fake_auto_dependencies.healthy()

    def compute(_inputs: object, _top_n: int) -> dict[str, Any]:
        candidates = [{"ticker": "300999", "industry": "电子"}]
        (snapshots_dir / "candidate_pool_20260710.json").write_text(
            json.dumps(candidates), encoding="utf-8"
        )
        return {
            "date": "20260710",
            "candidate_pool_run": {
                "trade_date": "20260710",
                "tickers": ["300999"],
                "candidates": candidates,
            },
            "recommendations": [{"ticker": "300999"}],
        }

    def build_manifest(inputs: object, _payload: dict[str, Any]) -> object:
        assert isinstance(inputs, type(prepared))
        assert inputs.candidate_tickers == ("300999",)
        assert inputs.run_id
        return SimpleNamespace(
            run_id=inputs.run_id,
            is_healthy=False,
            tickers={
                "300999": SimpleNamespace(
                    trade_ready=False, cache_fingerprint=None
                )
            },
        )

    dependencies = replace(
        dependencies,
        prepare_inputs=lambda _date: prepared,
        compute_report=compute,
        build_manifest=build_manifest,
    )

    result = run_auto_pipeline(
        "20260710", 10, reports_dir=reports_dir, dependencies=dependencies
    )

    assert result.status is AutoRunStatus.DEGRADED


def test_default_manifest_records_missing_evidence_and_degrades(tmp_path: Path) -> None:
    reports_dir = tmp_path / "data" / "reports"
    reports_dir.mkdir(parents=True)
    inputs = _capture_input_snapshot(
        "20260710",
        reports_dir=reports_dir,
        cache_refresh_summary={
            "price_failed": 0,
            "fund_flow_failed": 0,
            "industry_index_failed": 0,
        },
    )
    payload = {
        "date": "20260710",
        "data_freshness": {"fresh": True},
        "data_quality": {
            "scoring_features": {
                "price_history": {
                    "coverage": 1.0,
                    "stale": False,
                    "provider_failures": 0,
                }
            }
        },
        "daily_action_cache_refresh": dict(inputs.cache_refresh_summary),
        "recommendations": [{"ticker": "000001"}],
    }

    manifest = _build_default_manifest(inputs, payload, run_id="run-2")

    assert manifest.is_healthy is False
    assert manifest.tickers["000001"].trade_ready is False
    assert "cache_fingerprint:missing" in manifest.tickers["000001"].block_reasons


def test_default_manifest_covers_exact_layer_a_scan_space(tmp_path: Path) -> None:
    reports_dir = tmp_path / "data" / "reports"
    price_dir = tmp_path / "data" / "price_cache"
    reports_dir.mkdir(parents=True)
    price_dir.mkdir()
    for ticker in ("000001", "000002"):
        (price_dir / f"{ticker}.csv").write_text(
            "date,close,open,high,low,volume\n2026-07-10,10,9,11,8,1000\n",
            encoding="utf-8",
        )
    snapshots_dir = tmp_path / "data" / "snapshots"
    snapshots_dir.mkdir()
    candidates = [{"ticker": ticker} for ticker in ("000001", "000002")]
    (snapshots_dir / "candidate_pool_20260710.json").write_text(
        json.dumps(candidates), encoding="utf-8"
    )
    prepared = _capture_input_snapshot(
        "20260710",
        reports_dir=reports_dir,
        cache_refresh_summary={
            "price_failed": 0,
            "fund_flow_failed": 0,
            "industry_index_failed": 0,
        },
    )
    inputs = _finalize_inputs_after_compute(
        prepared,
        {
            "candidate_pool_run": {
                "trade_date": "20260710",
                "tickers": ["000001", "000002"],
                "candidates": candidates,
            }
        },
        run_id="run-full-scan",
    )
    payload = {
        "date": "20260710",
        "data_freshness": {"fresh": True},
        "data_quality": {
            "scoring_features": {
                "price_history": {
                    "coverage": 1.0,
                    "stale": False,
                    "provider_failures": 0,
                }
            }
        },
        "daily_action_cache_refresh": dict(inputs.cache_refresh_summary),
        "recommendations": [{"ticker": "000001"}],
    }

    manifest = _build_default_manifest(inputs, payload, run_id="run-full-scan")

    assert set(manifest.tickers) == {"000001", "000002"}


def test_cache_mutation_during_compute_forces_manifest_degraded(tmp_path: Path) -> None:
    reports_dir = tmp_path / "data" / "reports"
    price_dir = tmp_path / "data" / "price_cache"
    reports_dir.mkdir(parents=True)
    price_dir.mkdir()
    price_path = price_dir / "000001.csv"
    price_path.write_text(
        "date,close,open,high,low,volume\n2026-07-10,10,9,11,8,1000\n",
        encoding="utf-8",
    )
    summary = {
        "price_failed": 0,
        "fund_flow_failed": 0,
        "industry_index_failed": 0,
    }
    snapshots_dir = tmp_path / "data" / "snapshots"
    snapshots_dir.mkdir()
    candidates = [{"ticker": "000001"}]
    (snapshots_dir / "candidate_pool_20260710.json").write_text(
        json.dumps(candidates), encoding="utf-8"
    )
    prepared = _capture_input_snapshot(
        "20260710", reports_dir=reports_dir, cache_refresh_summary=summary
    )
    inputs = _finalize_inputs_after_compute(
        prepared,
        {
            "candidate_pool_run": {
                "trade_date": "20260710",
                "tickers": ["000001"],
                "candidates": candidates,
            }
        },
        run_id="run-mutated",
    )
    price_path.write_text(
        "date,close,open,high,low,volume\n2026-07-10,99,9,100,8,1000\n",
        encoding="utf-8",
    )
    payload = {
        "date": "20260710",
        "data_freshness": {"fresh": True},
        "data_quality": {
            "scoring_features": {
                "price_history": {
                    "coverage": 1.0,
                    "stale": False,
                    "provider_failures": 0,
                }
            }
        },
        "daily_action_cache_refresh": summary,
        "recommendations": [{"ticker": "000001"}],
    }

    manifest = _build_default_manifest(inputs, payload, run_id="run-mutated")

    assert _input_snapshot_is_current(inputs) is False
    assert manifest.is_healthy is False


def test_candidate_snapshot_mutation_after_finalize_is_detected(tmp_path: Path) -> None:
    reports_dir = tmp_path / "data" / "reports"
    snapshots_dir = tmp_path / "data" / "snapshots"
    reports_dir.mkdir(parents=True)
    snapshots_dir.mkdir()
    snapshot_path = snapshots_dir / "candidate_pool_20260710.json"
    candidates = [{"ticker": "000001", "industry": "银行"}]
    snapshot_path.write_text(json.dumps(candidates), encoding="utf-8")
    prepared = _capture_input_snapshot(
        "20260710", reports_dir=reports_dir, cache_refresh_summary={}
    )
    inputs = _finalize_inputs_after_compute(
        prepared,
        {
            "candidate_pool_run": {
                "trade_date": "20260710",
                "tickers": ["000001"],
                "candidates": candidates,
            }
        },
        run_id="run-drift",
    )
    snapshot_path.write_text(
        json.dumps([{"ticker": "000002", "industry": "电子"}]),
        encoding="utf-8",
    )

    assert _input_snapshot_is_current(inputs) is False


def test_future_cache_rows_do_not_change_past_snapshot_fingerprint(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data"
    reports_dir = data_dir / "reports"
    price_dir = data_dir / "price_cache"
    fund_dir = data_dir / "fund_flow_cache"
    reports_dir.mkdir(parents=True)
    price_dir.mkdir()
    fund_dir.mkdir()
    price_path = price_dir / "000001.csv"
    fund_path = fund_dir / "000001.csv"
    price_path.write_text(
        "date,close,open,high,low,volume\n2026-07-10,10,9,11,8,1000\n",
        encoding="utf-8",
    )
    fund_path.write_text(
        "date,ticker,main_net_pct\n2026-07-10,000001,1\n",
        encoding="utf-8",
    )
    summary = {
        "price_failed": 0,
        "fund_flow_failed": 0,
        "industry_index_failed": 0,
    }
    before = _capture_input_snapshot(
        "20260710",
        reports_dir=reports_dir,
        cache_refresh_summary=summary,
        candidate_tickers=("000001",),
    )
    price_path.write_text(
        price_path.read_text(encoding="utf-8") + "2026-07-11,20,19,21,18,2000\n",
        encoding="utf-8",
    )
    fund_path.write_text(
        fund_path.read_text(encoding="utf-8") + "2026-07-11,000001,2\n",
        encoding="utf-8",
    )
    after = _capture_input_snapshot(
        "20260710",
        reports_dir=reports_dir,
        cache_refresh_summary=summary,
        candidate_tickers=("000001",),
    )

    assert (
        before.tickers["000001"].price_fingerprint
        == after.tickers["000001"].price_fingerprint
    )
    assert (
        before.tickers["000001"].fund_flow_fingerprint
        == after.tickers["000001"].fund_flow_fingerprint
    )


def test_candidate_admission_evidence_must_match_trade_date(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    reports_dir = data_dir / "reports"
    price_dir = data_dir / "price_cache"
    snapshots_dir = data_dir / "snapshots"
    reports_dir.mkdir(parents=True)
    price_dir.mkdir()
    snapshots_dir.mkdir()
    (price_dir / "000001.csv").write_text(
        "date,close,open,high,low,volume\n2026-07-10,10,9,11,8,1000\n",
        encoding="utf-8",
    )
    for snapshot_date, industry in (("20260709", "旧行业"), ("20260711", "未来行业")):
        (snapshots_dir / f"candidate_pool_{snapshot_date}.json").write_text(
            json.dumps([{"ticker": "000001", "industry": industry}]),
            encoding="utf-8",
        )

    prepared = _capture_input_snapshot(
        "20260710",
        reports_dir=reports_dir,
        cache_refresh_summary={
            "price_failed": 0,
            "fund_flow_failed": 0,
            "industry_index_failed": 0,
        },
    )
    with pytest.raises(ValueError, match="candidate snapshot is missing"):
        _finalize_inputs_after_compute(
            prepared,
            {
                "candidate_pool_run": {
                    "trade_date": "20260710",
                    "tickers": ["000001"],
                    "candidates": [{"ticker": "000001", "industry": "银行"}],
                }
            },
            run_id="run-admission",
        )


def test_candidate_admission_evidence_accepts_exact_trade_date(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    reports_dir = data_dir / "reports"
    price_dir = data_dir / "price_cache"
    snapshots_dir = data_dir / "snapshots"
    reports_dir.mkdir(parents=True)
    price_dir.mkdir()
    snapshots_dir.mkdir()
    (price_dir / "000001.csv").write_text(
        "date,close,open,high,low,volume\n2026-07-10,10,9,11,8,1000\n",
        encoding="utf-8",
    )
    (snapshots_dir / "candidate_pool_20260710.json").write_text(
        json.dumps([{"ticker": "000001", "industry": "银行"}]),
        encoding="utf-8",
    )

    prepared = _capture_input_snapshot(
        "20260710",
        reports_dir=reports_dir,
        cache_refresh_summary={
            "price_failed": 0,
            "fund_flow_failed": 0,
            "industry_index_failed": 0,
        },
    )
    inputs = _finalize_inputs_after_compute(
        prepared,
        {
            "candidate_pool_run": {
                "trade_date": "20260710",
                "tickers": ["000001"],
                "candidates": [{"ticker": "000001", "industry": "银行"}],
            }
        },
        run_id="run-admission",
    )

    assert dict(inputs.ticker_industries) == {"000001": "银行"}


def test_healthy_run_publishes_one_canonical(
    tmp_path: Path,
    fake_auto_dependencies: _FakeAutoDependenciesFactory,
) -> None:
    result = run_auto_pipeline(
        "20260710",
        10,
        reports_dir=tmp_path,
        dependencies=fake_auto_dependencies.healthy(),
    )
    assert result.status is AutoRunStatus.HEALTHY
    assert result.exit_code == 0
    assert len(list(tmp_path.glob("auto_screening_20260710.json"))) == 1
    assert list(tmp_path.glob("auto_attempt_20260710_*.json")) == []
    assert fake_auto_dependencies.events == [
        ("prepare", "20260710"),
        ("compute", 10),
        ("manifest", result.payload),
        ("tracking", result.payload),
        ("canonical", result.payload),
    ]


def test_tracking_receives_exact_published_payload_object(
    tmp_path: Path,
    fake_auto_dependencies: _FakeAutoDependenciesFactory,
) -> None:
    result = run_auto_pipeline(
        "20260710",
        10,
        reports_dir=tmp_path,
        dependencies=fake_auto_dependencies.healthy(),
    )
    canonical_payload = next(
        value for event, value in fake_auto_dependencies.events if event == "canonical"
    )
    tracking_payload = next(
        value for event, value in fake_auto_dependencies.events if event == "tracking"
    )
    assert canonical_payload is result.payload
    assert tracking_payload is result.payload


def test_tracking_receives_same_json_normalization_as_canonical(
    tmp_path: Path,
    fake_auto_dependencies: _FakeAutoDependenciesFactory,
) -> None:
    dependencies = fake_auto_dependencies.healthy()
    payload = {
        "date": "20260710",
        "mode": "auto_screening",
        "recommendations": [{"ticker": "000001", "score_b": math.nan}],
    }
    dependencies = replace(dependencies, compute_report=lambda _inputs, _top_n: payload)

    result = run_auto_pipeline(
        "20260710",
        10,
        reports_dir=tmp_path,
        dependencies=dependencies,
    )

    tracking_payload = next(
        value for event, value in fake_auto_dependencies.events if event == "tracking"
    )
    disk_payload = json.loads(
        (tmp_path / "auto_screening_20260710.json").read_text(encoding="utf-8")
    )
    assert result.payload is tracking_payload
    assert tracking_payload["recommendations"][0]["score_b"] is None
    assert disk_payload["recommendations"] == tracking_payload["recommendations"]


def test_degraded_attempt_does_not_overwrite_healthy_canonical(
    tmp_path: Path,
    fake_auto_dependencies: _FakeAutoDependenciesFactory,
) -> None:
    canonical = tmp_path / "auto_screening_20260710.json"
    canonical.write_text('{"status":"healthy","run_id":"old"}', encoding="utf-8")
    result = run_auto_pipeline(
        "20260710",
        10,
        reports_dir=tmp_path,
        dependencies=fake_auto_dependencies.degraded(),
    )
    assert result.status is AutoRunStatus.DEGRADED
    assert result.exit_code == 0
    assert json.loads(canonical.read_text(encoding="utf-8"))["run_id"] == "old"
    assert len(list(tmp_path.glob("auto_attempt_20260710_*.json"))) == 1
    assert not any(event == "tracking" for event, _ in fake_auto_dependencies.events)


def test_claimed_healthy_manifest_without_ticker_evidence_fails_closed(
    tmp_path: Path,
    fake_auto_dependencies: _FakeAutoDependenciesFactory,
) -> None:
    dependencies = replace(
        fake_auto_dependencies.healthy(),
        build_manifest=lambda _inputs, _payload: SimpleNamespace(
            run_id="empty-run",
            is_healthy=True,
            tickers={},
        ),
    )

    result = run_auto_pipeline(
        "20260710",
        10,
        reports_dir=tmp_path,
        dependencies=dependencies,
    )

    assert result.status is AutoRunStatus.DEGRADED


def test_truthy_non_bool_manifest_health_fails_closed(
    tmp_path: Path,
    fake_auto_dependencies: _FakeAutoDependenciesFactory,
) -> None:
    dependencies = fake_auto_dependencies.healthy()
    dependencies = replace(
        dependencies,
        build_manifest=lambda _inputs, _payload: SimpleNamespace(
            run_id="truthy-run",
            is_healthy="yes",
            tickers={
                "000001": SimpleNamespace(
                    trade_ready=True, cache_fingerprint="sha256:test"
                )
            },
        ),
    )

    result = run_auto_pipeline(
        "20260710", 10, reports_dir=tmp_path, dependencies=dependencies
    )

    assert result.status is AutoRunStatus.DEGRADED
    assert not (tmp_path / "auto_screening_20260710.json").exists()


def test_strict_quality_maps_degraded_to_nonzero(
    tmp_path: Path,
    fake_auto_dependencies: _FakeAutoDependenciesFactory,
) -> None:
    result = run_auto_pipeline(
        "20260710",
        10,
        reports_dir=tmp_path,
        dependencies=fake_auto_dependencies.degraded(),
        strict_quality=True,
    )
    assert result.exit_code == 3


def test_fatal_attempt_is_auditable_without_replacing_canonical(
    tmp_path: Path,
    fake_auto_dependencies: _FakeAutoDependenciesFactory,
) -> None:
    canonical = tmp_path / "auto_screening_20260710.json"
    canonical.write_text('{"status":"healthy","run_id":"old"}', encoding="utf-8")

    result = run_auto_pipeline(
        "20260710",
        10,
        reports_dir=tmp_path,
        dependencies=fake_auto_dependencies.fatal("disk offline"),
    )

    assert result.status is AutoRunStatus.FATAL
    assert result.exit_code == 1
    assert json.loads(canonical.read_text(encoding="utf-8"))["run_id"] == "old"
    attempts = list(tmp_path.glob("auto_attempt_20260710_*.json"))
    assert len(attempts) == 1
    attempt = json.loads(attempts[0].read_text(encoding="utf-8"))
    assert attempt["status"] == "fatal"
    assert attempt["error"]["type"] == "RuntimeError"
    assert attempt["error"]["message"] == "disk offline"


def test_fatal_attempt_names_are_unique_for_same_trade_date(
    tmp_path: Path,
    fake_auto_dependencies: _FakeAutoDependenciesFactory,
) -> None:
    first = run_auto_pipeline(
        "20260710",
        10,
        reports_dir=tmp_path,
        dependencies=fake_auto_dependencies.fatal("first"),
    )
    second = run_auto_pipeline(
        "20260710",
        10,
        reports_dir=tmp_path,
        dependencies=fake_auto_dependencies.fatal("second"),
    )
    assert first.artifact_path != second.artifact_path
    assert len(list(tmp_path.glob("auto_attempt_20260710_*.json"))) == 2


def test_payload_date_mismatch_is_fatal_and_cannot_publish_other_date(
    tmp_path: Path,
    fake_auto_dependencies: _FakeAutoDependenciesFactory,
) -> None:
    dependencies = fake_auto_dependencies.healthy()
    dependencies = replace(
        dependencies,
        compute_report=lambda _inputs, _top_n: {
            "date": "20260711",
            "recommendations": [],
        },
    )

    result = run_auto_pipeline(
        "20260710",
        10,
        reports_dir=tmp_path,
        dependencies=dependencies,
    )

    assert result.status is AutoRunStatus.FATAL
    assert not (tmp_path / "auto_screening_20260710.json").exists()
    assert not (tmp_path / "auto_screening_20260711.json").exists()
    attempt = json.loads(result.artifact_path.read_text(encoding="utf-8"))
    assert attempt["stage"] == "validate_payload"


def test_tracking_failure_preserves_old_canonical_and_records_fatal_attempt(
    tmp_path: Path,
    fake_auto_dependencies: _FakeAutoDependenciesFactory,
) -> None:
    dependencies = replace(
        fake_auto_dependencies.healthy(),
        update_tracking=lambda _payload: (_ for _ in ()).throw(
            RuntimeError("tracking failed")
        ),
    )
    old_canonical = tmp_path / "auto_screening_20260710.json"
    old_canonical.write_text('{"status":"healthy","run_id":"old"}', encoding="utf-8")

    result = run_auto_pipeline(
        "20260710",
        10,
        reports_dir=tmp_path,
        dependencies=dependencies,
    )

    assert result.status is AutoRunStatus.FATAL
    assert result.exit_code == 1
    canonical = json.loads(old_canonical.read_text(encoding="utf-8"))
    assert canonical["run_id"] == "old"
    attempt = json.loads(result.artifact_path.read_text(encoding="utf-8"))
    assert attempt["run_id"] == "healthy-run"
    assert attempt["phase"] == "prepared"
    assert attempt["status"] == "pending"
    assert attempt["last_error"]["stage"] == "advance_pending"
    assert attempt["last_error"]["message"] == "tracking failed"


def test_canonical_publication_failure_preserves_old_canonical_and_is_auditable(
    tmp_path: Path,
    fake_auto_dependencies: _FakeAutoDependenciesFactory,
) -> None:
    old_canonical = tmp_path / "auto_screening_20260710.json"
    old_canonical.write_text('{"status":"healthy","run_id":"old"}', encoding="utf-8")
    dependencies = replace(
        fake_auto_dependencies.healthy(),
        publish_canonical=lambda _payload, _manifest: (_ for _ in ()).throw(
            OSError("replace failed")
        ),
    )

    result = run_auto_pipeline(
        "20260710",
        10,
        reports_dir=tmp_path,
        dependencies=dependencies,
    )

    assert result.status is AutoRunStatus.FATAL
    assert json.loads(old_canonical.read_text(encoding="utf-8"))["run_id"] == "old"
    attempt = json.loads(result.artifact_path.read_text(encoding="utf-8"))
    assert attempt["phase"] == "tracked"
    assert attempt["status"] == "pending"
    assert attempt["last_error"]["stage"] == "advance_pending"
    assert attempt["last_error"]["message"] == "replace failed"


def test_tracking_is_preceded_by_crash_durable_pending_attempt(
    tmp_path: Path,
    fake_auto_dependencies: _FakeAutoDependenciesFactory,
) -> None:
    dependencies = fake_auto_dependencies.healthy()

    def assert_pending_before_tracking(payload: dict[str, Any]) -> int:
        attempts = list((tmp_path / ".auto_pending" / "20260710").glob("*.json"))
        assert len(attempts) == 1
        pending = json.loads(attempts[0].read_text(encoding="utf-8"))
        assert pending["status"] == "pending"
        assert pending["phase"] == "prepared"
        assert pending["payload"] == payload
        return 1

    dependencies = replace(dependencies, update_tracking=assert_pending_before_tracking)

    result = run_auto_pipeline(
        "20260710",
        10,
        reports_dir=tmp_path,
        dependencies=dependencies,
    )

    assert result.status is AutoRunStatus.HEALTHY
    assert list((tmp_path / ".auto_pending").rglob("*.json")) == []


@pytest.mark.parametrize(
    ("crash_boundary", "durable_phase"),
    [
        ("after_prepared_persist", "prepared"),
        ("after_tracking", "prepared"),
        ("after_tracked_persist", "tracked"),
        ("after_canonical", "tracked"),
        ("after_canonical_persist", "canonical"),
        ("before_pending_remove", "canonical"),
    ],
)
def test_restart_resumes_exact_pending_run_at_every_durable_boundary(
    tmp_path: Path,
    fake_auto_dependencies: _FakeAutoDependenciesFactory,
    crash_boundary: str,
    durable_phase: str,
) -> None:
    from src.screening.recommendation_tracker import (
        update_tracking_history_from_payload,
    )

    def durable_tracking(payload: dict[str, Any]) -> int:
        return update_tracking_history_from_payload(
            tmp_path,
            "20260710",
            payload,
            use_data_fetcher=lambda *args: [],
        )

    def crash_hook(boundary: str, _path: Path, _state: dict[str, Any]) -> None:
        if boundary == crash_boundary:
            raise _InjectedCrash(boundary)

    dependencies = replace(
        fake_auto_dependencies.healthy(),
        update_tracking=durable_tracking,
        state_hook=crash_hook,
    )

    with pytest.raises(_InjectedCrash, match=crash_boundary):
        run_auto_pipeline(
            "20260710", 10, reports_dir=tmp_path, dependencies=dependencies
        )

    pending_paths = list(
        (tmp_path / ".auto_pending" / "20260710").glob("*.json")
    )
    assert len(pending_paths) == 1
    pending = json.loads(pending_paths[0].read_text(encoding="utf-8"))
    assert pending["schema_version"] == 1
    assert pending["phase"] == durable_phase
    assert pending["payload_checksum"].startswith("sha256:")
    assert pending["manifest_fingerprint"].startswith("sha256:")
    assert pending["input_fingerprint"].startswith("sha256:")
    assert pending["state_checksum"].startswith("sha256:")

    def no_new_run(_trade_date: str) -> object:
        raise AssertionError("recovery must finish the existing run before new compute")

    restart_dependencies = replace(
        fake_auto_dependencies.healthy(),
        prepare_inputs=no_new_run,
        state_hook=None,
    )
    recovered = run_auto_pipeline(
        "20260710", 10, reports_dir=tmp_path, dependencies=restart_dependencies
    )

    assert recovered.status is AutoRunStatus.HEALTHY
    assert recovered.recovered is True
    assert recovered.payload["run_id"] == "healthy-run"
    assert recovered.recovery_diagnostics
    assert list((tmp_path / ".auto_pending").rglob("*.json")) == []
    canonical = json.loads(
        (tmp_path / "auto_screening_20260710.json").read_text(encoding="utf-8")
    )
    assert canonical == recovered.payload
    records = json.loads(
        (tmp_path / "tracking_history.json").read_text(encoding="utf-8")
    )["records"]
    assert [(row["ticker"], row["recommendation_score"]) for row in records] == [
        ("000001", 0.5)
    ]
    assert records[0]["source_run_id"] == "healthy-run"


def test_pending_cleanup_failure_is_durable_and_surfaces_diagnostic(
    tmp_path: Path,
    fake_auto_dependencies: _FakeAutoDependenciesFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "src.screening.auto_pipeline._remove_pending_attempt", lambda _path: False
    )

    result = run_auto_pipeline(
        "20260710",
        10,
        reports_dir=tmp_path,
        dependencies=fake_auto_dependencies.healthy(),
    )

    assert result.status is AutoRunStatus.HEALTHY
    assert result.diagnostic_path is not None
    pending = json.loads(result.diagnostic_path.read_text(encoding="utf-8"))
    assert pending["phase"] == "canonical"
    assert result.recovery_diagnostics == (
        {
            "action": "pending_cleanup_failed",
            "run_id": "healthy-run",
            "pending_path": str(result.diagnostic_path),
        },
    )


def _crash_prepared_pending(
    reports_dir: Path,
    dependencies: AutoPipelineDependencies,
    *,
    trade_date: str,
    run_id: str,
) -> Path:
    payload = {
        "date": trade_date,
        "mode": "auto_screening",
        "recommendations": [{"ticker": "000001", "score_b": 0.5}],
    }
    manifest = SimpleNamespace(
        run_id=run_id,
        is_healthy=True,
        tickers={
            "000001": SimpleNamespace(
                trade_ready=True, cache_fingerprint="sha256:test"
            )
        },
    )

    def crash(boundary: str, _path: Path, _state: dict[str, Any]) -> None:
        if boundary == "after_prepared_persist":
            raise _InjectedCrash(boundary)

    dependencies = replace(
        dependencies,
        compute_report=lambda _inputs, _top_n: payload,
        build_manifest=lambda _inputs, _payload: manifest,
        state_hook=crash,
    )
    with pytest.raises(_InjectedCrash):
        run_auto_pipeline(
            trade_date, 10, reports_dir=reports_dir, dependencies=dependencies
        )
    pending = list((reports_dir / ".auto_pending").rglob("*.json"))
    assert len(pending) == 1
    return pending[0]


def test_next_date_invocation_recovers_prior_date_before_new_compute(
    tmp_path: Path,
    fake_auto_dependencies: _FakeAutoDependenciesFactory,
) -> None:
    _crash_prepared_pending(
        tmp_path,
        fake_auto_dependencies.healthy(),
        trade_date="20260709",
        run_id="prior-run",
    )

    recovered = run_auto_pipeline(
        "20260710",
        10,
        reports_dir=tmp_path,
        dependencies=replace(
            fake_auto_dependencies.healthy(),
            prepare_inputs=lambda _date: (_ for _ in ()).throw(
                AssertionError("new date must not compute before prior recovery")
            ),
        ),
    )

    assert recovered.recovered is True
    assert recovered.effective_trade_date == "20260709"
    assert recovered.payload["date"] == "20260709"
    assert recovered.payload["run_id"] == "prior-run"
    assert (tmp_path / "auto_screening_20260709.json").exists()
    assert not (tmp_path / "auto_screening_20260710.json").exists()
    assert recovered.recovery_diagnostics[0]["requested_trade_date"] == "20260710"
    assert recovered.recovery_diagnostics[0]["effective_trade_date"] == "20260709"
    assert recovered.recovery_diagnostics[0]["requested_date_executed"] is False


@pytest.mark.parametrize(
    "bad_content",
    [
        "{not-json",
        json.dumps({"schema_version": 1, "status": "fatal"}),
    ],
)
def test_any_corrupt_or_disguised_file_in_pending_namespace_fails_closed(
    tmp_path: Path,
    fake_auto_dependencies: _FakeAutoDependenciesFactory,
    bad_content: str,
) -> None:
    pending_dir = tmp_path / ".auto_pending" / "20260709"
    pending_dir.mkdir(parents=True)
    (pending_dir / "bad-run.json").write_text(bad_content, encoding="utf-8")

    result = run_auto_pipeline(
        "20260710",
        10,
        reports_dir=tmp_path,
        dependencies=replace(
            fake_auto_dependencies.healthy(),
            prepare_inputs=lambda _date: (_ for _ in ()).throw(
                AssertionError("corrupt pending namespace must block new compute")
            ),
        ),
    )

    assert result.status is AutoRunStatus.FATAL
    assert result.recovered is True
    assert result.recovery_diagnostics[0]["action"] == "recovery_failed"


@pytest.mark.parametrize("bad_schema", [True, 1.0])
def test_pending_schema_version_must_be_plain_int(
    tmp_path: Path,
    fake_auto_dependencies: _FakeAutoDependenciesFactory,
    bad_schema: object,
) -> None:
    pending_path = _crash_prepared_pending(
        tmp_path,
        fake_auto_dependencies.healthy(),
        trade_date="20260709",
        run_id="schema-run",
    )
    state = json.loads(pending_path.read_text(encoding="utf-8"))
    state["schema_version"] = bad_schema
    pending_path.write_text(json.dumps(state), encoding="utf-8")

    result = run_auto_pipeline("20260710", 10, reports_dir=tmp_path)

    assert result.status is AutoRunStatus.FATAL
    assert "schema" in result.recovery_diagnostics[0]["error"]


def test_renamed_pending_file_identity_mismatch_fails_closed(
    tmp_path: Path,
    fake_auto_dependencies: _FakeAutoDependenciesFactory,
) -> None:
    pending_path = _crash_prepared_pending(
        tmp_path,
        fake_auto_dependencies.healthy(),
        trade_date="20260709",
        run_id="original-run",
    )
    renamed = pending_path.with_name("renamed-run.json")
    pending_path.rename(renamed)

    result = run_auto_pipeline("20260710", 10, reports_dir=tmp_path)

    assert result.status is AutoRunStatus.FATAL
    assert "filename" in result.recovery_diagnostics[0]["error"]


def test_pending_date_must_be_exact_string_even_with_valid_checksums(
    tmp_path: Path,
    fake_auto_dependencies: _FakeAutoDependenciesFactory,
) -> None:
    pending_path = _crash_prepared_pending(
        tmp_path,
        fake_auto_dependencies.healthy(),
        trade_date="20260709",
        run_id="date-run",
    )
    state = json.loads(pending_path.read_text(encoding="utf-8"))
    state["date"] = 20260709
    state["state_checksum"] = _pending_state_checksum(state)
    pending_path.write_text(json.dumps(state), encoding="utf-8")

    result = run_auto_pipeline("20260710", 10, reports_dir=tmp_path)

    assert result.status is AutoRunStatus.FATAL
    assert "trade_date" in result.recovery_diagnostics[0]["error"]


def test_pending_manifest_run_id_must_match_filename_identity(
    tmp_path: Path,
    fake_auto_dependencies: _FakeAutoDependenciesFactory,
) -> None:
    pending_path = _crash_prepared_pending(
        tmp_path,
        fake_auto_dependencies.healthy(),
        trade_date="20260709",
        run_id="bound-run",
    )
    state = json.loads(pending_path.read_text(encoding="utf-8"))
    state["payload"]["manifest"]["run_id"] = "other-run"
    state["payload_checksum"] = _canonical_fingerprint(state["payload"])
    state["manifest_fingerprint"] = _canonical_fingerprint(
        state["payload"]["manifest"]
    )
    state["input_fingerprint"] = state["manifest_fingerprint"]
    state["state_checksum"] = _pending_state_checksum(state)
    pending_path.write_text(json.dumps(state), encoding="utf-8")

    result = run_auto_pipeline("20260710", 10, reports_dir=tmp_path)

    assert result.status is AutoRunStatus.FATAL
    assert "manifest run_id" in result.recovery_diagnostics[0]["error"]


def test_unsafe_dependency_run_id_cannot_escape_attempt_or_pending_paths(
    tmp_path: Path,
    fake_auto_dependencies: _FakeAutoDependenciesFactory,
) -> None:
    unsafe_manifest = SimpleNamespace(
        run_id="../../escape",
        is_healthy=False,
        tickers={},
    )
    dependencies = replace(
        fake_auto_dependencies.degraded(),
        build_manifest=lambda _inputs, _payload: unsafe_manifest,
    )

    result = run_auto_pipeline(
        "20260710", 10, reports_dir=tmp_path, dependencies=dependencies
    )

    assert result.status is AutoRunStatus.FATAL
    assert result.artifact_path is not None
    assert result.artifact_path.parent == tmp_path
    assert not (tmp_path.parent / "escape.json").exists()
    assert not (tmp_path / ".auto_pending").exists()


def test_multiple_cross_date_pending_states_fail_closed(
    tmp_path: Path,
    fake_auto_dependencies: _FakeAutoDependenciesFactory,
) -> None:
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    first_root.mkdir()
    second_root.mkdir()
    _crash_prepared_pending(
        first_root,
        fake_auto_dependencies.healthy(),
        trade_date="20260708",
        run_id="first-run",
    )
    _crash_prepared_pending(
        second_root,
        fake_auto_dependencies.healthy(),
        trade_date="20260709",
        run_id="second-run",
    )
    shutil.copytree(first_root / ".auto_pending", tmp_path / ".auto_pending")
    shutil.copytree(
        second_root / ".auto_pending",
        tmp_path / ".auto_pending",
        dirs_exist_ok=True,
    )

    result = run_auto_pipeline("20260710", 10, reports_dir=tmp_path)

    assert result.status is AutoRunStatus.FATAL
    assert "multiple pending" in result.recovery_diagnostics[0]["error"]


@pytest.mark.parametrize(
    ("mutate", "expected_error"),
    [
        (lambda state: state["payload"].update(status="degraded"), "payload status"),
        (lambda state: state["payload"].update(mode="daily_action"), "payload mode"),
        (
            lambda state: state["payload"]["manifest"].update(status="degraded"),
            "manifest status",
        ),
        (
            lambda state: state["payload"]["manifest"].update(is_healthy=1),
            "manifest health",
        ),
        (
            lambda state: state["payload"]["manifest"].update(is_healthy=False),
            "manifest health",
        ),
    ],
)
def test_recomputed_checksums_cannot_bless_noncanonical_pending_semantics(
    tmp_path: Path,
    fake_auto_dependencies: _FakeAutoDependenciesFactory,
    mutate: Any,
    expected_error: str,
) -> None:
    pending_path = _crash_prepared_pending(
        tmp_path,
        fake_auto_dependencies.healthy(),
        trade_date="20260709",
        run_id="semantic-run",
    )
    state = json.loads(pending_path.read_text(encoding="utf-8"))
    mutate(state)
    state["payload_checksum"] = _canonical_fingerprint(state["payload"])
    state["manifest_fingerprint"] = _canonical_fingerprint(
        state["payload"]["manifest"]
    )
    state["input_fingerprint"] = state["manifest_fingerprint"]
    state["state_checksum"] = _pending_state_checksum(state)
    pending_path.write_text(json.dumps(state), encoding="utf-8")

    result = run_auto_pipeline("20260710", 10, reports_dir=tmp_path)

    assert result.status is AutoRunStatus.FATAL
    assert expected_error in result.recovery_diagnostics[0]["error"]


@pytest.mark.parametrize(
    "ticker",
    ["１２３４５６", "0000017", "000/01", "../001", 1],
)
def test_candidate_evidence_ticker_must_be_exact_six_ascii_digits(
    ticker: object,
) -> None:
    with pytest.raises(ValueError, match="six ASCII digits"):
        _candidate_records([{"ticker": ticker}])


@pytest.mark.parametrize("root_kind", ["file", "symlink"])
def test_pending_root_must_be_real_directory_before_discovery(
    tmp_path: Path,
    fake_auto_dependencies: _FakeAutoDependenciesFactory,
    root_kind: str,
) -> None:
    pending_root = tmp_path / ".auto_pending"
    if root_kind == "file":
        pending_root.write_text("not a directory", encoding="utf-8")
    else:
        target = tmp_path / "outside"
        target.mkdir()
        pending_root.symlink_to(target, target_is_directory=True)

    result = run_auto_pipeline(
        "20260710",
        10,
        reports_dir=tmp_path,
        dependencies=replace(
            fake_auto_dependencies.healthy(),
            prepare_inputs=lambda _date: (_ for _ in ()).throw(
                AssertionError("unsafe pending root must block new compute")
            ),
        ),
    )

    assert result.status is AutoRunStatus.FATAL
    assert "pending root" in result.recovery_diagnostics[0]["error"]


def _replace_pending_root_after_descriptor_open(
    monkeypatch: pytest.MonkeyPatch,
    reports_dir: Path,
) -> tuple[Path, Path]:
    from src.screening import auto_pipeline as pipeline_mod

    held_root = reports_dir / ".auto_pending.held"
    attacker_root = reports_dir / "attacker"
    attacker_root.mkdir()
    (attacker_root / "marker.txt").write_text("untouched", encoding="utf-8")
    real_open = pipeline_mod.os.open
    replaced = False

    def replacing_open(path, flags, mode=0o777, *, dir_fd=None):
        nonlocal replaced
        fd = real_open(path, flags, mode, dir_fd=dir_fd)
        if path == ".auto_pending" and dir_fd is not None and not replaced:
            replaced = True
            (reports_dir / ".auto_pending").rename(held_root)
            (reports_dir / ".auto_pending").symlink_to(
                attacker_root,
                target_is_directory=True,
            )
        return fd

    monkeypatch.setattr(pipeline_mod.os, "open", replacing_open)
    return held_root, attacker_root


def test_pending_write_stays_on_opened_directory_after_path_replacement(
    tmp_path: Path,
    fake_auto_dependencies: _FakeAutoDependenciesFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    held_root, attacker_root = _replace_pending_root_after_descriptor_open(
        monkeypatch,
        tmp_path,
    )

    result = run_auto_pipeline(
        "20260710",
        10,
        reports_dir=tmp_path,
        dependencies=fake_auto_dependencies.healthy(),
    )

    assert result.status is AutoRunStatus.HEALTHY
    assert (attacker_root / "marker.txt").read_text(encoding="utf-8") == "untouched"
    assert list(attacker_root.rglob("*.json")) == []
    assert held_root.is_dir()
    assert list(held_root.rglob("*.json")) == []


def test_pending_discovery_stays_on_opened_directory_after_path_replacement(
    tmp_path: Path,
    fake_auto_dependencies: _FakeAutoDependenciesFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _crash_prepared_pending(
        tmp_path,
        fake_auto_dependencies.healthy(),
        trade_date="20260709",
        run_id="held-discovery",
    )
    held_root, attacker_root = _replace_pending_root_after_descriptor_open(
        monkeypatch,
        tmp_path,
    )

    recovered = run_auto_pipeline("20260710", 10, reports_dir=tmp_path)

    assert recovered.status is AutoRunStatus.HEALTHY
    assert recovered.effective_trade_date == "20260709"
    assert (tmp_path / "auto_screening_20260709.json").exists()
    assert (attacker_root / "marker.txt").read_text(encoding="utf-8") == "untouched"
    assert list(attacker_root.rglob("*.json")) == []
    assert held_root.is_dir()
    assert list(held_root.rglob("*.json")) == []


def test_pending_phase_replace_preserves_permissions(
    tmp_path: Path,
    fake_auto_dependencies: _FakeAutoDependenciesFactory,
) -> None:
    def permission_hook(boundary: str, path: Path, _state: dict[str, Any]) -> None:
        if boundary == "after_prepared_persist":
            path.chmod(0o640)
        if boundary == "after_tracked_persist":
            raise _InjectedCrash(boundary)

    dependencies = replace(
        fake_auto_dependencies.healthy(),
        state_hook=permission_hook,
    )
    with pytest.raises(_InjectedCrash):
        run_auto_pipeline(
            "20260710",
            10,
            reports_dir=tmp_path,
            dependencies=dependencies,
        )

    pending = next((tmp_path / ".auto_pending").rglob("*.json"))
    assert pending.stat().st_mode & 0o777 == 0o640


def test_pending_replace_error_closes_fds_and_cleans_temp_files(
    tmp_path: Path,
    fake_auto_dependencies: _FakeAutoDependenciesFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.screening import auto_pipeline as pipeline_mod

    opened_fds: list[int] = []
    real_open_handle = pipeline_mod._open_pending_handle
    real_replace = pipeline_mod.os.replace

    def capture_handle(*args, **kwargs):
        handle = real_open_handle(*args, **kwargs)
        opened_fds.extend([handle.reports_fd, handle.root_fd, handle.date_fd])
        return handle

    def fail_pending_replace(src, dst, **kwargs):
        if kwargs.get("src_dir_fd") is not None:
            raise OSError("descriptor replace failed")
        return real_replace(src, dst, **kwargs)

    monkeypatch.setattr(pipeline_mod, "_open_pending_handle", capture_handle)
    monkeypatch.setattr(pipeline_mod.os, "replace", fail_pending_replace)

    result = run_auto_pipeline(
        "20260710",
        10,
        reports_dir=tmp_path,
        dependencies=fake_auto_dependencies.healthy(),
    )

    assert result.status is AutoRunStatus.FATAL
    for fd in opened_fds:
        with pytest.raises(OSError):
            pipeline_mod.os.fstat(fd)
    assert list((tmp_path / ".auto_pending").rglob("*.tmp")) == []


def test_missing_descriptor_primitives_fail_closed_with_explicit_diagnostic(
    tmp_path: Path,
    fake_auto_dependencies: _FakeAutoDependenciesFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.screening import auto_pipeline as pipeline_mod

    monkeypatch.setattr(
        pipeline_mod,
        "_require_pending_fd_primitives",
        lambda: (_ for _ in ()).throw(
            RuntimeError("descriptor-relative pending operations unavailable")
        ),
    )

    result = run_auto_pipeline(
        "20260710",
        10,
        reports_dir=tmp_path,
        dependencies=fake_auto_dependencies.healthy(),
    )

    assert result.status is AutoRunStatus.FATAL
    assert "descriptor-relative" in result.recovery_diagnostics[0]["error"]
