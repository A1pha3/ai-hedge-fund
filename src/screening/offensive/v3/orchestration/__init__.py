"""Plan 05 Task 6+7: --auto 与 --daily-action 独立 shadow 编排。"""

from .auto_flow import AutoFlow, AutoFlowResult
from .daily_action_flow import DailyActionFlow, DailyActionFlowResult
from .genesis import (
    NormalizedTrialArmState,
    TrialArmGenesisSource,
    TrialGenesisArchive,
    TrialGenesisError,
    TrialGenesisManifest,
    normalized_trial_arm_state,
    restore_genesis_arm,
)
from .paired_trial import (
    ForwardPairedTrialRunner,
    PairedSignalReceipt,
    PairedTrialRunnerError,
    REGIME_EVIDENCE_ID,
    SignalSessionRequest,
    classify_pair_session,
)
from .replay import (
    ForwardTrialReplayEngine,
    PairedReplayResult,
    ReplayCorporateAction,
    ReplayRestatement,
    ReplayScenario,
    ReplaySessionFacts,
    TrialReplayError,
    TrialReplayInput,
    drive_session_lifecycle,
)
from .trial_store import (
    ArmDecision,
    PairCommitReceipt,
    TrialArmDecisionRecord,
    TrialArmDecisionStore,
    TrialStoreError,
    WriterLeaseToken,
)

__all__ = [
    "ArmDecision",
    "AutoFlow",
    "AutoFlowResult",
    "DailyActionFlow",
    "DailyActionFlowResult",
    "ForwardPairedTrialRunner",
    "ForwardTrialReplayEngine",
    "NormalizedTrialArmState",
    "PairedReplayResult",
    "PairedSignalReceipt",
    "PairedTrialRunnerError",
    "PairCommitReceipt",
    "REGIME_EVIDENCE_ID",
    "ReplayCorporateAction",
    "ReplayRestatement",
    "ReplayScenario",
    "ReplaySessionFacts",
    "SignalSessionRequest",
    "TrialArmDecisionRecord",
    "TrialArmDecisionStore",
    "TrialArmGenesisSource",
    "TrialGenesisArchive",
    "TrialGenesisError",
    "TrialGenesisManifest",
    "TrialReplayError",
    "TrialReplayInput",
    "TrialStoreError",
    "WriterLeaseToken",
    "classify_pair_session",
    "drive_session_lifecycle",
    "normalized_trial_arm_state",
    "restore_genesis_arm",
]
