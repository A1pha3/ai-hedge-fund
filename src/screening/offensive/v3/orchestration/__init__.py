"""Lazy public facade for v3 orchestration primitives.

Importing a disabled trial entry module must not initialize unrelated legacy
data clients.  Resolve facade attributes only when a caller asks for them.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any


_EXPORTS: dict[str, tuple[str, str]] = {
    "ArmDecision": ("trial_store", "ArmDecision"),
    "AutoFlow": ("auto_flow", "AutoFlow"),
    "AutoFlowResult": ("auto_flow", "AutoFlowResult"),
    "DailyActionFlow": ("daily_action_flow", "DailyActionFlow"),
    "DailyActionFlowResult": ("daily_action_flow", "DailyActionFlowResult"),
    "ForwardPairedTrialRunner": ("paired_trial", "ForwardPairedTrialRunner"),
    "ForwardTrialReplayEngine": ("replay", "ForwardTrialReplayEngine"),
    "NormalizedTrialArmState": ("genesis", "NormalizedTrialArmState"),
    "PairedReplayResult": ("replay", "PairedReplayResult"),
    "PairedSignalReceipt": ("paired_trial", "PairedSignalReceipt"),
    "PairedTrialRunnerError": ("paired_trial", "PairedTrialRunnerError"),
    "PairCommitReceipt": ("trial_store", "PairCommitReceipt"),
    "REGIME_EVIDENCE_ID": ("paired_trial", "REGIME_EVIDENCE_ID"),
    "ReplayCorporateAction": ("replay", "ReplayCorporateAction"),
    "ReplayRestatement": ("replay", "ReplayRestatement"),
    "ReplayScenario": ("replay", "ReplayScenario"),
    "ReplaySessionFacts": ("replay", "ReplaySessionFacts"),
    "SignalSessionRequest": ("paired_trial", "SignalSessionRequest"),
    "TrialArmDecisionRecord": ("trial_store", "TrialArmDecisionRecord"),
    "TrialArmDecisionStore": ("trial_store", "TrialArmDecisionStore"),
    "TrialArmGenesisSource": ("genesis", "TrialArmGenesisSource"),
    "TrialGenesisArchive": ("genesis", "TrialGenesisArchive"),
    "TrialGenesisError": ("genesis", "TrialGenesisError"),
    "TrialGenesisManifest": ("genesis", "TrialGenesisManifest"),
    "TrialReplayError": ("replay", "TrialReplayError"),
    "TrialReplayInput": ("replay", "TrialReplayInput"),
    "TrialStoreError": ("trial_store", "TrialStoreError"),
    "WriterLeaseToken": ("trial_store", "WriterLeaseToken"),
    "classify_pair_session": ("paired_trial", "classify_pair_session"),
    "normalized_trial_arm_state": ("genesis", "normalized_trial_arm_state"),
    "restore_genesis_arm": ("genesis", "restore_genesis_arm"),
}

__all__ = list(_EXPORTS)


def __getattr__(name: str) -> Any:
    try:
        module_name, attribute_name = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(name) from exc
    value = getattr(import_module(f"{__name__}.{module_name}"), attribute_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted((*globals(), *__all__))
