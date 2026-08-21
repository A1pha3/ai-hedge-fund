"""capital/scheduler 存储面路径守卫对抗回归网 (autodev 第五轮 Op3).

CapitalRepository.initialize / backup_consistent / restore_backup 与
LifecycleScheduler.write_process_lease 接入共享 ensure_directory_components
(Op1 单一实现) + 最终组件 lstat 拒 symlink — 预置 symlink 下资本真相库/
备份/恢复目标/进程 lease 不得在 root 外创建或读写 (穿出零副作用)。
open() (打开既有库) 不设 symlink 拒绝 — 合法部署手法, 见 AGENTS.md。
offline primitive: 不构成权限。
"""

from __future__ import annotations

import hashlib
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.screening.offensive.v3.capital.repository import (
    BackupManifest,
    CapitalConflict,
    CapitalRepository,
)
from src.screening.offensive.v3.gateway.exits import ExitLane
from src.screening.offensive.v3.services.identity import ServiceIdentity
from src.screening.offensive.v3.services.lifecycle_scheduler import (
    LifecycleScheduler,
    LifecycleSchedulerError,
)


# ---------------------------------------------------------------- initialize


def test_initialize_rejects_symlinked_parent_zero_side_effect(tmp_path: Path):
    victim = tmp_path / "victim"
    victim.mkdir()
    root = tmp_path / "caproot"
    root.mkdir()
    (root / "acct").symlink_to(victim, target_is_directory=True)
    with pytest.raises(CapitalConflict) as ei:
        CapitalRepository.initialize(root / "acct" / "capital.sqlite3")
    assert ei.value.code == "capital_component_rejected"
    assert list(victim.rglob("*")) == [], "穿出创建必须零副作用"


def test_initialize_rejects_symlinked_db_file(tmp_path: Path):
    victim = tmp_path / "victim"
    victim.mkdir()
    db = tmp_path / "capital.sqlite3"
    db.symlink_to(victim / "stolen.sqlite3")
    with pytest.raises(CapitalConflict) as ei:
        CapitalRepository.initialize(db)
    assert ei.value.code == "capital_path_rejected"
    assert list(victim.rglob("*")) == []


def test_initialize_rejects_relative_path(tmp_path: Path):
    with pytest.raises(CapitalConflict):
        CapitalRepository.initialize(Path("relative/capital.sqlite3"))


def test_initialize_creates_nested_dirs_idempotently(tmp_path: Path):
    path = tmp_path / "nest" / "acct" / "capital.sqlite3"
    repo = CapitalRepository.initialize(path)
    assert path.is_file()
    again = CapitalRepository.initialize(path)
    assert again.database_path == repo.database_path


# ---------------------------------------------------------------- backup_consistent


def test_backup_consistent_rejects_symlinked_destination(tmp_path: Path):
    """备份目的地预置 symlink — sqlite backup 不得写穿 (守卫先于账户绑定检查)。"""
    repo = CapitalRepository.initialize(tmp_path / "capital.sqlite3")
    victim = tmp_path / "victim"
    victim.mkdir()
    outside = tmp_path / "backups"
    outside.mkdir()
    (outside / "acct").symlink_to(victim, target_is_directory=True)
    with pytest.raises(CapitalConflict) as ei:
        repo.backup_consistent(outside / "acct" / "backup.sqlite3")
    assert ei.value.code == "backup_component_rejected"
    assert list(victim.rglob("*")) == []


def test_backup_consistent_rejects_symlinked_backup_file(tmp_path: Path):
    repo = CapitalRepository.initialize(tmp_path / "capital.sqlite3")
    victim = tmp_path / "victim"
    victim.mkdir()
    dest = tmp_path / "backup.sqlite3"
    dest.symlink_to(victim / "stolen.sqlite3")
    with pytest.raises(CapitalConflict) as ei:
        repo.backup_consistent(dest)
    assert ei.value.code == "backup_path_rejected"
    assert list(victim.rglob("*")) == []


