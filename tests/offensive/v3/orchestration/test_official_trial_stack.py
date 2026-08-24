"""官方 Trial 运行栈组装器 — stage receipt 选择面 (2026-08-23, R28).

R27 对抗性审查发现: ``_latest_stage_receipt`` 按文件名字典序取「最新」
stage 回执 — 无治理事实绑定。stage_id 是 ``NonEmptyStr`` 无命名约束
(``stage-10`` 字典序小于 ``stage-2``), receipt 自带权威签发时刻
``issued_at`` (P2-c 纪律: 签发行为身份的一部分) 却未被使用。预置一个
字典序更大的**旧** stage 回执文件, 官方栈就会静默绑定错误治理事实
(enrollment 窗口/晋级布尔式/manifest hash 全部随之错位)。

本文件钉死修复后的选择契约:
  1. 缺省选择 = 全量严格冷读 + 按 ``issued_at`` 取最新 (字典序无关);
  2. 显式 ``stage_id`` 精确选择 (确定性最强, 归档审计路径);
  3. 归档中任何一个回执损坏 → fail-closed, 不静默跳过 (预置损坏文件
     不能操纵选择面 — 即使其字典序不参与候选);
  4. 同 ``issued_at`` 不同 stage_id → ``stage_selection_ambiguous``
     (签发行为身份含时刻; 同刻双签是治理异常, fail-closed 而非任选)。
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.screening.offensive.v3.contracts.base import ExecutionMode
from src.screening.offensive.v3.contracts.regime import RegimeAdmissionMode
from src.screening.offensive.v3.contracts.trial import TrialArm
from src.screening.offensive.v3.governance.repository import (
    GovernanceRepository,
)
from src.screening.offensive.v3.governance.stage_issuance import (
    GovernanceStageIssuer,
    StageIssuanceRequest,
)
from src.screening.offensive.v3.orchestration.stage_archive import (
    write_stage_issuance_receipt,
)

# 跨目录 crib: 治理信任链/封存请求 (governance)、kernel 冻结世界 — 与
# test_privileged_worker 同款 import 纪律 (既有 fixture 世界, 不复制实现)。
for _dir in (
    Path(__file__).resolve().parents[1] / "governance",
    Path(__file__).resolve().parents[1] / "kernel",
):
    if str(_dir) not in sys.path:
        sys.path.insert(0, str(_dir))
from test_regime_trial_governance import (  # noqa: E402
    ENROLLMENT_START,
    NOW as GOV_NOW,
)
from test_shadow_kernel import (  # noqa: E402
    _config,
)
from test_privileged_worker import (  # noqa: E402
    TRIAL_ID,
    _seal_request,
)

UTC = timezone.utc
TRIAL_ID = "trial-regime-001"


@dataclass
class _ArchiveWorld:
    """官方布局最小可组装世界 (R27 端到端测试的 crib, 多回执签发版)。"""

    identity_dir: Path
    root: Path
    issuer: GovernanceStageIssuer
    sizing_config: object
    market_scenario: object
    trial_attribution: object


def _official_archive_world(tmp_path: Path) -> _ArchiveWorld:
    from src.screening.offensive.v3.capital.flows import GenesisRequest
    from src.screening.offensive.v3.capital.fills import FillAttribution
    from src.screening.offensive.v3.capital.identity import AccountBinding
    from src.screening.offensive.v3.capital.repository import CapitalRepository
    from src.screening.offensive.v3.evidence.governance_identity import (
        generate_governance_identity,
    )
    from src.screening.offensive.v3.governance.regime_trial import (
        RegimeTrialBundle,
    )
    from src.screening.offensive.v3.governance.repository import (
        RegimeTrialSealRequest,
    )
    from src.screening.offensive.v3.orchestration.arm_layout import (
        arm_capital_database_path,
    )
    from src.screening.offensive.v3.orchestration.arm_lifecycle import (
        CURRENT_COST_SCENARIO,
    )
    from src.screening.offensive.v3.orchestration.genesis import (
        TrialArmGenesisSource,
        TrialGenesisArchive,
        restore_genesis_arm,
    )

    identity_dir = tmp_path / "identity"
    generate_governance_identity(
        identity_dir,
        namespaces=("regime", "exchange-calendar", "btst-bars", "btst"),
        clock=lambda: datetime(2026, 8, 6, 8, 0, tzinfo=UTC),
    )
    root = tmp_path / "trial-root"
    _now = GOV_NOW
    seed = tmp_path / "seed-capital.sqlite3"
    repo = CapitalRepository.initialize(seed)
    repo.initialize_genesis(GenesisRequest(
        idempotency_key="genesis-r28",
        account_binding=AccountBinding(
            portfolio_id=f"pf-{TRIAL_ID}",
            mode=ExecutionMode.DAILY_BAR_PROXY,
            broker_account_id=None, base_currency="CNY",
            environment_fingerprint=None,
        ),
        unit_quanta=10_000, unit_price_numerator=1_000, unit_price_denominator=1,
        source_authority="governance.test", authorization_reference="t-r28",
        effective_at=_now, as_of=_now,
    ))
    source = TrialArmGenesisSource(capital_repository=repo)
    manifest = TrialGenesisArchive(root).seal(
        TRIAL_ID, champion_source=source, challenger_source=source
    )
    for arm in ("CHAMPION", "CHALLENGER"):
        target = arm_capital_database_path(root, TrialArm[arm])
        target.parent.mkdir(parents=True, exist_ok=True)
        restore_genesis_arm(manifest, root, target, arm=arm)

    governance = GovernanceRepository(
        database_path=str(root / "governance.sqlite3"),
        clock=lambda: GOV_NOW,
    )
    request, sign, verifier, current_head, caps, _bundle = _seal_request()
    governance.seal_regime_trial(
        request, verifier=verifier, current_head=current_head,
        trusted_at=ENROLLMENT_START,
    )
    issuer = GovernanceStageIssuer(
        repository=governance,
        signer=lambda payload: sign(payload, caps["stage"]),
        stage_capability=caps["stage"],
        verifier=verifier,
        trust_head=lambda: current_head,
        clock=lambda: GOV_NOW,
    )
    # 证据库真实播种 (R37): 组装面冷读探测要求 evidence 库 regime 命名
    # 空间 ≥1 条 committed 证据 (持久身份签发链)、bars 库 schema 落盘
    # (零记录合法) — 0 字节占位被 evidence_not_seeded/bars_store_not_seeded
    # 拒绝; spine 预置真实 enrollment (R32: 组装面校验 enrolled_sessions
    # 非空, 空文件/异 program 都 spine_not_registered — fixture 模拟注册流程)。
    from test_privileged_worker import seed_official_evidence_stores

    seed_official_evidence_stores(identity_dir, root)
    (root / "spine.sqlite3").touch()
    from src.screening.offensive.v3.evidence.session_spine import (
        SessionEnrollment,
        SessionSpine,
    )

    spine_writer = SessionSpine(
        database_path=str(root / "spine.sqlite3"), clock=lambda: GOV_NOW
    )
    spine_writer.enroll_expected_sessions(
        (
            SessionEnrollment(
                "research.btst.regime", date(2026, 8, 6), date(2026, 8, 6)
            ),
            SessionEnrollment(
                "research.btst.regime", date(2026, 8, 13), date(2026, 8, 13)
            ),
        )
    )
    # 冷读前置 (R35): 引擎 dispose 使 -wal 确定性 checkpoint 进主文件 —
    # 临时对象的引用回收时机不可依赖 (引擎对象图含环, GC 非确定),
    # 且官方 runbook 现实是封存进程终止即冷; 组装器对事实文件的冷读
    # 探测 (含 sidecar 拒绝) 要求 fixture 与之一致。
    spine_writer._engine.dispose()
    governance._engine.dispose()
    return _ArchiveWorld(
        identity_dir=identity_dir,
        root=root,
        issuer=issuer,
        sizing_config=_config(),
        market_scenario=CURRENT_COST_SCENARIO,
        trial_attribution=FillAttribution(
            producer_namespace="btst", research_program_id="research.btst.regime",
            economic_lineage_id="eline-1", stage_id="stage-1",
        ),
    )


def _issue_receipt(issuer: GovernanceStageIssuer, *, stage_id: str, issued_at: datetime):
    """签发一个真实治理链 receipt (stage_id/issued_at 及台账 id 相互独立)。"""
    seq = stage_id.rsplit("-", 1)[-1]
    receipt = issuer.issue(
        StageIssuanceRequest(
            trial_id=TRIAL_ID,
            stage_id=stage_id,
            stage_sample_reservation_id=f"smp-{seq}",
            alpha_sample_consumption_id=f"alpha-{seq}",
            alpha_or_evalue_budget_consumption_id=f"budget-{seq}",
            attempt_ledger_checkpoint_hash="a" * 64,
            stage_loss_budget_id=f"loss-{seq}",
            stage_loss_version=1,
            maximum_loss_budget_cents=1_000_000,
            issuer_id="governance.service",
            issued_at=issued_at,
        )
    )
    # 冷读前置 (R35): 签发写入后 checkpoint, 使 _build 的冷读探测看到
    # 主文件事实而非未 checkpoint 的 -wal。
    issuer._repository._engine.dispose()
    return receipt


def _build(world: _ArchiveWorld, **overrides):
    from src.screening.offensive.v3.orchestration.official_trial_stack import (
        build_official_trial_stack,
    )

    kwargs = dict(
        identity_dir=world.identity_dir,
        trial_root=world.root,
        trial_id=TRIAL_ID,
        sizing_config=world.sizing_config,
        clock=lambda: datetime(2026, 8, 6, 15, 30, tzinfo=UTC),
        market_scenario=world.market_scenario,
        trial_attribution=world.trial_attribution,
        research_program_id="research.btst.regime",
    )
    kwargs.update(overrides)
    return build_official_trial_stack(**kwargs)


def test_selects_latest_issued_at_not_filename_order(tmp_path):
    """字典序与签发顺序相反时, 选择由 issued_at 决定 (RED for R27 缺陷)。"""
    world = _official_archive_world(tmp_path)
    # 字典序大 (zeta) = 签发更早; 字典序小 (alpha) = 签发更晚。
    old = _issue_receipt(
        world.issuer, stage_id="stage-zeta", issued_at=GOV_NOW - timedelta(minutes=2)
    )
    new = _issue_receipt(
        world.issuer, stage_id="stage-alpha", issued_at=GOV_NOW - timedelta(minutes=1)
    )
    assert old.issued_at < new.issued_at
    write_stage_issuance_receipt(world.root, old)
    write_stage_issuance_receipt(world.root, new)

    stack = _build(world)
    # 修复前: sorted(glob)[-1] 按文件名选 stage-zeta (旧签发)。
    assert stack.stage_receipt.stage_id == "stage-alpha"


def test_explicit_stage_id_selects_exact_receipt(tmp_path):
    world = _official_archive_world(tmp_path)
    old = _issue_receipt(
        world.issuer, stage_id="stage-zeta", issued_at=GOV_NOW - timedelta(minutes=2)
    )
    new = _issue_receipt(
        world.issuer, stage_id="stage-alpha", issued_at=GOV_NOW - timedelta(minutes=1)
    )
    write_stage_issuance_receipt(world.root, old)
    write_stage_issuance_receipt(world.root, new)

    stack = _build(world, stage_id="stage-zeta")
    assert stack.stage_receipt.stage_id == "stage-zeta"
    assert stack.stage_receipt.issued_at == old.issued_at


def test_corrupt_non_target_receipt_fails_closed(tmp_path):
    """归档中损坏的第三方回执必须阻断组装 (预置文件不能操纵选择面)。"""
    from src.screening.offensive.v3.orchestration.official_trial_stack import (
        OfficialStackError,
    )

    world = _official_archive_world(tmp_path)
    old = _issue_receipt(
        world.issuer, stage_id="stage-mid", issued_at=GOV_NOW - timedelta(minutes=3)
    )
    new = _issue_receipt(
        world.issuer, stage_id="stage-new", issued_at=GOV_NOW - timedelta(minutes=1)
    )
    write_stage_issuance_receipt(world.root, old)
    write_stage_issuance_receipt(world.root, new)
    # 预置: 字典序介于两者之间的损坏 json (旧行为只读 sorted()[-1] 静默忽略)。
    poison = world.root / "archive" / "stage-issuance" / TRIAL_ID / "stage-poison.json"
    poison.write_text("{not-valid-json", encoding="utf-8")

    with pytest.raises(OfficialStackError) as ei:
        _build(world)
    assert ei.value.code == "stage_receipt_corrupt"


def test_same_issued_at_different_stage_ids_ambiguous(tmp_path):
    """同 issued_at 双签是治理异常 — fail-closed 而非任选其一。"""
    from src.screening.offensive.v3.orchestration.official_trial_stack import (
        OfficialStackError,
    )

    world = _official_archive_world(tmp_path)
    at = GOV_NOW - timedelta(minutes=5)
    first = _issue_receipt(world.issuer, stage_id="stage-twin-a", issued_at=at)
    second = _issue_receipt(world.issuer, stage_id="stage-twin-b", issued_at=at)
    write_stage_issuance_receipt(world.root, first)
    write_stage_issuance_receipt(world.root, second)

    with pytest.raises(OfficialStackError) as ei:
        _build(world)
    assert ei.value.code == "stage_selection_ambiguous"


def test_single_receipt_without_stage_id_unchanged(tmp_path):
    """单回执缺省选择 — 既有 R27 行为保持。"""
    world = _official_archive_world(tmp_path)
    only = _issue_receipt(
        world.issuer, stage_id="stage-solo", issued_at=GOV_NOW - timedelta(minutes=1)
    )
    write_stage_issuance_receipt(world.root, only)

    stack = _build(world)
    assert stack.stage_receipt.stage_id == "stage-solo"


@pytest.mark.parametrize(
    "evil_stage_id",
    ["../escape", "sub/dir", "/abs/path", ".", ".."],
)
def test_explicit_stage_id_traversal_rejected(tmp_path, evil_stage_id):
    """对抗 PoC: stage_id 穿越/绝对注入在拼路径前即拒 (不到达 lstat)。"""
    from src.screening.offensive.v3.orchestration.official_trial_stack import (
        OfficialStackError,
    )

    world = _official_archive_world(tmp_path)
    only = _issue_receipt(
        world.issuer, stage_id="stage-solo", issued_at=GOV_NOW - timedelta(minutes=1)
    )
    write_stage_issuance_receipt(world.root, only)
    # 归档外放置一个同内容 json — 若穿越未被拦截, 冷读会成功返回它。
    escapee = tmp_path / "escape.json"
    escapee.write_text(
        (world.root / "archive" / "stage-issuance" / TRIAL_ID / "stage-solo.json")
        .read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    with pytest.raises(OfficialStackError) as ei:
        _build(world, stage_id=evil_stage_id)
    assert ei.value.code == "stage_id_rejected"


# ---------------------------------------------------------------------------
# R29: 组装器磁盘面 symlink 守卫 + trial_id 入口单段校验
# ---------------------------------------------------------------------------

def test_symlinked_evidence_db_rejected(tmp_path):
    """对抗 PoC (R28 审查延伸实锤): evidence.sqlite3 symlink 穿透 is_file。"""
    import os

    from src.screening.offensive.v3.orchestration.official_trial_stack import (
        OfficialStackError,
    )

    world = _official_archive_world(tmp_path)
    only = _issue_receipt(
        world.issuer, stage_id="stage-solo", issued_at=GOV_NOW - timedelta(minutes=1)
    )
    write_stage_issuance_receipt(world.root, only)
    # 敌手: 把 evidence.sqlite3 替换为指向外部伪库的 symlink。
    outside = tmp_path / "outside"
    outside.mkdir()
    evil = outside / "evil-evidence.sqlite3"
    evil.touch()
    (world.root / "evidence.sqlite3").unlink()
    os.symlink(evil, world.root / "evidence.sqlite3")

    with pytest.raises(OfficialStackError) as ei:
        _build(world)
    assert ei.value.code == "official_stack_path_rejected"


def test_symlinked_bars_db_rejected(tmp_path):
    import os

    from src.screening.offensive.v3.orchestration.official_trial_stack import (
        OfficialStackError,
    )

    world = _official_archive_world(tmp_path)
    only = _issue_receipt(
        world.issuer, stage_id="stage-solo", issued_at=GOV_NOW - timedelta(minutes=1)
    )
    write_stage_issuance_receipt(world.root, only)
    outside = tmp_path / "outside"
    outside.mkdir()
    evil = outside / "evil-bars.sqlite3"
    evil.touch()
    (world.root / "bars-evidence.sqlite3").unlink()
    os.symlink(evil, world.root / "bars-evidence.sqlite3")

    with pytest.raises(OfficialStackError) as ei:
        _build(world)
    assert ei.value.code == "official_stack_path_rejected"


@pytest.mark.parametrize(
    "db_name", ["spine.sqlite3", "decisions.sqlite3", "governance.sqlite3"]
)
def test_symlinked_runtime_dbs_rejected(tmp_path, db_name):
    """spine/decisions/governance 同族: 存在时必须是常规文件。"""
    import os

    from src.screening.offensive.v3.orchestration.official_trial_stack import (
        OfficialStackError,
    )

    world = _official_archive_world(tmp_path)
    only = _issue_receipt(
        world.issuer, stage_id="stage-solo", issued_at=GOV_NOW - timedelta(minutes=1)
    )
    write_stage_issuance_receipt(world.root, only)
    outside = tmp_path / "outside"
    outside.mkdir()
    evil = outside / f"evil-{db_name}"
    evil.touch()
    target = world.root / db_name
    if target.exists():
        target.unlink()
    os.symlink(evil, target)

    with pytest.raises(OfficialStackError) as ei:
        _build(world)
    assert ei.value.code == "official_stack_path_rejected"


def test_directory_in_place_of_evidence_db_rejected(tmp_path):
    """目录替换物同样拒绝 (非常规文件一族)。"""
    from src.screening.offensive.v3.orchestration.official_trial_stack import (
        OfficialStackError,
    )

    world = _official_archive_world(tmp_path)
    only = _issue_receipt(
        world.issuer, stage_id="stage-solo", issued_at=GOV_NOW - timedelta(minutes=1)
    )
    write_stage_issuance_receipt(world.root, only)
    (world.root / "evidence.sqlite3").unlink()
    (world.root / "evidence.sqlite3").mkdir()

    with pytest.raises(OfficialStackError) as ei:
        _build(world)
    assert ei.value.code == "official_stack_path_rejected"


@pytest.mark.parametrize(
    "evil_trial_id", ["sub/trial-b", "../escape", "/abs/trial", "trial-x/../trial-y"]
)
def test_trial_id_injection_rejected_at_entry(tmp_path, evil_trial_id):
    """trial_id 入口单段校验 (R28 修 stage_id 段, 本轮补 trial_id 段)。"""
    from src.screening.offensive.v3.orchestration.official_trial_stack import (
        OfficialStackError,
    )

    world = _official_archive_world(tmp_path)
    only = _issue_receipt(
        world.issuer, stage_id="stage-solo", issued_at=GOV_NOW - timedelta(minutes=1)
    )
    write_stage_issuance_receipt(world.root, only)

    with pytest.raises(OfficialStackError) as ei:
        _build(world, trial_id=evil_trial_id)
    assert ei.value.code == "trial_id_rejected"


# ---------------------------------------------------------------------------
# R31: trial_root resolve() 前全组件 walk — root symlink 重定向在守卫前拒绝
# ---------------------------------------------------------------------------

def test_trial_root_symlink_redirect_rejected(tmp_path):
    """对抗 PoC (R31): trial_root 自身是 symlink。

    修复前: 组装器第一步 ``Path(trial_root).resolve()`` 静默跟随 symlink,
    R29 的五库 lstat 守卫全部作用在目标 root 的真实路径上 — 官方栈在
    敌手指向的 root 上构造成功, 守卫永远看不到这次重定向。
    """
    import os

    from src.screening.offensive.v3.orchestration.official_trial_stack import (
        OfficialStackError,
    )

    world = _official_archive_world(tmp_path)
    only = _issue_receipt(
        world.issuer, stage_id="stage-solo", issued_at=GOV_NOW - timedelta(minutes=1)
    )
    write_stage_issuance_receipt(world.root, only)
    redirect = tmp_path / "victim-link"
    os.symlink(world.root, redirect)

    with pytest.raises(OfficialStackError) as ei:
        _build(world, trial_root=redirect)
    assert ei.value.code == "official_stack_path_rejected"


def test_trial_root_intermediate_symlink_component_rejected(tmp_path):
    """对抗 PoC (R31): 到 trial_root 的中间目录组件是 symlink — 同族拒绝。"""
    import os

    from src.screening.offensive.v3.orchestration.official_trial_stack import (
        OfficialStackError,
    )

    world = _official_archive_world(tmp_path)
    only = _issue_receipt(
        world.issuer, stage_id="stage-solo", issued_at=GOV_NOW - timedelta(minutes=1)
    )
    write_stage_issuance_receipt(world.root, only)
    holder = tmp_path / "holder"
    holder.mkdir()
    os.symlink(world.root.parent, holder / "link-comp")
    via_link = holder / "link-comp" / world.root.name

    with pytest.raises(OfficialStackError) as ei:
        _build(world, trial_root=via_link)
    assert ei.value.code == "official_stack_path_rejected"


def test_trial_root_relative_traversal_rejected(tmp_path, monkeypatch):
    """相对路径含 ``..`` 在 walk 前即拒 (canonical 绝对路径纪律)。"""
    from src.screening.offensive.v3.orchestration.official_trial_stack import (
        OfficialStackError,
    )

    world = _official_archive_world(tmp_path)
    only = _issue_receipt(
        world.issuer, stage_id="stage-solo", issued_at=GOV_NOW - timedelta(minutes=1)
    )
    write_stage_issuance_receipt(world.root, only)
    monkeypatch.chdir(tmp_path)
    relative_escape = "../" + world.root.name

    with pytest.raises(OfficialStackError) as ei:
        _build(world, trial_root=relative_escape)
    # R34 收紧单码: walk_components 的 .. 前置检查在 lstat 前 — 若该
    # 前置被移除/重排, 测试必须红 (双码断言会掩盖回归)。
    assert ei.value.code == "path_traversal"


# ---------------------------------------------------------------------------
# R33: stage 回执选择面内容绑定 — 文件名↔id / 外 trial / 同 id 双时刻
# ---------------------------------------------------------------------------

FOREIGN_TRIAL_ID = "trial-foreign-002"


def _foreign_trial_receipt(tmp_path: Path):
    """独立治理库 + 真实签发链的外 trial 回执 (trial_id ≠ TRIAL_ID)。

    与主世界完全独立 (独立 sqlite), 复用 governance crib 组件重组
    seal 链 — 只改 trial_id, envelope 以改后 canonical bytes 重签。
    """
    from src.screening.offensive.v3.contracts.regime import RegimeAdmissionMode
    from src.screening.offensive.v3.governance.repository import (
        GovernanceRepository,
        RegimeTrialSealRequest,
    )
    from src.screening.offensive.v3.governance.stage_issuance import (
        StageIssuanceRequest,
    )
    from test_regime_trial_governance import (
        _baseline_activation,
        _governance_trust,
        _sap_manifest,
        _trial_manifest,
        _trial_policy,
    )

    sign, verifier, current_head, caps = _governance_trust()
    baseline = _trial_policy(RegimeAdmissionMode.IGNORE)
    target = _trial_policy(RegimeAdmissionMode.NORMAL_ONLY)
    trial = _trial_manifest(baseline, target).model_copy(
        update={"trial_id": FOREIGN_TRIAL_ID}
    )
    sap = _sap_manifest(trial)
    activation = _baseline_activation(baseline)
    governance = GovernanceRepository(
        database_path=str(tmp_path / "foreign-governance.sqlite3"),
        clock=lambda: GOV_NOW,
    )
    governance.seal_regime_trial(
        RegimeTrialSealRequest(
            stage_id="stage-regime-001",
            signed_trial_envelope=sign(trial.canonical_bytes(), caps["trial"]),
            trial_manifest=trial,
            trial_capability=caps["trial"],
            signed_sap_envelope=sign(sap.canonical_bytes(), caps["sap"]),
            sap_manifest=sap,
            sap_capability=caps["sap"],
            signed_baseline_activation_envelope=sign(
                activation.canonical_bytes(), caps["activation"]
            ),
            baseline_policy_activation=activation,
            baseline_activation_capability=caps["activation"],
            baseline_policy=baseline,
            target_policy=target,
            expected_signal_cutoff=GOV_NOW,
        ),
        verifier=verifier,
        current_head=current_head,
        trusted_at=ENROLLMENT_START,
    )
    from src.screening.offensive.v3.governance.stage_issuance import (
        GovernanceStageIssuer,
    )

    issuer = GovernanceStageIssuer(
        repository=governance,
        signer=lambda payload: sign(payload, caps["stage"]),
        stage_capability=caps["stage"],
        verifier=verifier,
        trust_head=lambda: current_head,
        clock=lambda: GOV_NOW,
    )
    return issuer.issue(
        StageIssuanceRequest(
            trial_id=FOREIGN_TRIAL_ID,
            stage_id="stage-foreign",
            stage_sample_reservation_id="smp-f",
            alpha_sample_consumption_id="alpha-f",
            alpha_or_evalue_budget_consumption_id="budget-f",
            attempt_ledger_checkpoint_hash="a" * 64,
            stage_loss_budget_id="loss-f",
            stage_loss_version=1,
            maximum_loss_budget_cents=1_000_000,
            issuer_id="governance.service",
            issued_at=GOV_NOW - timedelta(minutes=1),
        )
    )


def test_explicit_stage_id_filename_content_mismatch_rejected(tmp_path):
    """对抗 PoC (R33-①): a.json 内含 stage_id=b 的合法回执。

    修复前: 显式 stage_id 分支冷读后不断言 receipt.stage_id == 请求值,
    静默接线 b 的治理事实 (manifest hash/enrollment 窗口全部错位)。
    """
    from src.screening.offensive.v3.orchestration.official_trial_stack import (
        OfficialStackError,
    )

    world = _official_archive_world(tmp_path)
    receipt = _issue_receipt(
        world.issuer, stage_id="stage-content", issued_at=GOV_NOW - timedelta(minutes=1)
    )
    # 手写文件名 ≠ 内容 stage_id (write 面按内容定路径 — 该形态只能来自
    # 手工放置/预置; 归档文件名从未被校验绑定内容)。
    mismatch = (
        world.root / "archive" / "stage-issuance" / TRIAL_ID / "stage-filename.json"
    )
    mismatch.parent.mkdir(parents=True, exist_ok=True)
    mismatch.write_text(receipt.model_dump_json(), encoding="utf-8")

    with pytest.raises(OfficialStackError) as ei:
        _build(world, stage_id="stage-filename")
    assert ei.value.code == "stage_receipt_id_mismatch"


def test_foreign_trial_receipt_in_archive_rejected(tmp_path):
    """对抗 PoC (R33-②): 外 trial 真实签发链回执预置进本 trial 归档。

    issued_at 比主世界唯一回执更晚 — 参与缺省 max 选择并胜出; 修复前
    静默选择它, 唯一防线是 assemble 深处的 stage_trial_mismatch 兜底
    (R28 立论: 深处是兜底而非纵深)。
    """
    from src.screening.offensive.v3.orchestration.official_trial_stack import (
        OfficialStackError,
    )

    world = _official_archive_world(tmp_path)
    local = _issue_receipt(
        world.issuer, stage_id="stage-local", issued_at=GOV_NOW - timedelta(minutes=5)
    )
    write_stage_issuance_receipt(world.root, local)
    foreign = _foreign_trial_receipt(tmp_path)
    assert foreign.trial_id == FOREIGN_TRIAL_ID
    assert foreign.issued_at > local.issued_at
    poison = world.root / "archive" / "stage-issuance" / TRIAL_ID / "stage-foreign.json"
    poison.write_text(foreign.model_dump_json(), encoding="utf-8")

    with pytest.raises(OfficialStackError) as ei:
        _build(world)
    assert ei.value.code == "stage_receipt_foreign_trial"


def test_duplicate_stage_id_different_issued_at_rejected(tmp_path):
    """对抗 PoC (R33-③): 双独立签发链同 stage_id 不同 issued_at。

    归档内两文件内容 stage_id 同为 stage-dup, issued_at t1 < t2。修复前
    选择循环按文件名序返回首个 id 匹配 — 预置文件名可让旧签发胜出;
    seal_stage 写面对同 id 异内容是 stage_seal_conflict, 读面缺同款。
    """
    from src.screening.offensive.v3.orchestration.official_trial_stack import (
        OfficialStackError,
    )

    world = _official_archive_world(tmp_path)
    older = _issue_receipt(
        world.issuer, stage_id="stage-dup", issued_at=GOV_NOW - timedelta(minutes=9)
    )
    # 第二条独立签发链 (独立治理库): 同 trial 同 stage_id、更晚时刻。
    from src.screening.offensive.v3.governance.repository import (
        GovernanceRepository,
    )

    governance_b = GovernanceRepository(
        database_path=str(tmp_path / "second-governance.sqlite3"),
        clock=lambda: GOV_NOW,
    )
    request, sign, verifier, current_head, caps, _bundle = _seal_request()
    governance_b.seal_regime_trial(
        request, verifier=verifier, current_head=current_head,
        trusted_at=ENROLLMENT_START,
    )
    from src.screening.offensive.v3.governance.stage_issuance import (
        GovernanceStageIssuer,
        StageIssuanceRequest,
    )

    issuer_b = GovernanceStageIssuer(
        repository=governance_b,
        signer=lambda payload: sign(payload, caps["stage"]),
        stage_capability=caps["stage"],
        verifier=verifier,
        trust_head=lambda: current_head,
        clock=lambda: GOV_NOW,
    )
    newer = issuer_b.issue(
        StageIssuanceRequest(
            trial_id=TRIAL_ID,
            stage_id="stage-dup",
            stage_sample_reservation_id="smp-x",
            alpha_sample_consumption_id="alpha-x",
            alpha_or_evalue_budget_consumption_id="budget-x",
            attempt_ledger_checkpoint_hash="b" * 64,
            stage_loss_budget_id="loss-x",
            stage_loss_version=1,
            maximum_loss_budget_cents=1_000_000,
            issuer_id="governance.service",
            issued_at=GOV_NOW - timedelta(minutes=1),
        )
    )
    assert newer.issued_at > older.issued_at
    archive = world.root / "archive" / "stage-issuance" / TRIAL_ID
    archive.mkdir(parents=True, exist_ok=True)
    # 文件名刻意让旧的排在前 (字典序 aa < zz) — 修复前首个匹配即旧回执。
    (archive / "stage-dup-older.json").write_text(older.model_dump_json(), encoding="utf-8")
    (archive / "stage-dup-znewer.json").write_text(newer.model_dump_json(), encoding="utf-8")

    with pytest.raises(OfficialStackError) as ei:
        _build(world)
    assert ei.value.code == "stage_receipt_duplicate_id"


# ---------------------------------------------------------------------------
# R30: spine 预置纪律 (宪法 #13 expected-session spine 是预注册治理事实)
# ---------------------------------------------------------------------------

def test_missing_spine_fails_closed(tmp_path):
    """缺失 spine.sqlite3 不再静默自建 — 注册流程必须先跑 (RED for 缺口)。

    静默新建的完整性代价: runner finalize_missed_sessions 消费
    enrolled_sessions, 空 spine 使错过会话的 NO_RUN 补记静默失效。
    """
    from src.screening.offensive.v3.orchestration.official_trial_stack import (
        OfficialStackError,
    )

    world = _official_archive_world(tmp_path)
    only = _issue_receipt(
        world.issuer, stage_id="stage-solo", issued_at=GOV_NOW - timedelta(minutes=1)
    )
    write_stage_issuance_receipt(world.root, only)
    (world.root / "spine.sqlite3").unlink(missing_ok=True)

    with pytest.raises(OfficialStackError) as ei:
        _build(world)
    assert ei.value.code == "trial_root_not_initialized"


def test_preprovisioned_empty_spine_rejected(tmp_path):
    """空 touch spine 文件拒绝 (R32) — R30 只拒缺文件, 空文件形态原样绕过。

    R30 版测试曾固化「空文件接受, enrollment 内容校验属 worker/runner」—
    对抗审查证实 worker/runner 侧不存在该校验 (无主校验): SessionSpine
    __init__ 对 0 字节文件静默建全套 DDL, 零 enrollment 的空 spine 使
    finalize_missed_sessions 的 NO_RUN 补记静默失效。
    """
    from src.screening.offensive.v3.orchestration.official_trial_stack import (
        OfficialStackError,
    )

    world = _official_archive_world(tmp_path)
    only = _issue_receipt(
        world.issuer, stage_id="stage-solo", issued_at=GOV_NOW - timedelta(minutes=1)
    )
    write_stage_issuance_receipt(world.root, only)
    (world.root / "spine.sqlite3").unlink(missing_ok=True)
    (world.root / "spine.sqlite3").touch()

    with pytest.raises(OfficialStackError) as ei:
        _build(world)
    assert ei.value.code == "spine_not_registered"


def test_foreign_program_spine_rejected(tmp_path):
    """异 research_program 的合法 spine 拒绝 (R32) — 治理事实归属校验。

    预置一个只 enroll 了 prog-other 的完整 spine: 按 program 过滤后
    enrollment 为空, 修复前静默通过 (归属分歧永不暴露), 修复后拒绝。
    同时收口组装器接线错误 (research_program_id 传错提前失败)。
    """
    from src.screening.offensive.v3.evidence.session_spine import (
        SessionEnrollment,
        SessionSpine,
    )
    from src.screening.offensive.v3.orchestration.official_trial_stack import (
        OfficialStackError,
    )

    world = _official_archive_world(tmp_path)
    only = _issue_receipt(
        world.issuer, stage_id="stage-solo", issued_at=GOV_NOW - timedelta(minutes=1)
    )
    write_stage_issuance_receipt(world.root, only)
    (world.root / "spine.sqlite3").unlink(missing_ok=True)
    foreign = SessionSpine(
        database_path=str(world.root / "spine.sqlite3"),
        clock=lambda: GOV_NOW,
    )
    foreign.enroll_expected_sessions(
        (SessionEnrollment("prog-other", date(2026, 8, 6), date(2026, 8, 6)),)
    )
    foreign._engine.dispose()  # R35 冷读前置: 持有引用的引擎不 dispose 会留 -wal

    with pytest.raises(OfficialStackError) as ei:
        _build(world)  # research_program_id=research.btst.regime (封存对齐)
    assert ei.value.code == "spine_not_registered"


def test_missing_governance_db_rejected(tmp_path):
    """缺 governance.sqlite3 不再静默自建 (R32) — 封存流程产物同族纪律。

    docstring 自述「治理库由封存流程预置, 本层只读」, 但缺失时
    GovernanceRepository.__init__ 静默 CREATE TABLE 自建空治理库,
    失败推迟到首次 decide 的 stage_unknown — 掩盖「封存流程没跑」。
    """
    from src.screening.offensive.v3.orchestration.official_trial_stack import (
        OfficialStackError,
    )

    world = _official_archive_world(tmp_path)
    only = _issue_receipt(
        world.issuer, stage_id="stage-solo", issued_at=GOV_NOW - timedelta(minutes=1)
    )
    write_stage_issuance_receipt(world.root, only)
    (world.root / "governance.sqlite3").unlink(missing_ok=True)

    with pytest.raises(OfficialStackError) as ei:
        _build(world)
    assert ei.value.code == "trial_root_not_initialized"


def test_missing_decisions_store_still_self_builds(tmp_path):
    """decisions.sqlite3 是运行时产物 (首决策产生) — 缺失维持自建语义。"""
    world = _official_archive_world(tmp_path)
    only = _issue_receipt(
        world.issuer, stage_id="stage-solo", issued_at=GOV_NOW - timedelta(minutes=1)
    )
    write_stage_issuance_receipt(world.root, only)
    (world.root / "decisions.sqlite3").unlink(missing_ok=True)

    stack = _build(world)
    assert stack.decision_store is not None


def test_same_id_same_instant_two_files_ambiguous(tmp_path):
    """对抗审查复核 (R33 后): 同 stage_id 同 issued_at 异内容双文件。

    审查者断言该形态静默按文件名序选择 — 实证 ``candidates`` 列表推导
    不去重 (["S","S"] 长度 2) → ``stage_selection_ambiguous`` fail-closed。
    本测试钉死该形态, 防止未来去重"优化"重新打开它。
    """
    from src.screening.offensive.v3.governance.repository import (
        GovernanceRepository,
    )
    from src.screening.offensive.v3.governance.stage_issuance import (
        GovernanceStageIssuer,
        StageIssuanceRequest,
    )
    from src.screening.offensive.v3.orchestration.official_trial_stack import (
        OfficialStackError,
    )

    world = _official_archive_world(tmp_path)
    at = GOV_NOW - timedelta(minutes=5)
    first = _issue_receipt(world.issuer, stage_id="stage-twin", issued_at=at)
    governance_b = GovernanceRepository(
        database_path=str(tmp_path / "twin-governance.sqlite3"),
        clock=lambda: GOV_NOW,
    )
    request, sign, verifier, current_head, caps, _bundle = _seal_request()
    governance_b.seal_regime_trial(
        request, verifier=verifier, current_head=current_head,
        trusted_at=ENROLLMENT_START,
    )
    issuer_b = GovernanceStageIssuer(
        repository=governance_b,
        signer=lambda payload: sign(payload, caps["stage"]),
        stage_capability=caps["stage"],
        verifier=verifier,
        trust_head=lambda: current_head,
        clock=lambda: GOV_NOW,
    )
    second = issuer_b.issue(
        StageIssuanceRequest(
            trial_id=TRIAL_ID,
            stage_id="stage-twin",
            stage_sample_reservation_id="smp-t",
            alpha_sample_consumption_id="alpha-t",
            alpha_or_evalue_budget_consumption_id="budget-t",
            attempt_ledger_checkpoint_hash="f" * 64,
            stage_loss_budget_id="loss-t",
            stage_loss_version=1,
            maximum_loss_budget_cents=1_000_000,
            issuer_id="governance.service",
            issued_at=at,
        )
    )
    assert first.issued_at == second.issued_at
    assert first.content_hash() != second.content_hash()
    archive = world.root / "archive" / "stage-issuance" / TRIAL_ID
    archive.mkdir(parents=True, exist_ok=True)
    (archive / "stage-a-first.json").write_text(first.model_dump_json(), encoding="utf-8")
    (archive / "stage-z-second.json").write_text(second.model_dump_json(), encoding="utf-8")

    with pytest.raises(OfficialStackError) as ei:
        _build(world)
    assert ei.value.code == "stage_selection_ambiguous"


# ---------------------------------------------------------------------------
# R34: 三轮对抗审查返工 — governance 0 字节 / program 三角互证 / identity walk
# ---------------------------------------------------------------------------

def test_empty_touch_governance_db_rejected(tmp_path):
    """0 字节 governance.sqlite3 拒绝 (R34) — R32 只封缺文件的自我镜像。

    0 字节是常规文件, 通过 R32 的 lstat 守卫; GovernanceRepository.__init__
    的 CREATE TABLE IF NOT EXISTS 静默建空表, 失败推迟到首次 decide 的
    stage_unknown — 与 R32 批判 R30「只拒缺文件, 空文件形态原样绕过」
    同构。修复 = 构造期 quiet 读 regime_trial_bundle (stage 签发的单一
    事实源), 空库即 governance_not_sealed。
    """
    from src.screening.offensive.v3.orchestration.official_trial_stack import (
        OfficialStackError,
    )

    world = _official_archive_world(tmp_path)
    only = _issue_receipt(
        world.issuer, stage_id="stage-solo", issued_at=GOV_NOW - timedelta(minutes=1)
    )
    write_stage_issuance_receipt(world.root, only)
    (world.root / "governance.sqlite3").unlink(missing_ok=True)
    (world.root / "governance.sqlite3").touch()
    # R35: 清残留 sidecar, 本测试钉 0 字节主文件形态 (sidecar 形态由
    # test_stale_wal_sidecar_* 单独覆盖)。
    for suffix in ("-wal", "-shm"):
        (world.root / f"governance.sqlite3{suffix}").unlink(missing_ok=True)

    with pytest.raises(OfficialStackError) as ei:
        _build(world)
    assert ei.value.code == "governance_not_sealed"


def test_spine_program_vs_sealed_manifest_mismatch_rejected(tmp_path):
    """spine↔封存 manifest program 三角互证 (R34) — R32 只闭合了一条边。

    fixture 曾以完全错位的 program 组装成功 (spine prog-1 vs 封存
    research.btst.regime), NO_RUN 补记按错误 program 记账。
    """
    from datetime import date as _d

    from src.screening.offensive.v3.evidence.session_spine import (
        SessionEnrollment,
        SessionSpine,
    )
    from src.screening.offensive.v3.orchestration.official_trial_stack import (
        OfficialStackError,
    )

    world = _official_archive_world(tmp_path)
    only = _issue_receipt(
        world.issuer, stage_id="stage-solo", issued_at=GOV_NOW - timedelta(minutes=1)
    )
    write_stage_issuance_receipt(world.root, only)
    (world.root / "spine.sqlite3").unlink(missing_ok=True)
    mismatched = SessionSpine(
        database_path=str(world.root / "spine.sqlite3"), clock=lambda: GOV_NOW
    )
    mismatched.enroll_expected_sessions(
        (SessionEnrollment("prog-mismatched", _d(2026, 8, 6), _d(2026, 8, 6)),)
    )
    mismatched._engine.dispose()  # R35 冷读前置 (确定性 checkpoint)

    with pytest.raises(OfficialStackError) as ei:
        _build(world, research_program_id="prog-mismatched")
    assert ei.value.code == "program_binding_mismatch"


def test_identity_dir_symlink_redirect_rejected(tmp_path):
    """identity_dir 全组件 walk (R34) — R31 同族面收口。

    身份目录是全部签名面的信任链根; 预置 identity-dir -> 敌手身份目录
    (generate 是离线原语, 敌手可自建合法形态) 时 R31 的守卫对它无效 —
    load_governance_identity 的 identity.json 用 is_file() 跟随 symlink。
    """
    import os

    from src.screening.offensive.v3.orchestration.official_trial_stack import (
        OfficialStackError,
    )

    world = _official_archive_world(tmp_path)
    only = _issue_receipt(
        world.issuer, stage_id="stage-solo", issued_at=GOV_NOW - timedelta(minutes=1)
    )
    write_stage_issuance_receipt(world.root, only)
    redirect = tmp_path / "identity-link"
    os.symlink(world.identity_dir, redirect)

    with pytest.raises(OfficialStackError) as ei:
        _build(world, identity_dir=redirect)
    assert ei.value.code == "official_stack_path_rejected"


# ---------------------------------------------------------------------------
# R35: R34 登记三遗留项收口 — 拒绝路径零写痕全形态 + sidecar 复活收口
# ---------------------------------------------------------------------------

def _make_decoy_sqlite(path: Path) -> None:
    """非零空 schema 形态: 合法 sqlite 文件但不含任何 spine/governance 表。

    R34 的 0 字节特检只封最常见污染形态 — 非零字节但未注册 schema 的
    文件 (异工具产物/半成品) 原样穿过特检, 写副作用发生在 __init__。
    """
    import sqlite3 as _sqlite3

    connection = _sqlite3.connect(str(path))
    try:
        connection.execute("CREATE TABLE decoy (x INTEGER)")
        connection.commit()
    finally:
        connection.close()


def _clear_sidecars(path: Path) -> None:
    """清除事实文件的 -wal/-shm 残留, 使测试钉主文件形态本身。"""
    for suffix in ("-wal", "-shm"):
        (path.parent / f"{path.name}{suffix}").unlink(missing_ok=True)


def _snapshot_fact_file(path: Path) -> tuple[bytes, frozenset[str]]:
    """(文件字节, 同名 sidecar 集) — 拒绝路径零写痕断言的取证快照。"""
    return (
        path.read_bytes(),
        frozenset(
            entry.name
            for entry in path.parent.iterdir()
            if entry.name.startswith(path.name)
        ),
    )


def test_nonzero_empty_schema_spine_rejected_zero_write(tmp_path):
    """非零空 schema spine 拒绝且零写痕 (R35 发现 5 全形态收口)。

    修复前 (RED 实证): SessionSpine.__init__ 对该文件先落全套 DDL
    (文件字节被拒绝路径改写) 再以 enrolled 空拒绝 — R34 承诺的
    「读侧组装对预注册治理事实文件零写痕迹」在非 0 字节形态失效。
    """
    from src.screening.offensive.v3.orchestration.official_trial_stack import (
        OfficialStackError,
    )

    world = _official_archive_world(tmp_path)
    only = _issue_receipt(
        world.issuer, stage_id="stage-solo", issued_at=GOV_NOW - timedelta(minutes=1)
    )
    write_stage_issuance_receipt(world.root, only)
    spine = world.root / "spine.sqlite3"
    spine.unlink()
    _make_decoy_sqlite(spine)
    _clear_sidecars(spine)
    before = _snapshot_fact_file(spine)

    with pytest.raises(OfficialStackError) as ei:
        _build(world)
    assert ei.value.code == "spine_not_registered"
    after = _snapshot_fact_file(spine)
    assert after[0] == before[0], "rejected assembly must not rewrite the spine bytes"
    assert after[1] == before[1], "rejected assembly must not create WAL/SHM sidecars"


def test_nonzero_empty_schema_governance_rejected_zero_write(tmp_path):
    """非零空 schema governance 拒绝且零写痕 (R35 发现 5 同族收口)。

    修复前 (RED 实证): GovernanceRepository.__init__ 对该文件先落全套
    治理 DDL (字节被拒绝路径改写), 再由 R34 的 regime_trial_bundle
    quiet 读拒绝 — 错误码正确但文件已被污染。
    """
    from src.screening.offensive.v3.orchestration.official_trial_stack import (
        OfficialStackError,
    )

    world = _official_archive_world(tmp_path)
    only = _issue_receipt(
        world.issuer, stage_id="stage-solo", issued_at=GOV_NOW - timedelta(minutes=1)
    )
    write_stage_issuance_receipt(world.root, only)
    governance_db = world.root / "governance.sqlite3"
    governance_db.unlink()
    _make_decoy_sqlite(governance_db)
    _clear_sidecars(governance_db)
    before = _snapshot_fact_file(governance_db)

    with pytest.raises(OfficialStackError) as ei:
        _build(world)
    assert ei.value.code == "governance_not_sealed"
    after = _snapshot_fact_file(governance_db)
    assert after[0] == before[0], (
        "rejected assembly must not rewrite the governance bytes"
    )
    assert after[1] == before[1], (
        "rejected assembly must not create WAL/SHM sidecars on governance"
    )


def test_garbage_spine_bytes_rejected_typed(tmp_path):
    """垃圾字节 spine 类型化拒绝 (R35)。

    修复前 (RED 实证): 非 OfficialStackError 的原始异常泄漏, 或 (sidecar
    在场时) 经复活静默通过 — 违反 fail-closed 类型化纪律。
    """
    from src.screening.offensive.v3.orchestration.official_trial_stack import (
        OfficialStackError,
    )

    world = _official_archive_world(tmp_path)
    only = _issue_receipt(
        world.issuer, stage_id="stage-solo", issued_at=GOV_NOW - timedelta(minutes=1)
    )
    write_stage_issuance_receipt(world.root, only)
    spine = world.root / "spine.sqlite3"
    spine.unlink()
    spine.write_bytes(b"this is definitely not a sqlite database\n" * 4)
    _clear_sidecars(spine)
    before = _snapshot_fact_file(spine)

    with pytest.raises(OfficialStackError) as ei:
        _build(world)
    assert ei.value.code == "spine_not_registered"
    assert _snapshot_fact_file(spine) == before


def test_garbage_governance_bytes_rejected_typed(tmp_path):
    """垃圾字节 governance 类型化拒绝 (R35, 清 sidecar 后钉主文件形态)。"""
    from src.screening.offensive.v3.orchestration.official_trial_stack import (
        OfficialStackError,
    )

    world = _official_archive_world(tmp_path)
    only = _issue_receipt(
        world.issuer, stage_id="stage-solo", issued_at=GOV_NOW - timedelta(minutes=1)
    )
    write_stage_issuance_receipt(world.root, only)
    governance_db = world.root / "governance.sqlite3"
    governance_db.unlink()
    governance_db.write_bytes(b"\x00\x01garbage - not a sqlite file\xff" * 3)
    _clear_sidecars(governance_db)
    before = _snapshot_fact_file(governance_db)

    with pytest.raises(OfficialStackError) as ei:
        _build(world)
    assert ei.value.code == "governance_not_sealed"
    assert _snapshot_fact_file(governance_db) == before


def test_stale_wal_sidecar_resurrection_rejected(tmp_path):
    """sidecar 复活 PoC (R35 Act 期对抗发现, 修复主证据)。

    修复前 (RED 实证): 主文件替换为 90 字节垃圾 + 残留未 checkpoint 的
    -wal/-shm (当时来自 fixture 泄漏, 等价于敌手植入) → 组装**静默
    成功**, 构造期 regime_trial_bundle 经 sidecar 复活返回合法封存
    bundle —「文件字节」与「消费到的事实」脱钩。
    修复后: governance_not_checkpointed (探测先于任何 sqlite 打开)。
    """
    from src.screening.offensive.v3.orchestration.official_trial_stack import (
        OfficialStackError,
    )

    world = _official_archive_world(tmp_path)
    only = _issue_receipt(
        world.issuer, stage_id="stage-solo", issued_at=GOV_NOW - timedelta(minutes=1)
    )
    write_stage_issuance_receipt(world.root, only)
    governance_db = world.root / "governance.sqlite3"
    # fixture 冷读前置后不再自然泄漏 -wal (这正是语义所在) — 敌手形态
    # 是「替换主文件 + 植入 sidecar」, 在此显式植入。
    governance_db.unlink()
    governance_db.write_bytes(b"\x00\x01garbage - not a sqlite file\xff" * 3)
    (world.root / "governance.sqlite3-wal").write_bytes(b"planted-stale-wal")

    with pytest.raises(OfficialStackError) as ei:
        _build(world)
    assert ei.value.code == "governance_not_checkpointed"


def test_sidecar_present_spine_rejected(tmp_path):
    """合法 spine 但残留 -wal → spine_not_checkpointed (sidecar 形态面)。"""
    from src.screening.offensive.v3.orchestration.official_trial_stack import (
        OfficialStackError,
    )

    world = _official_archive_world(tmp_path)
    only = _issue_receipt(
        world.issuer, stage_id="stage-solo", issued_at=GOV_NOW - timedelta(minutes=1)
    )
    write_stage_issuance_receipt(world.root, only)
    (world.root / "spine.sqlite3-wal").write_bytes(b"stale-wal-debris")

    with pytest.raises(OfficialStackError) as ei:
        _build(world)
    assert ei.value.code == "spine_not_checkpointed"


def test_probe_tables_track_schema_ddl():
    """探测 SQL 表名 drift guard (R35): schema 演化时探测必须同步。

    探测 SQL 引用的表必须仍是各自 _SCHEMA_DDL 声明的表 — 否则未来
    schema 演化会把合法已注册文件误判为未注册 (fail-closed 退化)。
    """
    import re as _re

    from src.screening.offensive.v3.evidence import session_spine as _spine_mod
    from src.screening.offensive.v3.governance import repository as _gov_mod
    from src.screening.offensive.v3.orchestration import (
        official_trial_stack as _stack_mod,
    )

    declared = set(
        _re.findall(
            r"CREATE TABLE IF NOT EXISTS\s+(\w+)",
            "\n".join(_spine_mod._SCHEMA_DDL),
        )
    ) | set(
        _re.findall(
            r"CREATE TABLE IF NOT EXISTS\s+(\w+)",
            "\n".join(_gov_mod._SCHEMA_DDL),
        )
    )
    probes = (
        _stack_mod._SPINE_ENROLLMENT_PROBE_SQL,
        _stack_mod._GOVERNANCE_SEALED_PROBE_SQL,
    )
    referenced = {
        table for sql in probes for table in _re.findall(r"FROM\s+(\w+)", sql)
    }
    assert referenced <= declared


# -- R37: 运行时 append 面证据库 (evidence/bars) 冷读零写痕探测 ---------------


def _receipted_world(tmp_path):
    world = _official_archive_world(tmp_path)
    only = _issue_receipt(
        world.issuer, stage_id="stage-solo", issued_at=GOV_NOW - timedelta(minutes=1)
    )
    write_stage_issuance_receipt(world.root, only)
    return world


def test_zero_byte_evidence_db_rejected_zero_write(tmp_path):
    """0 字节 evidence 库拒绝且零写痕 (R37)。

    修复前 (RED 实证): EvidenceRepository.__init__ 对 0 字节文件静默落
    WAL+DDL (组装读路径改写事实文件字节), 以「合法空证据世界」通过 —
    fixture 曾以 touch() 依赖该副作用。修复后 evidence_not_seeded 且
    拒绝路径字节与 sidecar 零写痕。
    """
    from src.screening.offensive.v3.orchestration.official_trial_stack import (
        OfficialStackError,
    )

    world = _receipted_world(tmp_path)
    evidence_db = world.root / "evidence.sqlite3"
    evidence_db.unlink()
    evidence_db.touch()
    _clear_sidecars(evidence_db)
    before = _snapshot_fact_file(evidence_db)

    with pytest.raises(OfficialStackError) as ei:
        _build(world)
    assert ei.value.code == "evidence_not_seeded"
    after = _snapshot_fact_file(evidence_db)
    assert after[0] == before[0], (
        "rejected assembly must not rewrite the evidence bytes"
    )
    assert after[1] == before[1], (
        "rejected assembly must not create WAL/SHM sidecars on evidence"
    )


def test_real_schema_zero_records_evidence_db_rejected(tmp_path):
    """真实 schema 但零记录的 evidence 库拒绝 (R37) — 事实是记录不是 schema。

    「repo 开过一次但从未发布」形态: 全套 evidence DDL 在、evidence_head
    genesis 行在、evidence_records 空 — 修复前静默通过 (空证据世界)。
    修复后拒绝: regime 命名空间 ≥1 条 committed 记录才是启动完成事实
    (批规则 v1 固定成员; runbook ④ 前置)。
    """
    import sqlite3 as _sqlite3

    from src.screening.offensive.v3.evidence.repository import _SCHEMA_DDL
    from src.screening.offensive.v3.orchestration.official_trial_stack import (
        OfficialStackError,
    )

    world = _receipted_world(tmp_path)
    evidence_db = world.root / "evidence.sqlite3"
    evidence_db.unlink()
    connection = _sqlite3.connect(str(evidence_db))
    try:
        for ddl in _SCHEMA_DDL:
            connection.execute(ddl)
        connection.commit()
    finally:
        connection.close()
    _clear_sidecars(evidence_db)

    with pytest.raises(OfficialStackError) as ei:
        _build(world)
    assert ei.value.code == "evidence_not_seeded"


def test_garbage_evidence_db_rejected_typed(tmp_path):
    """垃圾字节 evidence 库类型化拒绝 (R37)。

    修复前 (RED 实证): DDL 执行以非类型化 sqlalchemy/sqlite3 异常泄漏
    (组装器 typed-error 纪律破口)。修复后统一 evidence_not_seeded。
    """
    from src.screening.offensive.v3.orchestration.official_trial_stack import (
        OfficialStackError,
    )

    world = _receipted_world(tmp_path)
    evidence_db = world.root / "evidence.sqlite3"
    evidence_db.write_bytes(b"\x90" * 90)
    _clear_sidecars(evidence_db)
    before = _snapshot_fact_file(evidence_db)

    with pytest.raises(OfficialStackError) as ei:
        _build(world)
    assert ei.value.code == "evidence_not_seeded"
    after = _snapshot_fact_file(evidence_db)
    assert after[0] == before[0], "typed rejection must be zero-write"
    assert after[1] == before[1]


def test_zero_byte_bars_db_rejected_zero_write(tmp_path):
    """0 字节 bars 库拒绝且零写痕 (R37) — bars_store_not_seeded。"""
    from src.screening.offensive.v3.orchestration.official_trial_stack import (
        OfficialStackError,
    )

    world = _receipted_world(tmp_path)
    bars_db = world.root / "bars-evidence.sqlite3"
    bars_db.unlink()
    bars_db.touch()
    _clear_sidecars(bars_db)
    before = _snapshot_fact_file(bars_db)

    with pytest.raises(OfficialStackError) as ei:
        _build(world)
    assert ei.value.code == "bars_store_not_seeded"
    after = _snapshot_fact_file(bars_db)
    assert after[0] == before[0], (
        "rejected assembly must not rewrite the bars bytes"
    )
    assert after[1] == before[1], (
        "rejected assembly must not create WAL/SHM sidecars on bars"
    )


def test_garbage_bars_db_rejected_typed(tmp_path):
    """垃圾字节 bars 库类型化拒绝 (R37)。"""
    from src.screening.offensive.v3.orchestration.official_trial_stack import (
        OfficialStackError,
    )

    world = _receipted_world(tmp_path)
    bars_db = world.root / "bars-evidence.sqlite3"
    bars_db.write_bytes(b"\x00garbage" * 11)
    _clear_sidecars(bars_db)

    with pytest.raises(OfficialStackError) as ei:
        _build(world)
    assert ei.value.code == "bars_store_not_seeded"


def test_zero_record_bars_db_accepted(tmp_path):
    """零记录 bars 库合法通过 (R37) — 首发 market session 前 0 bars 合法。

    bars 是运行时 append 面: 播种/发布管道落 schema 即启动完成, 记录
    随会话推进增长 (fixture 即此形态 — 本测试显式钉死该语义, 防未来
    把 bars 探测收紧成「非空记录」时无声破坏启动流程)。
    """
    world = _receipted_world(tmp_path)
    stack = _build(world)
    assert stack.runner is not None


def test_evidence_live_wal_sidecar_not_rejected(tmp_path):
    """evidence 库带活 -wal 不拒 (R37 sidecar 语义分流成文)。

    spine/governance 是 write-once 冻结事实文件 — sidecar 存在即拒
    (R35); evidence/bars 是运行时 append 面 — 活 publisher 的未
    checkpoint WAL 是合法形态 (publish→assemble 同进程流), 不做
    blanket sidecar 拒绝。冷主文件里的 regime 记录足以通过 immutable
    探测; 复活形态 (垃圾主文件) 由探测本身关闭, 与 sidecar 无关。
    """
    import sqlite3 as _sqlite3

    world = _receipted_world(tmp_path)
    evidence_db = world.root / "evidence.sqlite3"
    # 真 live writer: 打开连接落一笔不 checkpoint 的 WAL 写入后保持连接
    writer = _sqlite3.connect(str(evidence_db))
    try:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute(
            "INSERT OR IGNORE INTO evidence_head (issuer_namespace,"
            " last_commit_sequence, dependency_root)"
            " VALUES ('live-writer', 0, 'genesis')"
        )
        writer.commit()
        assert (world.root / "evidence.sqlite3-wal").exists()
        stack = _build(world)
        assert stack.runner is not None
    finally:
        writer.close()


def test_r37_probe_tables_track_schema_ddl():
    """R37 探测表 drift guard — evidence_records 必须仍是 repository DDL 声明的表。"""
    import re as _re

    from src.screening.offensive.v3.evidence import repository as _repo_mod
    from src.screening.offensive.v3.orchestration import (
        official_trial_stack as _stack_mod,
    )

    declared = set(
        _re.findall(
            r"CREATE TABLE IF NOT EXISTS\s+(\w+)",
            "\n".join(_repo_mod._SCHEMA_DDL),
        )
    )
    referenced = set(
        _re.findall(r"FROM\s+(\w+)", _stack_mod._EVIDENCE_REGIME_PROBE_SQL)
    )
    assert referenced <= declared


def test_garbage_decisions_db_rejected_typed_zero_write(tmp_path):
    """垃圾 decisions.sqlite3 类型化拒绝且零写痕 (R37 Act 期对抗发现)。

    decisions 是运行时自建产物: 缺失→首决策自建 (R32 成文)、0 字节→
    构造器自愈落 schema 是设计行为; 唯一拒绝形态 = 非 sqlite 垃圾 —
    修复前 TrialArmDecisionStore.__init__ 的 WAL/DDL 以非类型化
    sqlalchemy.exc.DatabaseError 泄漏 (evidence/bars 同族)。
    """
    from src.screening.offensive.v3.orchestration.official_trial_stack import (
        OfficialStackError,
    )

    world = _receipted_world(tmp_path)
    decisions_db = world.root / "decisions.sqlite3"
    decisions_db.write_bytes(b"\xde\xad" * 45)
    _clear_sidecars(decisions_db)
    before = _snapshot_fact_file(decisions_db)

    with pytest.raises(OfficialStackError) as ei:
        _build(world)
    assert ei.value.code == "decision_store_corrupt"
    after = _snapshot_fact_file(decisions_db)
    assert after[0] == before[0], "typed rejection must be zero-write"
    assert after[1] == before[1]


def test_zero_byte_decisions_db_still_self_builds(tmp_path):
    """0 字节 decisions.sqlite3 维持自建语义 (R37) — 与缺失同义, 不拒。

    钉死与 spine (0 字节=预注册事实缺失, 拒) 的语义分流: decisions 的
    schema 由构造器按需创建是运行时产物的设计行为, 探测只拒垃圾。
    """
    world = _receipted_world(tmp_path)
    decisions_db = world.root / "decisions.sqlite3"
    decisions_db.unlink(missing_ok=True)
    decisions_db.touch()

    stack = _build(world)
    assert stack.decision_store is not None
