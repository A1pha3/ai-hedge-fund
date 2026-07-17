"""Single-publication orchestration for the ``--auto`` screening run."""

from __future__ import annotations

import csv
import hashlib
import inspect
import io
import json
import math
import os
import re
import stat
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
    _sanitize_nonfinite,
    atomic_write_json,
)


class AutoRunStatus(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    FATAL = "fatal"


_RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_TRADE_DATE_PATTERN = re.compile(r"^\d{8}$")
_TICKER_PATTERN = re.compile(r"^[0-9]{6}$")
_PENDING_DIRNAME = ".auto_pending"


def _validate_trade_date(value: object) -> str:
    if type(value) is not str:
        raise ValueError("trade_date must be an exact YYYYMMDD string")
    text = value
    if not _TRADE_DATE_PATTERN.fullmatch(text):
        raise ValueError("trade_date must be exact YYYYMMDD")
    try:
        datetime.strptime(text, "%Y%m%d")
    except ValueError as exc:
        raise ValueError("trade_date must be a valid YYYYMMDD date") from exc
    return text


def _validate_run_id(value: object) -> str:
    if type(value) is not str:
        raise ValueError("run_id must be a string")
    text = value
    if not _RUN_ID_PATTERN.fullmatch(text):
        raise ValueError("run_id contains unsafe characters or invalid length")
    return text


@dataclass(frozen=True)
class AutoRunResult:
    status: AutoRunStatus
    exit_code: int
    artifact_path: Path | None
    payload: dict[str, Any] | None
    manifest: object | None
    diagnostic_path: Path | None = None
    recovered: bool = False
    recovery_diagnostics: tuple[dict[str, Any], ...] = ()
    effective_trade_date: str | None = None
    daily_action_readiness_publication: object | None = None


@dataclass(frozen=True)
class AutoPipelineDependencies:
    prepare_inputs: Callable[[str], object]
    compute_report: Callable[[object, int], dict[str, Any]]
    build_manifest: Callable[[object, dict[str, Any]], object]
    publish_canonical: Callable[[dict[str, Any], object], Path]
    publish_attempt: Callable[[dict[str, Any], object], Path]
    update_tracking: Callable[[dict[str, Any]], object]
    state_hook: Callable[[str, Path, dict[str, Any]], None] | None = None
    get_daily_readiness_publication: Callable[[], object | None] | None = None


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
    baseline_tickers: Mapping[str, TickerInputSnapshot]
    baseline_industries: Mapping[str, IndustryInputSnapshot]
    baseline_fingerprint: str
    baseline_consistent: bool
    industry_content_fingerprint: str
    run_id: str = ""
    candidate_tickers: tuple[str, ...] = ()
    candidate_set_fingerprint: str | None = None
    candidate_snapshot_fingerprint: str | None = None
    admission_projection_fingerprint: str | None = None


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


def _capture_ticker_snapshot(
    ticker: str,
    *,
    target_date: date,
    price_dir: Path,
    fund_dir: Path,
) -> TickerInputSnapshot:
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
    price_row = next(
        (
            row
            for row in reversed(pit_price_rows)
            if _parse_evidence_date(row.get("date") or row.get("trade_date"))
            == target_date
        ),
        None,
    )
    ohlcv_finite = False
    if price_row is not None:
        try:
            ohlcv_finite = all(
                math.isfinite(float(price_row[field]))
                for field in ("open", "high", "low", "close", "volume")
            )
        except (KeyError, TypeError, ValueError):
            pass
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
        }
    )
    return TickerInputSnapshot(
        ohlcv_date=target_date if price_row is not None else None,
        ohlcv_finite=ohlcv_finite,
        fund_flow_date=fund_dates[-1] if fund_dates else None,
        fund_flow_history_days=len(fund_dates),
        price_fingerprint=_fingerprint_rows(pit_price_rows),
        fund_flow_fingerprint=_fingerprint_rows(pit_fund_rows),
    )


def _capture_input_snapshot(
    trade_date: str,
    *,
    reports_dir: Path,
    cache_refresh_summary: Mapping[str, Any],
    candidate_tickers: tuple[str, ...] = (),
    ticker_industries: Mapping[str, str] | None = None,
    run_id: str = "",
    candidate_set_fingerprint: str | None = None,
    candidate_snapshot_fingerprint: str | None = None,
    admission_projection_fingerprint: str | None = None,
    baseline_tickers: Mapping[str, TickerInputSnapshot] | None = None,
    baseline_industries: Mapping[str, IndustryInputSnapshot] | None = None,
    baseline_fingerprint: str | None = None,
    baseline_consistent: bool = True,
) -> AutoInputs:
    """Freeze cache evidence before report computation can observe later writes."""
    target_date = datetime.strptime(trade_date, "%Y%m%d").date()
    data_dir = reports_dir.parent
    price_dir = data_dir / "price_cache"
    fund_dir = data_dir / "fund_flow_cache"
    industry_dir = data_dir / "industry_index_cache"

    ticker_names = set(candidate_tickers)
    all_cache_tickers = {
        path.stem
        for directory in (price_dir, fund_dir)
        for path in directory.glob("*.csv")
        if _TICKER_PATTERN.fullmatch(path.stem)
    }
    names_to_capture = ticker_names | (
        all_cache_tickers if baseline_tickers is None else set()
    )
    captured = {
        ticker: _capture_ticker_snapshot(
            ticker,
            target_date=target_date,
            price_dir=price_dir,
            fund_dir=fund_dir,
        )
        for ticker in sorted(names_to_capture)
    }
    ticker_snapshots = {ticker: captured[ticker] for ticker in ticker_names}

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

    frozen_baseline_tickers = (
        dict(baseline_tickers)
        if baseline_tickers is not None
        else {ticker: captured[ticker] for ticker in sorted(all_cache_tickers)}
    )
    frozen_baseline_industries = (
        dict(baseline_industries)
        if baseline_industries is not None
        else dict(industry_snapshots)
    )
    computed_baseline_fingerprint = baseline_fingerprint or _canonical_fingerprint(
        {
            "tickers": {
                ticker: {
                    "price": snapshot.price_fingerprint,
                    "fund_flow": snapshot.fund_flow_fingerprint,
                }
                for ticker, snapshot in sorted(frozen_baseline_tickers.items())
            },
            "industries": {
                name: snapshot.fingerprint
                for name, snapshot in sorted(frozen_baseline_industries.items())
            },
        }
    )
    industry_content_fingerprint = _canonical_fingerprint(
        {
            name: snapshot.fingerprint
            for name, snapshot in sorted(industry_snapshots.items())
        }
    )

    bound_industries = {
        ticker: str(industry).strip()
        for ticker, industry in (ticker_industries or {}).items()
        if ticker in ticker_names and str(industry).strip()
    }

    return AutoInputs(
        trade_date=trade_date,
        prepared_at=datetime.now(timezone.utc),
        reports_dir=reports_dir,
        tickers=MappingProxyType(ticker_snapshots),
        industries=MappingProxyType(industry_snapshots),
        ticker_industries=MappingProxyType(bound_industries),
        cache_refresh_summary=MappingProxyType(dict(cache_refresh_summary)),
        baseline_tickers=MappingProxyType(frozen_baseline_tickers),
        baseline_industries=MappingProxyType(frozen_baseline_industries),
        baseline_fingerprint=computed_baseline_fingerprint,
        baseline_consistent=baseline_consistent,
        industry_content_fingerprint=industry_content_fingerprint,
        run_id=run_id,
        candidate_tickers=tuple(sorted(ticker_names)),
        candidate_set_fingerprint=candidate_set_fingerprint,
        candidate_snapshot_fingerprint=candidate_snapshot_fingerprint,
        admission_projection_fingerprint=admission_projection_fingerprint,
    )


