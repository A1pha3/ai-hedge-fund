"""R6 route-A (loop 29) — profit-aware key persistence 测试.

目标: 给 ``TrackingRecord`` 加 profit-aware 排序键字段, 让
``update_tracking_history`` 把 auto_screening pick 上的
``win_rates`` / ``expected_returns`` / ``bucket_sample_count`` /
``composite_score`` 落盘到 ``tracking_history.json``.

背景 (R6 north-star blocker, loop 28 feasibility confirmed):
- composite_score 有 **负预测力** (top-3 winrate 47.3% vs 等权 59.5%, C219 n=7993);
  owner 决策点 = 是否 flip 默认排序到 ``--profit-aware`` (按经验 winrate 重排,
  backtested 47%→62%, C273/C276).
- 决策被阻: ``compute_selection_profitability_from_loaded`` 能跑 4 策略 (score_desc
  / score_asc / equal_weight / random_n) 但缺 ``profit_aware`` 策略, 因为
  profit-aware 键用的是评分时附加到 pick 的 LIVE win_rates/expected_returns/
  bucket_sample_count — 这些 **没有被持久化** 到 tracking_history (只存 score_b +
  score_decomposition). 历史 74 天数据因此无法重建 profit-aware 排序.
- route A = forward-persist profit-aware 键字段. 新记录 (从本 commit 起) 带 PIT
 诚实数据 (评分时刻的 winrate frozen = 正确 point-in-time); 等新记录成熟 (T+5/T+10)
 后 A/B 可在 compute_selection_profitability_from_loaded 加 profit_aware 策略.

设计决策 (loop 29, R6 route A):
- 4 个新字段, 全部 ``| None = None`` (向后兼容旧记录).
- 不验证 dict 内部 schema (win_rates 的 t1/t5/t10 键等); 由消费侧 (未来的 A/B
  策略) isinstance/键存在性校验, 保持持久化层与计算层解耦 (镜像 NS-6 模式).
- ``composite_score`` 用 ``_optional_float``; 两个 dict 字段 passthrough + isinstance
  守卫; ``bucket_sample_count`` passthrough (None if absent).
- 落盘点: ``_update_tracking_history_locked`` 把 pick rec 上的字段传入 TrackingRecord.
- 不改默认前门行为 (纯诊断字段持久化). 不做 A/B 本身 (那是 route A 数据成熟后的
  下一切片).
"""

from __future__ import annotations

from pathlib import Path

from src.screening.recommendation_tracker import (
    TrackingRecord,
    update_tracking_history,
)

# ---------------------------------------------------------------------------
# 1. TrackingRecord — profit-aware 字段默认 None (向后兼容)
# ---------------------------------------------------------------------------


def test_tracking_record_has_profit_aware_fields_default_none() -> None:
    """4 个 profit-aware 字段默认 None (旧记录 / 未注入 pick 向后兼容)."""
    record = TrackingRecord(
        ticker="000001",
        name="PingAn",
        recommended_date="20260623",
        recommended_price=12.5,
        recommendation_score=0.65,
    )
    assert hasattr(record, "composite_score")
    assert hasattr(record, "win_rates")
    assert hasattr(record, "expected_returns")
    assert hasattr(record, "bucket_sample_count")
    assert record.composite_score is None
    assert record.win_rates is None
    assert record.expected_returns is None
    assert record.bucket_sample_count is None


# ---------------------------------------------------------------------------
# 2. to_dict / from_dict round-trip 保留 profit-aware 字段
# ---------------------------------------------------------------------------


def test_tracking_record_profit_aware_fields_round_trip() -> None:
    """to_dict → from_dict 必须保留 profit-aware 键 (让未来 A/B 能重建排序)."""
    record = TrackingRecord(
        ticker="000001",
        name="PingAn",
        recommended_date="20260623",
        recommended_price=12.5,
        recommendation_score=0.4746,
        composite_score=0.5246,
        win_rates={"t1": 0.491, "t5": 0.593, "t10": 0.646},
        expected_returns={"t1": 0.318, "t5": 2.586, "t10": 5.544},
        bucket_sample_count=4902,
    )

    restored = TrackingRecord.from_dict(record.to_dict())

    assert restored.composite_score == 0.5246
    assert restored.win_rates == {"t1": 0.491, "t5": 0.593, "t10": 0.646}
    assert restored.expected_returns == {"t1": 0.318, "t5": 2.586, "t10": 5.544}
    assert restored.bucket_sample_count == 4902


def test_tracking_record_old_payload_without_profit_aware_fields_loads_none() -> None:
    """旧 tracking_history 记录 (无 profit-aware 字段) 反序列化为 None."""
    old_payload = {
        "ticker": "000001",
        "name": "PingAn",
        "recommended_date": "20260601",
        "recommended_price": 12.0,
        "recommendation_score": 0.5,
        "tracking_status": "complete",
    }
    restored = TrackingRecord.from_dict(old_payload)
    assert restored.composite_score is None
    assert restored.win_rates is None
    assert restored.expected_returns is None
    assert restored.bucket_sample_count is None


# ---------------------------------------------------------------------------
# 3. update_tracking_history 把 pick rec 上的 profit-aware 字段落盘
# ---------------------------------------------------------------------------


def test_update_tracking_history_persists_profit_aware_fields(tmp_path: Path) -> None:
    """auto_screening pick 上的 profit-aware 字段必须落盘到 tracking_history.

    这是 route A 的核心: 若 pick 带 win_rates/expected_returns/bucket_sample_count/
    composite_score 但 update_tracking_history 丢弃它们, 则未来 A/B 仍无数据可跑.
    镜像 NS-6 score_decomposition 落盘测试.
    """
    trade_date = "20260623"
    import json

    # auto_screening payload: pick 带 profit-aware 键 (顶层 model_version + recommendations[])
    screening_payload = {
        "mode": "auto_screening",
        "date": trade_date,
        "model_version": "abc1234",
        "recommendations": [
            {
                "ticker": "000001",
                "name": "PingAn",
                "score_b": 0.4746,
                "composite_score": 0.5246,
                "close": 12.5,
                "win_rates": {"t5": 0.593, "t10": 0.646},
                "expected_returns": {"t5": 2.586, "t10": 5.544},
                "bucket_sample_count": 4902,
            }
        ],
    }
    (tmp_path / f"auto_screening_{trade_date}.json").write_text(
        json.dumps(screening_payload),
        encoding="utf-8",
    )

    updated = update_tracking_history(
        tmp_path,
        trade_date=trade_date,
        use_data_fetcher=lambda ticker, start, end: [],
    )
    assert updated == 1

    history_path = tmp_path / "tracking_history.json"
    records = json.loads(history_path.read_text(encoding="utf-8"))["records"]
    assert len(records) == 1
    rec = records[0]
    assert rec["composite_score"] == 0.5246
    assert rec["win_rates"] == {"t5": 0.593, "t10": 0.646}
    assert rec["expected_returns"] == {"t5": 2.586, "t10": 5.544}
    assert rec["bucket_sample_count"] == 4902
