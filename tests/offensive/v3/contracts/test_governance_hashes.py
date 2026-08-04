"""Frozen, domain-separated golden hashes for every Task 2 artifact."""

from __future__ import annotations

from decimal import Decimal
import json
from pathlib import Path

from pydantic import TypeAdapter

from src.screening.offensive.v3.contracts.base import domain_hash

from task2_hash_exemplars import task2_hash_exemplars
from test_governance_schemas import TASK2_PUBLIC_MODELS
from test_governance import _trial

HASH_FIXTURE = Path(__file__).parent / "fixtures/revision2/governance_hashes.json"
DECIMAL_FIXTURE = Path(__file__).parent / "fixtures/revision2/exact_decimals.json"


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
        if hasattr(model_type, "APPROVAL_PREIMAGE_DOMAIN"):
            assert expected["approval_preimage_domain"] == (
                model_type.APPROVAL_PREIMAGE_DOMAIN
            )
            assert expected["approval_preimage_hash"] == (
                exemplar.approval_preimage_hash()
            )
            assert {
                approval.approved_manifest_preimage_hash
                for approval in restored.approval_attestations
            } == {expected["approval_preimage_hash"]}
        else:
            assert "approval_preimage_domain" not in expected
            assert "approval_preimage_hash" not in expected


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


def test_tiny_and_large_decimal_json_and_artifact_hash_goldens_are_frozen() -> None:
    from src.screening.offensive.v3.contracts.base import canonical_decimal_string
    from src.screening.offensive.v3.contracts.governance import TrialManifest

    fixture = json.loads(DECIMAL_FIXTURE.read_text(encoding="utf-8"))
    assert [item["decimal_input"] for item in fixture] == ["0.0000001", "1E+3"]
    for item in fixture:
        value = Decimal(item["decimal_input"])
        trial = TrialManifest.model_validate(_trial(minimum_economic_effect=value))
        assert canonical_decimal_string(value) == item["rendered"]
        assert json.loads(trial.model_dump_json())["minimum_economic_effect"] == item[
            "rendered"
        ]
        assert trial.artifact_hash() == item["trial_artifact_hash"]
        assert TrialManifest.model_validate_json(trial.model_dump_json()) == trial
