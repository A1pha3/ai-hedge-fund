"""Shared investability ranking helpers.

Blend composite confidence with long-horizon posterior evidence so the default
entry points can prioritize stocks that are both high-quality signals and
historically attractive over the next 30 trading days.
"""

from __future__ import annotations

from typing import Any

from src.screening.composite_score import CompositeReport
from src.screening.expected_return import ExpectedReturnReport
from src.utils.numeric import is_finite_number


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
    """Coerce to finite float, else default.

    NS-13: previously only guarded None/TypeError/ValueError, so ``float('nan')``
    returned NaN on the success path → NaN leaked into sort keys (composite_score,
    score_b) → ``sorted()`` ordering became non-deterministic (NaN comparisons are
    unstable) → same data produced different top picks across runs. Delegates to
    ``utils.numeric.safe_float`` which also rejects NaN/Inf/bool.
    """
    from src.utils.numeric import safe_float

    return safe_float(value, default)


def _safe_text(value: Any) -> str:
    return str(value or "").strip()


def _resolve_cluster_label(recommendation: dict[str, Any]) -> tuple[str, str]:
    industry = _safe_text(recommendation.get("industry_sw") or recommendation.get("industry"))
    if industry:
        return ("industry", industry)

    concept_value = recommendation.get("concepts") or recommendation.get("concept")
    if isinstance(concept_value, str):
        concept = concept_value.strip()
        if concept:
            return ("concept", concept)
    elif isinstance(concept_value, (list, tuple)):
        concepts = sorted(_safe_text(item) for item in concept_value if _safe_text(item))
        if concepts:
            return ("concept", concepts[0])

    ticker = _safe_text(recommendation.get("ticker")) or "unknown"
    return ("ticker", ticker)


def _decorate_cluster_candidate(
    recommendation: dict[str, Any],
    *,
    cluster_kind: str,
    cluster_label: str,
    cluster_members: list[dict[str, Any]],
) -> dict[str, Any]:
    ticker = _safe_text(recommendation.get("ticker"))
    member_tickers = [_safe_text(item.get("ticker")) for item in cluster_members if _safe_text(item.get("ticker"))]
    decorated = dict(recommendation)
    decorated["cluster_kind"] = cluster_kind
    decorated["cluster_label"] = cluster_label
    decorated["cluster_size"] = len(member_tickers)
    decorated["cluster_members"] = member_tickers
    decorated["cluster_alternatives"] = [member for member in member_tickers if member != ticker]
    decorated["is_cluster_representative"] = bool(member_tickers and member_tickers[0] == ticker)
    return decorated


def select_representative_candidates(
    recommendations: list[dict[str, Any]],
    *,
    count: int,
) -> list[dict[str, Any]]:
    """Keep one representative per cluster before backfilling duplicates.

    The input recommendations must already be sorted by desirability.
    Clusters currently prefer Shenwan industry labels and fall back to concept or ticker.
    """

    if count <= 0 or not recommendations:
        return []

    cluster_groups: dict[str, list[dict[str, Any]]] = {}
    cluster_labels: dict[str, tuple[str, str]] = {}

    for recommendation in recommendations:
        cluster_kind, cluster_label = _resolve_cluster_label(recommendation)
        cluster_key = f"{cluster_kind}:{cluster_label}"
        cluster_groups.setdefault(cluster_key, []).append(recommendation)
        cluster_labels[cluster_key] = (cluster_kind, cluster_label)

    selected: list[dict[str, Any]] = []
    selected_tickers: set[str] = set()
    selected_clusters: set[str] = set()

    for recommendation in recommendations:
        cluster_kind, cluster_label = _resolve_cluster_label(recommendation)
        cluster_key = f"{cluster_kind}:{cluster_label}"
        ticker = _safe_text(recommendation.get("ticker"))
        if cluster_key in selected_clusters or ticker in selected_tickers:
            continue
        selected.append(
            _decorate_cluster_candidate(
                recommendation,
                cluster_kind=cluster_kind,
                cluster_label=cluster_label,
                cluster_members=cluster_groups[cluster_key],
            )
        )
        selected_clusters.add(cluster_key)
        selected_tickers.add(ticker)
        if len(selected) >= count:
            return selected

    for recommendation in recommendations:
        ticker = _safe_text(recommendation.get("ticker"))
        if ticker in selected_tickers:
            continue
        cluster_kind, cluster_label = _resolve_cluster_label(recommendation)
        cluster_key = f"{cluster_kind}:{cluster_label}"
        selected.append(
            _decorate_cluster_candidate(
                recommendation,
                cluster_kind=cluster_kind,
                cluster_label=cluster_label,
                cluster_members=cluster_groups[cluster_key],
            )
        )
        selected_tickers.add(ticker)
        if len(selected) >= count:
            break

    return selected


