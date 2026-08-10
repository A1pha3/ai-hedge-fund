"""Plan 05 Task 9 S5: v3 shadow services 集成测试。

三个聚焦维度 (降脆弱性, 各自独立):
1. flow 端到端 shadow — 真实服务组合 (CapitalGatewayApi + BtstProducerApi +
   GrowthKernel + EvidenceRepository + InMemoryShadowStore) + genesis 种子资本 +
   注入快照 → DailyActionFlow 产出真实 ShadowDecision (execution_authority=none,
   counterfactual_lines 非空)。这是 S2b family_id 修复 + S4 合成 authority +
   S4a 信任链的端到端证明。
2. 写监控 — SHADOW 编排只写 v3 namespace, v2 ledger 字节不变 (byte-identical);
   v3 JSON 工件落 v3 namespace。
3. AST ACL 守卫 — v3_shadow.py 不 import governance/execution/gateway 写面,
   不调用 authority 写方法 (activate_*/publish_entry/claim_send/...); 用 AST
   (ast.walk 捕获函数级 lazy import) 不用行扫描。

复用 test_auto_flow 的 _snapshot + _hit_result (Task 5/6/7 同款 fixture, 2 个
可扫候选), 经 sys.path 注入 orchestration 测试目录。
"""

from __future__ import annotations

import ast
import hashlib
import json
import sys
from datetime import date, datetime, time, timezone
from pathlib import Path

import pytest

# 复用 orchestration 测试目录的快照/detect fixture (Task 5/6/7 同款)。
_ORCH_DIR = Path(__file__).resolve().parents[1] / "orchestration"
if str(_ORCH_DIR) not in sys.path:
    sys.path.insert(0, str(_ORCH_DIR))
from test_auto_flow import (  # noqa: E402 — sys.path 注入后的跨目录测试复用
    SIGNAL_DATE as AUTO_SIGNAL_DATE,
    _hit_result,
    _snapshot as _verified_snapshot,
)

from src.cli.v3_shadow import (  # noqa: E402
    V3ShadowConfig,
    _compose_daily_action_services,
    run_v3_shadow_daily_action,
)
from src.screening.offensive.daily_action_snapshot import (  # noqa: E402
    VerifiedSnapshotResult,
)
from src.screening.offensive.v3.capital.flows import GenesisRequest  # noqa: E402
from src.screening.offensive.v3.capital.repository import (  # noqa: E402
    AccountBinding,
    CapitalRepository,
)
from src.screening.offensive.v3.contracts import ExecutionMode  # noqa: E402
from src.screening.offensive.v3.kernel.sizing import SizingConfig  # noqa: E402
from src.screening.offensive.v3.orchestration.shadow_trust import (  # noqa: E402
    SHADOW_BTST_SPEC,
    build_shadow_trust_context,
    derive_deadline_contract,
    synthesize_shadow_authority,
)
from src.screening.offensive.v3.policy.loader import (  # noqa: E402
    load_policy_snapshot,
)
from src.screening.offensive.v3.policy.models import RuntimeMode  # noqa: E402
from src.screening.offensive.setups.btst_breakout import (  # noqa: E402
    BtstBreakoutSetup,
)

_REPO_ROOT = Path(__file__).resolve().parents[4]
_POLICY_TEMPLATE = _REPO_ROOT / "config/policies/v3/policy-v1.json"
SIGNAL_DATE = AUTO_SIGNAL_DATE  # date(2026, 8, 5) — 与 _verified_snapshot 一致
T_CLOSE = datetime(2026, 8, 5, 15, 0, tzinfo=timezone.utc)  # 收盘
CLOCK_AT = datetime(2026, 8, 5, 15, 5, tzinfo=timezone.utc)  # 收盘后 5min (新鲜度窗口内)
PORTFOLIO = "paper-v3"


