"""v3 官方 Trial 夜间运维链组合契约 (R54 Op2, scripts/v3_trial_nightly.sh)。

R53b 登记的 next_trigger ("23:30 定时任务执行 decide 08-28") 在代码面不存在 —
本链是 runbook 2b/2c + R53b next_trigger 的自动化落地:
  bar 源刷新 (btst_court_fetch) → decide (今日会话, 窗口 23:00 北京后) →
  finalize-missed (NO_RUN 补记)。

组合不变式 (hermetic stub 注入, 零网络、零生产 trial root 触碰):
- 每阶段独立记录 JSONL (v3_nightly_history.jsonl: date/stage/rc/detail);
  单阶段失败不中止后续阶段; 整体 rc = 失败阶段数。
- 解释器 preflight 失败 → 恰一条失败记录 + exit 97 + 零阶段调用
  (镜像 daily_daemon R54 Op1 语义)。
- decide 门: 本地时刻 < 23:00 或今日 readiness manifest 缺失 → skipped 记录,
  绝不调用 decide (typed 拒绝语义由 CLI 权威, 夜间链只如实转记)。
- selftest 面 (--selftest-once) 零锁、零 pid、零生产状态。
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
NIGHTLY = REPO_ROOT / "scripts" / "v3_trial_nightly.sh"
TIMEOUT_S = 30

STAGES = ("fetch", "decide", "finalize")


@pytest.fixture()
def fake_repo(tmp_path: Path) -> Path:
    (tmp_path / "logs" / "cron").mkdir(parents=True)
    (tmp_path / "data" / "reports").mkdir(parents=True)
    return tmp_path


def _write_stub(path: Path, body: str) -> str:
    path.write_text(body)
    path.chmod(0o755)
    return str(path)


def _control_stub_py(fake_repo: Path) -> str:
    """stub 解释器: 消费 V3N_* 控制变量 (nightly 透传 env)。

    - V3N_PREFLIGHT_FAIL=1 → "-c" 探活形态也失败 (7)
    - 其余调用: 记录 argv (单行) 进 stub_invocations.jsonl
    - V3N_FAIL_STAGE 命中 argv 中的 stage 令牌 → 打印 V3N_FAIL_STDOUT 后退 V3N_FAIL_RC
    """
    log = fake_repo / "stub_invocations.jsonl"
    return _write_stub(
        fake_repo / "stub_py",
        f'#!/bin/bash\n'
        f'if [ "${{1:-}}" = "-c" ]; then [ "${{V3N_PREFLIGHT_FAIL:-0}}" = "1" ] && exit 7; exit 0; fi\n'
        f'printf \'%s\\n\' "$*" >> "{log}"\n'
        # 只按 脚本 basename + 子命令 分词匹配 (禁全 argv 子串: tmp 路径含测试名)
        f'subject=" ${{1##*/}} ${{2:-}} "\n'
        f'case "$subject" in\n'
        f'  *" ${{V3N_FAIL_STAGE:-__none__}} "*) ;;\n'
        f'  *"btst_court_fetch.py"*) exit 0 ;;\n'
        f'  *" decide "*) [ -n "${{V3N_FAIL_STDOUT:-}}" ] && printf \'%s\\n\' "$V3N_FAIL_STDOUT"; exit 0 ;;\n'
        f'  *" finalize-missed "*) exit 0 ;;\n'
        f'  *) exit 0 ;;\n'
        f'esac\n'
        f'[ -n "${{V3N_FAIL_STDOUT:-}}" ] && printf \'%s\\n\' "$V3N_FAIL_STDOUT"\n'
        f'exit "${{V3N_FAIL_RC:-0}}"\n',
    )


def _run_nightly(fake_repo: Path, *args: str, now_hhmm: str = "2305",
                 manifest: bool = True, timeout: int = TIMEOUT_S,
                 extra_env: dict | None = None) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    for key in [k for k in env if k.startswith("V3N_")]:
        env.pop(key)
    env.update(
        {
            "V3N_REPO": str(fake_repo),
            "V3N_PY": _control_stub_py(fake_repo),
            "V3N_TRIAL_CLI": str(fake_repo / "trial_cli_dummy"),
            "V3N_REPORTS_DIR": str(fake_repo / "data" / "reports"),
            "V3N_HISTORY": str(fake_repo / "logs" / "cron" / "v3_nightly_history.jsonl"),
            "V3N_NOW_HHMM": now_hhmm,
            "V3N_TODAY": "20260101",
        }
    )
    if manifest:
        (fake_repo / "data" / "reports" / "daily_action_readiness_20260101.json").write_text("{}")
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        ["bash", str(NIGHTLY), *args],
        cwd=str(fake_repo), env=env, capture_output=True, text=True, timeout=timeout,
    )


def _history(fake_repo: Path) -> list[dict]:
    path = fake_repo / "logs" / "cron" / "v3_nightly_history.jsonl"
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]


def _invocations(fake_repo: Path) -> list[str]:
    path = fake_repo / "stub_invocations.jsonl"
    if not path.exists():
        return []
    return path.read_text().splitlines()


def test_preflight_broken_interpreter_records_and_skips_all_stages(fake_repo: Path) -> None:
    proc = _run_nightly(fake_repo, "--selftest-once",
                        extra_env={"V3N_PREFLIGHT_FAIL": "1"})
    assert proc.returncode == 97
    records = _history(fake_repo)
    assert len(records) == 1
    assert records[0]["detail"] == "interpreter_unavailable"
    assert _invocations(fake_repo) == []


def test_all_stages_run_in_order_when_gate_open_and_manifest_present(fake_repo: Path) -> None:
    proc = _run_nightly(fake_repo, "--selftest-once")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    invocations = _invocations(fake_repo)
    assert len(invocations) == 3
    assert "btst_court_fetch.py" in invocations[0]
    assert " decide " in f" {invocations[1]} "
    assert " finalize-missed " in f" {invocations[2]} "
    records = _history(fake_repo)
    assert [r["stage"] for r in records] == list(STAGES)
    assert all(r["rc"] == 0 for r in records)


def test_decide_invocation_carries_session_execute_and_manifest(fake_repo: Path) -> None:
    _run_nightly(fake_repo, "--selftest-once")
    decide_line = next(l for l in _invocations(fake_repo) if " decide " in f" {l} ")
    assert "--execute" in decide_line
    assert "--signal-session" in decide_line
    assert "--readiness-manifest" in decide_line
    assert "--trial-id" in decide_line
    assert "--now" in decide_line


def test_gate_closed_skips_decide_but_runs_other_stages(fake_repo: Path) -> None:
    proc = _run_nightly(fake_repo, "--selftest-once", now_hhmm="1200")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    records = _history(fake_repo)
    decide = next(r for r in records if r["stage"] == "decide")
    assert decide["detail"] == "skipped_gate_closed"
    assert [r["stage"] for r in records] == list(STAGES)
    assert len(_invocations(fake_repo)) == 2  # fetch + finalize, 无 decide


def test_gate_compare_is_octal_safe_for_early_morning_hours(fake_repo: Path) -> None:
    # 00-09 时段 HHMM 前导零: 门比较必须十进制 (无 stderr 八进制报错、语义恒为跳过)
    proc = _run_nightly(fake_repo, "--selftest-once", now_hhmm="0805")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "integer expression" not in proc.stderr
    records = _history(fake_repo)
    decide = next(r for r in records if r["stage"] == "decide")
    assert decide["detail"] == "skipped_gate_closed"


def test_manifest_missing_skips_decide_but_runs_other_stages(fake_repo: Path) -> None:
    proc = _run_nightly(fake_repo, "--selftest-once", manifest=False)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    records = _history(fake_repo)
    decide = next(r for r in records if r["stage"] == "decide")
    assert decide["detail"] == "skipped_no_manifest"
    assert len(_invocations(fake_repo)) == 2


def test_stage_failure_recorded_without_aborting_later_stages(fake_repo: Path) -> None:
    # fetch 失败 (rc 3): decide/finalize 照常; 整体 rc = 失败阶段数 = 1
    proc = _run_nightly(fake_repo, "--selftest-once",
                        extra_env={"V3N_FAIL_STAGE": "btst_court_fetch.py", "V3N_FAIL_RC": "3"})
    assert proc.returncode == 1
    records = _history(fake_repo)
    assert [r["stage"] for r in records] == list(STAGES)
    assert records[0]["rc"] == 3
    assert records[1]["rc"] == 0
    assert records[2]["rc"] == 0
    assert len(_invocations(fake_repo)) == 3


def test_decide_typed_refusal_recorded_with_code(fake_repo: Path) -> None:
    proc = _run_nightly(fake_repo, "--selftest-once",
                        extra_env={"V3N_FAIL_STAGE": "decide", "V3N_FAIL_RC": "2",
                                   "V3N_FAIL_STDOUT": '{"ok": false, "code": "decide_window_violated", "message": "m", "details": {}}'})
    assert proc.returncode == 1
    records = _history(fake_repo)
    decide = next(r for r in records if r["stage"] == "decide")
    assert decide["rc"] == 2
    assert decide["detail"] == "decide_window_violated"


def test_selftest_touches_no_lock_or_pid(fake_repo: Path) -> None:
    _run_nightly(fake_repo, "--selftest-once")
    assert not (fake_repo / "logs" / ".daily_daemon.pid").exists()
    assert not (fake_repo / "logs" / ".daily_daemon.lock.d").exists()


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
