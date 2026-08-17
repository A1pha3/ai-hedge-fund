"""regime gate 证据脚本 import 安全测试 — main 守卫化后 import 零副作用.

背景 (2026-08-18 守卫化前): 两脚本在模块级直接跑 4-8 次全市场回测并写
data/reports 产物, stop 脚本还操纵 os.environ['DAILY_ACTION_EXECUTION_STOP'] —
任何 import 即触发。守卫化后: import 只加载常量与函数, 回测仅在
`python scripts/<name>.py` 直接执行时发生。
"""

from __future__ import annotations

import os
import time


def test_import_cross_period_court_has_no_side_effects(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)  # 任何意外写盘都落在 tmp 而非仓库
    start = time.monotonic()
    import scripts.run_regime_gate_cross_period_court as mod  # noqa: F401

    elapsed = time.monotonic() - start
    # 全市场回测是分钟级; 60s 上限容忍冷启动字节码编译, 仍能捕获"import 即回测"回归
    assert elapsed < 60.0, f"import 耗时 {elapsed:.1f}s — 疑似触发了回测"
    assert not (tmp_path / "data" / "reports").exists(), "import 不应写任何产物"
    assert callable(mod.main)


def test_import_stop_loss_court_has_no_side_effects(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DAILY_ACTION_EXECUTION_STOP", raising=False)
    start = time.monotonic()
    import scripts.run_stop_loss_x_regime_gate_court as mod  # noqa: F401

    elapsed = time.monotonic() - start
    assert elapsed < 60.0, f"import 耗时 {elapsed:.1f}s — 疑似触发了回测"
    assert "DAILY_ACTION_EXECUTION_STOP" not in os.environ, "import 不得操纵 env"
    assert not (tmp_path / "data" / "reports").exists(), "import 不应写任何产物"
    assert callable(mod.main)


def test_periods_constants_frozen():
    # 证据窗口冻结: 变更 = 新证据世代, 不是随手改常量
    import scripts.run_regime_gate_cross_period_court as cross
    import scripts.run_stop_loss_x_regime_gate_court as stop

    assert cross.PERIODS == {
        "2022熊市": ("20220104", "20221230"),
        "2024": ("20240102", "20241231"),
    }
    assert stop.PERIODS == {
        "2025H2": ("20250701", "20251231"),
        "2026H1": ("20260101", "20260706"),
    }
