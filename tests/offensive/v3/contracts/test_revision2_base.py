"""Revision 2 canonical primitive contracts."""

from datetime import datetime, timezone
from decimal import Decimal
import json
from pathlib import Path

import pytest
from pydantic import TypeAdapter, ValidationError


def test_canonical_json_rejects_persisted_floats_at_any_depth() -> None:
    from src.screening.offensive.v3.contracts.base import canonical_json_bytes

    with pytest.raises(ValueError, match="float"):
        canonical_json_bytes({"truth": [{"value": 1.25}]})


def test_canonical_json_normalizes_finite_decimal_values() -> None:
    from src.screening.offensive.v3.contracts.base import canonical_json_bytes

    assert canonical_json_bytes({"value": Decimal("1.2300")}) == b'{"value":"1.23"}'


def test_utc_instant_requires_a_timezone_aware_utc_value() -> None:
    from src.screening.offensive.v3.contracts.base import UtcInstantAdapter

    instant = datetime(2026, 7, 26, 8, 0, tzinfo=timezone.utc)

    assert UtcInstantAdapter.validate_python(instant) == instant
    with pytest.raises(ValidationError, match="timezone-aware"):
        UtcInstantAdapter.validate_python(instant.replace(tzinfo=None))


def test_rational_quantity_requires_a_positive_exact_integer_denominator() -> None:
    from src.screening.offensive.v3.contracts.base import RationalQuantity

    assert RationalQuantity(numerator=-3, denominator=2).model_dump() == {
        "numerator": -3,
        "denominator": 2,
    }
    with pytest.raises(ValidationError, match="denominator"):
        RationalQuantity(numerator=1, denominator=0)
    with pytest.raises(ValidationError):
        RationalQuantity(numerator=1, denominator=2.0)


@pytest.mark.parametrize(
    ("numerator", "denominator", "expected"),
    [
        (2, 4, {"numerator": 1, "denominator": 2}),
        (-2, 4, {"numerator": -1, "denominator": 2}),
        (0, 9, {"numerator": 0, "denominator": 1}),
    ],
)
def test_rational_quantity_normalizes_to_unique_lowest_terms(
    numerator: int, denominator: int, expected: dict[str, int]
) -> None:
    from src.screening.offensive.v3.contracts.base import RationalQuantity

    assert RationalQuantity(numerator=numerator, denominator=denominator).model_dump() == expected


def test_equivalent_rational_quantities_have_identical_canonical_identity() -> None:
    from src.screening.offensive.v3.contracts.base import RationalQuantity

    left = RationalQuantity(numerator=2, denominator=4)
    right = RationalQuantity(numerator=1, denominator=2)

    assert left.canonical_bytes() == right.canonical_bytes()
    assert left.content_hash() == right.content_hash()


def test_schema_version_accepts_exact_revision_two() -> None:
    from src.screening.offensive.v3.contracts.base import SchemaVersion

    assert TypeAdapter(SchemaVersion).validate_python(2) == 2


@pytest.mark.parametrize("value", [1, 3, True, "2"])
def test_schema_version_rejects_unknown_and_coerced_values(value: object) -> None:
    from src.screening.offensive.v3.contracts.base import SchemaVersion

    with pytest.raises(ValidationError):
        TypeAdapter(SchemaVersion).validate_python(value)


def test_exact_integer_primitives_reject_boolean_and_float_values() -> None:
    from src.screening.offensive.v3.contracts.base import (
        MoneyCents,
        QuantityUnits,
        UnitQuanta,
    )

    for primitive in (MoneyCents, QuantityUnits, UnitQuanta):
        adapter = TypeAdapter(primitive)
        assert adapter.validate_python(-1) == -1
        for invalid in (True, 1.0):
            with pytest.raises(ValidationError):
                adapter.validate_python(invalid)


def test_same_payload_has_different_domain_hashes() -> None:
    from src.screening.offensive.v3.contracts.base import domain_hash

    payload = {"portfolio_id": "p1", "version": 1}
    assert domain_hash("policy-activation", 2, payload) != domain_hash(
        "capital-authorization", 2, payload
    )


@pytest.mark.parametrize("domain", ["", " policy-activation", "policy-activation "])
def test_domain_hash_rejects_empty_or_whitespace_surrounded_domains(domain: str) -> None:
    from src.screening.offensive.v3.contracts.base import domain_hash

    with pytest.raises(ValueError, match="domain"):
        domain_hash(domain, 2, {"portfolio_id": "p1"})


def test_revision_one_unscoped_base_hash_fixture_is_frozen() -> None:
    from src.screening.offensive.v3.contracts.base import canonical_json_bytes, content_hash

    fixture_path = Path(__file__).parent / "fixtures" / "revision1" / "base_hash.json"
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))

    assert fixture["schema_major"] == 1
    assert canonical_json_bytes(fixture["payload"]) == fixture["canonical_json"].encode(
        "utf-8"
    )
    assert content_hash(fixture["payload"]) == fixture["content_hash"]
