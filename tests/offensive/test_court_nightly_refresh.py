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
    ALIGNMENT_SUMMARY_REL,
    COURT_TABLE_DIR_REL,
    DIAGNOSTIC_SCRIPTS,
    DIAGNOSTIC_TIMEOUT_S,
    RECONCILE_SCRIPT_REL,
    run_court_nightly_refresh,
)


def _write_manifest(root: Path, manifest: object) -> None:
    table_dir = root / COURT_TABLE_DIR_REL
    table_dir.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(manifest, ensure_ascii=False) if not isinstance(manifest, str) else manifest
    (table_dir / "manifest_v1.json").write_text(payload, encoding="utf-8")


class _RecordingRunner:
    """fake _runner: 记录 (args, cwd, timeout), 按脚本名返回预设 (rc, out, err)。"""

    def __init__(self, rc_by_script: dict[str, int] | None = None,
                 exc: Exception | None = None,
                 err_by_script: dict[str, str] | None = None):
        self.calls: list[tuple[list[str], Path, int]] = []
        self.rc_by_script = rc_by_script or {}
        self.err_by_script = err_by_script or {}
        self.exc = exc

    def __call__(self, args: list[str], cwd: Path, timeout_s: int):
        self.calls.append((list(args), cwd, timeout_s))
        if self.exc is not None:
            raise self.exc
        script = args[0]
        return self.rc_by_script.get(script, 0), "out", self.err_by_script.get(script, "")


class TestCourtNightlyRefreshOrchestration:
    def test_fetch_then_build_with_manifest_window_start(self, tmp_path):
        _write_manifest(tmp_path, {"window": {"start": "20250102", "end": "20260901", "sessions": 396}})
        runner = _RecordingRunner()
        status = run_court_nightly_refresh(repo_root=tmp_path, _runner=runner)
        assert [c[0] for c in runner.calls] == [
            ["scripts/btst_court_fetch.py"],
            ["scripts/btst_court_build.py", "--start", "20250102"],
            [RECONCILE_SCRIPT_REL, "--summary-json", ALIGNMENT_SUMMARY_REL],
            *([[script] for script in DIAGNOSTIC_SCRIPTS]),
        ]
        assert all(c[1] == tmp_path for c in runner.calls)
        assert status["ok"] is True
        assert status["build"]["window_start"] == "20250102"
        assert status["build"]["rc"] == 0
        assert status["reconcile"] == {"rc": 0, "error": None}

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


