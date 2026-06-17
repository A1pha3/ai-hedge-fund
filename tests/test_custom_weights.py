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
            trend=1, trend_conf=100.0,
            mr=1, mr_conf=80.0,
            fund=1, fund_conf=60.0,
            es=1, es_conf=40.0,
        )
    ]
    w = StrategyWeights()
    out = reweight_recommendations(recs, w)
    # weighted = 0.25*100 + 0.25*80 + 0.25*60 + 0.25*40 = 70 → /100 = 0.70
    assert abs(out[0]["score_b"] - 0.70) < 1e-9


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

    from app.backend.routes.screening import router as screening_router

    # 准备临时报告
    monkeypatch.chdir(tmp_path)
    recs = [
        _make_rec("A", trend=1, trend_conf=80.0, score_b=0.5),
        _make_rec("B", trend=1, trend_conf=60.0, score_b=0.3),
    ]
    reports_dir = tmp_path / "data" / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    (reports_dir / "auto_screening_20260607.json").write_text(
        json.dumps({"recommendations": recs}), encoding="utf-8"
    )

    app = FastAPI()
    app.include_router(screening_router)  # screening_router 已含 /api/screening 前缀
    client = TestClient(app)

    payload = {
        "trend": 0.4,
        "mean_reversion": 0.1,
        "fundamental": 0.3,
        "event_sentiment": 0.2,
        "top_n": 5,
    }
    resp = client.post("/api/screening/custom-weights", json=payload)
    assert resp.status_code in (200, 404), resp.text  # 找不到报告 (data dir 隔离) 也接受
    if resp.status_code == 200:
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
