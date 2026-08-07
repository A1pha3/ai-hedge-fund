"""Plan 05 Task 9 S2 (RED): ``InMemoryShadowStore`` — ShadowDecision 进程级内存 store 契约。

背景: flow 的写面 ``ShadowPersisterPort.publish_shadow_decision(decision) -> str``
(orchestration/daily_action_flow.py:249-252) 与 reporting 的读面
``ShadowDecisionReader.active_shadow(portfolio_id, signal_session)``
(reporting/service.py:82-93) 目前都只有 Protocol、无生产实现。Plan 05 的 shadow
是 ephemeral — 证据身份每进程临时, capital ledger 进程内重算, 跨进程持久化无意义
且会丢注入句柄 — 因此主代理将在
``src/screening/offensive/v3/reporting/shadow_store.py`` 实现进程级内存 store
``InMemoryShadowStore``, 一个类同时满足写/读两个端口。该模块当前不存在 →
本文件整体 RED (ModuleNotFoundError), 由主代理实现 GREEN。

假设的方法签名 (供 GREEN 对齐):
- ``InMemoryShadowStore()`` — 无参构造;
- ``publish_shadow_decision(decision: ShadowDecision) -> str``
  — 返回 ``decision.shadow_decision_id``;
- ``active_shadow(portfolio_id: str, signal_session: date) -> ShadowDecision | None``
  — 无记录返回 ``None`` (合法 miss, 非失败)。

索引契约 (键 = ``counterfactual_key.(portfolio_id, signal_session)``;
header ``portfolio_id`` 与 key 内 portfolio 由 ShadowDecision validator 保证一致):
a. publish 存入后可按 (portfolio_id, signal_session) 读回同一对象;
b. 同键重复 publish 幂等/替换 — ``active_shadow`` 返回最近一次 publish 的决策
   (last-write-wins);
c. 不同 portfolio_id 或不同 signal_session 的键互不影响;
d. 无记录的 (portfolio_id, signal_session) → ``None``;
e. publish 返回值 == ``decision.shadow_decision_id``;
f. store 结构满足 ``ShadowDecisionReader`` runtime Protocol (reporting 读面)。

``_make_shadow_decision`` 的字段构造镜像 flow 的 ``_build_shadow_decision`` /
``_build_shadow_line`` / ``_shadow_issuer_binding`` (daily_action_flow.py:687-842),
满足 ``ShadowDecision.validate_shadow`` 全部不变量 (contracts/decision.py:1080):
key↔header portfolio 一致 / target_entry_session > signal_session /
available_at >= created_at / line id 唯一且字典序 / line 8 字段与 header 一致 /
line stage 5 字段与 shadow_stage_binding 一致 / issuer capability 五元组匹配。
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from src.screening.offensive.v3.contracts import ArtifactKind, ExecutionMode
from src.screening.offensive.v3.contracts.decision import (
    CounterfactualDecisionKey,
    ShadowDecision,
    ShadowIssuerBinding,
    ShadowOrderLine,
    ShadowStageBinding,
)
from src.screening.offensive.v3.reporting.service import ShadowDecisionReader
from src.screening.offensive.v3.reporting.shadow_store import InMemoryShadowStore

UTC = timezone.utc
NOW = datetime(2026, 8, 5, 15, 30, tzinfo=UTC)  # 决策 created_at (收盘后)
SIGNAL_DATE = date(2026, 8, 5)
PORTFOLIO = "paper-v3"
HASH = "a" * 64
ARTIFACT_HASH = "b" * 64
PAYLOAD_HASH = "c" * 64
FAMILY = "btst.limit-up-breakout"


def _make_shadow_decision(
    *,
    portfolio_id: str = PORTFOLIO,
    signal_session: date = SIGNAL_DATE,
    shadow_decision_id: str = "shadow-1",
    counterfactual_cycle_id: str = "daily-action-2026-08-05",
    created_at: datetime = NOW,
    shadow_line_id: str = "shadow-line-300001",
    security_id: str = "300001.SZ",
) -> ShadowDecision:
    """构造一份通过 ``validate_shadow`` 全部校验的最小合法 ShadowDecision。

    参数化 portfolio_id / signal_session / shadow_decision_id / created_at 以支撑
    同键替换与跨键隔离测试; line 经济学满足
    ``reserve == worst_case_price * qty + fee`` (1050*100+315) 与整手约束。
    """
    stage_binding = ShadowStageBinding(
        research_program_id="prog-1",
        economic_lineage_id="eline-1",
        stage_id="stage-1",
        trial_id="trial-1",
        stage_manifest_hash=HASH,
    )
    line = ShadowOrderLine(
        shadow_line_id=shadow_line_id,
        security_id=security_id,
        producer_namespace="btst",
        family_id=FAMILY,
        economic_lineage_id="eline-1",
        research_program_id="prog-1",
        stage_id="stage-1",
        trial_id="trial-1",
        stage_manifest_hash=HASH,
        evidence_id=f"btst:shadow:{shadow_line_id}",
        evidence_artifact_hash=ARTIFACT_HASH,
        evidence_payload_hash=PAYLOAD_HASH,
        target_quantity_units=100,
        lot_size_units=100,
        lot_rule_version="cn-a-share-lot.v1",
        order_type="LIMIT",
        limit_price_cents=1050,
        worst_case_price_cents=1050,
        price_boundary_version="cn-price-limit.v1",
        time_in_force="OPEN_AUCTION",
        exit_session_ordinal=10,
        estimated_fee_cents=315,
        estimated_cash_reserve_cents=1050 * 100 + 315,
        cost_assumption_version="cn-a-share-costs.v1",
        execution_assumption_version="btst.funnel.v1",
    )
    issuer = ShadowIssuerBinding(
        issuer_id="growth-kernel.shadow.service",
        key_id="shadow-key-1",
        capability_artifact_kind=ArtifactKind.SHADOW_DECISION,
        capability_namespace="growth-kernel.shadow.v1",
        capability_mode=ExecutionMode.DAILY_BAR_PROXY,
        capability_schema_major=2,
        capability_version="growth-kernel-shadow.v1",
        capability_scope=f"portfolio:{portfolio_id}",
        verification_result="VALID",
        verified_at=created_at,
        valid_until=created_at + timedelta(days=1),
        trust_bundle_hash=HASH,
        registry_epoch=1,
    )
    return ShadowDecision(
        artifact_kind=ArtifactKind.SHADOW_DECISION,
        artifact_namespace="growth-kernel.shadow.v1",
        schema_major=2,
        shadow_decision_id=shadow_decision_id,
        counterfactual_key=CounterfactualDecisionKey(
            portfolio_id=portfolio_id,
            signal_session=signal_session,
            counterfactual_cycle_id=counterfactual_cycle_id,
        ),
        portfolio_id=portfolio_id,
        mode=ExecutionMode.DAILY_BAR_PROXY,
        target_entry_session=signal_session + timedelta(days=1),
        producer_namespace="btst",
        family_id=FAMILY,
        research_program_id="prog-1",
        economic_lineage_id="eline-1",
        stage_id="stage-1",
        trial_id="trial-1",
        policy_activation_hash=HASH,
        policy_epoch=1,
        evidence_set_merkle_root=HASH,
        shadow_stage_binding=stage_binding,
        counterfactual_lines=(line,),
        cost_assumption_version="cn-a-share-costs.v1",
        execution_assumption_version="btst.funnel.v1",
        created_at=created_at,
        available_at=created_at,
        execution_authority="NONE",
        issuer_binding=issuer,
    )


# --------------------------------------------------------------------------
# 契约测试 (a)-(f)
# --------------------------------------------------------------------------


def test_publish_returns_shadow_decision_id() -> None:
    """契约 (e): publish 返回值 == decision.shadow_decision_id。"""
    store = InMemoryShadowStore()
    decision = _make_shadow_decision(shadow_decision_id="shadow-x")

    returned = store.publish_shadow_decision(decision)

    assert returned == "shadow-x"
    assert returned == decision.shadow_decision_id


def test_active_shadow_returns_published_decision() -> None:
    """契约 (a): publish 后按 (portfolio_id, signal_session) 读回同一对象。"""
    store = InMemoryShadowStore()
    decision = _make_shadow_decision()
    store.publish_shadow_decision(decision)

    active = store.active_shadow(PORTFOLIO, SIGNAL_DATE)

    assert active is decision
    assert active is not None
    assert active.shadow_decision_id == decision.shadow_decision_id


def test_active_shadow_unknown_key_returns_none() -> None:
    """契约 (d): 无记录的 (portfolio_id, signal_session) → None (合法 miss)。"""
    store = InMemoryShadowStore()

    # 空 store → None
    assert store.active_shadow(PORTFOLIO, SIGNAL_DATE) is None
    # 有记录但键不同 → 仍 None
    store.publish_shadow_decision(_make_shadow_decision())
    assert store.active_shadow("other-portfolio", SIGNAL_DATE) is None
    assert store.active_shadow(PORTFOLIO, date(2026, 8, 6)) is None


def test_republish_same_key_replaces_active_with_latest() -> None:
    """契约 (b): 同 portfolio_id+signal_session 重复 publish → 替换, 返回最新。"""
    store = InMemoryShadowStore()
    first = _make_shadow_decision(shadow_decision_id="shadow-1")
    second = _make_shadow_decision(
        shadow_decision_id="shadow-2",
        created_at=NOW + timedelta(hours=1),
    )

    assert store.publish_shadow_decision(first) == "shadow-1"
    assert store.active_shadow(PORTFOLIO, SIGNAL_DATE) is first
    # 同键再 publish → active 指向最新 publish 的决策 (last-write-wins)
    assert store.publish_shadow_decision(second) == "shadow-2"
    assert store.active_shadow(PORTFOLIO, SIGNAL_DATE) is second
    # 幂等: 同一对象重复 publish 不报错, active 不变
    assert store.publish_shadow_decision(second) == "shadow-2"
    assert store.active_shadow(PORTFOLIO, SIGNAL_DATE) is second


def test_different_portfolios_are_isolated() -> None:
    """契约 (c): 同 signal_session 不同 portfolio_id 的键互不影响。"""
    store = InMemoryShadowStore()
    decision_a = _make_shadow_decision(
        portfolio_id="paper-v3", shadow_decision_id="shadow-a"
    )
    decision_b = _make_shadow_decision(
        portfolio_id="paper-v4", shadow_decision_id="shadow-b"
    )
    store.publish_shadow_decision(decision_a)
    store.publish_shadow_decision(decision_b)

    assert store.active_shadow("paper-v3", SIGNAL_DATE) is decision_a
    assert store.active_shadow("paper-v4", SIGNAL_DATE) is decision_b


def test_different_signal_sessions_are_isolated() -> None:
    """契约 (c): 同 portfolio_id 不同 signal_session 的键互不影响。"""
    store = InMemoryShadowStore()
    day1 = date(2026, 8, 5)
    day2 = date(2026, 8, 6)
    decision_d1 = _make_shadow_decision(
        signal_session=day1, shadow_decision_id="shadow-d1"
    )
    decision_d2 = _make_shadow_decision(
        signal_session=day2,
        shadow_decision_id="shadow-d2",
        counterfactual_cycle_id="daily-action-2026-08-06",
        created_at=NOW + timedelta(days=1),
    )
    store.publish_shadow_decision(decision_d1)
    store.publish_shadow_decision(decision_d2)

    assert store.active_shadow(PORTFOLIO, day1) is decision_d1
    assert store.active_shadow(PORTFOLIO, day2) is decision_d2


def test_store_satisfies_shadow_decision_reader_protocol() -> None:
    """契约 (f): store 结构满足 reporting 读面 ``ShadowDecisionReader`` Protocol。"""
    store = InMemoryShadowStore()

    assert isinstance(store, ShadowDecisionReader)