def build_front_door_verdict(
    recommendation: dict[str, Any],
    *,
    market_regime: str,
) -> dict[str, str]:
    """Derive a compact Buy/Hold/Avoid verdict for default front-door outputs."""

    regime_lower = _safe_text(market_regime).lower()
    decision = _safe_text(recommendation.get("decision")).lower()
    composite_score = _safe_metric(recommendation.get("composite_score"), _safe_metric(recommendation.get("score_b", 0.0), 0.0))
    expected_returns = recommendation.get("expected_returns") or {}
    win_rates = recommendation.get("win_rates") or {}
    # C219 (autodev): per-horizon bootstrap CI (n=7203, 95%) 证明 low bucket
    # 是短期反弹票 — T+5 winrate=60.2% [59.0%, 61.3%], T+10 winrate=60.5%
    # [59.4%, 61.6%], 但 T+30 winrate=45.4% [44.2%, 46.5%] << 50%. 原 BUY gate
    # 用 T+30 horizon 导致 low bucket 票被门控翻转拒绝. 改为 T+5 OR T+10 OR
    # 逻辑: 任一短期 horizon 满足 (edge>0 AND winrate>=0.55) 即可 BUY, 让短期
    # 反弹票通过门控.
    t5_edge = _safe_metric(expected_returns.get("t5"), 0.0)
    t5_win_rate = _safe_metric(win_rates.get("t5"), 0.0)
    t10_edge = _safe_metric(expected_returns.get("t10"), 0.0)
    t10_win_rate = _safe_metric(win_rates.get("t10"), 0.0)
    # 保留 t30 用于长期衰退信号 (invalidation_reasons)
    t30_edge = _safe_metric(expected_returns.get("t30"), 0.0)
    t30_win_rate = _safe_metric(win_rates.get("t30"), 0.0)
    sample_count = int(_safe_metric(recommendation.get("bucket_sample_count"), 0.0))
    # R35 consistency drain: the BUY gate must be backed by enough *mature*
    # T+30 samples, not the all-records bucket_sample_count (which includes
    # picks too recent to have a realized 30-day return). When the R35
    # bucket_t30_mature_count field is present, require it to clear the same
    # statistical-significance bar as the legacy raw count; otherwise fall
    # back to the raw count so pre-R35 / partial pipelines keep working.
    # C219: T+30 mature_count 蕴含 T+5/T+10 mature (T+30 比 T+5/T+10 更严格),
    # 作为短期 horizon 的保守成熟度代理.
    t30_mature_count_raw = recommendation.get("bucket_t30_mature_count")
    has_mature_field = t30_mature_count_raw is not None
    backing_sample = (
        int(_safe_metric(t30_mature_count_raw, 0.0))
        if has_mature_field
        else sample_count
    )

    supports_long = decision != "bearish"
    # C219: BUY gate 改为 T+5 OR T+10 OR 逻辑 (短期反弹信号). 任一 horizon
    # 满足 edge>0 AND winrate>=0.55 即可通过. T+30 mature_count 仍作为成熟度
    # 代理 (T+30 mature 蕴含 T+5/T+10 mature, 更严格).
    _t5_passes = t5_edge > 0 and t5_win_rate >= 0.55
    _t10_passes = t10_edge > 0 and t10_win_rate >= 0.55
    _short_term_passes = _t5_passes or _t10_passes
    _meets_quality_bar = supports_long and composite_score >= 0.5 and _short_term_passes
    is_high_quality = _meets_quality_bar and backing_sample >= 20
    is_high_quality_for_hold = _meets_quality_bar and sample_count >= 20
    # is_watchable: 宽松版 (winrate>=0.5, edge>=0), 同样用 T+5 OR T+10
    _t5_watchable = t5_edge >= 0 and t5_win_rate >= 0.5
    _t10_watchable = t10_edge >= 0 and t10_win_rate >= 0.5
    is_watchable = supports_long and composite_score >= 0.25 and (_t5_watchable or _t10_watchable)

    if "crisis" in regime_lower or "risk_off" in regime_lower:
        action = "HOLD" if is_high_quality_for_hold else "AVOID"
    elif is_high_quality:
        action = "BUY"
    elif is_watchable:
        action = "HOLD"
    else:
        action = "AVOID"

    # BH-010: "T+30 edge 转负" must only be listed when the edge is actually
    # negative. Previously it was hardcoded unconditionally, so a BUY stock
    # (edge>0) would still carry a false "edge 转负" invalidation reason.
    invalidation_reasons: list[str] = []
    if t30_edge is not None and t30_edge < 0:
        invalidation_reasons.append("T+30 edge 转负")
    if "crisis" in regime_lower or "risk_off" in regime_lower:
        invalidation_reasons.append("市场门控维持 risk-off")
    else:
        invalidation_reasons.append("市场门控转弱")
    if _safe_metric(recommendation.get("momentum_bonus"), 0.0) < 0:
        invalidation_reasons.append("动量转负")
    if _safe_metric(recommendation.get("sector_bonus"), 0.0) < 0:
        invalidation_reasons.append("行业转弱")
    if _safe_metric(recommendation.get("consistency_adj"), 0.0) < 0:
        invalidation_reasons.append("信号分歧扩大")
    if _safe_metric(recommendation.get("volume_factor"), 0.0) < 0:
        invalidation_reasons.append("量价背离")
    if _safe_metric(recommendation.get("trend_resonance_factor"), 0.0) < 0:
        invalidation_reasons.append("趋势共振失效")
    # R68/R96 falsy-zero family drain: ``t30_win_rate`` is
    # ``_safe_metric(win_rates.get("t30"), 0.0)`` which returns 0.0 for BOTH
    # missing data (key absent/None) AND an actual 0.0 (0%) win rate. The
    # previous ``if t30_win_rate and t30_win_rate < 0.5`` guard short-circuited
    # on falsy 0.0, so the worst-possible real win rate (0%) did NOT trigger
    # the flag. Check the RAW value with is_finite_number so actual 0.0 flags
    # (0 < 0.5) while missing/NaN data does not.
    _raw_t30_wr = win_rates.get("t30")
    if is_finite_number(_raw_t30_wr) and float(_raw_t30_wr) < 0.5:
        invalidation_reasons.append("同分组胜率跌破 50%")
    if 0 < sample_count < 20:
        invalidation_reasons.append("样本量不足 20")

    deduped_reasons = list(dict.fromkeys(invalidation_reasons))
    return {
        "action": action,
        "market_regime": regime_lower or "unknown",
        "invalidation_reason": " / ".join(deduped_reasons[:4]),
    }


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
            merged["trend_resonance_factor"] = composite.trend_resonance_factor
            merged["composite_score"] = round(composite.composite_score, 4)
            merged["composite_grade"] = _grade_code(composite.composite_score)
            merged["composite_verified"] = True
        else:
            fallback_score = _safe_metric(rec.get("score_b", 0.0), 0.0)
            merged["base_score"] = fallback_score
            merged["momentum_bonus"] = 0.0
            merged["sector_bonus"] = 0.0
            merged["consistency_adj"] = 0.0
            merged["volume_factor"] = 0.0
            merged["trend_resonance_factor"] = 0.0
            # R39: composite_score 域是 [-1,1]（含负 penalties: consistency/momentum/
            # sector/volume 调整），但 score_b 域是 [0,1]（无 penalties）。直接把
            # score_b 赋给 composite_score 让 missing-composite 标的绕过所有负调整，
            # 可能把应降级为 HOLD 的标的（composite≈0.4）以 score_b=0.55 跨越 BUY 0.5
            # 门控。应用 0.9 保守折扣并标记 composite_verified=False，使 missing-composite
            # 标的不易轻易达到 BUY，同时保留它在排名里（不会被打成 AVOID）。
            penalized = round(fallback_score * 0.9, 4)
            merged["composite_score"] = penalized
            merged["composite_grade"] = _grade_code(penalized)
            merged["composite_verified"] = False

        expected = expected_map.get(ticker)
        if expected is not None:
            merged["bucket_label"] = expected.bucket_label
            merged["bucket_sample_count"] = expected.bucket_sample_count
            merged["bucket_t30_mature_count"] = expected.bucket_t30_mature_count
            merged["bucket_t30_avg_negative_return"] = expected.bucket_t30_avg_negative_return
            merged["expected_returns"] = dict(expected.expected_returns)
            merged["win_rates"] = dict(expected.win_rates)
        else:
            merged["bucket_label"] = "未知"
            merged["bucket_sample_count"] = 0
            merged["bucket_t30_mature_count"] = 0
            merged["bucket_t30_avg_negative_return"] = None
            merged["expected_returns"] = {}
            merged["win_rates"] = {}

        ranked.append(merged)

    # BH-011 family (sibling: composite_score.py:312, top_picks._apply_consecutive_bonus_and_resort,
    # portfolio/builder.compute_portfolio): the 5-level tuple above narrows ties heavily,
    # but its final key is score_b — a colliding float (and score_b is itself an input to
    # composite_score, so equal composite + equal calibration can imply equal score_b).
    # Two fallback/missing-expected-return recs can fully collide across all five levels,
    # leaving the order dependent on upstream dict/JSON iteration — non-deterministic across
    # runs, breaking the "稳定找到" goal. Append ticker ascending as the deterministic
    # final tie-break. reverse=True would also reverse the ticker key, so negate the
    # numeric levels and sort ascending instead.
    ranked.sort(
        key=lambda rec: (
            -_safe_metric(rec.get("composite_score"), _safe_metric(rec.get("score_b", 0.0), 0.0)),
            -_safe_metric((rec.get("expected_returns") or {}).get("t30"), float("-inf")),
            -_safe_metric((rec.get("win_rates") or {}).get("t30"), float("-inf")),
            -_safe_metric(rec.get("bucket_sample_count"), 0.0),
            -_safe_metric(rec.get("score_b", 0.0), 0.0),
            str(rec.get("ticker") or ""),
        ),
    )
    return ranked
