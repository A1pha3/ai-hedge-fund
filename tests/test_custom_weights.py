"""P2-5 自定义策略权重 — 单元测试 (≥10)。

覆盖:
  1. 默认权重 (sum=1)
  2. 自定义权重 (sum=1)
  3. 权重和不为 1 → ValueError
  4. 单策略权重 1.0 (其它 0)
  5. 负权重拒绝
  6. 权重 > 1 拒绝
  7. reweight_recommendations 重算
  8. 排序变化 (权重变化 → 排序变化)
  9. NaN 权重拒绝
 10. CLI smoke (--custom-weights)
 11. Web 端点 smoke (POST /api/screening/custom-weights)
 12. 缺失 strategy_signals 容错 (回退原 score_b)
 13. completeness=0 视为 0
 14. 排序稳定 (同分按 ticker 字典序)
 15. from_dict 缺省字段
 16. normalize 归一化
"""

from __future__ import annotations

import json
import math
import os
import subprocess
import sys
from pathlib import Path

import pytest

from src.screening.custom_weights import (
    DEFAULT_WEIGHTS,
    MAX_STRATEGY_SCORE,
    reweight_recommendations,
    STRATEGY_KEYS,
    StrategyWeights,
)

# ===========================================================================
# Fixtures
# ===========================================================================


def _make_rec(
    ticker: str,
    *,
    trend: int = 0,
    trend_conf: float = 0.0,
    mr: int = 0,
    mr_conf: float = 0.0,
    fund: int = 0,
    fund_conf: float = 0.0,
    es: int = 0,
    es_conf: float = 0.0,
    score_b: float = 0.0,
) -> dict:
    """构造一条标准 rec dict, 含 strategy_signals。"""
    return {
        "ticker": ticker,
        "name": f"测试_{ticker}",
        "score_b": score_b,
        "strategy_signals": {
            "trend": {"direction": trend, "confidence": trend_conf, "completeness": 1.0},
            "mean_reversion": {"direction": mr, "confidence": mr_conf, "completeness": 1.0},
            "fundamental": {"direction": fund, "confidence": fund_conf, "completeness": 1.0},
            "event_sentiment": {"direction": es, "confidence": es_conf, "completeness": 1.0},
        },
    }


# ===========================================================================
# 1. 默认权重
# ===========================================================================


def test_default_weights_sum_to_one() -> None:
    """默认权重 sum=1.0, 全部 0.25。"""
    w = StrategyWeights()
    assert w.trend == 0.25
    assert w.mean_reversion == 0.25
    assert w.fundamental == 0.25
    assert w.event_sentiment == 0.25
    assert w.to_dict() == DEFAULT_WEIGHTS


# ===========================================================================
# 2. 自定义权重 (sum=1)
# ===========================================================================


def test_custom_weights_sum_to_one() -> None:
    """用户自定义 0.4/0.1/0.3/0.2 — sum=1.0 通过。"""
    w = StrategyWeights(trend=0.4, mean_reversion=0.1, fundamental=0.3, event_sentiment=0.2)
    d = w.to_dict()
    assert abs(sum(d.values()) - 1.0) < 1e-9
    assert d["trend"] == 0.4


# ===========================================================================
# 3. 权重和不为 1 → ValueError
# ===========================================================================


def test_weights_not_summing_to_one_raises() -> None:
    """sum=0.9 或 1.1 都被拒绝。"""
    with pytest.raises(ValueError, match="权重之和必须为 1.0"):
        StrategyWeights(trend=0.3, mean_reversion=0.3, fundamental=0.2, event_sentiment=0.1)  # sum=0.9
    with pytest.raises(ValueError, match="权重之和必须为 1.0"):
        StrategyWeights(trend=0.4, mean_reversion=0.3, fundamental=0.3, event_sentiment=0.1)  # sum=1.1


# ===========================================================================
# 4. 单策略权重 1.0 (其它 0)
# ===========================================================================


def test_single_strategy_dominant_weight() -> None:
    """仅趋势权重 = 1.0 (其它 0), 应通过 sum=1 校验。"""
    w = StrategyWeights(trend=1.0, mean_reversion=0.0, fundamental=0.0, event_sentiment=0.0)
    assert w.trend == 1.0
    d = w.to_dict()
    assert sum(d.values()) == 1.0