class TestNightlyDiagnosticsRefresh:
    """R133 Op3: 证据链诊断报告保鲜步 — build 成功后与 reconcile 同门,
    逐脚本独立 fail-open (一个失败不阻断其余, ok 语义不变)。
    """

    def test_diagnostic_scripts_pinned_set(self):
        # R135 Op1 drift-guard: 保鲜链成员显式钉死全集 — R134 Op1 的
        # stock_feature_attribution 提交晚于 R133 Op3 曾静默缺席, 陈旧诊断
        # 面的 split-half 判定会被操作员当现状消费; 未来新增诊断脚本漏接
        # 在此当场暴露 (顺序也是契约: status.diagnostics 键序可读性)。
        assert DIAGNOSTIC_SCRIPTS == (
            "scripts/winrate_payoff_decomposition.py",
            "scripts/btst_signal_day_cohort.py",
            "scripts/realized_selection_wedge.py",
            "scripts/day_feature_attribution.py",
            "scripts/stock_feature_attribution.py",
        )

    def test_build_success_runs_diagnostics_in_order(self, tmp_path):
        _write_manifest(tmp_path, {"window": {"start": "20250102"}})
        runner = _RecordingRunner()
        status = run_court_nightly_refresh(repo_root=tmp_path, _runner=runner)
        diag_calls = runner.calls[-len(DIAGNOSTIC_SCRIPTS):]
        assert [c[0] for c in diag_calls] == [[s] for s in DIAGNOSTIC_SCRIPTS]
        assert all(c[1] == tmp_path for c in diag_calls)
        assert all(c[2] == DIAGNOSTIC_TIMEOUT_S for c in diag_calls)
        assert status["diagnostics"] == {
            s: {"rc": 0, "error": None} for s in DIAGNOSTIC_SCRIPTS
        }
        assert status["ok"] is True

    def test_build_skip_runs_no_diagnostics(self, tmp_path):
        # 与 reconcile 同门: 只在表真正重建后刷新, skip/fetch 失败零诊断调用
        runner = _RecordingRunner()
        status = run_court_nightly_refresh(repo_root=tmp_path, _runner=runner)
        assert "diagnostics" not in status
        assert len(runner.calls) == 1  # 仅 fetch

    def test_diagnostics_fail_open_one_failure_does_not_block_rest(self, tmp_path):
        _write_manifest(tmp_path, {"window": {"start": "20250102"}})
        runner = _RecordingRunner(
            rc_by_script={
                DIAGNOSTIC_SCRIPTS[0]: 5,
                DIAGNOSTIC_SCRIPTS[-1]: 6,
            },
            err_by_script={DIAGNOSTIC_SCRIPTS[0]: "boom"},
        )
        status = run_court_nightly_refresh(repo_root=tmp_path, _runner=runner)
        assert status["diagnostics"][DIAGNOSTIC_SCRIPTS[0]]["rc"] == 5
        assert "boom" in status["diagnostics"][DIAGNOSTIC_SCRIPTS[0]]["error"]
        assert status["diagnostics"][DIAGNOSTIC_SCRIPTS[-1]]["rc"] == 6
        assert status["diagnostics"][DIAGNOSTIC_SCRIPTS[1]] == {"rc": 0, "error": None}
        # 诊断面失败绝不改变 ok 语义 (build 成功即 True), reconcile 照跑
        assert status["ok"] is True
        assert status["reconcile"]["rc"] == 0
        assert len(runner.calls) == 3 + len(DIAGNOSTIC_SCRIPTS)

    def test_diagnostics_runner_exception_fail_open_never_raises(self, tmp_path):
        _write_manifest(tmp_path, {"window": {"start": "20250102"}})

        def _flaky_runner(args, cwd, timeout_s):
            if args[0] == DIAGNOSTIC_SCRIPTS[1]:
                raise OSError("interpreter vanished")
            return 0, "out", ""

        status = run_court_nightly_refresh(repo_root=tmp_path, _runner=_flaky_runner)
        assert "vanished" in str(status["diagnostics"][DIAGNOSTIC_SCRIPTS[1]]["error"])
        assert status["diagnostics"][DIAGNOSTIC_SCRIPTS[0]] == {"rc": 0, "error": None}
        assert status["diagnostics"][DIAGNOSTIC_SCRIPTS[2]] == {"rc": 0, "error": None}
        assert status["ok"] is True


class TestFailureDiagnosability:
    """Op1 交付面对抗审查 (R93 Op2): 夜度保鲜是无人值守步骤 — 失败可诊断性
    必须在交付时成立, 而非失败夜现场补。

    ① stderr 丢弃: _default_runner 只取 stdout, proc.stderr 捕获后丢弃 —
    夜跑失败时 status.error 只有 'spawn failed'/'timeout' 笼统串, tushare
    API 报错/缺 token 等真因只存在于被丢弃的 stderr;
    ② rc≠0 无诊断: 非零退出 (脚本自身 SystemExit/traceback rc=1) 连笼统
    error 都没有, status.fetch = {"rc": 1, "error": None};
    ③ SubprocessError 只捕 TimeoutExpired 子类 — 非超时变体外抛, 违反
    模块『绝不抛』fail-open 自述契约。
    """

    def test_rc_failure_error_includes_stderr_tail(self, tmp_path):
        _write_manifest(tmp_path, {"window": {"start": "20250102"}})
        runner = _RecordingRunner(
            rc_by_script={"scripts/btst_court_fetch.py": 1},
            err_by_script={"scripts/btst_court_fetch.py":
                           "Traceback ... tushare API Error: token invalid"},
        )
        status = run_court_nightly_refresh(repo_root=tmp_path, _runner=runner)
        assert "token invalid" in status["fetch"]["error"]
        assert status["fetch"]["rc"] == 1

    def test_error_tail_truncated(self, tmp_path):
        _write_manifest(tmp_path, {"window": {"start": "20250102"}})
        runner = _RecordingRunner(
            rc_by_script={"scripts/btst_court_fetch.py": 1},
            err_by_script={"scripts/btst_court_fetch.py": "x" * 10000},
        )
        status = run_court_nightly_refresh(repo_root=tmp_path, _runner=runner)
        assert len(status["fetch"]["error"]) < 500

    def test_success_steps_have_none_error(self, tmp_path):
        _write_manifest(tmp_path, {"window": {"start": "20250102"}})
        status = run_court_nightly_refresh(repo_root=tmp_path, _runner=_RecordingRunner())
        assert status["fetch"]["error"] is None
        assert status["build"]["error"] is None

    def test_non_timeout_subprocess_error_is_fail_open(self, tmp_path):
        _write_manifest(tmp_path, {"window": {"start": "20250102"}})
        runner = _RecordingRunner(exc=subprocess.SubprocessError("call failed"))
        status = run_court_nightly_refresh(repo_root=tmp_path, _runner=runner)
        assert "call failed" in str(status["fetch"]["error"])
        assert "skipped" in status["build"]
        assert status["ok"] is False


