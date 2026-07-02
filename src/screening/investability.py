"""Shared investability ranking helpers.

Blend composite confidence with short-horizon T+5/T+10 posterior evidence (BUY
gate decision horizon, see C220 commit 4184dd7e) so the default entry points
can prioritize stocks that are both high-quality signals and historically
attractive over the next T+5 or T+10 trading days. T+30 retained only as
long-term invalidation signal (not a BUY-decision horizon).
"""

from __future__ import annotations

from typing import Any

from src.screening.composite_score import CompositeReport
from src.screening.expected_return import ExpectedReturnReport
from src.utils.numeric import is_finite_number


#: C222 (2026-06-28 horizon 一致性): BUY gate 主决策 horizon 是 T+5 OR T+10
#: (见 ``_meets_quality_bar`` line 198-207). 排序键 tie-breaker 必须与 BUY gate
#: horizon 一致 — 用 max(t5, t10) 取短期 horizon 最优 metric. T+30 metric 排除出
#: 排序键 (保留为 long-term invalidation 信号, 见 ``invalidation_reasons`` 字段),
#: 与产品目标"未来 T+5 或 T+10 天"对齐.
_SHORT_HORIZON_KEYS: tuple[str, ...] = ("t5", "t10")


def _max_short_horizon_metric(metrics: dict[str, Any] | None) -> float | None:
    """Return max of short-horizon (T+5/T+10) metrics; ``None`` if all missing.

    Used as ranking tie-breaker after ``composite_score``, aligned with BUY gate
    horizon (T+5 OR T+10 pass, see C220). Returns the larger of the two horizons
    so a pick strong on *either* T+5 or T+10 ranks higher than one weak on both.
    Returns ``None`` when the metrics dict is missing or no T+5/T+10 entry is
    numeric — the caller's ``_safe_metric`` default (``-inf``) then pushes such
    picks below any pick with short-horizon data.

    Note: this is intentionally horizon-restricted (not max over all horizons)
    because the BUY gate decision is horizon-restricted (T+5 OR T+10, not T+30).
    Including T+30 in the sort key would re-introduce the horizon mismatch fixed
    by C222 (T+30-strong picks ranking above T+5/T+10-strong picks, even though
    BUY verdict is driven by T+5/T+10).
    """
    if not metrics:
        return None
    nums: list[float] = []
    for key in _SHORT_HORIZON_KEYS:
        raw = metrics.get(key)
        if isinstance(raw, (int, float)):
            nums.append(float(raw))
    return max(nums) if nums else None


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
    # NS-11 (autodev c232): 优先读 pre-bonus `composite_score_gated` 判 BUY gate,
    # 不被 consecutive bonus 放水. bonus 本意是排序 tie-break (R4), 不是放水
    # gate — 0.47 真分 + 0.05 bonus = 0.52 不应越过 BUY gate (>=0.5). C220
    # horizon 对齐后, bonus 污染 gate 会让 stale 挑选反而更容易 BUY, 与"稳定
    # 找到"产品目标相违. 缺省 composite_score_gated (旧报告/无 bonus 路径)
    # 回退 composite_score 保持向后兼容.
    _composite_score_raw = recommendation.get("composite_score_gated")
    if _composite_score_raw is None:
        _composite_score_raw = recommendation.get("composite_score")
    composite_score = _safe_metric(_composite_score_raw, _safe_metric(recommendation.get("score_b", 0.0), 0.0))
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
    # NS-23 (autodev c245): crisis/risk_off regime 下 T+5 不可靠 — BUY gate
    # 用全期 per-bucket T+5 winrate (~60%) 判门控, 但 crisis regime 实际 T+5
    # winrate=43.59% < 50% (用户 2026-06-29 直接复现证据, 8 只候选票本月 crisis
    # 回测). per-ticker 全期历史 stats 不能盲目外推到 regime-specific — T+5 alone
    # 不应放行 (用户原话 "T+5 winrate < 50% 时不应放行"). crisis 下只 T+10 可放行
    # (T+10 相对靠谱但仍需验证, 仅 2 信号日 mature, 等 7 月初更多数据). 非 crisis
    # 保持 C220 OR 逻辑 (短期反弹票在非 crisis 下 T+5 信号有效).
    _is_market_gate_active = "crisis" in regime_lower or "risk_off" in regime_lower
    if _is_market_gate_active:
        _short_term_passes = _t10_passes
    else:
        _short_term_passes = _t5_passes or _t10_passes
    _meets_quality_bar = supports_long and composite_score >= 0.5 and _short_term_passes
    is_high_quality = _meets_quality_bar and backing_sample >= 20
    is_high_quality_for_hold = _meets_quality_bar and sample_count >= 20
    # is_watchable: 宽松版 (winrate>=0.5, edge>=0), 同样用 T+5 OR T+10
    _t5_watchable = t5_edge >= 0 and t5_win_rate >= 0.5
    _t10_watchable = t10_edge >= 0 and t10_win_rate >= 0.5
    is_watchable = supports_long and composite_score >= 0.25 and (_t5_watchable or _t10_watchable)

    if _is_market_gate_active:
        action = "HOLD" if is_high_quality_for_hold else "AVOID"
    elif is_high_quality:
        action = "BUY"
    elif is_watchable:
        action = "HOLD"
    else:
        action = "AVOID"

    # C221: signal_horizon — 让用户区分 BUY 信号来源 (T+5 / T+10 / T+5+T+10).
    # C219 改 BUY gate 为 T+5 OR T+10 OR 逻辑, 但呈现层只显示 action=BUY,
    # 用户无法区分是 T+5 反弹还是 T+10 反弹, 容易把 T+5 票当 T+10 持有增加风险.
    # 基于 _short_term_passes 的两个 sub-signal 标注具体 horizon, 让用户灵活组合资金.
    # 注意: 即使 risk_off 降级为 HOLD, 只要 _short_term_passes 通过仍标注 horizon,
    # 让用户知道"本可 BUY 但被市场门控降级"的短期反弹信号.
    if _t5_passes and _t10_passes:
        signal_horizon = "T+5+T+10"
    elif _t5_passes:
        signal_horizon = "T+5"
    elif _t10_passes:
        signal_horizon = "T+10"
    else:
        signal_horizon = ""

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
    # NS-18 (autodev c275): invalidation_reasons 诚实化 — 原先只检查
    # ``0 < sample_count < 20``, 漏掉两个关键场景:
    #   1. ``sample_count == 0`` (完全无数据): ``0 < 0 < 20`` = False, 不标任何
    #      原因 → 用户看到 AVOID 但不知是 "数据完全缺失" 还是 "质量差".
    #   2. ``has_mature_field and backing_sample < 20`` (mature 不足但 raw 充足):
    #      BUY gate 正确降级 (line 258 ``backing_sample >= 20`` 拒绝 BUY), 但
    #      invalidation_reasons 不标原因 → 用户看到非 BUY 但不知是 "mature 不足"
    #      还是 "其他原因". 这是 trust calibration gap: gate 行为正确但呈现层
    #      不诚实, 用户无法 self-audit 决策.
    # 修复: 分三档标注, 让用户能区分 "数据缺失" / "mature 不足" / "raw 不足".
    if sample_count == 0:
        invalidation_reasons.append("数据缺失")
    if has_mature_field and backing_sample < 20:
        invalidation_reasons.append("成熟样本不足 20")
    elif not has_mature_field and 0 < sample_count < 20:
        # 旧路径 (pre-R35 / partial pipeline): 无 mature_count 字段时 fallback
        # 到 raw count, 保留原 "样本量不足 20" 标注.
        invalidation_reasons.append("样本量不足 20")

    deduped_reasons = list(dict.fromkeys(invalidation_reasons))
    return {
        "action": action,
        "market_regime": regime_lower or "unknown",
        "invalidation_reason": " / ".join(deduped_reasons[:4]),
        # C221: 短期反弹信号来源 horizon, 用于呈现层区分 T+5/T+10 反弹票
        "signal_horizon": signal_horizon,
    }