# ---------------------------------------------------------------- restore_backup


def _manifest_for(data: bytes) -> BackupManifest:
    return BackupManifest.model_construct(
        binding_content_hash="sha256:" + "0" * 64,
        schema_major=1,
        ledger_schema_version=1,
        stream_version=1,
        capital_version=1,
        risk_epoch=1,
        stage_loss_state_version=1,
        durable_inbox_cursor=None,
        durable_outbox_cursor=None,
        content_root=hashlib.sha256(data).hexdigest(),
        created_at=datetime.now(timezone.utc),
    )


def test_restore_backup_rejects_symlinked_destination(tmp_path: Path):
    backup_bytes = b"backup-bytes"
    backup = tmp_path / "backup.sqlite3"
    backup.write_bytes(backup_bytes)
    victim = tmp_path / "victim"
    victim.mkdir()
    outside = tmp_path / "restore"
    outside.mkdir()
    (outside / "acct").symlink_to(victim, target_is_directory=True)
    with pytest.raises(CapitalConflict) as ei:
        CapitalRepository.restore_backup(
            _manifest_for(backup_bytes), backup, outside / "acct" / "new.sqlite3"
        )
    assert ei.value.code == "restore_component_rejected"
    assert list(victim.rglob("*")) == []


def test_restore_backup_rejects_symlinked_target_file(tmp_path: Path):
    backup_bytes = b"backup-bytes"
    backup = tmp_path / "backup.sqlite3"
    backup.write_bytes(backup_bytes)
    victim = tmp_path / "victim"
    victim.mkdir()
    target = tmp_path / "new.sqlite3"
    target.symlink_to(victim / "stolen.sqlite3")
    with pytest.raises(CapitalConflict) as ei:
        CapitalRepository.restore_backup(_manifest_for(backup_bytes), backup, target)
    assert ei.value.code == "restore_path_rejected"
    assert list(victim.rglob("*")) == []


# ---------------------------------------------------------------- scheduler lease


def _scheduler(tmp_path: Path) -> LifecycleScheduler:
    identity = ServiceIdentity(
        service_name="lifecycle-scheduler",
        capability_namespace="lifecycle.durable.v2",
        owner_uid=os.getuid(),
        owner_gid=os.getgid(),
        socket_path=tmp_path / "lifecycle-scheduler.sock",
        db_dsn=f"sqlite:///{tmp_path}/lifecycle.sqlite",
    )
    return LifecycleScheduler(
        identity=identity,
        exit_lane=ExitLane(
            database_path=str(tmp_path / "lifecycle.sqlite3"),
            clock=lambda: datetime.now(timezone.utc),
        ),
        exit_rate_budget=100,
        reconcile_rate_budget=100,
    )


def test_write_process_lease_rejects_symlinked_parent(tmp_path: Path):
    scheduler = _scheduler(tmp_path)
    victim = tmp_path / "victim"
    victim.mkdir()
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "svc").symlink_to(victim, target_is_directory=True)
    with pytest.raises(LifecycleSchedulerError) as ei:
        scheduler.write_process_lease(run_dir / "svc" / "lease.json")
    assert ei.value.code == "lease_component_rejected"
    assert list(victim.rglob("*")) == []


def test_write_process_lease_rejects_symlinked_file(tmp_path: Path):
    scheduler = _scheduler(tmp_path)
    victim = tmp_path / "victim"
    victim.mkdir()
    lease = tmp_path / "lease.json"
    lease.symlink_to(victim / "stolen.json")
    with pytest.raises(LifecycleSchedulerError) as ei:
        scheduler.write_process_lease(lease)
    assert ei.value.code == "lease_path_rejected"
    assert list(victim.rglob("*")) == []


def test_write_process_lease_happy_path_nested(tmp_path: Path):
    scheduler = _scheduler(tmp_path)
    lease = tmp_path / "run" / "svc" / "lease.json"
    scheduler.write_process_lease(lease)
    assert lease.is_file()
