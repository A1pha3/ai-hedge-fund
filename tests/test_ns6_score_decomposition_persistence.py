"""NS-6 因子归因数据基础 — score_decomposition 持久化测试。

目标: 给 ``TrackingRecord`` 加 ``score_decomposition`` 字段, 让
``update_tracking_history`` 把 main.py 注入的 ``score_decomposition`` (来自
``signal_fusion.compute_score_decomposition``) 落盘到 ``tracking_history.json``.

背景 (autodev C235 discovery — friction mining on C231-C234 fresh code):
- main.py:698 注入 ``d["score_decomposition"] = _decompose(item)`` 到 recommendation dict
- ``TrackingRecord`` dataclass 缺该字段 → ``update_tracking_history`` 构造时丢弃
- 验证: 7993 records 中 0 个有 score_decomposition (0% 覆盖)
- 后果: ``factor_attribution.compute_factor_attribution_from_loaded`` 永远 insufficient
- 阻塞: NS-6 因子归因诊断 (高低分位 winrate 倒挂检测) 无法启动

设计决策 (autodev C235):
- 字段类型 ``dict[str, Any] | None = None`` (None = 旧记录/未注入, 向后兼容)
- 注入点: ``TrackingRecord.score_decomposition`` 默认 ``None``; 旧记录 round-trip 仍 ``None``
- 落盘点: ``update_tracking_history`` 把 ``rec.get("score_decomposition")`` 传入 TrackingRecord
- 不验证 dict 内部 schema (base_contributions/attention_contribution/...); 由 factor_attribution 模块
  在消费侧 isinstance(decomp, dict) 校验, 保持持久化层与计算层解耦
"""

from __future__ import annotations

import json
from pathlib import Path

from src.screening.recommendation_tracker import (
    TrackingRecord,
    update_tracking_history,
)


# ---------------------------------------------------------------------------
# 1. TrackingRecord — score_decomposition 字段默认 None
# ---------------------------------------------------------------------------


def test_tracking_record_has_score_decomposition_field_default_none() -> None:
    """TrackingRecord 默认 score_decomposition=None (向后兼容旧记录)."""
    record = TrackingRecord(
        ticker="000001",
        name="PingAn",
        recommended_date="20260623",
        recommended_price=12.5,
        recommendation_score=0.65,
    )
    assert hasattr(record, "score_decomposition")
    assert record.score_decomposition is None


# ---------------------------------------------------------------------------
# 2. to_dict / from_dict round-trip 保留 score_decomposition
# ---------------------------------------------------------------------------


def test_tracking_record_round_trip_preserves_score_decomposition() -> None:
    """to_dict / from_dict round-trip 保留 score_decomposition dict."""
    decomp = {
        "base_contributions": {"T": 0.10, "MR": 0.05, "F": 0.20, "E": -0.05},
        "attention_contribution": 0.03,
        "stability_bonus": 0.0,
        "consensus_bonus": 0.05,
        "other_adjustments": 0.02,
        "total": 0.40,
    }
    record = TrackingRecord(
        ticker="000001",
        name="PingAn",
        recommended_date="20260623",
        recommended_price=12.5,
        recommendation_score=0.65,
        score_decomposition=decomp,
    )
    dumped = record.to_dict()
    assert dumped["score_decomposition"] == decomp

    restored = TrackingRecord.from_dict(dumped)
    assert restored.score_decomposition == decomp


# ---------------------------------------------------------------------------
# 3. 旧 tracking_history 记录无 score_decomposition → from_dict 默认 None
# ---------------------------------------------------------------------------


def test_tracking_record_from_dict_missing_score_decomposition_defaults_none() -> None:
    """旧 tracking_history 记录无 score_decomposition → from_dict 默认 None."""
    legacy_payload = {
        "ticker": "000001",
        "name": "PingAn",
        "recommended_date": "20260620",
        "recommended_price": 11.0,
        "recommendation_score": 0.5,
    }
    record = TrackingRecord.from_dict(legacy_payload)
    assert record.score_decomposition is None


# ---------------------------------------------------------------------------
# 4. update_tracking_history — 把 rec.score_decomposition 落盘
# ---------------------------------------------------------------------------


def _make_report_with_decomp(
    reports_dir: Path,
    date_str: str,
    recs: list[dict],
    *,
    model_version: str = "abc1234",
) -> Path:
    """写入带 score_decomposition 字段的 auto_screening 报告."""
    path = reports_dir / f"auto_screening_{date_str}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "mode": "auto_screening",
        "date": date_str,
        "model_version": model_version,
        "recommendations": recs,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    return path


def test_update_tracking_history_persists_score_decomposition(tmp_path: Path) -> None:
    """update_tracking_history 把 rec.score_decomposition 落盘到 tracking_history."""
    decomp = {
        "base_contributions": {"T": 0.10, "MR": 0.05, "F": 0.20, "E": -0.05},
        "attention_contribution": 0.03,
        "stability_bonus": 0.0,
        "consensus_bonus": 0.05,
        "other_adjustments": 0.02,
        "total": 0.40,
    }
    recs = [
        {
            "ticker": "000001",
            "name": "PingAn",
            "score_b": 0.65,
            "close": 12.5,
            "score_decomposition": decomp,
        },
    ]
    _make_report_with_decomp(tmp_path, "20260623", recs, model_version="cafef00")

    updated = update_tracking_history(
        tmp_path,
        trade_date="20260623",
        use_data_fetcher=lambda ticker, start, end: [],
    )
    assert updated == 1

    history_path = tmp_path / "tracking_history.json"
    with open(history_path, encoding="utf-8") as f:
        history = json.load(f)

    record = history["records"][0]
    assert record["score_decomposition"] == decomp, (
        f"TrackingRecord 缺少 score_decomposition 或值不匹配: {record}"
    )


def test_update_tracking_history_missing_score_decomposition_defaults_none(
    tmp_path: Path,
) -> None:
    """旧 rec 无 score_decomposition → TrackingRecord.score_decomposition = None."""
    recs = [
        {"ticker": "000001", "name": "PingAn", "score_b": 0.65, "close": 12.5},
    ]
    _make_report_with_decomp(tmp_path, "20260620", recs, model_version="cafef00")

    update_tracking_history(
        tmp_path,
        trade_date="20260620",
        use_data_fetcher=lambda ticker, start, end: [],
    )

    history_path = tmp_path / "tracking_history.json"
    with open(history_path, encoding="utf-8") as f:
        history = json.load(f)

    # 旧记录无 score_decomposition → 字段存在但为 None (向后兼容)
    assert "score_decomposition" in history["records"][0]
    assert history["records"][0]["score_decomposition"] is None
