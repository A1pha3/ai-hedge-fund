"""综合信心排名 (`--conviction-ranking`) — P0-11.

整合多个已实现的可观测信号为单一决策视图, 解决"Top 10 中该买哪个"问题。

权重 (透明可配置):
- ``score_weight`` (40%): 原始 score_b 信号强度
- ``consecutive_weight`` (20%): 多日连续推荐稳定性 (减少单日噪声)
- ``quality_weight`` (20%): 数据完整性 (低质量推荐降权)
- ``calibration_weight`` (20%): 历史命中率校准 (高命中率的 score 桶加权)

业界对标: Numerai「Stake Confidence」/ QuantConnect「Alpha Confidence Score」。
我们的实现复用本地真实推荐历史, 而非合成 benchmark。

CLI:
    python src/main.py --conviction-ranking [--top-n=10] [--lookback=60]

输出:
- 综合信心分 0-100, 按 Conviction 降序
- 各分量贡献明细 (Score / Streak / Quality / Calib)
- 与原 score_b 排名的差异 (揭示数据质量/历史命中率调整)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.screening.confidence_calibration import (
    _find_bucket,
    CalibrationSummary,
    compute_calibration,
)
from src.screening.consecutive_recommendation import resolve_report_dir
from src.screening.data_quality_audit import (
    audit_recommendation,
    DEFAULT_QUALITY_THRESHOLD,
    load_latest_recommendations,
)
from src.utils.display import Fore, Style

# ---------------------------------------------------------------------------
# Weights — 透明可调
# ---------------------------------------------------------------------------

DEFAULT_WEIGHTS: dict[str, float] = {
    "score": 0.40,
    "consecutive": 0.20,
    "quality": 0.20,
    "calibration": 0.20,
}

# Consecutive days normalization: streak=1 → 0.0, streak=3+ → 1.0
CONSECUTIVE_FULL_STREAK: int = 3


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class ConvictionRow:
    """单只票的综合信心排名行。"""

    ticker: str
    name: str
    industry_sw: str
    original_score: float
    original_rank: int
    conviction_score: float
    conviction_rank: int
    # 各分量 (归一化 0-1)
    score_component: float
    consecutive_component: float
    quality_component: float
    calibration_component: float
    # 原始辅助信息
    consecutive_days: int
    composite_completeness: float
    bucket_label: str
    bucket_t5_win_rate: float | None
    rank_delta: int  # conviction_rank - original_rank (负=提升, 正=下降)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "name": self.name,
            "industry_sw": self.industry_sw,
            "original_score": self.original_score,
            "original_rank": self.original_rank,
            "conviction_score": self.conviction_score,
            "conviction_rank": self.conviction_rank,
            "score_component": self.score_component,
            "consecutive_component": self.consecutive_component,
            "quality_component": self.quality_component,
            "calibration_component": self.calibration_component,
            "consecutive_days": self.consecutive_days,
            "composite_completeness": self.composite_completeness,
            "bucket_label": self.bucket_label,
            "bucket_t5_win_rate": self.bucket_t5_win_rate,
            "rank_delta": self.rank_delta,
        }


@dataclass
class ConvictionSummary:
    """综合信心排名汇总。"""

    date_str: str
    weights: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_WEIGHTS))
    rows: list[ConvictionRow] = field(default_factory=list)
    has_calibration_data: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "date_str": self.date_str,
            "weights": self.weights,
            "rows": [r.to_dict() for r in self.rows],
            "has_calibration_data": self.has_calibration_data,
        }


# ---------------------------------------------------------------------------
# Component normalization
# ---------------------------------------------------------------------------


def _normalize_score(score: float) -> float:
    """score_b 范围 0-1 → 直接用作分量。"""
    return max(0.0, min(1.0, float(score)))


def _normalize_consecutive(days: int) -> float:
    """streak=1 → 0.0, streak=2 → 0.5, streak>=3 → 1.0 (线性插值)。"""
    if days <= 1:
        return 0.0
    if days >= CONSECUTIVE_FULL_STREAK:
        return 1.0
    # 1 < days < 3 即 days=2 → 0.5
    return (days - 1) / (CONSECUTIVE_FULL_STREAK - 1)


def _normalize_completeness(completeness: float) -> float:
    """completeness 已在 0-1 范围, 直接用。"""
    return max(0.0, min(1.0, float(completeness)))


def _normalize_calibration(win_rate: float | None) -> float:
    """T+5 win_rate 0-1 直接用; None (无样本) 视为中性 0.5 (不奖不罚)。"""
    if win_rate is None:
        return 0.5
    return max(0.0, min(1.0, float(win_rate)))


# ---------------------------------------------------------------------------
# Conviction computation
# ---------------------------------------------------------------------------


def compute_conviction_row(
    rec: dict[str, Any],
    original_rank: int,
    calibration: CalibrationSummary,
    weights: dict[str, float] | None = None,
    threshold: float = DEFAULT_QUALITY_THRESHOLD,
) -> ConvictionRow:
    """计算单条推荐的 conviction 分数。

    Args:
        rec: auto_screening recommendation dict
        original_rank: 在原 score_b 排名中的位置 (1-based)
        calibration: 校准数据 (用于查 score 桶的 T+5 命中率)
        weights: 各分量权重 (默认 :data:`DEFAULT_WEIGHTS`)
        threshold: data quality 阈值
    """
    weights = weights or DEFAULT_WEIGHTS
    audit = audit_recommendation(rec, threshold=threshold)
    score = float(rec.get("score_b") or 0.0)
    # NOTE: consecutive_days=0 是合法值 (首次推荐/非连续, 来自 consecutive_recommendation.py:338),
    # 不能用 `or 1` 静默覆盖为 1 — 会污染 row.consecutive_days 元数据 (R20.26-A)。
    raw_consecutive = rec.get("consecutive_days")
    consecutive_days = int(raw_consecutive) if raw_consecutive is not None else 1

    # 各分量 (0-1)
    score_comp = _normalize_score(score)
    consec_comp = _normalize_consecutive(consecutive_days)
    quality_comp = _normalize_completeness(audit["composite_completeness"])

    # 校准分量: 找到 score 所在桶的 T+5 win_rate
    bucket = _find_bucket(score)
    bucket_label = bucket[0] if bucket else "—"
    bucket_t5: float | None = None
    if bucket is not None:
        for b in calibration.buckets:
            if b.label == bucket[0]:
                bucket_t5 = b.t5_win_rate
                break
    calib_comp = _normalize_calibration(bucket_t5)

    # 加权综合 (0-1)
    conviction = (
        weights.get("score", 0.0) * score_comp
        + weights.get("consecutive", 0.0) * consec_comp
        + weights.get("quality", 0.0) * quality_comp
        + weights.get("calibration", 0.0) * calib_comp
    )
    conviction_score = round(max(0.0, min(1.0, conviction)) * 100, 1)

    return ConvictionRow(
        ticker=str(rec.get("ticker") or ""),
        name=str(rec.get("name") or "—"),
        industry_sw=str(rec.get("industry_sw") or ""),
        original_score=score,
        original_rank=original_rank,
        conviction_score=conviction_score,
        conviction_rank=0,  # 待填充
        score_component=round(score_comp, 3),
        consecutive_component=round(consec_comp, 3),
        quality_component=round(quality_comp, 3),
        calibration_component=round(calib_comp, 3),
        consecutive_days=consecutive_days,
        composite_completeness=audit["composite_completeness"],
        bucket_label=bucket_label,
        bucket_t5_win_rate=bucket_t5,
        rank_delta=0,  # 待填充
    )


def compute_conviction_ranking(
    recs: list[dict[str, Any]],
    calibration: CalibrationSummary,
    weights: dict[str, float] | None = None,
    top_n: int | None = None,
    threshold: float = DEFAULT_QUALITY_THRESHOLD,
) -> list[ConvictionRow]:
    """计算 Top N 推荐的综合信心排名。

    Args:
        recs: auto_screening recommendations (按 score_b 降序)
        calibration: 校准数据
        weights: 各分量权重
        top_n: 限制处理数量
        threshold: data quality 阈值

    Returns:
        按 conviction_score 降序的 ConvictionRow 列表 (rank 已填充)
    """
    if top_n is not None and top_n > 0:
        recs = recs[:top_n]
    rows: list[ConvictionRow] = []
    for idx, rec in enumerate(recs, start=1):
        rows.append(compute_conviction_row(rec, original_rank=idx, calibration=calibration, weights=weights, threshold=threshold))
    # 按 conviction 降序。BH-011 drain: 确定性 tie-break (original_score 降序,
    # ticker 升序)，避免相同 conviction 的 ticker 因 JSON dict 输入顺序
    # 导致 Top-N 成员跨运行非确定翻转。
    rows.sort(key=lambda r: (-r.conviction_score, -r.original_score, r.ticker))
    # 填充 conviction_rank 和 rank_delta
    for new_rank, row in enumerate(rows, start=1):
        row.conviction_rank = new_rank
        row.rank_delta = new_rank - row.original_rank
    return rows


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _component_str(value: float) -> str:
    """分量渲染: 0-1 → 5 格迷你 bar。"""
    filled = max(0, min(5, int(round(value * 5))))
    bar = "▌" * filled + "·" * (5 - filled)
    if value >= 0.66:
        color = Fore.GREEN
    elif value >= 0.33:
        color = Fore.YELLOW
    else:
        color = Fore.RED
    return f"{color}{bar}{Style.RESET_ALL}"


def _conviction_color(score: float) -> str:
    if score >= 75:
        return Fore.GREEN
    if score >= 60:
        return Fore.YELLOW
    return Fore.RED


def _rank_delta_str(delta: int) -> str:
    if delta < 0:
        return f"{Fore.GREEN}↑{-delta}{Style.RESET_ALL}"
    if delta > 0:
        return f"{Fore.RED}↓{delta}{Style.RESET_ALL}"
    return f"{Fore.YELLOW}—{Style.RESET_ALL}"


def render_conviction_ranking(summary: ConvictionSummary) -> str:
    """渲染综合信心排名表。"""
    if not summary.rows:
        return f"{Fore.YELLOW}未找到推荐数据 — 请先运行 `--auto` 生成报告。{Style.RESET_ALL}\n"

    lines: list[str] = []
    w = summary.weights
    lines.append(
        f"\n{Fore.CYAN}{Style.BRIGHT}═══ 综合信心排名 (date={summary.date_str or '未知'}) ═══{Style.RESET_ALL}"
    )
    lines.append(
        f"{Fore.CYAN}权重: Score {w['score']:.0%} · 连续 {w['consecutive']:.0%} · "
        f"数据质量 {w['quality']:.0%} · 历史命中率 {w['calibration']:.0%}{Style.RESET_ALL}"
    )
    if not summary.has_calibration_data:
        lines.append(
            f"{Fore.YELLOW}⚠ 无历史校准数据, calibration 分量全部为中性 0.5 (不奖不罚)。"
            f"多次运行 --auto 积累样本后此列才有区分度。{Style.RESET_ALL}"
        )
    lines.append("")

    header = (
        f"{Fore.CYAN}{'#':<3} {'Ticker':<8} {'名称':<12} {'Conv':>6} {'Δ':>4} "
        f"{'Score':<8} {'Streak':<8} {'Quality':<8} {'Calib':<8} 桶{Style.RESET_ALL}"
    )
    lines.append(header)
    lines.append("─" * 95)

    for row in summary.rows:
        conv_color = _conviction_color(row.conviction_score)
        lines.append(
            f"{row.conviction_rank:<3} {row.ticker:<8} {row.name[:10]:<12} "
            f"{conv_color}{row.conviction_score:>5.1f}{Style.RESET_ALL} "
            f"{_rank_delta_str(row.rank_delta):>4} "
            f"{_component_str(row.score_component)} "
            f"{_component_str(row.consecutive_component)} "
            f"{_component_str(row.quality_component)} "
            f"{_component_str(row.calibration_component)} "
            f"{row.bucket_label[:8]}"
        )

    lines.append("─" * 95)
    # 显著提升/下降的标的
    promoted = [r for r in summary.rows if r.rank_delta < 0]
    demoted = [r for r in summary.rows if r.rank_delta > 0]
    if promoted:
        names = ", ".join(f"{r.ticker}(+{-r.rank_delta})" for r in promoted[:3])
        lines.append(f"{Fore.GREEN}↑ 信心提升: {names}{Style.RESET_ALL}")
    if demoted:
        names = ", ".join(f"{r.ticker}(-{r.rank_delta})" for r in demoted[:3])
        lines.append(f"{Fore.RED}↓ 信心下降: {names}{Style.RESET_ALL}")
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI entry
# ---------------------------------------------------------------------------


def run_conviction_ranking(
    top_n: int = 10,
    lookback_days: int = 60,
    weights: dict[str, float] | None = None,
    report_dir: Path | None = None,
) -> int:
    """CLI 入口: 加载最新报告 + 校准 → 计算 conviction → 渲染。"""
    from src.screening.confidence_calibration import _load_tracking_records

    report_dir = report_dir or resolve_report_dir()
    date_str, recs = load_latest_recommendations(report_dir=report_dir)
    if not recs:
        print(f"{Fore.YELLOW}未找到推荐数据 — 请先运行 `--auto` 生成报告。{Style.RESET_ALL}")
        return 1

    # 加载校准数据
    records = _load_tracking_records(report_dir=report_dir)
    calibration = compute_calibration(records, lookback_days=lookback_days)
    has_calib = calibration.total_samples > 0

    rows = compute_conviction_ranking(
        recs, calibration=calibration, weights=weights, top_n=top_n
    )
    summary = ConvictionSummary(
        date_str=date_str,
        weights=weights or DEFAULT_WEIGHTS,
        rows=rows,
        has_calibration_data=has_calib,
    )
    print(render_conviction_ranking(summary))
    return 0


__all__ = [
    "DEFAULT_WEIGHTS",
    "CONSECUTIVE_FULL_STREAK",
    "ConvictionRow",
    "ConvictionSummary",
    "compute_conviction_row",
    "compute_conviction_ranking",
    "render_conviction_ranking",
    "run_conviction_ranking",
]
