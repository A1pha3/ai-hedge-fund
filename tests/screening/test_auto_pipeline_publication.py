from __future__ import annotations

import json
import math
from dataclasses import dataclass, replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from src.screening.auto_pipeline import (
    AutoPipelineDependencies,
    AutoRunStatus,
    _build_default_manifest,
    _capture_input_snapshot,
    _input_snapshot_is_current,
    _quality_is_healthy,
    run_auto_pipeline,
)
from src.utils.atomic_files import atomic_write_json


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
    (industry_dir / "_industry_codes.json").write_text(
        '{"801780.SI":"银行"}', encoding="utf-8"
    )
    (industry_dir / "801780.SI.csv").write_text(
        "ts_code,trade_date,close\n801780.SI,20260710,3800\n",
        encoding="utf-8",
    )

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


def test_default_manifest_covers_full_price_cache_scan_space(tmp_path: Path) -> None:
    reports_dir = tmp_path / "data" / "reports"
    price_dir = tmp_path / "data" / "price_cache"
    reports_dir.mkdir(parents=True)
    price_dir.mkdir()
    for ticker in ("000001", "000002"):
        (price_dir / f"{ticker}.csv").write_text(
            "date,close,open,high,low,volume\n2026-07-10,10,9,11,8,1000\n",
            encoding="utf-8",
        )
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
    inputs = _capture_input_snapshot(
        "20260710", reports_dir=reports_dir, cache_refresh_summary=summary
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
        "20260710", reports_dir=reports_dir, cache_refresh_summary=summary
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
        "20260710", reports_dir=reports_dir, cache_refresh_summary=summary
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

    inputs = _capture_input_snapshot(
        "20260710",
        reports_dir=reports_dir,
        cache_refresh_summary={
            "price_failed": 0,
            "fund_flow_failed": 0,
            "industry_index_failed": 0,
        },
    )

    assert dict(inputs.ticker_industries) == {}


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

    inputs = _capture_input_snapshot(
        "20260710",
        reports_dir=reports_dir,
        cache_refresh_summary={
            "price_failed": 0,
            "fund_flow_failed": 0,
            "industry_index_failed": 0,
        },
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
    assert not (tmp_path / "auto_screening_20260710.json").exists()
    assert result.artifact_path.name == "auto_attempt_20260710_empty-run.json"


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
    assert attempt["stage"] == "update_tracking"
    assert attempt["status"] == "fatal"


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
    assert attempt["stage"] == "publish_canonical"
    assert attempt["error"]["message"] == "replace failed"


def test_tracking_is_preceded_by_crash_durable_pending_attempt(
    tmp_path: Path,
    fake_auto_dependencies: _FakeAutoDependenciesFactory,
) -> None:
    dependencies = fake_auto_dependencies.healthy()

    def assert_pending_before_tracking(payload: dict[str, Any]) -> int:
        attempts = list(tmp_path.glob("auto_attempt_20260710_*.json"))
        assert len(attempts) == 1
        pending = json.loads(attempts[0].read_text(encoding="utf-8"))
        assert pending["status"] == "pending"
        assert pending["intended_payload"] == payload
        return 1

    dependencies = replace(dependencies, update_tracking=assert_pending_before_tracking)

    result = run_auto_pipeline(
        "20260710",
        10,
        reports_dir=tmp_path,
        dependencies=dependencies,
    )

    assert result.status is AutoRunStatus.HEALTHY
    assert list(tmp_path.glob("auto_attempt_20260710_*.json")) == []
