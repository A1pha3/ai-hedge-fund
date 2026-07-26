"""Frozen, domain-separated golden hashes for every Task 2 artifact."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import TypeAdapter

from src.screening.offensive.v3.contracts.base import domain_hash

from task2_hash_exemplars import task2_hash_exemplars
from test_governance_schemas import TASK2_PUBLIC_MODELS

HASH_FIXTURE = Path(__file__).parent / "fixtures/revision2/governance_hashes.json"


def test_every_task2_artifact_has_unique_fixed_versioned_hash_domain() -> None:
    domains = [model.HASH_DOMAIN for model in TASK2_PUBLIC_MODELS.values()]
    assert len(domains) == len(set(domains))
    assert all(domain.startswith("ai-hedge-fund.v3.governance.") for domain in domains)
    assert all(domain.endswith(".v1") for domain in domains)


def test_task2_payload_and_artifact_hash_goldens_are_frozen() -> None:
    fixture = json.loads(HASH_FIXTURE.read_text(encoding="utf-8"))
    exemplars = task2_hash_exemplars()
    assert list(fixture) == sorted(TASK2_PUBLIC_MODELS)
    assert set(exemplars) == set(TASK2_PUBLIC_MODELS)
    for name, model_type in TASK2_PUBLIC_MODELS.items():
        exemplar = exemplars[name]
        expected = fixture[name]
        assert expected["hash_domain"] == model_type.HASH_DOMAIN
        assert expected["payload"] == exemplar.model_dump(mode="json")
        assert expected["artifact_hash"] == exemplar.artifact_hash()
        restored = model_type.model_validate_json(json.dumps(expected["payload"]))
        assert restored.artifact_hash() == expected["artifact_hash"]


def test_same_payload_hashes_differ_across_task2_domains() -> None:
    payload = {"schema_major": 2, "sentinel": "same-payload"}
    models = list(TASK2_PUBLIC_MODELS.values())
    assert domain_hash(models[0].HASH_DOMAIN, 2, payload) != domain_hash(
        models[1].HASH_DOMAIN, 2, payload
    )


def test_exact_integer_json_adapter_rejects_non_integer_numbers() -> None:
    from src.screening.offensive.v3.contracts.base import ExactInteger

    adapter = TypeAdapter(ExactInteger)
    assert adapter.validate_json("3") == 3
