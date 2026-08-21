"""migration 状态库路径守卫对抗回归网 (autodev 第五轮 Op2).

DurableCapitalInbox / AuthorityRegistry / MigrationCoordinator 三个持久化
构造面接入共享 ensure_directory_components (Op1 单一实现) + db 最终组件
lstat 拒 symlink — 预置 symlink 中间段/最终组件下, 状态库不得在 root 外
创建或读写 (穿出零副作用)。offline primitive: 不构成权限。
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.screening.offensive.v3.migration.authority import AuthorityError, AuthorityRegistry
from src.screening.offensive.v3.migration.coordinator import MigrationCoordinator, MigrationError
from src.screening.offensive.v3.migration.inbox import DurableCapitalInbox, InboxError


def _clock():
    now = {"t": datetime(2026, 8, 21, tzinfo=timezone.utc)}

    def tick() -> datetime:
        now["t"] = now["t"].replace(second=now["t"].second + 1)
        return now["t"]

    return tick


# ---------------------------------------------------------------- 中间段 symlink


def test_inbox_rejects_symlinked_parent_with_zero_side_effect(tmp_path: Path):
    victim = tmp_path / "victim"
    victim.mkdir()
    state_root = tmp_path / "state"
    state_root.mkdir()
    (state_root / "mig").symlink_to(victim, target_is_directory=True)
    with pytest.raises(InboxError) as ei:
        DurableCapitalInbox(state_root / "mig" / "inbox.sqlite3", clock=_clock())
    assert ei.value.code == "inbox_component_rejected"
    assert list(victim.rglob("*")) == [], "穿出创建必须零副作用"


def test_authority_rejects_symlinked_parent_with_zero_side_effect(tmp_path: Path):
    victim = tmp_path / "victim"
    victim.mkdir()
    state_root = tmp_path / "state"
    state_root.mkdir()
    (state_root / "mig").symlink_to(victim, target_is_directory=True)
    with pytest.raises(AuthorityError) as ei:
        AuthorityRegistry(state_root / "mig" / "authority.sqlite3", clock=_clock())
    assert ei.value.code == "authority_component_rejected"
    assert list(victim.rglob("*")) == []


def test_coordinator_rejects_symlinked_parent_with_zero_side_effect(tmp_path: Path):
    victim = tmp_path / "victim"
    victim.mkdir()
    state_root = tmp_path / "state"
    state_root.mkdir()
    (state_root / "mig").symlink_to(victim, target_is_directory=True)
    with pytest.raises(MigrationError) as ei:
        MigrationCoordinator(
            state_path=state_root / "mig" / "coordinator.sqlite3",
            migration_id="m-1",
            source_path=str(tmp_path / "v2.sqlite3"),
            ledger_id="ledger-1",
            clock=_clock(),
        )
    assert ei.value.code == "state_component_rejected"
    assert list(victim.rglob("*")) == []


# ---------------------------------------------------------------- 最终组件 symlink


def test_inbox_rejects_symlinked_db_file(tmp_path: Path):
    """db 最终组件预置 symlink: sqlite connect 不得跟随读写穿 (Op1 实证同型)。"""
    victim = tmp_path / "victim"
    victim.mkdir()
    db = tmp_path / "inbox.sqlite3"
    db.symlink_to(victim / "stolen.sqlite3")
    with pytest.raises(InboxError) as ei:
        DurableCapitalInbox(db, clock=_clock())
    assert ei.value.code == "inbox_path_rejected"
    assert list(victim.rglob("*")) == []


def test_authority_rejects_symlinked_db_file(tmp_path: Path):
    victim = tmp_path / "victim"
    victim.mkdir()
    db = tmp_path / "authority.sqlite3"
    db.symlink_to(victim / "stolen.sqlite3")
    with pytest.raises(AuthorityError) as ei:
        AuthorityRegistry(db, clock=_clock())
    assert ei.value.code == "authority_path_rejected"
    assert list(victim.rglob("*")) == []


def test_coordinator_rejects_symlinked_db_file(tmp_path: Path):
    victim = tmp_path / "victim"
    victim.mkdir()
    db = tmp_path / "coordinator.sqlite3"
    db.symlink_to(victim / "stolen.sqlite3")
    with pytest.raises(MigrationError) as ei:
        MigrationCoordinator(
            state_path=db,
            migration_id="m-1",
            source_path=str(tmp_path / "v2.sqlite3"),
            ledger_id="ledger-1",
            clock=_clock(),
        )
    assert ei.value.code == "state_path_rejected"
    assert list(victim.rglob("*")) == []


# ---------------------------------------------------------------- canonical / happy


@pytest.mark.parametrize(
    "bad", [Path("relative/inbox.sqlite3"), Path("/abs/../escape/inbox.sqlite3")]
)
def test_inbox_rejects_non_canonical_paths(bad: Path):
    with pytest.raises(InboxError):
        DurableCapitalInbox(bad, clock=_clock())


def test_inbox_creates_nested_state_dirs_and_is_idempotent(tmp_path: Path):
    path = tmp_path / "state" / "mig" / "inbox.sqlite3"
    inbox = DurableCapitalInbox(path, clock=_clock())
    assert path.is_file()
    again = DurableCapitalInbox(path, clock=_clock())
    assert again.path == inbox.path


def test_authority_happy_path(tmp_path: Path):
    registry = AuthorityRegistry(tmp_path / "state" / "authority.sqlite3", clock=_clock())
    assert (tmp_path / "state" / "authority.sqlite3").is_file()
    # 重放幂等
    AuthorityRegistry(tmp_path / "state" / "authority.sqlite3", clock=_clock())


def test_coordinator_happy_path(tmp_path: Path):
    coordinator = MigrationCoordinator(
        state_path=tmp_path / "state" / "coordinator.sqlite3",
        migration_id="m-1",
        source_path=str(tmp_path / "v2.sqlite3"),
        ledger_id="ledger-1",
        clock=_clock(),
    )
    assert (tmp_path / "state" / "coordinator.sqlite3").is_file()
