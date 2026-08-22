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
        namespaces=("regime", "sse-sessions", "btst-bars", "btst"),
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
    # 官方布局占位: 证据库存在即可构造 (选择面测试不进证据链);
    # spine 预置真实 enrollment (R32: 组装面校验 enrolled_sessions 非空,
    # 空文件/异 program 都 spine_not_registered — fixture 模拟注册流程)。
    (root / "evidence.sqlite3").touch()
    (root / "bars-evidence.sqlite3").touch()
    (root / "spine.sqlite3").touch()
    from src.screening.offensive.v3.evidence.session_spine import (
        SessionEnrollment,
        SessionSpine,
    )

    SessionSpine(
        database_path=str(root / "spine.sqlite3"), clock=lambda: GOV_NOW
    ).enroll_expected_sessions(
        (
            SessionEnrollment("prog-1", date(2026, 8, 6), date(2026, 8, 6)),
            SessionEnrollment("prog-1", date(2026, 8, 13), date(2026, 8, 13)),
        )
    )
    return _ArchiveWorld(
        identity_dir=identity_dir,
        root=root,
        issuer=issuer,
        sizing_config=_config(),
        market_scenario=CURRENT_COST_SCENARIO,
        trial_attribution=FillAttribution(
            producer_namespace="btst", research_program_id="prog-1",
            economic_lineage_id="eline-1", stage_id="stage-1",
        ),
    )


def _issue_receipt(issuer: GovernanceStageIssuer, *, stage_id: str, issued_at: datetime):
    """签发一个真实治理链 receipt (stage_id/issued_at 及台账 id 相互独立)。"""
    seq = stage_id.rsplit("-", 1)[-1]
    return issuer.issue(
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
        research_program_id="prog-1",
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
    assert ei.value.code in ("path_traversal", "trial_root_not_initialized")


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

    with pytest.raises(OfficialStackError) as ei:
        _build(world)  # research_program_id="prog-1"
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
