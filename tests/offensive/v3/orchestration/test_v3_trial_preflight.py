"""Preflight rehearsal tool tests (R108 Op1).

`scripts/v3_trial_preflight.py` 在生产 trial root 的隔离副本上预演信号会话
的 decide 全链 (官方 CLI ``v3_trial_session.py decide --execute`` 子进程,
注入排练时钟), 把 R103 形态的「烧会话」缺陷从 23:05 后移到 readiness
manifest 就绪后即可人眼拦截的干预窗。契约:

- 预演成功: pair 结果 verbatim 报告, 生产 root + identity 目录字节级零写
  (前后树 digest 相等), 副本默认清理 (``--keep`` 保留);
- 预演失败 (CLI typed 拒绝): 权威 code 原样透传, 副本保留供诊断;
- 守卫: 生产 root 含非空 ``-wal`` (活跃写者/crash 残留) 或 symlink 一律
  拒绝; 排练时钟必须在候选入库窗内;
- 生产 root 被写 (digest 背离): rc=4 最响亮的失败。

fixture 复用 ``test_trial_session_driver`` 的官方栈世界 (R38 CLI --execute
先例); 冷读纪律同款 (dispose + gc — R41/R42 确定性 checkpoint)。
"""

from __future__ import annotations

import gc
import json
import sqlite3
import sys
from pathlib import Path

import pytest

from test_official_trial_stack import TRIAL_ID  # noqa: E402
from test_trial_session_driver import (  # noqa: E402
    DECIDE_AT,
    SIGNAL_SESSION,
    _DriverWorld,
    _published_manifest,
    _tree_digest,
)


def _quiet_world(tmp_path: Path) -> _DriverWorld:
    """官方栈世界 + R35 冷读纪律 (全部引擎确定性 checkpoint, 预演守卫可用).

    预演工具拒绝任何非空 ``-wal`` (撕裂副本防线), 故测试世界必须比 R38
    CLI 测试更彻底地静默——不止 spine/governance, 三命名空间证据库 +
    bars 库的池化引擎全部 dispose, 引用循环持有的连接靠强制 GC 释放
    (R41/R42 同款)。生产 root 在预演时段 (20:30+) 天然处于此形态
    (R107 实测 5 库 -wal 全 0 字节)。
    """
    import gc as _gc

    world = _DriverWorld(tmp_path)
    # 引擎实例清单会随栈构造漂移 (sealer/assembler/dataclass 各持一组),
    # 手工点名不可靠——对进程内全部 SQLAlchemy Engine 全量 dispose,
    # 语义 = 生产预演时段的「无其他持有者」形态 (进程边界天然如此)。
    from sqlalchemy.engine import Engine

    for obj in _gc.get_objects():
        if isinstance(obj, Engine):
            obj.dispose()
    _gc.collect()
    return world


def _argv(
    world: _DriverWorld,
    manifest: Path,
    tmp_path: Path,
    *,
    scratch: Path | None = None,
    keep: bool = False,
    at: str | None = None,
    signal_session: str | None = None,
) -> list[str]:
    argv = [
        "--trial-root", str(world.root),
        "--identity-dir", str(world.identity_dir),
        "--trial-id", TRIAL_ID,
        "--calendar", str(world.calendar_path),
        "--readiness-manifest", str(manifest),
        "--signal-session", signal_session or SIGNAL_SESSION.isoformat(),
        "--at", at or DECIDE_AT.isoformat(),
        "--data-dir", str(tmp_path / "preflight-data"),
        "--scratch-root", str(scratch or tmp_path / "scratch"),
    ]
    if keep:
        argv.append("--keep")
    return argv


def _run(argv: list[str], capsys) -> tuple[int, dict]:
    from scripts.v3_trial_preflight import main

    rc = main(argv)
    payload = json.loads(capsys.readouterr().out)
    return rc, payload


