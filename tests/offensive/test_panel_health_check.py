"""Tests for the read-only setup-output panel health check."""

from __future__ import annotations

import math

from scripts.panel_health_check import (
    _cohens_d,
    _returns,
    _verdict,
    check_horizon,
    load_panel,
    panel_health_oneline,
)


def _row(eligible: bool, horizon: int, value) -> dict:
    return {"plan_eligible": eligible, f"return_t{horizon}": value}


def _rows(eligible_vals: list[float], filtered_vals: list[float], horizon: int = 1) -> list[dict]:
    return [_row(True, horizon, v) for v in eligible_vals] + [_row(False, horizon, v) for v in filtered_vals]


def test_untestable_below_min_n() -> None:
    rows = _rows([3.0, 4.0], [-1.0, -2.0])  # total=4
    block, verdict = check_horizon(rows, 1, min_n=30, min_group=5)
    assert verdict is None
    assert "样本不足" in block


def test_untestable_when_one_group_too_small() -> None:
    rows = _rows([3.0] * 12, [-1.0, -2.0], horizon=1)  # total=14 but filtered=2
    block, verdict = check_horizon(rows, 1, min_n=10, min_group=5)
    assert verdict is None
    assert "某组样本过小" in block


def test_eligible_significantly_better_reports_alpha() -> None:
    elig = [3.0, 4.0, 5.0, 3.5, 4.5, 5.5, 3.2, 4.2]
    filt = [-2.0, -1.0, 0.0, -1.5, -0.5, -2.5, -1.2, -0.8]
    block, verdict = check_horizon(_rows(elig, filt), 1, min_n=10, min_group=5)
    assert verdict is True
    assert "✅" in block
    assert "Welch t-test" in block


def test_overlapping_distributions_not_significant() -> None:
    same = [1.0, -1.0, 2.0, -2.0, 0.5, -0.5, 1.5, -1.5]
    block, verdict = check_horizon(_rows(same, list(same)), 1, min_n=10, min_group=5)
    assert verdict is False
    assert "◻️" in block


def test_reverse_signal_flags_harm() -> None:
    elig = [-2.0, -1.0, 0.0, -1.5, -0.5, -2.5, -1.2, -0.8]
    filt = [3.0, 4.0, 5.0, 3.5, 4.5, 5.5, 3.2, 4.2]
    block, verdict = check_horizon(_rows(elig, filt), 1, min_n=10, min_group=5)
    assert verdict is False
    assert "反向" in block


def test_returns_is_nan_safe() -> None:
    rows = [
        _row(True, 1, 5.0),
        _row(True, 1, None),
        _row(True, 1, "not-a-number"),
        _row(True, 1, float("inf")),
        _row(False, 1, -1.0),
    ]
    assert _returns(rows, 1, eligible=True) == [5.0]
    assert _returns(rows, 1, eligible=False) == [-1.0]


def test_load_panel_missing_and_malformed(tmp_path) -> None:
    assert load_panel(tmp_path / "nope.jsonl") == []
    p = tmp_path / "panel.jsonl"
    p.write_text('{"a": 1}\n\n{bad json}\n{"b": 2}\n', encoding="utf-8")
    assert load_panel(p) == [{"a": 1}, {"b": 2}]


def test_verdict_thresholds() -> None:
    assert "✅" in _verdict(0.01, +2.0)
    assert "反向" in _verdict(0.01, -2.0)
    assert "◻️" in _verdict(0.20, +2.0)


def test_cohens_d_sign_and_small_group() -> None:
    assert _cohens_d([3.0, 4.0, 5.0], [-1.0, -2.0, -3.0]) > 0
    assert math.isnan(_cohens_d([1.0], [2.0]))  # n<2 in a group -> NaN


def test_oneline_empty_panel(tmp_path) -> None:
    assert panel_health_oneline(tmp_path / "nope.jsonl") == "面板为空"


def test_oneline_below_threshold(tmp_path) -> None:
    import json

    rows = _rows([3.0, 4.0], [-1.0, -2.0])  # total=4
    p = tmp_path / "panel.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    out = panel_health_oneline(p, min_n=30, min_group=5)
    assert "未达检验门槛" in out
    assert "已实现" in out


def test_oneline_reports_alpha(tmp_path) -> None:
    import json

    elig = [3.0, 4.0, 5.0, 3.5, 4.5, 5.5, 3.2, 4.2]
    filt = [-2.0, -1.0, 0.0, -1.5, -0.5, -2.5, -1.2, -0.8]
    rows = [dict(r, realized=True) for r in _rows(elig, filt)]
    p = tmp_path / "panel.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    out = panel_health_oneline(p, min_n=10, min_group=5)
    assert "✅" in out
    assert "T+1" in out


# ---------------------------------------------------------------------------
# 数据护栏降级分层 (2026-08-16): block_reason 为 "readiness degraded: ..." 的票
# 未跑完整策略判断, 混入对照会把基础设施事件冒充策略证据 (真实 panel 曾因此
# 产出 p<0.001 的「全过滤挑 alpha」假阳性 — 257/295 filtered 来自单日
# industry_data_missing 事件, 剔除后 T+3/T+5/T+10 全部不显著).
# ---------------------------------------------------------------------------

def _deg_row(horizon: int, value) -> dict:
    return {
        "plan_eligible": False,
        f"return_t{horizon}": value,
        "degraded": True,
        "block_reason": "readiness degraded: industry_data_missing",
    }


