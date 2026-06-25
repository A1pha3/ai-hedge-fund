"""置信度校准 (`--confidence-calibration`) — P0-9.

把抽象的 score_b (0-1) 校准为用户可理解的**历史命中率 / 预期收益区间**。
基于 ``tracking_history.json`` 中历史推荐的实际 T+1/T+3/T+5 收益, 按 score 分桶统计。

输出:
1. 校准曲线表: 每个 score 桶 → 样本数 / T+1 命中率 / T+3 命中率 / T+5 命中率 / 平均收益
2. Top N 推荐的校准结果: 每只票落到哪个桶 → 该桶的历史命中率

业界对标: Numerai「Calibration Plot」、QuantConnect Alpha Streams 的回测后验分布。
我们的实现用真实推荐 + 真实成交收益, 而非合成 benchmark。

CLI:
    python src/main.py --confidence-calibration [--top-n=10] [--lookback=60]
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.screening.consecutive_recommendation import (
    load_tracking_history,
    resolve_report_dir,
)
from src.screening.data_quality_audit import load_latest_recommendations
from src.utils.display import Fore, Style

# ---------------------------------------------------------------------------
# Constants — score buckets
# ---------------------------------------------------------------------------

# 5 桶, 每桶 0.1 宽 (score_b 实际范围 0-1, 但理论可到 -1)
SCORE_BUCKETS: tuple[tuple[str, float, float], ...] = (
    ("高 (>0.8)", 0.8, 1.01),
    ("中高 (0.7-0.8)", 0.7, 0.8),
    ("中 (0.6-0.7)", 0.6, 0.7),
    ("中低 (0.5-0.6)", 0.5, 0.6),
    ("低 (<0.5)", -1.01, 0.5),
)

DEFAULT_LOOKBACK_DAYS: int = 60


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class ScoreBucketStats:
    """单个 score 桶的历史统计。"""

    label: str
    score_low: float
    score_high: float
    sample_count: int = 0
    t1_win_rate: float | None = None
    t3_win_rate: float | None = None
    t5_win_rate: float | None = None
    t10_win_rate: float | None = None
    # Task 4 (multi-horizon diagnosis): T+15 horizon stat. Same semantics as
    # t10_win_rate — fraction of matured T+15 returns that are positive. None
    # when no record in the bucket has a realized 15-day return.
    t15_win_rate: float | None = None
    t20_win_rate: float | None = None
    # Task 4: T+25 horizon stat (midpoint between T+20 / T+30).
    t25_win_rate: float | None = None
    t30_win_rate: float | None = None
    t1_avg_return: float | None = None
    t5_avg_return: float | None = None
    t10_avg_return: float | None = None
    # Task 4: mean realized T+15 return; None when no matured T+15 record.
    t15_avg_return: float | None = None
    t20_avg_return: float | None = None
    # Task 4: mean realized T+25 return.
    t25_avg_return: float | None = None
    t30_avg_return: float | None = None
    # R-6: median of realized T+30 returns — outlier-robust center vs t30_avg_return.
    # realized evidence 20260624 showed arithmetic mean is distorted by a single
    # extreme winner; median reflects the typical pick. mean ≫ median ⇒ outlier
    # pollution. None when no matured T+30.
    t30_median_return: float | None = None
    # O-4: mean of realized LOSING T+30 returns (赔率 / typical-downside).
    t30_avg_negative_return: float | None = None
    # P-2: sample standard deviation of realized T+30 returns (outcome dispersion).
    # 服务产品目标 "更高确信": 点估计 "+3.2%" 此前无离散度; ±std 让用户校准对点估计的
    # 信任 (±1.5% vs ±8% 是完全不同的置信度, 即使 mean 相同)。None when <2 matured T+30。
    t30_std_return: float | None = None
    # Q-5: 5th percentile of realized T+30 returns (tail risk / CVaR proxy).
    # 服务"赔率"深尾: R144 给亏损均值, P-2 给离散度, 此项给最坏 plausible 情形
    # (-5% 均值配 -30% 尾 ≠ -5% 配 -8% 尾, 即使 std 相同)。None when <2 matured T+30。
    t30_p5_return: float | None = None
    # Matured-sample counts per horizon (records that actually have a realized
    # return at that horizon). ``sample_count`` counts every record in the
    # bucket regardless of return maturity, so displaying it next to a
    # realized-horizon stat (e.g. T+30 edge) misleads users into thinking the
    # full bucket backs that number. These fields let renderers attribute each
    # horizon's stat to its true (smaller, matured) denominator. See BH-002.
    t1_sample_count: int = 0
    t3_sample_count: int = 0
    t5_sample_count: int = 0
    t10_sample_count: int = 0
    # Task 4: matured-sample counts for the new T+15 / T+25 horizons.
    t15_sample_count: int = 0
    t20_sample_count: int = 0
    t25_sample_count: int = 0
    t30_sample_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "score_low": self.score_low,
            "score_high": self.score_high,
            "sample_count": self.sample_count,
            "t1_win_rate": self.t1_win_rate,
            "t3_win_rate": self.t3_win_rate,
            "t5_win_rate": self.t5_win_rate,
            "t10_win_rate": self.t10_win_rate,
            "t15_win_rate": self.t15_win_rate,
            "t20_win_rate": self.t20_win_rate,
            "t25_win_rate": self.t25_win_rate,
            "t30_win_rate": self.t30_win_rate,
            "t1_avg_return": self.t1_avg_return,
            "t5_avg_return": self.t5_avg_return,
            "t10_avg_return": self.t10_avg_return,
            "t15_avg_return": self.t15_avg_return,
            "t20_avg_return": self.t20_avg_return,
            "t25_avg_return": self.t25_avg_return,
            "t30_avg_return": self.t30_avg_return,
            "t30_median_return": self.t30_median_return,
            "t30_avg_negative_return": self.t30_avg_negative_return,
            "t30_std_return": self.t30_std_return,
            "t30_p5_return": self.t30_p5_return,
            "t1_sample_count": self.t1_sample_count,
            "t3_sample_count": self.t3_sample_count,
            "t5_sample_count": self.t5_sample_count,
            "t10_sample_count": self.t10_sample_count,
            "t15_sample_count": self.t15_sample_count,
            "t20_sample_count": self.t20_sample_count,
            "t25_sample_count": self.t25_sample_count,
            "t30_sample_count": self.t30_sample_count,
        }


@dataclass
class CalibrationSummary:
    """校准结果汇总。"""

    lookback_days: int
    total_samples: int = 0
    buckets: list[ScoreBucketStats] = field(default_factory=list)
    overall_t1_win_rate: float | None = None
    overall_t5_win_rate: float | None = None
    overall_t10_win_rate: float | None = None
    # Task 4: overall T+15 / T+25 aggregates across all buckets.
    overall_t15_win_rate: float | None = None
    overall_t20_win_rate: float | None = None
    overall_t25_win_rate: float | None = None
    overall_t30_win_rate: float | None = None
    overall_t5_avg_return: float | None = None
    overall_t10_avg_return: float | None = None
    # Task 4: overall mean realized T+15 / T+25 return across all buckets.
    overall_t15_avg_return: float | None = None
    overall_t20_avg_return: float | None = None
    overall_t25_avg_return: float | None = None
    overall_t30_avg_return: float | None = None
    # Total records with a realized return at each horizon (sum of per-bucket
    # matured counts). ``total_samples`` counts every record; these count only
    # records old enough to have a realized N-day return, so a 30-day edge
    # header can be attributed to its true denominator. See BH-002.
    total_t5_samples: int = 0
    total_t10_samples: int = 0
    # Task 4: total matured records at T+15 / T+25 (sum of per-bucket matured counts).
    total_t15_samples: int = 0
    total_t20_samples: int = 0
    total_t25_samples: int = 0
    total_t30_samples: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "lookback_days": self.lookback_days,
            "total_samples": self.total_samples,
            "buckets": [b.to_dict() for b in self.buckets],
            "overall_t1_win_rate": self.overall_t1_win_rate,
            "overall_t5_win_rate": self.overall_t5_win_rate,
            "overall_t10_win_rate": self.overall_t10_win_rate,
            "overall_t15_win_rate": self.overall_t15_win_rate,
            "overall_t20_win_rate": self.overall_t20_win_rate,
            "overall_t25_win_rate": self.overall_t25_win_rate,
            "overall_t30_win_rate": self.overall_t30_win_rate,
            "overall_t5_avg_return": self.overall_t5_avg_return,
            "overall_t10_avg_return": self.overall_t10_avg_return,
            "overall_t15_avg_return": self.overall_t15_avg_return,
            "overall_t20_avg_return": self.overall_t20_avg_return,
            "overall_t25_avg_return": self.overall_t25_avg_return,
            "overall_t30_avg_return": self.overall_t30_avg_return,
            "total_t5_samples": self.total_t5_samples,
            "total_t10_samples": self.total_t10_samples,
            "total_t15_samples": self.total_t15_samples,
            "total_t20_samples": self.total_t20_samples,
            "total_t25_samples": self.total_t25_samples,
            "total_t30_samples": self.total_t30_samples,
        }


# ---------------------------------------------------------------------------
# History loading
# ---------------------------------------------------------------------------


def _load_tracking_records(report_dir: Path | None = None) -> list[dict[str, Any]]:
    """读取 ``tracking_history.json`` 的 records 列表; 缺失返回 []。

    Delegates to :func:`src.screening.consecutive_recommendation.load_tracking_history`.
    """
    search_dir = report_dir or resolve_report_dir()
    return load_tracking_history(search_dir)


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _win_rate_or_none(valid_returns: list[float]) -> float | None:
    """Fraction of realized returns that are positive; None when empty.

    Centralizes the per-horizon win-rate pattern so every horizon uses the
    same denominator (matured returns only) and a future horizon addition
    touches one helper instead of six near-identical expressions.
    """
    return (sum(1 for x in valid_returns if x > 0) / len(valid_returns)) if valid_returns else None


def _mean_or_none(valid_returns: list[float]) -> float | None:
    """Arithmetic mean of realized returns; None when empty."""
    return (sum(valid_returns) / len(valid_returns)) if valid_returns else None


def _median_or_none(valid_returns: list[float]) -> float | None:
    """Median of realized returns; None when empty.

    R-6 (realized evidence 20260624): ``t30_avg_return`` (arithmetic mean) is
    outlier-fragile — a single extreme winner (688008 +112% across 4 batches)
    pulled a bucket's mean to +17% while the typical pick was flat. The median
    is immune to that single-pick distortion, so it reflects the *typical*
    realized T+30 for a score bucket. Pair with ``t30_avg_return`` so consumers
    (``--reconcile`` predicted edge, display) can detect outlier pollution
    (mean ≫ median ⇒ a few picks dominate).
    """
    if not valid_returns:
        return None
    ordered = sorted(valid_returns)
    n = len(ordered)
    mid = n // 2
    if n % 2 == 1:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def _mean_negative_or_none(valid_returns: list[float]) -> float | None:
    """Arithmetic mean of realized LOSING returns (< 0); None when no losers.

    O-4: the per-bucket T+30 downside — how much a typical loss costs. Pairs
    with ``t30_win_rate`` to surface 赔率 (a 60% win rate with a -4% typical
    loss is a very different bet from 60% with -30%, but the bare win rate /
    avg-return can't distinguish them)."""
    losers = [x for x in valid_returns if x < 0]
    return (sum(losers) / len(losers)) if losers else None


def _std_or_none(valid_returns: list[float]) -> float | None:
    """Sample standard deviation of realized returns; None when < 2 samples.

    P-2: outcome dispersion for the front-door confidence display. 服务产品目标
    "更高确信" — a point-estimate mean (+3.2%) is meaningless without dispersion;
    +3.2% (±1.5%) vs +3.2% (±8%) imply very different confidence in the estimate.
    Uses sample std (n-1 denominator) so small buckets stay conservative."""
    n = len(valid_returns)
    if n < 2:
        return None
    mean = sum(valid_returns) / n
    variance = sum((x - mean) ** 2 for x in valid_returns) / (n - 1)
    return variance ** 0.5


def _p5_or_none(valid_returns: list[float]) -> float | None:
    """5th percentile of realized returns (tail risk); None when < 2 samples.

    Q-5: the worst plausible outcome (CVaR proxy). Delegates to
    ``tail_risk._percentile_or_none`` (linear-interpolation percentile).
    Pairs with R144 mean-of-losers + P-2 std to complete the risk triplet
    (mean + dispersion + tail)."""
    if len(valid_returns) < 2:
        return None
    from src.screening.tail_risk import _percentile_or_none

    return _percentile_or_none(valid_returns, 5)


# ---------------------------------------------------------------------------
# Calibration logic
# ---------------------------------------------------------------------------


def _score_in_bucket(score: float, low: float, high: float) -> bool:
    """左闭右开 [low, high), 但 high=1.01 时含 1.0。"""
    return low <= score < high


def _find_bucket(score: float) -> tuple[str, float, float] | None:
    """根据 score 定位所属桶; 落入桶外返回 None。"""
    for label, low, high in SCORE_BUCKETS:
        if _score_in_bucket(score, low, high):
            return (label, low, high)
    return None


def compute_calibration(
    records: list[dict[str, Any]], lookback_days: int = DEFAULT_LOOKBACK_DAYS
) -> CalibrationSummary:
    """计算 score 分桶校准。

    Args:
        records: tracking_history 记录列表
        lookback_days: 仅取最近 N 天的记录 (按 recommended_date 倒序)

    Returns:
        :class:`CalibrationSummary`
    """
    # 按日期倒序, 截取 lookback_days 天
    sorted_records = sorted(
        records,
        key=lambda r: str(r.get("recommended_date") or ""),
        reverse=True,
    )
    # 取最近 lookback_days 天的不同日期集合
    unique_dates: list[str] = []
    seen = set()
    for rec in sorted_records:
        d = str(rec.get("recommended_date") or "")
        if d and d not in seen:
            seen.add(d)
            unique_dates.append(d)
    cutoff_dates = set(unique_dates[:lookback_days]) if lookback_days > 0 else set(unique_dates)
    filtered = [r for r in sorted_records if str(r.get("recommended_date") or "") in cutoff_dates]

    # 初始化桶
    bucket_records: dict[str, list[dict[str, Any]]] = {label: [] for label, _, _ in SCORE_BUCKETS}

    for rec in filtered:
        score = _optional_float(rec.get("recommendation_score"))
        if score is None:
            continue
        bucket = _find_bucket(score)
        if bucket is None:
            continue
        bucket_records[bucket[0]].append(rec)

    # 统计每桶
    bucket_stats: list[ScoreBucketStats] = []
    all_t1: list[float] = []
    all_t5: list[float] = []
    all_t10: list[float] = []
    # Task 4: aggregate T+15 / T+25 valid returns across buckets.
    all_t15: list[float] = []
    all_t20: list[float] = []
    all_t25: list[float] = []
    all_t30: list[float] = []
    all_t5_returns: list[float] = []
    all_t10_returns: list[float] = []
    # Task 4: aggregate T+15 / T+25 returns for overall avg_return.
    all_t15_returns: list[float] = []
    all_t20_returns: list[float] = []
    all_t25_returns: list[float] = []
    all_t30_returns: list[float] = []
    for label, low, high in SCORE_BUCKETS:
        recs = bucket_records[label]
        t1_returns = [_optional_float(r.get("next_day_return")) for r in recs]
        t3_returns = [_optional_float(r.get("next_3day_return")) for r in recs]
        t5_returns = [_optional_float(r.get("next_5day_return")) for r in recs]
        t10_returns = [_optional_float(r.get("next_10day_return")) for r in recs]
        # Task 4: T+15 / T+25 returns extraction.
        t15_returns = [_optional_float(r.get("next_15day_return")) for r in recs]
        t20_returns = [_optional_float(r.get("next_20day_return")) for r in recs]
        t25_returns = [_optional_float(r.get("next_25day_return")) for r in recs]
        t30_returns = [_optional_float(r.get("next_30day_return")) for r in recs]
        t1_valid = [x for x in t1_returns if x is not None]
        t3_valid = [x for x in t3_returns if x is not None]
        t5_valid = [x for x in t5_returns if x is not None]
        t10_valid = [x for x in t10_returns if x is not None]
        # Task 4: T+15 / T+25 valid filters.
        t15_valid = [x for x in t15_returns if x is not None]
        t20_valid = [x for x in t20_returns if x is not None]
        t25_valid = [x for x in t25_returns if x is not None]
        t30_valid = [x for x in t30_returns if x is not None]
        stats = ScoreBucketStats(
            label=label,
            score_low=low,
            score_high=high,
            sample_count=len(recs),
            t1_win_rate=_win_rate_or_none(t1_valid),
            t3_win_rate=_win_rate_or_none(t3_valid),
            t5_win_rate=_win_rate_or_none(t5_valid),
            t10_win_rate=_win_rate_or_none(t10_valid),
            # Task 4: T+15 / T+25 per-bucket stats.
            t15_win_rate=_win_rate_or_none(t15_valid),
            t20_win_rate=_win_rate_or_none(t20_valid),
            t25_win_rate=_win_rate_or_none(t25_valid),
            t30_win_rate=_win_rate_or_none(t30_valid),
            t1_avg_return=_mean_or_none(t1_valid),
            t5_avg_return=_mean_or_none(t5_valid),
            t10_avg_return=_mean_or_none(t10_valid),
            t15_avg_return=_mean_or_none(t15_valid),
            t20_avg_return=_mean_or_none(t20_valid),
            t25_avg_return=_mean_or_none(t25_valid),
            t30_avg_return=_mean_or_none(t30_valid),
            t30_median_return=_median_or_none(t30_valid),
            t30_avg_negative_return=_mean_negative_or_none(t30_valid),
            t30_std_return=_std_or_none(t30_valid),
            t30_p5_return=_p5_or_none(t30_valid),
            t1_sample_count=len(t1_valid),
            t3_sample_count=len(t3_valid),
            t5_sample_count=len(t5_valid),
            t10_sample_count=len(t10_valid),
            t15_sample_count=len(t15_valid),
            t20_sample_count=len(t20_valid),
            t25_sample_count=len(t25_valid),
            t30_sample_count=len(t30_valid),
        )
        bucket_stats.append(stats)
        all_t1.extend(t1_valid)
        all_t5.extend(t5_valid)
        all_t10.extend(t10_valid)
        # Task 4: extend T+15 / T+25 aggregates.
        all_t15.extend(t15_valid)
        all_t20.extend(t20_valid)
        all_t25.extend(t25_valid)
        all_t30.extend(t30_valid)
        all_t5_returns.extend(t5_valid)
        all_t10_returns.extend(t10_valid)
        all_t15_returns.extend(t15_valid)
        all_t20_returns.extend(t20_valid)
        all_t25_returns.extend(t25_valid)
        all_t30_returns.extend(t30_valid)

    return CalibrationSummary(
        lookback_days=lookback_days,
        total_samples=sum(b.sample_count for b in bucket_stats),
        buckets=bucket_stats,
        overall_t1_win_rate=_win_rate_or_none(all_t1),
        overall_t5_win_rate=_win_rate_or_none(all_t5),
        overall_t10_win_rate=_win_rate_or_none(all_t10),
        # Task 4: overall T+15 / T+25 aggregates.
        overall_t15_win_rate=_win_rate_or_none(all_t15),
        overall_t20_win_rate=_win_rate_or_none(all_t20),
        overall_t25_win_rate=_win_rate_or_none(all_t25),
        overall_t30_win_rate=_win_rate_or_none(all_t30),
        overall_t5_avg_return=_mean_or_none(all_t5_returns),
        overall_t10_avg_return=_mean_or_none(all_t10_returns),
        overall_t15_avg_return=_mean_or_none(all_t15_returns),
        overall_t20_avg_return=_mean_or_none(all_t20_returns),
        overall_t25_avg_return=_mean_or_none(all_t25_returns),
        overall_t30_avg_return=_mean_or_none(all_t30_returns),
        total_t5_samples=len(all_t5),
        total_t10_samples=len(all_t10),
        total_t15_samples=len(all_t15),
        total_t20_samples=len(all_t20),
        total_t25_samples=len(all_t25),
        total_t30_samples=len(all_t30),
    )


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _win_rate_str(rate: float | None) -> str:
    if rate is None:
        return f"{Fore.YELLOW}—{Style.RESET_ALL}     "
    if rate >= 0.55:
        color = Fore.GREEN
    elif rate >= 0.45:
        color = Fore.YELLOW
    else:
        color = Fore.RED
    return f"{color}{rate:>5.0%}{Style.RESET_ALL}"


def _return_str(ret: float | None) -> str:
    if ret is None:
        return f"{Fore.YELLOW}—{Style.RESET_ALL}      "
    color = Fore.GREEN if ret > 0 else (Fore.RED if ret < 0 else Fore.YELLOW)
    return f"{color}{ret:>+6.2f}%{Style.RESET_ALL}"


def render_calibration_table(summary: CalibrationSummary) -> str:
    """渲染 score 分桶校准曲线表。"""
    lines: list[str] = []
    lines.append(
        f"\n{Fore.CYAN}{Style.BRIGHT}═══ 置信度校准 (lookback={summary.lookback_days}d, "
        f"样本={summary.total_samples}, 其中 T+30 成熟={summary.total_t30_samples}) ═══{Style.RESET_ALL}"
    )

    if summary.total_samples == 0:
        lines.append(
            f"{Fore.YELLOW}无历史推荐追踪数据 — 请先多次运行 `--auto` 并 `update_tracking_history` "
            f"积累 T+1/T+3/T+5/T+10/T+20/T+30 实际收益样本。{Style.RESET_ALL}"
        )
        lines.append("")
        return "\n".join(lines)

    header = (
        f"{Fore.CYAN}{'Score 桶':<18} {'样本':>5} "
        f"{'T+1 胜率':>10} {'T+3 胜率':>10} {'T+5 胜率':>10} {'T+10 胜率':>11} {'T+20 胜率':>11} {'T+30 胜率':>11} "
        f"{'T+1 均收':>10} {'T+5 均收':>10} {'T+10 均收':>11} {'T+20 均收':>11} {'T+30 均收':>11}{Style.RESET_ALL}"
    )
    lines.append(header)
    lines.append("─" * 180)

    for b in summary.buckets:
        lines.append(
            f"{b.label:<18} {b.sample_count:>5} "
            f"{_win_rate_str(b.t1_win_rate):>10} {_win_rate_str(b.t3_win_rate):>10} "
            f"{_win_rate_str(b.t5_win_rate):>10} {_win_rate_str(b.t10_win_rate):>11} {_win_rate_str(b.t20_win_rate):>11} {_win_rate_str(b.t30_win_rate):>11} "
            f"{_return_str(b.t1_avg_return):>10} {_return_str(b.t5_avg_return):>10} {_return_str(b.t10_avg_return):>11} {_return_str(b.t20_avg_return):>11} {_return_str(b.t30_avg_return):>11}"
        )

    lines.append("─" * 180)
    overall_line = (
        f"{'整体':<18} {summary.total_samples:>5} "
        f"{_win_rate_str(summary.overall_t1_win_rate):>10} {'':>10} "
        f"{_win_rate_str(summary.overall_t5_win_rate):>10} {_win_rate_str(summary.overall_t10_win_rate):>11} {_win_rate_str(summary.overall_t20_win_rate):>11} {_win_rate_str(summary.overall_t30_win_rate):>11} "
        f"{'':>10} {_return_str(summary.overall_t5_avg_return):>10} {_return_str(summary.overall_t10_avg_return):>11} {_return_str(summary.overall_t20_avg_return):>11} {_return_str(summary.overall_t30_avg_return):>11}"
    )
    lines.append(overall_line)
    lines.append("")
    return "\n".join(lines)


def render_top_n_calibration(
    top_recs: list[dict[str, Any]], summary: CalibrationSummary, top_n: int = 10
) -> str:
    """渲染当前 Top N 推荐的校准结果 (每只票落到哪个桶)。"""
    if not top_recs:
        return ""
    bucket_lookup: dict[tuple[float, float], ScoreBucketStats] = {
        (b.score_low, b.score_high): b for b in summary.buckets
    }

    lines: list[str] = []
    lines.append(f"{Fore.CYAN}{Style.BRIGHT}═══ Top {min(top_n, len(top_recs))} 推荐校准 ═══{Style.RESET_ALL}")
    header = (
        f"{Fore.CYAN}{'Ticker':<8} {'名称':<14} {'Score':>7} "
        f"{'所在桶':<18} {'桶样本':>6} {'T+5 胜率':>10} {'T+10 胜率':>11} {'T+20 胜率':>11} {'T+30 胜率':>11} "
        f"{'T+5 均收':>10} {'T+10 均收':>11} {'T+20 均收':>11} {'T+30 均收':>11}{Style.RESET_ALL}"
    )
    lines.append(header)
    lines.append("─" * 150)

    for rec in top_recs[:top_n]:
        ticker = str(rec.get("ticker") or "")
        name = str(rec.get("name") or "—")[:12]
        score = _optional_float(rec.get("score_b")) or 0.0
        bucket = _find_bucket(score)
        if bucket is None:
            lines.append(f"{ticker:<8} {name:<14} {score:>7.2f}  {Fore.YELLOW}桶外{Style.RESET_ALL}")
            continue
        stats = bucket_lookup.get((bucket[1], bucket[2]))
        if stats is None or stats.sample_count == 0:
            lines.append(
                f"{ticker:<8} {name:<14} {score:>7.2f}  {bucket[0]:<18} "
                f"{Fore.YELLOW}{'—':>6} {Fore.YELLOW}无样本, 不可校准{Style.RESET_ALL}"
            )
            continue
        lines.append(
            f"{ticker:<8} {name:<14} {score:>7.2f}  {bucket[0]:<18} "
            f"{stats.sample_count:>6} {_win_rate_str(stats.t5_win_rate):>10} {_win_rate_str(stats.t10_win_rate):>11} {_win_rate_str(stats.t20_win_rate):>11} {_win_rate_str(stats.t30_win_rate):>11} "
            f"{_return_str(stats.t5_avg_return):>10} {_return_str(stats.t10_avg_return):>11} {_return_str(stats.t20_avg_return):>11} {_return_str(stats.t30_avg_return):>11}"
        )

    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI entry
# ---------------------------------------------------------------------------


def run_confidence_calibration(
    top_n: int = 10, lookback_days: int = DEFAULT_LOOKBACK_DAYS, report_dir: Path | None = None
) -> int:
    """CLI 入口: 加载历史 → 校准 → 渲染校准表 + Top N 推荐。"""
    records = _load_tracking_records(report_dir=report_dir)
    summary = compute_calibration(records, lookback_days=lookback_days)
    print(render_calibration_table(summary))

    # 仅当有 Top N 推荐时才显示
    _, recs = load_latest_recommendations(report_dir=report_dir)
    if recs:
        print(render_top_n_calibration(recs, summary, top_n=top_n))
    return 0


__all__ = [
    "SCORE_BUCKETS",
    "DEFAULT_LOOKBACK_DAYS",
    "ScoreBucketStats",
    "CalibrationSummary",
    "compute_calibration",
    "render_calibration_table",
    "render_top_n_calibration",
    "run_confidence_calibration",
]
