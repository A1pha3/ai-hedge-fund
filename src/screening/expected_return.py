"""预期收益估算 — P9-1.

基于历史 score_b 分桶的实际收益, 为每只推荐估算预期 N 日收益。
复用 :mod:`confidence_calibration` 的校准数据, 无需额外数据源。

工作原理:
1. 加载历史 tracking 数据, 计算 score 分桶的平均收益
2. 根据当前推荐的 score_b, 找到所属分桶
3. 用该分桶的历史平均收益作为"预期收益"

业界对标: QuantConnect Alpha Streams 的预期收益展示; Numerai 的
"Expected Value" 列。

CLI 集成:
    通过 ``--decision-flow`` 或 ``--expected-returns`` 调用。
    结果也整合到 ``--auto`` 输出的推荐列表中。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.screening.confidence_calibration import (
    _find_bucket,
    _load_tracking_records,
    CalibrationSummary,
    compute_calibration,
)
from src.screening.consecutive_recommendation import resolve_report_dir
from src.screening.drawdown_estimate import compute_drawdown_estimate
from src.utils.display import Fore, Style
from src.utils.numeric import safe_float  # NS-13: NaN-rejecting coercion

# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

HORIZONS = ("t1", "t5", "t10", "t20", "t30")

HORIZON_LABELS = {
    "t1": "T+1",
    "t5": "T+5",
    "t10": "T+10",
    "t20": "T+20",
    "t30": "T+30",
}


@dataclass
class ExpectedReturn:
    """单只推荐的预期收益信息。"""

    ticker: str
    score_b: float
    bucket_label: str
    bucket_sample_count: int
    expected_returns: dict[str, float | None]  # horizon → expected return pct
    win_rates: dict[str, float | None]  # horizon → win rate
    # Records in this bucket old enough to have a realized 30-day return.
    # ``bucket_sample_count`` counts every record; the T+30 edge/胜率 come from
    # this smaller matured subset. Surfacing both lets users judge how much the
    # 30-day stat actually backs. See BH-002.
    bucket_t30_mature_count: int = 0
    # O-4: per-bucket mean of realized LOSING T+30 returns (typical downside /
    # 赔率). Pairs with the T+30 win rate so users can size position by tail
    # risk, not just win frequency. None when the bucket has no losing records.
    bucket_t30_avg_negative_return: float | None = None
    # P-2: per-bucket sample std of realized T+30 returns (outcome dispersion /
    # 离散度). Pairs with the T+30 mean edge so users can judge confidence in
    # the point estimate. None when the bucket has < 2 matured T+30 records.
    bucket_t30_std_return: float | None = None
    # Q-5: per-bucket 5th percentile of realized T+30 returns (tail risk /
    # worst plausible). Completes the risk triplet (R144 mean-of-losers + P-2 std
    # + this tail). None when < 2 matured T+30.
    bucket_t30_p5_return: float | None = None
    # R-5.C: per-bucket median of realized T+30 returns (诚实窄预测).
    # Mean 被 outlier 污染 (688008 +112% 案例); median 更稳健反映典型票.
    # None when bucket has no matured T+30 records.
    bucket_t30_median_return: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "score_b": round(self.score_b, 4),
            "bucket_label": self.bucket_label,
            "bucket_sample_count": self.bucket_sample_count,
            "bucket_t30_mature_count": self.bucket_t30_mature_count,
            "bucket_t30_avg_negative_return": (
                round(self.bucket_t30_avg_negative_return, 4)
                if self.bucket_t30_avg_negative_return is not None
                else None
            ),
            "bucket_t30_std_return": (
                round(self.bucket_t30_std_return, 4)
                if self.bucket_t30_std_return is not None
                else None
            ),
            "bucket_t30_p5_return": (
                round(self.bucket_t30_p5_return, 4)
                if self.bucket_t30_p5_return is not None
                else None
            ),
            "bucket_t30_median_return": (
                round(self.bucket_t30_median_return, 4)
                if self.bucket_t30_median_return is not None
                else None
            ),
            "expected_returns": {k: round(v, 4) if v is not None else None for k, v in self.expected_returns.items()},
            "win_rates": {k: round(v, 4) if v is not None else None for k, v in self.win_rates.items()},
        }


@dataclass
class ExpectedReturnReport:
    """预期收益汇总报告。"""

    trade_date: str
    lookback_days: int
    total_samples: int
    items: list[ExpectedReturn] = field(default_factory=list)
    # Records old enough to have a realized 30-day return. ``total_samples``
    # counts every recommendation in the lookback window regardless of
    # maturity, so the long-horizon (T+30) edge must be attributed to this
    # smaller, matured denominator — otherwise a freshly-recommended batch
    # inflates the displayed backing-sample count for a stat it cannot yet
    # contribute to. See BH-002.
    mature_t30_samples: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "trade_date": self.trade_date,
            "lookback_days": self.lookback_days,
            "total_samples": self.total_samples,
            "mature_t30_samples": self.mature_t30_samples,
            "items": [item.to_dict() for item in self.items],
        }


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------


def _build_bucket_return_map(calibration: CalibrationSummary) -> dict[str, dict[str, float | None]]:
    """Build a mapping from bucket label → {horizon: return}.

    R-5.C (autodev): T+30 (``t30``) uses bucket **median** (``t30_median_return``)
    instead of mean (``t30_avg_return``). Realized evidence R-6/R-7: median MAE
    8.7% < mean MAE 10.7% — mean is outlier-polluted (e.g. 688008 +112% case
    dragged a bucket mean positive while the typical stock was negative).
    Median is the honest "typical stock" T+30 prediction.

    Isotonic calibration (``src/screening/isotonic_calibration.py``) is DEFERRED:
    NS-4 (C192) found the T+30 score→winrate ranking is **inverted** (low-score
    50.5% → high-score 39.5%). PAV isotonic enforces monotonicity and would
    **mask** that inversion in the displayed T+30 prediction — dishonest while
    ``rank_monotonicity`` footer separately discloses 倒挂. Revisit isotonic
    wiring after the owner fixes the inversion.

    BUY-gate orthogonality: the BUY gate (``investability.build_front_door_verdict``)
    and ranking tie-breakers (C222) consume only ``t5``/``t10`` (T+5/T+10),
    NOT ``t30``. T+30 is retained solely as a long-term invalidation /
    display signal (``invalidation_reasons`` "T+30 edge 转负" is advisory).
    So this t30 mean→median switch does not change any BUY verdict or ranking
    order — orthogonal to iv069 (vol-threshold) post-push observation.

    t1/t5/t10/t20 remain mean-based (``tN_avg_return``).

    Returns:
        ``{"高 (>0.8)": {"t1": 1.5, "t5": 3.2, ..., "t30": <median>}, ...}``
    """
    result: dict[str, dict[str, float | None]] = {}
    for bucket in calibration.buckets:
        result[bucket.label] = {
            "t1": bucket.t1_avg_return,
            "t5": bucket.t5_avg_return,
            "t10": bucket.t10_avg_return,
            "t20": bucket.t20_avg_return,
            "t30": bucket.t30_median_return,  # R-5.C: median (outlier-robust); was t30_avg_return
        }
    return result


def _build_bucket_winrate_map(calibration: CalibrationSummary) -> dict[str, dict[str, float | None]]:
    """Build a mapping from bucket label → {horizon: win_rate}."""
    result: dict[str, dict[str, float | None]] = {}
    for bucket in calibration.buckets:
        result[bucket.label] = {
            "t1": bucket.t1_win_rate,
            "t5": bucket.t5_win_rate,
            "t10": bucket.t10_win_rate,
            "t20": bucket.t20_win_rate,
            "t30": bucket.t30_win_rate,
        }
    return result


def _build_bucket_sample_map(calibration: CalibrationSummary) -> dict[str, int]:
    """Build a mapping from bucket label → sample count."""
    return {bucket.label: bucket.sample_count for bucket in calibration.buckets}


def _build_bucket_mature_t30_map(calibration: CalibrationSummary) -> dict[str, int]:
    """Build a mapping from bucket label → matured T+30 sample count.

    ``bucket.sample_count`` counts every record; this counts only records with
    a realized 30-day return, so a per-row T+30 stat can be attributed to its
    true denominator instead of the larger all-records count. See BH-002.
    """
    return {bucket.label: bucket.t30_sample_count for bucket in calibration.buckets}


def _build_bucket_t30_downside_map(calibration: CalibrationSummary) -> dict[str, float | None]:
    """Build a mapping from bucket label → mean realized LOSING T+30 return.

    O-4: the typical downside (赔率) for the bucket — how much a losing pick
    tends to cost. None when the bucket has no observed losers.
    """
    return {bucket.label: bucket.t30_avg_negative_return for bucket in calibration.buckets}


def _build_bucket_t30_std_map(calibration: CalibrationSummary) -> dict[str, float | None]:
    """Build a mapping from bucket label → sample std of realized T+30 returns.

    P-2: outcome dispersion (离散度) for the bucket — how widely individual T+30
    outcomes vary around the mean. None when the bucket has < 2 matured T+30.
    """
    return {bucket.label: bucket.t30_std_return for bucket in calibration.buckets}


def _build_bucket_t30_p5_map(calibration: CalibrationSummary) -> dict[str, float | None]:
    """Build a mapping from bucket label → 5th percentile of realized T+30 returns.

    Q-5: tail risk (worst plausible) for the bucket. None when < 2 matured T+30.
    """
    return {bucket.label: bucket.t30_p5_return for bucket in calibration.buckets}


def _build_bucket_t30_median_map(calibration: CalibrationSummary) -> dict[str, float | None]:
    """Build a mapping from bucket label → median of realized T+30 returns.

    R-5.C: 诚实窄预测. Mean 被 outlier 污染 (例如 688008 +112% 案例); median
    更稳健地反映"典型票"在该分位的实际 T+30 表现. None when the bucket has no
    matured T+30 records (复用 confidence_calibration.R-6 的 t30_median_return).
    """
    return {bucket.label: bucket.t30_median_return for bucket in calibration.buckets}


def compute_expected_returns(
    *,
    recommendations: list[dict[str, Any]],
    lookback_days: int = 60,
    reports_dir: Path | None = None,
) -> ExpectedReturnReport:
    """Compute expected returns for a list of recommendations.

    Args:
        recommendations: List of recommendation dicts (must have ``ticker`` and ``score_b``)
        lookback_days: How many days of history to use for calibration
        reports_dir: Reports directory for tracking history

    Returns:
        :class:`ExpectedReturnReport`
    """
    search_dir = reports_dir or resolve_report_dir()
    records = _load_tracking_records(search_dir)
    calibration = compute_calibration(records, lookback_days=lookback_days)
    return_map = _build_bucket_return_map(calibration)
    winrate_map = _build_bucket_winrate_map(calibration)
    sample_map = _build_bucket_sample_map(calibration)
    mature_t30_map = _build_bucket_mature_t30_map(calibration)
    downside_t30_map = _build_bucket_t30_downside_map(calibration)
    std_t30_map = _build_bucket_t30_std_map(calibration)
    p5_t30_map = _build_bucket_t30_p5_map(calibration)
    median_t30_map = _build_bucket_t30_median_map(calibration)

    trade_date = ""
    items: list[ExpectedReturn] = []
    for rec in recommendations:
        ticker = str(rec.get("ticker", ""))
        score_b = safe_float(rec.get("score_b", 0.0))  # NS-13: NaN is truthy, `float(x or 0.0)` passed NaN through → NaN bucket lookup
        if not trade_date:
            trade_date = str(rec.get("trade_date", ""))

        bucket_info = _find_bucket(score_b)
        if bucket_info is None:
            items.append(
                ExpectedReturn(
                    ticker=ticker,
                    score_b=score_b,
                    bucket_label="未知",
                    bucket_sample_count=0,
                    expected_returns={h: None for h in HORIZONS},
                    win_rates={h: None for h in HORIZONS},
                )
            )
            continue

        label = bucket_info[0]
        items.append(
            ExpectedReturn(
                ticker=ticker,
                score_b=score_b,
                bucket_label=label,
                bucket_sample_count=sample_map.get(label, 0),
                expected_returns=return_map.get(label, {h: None for h in HORIZONS}),
                win_rates=winrate_map.get(label, {h: None for h in HORIZONS}),
                bucket_t30_mature_count=mature_t30_map.get(label, 0),
                bucket_t30_avg_negative_return=downside_t30_map.get(label),
                bucket_t30_std_return=std_t30_map.get(label),
                bucket_t30_p5_return=p5_t30_map.get(label),
                bucket_t30_median_return=median_t30_map.get(label),
            )
        )

    return ExpectedReturnReport(
        trade_date=trade_date,
        lookback_days=lookback_days,
        total_samples=calibration.total_samples,
        mature_t30_samples=calibration.total_t30_samples,
        items=items,
    )


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _fmt_return(value: float | None) -> str:
    """Format an expected return value with color coding."""
    if value is None:
        return f"{Fore.YELLOW}—{Style.RESET_ALL}"
    if value > 0:
        return f"{Fore.GREEN}+{value:.2f}%{Style.RESET_ALL}"
    if value < 0:
        return f"{Fore.RED}{value:.2f}%{Style.RESET_ALL}"
    return f"{Fore.WHITE}0.00%{Style.RESET_ALL}"


def _fmt_winrate(value: float | None) -> str:
    """Format a win rate value."""
    if value is None:
        return f"{Fore.YELLOW}—{Style.RESET_ALL}"
    if value >= 0.55:
        color = Fore.GREEN
    elif value >= 0.45:
        color = Fore.YELLOW
    else:
        color = Fore.RED
    return f"{color}{value:.0%}{Style.RESET_ALL}"


def render_expected_returns(report: ExpectedReturnReport) -> str:
    """Render expected returns as a readable table.

    Shows each recommendation with:
    - Score bucket
    - Historical sample count
    - Expected return per horizon (T+1/T+5/T+10/T+20/T+30)
    - Win rate per horizon
    """
    if not report.items:
        return f"\n{Fore.CYAN}📊 预期收益估算{Style.RESET_ALL}\n  无推荐数据\n"

    lines = [
        f"\n{Fore.CYAN}📊 预期收益估算{Style.RESET_ALL}",
        f"  基于最近 {report.lookback_days} 天 {report.total_samples} 条历史推荐"
        f" (其中 {report.mature_t30_samples} 条已有 T+30 实际收益)",
        "",
        # R52: add T+30 win-rate column. ``win_rates`` is computed for all
        # horizons but the full render previously showed only expected returns
        # — the T+30 win rate (which backs the BUY-gate edge) was
        # computed-but-hidden. Surfacing it lets the user judge whether the
        # T+30 edge is backed by a high or low hit rate.
        # R-5.C: add T+30中位 column. T+30 mean is polluted by outliers
        # (e.g. 688008 +112%); median is a more honest "typical pick" view.
        # 用户看到 T+30 与 T+30中位 差距大时, 即可判断本桶被尾部极端值拉高.
        f"  {'标的':<8} {'Score':>6} {'分位':>10} {'样本':>4} {'T30熟':>5}  {'T+1':>8}  {'T+5':>8}  {'T+10':>8}  {'T+20':>9}  {'T+30':>9}  {'T+30中位':>9}  {'T+30胜率':>8}",
        f"  {'─' * 8} {'─' * 6} {'─' * 10} {'─' * 4} {'─' * 5}  {'─' * 8}  {'─' * 8}  {'─' * 8}  {'─' * 9}  {'─' * 9}  {'─' * 9}  {'─' * 8}",
    ]

    for item in report.items:
        er = item.expected_returns
        wr_t30 = _fmt_winrate(item.win_rates.get("t30"))
        # R140 Bug Hunt (R51/R52 family — same-function coverage gap): c271 added the
        # ``⚠少样本`` low-confidence marker to ``render_expected_returns_compact`` (the
        # --decision-flow view) but missed this full --expected-returns table, even
        # though both render the SAME T+30 winrate via the SAME ``_fmt_winrate`` and
        # both have ``bucket_t30_mature_count`` available (the full table even displays
        # it as ``T30熟``). A per-bucket n=1 "100% winrate" rendered confident-green
        # here but flagged-yellow in --decision-flow — c271's honesty fix was
        # inconsistent across the two surfaces. Mirror the compact renderer's c271
        # guard: flag when 0 < mature < 5 so a green 100% on n=1 does not mislead.
        if 0 < item.bucket_t30_mature_count < 5:
            wr_t30 = f"{wr_t30} {Fore.YELLOW}⚠少样本{Style.RESET_ALL}"
        row = (
            f"  {item.ticker:<8} {item.score_b:>6.3f} {item.bucket_label:>10} {item.bucket_sample_count:>4} {item.bucket_t30_mature_count:>5}"
            f"  {_fmt_return(er.get('t1')):>18}"
            f"  {_fmt_return(er.get('t5')):>18}"
            f"  {_fmt_return(er.get('t10')):>18}"
            f"  {_fmt_return(er.get('t20')):>19}"
            f"  {_fmt_return(er.get('t30')):>19}"
            f"  {_fmt_return(item.bucket_t30_median_return):>19}"
            f"  {wr_t30:>8}"
        )
        lines.append(row)

    lines.append("")
    lines.append(
        f"  {Fore.WHITE}说明: 预期收益 = 历史同 score 分位的平均实际收益;"
        f"T+30中位 = 同分位 T+30 收益中位数 (R-5.C 诚实窄预测, 抗 outlier)."
        f"「样本」为该分位全部历史推荐数;「T30熟」为其中已满 30 天、"
        f"实际贡献 T+30 统计的成熟样本数。仅供参考。{Style.RESET_ALL}"
    )
    return "\n".join(lines)


def render_expected_returns_compact(report: ExpectedReturnReport) -> str:
    """Render a compact summary for integration into decision flow.

    C222 (2026-06-28 horizon 一致性): this is the *long-horizon invalidation*
    view (T+20/T+30) — historical回测 distribution, tail risk, max drawdown.
    The BUY-gate decision horizon is T+5 OR T+10 (see ``_meets_quality_bar``
    C220 commit 4184dd7e); T+30 here is the long-term衰退 signal retained
    alongside the short-horizon decision (see ``invalidation_reasons`` in
    ``build_front_door_verdict``). Header labels the view as "长期 invalidation
    horizon" so power-users do not mistake T+30 stats for the BUY decision basis.
    """
    if not report.items:
        return "无预期收益数据"

    # Long-horizon invalidation view (T+20/T+30). Attribute the T+30 stat to
    # its matured-sample denominator (BH-002), not the all-records
    # ``bucket_sample_count``, so users see how much actually backs the number.
    lines = [f"  长期 invalidation horizon T+20/T+30 edge (基于 {report.total_samples} 条历史, 其中 {report.mature_t30_samples} 条已满 30 天; BUY 决策 horizon 为 T+5/T+10):"]
    for item in report.items[:5]:
        er = item.expected_returns
        t20 = _fmt_return(er.get("t20"))
        t30 = _fmt_return(er.get("t30"))
        wr_str = _fmt_winrate(item.win_rates.get("t30"))
        # C271 (2026-07-01, empirical dogfood via --decision-flow on 2026-06-30):
        # flag the T+30 winrate low-confidence when the mature sample is tiny
        # (< 5). _fmt_winrate colors 100% green regardless of n; a per-bucket n=1
        # "100% winrate" is statistically meaningless yet rendered confident-green
        # — for a 赚钱工具 this invites over-reaction to noise. The codebase
        # already requires backing_sample >= 20 for the BUY gate; this extends
        # that honesty to the display without hiding the number.
        _t30_mature = item.bucket_t30_mature_count
        if 0 < _t30_mature < 5:
            wr_str = f"{wr_str} {Fore.YELLOW}⚠少样本{Style.RESET_ALL}"
        # P-2: show outcome dispersion (±std) next to T+30 edge so the user can
        # calibrate confidence in the point estimate. +3.2%(±1.5%) vs +3.2%(±8%)
        # are very different bets even with identical mean.
        std_str = f" (±{item.bucket_t30_std_return:.1f}% 离散)" if item.bucket_t30_std_return is not None else ""
        # Q-5: tail risk (5th percentile) — worst plausible outcome.
        p5_str = f"  尾={item.bucket_t30_p5_return:.1f}%" if item.bucket_t30_p5_return is not None else ""
        # Q-2: average-path max drawdown from per-horizon cumulative returns.
        # +3.2% T+30 with −15% mid-hold drawdown ≠ +3.2% with −2%; the path matters.
        dd_est = compute_drawdown_estimate(er)
        dd_str = f"  回撤={dd_est.max_drawdown:.1f}%" if dd_est.available and dd_est.max_drawdown is not None else ""
        # R-5.C: T+30 中位数 (诚实窄预测). 与 mean 并列展示 — 差距大说明本桶被
        # outlier 拉高/拉低, 用户应更信任 median 作为典型票的代表.
        med_str = f"  T+30中位={_fmt_return(item.bucket_t30_median_return)}" if item.bucket_t30_median_return is not None else ""
        lines.append(
            f"    {item.ticker:<8} score={item.score_b:.3f}  样本={item.bucket_sample_count:<3d}(T30熟={item.bucket_t30_mature_count:<3d})  T+20={t20}  T+30={t30}{med_str}{std_str}  T+30胜率={wr_str}{dd_str}{p5_str}"
        )

    return "\n".join(lines)
