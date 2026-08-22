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
from datetime import datetime, timedelta, timezone
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
    # 官方布局占位: 证据库存在即可构造 (选择面测试不进证据链)。
    (root / "evidence.sqlite3").touch()
    (root / "bars-evidence.sqlite3").touch()
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