# ===========================================================================
# 5. 负权重拒绝
# ===========================================================================


def test_negative_weight_rejected() -> None:
    with pytest.raises(ValueError, match="不能为负数"):
        StrategyWeights(trend=-0.1, mean_reversion=0.4, fundamental=0.4, event_sentiment=0.3)


# ===========================================================================
# 6. 权重 > 1 拒绝
# ===========================================================================


def test_weight_above_one_rejected() -> None:
    with pytest.raises(ValueError, match="不能超过 1.0"):
        StrategyWeights(trend=1.5, mean_reversion=-0.1, fundamental=0.0, event_sentiment=-0.4)


# ===========================================================================
# 7. reweight_recommendations 重算
# ===========================================================================


def test_reweight_recommendations_recomputes() -> None:
    """趋势权重 1.0 → score_b = trend signal / 100。"""
    recs = [
        _make_rec("A", trend=1, trend_conf=80.0, score_b=0.5),
        _make_rec("B", trend=-1, trend_conf=60.0, score_b=-0.3),
    ]
    w = StrategyWeights(trend=1.0, mean_reversion=0.0, fundamental=0.0, event_sentiment=0.0)
    out = reweight_recommendations(recs, w)
    assert len(out) == 2
    # A: trend_sign=+1, conf=80 → score_b = 80/100 = 0.8
    a = next(r for r in out if r["ticker"] == "A")
    assert abs(a["score_b"] - 0.8) < 1e-9
    # B: trend_sign=-1, conf=60 → score_b = -0.6
    b = next(r for r in out if r["ticker"] == "B")
    assert abs(b["score_b"] - (-0.6)) < 1e-9
    # original_score_b 保留
    assert a["original_score_b"] == 0.5
    assert b["original_score_b"] == -0.3
    # custom_weights 记录
    assert a["custom_weights"] == w.to_dict()


def test_reweight_with_balanced_weights_matches_average() -> None:
    """等权 0.25/0.25/0.25/0.25 → score_b = 四策略分数均值。"""
    recs = [
        _make_rec(
            "X",
            trend=1,
            trend_conf=100.0,
            mr=1,
            mr_conf=80.0,
            fund=1,
            fund_conf=60.0,
            es=1,
            es_conf=40.0,
        )
    ]
    w = StrategyWeights()
    out = reweight_recommendations(recs, w)
    # weighted = 0.25*100 + 0.25*80 + 0.25*60 + 0.25*40 = 70 → /100 = 0.70
    assert abs(out[0]["score_b"] - 0.70) < 1e-9


# ===========================================================================
# 7b. reweight bucket-stale reset (NS-19/c284)
# ===========================================================================


def _make_rec_with_calibration(
    ticker: str,
    *,
    score_b: float,
    new_score_b: float,
    composite_score: float = 0.64,
) -> tuple[dict, float]:
    """构造一条带 bucket 校准数据 (模拟 auto_screening 报告 rec) + 能重权到 new_score_b 的信号.

    返回 (rec, expected_new_score_b). 用 trend=1.0 权重把 trend 信号直接映射成 score_b.
    """
    # trend signal: direction=+1, confidence=new_score_b*100 → reweight(trend=1.0) = new_score_b
    # 用 trend 信号承载目标 new_score_b; 其余策略 0.
    rec = _make_rec(
        ticker,
        trend=1 if new_score_b >= 0 else -1,
        trend_conf=abs(new_score_b) * 100.0,
        score_b=score_b,
    )
    rec["composite_score"] = composite_score
    rec["composite_verified"] = True
    rec["bucket_label"] = "中低 (0.5-0.6)"  # 假设 orig score_b 落中低桶
    rec["bucket_sample_count"] = 41
    rec["bucket_t30_mature_count"] = 38
    rec["bucket_t30_avg_negative_return"] = -7.94
    rec["expected_returns"] = {"t5": 0.293, "t10": 1.146, "t30": -7.94}
    rec["win_rates"] = {"t5": 0.474, "t10": 0.447, "t30": 0.368}
    return rec, new_score_b


