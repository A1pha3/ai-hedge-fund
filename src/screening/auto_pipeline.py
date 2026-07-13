"""Single-publication orchestration for the ``--auto`` screening run."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Mapping

from src.screening.data_quality_manifest import (
    RunManifest,
    TickerReadiness,
    validate_ticker_readiness,
)
from src.utils.atomic_files import (
    _fsync_directory,
    _sanitize_nonfinite,
    atomic_write_json,
)


class AutoRunStatus(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    FATAL = "fatal"


@dataclass(frozen=True)
class AutoRunResult:
    status: AutoRunStatus
    exit_code: int
    artifact_path: Path | None
    payload: dict[str, Any] | None
    manifest: object | None
    diagnostic_path: Path | None = None


@dataclass(frozen=True)
class AutoPipelineDependencies:
    prepare_inputs: Callable[[str], object]
    compute_report: Callable[[object, int], dict[str, Any]]
    build_manifest: Callable[[object, dict[str, Any]], object]
    publish_canonical: Callable[[dict[str, Any], object], Path]
    publish_attempt: Callable[[dict[str, Any], object], Path]
    update_tracking: Callable[[dict[str, Any]], object]


@dataclass(frozen=True)
class TickerInputSnapshot:
    ohlcv_date: date | None
    ohlcv_finite: bool
    fund_flow_date: date | None
    fund_flow_history_days: int
    price_fingerprint: str | None
    fund_flow_fingerprint: str | None


@dataclass(frozen=True)
class IndustryInputSnapshot:
    industry_date: date | None
    fingerprint: str | None


@dataclass(frozen=True)
class AutoInputs:
    trade_date: str
    prepared_at: datetime
    reports_dir: Path
    tickers: Mapping[str, TickerInputSnapshot]
    industries: Mapping[str, IndustryInputSnapshot]
    ticker_industries: Mapping[str, str]
    cache_refresh_summary: Mapping[str, Any]


def _new_run_id(trade_date: str) -> str:
    """Return a filesystem-safe identity unique to one invocation."""
    return f"{trade_date}-{uuid.uuid4().hex}"


def _parse_evidence_date(value: object) -> date | None:
    text = str(value or "").strip()
    for fmt in ("%Y%m%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _read_csv_snapshot(path: Path) -> tuple[list[dict[str, str]], str | None]:
    try:
        raw = path.read_bytes()
        rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8"))))
    except (OSError, UnicodeDecodeError, csv.Error):
        return [], None
    return rows, f"sha256:{hashlib.sha256(raw).hexdigest()}"


def _fingerprint_rows(rows: list[dict[str, str]]) -> str | None:
    if not rows:
        return None
    canonical_rows = sorted(
        rows,
        key=lambda row: json.dumps(row, ensure_ascii=False, sort_keys=True),
    )
    raw = json.dumps(
        canonical_rows,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(raw).hexdigest()}"


def _capture_input_snapshot(
    trade_date: str,
    *,
    reports_dir: Path,
    cache_refresh_summary: Mapping[str, Any],
) -> AutoInputs:
    """Freeze cache evidence before report computation can observe later writes."""
    target_date = datetime.strptime(trade_date, "%Y%m%d").date()
    data_dir = reports_dir.parent
    price_dir = data_dir / "price_cache"
    fund_dir = data_dir / "fund_flow_cache"
    industry_dir = data_dir / "industry_index_cache"

    ticker_snapshots: dict[str, TickerInputSnapshot] = {}
    ticker_names = {
        path.stem
        for path in price_dir.glob("*.csv")
        if path.stem.isdigit() and len(path.stem) == 6
    }
    for ticker in sorted(ticker_names):
        price_rows, _ = _read_csv_snapshot(price_dir / f"{ticker}.csv")
        fund_rows, _ = _read_csv_snapshot(fund_dir / f"{ticker}.csv")

        pit_price_rows = [
            row
            for row in price_rows
            if (
                parsed := _parse_evidence_date(row.get("date") or row.get("trade_date"))
            )
            is not None
            and parsed <= target_date
        ]
        pit_fund_rows = [
            row
            for row in fund_rows
            if (
                parsed := _parse_evidence_date(row.get("date") or row.get("trade_date"))
            )
            is not None
            and parsed <= target_date
        ]
        price_hash = _fingerprint_rows(pit_price_rows)
        fund_hash = _fingerprint_rows(pit_fund_rows)

        price_row = next(
            (
                row
                for row in reversed(pit_price_rows)
                if _parse_evidence_date(row.get("date") or row.get("trade_date"))
                == target_date
            ),
            None,
        )
        required_ohlcv = ("open", "high", "low", "close", "volume")
        ohlcv_finite = False
        if price_row is not None:
            try:
                ohlcv_finite = all(
                    math.isfinite(float(price_row[field])) for field in required_ohlcv
                )
            except (KeyError, TypeError, ValueError):
                ohlcv_finite = False

        fund_dates = sorted(
            {
                parsed
                for row in pit_fund_rows
                if (
                    parsed := _parse_evidence_date(
                        row.get("date") or row.get("trade_date")
                    )
                )
                is not None
                and parsed <= target_date
            }
        )
        ticker_snapshots[ticker] = TickerInputSnapshot(
            ohlcv_date=target_date if price_row is not None else None,
            ohlcv_finite=ohlcv_finite,
            fund_flow_date=fund_dates[-1] if fund_dates else None,
            fund_flow_history_days=len(fund_dates),
            price_fingerprint=price_hash,
            fund_flow_fingerprint=fund_hash,
        )

    industry_names: dict[str, str] = {}
    try:
        raw_codes = json.loads(
            (industry_dir / "_industry_codes.json").read_text(encoding="utf-8")
        )
        if isinstance(raw_codes, dict):
            industry_names = {
                str(code): str(name)
                for code, name in raw_codes.items()
                if str(code) and str(name)
            }
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        pass

    industry_snapshots: dict[str, IndustryInputSnapshot] = {}
    for code, name in industry_names.items():
        rows, _ = _read_csv_snapshot(industry_dir / f"{code}.csv")
        pit_rows = [
            row
            for row in rows
            if (
                parsed := _parse_evidence_date(row.get("trade_date") or row.get("date"))
            )
            is not None
            and parsed <= target_date
        ]
        fingerprint = _fingerprint_rows(pit_rows)
        dates = {
            parsed
            for row in pit_rows
            if (
                parsed := _parse_evidence_date(row.get("trade_date") or row.get("date"))
            )
            is not None
        }
        industry_snapshots[name] = IndustryInputSnapshot(
            industry_date=max(dates) if dates else None,
            fingerprint=fingerprint,
        )

    ticker_industries: dict[str, str] = {}
    snapshots_dir = data_dir / "snapshots"
    candidate_snapshot = snapshots_dir / f"candidate_pool_{trade_date}.json"
    for path in (candidate_snapshot,) if candidate_snapshot.is_file() else ():
        try:
            snapshot_payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        records: list[Any] = []
        if isinstance(snapshot_payload, list):
            records = snapshot_payload
        elif isinstance(snapshot_payload, dict):
            for key in (
                "recommendations",
                "candidates",
                "candidate_pool",
                "selected_candidates",
                "shadow_candidates",
            ):
                value = snapshot_payload.get(key)
                if isinstance(value, list):
                    records.extend(value)
        for record in records:
            if not isinstance(record, dict):
                continue
            ticker = str(record.get("ticker") or record.get("ts_code") or "")[:6]
            industry = str(
                record.get("industry_sw") or record.get("industry") or ""
            ).strip()
            if ticker in ticker_names and industry and ticker not in ticker_industries:
                ticker_industries[ticker] = industry

    return AutoInputs(
        trade_date=trade_date,
        prepared_at=datetime.now(timezone.utc),
        reports_dir=reports_dir,
        tickers=MappingProxyType(ticker_snapshots),
        industries=MappingProxyType(industry_snapshots),
        ticker_industries=MappingProxyType(ticker_industries),
        cache_refresh_summary=MappingProxyType(dict(cache_refresh_summary)),
    )


def _input_snapshot_is_current(inputs: AutoInputs) -> bool:
    current = _capture_input_snapshot(
        inputs.trade_date,
        reports_dir=inputs.reports_dir,
        cache_refresh_summary=inputs.cache_refresh_summary,
    )
    return (
        inputs.tickers == current.tickers
        and inputs.industries == current.industries
        and inputs.ticker_industries == current.ticker_industries
    )


def _combined_fingerprint(*fingerprints: str | None) -> str | None:
    if any(not value for value in fingerprints):
        return None
    digest = hashlib.sha256(
        "|".join(str(value) for value in fingerprints).encode("utf-8")
    )
    return f"sha256:{digest.hexdigest()}"


def _build_default_manifest(
    inputs: AutoInputs,
    payload: Mapping[str, Any],
    *,
    run_id: str,
) -> RunManifest:
    target_date = datetime.strptime(inputs.trade_date, "%Y%m%d").date()
    readiness_by_ticker: dict[str, TickerReadiness] = {}
    recommendations = payload.get("recommendations")
    recommendation_by_ticker: dict[str, Mapping[str, Any]] = {}
    if isinstance(recommendations, list):
        for recommendation in recommendations:
            if not isinstance(recommendation, Mapping):
                continue
            ticker = str(recommendation.get("ticker", "") or "").strip()
            if ticker and ticker not in recommendation_by_ticker:
                recommendation_by_ticker[ticker] = recommendation

    scan_tickers = sorted(set(inputs.tickers) | set(recommendation_by_ticker))
    for ticker in scan_tickers:
        recommendation = recommendation_by_ticker.get(ticker, {})
        ticker_snapshot = inputs.tickers.get(ticker)
        industry_name = str(
            recommendation.get("industry_sw")
            or recommendation.get("industry")
            or inputs.ticker_industries.get(ticker)
            or ""
        ).strip()
        industry_snapshot = inputs.industries.get(industry_name)
        admitted_by_candidate_snapshot = ticker in inputs.ticker_industries
        readiness_by_ticker[ticker] = validate_ticker_readiness(
            ticker=ticker,
            trade_date=target_date,
            ohlcv_date=ticker_snapshot.ohlcv_date if ticker_snapshot else None,
            ohlcv_finite=ticker_snapshot.ohlcv_finite if ticker_snapshot else False,
            fund_flow_date=ticker_snapshot.fund_flow_date if ticker_snapshot else None,
            fund_flow_history_days=(
                ticker_snapshot.fund_flow_history_days if ticker_snapshot else 0
            ),
            industry_date=(
                industry_snapshot.industry_date if industry_snapshot else None
            ),
            security_status=(
                recommendation.get("security_status")
                or ("listed" if admitted_by_candidate_snapshot else None)
            ),
            st_status=(
                recommendation.get("st_status")
                if "st_status" in recommendation
                else (False if admitted_by_candidate_snapshot else None)
            ),
            board_rule_version=(
                recommendation.get("board_rule_version")
                or (
                    "ashare-board-prefix-v1" if admitted_by_candidate_snapshot else None
                )
            ),
            cache_fingerprint=_combined_fingerprint(
                ticker_snapshot.price_fingerprint if ticker_snapshot else None,
                ticker_snapshot.fund_flow_fingerprint if ticker_snapshot else None,
                industry_snapshot.fingerprint if industry_snapshot else None,
            ),
        )

    required_tickers = set(recommendation_by_ticker)
    is_healthy = (
        _quality_is_healthy(payload)
        and _input_snapshot_is_current(inputs)
        and bool(readiness_by_ticker)
        and bool(required_tickers)
        and required_tickers.issubset(readiness_by_ticker)
        and all(readiness_by_ticker[ticker].trade_ready for ticker in required_tickers)
    )
    return RunManifest(
        run_id=run_id,
        trade_date=target_date,
        status=(
            AutoRunStatus.HEALTHY.value if is_healthy else AutoRunStatus.DEGRADED.value
        ),
        created_at=inputs.prepared_at,
        tickers=readiness_by_ticker,
    )


def _readiness_payload(readiness: TickerReadiness) -> dict[str, Any]:
    return {
        "ticker": readiness.ticker,
        "trade_date": readiness.trade_date.isoformat(),
        "ohlcv_date": readiness.ohlcv_date.isoformat()
        if readiness.ohlcv_date
        else None,
        "ohlcv_finite": readiness.ohlcv_finite,
        "fund_flow_date": readiness.fund_flow_date.isoformat()
        if readiness.fund_flow_date
        else None,
        "fund_flow_history_days": readiness.fund_flow_history_days,
        "industry_date": readiness.industry_date.isoformat()
        if readiness.industry_date
        else None,
        "security_status": readiness.security_status,
        "st_status": readiness.st_status,
        "board_rule_version": readiness.board_rule_version,
        "cache_fingerprint": readiness.cache_fingerprint,
        "trade_ready": readiness.trade_ready,
        "block_reasons": list(readiness.block_reasons),
    }


def _manifest_payload(manifest: object) -> dict[str, Any]:
    if isinstance(manifest, RunManifest):
        return {
            "run_id": manifest.run_id,
            "trade_date": manifest.trade_date.isoformat(),
            "status": manifest.status,
            "created_at": manifest.created_at.isoformat(),
            "tickers": {
                ticker: _readiness_payload(readiness)
                for ticker, readiness in manifest.tickers.items()
            },
        }
    return {
        "run_id": str(getattr(manifest, "run_id")),
        "status": "healthy" if bool(getattr(manifest, "is_healthy")) else "degraded",
    }


def _publication_payload(
    payload: dict[str, Any],
    manifest: object,
    *,
    status: AutoRunStatus,
) -> dict[str, Any]:
    manifest_payload = _manifest_payload(manifest)
    payload["run_id"] = manifest_payload["run_id"]
    payload["status"] = status.value
    payload["manifest"] = manifest_payload
    return payload


def _quality_is_healthy(payload: Mapping[str, Any]) -> bool:
    freshness = payload.get("data_freshness")
    if not isinstance(freshness, Mapping) or freshness.get("fresh") is not True:
        return False

    cache_refresh = payload.get("daily_action_cache_refresh")
    if cache_refresh is not None:
        if (
            not isinstance(cache_refresh, Mapping)
            or cache_refresh.get("status") == "failed"
        ):
            return False
        for field in ("price_failed", "fund_flow_failed", "industry_index_failed"):
            value = cache_refresh.get(field)
            if type(value) is not int or value != 0:
                return False

    quality = payload.get("data_quality")
    if not isinstance(quality, Mapping) or not quality:
        return False
    evidence_count = 0
    for group in quality.values():
        if not isinstance(group, Mapping):
            return False
        for evidence in group.values():
            if not isinstance(evidence, Mapping):
                return False
            evidence_count += 1
            if evidence.get("stale") is not False:
                return False
            provider_failures = evidence.get("provider_failures", 0)
            if (
                type(provider_failures) is not int
                or provider_failures < 0
                or provider_failures > 0
            ):
                return False
            coverage = evidence.get("coverage")
            if (
                not isinstance(coverage, (int, float))
                or isinstance(coverage, bool)
                or coverage != 1.0
            ):
                return False
    return evidence_count > 0


def _manifest_has_auditable_evidence(
    manifest: object,
    payload: Mapping[str, Any],
) -> bool:
    tickers = getattr(manifest, "tickers", None)
    if not isinstance(tickers, Mapping) or not tickers:
        return False
    recommendations = payload.get("recommendations")
    if not isinstance(recommendations, list) or not recommendations:
        return False
    expected = {
        str(item.get("ticker", "") or "").strip()
        for item in recommendations
        if isinstance(item, Mapping)
    }
    expected.discard("")
    return (
        bool(expected)
        and expected.issubset(set(tickers))
        and all(
            getattr(tickers[ticker], "trade_ready", False) is True
            and bool(getattr(tickers[ticker], "cache_fingerprint", None))
            for ticker in expected
        )
    )


def _default_dependencies(reports_dir: Path, run_id: str) -> AutoPipelineDependencies:
    def prepare_inputs(trade_date: str) -> AutoInputs:
        from src import main

        refresh_payload: dict[str, Any] = {}
        main._refresh_daily_action_caches_for_auto(trade_date, refresh_payload)
        return _capture_input_snapshot(
            trade_date,
            reports_dir=reports_dir,
            cache_refresh_summary=refresh_payload.get("daily_action_cache_refresh", {}),
        )

    def compute_report(inputs: object, top_n: int) -> dict[str, Any]:
        from src import main

        assert isinstance(inputs, AutoInputs)
        payload = main.compute_auto_screening_results(inputs.trade_date, top_n)
        if inputs.cache_refresh_summary:
            payload["daily_action_cache_refresh"] = dict(inputs.cache_refresh_summary)
        main._attach_freshness_check(inputs.trade_date, payload)
        return payload

    def build_manifest(inputs: object, payload: dict[str, Any]) -> RunManifest:
        assert isinstance(inputs, AutoInputs)
        return _build_default_manifest(inputs, payload, run_id=run_id)

    def publish_canonical(payload: dict[str, Any], manifest: object) -> Path:
        target = reports_dir / f"auto_screening_{payload['date']}.json"
        atomic_write_json(
            target,
            _publication_payload(payload, manifest, status=AutoRunStatus.HEALTHY),
        )
        return target

    def publish_attempt(payload: dict[str, Any], manifest: object) -> Path:
        target = (
            reports_dir
            / f"auto_attempt_{payload['date']}_{getattr(manifest, 'run_id')}.json"
        )
        atomic_write_json(
            target,
            _publication_payload(payload, manifest, status=AutoRunStatus.DEGRADED),
        )
        return target

    def update_tracking(payload: dict[str, Any]) -> int:
        from src.screening.recommendation_tracker import (
            update_tracking_history_from_payload,
        )

        return update_tracking_history_from_payload(
            reports_dir=reports_dir,
            trade_date=str(payload["date"]),
            report_payload=payload,
        )

    return AutoPipelineDependencies(
        prepare_inputs=prepare_inputs,
        compute_report=compute_report,
        build_manifest=build_manifest,
        publish_canonical=publish_canonical,
        publish_attempt=publish_attempt,
        update_tracking=update_tracking,
    )


def _publish_failure_attempt(
    reports_dir: Path,
    trade_date: str,
    run_id: str,
    stage: str,
    exc: Exception,
    *,
    status: str = AutoRunStatus.FATAL.value,
    payload: Mapping[str, Any] | None = None,
) -> Path | None:
    target = reports_dir / f"auto_attempt_{trade_date}_{run_id}.json"
    try:
        atomic_write_json(
            target,
            {
                "run_id": run_id,
                "date": trade_date,
                "status": status,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "stage": stage,
                "error": {"type": type(exc).__name__, "message": str(exc)},
                "intended_payload": dict(payload) if payload is not None else None,
            },
        )
    except Exception:
        return None
    return target


def _publish_pending_attempt(
    reports_dir: Path,
    trade_date: str,
    run_id: str,
    payload: Mapping[str, Any],
) -> Path:
    target = reports_dir / f"auto_attempt_{trade_date}_{run_id}.json"
    atomic_write_json(
        target,
        {
            "run_id": run_id,
            "date": trade_date,
            "status": "pending",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "stage": "update_tracking",
            "intended_payload": dict(payload),
        },
    )
    return target


def _remove_pending_attempt(path: Path) -> bool:
    try:
        path.unlink()
        _fsync_directory(path.parent)
    except OSError:
        return False
    return True


def run_auto_pipeline(
    trade_date: str,
    top_n: int,
    strict_quality: bool = False,
    *,
    reports_dir: Path | None = None,
    dependencies: AutoPipelineDependencies | None = None,
) -> AutoRunResult:
    """Compute once and atomically publish either canonical or attempt output."""
    resolved_reports_dir = (
        Path(reports_dir)
        if reports_dir is not None
        else Path(__file__).resolve().parents[2] / "data" / "reports"
    )
    run_id = _new_run_id(trade_date)
    resolved_dependencies = dependencies or _default_dependencies(
        resolved_reports_dir, run_id
    )
    payload: dict[str, Any] | None = None
    manifest: object | None = None
    stage = "prepare_inputs"
    try:
        inputs = resolved_dependencies.prepare_inputs(trade_date)
        stage = "compute_report"
        payload = resolved_dependencies.compute_report(inputs, top_n)
        stage = "validate_payload"
        if not isinstance(payload, dict):
            raise TypeError("auto report payload must be a dict")
        payload_date = str(payload.get("date", "") or "")
        if payload_date != trade_date:
            raise ValueError(
                f"auto report payload date {payload_date!r} does not match trade_date {trade_date!r}"
            )
        normalized = json.loads(
            json.dumps(
                _sanitize_nonfinite(payload),
                ensure_ascii=False,
                default=str,
                allow_nan=False,
            )
        )
        payload.clear()
        payload.update(normalized)
        stage = "build_manifest"
        manifest = resolved_dependencies.build_manifest(inputs, payload)
        if bool(getattr(manifest, "is_healthy")) and _manifest_has_auditable_evidence(
            manifest, payload
        ):
            _publication_payload(payload, manifest, status=AutoRunStatus.HEALTHY)
            stage = "publish_pending_attempt"
            pending_attempt = _publish_pending_attempt(
                resolved_reports_dir,
                trade_date,
                str(getattr(manifest, "run_id", run_id)),
                payload,
            )
            stage = "update_tracking"
            resolved_dependencies.update_tracking(payload)
            stage = "publish_canonical"
            canonical = resolved_dependencies.publish_canonical(payload, manifest)
            pending_removed = _remove_pending_attempt(pending_attempt)
            return AutoRunResult(
                AutoRunStatus.HEALTHY,
                0,
                canonical,
                payload,
                manifest,
                None if pending_removed else pending_attempt,
            )
        stage = "publish_attempt"
        attempt = resolved_dependencies.publish_attempt(payload, manifest)
        code = 3 if strict_quality else 0
        return AutoRunResult(
            AutoRunStatus.DEGRADED,
            code,
            attempt,
            payload,
            manifest,
        )
    except Exception as exc:
        failure_run_id = str(getattr(manifest, "run_id", run_id))
        attempt = _publish_failure_attempt(
            resolved_reports_dir,
            trade_date,
            failure_run_id,
            stage,
            exc,
            payload=payload,
        )
        return AutoRunResult(
            AutoRunStatus.FATAL,
            1,
            attempt,
            payload,
            manifest,
        )
