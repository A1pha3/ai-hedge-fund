"""Strict primitives and canonical serialization for v3 contracts."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum, StrEnum
import hashlib
import json
import math
from typing import Annotated, Any, TypeAlias

from pydantic import AfterValidator, BaseModel, ConfigDict, StringConstraints, TypeAdapter


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


UtcInstant: TypeAlias = Annotated[datetime, AfterValidator(_validate_utc)]
"""A timezone-aware datetime whose offset is exactly UTC."""

UtcInstantAdapter = TypeAdapter(UtcInstant, config=ConfigDict(strict=True))


Sha256: TypeAlias = Annotated[
    str,
    StringConstraints(pattern=r"^[0-9a-f]{64}$"),
]
"""A lowercase, unprefixed SHA-256 hexadecimal digest."""

Sha256Adapter = TypeAdapter(Sha256, config=ConfigDict(strict=True))


def _normalized_decimal(value: Decimal) -> str:
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
        if not math.isfinite(value):
            raise ValueError("canonical JSON requires finite float values")
        return value
    if isinstance(value, Decimal):
        return _normalized_decimal(value)
    if isinstance(value, datetime):
        utc_value = _validate_utc(value)
        return utc_value.isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Enum):
        return _canonical_value(value.value)
    if isinstance(value, BaseModel):
        return _canonical_value(value.model_dump(mode="python", exclude_none=False))
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


class CanonicalModel(BaseModel):
    """Base model for immutable, strict, canonically hashable contracts."""

    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.model_dump(mode="python", exclude_none=False))

    def content_hash(self) -> str:
        return content_hash(self.model_dump(mode="python", exclude_none=False))
