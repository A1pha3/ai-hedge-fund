"""Strict primitives and canonical serialization for v3 contracts."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum, StrEnum
from math import gcd
from typing import Annotated, Any, TypeAlias

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    field_validator,
    model_validator,
    Strict,
    StringConstraints,
    TypeAdapter,
)


class ExecutionMode(StrEnum):
    """How an outcome or execution fact was established."""

    RESEARCH_RECONSTRUCTION = "research_reconstruction"
    DAILY_BAR_PROXY = "daily_bar_proxy"
    MANUAL_CONFIRMED = "manual_confirmed"
    BROKER_CONFIRMED = "broker_confirmed"


class EvidenceScope(StrEnum):
    """Whether evidence is global or bound to one strategy lineage."""

    GLOBAL = "global"
    STRATEGY_LINEAGE = "strategy_lineage"


class SignalStage(StrEnum):
    """A signal's immutable position in the producer funnel."""

    CANDIDATE = "candidate"
    DATA_ELIGIBLE = "data_eligible"
    SELECTED = "selected"


def _validate_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("UTC instant must be timezone-aware")
    if value.tzinfo is not timezone.utc or value.utcoffset() != timedelta(0):
        raise ValueError("UTC instant must use the UTC timezone")
    return value


def _normalize_json_utc(value: Any, info: Any) -> Any:
    if info.mode == "json" and isinstance(value, str):
        iso_value = value[:-1] + "+00:00" if value.endswith("Z") else value
        parsed = datetime.fromisoformat(iso_value)
        if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
            raise ValueError("UTC instant must use the UTC timezone")
        return parsed.astimezone(timezone.utc)
    return value


UtcInstant: TypeAlias = Annotated[
    datetime,
    BeforeValidator(_normalize_json_utc),
    AfterValidator(_validate_utc),
]
"""A timezone-aware datetime whose offset is exactly UTC."""

UtcInstantAdapter = TypeAdapter(UtcInstant, config=ConfigDict(strict=True))


def _validate_exact_integer(value: Any) -> Any:
    if type(value) is not int:
        raise ValueError("exact integer values must use the native int type")
    return value


ExactInteger: TypeAlias = Annotated[
    int,
    BeforeValidator(_validate_exact_integer),
    Strict(),
]
"""A semantically neutral exact native integer without numeric coercion."""

MoneyCents: TypeAlias = ExactInteger
"""An exact integer count of the smallest monetary unit."""

QuantityUnits: TypeAlias = ExactInteger
"""An exact integer count of a domain quantity's smallest unit."""

UnitQuanta: TypeAlias = ExactInteger
"""An exact integer count of issued or redeemed unit quanta."""


def _validate_schema_version(value: int) -> int:
    if value != 2:
        raise ValueError("unsupported schema major: expected 2")
    return value


SchemaVersion: TypeAlias = Annotated[
    int,
    BeforeValidator(_validate_exact_integer),
    Strict(),
    AfterValidator(_validate_schema_version),
]
"""The only Revision 2 schema major accepted by new domain contracts."""


Sha256: TypeAlias = Annotated[
    str,
    StringConstraints(pattern=r"^[0-9a-f]{64}$"),
]
"""A lowercase, unprefixed SHA-256 hexadecimal digest."""

Sha256Adapter = TypeAdapter(Sha256, config=ConfigDict(strict=True))


def canonical_decimal_string(value: Decimal) -> str:
    """Render a finite Decimal without exponent notation or redundant zeros."""

    if not value.is_finite():
        raise ValueError("canonical JSON requires finite Decimal values")
    if value.is_zero():
        return "0"

    sign, digits, exponent = value.as_tuple()
    digits_text = "".join(str(digit) for digit in digits)
    if exponent >= 0:
        integer_part = digits_text + ("0" * exponent)
        fraction_part = ""
    else:
        decimal_index = len(digits_text) + exponent
        if decimal_index > 0:
            integer_part = digits_text[:decimal_index]
            fraction_part = digits_text[decimal_index:]
        else:
            integer_part = "0"
            fraction_part = ("0" * -decimal_index) + digits_text
        fraction_part = fraction_part.rstrip("0")

    rendered = integer_part if not fraction_part else f"{integer_part}.{fraction_part}"
    return ("-" if sign else "") + rendered