def _shadow_config(
    tmp_path: Path, *, capital_ledger: Path, portfolio_id: str = PORTFOLIO
) -> V3ShadowConfig:
    """直接构造 V3ShadowConfig 指向 tmp 树 (绕开 toml 加载; capital_ledger 可控)。"""
    shadow = tmp_path / "v3_shadow"
    return V3ShadowConfig(
        portfolio_id=portfolio_id,
        evidence_database=shadow / "evidence.sqlite3",
        blob_root=shadow / "blobs",
        capital_ledger=capital_ledger,
        gateway_database=shadow / "gateway.sqlite3",
        shadow_artifacts_dir=shadow / "artifacts",
        policy_path=tmp_path / "policy.json",
        sizing=SizingConfig(
            per_ticker_gross_cap_cents=500_000,
            per_industry_gross_cap_cents=1_500_000,
            per_day_gross_cap_cents=3_000_000,
            portfolio_gross_cap_cents=5_000_000,
            worst_case_fee_ppm=3000,
        ),
    )


def _seed_genesis_capital(capital_path: Path) -> None:
    """种子资本 ledger: initialize schema + genesis 发行 100M 单位 @1cent → 1M yuan cash。

    NAV 充裕 (100M cents = 1M yuan) 使 kernel sizing 产出非零 entry: grant lineage
    cap 2% × NAV = 2M cents, per_ticker cap 500k cents → 每 ticket 可 size ≥1 lot
    (不因资本不足退化为 NoTrade)。risk_snapshot 在有效窗口内 FRESH+COMPLETE,
    positions=()。"""
    repo = CapitalRepository.initialize(capital_path)
    repo.initialize_genesis(
        GenesisRequest(
            idempotency_key="genesis-1",
            account_binding=AccountBinding(
                portfolio_id=PORTFOLIO,
                mode=ExecutionMode.MANUAL_CONFIRMED,
                broker_account_id="acct-test",
                base_currency="CNY",
                environment_fingerprint="ab" * 32,
            ),
            unit_quanta=100_000_000,
            unit_price_numerator=1,
            unit_price_denominator=1,
            source_authority="governance.test",
            authorization_reference="gov-genesis-1",
            effective_at=T_CLOSE,
            as_of=T_CLOSE,
        )
    )


def _policy_json(runtime_mode: str) -> str:
    """policy-v1 模板 → SHADOW 变体: runtime_mode + 非零资本 caps。

    checked-in policy-v1.json 是 off 候选 (caps 全 0, ``test_off_policy_cannot_hide_nonzero_executable_risk``
    锁定 off+caps>0 被拒)。SHADOW 编排需要真实 caps>0 的快照, 故在模板上
    override runtime_mode/caps/btst_enabled — 与 Task 5 起"真实 PolicySnapshot
    经 kernel 校验 (content_hash)"的接线一致 (否则 policy caps=0 → 恒
    CAPACITY_EXHAUSTED, 端到端 shadow 决策无法产出)。
    """
    template = json.loads(_POLICY_TEMPLATE.read_text(encoding="utf-8"))
    template["runtime_mode"] = runtime_mode
    template["producers"]["btst_enabled"] = True
    template["capital"]["exploration_aggregate_gross_cap"] = 0.02
    template["capital"]["portfolio_gross_cap"] = 0.02
    template["capital"]["single_name_gross_cap"] = 0.01
    template["capital"]["industry_gross_cap"] = 0.02
    template["capital"]["daily_entry_gross_cap"] = 0.02
    template["capital"]["stage_loss_budget_cap"] = 0.02
    return json.dumps(template, ensure_ascii=False)


def _write_policy_json(tmp_path: Path, *, runtime_mode: str) -> Path:
    """写 policy JSON (真实 loader 加载路径, Task 5 起 flow 校验真实 content_hash)。"""
    policy = tmp_path / "policy.json"
    policy.write_text(_policy_json(runtime_mode), encoding="utf-8")
    return policy


