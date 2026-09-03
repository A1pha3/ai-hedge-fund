"""R105 Op2 对抗性审查: NO_SIGNAL 语义修复的消费面与重放边界。

Op1 (8462fcfa) 把 decide_core 的空候选 no-trade reason 从
CAPACITY_EXHAUSTED 修正为 NO_SIGNAL (与 executable admission 的
no-candidates 分支对称)。本文件钉死三个对抗面:

1. **行为变化的重放边界** — 修复改变 NoTradeDecision canonical bytes,
   生产历史 6 行 (08-28/09-02/09-03 × 双臂) 是修复前语义的诚实记录,
   append-only 前向唯序保留; 修复后代码重放同会话必须类型化冲突
   (``arm_decision_conflict``), 绝不静默改写历史。
2. **no-trade 门优先序不变式** — 零候选语义不吞更高优先级的门:
   DEADLINE_MISSED / risk 先于 NO_SIGNAL, NO_SIGNAL 先于 regime
   admission gate (零候选 + crisis 时 Challenger 报 NO_SIGNAL — 无信号
   是比 regime 拦截更早的事实层判定)。
3. **恰等幂等保留** — 修复后同一冻结输入重放逐字节收敛 (既有 store
   纪律在 NO_SIGNAL 语义下不变)。

消费面扫描结论 (2026-09-04 侦察, 定性入册不重复断言):
- ``classify_pair_session`` (paired_trial.py:221-238): 零候选走
  ``shared_candidate_count == 0`` 先行短路 → NO_SIGNAL, 不依赖 reason
  值; BLOCKED 判定显式排除 ``value != "NO_SIGNAL"``。
- ``reporting/projection.py:150-157``: ``no_trade_reason`` 透传 typed
  BlockReason, docstring 自 R36 起就区分 NO_SIGNAL / CAPACITY_EXHAUSTED
  — 注释语义与实现一致化是本修复的直接受益面。
- kernel 外无其他 BlockReason 值消费点 (execution/*.py 的 settlement
  reason 是不同域)。
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from src.screening.offensive.v3.contracts.regime import RegimeState
from src.screening.offensive.v3.kernel.decide import GrowthKernel
from src.screening.offensive.v3.kernel.models import BlockReason, NoTradeDecision
from src.screening.offensive.v3.orchestration.paired_trial import (
    build_arm_kernel_inputs,
    build_pair_records,
)
from src.screening.offensive.v3.orchestration.trial_store import (
    TrialArmDecisionRecord,
    TrialArmDecisionStore,
    TrialStoreError,
)

import sys
from pathlib import Path

_KERNEL_TEST_DIR = Path(__file__).resolve().parents[1] / "kernel"
if str(_KERNEL_TEST_DIR) not in sys.path:
    sys.path.insert(0, str(_KERNEL_TEST_DIR))
from test_shadow_kernel import (  # noqa: E402 - crib (glue 测试同款引用面)
    HASH,
    _capital_checkpoint,
    _config,
    _deadlines,
    _paired_world,
    _regime_observation,
    _sap,
    _shared,
    _trial_manifest,
    _trial_policy,
)


def _empty_inputs():
    """零候选世界的双臂 kernel inputs (工厂单一入口)。"""

    champion, challenger, shared, *_ = _paired_world(candidates=())
    sizing = _config()
    champion_in, challenger_in = build_arm_kernel_inputs(
        validated=_validated_bundle(),
        shared_input=shared,
        candidates=(),
        champion_capital_checkpoint=champion.capital_checkpoint,
        challenger_capital_checkpoint=challenger.capital_checkpoint,
        deadlines=_deadlines(),
        sizing_config=sizing,
    )
    return champion_in, challenger_in, shared


def _legacy_reason_records(champion_input, challenger_input, shared, reason: BlockReason):
    """手工构造修复前语义的 pair records (历史行的形态学重建)。

    build_pair_records 接受 ArmDecision; NoTradeDecision 的
    kernel_input_hash 必须绑定真实 input hash, 与生产历史行
    (kernel_input_hash 有效、reason=CAPACITY_EXHAUSTED) 同构。
    """

    def _legacy(input_) -> NoTradeDecision:
        return NoTradeDecision(
            portfolio_id=input_.portfolio_id,
            signal_session=shared.signal_session,
            decision_cycle_id=shared.decision_cycle_id,
            reason=reason,
            kernel_input_hash=input_.content_hash(),
        )

    return build_pair_records(
        trial_id=shared.trial_id,
        session=shared.signal_session,
        cycle_id=shared.decision_cycle_id,
        shared_input=shared,
        regime_hash=HASH,
        champion=_legacy(champion_input),
        challenger=_legacy(challenger_input),
        trusted_at=shared.trusted_at,
        champion_input=champion_input,
        challenger_input=challenger_input,
    )


def _decide_pair(kernel: GrowthKernel, champion_input, challenger_input, shared):
    return build_pair_records(
        trial_id=shared.trial_id,
        session=shared.signal_session,
        cycle_id=shared.decision_cycle_id,
        shared_input=shared,
        regime_hash=HASH,
        champion=kernel.decide_shadow(champion_input),
        challenger=kernel.decide_shadow(challenger_input),
        trusted_at=shared.trusted_at,
        champion_input=champion_input,
        challenger_input=challenger_input,
    )


def _register(store: TrialArmDecisionStore, shared):
    from src.screening.offensive.v3.contracts import ExecutionMode
    from src.screening.offensive.v3.contracts.governance import PolicyActivation
    from src.screening.offensive.v3.contracts.regime import RegimeAdmissionMode
    from src.screening.offensive.v3.governance.regime_trial import RegimeTrialBundle
    from src.screening.offensive.v3.orchestration.genesis import (
        TrialGenesisManifest,
    )

    baseline = _trial_policy(RegimeAdmissionMode.IGNORE)
    target = _trial_policy(RegimeAdmissionMode.NORMAL_ONLY)
    trial = _trial_manifest(baseline, target)
    sap = _sap(trial)
    bundle = RegimeTrialBundle(
        baseline_policy=baseline,
        target_policy=target,
        trial_manifest=trial,
        sap_manifest=sap,
        baseline_policy_activation=PolicyActivation(
            portfolio_id="paper-v3",
            mode=ExecutionMode.DAILY_BAR_PROXY,
            policy_snapshot_hash=baseline.content_hash(),
            predecessor_policy_activation_hash="0" * 64,
            trust_bundle_hash=HASH,
            registry_epoch=1,
            policy_epoch=1,
            authority_epoch=1,
            risk_epoch=1,
            effective_from=shared.trusted_at,
            expires_at=shared.trusted_at + timedelta(days=120),
            issuer_id="governance.service",
            issuer_capability="governance.policy.activation.v1",
            schema_major=2,
        ),
    )
    genesis = TrialGenesisManifest(
        trial_id=trial.trial_id,
        normalized_genesis_hash=HASH,
        champion_normalized_hash=HASH,
        challenger_normalized_hash=HASH,
        champion_backup_root="b" * 64,
        challenger_backup_root="c" * 64,
        trial_manifest_hash="d" * 64,
        sap_manifest_hash="e" * 64,
        sealed_at=shared.trusted_at,
        schema_major=2,
    )
    store.register_trial(bundle, genesis)
    return trial


class TestReasonSemanticsChangeReplayBoundary:
    """对抗面 1: 行为变化的重放边界 (历史不可改写 fail-closed)。"""

    def test_post_fix_replay_of_legacy_capacity_session_conflicts(self, tmp_path):
        """生产历史行 (CAPACITY_EXHAUSTED) + 修复后重放同会话
        (NO_SIGNAL) → arm_decision_conflict, 绝不静默改写历史。"""

        champion_in, challenger_in, shared = _empty_inputs()
        legacy = _legacy_reason_records(
            champion_in, challenger_in, shared, BlockReason.CAPACITY_EXHAUSTED
        )
        store = TrialArmDecisionStore(database_path=str(tmp_path / "trial.sqlite3"))
        _register(store, shared)
        store.commit_pair(*legacy)  # 修复前历史行落库

        kernel = GrowthKernel(_config())
        fixed = _decide_pair(kernel, champion_in, challenger_in, shared)
        assert fixed[0].decision.reason is BlockReason.NO_SIGNAL  # 修复语义
        with pytest.raises(TrialStoreError) as exc_info:
            store.commit_pair(*fixed)
        assert exc_info.value.code == "arm_decision_conflict"

    def test_post_fix_same_reason_replay_stays_idempotent(self, tmp_path):
        """修复后同一冻结输入恰等重放幂等 (store 纪律在 NO_SIGNAL 下不变)。"""

        champion_in, challenger_in, shared = _empty_inputs()
        kernel = GrowthKernel(_config())
        fixed = _decide_pair(kernel, champion_in, challenger_in, shared)
        store = TrialArmDecisionStore(database_path=str(tmp_path / "trial.sqlite3"))
        _register(store, shared)
        receipt = store.commit_pair(*fixed)
        assert store.commit_pair(*fixed) == receipt


def _empty_inputs():
    """零候选世界的双臂 kernel inputs (工厂单一入口)。"""

    champion, challenger, shared, *_ = _paired_world(candidates=())
    sizing = _config()
    champion_in, challenger_in = build_arm_kernel_inputs(
        validated=_validated_bundle(),
        shared_input=shared,
        candidates=(),
        champion_capital_checkpoint=champion.capital_checkpoint,
        challenger_capital_checkpoint=challenger.capital_checkpoint,
        deadlines=_deadlines(),
        sizing_config=sizing,
    )
    return champion_in, challenger_in, shared


def _validated_bundle():
    from src.screening.offensive.v3.contracts.regime import RegimeAdmissionMode
    from src.screening.offensive.v3.orchestration.paired_trial import (
        ValidatedRegimeTrialBundle,
    )

    baseline = _trial_policy(RegimeAdmissionMode.IGNORE)
    target = _trial_policy(RegimeAdmissionMode.NORMAL_ONLY)
    trial = _trial_manifest(baseline, target)
    sap = _sap(trial)
    return ValidatedRegimeTrialBundle(
        champion_policy=baseline,
        challenger_policy=target,
        baseline_policy=baseline,
        target_policy=target,
        trial_manifest=trial,
        sap_manifest=sap,
        admission_delta=("producers.btst_regime_admission_mode",),
    )


class TestNoTradeGateOrdering:
    """对抗面 2: 零候选语义不吞更高优先级的 no-trade 门。"""

    def test_deadline_miss_survives_empty_candidates(self):
        champion_in, _, shared = _empty_inputs()
        missed = champion_in.model_copy(
            update={
                "shared": champion_in.shared.model_copy(
                    update={
                        "trusted_at": champion_in.shared.trusted_at
                        + timedelta(hours=2),
                    }
                )
            }
        )
        decision = GrowthKernel(_config()).decide_shadow(missed)
        assert decision.reason is BlockReason.DEADLINE_MISSED

    def test_empty_candidates_reports_no_signal_before_regime_gate(self):
        """零候选 + crisis regime: Challenger (NORMAL_ONLY) 报 NO_SIGNAL
        而非 REGIME_ADMISSION_BLOCKED — 无信号是更早的事实层判定,
        双臂同 reason 使 pair 分类 (count==0 先行短路) 不变。"""

        champion, challenger, *_ = _paired_world(
            regime_state=RegimeState.CRISIS, candidates=()
        )
        sizing = _config()
        kernel = GrowthKernel(sizing)
        champion_decision = kernel.decide_shadow(champion)
        challenger_decision = kernel.decide_shadow(challenger)
        assert champion_decision.reason is BlockReason.NO_SIGNAL
        assert challenger_decision.reason is BlockReason.NO_SIGNAL
