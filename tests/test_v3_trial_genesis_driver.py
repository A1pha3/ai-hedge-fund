"""v3_trial_genesis driver 守卫测试 — Phase 4 (2026-08-20).

封存正确性 (等状态/守恒/幂等/冲突) 由 tests/offensive/v3/orchestration/
test_trial_genesis_archive.py 的存储级套件承担; 本文件锁定 driver 层的
路径守卫、trial-id 校验、dry-run 零写入语义与 --help 可用性。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "v3_trial_genesis.py"
PY = Path(__file__).resolve().parents[1] / ".venv" / "bin" / "python"


def _run(*argv: str) -> subprocess.CompletedProcess:
    return subprocess.run([str(PY), str(SCRIPT), *argv], capture_output=True, text=True)


def test_help_smoke():
    r = _run("--help")
    assert r.returncode == 0 and "genesis" in r.stdout


def test_trial_id_and_capital_guards(tmp_path):
    r = _run("--capital", str(tmp_path / "c.sqlite3"), "--root", str(tmp_path), "--trial-id", "Bad_ID!")
    assert r.returncode == 2 and json.loads(r.stderr)["error"] == "trial_id_rejected"
    r2 = _run("--capital", str(tmp_path / "nope.sqlite3"), "--root", str(tmp_path), "--trial-id", "btst-regime-1")
    assert r2.returncode == 2 and json.loads(r2.stderr)["error"] == "capital_ledger_missing"


def test_relative_root_rejected(tmp_path):
    (tmp_path / "c.sqlite3").write_bytes(b"x")
    r = _run("--capital", str(tmp_path / "c.sqlite3"), "--root", "relative/root", "--trial-id", "btst-regime-1")
    assert r.returncode == 1 and json.loads(r.stderr)["error"] == "root_not_absolute"


def test_dry_run_writes_nothing(tmp_path, monkeypatch):
    capital = tmp_path / "capital.sqlite3"
    capital.write_bytes(b"placeholder-not-a-real-ledger")
    # 打不开的真实 ledger → dry-run fail-closed, 且 root 下零新增
    r = _run("--capital", str(capital), "--root", str(tmp_path / "root"), "--trial-id", "btst-regime-1")
    assert r.returncode != 0
    assert not (tmp_path / "root").exists()


def test_symlink_root_component_rejected(tmp_path):
    (tmp_path / "c.sqlite3").write_bytes(b"x")
    real = tmp_path / "real-root"
    real.mkdir()
    link = tmp_path / "link-root"
    link.symlink_to(real)
    r = _run("--capital", str(tmp_path / "c.sqlite3"), "--root", str(link), "--trial-id", "btst-regime-1")
    assert r.returncode == 1
    assert json.loads(r.stderr)["error"] == "root_symlink_rejected"