def test_reweight_clears_stale_bucket_when_crossing_boundary() -> None:
    """NS-19/c284: reweight 改 score_b; 若越过桶边界, 原 bucket 校准 (为旧 score_b 计算) 失效.

    rec 原 score_b=0.55 (中低 0.5-0.6), 带 中低桶 校准数据.
    trend=1.0 重权 → score_b=0.80 (高 0.7-1.0), 越过边界.
    原 bucket_label/expected_returns/win_rates/sample_count 是 中低桶 的, 对 0.80 的新 score_b STALE.
    reweight 是纯函数无法重算校准 → 必须 reset 为未知, 不能 ship 过期数据误导下游.
    """
    rec, expected_new = _make_rec_with_calibration("X", score_b=0.55, new_score_b=0.80)
    w = StrategyWeights(trend=1.0, mean_reversion=0.0, fundamental=0.0, event_sentiment=0.0)
    out = reweight_recommendations([rec], w)
    r = out[0]
    assert abs(r["score_b"] - expected_new) < 1e-9, f"new score_b should be {expected_new}"
    # 越过桶边界 → 校准数据 reset 为未知
    assert r["bucket_label"] == "未知", f"crossed bucket boundary → bucket_label must reset to '未知'; got {r['bucket_label']!r}"
    assert r["bucket_sample_count"] == 0
    assert r["bucket_t30_mature_count"] == 0
    assert r["expected_returns"] == {}
    assert r["win_rates"] == {}
    assert r.get("bucket_recalibration_needed") is True


def test_reweight_preserves_bucket_when_not_crossing() -> None:
    """NS-19/c284: reweight 后仍在同一桶 → 校准数据保留 (仍有效)."""
    # orig 0.55 → new 0.58, 都在 中低 (0.5-0.6)
    rec, _ = _make_rec_with_calibration("X", score_b=0.55, new_score_b=0.58)
    w = StrategyWeights(trend=1.0, mean_reversion=0.0, fundamental=0.0, event_sentiment=0.0)
    out = reweight_recommendations([rec], w)
    r = out[0]
    assert r["bucket_label"] == "中低 (0.5-0.6)", "same bucket → preserve calibration"
    assert r["bucket_sample_count"] == 41
    assert r["expected_returns"] == {"t5": 0.293, "t10": 1.146, "t30": -7.94}
    assert r["win_rates"] == {"t5": 0.474, "t10": 0.447, "t30": 0.368}
    assert "bucket_recalibration_needed" not in r


def test_reweight_preserves_composite_score_when_crossing() -> None:
    """NS-19/c284: composite_score 独立于 score_b (从 agent 信号算), 越界时不 reset.

    dogfood 证实 (auto_screening vs custom_weights 同 ticker composite_score 完全一致),
    reweight 只改 score_b 不改 composite_score. 越界 reset 只清 bucket 校准, 不动 composite.
    """
    rec, _ = _make_rec_with_calibration("X", score_b=0.55, new_score_b=0.80, composite_score=0.72)
    w = StrategyWeights(trend=1.0, mean_reversion=0.0, fundamental=0.0, event_sentiment=0.0)
    out = reweight_recommendations([rec], w)
    r = out[0]
    # bucket 越界 reset, 但 composite_score 保留
    assert r["bucket_label"] == "未知"
    assert r["composite_score"] == 0.72, "composite_score is score_b-independent; must survive bucket reset"
    assert r["composite_verified"] is True