def test_data_degraded_pollution_no_longer_fakes_alpha() -> None:
    """eligible ≈ 策略过滤 (无差异) + 大量数据降级票收益极差 → 主检验必须不显著."""
    # 旧口径 (全部非 eligible 混为一组) 下 filtered 均值被降级票拉到深负, Welch 显著.
    elig = [0.5, 1.0, 1.5, 0.8, 1.2, 0.9, 1.1, 0.7]
    strat = [0.4, 0.9, 1.6, 0.7, 1.3, 0.8, 1.2, 1.0]  # 与 eligible 同分布
    deg = [-9.0, -12.0, -15.0, -8.0, -11.0, -14.0, -10.0, -13.0]
    rows = [_row(True, 1, v) for v in elig]
    rows += [_row(False, 1, v) for v in strat]
    rows += [_deg_row(1, v) for v in deg]
    block, verdict = check_horizon(rows, 1, min_n=10, min_group=5)
    assert verdict is False, "数据降级票不得把同分布对照污染成显著 alpha"
    assert "◻️" in block
    # 披露: 降级层规模必须可见
    assert "数据护栏降级" in block
    assert "8" in block


def test_strategy_alpha_still_detected_after_stratification() -> None:
    """保真: 策略过滤组真实显著更差时分层后仍能检出 alpha (无降级票)."""
    elig = [3.0, 4.0, 5.0, 3.5, 4.5, 5.5, 3.2, 4.2]
    strat = [0.0, 0.5, -0.5, 0.2, 0.8, -0.2, 0.4, 0.1]  # 显著低于 eligible
    deg = [-9.0, -12.0, -15.0, -8.0, -11.0, -14.0, -10.0, -13.0]
    rows = [_row(True, 1, v) for v in elig]
    rows += [_row(False, 1, v) for v in strat]
    rows += [_deg_row(1, v) for v in deg]
    block, verdict = check_horizon(rows, 1, min_n=10, min_group=5)
    assert verdict is True, "真实策略差异不得被分层吞掉"
    assert "✅" in block


def test_strategy_alpha_detected_with_degraded_layer_alongside() -> None:
    """eligible 显著优于策略过滤 (即便有降级票在场) → 主检验仍显著且降级层照常披露."""
    elig = [3.0, 4.0, 5.0, 3.5, 4.5, 5.5, 3.2, 4.2]
    strat = [0.0, 0.5, -0.5, 0.2, 0.8, -0.2, 0.4, 0.1]
    rows = [_row(True, 1, v) for v in elig] + [_row(False, 1, v) for v in strat]
    rows += [_deg_row(1, v) for v in (-9.0, -12.0, -15.0, -8.0, -11.0, -14.0)]
    block, verdict = check_horizon(rows, 1, min_n=10, min_group=5)
    assert verdict is True
    assert "数据护栏降级" in block


def test_degraded_only_filtered_group_reports_untestable_honestly() -> None:
    """filtered 全是降级票 (无策略对照) → 主检验不可判, 不得拿降级票充当对照."""
    elig = [3.0, 4.0, 5.0, 3.5, 4.5]
    rows = [_row(True, 1, v) for v in elig]
    rows += [_deg_row(1, v) for v in (-9.0, -12.0, -15.0, -8.0, -11.0)]
    block, verdict = check_horizon(rows, 1, min_n=6, min_group=5)
    assert verdict is None
    assert "某组样本过小" in block or "样本不足" in block


def test_degraded_flag_used_when_block_reason_missing() -> None:
    """结构化 degraded=True 单独存在也归入降级层 (不依赖字符串)."""
    row = {"plan_eligible": False, "return_t1": -9.0, "degraded": True}
    rows = [_row(True, 1, 1.0)] * 6 + [_row(False, 1, 1.1)] * 6 + [row] * 6
    block, verdict = check_horizon(rows, 1, min_n=12, min_group=5)
    assert verdict is False  # eligible 与策略过滤同分布
    assert "数据护栏降级" in block


def test_panel_health_status_reports_n_degraded() -> None:
    import json

    elig = [3.0, 4.0, 5.0, 3.5, 4.5, 5.5]
    strat = [0.0, 0.5, -0.5, 0.2, 0.8, -0.2]
    rows = [dict(_row(True, 1, v), realized=True) for v in elig]
    rows += [dict(_row(False, 1, v), realized=True) for v in strat]
    rows += [dict(_deg_row(1, v), realized=True) for v in (-9.0, -12.0, -15.0, -8.0)]
    p = tmp_panel = __import__("pathlib").Path(__import__("tempfile").mkdtemp()) / "panel.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    status = __import__("scripts.panel_health_check", fromlist=["panel_health_status"]).panel_health_status(p, min_n=10, min_group=5)
    h1 = status["horizons"]["1"]
    assert h1["testable"] is True
    assert h1["n_degraded"] == 4
    assert h1["n_filt"] == 6  # 策略过滤组, 不含降级票


def test_oneline_discloses_degraded_layer(tmp_path) -> None:
    import json

    elig = [3.0, 4.0, 5.0, 3.5, 4.5, 5.5]
    strat = [0.0, 0.5, -0.5, 0.2, 0.8, -0.2]
    rows = [dict(_row(True, 1, v), realized=True) for v in elig]
    rows += [dict(_row(False, 1, v), realized=True) for v in strat]
    rows += [dict(_deg_row(1, v), realized=True) for v in (-9.0, -12.0, -15.0)]
    p = tmp_path / "panel.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    out = panel_health_oneline(p, min_n=10, min_group=5)
    assert "降级" in out
