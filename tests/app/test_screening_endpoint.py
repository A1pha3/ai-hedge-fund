"""Tests for the Web 端一键选股端点 (P1-5).

覆盖:
  1. 端点存在 + 注册
  2. 默认请求 → 200 + 正确响应结构
  3. trade_date 格式校验 (YYYYMMDD / YYYY-MM-DD / 非法)
  4. top_n 边界 (0 / 1 / 100 / 101)
  5. 错误处理: 候选池为空 → 503
  6. 错误处理: TUSHARE_TOKEN 缺失 → 503
  7. 错误处理: 超时 → 504
  8. 与 run_auto_screening 输出一致 (字段对齐)
  9. JSON 序列化: NaN/Inf 字段处理
 10. strategies 校验
"""

from __future__ import annotations

import json
import math
import os
from datetime import datetime
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.backend.routes.screening import (
    _apply_score_threshold,
    _attach_explain,
    _normalize_trade_date,
    _sanitize_nan,
    _validate_strategies,
    MAX_TOP_N,
    MIN_TOP_N,
)
from app.backend.routes.screening import router as screening_router

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _build_client() -> TestClient:
    """最小化 TestClient — 端点不需要 DB / auth。"""
    app = FastAPI()
    app.include_router(screening_router)
    return TestClient(app)


def _make_payload(
    n_recs: int = 3,
    include_nan: bool = False,
    industry: str = "电子",
    top_n: int = 20,
) -> dict:
    """构造与 compute_auto_screening_results 输出一致的 mock payload。"""
    recs = []
    for i in range(n_recs):
        recs.append(
            {
                "ticker": f"{600000 + i:06d}",
                "name": f"测试股票{i}",
                "industry_sw": industry,
                "score_b": 0.5 + i * 0.05,
                "decision": "watch",
                "strategy_signals": {
                    "trend": {
                        "direction": 1,
                        "confidence": 65.0,
                        "sub_factors": {"mom_20d": {"name": "20日动量", "direction": 1, "confidence": 70.0}},
                    },
                    "mean_reversion": {
                        "direction": 0,
                        "confidence": 50.0,
                        "sub_factors": {},
                    },
                },
            }
        )
    if include_nan and recs:
        recs[0]["score_b"] = float("nan")
        recs[0]["strategy_signals"]["trend"]["confidence"] = float("inf")
    return {
        "mode": "auto_screening",
        "date": "20260607",
        "market_state": {
            "state_type": "trend",
            "adx": 22.5,
            "atr_price_ratio": 0.015,
            "position_scale": 0.85,
            "regime_gate_level": "normal",
        },
        "layer_a_count": 500,
        "total_scored": 480,
        "high_pool_count": 60,
        "top_n": top_n,
        "recommendations": recs,
        "sector_concentration_warnings": [],
        "consecutive_recommendation": {"lookback_days": 30, "high_streak_count": 2},
        "signal_decay_summary": {"mild": 1, "moderate": 0, "severe": 0, "total": 5},
        "batch_data_fetcher": {"use_batch": True, "batch_calls": 10, "batch_failures": 0, "single_ticker_calls": 5, "cache_hits": 100},
        "industry_rotation": [
            {
                "industry_name": "电子",
                "industry_code": "申万电子",
                "momentum_score": 25.5,
                "avg_score_b": 0.62,
                "candidate_count": 8,
                "north_money_flow": 0.0,
                "rank": 1,
                "tickers": ["600000", "600001"],
            }
        ],
        "tracking_summary": {"total_recommendations": 50, "lookback_days": 30, "win_rate": 0.55},
    }


# ---------------------------------------------------------------------------
# 1. 端点存在 + 注册
# ---------------------------------------------------------------------------


def test_endpoint_registered() -> None:
    """端点必须出现在 screening router 的路由表中。"""
    paths = {r.path for r in screening_router.routes if hasattr(r, "path")}
    assert "/api/screening/auto" in paths
    assert "/api/screening/latest" in paths