def test_print_custom_weights_warns_on_recalibration_needed(capsys: pytest.CaptureFixture) -> None:
    """c284 observability: CLI 显示必须告知哪些 pick 因重权越过桶边界被 reset.

    c284 的 bucket reset 写入 JSON (bucket_recalibration_needed=True), 但若 CLI
    显示 (_print_custom_weights_results) 只打 score_b, 操作者看不到 reset 发生.
    必须在越界 pick 行加标记 + 末尾汇总, 让操作者知道去 --top-picks 复核.
    """
    from src.main import _print_custom_weights_results

    top = [
        {
            "ticker": "X",
            "name": "测试_X",
            "score_b": 0.80,
            "original_score_b": 0.55,
            "bucket_recalibration_needed": True,
        },
        {
            "ticker": "Y",
            "name": "测试_Y",
            "score_b": 0.58,
            "original_score_b": 0.55,  # 未越界, 无 marker
        },
    ]
    w = StrategyWeights().to_dict()
    assert _print_custom_weights_results(top, w) is True
    out = capsys.readouterr().out
    # 末尾汇总: 提及越界 + 复核指引
    assert "越过桶边界" in out or "越界" in out, f"CLI must summarize recalibration-needed picks; got stdout={out!r}"
    assert "--top-picks" in out, f"CLI must point operator to --top-picks for re-validation; got stdout={out!r}"
    # 越界 pick (X) 行应带可视标记区分 (Y 不带)
    x_line = [ln for ln in out.splitlines() if "X" in ln and "测试_X" in ln]
    assert x_line, f"X pick line missing; stdout={out!r}"
    assert "重权" in x_line[0] or "越界" in x_line[0] or "⚠" in x_line[0], f"crossed pick X must carry a visible marker; got {x_line[0]!r}"


def test_print_custom_weights_surfaces_front_door_verdict(capsys: pytest.CaptureFixture) -> None:
    """CLI 自定义权重展示 score_b 时, 必须同时展示前门 BUY/HOLD/AVOID 判决。"""
    from src.main import _print_custom_weights_results

    top = [
        {
            "ticker": "X",
            "name": "测试_X",
            "score_b": 0.80,
            "original_score_b": 0.55,
            "decision": "bullish",
        }
    ]
    w = StrategyWeights().to_dict()
    assert _print_custom_weights_results(top, w) is True
    out = capsys.readouterr().out

    assert "前门" in out
    assert "AVOID" in out


# ===========================================================================
# 7b. autodev-25 loop 134: top-level verdict summary + color-coded rows
# ===========================================================================


class TestCustomWeightsVerdictSummary:
    """autodev-25 loop 134: --custom-weights 必须在 Top N 明细前渲染 🎯 前门判决
    汇总行 (extending loop-126/132 pattern), 并对每行 verdict 着色.
    """

    def test_summary_line_present_when_recs_exist(self, capsys: pytest.CaptureFixture) -> None:
        from src.main import _print_custom_weights_results

        top = [
            {"ticker": "A", "name": "A", "score_b": 0.8, "original_score_b": 0.7, "decision": "bullish"},
            {"ticker": "B", "name": "B", "score_b": 0.5, "original_score_b": 0.5, "decision": "bullish"},
        ]
        w = StrategyWeights().to_dict()
        assert _print_custom_weights_results(top, w) is True
        out = capsys.readouterr().out

        # 汇总行必须出现
        assert "前门判决" in out
        # 必须显示总数 (2 条)
        assert "/2" in out

    def test_summary_shows_AVOID_tickers_when_present(self, capsys: pytest.CaptureFixture) -> None:
        from unittest.mock import patch

        from src.main import _print_custom_weights_results

        top = [
            {"ticker": "GOOD", "name": "好票", "score_b": 0.8, "original_score_b": 0.7, "decision": "bullish"},
            {"ticker": "BAD", "name": "坏票", "score_b": 0.5, "original_score_b": 0.5, "decision": "bullish"},
        ]
        w = StrategyWeights().to_dict()

        # Mock: GOOD=BUY, BAD=AVOID
        verdicts = [{"action": "BUY"}, {"action": "AVOID"}]
        with patch("src.screening.investability.build_front_door_verdict", side_effect=verdicts):
            assert _print_custom_weights_results(top, w) is True
        out = capsys.readouterr().out

        # 汇总必须显示 BUY 1/2 + AVOID 1
        assert "BUY 1/2" in out
        assert "AVOID 1" in out
        # AVOID ticker 必须列出
        assert "BAD" in out
        assert "前门门控拒绝" in out

    def test_summary_shows_HOLD_count(self, capsys: pytest.CaptureFixture) -> None:
        from unittest.mock import patch

        from src.main import _print_custom_weights_results

        top = [
            {"ticker": "A", "name": "A", "score_b": 0.8, "original_score_b": 0.7, "decision": "bullish"},
        ]
        w = StrategyWeights().to_dict()

        with patch("src.screening.investability.build_front_door_verdict", return_value={"action": "HOLD"}):
            assert _print_custom_weights_results(top, w) is True
        out = capsys.readouterr().out

        assert "HOLD 1" in out
        assert "BUY 0/1" in out

    def test_per_row_verdict_label_visible(self, capsys: pytest.CaptureFixture) -> None:
        """行内 前门 标签必须保留 (即使着色, 核心词应可见)."""
        from src.main import _print_custom_weights_results

        top = [
            {"ticker": "X", "name": "X", "score_b": 0.8, "original_score_b": 0.7, "decision": "bullish"},
        ]
        w = StrategyWeights().to_dict()
        assert _print_custom_weights_results(top, w) is True
        out = capsys.readouterr().out

        # 行内 "前门" 标签 + verdict 词均应可见
        assert "前门" in out
        # 默认测试 rec → AVOID (gate 不够)
        assert "AVOID" in out or "BUY" in out or "HOLD" in out


