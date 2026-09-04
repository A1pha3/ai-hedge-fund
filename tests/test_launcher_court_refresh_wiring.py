"""launcher court 保鲜步骤单一事实源 wiring 测试 (R110 Op1/Op2)。

R93 Op1 把 court 夜刷 (fetch+build) 只接线进安装副本 ~/.local/bin/
run_daily_auto_launcher.sh, 仓库副本未同步 — 而脚本头注自述安装方式是
`cp scripts/run_daily_auto_launcher.sh ~/.local/bin/`: 任何一次按文档重装
都会静默丢掉 Step 6 (该步 fail-open 无告警), 触发器账本/分解报告/先验断言
三类证据的数据增长端冻结在最后覆盖日。本文件钉死: 仓库副本含 Step 6 接线
(单一事实源), 且安装副本存在时与仓库副本逐字节一致 (漂移绊线)。

R110 Op2: 接线断言块级化 — 全文级 contains 的相邻命中可放行块内缺防
(如生产步骤哨点行的 "|| true" 恰好垫背), 断言收敛到 Step 6 heredoc 块切片内。
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

REPO_LAUNCHER = Path(__file__).resolve().parent.parent / "scripts" / "run_daily_auto_launcher.sh"
INSTALLED_LAUNCHER = Path.home() / ".local" / "bin" / "run_daily_auto_launcher.sh"


def _step6_block() -> str:
    """Step 6 heredoc 块切片: '# Step 6' 起, 'PYEOF' 行止 (含)."""
    text = REPO_LAUNCHER.read_text(encoding="utf-8")
    start = text.index("# Step 6")
    end = text.index("\nPYEOF", start) + len("\nPYEOF")  # 行首 PYEOF = heredoc 闭合 (非 <<PYEOF 起始符)
    return text[start:end]


def test_launcher_contains_court_refresh_step_fail_open():
    """Step 6 块内含 court_nightly_refresh 调用 + fail-open + .env 预载."""
    text = REPO_LAUNCHER.read_text(encoding="utf-8")
    assert "# Step 6" in text, "仓库 launcher 缺 Step 6 (court 夜刷) — cp 重装会静默丢失"
    block = _step6_block()
    assert "run_court_nightly_refresh()" in block
    assert "|| true" in block, "court 步必须 fail-open (绝不影响生产步骤退出码)"
    assert "dotenv_values" in block, "heredoc 内需自载 .env (launchd 无继承环境)"


def test_step6_block_assertions_have_teeth():
    """负面对照: 缺 fail-open 的伪块必须使块级断言失败 (断言有牙)."""
    text = REPO_LAUNCHER.read_text(encoding="utf-8")
    block = _step6_block()
    toothless = text.replace("<<PYEOF || true", "<<PYEOF")
    assert toothless != text, "伪块构造失效 — launcher 里找不到 <<PYEOF || true"
    # 伪块的块切片不再含 || true → 断言语义可失败
    start = toothless.index("# Step 6")
    end = toothless.index("\nPYEOF", start) + len("\nPYEOF")
    assert "|| true" not in toothless[start:end]


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
        pytest.skip(f"installed launcher missing: {INSTALLED_LAUNCHER}")
    assert INSTALLED_LAUNCHER.read_bytes() == REPO_LAUNCHER.read_bytes(), (
        "launcher 安装副本与仓库副本漂移 — 单一事实源破坏, "
        "重新 cp scripts/run_daily_auto_launcher.sh ~/.local/bin/ 对齐"
    )
