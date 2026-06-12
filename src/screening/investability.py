"""Shared investability ranking helpers.

Blend composite confidence with long-horizon posterior evidence so the default
entry points can prioritize stocks that are both high-quality signals and
historically attractive over the next 30 trading days.
"""

from __future__ import annotations

from typing import Any

from src.screening.composite_score import CompositeReport
from src.screening.expected_return import ExpectedReturnReport


def _grade_code(score: float) -> str:
    if score >= 0.7:
        return "A"
    if score >= 0.5:
        return "B"
    if score >= 0.3:
        return "C"
    if score >= 0.1:
        return "D"
    return "F"


def _safe_metric(value: Any, default: float) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def rank_recommendations_by_investability(
    recommendations: list[dict[str, Any]],
    composite_report: CompositeReport,
    expected_report: ExpectedReturnReport,
) -> list[dict[str, Any]]:
    """Merge composite and long-horizon evidence, then sort by investability.

    Ranking priority:
    1. composite confidence score
    2. T+30 expected return
    3. T+30 win rate
    4. bucket sample count
    5. raw score_b
    """

    composite_map = {item.ticker: item for item in composite_report.items}
    expected_map = {item.ticker: item for item in expected_report.items}

    ranked: list[dict[str, Any]] = []
    for rec in recommendations:
        ticker = str(rec.get("ticker", ""))
        merged = dict(rec)

        composite = composite_map.get(ticker)
        if composite is not None:
            merged["base_score"] = composite.base_score
            merged["momentum_bonus"] = composite.momentum_bonus
            merged["sector_bonus"] = composite.sector_bonus
            merged["consistency_adj"] = composite.consistency_adj
            merged["volume_factor"] = composite.volume_factor
            merged["composite_score"] = round(composite.composite_score, 4)
            merged["composite_grade"] = _grade_code(composite.composite_score)
        else:
            fallback_score = _safe_metric(rec.get("score_b", 0.0), 0.0)
            merged["base_score"] = fallback_score
            merged["momentum_bonus"] = 0.0
            merged["sector_bonus"] = 0.0
            merged["consistency_adj"] = 0.0
            merged["volume_factor"] = 0.0
            merged["composite_score"] = round(fallback_score, 4)
            merged["composite_grade"] = _grade_code(fallback_score)

        expected = expected_map.get(ticker)
        if expected is not None:
            merged["bucket_label"] = expected.bucket_label
            merged["bucket_sample_count"] = expected.bucket_sample_count
            merged["expected_returns"] = dict(expected.expected_returns)
            merged["win_rates"] = dict(expected.win_rates)
        else:
            merged["bucket_label"] = "未知"
            merged["bucket_sample_count"] = 0
            merged["expected_returns"] = {}
            merged["win_rates"] = {}

        ranked.append(merged)

    ranked.sort(
        key=lambda rec: (
            _safe_metric(rec.get("composite_score"), _safe_metric(rec.get("score_b", 0.0), 0.0)),
            _safe_metric((rec.get("expected_returns") or {}).get("t30"), float("-inf")),
            _safe_metric((rec.get("win_rates") or {}).get("t30"), float("-inf")),
            _safe_metric(rec.get("bucket_sample_count"), 0.0),
            _safe_metric(rec.get("score_b", 0.0), 0.0),
        ),
        reverse=True,
    )
    return ranked