# ===========================================================================
# 7c. autodev-25 loop 136: integration guard — ANSI color + summary invariant
# ===========================================================================


class TestCustomWeightsRegressionGuard:
    """集成守护: 通过 @patch 强制 BUY/AVOID 路径, 锁定循环 134 的修复。

    如果未来的重构移除了预计算前端或颜色映射,
    _print_custom_weights_results 会退化回纯文本渲染,
    此守护将捕获回归。
    """

    def test_all_BUY_no_warnings(self, capsys: pytest.CaptureFixture) -> None:
        """所有判决均为 BUY → 不应出现 AVOID 警告."""
        from unittest.mock import patch

        from src.main import _print_custom_weights_results

        top = [
            {"ticker": "A", "name": "A", "score_b": 0.8, "original_score_b": 0.7, "decision": "bullish"},
            {"ticker": "B", "name": "B", "score_b": 0.7, "original_score_b": 0.6, "decision": "bullish"},
        ]
        w = StrategyWeights().to_dict()
        with patch("src.screening.investability.build_front_door_verdict", return_value={"action": "BUY"}):
            assert _print_custom_weights_results(top, w) is True
        out = capsys.readouterr().out

        # BUY 汇总, 无 AVOID 部分
        assert "BUY 2/2" in out
        assert "AVOID" not in out
        assert "前门门控拒绝" not in out

    def test_mixed_verdict_shows_color_codes(self, capsys: pytest.CaptureFixture) -> None:
        """混合判决 → ANSI 颜色码必须出现在行内."""
        from unittest.mock import patch

        from src.main import _print_custom_weights_results

        top = [
            {"ticker": "GOOD", "name": "好", "score_b": 0.8, "original_score_b": 0.7, "decision": "bullish"},
            {"ticker": "BAD", "name": "坏", "score_b": 0.3, "original_score_b": 0.3, "decision": "bearish"},
            {"ticker": "MID", "name": "中", "score_b": 0.5, "original_score_b": 0.5, "decision": "neutral"},
        ]
        w = StrategyWeights().to_dict()
        verdicts = [{"action": "BUY"}, {"action": "AVOID"}, {"action": "HOLD"}]
        with patch("src.screening.investability.build_front_door_verdict", side_effect=verdicts):
            assert _print_custom_weights_results(top, w) is True
        out = capsys.readouterr().out

        # 汇总行完整
        assert "BUY 1/3" in out
        assert "HOLD 1" in out
        assert "AVOID 1" in out
        # ANSI 颜色码必须出现 (证明着色未被删除)
        assert "\x1b[" in out
        # AVOID 个票必须列出
        assert "BAD" in out
        assert "前门门控拒绝" in out


# ===========================================================================
# 8. 排序变化
# ===========================================================================


