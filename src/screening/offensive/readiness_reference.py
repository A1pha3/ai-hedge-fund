"""Typed, immutable provenance for Daily Action reference datasets."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date
from types import MappingProxyType
from typing import Mapping

import pandas as pd

SECURITY_REFERENCE_SOURCES = frozenset({"tushare.stock_basic"})
SW_REFERENCE_SOURCES = frozenset({"tushare.index_classify+index_member"})


def reference_fingerprint(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def is_sha256(value: object) -> bool:
    return (
        type(value) is str
        and len(value) == 71
        and value.startswith("sha256:")
        and all(ch in "0123456789abcdef" for ch in value[7:])
    )


@dataclass(frozen=True)
class ReferenceProvenance:
    """Dated source identity whose effective window is explicit and auditable."""

    observed_on: date
    effective_from: date
    effective_through: date
    source: str
    version: str
    content_fingerprint: str
    source_fingerprint: str

    def __post_init__(self) -> None:
        if any(
            type(value) is not date
            for value in (self.observed_on, self.effective_from, self.effective_through)
        ):
            raise ValueError("reference provenance dates must be exact")
        if self.effective_from > self.effective_through:
            raise ValueError("reference effective window is inverted")
        if type(self.source) is not str or not self.source.strip():
            raise ValueError("reference source must be nonempty")
        if type(self.version) is not str or not self.version.strip():
            raise ValueError("reference version must be nonempty")
        if not is_sha256(self.content_fingerprint):
            raise ValueError("reference content fingerprint is invalid")
        if self.source_fingerprint != reference_fingerprint(self._identity_payload()):
            raise ValueError("reference source fingerprint mismatch")

    def _identity_payload(self) -> dict[str, str]:
        return {
            "observed_on": self.observed_on.isoformat(),
            "effective_from": self.effective_from.isoformat(),
            "effective_through": self.effective_through.isoformat(),
            "source": self.source,
            "version": self.version,
            "content_fingerprint": self.content_fingerprint,
        }

    def to_dict(self) -> dict[str, str]:
        return {**self._identity_payload(), "source_fingerprint": self.source_fingerprint}

    @classmethod
    def create(
        cls,
        *,
        observed_on: date,
        effective_from: date,
        effective_through: date,
        source: str,
        version: str,
        content_fingerprint: str,
    ) -> "ReferenceProvenance":
        identity = {
            "observed_on": observed_on.isoformat(),
            "effective_from": effective_from.isoformat(),
            "effective_through": effective_through.isoformat(),
            "source": source,
            "version": version,
            "content_fingerprint": content_fingerprint,
        }
        return cls(
            observed_on=observed_on,
            effective_from=effective_from,
            effective_through=effective_through,
            source=source,
            version=version,
            content_fingerprint=content_fingerprint,
            source_fingerprint=reference_fingerprint(identity),
        )


def validate_reference_for_session(
    reference: ReferenceProvenance,
    signal_date: date,
    *,
    label: str,
    known_sources: frozenset[str],
) -> None:
    """Fail closed unless a known reference is fresh for the exact session."""

    if type(reference) is not ReferenceProvenance:
        raise ValueError(f"{label} reference provenance must be exact")
    if reference.source not in known_sources:
        raise ValueError(f"{label} reference source is unknown")
    if reference.observed_on != signal_date:
        raise ValueError(
            f"{label} reference signal date mismatch: observed_on must be exact"
        )
    if not (reference.effective_from <= signal_date <= reference.effective_through):
        raise ValueError(
            f"{label} reference effective window does not cover signal date"
        )


@dataclass(frozen=True)
class DailyReadinessReferenceSnapshot:
    """Detached stock/security and SW observations with dated provenance."""

    stock_basic_rows: tuple[Mapping[str, str], ...]
    sw_industry_by_ticker: Mapping[str, str]
    security_reference: ReferenceProvenance
    sw_reference: ReferenceProvenance
    effective_as_of: date

    def __post_init__(self) -> None:
        if type(self.effective_as_of) is not date:
            raise ValueError("reference effective_as_of must be exact")
        rows = tuple(MappingProxyType(dict(row)) for row in self.stock_basic_rows)
        sw = dict(self.sw_industry_by_ticker)
        if self.security_reference.content_fingerprint != reference_fingerprint(
            [dict(row) for row in rows]
        ):
            raise ValueError("security reference content mismatch")
        if self.sw_reference.content_fingerprint != reference_fingerprint(sw):
            raise ValueError("SW reference content mismatch")
        object.__setattr__(self, "stock_basic_rows", rows)
        object.__setattr__(self, "sw_industry_by_ticker", MappingProxyType(sw))


def make_daily_readiness_reference_snapshot(
    *,
    stock_basic: object,
    sw_industry_by_ticker: object,
    security_observed_on: date,
    security_effective_from: date,
    security_effective_through: date,
    security_source: str,
    security_version: str,
    sw_observed_on: date,
    sw_effective_from: date,
    sw_effective_through: date,
    sw_source: str,
    sw_version: str,
    effective_as_of: date | None = None,
) -> DailyReadinessReferenceSnapshot:
    if isinstance(stock_basic, pd.DataFrame):
        raw_rows = stock_basic.copy(deep=True).to_dict("records")
    elif isinstance(stock_basic, (list, tuple)):
        raw_rows = list(stock_basic)
    else:
        raise ValueError("stock_basic reference must be tabular")
    rows: list[dict[str, str]] = []
    for raw in raw_rows:
        if not isinstance(raw, Mapping):
            raise ValueError("stock_basic reference row is malformed")
        values = tuple(raw.get(key) for key in ("ts_code", "name", "list_status"))
        if any(type(value) is not str for value in values):
            raise ValueError("stock_basic reference row is malformed")
        code, name, status = values
        rows.append({"ts_code": code, "name": name, "list_status": status})
    rows.sort(key=lambda row: row["ts_code"])
    if not isinstance(sw_industry_by_ticker, Mapping):
        raise ValueError("SW reference must be a mapping")
    sw = {
        code: industry
        for code, industry in sorted(sw_industry_by_ticker.items())
        if type(code) is str and type(industry) is str
    }
    if len(sw) != len(sw_industry_by_ticker):
        raise ValueError("SW reference mapping is malformed")
    security_content = reference_fingerprint(rows)
    sw_content = reference_fingerprint(sw)
    return DailyReadinessReferenceSnapshot(
        stock_basic_rows=tuple(rows),
        sw_industry_by_ticker=sw,
        security_reference=ReferenceProvenance.create(
            observed_on=security_observed_on,
            effective_from=security_effective_from,
            effective_through=security_effective_through,
            source=security_source,
            version=security_version,
            content_fingerprint=security_content,
        ),
        sw_reference=ReferenceProvenance.create(
            observed_on=sw_observed_on,
            effective_from=sw_effective_from,
            effective_through=sw_effective_through,
            source=sw_source,
            version=sw_version,
            content_fingerprint=sw_content,
        ),
        effective_as_of=effective_as_of or sw_effective_from,
    )
