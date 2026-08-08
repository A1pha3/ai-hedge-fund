"""Plan 05 Task 9 S2a: ``InMemoryShadowStore`` — 进程级 ShadowDecision 内存 store。

同时实现两个鸭子类型端口:
- 写面 ``ShadowPersisterPort.publish_shadow_decision(decision) -> str``
  (``orchestration/daily_action_flow.py:249-252``, flow 在 shadow 决策产出后调用)。
- 读面 ``ShadowDecisionReader.active_shadow(portfolio_id, signal_session)``
  (``reporting/service.py:82-93``, reporting service 读回以派生
  ``ShadowDecisionSummary``)。

-------------------------------------------------------------------------------
为何是进程级内存 store (而非 JSONL/SQLite 持久化)
-------------------------------------------------------------------------------
Plan 05 是 shadow-only **ephemeral** 编排: 证据身份每进程临时
(``Ed25519PrivateKey.generate()``), capital ledger 每进程从 truth 重算, 整次
CLI 运行是一次性 shadow 观测。**跨进程持久化 ShadowDecision 无意义**, 且
pydantic 序列化 (``model_dump_json``) 会丢弃 flow epilogue 已构造好的注入句柄
(kernel/fake verifier 等), 无法做无依赖 round-trip。因此 Plan 05 的 store 语义
= 同进程内"写一次、读一次"的 flow→reporting 桥: flow persist 后, reporting
service 在同一进程内读回。跨进程持久化与 broker ACK 接线留待 Plan 06+ "真实上线"
(届时 ShadowDecision 会进 v3 evidence DB 的 shadow namespace)。

-------------------------------------------------------------------------------
契约
-------------------------------------------------------------------------------
- ``publish_shadow_decision`` 按 ``counterfactual_key`` 的
  ``(portfolio_id, signal_session)`` 索引; 返回 ``decision.shadow_decision_id``
  (确定性 id, ``f"shadow-{decision_cycle_id}"``, 同 signal_date 二次 run 幂等)。
- 同 ``(portfolio_id, signal_session)`` 重复 publish: last-write-wins,
  ``active_shadow`` 返回最新。
- 不同 portfolio / 不同 signal_session 互不影响。
- ``active_shadow`` 对无记录的 ``(portfolio_id, signal_session)`` 返回 ``None``
  (合法, 非失败 — reporting 对 None 的语义见 ``service.py``)。
"""

from __future__ import annotations

from datetime import date

from src.screening.offensive.v3.contracts.decision import ShadowDecision


class InMemoryShadowStore:
    """进程级 ShadowDecision 内存 store (flow 写面 + reporting 读面)。"""
    _by_key: dict[tuple[str, date], ShadowDecision]

    def __init__(self) -> None:
        self._by_key = {}

    def publish_shadow_decision(self, decision: ShadowDecision) -> str:
        """持久化一条 ShadowDecision, 返回其确定性 ``shadow_decision_id``。

        按 ``(counterfactual_key.portfolio_id, counterfactual_key.signal_session)``
        索引; 同键重复 publish 为 last-write-wins (同 signal_date 二次 run 幂等
        覆盖, 因 ``shadow_decision_id`` 确定性相同)。
        """
        key = (
            decision.counterfactual_key.portfolio_id,
            decision.counterfactual_key.signal_session,
        )
        self._by_key[key] = decision
        return decision.shadow_decision_id

    def active_shadow(
        self, portfolio_id: str, signal_session: date
    ) -> ShadowDecision | None:
        """读回 ``(portfolio_id, signal_session)`` 的 active ShadowDecision。

        无记录返回 ``None`` (该 signal_session 无持久化 shadow decision, 合法)。
        """
        return self._by_key.get((portfolio_id, signal_session))


__all__ = ["InMemoryShadowStore"]
