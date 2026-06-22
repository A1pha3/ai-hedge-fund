"""Tests for src/screening/position_health.py — P15-1 持仓健康检查."""

from __future__ import annotations

import pytest

from src.screening.position_health import (
    _action_colored,
    _determine_action,
    _find_ticker_in_history,
    PositionHealth,
    PositionHealthReport,
    render_position_health,
)
from src.utils.display import Fore, Style

# ---------------------------------------------------------------------------
# _determine_action
# ---------------------------------------------------------------------------


class TestDetermineAction:
    def test_sell(self) -> None:
        action, reason = _determine_action(0.10, 0.0, 0.0, sell_threshold=0.15, watch_threshold=0.30)
        assert action == "SELL"
        assert "sell_threshold" in reason

    def test_watch(self) -> None:
        action, reason = _determine_action(0.20, 0.0, 0.0, sell_threshold=0.15, watch_threshold=0.30)
        assert action == "WATCH"
        assert "watch zone" in reason

    def test_hold(self) -> None:
        action, reason = _determine_action(0.50, 0.0, 0.0, sell_threshold=0.15, watch_threshold=0.30)
        assert action == "HOLD"

    def test_hold_deteriorating_signals(self) -> None:
        """Negative momentum + negative trend → WATCH even with good composite."""
        action, reason = _determine_action(0.50, -0.10, -0.05, sell_threshold=0.15, watch_threshold=0.30)
        assert action == "WATCH"
        assert "衰减" in reason

    def test_boundary_sell(self) -> None:
        """Exactly at sell_threshold → not SELL (must be < threshold)."""
        action, _ = _determine_action(0.15, 0.0, 0.0, sell_threshold=0.15, watch_threshold=0.30)
        assert action == "WATCH"  # 0.15 >= 0.15 but < 0.30

    def test_boundary_watch(self) -> None:
        """Exactly at watch_threshold → HOLD (must be < threshold for WATCH)."""
        action, _ = _determine_action(0.30, 0.0, 0.0, sell_threshold=0.15, watch_threshold=0.30)
        assert action == "HOLD"

    def test_momentum_only_not_enough(self) -> None:
        """Negative momentum alone (with good trend) → still HOLD."""
        action, _ = _determine_action(0.50, -0.10, 0.05, sell_threshold=0.15, watch_threshold=0.30)
        assert action == "HOLD"


# ---------------------------------------------------------------------------
# _find_ticker_in_history
# ---------------------------------------------------------------------------


class TestFindTickerInHistory:
    def test_found(self) -> None:
        history = [
            {"payload": {"recommendations": [{"ticker": "000001", "score_b": 0.5}]}},
        ]
        result = _find_ticker_in_history("000001", history)
        assert result is not None
        assert result["ticker"] == "000001"

    def test_not_found(self) -> None:
        history = [
            {"payload": {"recommendations": [{"ticker": "000002", "score_b": 0.5}]}},
        ]
        assert _find_ticker_in_history("000001", history) is None

    def test_empty_history(self) -> None:
        assert _find_ticker_in_history("000001", []) is None

    def test_first_match_wins(self) -> None:
        history = [
            {"payload": {"recommendations": [{"ticker": "000001", "score_b": 0.5}]}},
            {"payload": {"recommendations": [{"ticker": "000001", "score_b": 0.3}]}},
        ]
        result = _find_ticker_in_history("000001", history)
        assert result["score_b"] == 0.5


# ---------------------------------------------------------------------------
# PositionHealth / PositionHealthReport
# ---------------------------------------------------------------------------


class TestPositionHealth:
    def test_defaults(self) -> None:
        ph = PositionHealth(ticker="000001")
        assert ph.action == "HOLD"
        assert ph.composite_score == 0.0


class TestPositionHealthReport:
    def test_empty(self) -> None:
        report = PositionHealthReport()
        assert report.items == []

    def test_to_dict(self) -> None:
        report = PositionHealthReport(
            trade_date="2026-01-01",
            items=[
                PositionHealth(ticker="000001", name="平安", composite_score=0.5, action="HOLD", reason="OK"),
            ],
        )
        d = report.to_dict()
        assert d["trade_date"] == "2026-01-01"
        assert d["items"][0]["action"] == "HOLD"


# ---------------------------------------------------------------------------
# render_position_health
# ---------------------------------------------------------------------------


