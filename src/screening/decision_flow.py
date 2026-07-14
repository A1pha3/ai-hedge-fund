"""One-command decision flow -- P8-1 + P9-2.

Chains the entire CLI decision pipeline into a single command:
  auto screening → data freshness → signal consistency →
  dynamic threshold → outlier detection → expected returns →
  daily delta → summary

This is the primary entry point for daily stock selection.

CLI:
    python src/main.py --decision-flow
    python src/main.py --decision-flow --top-n=10 --lookback=30
"""

from __future__ import annotations

import json
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any

from src.screening.consecutive_recommendation import resolve_report_dir
from colorama import Fore, Style

# ---------------------------------------------------------------------------
# Core decision flow
# ---------------------------------------------------------------------------


def _format_bucket_tag(item: dict) -> str:
    """autodev-13 / loop 99: format the score-bucket label as an inline
    disclosure tag for the Top-investable headline.

    Sibling of ``top_picks._format_bucket_tag`` (loop 98) — same disease class:
    the 决策 edge / 胜率 / T+30 edge/winrate / 样本 rendered on this headline
    are BUCKET-LEVEL aggregates (shrinkage estimator). The operator reads
    "Top investable: 000001 (决策=+4.67% 胜率=60%...)" as 000001's own measured
    edge when it is actually the 低(<0.5) bucket average. Surfacing the bucket
    label inline lets the operator distinguish per-ticker measurement from
    bucket estimate (contract §估计值的清晰披露). Display-only; the bucket
    estimator is NOT changed.

    Returns ``""`` when ``bucket_label`` is absent (legacy reports) — graceful
    degradation. Duplicated locally (not imported from top_picks) to follow the
    codebase precedent for bucket-formatting helpers (``_format_sample_count``
    is also local to top_picks); kept in sync with ``top_picks._format_bucket_tag``.
    """
    label = str(item.get("bucket_label", "") or "").strip()
    if not label:
        return ""
    compact = label.replace(" (", "(")
    return f"  bucket={compact}"


def _check_report_age_vs_today(report_date_str: str) -> str:
    """autodev-8 / disease J: warn if the report is stale relative to TODAY.

    ``check_data_freshness`` (data_freshness_guard) uses the report's own date
    as ``trade_date``, so its report_file freshness check compares the report
    file against itself and always returns fresh=True. This helper closes that
    gap by checking the report's age against the operator's actual "today"
    (calendar-day approximation). Mirrors ``top_picks._check_report_freshness``
    but returns only the warning line (empty when fresh), so the caller can
    print it inline with the freshness summary.

    A report is flagged when it is more than 3 calendar days old — a coarse
    proxy that avoids false positives on weekends/holidays without requiring
    the trade-calendar lookup that the top_picks variant uses.
    """
    if not report_date_str or len(report_date_str) != 8 or not report_date_str.isdigit():
        return ""
    try:
        report_dt = datetime.strptime(report_date_str, "%Y%m%d")
    except ValueError:
        return ""
    age_days = (datetime.now() - report_dt).days
    if age_days > 3:
        formatted = report_dt.strftime("%Y-%m-%d")
        return (
            f"{Fore.YELLOW}⚠ 报告日期 {formatted} 已过期 {age_days} 天 "
            f"(相对今天, 非报告生成时数据新鲜度); 建议运行 --auto 更新后再决策{Style.RESET_ALL}"
        )
    return ""