class TestCourtNightlyRefreshStatusPersistence:
    """R115 Op2: 结构化 status 原子落盘 — 操作员新鲜度告警行的归因真话来源."""

    def test_status_artifact_written_on_success(self, tmp_path):
        _write_manifest(tmp_path, {"window": {"start": "20250102"}})
        status = run_court_nightly_refresh(repo_root=tmp_path, _runner=_RecordingRunner())
        assert status["ok"] is True
        data = json.loads(
            (tmp_path / "data/reports/court_refresh_status.json").read_text(encoding="utf-8")
        )
        assert data["ok"] is True
        assert data["build"]["rc"] == 0

    def test_status_artifact_written_on_fetch_failure(self, tmp_path):
        runner = _RecordingRunner(rc_by_script={"scripts/btst_court_fetch.py": 1})
        status = run_court_nightly_refresh(repo_root=tmp_path, _runner=runner)
        assert status["ok"] is False
        data = json.loads(
            (tmp_path / "data/reports/court_refresh_status.json").read_text(encoding="utf-8")
        )
        assert data["ok"] is False
        assert data["build"]["skipped"] == "fetch_failed"

    def test_status_persist_failure_is_advisory(self, tmp_path):
        """data/reports 为文件 → 落盘失败只 WARNING, 返回值形状不变不抛."""
        (tmp_path / "data").write_text("not a dir", encoding="utf-8")
        runner = _RecordingRunner(rc_by_script={"scripts/btst_court_fetch.py": 1})
        status = run_court_nightly_refresh(repo_root=tmp_path, _runner=runner)
        assert status["ok"] is False


class TestCourtNightlyReconcileStep:
    """R118 Op1: 宇宙对齐刷新步 — 只在 build 成功后重算, fail-open 不改 ok 语义."""

    def test_reconcile_failure_does_not_flip_ok(self, tmp_path):
        _write_manifest(tmp_path, {"window": {"start": "20250102"}})
        runner = _RecordingRunner(rc_by_script={RECONCILE_SCRIPT_REL: 1},
                                  err_by_script={RECONCILE_SCRIPT_REL: "exit rc=1: alignment boom"})
        status = run_court_nightly_refresh(repo_root=tmp_path, _runner=runner)
        assert status["ok"] is True  # ok 语义 = fetch+build, reconcile 是诊断面
        assert status["reconcile"]["rc"] == 1
        assert "alignment boom" in status["reconcile"]["error"]

    def test_build_skip_runs_no_reconcile(self, tmp_path):
        # manifest 缺失 → build skip → court 表未重建, 不重算 (fresh install 无表不加噪声)
        runner = _RecordingRunner()
        status = run_court_nightly_refresh(repo_root=tmp_path, _runner=runner)
        assert "reconcile" not in status
        assert [c[0] for c in runner.calls] == [["scripts/btst_court_fetch.py"]]

    def test_fetch_failure_runs_no_reconcile(self, tmp_path):
        _write_manifest(tmp_path, {"window": {"start": "20250102"}})
        runner = _RecordingRunner(rc_by_script={"scripts/btst_court_fetch.py": 1})
        status = run_court_nightly_refresh(repo_root=tmp_path, _runner=runner)
        assert status["ok"] is False
        assert "reconcile" not in status
        assert [c[0] for c in runner.calls] == [["scripts/btst_court_fetch.py"]]

    def test_build_failure_runs_no_reconcile(self, tmp_path):
        _write_manifest(tmp_path, {"window": {"start": "20250102"}})
        runner = _RecordingRunner(rc_by_script={"scripts/btst_court_build.py": 2})
        status = run_court_nightly_refresh(repo_root=tmp_path, _runner=runner)
        assert status["ok"] is False
        assert "reconcile" not in status
