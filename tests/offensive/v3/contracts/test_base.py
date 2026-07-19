"""Tests for storage-free v3 contract primitives."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal, localcontext
import hashlib
from math import inf, nan

import pytest
from pydantic import ValidationError


def test_canonical_hash_is_stable() -> None:
    from src.screening.offensive.v3.contracts.base import canonical_json_bytes

    left = canonical_json_bytes({"b": Decimal("1.00"), "a": 2})
    right = canonical_json_bytes({"a": 2, "b": Decimal("1")})

    assert left == right == b'{"a":2,"b":"1"}'


def test_naive_datetime_is_rejected() -> None:
    from src.screening.offensive.v3.contracts.base import UtcInstantAdapter

    with pytest.raises(ValidationError):
        UtcInstantAdapter.validate_python(datetime(2026, 7, 19, 16, 0))


def test_non_utc_datetime_is_rejected() -> None:
    from src.screening.offensive.v3.contracts.base import UtcInstantAdapter

    with pytest.raises(ValidationError, match="UTC"):
        UtcInstantAdapter.validate_python(
            datetime(2026, 7, 19, 16, 0, tzinfo=timezone(timedelta(hours=8)))
        )

    with pytest.raises(ValidationError, match="UTC"):
        UtcInstantAdapter.validate_python(
            datetime(2026, 7, 19, 16, 0, tzinfo=timezone(timedelta(0), "zero"))
        )


def test_canonical_model_rejects_boolean_coercion() -> None:
    from src.screening.offensive.v3.contracts.base import CanonicalModel

    class StrictFlag(CanonicalModel):
        enabled: bool

    with pytest.raises(ValidationError):
        StrictFlag.model_validate({"enabled": 1})


def test_canonical_model_forbids_unknown_fields_and_is_frozen() -> None:
    from src.screening.offensive.v3.contracts.base import CanonicalModel

    class StrictFlag(CanonicalModel):
        enabled: bool

    with pytest.raises(ValidationError, match="extra_forbidden"):
        StrictFlag.model_validate({"enabled": True, "unexpected": "field"})

    flag = StrictFlag(enabled=True)
    with pytest.raises(ValidationError, match="frozen_instance"):
        flag.enabled = False


def test_canonical_json_rejects_non_finite_decimals() -> None:
    from src.screening.offensive.v3.contracts.base import canonical_json_bytes

    with pytest.raises(ValueError, match="finite"):
        canonical_json_bytes({"value": Decimal("NaN")})

    with pytest.raises(ValueError, match="finite"):
        canonical_json_bytes({"value": Decimal("Infinity")})


def test_canonical_json_handles_finite_and_non_finite_floats() -> None:
    from src.screening.offensive.v3.contracts.base import canonical_json_bytes

    assert canonical_json_bytes({"value": 1.25}) == b'{"value":1.25}'
    for value in (nan, inf, -inf):
        with pytest.raises(ValueError, match="finite"):
            canonical_json_bytes({"value": value})


def test_decimal_canonicalization_does_not_depend_on_decimal_context() -> None:
    from src.screening.offensive.v3.contracts.base import canonical_json_bytes

    value = Decimal("123456789012345678901234567890.123456789000")
    expected = b'{"value":"123456789012345678901234567890.123456789"}'

    with localcontext() as context:
        context.prec = 6
        assert canonical_json_bytes({"value": value}) == expected

    assert canonical_json_bytes({"value": value}) == expected


def test_decimal_canonicalization_preserves_a_negative_sign() -> None:
    from src.screening.offensive.v3.contracts.base import canonical_json_bytes

    assert canonical_json_bytes({"value": Decimal("-1.50")}) == b'{"value":"-1.5"}'


def test_content_hash_matches_canonical_payload() -> None:
    from src.screening.offensive.v3.contracts.base import CanonicalModel, content_hash

    class Payload(CanonicalModel):
        name: str
        quantity: Decimal

    payload = Payload(name="BTST", quantity=Decimal("1.00"))
    expected = hashlib.sha256(b'{"name":"BTST","quantity":"1"}').hexdigest()

    assert content_hash({"quantity": Decimal("1"), "name": "BTST"}) == expected
    assert payload.canonical_bytes() == b'{"name":"BTST","quantity":"1"}'
    assert payload.content_hash() == expected


def test_base_enum_values_and_sha256_validation() -> None:
    from src.screening.offensive.v3.contracts.base import (
        EvidenceScope,
        ExecutionMode,
        Sha256Adapter,
        SignalStage,
    )

    assert [mode.value for mode in ExecutionMode] == [
        "research_reconstruction",
        "daily_bar_proxy",
        "manual_confirmed",
        "broker_confirmed",
    ]
    assert [scope.value for scope in EvidenceScope] == ["global", "strategy_lineage"]
    assert [stage.value for stage in SignalStage] == [
        "candidate",
        "data_eligible",
        "selected",
    ]
    assert Sha256Adapter.validate_python("a" * 64) == "a" * 64
    with pytest.raises(ValidationError):
        Sha256Adapter.validate_python("A" * 64)