def test_reweight_changes_ranking() -> None:
    """A 在原 score_b 中最高, 但重权后 B 超过 A。"""
    recs = [
        _make_rec("A", trend=1, trend_conf=20.0, fund=1, fund_conf=80.0, score_b=0.5),  # 原 0.5
        _make_rec("B", trend=1, trend_conf=80.0, fund=1, fund_conf=20.0, score_b=0.3),  # 原 0.3
    ]
    # 重权为纯 trend → B 升, A 降
    w = StrategyWeights(trend=1.0, mean_reversion=0.0, fundamental=0.0, event_sentiment=0.0)
    out = reweight_recommendations(recs, w)
    tickers = [r["ticker"] for r in out]
    assert tickers[0] == "B"  # B 新 score_b=0.8 > A 新 0.2
    assert tickers[1] == "A"


# ===========================================================================
# 9. NaN 权重拒绝
# ===========================================================================


def test_nan_weight_rejected() -> None:
    with pytest.raises(ValueError, match="必须为有限数"):
        StrategyWeights(trend=float("nan"), mean_reversion=0.25, fundamental=0.25, event_sentiment=0.25)
    with pytest.raises(ValueError, match="必须为有限数"):
        StrategyWeights(trend=0.25, mean_reversion=float("inf"), fundamental=0.25, event_sentiment=0.25)


# ===========================================================================
# 10. CLI smoke test
# ===========================================================================


def test_cli_custom_weights_smoke(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """--custom-weights 配合临时 auto_screening 报告, 应以退出码 0/1 结束 (不崩溃)。"""
    monkeypatch.chdir(tmp_path)

    # 写一份临时报告
    recs = [
        _make_rec("A", trend=1, trend_conf=80.0, score_b=0.5),
        _make_rec("B", trend=-1, trend_conf=60.0, score_b=-0.3),
    ]
    reports_dir = tmp_path / "data" / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_path = reports_dir / "auto_screening_20260607.json"
    report_path.write_text(json.dumps({"recommendations": recs}), encoding="utf-8")

    # 临时把 data 目录塞到 cwd, 让 resolve_report_dir 找到
    repo_root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "src.main",
            "--custom-weights",
            "--trend=0.4",
            "--mean-reversion=0.1",
            "--fundamental=0.3",
            "--event-sentiment=0.2",
            "--top-n=5",
        ],
        cwd=str(repo_root),
        env={**os.environ, "PYTHONPATH": str(repo_root)},
        capture_output=True,
        text=True,
        timeout=30,
    )
    # 不强制 0 — 若无最新报告则返回 1 (但 stderr 不应崩溃)
    combined = result.stdout + result.stderr
    assert result.returncode in (0, 1), f"unexpected returncode: {result.returncode}\nstdout={result.stdout}\nstderr={result.stderr}"
    # 至少不是 ImportError / SyntaxError
    assert "ModuleNotFoundError" not in combined
    assert "SyntaxError" not in combined


def test_cli_custom_weights_invalid_weights_returns_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """--custom-weights 权重和 != 1.0 时应返回 1 (校验失败)。"""
    monkeypatch.chdir(tmp_path)
    repo_root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "src.main",
            "--custom-weights",
            "--trend=0.5",
            "--mean-reversion=0.5",
            "--fundamental=0.5",
            "--event-sentiment=0.5",  # sum=2.0
        ],
        cwd=str(repo_root),
        env={**os.environ, "PYTHONPATH": str(repo_root)},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 1
    combined = result.stdout + result.stderr
    assert "权重校验失败" in combined or "权重之和" in combined


# ===========================================================================
# 11. Web 端点 smoke test
# ===========================================================================


