"""Mutually exclusive per-ticker cache refresh outcomes and universe conservation.

Replaces the flat counter model where a single stock could be counted in
multiple overlapping categories. Each ticker gets exactly one price status
and one fund-flow status; all statuses must sum to the universe total.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import date
from enum import StrEnum
from types import MappingProxyType


def _deep_freeze(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {key: _deep_freeze(item) for key, item in value.items()}
        )
    if isinstance(value, (list, tuple)):
        return tuple(_deep_freeze(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return frozenset(_deep_freeze(item) for item in value)
    return value


def _valid_sha256(value: str) -> bool:
    if not value.startswith("sha256:"):
        return False
    digest = value.removeprefix("sha256:")
    return len(digest) == 64 and all(char in "0123456789abcdef" for char in digest)


class PriceStatus(StrEnum):
    CURRENT = "current"
    SUSPENDED = "suspended"
    MISSING_UNEXPLAINED = "missing_unexplained"
    FAILED = "failed"
    NOT_ATTEMPTED = "not_attempted"


class FundFlowStatus(StrEnum):
    CURRENT = "current"
    SUSPENDED = "suspended"
    UNSUPPORTED = "unsupported"
    MISSING_UNEXPLAINED = "missing_unexplained"
    FAILED = "failed"
    NOT_ATTEMPTED = "not_attempted"


class SuspensionEvidenceStatus(StrEnum):
    AVAILABLE_NONEMPTY = "available_nonempty"
    AVAILABLE_EMPTY = "available_empty"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class SuspensionEvidence:
    trade_date: date
    status: SuspensionEvidenceStatus
    tickers: frozenset[str]
    source_fingerprint: str | None = None

    def __post_init__(self) -> None:
        try:
            frozen_tickers = frozenset(self.tickers)
        except (TypeError, ValueError) as exc:
            raise ValueError("suspension evidence tickers must be iterable") from exc
        object.__setattr__(self, "tickers", frozen_tickers)
        if not isinstance(self.trade_date, date):
            raise ValueError("suspension evidence trade_date must be a date")
        if not isinstance(self.status, SuspensionEvidenceStatus):
            raise ValueError("invalid suspension evidence status")
        if any(
            not isinstance(ticker, str)
            or len(ticker) != 6
            or not ticker.isdigit()
            for ticker in frozen_tickers
        ):
            raise ValueError("suspension evidence contains invalid ticker identity")
        if self.status is SuspensionEvidenceStatus.AVAILABLE_NONEMPTY:
            if not frozen_tickers:
                raise ValueError("available_nonempty suspension evidence needs tickers")
        elif self.status is SuspensionEvidenceStatus.AVAILABLE_EMPTY:
            if frozen_tickers:
                raise ValueError("available_empty suspension evidence cannot have tickers")
        elif frozen_tickers or self.source_fingerprint is not None:
            raise ValueError("unavailable suspension evidence cannot carry evidence")
        if self.source_fingerprint is not None and not _valid_sha256(
            self.source_fingerprint
        ):
            raise ValueError("invalid suspension source fingerprint")

    @classmethod
    def available(
        cls,
        trade_date: date,
        tickers: frozenset[str] | set[str],
        *,
        source_fingerprint: str | None = None,
    ) -> SuspensionEvidence:
        return cls(
            trade_date=trade_date,
            status=(
                SuspensionEvidenceStatus.AVAILABLE_NONEMPTY
                if tickers
                else SuspensionEvidenceStatus.AVAILABLE_EMPTY
            ),
            tickers=frozenset(tickers),
            source_fingerprint=source_fingerprint,
        )

    @classmethod
    def unavailable(
        cls,
        trade_date: date,
        *,
        source_fingerprint: str | None = None,
    ) -> SuspensionEvidence:
        return cls(
            trade_date=trade_date,
            status=SuspensionEvidenceStatus.UNAVAILABLE,
            tickers=frozenset(),
            source_fingerprint=source_fingerprint,
        )


@dataclass(frozen=True)
class TickerRefreshOutcome:
    ticker: str
    price_status: PriceStatus
    price_history_rows: int
    fund_flow_status: FundFlowStatus
    fund_flow_history_rows: int
    evidence_fingerprints: Mapping[str, str] = field(default_factory=dict)
    block_reasons: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "evidence_fingerprints",
            MappingProxyType(dict(self.evidence_fingerprints)),
        )
        object.__setattr__(self, "block_reasons", tuple(self.block_reasons))
        object.__setattr__(self, "warnings", tuple(self.warnings))


@dataclass(frozen=True)
class DailyActionCacheRefreshStats:
    """Derived stats from per-ticker outcomes. Display-only, not a gate."""

    price_status_counts: Mapping[str, int]
    fund_flow_status_counts: Mapping[str, int]
    industry_index_total: int
    industry_index_failed: int
    limit_up_injected: int

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "price_status_counts",
            MappingProxyType(dict(self.price_status_counts)),
        )
        object.__setattr__(
            self,
            "fund_flow_status_counts",
            MappingProxyType(dict(self.fund_flow_status_counts)),
        )

    def to_dict(self) -> dict:
        return {
            "price_status_counts": dict(self.price_status_counts),
            "fund_flow_status_counts": dict(self.fund_flow_status_counts),
            "industry_index_total": self.industry_index_total,
            "industry_index_failed": self.industry_index_failed,
            "limit_up_injected": self.limit_up_injected,
        }


@dataclass(frozen=True)
class DailyActionRefreshResult:
    trade_date: date
    universe_tickers: tuple[str, ...]
    universe_fingerprint: str
    daily_batch_fingerprint: str | None
    suspension_evidence: SuspensionEvidence
    outcomes: Mapping[str, TickerRefreshOutcome]
    stats: DailyActionCacheRefreshStats
    _refresh_counters: Mapping[str, object] = field(
        default_factory=dict,
        repr=False,
        compare=False,
    )

    def __post_init__(self):
        object.__setattr__(self, "universe_tickers", tuple(self.universe_tickers))
        # Validate: no duplicate tickers in universe
        if len(set(self.universe_tickers)) != len(self.universe_tickers):
            raise ValueError("universe_tickers contains duplicates")
        outcome_tickers = set(self.outcomes.keys())
        universe_set = set(self.universe_tickers)
        if outcome_tickers != universe_set:
            if outcome_tickers.issubset(universe_set):
                # Retain the more specific conservation diagnostic for legacy
                # callers that only omit outcomes.
                raise ValueError(
                    f"price status counts ({len(outcome_tickers)}) != universe "
                    f"({len(self.universe_tickers)}); outcomes must exactly cover "
                    "the frozen universe"
                )
            raise ValueError("outcomes must exactly cover the frozen universe")

        frozen_outcomes: dict[str, TickerRefreshOutcome] = {}
        for ticker in self.universe_tickers:
            outcome = self.outcomes[ticker]
            if outcome.ticker != ticker:
                raise ValueError("outcome ticker identity must match its mapping key")
            frozen_outcomes[ticker] = replace(
                outcome,
                evidence_fingerprints=MappingProxyType(
                    dict(outcome.evidence_fingerprints)
                ),
                block_reasons=tuple(outcome.block_reasons),
                warnings=tuple(outcome.warnings),
            )
        object.__setattr__(self, "outcomes", MappingProxyType(frozen_outcomes))
        object.__setattr__(
            self,
            "_refresh_counters",
            _deep_freeze(self._refresh_counters),
        )
        # Validate: conservation — sum of price statuses == universe total
        price_counts: dict[str, int] = {}
        for outcome in self.outcomes.values():
            price_counts[outcome.price_status.value] = (
                price_counts.get(outcome.price_status.value, 0) + 1
            )
        if sum(price_counts.values()) != len(self.universe_tickers):
            raise ValueError(
                f"price status counts ({sum(price_counts.values())}) != universe ({len(self.universe_tickers)})"
            )
        # Validate: conservation — sum of fund_flow statuses == universe total
        flow_counts: dict[str, int] = {}
        for outcome in self.outcomes.values():
            flow_counts[outcome.fund_flow_status.value] = (
                flow_counts.get(outcome.fund_flow_status.value, 0) + 1
            )
        if sum(flow_counts.values()) != len(self.universe_tickers):
            raise ValueError(
                f"fund_flow status counts ({sum(flow_counts.values())}) != universe ({len(self.universe_tickers)})"
            )

    def __getattr__(self, name: str) -> object:
        """Keep legacy display-counter reads working during the v2 migration."""

        counters = object.__getattribute__(self, "_refresh_counters")
        if name in counters:
            return counters[name]
        raise AttributeError(name)

    def to_dict(self) -> dict:
        return {
            "trade_date": self.trade_date.isoformat(),
            "universe_tickers": list(self.universe_tickers),
            "universe_fingerprint": self.universe_fingerprint,
            "daily_batch_fingerprint": self.daily_batch_fingerprint,
            "suspension_evidence": {
                "status": self.suspension_evidence.status.value,
                "tickers": sorted(self.suspension_evidence.tickers),
                "source_fingerprint": self.suspension_evidence.source_fingerprint,
            },
            "outcomes": {
                ticker: {
                    "price_status": o.price_status.value,
                    "price_history_rows": o.price_history_rows,
                    "fund_flow_status": o.fund_flow_status.value,
                    "fund_flow_history_rows": o.fund_flow_history_rows,
                    "evidence_fingerprints": dict(o.evidence_fingerprints),
                    "block_reasons": list(o.block_reasons),
                    "warnings": list(o.warnings),
                }
                for ticker, o in self.outcomes.items()
            },
            "stats": self.stats.to_dict(),
        }


def derive_stats_from_outcomes(
    outcomes: Mapping[str, TickerRefreshOutcome],
    *,
    industry_index_total: int = 0,
    industry_index_failed: int = 0,
    limit_up_injected: int = 0,
) -> DailyActionCacheRefreshStats:
    price_counts: dict[str, int] = {}
    flow_counts: dict[str, int] = {}
    for outcome in outcomes.values():
        price_counts[outcome.price_status.value] = (
            price_counts.get(outcome.price_status.value, 0) + 1
        )
        flow_counts[outcome.fund_flow_status.value] = (
            flow_counts.get(outcome.fund_flow_status.value, 0) + 1
        )
    return DailyActionCacheRefreshStats(
        price_status_counts=MappingProxyType(price_counts),
        fund_flow_status_counts=MappingProxyType(flow_counts),
        industry_index_total=industry_index_total,
        industry_index_failed=industry_index_failed,
        limit_up_injected=limit_up_injected,
    )


def universe_fingerprint(tickers: tuple[str, ...]) -> str:
    """SHA-256 fingerprint of the sorted unique universe."""
    canonical = json.dumps(sorted(set(tickers)), separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canonical.encode()).hexdigest()