def rank_recommendations_by_investability(
    recommendations: list[dict[str, Any]],
    composite_report: CompositeReport,
    expected_report: ExpectedReturnReport,
    *,
    profit_aware: bool = False,
) -> list[dict[str, Any]]:
    """Merge composite and long-horizon evidence, then sort by investability.

    Ranking priority (default, ``profit_aware=False``):
    1. composite confidence score
    2. T+30 expected return
    3. T+30 win rate
    4. bucket sample count
    5. raw score_b

    C273 (2026-07-01) ``profit_aware=True``: re-key the ranking on the
    EMPIRICAL bucket winrate instead of composite_score. Grounded in the c272
    selection-profitability backtest (74 days, n=7993): the model's
    ``composite_score`` has NEGATIVE predictive value for top-N selection
    (``score_desc`` portfolio T+5 winrate 47.3% vs ``equal_weight`` 59.5% —
    following the model's top picks loses money). Profit-aware mode keys on
    the BUY-gate-aligned short-horizon bucket winrate (the backtested profit
    signal), demoting ``composite_score`` to a tie-break. Opt-in only —
    default behavior is unchanged.
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
    #
    # C222 (2026-06-28 horizon 一致性): tie-breakers 2/3 previously used t30_edge /
    # t30_winrate, but BUY gate decision horizon is T+5 OR T+10 (see
    # ``_meets_quality_bar`` line 198-207, C220 commit 4184dd7e). Two picks with equal
    # composite_score could be ordered by T+30 strength even though BUY verdict is
    # driven by T+5/T+10 — letting a T+30-strong-but-T+5/T+10-weak pick rank above a
    # T+5/T+10-strong pick. Tie-breakers 2/3 now use ``_max_short_horizon_metric``
    # (max of t5/t10), aligned with BUY gate horizon. T+30 metrics retained only as
    # long-term invalidation signal (``invalidation_reasons``), not as ranking
    # tie-breaker. Behavior change: picks whose T+30 was their only strength drop
    # below picks strong on T+5/T+10 — which is the intended BUY-gate alignment.
    ranked.sort(
        key=lambda rec: (
            -_safe_metric(rec.get("composite_score"), _safe_metric(rec.get("score_b", 0.0), 0.0)),
            -_safe_metric(_max_short_horizon_metric(rec.get("expected_returns")), float("-inf")),
            -_safe_metric(_max_short_horizon_metric(rec.get("win_rates")), float("-inf")),
            -_safe_metric(rec.get("bucket_sample_count"), 0.0),
            -_safe_metric(rec.get("score_b", 0.0), 0.0),
            str(rec.get("ticker") or ""),
        ),
    )
    if profit_aware:
        # C273 (2026-07-01): re-key on empirical bucket winrate — the backtested
        # profit signal. c272 proved composite_score has NEGATIVE predictive value
        # for top-N selection (47% score_desc vs 60% equal_weight). Primary =
        # max(T+5/T+10) bucket winrate (BUY-gate-aligned); expected_return as
        # secondary (magnitude); bucket_sample_count rewards mature buckets;
        # composite_score demoted to tie-break (keeps the model's residual signal
        # as the last resort, so profit-aware mode never throws the model away
        # entirely — it just stops trusting it as the PRIMARY key).
        ranked.sort(
            key=lambda rec: (
                -_safe_metric(_max_short_horizon_metric(rec.get("win_rates")), float("-inf")),
                -_safe_metric(_max_short_horizon_metric(rec.get("expected_returns")), float("-inf")),
                -_safe_metric(rec.get("bucket_sample_count"), 0.0),
                -_safe_metric(rec.get("composite_score"), _safe_metric(rec.get("score_b", 0.0), 0.0)),
                -_safe_metric(rec.get("score_b", 0.0), 0.0),
                str(rec.get("ticker") or ""),
            ),
        )
    return ranked