def test_endpoint_post_returns_json() -> None:
    """POST /api/screening/auto 端点能响应 HTTP 请求。"""
    client = _build_client()
    with (
        patch.dict(os.environ, {"TUSHARE_TOKEN": "test_token"}, clear=False),
        patch(
            "app.backend.routes.screening.compute_auto_screening_results",
            return_value=_make_payload(),
        ),
    ):
        response = client.post("/api/screening/auto", json={})
    # 即使 mock 也可能因 TUSHARE_TOKEN 缺失失败, 但至少不是 404
    assert response.status_code != 404


def test_latest_endpoint_returns_latest_saved_payload() -> None:
    """GET /api/screening/latest 应返回最近一次 auto_screening 的完整 payload。"""
    client = _build_client()
    with patch(
        "app.backend.routes.screening._load_latest_auto_screening_payload",
        return_value=_make_payload(),
    ) as mock_loader:
        response = client.get("/api/screening/latest")

    assert response.status_code == 200
    assert response.json()["trade_date"] == "20260607"
    assert response.json()["top_n"] == 20
    mock_loader.assert_called_once_with(trade_date=None)


# ---------------------------------------------------------------------------
# 2. 默认请求 → 200 + 正确响应结构
# ---------------------------------------------------------------------------


def test_default_request_returns_full_payload() -> None:
    """默认参数请求应返回 200 + 完整 ScreeningResponse 字段。"""
    client = _build_client()
    with (
        patch.dict(os.environ, {"TUSHARE_TOKEN": "test_token"}, clear=False),
        patch(
            "app.backend.routes.screening.compute_auto_screening_results",
            return_value=_make_payload(),
        ) as mock_fn,
    ):
        response = client.post("/api/screening/auto", json={})
    assert response.status_code == 200
    body = response.json()

    # 必填字段存在
    for key in (
        "trade_date",
        "recommendations",
        "market_state",
        "tracking_summary",
        "consecutive_recommendation",
        "industry_rotation",
        "execution_time_seconds",
        "batch_data_fetcher",
        "signal_decay_summary",
        "sector_concentration_warnings",
        "layer_a_count",
        "total_scored",
        "high_pool_count",
        "top_n",
        "meta",
    ):
        assert key in body, f"missing key: {key}"

    # 默认 trade_date = 今日
    expected_today = datetime.now().strftime("%Y%m%d")
    assert body["trade_date"] == expected_today
    # mock 应该被调用 (因 TUSHARE_TOKEN mock)
    assert mock_fn.called
    # meta 默认值
    assert body["meta"]["use_explain"] is True
    assert body["meta"]["score_threshold"] == 0.0


# ---------------------------------------------------------------------------
# 3. trade_date 格式校验
# ---------------------------------------------------------------------------


def test_trade_date_yyyymmdd_accepted() -> None:
    """YYYYMMDD 格式应被接受, 内部统一存储。"""
    result = _normalize_trade_date("20260607")
    assert result == "20260607"


def test_trade_date_iso_format_accepted() -> None:
    """YYYY-MM-DD 格式应被接受, 内部统一为 YYYYMMDD。"""
    result = _normalize_trade_date("2026-06-07")
    assert result == "20260607"


def test_trade_date_invalid_format_rejected() -> None:
    """非法格式应在单元层直接抛 422。"""
    client = _build_client()
    with (
        patch.dict(os.environ, {"TUSHARE_TOKEN": "test_token"}, clear=False),
        patch(
            "app.backend.routes.screening.compute_auto_screening_results",
            return_value=_make_payload(),
        ),
    ):
        response = client.post("/api/screening/auto", json={"trade_date": "2026/06/07"})
    assert response.status_code == 422
    assert "trade_date" in response.json()["detail"] or "格式" in response.json()["detail"]


def test_trade_date_empty_rejected() -> None:
    """空字符串/空白字符串应被拒绝 (_normalize_trade_date 校验)。"""
    client = _build_client()
    with (
        patch.dict(os.environ, {"TUSHARE_TOKEN": "test_token"}, clear=False),
        patch(
            "app.backend.routes.screening.compute_auto_screening_results",
            return_value=_make_payload(),
        ),
    ):
        response = client.post("/api/screening/auto", json={"trade_date": "  "})
    # 空白字符不匹配 YYYYMMDD 模式 -> 422
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# 4. top_n 边界
# ---------------------------------------------------------------------------


