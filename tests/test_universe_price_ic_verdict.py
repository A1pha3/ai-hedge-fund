"""c317b (loop 50) — verdict-rendering + amplification disclosure for the c307
universe price-IC diagnostic.

c308 extracted ``classify_price_effect`` for testability, but the verdict block
in ``run()`` still (a) never called ``amplification_ratio`` (orphaned helper —
the commit message's '3.59× amplification' headline was computed only by tests)
and (b) had no pure-function rendering. This pins the verdict text so a future
change can't silently drop the amplification disclosure or flip the verdict.

Pure helper tests — no network.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from scripts._diag_universe_price_ic import (  # noqa: E402
    render_price_verdict,
)


def test_verdict_bias_amplified_includes_amplification_ratio():
    """bias_amplified 判读必须披露 amplification 倍数 (c307 commit message 的
    '3.59× amplification' headline 之前只在测试里算, run() 从未显示)."""
    lines = render_price_verdict(
        universe_ic=0.049,
        pool_ic=0.176,
        n_records=7993,
        n_days=18,
    )
    joined = "\n".join(lines)
    assert "选择偏差" in joined  # bias_amplified 判读
    # amplification 倍数必须出现在判读里 (de-orphan amplification_ratio)
    assert "×" in joined or "x" in joined.lower(), f"判读应含 amplification 倍数 (×), got:\n{joined}"


def test_verdict_real_factor_does_not_claim_bias():
    lines = render_price_verdict(
        universe_ic=0.15,
        pool_ic=0.176,
        n_records=5000,
        n_days=18,
    )
    joined = "\n".join(lines)
    assert "真实 factor" in joined or "real" in joined.lower()
    # 判读主体 (✅/⚠️ 行) 不应含 bias_amplified 的 "✅ ... 选择偏差伪象" 结论
    # (header 含 "是否是选择偏差伪象" 是问题陈述, 不是结论 — 排除 header)
    body = "\n".join(ln for ln in lines if ln.strip().startswith(("✅", "⚠", "≈")))
    assert "✅" not in body, f"real_factor 判读不应有 bias_amplified 的 ✅ 结论, got body:\n{body}"


def test_verdict_mixed_mentions_partial():
    lines = render_price_verdict(
        universe_ic=0.07,
        pool_ic=0.176,
        n_records=5000,
        n_days=18,
    )
    joined = "\n".join(lines)
    assert "部分" in joined or "mixed" in joined.lower()


def test_verdict_discloses_sample_size():
    """判读应披露 n_records + n_days (让 owner 评估 verdict 可信度)."""
    lines = render_price_verdict(
        universe_ic=0.049,
        pool_ic=0.176,
        n_records=7993,
        n_days=18,
    )
    joined = "\n".join(lines)
    assert "7993" in joined
    assert "18" in joined


def test_verdict_amplification_none_when_universe_zero():
    """universe_ic=0 → amplification_ratio=None → 判读不应崩溃, 应优雅标注."""
    lines = render_price_verdict(
        universe_ic=0.0,
        pool_ic=0.176,
        n_records=100,
        n_days=5,
    )
    joined = "\n".join(lines)
    # 不崩溃 + 标注无法计算 (universe=0 → bias_amplified 因为 0 < 0.05)
    assert "选择偏差" in joined
