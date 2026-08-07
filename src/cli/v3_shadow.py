"""Plan 05 Task 9 S3/S4: V3 shadow CLI 接线 — config 加载 + shadow 编排入口。

本模块是 CLI↔v3 的【库层编排】接线点 (owner 批准方案 A)。两个窄入口:
``run_v3_shadow_daily_action`` / ``run_v3_shadow_auto`` 在 ``--daily-action`` /
``--auto`` 的 v2 渲染后被薄 hook 调用 (dispatcher.py / main.py), 按 policy
``runtime_mode`` 决定是否跑 v3 shadow 编排:

- ``OFF``: 零 v3 调用、零 v3 输出 (v2 行为完全不变)。
- 超前 mode (``BTST_CANARY`` / ``AUTHORITATIVE``, 超前于 Plan 05 的 off|shadow):
  打印 warning + 按 flow 内建行为放行 (只读观测步照常、shadow 管线 skip)。
- ``SHADOW``: 构造库层服务跑编排 (DailyActionFlow / AutoFlow) +
  ``ReportingService`` 投影 → ``render_text`` 中文操作员输出 + ``render_json``
  工件落 v3 namespace。

任何 v3 失败打印 ``⚠ v3 shadow 编排失败`` (整体 try/except), 不影响 v2 退出码
(dispatch handler 异常会改写 rc=1; 故 v3 异常绝不漏出)。

-------------------------------------------------------------------------------
安全边界 (shadow-only 阶段, in-process 偏差)
-------------------------------------------------------------------------------
Plan Architecture 要求 "privileged worker 独立进程 + CLI 不持 writable DSN";
Plan 05 实际是【库层】编排 (Task 1-8 无 FastAPI/uvicorn server 进程层, UDS
worker 留 Plan 06+)。CLI 进程内构造服务持有 capital sqlite 句柄 (shadow 只读),
严格说不满足进程级 writable-DSN 隔离 — owner 知情批准。补偿控制 (AST 守卫锁定,
见 S5 集成测试): (1) 本模块不 import governance/authority 写面、不 import
execution proxy/manual; (2) 不调用 activate_*/publish_entry/claim_send/
record_fill 等 authority 写方法; (3) 证据 signer 用进程内 ephemeral key
(``Ed25519PrivateKey.generate()``, 不读持久化签名材料 — 与 plan 全局约束一致)。

【privileged service-owned】路径 (capital ledger 真实激活态 / signer keystore /
governance authority / broker credential) 刻意不在本模块构造 — 本模块只构造
shadow 观测所需的 v3 namespace 临时树 + ephemeral 身份。
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

from src.screening.offensive.v3.kernel.sizing import SizingConfig


def _repo_root() -> Path:
    """返回 repo root (含 ``pyproject.toml`` 的目录; 不依赖 cwd)。

    向上 walk 找 ``pyproject.toml``, 比硬编码 ``parents[N]`` 稳健 (层级调整
    无需改 N)。CLI 可从 cron/任意目录运行, 路径解析必须锚定 repo root。
    """
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").is_file():
            return parent
    # 不可达: 本文件必在 repo 内。fail-closed 不静默回退 cwd。
    raise V3ShadowConfigError(
        "cannot locate repo root (pyproject.toml not found above"
        f" {here})"
    )


class V3ShadowConfigError(ValueError):
    """配置加载/校验失败 (缺字段 / 非法 toml / 文件不存在)。fail-closed。"""


@dataclass(frozen=True)
class V3ShadowConfig:
    """V3 shadow CLI 接线配置 (toml 加载结果, 路径已解析为绝对路径)。

    所有 Path 字段相对 repo root 解析 (不依赖 cwd)。``sizing`` 是 kernel
    ``SizingConfig`` (policy JSON 无对应物, 独立配)。
    """

    portfolio_id: str
    evidence_database: Path
    blob_root: Path
    capital_ledger: Path
    gateway_database: Path
    shadow_artifacts_dir: Path
    policy_path: Path
    sizing: SizingConfig


def _require(data: dict, section: str, key: str) -> object:
    """fail-closed 取 ``data[section][key]``; 缺段/缺键抛 ``V3ShadowConfigError``。"""
    section_obj = data.get(section)
    if not isinstance(section_obj, dict):
        raise V3ShadowConfigError(
            f"v3 shadow config missing [{section}] section"
        )
    if key not in section_obj:
        raise V3ShadowConfigError(
            f"v3 shadow config missing [{section}].{key}"
        )
    return section_obj[key]


def _resolve_path(value: object, repo_root: Path) -> Path:
    """把 toml 路径值解析为绝对路径: 绝对路径原样, 相对路径相对 repo root。"""
    if not isinstance(value, str):
        raise V3ShadowConfigError("v3 shadow config path value must be a string")
    p = Path(value)
    return p if p.is_absolute() else (repo_root / p).resolve()


def load_v3_shadow_config(config_path: Path) -> V3ShadowConfig:
    """加载 v3 shadow toml 配置 → ``V3ShadowConfig`` (fail-closed, cwd 无关)。

    相对路径相对 repo root 解析 (非 cwd)。缺任一必填字段、文件不存在、toml
    语法错误均抛 ``V3ShadowConfigError`` (fail-closed — 配置损坏不得静默
    回退默认, 也不得影响 v2 退出码; 调用方 catch 后按 OFF 处理)。
    """
    path = Path(config_path)
    if not path.is_absolute():
        path = _repo_root() / path
    try:
        raw = path.read_bytes()
    except FileNotFoundError as exc:
        raise V3ShadowConfigError(
            f"v3 shadow config not found: {config_path}"
        ) from exc
    except OSError as exc:
        raise V3ShadowConfigError(
            f"v3 shadow config unreadable: {config_path}: {exc}"
        ) from exc
    try:
        data = tomllib.loads(raw.decode("utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise V3ShadowConfigError(
            f"v3 shadow config malformed toml: {config_path}: {exc}"
        ) from exc

    repo_root = _repo_root()
    paths_section = data.get("paths")
    if not isinstance(paths_section, dict):
        raise V3ShadowConfigError("v3 shadow config missing [paths] section")
    try:
        portfolio_id = _require(data, "paths", "portfolio_id")
    except V3ShadowConfigError:
        raise
    if not isinstance(portfolio_id, str) or not portfolio_id:
        raise V3ShadowConfigError("[paths].portfolio_id must be a non-empty string")
    evidence_database = _resolve_path(
        _require(data, "paths", "evidence_database"), repo_root
    )
    blob_root = _resolve_path(_require(data, "paths", "blob_root"), repo_root)
    capital_ledger = _resolve_path(
        _require(data, "paths", "capital_ledger"), repo_root
    )
    gateway_database = _resolve_path(
        _require(data, "paths", "gateway_database"), repo_root
    )
    shadow_artifacts_dir = _resolve_path(
        _require(data, "paths", "shadow_artifacts_dir"), repo_root
    )
    policy_path = _resolve_path(_require(data, "policy", "path"), repo_root)

    sizing_section = data.get("sizing")
    if not isinstance(sizing_section, dict):
        raise V3ShadowConfigError("v3 shadow config missing [sizing] section")
    sizing = SizingConfig(
        per_ticker_gross_cap_cents=int(
            _require(data, "sizing", "per_ticker_gross_cap_cents")
        ),
        per_industry_gross_cap_cents=int(
            _require(data, "sizing", "per_industry_gross_cap_cents")
        ),
        per_day_gross_cap_cents=int(
            _require(data, "sizing", "per_day_gross_cap_cents")
        ),
        portfolio_gross_cap_cents=int(
            _require(data, "sizing", "portfolio_gross_cap_cents")
        ),
        worst_case_fee_ppm=int(_require(data, "sizing", "worst_case_fee_ppm")),
    )

    return V3ShadowConfig(
        portfolio_id=portfolio_id,
        evidence_database=evidence_database,
        blob_root=blob_root,
        capital_ledger=capital_ledger,
        gateway_database=gateway_database,
        shadow_artifacts_dir=shadow_artifacts_dir,
        policy_path=policy_path,
        sizing=sizing,
    )


__all__ = [
    "V3ShadowConfig",
    "V3ShadowConfigError",
    "load_v3_shadow_config",
    "run_v3_shadow_auto",
    "run_v3_shadow_daily_action",
]


# ---------------------------------------------------------------------------
# Plan 05 Task 9 S4: shadow 编排 composition root + CLI 入口
# ---------------------------------------------------------------------------
#
# 两个窄入口 (``run_v3_shadow_daily_action`` / ``run_v3_shadow_auto``) 被
# dispatcher.py / main.py 的薄 hook 在 v2 渲染后调用。按 policy ``runtime_mode``
# 决定是否跑 v3 shadow 编排 (语义见模块顶部 docstring)。
#
# rc 保护 (关键): dispatch handler 异常 → rc=1 (dispatcher.py:1406-1427), 故 v3
# 异常绝不漏出。入口用两层 try: (1) config/policy 加载失败 → 静默返回 (fail-safe
# OFF — v3 是 Plan 05 可选层, 未配置/配置损坏不得影响 v2); (2) 编排失败 → 打印
# ``⚠ v3 shadow 编排失败`` 并吞掉。两层都保 v2 退出码。

_DEFAULT_CONFIG_PATH = "config/services/v3/services.example.toml"
"""默认 v3 shadow 配置 (相对 repo root)。owner 未显式提供 config 时用之; 真实
部署复制为 services.toml 并按本机路径调整 (见 runbook)。"""

_WARN_PREFIX = "⚠ v3 shadow"
"""v3 shadow 告警/状态前缀 (中文操作员输出; 与 v2 输出视觉区分)。"""


def _wall_clock():
    """默认可信时钟 (wall UTC); 测试注入固定值以确定性运行。"""
    from datetime import datetime, timezone

    return datetime.now(timezone.utc)


def _default_config_path() -> Path:
    """默认配置绝对路径 (repo root 相对, 不依赖 cwd)。"""
    return _repo_root() / _DEFAULT_CONFIG_PATH


def _signal_session_close(signal_date):
    """signal_date 收盘时刻 (15:00 UTC) — capital as_of / PIT evidence cutoff /
    DeadlineContract 推导基准 (与 DailyActionFlow 内部 as_of 派生一致, :421)。"""
    from datetime import datetime, time, timezone

    return datetime.combine(signal_date, time(15, 0), tzinfo=timezone.utc)


class _NoBaseline(RuntimeError):
    """v3 capital/outcome baseline 不存在 (shadow-only CLI 真实运行的常态)。

    flow.run (capital/lifecycle/auto_shadow step) 与 reporting.build (各 reader
    调用) 均 try/except → 记 failed/partial_failure。非错误 — shadow 阶段无真实
    资本激活, capital ledger 通常不存在 (Plan 06+ privileged worker 注入真实
    baseline)。"""


class _GracefulCapitalReader:
    """无 capital baseline 时的只读面占位: 每方法抛 ``_NoBaseline``。

    满足 DailyActionFlow ``CapitalReaderPort`` (risk_snapshot) +
    ``LifecycleReaderPort`` (exit_state) + reporting ``CapitalReaderPort``
    (risk_snapshot/authority_state/entry_state/active_seal/exit_state/
    lifecycle_state) 的鸭子类型。调用方全 try/except, 故抛错 = 优雅降级
    (capital_status=failed / projection partial_failure) 而非崩溃。当
    ``config.capital_ledger`` 不存在时用之。"""

    def risk_snapshot(self, portfolio_id, as_of):
        raise _NoBaseline(f"no v3 capital baseline (portfolio={portfolio_id})")

    def exit_state(self, position_lineage_id, economic_lot_id):
        raise _NoBaseline("no v3 capital baseline")

    def authority_state(self, portfolio_id):
        raise _NoBaseline("no v3 capital baseline")

    def entry_state(self, seal_id):
        raise _NoBaseline("no v3 capital baseline")

    def active_seal(self, logical_key):
        raise _NoBaseline("no v3 capital baseline")

    def lifecycle_state(self, portfolio_id):
        raise _NoBaseline("no v3 capital baseline")


class _GracefulOutcomeFinalizer:
    """无 enrolled plan lines / capital engine 时的 outcome 占位。

    AutoFlow 对 outcome 步 try/except → outcome_status=failed (snapshot/auto_shadow
    步独立继续)。shadow CLI 无真实 enrolled plan lines, outcome finalization 本就
    no-op; 真实 outcome (Plan 02 capital engine + SessionSpine) 留 Plan 06+。"""

    def finalize_due(self, as_of, *, program):
        raise _NoBaseline("no outcome baseline (shadow CLI)")


def _build_capital_reader(config, *, bundle_verifier, clock, runtime_mode):
    """防御性构造 capital reader: ledger 可用 → ``CapitalGatewayApi``; 否则 graceful。

    ``CapitalGatewayApi.__init__`` 调 ``CapitalRepository.open(capital_path)``:
    文件不存在 → FileNotFoundError; schema 版本不匹配 → 冲突错。本 helper 捕获
    不可用情形退回 ``_GracefulCapitalReader``, 使 shadow 编排仍跑通 (snapshot
    观测 + 空 projection), 而非整体失败 — 与 flow/reporting 的优雅降级设计一致。
    仅读面被使用 (risk_snapshot/exit_state);绝不调用 activate_*/seal/reserve/
    send 等 authority 写方法 (AST 守卫锁定, S5)。"""
    from src.screening.offensive.v3.contracts import ExecutionMode
    from src.screening.offensive.v3.services.capital_gateway_api import (
        CapitalGatewayApi,
    )

    try:
        return CapitalGatewayApi(
            database_path=str(config.gateway_database),
            capital_path=str(config.capital_ledger),
            clock=clock,
            bundle_verifier=bundle_verifier,
            mode=ExecutionMode.DAILY_BAR_PROXY,
            broker_account_id=None,
            runtime_mode_provider=lambda: runtime_mode,
        )
    except (FileNotFoundError, OSError):
        return _GracefulCapitalReader()


def _persist_json_artifact(config, projection, *, signal_date, prefix):
    """render_json 工件落 v3 namespace (``shadow_artifacts_dir``), 绝不写 v2 reports。

    目录 mkdir 幂等; 文件名含 signal_date (同日二次 run 覆盖, 与 ShadowDecision
    确定性 id 一致)。失败由调用方外层 try 吞掉 (工件落盘非关键路径)。"""
    config.shadow_artifacts_dir.mkdir(parents=True, exist_ok=True)
    from src.screening.offensive.v3.reporting import render_json

    payload = render_json(projection)
    (config.shadow_artifacts_dir / f"{prefix}-{signal_date.isoformat()}.json").write_text(
        payload, encoding="utf-8"
    )


def _compose_daily_action_services(
    config,
    *,
    ctx,
    authority,
    clock,
    runtime_mode,
    signal_date,
    deadlines,
    trusted_evidence_cutoff,
    v2_plans_reader,
):
    """构造 DailyActionFlow + ReportingService + 共享 InMemoryShadowStore。

    shadow_store 同时注入 flow (写面 ``publish_shadow_decision``) 与 reporting
    (读面 ``active_shadow``), 使 flow 产出的 ShadowDecision 在同进程被 reporting
    读回投影。capital_reader 同时作 flow 的 capital_reader + lifecycle_reader
    (CapitalGatewayApi 满足两者; graceful reader 亦然)。
    """
    from src.screening.offensive.v3.evidence.blob_store import BlobStore
    from src.screening.offensive.v3.evidence.repository import EvidenceRepository
    from src.screening.offensive.v3.kernel.decide import GrowthKernel
    from src.screening.offensive.v3.orchestration.daily_action_flow import (
        DailyActionFlow,
    )
    from src.screening.offensive.v3.producers.btst import BTST_BEHAVIOR_BASELINE
    from src.screening.offensive.v3.reporting import ReportingService
    from src.screening.offensive.v3.reporting.shadow_store import (
        InMemoryShadowStore,
    )
    from src.screening.offensive.v3.services.btst_producer_api import (
        BtstProducerApi,
    )

    blob_store = BlobStore(config.blob_root)
    evidence_store = EvidenceRepository(
        database_path=str(config.evidence_database),
        blob_store=blob_store,
        verifier=ctx.verifier,
        trust_head_provider=ctx.head_provider,
        issuer_namespace="btst",
        clock=clock,
    )
    btst_producer = BtstProducerApi(
        database_path=str(config.evidence_database),
        blob_store=blob_store,
        verifier=ctx.verifier,
        trust_head_provider=ctx.head_provider,
        clock=clock,
        signer=ctx.signer_for("btst"),
        behavior_fingerprint=BTST_BEHAVIOR_BASELINE,
    )
    kernel = GrowthKernel(config.sizing)
    shadow_store = InMemoryShadowStore()
    capital_reader = _build_capital_reader(
        config,
        bundle_verifier=ctx.bundle_verifier,
        clock=clock,
        runtime_mode=runtime_mode,
    )
    mode_provider = lambda: runtime_mode  # noqa: E731 — 闭包 capture, 与 flow 契约一致
    flow = DailyActionFlow(
        lifecycle_reader=capital_reader,
        capital_reader=capital_reader,
        snapshot_loader=None,
        btst_producer=btst_producer,
        evidence_store=evidence_store,
        kernel=kernel,
        shadow_persister=shadow_store,
        mode_provider=mode_provider,
        policy_activation=authority.policy_activation,
        envelope=authority.envelope,
        portfolio_id=config.portfolio_id,
        deadlines=deadlines,
        trusted_evidence_cutoff=trusted_evidence_cutoff,
        evidence_ids=(),
        v2_plans_reader=v2_plans_reader,
        program="daily-action",
    )
    reporting = ReportingService(
        capital_reader=capital_reader,
        shadow_reader=shadow_store,
        mode_provider=mode_provider,
        v2_plans_reader=v2_plans_reader,
    )
    return flow, reporting


def _compose_auto_services(config, *, ctx, clock, runtime_mode):
    """构造 AutoFlow (auto shadow 管线)。

    auto_producer 恒 SHADOW-only (``runtime_mode_provider=lambda: SHADOW``; flow
    仅在 SHADOW mode 调用它)。outcome_finalizer 用 graceful 占位 — shadow CLI 无
    真实 enrolled plan lines (Plan 06+ privileged worker 注入 capital engine +
    SessionSpine 后才 finalize 真实 outcome)。"""
    from src.screening.offensive.v3.evidence.blob_store import BlobStore
    from src.screening.offensive.v3.orchestration.auto_flow import AutoFlow
    from src.screening.offensive.v3.policy.models import RuntimeMode
    from src.screening.offensive.v3.producers.auto import AUTO_BEHAVIOR_BASELINE
    from src.screening.offensive.v3.services.auto_producer_api import (
        AutoProducerApi,
    )

    blob_store = BlobStore(config.blob_root)
    auto_producer = AutoProducerApi(
        database_path=str(config.evidence_database),
        blob_store=blob_store,
        verifier=ctx.verifier,
        trust_head_provider=ctx.head_provider,
        clock=clock,
        signer=ctx.signer_for("auto"),
        behavior_fingerprint=AUTO_BEHAVIOR_BASELINE,
        runtime_mode_provider=lambda: RuntimeMode.SHADOW,
    )
    return AutoFlow(
        outcome_finalizer=_GracefulOutcomeFinalizer(),
        auto_producer=auto_producer,
        mode_provider=lambda: runtime_mode,
        program="auto",
    )


def _load_shadow_policy(config_path):
    """加载 config + policy snapshot; 任一不可用抛 (调用方按 fail-safe OFF 处理)。"""
    config = load_v3_shadow_config(
        Path(config_path) if config_path else _default_config_path()
    )
    from src.screening.offensive.v3.policy.loader import load_policy_snapshot

    policy = load_policy_snapshot(config.policy_path)
    return config, policy


def run_v3_shadow_daily_action(
    *,
    signal_date,
    reports_dir,
    data_dir,
    v2_plans_reader=None,
    config_path=None,
    clock=None,
):
    """``--daily-action`` 的 v3 shadow hook (v2 渲染后调用)。

    按 policy ``runtime_mode`` 决定: OFF → 零 v3 调用零 v3 输出 (v2 完全不变);
    超前 mode (BTST_CANARY/AUTHORITATIVE) → warning + flow 内建行为 (只读观测步
    照常, shadow 管线 skip); SHADOW → 库层编排 (DailyActionFlow) + reporting 投影
    → render_text 上 stdout + render_json 落 v3 namespace。任何 v3 失败打印
    ``⚠ v3 shadow 编排失败`` 并吞掉, 不影响 v2 退出码。
    """
    try:
        config, policy = _load_shadow_policy(config_path)
    except Exception:
        # fail-safe OFF: v3 未配置/配置损坏 — Plan 05 v3 是可选层, 静默不影响 v2。
        return
    try:
        from src.screening.offensive.v3.orchestration.shadow_trust import (
            build_shadow_trust_context,
            derive_deadline_contract,
            SHADOW_BTST_SPEC,
            synthesize_shadow_authority,
        )
        from src.screening.offensive.v3.policy.models import RuntimeMode
        from src.screening.offensive.v3.reporting import render_text

        mode = policy.runtime_mode
        if mode is RuntimeMode.OFF:
            return
        if mode in (RuntimeMode.BTST_CANARY, RuntimeMode.AUTHORITATIVE):
            print(
                f"{_WARN_PREFIX}: runtime_mode={mode.value} 超前于 Plan 05 "
                f"off|shadow; 按内建行为放行 (shadow 管线 skip)"
            )
        clk = clock if clock is not None else _wall_clock
        now = clk()
        ctx = build_shadow_trust_context(
            reference_time=now, specs=(SHADOW_BTST_SPEC,)
        )
        authority = synthesize_shadow_authority(
            portfolio_id=config.portfolio_id,
            trust_bundle_hash=ctx.active_bundle_hash,
            reference_time=now,
        )
        close = _signal_session_close(signal_date)
        deadlines = derive_deadline_contract(close_finalized_at=close)
        flow, reporting = _compose_daily_action_services(
            config,
            ctx=ctx,
            authority=authority,
            clock=clk,
            runtime_mode=mode,
            signal_date=signal_date,
            deadlines=deadlines,
            trusted_evidence_cutoff=close,
            v2_plans_reader=v2_plans_reader,
        )
        flow.run(
            signal_date=signal_date,
            reports_dir=reports_dir,
            data_dir=data_dir,
            trusted_at=now,
        )
        projection = reporting.build(
            portfolio_id=config.portfolio_id,
            signal_session=signal_date,
            as_of=now,
        )
        print(render_text(projection))
        _persist_json_artifact(
            config, projection, signal_date=signal_date, prefix="daily-action"
        )
    except Exception as exc:
        print(f"{_WARN_PREFIX} 编排失败: {type(exc).__name__}: {exc}")
        # swallow — 不影响 v2 退出码


def run_v3_shadow_auto(
    *,
    signal_date,
    reports_dir,
    data_dir,
    config_path=None,
    clock=None,
):
    """``--auto`` 的 v3 shadow hook (v2 渲染后调用)。

    语义同 ``run_v3_shadow_daily_action`` (OFF 零调用 / 超前 warning / SHADOW 走
    编排 / rc 保护), 但跑 AutoFlow (snapshot + outcome + auto_shadow 三步独立)。
    AutoFlowResult 是状态汇总 (无 ShadowDecision/projection), 故打印一行 v3 auto
    状态而非投影。outcome 步恒 graceful (shadow CLI 无 enrolled plan lines)。
    """
    try:
        config, policy = _load_shadow_policy(config_path)
    except Exception:
        return
    try:
        from src.screening.offensive.v3.orchestration.shadow_trust import (
            build_shadow_trust_context,
            SHADOW_AUTO_SPEC,
        )
        from src.screening.offensive.v3.policy.models import RuntimeMode

        mode = policy.runtime_mode
        if mode is RuntimeMode.OFF:
            return
        if mode in (RuntimeMode.BTST_CANARY, RuntimeMode.AUTHORITATIVE):
            print(
                f"{_WARN_PREFIX}: runtime_mode={mode.value} 超前于 Plan 05 "
                f"off|shadow; 按内建行为放行"
            )
        clk = clock if clock is not None else _wall_clock
        now = clk()
        ctx = build_shadow_trust_context(
            reference_time=now, specs=(SHADOW_AUTO_SPEC,)
        )
        flow = _compose_auto_services(
            config, ctx=ctx, clock=clk, runtime_mode=mode
        )
        result = flow.run(
            signal_date=signal_date, reports_dir=reports_dir, data_dir=data_dir
        )
        print(
            f"{_WARN_PREFIX} auto: snapshot={result.snapshot_status} "
            f"outcome={result.outcome_status} "
            f"auto_shadow={result.auto_shadow_status}"
        )
    except Exception as exc:
        print(f"{_WARN_PREFIX} 编排失败: {type(exc).__name__}: {exc}")