def test_top_n_zero_rejected() -> None:
    """top_n=0 越界 → Pydantic 422。"""
    client = _build_client()
    response = client.post("/api/screening/auto", json={"top_n": 0})
    assert response.status_code == 422


def test_top_n_above_max_rejected() -> None:
    """top_n=101 越界 → Pydantic 422。"""
    client = _build_client()
    response = client.post("/api/screening/auto", json={"top_n": 101})
    assert response.status_code == 422


def test_top_n_at_min_accepted() -> None:
    """top_n=1 (下界) 应被接受。"""
    client = _build_client()
    with (
        patch.dict(os.environ, {"TUSHARE_TOKEN": "test_token"}, clear=False),
        patch(
            "app.backend.routes.screening.compute_auto_screening_results",
            return_value=_make_payload(n_recs=1, top_n=1),
        ),
    ):
        response = client.post("/api/screening/auto", json={"top_n": 1})
    assert response.status_code == 200
    assert response.json()["top_n"] == 1


def test_top_n_at_max_accepted() -> None:
    """top_n=100 (上界) 应被接受。"""
    client = _build_client()
    with (
        patch.dict(os.environ, {"TUSHARE_TOKEN": "test_token"}, clear=False),
        patch(
            "app.backend.routes.screening.compute_auto_screening_results",
            return_value=_make_payload(n_recs=5, top_n=100),
        ),
    ):
        response = client.post("/api/screening/auto", json={"top_n": 100})
    assert response.status_code == 200
    assert response.json()["top_n"] == 100


# ---------------------------------------------------------------------------
# 5. 错误处理: 候选池为空 → 503
# ---------------------------------------------------------------------------


def test_empty_candidate_pool_returns_503() -> None:
    """当 compute_auto_screening_results 抛 ValueError (候选池空) → 503。"""
    client = _build_client()
    with (
        patch.dict(os.environ, {"TUSHARE_TOKEN": "test_token"}, clear=False),
        patch(
            "app.backend.routes.screening.compute_auto_screening_results",
            side_effect=ValueError("候选池为空 (trade_date=20260607), 请检查市场数据源是否可用"),
        ),
    ):
        response = client.post("/api/screening/auto", json={"trade_date": "20260607"})
    assert response.status_code == 503
    assert "候选池" in response.json()["detail"]


# ---------------------------------------------------------------------------
# 6. 错误处理: TUSHARE_TOKEN 缺失 → 503
# ---------------------------------------------------------------------------


def test_missing_tushare_token_returns_503() -> None:
    """TUSHARE_TOKEN 缺失时直接 503, 不调用 compute 函数。"""
    client = _build_client()
    env_without_token = {k: v for k, v in os.environ.items() if k not in ("TUSHARE_TOKEN", "TUSHARE_API_KEY")}
    with (
        patch.dict(os.environ, env_without_token, clear=True),
        patch(
            "app.backend.routes.screening.compute_auto_screening_results",
            return_value=_make_payload(),
        ) as mock_fn,
    ):
        response = client.post("/api/screening/auto", json={})
    assert response.status_code == 503
    assert "TUSHARE_TOKEN" in response.json()["detail"]
    # 不应调用核心函数
    assert not mock_fn.called


# ---------------------------------------------------------------------------
# 7. 错误处理: 超时 → 504
# ---------------------------------------------------------------------------


