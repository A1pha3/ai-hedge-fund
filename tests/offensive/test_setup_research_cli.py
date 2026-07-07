"""Phase 0 研究 CLI 测试 — IS/OOS 切分 + 准入判定 + 报告渲染。"""

from __future__ import annotations

import pandas as pd

from scripts.setup_research import (
    split_is_oos,
    evaluate_setup,
    render_report,
    is_setup_qualified,
)
from src.screening.offensive.setups.btst_breakout import BtstBreakoutSetup


def test_split_is_oos_by_date():
    dates = ["20240101", "20240601", "20250101", "20250601", "20260101"]
    is_dates, oos_dates = split_is_oos(dates, split_date="20250101")
    assert is_dates == ["20240101", "20240601"]
    assert oos_dates == ["20250101", "20250601", "20260101"]


def test_is_setup_qualified_passes_strong_setup():
    """convexity 2.0 + winrate 0.6 + n 60 + ic 0.08 → qualified。"""
    from src.screening.offensive.statistics import Distribution

    dist = Distribution(n=60, winrate=0.6, avg_gain=0.2, avg_loss=-0.05, convexity_ratio=3.0, expected_return=0.1, ci_low=0.05, ci_high=0.15, ic=0.08)
    assert is_setup_qualified(dist) is True


def test_is_setup_qualified_fails_low_n():
    from src.screening.offensive.statistics import Distribution

    dist = Distribution(n=40, winrate=0.6, avg_gain=0.2, avg_loss=-0.05, convexity_ratio=3.0, expected_return=0.1, ci_low=0.05, ci_high=0.15, ic=0.08)
    assert is_setup_qualified(dist) is False  # n < 50


def test_is_setup_qualified_fails_low_convexity():
    from src.screening.offensive.statistics import Distribution

    dist = Distribution(n=60, winrate=0.55, avg_gain=0.1, avg_loss=-0.1, convexity_ratio=1.2, expected_return=0.005, ci_low=-0.02, ci_high=0.03, ic=0.06)
    assert is_setup_qualified(dist) is False  # convexity < 1.5


def test_render_report_contains_verdict_and_stats():
    """报告含 PASS/FAIL verdict + 分布数字 + IS vs OOS 对比。"""
    from src.screening.offensive.distribution_builder import TermStructureDistribution
    from src.screening.offensive.statistics import Distribution

    dist_is = Distribution(n=60, winrate=0.6, avg_gain=0.2, avg_loss=-0.05, convexity_ratio=3.0, expected_return=0.1, ci_low=0.05, ci_high=0.15, ic=0.08)
    dist_oos = Distribution(n=55, winrate=0.55, avg_gain=0.15, avg_loss=-0.06, convexity_ratio=2.5, expected_return=0.07, ci_low=0.02, ci_high=0.12, ic=0.06)
    eval_result = {
        "setup_name": "btst_breakout",
        "natural_horizon": 3,
        "is": TermStructureDistribution("btst_breakout", {3: dist_is}, 3, "ALL", "IS", 60),
        "oos": TermStructureDistribution("btst_breakout", {3: dist_oos}, 3, "ALL", "OOS", 55),
        "qualified_is": True,
        "qualified_oos": True,
        "verdict": "PASS",
    }
    report = render_report(eval_result)
    assert "PASS" in report
    assert "btst_breakout" in report
    assert "IS" in report and "OOS" in report
    assert "60" in report  # n


def test_evaluate_setup_integration():
    """端到端: evaluate_setup 跑 setup 在样本上, 返回 IS/OOS/ALL 分布。"""
    tickers = ["000001", "000002", "000003"]
    prices_by_ticker = {}
    for t in tickers:
        dates = pd.bdate_range("2024-01-01", periods=15)
        closes = [10.0 + i * 0.1 for i in range(15)]
        closes[5] = closes[4] * 1.10  # 第 5 日涨停
        pct = [0.0] * 5 + [10.0] + [0.0] * 9
        prices_by_ticker[t] = pd.DataFrame(
            {
                "date": dates,
                "close": closes,
                "open": closes,
                "high": closes,
                "low": closes,
                "pct_change": pct,
            }
        )

    from src.screening.offensive.data.fund_flow_store import FundFlowRecord

    fund_flow = {}
    for t in tickers:
        trigger_date = prices_by_ticker[t].iloc[5]["date"].strftime("%Y%m%d")
        fund_flow[t] = [
            FundFlowRecord(ticker=t, date=trigger_date, close=closes[5], pct_change=10.0, main_net_inflow=5_000_000, main_net_pct=8.0),
        ]

    trade_dates = [prices_by_ticker[t].iloc[5]["date"].strftime("%Y%m%d") for t in tickers]

    result = evaluate_setup(
        setup=BtstBreakoutSetup(),
        tickers=tickers,
        trade_dates=trade_dates,
        prices_by_ticker=prices_by_ticker,
        fund_flow_by_ticker=fund_flow,
        industry_pct_by_date={d: 3.0 for d in trade_dates},
        regimes_by_date={d: "normal" for d in trade_dates},
    )
    assert "is" in result and "oos" in result
    assert result["setup_name"] == "btst_breakout"


