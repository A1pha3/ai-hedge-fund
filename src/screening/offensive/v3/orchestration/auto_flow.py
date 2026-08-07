"""Plan 05 Task 6: AutoFlow — --auto 独立 shadow 编排。

三步 sequential 独立提交 (无跨步回滚, 前步失败不阻止后步; 后步失败不回填
前步、不伪装全成功), 只由 loaded candidate policy 的 ``runtime_mode`` 投影
控制。三步:

1. ``snapshot``    — ``load_verified_daily_action_snapshot(signal_date, *,
                     reports_dir=, data_dir=)`` → ``VerifiedSnapshotResult``;
                     成功 = ``result.snapshot is not None``; 失败 =
                     ``snapshot is None`` + ``global_reason`` (manifest
                     缺失/无效), 或加载抛异常。
2. ``outcome``     — ``outcome_finalizer.finalize_due(as_of, program=)``;
                     成功 = 返回任意 tuple (含空 tuple — rerun 幂等形态);
                     失败 = 抛 ``OutcomeFinalizerError`` /
                     ``EvidenceStoreError`` / ``DependencyFixError``
                     (``fence_not_active`` correction pending fence)。
3. ``auto_shadow`` — ``auto_producer.produce_and_publish(snapshot)``;
                     成功 = 返回 records; 失败 = ``AutoProducerApiError``
                     (``AUTO_PRODUCER_NOT_SHADOW`` gate) /
                     ``EvidenceStoreError``。只在 snapshot 成功
                     (snapshot 非 None) 时执行。

状态值域 (每步独立, ``AutoFlowResult`` 三个字段):
- ``"ok"``      — 该步被尝试且未抛异常 (outcome 空 tuple 也是 ok)。
- ``"failed"``  — 该步被尝试但抛异常 (snapshot 失败 = loader 返回 None
                  或抛异常)。
- ``"skipped"`` — 该步未被尝试: OFF 模式 (三步全 skipped), 或
                  auto_shadow 步无输入 (reason ``"no_snapshot"``) /
                  投影 mode 非 SHADOW (reason ``"not_shadow_mode"``)。

``execution_authority`` 恒为 ``"none"`` — 本编排永远不产生任何授权 (镜像
``ShadowDecision.execution_authority: Literal["NONE"]`` 语义,
contracts/decision.py:1077: shadow 恒无授权)。

``failure_reason: Mapping[str, str]`` — key = 步名
``"snapshot" | "outcome" | "auto_shadow"``; 值 = 机器可读原因:
- 异常: ``f"{type(exc).__name__}: {exc}"`` (异常 ``__str__`` 携带稳定
  error code, 如 ``OutcomeFinalizerError`` code 或 ``DependencyFixError``
  的 ``fence_not_active``);
- snapshot 加载失败: ``global_reason`` (为空时 ``"snapshot_unavailable"``);
- skip: ``"no_snapshot"`` / ``"not_shadow_mode"``。
ok 步无条目; OFF 模式整体无条目。

mode 投影 (run() 第一件事 = ``mode_provider()``):
- ``RuntimeMode.OFF`` → 三步全 ``"skipped"``, 零 v3 调用, 不做任何
  snapshot/outcome/producer 调用 (legacy 行为不变; 现有 legacy cache
  refresh 仍是显式独立步骤)。
- ``RuntimeMode.SHADOW`` → 依次独立执行三步, 每步 try/except 捕获自身
  异常记入对应 status/reason, 绝不因一步失败跳过或回滚其他步。
- 其他模式 (``BTST_CANARY`` / ``AUTHORITATIVE``) → snapshot/outcome 照常
  执行 (快照加载是只读校验, outcome 是 mode-pure 证据累积), auto_shadow
  步 flow 层 ``"skipped"`` + reason ``"not_shadow_mode"`` — 不调用
  producer; producer 自身 fail-closed gate (``AUTO_PRODUCER_NOT_SHADOW``)
  是纵深防御 (Task 5 已单独覆盖)。

outcome 步的 ``as_of`` = ``datetime.combine(signal_date, time(15, 0,
tzinfo=timezone.utc))`` — signal_date 15:00 UTC, 与 Task 5 信封时间链
起点约定一致。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timezone
from pathlib import Path
from types import MappingProxyType
from typing import Callable, Literal, Mapping, Protocol

from src.screening.offensive.daily_action_snapshot import (
    load_verified_daily_action_snapshot,
    VerifiedDailyActionSnapshot,
    VerifiedSnapshotResult,
)
from src.screening.offensive.v3.policy.models import RuntimeMode
from src.screening.offensive.v3.services.auto_producer_api import AutoProducerApi


class SnapshotLoader(Protocol):
    """注入的快照加载器 — 与 ``load_verified_daily_action_snapshot`` 同签名。"""

    def __call__(self, signal_date: date, *, reports_dir: Path, data_dir: Path) -> VerifiedSnapshotResult: ...


class OutcomeFinalizerPort(Protocol):
    """鸭子类型 outcome finalizer — flow 只依赖 ``finalize_due``。

    真实实现 ``OutcomeFinalizerService`` 还暴露 ``outcome_fact``, 本 flow
    不使用。测试注入轻量 fake 控制成功/失败/抛 fence 错。
    """

    def finalize_due(self, as_of: datetime, *, program: str) -> tuple[str, ...]: ...


@dataclass(frozen=True)
class AutoFlowResult:
    """一次 ``AutoFlow.run`` 的三步独立结果汇总。

    字段:
    - ``snapshot_status`` / ``outcome_status`` / ``auto_shadow_status``:
      值域 ``"ok" | "failed" | "skipped"`` (语义见模块 docstring)。
    - ``execution_authority``: 恒 ``"none"`` — 本编排永不产生授权。
    - ``failure_reason``: 失败/跳过步的机器可读原因 (key = 步名)。
    """

    snapshot_status: Literal["ok", "failed", "skipped"]
    outcome_status: Literal["ok", "failed", "skipped"]
    auto_shadow_status: Literal["ok", "failed", "skipped"]
    execution_authority: Literal["none"] = "none"
    failure_reason: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}))


class AutoFlow:
    """--auto 独立 shadow 编排: 三步 sequential 独立提交, 只由 policy 控制。"""

    def __init__(
        self,
        *,
        snapshot_loader: SnapshotLoader | None = None,
        outcome_finalizer: OutcomeFinalizerPort,
        auto_producer: AutoProducerApi,
        mode_provider: Callable[[], RuntimeMode],
        program: str = "auto",
    ) -> None:
        """构造 AutoFlow。

        Args:
            snapshot_loader: 快照加载器 (同 ``load_verified_daily_action_snapshot``
                签名); 默认 ``None`` → 使用真实
                ``load_verified_daily_action_snapshot``。
            outcome_finalizer: 鸭子类型 finalizer, 只要求 ``finalize_due``
                (真实实现 ``OutcomeFinalizerService``)。
            auto_producer: ``AutoProducerApi`` (flow 只调用
                ``produce_and_publish``; 测试可注入鸭子类型 fake)。
            mode_provider: 每次 ``run`` 最先读取的 runtime_mode 投影
                (由 loaded candidate policy 的 ``PolicySnapshot.runtime_mode``
                提供)。
            program: 传给 ``finalize_due`` 的 program 标签, 默认 ``"auto"``。
        """
        self._snapshot_loader = (
            snapshot_loader or load_verified_daily_action_snapshot
        )
        self._outcome_finalizer = outcome_finalizer
        self._auto_producer = auto_producer
        self._mode_provider = mode_provider
        self._program = program

    def run(self, *, signal_date: date, reports_dir: Path, data_dir: Path) -> AutoFlowResult:
        """按投影 mode 依次独立执行三步 (完整语义见模块 docstring)。

        1. ``mode = mode_provider()``。
        2. ``OFF`` → 返回三步全 ``"skipped"``、``failure_reason`` 为空的
           ``AutoFlowResult``, 不做任何 v3 调用。
        3. ``SHADOW`` → 依次独立执行三步, 每步 try/except 捕获自身异常:
           - snapshot: 调用注入 loader (``signal_date, reports_dir=...,
             data_dir=...``); ``result.snapshot is None`` → 该步
             ``"failed"`` + reason = ``global_reason`` (为空时
             ``"snapshot_unavailable"``); 异常 → ``"failed"`` + reason =
             ``f"{type(exc).__name__}: {exc}"``。
           - outcome: ``finalize_due(as_of, program=self._program)``,
             ``as_of = datetime.combine(signal_date, time(15, 0,
             tzinfo=timezone.utc))``; 任意 tuple (含空 tuple) → ``"ok"``;
             异常 → ``"failed"``。snapshot 失败不影响本步。
           - auto_shadow: 仅当 snapshot 成功 (非 None) 时调用
             ``produce_and_publish(snapshot)``; 成功 → ``"ok"``; 异常 →
             ``"failed"``。snapshot 缺失 → ``"skipped"`` + reason
             ``"no_snapshot"``, 不调用 producer。
        4. 非 OFF 非 SHADOW 模式 (``BTST_CANARY`` / ``AUTHORITATIVE``):
           snapshot/outcome 照常执行, auto_shadow 步 ``"skipped"`` +
           reason ``"not_shadow_mode"`` (不调用 producer)。
        5. 三步之间无任何回滚: 前步失败不阻止后步, 后步失败不回填前步。
           ``execution_authority`` 恒 ``"none"``。
        """
        mode = self._mode_provider()
        if mode is RuntimeMode.OFF:
            return AutoFlowResult(
                snapshot_status="skipped",
                outcome_status="skipped",
                auto_shadow_status="skipped",
            )
        reasons: dict[str, str] = {}
        snapshot_status: Literal["ok", "failed", "skipped"]
        outcome_status: Literal["ok", "failed", "skipped"]
        auto_shadow_status: Literal["ok", "failed", "skipped"]
        shadow_step_allowed = mode is RuntimeMode.SHADOW

        # -- 1. snapshot (只读校验; 任何模式都尝试) --------------------------
        snapshot: VerifiedDailyActionSnapshot | None = None
        try:
            loaded = self._snapshot_loader(
                signal_date, reports_dir=reports_dir, data_dir=data_dir
            )
        except Exception as exc:
            snapshot_status = "failed"
            reasons["snapshot"] = f"{type(exc).__name__}: {exc}"
        else:
            if loaded.snapshot is None:
                snapshot_status = "failed"
                reasons["snapshot"] = (
                    loaded.global_reason or "snapshot_unavailable"
                )
            else:
                snapshot_status = "ok"
                snapshot = loaded.snapshot

        # -- 2. outcome (独立于 snapshot) --------------------------------------
        try:
            self._outcome_finalizer.finalize_due(
                datetime.combine(
                    signal_date, time(15, 0), tzinfo=timezone.utc
                ),
                program=self._program,
            )
        except Exception as exc:
            outcome_status = "failed"
            reasons["outcome"] = f"{type(exc).__name__}: {exc}"
        else:
            outcome_status = "ok"

        # -- 3. auto_shadow (仅 SHADOW 模式 + 有快照) -------------------------
        if not shadow_step_allowed:
            auto_shadow_status = "skipped"
            reasons["auto_shadow"] = "not_shadow_mode"
        elif snapshot is None:
            auto_shadow_status = "skipped"
            reasons["auto_shadow"] = "no_snapshot"
        else:
            try:
                self._auto_producer.produce_and_publish(snapshot)
            except Exception as exc:
                auto_shadow_status = "failed"
                reasons["auto_shadow"] = f"{type(exc).__name__}: {exc}"
            else:
                auto_shadow_status = "ok"

        return AutoFlowResult(
            snapshot_status=snapshot_status,
            outcome_status=outcome_status,
            auto_shadow_status=auto_shadow_status,
            failure_reason=MappingProxyType(reasons),
        )


__all__ = ["AutoFlow", "AutoFlowResult"]
