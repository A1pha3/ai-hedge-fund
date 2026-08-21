"""arm_capital — 两臂 PIT capital checkpoint 读取原语 (2026-08-21).

锁定: genesis manifest 冷读 (严格解析/损坏/symlink/穿越/错配全类型化)、
checkpoint 绑定 (PIT snapshot 哈希、arm backup root 按臂、manifest hash、
portfolio/mode 一致性 — 校验器背书)、台账→checkpoint→kernel input 的
真实链 (两臂从各自分化台账独立取快照)。
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.screening.offensive.v3.capital.flows import GenesisRequest
from src.screening.offensive.v3.capital.identity import AccountBinding
from src.screening.offensive.v3.capital.repository import CapitalRepository
from src.screening.offensive.v3.contracts import ExecutionMode
from src.screening.offensive.v3.contracts.trial import TrialArm
from src.screening.offensive.v3.orchestration.arm_capital import (
    ArmCapitalError,
    arm_capital_checkpoint,
    genesis_manifest_path,
    read_genesis_manifest,
)
from src.screening.offensive.v3.orchestration.genesis import TrialGenesisManifest

UTC = timezone.utc
TRIAL_ID = "trial-regime-001"
AS_OF = datetime(2026, 8, 6, 15, 0, tzinfo=UTC)


def _genesis_manifest(**overrides) -> TrialGenesisManifest:
    values = dict(
        trial_id=TRIAL_ID,
        normalized_genesis_hash="a" * 64,
        champion_normalized_hash="b" * 64,
        challenger_normalized_hash="c" * 64,
        champion_backup_root="d" * 64,
        challenger_backup_root="e" * 64,
        trial_manifest_hash="f" * 64,
        sap_manifest_hash="g" * 64,
        sealed_at=AS_OF,
        schema_major=2,
    )
    values.update(overrides)
    return TrialGenesisManifest(**values)


def _repo(tmp_path: Path, name: str) -> CapitalRepository:
    repository = CapitalRepository.initialize(tmp_path / f"{name}.sqlite3")
    repository.initialize_genesis(
        GenesisRequest(
            idempotency_key=f"genesis-{name}",
            account_binding=AccountBinding(
                portfolio_id="trial-portfolio",
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
            effective_at=AS_OF,
            as_of=AS_OF,
        )
    )
    return repository


def test_genesis_manifest_round_trip_and_guards(tmp_path):
    root = tmp_path / "trial-root"
    root.mkdir()
    manifest = _genesis_manifest()
    target = genesis_manifest_path(root, TRIAL_ID)
    target.parent.mkdir(parents=True)
    target.write_text(manifest.model_dump_json(), encoding="utf-8")

    assert read_genesis_manifest(root, TRIAL_ID) == manifest

    # 损坏 → 类型化
    target.write_text("{corrupt", encoding="utf-8")
    with pytest.raises(ArmCapitalError) as ei:
        read_genesis_manifest(root, TRIAL_ID)
    assert ei.value.code == "genesis_manifest_corrupt"

    # symlink → 拒绝
    target.unlink()
    victim = tmp_path / "victim.json"
    victim.write_text(manifest.model_dump_json(), encoding="utf-8")
    target.symlink_to(victim)
    with pytest.raises(ArmCapitalError) as ei:
        read_genesis_manifest(root, TRIAL_ID)
    assert ei.value.code == "genesis_manifest_rejected"

    # 缺失
    target.unlink()
    with pytest.raises(ArmCapitalError) as ei:
        read_genesis_manifest(root, TRIAL_ID)
    assert ei.value.code == "genesis_manifest_missing"

    # 错配 trial
    target.write_text(
        _genesis_manifest(trial_id="trial-other").model_dump_json(), encoding="utf-8"
    )
    with pytest.raises(ArmCapitalError) as ei:
        read_genesis_manifest(root, TRIAL_ID)
    assert ei.value.code == "genesis_trial_mismatch"

    # 根穿越
    with pytest.raises(ArmCapitalError) as ei:
        read_genesis_manifest(root / ".." / "elsewhere", TRIAL_ID)
    assert ei.value.code == "root_path_traversal"


def test_arm_capital_checkpoint_binds_snapshot_and_genesis_per_arm(tmp_path):
    manifest = _genesis_manifest()
    champion = arm_capital_checkpoint(
        repository=_repo(tmp_path, "champion"),
        trial_id=TRIAL_ID,
        arm=TrialArm.CHAMPION,
        portfolio_id="trial-portfolio",
        mode=ExecutionMode.DAILY_BAR_PROXY,
        as_of=AS_OF,
        capital_store_id=f"{TRIAL_ID}:CHAMPION:capital",
        genesis_manifest=manifest,
    )
    challenger = arm_capital_checkpoint(
        repository=_repo(tmp_path, "challenger"),
        trial_id=TRIAL_ID,
        arm=TrialArm.CHALLENGER,
        portfolio_id="trial-portfolio",
        mode=ExecutionMode.DAILY_BAR_PROXY,
        as_of=AS_OF,
        capital_store_id=f"{TRIAL_ID}:CHALLENGER:capital",
        genesis_manifest=manifest,
    )
    # snapshot 哈希绑定 + genesis 绑定字段 (manifest hash / 按臂 backup root)
    assert champion.capital_snapshot.content_hash() == champion.capital_snapshot_hash
    assert challenger.capital_snapshot.content_hash() == challenger.capital_snapshot_hash
    assert champion.trial_genesis_manifest_hash == manifest.content_hash()
    assert champion.arm_capital_genesis_root == manifest.champion_backup_root
    assert challenger.arm_capital_genesis_root == manifest.challenger_backup_root
    # 两臂从各自台账独立取快照 (同一 genesis 经济状态 → 相同 economics)
    assert (
        champion.capital_snapshot.as_observed_nav_cents
        == challenger.capital_snapshot.as_observed_nav_cents
    )
    # P2-1 (第四轮审查): 跨 trial manifest 在 checkpoint 构造即拒 —
    # 不等下游 build_pair_records 兜底
    with pytest.raises(ArmCapitalError) as ei:
        arm_capital_checkpoint(
            repository=_repo(tmp_path, "xtrial"),
            trial_id=TRIAL_ID,
            arm=TrialArm.CHAMPION,
            portfolio_id="trial-portfolio",
            mode=ExecutionMode.DAILY_BAR_PROXY,
            as_of=AS_OF,
            capital_store_id="x",
            genesis_manifest=_genesis_manifest(trial_id="trial-other"),
        )
    assert ei.value.code == "genesis_trial_mismatch"

    # checkpoint 校验器背书: portfolio/mode 一致性, 漂移即构造失败
    with pytest.raises(Exception):
        arm_capital_checkpoint(
            repository=_repo(tmp_path, "mismatch"),
            trial_id=TRIAL_ID,
            arm=TrialArm.CHAMPION,
            portfolio_id="other-portfolio",  # 与台账 genesis 绑定错配
            mode=ExecutionMode.DAILY_BAR_PROXY,
            as_of=AS_OF,
            capital_store_id="x",
            genesis_manifest=manifest,
        )


def test_checkpoint_flows_into_kernel_input_via_builder(tmp_path):
    """台账 → checkpoint → build_arm_kernel_inputs 消费 (真实链, 非 fixture)。"""
    import sys

    from src.screening.offensive.v3.contracts.regime import (
        RegimeAdmissionMode,
        RegimeState,
    )
    from src.screening.offensive.v3.governance.regime_trial import (
        ValidatedRegimeTrialBundle,
    )
    from src.screening.offensive.v3.orchestration.paired_trial import (
        build_arm_kernel_inputs,
    )

    _kernel_dir = Path(__file__).resolve().parents[1] / "kernel"
    if str(_kernel_dir) not in sys.path:
        sys.path.insert(0, str(_kernel_dir))
    from test_shadow_kernel import (  # noqa: E402 - crib
        _config,
        _deadlines,
        _regime_observation,
        _sap,
        _shared,
        _trial_manifest,
        _trial_policy,
    )

    manifest = _genesis_manifest()
    champion = arm_capital_checkpoint(
        repository=_repo(tmp_path, "champion"),
        trial_id=TRIAL_ID,
        arm=TrialArm.CHAMPION,
        portfolio_id="trial-portfolio",
        mode=ExecutionMode.DAILY_BAR_PROXY,
        as_of=AS_OF,
        capital_store_id=f"{TRIAL_ID}:CHAMPION:capital",
        genesis_manifest=manifest,
    )
    challenger = arm_capital_checkpoint(
        repository=_repo(tmp_path, "challenger"),
        trial_id=TRIAL_ID,
        arm=TrialArm.CHALLENGER,
        portfolio_id="trial-portfolio",
        mode=ExecutionMode.DAILY_BAR_PROXY,
        as_of=AS_OF,
        capital_store_id=f"{TRIAL_ID}:CHALLENGER:capital",
        genesis_manifest=manifest,
    )
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
    sizing = _config()
    champion_input, challenger_input = build_arm_kernel_inputs(
        validated=validated,
        shared_input=shared,
        candidates=(),
        champion_capital_checkpoint=champion,
        challenger_capital_checkpoint=challenger,
        deadlines=_deadlines(),
        sizing_config=sizing,
    )
    # 真实台账快照流进双臂 kernel input (checkpoint 原样保留)
    assert champion_input.capital_checkpoint == champion
    assert challenger_input.capital_checkpoint == challenger
    assert (
        champion_input.capital_checkpoint.content_hash()
        != challenger_input.capital_checkpoint.content_hash()
    )
