"""P0-6 多日推荐聚合 — 连续推荐标记与稳定性加权单元测试"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.screening.consecutive_recommendation import (
    RecommendationStatus,
    ConsecutiveStats,
    compute_consecutive_recommendations,
    enrich_recommendations_with_history,
    load_auto_screening_history,
    resolve_report_dir,
)

# ============================================================================
# Helpers
# ============================================================================


def _write_auto_report(
    report_dir: Path,
    date_str: str,
    tickers: list[str],
    score_b: float = 0.5,
) -> Path:
    """写入一个最小可用的 auto_screening_{date}.json 文件。"""
    report_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "mode": "auto_screening",
        "date": date_str,
        "market_state": {"state_type": "mixed", "position_scale": 1.0},
        "layer_a_count": 100,
        "total_scored": 50,
        "high_pool_count": 10,
        "top_n": len(tickers),
        "recommendations": [
            {
                "ticker": t,
                "name": t,
                "industry_sw": "test",
                "score_b": score_b,
                "decision": "watch",
                "strategy_signals": {},
                "metrics": {},
                "arbitration_applied": [],
            }
            for t in tickers
        ],
        "sector_concentration_warnings": [],
    }
    out = report_dir / f"auto_screening_{date_str}.json"
    out.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return out


# ============================================================================
# Empty / single-day history
# ============================================================================


def test_empty_history_returns_empty_mapping(tmp_path: Path) -> None:
    """空历史目录：返回空映射。"""
    result = compute_consecutive_recommendations(
        lookback_days=3,
        report_dir=tmp_path,
        end_date="20260607",
    )
    assert result == {}


def test_single_day_history_first_appearance(tmp_path: Path) -> None:
    """只有当前日期的历史：所有标的为「首次出现」。"""
    _write_auto_report(tmp_path, "20260607", ["000001", "000002"])

    result = compute_consecutive_recommendations(
        lookback_days=3,
        report_dir=tmp_path,
        end_date="20260607",
    )

    # 仅有今天一天
    assert set(result.keys()) == {"000001", "000002"}
    for stats in result.values():
        assert stats.consecutive_days == 1
        assert stats.status == RecommendationStatus.FIRST_APPEARANCE
        assert stats.stability_bonus == 0.0


# ============================================================================
# Three consecutive days
# ============================================================================


def test_three_consecutive_days_bonus(tmp_path: Path) -> None:
    """连续 3 天推荐：stability_bonus 应为最高档 (10.0)。"""
    _write_auto_report(tmp_path, "20260605", ["000001", "000002"])
    _write_auto_report(tmp_path, "20260606", ["000001", "000002"])
    _write_auto_report(tmp_path, "20260607", ["000001", "000002"])

    result = compute_consecutive_recommendations(
        lookback_days=3,
        report_dir=tmp_path,
        end_date="20260607",
    )

    for ticker in ("000001", "000002"):
        stats = result[ticker]
        assert stats.consecutive_days == 3
        assert stats.status == RecommendationStatus.CONSECUTIVE_3PLUS
        assert stats.stability_bonus == 10.0
        # 历史应包含最近 3 天
        assert stats.recommendation_history == [
            {"date": "20260605", "score_b": 0.5},
            {"date": "20260606", "score_b": 0.5},
            {"date": "20260607", "score_b": 0.5},
        ]


def test_four_plus_consecutive_days_caps_at_max_bonus(tmp_path: Path) -> None:
    """连续 4+ 天：streak 可超过 3，但 bonus 上限为 10.0。"""
    _write_auto_report(tmp_path, "20260604", ["000001"])
    _write_auto_report(tmp_path, "20260605", ["000001"])
    _write_auto_report(tmp_path, "20260606", ["000001"])
    _write_auto_report(tmp_path, "20260607", ["000001"])

    result = compute_consecutive_recommendations(
        lookback_days=3,
        report_dir=tmp_path,
        end_date="20260607",
    )
    stats = result["000001"]
    # 当前 3 天窗口内连续 3 天 + 历史已超 3，streak 至少为 3
    assert stats.consecutive_days >= 3
    assert stats.stability_bonus == 10.0
    assert stats.status == RecommendationStatus.CONSECUTIVE_3PLUS


# ============================================================================
# Broken streak
# ============================================================================


def test_broken_streak_with_gap(tmp_path: Path) -> None:
    """中间断档：连续天数重置为 1。"""
    # 000001 在 06-05 出现，但 06-06 缺失，06-07 出现
    _write_auto_report(tmp_path, "20260605", ["000001", "000002"])
    _write_auto_report(tmp_path, "20260606", ["000002"])  # 000001 缺失
    _write_auto_report(tmp_path, "20260607", ["000001", "000002"])

    result = compute_consecutive_recommendations(
        lookback_days=3,
        report_dir=tmp_path,
        end_date="20260607",
    )

    # 000001: 06-05 出现 (score_b=0.5>=0.3) -> 06-06 断 -> 06-07 出现 (score_b=0.5>=0.3)
    # P4-2: 历史 score_b >= 0.3, 重返 → REENTRY_SIGNAL (bonus=5.0)
    stats_001 = result["000001"]
    assert stats_001.consecutive_days == 1
    assert stats_001.status == RecommendationStatus.REENTRY_SIGNAL
    assert stats_001.stability_bonus == 5.0
    # 000002 连续 3 天
    stats_002 = result["000002"]
    assert stats_002.consecutive_days == 3
    assert stats_002.status == RecommendationStatus.CONSECUTIVE_3PLUS


def test_two_consecutive_days_mid_bonus(tmp_path: Path) -> None:
    """连续 2 天：中等 bonus (3.0)。"""
    _write_auto_report(tmp_path, "20260606", ["000001"])
    _write_auto_report(tmp_path, "20260607", ["000001"])

    result = compute_consecutive_recommendations(
        lookback_days=3,
        report_dir=tmp_path,
        end_date="20260607",
    )
    stats = result["000001"]
    assert stats.consecutive_days == 2
    assert stats.stability_bonus == 3.0
    assert stats.status == RecommendationStatus.CONSECUTIVE_2DAYS


# ============================================================================
# Configuration change
# ============================================================================


def test_lookback_window_5_days(tmp_path: Path) -> None:
    """配置变更：lookback_days=5, 5 天连续都出现则 streak=5。"""
    for d in ("20260603", "20260604", "20260605", "20260606", "20260607"):
        _write_auto_report(tmp_path, d, ["000001"])

    result = compute_consecutive_recommendations(
        lookback_days=5,
        report_dir=tmp_path,
        end_date="20260607",
    )
    stats = result["000001"]
    assert stats.consecutive_days == 5
    assert stats.stability_bonus == 10.0
    assert stats.status == RecommendationStatus.CONSECUTIVE_3PLUS
    assert len(stats.recommendation_history) == 5


def test_lookback_window_excludes_too_old_reports(tmp_path: Path) -> None:
    """超 lookback 窗口的报告应被忽略。"""
    # 6 天前 (超出 lookback=3)
    _write_auto_report(tmp_path, "20260601", ["000001"])
    _write_auto_report(tmp_path, "20260605", ["000001"])
    _write_auto_report(tmp_path, "20260606", ["000001"])
    _write_auto_report(tmp_path, "20260607", ["000001"])

    result = compute_consecutive_recommendations(
        lookback_days=3,
        report_dir=tmp_path,
        end_date="20260607",
    )
    stats = result["000001"]
    # 窗口内连续 3 天 (06-05/06/07)
    assert stats.consecutive_days == 3
    assert len(stats.recommendation_history) == 3


# ============================================================================
# load_auto_screening_history
# ============================================================================


def test_load_history_returns_all_reports_in_window(tmp_path: Path) -> None:
    """load_auto_screening_history 应按日期降序返回窗口内所有报告。"""
    for d in ("20260605", "20260606", "20260607"):
        _write_auto_report(tmp_path, d, [f"TS{d}"])

    history = load_auto_screening_history(
        lookback_days=3,
        report_dir=tmp_path,
        end_date="20260607",
    )
    assert len(history) == 3
    # 降序
    assert [r["date"] for r in history] == ["20260607", "20260606", "20260605"]


def test_load_history_ignores_malformed_files(tmp_path: Path) -> None:
    """损坏的 JSON 文件应被忽略而非崩溃。"""
    _write_auto_report(tmp_path, "20260605", ["000001"])
    _write_auto_report(tmp_path, "20260606", ["000001"])
    bad = tmp_path / "auto_screening_20260607.json"
    bad.write_text("not valid json{{{", encoding="utf-8")

    history = load_auto_screening_history(
        lookback_days=3,
        report_dir=tmp_path,
        end_date="20260607",
    )
    # 仅 2 个有效报告
    assert len(history) == 2
    dates = [r["date"] for r in history]
    assert "20260605" in dates and "20260606" in dates


# ============================================================================
# resolve_report_dir
# ============================================================================


def test_resolve_report_dir_finds_data_reports(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """resolve_report_dir 应在 data/reports 下找到 auto_screening_*.json。"""
    reports = tmp_path / "data" / "reports"
    reports.mkdir(parents=True)
    _write_auto_report(reports, "20260607", ["000001"])

    # monkeypatch cwd -> tmp_path
    monkeypatch.chdir(tmp_path)
    result = resolve_report_dir()
    assert result == reports


# ============================================================================
# enrich_recommendations_with_history
# ============================================================================


def test_enrich_adds_fields_in_place(tmp_path: Path) -> None:
    """enrich_recommendations_with_history 应在每个 result 上添加连续推荐字段。"""
    _write_auto_report(tmp_path, "20260605", ["000001", "000002"])
    _write_auto_report(tmp_path, "20260606", ["000001", "000002"])
    _write_auto_report(tmp_path, "20260607", ["000001", "000002"])

    recommendations = [
        {
            "ticker": "000001",
            "name": "AAA",
            "score_b": 0.5,
            "decision": "watch",
        },
        {
            "ticker": "000002",
            "name": "BBB",
            "score_b": 0.6,
            "decision": "strong_buy",
        },
    ]

    enriched = enrich_recommendations_with_history(
        recommendations=recommendations,
        lookback_days=3,
        report_dir=tmp_path,
        end_date="20260607",
    )

    assert len(enriched) == 2
    for rec in enriched:
        assert "consecutive_days" in rec
        assert "recommendation_history" in rec
        assert "stability_bonus" in rec
        assert rec["consecutive_days"] == 3
        assert rec["stability_bonus"] == 10.0


def test_enrich_unknown_ticker_gets_zero_bonus(tmp_path: Path) -> None:
    """历史中不存在的 ticker 应得 0 bonus, 首次出现状态。"""
    _write_auto_report(tmp_path, "20260607", ["000001"])

    recommendations = [
        {"ticker": "999999", "score_b": 0.5, "decision": "watch"},
    ]

    enriched = enrich_recommendations_with_history(
        recommendations=recommendations,
        lookback_days=3,
        report_dir=tmp_path,
        end_date="20260607",
    )
    rec = enriched[0]
    assert rec["consecutive_days"] == 0
    assert rec["stability_bonus"] == 0.0
    assert rec["recommendation_history"] == []


# ============================================================================
# ConsecutiveStats shape
# ============================================================================


def test_consecutive_stats_dataclass_fields() -> None:
    """ConsecutiveStats 应包含规定字段。"""
    stats = ConsecutiveStats(
        ticker="000001",
        consecutive_days=3,
        status=RecommendationStatus.CONSECUTIVE_3PLUS,
        recommendation_history=[{"date": "20260607", "score_b": 0.5}],
        stability_bonus=10.0,
    )
    assert stats.ticker == "000001"
    assert stats.consecutive_days == 3
    assert stats.status == RecommendationStatus.CONSECUTIVE_3PLUS
    assert stats.stability_bonus == 10.0
    assert isinstance(stats.recommendation_history, list)


def test_status_enum_values() -> None:
    """RecommendationStatus 应有 5 个枚举值 (含 P4-2 reentry_signal)。"""
    expected = {"first_appearance", "consecutive_2days", "consecutive_3plus", "broken_streak", "reentry_signal"}
    actual = {s.value for s in RecommendationStatus}
    assert actual == expected


# ============================================================================
# Robustness — None/malformed recommendation entries
# ============================================================================


def test_compute_skips_none_recommendation_entries(tmp_path: Path) -> None:
    """报告中的 None 推荐条目应被跳过, 不应触发 AttributeError。"""
    # Manually craft a report payload with a None entry mixed in to simulate corruption.
    payload = {
        "mode": "auto_screening",
        "date": "20260607",
        "recommendations": [
            {"ticker": "000001", "score_b": 0.5},
            None,
            {"ticker": "000002", "score_b": 0.4},
        ],
    }
    (tmp_path / "auto_screening_20260607.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )

    # Must not raise AttributeError.
    result = compute_consecutive_recommendations(
        lookback_days=3,
        report_dir=tmp_path,
        end_date="20260607",
    )
    assert set(result.keys()) == {"000001", "000002"}


def test_score_b_none_is_coerced_to_zero(tmp_path: Path) -> None:
    """``score_b`` 为 None 时应被强制归零, 避免污染下游消费者。"""
    payload = {
        "mode": "auto_screening",
        "date": "20260607",
        "recommendations": [
            {"ticker": "000001", "score_b": None},
        ],
    }
    (tmp_path / "auto_screening_20260607.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )

    result = compute_consecutive_recommendations(
        lookback_days=3,
        report_dir=tmp_path,
        end_date="20260607",
    )
    history = result["000001"].recommendation_history
    assert history == [{"date": "20260607", "score_b": 0.0}]


def test_score_b_nan_is_coerced_to_zero(tmp_path: Path) -> None:
    """``score_b`` 为 NaN/非数值时应被强制归零。"""
    # NaN cannot be encoded in standard JSON, so we inject via dict after parsing.
    # The function reads via json.loads which will accept NaN if allow_nan=True (default).
    payload_text = (
        '{"mode": "auto_screening", "date": "20260607", '
        '"recommendations": [{"ticker": "000001", "score_b": NaN}]}'
    )
    (tmp_path / "auto_screening_20260607.json").write_text(payload_text, encoding="utf-8")

    result = compute_consecutive_recommendations(
        lookback_days=3,
        report_dir=tmp_path,
        end_date="20260607",
    )
    history = result["000001"].recommendation_history
    assert history == [{"date": "20260607", "score_b": 0.0}]


# ============================================================================
# P4-2: Re-entry signal tests
# ============================================================================


class TestReentrySignal:
    """P4-2: 智能再入场信号 — 曾被推荐后消失又重返的标的。"""

    def test_reentry_detected_with_high_historical_score(self, tmp_path: Path) -> None:
        """标的 D1 出现 (score_b=0.5), D2 消失, D3 再出现 (score_b=0.4) → REENTRY_SIGNAL。"""
        _write_auto_report(tmp_path, "20260605", ["000001"], score_b=0.5)
        # D2: 000001 不在推荐中
        _write_auto_report(tmp_path, "20260606", ["000002"], score_b=0.3)
        _write_auto_report(tmp_path, "20260607", ["000001"], score_b=0.4)

        result = compute_consecutive_recommendations(
            lookback_days=3,
            report_dir=tmp_path,
            end_date="20260607",
        )
        assert result["000001"].status == RecommendationStatus.REENTRY_SIGNAL
        assert result["000001"].stability_bonus == 5.0

    def test_broken_streak_low_historical_score_not_reentry(self, tmp_path: Path) -> None:
        """D1 score_b=0.2 (低于 0.3 阈值), D2 消失, D3 返回 (score_b=0.2) → 仍为 BROKEN_STREAK。"""
        _write_auto_report(tmp_path, "20260605", ["000001"], score_b=0.2)
        _write_auto_report(tmp_path, "20260606", ["000002"], score_b=0.3)
        _write_auto_report(tmp_path, "20260607", ["000001"], score_b=0.2)

        result = compute_consecutive_recommendations(
            lookback_days=3,
            report_dir=tmp_path,
            end_date="20260607",
        )
        assert result["000001"].status == RecommendationStatus.BROKEN_STREAK
        assert result["000001"].stability_bonus == 0.0

    def test_consecutive_not_reentry(self, tmp_path: Path) -> None:
        """连续推荐 (D1+D2+D3) → CONSECUTIVE_3PLUS, 不是 reentry。"""
        _write_auto_report(tmp_path, "20260605", ["000001"], score_b=0.5)
        _write_auto_report(tmp_path, "20260606", ["000001"], score_b=0.5)
        _write_auto_report(tmp_path, "20260607", ["000001"], score_b=0.5)

        result = compute_consecutive_recommendations(
            lookback_days=3,
            report_dir=tmp_path,
            end_date="20260607",
        )
        assert result["000001"].status == RecommendationStatus.CONSECUTIVE_3PLUS
        assert result["000001"].stability_bonus == 10.0

    def test_reentry_only_one_appearance_no_history(self, tmp_path: Path) -> None:
        """仅 1 天出现 → FIRST_APPEARANCE, 不会触发 reentry。"""
        _write_auto_report(tmp_path, "20260607", ["000001"], score_b=0.5)

        result = compute_consecutive_recommendations(
            lookback_days=3,
            report_dir=tmp_path,
            end_date="20260607",
        )
        assert result["000001"].status == RecommendationStatus.FIRST_APPEARANCE

    def test_reentry_bonus_between_first_and_consecutive(self, tmp_path: Path) -> None:
        """Reentry bonus (5.0) 应介于首次出现 (0.0) 和连续3天 (10.0) 之间。"""
        _write_auto_report(tmp_path, "20260605", ["000001"], score_b=0.5)
        _write_auto_report(tmp_path, "20260606", ["000002"], score_b=0.3)
        _write_auto_report(tmp_path, "20260607", ["000001"], score_b=0.4)

        result = compute_consecutive_recommendations(
            lookback_days=3,
            report_dir=tmp_path,
            end_date="20260607",
        )
        bonus = result["000001"].stability_bonus
        assert 0.0 < bonus < 10.0  # 介于首次和连续之间


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
