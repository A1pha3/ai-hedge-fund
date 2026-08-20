"""path_guards — archive 动态路径段守卫的对抗性回归网 (2026-08-21).

autodev 第四轮对抗性审查发现家族性缺陷: ``_validate_root`` 只 walk trial
root 自身组件, root 之下的动态段 (trial_id/stage_id/archive 常量段) 从不被
lstat。本文件把 4 个已实锤的穿透 PoC 钉死为类型化拒绝:

① ``root/<trial_id>`` 目录组件 symlink → ``read_genesis_manifest`` 穿透
   读取 (跨 trial 混淆 — checkpoint 会绑定错误 genesis 事实);
② trial_id 含 ``..`` → 穿越读取 root 外 manifest (manifest.trial_id 与
   请求串一致时业务校验拦不住);
③ trial_id 绝对路径 → ``pathlib root / '/abs'`` 整体替换 root;
④ ``root/archive`` symlink 预置 → ``write_stage_issuance_receipt`` 回执
   写穿到 symlink 指向的任意目录。

另覆盖: 段形状边界、walk 组件边界、genesis seal 入口形状校验与
restore_genesis_arm 路径纵深 (内容哈希绑定的是字节, 不是路径)。
正向往返由 test_arm_capital / test_privileged_worker /
test_trial_genesis_archive 的既有用例承载。
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.screening.offensive.v3.governance.stage_issuance import (
    StageIssuanceReceipt,
)
from src.screening.offensive.v3.orchestration.arm_capital import (
    ArmCapitalError,
    read_genesis_manifest,
)
from src.screening.offensive.v3.orchestration.genesis import (
    TrialGenesisArchive,
    TrialGenesisError,
    TrialGenesisManifest,
    restore_genesis_arm,
)
from src.screening.offensive.v3.orchestration.path_guards import (
    PathGuardError,
    require_safe_segment,
    walk_components,
)
from src.screening.offensive.v3.orchestration.stage_archive import (
    StageArchiveError,
    stage_receipt_path,
    write_stage_issuance_receipt,
)

UTC = timezone.utc
TRIAL_ID = "trial-regime-001"


def _manifest(trial_id: str = TRIAL_ID, **overrides) -> TrialGenesisManifest:
    values = dict(
        trial_id=trial_id,
        normalized_genesis_hash="a" * 64,
        champion_normalized_hash="b" * 64,
        challenger_normalized_hash="c" * 64,
        champion_backup_root="d" * 64,
        challenger_backup_root="e" * 64,
        trial_manifest_hash="f" * 64,
        sap_manifest_hash="g" * 64,
        sealed_at=datetime(2026, 8, 6, 15, 0, tzinfo=UTC),
        schema_major=2,
    )
    values.update(overrides)
    return TrialGenesisManifest(**values)


def _receipt(trial_id: str = "trial-x", stage_id: str = "stage-1"):
    """最小路径消费 receipt — stage_receipt_path 只读 trial_id/stage_id。"""
    return StageIssuanceReceipt.model_construct(trial_id=trial_id, stage_id=stage_id)


# ---------------------------------------------------------------- 段形状


@pytest.mark.parametrize(
    "bad",
    ["", ".", "..", "a/b", "/absolute/path", "../x", ".hidden", "a\\b", "a:b"],
)
def test_segment_rejects_unsafe_names(bad):
    with pytest.raises(PathGuardError) as ei:
        require_safe_segment(bad, field="trial_id")
    assert ei.value.code == "trial_id_rejected"


@pytest.mark.parametrize("good", ["t", "trial-x", "Stage_1.2026", "0", "a" * 128])
def test_segment_accepts_safe_names(good):
    assert require_safe_segment(good, field="trial_id") == good


def test_segment_rejects_non_string():
    with pytest.raises(PathGuardError):
        require_safe_segment(None, field="trial_id")  # type: ignore[arg-type]


# ---------------------------------------------------------------- walk


def test_walk_accepts_real_directory_chain(tmp_path: Path):
    deep = tmp_path / "a" / "b" / "c"
    deep.mkdir(parents=True)
    walk_components(deep)  # 不抛即通过


def test_walk_rejects_relative_path(tmp_path: Path):
    with pytest.raises(PathGuardError) as ei:
        walk_components(Path("relative/dir"))
    assert ei.value.code == "path_not_canonical"


def test_walk_rejects_dotdot(tmp_path: Path):
    with pytest.raises(PathGuardError) as ei:
        walk_components(tmp_path / ".." / "elsewhere")
    assert ei.value.code == "path_traversal"


def test_walk_rejects_missing_component(tmp_path: Path):
    with pytest.raises(PathGuardError) as ei:
        walk_components(tmp_path / "absent" / "leaf")
    assert ei.value.code == "path_component_missing"


def test_walk_rejects_file_as_intermediate_component(tmp_path: Path):
    blocker = tmp_path / "blocker"
    blocker.write_text("file, not a directory", encoding="utf-8")
    with pytest.raises(PathGuardError) as ei:
        walk_components(blocker / "leaf")
    assert ei.value.code == "path_component_rejected"


def test_walk_rejects_symlinked_component(tmp_path: Path):
    real = tmp_path / "real"
    real.mkdir()
    (tmp_path / "alias").symlink_to(real, target_is_directory=True)
    with pytest.raises(PathGuardError) as ei:
        walk_components(tmp_path / "alias" / "leaf")
    assert ei.value.code == "path_component_rejected"


# ---------------------------------------------------------------- PoC ①
# root/<trial_id> 目录组件是 symlink → 穿透读取另一目录的 manifest。


def test_poc1_symlinked_trial_directory_is_rejected(tmp_path: Path):
    victim = tmp_path / "victim"
    victim.mkdir()
    (victim / "genesis-manifest.json").write_text(
        _manifest("trial-x").model_dump_json(), encoding="utf-8"
    )
    root = tmp_path / "trialroot"
    root.mkdir()
    (root / "trial-x").symlink_to(victim, target_is_directory=True)
    with pytest.raises(ArmCapitalError) as ei:
        read_genesis_manifest(root, "trial-x")
    assert ei.value.code == "trial_directory_rejected"


# ---------------------------------------------------------------- PoC ②
# trial_id 含 '..' → 穿越读取 root 外; manifest.trial_id 与请求串一致时
# 业务校验 (genesis_trial_mismatch) 拦不住。


def test_poc2_traversal_trial_id_is_rejected_by_shape(tmp_path: Path):
    inner = tmp_path / "real"
    inner.mkdir()
    (inner / "genesis-manifest.json").write_text(
        _manifest("../trialroot/real").model_dump_json(), encoding="utf-8"
    )
    root = tmp_path / "trialroot"
    root.mkdir()
    with pytest.raises(ArmCapitalError) as ei:
        read_genesis_manifest(root, "../trialroot/real")
    assert ei.value.code == "trial_id_rejected"


# ---------------------------------------------------------------- PoC ③
# trial_id 绝对路径 → pathlib ``root / '/abs'`` 整体替换 root。


def test_poc3_absolute_trial_id_is_rejected_by_shape(tmp_path: Path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "genesis-manifest.json").write_text(
        _manifest(str(outside)).model_dump_json(), encoding="utf-8"
    )
    root = tmp_path / "trialroot"
    root.mkdir()
    with pytest.raises(ArmCapitalError) as ei:
        read_genesis_manifest(root, str(outside))
    assert ei.value.code == "trial_id_rejected"


# ---------------------------------------------------------------- PoC ④
# root/archive symlink 预置 → 回执写穿到 symlink 指向目录。


def test_poc4_symlinked_archive_write_through_is_rejected(tmp_path: Path):
    victim = tmp_path / "victim"
    victim.mkdir()
    root = tmp_path / "trialroot"
    root.mkdir()
    (root / "archive").symlink_to(victim, target_is_directory=True)
    with pytest.raises(StageArchiveError) as ei:
        write_stage_issuance_receipt(root, _receipt())
    assert ei.value.code == "archive_component_rejected"
    assert not list(victim.rglob("*.json")), "任何字节都不得落入 victim"


# ---------------------------------------------------------------- 其余接线面


def test_stage_receipt_path_rejects_unsafe_ids(tmp_path: Path):
    with pytest.raises(StageArchiveError) as ei:
        stage_receipt_path(tmp_path, _receipt(trial_id="../evil"))
    assert ei.value.code == "trial_id_rejected"
    with pytest.raises(StageArchiveError) as ei:
        stage_receipt_path(tmp_path, _receipt(stage_id="a/b"))
    assert ei.value.code == "stage_id_rejected"


def test_read_stage_receipt_rejects_symlinked_parent(tmp_path: Path):
    from src.screening.offensive.v3.orchestration.stage_archive import (
        read_stage_issuance_receipt,
    )

    victim = tmp_path / "victim"
    victim.mkdir()
    (victim / "stage-1.json").write_text("{}", encoding="utf-8")
    (tmp_path / "alias").symlink_to(victim, target_is_directory=True)
    with pytest.raises(StageArchiveError) as ei:
        read_stage_issuance_receipt(tmp_path / "alias" / "stage-1.json")
    assert ei.value.code == "archive_component_rejected"


def test_genesis_seal_rejects_unsafe_trial_id(tmp_path: Path):
    archive = TrialGenesisArchive(tmp_path)
    with pytest.raises(TrialGenesisError) as ei:
        archive.seal("../evil", None, None)  # type: ignore[arg-type]
    assert ei.value.code == "trial_id_rejected"


def test_restore_genesis_arm_rejects_symlinked_backup_path(tmp_path: Path):
    """restore 面路径纵深: 内容哈希绑定字节, 绑定不了路径 — symlink 让
    ``read_bytes`` 发生在 root 之外, 必须在哈希校验前被路径守卫拒绝。"""
    payload = b"attacker-controlled bytes"
    root_hash = hashlib.sha256(payload).hexdigest()
    victim = tmp_path / "victim"
    victim.mkdir()
    (victim / "capital.sqlite3").write_bytes(payload)
    root = tmp_path / "trialroot"
    root.mkdir()
    (root / TRIAL_ID).symlink_to(victim, target_is_directory=True)
    manifest = _manifest(champion_backup_root=root_hash)
    with pytest.raises(TrialGenesisError) as ei:
        restore_genesis_arm(
            manifest, root, tmp_path / "restored.sqlite3", arm="CHAMPION"
        )
    assert ei.value.code == "archive_component_rejected"