class TestRenderPositionHealth:
    def test_empty(self) -> None:
        result = render_position_health(PositionHealthReport())
        assert "无持仓数据" in result

    def test_with_items(self) -> None:
        report = PositionHealthReport(
            trade_date="2026-01-01",
            items=[
                PositionHealth(ticker="000001", name="平安", composite_score=0.5, action="HOLD", reason="健康"),
                PositionHealth(ticker="000002", name="万科", composite_score=0.1, action="SELL", reason="低分"),
            ],
        )
        result = render_position_health(report)
        assert "000001" in result
        assert "SELL" in result
        assert "HOLD" in result

    def test_signed_factor_coloring(self) -> None:
        """Lock the +/-/0 coloring of momentum/trend/volume factors so the
        _fmt closure can be safely hoisted out of the render loop (R91 refactor)."""
        report = PositionHealthReport(
            trade_date="2026-01-01",
            items=[
                PositionHealth(
                    ticker="000001", name="A", composite_score=0.5,
                    momentum_bonus=0.12, trend_resonance_factor=-0.08, volume_factor=0.0,
                    action="HOLD", reason="ok",
                ),
            ],
        )
        result = render_position_health(report)
        # positive → green "+", negative → red, zero → "0.00"
        assert "+0.12" in result
        assert "-0.08" in result
        assert "0.00" in result

    def test_degraded_report_shows_trust_banner(self) -> None:
        """R92 product-quality: a degraded report must render a user-visible trust
        banner so the user knows scores are unreliable (not a real 'all zero')."""
        report = PositionHealthReport(
            trade_date="2026-01-01",
            degraded=True,
            items=[
                PositionHealth(ticker="000001", name="A", composite_score=0.0, action="HOLD"),
            ],
        )
        result = render_position_health(report)
        assert "降级" in result or "degraded" in result.lower() or "不可靠" in result or " unreliable" in result.lower()


# ---------------------------------------------------------------------------
# compute_position_health (end-to-end, no reports → empty)
# ---------------------------------------------------------------------------