# ---------------------------------------------------------------------------
# evaluate_setups — 批量 + FDR 校正 (v2 §C.5 反 p-hacking)
# ---------------------------------------------------------------------------


def _fake_eval_result(setup_name: str, is_returns, oos_returns):
    """构造 evaluate_setup 的返回结构, 含 returns (供 FDR 算 p-value)."""
    from src.screening.offensive.statistics import compute_distribution
    from src.screening.offensive.distribution_builder import TermStructureDistribution
    import numpy as np

    is_returns = np.asarray(is_returns, dtype=float)
    oos_returns = np.asarray(oos_returns, dtype=float)
    is_dist = compute_distribution(is_returns)
    oos_dist = compute_distribution(oos_returns)
    return {
        "setup_name": setup_name,
        "natural_horizon": 3,
        "is": TermStructureDistribution(setup_name, {3: is_dist}, 3, "ALL", "IS", len(is_returns)),
        "oos": TermStructureDistribution(setup_name, {3: oos_dist}, 3, "ALL", "OOS", len(oos_returns)),
        "qualified_is": is_setup_qualified(is_dist),
        "qualified_oos": is_setup_qualified(oos_dist),
        "verdict": "PASS" if (is_setup_qualified(is_dist) and is_setup_qualified(oos_dist)) else "FAIL",
        "is_returns": is_returns,
        "oos_returns": oos_returns,
        "degraded_count": 0,
        "degraded_ratio": 0.0,
    }


def test_evaluate_setups_applies_fdr_two_strong_pass(monkeypatch):
    """2 个强 setup (p 极小) + 1 个噪声 → FDR 后 2 个显著, phase0 PASS.

    文档 §3.3: FDR 校正后 ≥2 个达标才进 Phase 1.
    """
    import numpy as np
    from scripts import setup_research as sr

    rng = np.random.default_rng(42)
    strong = rng.normal(0.05, 0.10, 200)  # mean +5%, 极显著
    weak = rng.normal(0.0, 0.10, 200)  # mean 0, 噪声

    results = [
        _fake_eval_result("strong_a", strong, strong),
        _fake_eval_result("strong_b", strong, strong),
        _fake_eval_result("noise_c", weak, weak),
    ]
    monkeypatch.setattr(sr, "evaluate_setup", lambda setup, **kw: results.pop(0))

    out = sr.evaluate_setups(
        setups=["dummy1", "dummy2", "dummy3"],
        tickers=[], trade_dates=[], prices_by_ticker={},
        fund_flow_by_ticker={}, industry_pct_by_date={}, regimes_by_date={},
    )
    assert out["n_fdr_significant"] == 2, f"应 2 个 FDR 显著, got {out['n_fdr_significant']}"
    assert out["phase0_verdict"] == "PASS"
    # 噪声 setup 的 fdr_significant 应为 False
    noise_entry = next(s for s in out["setups"] if s["setup_name"] == "noise_c")
    assert noise_entry["fdr_significant"] is False
    assert noise_entry["p_value"] > 0.05


def test_evaluate_setups_one_significant_fails_phase0(monkeypatch):
    """1 个显著 + 2 个噪声 → n_fdr_significant=1 < 2 → phase0 FAIL (文档 STOP)."""
    import numpy as np
    from scripts import setup_research as sr

    rng = np.random.default_rng(42)
    strong = rng.normal(0.05, 0.10, 200)
    weak = rng.normal(0.0, 0.10, 200)

    results = [
        _fake_eval_result("strong_a", strong, strong),
        _fake_eval_result("noise_b", weak, weak),
        _fake_eval_result("noise_c", weak, weak),
    ]
    monkeypatch.setattr(sr, "evaluate_setup", lambda setup, **kw: results.pop(0))

    out = sr.evaluate_setups(
        setups=["d1", "d2", "d3"],
        tickers=[], trade_dates=[], prices_by_ticker={},
        fund_flow_by_ticker={}, industry_pct_by_date={}, regimes_by_date={},
    )
    assert out["n_fdr_significant"] == 1
    assert out["phase0_verdict"] == "FAIL", "仅 1 个 FDR 显著 < 2, 应 STOP"


