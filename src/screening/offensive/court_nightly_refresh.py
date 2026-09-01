"""court 判定面夜度保鲜编排器 (R93 Op1) — NS-5 run_daily_regime_refresh 同款先例.

判定面 (触发器账本『稳定越零』/ gap 罚分证据 / 先验对齐披露) 的机械耦合
终点在 btst_court_build 成功后的 R84 判定刷新钩子, 但 fetch+build 本身只
存在于人工运行 — 数据停更时三类证据静默冻结在最后覆盖日, 操作员只看到
被动披露 (court 覆盖至 X) 而无机制。本编排器把刷新接进夜度链 (launcher
heredoc 调用, 与 flywheel/regime_refresh 步骤同模式):

1. fetch: ``scripts/btst_court_fetch.py`` 默认参数即前向增长契约
   (daily 自 PANEL_START、limit_list 自 WINDOW_A_START; H1 2025 回填已由
   R89 完成), 幂等续传。
2. build: ``--start`` 从生产 manifest 的 ``window.start`` 派生 — 表自身
   是窗口真话 (R89 Op1), 不在本模块二次硬编码; manifest 缺失/损坏/窗口
   缺失 → skip (建立判定面是人为决策, 编排器绝不擅自发明窗口)。

fail-open 纪律: 任何失败只进结构化 status + 打印, 绝不抛 — 夜度链的
生产步骤 (--auto / --daily-action) 永不被研究面刷新阻断。fetch 失败
(含超时) 时跳过 build: 绝不在可能撕裂的原料上重建; 跳过自愈无损 —
同数据重建本就被前进门 (require_advance) skip, 只损失一夜刷新。
判定刷新的账本保护在 build 侧钩子 (R84 数据前进门 + R93 built_at 出身份),
本模块不重复其语义。
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import Callable

# 与 scripts/_btst_court_common.py TABLE_DIR 单源 (drift-guard 见测试):
# build 换目录而编排器不知 → 从旧 manifest 派生旧窗口重建错表。
COURT_TABLE_DIR_REL = "data/research/btst_court/event_tables"

FetchBuildRunner = Callable[[list[str], Path, int], tuple[int, str]]


def _default_runner(args: list[str], cwd: Path, timeout_s: int) -> tuple[int, str]:
    """venv 内同解释器执行 scripts 子命令 (继承 env: launcher 已注入 .env)。"""
    proc = subprocess.run(
        [sys.executable, *args],
        capture_output=True,
        text=True,
        cwd=str(cwd),
        timeout=timeout_s,
    )
    return proc.returncode, (proc.stdout or "")


def _manifest_window_start(table_dir: Path) -> str | None:
    """生产 manifest 的 window.start (窗口真话单一来源); 不可得 → None。"""
    try:
        manifest = json.loads((table_dir / "manifest_v1.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(manifest, dict):
        return None
    window = manifest.get("window")
    if not isinstance(window, dict):
        return None
    start = window.get("start")
    return start if isinstance(start, str) and start else None


def _run_step(
    runner: FetchBuildRunner, args: list[str], cwd: Path, timeout_s: int
) -> tuple[int | None, str | None]:
    """执行一步; 失败收敛为 (None, error) — 超时/OSError 都不外抛。"""
    try:
        rc, out = runner(args, cwd, timeout_s)
    except subprocess.TimeoutExpired as exc:
        return None, f"timeout after {timeout_s}s: {exc}"
    except OSError as exc:
        return None, f"spawn failed: {exc}"
    return rc, None


def run_court_nightly_refresh(
    repo_root: Path | None = None,
    *,
    fetch_timeout_s: int = 900,
    build_timeout_s: int = 1800,
    _runner: FetchBuildRunner | None = None,
) -> dict[str, object]:
    """fetch → build 一夜保鲜; 返回结构化 status, 绝不抛。

    status 形态::

        {"date": "20260902",
         "fetch": {"rc": 0, "error": None} | {"rc": None, "error": "..."},
         "build": {"rc": 0, "window_start": "20250102", "error": None}
                  | {"skipped": "<reason>"},
         "ok": bool}

    ``ok`` = fetch 成功且 build 成功或合法 skip (判定面未建立是稳态, 不是错误)。
    """
    root = Path(repo_root) if repo_root is not None else Path(__file__).resolve().parents[3]
    runner: FetchBuildRunner = _runner if _runner is not None else _default_runner
    status: dict[str, object] = {"date": date.today().strftime("%Y%m%d")}

    fetch_rc, fetch_err = _run_step(
        runner, ["scripts/btst_court_fetch.py"], root, fetch_timeout_s
    )
    status["fetch"] = {"rc": fetch_rc, "error": fetch_err}

    if fetch_rc != 0 or fetch_err is not None:
        # 绝不在可能撕裂的原料上重建 (跳过自愈无损: 同数据重建本被前进门 skip)
        status["build"] = {"skipped": "fetch_failed"}
        status["ok"] = False
    else:
        window_start = _manifest_window_start(root / COURT_TABLE_DIR_REL)
        if window_start is None:
            status["build"] = {
                "skipped": "court_manifest_missing_or_window_missing"
            }
            status["ok"] = True
        else:
            build_rc, build_err = _run_step(
                runner,
                ["scripts/btst_court_build.py", "--start", window_start],
                root,
                build_timeout_s,
            )
            status["build"] = {
                "rc": build_rc,
                "window_start": window_start,
                "error": build_err,
            }
            status["ok"] = build_rc == 0 and build_err is None

    print("court_nightly_refresh:", json.dumps(status, ensure_ascii=False))
    return status
