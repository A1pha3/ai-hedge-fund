"""NS-2 模型版本基础设施 — 单元测试。

目标: 给 ``auto_screening`` 报告顶层和 ``TrackingRecord`` 加 ``model_version`` 字段
(git short sha), 让后续诊断模块 (state_type_calibration / regime_calibration /
expected_return / conviction_ranking) 能按版本分组区分老/新模型效果。

设计决策 (autodev C190 design_decision_packet):
- model_version = git short sha (7 位 hex), 失败回退 ``"unknown"``
- 理由: owner 改因子 = 改代码 = commit = git sha 变, 精确反映打分逻辑状态
- 注入点 1: ``_build_auto_screening_payload`` 顶层 (payload 单一真相源)
- 注入点 2: ``TrackingRecord.model_version`` (向后兼容默认 ``""``)
- 新增 ``load_pending_recommendations_with_version`` 返回 ``(recs, model_version)``,
  保持原 ``load_pending_recommendations`` API 不变
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from src.main import _build_auto_screening_payload, _compute_model_version
from src.screening.recommendation_tracker import (
    load_pending_recommendations,
    load_pending_recommendations_with_version,
    TrackingRecord,
    update_tracking_history,
)

# ---------------------------------------------------------------------------
# 1. _compute_model_version — git short sha 或 "unknown" 回退
# ---------------------------------------------------------------------------


def test_compute_model_version_returns_nonempty_string():
    """model_version 必须是非空字符串 (git sha 或 'unknown')。"""
    version = _compute_model_version()
    assert isinstance(version, str)
    assert version != ""


def test_compute_model_version_is_short_sha_or_unknown():
    """成功时返回 7 位 hex; 失败时返回 'unknown'。绝不抛异常。"""
    version = _compute_model_version()
    # git short sha = 7 位小写 hex; 回退 = "unknown"
    assert version == "unknown" or re.fullmatch(r"[0-9a-f]{7,40}", version), f"model_version 必须是 git short sha (hex) 或 'unknown', 实际: {version!r}"


def test_compute_model_version_never_raises(monkeypatch):
    """git subprocess 失败时绝不抛异常阻断主流程。"""

    def _raise(*args, **kwargs):
        raise OSError("git not available")

    monkeypatch.setattr("subprocess.run", _raise)
    version = _compute_model_version()
    assert version == "unknown"


# ---------------------------------------------------------------------------
# 2. _build_auto_screening_payload — 顶层包含 model_version
# ---------------------------------------------------------------------------


class _FakeMarketState:
    """最小 MarketState 替身 — 只需 model_dump()。"""

    def model_dump(self) -> dict:
        return {"state_type": "TREND", "regime_gate_level": "normal"}


def _build_minimal_payload(**overrides):
    """构造 _build_auto_screening_payload 所需的最小参数。"""
    defaults = dict(
        trade_date="20260623",
        top_n=3,
        market_state=_FakeMarketState(),
        candidates=[],
        fused=[],
        top_results_serializable=[
            {"ticker": "000001", "name": "PingAn", "score_b": 0.65},
        ],
        sector_warnings=[],
        consecutive_highlight=0,
        decay_summary={},
        industry_rotation_payload=[],
        batch_fetcher_use_batch=True,
        batch_fetcher_stats={"cached": 0, "fetched": 0},
    )
    defaults.update(overrides)
    return _build_auto_screening_payload(**defaults)


def test_build_payload_includes_model_version():
    """payload 顶层必须有非空 model_version 字段。"""
    payload = _build_minimal_payload()
    assert "model_version" in payload, "payload 缺少 model_version 字段"
    assert isinstance(payload["model_version"], str)
    assert payload["model_version"] != ""


def test_build_payload_model_version_matches_compute():
    """payload.model_version 与 _compute_model_version() 一致。"""
    payload = _build_minimal_payload()
    assert payload["model_version"] == _compute_model_version()


# ---------------------------------------------------------------------------
# 3. TrackingRecord — model_version 字段 + round-trip
# ---------------------------------------------------------------------------


def test_tracking_record_has_model_version_field_default_empty():
    """TrackingRecord 默认 model_version='' (向后兼容旧记录)。"""
    record = TrackingRecord(
        ticker="000001",
        name="PingAn",
        recommended_date="20260623",
        recommended_price=12.5,
        recommendation_score=0.65,
    )
    assert hasattr(record, "model_version")
    assert record.model_version == ""


def test_tracking_record_round_trip_preserves_model_version():
    """to_dict / from_dict round-trip 保留 model_version。"""
    record = TrackingRecord(
        ticker="000001",
        name="PingAn",
        recommended_date="20260623",
        recommended_price=12.5,
        recommendation_score=0.65,
        model_version="abc1234",
    )
    dumped = record.to_dict()
    assert dumped["model_version"] == "abc1234"

    restored = TrackingRecord.from_dict(dumped)
    assert restored.model_version == "abc1234"


def test_tracking_record_from_dict_missing_model_version_defaults_empty():
    """旧 tracking_history 记录无 model_version → from_dict 默认 ''。"""
    legacy_payload = {
        "ticker": "000001",
        "name": "PingAn",
        "recommended_date": "20260620",
        "recommended_price": 11.0,
        "recommendation_score": 0.5,
    }
    record = TrackingRecord.from_dict(legacy_payload)
    assert record.model_version == ""


# ---------------------------------------------------------------------------
# 4. load_pending_recommendations_with_version — 返回 (recs, version)
# ---------------------------------------------------------------------------


def _make_report_with_version(
    reports_dir: Path,
    date_str: str,
    recs: list[dict],
    *,
    model_version: str = "abc1234",
) -> Path:
    """写入带 model_version 顶层的 auto_screening 报告。"""
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


def test_load_pending_with_version_returns_tuple(tmp_path: Path):
    """新函数返回 (recs_list, model_version_str)。"""
    recs = [{"ticker": "000001", "name": "PingAn", "score_b": 0.65}]
    _make_report_with_version(tmp_path, "20260623", recs, model_version="deadbee")

    loaded_recs, version = load_pending_recommendations_with_version(tmp_path, "20260623")
    assert len(loaded_recs) == 1
    assert loaded_recs[0]["ticker"] == "000001"
    assert version == "deadbee"


def test_load_pending_with_version_missing_version_returns_empty_string(tmp_path: Path):
    """旧报告无 model_version 顶层 → 返回 (recs, '')。"""
    recs = [{"ticker": "000001", "name": "PingAn", "score_b": 0.65}]
    # 写入无 model_version 的旧格式报告
    path = tmp_path / "auto_screening_20260620.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"mode": "auto_screening", "date": "20260620", "recommendations": recs}, f)

    loaded_recs, version = load_pending_recommendations_with_version(tmp_path, "20260620")
    assert len(loaded_recs) == 1
    assert version == ""


def test_load_pending_with_version_no_report_returns_empty(tmp_path: Path):
    """报告不存在 → 返回 ([], '')。"""
    loaded_recs, version = load_pending_recommendations_with_version(tmp_path, "20260607")
    assert loaded_recs == []
    assert version == ""


def test_load_pending_recommendations_backward_compatible(tmp_path: Path):
    """原 load_pending_recommendations API 不变, 仍只返回 recs list。"""
    recs = [{"ticker": "000001", "name": "PingAn", "score_b": 0.65}]
    _make_report_with_version(tmp_path, "20260623", recs, model_version="abc1234")

    loaded = load_pending_recommendations(tmp_path, "20260623")
    assert isinstance(loaded, list)
    assert len(loaded) == 1


# ---------------------------------------------------------------------------
# 5. update_tracking_history — 把 payload 顶层 model_version 注入 TrackingRecord
# ---------------------------------------------------------------------------


def test_update_tracking_history_persists_model_version(tmp_path: Path):
    """update_tracking_history 把 payload.model_version 写入每条 TrackingRecord。"""
    recs = [
        {"ticker": "000001", "name": "PingAn", "score_b": 0.65, "close": 12.5},
        {"ticker": "600519", "name": "Maotai", "score_b": 0.55, "close": 1500.0},
    ]
    _make_report_with_version(tmp_path, "20260620", recs, model_version="cafef00")

    updated = update_tracking_history(
        tmp_path,
        trade_date="20260620",
        use_data_fetcher=lambda ticker, start, end: [],
    )
    assert updated == 2

    history_path = tmp_path / "tracking_history.json"
    with open(history_path, encoding="utf-8") as f:
        history = json.load(f)

    for record in history["records"]:
        assert record["model_version"] == "cafef00", f"TrackingRecord 缺少或 model_version 不匹配: {record}"


def test_update_tracking_history_missing_model_version_defaults_empty(tmp_path: Path):
    """旧报告无 model_version → TrackingRecord.model_version = ''。"""
    recs = [{"ticker": "000001", "name": "PingAn", "score_b": 0.65, "close": 12.5}]
    path = tmp_path / "auto_screening_20260620.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"mode": "auto_screening", "date": "20260620", "recommendations": recs}, f)

    update_tracking_history(
        tmp_path,
        trade_date="20260620",
        use_data_fetcher=lambda ticker, start, end: [],
    )

    history_path = tmp_path / "tracking_history.json"
    with open(history_path, encoding="utf-8") as f:
        history = json.load(f)

    assert history["records"][0]["model_version"] == ""
