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

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.screening.consecutive_recommendation import resolve_report_dir
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
    t1_avg_return: float | None = None
    t5_avg_return: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "score_low": self.score_low,
            "score_high": self.score_high,
            "sample_count": self.sample_count,
            "t1_win_rate": self.t1_win_rate,
            "t3_win_rate": self.t3_win_rate,
            "t5_win_rate": self.t5_win_rate,
            "t1_avg_return": self.t1_avg_return,
            "t5_avg_return": self.t5_avg_return,
        }


@dataclass
class CalibrationSummary:
    """校准结果汇总。"""

    lookback_days: int
    total_samples: int = 0
    buckets: list[ScoreBucketStats] = field(default_factory=list)
    overall_t1_win_rate: float | None = None
    overall_t5_win_rate: float | None = None
    overall_t5_avg_return: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "lookback_days": self.lookback_days,
            "total_samples": self.total_samples,
            "buckets": [b.to_dict() for b in self.buckets],
            "overall_t1_win_rate": self.overall_t1_win_rate,
            "overall_t5_win_rate": self.overall_t5_win_rate,
            "overall_t5_avg_return": self.overall_t5_avg_return,
        }


# ---------------------------------------------------------------------------
# History loading
# ---------------------------------------------------------------------------


def _load_tracking_records(report_dir: Path | None = None) -> list[dict[str, Any]]:
    """读取 ``tracking_history.json`` 的 records 列表; 缺失返回 []。"""
    search_dir = report_dir or resolve_report_dir()
    path = search_dir / "tracking_history.json"
    if not path.exists():
        return []
    try:
        with path.open(encoding="utf-8") as f:
            payload = json.load(f)
    except (OSError, json.JSONDecodeError):
        return []
    records = payload.get("records") if isinstance(payload, dict) else payload
    return list(records) if isinstance(records, list) else []


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


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
    label_map = {label: (low, high) for label, low, high in SCORE_BUCKETS}

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
    all_t5_returns: list[float] = []
    for label, low, high in SCORE_BUCKETS:
        recs = bucket_records[label]
        t1_returns = [_optional_float(r.get("next_day_return")) for r in recs]
        t3_returns = [_optional_float(r.get("next_3day_return")) for r in recs]
        t5_returns = [_optional_float(r.get("next_5day_return")) for r in recs]
        t1_valid = [x for x in t1_returns if x is not None]
        t3_valid = [x for x in t3_returns if x is not None]
        t5_valid = [x for x in t5_returns if x is not None]
        stats = ScoreBucketStats(
            label=label,
            score_low=low,
            score_high=high,
            sample_count=len(recs),
            t1_win_rate=(sum(1 for x in t1_valid if x > 0) / len(t1_valid)) if t1_valid else None,
            t3_win_rate=(sum(1 for x in t3_valid if x > 0) / len(t3_valid)) if t3_valid else None,
            t5_win_rate=(sum(1 for x in t5_valid if x > 0) / len(t5_valid)) if t5_valid else None,
            t1_avg_return=(sum(t1_valid) / len(t1_valid)) if t1_valid else None,
            t5_avg_return=(sum(t5_valid) / len(t5_valid)) if t5_valid else None,
        )
        bucket_stats.append(stats)
        all_t1.extend(t1_valid)
        all_t5.extend(t5_valid)
        all_t5_returns.extend(t5_valid)

    return CalibrationSummary(
        lookback_days=lookback_days,
        total_samples=sum(b.sample_count for b in bucket_stats),
        buckets=bucket_stats,
        overall_t1_win_rate=(sum(1 for x in all_t1 if x > 0) / len(all_t1)) if all_t1 else None,
        overall_t5_win_rate=(sum(1 for x in all_t5 if x > 0) / len(all_t5)) if all_t5 else None,
        overall_t5_avg_return=(sum(all_t5_returns) / len(all_t5_returns)) if all_t5_returns else None,
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
        f"样本={summary.total_samples}) ═══{Style.RESET_ALL}"
    )

    if summary.total_samples == 0:
        lines.append(
            f"{Fore.YELLOW}无历史推荐追踪数据 — 请先多次运行 `--auto` 并 `update_tracking_history` "
            f"积累 T+1/T+3/T+5 实际收益样本。{Style.RESET_ALL}"
        )
        lines.append("")
        return "\n".join(lines)

    header = (
        f"{Fore.CYAN}{'Score 桶':<18} {'样本':>5} "
        f"{'T+1 胜率':>10} {'T+3 胜率':>10} {'T+5 胜率':>10} "
        f"{'T+1 均收':>10} {'T+5 均收':>10}{Style.RESET_ALL}"
    )
    lines.append(header)
    lines.append("─" * 95)

    for b in summary.buckets:
        lines.append(
            f"{b.label:<18} {b.sample_count:>5} "
            f"{_win_rate_str(b.t1_win_rate):>10} {_win_rate_str(b.t3_win_rate):>10} "
            f"{_win_rate_str(b.t5_win_rate):>10} {_return_str(b.t1_avg_return):>10} "
            f"{_return_str(b.t5_avg_return):>10}"
        )

    lines.append("─" * 95)
    overall_line = (
        f"{'整体':<18} {summary.total_samples:>5} "
        f"{_win_rate_str(summary.overall_t1_win_rate):>10} {'':>10} "
        f"{_win_rate_str(summary.overall_t5_win_rate):>10} {'':>10} "
        f"{_return_str(summary.overall_t5_avg_return):>10}"
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
        f"{'所在桶':<18} {'桶样本':>6} {'T+5 胜率':>10} {'T+5 均收':>10}{Style.RESET_ALL}"
    )
    lines.append(header)
    lines.append("─" * 85)

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
            f"{stats.sample_count:>6} {_win_rate_str(stats.t5_win_rate):>10} "
            f"{_return_str(stats.t5_avg_return):>10}"
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
