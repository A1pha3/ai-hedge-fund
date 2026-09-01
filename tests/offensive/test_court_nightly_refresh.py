"""court 夜度保鲜编排器测试 (R93 Op1)。

判定面 (触发器账本/gap 证据/先验对齐) 的机械耦合终点在 btst_court_build 的
R84 判定刷新钩子, 但 build 本身只存在于人工运行 — 数据停更时三类证据静默
冻结在最后覆盖日。本编排器把 fetch→build 接进夜度链 (launcher heredoc,
同 NS-5 run_daily_regime_refresh 先例)。测试钉死:

① 编排契约: fetch 用默认参数 (默认值即前向增长契约: daily 自 PANEL_START,
   limit_list 自 WINDOW_A_START — H1 2025 回填已由 R89 完成), build 的
   --start 从生产 manifest window.start 派生 (表自身是窗口真话, 不二次硬
   编码), cwd=repo_root;
② fail-open: fetch/build 失败、超时 → 结构化 status, 绝不抛 (夜度链的
   生产步骤 --auto/--daily-action 永不被研究面刷新阻断);
③ 窗口真话: manifest 缺失/损坏/window.start 非 str → skip build 并披露
   reason (建立判定面是人为决策, 编排器绝不发明窗口), fetch 照常;
④ 常量 drift-guard: 表目录常量与 btst_court_build.TABLE_DIR 单源。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from screening.offensive.court_nightly_refresh import (  # noqa: E402
    COURT_TABLE_DIR_REL,
    run_court_nightly_refresh,
)


def _write_manifest(root: Path, manifest: object) -> None:
    table_dir = root / COURT_TABLE_DIR_REL
    table_dir.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(manifest, ensure_ascii=False) if not isinstance(manifest, str) else manifest
    (table_dir / "manifest_v1.json").write_text(payload, encoding="utf-8")


class _RecordingRunner:
    """fake _runner: 记录 (args, cwd, timeout), 按脚本名返回预设 rc。"""

    def __init__(self, rc_by_script: dict[str, int] | None = None, exc: Exception | None = None):
        self.calls: list[tuple[list[str], Path, int]] = []
        self.rc_by_script = rc_by_script or {}
        self.exc = exc

    def __call__(self, args: list[str], cwd: Path, timeout_s: int):
        self.calls.append((list(args), cwd, timeout_s))
        if self.exc is not None:
            raise self.exc
        script = args[0]
        return self.rc_by_script.get(script, 0), "out"


class TestCourtNightlyRefreshOrchestration:
    def test_fetch_then_build_with_manifest_window_start(self, tmp_path):
        _write_manifest(tmp_path, {"window": {"start": "20250102", "end": "20260901", "sessions": 396}})
        runner = _RecordingRunner()
        status = run_court_nightly_refresh(repo_root=tmp_path, _runner=runner)
        assert [c[0] for c in runner.calls] == [
            ["scripts/btst_court_fetch.py"],
            ["scripts/btst_court_build.py", "--start", "20250102"],
        ]
        assert all(c[1] == tmp_path for c in runner.calls)
        assert status["ok"] is True
        assert status["build"]["window_start"] == "20250102"
        assert status["build"]["rc"] == 0

    def test_manifest_missing_skips_build_but_fetch_still_runs(self, tmp_path):
        runner = _RecordingRunner()
        status = run_court_nightly_refresh(repo_root=tmp_path, _runner=runner)
        assert [c[0] for c in runner.calls] == [["scripts/btst_court_fetch.py"]]
        assert "skipped" in status["build"]
        assert status["ok"] is True  # skip 不是错误 (判定面未建立的合法稳态)

    def test_manifest_corrupt_or_window_missing_skips_build(self, tmp_path):
        for bad in ("not json at all", {"window": {"start": 5}}, {"window": "bad"}, {}):
            root = tmp_path / str(abs(hash(json.dumps(bad, default=str))))
            root.mkdir()
            _write_manifest(root, bad)
            runner = _RecordingRunner()
            status = run_court_nightly_refresh(repo_root=root, _runner=runner)
            assert [c[0] for c in runner.calls] == [["scripts/btst_court_fetch.py"]]
            assert "skipped" in status["build"]

    def test_fetch_failure_skips_build_fail_open(self, tmp_path):
        """fetch 失败 → build 跳过 (绝不在可能撕裂的原料上重建; 跳过自愈
        无损 — 同数据重建本就被前进门 skip, 只损失一夜刷新)。"""
        _write_manifest(tmp_path, {"window": {"start": "20250102"}})
        runner = _RecordingRunner(rc_by_script={"scripts/btst_court_fetch.py": 1})
        status = run_court_nightly_refresh(repo_root=tmp_path, _runner=runner)
        assert status["fetch"]["rc"] == 1
        assert len(runner.calls) == 1
        assert "skipped" in status["build"]
        assert status["ok"] is False

    def test_runner_timeout_is_fail_open(self, tmp_path):
        _write_manifest(tmp_path, {"window": {"start": "20250102"}})
        runner = _RecordingRunner(exc=subprocess.TimeoutExpired(cmd="fetch", timeout=1))
        status = run_court_nightly_refresh(repo_root=tmp_path, _runner=runner)
        assert "timeout" in str(status["fetch"]["error"]).lower()
        assert len(runner.calls) == 1
        assert "skipped" in status["build"]
        assert status["ok"] is False

    def test_build_failure_is_fail_open(self, tmp_path):
        _write_manifest(tmp_path, {"window": {"start": "20250102"}})
        runner = _RecordingRunner(rc_by_script={"scripts/btst_court_build.py": 2})
        status = run_court_nightly_refresh(repo_root=tmp_path, _runner=runner)
        assert status["build"]["rc"] == 2
        assert status["ok"] is False

    def test_never_raises_on_any_step(self, tmp_path):
        _write_manifest(tmp_path, {"window": {"start": "20250102"}})
        runner = _RecordingRunner(
            rc_by_script={"scripts/btst_court_fetch.py": 3, "scripts/btst_court_build.py": 4},
            exc=OSError("no interpreter"),
        )
        status = run_court_nightly_refresh(repo_root=tmp_path, _runner=runner)
        assert status["ok"] is False
        assert "no interpreter" in str(status["fetch"]["error"])
        assert "skipped" in status["build"]


class TestConstantsDriftGuard:
    def test_table_dir_matches_build_single_source(self):
        """编排器读 manifest 的表目录必须与 btst_court_build.TABLE_DIR 单源 —
        build 换目录而编排器不知 → 派生旧窗口重建错表。"""
        scripts_dir = Path(__file__).resolve().parents[2] / "scripts"
        sys.path.insert(0, str(scripts_dir))
        try:
            import btst_court_build as bcb
        finally:
            sys.path.remove(str(scripts_dir))
        assert bcb.TABLE_DIR == Path(COURT_TABLE_DIR_REL) or bcb.TABLE_DIR.resolve() == Path(
            COURT_TABLE_DIR_REL
        ).resolve()
