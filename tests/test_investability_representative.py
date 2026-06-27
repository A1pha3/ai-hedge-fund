"""Tests for new investability.py functions — R20.40 representative candidates + front-door verdict."""
from __future__ import annotations

import pytest

from src.screening.investability import (
    _resolve_cluster_label,
    _safe_text,
    build_front_door_verdict,
    select_representative_candidates,
)

# ---------------------------------------------------------------------------
# Unit: _safe_text
# ---------------------------------------------------------------------------


class TestSafeText:
    def test_none(self) -> None:
        assert _safe_text(None) == ""

    def test_empty_string(self) -> None:
        assert _safe_text("") == ""

    def test_strips_whitespace(self) -> None:
        assert _safe_text("  hello  ") == "hello"

    def test_number(self) -> None:
        assert _safe_text(42) == "42"

    def test_zero(self) -> None:
        assert _safe_text(0) == ""  # 0 is falsy


# ---------------------------------------------------------------------------
# Unit: _resolve_cluster_label
# ---------------------------------------------------------------------------


class TestResolveClusterLabel:
    def test_industry_sw(self) -> None:
        kind, label = _resolve_cluster_label({"industry_sw": "电子"})
        assert kind == "industry"
        assert label == "电子"

    def test_industry_fallback(self) -> None:
        kind, label = _resolve_cluster_label({"industry": "银行"})
        assert kind == "industry"
        assert label == "银行"

    def test_concept_string(self) -> None:
        kind, label = _resolve_cluster_label({"concept": "新能源"})
        assert kind == "concept"
        assert label == "新能源"

    def test_concepts_list(self) -> None:
        kind, label = _resolve_cluster_label({"concepts": ["AI", "芯片"]})
        assert kind == "concept"
        assert label == "AI"  # sorted alphabetically

    def test_fallback_to_ticker(self) -> None:
        kind, label = _resolve_cluster_label({"ticker": "000001"})
        assert kind == "ticker"
        assert label == "000001"

    def test_empty_concepts_list(self) -> None:
        kind, label = _resolve_cluster_label({"concepts": []})
        assert kind == "ticker"

    def test_industry_priority_over_concept(self) -> None:
        kind, label = _resolve_cluster_label({"industry_sw": "电子", "concept": "新能源"})
        assert kind == "industry"
        assert label == "电子"


# ---------------------------------------------------------------------------
# Unit: select_representative_candidates
# ---------------------------------------------------------------------------


class TestSelectRepresentativeCandidates:
    def test_empty(self) -> None:
        assert select_representative_candidates([], count=5) == []

    def test_count_zero(self) -> None:
        assert select_representative_candidates([{"ticker": "A"}], count=0) == []

    def test_single(self) -> None:
        recs = [{"ticker": "000001", "industry_sw": "银行", "score_b": 0.5}]
        result = select_representative_candidates(recs, count=5)
        assert len(result) == 1
        assert result[0]["ticker"] == "000001"
        assert result[0]["cluster_label"] == "银行"

    def test_dedup_by_industry(self) -> None:
        """Two stocks from same industry — first pass gives 1, backfill adds the other."""
        recs = [
            {"ticker": "000001", "industry_sw": "银行", "score_b": 0.6},
            {"ticker": "600000", "industry_sw": "银行", "score_b": 0.5},
            {"ticker": "300750", "industry_sw": "电气设备", "score_b": 0.4},
        ]
        result = select_representative_candidates(recs, count=3)
        # First pass: 1 per cluster = 2 (银行 + 电气设备)
        # Backfill: B (different ticker) = 3 total
        assert len(result) == 3
        tickers = [r["ticker"] for r in result]
        assert "000001" in tickers  # Representative from 银行
        assert "300750" in tickers  # From 电气设备
        assert "600000" in tickers  # Backfilled
        # First representative should show cluster metadata
        bank_rep = next(r for r in result if r["ticker"] == "000001")
        assert bank_rep["cluster_size"] == 2
        assert "600000" in bank_rep["cluster_alternatives"]

    def test_no_dedup_different_industries(self) -> None:
        recs = [
            {"ticker": "A", "industry_sw": "电子"},
            {"ticker": "B", "industry_sw": "银行"},
            {"ticker": "C", "industry_sw": "医药"},
        ]
        result = select_representative_candidates(recs, count=3)
        assert len(result) == 3

    def test_count_limit(self) -> None:
        recs = [
            {"ticker": f"T{i}", "industry_sw": f"行业{i}"}
            for i in range(10)
        ]
        result = select_representative_candidates(recs, count=3)
        assert len(result) == 3

    def test_cluster_metadata(self) -> None:
        recs = [
            {"ticker": "A", "industry_sw": "电子"},
            {"ticker": "B", "industry_sw": "电子"},
        ]
        result = select_representative_candidates(recs, count=5)
        assert len(result) == 2  # First pass: 1, backfill: 1
        rep = result[0]
        assert rep["cluster_kind"] == "industry"
        assert rep["cluster_label"] == "电子"
        assert rep["cluster_size"] == 2
        assert rep["is_cluster_representative"] is True
        assert rep["cluster_alternatives"] == ["B"]

    def test_backfill(self) -> None:
        """After unique clusters are exhausted, backfill remaining."""
        recs = [
            {"ticker": "A", "industry_sw": "电子"},
            {"ticker": "B", "industry_sw": "电子"},  # Same cluster, different ticker
            {"ticker": "C", "industry_sw": "银行"},
        ]
        result = select_representative_candidates(recs, count=3)
        # First pass: A (电子) + C (银行) = 2
        # Backfill: B (already in A's cluster, but ticker not in selected_tickers)
        assert len(result) == 3
        tickers = [r["ticker"] for r in result]
        assert "A" in tickers
        assert "B" in tickers
        assert "C" in tickers


