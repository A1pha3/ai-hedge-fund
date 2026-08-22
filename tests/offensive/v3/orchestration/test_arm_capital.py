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


# --- R21: 两臂台账运行态路径约定 --------------------------------------------


class TestArmLayout:
    def _trial_root(self, tmp_path: Path) -> Path:
        from src.screening.offensive.v3.capital.repository import CapitalRepository

        root = tmp_path / "trial-root"
        for arm in ("champion", "challenger"):
            db = root / "arms" / arm / "capital.sqlite3"  # 约定小写目录
            db.parent.mkdir(parents=True)
            CapitalRepository.initialize(db)
        return root

    def test_agreed_path_shape(self, tmp_path):
        from src.screening.offensive.v3.orchestration.arm_layout import (
            arm_capital_database_path,
        )

        p = arm_capital_database_path(tmp_path, TrialArm.CHALLENGER)
        assert p == tmp_path / "arms" / "challenger" / "capital.sqlite3"

    def test_open_missing_ledger_fails_closed(self, tmp_path):
        from src.screening.offensive.v3.orchestration.arm_layout import (
            ArmLayoutError,
            open_arm_capital_repository,
        )

        with pytest.raises(ArmLayoutError) as ei:
            open_arm_capital_repository(tmp_path, TrialArm.CHAMPION)
        assert ei.value.code == "arm_ledger_missing"

    def test_open_and_checkpoint_roundtrip(self, tmp_path):
        """组合面: 初始化两臂库 → arm_session_checkpoint 读出 (genesis 错配在
        arm_capital 层拒绝 — 本测只钉路径约定与 open 语义)。"""
        from src.screening.offensive.v3.orchestration.arm_layout import (
            ArmLayoutError,
            open_arm_capital_repository,
        )

        root = self._trial_root(tmp_path)
        repo = open_arm_capital_repository(root, TrialArm.CHAMPION)
        assert repo.database_path.name == "capital.sqlite3"
        # genesis manifest 不存在 → arm_capital 的读面拒绝 (组合面不静默)
        from src.screening.offensive.v3.orchestration.arm_layout import (
            arm_session_checkpoint,
        )

        with pytest.raises((ArmCapitalError, ArmLayoutError)):
            arm_session_checkpoint(
                root,
                trial_id="trial-x",
                arm=TrialArm.CHAMPION,
                portfolio_id="paper-v3",
                mode=ExecutionMode.DAILY_BAR_PROXY,
                as_of=datetime(2026, 8, 6, 15, 0, tzinfo=UTC),
                capital_store_id="trial-x:champion:capital",
            )

    def test_symlinked_arm_dir_rejected(self, tmp_path):
        from src.screening.offensive.v3.orchestration.arm_layout import (
            ArmLayoutError,
            open_arm_capital_repository,
        )

        root = self._trial_root(tmp_path)
        hostile = tmp_path / "elsewhere"
        hostile.mkdir()
        import shutil

        shutil.rmtree(root / "arms" / "champion")
        (root / "arms" / "champion").symlink_to(hostile)
        with pytest.raises(ArmLayoutError):
            open_arm_capital_repository(root, TrialArm.CHAMPION)


class TestGenesisManifestJsonRoundtripHash:
    """R23 执行发现的缺陷回归: seal→cold-read→content_hash 链。

    pydantic 解析 ISO UTC 产出 TzInfo(UTC) 非 timezone.utc 单例 —
    裸 ``datetime`` 注解使 ``_validate_utc`` 身份比较恒拒; 既有测试全部
    直接构造单例对象, 真实封存产物的冷读哈希从未通过。sealed_at 改
    UtcInstant (BeforeValidator normalize json 字符串→单例) 后收敛。
    """

    def _manifest(self):
        return TrialGenesisManifest(
            trial_id="trial-rr",
            normalized_genesis_hash="1" * 64,
            champion_normalized_hash="2" * 64,
            challenger_normalized_hash="3" * 64,
            champion_backup_root="a" * 64,
            challenger_backup_root="b" * 64,
            trial_manifest_hash="d" * 64,
            sap_manifest_hash="e" * 64,
            sealed_at=datetime(2026, 8, 22, 8, 52, 23, tzinfo=UTC),
            schema_major=2,
        )

    def test_json_roundtrip_hash_identical(self, tmp_path):
        import json as _json

        manifest = self._manifest()
        expect = manifest.content_hash()
        # 冷读路径: 落盘 JSON (Z 后缀) → read_genesis_manifest → hash
        root = tmp_path / "trial-rr"
        root.mkdir()
        (root / "genesis-manifest.json").write_text(
            manifest.model_dump_json(), encoding="utf-8"
        )
        back = read_genesis_manifest(tmp_path, "trial-rr")
        assert back.sealed_at.tzinfo is UTC  # 单例 (非 pydantic TzInfo)
        assert back.content_hash() == expect  # 冷读哈希与封存时逐字节一致

    def test_tzinfo_singleton_after_json_parse(self):
        from src.screening.offensive.v3.orchestration.genesis import (
            TrialGenesisManifest as M,
        )

        parsed = M.model_validate_json(self._manifest().model_dump_json())
        assert parsed.sealed_at.tzinfo is UTC