def test_evaluate_setups_all_noise_fails(monkeypatch):
    """全噪声 → n_fdr_significant=0 → FAIL."""
    import numpy as np
    from scripts import setup_research as sr

    rng = np.random.default_rng(42)
    weak = rng.normal(0.0, 0.10, 200)

    results = [_fake_eval_result(f"noise_{i}", weak, weak) for i in range(3)]
    monkeypatch.setattr(sr, "evaluate_setup", lambda setup, **kw: results.pop(0))

    out = sr.evaluate_setups(
        setups=["d1", "d2", "d3"],
        tickers=[], trade_dates=[], prices_by_ticker={},
        fund_flow_by_ticker={}, industry_pct_by_date={}, regimes_by_date={},
    )
    assert out["n_fdr_significant"] == 0
    assert out["phase0_verdict"] == "FAIL"


def test_evaluate_setups_single_setup_fdr_passthrough(monkeypatch):
    """单 setup → FDR 无校正负担 (n=1), 但管线一致; phase0 仍需 ≥2 故 FAIL.

    n=1 的 FDR q=p (无校正), 但文档 §3.3 要求 ≥2 个达标, 故单 setup 必 FAIL.
    这防止"只测一个 setup 就宣称 Phase 0 通过"的 p-hacking.
    """
    import numpy as np
    from scripts import setup_research as sr

    rng = np.random.default_rng(42)
    strong = rng.normal(0.05, 0.10, 200)
    monkeypatch.setattr(sr, "evaluate_setup", lambda setup, **kw: _fake_eval_result("solo", strong, strong))

    out = sr.evaluate_setups(
        setups=["solo"],
        tickers=[], trade_dates=[], prices_by_ticker={},
        fund_flow_by_ticker={}, industry_pct_by_date={}, regimes_by_date={},
    )
    assert len(out["setups"]) == 1
    assert out["setups"][0]["fdr_significant"] is True  # 单检验 FDR=q=p 显著
    assert out["n_fdr_significant"] == 1
    assert out["phase0_verdict"] == "FAIL", "单 setup 即使显著也 < 2, Phase 0 不通过"


# ---------------------------------------------------------------------------
# render_phase0_report — FDR 披露渲染
# ---------------------------------------------------------------------------


def test_render_phase0_report_shows_fdr_table(monkeypatch):
    """render_phase0_report 必须披露每个 setup 的 p-value/q-value/FDR 状态 + phase0 verdict."""
    import numpy as np
    from scripts import setup_research as sr

    rng = np.random.default_rng(42)
    strong = rng.normal(0.05, 0.10, 200)
    weak = rng.normal(0.0, 0.10, 200)
    results = [
        _fake_eval_result("strong_a", strong, strong),
        _fake_eval_result("strong_b", strong, strong),
        _fake_eval_result("noise_c", weak, weak),
    ]
    monkeypatch.setattr(sr, "evaluate_setup", lambda setup, **kw: results.pop(0))
    out = sr.evaluate_setups(
        setups=["d1", "d2", "d3"],
        tickers=[], trade_dates=[], prices_by_ticker={},
        fund_flow_by_ticker={}, industry_pct_by_date={}, regimes_by_date={},
    )
    report = sr.render_phase0_report(out)
    assert "Phase 0" in report
    assert "FDR" in report
    assert "PASS" in report  # 2 个显著 → PASS
    assert "strong_a" in report and "strong_b" in report and "noise_c" in report
    # p-value 和 q-value 必须可见
    assert "p=" in report or "p-value" in report.lower()
    assert "q=" in report or "q-value" in report.lower()
    # STOP 条件检查段
    assert "STOP" in report or "停止" in report


def test_render_phase0_report_fail_shows_stop(monkeypatch):
    """phase0 FAIL 时报告必须明确显示 STOP 条件触发."""
    import numpy as np
    from scripts import setup_research as sr

    rng = np.random.default_rng(42)
    weak = rng.normal(0.0, 0.10, 200)
    results = [_fake_eval_result(f"noise_{i}", weak, weak) for i in range(3)]
    monkeypatch.setattr(sr, "evaluate_setup", lambda setup, **kw: results.pop(0))
    out = sr.evaluate_setups(
        setups=["d1", "d2", "d3"],
        tickers=[], trade_dates=[], prices_by_ticker={},
        fund_flow_by_ticker={}, industry_pct_by_date={}, regimes_by_date={},
    )
    report = sr.render_phase0_report(out)
    assert "FAIL" in report
    assert "0" in report  # n_fdr_significant=0