def _write_toml_config(tmp_path: Path, *, runtime_mode: str, capital_ledger: Path) -> Path:
    """写 services.toml + policy JSON (run_v3_shadow_daily_action 入口用)。"""
    policy = _write_policy_json(tmp_path, runtime_mode=runtime_mode)
    shadow = tmp_path / "v3_shadow"
    config = tmp_path / "services.toml"
    config.write_text(
        "\n".join(
            [
                "[paths]",
                f'portfolio_id = "{PORTFOLIO}"',
                f'evidence_database = "{shadow / "evidence.sqlite3"}"',
                f'blob_root = "{shadow / "blobs"}"',
                f'capital_ledger = "{capital_ledger}"',
                f'gateway_database = "{shadow / "gateway.sqlite3"}"',
                f'shadow_artifacts_dir = "{shadow / "artifacts"}"',
                "[policy]",
                f'path = "{policy}"',
                "[sizing]",
                "per_ticker_gross_cap_cents = 500000",
                "per_industry_gross_cap_cents = 1500000",
                "per_day_gross_cap_cents = 3000000",
                "portfolio_gross_cap_cents = 5000000",
                "worst_case_fee_ppm = 3000",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return config


# ===========================================================================
# 1. flow 端到端 shadow (真实服务组合 → ShadowDecision)
# ===========================================================================


def test_flow_end_to_end_produces_shadow_decision(tmp_path, monkeypatch):
    """真实服务组合 + genesis 资本 + 注入快照 → ShadowDecision 产出。

    端到端证明: S2b family_id 修复 (BTST_FAMILY) + S4 合成 authority (ADMITTED) +
    S4a 信任链 (producer publish+verify) + 真实 GrowthKernel (size 非零 entry) +
    InMemoryShadowStore (flow 写 → reporting 读) 协同工作。ShadowDecision 形态:
    execution_authority=NONE, counterfactual_lines 非空 (有 ADMITTED 候选)。
    """
    capital_path = tmp_path / "capital.sqlite3"
    _seed_genesis_capital(capital_path)

    # BTST detect 固定命中 (Task 5/6/7 同款): 2 个可扫候选 → producer 产 4 枚信封。
    monkeypatch.setattr(
        BtstBreakoutSetup,
        "detect",
        lambda self, ticker, trade_date, context: _hit_result(ticker),
    )

    config = _shadow_config(tmp_path, capital_ledger=capital_path)
    ctx = build_shadow_trust_context(
        reference_time=CLOCK_AT, specs=(SHADOW_BTST_SPEC,)
    )
    # 真实 GrowthKernel 校验 policy_activation.policy_snapshot_hash ==
    # policy_snapshot.content_hash() (Task 5); 从真实 policy JSON 加载快照,
    # 由它派生 authority 的 activation hash, 使 pair 内部一致。
    policy = load_policy_snapshot(
        _write_policy_json(tmp_path, runtime_mode="shadow")
    )
    authority = synthesize_shadow_authority(
        portfolio_id=PORTFOLIO,
        trust_bundle_hash=ctx.active_bundle_hash,
        reference_time=CLOCK_AT,
        policy_snapshot=policy,
    )
    deadlines = derive_deadline_contract(close_finalized_at=T_CLOSE)

    def _clock():
        return CLOCK_AT

    def _loader(signal_date, *, reports_dir, data_dir):
        return VerifiedSnapshotResult(snapshot=_verified_snapshot())

    flow, reporting = _compose_daily_action_services(
        config,
        ctx=ctx,
        authority=authority,
        clock=_clock,
        runtime_mode=RuntimeMode.SHADOW,
        signal_date=SIGNAL_DATE,
        deadlines=deadlines,
        trusted_evidence_cutoff=T_CLOSE,
        v2_plans_reader=None,
        snapshot_loader=_loader,
        policy_snapshot=policy,
    )
    result = flow.run(
        signal_date=SIGNAL_DATE,
        reports_dir=tmp_path / "reports",
        data_dir=tmp_path / "data",
        trusted_at=CLOCK_AT,
    )

    # ShadowDecision 产出 (status ok + 持久化 id); 各读步独立 ok。
    assert result.capital_status == "ok", result.failure_reason
    assert result.snapshot_status == "ok", result.failure_reason
    assert result.shadow_decision_status == "ok", result.failure_reason
    assert result.shadow_decision_id is not None
    assert result.execution_authority == "none"

    # flow 写的 ShadowDecision 被 reporting 读回 (同进程 InMemoryShadowStore 桥)。
    shadow = reporting._shadow_reader.active_shadow(PORTFOLIO, SIGNAL_DATE)
    assert shadow is not None
    # ShadowDecision.execution_authority 是 Literal["NONE"] (契约大写); flow result
    # 的 execution_authority 是小写 "none" — 二者均表示 shadow 永不产生可执行授权。
    assert shadow.execution_authority == "NONE"
    assert len(shadow.counterfactual_lines) >= 1


def test_flow_end_to_end_no_capital_baseline_degrades_gracefully(tmp_path, monkeypatch):
    """无 capital ledger (真实 CLI 常态) → graceful capital reader, flow 不崩溃。

    capital_status=failed, shadow 管线 skipped (no_capital); 但 snapshot/lifecycle
    观测照常 — 与 flow/reporting 的优雅降级设计一致 (rc 保护 + 诚实观测)。"""
    monkeypatch.setattr(
        BtstBreakoutSetup,
        "detect",
        lambda self, ticker, trade_date, context: _hit_result(ticker),
    )
    # capital_ledger 指向不存在的路径 → _build_capital_reader 退回 graceful reader。
    config = _shadow_config(tmp_path, capital_ledger=tmp_path / "missing.sqlite3")
    ctx = build_shadow_trust_context(
        reference_time=CLOCK_AT, specs=(SHADOW_BTST_SPEC,)
    )
    policy = load_policy_snapshot(
        _write_policy_json(tmp_path, runtime_mode="shadow")
    )
    authority = synthesize_shadow_authority(
        portfolio_id=PORTFOLIO,
        trust_bundle_hash=ctx.active_bundle_hash,
        reference_time=CLOCK_AT,
        policy_snapshot=policy,
    )
    deadlines = derive_deadline_contract(close_finalized_at=T_CLOSE)

    def _loader(signal_date, *, reports_dir, data_dir):
        return VerifiedSnapshotResult(snapshot=_verified_snapshot())

    flow, _ = _compose_daily_action_services(
        config,
        ctx=ctx,
        authority=authority,
        clock=lambda: CLOCK_AT,
        runtime_mode=RuntimeMode.SHADOW,
        signal_date=SIGNAL_DATE,
        deadlines=deadlines,
        trusted_evidence_cutoff=T_CLOSE,
        v2_plans_reader=None,
        snapshot_loader=_loader,
        policy_snapshot=policy,
    )
    result = flow.run(
        signal_date=SIGNAL_DATE,
        reports_dir=tmp_path / "reports",
        data_dir=tmp_path / "data",
        trusted_at=CLOCK_AT,
    )
    assert result.capital_status == "failed"
    assert result.shadow_decision_status == "skipped"
    assert "capital" in result.failure_reason


# ===========================================================================
# 2. 写监控: SHADOW 只写 v3 namespace, v2 byte-identical
# ===========================================================================


def test_shadow_entry_writes_only_v3_namespace_v2_byte_identical(
    tmp_path, monkeypatch, capsys
):
    """SHADOW 编排经入口跑通: v2 ledger 字节不变, v3 JSON 工件落 v3 namespace。

    无 genesis (capital graceful) → flow 降级但入口完成 render_text + render_json
    工件。v2 ledger (placeholder bytes) sha256 前后不变; v3 artifacts 目录新建含 JSON。
    """
    v2_ledger = tmp_path / "v2" / "ledger.sqlite3"
    v2_ledger.parent.mkdir(parents=True)
    v2_ledger.write_bytes(b"V2-LEDGER-PLACEHOLDER-DO-NOT-TOUCH")
    before_sha = hashlib.sha256(v2_ledger.read_bytes()).hexdigest()

    config = _write_toml_config(
        tmp_path,
        runtime_mode="shadow",
        capital_ledger=tmp_path / "v3_shadow" / "capital.sqlite3",
    )
    run_v3_shadow_daily_action(
        signal_date=SIGNAL_DATE,
        reports_dir=tmp_path / "v2" / "reports",
        data_dir=tmp_path / "v2" / "data",
        config_path=config,
        clock=lambda: CLOCK_AT,
    )
    capsys.readouterr()  # drain stdout (projection render)

    # v2 ledger 字节不变 (byte-identical 契约)。
    assert hashlib.sha256(v2_ledger.read_bytes()).hexdigest() == before_sha
    # v3 JSON 工件落 v3 namespace (绝不写 v2 reports)。
    artifact = (
        tmp_path
        / "v3_shadow"
        / "artifacts"
        / f"daily-action-{SIGNAL_DATE.isoformat()}.json"
    )
    assert artifact.is_file()
    payload = json.loads(artifact.read_text(encoding="utf-8"))
    assert payload["portfolio_id"] == PORTFOLIO
    assert payload["signal_session"] == SIGNAL_DATE.isoformat()


# ===========================================================================
# 3. AST ACL 守卫: v3_shadow.py 无写面 import + 无写方法调用
# ===========================================================================

# v3_shadow.py 不得 import 的子包/模块 (真实激活/执行/治理写面; capital_gateway_api
# 读 facade 除外)。
_FORBIDDEN_IMPORT_PREFIXES = (
    "src.screening.offensive.v3.governance",
    "src.screening.offensive.v3.execution",
    "src.screening.offensive.v3.gateway",
    "src.screening.offensive.v3.services.authorizer_api",
    "src.screening.offensive.v3.services.governance_api",
    "src.screening.offensive.v3.services.market_publisher",
)

# v3_shadow.py 不得调用的 authority/execution 写方法 (capital_gateway_api 读面除外)。
_FORBIDDEN_CALLS = frozenset(
    {
        "activate_trust_bundle",
        "activate_policy_and_envelope",
        "raise_entry_fence",
        "acknowledge_fence",
        "publish_entry",
        "issue_permit",
        "make_outbox_durable",
        "claim_send",
        "cancel_unclaimed_entry",
        "record_delivery_outcome",
        "derive_exit_mandates",
        "claim_due_exit_work",
        "record_exit_attempt",
        "reconcile_exit",
        "record_fill",
    }
)


def test_v3_shadow_acl_no_write_side_imports_or_calls() -> None:
    """AST 扫描 v3_shadow.py: 无 governance/execution/gateway 写面 import, 无写方法调用。

    ast.walk 捕获函数级 lazy import (dispatcher 多为函数内 import, 行扫描会漏)。
    capital_gateway_api 读 facade 允许 (plan S4 批准); 仅锁写面 + 写方法调用。
    """
    src = (_REPO_ROOT / "src" / "cli" / "v3_shadow.py").read_text(encoding="utf-8")
    tree = ast.parse(src)

    import_violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            for prefix in _FORBIDDEN_IMPORT_PREFIXES:
                if node.module == prefix or node.module.startswith(prefix + "."):
                    import_violations.append(node.module)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                for prefix in _FORBIDDEN_IMPORT_PREFIXES:
                    if alias.name == prefix or alias.name.startswith(prefix + "."):
                        import_violations.append(alias.name)

    call_violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = None
            if isinstance(node.func, ast.Attribute):
                name = node.func.attr
            elif isinstance(node.func, ast.Name):
                name = node.func.id
            if name and (name in _FORBIDDEN_CALLS or name.startswith("activate_")):
                call_violations.append(name)

    assert not import_violations, (
        "v3_shadow.py imports forbidden write-side modules:\n  - "
        + "\n  - ".join(sorted(set(import_violations)))
    )
    assert not call_violations, (
        "v3_shadow.py calls forbidden authority/execution write methods:\n  - "
        + "\n  - ".join(sorted(set(call_violations)))
    )


def test_v3_shadow_acl_allows_capital_read_facade() -> None:
    """capital_gateway_api 读 facade 允许 (plan S4 批准): 确认它不被误禁。

    防止 _FORBIDDEN_IMPORT_PREFIXES 误把 services.capital_gateway_api 圈入
    (它持写能力但 CLI 只用读面; AST 调用守卫锁写方法)。"""
    src = (_REPO_ROOT / "src" / "cli" / "v3_shadow.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
    assert any("services.capital_gateway_api" in m for m in modules), (
        "capital_gateway_api 读 facade 应被允许 import (plan S4)"
    )