def test_timeout_returns_504(monkeypatch) -> None:
    """compute_auto_screening_results 阻塞超过 60s → 504。"""
    client = _build_client()
    monkeypatch.setattr("app.backend.routes.screening.DEFAULT_TIMEOUT_SECONDS", 0.001)

    def _slow(*_args, **_kwargs):
        # 模拟真实阻塞, 让真实 wait_for 对 to_thread 超时。
        import time as _t

        _t.sleep(0.05)
        return _make_payload()

    with (
        patch.dict(os.environ, {"TUSHARE_TOKEN": "test_token"}, clear=False),
        patch(
            "app.backend.routes.screening.compute_auto_screening_results",
            side_effect=_slow,
        ),
    ):
        response = client.post("/api/screening/auto", json={})
    assert response.status_code == 504
    assert "超时" in response.json()["detail"]


# ---------------------------------------------------------------------------
# 8. 与 run_auto_screening 输出一致 (字段对齐)
# ---------------------------------------------------------------------------


def test_response_field_alignment_with_cli() -> None:
    """响应字段与 compute_auto_screening_results 输出字段必须一致。"""
    client = _build_client()
    mock_payload = _make_payload(n_recs=4)
    with (
        patch.dict(os.environ, {"TUSHARE_TOKEN": "test_token"}, clear=False),
        patch(
            "app.backend.routes.screening.compute_auto_screening_results",
            return_value=mock_payload,
        ) as mock_fn,
    ):
        response = client.post("/api/screening/auto", json={"trade_date": "20260607"})
    assert response.status_code == 200
    body = response.json()

    # 调用参数: trade_date 与 top_n 透传
    call_args = mock_fn.call_args
    assert call_args[0][0] == "20260607"  # trade_date
    assert call_args[0][1] == 20  # top_n default
    assert call_args.kwargs.get("selected_strategies") is None

    # 字段对齐: 响应字段必须从 payload 中正确取出
    assert body["trade_date"] == "20260607"
    assert len(body["recommendations"]) == 4
    assert body["market_state"]["state_type"] == "trend"
    assert body["industry_rotation"][0]["industry_name"] == "电子"
    assert body["tracking_summary"]["win_rate"] == 0.55
    assert body["consecutive_recommendation"]["high_streak_count"] == 2
    assert body["batch_data_fetcher"]["batch_calls"] == 10
    assert body["signal_decay_summary"]["mild"] == 1
    assert body["layer_a_count"] == 500
    assert body["total_scored"] == 480
    assert body["high_pool_count"] == 60


# ---------------------------------------------------------------------------
# 9. JSON 序列化: NaN/Inf 字段处理
# ---------------------------------------------------------------------------


def test_nan_inf_in_payload_replaced_with_none() -> None:
    """payload 中 NaN/Inf 必须被清洗为 None (避免前端 JSON.parse 失败)。"""
    client = _build_client()
    mock_payload = _make_payload(n_recs=2, include_nan=True)
    with (
        patch.dict(os.environ, {"TUSHARE_TOKEN": "test_token"}, clear=False),
        patch(
            "app.backend.routes.screening.compute_auto_screening_results",
            return_value=mock_payload,
        ),
    ):
        response = client.post("/api/screening/auto", json={"trade_date": "20260607"})
    assert response.status_code == 200

    # 严格 JSON 解析 (Python 的 json.loads 默认允许 NaN, 但前端 JSON.parse 严格)
    raw = response.content.decode("utf-8")
    # 确保 body 不含裸 NaN/Inf (这些不是合法 JSON)
    # 我们用 json.loads(strict=False) 默认通过, 但应该 None 化
    body = json.loads(raw)
    first_rec = body["recommendations"][0]
    # NaN 已被替换为 None
    assert first_rec["score_b"] is None
    assert first_rec["strategy_signals"]["trend"]["confidence"] is None

    # 同时验证单元 _sanitize_nan 自身
    assert _sanitize_nan(float("nan")) is None
    assert _sanitize_nan(float("inf")) is None
    assert _sanitize_nan(float("-inf")) is None
    assert _sanitize_nan({"a": float("nan"), "b": [float("inf"), 1.0]}) == {"a": None, "b": [None, 1.0]}
    # 普通值不变
    assert _sanitize_nan(0.5) == 0.5
    assert _sanitize_nan("hello") == "hello"


