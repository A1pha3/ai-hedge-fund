"""C241 Bug Hunt — apply_freshness_confidence_penalty dead-code drain.

Background:
    R96 (Campaign 82) fixed the falsy-zero ``or`` bug INSIDE
    ``apply_freshness_confidence_penalty``. R118 (Campaign 102) fixed
    ``check_data_freshness`` to mark unknown sources as not-fresh. But
    neither wired ``apply_freshness_confidence_penalty`` into the production
    pipeline — the function is DEFINED in ``data_freshness_guard.py:133``
    and tested in ``test_data_freshness_guard.py``, but NEVER CALLED in
    ``src/`` (grep confirms only tests reference it). ``check_data_freshness``
    is called in ``decision_flow.py:101`` and ``dispatcher.py:674`` but only
    for display (``_render_freshness_summary`` print). The data freshness
    guard is therefore COSMETIC in production — stale data does not actually
    reduce recommendation confidence, breaking the R96/R118 design intent.

Fix:
    Wire ``apply_freshness_confidence_penalty`` into
    ``run_decision_flow`` after ``check_data_freshness`` so stale-data recs
    get the confidence penalty. The penalized recs then flow into
    signal_consistency / expected_returns / investability downstream.

Orthogonal to awaiting_release:
    iv072 (factor_attribution by state) + iv073 (score-controlled) touch
    factor_attribution / top_picks rendering. This fix touches
    data_freshness_guard wiring in decision_flow — orthogonal.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

from src.screening import data_freshness_guard
from src.screening.decision_flow import run_decision_flow


def _make_report(date_str: str, recs: list[dict]) -> dict:
    return {"date": date_str, "recommendations": recs}


def _make_rec(ticker: str, name: str, score_b: float, confidence: float = 80.0) -> dict:
    return {
        "ticker": ticker,
        "name": name,
        "score_b": score_b,
        "confidence": confidence,
        "strategy_signals": {},
    }


class TestC241FreshnessPenaltyWiring:
    """C241: ``apply_freshness_confidence_penalty`` must be wired into
    ``run_decision_flow`` so stale-data recs get confidence penalty
    (R96/R118 design intent)."""

    def test_stale_freshness_applies_confidence_penalty(self, tmp_path: Path) -> None:
        """When ``check_data_freshness`` returns fresh=False with a HIGH
        severity warning, ``run_decision_flow`` must call
        ``apply_freshness_confidence_penalty`` so the rec's confidence is
        reduced (HIGH penalty = 0.7). Before C241 the function was dead
        code — confidence stayed at its original value."""
        reports_dir = tmp_path / "reports"
        reports_dir.mkdir()
        rec = _make_rec("000001", "A", 0.8, confidence=80.0)
        today = _make_report("20260611", [rec])
        (reports_dir / "auto_screening_20260611.json").write_text(
            json.dumps(today), encoding="utf-8"
        )

        stale_freshness = {
            "fresh": False,
            "trade_date": "2026-06-11",
            "warnings": [
                {
                    "source": "daily_prices",
                    "label": "行情数据",
                    "latest_date": "2026-06-09",
                    "stale_days": 2,
                    "max_stale_days": 1,
                    "severity": "HIGH",
                }
            ],
            "warning_count": 1,
            "summary": "stale",
        }
        with mock.patch.object(
            data_freshness_guard, "check_data_freshness", return_value=stale_freshness
        ):
            with mock.patch.object(
                data_freshness_guard,
                "apply_freshness_confidence_penalty",
                wraps=data_freshness_guard.apply_freshness_confidence_penalty,
            ) as spy:
                result = run_decision_flow(top_n=10, reports_dir=reports_dir)

        assert "error" not in result, f"flow errored: {result}"
        assert spy.called, (
            "apply_freshness_confidence_penalty must be called when "
            "check_data_freshness returns fresh=False (R96/R118 design intent)"
        )
        # The spy wraps the real function, which mutates recs in place.
        # Verify the confidence was actually reduced (HIGH penalty = 0.7).
        called_args, _ = spy.call_args
        recs_arg = called_args[0]
        assert recs_arg[0]["confidence"] == round(80.0 * 0.7, 1), (
            f"confidence should be penalized to 56.0 (80 * 0.7), "
            f"got {recs_arg[0]['confidence']}"
        )
        assert recs_arg[0].get("confidence_penalty") == 0.3
        assert recs_arg[0].get("confidence_penalty_reason") == "data_freshness_warning"

    def test_fresh_freshness_does_not_apply_penalty(self, tmp_path: Path) -> None:
        """When ``check_data_freshness`` returns fresh=True, no penalty
        should be applied (recs keep original confidence)."""
        reports_dir = tmp_path / "reports"
        reports_dir.mkdir()
        rec = _make_rec("000001", "A", 0.8, confidence=80.0)
        today = _make_report("20260611", [rec])
        (reports_dir / "auto_screening_20260611.json").write_text(
            json.dumps(today), encoding="utf-8"
        )

        fresh_report = {
            "fresh": True,
            "trade_date": "2026-06-11",
            "warnings": [],
            "warning_count": 0,
            "summary": "fresh",
        }
        with mock.patch.object(
            data_freshness_guard, "check_data_freshness", return_value=fresh_report
        ):
            with mock.patch.object(
                data_freshness_guard, "apply_freshness_confidence_penalty"
            ) as spy:
                result = run_decision_flow(top_n=10, reports_dir=reports_dir)

        assert "error" not in result, f"flow errored: {result}"
        assert not spy.called, (
            "apply_freshness_confidence_penalty must NOT be called when "
            "freshness check passes (fresh=True)"
        )