def _canonical_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        raise ValueError("canonical JSON forbids float values")
    if isinstance(value, Decimal):
        return canonical_decimal_string(value)
    if isinstance(value, datetime):
        utc_value = _validate_utc(value)
        return utc_value.isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Enum):
        return _canonical_value(value.value)
    if isinstance(value, BaseModel):
        validated = type(value).model_validate(
            value.model_dump(
                mode="python",
                round_trip=True,
                exclude_none=False,
                warnings="none",
            ),
            strict=True,
        )
        return _canonical_value(
            validated.model_dump(
                mode="python",
                round_trip=True,
                exclude_none=False,
                warnings="none",
            )
        )
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            raise TypeError("canonical JSON object keys must be strings")
        return {key: _canonical_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_canonical_value(item) for item in value]
    raise TypeError(f"unsupported canonical JSON value: {type(value).__name__}")


def canonical_json_bytes(value: Any) -> bytes:
    """Serialize a supported value into deterministic, UTF-8 JSON bytes."""

    encoded = json.dumps(
        _canonical_value(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return encoded.encode("utf-8")


def content_hash(value: Any) -> str:
    """Return the lowercase SHA-256 digest of a canonical payload."""

    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def domain_hash(domain: str, schema_major: int, payload: Any) -> str:
    """Hash a Revision 2 payload in one explicit domain-separated envelope.

    The envelope ``schema_major`` is the domain-hashing scheme version. Revision
    2 artifacts seal under major 2; historical/current ShadowDecision artifacts
    seal under their own schema major 3/4. This does not loosen the
    ``SchemaVersion`` field type that every Revision 2 contract still enforces.
    """

    if not isinstance(domain, str) or not domain or domain.strip() != domain:
        raise ValueError("domain must be nonempty and have no surrounding whitespace")
    if type(schema_major) is not int or schema_major not in _DOMAIN_SCHEMA_MAJORS:
        raise ValueError(f"unsupported domain schema major: {schema_major!r}; " f"expected one of {sorted(_DOMAIN_SCHEMA_MAJORS)}")
    return hashlib.sha256(
        canonical_json_bytes(
            {
                "domain": domain,
                "schema_major": schema_major,
                "payload": payload,
            }
        )
    ).hexdigest()


#: Domain-hash envelope schema majors admitted by this revision.
_DOMAIN_SCHEMA_MAJORS: frozenset[int] = frozenset({2, 3, 4})


class CanonicalModel(BaseModel):
    """Base model for immutable, strict, canonically hashable contracts."""

    model_config = ConfigDict(
        strict=True,
        frozen=True,
        extra="forbid",
        revalidate_instances="always",
    )

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self)

    def content_hash(self) -> str:
        return content_hash(self)


class RationalQuantity(CanonicalModel):
    """A minimal exact rational quantity for later corporate-action contracts."""

    numerator: QuantityUnits
    denominator: QuantityUnits

    @model_validator(mode="before")
    @classmethod
    def normalize_lowest_terms(cls, value: Any) -> Any:
        if not isinstance(value, Mapping):
            return value

        numerator = value.get("numerator")
        denominator = value.get("denominator")
        if type(numerator) is not int or type(denominator) is not int:
            return value
        if denominator <= 0:
            return value

        divisor = gcd(abs(numerator), denominator)
        return {
            **value,
            "numerator": numerator // divisor,
            "denominator": denominator // divisor,
        }

    @field_validator("denominator")
    @classmethod
    def validate_positive_denominator(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("denominator must be greater than zero")
        return value
