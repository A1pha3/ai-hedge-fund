"""launcher court 保鲜步骤单一事实源 wiring 测试 (R110 Op1)。

R93 Op1 把 court 夜刷 (fetch+build) 只接线进安装副本 ~/.local/bin/
run_daily_auto_launcher.sh, 仓库副本未同步 — 而脚本头注自述安装方式是
`cp scripts/run_daily_auto_launcher.sh ~/.local/bin/`: 任何一次按文档重装
都会静默丢掉 Step 6 (该步 fail-open 无告警), 触发器账本/分解报告/先验断言
三类证据的数据增长端冻结在最后覆盖日。本文件钉死: 仓库副本含 Step 6 接线
(单一事实源), 且安装副本存在时与仓库副本逐字节一致 (漂移绊线)。
"""

from __future__ import annotations

import subprocess
from pathlib import Path

REPO_LAUNCHER = Path(__file__).resolve().parent.parent / "scripts" / "run_daily_auto_launcher.sh"
INSTALLED_LAUNCHER = Path.home() / ".local" / "bin" / "run_daily_auto_launcher.sh"


def test_launcher_contains_court_refresh_step_fail_open():
    """仓库副本含 Step 6 接线: court_nightly_refresh 调用 + fail-open + .env 预载."""
    text = REPO_LAUNCHER.read_text(encoding="utf-8")
    assert "# Step 6" in text, "仓库 launcher 缺 Step 6 (court 夜刷) — cp 重装会静默丢失"
    assert "run_court_nightly_refresh()" in text
    assert "|| true" in text, "court 步必须 fail-open (绝不影响生产步骤退出码)"
    assert "dotenv_values" in text, "heredoc 内需自载 .env (launchd 无继承环境)"


def test_launcher_syntax_valid():
    """bash -n 语法校验 — 接线改动不得破坏 launcher 可执行性."""
    proc = subprocess.run(["bash", "-n", str(REPO_LAUNCHER)], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr


def test_installed_launcher_matches_repo_copy():
    """漂移绊线: 安装副本存在时必须与仓库副本逐字节一致.

    R93 的病根是改了安装副本没回仓库 (或反向) — 任何一侧单独漂移都使
    『cp 重装』或『现役夜刷』与审计真相脱节。安装副本缺失 (未部署环境)
    时 skip — 本断言的真实生效面是宿主。
    """
    if not INSTALLED_LAUNCHER.exists():
        import pytest

        pytest.skip(f"installed launcher missing: {INSTALLED_LAUNCHER}")
    assert INSTALLED_LAUNCHER.read_bytes() == REPO_LAUNCHER.read_bytes(), (
        "launcher 安装副本与仓库副本漂移 — 单一事实源破坏, "
        "重新 cp scripts/run_daily_auto_launcher.sh ~/.local/bin/ 对齐"
    )