class TestPreflightHappyPath:
    def test_rehearsal_commits_pair_verbatim_and_zero_production_write(
        self, tmp_path: Path, tmp_path_factory, capsys
    ) -> None:
        world = _quiet_world(tmp_path)
        publication = _published_manifest(
            tmp_path_factory.mktemp("reports-pf"), SIGNAL_SESSION
        )
        manifest = publication.artifact_path
        before = _tree_digest(world.root) + _tree_digest(world.identity_dir)
        scratch = tmp_path / "scratch"

        rc, payload = _run(_argv(world, manifest, tmp_path, scratch=scratch), capsys)

        assert rc == 0
        assert payload["ok"] is True
        assert payload["mode"] == "preflight"
        # verbatim pair outcome (双臂状态原样, 不重推导 — R107 纪律)
        # pair_key = (trial_id, signal_session, decision_cycle_id) — 前两位身份断言,
        # cycle id 由会话确定性派生 (daily-action-YYYYMMDD), 不在本测试耦合。
        assert payload["pair_key"][:2] == [TRIAL_ID, SIGNAL_SESSION.isoformat()]
        assert isinstance(payload["champion_status"], str)
        assert payload["champion_status"] == payload["challenger_status"]
        # 字节级零写断言 (前后树 digest 在工具内自证 + 测试独立复证)
        assert payload["production_root_untouched"] is True
        assert _tree_digest(world.root) + _tree_digest(world.identity_dir) == before
        # 成功路径副本默认清理
        assert not scratch.exists() or not any(scratch.rglob("*"))

    def test_keep_preserves_copy_with_committed_pair(
        self, tmp_path: Path, tmp_path_factory, capsys
    ) -> None:
        world = _quiet_world(tmp_path)
        publication = _published_manifest(
            tmp_path_factory.mktemp("reports-keep"), SIGNAL_SESSION
        )
        manifest = publication.artifact_path
        scratch = tmp_path / "scratch-keep"

        rc, payload = _run(
            _argv(world, manifest, tmp_path, scratch=scratch, keep=True), capsys
        )

        assert rc == 0
        copies = list(scratch.rglob("decisions.sqlite3"))
        assert len(copies) == 1, "预演副本必须恰好含一个决策库"
        with sqlite3.connect(f"file:{copies[0]}?mode=ro", uri=True) as conn:
            rows = conn.execute(
                "SELECT count(*) FROM trial_arm_decisions"
                " WHERE signal_session = ?",
                (SIGNAL_SESSION.isoformat(),),
            ).fetchone()
        assert rows[0] == 2, "双臂 pair 两行落库在副本 (不在生产 root)"


class TestPreflightTypedFailures:
    def test_cli_failure_code_passthrough_and_copy_retained(
        self, tmp_path: Path, tmp_path_factory, capsys
    ) -> None:
        """CLI typed 拒绝原样透传; 失败路径副本保留供诊断."""
        world = _quiet_world(tmp_path)
        publication = _published_manifest(
            tmp_path_factory.mktemp("reports-fail"), SIGNAL_SESSION
        )
        manifest = publication.artifact_path
        before = _tree_digest(world.root) + _tree_digest(world.identity_dir)
        scratch = tmp_path / "scratch-fail"

        rc, payload = _run(
            _argv(
                world, manifest, tmp_path, scratch=scratch,
                signal_session="2026-08-07",  # 日历内次日: 预演守卫全过
                at="2026-08-07T15:30:00+00:00",  # (时钟在 08-07 自己的窗内),
            ),
            capsys,
        )
        # 但 reports 目录只有 08-06 的 manifest → CLI typed 拒绝
        # snapshot_load_failed (loader 面先于 session 比对面, R41 契约)

        assert rc == 2
        assert payload["ok"] is False
        assert payload["code"] == "snapshot_load_failed"
        assert payload["production_root_untouched"] is True
        assert _tree_digest(world.root) + _tree_digest(world.identity_dir) == before
        assert any(scratch.rglob("evidence.sqlite3")), "失败副本保留供诊断"

    def test_nonempty_wal_sidecar_refused_before_any_copy(
        self, tmp_path: Path, capsys
    ) -> None:
        world = _quiet_world(tmp_path)
        wal = world.root / "evidence.sqlite3-wal"
        wal.write_bytes(b"x" * 64)  # 活跃写者 / crash 残留形态
        before = _tree_digest(world.root) + _tree_digest(world.identity_dir)
        scratch = tmp_path / "scratch-wal"

        rc, payload = _run(
            _argv(world, tmp_path / "m.json", tmp_path, scratch=scratch), capsys
        )

        assert rc == 2
        assert payload["code"] == "wal_sidecar_active"
        assert payload["production_root_untouched"] is True
        # 守卫先于复制: 零副本副作用 (排除守卫自身写入的 -wal 哨兵后树不变)
        after = _tree_digest(world.root) + _tree_digest(world.identity_dir)
        assert after == before
        assert not scratch.exists()

    def test_symlink_inside_root_refused(self, tmp_path: Path, capsys) -> None:
        world = _quiet_world(tmp_path)
        victim = tmp_path / "victim"
        victim.mkdir()
        (world.root / "arms" / "elsewhere").symlink_to(victim)
        scratch = tmp_path / "scratch-link"

        rc, payload = _run(
            _argv(world, tmp_path / "m.json", tmp_path, scratch=scratch), capsys
        )

        assert rc == 2
        assert payload["code"] == "symlink_in_root"
        assert not scratch.exists()

    def test_rehearsal_clock_outside_window_refused(
        self, tmp_path: Path, capsys
    ) -> None:
        world = _quiet_world(tmp_path)
        scratch = tmp_path / "scratch-clock"

        rc, payload = _run(
            _argv(
                world, tmp_path / "m.json", tmp_path, scratch=scratch,
                at="2026-08-06T14:00:00+00:00",  # 窗开 (15:00 UTC) 之前
            ),
            capsys,
        )

        assert rc == 2
        assert payload["code"] == "rehearsal_clock_out_of_window"
        assert not scratch.exists()

    def test_missing_manifest_refused(self, tmp_path: Path, capsys) -> None:
        world = _quiet_world(tmp_path)
        missing = tmp_path / "no-such-manifest.json"
        rc, payload = _run(
            _argv(world, missing, tmp_path), capsys
        )
        assert rc == 2
        assert payload["code"] == "readiness_manifest_missing"