class TestComputePositionHealth:
    def test_no_reports_returns_empty(self, tmp_path) -> None:
        from src.screening.position_health import compute_position_health

        report = compute_position_health(tickers=["000001"], reports_dir=tmp_path)
        assert report.items == []

    def _seed_report(self, tmp_path) -> None:
        """Seed one auto_screening report so held_recs is non-empty and the
        composite/momentum/trend/volume compute branches are reached.
        Filename must match ``auto_screening_YYYYMMDD.json`` (see
        consecutive_recommendation._REPORT_FILENAME_PATTERN)."""
        import json

        report = {
            "date": "20260102",
            "recommendations": [
                {"ticker": "000001", "name": "平安", "score_b": 0.5},
            ],
        }
        (tmp_path / "auto_screening_20260102.json").write_text(
            json.dumps(report), encoding="utf-8"
        )

    def test_silent_compute_failure_logs_warning(self, tmp_path, monkeypatch, caplog) -> None:
        """R89 BH-017 silent-crash residue: if compute_composite_scores_for_recommendations
        raises (provider/cache/numeric failure), position-check must NOT silently degrade to
        score=0/HOLD — it must emit a warning so the user/operator can diagnose a broken
        health check instead of trusting a false 'all healthy' result."""
        import logging

        from src.screening import position_health as ph_mod
        from src.screening.position_health import compute_position_health

        self._seed_report(tmp_path)

        def _boom(*args, **kwargs):  # noqa: ANN002, ANN003
            raise RuntimeError("simulated provider/cache failure")

        monkeypatch.setattr(ph_mod, "compute_composite_scores_for_recommendations", _boom)
        monkeypatch.setattr(ph_mod, "compute_signal_momentum", _boom)
        monkeypatch.setattr(ph_mod, "compute_trend_resonance", _boom)
        monkeypatch.setattr(ph_mod, "compute_volume_confirmation", _boom)

        with caplog.at_level(logging.WARNING, logger="src.screening.position_health"):
            report = compute_position_health(tickers=["000001"], reports_dir=tmp_path)

        # Behavior preserved: still returns a report with the held ticker
        assert len(report.items) == 1
        # Diagnostic: each silent fallback must now log a warning (the BH-017 fix)
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) >= 1, "compute failure must be logged, not silent"
        assert any("000001" in r.getMessage() or "position" in r.getMessage().lower() or "health" in r.getMessage().lower() for r in warnings)

    def test_compute_failure_marks_report_degraded(self, tmp_path, monkeypatch) -> None:
        """R92 product-quality: when composite scoring degrades, the report must carry
        a ``degraded`` flag so the user-visible render can disclose trust-calibration
        (serves 'higher confidence' goal — distinguish real low score from silent failure)."""
        from src.screening import position_health as ph_mod
        from src.screening.position_health import compute_position_health

        self._seed_report(tmp_path)

        def _boom(*args, **kwargs):  # noqa: ANN002, ANN003
            raise RuntimeError("simulated provider failure")

        monkeypatch.setattr(ph_mod, "compute_composite_scores_for_recommendations", _boom)

        report = compute_position_health(tickers=["000001"], reports_dir=tmp_path)
        assert report.degraded is True

    def test_healthy_compute_not_degraded(self, tmp_path, monkeypatch) -> None:
        """Baseline: when scoring succeeds, report.degraded is False (no false alarm)."""
        from src.screening import position_health as ph_mod
        from src.screening.position_health import compute_position_health

        self._seed_report(tmp_path)
        # All compute functions succeed (return empty reports — no exception)
        monkeypatch.setattr(
            ph_mod, "compute_composite_scores_for_recommendations",
            lambda **k: type("R", (), {"items": []})(),
        )

        report = compute_position_health(tickers=["000001"], reports_dir=tmp_path)
        assert report.degraded is False

    def test_degraded_composite_does_not_emit_false_sell(self, tmp_path, monkeypatch) -> None:
        """R161: when composite scoring is unavailable for a held ticker, the
        fallback composite_score=0.0 MUST NOT trigger a SELL action. A failed
        score is not evidence the position deteriorated — issuing SELL on a
        real-money surface (--position-check tells users to sell actual holdings)
        would panic-sell a healthy position. The degraded banner mitigates at
        report level, but the per-item action must also be safe (HOLD with a
        data-unavailable reason, not SELL)."""
        from src.screening import position_health as ph_mod
        from src.screening.position_health import compute_position_health

        self._seed_report(tmp_path)  # healthy ticker 000001, score_b=0.5

        def _boom(*args, **kwargs):  # noqa: ANN002, ANN003
            raise RuntimeError("simulated provider failure")

        monkeypatch.setattr(ph_mod, "compute_composite_scores_for_recommendations", _boom)

        report = compute_position_health(tickers=["000001"], reports_dir=tmp_path)
        assert len(report.items) == 1
        item = report.items[0]
        assert item.action != "SELL", (
            f"composite-unavailable must not emit SELL (got {item.action!r} from "
            f"fallback composite_score={item.composite_score}); a failed score is "
            f"not a sell signal on a real-money surface"
        )
        assert item.action == "HOLD"

    def test_partial_composite_miss_does_not_emit_false_sell(self, tmp_path, monkeypatch) -> None:
        """R161 sibling: even without a full compute failure (degraded stays
        False), a held ticker absent from the composite report (comp=None) would
        fall back to composite_score=0.0 → false SELL. The guard must fire
        per-item, not only on the whole-report degraded flag."""
        from src.screening import position_health as ph_mod
        from src.screening.position_health import compute_position_health

        self._seed_report(tmp_path)  # ticker 000001 in history

        # Composite scorer succeeds but returns NO items → 000001 is comp=None
        monkeypatch.setattr(
            ph_mod, "compute_composite_scores_for_recommendations",
            lambda **k: type("R", (), {"items": []})(),
        )

        report = compute_position_health(tickers=["000001"], reports_dir=tmp_path)
        assert len(report.items) == 1
        assert report.items[0].action != "SELL"


# ---------------------------------------------------------------------------
# _action_colored (was 0 direct coverage)
# ---------------------------------------------------------------------------


class TestActionColored:
    """_action_colored — color-code a position action label."""

    def test_sell_red_bright(self) -> None:
        result = _action_colored("SELL")
        assert Fore.RED in result
        assert Style.BRIGHT in result
        assert "SELL" in result

    def test_watch_yellow(self) -> None:
        result = _action_colored("WATCH")
        assert Fore.YELLOW in result
        assert "WATCH" in result

    def test_hold_green_default(self) -> None:
        result = _action_colored("HOLD")
        assert Fore.GREEN in result
        assert "HOLD" in result

    def test_unknown_action_defaults_to_hold_green(self) -> None:
        result = _action_colored("bogus")
        assert Fore.GREEN in result
        assert "HOLD" in result

    def test_ends_with_reset(self) -> None:
        assert _action_colored("SELL").endswith(Style.RESET_ALL)
        assert _action_colored("WATCH").endswith(Style.RESET_ALL)
