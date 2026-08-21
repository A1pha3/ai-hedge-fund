"""ensure_directory_components 对抗回归网 (autodev 第五轮 Op1).

共享原语自 blob_store._ensure_directory 推广 (单一实现原则):
``mkdir(parents=True, exist_ok=True)`` 的穿透语义 — 静默跟随预置 symlink
在 root 之外创建目录 — 在 ensure 原语下不可能发生。本网钉死:

① 原语单元谱: happy/幂等/穿出零副作用/竞态收敛/canonical 前置;
② blob_store 委托等价 (错误码保持 blob 族);
③ stage_archive 写面: 先 mkdir 后 walk 的『穿出创建后拒绝』窗口关闭
   — 既有 PoC-4 只断言零 ``*.json``, 漏掉 mkdir 已经在 victim 里创建的
   目录树; 这里收紧为零条目;
④ genesis seal 链 export_backup/_finalize_backup: sqlite 备份与
   staging.replace 不得经预置 symlink 落到 root 之外;
⑤ restore 恢复目的地 new_path 的守卫接线 (原语级, 同函数同语义)。

offline primitive: 纯路径守卫回归网, 不构成权限。
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.screening.offensive.v3.evidence.blob_store import BlobStoreError
from src.screening.offensive.v3.gateway.exits import ExitLane
from src.screening.offensive.v3.governance.stage_issuance import (
    StageIssuanceReceipt,
)
from src.screening.offensive.v3.orchestration.genesis import (
    TrialGenesisArchive,
    TrialGenesisError,
    _ExitLaneReader,
)
from src.screening.offensive.v3.orchestration.path_guards import (
    PathGuardError,
    ensure_directory_components,
)
from src.screening.offensive.v3.orchestration.stage_archive import (
    StageArchiveError,
    write_stage_issuance_receipt,
)


def _receipt(trial_id: str = "trial-x", stage_id: str = "stage-1"):
    """最小路径消费 receipt — write 面只读 trial_id/stage_id 到路径。"""
    return StageIssuanceReceipt.model_construct(trial_id=trial_id, stage_id=stage_id)


# ---------------------------------------------------------------- 原语单元谱


def test_ensure_creates_nested_missing_directories(tmp_path: Path):
    target = tmp_path / "a" / "b" / "c"
    ensure_directory_components(target)
    assert target.is_dir()
    # 幂等: 已存在路径重放无副作用
    ensure_directory_components(target)


def test_ensure_symlinked_intermediate_rejects_with_zero_side_effect(
    tmp_path: Path,
):
    """穿出零副作用 — mkdir(parents=True) 违反的不变式。

    预置 ``root/a`` 为指向 victim 的 symlink: 旧语义下
    ``mkdir(parents=True)`` 会在 victim 内创建 ``b/c`` 目录树后才可能被
    后置 walk 拒绝; ensure 原语在创建发生前即拒绝, victim 必须保持空。
    """
    root = tmp_path / "root"
    root.mkdir()
    victim = tmp_path / "victim"
    victim.mkdir()
    (root / "a").symlink_to(victim, target_is_directory=True)
    with pytest.raises(PathGuardError) as ei:
        ensure_directory_components(root / "a" / "b" / "c")
    assert ei.value.code == "path_component_rejected"
    assert list(victim.rglob("*")) == [], "穿出创建必须零副作用"


def test_ensure_symlinked_final_component_rejects(tmp_path: Path):
    victim = tmp_path / "victim-real"
    victim.mkdir()
    target = tmp_path / "link-target"
    target.symlink_to(victim, target_is_directory=True)
    with pytest.raises(PathGuardError) as ei:
        ensure_directory_components(target)
    assert ei.value.code == "path_component_rejected"


def test_ensure_regular_file_as_intermediate_rejects(tmp_path: Path):
    blocker = tmp_path / "blocker"
    blocker.write_text("not a dir", encoding="utf-8")
    with pytest.raises(PathGuardError) as ei:
        ensure_directory_components(blocker / "below")
    assert ei.value.code == "path_component_rejected"
    assert blocker.read_text(encoding="utf-8") == "not a dir"


@pytest.mark.parametrize(
    ("bad", "code"),
    [
        (Path("relative/child"), "path_not_canonical"),
        (Path("/abs/../escape"), "path_traversal"),
    ],
)
def test_ensure_canonical_preconditions(bad: Path, code: str):
    with pytest.raises(PathGuardError) as ei:
        ensure_directory_components(bad)
    assert ei.value.code == code


class _LyingPath(type(Path())):
    """首测报缺失、其后如实的竞态探针路径。

    上溯 lstat 对目标段报 FileNotFoundError (谎报缺失), 其后所有 lstat
    都如实 — 确定性地驱动 ``mkdir() → FileExistsError`` 分支: 并发同伴
    已创建真实目录时收敛放行; 预置 symlink 时仍然拒绝。
    """

    lie_remaining: int
    _lied_name: str = ""

    def lstat(self):  # noqa: D102 - 测试探针
        if self.lie_remaining > 0 and self.name == self._lied_name:
            type(self).lie_remaining -= 1
            raise FileNotFoundError(self)
        return super().lstat()


def _racing_probe(real_dir: Path, *, preset_symlink: bool) -> Path:
    probe = _LyingPath(real_dir)
    probe._lied_name = real_dir.name
    type(probe).lie_remaining = 1
    if preset_symlink:
        victim = real_dir.parent / "victim-real"
        victim.mkdir()
        real_dir.rmdir()
        real_dir.symlink_to(victim, target_is_directory=True)
    return probe


def test_ensure_race_converges_on_peer_created_real_directory(tmp_path: Path):
    """上溯后同伴已创建真实目录: FileExistsError 分支收敛放行。"""
    target = tmp_path / "a" / "b"
    target.mkdir(parents=True)
    probe = _racing_probe(target, preset_symlink=False)
    ensure_directory_components(probe)
    assert target.is_dir()


def test_ensure_race_branch_rejects_preset_symlink(tmp_path: Path):
    """上溯后组件是预置 symlink: FileExistsError 分支仍然拒绝。"""
    target = tmp_path / "a" / "b"
    target.mkdir(parents=True)
    probe = _racing_probe(target, preset_symlink=True)
    with pytest.raises(PathGuardError) as ei:
        ensure_directory_components(probe)
    assert ei.value.code == "path_component_rejected"


# ------------------------------------------------- blob_store 委托等价


def test_blob_ensure_delegation_keeps_error_family(tmp_path: Path):
    from src.screening.offensive.v3.evidence.blob_store import _ensure_directory

    victim = tmp_path / "victim"
    victim.mkdir()
    root = tmp_path / "blobs"
    root.mkdir()
    (root / "ab").symlink_to(victim, target_is_directory=True)
    with pytest.raises(BlobStoreError) as ei:
        _ensure_directory(root / "ab" / "cd" / "hash", code="blob_root_rejected")
    assert ei.value.code == "blob_root_rejected"
    assert list(victim.rglob("*")) == []

    fresh = tmp_path / "fresh" / "x" / "y"
    _ensure_directory(fresh)
    assert fresh.is_dir()


# ------------------------------------------------- stage_archive 写面


def test_stage_archive_write_closes_mkdir_first_window(tmp_path: Path):
    """既有 PoC-4 收紧: victim 内不仅零 json, 且零条目。

    旧实现 ``mkdir(parents=True)`` 先于 walk 执行 — ``root/archive``
    symlink 预置时 stage-issuance/<trial_id> 目录树已在 victim 创建,
    walk 事后才拒绝。ensure 原语下创建不可能穿出。
    """
    victim = tmp_path / "victim"
    victim.mkdir()
    root = tmp_path / "trialroot"
    root.mkdir()
    (root / "archive").symlink_to(victim, target_is_directory=True)
    with pytest.raises(StageArchiveError) as ei:
        write_stage_issuance_receipt(root, _receipt())
    assert ei.value.code == "archive_component_rejected"
    assert list(victim.rglob("*")) == [], "mkdir 先行穿出创建窗口必须关闭"


def test_stage_archive_write_deep_symlink_rejects(tmp_path: Path):
    """archive 真实、trial_id 段预置 symlink: 回执不得落入 victim。"""
    victim = tmp_path / "victim"
    victim.mkdir()
    root = tmp_path / "trialroot"
    (root / "archive" / "stage-issuance").mkdir(parents=True)
    (root / "archive" / "stage-issuance" / "trial-x").symlink_to(
        victim, target_is_directory=True
    )
    with pytest.raises(StageArchiveError) as ei:
        write_stage_issuance_receipt(root, _receipt())
    assert ei.value.code == "archive_component_rejected"
    assert list(victim.rglob("*")) == []


def test_stage_archive_write_happy_path_creates_components(tmp_path: Path):
    root = tmp_path / "trialroot"
    root.mkdir()
    target = write_stage_issuance_receipt(root, _receipt())
    assert target.is_file()
    assert target.parent == (
        root / "archive" / "stage-issuance" / "trial-x"
    )


# ------------------------------------------------- genesis seal 链


def _make_exit_reader(db: Path) -> _ExitLaneReader:
    lane = ExitLane(
        database_path=str(db),
        clock=lambda: datetime.now(timezone.utc),
    )
    return _ExitLaneReader(lane)


def test_genesis_export_backup_rejects_symlinked_parent(tmp_path: Path):
    """sqlite backup 不得经预置 symlink 落到 root 外 (旧语义直接写穿)。"""
    victim = tmp_path / "victim"
    victim.mkdir()
    reader = _make_exit_reader(tmp_path / "lane.sqlite3")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "trial-t").symlink_to(victim, target_is_directory=True)
    with pytest.raises(TrialGenesisError) as ei:
        reader.export_backup(outside / "trial-t" / ".staging-champion.sqlite3")
    assert ei.value.code == "archive_component_rejected"
    assert list(victim.rglob("*")) == []


def test_genesis_export_backup_rejects_symlinked_destination(tmp_path: Path):
    """对抗审查增量: destination 最终组件预置 symlink — sqlite 写穿。"""
    import stat as stat_module

    victim = tmp_path / "victim"
    victim.mkdir()
    reader = _make_exit_reader(tmp_path / "lane.sqlite3")
    parent = tmp_path / "trial-t"
    parent.mkdir()
    dest = parent / ".staging-champion.sqlite3"
    dest.symlink_to(victim / "stolen.sqlite3")
    with pytest.raises(TrialGenesisError) as ei:
        reader.export_backup(dest)
    assert ei.value.code == "archive_component_rejected"
    assert list(victim.rglob("*")) == [], "sqlite 不得写穿 symlink 最终组件"


def test_genesis_finalize_backup_rejects_absolute_root_injection(tmp_path: Path):
    """对抗审查增量: root 段绝对注入 — pathlib 整体替换 trial root。"""
    archive = TrialGenesisArchive(tmp_path / "trialroot")
    (tmp_path / "trialroot" / "trial-t").mkdir(parents=True)
    staging = tmp_path / "trialroot" / "trial-t" / ".staging-champion.sqlite3"
    staging.write_bytes(b"backup-bytes")
    outside = tmp_path / "outside-victim"
    outside.mkdir()
    with pytest.raises(TrialGenesisError) as ei:
        archive._finalize_backup("trial-t", "champion", str(outside))
    assert ei.value.code == "backup_root_rejected"
    assert list(outside.rglob("*")) == [], "绝对注入不得创建任何组件"


def test_genesis_export_backup_happy_path(tmp_path: Path):
    reader = _make_exit_reader(tmp_path / "lane.sqlite3")
    dest = tmp_path / "trial-t" / ".staging-champion.sqlite3"
    reader.export_backup(dest)
    assert dest.is_file()


def test_genesis_finalize_backup_rejects_symlinked_content_root(
    tmp_path: Path,
):
    """staging.replace 不得把封存备份移进预置 symlink 指向的 victim。"""
    victim = tmp_path / "victim"
    victim.mkdir()
    root = tmp_path / "trialroot"
    archive = TrialGenesisArchive(root)
    (root / "trial-t").mkdir(parents=True)
    staging = root / "trial-t" / ".staging-champion.sqlite3"
    staging.write_bytes(b"backup-bytes")
    content_root = hashlib.sha256(b"backup-bytes").hexdigest()
    (root / "trial-t" / content_root).symlink_to(victim, target_is_directory=True)
    with pytest.raises(TrialGenesisError) as ei:
        archive._finalize_backup("trial-t", "champion", content_root)
    assert ei.value.code == "archive_component_rejected"
    assert list(victim.rglob("*")) == []
    assert staging.read_bytes() == b"backup-bytes", "staging 不得被移走"


def test_genesis_finalize_backup_happy_path_moves_staging(tmp_path: Path):
    root = tmp_path / "trialroot"
    archive = TrialGenesisArchive(root)
    (root / "trial-t").mkdir(parents=True)
    staging = root / "trial-t" / ".staging-champion.sqlite3"
    staging.write_bytes(b"backup-bytes")
    content_root = hashlib.sha256(b"backup-bytes").hexdigest()
    final = archive._finalize_backup("trial-t", "champion", content_root)
    assert final.read_bytes() == b"backup-bytes"
    assert not staging.exists()


def test_restore_destination_guard_wiring(tmp_path: Path):
    """restore_genesis_arm 的 new_path 守卫接线 (原语级同语义)。

    恢复目的地是调用方供给路径: 预置 symlink 父段时 restore_destination_rejected,
    且穿出零副作用。完整 restore 集成链由 test_trial_genesis_archive 覆盖
    (happy path 经 ensure 无扰动)。
    """
    victim = tmp_path / "victim"
    victim.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "dest").symlink_to(victim, target_is_directory=True)
    with pytest.raises(PathGuardError) as ei:
        ensure_directory_components(
            outside / "dest",
            missing_code="restore_destination_missing",
            rejected_code="restore_destination_rejected",
        )
    assert ei.value.code == "restore_destination_rejected"
    assert list(victim.rglob("*")) == []
