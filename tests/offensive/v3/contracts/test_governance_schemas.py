"""Frozen Revision 2 governance contract schema snapshots."""

from __future__ import annotations

import json
from pathlib import Path

from src.screening.offensive.v3.contracts.authorization import (
    CapitalAuthorizationEnvelope,
)
from src.screening.offensive.v3.contracts.governance import (
    AuthorizationStatus,
    BrokerEnablementManifest,
    DisasterRecoveryManifest,
    EntryFenceRaised,
    LineageGrant,
    MigrationApprovalManifest,
    PolicyActivation,
    ProgramLossBudgetBinding,
    RiskEpochStarted,
    StageManifest,
    StatisticalAnalysisPlan,
    TrialManifest,
    TrustBundle,
)

TASK2_PUBLIC_MODELS = {
    "AuthorizationStatus": AuthorizationStatus,
    "BrokerEnablementManifest": BrokerEnablementManifest,
    "CapitalAuthorizationEnvelope": CapitalAuthorizationEnvelope,
    "DisasterRecoveryManifest": DisasterRecoveryManifest,
    "EntryFenceRaised": EntryFenceRaised,
    "LineageGrant": LineageGrant,
    "MigrationApprovalManifest": MigrationApprovalManifest,
    "PolicyActivation": PolicyActivation,
    "ProgramLossBudgetBinding": ProgramLossBudgetBinding,
    "RiskEpochStarted": RiskEpochStarted,
    "StageManifest": StageManifest,
    "StatisticalAnalysisPlan": StatisticalAnalysisPlan,
    "TrialManifest": TrialManifest,
    "TrustBundle": TrustBundle,
}

SNAPSHOT_PATH = Path(__file__).parent / "fixtures/revision2/governance_schemas.json"


def test_task2_public_model_fields_exactly_match_checked_in_schema() -> None:
    snapshot = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    assert list(snapshot) == sorted(TASK2_PUBLIC_MODELS)
    for name, model in TASK2_PUBLIC_MODELS.items():
        assert set(model.model_fields) == set(snapshot[name]["properties"])


def test_task2_json_schemas_exactly_match_checked_in_snapshot() -> None:
    snapshot = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    current = {
        name: model.model_json_schema()
        for name, model in sorted(TASK2_PUBLIC_MODELS.items())
    }
    assert current == snapshot


def test_task2_schemas_are_closed_object_contracts() -> None:
    snapshot = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    for schema in snapshot.values():
        assert schema["additionalProperties"] is False
        assert "schema_major" in schema["required"]
