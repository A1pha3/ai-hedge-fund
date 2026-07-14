"""Daily Action readiness manifest: model, serialization, validation, publication.

Independent from Auto canonical. Published atomically as
data/reports/daily_action_readiness_YYYYMMDD.json. Failed runs write
daily_action_readiness_attempt_YYYYMMDD_RUNID.json instead.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from types import MappingProxyType

from src.screening.offensive.setup_data_contracts import (
    SETUP_REQUIREMENTS_VERSION,
    SetupCapability,
    evaluate_btst_capability,
    evaluate_oversold_bounce_capability,
)

logger = logging.getLogger(__name__)

DAILY_ACTION_READINESS_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class SharedReadinessEvidence:
    """Evidence shared across all tickers in the manifest."""

    regime_row: Mapping[str, object]
    regime_fingerprint: str | None
    industry_mapping_fingerprint: str | None
    security_status_fingerprint: str | None
    board_rule_version: str
    normalization_version: str
    signal_session_policy_version: str


@dataclass(frozen=True)
class DailyActionTickerReadiness:
    """Per-ticker readiness across all setups."""

    evidence_status: str  # "verified" | "blocked"
    capabilities: Mapping[str, SetupCapability]


@dataclass(frozen=True)
class DailyActionReadinessManifest:
    """Full-universe Daily Action readiness manifest."""

    schema_version: int
    domain: str  # always "daily_action"
    run_id: str
    trade_date: date
    created_at: str  # ISO timestamp
    status: str  # "healthy" | "degraded"
    universe_kind: str  # "resolved_refresh_universe"
    universe_tickers: tuple[str, ...]
    universe_fingerprint: str
    input_fingerprint: str | None
    ticker_readiness: Mapping[str, DailyActionTickerReadiness]
    warnings: tuple[str, ...]
    shared_evidence: SharedReadinessEvidence
    policy_versions: Mapping[str, str]

    @property
    def is_healthy(self) -> bool:
        """Manifest structural health (not 'all tickers tradeable')."""
        return (
            self.status == "healthy"
            and self.schema_version == DAILY_ACTION_READINESS_SCHEMA_VERSION
        )

    @property
    def scannable_count(self) -> int:
        return sum(
            1
            for tr in self.ticker_readiness.values()
            for cap in tr.capabilities.values()
            if cap.scannable
        )

    @property
    def plan_eligible_count(self) -> int:
        return sum(
            1
            for tr in self.ticker_readiness.values()
            for cap in tr.capabilities.values()
            if cap.plan_eligible
        )

    def to_dict(self) -> dict:
        return {
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
            "ticker_readiness": {
                ticker: {
                    "evidence_status": tr.evidence_status,
                    "capabilities": {
                        setup: {
                            "enabled": cap.enabled,
                            "scannable": cap.scannable,
                            "plan_eligible": cap.plan_eligible,
                            "degraded": cap.degraded,
                            "block_reasons": list(cap.block_reasons),
                            "warnings": list(cap.warnings),
                        }
                        for setup, cap in tr.capabilities.items()
                    },
                }
                for ticker, tr in self.ticker_readiness.items()
            },
            "warnings": list(self.warnings),
            "shared_evidence": {
                "regime_fingerprint": self.shared_evidence.regime_fingerprint,
                "industry_mapping_fingerprint": self.shared_evidence.industry_mapping_fingerprint,
                "security_status_fingerprint": self.shared_evidence.security_status_fingerprint,
                "board_rule_version": self.shared_evidence.board_rule_version,
                "normalization_version": self.shared_evidence.normalization_version,
                "signal_session_policy_version": self.shared_evidence.signal_session_policy_version,
            },
            "policy_versions": dict(self.policy_versions),
        }


@dataclass(frozen=True)
class DailyActionReadinessPublication:
    status: str  # "healthy" | "degraded" | "fatal"
    artifact_path: Path
    manifest: DailyActionReadinessManifest | None
    summary: Mapping[str, Mapping[str, int]]


def _outcome_warnings(outcome: object) -> tuple[str, ...]:
    """Best-effort extraction of warnings from a TickerRefreshOutcome-like object."""
    warnings = getattr(outcome, "warnings", None)
    if warnings is None and isinstance(outcome, Mapping):
        warnings = outcome.get("warnings", ())
    if warnings is None:
        return ()
    return tuple(warnings)


def build_ticker_readiness(
    outcomes: Mapping[str, object],  # DailyActionRefreshResult.outcomes
    *,
    oversold_bounce_enabled: bool = False,
    st_tickers: frozenset[str] | None = None,
) -> dict[str, DailyActionTickerReadiness]:
    """Build per-ticker readiness from refresh outcomes.

    outcomes: ticker -> TickerRefreshOutcome (from cache_readiness.py)
    """
    from src.screening.offensive.cache_readiness import PriceStatus

    st_set = st_tickers or frozenset()
    result: dict[str, DailyActionTickerReadiness] = {}

    for ticker, outcome in outcomes.items():
        price_status = (
            outcome.price_status.value
            if hasattr(outcome, "price_status")
            else str(outcome.get("price_status", ""))
        )
        fund_flow_status = (
            outcome.fund_flow_status.value
            if hasattr(outcome, "fund_flow_status")
            else str(outcome.get("fund_flow_status", ""))
        )
        price_history_days = (
            outcome.price_history_rows
            if hasattr(outcome, "price_history_rows")
            else int(outcome.get("price_history_rows", 0))
        )
        fund_flow_history_days = (
            outcome.fund_flow_history_rows
            if hasattr(outcome, "fund_flow_history_rows")
            else int(outcome.get("fund_flow_history_rows", 0))
        )

        is_suspended = price_status == PriceStatus.SUSPENDED.value
        is_st = ticker in st_set

        # Industry is current if outcome has no industry-related warnings
        outcome_warnings = _outcome_warnings(outcome)
        industry_current = not any("industry" in w for w in outcome_warnings)

        btst_cap = evaluate_btst_capability(
            price_status=price_status,
            price_history_days=price_history_days,
            fund_flow_status=fund_flow_status,
            fund_flow_history_days=fund_flow_history_days,
            industry_current=industry_current,
            is_suspended=is_suspended,
            is_st=is_st,
        )

        ob_cap = evaluate_oversold_bounce_capability(
            price_status=price_status,
            price_history_days=price_history_days,
            fund_flow_status=fund_flow_status,
            is_suspended=is_suspended,
            is_st=is_st,
            enabled=oversold_bounce_enabled,
        )

        evidence_status = (
            "verified" if btst_cap.scannable or ob_cap.scannable else "blocked"
        )
        if is_suspended or is_st:
            evidence_status = "blocked"

        result[ticker] = DailyActionTickerReadiness(
            evidence_status=evidence_status,
            capabilities=MappingProxyType(
                {"btst_breakout": btst_cap, "oversold_bounce": ob_cap}
            ),
        )

    return result


def build_daily_action_readiness(
    refresh_result: object,  # DailyActionRefreshResult
    shared_evidence: SharedReadinessEvidence,
    *,
    run_id: str,
    oversold_bounce_enabled: bool = False,
    st_tickers: frozenset[str] | None = None,
    warnings: tuple[str, ...] = (),
) -> DailyActionReadinessManifest:
    """Build manifest from refresh result and shared evidence."""
    ticker_readiness = build_ticker_readiness(
        refresh_result.outcomes,
        oversold_bounce_enabled=oversold_bounce_enabled,
        st_tickers=st_tickers,
    )

    return DailyActionReadinessManifest(
        schema_version=DAILY_ACTION_READINESS_SCHEMA_VERSION,
        domain="daily_action",
        run_id=run_id,
        trade_date=refresh_result.trade_date,
        created_at=datetime.now(UTC).replace(tzinfo=None).isoformat() + "Z",
        status="healthy",
        universe_kind="resolved_refresh_universe",
        universe_tickers=refresh_result.universe_tickers,
        universe_fingerprint=refresh_result.universe_fingerprint,
        input_fingerprint=refresh_result.daily_batch_fingerprint,
        ticker_readiness=MappingProxyType(ticker_readiness),
        warnings=warnings,
        shared_evidence=shared_evidence,
        policy_versions=MappingProxyType(
            {
                "readiness_policy": "daily-action-readiness-v1",
                "normalization": shared_evidence.normalization_version,
                "board_rule": shared_evidence.board_rule_version,
                "setup_requirements": SETUP_REQUIREMENTS_VERSION,
                "signal_session_cutoff": shared_evidence.signal_session_policy_version,
            }
        ),
    )


def validate_manifest(
    manifest_data: Mapping,
) -> DailyActionReadinessManifest | None:
    """Validate and deserialize a manifest from raw JSON mapping.

    Returns None if validation fails (unknown schema, wrong domain, etc).
    """
    try:
        schema_version = int(manifest_data.get("schema_version", 0))
        if schema_version != DAILY_ACTION_READINESS_SCHEMA_VERSION:
            logger.warning(
                "daily_action_readiness: unknown schema_version %s", schema_version
            )
            return None

        domain = manifest_data.get("domain", "")
        if domain != "daily_action":
            logger.warning("daily_action_readiness: wrong domain %s", domain)
            return None

        trade_date = date.fromisoformat(manifest_data["trade_date"])

        # Security: validate universe_tickers format to prevent path injection.
        # Tickers must be exactly 6 digits — no separators, no path traversal.
        universe_tickers_raw = manifest_data.get("universe_tickers", [])
        if not isinstance(universe_tickers_raw, list):
            raise ValueError("universe_tickers must be a list")
        for ticker in universe_tickers_raw:
            if not isinstance(ticker, str) or not ticker.isdigit() or len(ticker) != 6:
                raise ValueError(
                    f"universe_tickers contains invalid entry: {ticker!r} "
                    "(must be exactly 6 digits)"
                )
        # Check for duplicates
        if len(set(universe_tickers_raw)) != len(universe_tickers_raw):
            raise ValueError("universe_tickers contains duplicates")

        # Rebuild shared evidence
        se_raw = manifest_data.get("shared_evidence", {})
        shared_evidence = SharedReadinessEvidence(
            regime_row=MappingProxyType({}),
            regime_fingerprint=se_raw.get("regime_fingerprint"),
            industry_mapping_fingerprint=se_raw.get("industry_mapping_fingerprint"),
            security_status_fingerprint=se_raw.get("security_status_fingerprint"),
            board_rule_version=se_raw.get("board_rule_version", ""),
            normalization_version=se_raw.get("normalization_version", ""),
            signal_session_policy_version=se_raw.get(
                "signal_session_policy_version", ""
            ),
        )

        # Rebuild ticker readiness
        ticker_readiness: dict[str, DailyActionTickerReadiness] = {}
        for ticker, tr_raw in manifest_data.get("ticker_readiness", {}).items():
            caps: dict[str, SetupCapability] = {}
            for setup, cap_raw in tr_raw.get("capabilities", {}).items():
                caps[setup] = SetupCapability(
                    enabled=bool(cap_raw.get("enabled", False)),
                    scannable=bool(cap_raw.get("scannable", False)),
                    plan_eligible=bool(cap_raw.get("plan_eligible", False)),
                    degraded=bool(cap_raw.get("degraded", False)),
                    block_reasons=tuple(cap_raw.get("block_reasons", [])),
                    warnings=tuple(cap_raw.get("warnings", [])),
                )
            ticker_readiness[ticker] = DailyActionTickerReadiness(
                evidence_status=tr_raw.get("evidence_status", "blocked"),
                capabilities=MappingProxyType(caps),
            )

        return DailyActionReadinessManifest(
            schema_version=schema_version,
            domain=domain,
            run_id=manifest_data.get("run_id", ""),
            trade_date=trade_date,
            created_at=manifest_data.get("created_at", ""),
            status=manifest_data.get("status", ""),
            universe_kind=manifest_data.get("universe_kind", ""),
            universe_tickers=tuple(manifest_data.get("universe_tickers", [])),
            universe_fingerprint=manifest_data.get("universe_fingerprint", ""),
            input_fingerprint=manifest_data.get("input_fingerprint"),
            ticker_readiness=MappingProxyType(ticker_readiness),
            warnings=tuple(manifest_data.get("warnings", [])),
            shared_evidence=shared_evidence,
            policy_versions=MappingProxyType(manifest_data.get("policy_versions", {})),
        )
    except (KeyError, ValueError, TypeError) as exc:
        logger.warning("daily_action_readiness: validation failed: %s", exc)
        return None


def publish_daily_action_readiness(
    manifest: DailyActionReadinessManifest,
    reports_dir: Path,
) -> DailyActionReadinessPublication:
    """Atomically publish the readiness manifest.

    Uses tempfile + os.replace for atomicity. On success, writes
    daily_action_readiness_YYYYMMDD.json.
    """
    reports_dir = Path(reports_dir)
    reports_dir.mkdir(parents=True, exist_ok=True)

    filename = (
        f"daily_action_readiness_{manifest.trade_date.strftime('%Y%m%d')}.json"
    )
    target_path = reports_dir / filename

    payload = manifest.to_dict()

    # Atomic write: tempfile in same dir, then os.replace
    fd, tmp_path = tempfile.mkstemp(
        dir=str(reports_dir), prefix=".daily_readiness_", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(
                payload, f, ensure_ascii=False, allow_nan=False, sort_keys=True
            )
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, target_path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise

    # Build summary
    btst_scannable = sum(
        1
        for tr in manifest.ticker_readiness.values()
        if tr.capabilities.get("btst_breakout")
        and tr.capabilities["btst_breakout"].scannable
    )
    btst_eligible = sum(
        1
        for tr in manifest.ticker_readiness.values()
        if tr.capabilities.get("btst_breakout")
        and tr.capabilities["btst_breakout"].plan_eligible
    )

    summary = MappingProxyType(
        {
            "universe": MappingProxyType({"total": len(manifest.universe_tickers)}),
            "btst": MappingProxyType(
                {"scannable": btst_scannable, "plan_eligible": btst_eligible}
            ),
        }
    )

    return DailyActionReadinessPublication(
        status="healthy",
        artifact_path=target_path,
        manifest=manifest,
        summary=summary,
    )
