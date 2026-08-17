"""R53: surface ``days_since_peak`` in the table decay tag (--top v3 迁移后)。

``DecayInfo.days_since_peak`` (how many days since the ticker's score peaked)
is computed by ``signal_decay_detector`` and serialized into the report;
``--top`` 现复用 v3 行构造器 ``_build_auto_screening_table_row`` + 
``_decay_map_from_recs`` 形状适配 (2026-08-16 迁移)。R53 契约不变: 早期衰减
(↓20% 1天) 与晚期衰减 (↓20% 5天) 必须可区分。

行为变化 (v3): 旧 ``_build_top_table_row`` 对 ``score_b=None`` 渲染 0.0;
新路径按 FusedScore 校验失败**跳行 + 警告** — 报告 JSON 来自自身 dump,
坏行不该被静默补零渲染 (bucket 分组也依赖 score_b)。
"""

from __future__ import annotations

import pytest

from src.main import _build_auto_screening_table_row, _decay_map_from_recs, _front_door_cell
from src.screening.models import FusedScore, StrategySignal
from src.screening.signal_decay_detector import DecayLevel


def _item(ticker: str = "000001") -> FusedScore:
    return FusedScore(
        ticker=ticker,
        name="测试",
        industry_sw="银行",
        score_b=0.5,
        strategy_signals={
            "trend": StrategySignal(direction=1, confidence=50.0, completeness=1.0, sub_factors={}),
        },
    )


def _render(decay: dict) -> list:
    rec = {"ticker": "000001", "decay": decay}
    item = _item()
    row = _build_auto_screening_table_row(
        idx=1,
        item=item,
        consecutive_lookup={"000001": rec},
        decay_map=_decay_map_from_recs([rec]),
        composite_score=0.48,
    )
    return row


class TestDecayTagR53:
    def test_decay_tag_shows_days_since_peak(self) -> None:
        """R53: decaying pick must surface days_since_peak in the decay cell."""
        row = _render({"level": "moderate", "change_pct": -20.0, "days_since_peak": 5})
        decay_cell = row[6]
        assert "(5天)" in decay_cell, f"Expected '(5天)' in decay cell, got: {decay_cell!r}"
        assert "20%" in decay_cell

    def test_decay_tag_omits_days_when_at_peak(self) -> None:
        """days_since_peak=0 (today IS the peak) must not append a days tag."""
        row = _render({"level": "mild", "change_pct": -5.0, "days_since_peak": 0})
        decay_cell = row[6]
        assert "(0天)" not in decay_cell
        assert "5%" in decay_cell

    def test_decay_none_shows_dash(self) -> None:
        row = _render({"level": "none", "change_pct": None, "days_since_peak": 0})
        decay_cell = row[6]
        assert "↓" not in decay_cell
        assert "—" in decay_cell


class TestDecayMapFromRecs:
    def test_invalid_level_skipped_not_crash(self) -> None:
        recs = [{"ticker": "000001", "decay": {"level": "非枚举值", "change_pct": -1.0}}]
        assert _decay_map_from_recs(recs) == {}

    def test_missing_decay_skipped(self) -> None:
        assert _decay_map_from_recs([{"ticker": "000001"}]) == {}

    def test_maps_to_decay_level(self) -> None:
        out = _decay_map_from_recs([{"ticker": "000001", "decay": {"level": "severe", "change_pct": -30.0, "days_since_peak": 2}}])
        assert out["000001"].level is DecayLevel.SEVERE


class TestFrontDoorCell:
    def test_three_actions_labeled(self, monkeypatch) -> None:
        import src.main as main_mod

        for action, label in (("BUY", "买入"), ("HOLD", "持有"), ("AVOID", "回避")):
            monkeypatch.setattr(
                "src.screening.investability.build_front_door_verdict",
                lambda *a, **k: {"action": action},
            )
            assert label in _front_door_cell({}, "normal")

    def test_junk_rec_never_raises(self) -> None:
        cell = _front_door_cell({"ticker": "000001"}, "normal")
        assert isinstance(cell, str) and cell  # 回避 或 不可用 — 均不崩溃