# ---------------------------------------------------------------------------
# Unit: build_front_door_verdict
# ---------------------------------------------------------------------------


class TestBuildFrontDoorVerdict:
    def _high_quality_rec(self) -> dict:
        return {
            "decision": "bullish",
            "composite_score": 0.6,
            "score_b": 0.5,
            # C219: BUY gate 用 T+5 OR T+10, 需提供 t5/t10 强信号让 BUY 通过
            "expected_returns": {"t5": 0.05, "t10": 0.05, "t30": 0.05},
            "win_rates": {"t5": 0.6, "t10": 0.6, "t30": 0.6},
            "bucket_sample_count": 50,
        }

    def _watchable_rec(self) -> dict:
        return {
            "decision": "bullish",
            "composite_score": 0.3,
            "score_b": 0.25,
            # C219: is_watchable 用 T+5 OR T+10 (winrate>=0.5, edge>=0),
            # 需提供 t5/t10 watchable 信号让 HOLD 通过 (winrate 0.52 >= 0.5)
            "expected_returns": {"t5": 0.01, "t10": 0.01, "t30": 0.01},
            "win_rates": {"t5": 0.52, "t10": 0.52, "t30": 0.52},
            "bucket_sample_count": 30,
        }

    def _weak_rec(self) -> dict:
        return {
            "decision": "bearish",
            "composite_score": 0.1,
            "score_b": 0.05,
            "expected_returns": {"t30": -0.02},
            "win_rates": {"t30": 0.4},
            "bucket_sample_count": 5,
        }

    def test_buy_normal_market(self) -> None:
        v = build_front_door_verdict(self._high_quality_rec(), market_regime="normal")
        assert v["action"] == "BUY"

    def test_hold_watchable(self) -> None:
        v = build_front_door_verdict(self._watchable_rec(), market_regime="normal")
        assert v["action"] == "HOLD"

    def test_avoid_weak(self) -> None:
        v = build_front_door_verdict(self._weak_rec(), market_regime="normal")
        assert v["action"] == "AVOID"

    def test_crisis_downgrades_buy_to_hold(self) -> None:
        v = build_front_door_verdict(self._high_quality_rec(), market_regime="crisis")
        assert v["action"] == "HOLD"  # Even high quality is HOLD in crisis
        assert "risk-off" in v["invalidation_reason"]

    def test_crisis_weak_becomes_avoid(self) -> None:
        v = build_front_door_verdict(self._weak_rec(), market_regime="risk_off")
        assert v["action"] == "AVOID"

    def test_momentum_negative(self) -> None:
        rec = self._high_quality_rec()
        rec["momentum_bonus"] = -0.05
        v = build_front_door_verdict(rec, market_regime="normal")
        assert "动量转负" in v["invalidation_reason"]

    def test_sector_negative(self) -> None:
        rec = self._high_quality_rec()
        rec["sector_bonus"] = -0.03
        v = build_front_door_verdict(rec, market_regime="normal")
        assert "行业转弱" in v["invalidation_reason"]

    def test_invalidation_dedup(self) -> None:
        """Reasons should be deduplicated."""
        rec = self._high_quality_rec()
        rec["momentum_bonus"] = -0.05
        v = build_front_door_verdict(rec, market_regime="normal")
        # Check no duplicates in reason list
        reasons = v["invalidation_reason"].split(" / ")
        assert len(reasons) == len(set(reasons))

    def test_low_sample_count(self) -> None:
        rec = self._high_quality_rec()
        rec["bucket_sample_count"] = 10
        v = build_front_door_verdict(rec, market_regime="normal")
        assert "样本量不足 20" in v["invalidation_reason"]

    def test_win_rate_below_50(self) -> None:
        rec = self._high_quality_rec()
        rec["win_rates"] = {"t30": 0.45}
        v = build_front_door_verdict(rec, market_regime="normal")
        assert "胜率跌破 50%" in v["invalidation_reason"]
