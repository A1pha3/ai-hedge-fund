"""⑦ 胶水测试 — replay_assembly ↔ SessionLifecycleDriver 正式汇合点 (2026-08-20).

两条平行抽象在此显式汇合 (终轮审查 P3-b): replay_assembly (Phase 5b,
证据记录 → ReplaySessionFacts) 与 session_driver (Phase 6, OpenLine +
bar_for 回调 → 结算/收盘估值/守恒) 互不直接消费。汇合点不是隐式
lambda, 而是 ``replay_assembly.evidence_backed_bar_for`` —— 第三轮遗留
项收口起升入 src (签名只接受证据仓库与已发布 bar-set 证据记录, 调用方
无法绕过证据时间轴; P3-a 源契约的 blessed 实现), 本文件只消费不再
自定义。

断言面四件 (写码前钉死): pair 幂等 / 映射后 lines 与 kernel 行逐字段
一致 / 驱动器守恒 / nav_projections() 非空。fixture 世界模块级构建一次
(kernel/bundle/checkpoint 构造重); crib 源 test_shadow_kernel.py:814-839
(checkpoint-v2 绿色调用法), 不触 run_official (其标注 RETAINED-SPEC
STALENESS, 待特权 worker 重写)。
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.screening.offensive.v3.capital.fills import FillAttribution
from src.screening.offensive.v3.capital.flows import GenesisRequest
from src.screening.offensive.v3.capital.identity import AccountBinding
from src.screening.offensive.v3.capital.repository import CapitalRepository
from src.screening.offensive.v3.contracts import ExecutionMode, SUPPORTED_SCHEMA_MAJOR
from src.screening.offensive.v3.contracts.base import SignalStage
from src.screening.offensive.v3.contracts.btst_candidate import (
    BtstCandidateIndustryState,
    BtstRawCandidatePayload,
)
from src.screening.offensive.v3.contracts.decision import ShadowDecision
from src.screening.offensive.v3.contracts.evidence import (
    EvidenceRecord,
    EvidenceScope,
    SignalEvidence,
)
from src.screening.offensive.v3.contracts.governance import PolicyActivation
from src.screening.offensive.v3.contracts.regime import RegimeAdmissionMode, RegimeState
from src.screening.offensive.v3.contracts.trial import TrialArm
from src.screening.offensive.v3.evidence.offline_rig import build_offline_evidence_rig
from src.screening.offensive.v3.execution.lifecycle import DailyBar, OpenExecutionVerdict
from src.screening.offensive.v3.governance.regime_trial import (
    RegimeTrialBundle,
    ValidatedRegimeTrialBundle,
)
from src.screening.offensive.v3.kernel.decide import GrowthKernel
from src.screening.offensive.v3.kernel.models import (
    ShadowCapitalCheckpoint,
    ShadowKernelInput,
    ShadowSharedInput,
)
from src.screening.offensive.v3.orchestration.arm_lifecycle import CURRENT_COST_SCENARIO
from src.screening.offensive.v3.orchestration.genesis import TrialGenesisManifest
from src.screening.offensive.v3.orchestration.paired_trial import (
    CommittedBtstCandidate,
    build_arm_kernel_inputs,
    build_pair_records,
)
from src.screening.offensive.v3.orchestration.replay_assembly import (
    evidence_backed_bar_for,
)
from src.screening.offensive.v3.orchestration.session_driver import (
    UNCONDITIONAL_EXIT_LIMIT_CENTS,
    SessionLifecycleDriver,
    open_line_from_shadow_line,
)
from src.screening.offensive.v3.orchestration.trial_store import (
    TrialArmDecisionRecord,
    TrialArmDecisionStore,
    TrialStoreError,
)

# crib: 复用 kernel 测试的冻结世界构造器 (模块级共享, 只读)
_KERNEL_TEST_DIR = Path(__file__).resolve().parents[1] / "kernel"
if str(_KERNEL_TEST_DIR) not in sys.path:
    sys.path.insert(0, str(_KERNEL_TEST_DIR))
from test_shadow_kernel import (  # noqa: E402
    CUTOFF,
    HASH,
    PORTFOLIO,
    SIGNAL_DATE,
    TRADING_SESSIONS,
    _capital_checkpoint,
    _config,
    _deadlines,
    _regime_observation,
    _sap,
    _shared,
    _trial_manifest,
    _trial_policy,
)

UTC = timezone.utc
SECURITY_ID = "300001.SZ"
CANDIDATE_ID = "btst:snap-1:300001:btst_breakout"
#: 驱动器会话序列 = 信号日 + 排程的 10 个后继会话 + 两个后验估值日
DRIVER_SESSIONS = (
    SIGNAL_DATE,
    *TRADING_SESSIONS,
    date(2026, 8, 20),
    date(2026, 8, 21),
)
ATTR = FillAttribution(
    producer_namespace="btst",
    research_program_id="prog-1",
    economic_lineage_id="eline-1",
    stage_id="stage-1",
)


# ---------------------------------------------------------------------------
# P3-b: 汇合点已升入 src (replay_assembly.evidence_backed_bar_for) —
# 本文件自此只消费, 不再持有本地定义 (第三轮遗留项收口)。
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 模块级 fixture 世界: 构建一次, 全部纯数据/纯函数, 无 I/O
# ---------------------------------------------------------------------------


def _committed_candidate() -> CommittedBtstCandidate:
    """一个手工绑定的 SELECTED 候选 (记录↔载荷四重绑定经构造器校验)。

    entry_price 取 ¥1.00 (crib test_risk 同款低价位锚): 保证整手截断后
    数量仍 ≥1 手, 夹具常数漂移会在映射断言处响亮失败而非静默归零。
    """
    payload = BtstRawCandidatePayload(
        payload_kind="btst_raw_candidate",
        schema_major=1,
        candidate_id=CANDIDATE_ID,
        producer_namespace="btst",
        security_id=SECURITY_ID,
        signal_stage=SignalStage.SELECTED,
        signal_session=SIGNAL_DATE,
        entry_price_micros=1_000_000,  # ¥1.00 (1 元 = 1e6 micros; 100_000 是 ¥0.10)
        setup="btst_breakout",
        setup_version="v2",
        target_weight_ppm=100_000,
        trigger_strength_ppm=900_000,
        priority=1,
        industry_state=BtstCandidateIndustryState.KNOWN,
        industry="electronics",
        snapshot_id="snap-1",
        setup_consumed_fingerprint="sha256:" + "a" * 64,
        strategy_semver="0.1.0",
        behavior_fingerprint=HASH,
        execution_version="btst.funnel.v1",
        cost_version="cn-a-share-costs.v1",
    )
    envelope = SignalEvidence(
        evidence_id=f"{CANDIDATE_ID}:selected",
        subject_scope=EvidenceScope.STRATEGY_LINEAGE,
        subject_producer="btst",
        family_id="btst:snap-1",
        strategy_semver="0.1.0",
        behavior_fingerprint=HASH,
        policy_epoch=1,
        execution_version="btst.funnel.v1",
        cost_version="cn-a-share-costs.v1",
        effective_at=CUTOFF,
        provider_published_at=CUTOFF,
        observed_at=CUTOFF,
        available_at=CUTOFF,
        mode=ExecutionMode.DAILY_BAR_PROXY,
        source_authority="btst.producer",
        payload_content_hash=payload.content_hash(),
        schema_major=SUPPORTED_SCHEMA_MAJOR,
        evidence_kind="signal",
        stage=SignalStage.SELECTED,
    )
    record = EvidenceRecord[SignalEvidence](
        evidence=envelope,
        ingested_at=CUTOFF,
        commit_sequence=1,
        revision=1,
        supersedes_revision=None,
        active_revision=1,
    )
    return CommittedBtstCandidate(record=record, payload=payload)


@dataclass(frozen=True)
class _GlueWorld:
    validated: ValidatedRegimeTrialBundle
    registration_bundle: RegimeTrialBundle
    genesis_manifest: TrialGenesisManifest
    shared: ShadowSharedInput
    champion_checkpoint: ShadowCapitalCheckpoint
    challenger_checkpoint: ShadowCapitalCheckpoint
    kernel: GrowthKernel
    champion_input: ShadowKernelInput
    challenger_input: ShadowKernelInput
    champion_decision: ShadowDecision
    challenger_decision: ShadowDecision
    pair_records: tuple[TrialArmDecisionRecord, TrialArmDecisionRecord]


def _build_world() -> _GlueWorld:
    baseline = _trial_policy(RegimeAdmissionMode.IGNORE)
    target = _trial_policy(RegimeAdmissionMode.NORMAL_ONLY)
    trial = _trial_manifest(baseline, target)
    sap = _sap(trial)
    shared = _shared(
        trial=trial, sap=sap, regime=_regime_observation(RegimeState.NORMAL)
    )
    validated = ValidatedRegimeTrialBundle(
        champion_policy=baseline,
        challenger_policy=target,
        baseline_policy=baseline,
        target_policy=target,
        trial_manifest=trial,
        sap_manifest=sap,
        admission_delta=("producers.btst_regime_admission_mode",),
    )
    registration_bundle = RegimeTrialBundle(
        baseline_policy=baseline,
        target_policy=target,
        trial_manifest=trial,
        sap_manifest=sap,
        baseline_policy_activation=PolicyActivation(
            portfolio_id=PORTFOLIO,
            mode=ExecutionMode.DAILY_BAR_PROXY,
            policy_snapshot_hash=baseline.content_hash(),
            predecessor_policy_activation_hash="0" * 64,
            trust_bundle_hash=HASH,
            registry_epoch=1,
            policy_epoch=1,
            authority_epoch=1,
            risk_epoch=1,
            effective_from=CUTOFF,
            expires_at=shared.trusted_at + timedelta(days=120),
            issuer_id="governance.service",
            issuer_capability="governance.policy.activation.v1",
            schema_major=2,
        ),
    )
    genesis_manifest = TrialGenesisManifest(
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
    capital = _capital_checkpoint()
    champion_checkpoint = ShadowCapitalCheckpoint(
        trial_id=trial.trial_id,
        arm=TrialArm.CHAMPION,
        portfolio_id=PORTFOLIO,
        mode=ExecutionMode.DAILY_BAR_PROXY,
        capital_store_id=f"{trial.trial_id}:CHAMPION:capital",
        trial_genesis_manifest_hash="1" * 64,
        arm_capital_genesis_root="2" * 64,
        capital_snapshot_hash=capital.content_hash(),
        capital_snapshot=capital,
    )
    challenger_checkpoint = ShadowCapitalCheckpoint(
        trial_id=trial.trial_id,
        arm=TrialArm.CHALLENGER,
        portfolio_id=PORTFOLIO,
        mode=ExecutionMode.DAILY_BAR_PROXY,
        capital_store_id=f"{trial.trial_id}:CHALLENGER:capital",
        trial_genesis_manifest_hash="1" * 64,
        arm_capital_genesis_root="3" * 64,
        capital_snapshot_hash=capital.content_hash(),
        capital_snapshot=capital,
    )
    sizing = _config()
    kernel = GrowthKernel(sizing)
    champion_input, challenger_input = build_arm_kernel_inputs(
        validated=validated,
        shared_input=shared,
        candidates=(_committed_candidate(),),
        champion_capital_checkpoint=champion_checkpoint,
        challenger_capital_checkpoint=challenger_checkpoint,
        deadlines=_deadlines(),
        sizing_config=sizing,
    )
    champion_decision = kernel.decide_shadow(champion_input)
    challenger_decision = kernel.decide_shadow(challenger_input)
    pair_records = build_pair_records(
        trial_id=trial.trial_id,
        session=shared.signal_session,
        cycle_id=shared.decision_cycle_id,
        shared_input=shared,
        regime_hash=HASH,
        champion=champion_decision,
        challenger=challenger_decision,
        trusted_at=shared.trusted_at,
        champion_input=champion_input,
        challenger_input=challenger_input,
    )
    return _GlueWorld(
        validated=validated,
        registration_bundle=registration_bundle,
        genesis_manifest=genesis_manifest,
        shared=shared,
        champion_checkpoint=champion_checkpoint,
        challenger_checkpoint=challenger_checkpoint,
        kernel=kernel,
        champion_input=champion_input,
        challenger_input=challenger_input,
        champion_decision=champion_decision,
        challenger_decision=challenger_decision,
        pair_records=pair_records,
    )


WORLD: _GlueWorld = _build_world()


# ---------------------------------------------------------------------------
# 断言面 1: pair 幂等
# ---------------------------------------------------------------------------


def test_pair_exact_replay_is_idempotent_and_divergence_conflicts(tmp_path):
    """同一冻结输入 → 逐字节相同 pair; 恰等重放幂等, 背离重放冲突。"""
    store = TrialArmDecisionStore(database_path=str(tmp_path / "trial.sqlite3"))
    store.register_trial(WORLD.registration_bundle, WORLD.genesis_manifest)
    receipt = store.commit_pair(*WORLD.pair_records)
    assert store.commit_pair(*WORLD.pair_records) == receipt  # 恰等重放幂等

    # 冻结输入完全重建 (纯构造器) → replay 复现 official 逐字节
    sizing = _config()
    rebuilt_champion, rebuilt_challenger = build_arm_kernel_inputs(
        validated=WORLD.validated,
        shared_input=WORLD.shared,
        candidates=(_committed_candidate(),),
        champion_capital_checkpoint=WORLD.champion_checkpoint,
        challenger_capital_checkpoint=WORLD.challenger_checkpoint,
        deadlines=_deadlines(),
        sizing_config=sizing,
    )
    rebuilt_records = build_pair_records(
        trial_id=WORLD.shared.trial_id,
        session=WORLD.shared.signal_session,
        cycle_id=WORLD.shared.decision_cycle_id,
        shared_input=WORLD.shared,
        regime_hash=HASH,
        champion=GrowthKernel(sizing).decide_shadow(rebuilt_champion),
        challenger=GrowthKernel(sizing).decide_shadow(rebuilt_challenger),
        trusted_at=WORLD.shared.trusted_at,
        champion_input=rebuilt_champion,
        challenger_input=rebuilt_challenger,
    )
    assert rebuilt_records == WORLD.pair_records
    assert store.commit_pair(*rebuilt_records) == receipt

    # 同键不同内容 → 类型化冲突, 不是静默覆盖
    mutated = WORLD.pair_records[0].model_copy(
        update={"arm_capital_checkpoint_hash": "f" * 64}
    )
    with pytest.raises(TrialStoreError, match="arm_decision_conflict"):
        store.commit_pair(mutated, WORLD.pair_records[1])


# ---------------------------------------------------------------------------
# 断言面 2: 映射后 lines 与 kernel 行逐字段一致
# ---------------------------------------------------------------------------


def test_mapped_open_lines_match_kernel_rows_field_by_field():
    """kernel 影子行 → OpenLine: 全部八个字段逐一断言, 无一凭映射函数自证。"""
    decision = WORLD.champion_decision
    lines = decision.counterfactual_lines
    assert lines, "fixture 世界必须产出至少一条 kernel 影子行 (否则断言空转)"
    assert decision.target_entry_session == TRADING_SESSIONS[0]  # T+1 开盘入场
    for line in lines:
        o = open_line_from_shadow_line(
            line, entry_session=decision.target_entry_session
        )
        assert o.decision_id == line.shadow_line_id
        assert o.security_id == line.security_id
        assert o.quantity == line.target_quantity_units
        assert o.limit_price_cents == line.limit_price_cents  # 入场限价 = 买上限
        assert o.exit_limit_price_cents == UNCONDITIONAL_EXIT_LIMIT_CENTS
        assert o.exit_session == line.target_exit_session  # 排程日期是权威
        assert o.position_lineage_id == f"shadow:{line.shadow_line_id}"
        assert o.economic_lot_id == f"lot:{line.shadow_line_id}"
    assert lines[0].target_exit_session == TRADING_SESSIONS[9]  # T+10 冻结排程
    assert lines[0].target_quantity_units >= 100  # ≥1 手: 夹具量非平凡锚


# ---------------------------------------------------------------------------
# 断言面 3 + 4: 驱动器守恒 / nav_projections() 非空 (全链过汇合点)
# ---------------------------------------------------------------------------


def _bar(session: date) -> DailyBar:
    # 创业板 20% 围栏锚在 ¥1.00 前收: 120/80; 开盘 99 < 入场买上限可成交
    return DailyBar(
        security_id=SECURITY_ID,
        session=session,
        open_cents=99,
        high_cents=101,
        low_cents=98,
        close_cents=100,
        limit_up_cents=120,
        limit_down_cents=80,
    )


def _capital_repo(tmp_path: Path) -> CapitalRepository:
    t = datetime(SIGNAL_DATE.year, SIGNAL_DATE.month, SIGNAL_DATE.day, 9, 30, tzinfo=UTC)
    repository = CapitalRepository.initialize(tmp_path / "capital.sqlite3")
    repository.initialize_genesis(
        GenesisRequest(
            idempotency_key="genesis-glue",
            account_binding=AccountBinding(
                portfolio_id=PORTFOLIO,
                mode=ExecutionMode.DAILY_BAR_PROXY,
                broker_account_id=None,
                base_currency="CNY",
                environment_fingerprint=None,
            ),
            unit_quanta=10_000,
            unit_price_numerator=1_000,
            unit_price_denominator=1,
            source_authority="test.seed",
            authorization_reference="auth-1",
            effective_at=t,
            as_of=t,
        )
    )
    return repository


def test_glue_full_cycle_evidence_bars_to_conservation_and_nav(tmp_path):
    """bar-set 证据 → 汇合点适配 → 驱动器全周期: 守恒 + NAV 序列非空。"""
    rig = build_offline_evidence_rig(
        database_path=tmp_path / "evidence.sqlite3",
        blobs_dir=tmp_path / "blobs",
        namespace="market-bars",
    )
    bar_records = {
        session: rig.bar_publisher.publish(
            session=session, bars={SECURITY_ID: _bar(session)}
        )
        for session in TRADING_SESSIONS
    }
    bar_for = evidence_backed_bar_for(rig.repository, bar_records)
    # 汇合点源契约的测试面: bar 只来自已发布证据记录, 未发布会话无 bar
    served = bar_for(TRADING_SESSIONS[0], SECURITY_ID)
    assert served is not None and served.session == TRADING_SESSIONS[0]
    assert bar_for(SIGNAL_DATE, SECURITY_ID) is None

    decision = WORLD.champion_decision
    entry_session = decision.target_entry_session
    lines = tuple(
        open_line_from_shadow_line(line, entry_session=entry_session)
        for line in decision.counterfactual_lines
    )
    repository = _capital_repo(tmp_path)
    result = SessionLifecycleDriver(
        repository=repository,
        arm="champion",
        scenario=CURRENT_COST_SCENARIO,
        sessions=DRIVER_SESSIONS,
        entries_by_session={entry_session: lines},
        attribution=ATTR,
        command_at=lambda s: datetime(s.year, s.month, s.day, 9, 30, tzinfo=UTC),
        send_deadline=lambda s: datetime(s.year, s.month, s.day, 10, 0, tzinfo=UTC),
        bar_for=bar_for,
    ).run()

    exit_session = lines[0].exit_session
    entry = result.settlements[(entry_session, SECURITY_ID, "entry")]
    assert entry.verdict is OpenExecutionVerdict.FILLED and entry.fill_receipt is not None
    exit_s = result.settlements[(exit_session, SECURITY_ID, "exit")]
    assert exit_s.verdict is OpenExecutionVerdict.FILLED
    assert result.open_at_end == {}  # T+10 全周期平仓, 无悬挂持仓
    assert result.conservation_ok, result.conservation_details  # 断言面 3

    path = repository.nav_projections()
    # 断言面 4: NAV 序列非空 → 精确钉死: genesis(1) + 每驱动会话(13) 各一条,
    # 成交/费用不另增 NAV 观察行; 干净全周期无 restatement
    assert len(path.as_observed) == 1 + len(DRIVER_SESSIONS)
    assert path.as_observed[0].nav_cents == 10_000_000  # genesis NAV 与 checkpoint 同源锚
    assert all(o.nav_cents > 0 for o in path.as_observed)
    assert path.restated_final == ()