def _canonical_fingerprint(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _candidate_records(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value:
        raise ValueError("candidate evidence must be a nonempty list")
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, Mapping):
            raise ValueError("candidate evidence rows must be mappings")
        row = dict(item)
        raw_ticker = row.get("ticker") if "ticker" in row else row.get("ts_code")
        if type(raw_ticker) is not str or not _TICKER_PATTERN.fullmatch(raw_ticker):
            raise ValueError("candidate evidence ticker must be exact six ASCII digits")
        ticker = raw_ticker
        if ticker in seen:
            raise ValueError("candidate evidence tickers must be unique")
        row["ticker"] = ticker
        records.append(row)
        seen.add(ticker)
    return records


def _admission_projection(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    projection: list[dict[str, Any]] = []
    for row in records:
        projection.append(
            {
                "ticker": row["ticker"],
                "name": str(row.get("name") or ""),
                "industry_sw": str(
                    row.get("industry_sw") or row.get("industry") or ""
                ),
                "listing_date": str(row.get("listing_date") or ""),
                "security_status": row.get("security_status"),
                "st_status": row.get("st_status"),
                "board_rule_version": row.get("board_rule_version"),
            }
        )
    return sorted(projection, key=lambda row: row["ticker"])


def _finalize_inputs_after_compute(
    prepared: AutoInputs,
    payload: Mapping[str, Any],
    *,
    run_id: str,
) -> AutoInputs:
    """Bind cache evidence to the exact Layer-A output from this compute call."""
    evidence = payload.get("candidate_pool_run")
    if not isinstance(evidence, Mapping):
        raise ValueError("missing candidate_pool_run evidence")
    if str(evidence.get("trade_date") or "") != prepared.trade_date:
        raise ValueError("candidate evidence trade_date does not match run")
    direct_records = _candidate_records(evidence.get("candidates"))
    direct_tickers = tuple(sorted(row["ticker"] for row in direct_records))
    declared = evidence.get("tickers")
    if (
        not isinstance(declared, list)
        or any(
            type(ticker) is not str or not _TICKER_PATTERN.fullmatch(ticker)
            for ticker in declared
        )
        or tuple(sorted(declared)) != direct_tickers
    ):
        raise ValueError("candidate ticker declaration does not match compute output")

    snapshot_path = (
        prepared.reports_dir.parent
        / "snapshots"
        / f"candidate_pool_{prepared.trade_date}.json"
    )
    try:
        snapshot_records = _candidate_records(
            json.loads(snapshot_path.read_text(encoding="utf-8"))
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("candidate snapshot is missing or invalid") from exc
    snapshot_tickers = tuple(sorted(row["ticker"] for row in snapshot_records))
    if snapshot_tickers != direct_tickers:
        raise ValueError("candidate snapshot does not match current compute output")
    direct_projection = _admission_projection(direct_records)
    snapshot_projection = _admission_projection(snapshot_records)
    if snapshot_projection != direct_projection:
        raise ValueError("candidate admission evidence does not match current compute output")

    industries = {
        row["ticker"]: str(row.get("industry_sw") or row.get("industry") or "").strip()
        for row in direct_records
    }
    candidate_set_fingerprint = _canonical_fingerprint(list(direct_tickers))
    snapshot_fingerprint = _canonical_fingerprint(snapshot_records)
    admission_projection_fingerprint = _canonical_fingerprint(direct_projection)
    finalized = _capture_input_snapshot(
        prepared.trade_date,
        reports_dir=prepared.reports_dir,
        cache_refresh_summary=prepared.cache_refresh_summary,
        candidate_tickers=direct_tickers,
        ticker_industries=industries,
        run_id=run_id,
        candidate_set_fingerprint=candidate_set_fingerprint,
        candidate_snapshot_fingerprint=snapshot_fingerprint,
        admission_projection_fingerprint=admission_projection_fingerprint,
        baseline_tickers=prepared.baseline_tickers,
        baseline_industries=prepared.baseline_industries,
        baseline_fingerprint=prepared.baseline_fingerprint,
    )
    candidate_cache_consistent = all(
        ticker in prepared.baseline_tickers
        and prepared.baseline_tickers[ticker] == finalized.tickers[ticker]
        and prepared.baseline_tickers[ticker].price_fingerprint is not None
        and prepared.baseline_tickers[ticker].fund_flow_fingerprint is not None
        for ticker in direct_tickers
    )
    industry_consistent = all(
        bool(industry := industries.get(ticker))
        and industry in prepared.baseline_industries
        and prepared.baseline_industries[industry] == finalized.industries.get(industry)
        and prepared.baseline_industries[industry].fingerprint is not None
        for ticker in direct_tickers
    )
    return _capture_input_snapshot(
        prepared.trade_date,
        reports_dir=prepared.reports_dir,
        cache_refresh_summary=prepared.cache_refresh_summary,
        candidate_tickers=direct_tickers,
        ticker_industries=industries,
        run_id=run_id,
        candidate_set_fingerprint=candidate_set_fingerprint,
        candidate_snapshot_fingerprint=snapshot_fingerprint,
        admission_projection_fingerprint=admission_projection_fingerprint,
        baseline_tickers=prepared.baseline_tickers,
        baseline_industries=prepared.baseline_industries,
        baseline_fingerprint=prepared.baseline_fingerprint,
        baseline_consistent=candidate_cache_consistent and industry_consistent,
    )


def _input_snapshot_is_current(inputs: AutoInputs) -> bool:
    snapshot_path = (
        inputs.reports_dir.parent
        / "snapshots"
        / f"candidate_pool_{inputs.trade_date}.json"
    )
    try:
        current_candidate_fingerprint = _canonical_fingerprint(
            _candidate_records(json.loads(snapshot_path.read_text(encoding="utf-8")))
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return False
    if current_candidate_fingerprint != inputs.candidate_snapshot_fingerprint:
        return False
    current = _capture_input_snapshot(
        inputs.trade_date,
        reports_dir=inputs.reports_dir,
        cache_refresh_summary=inputs.cache_refresh_summary,
        candidate_tickers=inputs.candidate_tickers,
        ticker_industries=inputs.ticker_industries,
        run_id=inputs.run_id,
        candidate_set_fingerprint=inputs.candidate_set_fingerprint,
        candidate_snapshot_fingerprint=inputs.candidate_snapshot_fingerprint,
        admission_projection_fingerprint=inputs.admission_projection_fingerprint,
        baseline_tickers=inputs.baseline_tickers,
        baseline_industries=inputs.baseline_industries,
        baseline_fingerprint=inputs.baseline_fingerprint,
        baseline_consistent=inputs.baseline_consistent,
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
    if inputs.run_id and inputs.run_id != run_id:
        raise ValueError("manifest run_id does not match finalized inputs")
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

    scan_tickers = sorted(set(inputs.candidate_tickers) | set(recommendation_by_ticker))
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

    # Authoritative Auto quality verdict comes from the pure assessor that
    # reads only ``data_quality.scoring_features``. We serialize the
    # structured decision (blockers + warnings) into the payload so consumers
    # can inspect WHY Auto is healthy or degraded without re-running the
    # assessor. The wrapper ``_quality_is_healthy`` exists only for backward
    # compatibility with callers that expect a boolean.
    from src.screening.scoring_feature_quality import assess_auto_quality

    quality_decision = assess_auto_quality(payload)
    payload["quality_decision"] = {
        "healthy": quality_decision.healthy,
        "blockers": [
            {"family": blocker.family, "code": blocker.code, "detail": blocker.detail}
            for blocker in quality_decision.blockers
        ],
        "warnings": [
            {"family": warning.family, "code": warning.code, "detail": warning.detail}
            for warning in quality_decision.warnings
        ],
    }
    manifest_status = (
        AutoRunStatus.HEALTHY
        if quality_decision.healthy
        else AutoRunStatus.DEGRADED
    )
    input_fingerprint = _canonical_fingerprint(
        {
            "run_id": inputs.run_id,
            "trade_date": inputs.trade_date,
            "candidate_tickers": list(inputs.candidate_tickers),
            "candidate_set_fingerprint": inputs.candidate_set_fingerprint,
            "candidate_snapshot_fingerprint": inputs.candidate_snapshot_fingerprint,
            "admission_projection_fingerprint": inputs.admission_projection_fingerprint,
            "baseline_fingerprint": inputs.baseline_fingerprint,
            "industry_content_fingerprint": inputs.industry_content_fingerprint,
            "ticker_inputs": {
                ticker: {
                    "price": snapshot.price_fingerprint,
                    "fund_flow": snapshot.fund_flow_fingerprint,
                    "industry": inputs.ticker_industries.get(ticker),
                }
                for ticker, snapshot in sorted(inputs.tickers.items())
            },
        }
    )
    return RunManifest(
        run_id=run_id,
        trade_date=target_date,
        status=manifest_status.value,
        created_at=inputs.prepared_at,
        tickers=readiness_by_ticker,
        candidate_tickers=inputs.candidate_tickers,
        candidate_set_fingerprint=inputs.candidate_set_fingerprint,
        candidate_snapshot_fingerprint=inputs.candidate_snapshot_fingerprint,
        admission_projection_fingerprint=inputs.admission_projection_fingerprint,
        baseline_fingerprint=inputs.baseline_fingerprint,
        industry_content_fingerprint=inputs.industry_content_fingerprint,
        input_fingerprint=input_fingerprint,
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
            "trade_date": manifest.trade_date.strftime("%Y%m%d"),
            "status": manifest.status,
            "is_healthy": manifest.is_healthy,
            "created_at": manifest.created_at.isoformat(),
            "candidate_tickers": list(manifest.candidate_tickers),
            "candidate_set_fingerprint": manifest.candidate_set_fingerprint,
            "candidate_snapshot_fingerprint": manifest.candidate_snapshot_fingerprint,
            "admission_projection_fingerprint": manifest.admission_projection_fingerprint,
            "baseline_fingerprint": manifest.baseline_fingerprint,
            "industry_content_fingerprint": manifest.industry_content_fingerprint,
            "input_fingerprint": manifest.input_fingerprint,
            "tickers": {
                ticker: _readiness_payload(readiness)
                for ticker, readiness in manifest.tickers.items()
            },
        }
    return {
        "run_id": str(getattr(manifest, "run_id")),
        "status": (
            "healthy"
            if getattr(manifest, "is_healthy", None) is True
            else "degraded"
        ),
        "is_healthy": getattr(manifest, "is_healthy", None),
    }


def _publication_payload(
    payload: dict[str, Any],
    manifest: object,
    *,
    status: AutoRunStatus,
) -> dict[str, Any]:
    manifest_payload = _manifest_payload(manifest)
    manifest_payload.setdefault("trade_date", str(payload.get("date") or ""))
    payload["run_id"] = manifest_payload["run_id"]
    payload["status"] = status.value
    payload["manifest"] = manifest_payload
    return payload


def _quality_is_healthy(payload: Mapping[str, Any]) -> bool:
    """Compatibility wrapper. Returns only the healthy boolean.

    Full structured decision (blockers, warnings) is available via
    ``assess_auto_quality(payload)`` from :mod:`scoring_feature_quality`.

    The Auto canonical health authority is ``payload["data_quality"]
    ["scoring_features"]``. The legacy ``daily_action_cache_refresh`` block
    and the ``optional_features`` compatibility projection are intentionally
    ignored here: per spec sections 4 and 10, those belong to other domains
    and must not gate the Auto verdict. The structured verdict is serialized
    into the payload as ``payload["quality_decision"]`` by
    :func:`_build_default_manifest` so consumers can inspect blockers and
    warnings without re-running the assessor.
    """
    from src.screening.scoring_feature_quality import assess_auto_quality

    return assess_auto_quality(payload).healthy


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


def _default_dependencies(
    reports_dir: Path,
    data_dir: Path,
    run_id: str,
    *,
    refresh_fn: Callable[..., object] | None = None,
    calendar_refresh_fn: Callable[..., object] | None = None,
    panel_backfill_fn: Callable[..., object] | None = None,
    panel_health_fn: Callable[..., object] | None = None,
    reference_snapshot_loader: Callable[[], object] | None = None,
) -> AutoPipelineDependencies:
    from src.screening.offensive.daily_action import _env_setup_disable_list

    # Environment policy is mutable process-global state. Freeze it once when
    # the default run dependencies are created; builders and publishers must
    # consume only this run-bound value.
    oversold_bounce_enabled = (
        "oversold_bounce" not in _env_setup_disable_list()
    )
    readiness_state: dict[str, object | None] = {
        "refresh_result": None,
        "publication": None,
    }

    def prepare_inputs(trade_date: str) -> AutoInputs:
        from src import main
        refresh_payload: dict[str, Any] = {}
        readiness_state["refresh_result"] = main._refresh_daily_action_caches_for_auto(
            trade_date,
            refresh_payload,
            reports_dir=reports_dir,
            data_dir=data_dir,
            refresh_fn=refresh_fn,
            calendar_refresh_fn=calendar_refresh_fn,
            panel_backfill_fn=panel_backfill_fn,
            panel_health_fn=panel_health_fn,
        )
        return _capture_input_snapshot(
            trade_date,
            reports_dir=reports_dir,
            cache_refresh_summary=refresh_payload.get("daily_action_cache_refresh", {}),
        )

    def compute_report(inputs: object, top_n: int) -> dict[str, Any]:
        from src import main

        assert isinstance(inputs, AutoInputs)
        captured_reference_snapshot: object | None = None
        if reference_snapshot_loader is None:
            from src.tools.tushare_api import (
                begin_daily_readiness_reference_capture,
                end_daily_readiness_reference_capture,
            )

            capture_token = begin_daily_readiness_reference_capture(
                inputs.trade_date
            )
            try:
                payload = main.compute_auto_screening_results(inputs.trade_date, top_n)
            finally:
                captured_reference_snapshot = (
                    end_daily_readiness_reference_capture(capture_token)
                )
        else:
            payload = main.compute_auto_screening_results(inputs.trade_date, top_n)
        if inputs.cache_refresh_summary:
            payload["daily_action_cache_refresh"] = dict(inputs.cache_refresh_summary)
        main._attach_freshness_check(inputs.trade_date, payload)
        refresh_result = readiness_state["refresh_result"]
        from src.screening.offensive.cache_readiness import DailyActionRefreshResult
        from src.screening.offensive.daily_action_readiness import (
            publish_daily_action_attempt,
        )

        if type(refresh_result) is DailyActionRefreshResult:
            try:
                frozen_source = main._capture_shared_readiness_evidence_source_for_auto(
                    refresh_result,
                    data_dir=data_dir,
                    reference_snapshot_loader=(
                        reference_snapshot_loader
                        if reference_snapshot_loader is not None
                        else lambda: captured_reference_snapshot
                    ),
                )
                publication = main._complete_daily_action_readiness_for_auto(
                    refresh_result,
                    payload,
                    reports_dir=reports_dir,
                    frozen_source=frozen_source,
                    oversold_bounce_enabled=oversold_bounce_enabled,
                )
            except Exception as exc:  # noqa: BLE001 - fail closed into attempt
                main.logger.warning(
                    "[Auto] Daily Action 证据冻结失败，未就绪: %s", exc
                )
                publication = main._publish_daily_action_attempt_for_auto(
                    refresh_result=refresh_result,
                    reports_dir=reports_dir,
                    reason=f"shared_source_capture_failed:{type(exc).__name__}: {str(exc)[:200]}",
                )
        else:
            attempt_run_id = hashlib.sha256(
                f"{inputs.trade_date}|{run_id}|refresh-unavailable".encode("utf-8")
            ).hexdigest()[:32]
            publication = publish_daily_action_attempt(
                trade_date=datetime.strptime(inputs.trade_date, "%Y%m%d").date(),
                run_id=attempt_run_id,
                reports_dir=reports_dir,
                reasons=("refresh_result_unavailable",),
            )
        readiness_state["publication"] = publication
        payload["daily_action_readiness"] = _daily_readiness_publication_payload(
            publication
        )
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
        get_daily_readiness_publication=lambda: readiness_state["publication"],
    )


def _daily_readiness_publication_payload(publication: object) -> dict[str, Any]:
    """Serialize operator-facing readiness facts from the actual publication."""

    manifest = getattr(publication, "manifest", None)
    publication_status = str(
        getattr(publication, "status", "degraded") or "degraded"
    )
    if manifest is None or publication_status != "healthy":
        return {
            "status": "blocked",
            "publication_status": publication_status,
            "universe_count": None,
            "scannable_count": None,
            "plan_eligible_count": None,
            "degraded_count": None,
            "failed_count": None,
            "block_reasons": ["readiness_attempt"],
        }

    readiness_values = tuple(manifest.ticker_readiness.values())
    return {
        "status": "healthy",
        "publication_status": publication_status,
        "universe_count": len(manifest.universe_tickers),
        "scannable_count": sum(
            any(capability.scannable for capability in item.capabilities.values())
            for item in readiness_values
        ),
        "plan_eligible_count": sum(
            any(
                capability.plan_eligible
                for capability in item.capabilities.values()
            )
            for item in readiness_values
        ),
        "degraded_count": sum(
            any(capability.degraded for capability in item.capabilities.values())
            for item in readiness_values
        ),
        "failed_count": sum(
            item.evidence_status != "verified" for item in readiness_values
        ),
        "block_reasons": [],
    }


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
    safe_date = _validate_trade_date(trade_date)
    try:
        safe_run_id = _validate_run_id(run_id)
    except ValueError:
        safe_run_id = _new_run_id(safe_date)
    target = reports_dir / f"auto_attempt_{safe_date}_{safe_run_id}.json"
    try:
        atomic_write_json(
            target,
            {
                "run_id": safe_run_id,
                "date": safe_date,
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


_PENDING_SCHEMA_VERSION = 1
_PENDING_PHASES = ("prepared", "tracked", "canonical")


_PENDING_DIR_FLAGS = (
    os.O_RDONLY
    | getattr(os, "O_DIRECTORY", 0)
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_CLOEXEC", 0)
)
_PENDING_FILE_FLAGS = getattr(os, "O_NOFOLLOW", 0) | getattr(
    os, "O_CLOEXEC", 0
)
_PENDING_DIR_FD_SUPPORTED = all(
    function in os.supports_dir_fd
    for function in (os.open, os.mkdir, os.stat, os.unlink, os.rmdir)
) and os.listdir in os.supports_fd
try:
    _replace_parameters = inspect.signature(os.replace).parameters
    _PENDING_REPLACE_DIR_FD_SUPPORTED = {
        "src_dir_fd",
        "dst_dir_fd",
    }.issubset(_replace_parameters)
except (TypeError, ValueError):
    _PENDING_REPLACE_DIR_FD_SUPPORTED = False
_PENDING_NOFOLLOW_STAT_SUPPORTED = os.stat in os.supports_follow_symlinks


def _require_pending_fd_primitives() -> None:
    missing = [
        name
        for name in ("O_DIRECTORY", "O_NOFOLLOW")
        if not hasattr(os, name)
    ]
    if (
        missing
        or not _PENDING_DIR_FD_SUPPORTED
        or not _PENDING_REPLACE_DIR_FD_SUPPORTED
        or not _PENDING_NOFOLLOW_STAT_SUPPORTED
    ):
        detail = ", ".join(missing) or "dir_fd operations"
        raise RuntimeError(
            f"descriptor-relative pending operations unavailable: {detail}"
        )


def _close_fd(fd: int | None) -> None:
    if fd is None:
        return
    try:
        os.close(fd)
    except OSError:
        pass


@dataclass
class _PendingStateHandle:
    reports_dir: Path
    reports_fd: int
    root_fd: int
    date_fd: int
    date_name: str
    state_name: str
    closed: bool = False

    @property
    def path(self) -> Path:
        return (
            self.reports_dir
            / _PENDING_DIRNAME
            / self.date_name
            / self.state_name
        )

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        _close_fd(self.date_fd)
        _close_fd(self.root_fd)
        _close_fd(self.reports_fd)


def _open_dir_at(name: str, parent_fd: int) -> int:
    try:
        fd = os.open(name, _PENDING_DIR_FLAGS, dir_fd=parent_fd)
    except (NotImplementedError, TypeError) as exc:
        raise RuntimeError(
            "descriptor-relative pending directory open unavailable"
        ) from exc
    if not stat.S_ISDIR(os.fstat(fd).st_mode):
        _close_fd(fd)
        raise ValueError(f"pending namespace entry is not a directory: {name}")
    return fd


def _open_reports_fd(reports_dir: Path) -> int:
    _require_pending_fd_primitives()
    reports_dir.mkdir(parents=True, exist_ok=True)
    try:
        return os.open(reports_dir, _PENDING_DIR_FLAGS)
    except (NotImplementedError, TypeError) as exc:
        raise RuntimeError("secure reports directory open unavailable") from exc


def _open_pending_handle(
    reports_dir: Path,
    trade_date: str,
    run_id: str,
    *,
    create: bool,
) -> _PendingStateHandle:
    safe_date = _validate_trade_date(trade_date)
    safe_run_id = _validate_run_id(run_id)
    reports_fd = _open_reports_fd(reports_dir)
    root_fd: int | None = None
    date_fd: int | None = None
    try:
        if create:
            try:
                os.mkdir(_PENDING_DIRNAME, 0o700, dir_fd=reports_fd)
            except FileExistsError:
                pass
        try:
            root_fd = _open_dir_at(_PENDING_DIRNAME, reports_fd)
        except OSError as exc:
            raise ValueError("pending root must be a real directory") from exc
        if create:
            os.fsync(reports_fd)
        if create:
            try:
                os.mkdir(safe_date, 0o700, dir_fd=root_fd)
            except FileExistsError:
                pass
        date_fd = _open_dir_at(safe_date, root_fd)
        if create:
            os.fsync(root_fd)
        return _PendingStateHandle(
            reports_dir=reports_dir,
            reports_fd=reports_fd,
            root_fd=root_fd,
            date_fd=date_fd,
            date_name=safe_date,
            state_name=f"{safe_run_id}.json",
        )
    except BaseException:
        _close_fd(date_fd)
        _close_fd(root_fd)
        _close_fd(reports_fd)
        raise


def _listdir_fd(directory_fd: int) -> list[str]:
    try:
        names = os.listdir(directory_fd)
    except (NotImplementedError, TypeError) as exc:
        raise RuntimeError(
            "descriptor-relative pending discovery unavailable"
        ) from exc
    if not all(type(name) is str and name not in (".", "..") for name in names):
        raise ValueError("pending namespace returned unsafe entry names")
    return sorted(names)


def _read_pending_json(handle: _PendingStateHandle) -> dict[str, Any]:
    fd: int | None = None
    try:
        fd = os.open(
            handle.state_name,
            os.O_RDONLY | _PENDING_FILE_FLAGS,
            dir_fd=handle.date_fd,
        )
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ValueError(f"pending state is not a regular file: {handle.path}")
        chunks: list[bytes] = []
        while chunk := os.read(fd, 65536):
            chunks.append(chunk)
        state = json.loads(b"".join(chunks).decode("utf-8"))
    except (NotImplementedError, TypeError) as exc:
        raise RuntimeError("descriptor-relative pending read unavailable") from exc
    finally:
        _close_fd(fd)
    if not isinstance(state, dict):
        raise ValueError(f"pending state must be an object: {handle.path}")
    return state


def _pending_target_mode(handle: _PendingStateHandle) -> int | None:
    try:
        target_stat = os.stat(
            handle.state_name,
            dir_fd=handle.date_fd,
            follow_symlinks=False,
        )
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(target_stat.st_mode):
        raise ValueError(f"pending state target is not regular: {handle.path}")
    return stat.S_IMODE(target_stat.st_mode)


def _write_pending_json(handle: _PendingStateHandle, payload: Mapping[str, Any]) -> None:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        indent=2,
        default=str,
        allow_nan=False,
    ).encode("utf-8")
    mode = _pending_target_mode(handle)
    temp_name = f".{handle.state_name}.{uuid.uuid4().hex}.tmp"
    temp_fd: int | None = None
    temp_created = False
    try:
        temp_fd = os.open(
            temp_name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | _PENDING_FILE_FLAGS,
            0o666,
            dir_fd=handle.date_fd,
        )
        temp_created = True
        if mode is not None:
            os.fchmod(temp_fd, mode)
        view = memoryview(encoded)
        while view:
            written = os.write(temp_fd, view)
            if written <= 0:
                raise OSError("short pending state write")
            view = view[written:]
        os.fsync(temp_fd)
        os.close(temp_fd)
        temp_fd = None
        try:
            os.replace(
                temp_name,
                handle.state_name,
                src_dir_fd=handle.date_fd,
                dst_dir_fd=handle.date_fd,
            )
        except (NotImplementedError, TypeError) as exc:
            raise RuntimeError(
                "descriptor-relative pending replace unavailable"
            ) from exc
        os.fsync(handle.date_fd)
    except BaseException:
        _close_fd(temp_fd)
        if temp_created:
            try:
                os.unlink(temp_name, dir_fd=handle.date_fd)
            except OSError:
                pass
        raise


def _entry_matches_fd(name: str, parent_fd: int, child_fd: int) -> bool:
    try:
        entry = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except OSError:
        return False
    held = os.fstat(child_fd)
    return stat.S_ISDIR(entry.st_mode) and (entry.st_dev, entry.st_ino) == (
        held.st_dev,
        held.st_ino,
    )


def _pending_state_checksum(state: Mapping[str, Any]) -> str:
    return _canonical_fingerprint(
        {
            "schema_version": state.get("schema_version"),
            "run_id": state.get("run_id"),
            "date": state.get("date"),
            "phase": state.get("phase"),
            "payload_checksum": state.get("payload_checksum"),
            "manifest_fingerprint": state.get("manifest_fingerprint"),
            "input_fingerprint": state.get("input_fingerprint"),
            "canonical_filename": state.get("canonical_filename"),
        }
    )


def _build_pending_state(
    trade_date: str,
    run_id: str,
    payload: Mapping[str, Any],
    manifest: object,
) -> dict[str, Any]:
    safe_date = _validate_trade_date(trade_date)
    safe_run_id = _validate_run_id(run_id)
    manifest_payload = payload.get("manifest")
    if not isinstance(manifest_payload, Mapping):
        raise ValueError("healthy payload must contain serialized manifest")
    manifest_fingerprint = _canonical_fingerprint(manifest_payload)
    input_fingerprint = str(
        manifest_payload.get("input_fingerprint") or manifest_fingerprint
    )
    now = datetime.now(timezone.utc).isoformat()
    state: dict[str, Any] = {
        "schema_version": _PENDING_SCHEMA_VERSION,
        "run_id": safe_run_id,
        "date": safe_date,
        "status": "pending",
        "phase": "prepared",
        "created_at": now,
        "updated_at": now,
        "payload": dict(payload),
        "payload_checksum": _canonical_fingerprint(payload),
        "manifest_fingerprint": manifest_fingerprint,
        "input_fingerprint": input_fingerprint,
        "canonical_filename": f"auto_screening_{safe_date}.json",
    }
    state["state_checksum"] = _pending_state_checksum(state)
    return state


def _pending_identity(handle: _PendingStateHandle) -> tuple[str, str]:
    if not handle.state_name.endswith(".json"):
        raise ValueError(f"invalid pending filename: {handle.path}")
    return _validate_trade_date(handle.date_name), _validate_run_id(
        handle.state_name.removesuffix(".json")
    )


def _validate_pending_state(
    state: Mapping[str, Any],
    *,
    handle: _PendingStateHandle,
) -> None:
    path = handle.path
    filename_date, filename_run_id = _pending_identity(handle)
    if type(state.get("schema_version")) is not int or state.get(
        "schema_version"
    ) != _PENDING_SCHEMA_VERSION:
        raise ValueError(f"unsupported pending schema in {path}")
    if (
        state.get("status") != "pending"
        or type(state.get("phase")) is not str
        or state.get("phase") not in _PENDING_PHASES
    ):
        raise ValueError(f"invalid pending status/phase in {path}")
    state_date = _validate_trade_date(state.get("date"))
    state_run_id = _validate_run_id(state.get("run_id"))
    if state_date != filename_date or state_run_id != filename_run_id:
        raise ValueError(f"pending filename identity mismatch in {path}")
    payload = state.get("payload")
    if not isinstance(payload, Mapping):
        raise ValueError(f"pending payload missing in {path}")
    if type(payload.get("date")) is not str or payload.get("date") != state_date:
        raise ValueError(f"pending payload date mismatch in {path}")
    if (
        type(payload.get("run_id")) is not str
        or payload.get("run_id") != state_run_id
    ):
        raise ValueError(f"pending payload run_id mismatch in {path}")
    if payload.get("status") != AutoRunStatus.HEALTHY.value:
        raise ValueError(f"pending payload status must be healthy in {path}")
    if payload.get("mode") != "auto_screening":
        raise ValueError(f"pending payload mode must be auto_screening in {path}")
    if _canonical_fingerprint(payload) != state.get("payload_checksum"):
        raise ValueError(f"pending payload checksum mismatch in {path}")
    manifest = payload.get("manifest")
    if not isinstance(manifest, Mapping):
        raise ValueError(f"pending manifest missing in {path}")
    if (
        type(manifest.get("run_id")) is not str
        or manifest.get("run_id") != state_run_id
    ):
        raise ValueError(f"pending manifest run_id mismatch in {path}")
    if manifest.get("status") != AutoRunStatus.HEALTHY.value:
        raise ValueError(f"pending manifest status must be healthy in {path}")
    if manifest.get("is_healthy") is not True:
        raise ValueError(f"pending manifest health must be plain true in {path}")
    if _canonical_fingerprint(manifest) != state.get("manifest_fingerprint"):
        raise ValueError(f"pending manifest checksum mismatch in {path}")
    expected_input = str(
        manifest.get("input_fingerprint") or state.get("manifest_fingerprint")
    )
    if expected_input != state.get("input_fingerprint"):
        raise ValueError(f"pending input fingerprint mismatch in {path}")
    if (
        type(manifest.get("trade_date")) is not str
        or manifest.get("trade_date") != state_date
    ):
        raise ValueError(f"pending manifest trade_date mismatch in {path}")
    if state.get("canonical_filename") != f"auto_screening_{state_date}.json":
        raise ValueError(f"pending canonical binding mismatch in {path}")
    if _pending_state_checksum(state) != state.get("state_checksum"):
        raise ValueError(f"pending state checksum mismatch in {path}")


def _persist_pending_phase(
    handle: _PendingStateHandle,
    state: Mapping[str, Any],
    phase: str,
) -> dict[str, Any]:
    if phase not in _PENDING_PHASES:
        raise ValueError(f"unsupported pending phase: {phase}")
    updated = dict(state)
    updated["phase"] = phase
    updated["updated_at"] = datetime.now(timezone.utc).isoformat()
    updated["state_checksum"] = _pending_state_checksum(updated)
    _write_pending_json(handle, updated)
    return updated


def _publish_pending_attempt(
    reports_dir: Path,
    trade_date: str,
    run_id: str,
    payload: Mapping[str, Any],
    manifest: object,
) -> _PendingStateHandle:
    safe_date = _validate_trade_date(trade_date)
    safe_run_id = _validate_run_id(run_id)
    handle = _open_pending_handle(
        reports_dir,
        safe_date,
        safe_run_id,
        create=True,
    )
    try:
        _write_pending_json(
            handle,
            _build_pending_state(trade_date, run_id, payload, manifest),
        )
        return handle
    except BaseException:
        handle.close()
        raise


def _remove_pending_attempt(handle: _PendingStateHandle) -> bool:
    try:
        os.unlink(handle.state_name, dir_fd=handle.date_fd)
        os.fsync(handle.date_fd)
        try:
            if _entry_matches_fd(handle.date_name, handle.root_fd, handle.date_fd):
                os.rmdir(handle.date_name, dir_fd=handle.root_fd)
                os.fsync(handle.root_fd)
            if _entry_matches_fd(_PENDING_DIRNAME, handle.reports_fd, handle.root_fd):
                os.rmdir(_PENDING_DIRNAME, dir_fd=handle.reports_fd)
                os.fsync(handle.reports_fd)
        except OSError:
            pass
    except OSError:
        return False
    return True


def _call_state_hook(
    hook: Callable[[str, Path, dict[str, Any]], None] | None,
    boundary: str,
    path: Path,
    state: Mapping[str, Any],
) -> None:
    if hook is not None:
        hook(boundary, path, dict(state))


def _advance_pending_state(
    handle: _PendingStateHandle,
    state: Mapping[str, Any],
    *,
    update_tracking: Callable[[dict[str, Any]], object],
    publish_canonical: Callable[[dict[str, Any]], Path],
    state_hook: Callable[[str, Path, dict[str, Any]], None] | None = None,
    runtime_payload: dict[str, Any] | None = None,
) -> tuple[Path, dict[str, Any], bool]:
    """Idempotently advance one checksum-verified pending publication."""
    path = handle.path
    current = dict(state)
    reports_dir = handle.reports_dir
    _validate_pending_state(current, handle=handle)
    payload = runtime_payload if runtime_payload is not None else dict(current["payload"])
    if _canonical_fingerprint(payload) != current["payload_checksum"]:
        raise ValueError("runtime payload does not match durable pending payload")

    if current["phase"] == "prepared":
        update_tracking(payload)
        _call_state_hook(state_hook, "after_tracking", path, current)
        current = _persist_pending_phase(handle, current, "tracked")
        _call_state_hook(state_hook, "after_tracked_persist", path, current)

    canonical_path = reports_dir / str(current["canonical_filename"])
    if current["phase"] == "tracked":
        canonical_path = publish_canonical(payload)
        _call_state_hook(state_hook, "after_canonical", path, current)
        current = _persist_pending_phase(handle, current, "canonical")
        _call_state_hook(state_hook, "after_canonical_persist", path, current)

    if current["phase"] == "canonical":
        try:
            canonical_payload = json.loads(canonical_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            canonical_payload = None
        if canonical_payload != payload:
            canonical_path = publish_canonical(payload)
        _call_state_hook(state_hook, "before_pending_remove", path, current)
        removed = _remove_pending_attempt(handle)
        return canonical_path, current, removed
    raise ValueError(f"pending state did not reach canonical phase: {path}")


def _record_pending_error(
    handle: _PendingStateHandle,
    stage: str,
    exc: Exception,
) -> Path:
    path = handle.path
    try:
        state = _read_pending_json(handle)
        _validate_pending_state(state, handle=handle)
        state["last_error"] = {
            "stage": stage,
            "type": type(exc).__name__,
            "message": str(exc),
            "recorded_at": datetime.now(timezone.utc).isoformat(),
        }
        _write_pending_json(handle, state)
    except Exception:
        pass
    return path


def _discover_pending_states(
    reports_dir: Path,
) -> list[tuple[_PendingStateHandle, dict[str, Any]]]:
    reports_fd = _open_reports_fd(reports_dir)
    root_fd: int | None = None
    discovered: list[tuple[_PendingStateHandle, dict[str, Any]]] = []
    try:
        try:
            root_fd = _open_dir_at(_PENDING_DIRNAME, reports_fd)
        except FileNotFoundError:
            return []
        except OSError as exc:
            raise ValueError("pending root must be a real directory") from exc
        for date_name in _listdir_fd(root_fd):
            _validate_trade_date(date_name)
            date_fd = _open_dir_at(date_name, root_fd)
            try:
                for state_name in _listdir_fd(date_fd):
                    if not state_name.endswith(".json"):
                        raise ValueError(
                            f"invalid pending filename: {date_name}/{state_name}"
                        )
                    _validate_run_id(state_name.removesuffix(".json"))
                    handle = _PendingStateHandle(
                        reports_dir=reports_dir,
                        reports_fd=os.dup(reports_fd),
                        root_fd=os.dup(root_fd),
                        date_fd=os.dup(date_fd),
                        date_name=date_name,
                        state_name=state_name,
                    )
                    try:
                        state = _read_pending_json(handle)
                        _validate_pending_state(state, handle=handle)
                        discovered.append((handle, state))
                    except BaseException:
                        handle.close()
                        raise
            finally:
                _close_fd(date_fd)
        return discovered
    except BaseException:
        for handle, _state in discovered:
            handle.close()
        raise
    finally:
        _close_fd(root_fd)
        _close_fd(reports_fd)


def _reconcile_pending_run(
    reports_dir: Path,
    requested_trade_date: str,
) -> AutoRunResult | None:
    try:
        pending = _discover_pending_states(reports_dir)
    except Exception as exc:
        diagnostic = _publish_failure_attempt(
            reports_dir,
            requested_trade_date,
            _new_run_id(requested_trade_date),
            "discover_pending",
            exc,
        )
        return AutoRunResult(
            AutoRunStatus.FATAL,
            1,
            diagnostic,
            None,
            None,
            diagnostic,
            True,
            ({"action": "recovery_failed", "error": str(exc)},),
        )
    if not pending:
        return None
    if len(pending) != 1:
        for pending_handle, _pending_state in pending:
            pending_handle.close()
        exc = RuntimeError("multiple pending auto runs across dates")
        diagnostic = _publish_failure_attempt(
            reports_dir,
            requested_trade_date,
            _new_run_id(requested_trade_date),
            "reconcile_pending",
            exc,
        )
        return AutoRunResult(
            AutoRunStatus.FATAL,
            1,
            diagnostic,
            None,
            None,
            diagnostic,
            True,
            ({"action": "recovery_failed", "error": str(exc)},),
        )

    handle, state = pending[0]
    path = handle.path
    try:
        _validate_pending_state(state, handle=handle)
        payload = dict(state["payload"])
        bound_trade_date = str(state["date"])

        def durable_tracking(exact_payload: dict[str, Any]) -> object:
            from src.screening.recommendation_tracker import (
                update_tracking_history_from_payload,
            )

            return update_tracking_history_from_payload(
                reports_dir,
                bound_trade_date,
                exact_payload,
            )

        def durable_canonical(exact_payload: dict[str, Any]) -> Path:
            target = reports_dir / str(state["canonical_filename"])
            atomic_write_json(target, exact_payload)
            return target

        from_phase = str(state["phase"])
        canonical, final_state, removed = _advance_pending_state(
            handle,
            state,
            update_tracking=durable_tracking,
            publish_canonical=durable_canonical,
        )
        diagnostics = (
            {
                "action": "recovered_pending",
                "run_id": state["run_id"],
                "from_phase": from_phase,
                "final_phase": final_state["phase"],
                "pending_removed": removed,
                "pending_path": str(path),
                "requested_trade_date": requested_trade_date,
                "effective_trade_date": bound_trade_date,
                "requested_date_executed": requested_trade_date
                == bound_trade_date,
            },
        )
        return AutoRunResult(
            AutoRunStatus.HEALTHY,
            0,
            canonical,
            payload,
            payload.get("manifest"),
            None if removed else path,
            True,
            diagnostics,
            effective_trade_date=bound_trade_date,
        )
    except Exception as exc:
        _record_pending_error(handle, "reconcile_pending", exc)
        return AutoRunResult(
            AutoRunStatus.FATAL,
            1,
            path,
            state.get("payload") if isinstance(state, dict) else None,
            None,
            path,
            True,
            ({"action": "recovery_failed", "error": str(exc), "path": str(path)},),
        )
    finally:
        handle.close()


def run_auto_pipeline(
    trade_date: str,
    top_n: int,
    strict_quality: bool = False,
    *,
    reports_dir: Path | None = None,
    data_dir: Path | None = None,
    dependencies: AutoPipelineDependencies | None = None,
    preheat_fn: Callable[[str], object] | None = None,
) -> AutoRunResult:
    """Recover an interrupted publication or compute one new auto run."""
    trade_date = _validate_trade_date(trade_date)
    resolved_reports_dir = (
        Path(reports_dir)
        if reports_dir is not None
        else Path(__file__).resolve().parents[2] / "data" / "reports"
    )
    recovered = _reconcile_pending_run(resolved_reports_dir, trade_date)
    if recovered is not None:
        return recovered
    if preheat_fn is not None:
        preheat_fn(trade_date)
    run_id = _new_run_id(trade_date)
    if dependencies is None:
        if data_dir is None:
            raise ValueError("data_dir is required for default Auto dependencies")
        resolved_dependencies = _default_dependencies(
            resolved_reports_dir, Path(data_dir), run_id
        )
    else:
        resolved_dependencies = dependencies

    def readiness_publication() -> object | None:
        getter = resolved_dependencies.get_daily_readiness_publication
        return getter() if getter is not None else None
    payload: dict[str, Any] | None = None
    manifest: object | None = None
    pending_handle: _PendingStateHandle | None = None
    pending_attempt: Path | None = None
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
        if isinstance(inputs, AutoInputs):
            stage = "finalize_inputs"
            inputs = _finalize_inputs_after_compute(inputs, payload, run_id=run_id)
        stage = "build_manifest"
        manifest = resolved_dependencies.build_manifest(inputs, payload)
        manifest_run_id = _validate_run_id(getattr(manifest, "run_id", ""))
        if getattr(manifest, "is_healthy", None) is True:
            _publication_payload(payload, manifest, status=AutoRunStatus.HEALTHY)
            stage = "publish_pending_attempt"
            pending_handle = _publish_pending_attempt(
                resolved_reports_dir,
                trade_date,
                manifest_run_id,
                payload,
                manifest,
            )
            pending_attempt = pending_handle.path
            pending_state = _read_pending_json(pending_handle)
            _call_state_hook(
                resolved_dependencies.state_hook,
                "after_prepared_persist",
                pending_attempt,
                pending_state,
            )
            stage = "advance_pending"
            canonical, _final_state, pending_removed = _advance_pending_state(
                pending_handle,
                pending_state,
                update_tracking=resolved_dependencies.update_tracking,
                publish_canonical=lambda exact_payload: resolved_dependencies.publish_canonical(
                    exact_payload, manifest
                ),
                state_hook=resolved_dependencies.state_hook,
                runtime_payload=payload,
            )
            return AutoRunResult(
                AutoRunStatus.HEALTHY,
                0,
                canonical,
                payload,
                manifest,
                None if pending_removed else pending_attempt,
                False,
                (
                    {
                        "action": "pending_cleanup_failed",
                        "run_id": manifest_run_id,
                        "pending_path": str(pending_attempt),
                    },
                )
                if not pending_removed
                else (),
                effective_trade_date=trade_date,
                daily_action_readiness_publication=readiness_publication(),
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
            effective_trade_date=trade_date,
            daily_action_readiness_publication=readiness_publication(),
        )
    except Exception as exc:
        failure_run_id = str(getattr(manifest, "run_id", run_id))
        if pending_handle is not None:
            attempt = _record_pending_error(pending_handle, stage, exc)
        else:
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
            daily_action_readiness_publication=readiness_publication(),
        )
    finally:
        if pending_handle is not None:
            pending_handle.close()