def test_score_threshold_filters_recommendations() -> None:
    """score_threshold > 0 时应过滤 score_b 不足的票。"""
    recs = [
        {"ticker": "600000", "score_b": 0.7, "industry_sw": "电子"},
        {"ticker": "600001", "score_b": 0.3, "industry_sw": "电子"},
        {"ticker": "600002", "score_b": None, "industry_sw": "电子"},  # 视为不通过
        {"ticker": "600003", "score_b": float("nan"), "industry_sw": "电子"},  # 视为不通过
    ]
    out = _apply_score_threshold(recs, threshold=0.5)
    assert len(out) == 1
    assert out[0]["ticker"] == "600000"

    # threshold <= 0 不过滤
    out2 = _apply_score_threshold(recs, threshold=0.0)
    assert len(out2) == 4


def test_attach_explain_disabled_strips_sub_factors() -> None:
    """use_explain=False 时应从 strategy_signals 中剔除 sub_factors。"""
    recs = [
        {
            "ticker": "600000",
            "score_b": 0.5,
            "strategy_signals": {
                "trend": {"direction": 1, "confidence": 60, "sub_factors": {"mom_20d": {"name": "20日动量"}}},
                "mean_reversion": {"direction": 0, "confidence": 50},  # 无 sub_factors
            },
        }
    ]
    out = _attach_explain(recs, enabled=False)
    assert "sub_factors" not in out[0]["strategy_signals"]["trend"]
    assert out[0]["strategy_signals"]["trend"]["direction"] == 1
    # mean_reversion 没 sub_factors, 不变
    assert "sub_factors" not in out[0]["strategy_signals"]["mean_reversion"]

    # use_explain=True 保留
    out2 = _attach_explain(recs, enabled=True)
    assert "sub_factors" in out2[0]["strategy_signals"]["trend"]


# ---------------------------------------------------------------------------
# 10. strategies 校验
# ---------------------------------------------------------------------------


def test_strategies_invalid_value_rejected() -> None:
    """未知策略名应在 _validate_strategies 直接抛 422。"""
    client = _build_client()
    with (
        patch.dict(os.environ, {"TUSHARE_TOKEN": "test_token"}, clear=False),
        patch(
            "app.backend.routes.screening.compute_auto_screening_results",
            return_value=_make_payload(),
        ),
    ):
        response = client.post("/api/screening/auto", json={"strategies": ["unknown_strategy"]})
    assert response.status_code == 422
    assert "未知策略" in response.json()["detail"]


def test_selected_strategies_forwarded_to_compute_function() -> None:
    """合法 strategies 应透传到 compute_auto_screening_results。"""
    client = _build_client()
    with (
        patch.dict(os.environ, {"TUSHARE_TOKEN": "test_token"}, clear=False),
        patch(
            "app.backend.routes.screening.compute_auto_screening_results",
            return_value=_make_payload(),
        ) as mock_fn,
    ):
        response = client.post(
            "/api/screening/auto",
            json={"trade_date": "20260607", "strategies": ["fundamental"]},
        )
    assert response.status_code == 200
    assert mock_fn.call_args.kwargs["selected_strategies"] == ["fundamental"]


def test_strategies_all_valid_passes() -> None:
    """合法策略组合应通过校验。"""
    out = _validate_strategies(["trend", "mean_reversion"])
    assert out == ["trend", "mean_reversion"]


def test_strategies_none_returns_none() -> None:
    """None 表示全部四策略, 直接返回 None。"""
    assert _validate_strategies(None) is None


# ---------------------------------------------------------------------------
# 11. score_threshold 边界
# ---------------------------------------------------------------------------


def test_score_threshold_above_one_rejected() -> None:
    """score_threshold > 1.0 → Pydantic 422。"""
    client = _build_client()
    response = client.post("/api/screening/auto", json={"score_threshold": 1.5})
    assert response.status_code == 422


def test_score_threshold_negative_rejected() -> None:
    """score_threshold < -1.0 → Pydantic 422。"""
    client = _build_client()
    response = client.post("/api/screening/auto", json={"score_threshold": -1.5})
    assert response.status_code == 422
