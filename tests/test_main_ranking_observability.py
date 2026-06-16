"""BH-017: observability for silent ranking degradation in src/main.py.

``_rank_pool_by_investability`` wraps composite-score + expected-return ranking
in a broad ``except Exception`` that returns the unranked pool. BH-017 adds a
``logger.warning`` so the degradation is observable — the user otherwise sees an
unranked fallback with no signal that investability ranking failed.
"""

from __future__ import annotations

import logging

import pytest

from src.main import _rank_pool_by_investability


def test_ranking_degradation_logs_warning(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    """When composite ranking raises, the helper must (a) return the unranked
    pool AND (b) emit a warning so the silent fallback is diagnosable."""
    ranking_pool = [{"ticker": "000001", "score_b": 0.6}, {"ticker": "000002", "score_b": 0.5}]

    def boom(*_args, **_kwargs):
        raise RuntimeError("simulated composite-score failure")

    # Force the composite-score builder (imported locally inside the helper) to
    # raise, triggering the except branch.
    import src.screening.composite_score as composite_score

    monkeypatch.setattr(composite_score, "compute_composite_scores_for_recommendations", boom)

    with caplog.at_level(logging.WARNING, logger="src.main"):
        result = _rank_pool_by_investability(ranking_pool, trade_date="20260105")

    # Behavior preserved: unranked pool returned unchanged.
    assert result == ranking_pool
    # BH-017 observability: a warning must be logged.
    assert any("investability" in rec.message.lower() or "ranking" in rec.message.lower() for rec in caplog.records), (
        f"Expected a warning about ranking degradation, got: {[rec.message for rec in caplog.records]}"
    )


def test_ranking_normal_path_no_warning(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    """Normal ranking path (no exception) must NOT emit a degradation warning."""
    ranking_pool = [{"ticker": "000001", "score_b": 0.6}]

    # Composite/expected builders succeed and rank returns a list.
    import src.screening.composite_score as composite_score
    import src.screening.expected_return as expected_return

    monkeypatch.setattr(composite_score, "compute_composite_scores_for_recommendations", lambda **_kw: object())
    monkeypatch.setattr(expected_return, "compute_expected_returns", lambda **_kw: object())
    # rank_recommendations_by_investability is imported at module top in main.py.
    import src.main as main_mod

    monkeypatch.setattr(main_mod, "rank_recommendations_by_investability", lambda pool, *_a, **_kw: pool)

    with caplog.at_level(logging.WARNING, logger="src.main"):
        result = _rank_pool_by_investability(ranking_pool, trade_date="20260105")

    assert result == ranking_pool
    assert not any("ranking" in rec.message.lower() for rec in caplog.records)
