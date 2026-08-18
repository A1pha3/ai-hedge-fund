"""先验方向断言接入 daemon 日链 — advisory 哨点接线行为测试.

背景: review_btst_prior_court.py --check (2026-08-19) 的方向断言此前只在
人工重验时执行; 事件表重建后先验-court 关系漂移被动等待下次评估才可见。
daemon 日链收尾跑一次 --check (秒级) 让漂移当天暴露 (trap 20 同型)。

advisory 语义: 哨点异常/超时绝不拖垮每日管道, final_rc 计算路径不变。
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "run_daily_pipeline.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("run_daily_pipeline_for_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class _NullLog:
    def write(self, *_a, **_k):  # pragma: no cover - 仅吸收
        pass

    def flush(self):  # pragma: no cover
        pass


def test_advisory_sentinels_include_prior_direction_check(monkeypatch):
    """_run_advisory_sentinels 必须调用 court 资产哨点 + 先验方向断言两个 advisory."""
    module = _load_module()
    calls: list[list[str]] = []

    def fake_call(argv, **_kw):
        calls.append([str(a) for a in argv])
        return 0

    monkeypatch.setattr(module.subprocess, "call", fake_call)
    module._run_advisory_sentinels(_NullLog())
    joined = [" ".join(c) for c in calls]
    assert any("court_asset_sentinel.py" in c for c in joined), joined
    assert any("review_btst_prior_court.py" in c and "--check" in c for c in joined), joined


def test_advisory_sentinels_swallow_failure(monkeypatch):
    """任一哨点崩溃不抛出 — advisory 语义 (trap 22 先例)."""
    module = _load_module()

    def boom(*_a, **_kw):
        raise RuntimeError("sentinel crashed")

    monkeypatch.setattr(module.subprocess, "call", boom)
    module._run_advisory_sentinels(_NullLog())  # 不应抛出


def test_prior_check_timeout_bounded():
    """--check 的 bootstrap 计算有界: timeout 不得超过 120s (daemon 链尾延迟可控)."""
    text = SCRIPT.read_text(encoding="utf-8")
    m = [line for line in text.splitlines() if "review_btst_prior_court.py" in line]
    assert m, "run_daily_pipeline 未接线 review_btst_prior_court.py"
    timeout_lines = [l for l in text.splitlines() if "timeout" in l and "review_btst_prior_court" not in l]
    # 接线行所在调用块的 timeout 参数 (同段内) 必须 ≤ 120
    block = text[text.index("_run_advisory_sentinels"):text.index("_run_advisory_sentinels") + 1600]
    import re
    timeouts = [int(v) for v in re.findall(r"timeout=(\d+)", block)]
    assert timeouts and all(t <= 120 for t in timeouts), timeouts


def test_advisory_block_does_not_touch_final_rc():
    """哨点段不得改写 final_rc/status — 只读诊断 (结构断言)."""
    text = SCRIPT.read_text(encoding="utf-8")
    start = text.index("def _run_advisory_sentinels")
    end = text.index('if __name__', start)  # 函数体到模块尾部 guard 为止
    body = text[start:end]
    assert "final_rc" not in body, "advisory 段不得触碰 final_rc"
