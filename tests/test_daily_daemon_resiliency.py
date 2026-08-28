"""daily_daemon.sh 解释器级故障韧性契约 (R54 Op1)。

08-27 实锤的故障族: .venv python 不可用 (TCC 类 PermissionError) 时 run_once
静默失败、无当晚补跑、无失败记录 (status_history.jsonl 中 08-27 整日缺席)。
本套件以 stub 解释器/管道注入 (hermetic tmp repo, 零网络、零生产状态触碰)
真实驱动 daemon 的 run_once + preflight + 有界重试 + 显式失败记录逻辑。

生产不变式:
- 默认配置 (DAEMON_* 未设置时) 逐字节保持旧行为: PY=.venv/bin/python、
  触发 18:01、管道 scripts/run_daily_pipeline.py。
- selftest 注入面 (--selftest-once / --print-config / --selftest-next-trigger)
  跳过生产单实例锁与 pid 文件, 绝不触碰运行中守护的状态。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
DAEMON = REPO_ROOT / "scripts" / "daily_daemon.sh"
SELFTEST_TIMEOUT_S = 30


def _write_stub(path: Path, body: str) -> str:
    path.write_text(body)
    path.chmod(0o755)
    return str(path)


@pytest.fixture()
def fake_repo(tmp_path: Path) -> Path:
    """hermetic 假 repo: daemon 的 DAEMON_REPO 覆盖目标。"""
    (tmp_path / "logs" / "cron").mkdir(parents=True)
    return tmp_path


def _stub_py(fake_repo: Path, fail_times: int) -> str:
    counter = fake_repo / "py_counter"
    return _write_stub(
        fake_repo / "stub_py",
        f'#!/bin/bash\n'
        f'n=$(cat "{counter}" 2>/dev/null || echo 0)\n'
        f'n=$((n + 1))\necho "$n" > "{counter}"\n'
        f'[ "$n" -le {fail_times} ] && exit 7\n'
        # 假解释器语义: "-c cmd" 内联求值 (探活形态); 文件参数形态 exec 该脚本
        f'if [ "${{1:-}}" = "-c" ]; then exit 0; fi\n'  # 探活形态: 解释器能启动即退出 0

        f'[ "$#" -gt 0 ] && exec "$@"\nexit 0\n',
    )


def _stub_pipeline(fake_repo: Path) -> str:
    marker = fake_repo / "pipeline_invocations"
    return _write_stub(
        fake_repo / "stub_pipeline",
        f'#!/bin/bash\necho "$*" >> "{marker}"\nexit 0\n',
    )


def _run_daemon(fake_repo: Path, *args: str, fail_times: int = 0,
                max_attempts: int = 3, retry_interval: int = 1,
                timeout: int = SELFTEST_TIMEOUT_S) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env.update(
        {
            "DAEMON_REPO": str(fake_repo),
            "DAEMON_PY": _stub_py(fake_repo, fail_times),
            "DAEMON_PIPELINE": _stub_pipeline(fake_repo),
            "DAEMON_MAX_ATTEMPTS": str(max_attempts),
            "DAEMON_RETRY_INTERVAL": str(retry_interval),
        }
    )
    return subprocess.run(
        ["bash", str(DAEMON), *args],
        cwd=str(fake_repo),
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _status_history(fake_repo: Path) -> list[dict]:
    path = fake_repo / "logs" / "cron" / "status_history.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def test_healthy_interpreter_runs_pipeline_without_failure_records(fake_repo: Path) -> None:
    proc = _run_daemon(fake_repo, "--selftest-once")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "=== 每日管道开始 ===" in proc.stdout
    assert "=== 每日管道结束 rc=0 ===" in proc.stdout
    invocations = (fake_repo / "pipeline_invocations").read_text().splitlines()
    assert len(invocations) == 1
    assert _status_history(fake_repo) == []


def test_interpreter_never_recovers_records_failures_and_gives_up(fake_repo: Path) -> None:
    proc = _run_daemon(fake_repo, "--selftest-once", fail_times=999,
                       max_attempts=3, retry_interval=1)
    assert proc.returncode == 97, proc.stdout + proc.stderr
    invocations = fake_repo / "pipeline_invocations"
    assert not invocations.exists()
    assert "=== 每日管道开始 ===" not in proc.stdout
    lines = _status_history(fake_repo)
    assert len(lines) == 4  # 3 次尝试失败 + 1 条终态放弃
    for line in lines[:3]:
        assert line["daemon_error"] == "interpreter_unavailable"
        assert line["date"] == "20260101" or len(line["date"]) == 8
    assert lines[3]["daemon_error"] == "interpreter_unavailable_gave_up"


def test_retry_after_transient_failure_runs_pipeline_once(fake_repo: Path) -> None:
    proc = _run_daemon(fake_repo, "--selftest-once", fail_times=1,
                       max_attempts=3, retry_interval=1)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    invocations = (fake_repo / "pipeline_invocations").read_text().splitlines()
    assert len(invocations) == 1
    lines = _status_history(fake_repo)
    assert len(lines) == 1
    assert lines[0]["daemon_error"] == "interpreter_unavailable"
    assert lines[0]["attempt"] == 1


def test_failure_lines_are_valid_json_with_required_keys(fake_repo: Path) -> None:
    _run_daemon(fake_repo, "--selftest-once", fail_times=999,
                max_attempts=3, retry_interval=1)
    lines = _status_history(fake_repo)
    assert len(lines) == 4  # 3 次尝试 + 1 条终态放弃 (attempt 重复计最后一次)
    for i, line in enumerate(lines, start=1):
        assert set(line) == {"date", "daemon_error", "rc", "attempt"}
        assert isinstance(line["rc"], int)
    for i, line in enumerate(lines[:3], start=1):
        assert line["attempt"] == i
        assert line["daemon_error"] == "interpreter_unavailable"
    assert lines[3]["daemon_error"] == "interpreter_unavailable_gave_up"
    assert lines[3]["attempt"] == 3


def test_print_config_reports_production_defaults(fake_repo: Path) -> None:
    env = dict(os.environ)
    for key in [k for k in env if k.startswith("DAEMON_")]:
        env.pop(key)
    # DAEMON_REPO 指向本 checkout (slot 兼容): 断言其余默认值相对该 repo 组合
    env["DAEMON_REPO"] = str(REPO_ROOT)
    proc = subprocess.run(
        ["bash", str(DAEMON), "--print-config"],
        cwd=str(fake_repo), env=env, capture_output=True, text=True, timeout=30,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    config = dict(
        line.split("=", 1) for line in proc.stdout.splitlines() if "=" in line
    )
    assert config["REPO"] == str(REPO_ROOT)
    assert config["PY"] == str(REPO_ROOT / ".venv" / "bin" / "python")
    assert config["PIPELINE"] == "scripts/run_daily_pipeline.py"
    assert config["TRIGGER_HH"] == "18"
    assert config["TRIGGER_MM"] == "1"
    assert int(config["MAX_ATTEMPTS"]) >= 2


def test_selftest_never_touches_production_lock_or_pid(fake_repo: Path) -> None:
    pid_file = REPO_ROOT / "logs" / ".daily_daemon.pid"
    pid_before = pid_file.read_text() if pid_file.exists() else None
    _run_daemon(fake_repo, "--selftest-once", fail_times=1, retry_interval=1)
    if pid_before is not None:
        assert pid_file.read_text() == pid_before
    assert not (fake_repo / "logs" / ".daily_daemon.pid").exists()
    assert not (fake_repo / "logs" / ".daily_daemon.lock.d").exists()
    if pid_before is None:
        assert not pid_file.exists()


def test_next_trigger_math_is_pure_and_date_rolling() -> None:
    # 2026-08-28 12:00 CST 的 epoch; 触发 18:01 同日
    now = 1787889600  # 通过 --selftest-next-trigger 注入假 now, 断言相对秒数
    proc = subprocess.run(
        ["bash", str(DAEMON), "--selftest-next-trigger", "18", "1", str(now)],
        cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=30,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    seconds = int(proc.stdout.strip())
    assert 6 * 3600 <= seconds <= 6 * 3600 + 120  # 12:00 → 18:01 ≈ 6h1m

    now_after = 1787914000  # 同日 18:50 之后 → 次日 18:01
    proc = subprocess.run(
        ["bash", str(DAEMON), "--selftest-next-trigger", "18", "1", str(now_after)],
        cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=30,
    )
    seconds = int(proc.stdout.strip())
    assert 23 * 3600 <= seconds <= 24 * 3600


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