def run_decision_flow(
    *,
    top_n: int = 10,
    lookback_days: int = 30,
    reports_dir: Path | None = None,
) -> dict[str, Any]:
    """Execute the full decision flow pipeline.

    Steps:
    1. Load latest auto screening results
    2. Check data freshness
    3. Check signal consistency
    4. Compute dynamic threshold
    5. Detect outliers
    6. Estimate expected returns
    7. Compute daily delta
    8. Render summary

    Args:
        top_n: Number of top recommendations to process
        lookback_days: Lookback for tracking history
        reports_dir: Reports directory

    Returns:
        Complete decision flow report
    """
    start_time = time.time()
    search_dir = reports_dir or resolve_report_dir()
    total_steps = 10
    flow_result: dict[str, Any] = {
        "generated_at": date.today().isoformat(),
        "top_n": top_n,
        "lookback_days": lookback_days,
    }

    # Step 1: Load latest screening report
    print(f"{Fore.CYAN}═══ Decision Flow ═══{Style.RESET_ALL}")
    print(f"\n{Fore.WHITE}Step 1/{total_steps}: Loading latest screening results...{Style.RESET_ALL}")
    from src.screening.data_quality_audit import _find_latest_report

    report_path = _find_latest_report(search_dir)
    if report_path is None:
        print(f"  {Fore.RED}✗ No auto_screening report found. Run --auto first.{Style.RESET_ALL}")
        return {**flow_result, "error": "no_report"}

    # R104 (R88/BH-017 family): a corrupt/truncated report (partial write /
    # interrupted run) must not crash the whole --decision-flow CLI. Degrade
    # to "no report" + user-visible warning so the operator re-runs --auto
    # rather than debugging a JSONDecodeError.
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        print(f"  {Fore.RED}✗ 最新报告 {report_path.name} 损坏或不可读 ({exc}); " f"请重新运行 --auto 生成.{Style.RESET_ALL}")
        return {**flow_result, "error": "corrupt_report"}
    recs = (report.get("recommendations") or [])[:top_n]
    # Preserve missing/malformed snapshot identity.  Strict downstream scorers
    # must fail neutral instead of silently treating an undated report as today.
    trade_date = str(report.get("date") or "")
    model_version = str(report.get("model_version") or "")
    from src.screening.consecutive_recommendation import (
        load_auto_screening_history,
        load_tracking_history,
    )

    history_records = load_tracking_history(search_dir)
    history_reports = load_auto_screening_history(
        lookback_days=max(60, lookback_days),
        report_dir=search_dir,
        end_date=str(trade_date),
    )
    print(f"  {Fore.GREEN}✓{Style.RESET_ALL} Loaded {len(recs)} recommendations (date: {trade_date})")
    flow_result["trade_date"] = trade_date
    flow_result["recommendation_count"] = len(recs)

    # Step 2: Data freshness
    print(f"\n{Fore.WHITE}Step 2/{total_steps}: Checking data freshness...{Style.RESET_ALL}")
    from src.screening.data_freshness_guard import (
        _render_freshness_summary,
        apply_freshness_confidence_penalty,
        check_data_freshness,
    )

    freshness = check_data_freshness(trade_date=trade_date, reports_dir=search_dir)
    print(f"  {_render_freshness_summary(freshness['fresh'], freshness['warnings'])}")

    # autodev-8 / disease J: check_data_freshness uses the report's own date as
    # trade_date, so its report_file check compares the report against itself
    # and ALWAYS returns fresh=True. The operator running the flow days after
    # the report was generated gets no warning that the report is stale relative
    # to today. --top-picks handles this correctly (datetime.now() vs report_date);
    # mirror that here so the operator is warned when acting on a stale report.
    report_age_warning = _check_report_age_vs_today(trade_date)
    if report_age_warning:
        print(f"  {report_age_warning}")
    flow_result["freshness"] = freshness

    # C241 (R96/R118 family drain): apply_freshness_confidence_penalty was
    # defined in data_freshness_guard.py and tested in test_data_freshness_guard.py
    # but never wired into production. check_data_freshness was display-only,
    # so stale data never actually reduced recommendation confidence -- breaking
    # the R96/R118 design intent. Wire the penalty here so stale-data recs get
    # confidence *= {0.7 HIGH | 0.85 MEDIUM | 0.95 LOW} before they flow into
    # signal_consistency / expected_returns / investability downstream.
    if not freshness.get("fresh", True):
        recs = apply_freshness_confidence_penalty(recs, freshness)

    # Step 3: Signal consistency
    print(f"\n{Fore.WHITE}Step 3/{total_steps}: Cross-checking signal consistency...{Style.RESET_ALL}")
    from src.screening.signal_consistency import (
        check_signal_consistency,
        render_consistency_report,
    )

    consistency = check_signal_consistency(recs)
    print(render_consistency_report(consistency))
    flow_result["consistency"] = consistency
    high_consistency_count = sum(1 for c in consistency if c.get("consistency_level") == "high")
    flow_result["high_consistency_count"] = high_consistency_count

    # Step 4: Dynamic threshold
    print(f"\n{Fore.WHITE}Step 4/{total_steps}: Computing dynamic threshold...{Style.RESET_ALL}")
    from src.screening.dynamic_threshold import (
        compute_dynamic_threshold,
        render_dynamic_threshold,
    )

    threshold_result = compute_dynamic_threshold(
        lookback_days=lookback_days,
        reports_dir=search_dir,
    )
    print(render_dynamic_threshold(threshold_result))
    flow_result["dynamic_threshold"] = threshold_result

    # Step 5: Outlier detection
    print(f"\n{Fore.WHITE}Step 5/{total_steps}: Detecting recommendation outliers...{Style.RESET_ALL}")
    from src.screening.outlier_detect import detect_outliers, render_outliers

    outliers_result = detect_outliers(top_n=top_n, reports_dir=search_dir)
    print(render_outliers(outliers_result))
    flow_result["outliers"] = outliers_result
    outlier_count = len(outliers_result.get("outliers", []))
    flow_result["outlier_count"] = outlier_count

    # Step 6: Expected returns
    print(f"\n{Fore.WHITE}Step 6/{total_steps}: Estimating expected returns...{Style.RESET_ALL}")
    from src.screening.expected_return import (
        compute_expected_returns,
        render_expected_returns_compact,
    )
    from src.screening.investability import rank_recommendations_by_investability

    expected = compute_expected_returns(
        recommendations=recs,
        as_of=str(trade_date),
        model_version=model_version,
        history_records=history_records,
        lookback_days=lookback_days,
    )
    print(render_expected_returns_compact(expected))
    flow_result["expected_returns"] = expected.to_dict()

    # Step 7: Daily delta
    print(f"\n{Fore.WHITE}Step 7/{total_steps}: Comparing with yesterday's picks...{Style.RESET_ALL}")
    from src.screening.daily_delta import compute_daily_delta, render_daily_delta

    delta = compute_daily_delta(reports_dir=search_dir, top_n=top_n, lookback_days=5)
    print(render_daily_delta(delta))
    flow_result["daily_delta"] = delta

    # Step 8: Signal momentum (P10-1)
    print(f"\n{Fore.WHITE}Step 8/{total_steps}: Analyzing signal momentum...{Style.RESET_ALL}")
    from src.screening.signal_momentum import (
        compute_signal_momentum,
        render_signal_momentum,
    )

    momentum = compute_signal_momentum(top_n=top_n, lookback_days=lookback_days, reports_dir=search_dir)
    print(render_signal_momentum(momentum))
    flow_result["signal_momentum"] = momentum.to_dict()
    improving_count = sum(1 for i in momentum.items if i.momentum_bonus > 0)
    declining_count = sum(1 for i in momentum.items if i.momentum_bonus < 0)

    # Step 9: Sector strength (P10-2)
    print(f"\n{Fore.WHITE}Step 9/{total_steps}: Evaluating sector strength...{Style.RESET_ALL}")
    from src.screening.sector_strength import (
        compute_sector_strength,
        render_sector_strength,
    )

    sector = compute_sector_strength(top_n=top_n, lookback_days=lookback_days, reports_dir=search_dir)
    print(render_sector_strength(sector))
    flow_result["sector_strength"] = sector.to_dict()

    # Step 10: Composite confidence score (P11-1)
    print(f"\n{Fore.WHITE}Step 10/{total_steps}: Computing composite confidence scores...{Style.RESET_ALL}")
    from src.screening.composite_score import (
        compute_composite_scores_for_recommendations,
        render_composite_scores,
    )

    composite = compute_composite_scores_for_recommendations(
        recommendations=recs,
        trade_date=str(trade_date),
        as_of=str(trade_date),
        history_reports=history_reports,
        lookback_days=lookback_days,
    )
    print(render_composite_scores(composite))
    flow_result["composite_scores"] = composite.to_dict()
    investability = rank_recommendations_by_investability(recs, composite, expected)
    flow_result["investability_ranking"] = investability

    # Summary
    elapsed = time.time() - start_time
    print(f"\n{Fore.CYAN}═══ Decision Summary ═══{Style.RESET_ALL}")
    print(f"  Date: {trade_date}")
    print(f"  Recommendations: {len(recs)} (top {top_n})")
    print(f"  Data freshness: {'✓ PASS' if freshness['fresh'] else '⚠ WARNING'}")
    print(f"  Signal consistency: {high_consistency_count}/{len(consistency)} high")
    print(f"  Dynamic threshold: {threshold_result['threshold']:.4f}")
    print(f"  Outliers: {outlier_count}")
    print(f"  Momentum: {Fore.GREEN}{improving_count} improving{Style.RESET_ALL} / {Fore.RED}{declining_count} declining{Style.RESET_ALL}")
    if investability:
        best = investability[0]
        # C222 (2026-06-28 horizon 一致性): BUY gate decision horizon is T+5 OR
        # T+10 (see ``_meets_quality_bar`` C220 commit 4184dd7e). The Top-investable
        # headline must show the decision-horizon edge/winrate that actually drove
        # the BUY verdict (max of t5/t10), not T+30 which is the long-term
        # invalidation horizon. T+30 retained as a secondary display so the user
        # can see the long-term view alongside the short-term decision basis.
        decision_edge_raw = None
        decision_winrate_raw = None
        for _hk in ("t10", "t5"):  # max(t5, t10) by reading larger horizon first
            _e = (best.get("expected_returns") or {}).get(_hk)
            if isinstance(_e, (int, float)) and (decision_edge_raw is None or _e > decision_edge_raw):
                decision_edge_raw = float(_e)
            _w = (best.get("win_rates") or {}).get(_hk)
            if isinstance(_w, (int, float)) and (decision_winrate_raw is None or _w > decision_winrate_raw):
                decision_winrate_raw = float(_w)
        decision_str = f"{decision_edge_raw:+.2f}%" if decision_edge_raw is not None else "—"
        decision_wr_str = f"{decision_winrate_raw:.0%}" if decision_winrate_raw is not None else "—"
        # T+30 retained as long-term invalidation view (per C222 dual-horizon rule).
        t30 = (best.get("expected_returns") or {}).get("t30")
        t30_str = f"{float(t30):+.2f}%" if isinstance(t30, (int, float)) else "—"
        t30_wr = (best.get("win_rates") or {}).get("t30")
        t30_wr_str = f"{float(t30_wr):.0%}" if isinstance(t30_wr, (int, float)) else "—"
        # BH-002 drain: attribute the T+30 stat to its matured-sample denominator,
        # not the all-records ``bucket_sample_count``. A freshly-recommended
        # batch inflates the all-records count without contributing to the T+30
        # estimate, so the displayed backing sample was misleading.
        sample_all = int(best.get("bucket_sample_count", 0) or 0)
        sample_t30_mature = int(best.get("bucket_t30_mature_count", 0) or 0)
        sample_str = f"样本={sample_all}(T30熟={sample_t30_mature})"
        # R141 Bug Hunt (R51/R52 family — coverage gap drain): c271 added the
        # ``⚠少样本`` low-confidence marker to ``render_expected_returns_compact``
        # in this SAME ``--decision-flow`` output, but this Top investable
        # headline line (which reads the SAME ``win_rates.t30`` +
        # ``bucket_t30_mature_count`` fields) was missed. A per-bucket n=1
        # "100% winrate" renders confident-green in the headline while the
        # expected-returns section below flags the same ticker yellow.
        # Mirror the c271 guard: flag when 0 < mature < 5.
        if 0 < sample_t30_mature < 5 and isinstance(t30_wr, (int, float)):
            t30_wr_str = f"{t30_wr_str} {Fore.YELLOW}⚠少样本{Style.RESET_ALL}"
        # R111 cross-layer sibling (C143 learning item 4: a hardened computation
        # layer's consumer can silently violate its contract): investability.py:282
        # sets composite_verified=False on the R39 missing-composite fallback path
        # (composite_score = 0.9-discounted score_b, a conservative estimate, not a
        # fully dimension-adjusted composite). --top-picks (R111) already discloses
        # this with an "估" marker; this power-user surface must do the same so the
        # user can calibrate trust on the headline Top-investable score. Missing
        # flag (old reports) is treated as verified (behavior preserved).
        composite_verified = best.get("composite_verified")
        estimate_marker = "估" if composite_verified is False else ""
        # autodev-13 / loop 99: surface the bucket label so the operator can
        # tell the 决策/胜率/T+30/样本 aggregates are bucket-level estimates
        # (same-bucket tickers share byte-identical values), NOT this ticker's
        # own measured edge. See ``_format_bucket_tag`` + top_picks loop 98.
        bucket_tag = _format_bucket_tag(best)
        print(f"  Top investable: {best.get('ticker', '?')} (composite={float(best.get('composite_score', 0.0)):+.3f}{estimate_marker},{bucket_tag} " f"决策={decision_str} 胜率={decision_wr_str}, T+30={t30_str} T+30胜率={t30_wr_str}, {sample_str})")
    print(f"  Completed in {elapsed:.1f}s")

    # R77 (R71/R72/R73/R75/R76 trust-calibration family): this surface emits a
    # concrete Top-investable ticker with composite score, T+30 edge and win
    # rate. Carry the same non-advice disclaimer as the other six user-facing
    # decision surfaces (--top-picks / --daily-brief / --position-check /
    # --explain / --why-not / PDF / backtest) so users do not read
    # "Top investable: 000001 (T+30=+3.2%, 胜率=58%)" as a deterministic
    # instruction (serves product goal "更高确信" = confidence includes honest
    # boundary disclosure).
    _print_decision_flow_disclaimer()

    return flow_result


def _print_decision_flow_disclaimer() -> None:
    """R77: research-only disclaimer at the end of the --decision-flow summary.

    Mirrors the R71 ``--top-picks`` disclaimer wording so all user-facing
    decision surfaces stay consistent.
    """
    print(f"\n  {Fore.WHITE}⚠ 以上决策流摘要由 AI 模型自动生成, 仅供研究 / 学习用途, 不构成任何投资建议。" f"实际投资需结合个人风险承受能力与最新市场情况。{Style.RESET_ALL}")


def render_decision_flow_summary(flow: dict[str, Any]) -> str:
    """Render a compact summary suitable for daily brief."""
    lines = [
        f"Decision Flow — {flow.get('trade_date', '?')}",
        f"Recommendations: {flow.get('recommendation_count', 0)}",
        f"Freshness: {'PASS' if flow.get('freshness', {}).get('fresh') else 'WARNING'}",
        f"High consistency: {flow.get('high_consistency_count', 0)}/{flow.get('recommendation_count', 0)}",
        f"Outliers: {flow.get('outlier_count', 0)}",
    ]
    return "\n".join(lines)