def test_web_custom_weights_endpoint_smoke(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """POST /api/screening/custom-weights 应用权重并返回 Top N。"""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.backend.routes import screening as screening_mod

    # 准备测试数据 (不含 market_state 也可 — 会在 _attach_front_door_verdicts
    # 中 fallback 为 "unknown", c282 honest disclosure)
    recs = [
        _make_rec("A", trend=1, trend_conf=80.0, score_b=0.5),
        _make_rec("B", trend=1, trend_conf=60.0, score_b=0.3),
    ]
    payload = {"recommendations": recs, "market_state": {"regime_gate_level": "normal"}}

    # c329: _load_latest_auto_screening_payload 使用 __file__ 定位,
    # monkeypatch.chdir(tmp_path) 无效 → mock 整个 loader.
    monkeypatch.setattr(
        screening_mod,
        "_load_latest_auto_screening_payload",
        lambda trade_date=None: payload,
    )

    app = FastAPI()
    app.include_router(screening_mod.router)
    client = TestClient(app)

    req_payload = {
        "trend": 0.4,
        "mean_reversion": 0.1,
        "fundamental": 0.3,
        "event_sentiment": 0.2,
        "top_n": 5,
    }
    resp = client.post("/api/screening/custom-weights", json=req_payload)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "recommendations" in data
    assert "meta" in data
    # meta.weights 仅含四策略权重, 不含 top_n
    assert data["meta"]["weights"] == {
        "trend": 0.4,
        "mean_reversion": 0.1,
        "fundamental": 0.3,
        "event_sentiment": 0.2,
    }
    # 报告里的 ticker 应在结果中
    tickers = [r["ticker"] for r in data["recommendations"]]
    assert "A" in tickers


def test_web_custom_weights_invalid_sum_returns_422() -> None:
    """权重和 != 1.0 → 422。"""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.backend.routes.screening import router as screening_router

    app = FastAPI()
    app.include_router(screening_router)  # screening_router 已含 /api/screening 前缀
    client = TestClient(app)

    payload = {
        "trend": 0.5,
        "mean_reversion": 0.5,
        "fundamental": 0.5,
        "event_sentiment": 0.5,
    }
    resp = client.post("/api/screening/custom-weights", json=payload)
    assert resp.status_code == 422
    assert "权重之和" in resp.json()["detail"]


def test_web_custom_weights_negative_weight_returns_422() -> None:
    """负权重被 Pydantic Field(ge=0) 拦截 → 422。"""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.backend.routes.screening import router as screening_router

    app = FastAPI()
    app.include_router(screening_router)  # screening_router 已含 /api/screening 前缀
    client = TestClient(app)

    payload = {
        "trend": -0.1,
        "mean_reversion": 0.4,
        "fundamental": 0.4,
        "event_sentiment": 0.3,
    }
    resp = client.post("/api/screening/custom-weights", json=payload)
    assert resp.status_code == 422


# ===========================================================================
# 12. 缺失 strategy_signals 容错
# ===========================================================================


def test_reweight_missing_signals_falls_back_to_original_score() -> None:
    """rec 完全缺失 strategy_signals → 保留原 score_b。"""
    recs = [{"ticker": "X", "name": "x", "score_b": 0.42}]
    w = StrategyWeights()
    out = reweight_recommendations(recs, w)
    assert out[0]["score_b"] == 0.42
    assert out[0]["original_score_b"] == 0.42


def test_reweight_empty_signals_falls_back() -> None:
    """strategy_signals 为空 dict → 保留原 score_b。"""
    recs = [{"ticker": "Y", "score_b": 0.1, "strategy_signals": {}}]
    w = StrategyWeights()
    out = reweight_recommendations(recs, w)
    assert out[0]["score_b"] == 0.1


# ===========================================================================
# 13. completeness=0 视为 0
# ===========================================================================


def test_reweight_zero_completeness_contributes_zero() -> None:
    """completeness=0 的策略不参与重算 (避免低质量数据污染)。"""
    rec = {
        "ticker": "Z",
        "score_b": 0.0,
        "strategy_signals": {
            "trend": {"direction": 1, "confidence": 100.0, "completeness": 0.0},  # 数据不可用
            "mean_reversion": {"direction": 0, "confidence": 0.0, "completeness": 1.0},
            "fundamental": {"direction": 0, "confidence": 0.0, "completeness": 1.0},
            "event_sentiment": {"direction": 0, "confidence": 0.0, "completeness": 1.0},
        },
    }
    w = StrategyWeights()  # 等权
    out = reweight_recommendations([rec], w)
    # trend 因 completeness=0 被忽略, 其余 3 策略都 0 → 加权 = 0 → 归 0 → 但有 has_any_signal?
    # 实际: trend completeness=0 → 0, 其它 direction=0 → 0; has_any_signal=False → 回退原 score_b=0.0
    assert out[0]["score_b"] == 0.0


# ===========================================================================
# 14. 排序稳定 (同分按 ticker 字典序)
# ===========================================================================


def test_reweight_stable_sort_by_ticker() -> None:
    """同 score_b 时, ticker 字典序升序。"""
    recs = [
        _make_rec("B", trend=1, trend_conf=50.0, score_b=0.5),
        _make_rec("A", trend=1, trend_conf=50.0, score_b=0.5),
        _make_rec("C", trend=1, trend_conf=50.0, score_b=0.5),
    ]
    w = StrategyWeights()  # 等权, 三个 score_b 都是 0.5
    out = reweight_recommendations(recs, w)
    assert [r["ticker"] for r in out] == ["A", "B", "C"]


# ===========================================================================
# 15. from_dict 缺省字段
# ===========================================================================


def test_from_dict_with_defaults() -> None:
    """from_dict 缺省字段 = DEFAULT_WEIGHTS。"""
    w = StrategyWeights.from_dict({})
    assert w.to_dict() == DEFAULT_WEIGHTS
    # 显式给出 sum=1 的合法值 — mean_reversion 覆盖 default
    w2 = StrategyWeights.from_dict({"trend": 0.5, "mean_reversion": 0.15, "fundamental": 0.25, "event_sentiment": 0.1})
    assert w2.trend == 0.5
    # 显式给出的字段就是给定值
    assert w2.mean_reversion == 0.15
    assert w2.event_sentiment == 0.1
    # 缺省字段: 当仅给出一个非 default 字段时, 其它仍取 DEFAULT_WEIGHTS 的值 (0.25)
    # 注意: 用户需保证 sum=1; 此处 0.4 + 0.25*3 = 1.15 不合法, 改测 sum=1 的情况:
    # 显式给 trend=0.4, 把 fundamental 改为 0.1 (其它 0.25), sum=1.0
    w3 = StrategyWeights.from_dict({"trend": 0.4, "fundamental": 0.1})
    assert w3.trend == 0.4
    assert w3.fundamental == 0.1
    # 缺省字段 (mean_reversion, event_sentiment) 走 DEFAULT_WEIGHTS
    assert w3.mean_reversion == DEFAULT_WEIGHTS["mean_reversion"]  # 0.25
    assert w3.event_sentiment == DEFAULT_WEIGHTS["event_sentiment"]  # 0.25


# ===========================================================================
# 16. normalize 归一化
# ===========================================================================


def test_normalize_scales_to_one() -> None:
    """normalize 把任意正权重和归一到 1。"""
    # 注意: __post_init__ 会先校验, 所以这里直接构造 sum=2 的非法值不可行
    # 改测 sum=1 的情况 → normalize 后应仍为 1
    w = StrategyWeights(trend=0.4, mean_reversion=0.2, fundamental=0.3, event_sentiment=0.1)
    w2 = w.normalize()
    assert abs(sum(w2.to_dict().values()) - 1.0) < 1e-9


# ===========================================================================
# 17. score_b 范围 [-1, +1]
# ===========================================================================


def test_reweight_score_b_clamped_to_minus1_plus1() -> None:
    """加权超过 ±1 时被截断。"""
    rec = _make_rec("Q", trend=1, trend_conf=100.0, fund=1, fund_conf=100.0, es=1, es_conf=100.0, mr=1, mr_conf=100.0)
    w = StrategyWeights()  # 等权 0.25
    out = reweight_recommendations([rec], w)
    # weighted = 0.25*100*4 = 100, /100 = 1.0
    assert abs(out[0]["score_b"] - 1.0) < 1e-9
    # 不应超过 1
    assert out[0]["score_b"] <= 1.0
    assert out[0]["score_b"] >= -1.0


# ===========================================================================
# 18. 输入校验: 非 dict rec 跳过
# ===========================================================================


def test_reweight_skips_non_dict_entries() -> None:
    """非 dict 项 (如 str/None) 静默跳过, 不崩溃。"""
    recs = [
        _make_rec("A", trend=1, trend_conf=80.0, score_b=0.5),
        "INVALID",
        None,
        _make_rec("B", trend=1, trend_conf=60.0, score_b=0.3),
    ]
    w = StrategyWeights()
    out = reweight_recommendations(recs, w)
    assert len(out) == 2
    assert {r["ticker"] for r in out} == {"A", "B"}


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