class TestPreflightMutationGuard:
    def test_production_mutation_is_loudest_failure_rc4(
        self, tmp_path: Path, tmp_path_factory, capsys, monkeypatch
    ) -> None:
        """预演期间生产 root 字节背离 → rc=4 (最响亮, 独立于一切 typed rc=2)."""
        world = _quiet_world(tmp_path)
        publication = _published_manifest(
            tmp_path_factory.mktemp("reports-mut"), SIGNAL_SESSION
        )
        manifest = publication.artifact_path

        def mutating_rehearsal(**kwargs):
            # 模拟工具自身越界 (或并发写者) 在预演期间改写生产 root
            (world.root / "evidence.sqlite3").write_bytes(b"tampered")
            return 0, {"ok": True, "pair_key": None}, ""

        monkeypatch.setattr(
            "scripts.v3_trial_preflight._run_rehearsal", mutating_rehearsal
        )

        rc, payload = _run(_argv(world, manifest, tmp_path), capsys)

        assert rc == 4, "生产面被写必须是 rc=4, 不得混入 typed rc=2 失败族"
        assert payload["ok"] is False
        assert payload["code"] == "production_root_mutated"
        assert payload["production_root_untouched"] is False


class TestPreflightReplayBoundary:
    def test_untyped_cli_crash_passthrough_verbatim(
        self, tmp_path: Path, tmp_path_factory, capsys, monkeypatch
    ) -> None:
        """CLI 裸异常逃逸 (rc=1, 无 JSON) 时工具契约: cli_output_unparseable
        + stderr 尾 verbatim + 生产 root 零写 + 副本保留。

        R108 宿主实演三次取证的真实触发形态: 对已决策会话的事后重放,
        decide 后夜间链 advance 前进了臂台账 (capital 快照读当前头,
        ``as_of`` 只是印记不过滤历史) → checkpoint hash 偏离已存 pair →
        ``arm_decision_conflict`` 自 decide CLI 裸逃逸。分歧根因属 store
        语义 (store 级测试域); 本测试钉死工具侧的全部责任——不吞、不重
        推导、如实透传 + 零写不变式在崩溃路径同样成立。
        """
        world = _quiet_world(tmp_path)
        manifest = _published_manifest(
            tmp_path_factory.mktemp("reports-rb"), SIGNAL_SESSION
        ).artifact_path
        before = _tree_digest(world.root) + _tree_digest(world.identity_dir)
        scratch = tmp_path / "scratch-rb"

        def crashing_rehearsal(**kwargs):
            # _run_rehearsal 契约: stdout 不可解析时返回该权威 dict (空
            # stdout + traceback 全在 stderr = 裸异常逃逸的真实字节形态)
            return (
                1,
                {"ok": False, "code": "cli_output_unparseable"},
                "Traceback (most recent call last):\n"
                "TrialStoreError: arm_decision_conflict: same decision key"
                " already committed with different content\n",
            )

        monkeypatch.setattr(
            "scripts.v3_trial_preflight._run_rehearsal", crashing_rehearsal
        )

        rc, payload = _run(
            _argv(world, manifest, tmp_path, scratch=scratch), capsys
        )

        assert rc == 2
        assert payload["ok"] is False
        assert payload["code"] == "cli_output_unparseable"
        assert payload["production_root_untouched"] is True
        assert "arm_decision_conflict" in (payload["stderr_tail"] or "")
        assert _tree_digest(world.root) + _tree_digest(world.identity_dir) == before
        assert any(scratch.rglob("evidence.sqlite3")), "崩溃路径副本保留供诊断"


class TestPreflightSelfCheck:
    def test_tree_digest_detects_mutation(self, tmp_path: Path) -> None:
        """digest 复验面的自证: 任意新增字节必须改变树 digest (防恒等假绿)."""
        from scripts.v3_trial_preflight import _tree_digest

        (tmp_path / "a.bin").write_bytes(b"one")
        first = _tree_digest(tmp_path)
        (tmp_path / "a.bin").write_bytes(b"two")
        assert _tree_digest(tmp_path) != first
