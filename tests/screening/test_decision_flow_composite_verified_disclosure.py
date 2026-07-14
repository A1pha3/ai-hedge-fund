"""TDD red test: --decision-flow must disclose composite_verified=False on the
Top investable headline, mirroring R111 on --top-picks.

R39 set ``composite_verified=False`` on items whose composite_score fell back
to a 0.9-discounted score_b (missing-composite path). R111 made ``--top-picks``
show an "估" marker so the user can distinguish a verified composite from a
conservative estimate. But ``--decision-flow`` (R34/R77 trust-calibration
surface) prints the same composite score on its "Top investable" headline
(decision_flow.py:227) WITHOUT reading ``composite_verified`` — a cross-layer
sibling miss of the C143 pattern ("a computation layer can be hardened while
its consumer silently violates the contract"). The user sees a fallback
estimate rendered identically to a fully dimension-adjusted composite on the
power-user deep-dive surface, undermining the "更高确信" product goal.

Fix: mirror R111 — append "估" to the composite score when
``composite_verified is explicitly False``. Verified/missing-flag items render
unchanged (behavior preserved).
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from src.screening.composite_score import CompositeEntry, CompositeReport
from src.screening.decision_flow import run_decision_flow


def _seed_report(tmp_path: Path, recs: list[dict]) -> Path:
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    report = {"date": "20260611", "recommendations": recs}
    (reports_dir / "auto_screening_20260611.json").write_text(json.dumps(report), encoding="utf-8")
    return reports_dir


def _rec(ticker: str, score_b: float) -> dict:
    return {"ticker": ticker, "name": ticker, "score_b": score_b, "strategy_signals": {}}


def test_fallback_top_investable_discloses_estimate_marker(tmp_path: Path, capsys) -> None:
    """composite_verified=False (missing-composite R39 fallback) must show 估
    on the --decision-flow Top investable headline, not render the conservative
    estimate identically to a verified composite (cross-layer sibling of R111)."""
    reports_dir = _seed_report(tmp_path, [_rec("000001", 0.8)])

    # Mock composite scoring to return NO items for the ticker → R39 fallback
    # path fires (investability.py:282 composite_verified=False).
    empty_composite = CompositeReport(trade_date="20260611", items=[])
    with patch(
        "src.screening.composite_score.compute_composite_scores_for_recommendations",
        return_value=empty_composite,
    ):
        result = run_decision_flow(top_n=10, reports_dir=reports_dir)

    assert "error" not in result, f"flow should succeed, got: {result}"
    out = capsys.readouterr().out
    assert "Top investable" in out
    assert "估" in out, "composite_verified=False Top investable must disclose an estimate marker; " "currently --decision-flow renders a conservative-estimate composite " "identically to a verified composite (R111 cross-layer sibling miss)"


def test_verified_top_investable_has_no_estimate_marker(tmp_path: Path, capsys) -> None:
    """composite_verified=True (ticker present in composite report) must NOT
    show 估 — the score is a fully dimension-adjusted composite, not an estimate."""
    reports_dir = _seed_report(tmp_path, [_rec("000001", 0.8)])

    # Mock composite scoring to INCLUDE the ticker → verified path
    # (investability.py:264 composite_verified=True).
    verified_composite = CompositeReport(
        trade_date="20260611",
        items=[
            CompositeEntry(
                ticker="000001",
                name="000001",
                base_score=0.7,
                composite_score=0.72,
            )
        ],
    )
    with patch(
        "src.screening.composite_score.compute_composite_scores",
        return_value=verified_composite,
    ):
        result = run_decision_flow(top_n=10, reports_dir=reports_dir)

    assert "error" not in result, f"flow should succeed, got: {result}"
    out = capsys.readouterr().out
    assert "Top investable" in out
    assert "估" not in out, "verified composite pick must NOT show an estimate marker"
