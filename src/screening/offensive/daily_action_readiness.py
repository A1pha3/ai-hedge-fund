"""Strict Daily Action readiness v2 model, parser, and publisher.

The manifest is independent from Auto scoring.  A canonical is replaced only
after every identity and capability invariant can be recomputed from the
serialized payload.  Any incomplete run is preserved as a unique attempt.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import re
import tempfile
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from pathlib import Path
from types import MappingProxyType, SimpleNamespace

from src.screening.offensive.cache_readiness import (
    DailyActionRefreshResult,
    SuspensionEvidenceStatus,
    universe_fingerprint,
)
from src.screening.offensive.pit_evidence import canonical_fingerprint
from src.screening.offensive.setup_data_contracts import (
    SETUP_CONTRACTS,
    SETUP_REQUIREMENTS_VERSION,
    SetupCapability,
    evaluate_btst_capability,
    evaluate_oversold_bounce_capability,
)
from src.utils.date_utils import SIGNAL_SESSION_POLICY_VERSION

logger = logging.getLogger(__name__)

DAILY_ACTION_READINESS_SCHEMA_VERSION = 2
READINESS_POLICY_VERSION = "daily-action-readiness-v2"
BOARD_RULE_VERSION = "ashare-board-prefix-v1"
NORMALIZATION_VERSION = "pit-canonical-v1"

_DOMAIN = "daily_action"
_UNIVERSE_KIND = "resolved_refresh_universe"
_RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_SECURITY_STATUSES = frozenset({"listed", "st"})
DAILY_ACTION_REGIMES = frozenset({"normal", "risk_off", "crisis"})
_EVIDENCE_STATUSES = frozenset({"verified", "blocked"})
_MANIFEST_STATUSES = frozenset({"healthy", "degraded"})
_POLICY_KEYS = frozenset(
    {
        "readiness_policy",
        "normalization",
        "board_rule",
        "setup_requirements",
        "signal_session_cutoff",
    }
)
_TOP_LEVEL_KEYS = frozenset(
    {
        "schema_version",
        "domain",
        "run_id",
        "trade_date",
        "created_at",
        "status",
        "universe_kind",
        "universe_tickers",
        "universe_fingerprint",
        "input_fingerprint",
        "suspension_evidence",
        "ticker_readiness",
        "warnings",
        "shared_evidence",
        "policy_versions",
        "content_fingerprint",
    }
)
_SHARED_KEYS = frozenset(
    {
        "as_of_date",
        "regime_row",
        "industry_by_ticker",
        "industry_day_pct",
        "security_status_by_ticker",
        "regime_fingerprint",
        "industry_fingerprint",
        "security_fingerprint",
        "evidence_fingerprint",
        "board_rule_version",
        "normalization_version",
        "signal_session_policy_version",
    }
)
_TICKER_READINESS_KEYS = frozenset({"evidence_status", "capabilities"})
_CAPABILITY_KEYS = frozenset(
    {
        "enabled",
        "scannable",
        "plan_eligible",
        "degraded",
        "block_reasons",
        "warnings",
        "consumed_fingerprint",
    }
)
_SUSPENSION_KEYS = frozenset({"status", "tickers", "source_fingerprint"})


class ManifestValidationError(ValueError):
    """Raised when a readiness payload cannot authorize Daily Action."""


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and _SHA256_RE.fullmatch(value) is not None


def _require_sha256(value: object, field_name: str) -> str:
    if not _is_sha256(value):
        raise ManifestValidationError(f"{field_name} must be a sha256 fingerprint")
    return value


def _validate_run_id(run_id: object) -> str:
    if not isinstance(run_id, str) or _RUN_ID_RE.fullmatch(run_id) is None:
        raise ManifestValidationError("run_id is empty or path-unsafe")
    return run_id


def _safe_attempt_run_id(run_id: object) -> str:
    """Sanitize an unvalidated run_id into a path-safe attempt token.

    The attempt/quarantine path must never fail open or crash on a corrupt
    manifest, so an unsafe run_id degrades to a constant safe token instead of
    raising. Valid run_ids pass through unchanged.
    """

    if isinstance(run_id, str) and _RUN_ID_RE.fullmatch(run_id) is not None:
        return run_id
    return "invalid-run-id"


def _require_exact_keys(
    raw: Mapping[str, object], expected: frozenset[str], scope: str
) -> None:
    keys = set(raw)
    if keys != expected:
        unknown = sorted(keys - expected)
        missing = sorted(expected - keys)
        details: list[str] = []
        if unknown:
            details.append(f"unknown fields={unknown}")
        if missing:
            details.append(f"missing fields={missing}")
        raise ManifestValidationError(f"{scope}: " + "; ".join(details))


def _require_mapping(value: object, field_name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise ManifestValidationError(f"{field_name} must be a string-keyed mapping")
    return value


def _require_str(value: object, field_name: str, *, nonempty: bool = True) -> str:
    if not isinstance(value, str) or (nonempty and not value):
        raise ManifestValidationError(f"{field_name} must be a non-empty string")
    return value


def _require_bool(raw: Mapping[str, object], key: str, *, scope: str) -> bool:
    value = raw.get(key)
    if type(value) is not bool:
        raise ManifestValidationError(f"{scope}.{key} must be bool")
    return value


def _require_string_list(value: object, field_name: str) -> tuple[str, ...]:
    if type(value) is not list or any(not isinstance(item, str) for item in value):
        raise ManifestValidationError(f"{field_name} must be a list of strings")
    return tuple(value)


def _validate_ticker(value: object, field_name: str = "ticker") -> str:
    if not isinstance(value, str) or len(value) != 6 or not value.isdigit():
        raise ManifestValidationError(f"{field_name} must be exactly six digits")
    return value


def _normalize_json(value: object, field_name: str) -> object:
    """Copy JSON-compatible evidence while rejecting coercions and non-finite data."""

    if value is None or type(value) in (str, bool, int):
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise ManifestValidationError(f"{field_name} must be finite JSON")
        return value
    if isinstance(value, Mapping):
        copied: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ManifestValidationError(f"{field_name} keys must be strings")
            copied[key] = _normalize_json(item, f"{field_name}.{key}")
        return MappingProxyType(copied)
    if type(value) in (list, tuple):
        return tuple(
            _normalize_json(item, f"{field_name}[{index}]")
            for index, item in enumerate(value)
        )
    raise ManifestValidationError(
        f"{field_name} contains unsupported type {type(value).__name__}"
    )


def _plain_json(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _plain_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_plain_json(item) for item in value]
    return value


def _fingerprint(value: object) -> str:
    try:
        encoded = json.dumps(
            _plain_json(value),
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ManifestValidationError("fingerprint input is not canonical JSON") from exc
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _expected_policy_versions(shared: SharedReadinessEvidence) -> dict[str, str]:
    return {
        "readiness_policy": READINESS_POLICY_VERSION,
        "normalization": shared.normalization_version,
        "board_rule": shared.board_rule_version,
        "setup_requirements": SETUP_REQUIREMENTS_VERSION,
        "signal_session_cutoff": shared.signal_session_policy_version,
    }


@dataclass(frozen=True)
class SharedReadinessEvidence:
    """Complete serialized shared evidence, with recomputable fingerprints."""

    as_of_date: date
    regime_row: Mapping[str, object]
    industry_by_ticker: Mapping[str, str]
    industry_day_pct: Mapping[str, float]
    security_status_by_ticker: Mapping[str, str]
    regime_fingerprint: str
    industry_fingerprint: str
    security_fingerprint: str
    board_rule_version: str
    normalization_version: str
    signal_session_policy_version: str
    evidence_fingerprint: str = ""

    def __post_init__(self) -> None:
        if type(self.as_of_date) is not date:
            raise ManifestValidationError("as_of_date must be an exact date")
        regime_raw = _require_mapping(self.regime_row, "regime_row")
        if set(regime_raw) != {"trade_date", "regime"}:
            raise ManifestValidationError(
                "regime_row must contain exactly trade_date and regime"
            )
        regime_row = _normalize_json(regime_raw, "regime_row")
        trade_date = regime_row.get("trade_date")
        if type(trade_date) is not str or trade_date != self.as_of_date.isoformat():
            raise ManifestValidationError("regime_row.trade_date must match as_of_date")
        regime = regime_row.get("regime")
        if type(regime) is not str or regime not in DAILY_ACTION_REGIMES:
            raise ManifestValidationError("regime_row.regime is unknown")

        industry_raw = _require_mapping(
            self.industry_by_ticker, "industry_by_ticker"
        )
        industry_by_ticker: dict[str, str] = {}
        for ticker, industry in industry_raw.items():
            ticker = _validate_ticker(ticker, "industry_by_ticker key")
            industry_by_ticker[ticker] = _require_str(
                industry, f"industry_by_ticker[{ticker}]"
            )

        pct_raw = _require_mapping(self.industry_day_pct, "industry_day_pct")
        industry_day_pct: dict[str, float] = {}
        for ticker, value in pct_raw.items():
            ticker = _validate_ticker(ticker, "industry_day_pct key")
            if isinstance(value, bool) or type(value) not in (int, float):
                raise ManifestValidationError(
                    f"industry_day_pct[{ticker}] must be a finite number"
                )
            normalized = float(value)
            if not math.isfinite(normalized):
                raise ManifestValidationError(
                    f"industry_day_pct[{ticker}] must be a finite number"
                )
            industry_day_pct[ticker] = normalized
        if not set(industry_day_pct).issubset(industry_by_ticker):
            raise ManifestValidationError(
                "industry_day_pct keys require industry_by_ticker identities"
            )

        security_raw = _require_mapping(
            self.security_status_by_ticker, "security_status_by_ticker"
        )
        security_status: dict[str, str] = {}
        for ticker, status in security_raw.items():
            ticker = _validate_ticker(ticker, "security_status_by_ticker key")
            if status not in _SECURITY_STATUSES:
                raise ManifestValidationError(
                    f"security_status_by_ticker[{ticker}] is unknown"
                )
            security_status[ticker] = status

        _require_str(self.board_rule_version, "board_rule_version")
        _require_str(self.normalization_version, "normalization_version")
        _require_str(
            self.signal_session_policy_version,
            "signal_session_policy_version",
        )
        if self.board_rule_version != BOARD_RULE_VERSION:
            raise ManifestValidationError("unknown board_rule_version")
        if self.normalization_version != NORMALIZATION_VERSION:
            raise ManifestValidationError("unknown normalization_version")
        if self.signal_session_policy_version != SIGNAL_SESSION_POLICY_VERSION:
            raise ManifestValidationError("unknown signal_session_policy_version")

        as_of = self.as_of_date.isoformat()
        expected_regime = _fingerprint(
            {"as_of_date": as_of, "regime_row": regime_row}
        )
        expected_industry = _fingerprint(
            {
                "as_of_date": as_of,
                "industry_by_ticker": industry_by_ticker,
                "industry_day_pct": industry_day_pct,
            }
        )
        expected_security = _fingerprint(
            {
                "as_of_date": as_of,
                "security_status_by_ticker": security_status,
            }
        )
        if self.regime_fingerprint != expected_regime:
            raise ManifestValidationError("regime_fingerprint mismatch")
        if self.industry_fingerprint != expected_industry:
            raise ManifestValidationError("industry_fingerprint mismatch")
        if self.security_fingerprint != expected_security:
            raise ManifestValidationError("security_fingerprint mismatch")

        object.__setattr__(self, "regime_row", regime_row)
        object.__setattr__(
            self, "industry_by_ticker", MappingProxyType(industry_by_ticker)
        )
        object.__setattr__(
            self, "industry_day_pct", MappingProxyType(industry_day_pct)
        )
        object.__setattr__(
            self,
            "security_status_by_ticker",
            MappingProxyType(security_status),
        )
        evidence_payload = self._payload(include_evidence_fingerprint=False)
        expected_evidence = _fingerprint(evidence_payload)
        if self.evidence_fingerprint and self.evidence_fingerprint != expected_evidence:
            raise ManifestValidationError("shared evidence_fingerprint mismatch")
        object.__setattr__(self, "evidence_fingerprint", expected_evidence)

    @property
    def industry_mapping_fingerprint(self) -> str:
        """Compatibility alias for pre-v2 readers."""

        return self.industry_fingerprint

    @property
    def security_status_fingerprint(self) -> str:
        """Compatibility alias for pre-v2 readers."""

        return self.security_fingerprint

    def _payload(self, *, include_evidence_fingerprint: bool) -> dict[str, object]:
        payload: dict[str, object] = {
            "as_of_date": self.as_of_date.isoformat(),
            "regime_row": _plain_json(self.regime_row),
            "industry_by_ticker": dict(self.industry_by_ticker),
            "industry_day_pct": dict(self.industry_day_pct),
            "security_status_by_ticker": dict(self.security_status_by_ticker),
            "regime_fingerprint": self.regime_fingerprint,
            "industry_fingerprint": self.industry_fingerprint,
            "security_fingerprint": self.security_fingerprint,
            "board_rule_version": self.board_rule_version,
            "normalization_version": self.normalization_version,
            "signal_session_policy_version": self.signal_session_policy_version,
        }
        if include_evidence_fingerprint:
            payload["evidence_fingerprint"] = self.evidence_fingerprint
        return payload

    def to_dict(self) -> dict[str, object]:
        return self._payload(include_evidence_fingerprint=True)


@dataclass(frozen=True)
class SuspensionReadinessEvidence:
    status: str
    tickers: tuple[str, ...]
    source_fingerprint: str

    def __post_init__(self) -> None:
        if self.status not in {
            SuspensionEvidenceStatus.AVAILABLE_EMPTY.value,
            SuspensionEvidenceStatus.AVAILABLE_NONEMPTY.value,
        }:
            raise ManifestValidationError("suspension evidence is unavailable")
        tickers = tuple(self.tickers)
        if tickers != tuple(sorted(tickers)):
            raise ManifestValidationError("suspension tickers must be sorted")
        if len(set(tickers)) != len(tickers):
            raise ManifestValidationError("suspension tickers contain duplicates")
        for ticker in tickers:
            _validate_ticker(ticker, "suspension ticker")
        if self.status == SuspensionEvidenceStatus.AVAILABLE_EMPTY.value and tickers:
            raise ManifestValidationError("available_empty suspension must be empty")
        if self.status == SuspensionEvidenceStatus.AVAILABLE_NONEMPTY.value and not tickers:
            raise ManifestValidationError("available_nonempty suspension needs tickers")
        _require_sha256(self.source_fingerprint, "suspension source_fingerprint")
        object.__setattr__(self, "tickers", tickers)

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "tickers": list(self.tickers),
            "source_fingerprint": self.source_fingerprint,
        }


@dataclass(frozen=True)
class DailyActionTickerReadiness:
    evidence_status: str
    capabilities: Mapping[str, SetupCapability]

    def __post_init__(self) -> None:
        if self.evidence_status not in _EVIDENCE_STATUSES:
            raise ManifestValidationError("unknown ticker evidence_status")
        if not isinstance(self.capabilities, Mapping):
            raise ManifestValidationError("capabilities must be a mapping")
        copied = dict(self.capabilities)
        if set(copied) != set(SETUP_CONTRACTS):
            raise ManifestValidationError("capabilities must exactly cover known setups")
        if any(type(capability) is not SetupCapability for capability in copied.values()):
            raise ManifestValidationError("capabilities contain an invalid value")
        expected_status = (
            "verified" if any(cap.scannable for cap in copied.values()) else "blocked"
        )
        if self.evidence_status != expected_status:
            raise ManifestValidationError("ticker evidence_status contradicts capabilities")
        object.__setattr__(self, "capabilities", MappingProxyType(copied))


@dataclass(frozen=True)
class DailyActionReadinessManifest:
    schema_version: int
    domain: str
    run_id: str
    trade_date: date
    created_at: str
    status: str
    universe_kind: str
    universe_tickers: tuple[str, ...]
    universe_fingerprint: str
    input_fingerprint: str
    suspension_evidence: SuspensionReadinessEvidence
    ticker_readiness: Mapping[str, DailyActionTickerReadiness]
    warnings: tuple[str, ...]
    shared_evidence: SharedReadinessEvidence
    policy_versions: Mapping[str, str]
    content_fingerprint: str

    @property
    def is_healthy(self) -> bool:
        return (
            self.status == "healthy"
            and self.schema_version == DAILY_ACTION_READINESS_SCHEMA_VERSION
        )

    @property
    def scannable_count(self) -> int:
        return sum(
            cap.scannable
            for readiness in self.ticker_readiness.values()
            for cap in readiness.capabilities.values()
        )

    @property
    def plan_eligible_count(self) -> int:
        return sum(
            cap.plan_eligible
            for readiness in self.ticker_readiness.values()
            for cap in readiness.capabilities.values()
        )

    def to_dict(self, *, include_content_fingerprint: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "domain": self.domain,
            "run_id": self.run_id,
            "trade_date": self.trade_date.isoformat(),
            "created_at": self.created_at,
            "status": self.status,
            "universe_kind": self.universe_kind,
            "universe_tickers": list(self.universe_tickers),
            "universe_fingerprint": self.universe_fingerprint,
            "input_fingerprint": self.input_fingerprint,
            "suspension_evidence": self.suspension_evidence.to_dict(),
            "ticker_readiness": {
                ticker: {
                    "evidence_status": readiness.evidence_status,
                    "capabilities": {
                        setup: {
                            "enabled": capability.enabled,
                            "scannable": capability.scannable,
                            "plan_eligible": capability.plan_eligible,
                            "degraded": capability.degraded,
                            "block_reasons": list(capability.block_reasons),
                            "warnings": list(capability.warnings),
                            "consumed_fingerprint": capability.consumed_fingerprint,
                        }
                        for setup, capability in readiness.capabilities.items()
                    },
                }
                for ticker, readiness in self.ticker_readiness.items()
            },
            "warnings": list(self.warnings),
            "shared_evidence": self.shared_evidence.to_dict(),
            "policy_versions": dict(self.policy_versions),
        }
        if include_content_fingerprint:
            payload["content_fingerprint"] = self.content_fingerprint
        return payload


@dataclass(frozen=True)
class DailyActionReadinessPublication:
    status: str
    artifact_path: Path
    manifest: DailyActionReadinessManifest | None
    summary: Mapping[str, Mapping[str, int]]


def _setup_consumed_fingerprint(
    *,
    ticker: str,
    setup_name: str,
    outcome: object,
    trade_date: date,
    shared_evidence: SharedReadinessEvidence | None,
    suspension_evidence: SuspensionReadinessEvidence | None,
) -> str | None:
    if shared_evidence is None or suspension_evidence is None:
        return None
    evidence = getattr(outcome, "evidence_fingerprints", {})
    if not isinstance(evidence, Mapping):
        return None
    price_fingerprint = evidence.get("price")
    flow_fingerprint = evidence.get("fund_flow")
    if not _is_sha256(price_fingerprint) or not _is_sha256(flow_fingerprint):
        return None
    if shared_evidence.security_status_by_ticker.get(ticker) != "listed":
        return None
    if setup_name == "btst_breakout" and (
        ticker not in shared_evidence.industry_by_ticker
        or ticker not in shared_evidence.industry_day_pct
    ):
        return None
    payload = {
        "ticker": ticker,
        "setup": setup_name,
        "trade_date": trade_date.isoformat(),
        "price_fingerprint": price_fingerprint,
        "fund_flow_fingerprint": flow_fingerprint,
        "regime_fingerprint": shared_evidence.regime_fingerprint,
        "industry_fingerprint": (
            shared_evidence.industry_fingerprint
            if setup_name == "btst_breakout"
            else None
        ),
        "security_fingerprint": shared_evidence.security_fingerprint,
        "suspension_fingerprint": suspension_evidence.source_fingerprint,
        "board_rule_version": shared_evidence.board_rule_version,
        "normalization_version": shared_evidence.normalization_version,
        "setup_requirements_version": SETUP_REQUIREMENTS_VERSION,
        "signal_session_policy_version": shared_evidence.signal_session_policy_version,
    }
    return _fingerprint(payload)


def recompute_setup_consumed_fingerprint(
    *,
    ticker: str,
    setup_name: str,
    price_fingerprint: str | None,
    flow_fingerprint: str | None,
    trade_date: date,
    shared_evidence: SharedReadinessEvidence,
    suspension_evidence: SuspensionReadinessEvidence,
) -> str | None:
    """Recompute a setup's consumed fingerprint from explicit PIT fingerprints.

    The verified-snapshot loader calls this with fingerprints recomputed from the
    on-disk caches so it can compare against the manifest's authorized value using
    the exact same algorithm the manifest builder used.
    """

    outcome = SimpleNamespace(
        evidence_fingerprints={
            "price": price_fingerprint,
            "fund_flow": flow_fingerprint,
        }
    )
    return _setup_consumed_fingerprint(
        ticker=ticker,
        setup_name=setup_name,
        outcome=outcome,
        trade_date=trade_date,
        shared_evidence=shared_evidence,
        suspension_evidence=suspension_evidence,
    )


def build_ticker_readiness(
    outcomes: Mapping[str, object],
    *,
    trade_date: date | None = None,
    shared_evidence: SharedReadinessEvidence | None = None,
    suspension_evidence: SuspensionReadinessEvidence | None = None,
    oversold_bounce_enabled: bool = False,
    st_tickers: frozenset[str] | None = None,
) -> dict[str, DailyActionTickerReadiness]:
    """Build capabilities without inventing evidence absent from the refresh."""

    from src.screening.offensive.cache_readiness import PriceStatus

    effective_date = trade_date or date.min
    result: dict[str, DailyActionTickerReadiness] = {}
    compatibility_st = st_tickers or frozenset()
    for ticker, outcome in outcomes.items():
        _validate_ticker(ticker)
        price_status = getattr(getattr(outcome, "price_status", None), "value", None)
        fund_flow_status = getattr(
            getattr(outcome, "fund_flow_status", None), "value", None
        )
        price_rows = getattr(outcome, "price_history_rows", 0)
        flow_rows = getattr(outcome, "fund_flow_history_rows", 0)
        if type(price_rows) is not int or type(flow_rows) is not int:
            raise ManifestValidationError("refresh history rows must be integers")
        is_suspended = price_status == PriceStatus.SUSPENDED.value
        security_status = (
            shared_evidence.security_status_by_ticker.get(ticker)
            if shared_evidence is not None
            else None
        )
        is_st = security_status == "st" or ticker in compatibility_st
        industry_current = (
            shared_evidence is not None
            and ticker in shared_evidence.industry_by_ticker
            and ticker in shared_evidence.industry_day_pct
        )
        btst_consumed = _setup_consumed_fingerprint(
            ticker=ticker,
            setup_name="btst_breakout",
            outcome=outcome,
            trade_date=effective_date,
            shared_evidence=shared_evidence,
            suspension_evidence=suspension_evidence,
        )
        ob_consumed = _setup_consumed_fingerprint(
            ticker=ticker,
            setup_name="oversold_bounce",
            outcome=outcome,
            trade_date=effective_date,
            shared_evidence=shared_evidence,
            suspension_evidence=suspension_evidence,
        )
        btst = evaluate_btst_capability(
            price_status=str(price_status or "failed"),
            price_history_days=price_rows,
            fund_flow_status=str(fund_flow_status or "failed"),
            fund_flow_history_days=flow_rows,
            industry_current=industry_current,
            is_suspended=is_suspended,
            is_st=is_st,
            consumed_fingerprint=btst_consumed,
        )
        oversold = evaluate_oversold_bounce_capability(
            price_status=str(price_status or "failed"),
            price_history_days=price_rows,
            fund_flow_status=str(fund_flow_status or "failed"),
            is_suspended=is_suspended,
            is_st=is_st,
            enabled=oversold_bounce_enabled,
            consumed_fingerprint=ob_consumed,
        )
        capabilities = {
            "btst_breakout": btst,
            "oversold_bounce": oversold,
        }
        result[ticker] = DailyActionTickerReadiness(
            evidence_status=(
                "verified" if any(cap.scannable for cap in capabilities.values()) else "blocked"
            ),
            capabilities=capabilities,
        )
    return result


def _suspension_from_refresh(
    refresh_result: DailyActionRefreshResult,
) -> SuspensionReadinessEvidence:
    evidence = refresh_result.suspension_evidence
    if evidence.source_fingerprint is None:
        raise ManifestValidationError("suspension source_fingerprint is required")
    serialized = SuspensionReadinessEvidence(
        status=evidence.status.value,
        tickers=tuple(sorted(evidence.tickers)),
        source_fingerprint=evidence.source_fingerprint,
    )
    rows = (
        []
        if not serialized.tickers
        else [
            {"date": refresh_result.trade_date.isoformat(), "ticker": ticker}
            for ticker in serialized.tickers
        ]
    )
    expected = canonical_fingerprint("suspension", "*", rows)
    if serialized.source_fingerprint != expected:
        raise ManifestValidationError("suspension source_fingerprint mismatch")
    return serialized


def build_daily_action_readiness(
    refresh_result: DailyActionRefreshResult,
    shared_evidence: SharedReadinessEvidence,
    *,
    run_id: str,
    oversold_bounce_enabled: bool = False,
    st_tickers: frozenset[str] | None = None,
    warnings: tuple[str, ...] = (),
) -> DailyActionReadinessManifest:
    """Build and self-validate v2 from the exact frozen refresh result."""

    if type(refresh_result) is not DailyActionRefreshResult:
        raise ManifestValidationError(
            "readiness build requires exact DailyActionRefreshResult"
        )
    if type(shared_evidence) is not SharedReadinessEvidence:
        raise ManifestValidationError(
            "readiness build requires exact SharedReadinessEvidence"
        )
    if shared_evidence.as_of_date != refresh_result.trade_date:
        raise ManifestValidationError("shared evidence date mismatch")
    _validate_run_id(run_id)
    universe = tuple(refresh_result.universe_tickers)
    if not universe:
        raise ManifestValidationError("universe_tickers must not be empty")
    if universe != tuple(sorted(universe)):
        raise ManifestValidationError("universe_tickers must be sorted")
    if refresh_result.universe_fingerprint != universe_fingerprint(universe):
        raise ManifestValidationError("universe_fingerprint mismatch")
    input_fingerprint = _require_sha256(
        refresh_result.daily_batch_fingerprint,
        "input_fingerprint",
    )
    if set(shared_evidence.security_status_by_ticker) != set(universe):
        raise ManifestValidationError(
            "security_status_by_ticker must exactly cover universe"
        )
    evidence_tickers = (
        set(shared_evidence.industry_by_ticker)
        | set(shared_evidence.industry_day_pct)
        | set(shared_evidence.security_status_by_ticker)
    )
    if not evidence_tickers.issubset(universe):
        raise ManifestValidationError("shared evidence contains ticker outside universe")
    suspension = _suspension_from_refresh(refresh_result)
    if not set(suspension.tickers).issubset(universe):
        raise ManifestValidationError("suspension evidence contains ticker outside universe")
    policies = _expected_policy_versions(shared_evidence)
    readiness = build_ticker_readiness(
        refresh_result.outcomes,
        trade_date=refresh_result.trade_date,
        shared_evidence=shared_evidence,
        suspension_evidence=suspension,
        oversold_bounce_enabled=oversold_bounce_enabled,
        st_tickers=st_tickers,
    )
    if not isinstance(warnings, (list, tuple)) or any(
        not isinstance(warning, str) for warning in warnings
    ):
        raise ManifestValidationError("warnings must contain only strings")
    provisional = DailyActionReadinessManifest(
        schema_version=DAILY_ACTION_READINESS_SCHEMA_VERSION,
        domain=_DOMAIN,
        run_id=run_id,
        trade_date=refresh_result.trade_date,
        created_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        status="healthy",
        universe_kind=_UNIVERSE_KIND,
        universe_tickers=universe,
        universe_fingerprint=refresh_result.universe_fingerprint,
        input_fingerprint=input_fingerprint,
        suspension_evidence=suspension,
        ticker_readiness=MappingProxyType(readiness),
        warnings=tuple(warnings),
        shared_evidence=shared_evidence,
        policy_versions=MappingProxyType(policies),
        content_fingerprint="",
    )
    content_fingerprint = _fingerprint(
        provisional.to_dict(include_content_fingerprint=False)
    )
    return parse_manifest_v2(
        replace(provisional, content_fingerprint=content_fingerprint).to_dict()
    )


def _parse_created_at(value: object) -> str:
    text = _require_str(value, "created_at")
    if not text.endswith("Z"):
        raise ManifestValidationError("created_at must be UTC with Z suffix")
    try:
        parsed = datetime.fromisoformat(text.removesuffix("Z") + "+00:00")
    except ValueError as exc:
        raise ManifestValidationError("created_at must be an ISO timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        raise ManifestValidationError("created_at must be UTC")
    return text


def _parse_shared_evidence(raw_value: object) -> SharedReadinessEvidence:
    raw = _require_mapping(raw_value, "shared_evidence")
    _require_exact_keys(raw, _SHARED_KEYS, "shared_evidence")
    as_of_text = _require_str(raw["as_of_date"], "shared_evidence.as_of_date")
    try:
        as_of_date = date.fromisoformat(as_of_text)
    except ValueError as exc:
        raise ManifestValidationError(
            "shared_evidence.as_of_date must be ISO date"
        ) from exc
    if as_of_date.isoformat() != as_of_text:
        raise ManifestValidationError(
            "shared_evidence.as_of_date must be canonical ISO date"
        )
    return SharedReadinessEvidence(
        as_of_date=as_of_date,
        regime_row=_require_mapping(raw["regime_row"], "regime_row"),
        industry_by_ticker=_require_mapping(
            raw["industry_by_ticker"], "industry_by_ticker"
        ),
        industry_day_pct=_require_mapping(
            raw["industry_day_pct"], "industry_day_pct"
        ),
        security_status_by_ticker=_require_mapping(
            raw["security_status_by_ticker"], "security_status_by_ticker"
        ),
        regime_fingerprint=_require_str(
            raw["regime_fingerprint"], "regime_fingerprint"
        ),
        industry_fingerprint=_require_str(
            raw["industry_fingerprint"], "industry_fingerprint"
        ),
        security_fingerprint=_require_str(
            raw["security_fingerprint"], "security_fingerprint"
        ),
        board_rule_version=_require_str(
            raw["board_rule_version"], "board_rule_version"
        ),
        normalization_version=_require_str(
            raw["normalization_version"], "normalization_version"
        ),
        signal_session_policy_version=_require_str(
            raw["signal_session_policy_version"],
            "signal_session_policy_version",
        ),
        evidence_fingerprint=_require_str(
            raw["evidence_fingerprint"], "evidence_fingerprint"
        ),
    )


def _parse_suspension(
    raw_value: object, *, trade_date: date, universe: tuple[str, ...]
) -> SuspensionReadinessEvidence:
    raw = _require_mapping(raw_value, "suspension_evidence")
    _require_exact_keys(raw, _SUSPENSION_KEYS, "suspension_evidence")
    tickers = _require_string_list(raw["tickers"], "suspension_evidence.tickers")
    evidence = SuspensionReadinessEvidence(
        status=_require_str(raw["status"], "suspension_evidence.status"),
        tickers=tickers,
        source_fingerprint=_require_str(
            raw["source_fingerprint"], "suspension_evidence.source_fingerprint"
        ),
    )
    if not set(evidence.tickers).issubset(universe):
        raise ManifestValidationError("suspension tickers must be within universe")
    rows = (
        []
        if not evidence.tickers
        else [
            {"date": trade_date.isoformat(), "ticker": ticker}
            for ticker in evidence.tickers
        ]
    )
    if evidence.source_fingerprint != canonical_fingerprint(
        "suspension", "*", rows
    ):
        raise ManifestValidationError("suspension source_fingerprint mismatch")
    return evidence


def _parse_capability(
    raw_value: object, *, ticker: str, setup_name: str
) -> SetupCapability:
    raw = _require_mapping(raw_value, f"{ticker}.{setup_name}")
    _require_exact_keys(raw, _CAPABILITY_KEYS, f"{ticker}.{setup_name}")
    consumed_raw = raw["consumed_fingerprint"]
    if consumed_raw is not None and not isinstance(consumed_raw, str):
        raise ManifestValidationError(
            f"{ticker}.{setup_name}.consumed_fingerprint must be string or null"
        )
    try:
        return SetupCapability(
            enabled=_require_bool(raw, "enabled", scope=f"{ticker}.{setup_name}"),
            scannable=_require_bool(
                raw, "scannable", scope=f"{ticker}.{setup_name}"
            ),
            plan_eligible=_require_bool(
                raw, "plan_eligible", scope=f"{ticker}.{setup_name}"
            ),
            degraded=_require_bool(
                raw, "degraded", scope=f"{ticker}.{setup_name}"
            ),
            block_reasons=_require_string_list(
                raw["block_reasons"], f"{ticker}.{setup_name}.block_reasons"
            ),
            warnings=_require_string_list(
                raw["warnings"], f"{ticker}.{setup_name}.warnings"
            ),
            consumed_fingerprint=consumed_raw,
        )
    except ValueError as exc:
        raise ManifestValidationError(
            f"{ticker}.{setup_name} plan_eligible capability invariant failed: {exc}"
        ) from exc


def parse_manifest_v2(
    raw_value: Mapping[str, object],
) -> DailyActionReadinessManifest:
    """Strictly parse, copy, and recompute a readiness v2 manifest."""

    raw = _require_mapping(raw_value, "manifest")
    _require_exact_keys(raw, _TOP_LEVEL_KEYS, "manifest")
    if type(raw["schema_version"]) is not int:
        raise ManifestValidationError("schema_version must be int")
    if raw["schema_version"] != DAILY_ACTION_READINESS_SCHEMA_VERSION:
        raise ManifestValidationError("unknown schema_version")
    if raw["domain"] != _DOMAIN:
        raise ManifestValidationError("domain must be daily_action")
    run_id = _validate_run_id(raw["run_id"])
    trade_date_text = _require_str(raw["trade_date"], "trade_date")
    try:
        trade_date_value = date.fromisoformat(trade_date_text)
    except ValueError as exc:
        raise ManifestValidationError("trade_date must be ISO date") from exc
    if trade_date_value.isoformat() != trade_date_text:
        raise ManifestValidationError("trade_date must be canonical ISO date")
    created_at = _parse_created_at(raw["created_at"])
    status = _require_str(raw["status"], "status")
    if status not in _MANIFEST_STATUSES:
        raise ManifestValidationError("unknown manifest status")
    if raw["universe_kind"] != _UNIVERSE_KIND:
        raise ManifestValidationError("unknown universe_kind")

    universe_raw = raw["universe_tickers"]
    if type(universe_raw) is not list:
        raise ManifestValidationError("universe_tickers must be a list")
    universe = tuple(
        _validate_ticker(ticker, "universe ticker") for ticker in universe_raw
    )
    if not universe:
        raise ManifestValidationError("universe_tickers must not be empty")
    if len(set(universe)) != len(universe):
        raise ManifestValidationError("universe_tickers contains duplicates")
    if universe != tuple(sorted(universe)):
        raise ManifestValidationError("universe_tickers must be sorted")
    claimed_universe = _require_sha256(
        raw["universe_fingerprint"], "universe_fingerprint"
    )
    if universe_fingerprint(universe) != claimed_universe:
        raise ManifestValidationError("universe_fingerprint mismatch")
    input_fingerprint = _require_sha256(raw["input_fingerprint"], "input_fingerprint")

    shared = _parse_shared_evidence(raw["shared_evidence"])
    if shared.as_of_date != trade_date_value:
        raise ManifestValidationError("shared evidence date mismatch")
    if set(shared.security_status_by_ticker) != set(universe):
        raise ManifestValidationError(
            "security_status_by_ticker must exactly cover universe"
        )
    shared_tickers = (
        set(shared.industry_by_ticker)
        | set(shared.industry_day_pct)
        | set(shared.security_status_by_ticker)
    )
    if not shared_tickers.issubset(universe):
        raise ManifestValidationError("shared evidence contains ticker outside universe")
    suspension = _parse_suspension(
        raw["suspension_evidence"],
        trade_date=trade_date_value,
        universe=universe,
    )

    policies_raw = _require_mapping(raw["policy_versions"], "policy_versions")
    _require_exact_keys(policies_raw, _POLICY_KEYS, "policy_versions")
    policies: dict[str, str] = {
        key: _require_str(value, f"policy_versions.{key}")
        for key, value in policies_raw.items()
    }
    expected_policies = _expected_policy_versions(shared)
    for key, expected in expected_policies.items():
        if policies.get(key) != expected:
            raise ManifestValidationError(f"unknown policy_versions.{key}")

    readiness_raw = _require_mapping(raw["ticker_readiness"], "ticker_readiness")
    if set(readiness_raw) != set(universe):
        raise ManifestValidationError("ticker_readiness must exactly cover universe")
    readiness: dict[str, DailyActionTickerReadiness] = {}
    for ticker in universe:
        ticker_raw = _require_mapping(readiness_raw[ticker], f"ticker_readiness.{ticker}")
        _require_exact_keys(
            ticker_raw, _TICKER_READINESS_KEYS, f"ticker_readiness.{ticker}"
        )
        capabilities_raw = _require_mapping(
            ticker_raw["capabilities"], f"{ticker}.capabilities"
        )
        if set(capabilities_raw) != set(SETUP_CONTRACTS):
            raise ManifestValidationError(
                f"{ticker}.capabilities must exactly cover known setups"
            )
        capabilities = {
            setup_name: _parse_capability(
                capabilities_raw[setup_name],
                ticker=ticker,
                setup_name=setup_name,
            )
            for setup_name in SETUP_CONTRACTS
        }
        readiness[ticker] = DailyActionTickerReadiness(
            evidence_status=_require_str(
                ticker_raw["evidence_status"], f"{ticker}.evidence_status"
            ),
            capabilities=capabilities,
        )

    warnings = _require_string_list(raw["warnings"], "warnings")
    claimed_content = _require_sha256(
        raw["content_fingerprint"], "content_fingerprint"
    )
    unsigned = {key: value for key, value in raw.items() if key != "content_fingerprint"}
    if _fingerprint(unsigned) != claimed_content:
        raise ManifestValidationError("content_fingerprint mismatch")

    return DailyActionReadinessManifest(
        schema_version=DAILY_ACTION_READINESS_SCHEMA_VERSION,
        domain=_DOMAIN,
        run_id=run_id,
        trade_date=trade_date_value,
        created_at=created_at,
        status=status,
        universe_kind=_UNIVERSE_KIND,
        universe_tickers=universe,
        universe_fingerprint=claimed_universe,
        input_fingerprint=input_fingerprint,
        suspension_evidence=suspension,
        ticker_readiness=MappingProxyType(readiness),
        warnings=warnings,
        shared_evidence=shared,
        policy_versions=MappingProxyType(policies),
        content_fingerprint=claimed_content,
    )


def validate_manifest(
    manifest_data: Mapping[str, object],
) -> DailyActionReadinessManifest | None:
    """Compatibility wrapper for loaders that use ``None`` as fail-closed."""

    try:
        return parse_manifest_v2(manifest_data)
    except (ManifestValidationError, TypeError, ValueError) as exc:
        logger.warning("daily_action_readiness: validation failed: %s", exc)
        return None


def new_readiness_run_id(refresh_result: DailyActionRefreshResult) -> str:
    """Create one path-safe run identity bound to the frozen refresh identity."""

    seed = (
        f"{refresh_result.trade_date.isoformat()}|"
        f"{refresh_result.universe_fingerprint}|"
        f"{refresh_result.daily_batch_fingerprint}|{uuid.uuid4().hex}"
    )
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:32]


def _publication_summary(
    manifest: DailyActionReadinessManifest,
) -> Mapping[str, Mapping[str, int]]:
    return MappingProxyType(
        {
            "universe": MappingProxyType({"total": len(manifest.universe_tickers)}),
            "btst": MappingProxyType(
                {
                    "scannable": sum(
                        readiness.capabilities["btst_breakout"].scannable
                        for readiness in manifest.ticker_readiness.values()
                    ),
                    "plan_eligible": sum(
                        readiness.capabilities["btst_breakout"].plan_eligible
                        for readiness in manifest.ticker_readiness.values()
                    ),
                }
            ),
        }
    )


def _write_json_temp(payload: Mapping[str, object], directory: Path) -> str:
    fd, tmp_path = tempfile.mkstemp(
        dir=str(directory), prefix=".daily_readiness_", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(
                payload,
                handle,
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
    return tmp_path


def _atomic_replace_json(
    payload: Mapping[str, object], target: Path
) -> None:
    tmp_path = _write_json_temp(payload, target.parent)
    try:
        os.replace(tmp_path, target)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _atomic_unique_json(
    payload: Mapping[str, object], target: Path
) -> Path:
    """Atomically publish a complete attempt without replacing an older one."""

    tmp_path = _write_json_temp(payload, target.parent)
    try:
        candidate = target
        suffix = 0
        while True:
            try:
                os.link(tmp_path, candidate)
                return candidate
            except FileExistsError:
                suffix += 1
                candidate = target.with_name(f"{target.stem}_{suffix}{target.suffix}")
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def publish_daily_action_attempt(
    *,
    trade_date: date,
    run_id: str,
    reports_dir: Path,
    reasons: tuple[str, ...],
    status: str = "degraded",
) -> DailyActionReadinessPublication:
    """Publish a unique non-authorizing attempt and preserve the canonical."""

    if type(trade_date) is not date:
        raise ManifestValidationError("trade_date must be a date")
    run_id = _validate_run_id(run_id)
    if not isinstance(reasons, (list, tuple)) or not reasons or any(
        not isinstance(reason, str) or not reason for reason in reasons
    ):
        raise ManifestValidationError("attempt reasons must be non-empty strings")
    if status not in {"degraded", "fatal"}:
        raise ManifestValidationError("attempt status must be degraded or fatal")
    reports_dir = Path(reports_dir)
    reports_dir.mkdir(parents=True, exist_ok=True)
    payload: dict[str, object] = {
        "schema_version": DAILY_ACTION_READINESS_SCHEMA_VERSION,
        "domain": _DOMAIN,
        "run_id": run_id,
        "trade_date": trade_date.isoformat(),
        "created_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "status": status,
        "reasons": list(reasons),
    }
    payload["content_fingerprint"] = _fingerprint(payload)
    base = reports_dir / (
        f"daily_action_readiness_attempt_{trade_date.strftime('%Y%m%d')}_{run_id}.json"
    )
    artifact_path = _atomic_unique_json(payload, base)
    return DailyActionReadinessPublication(
        status=status,
        artifact_path=artifact_path,
        manifest=None,
        summary=MappingProxyType({}),
    )


def publish_daily_action_readiness(
    manifest: DailyActionReadinessManifest,
    reports_dir: Path,
    *,
    attempt_reason: str | None = None,
) -> DailyActionReadinessPublication:
    """Publish only a fully revalidated healthy canonical."""

    if type(manifest) is not DailyActionReadinessManifest:
        raise ManifestValidationError(
            "publication requires exact DailyActionReadinessManifest"
        )
    reports_dir = Path(reports_dir)
    reports_dir.mkdir(parents=True, exist_ok=True)
    if attempt_reason is not None:
        return publish_daily_action_attempt(
            trade_date=manifest.trade_date,
            run_id=_safe_attempt_run_id(manifest.run_id),
            reports_dir=reports_dir,
            reasons=(attempt_reason,),
        )
    try:
        validated = parse_manifest_v2(manifest.to_dict())
    except ManifestValidationError as exc:
        return publish_daily_action_attempt(
            trade_date=manifest.trade_date,
            run_id=_safe_attempt_run_id(manifest.run_id),
            reports_dir=reports_dir,
            reasons=(f"manifest_validation_failed:{exc}",),
        )
    if not validated.is_healthy:
        return publish_daily_action_attempt(
            trade_date=validated.trade_date,
            run_id=validated.run_id,
            reports_dir=reports_dir,
            reasons=("manifest_not_healthy",),
        )
    target = reports_dir / (
        f"daily_action_readiness_{validated.trade_date.strftime('%Y%m%d')}.json"
    )
    try:
        _atomic_replace_json(validated.to_dict(), target)
    except OSError as exc:
        logger.error("daily readiness canonical replace failed: %s", exc)
        return publish_daily_action_attempt(
            trade_date=validated.trade_date,
            run_id=validated.run_id,
            reports_dir=reports_dir,
            reasons=("canonical_replace_failed",),
            status="fatal",
        )
    return DailyActionReadinessPublication(
        status="healthy",
        artifact_path=target,
        manifest=validated,
        summary=_publication_summary(validated),
    )
