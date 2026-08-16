"""排序记分牌 — --auto Top10 切片的诚实自评 (展示层统计, 只读 tracking_history).

背景 (2026-08-16 v3 展示层规格): tracking_history 近期每日只记录 Top10 本身,
没有池级对照, 所以记分牌**不编造全池基准**, 而是披露三件可以从切片内部
诚实计算的事:

1. 切片胜率 / 均值 (单一 T+5 口径, 不做 max(T+5,T+10) 的选择性挑选);
2. 切片内排序质量: 日内 Spearman IC (分数 vs T+5 收益) + 前3 vs 后7 梯度;
3. verdict 三态 — ``positive`` 要求 IC 显著为正 (t>=2) 且切片均值为正;
   t<=-2 判 ``negative`` (排越前越差); 其余 ``no_positive_evidence``。

样本不足时 ``insufficient`` — 不给点估计, 未知不编造 (项目纪律)。

统计口径注意 (对抗审查 F4, 2026-08-16): 日 IC 的 t 统计按独立日假设计算,
但 Top10 切片的 T+5 窗口互相重叠, 自相关使 t 偏乐观 — verdict 只是展示
层标签 (有/无正向证据), 不是显著性证明, 更不构成任何授权; 引用 |t| 接近
2 的边缘判定时应按更保守的阈值复核。IC 日数 <2 (成熟稀薄窗口) 时 ic_t
恒 None (样本不足) — 单日 IC 无标准误, 不宣称显著方向 (2026-08-16 收口)。

返回单位: tracking_history 的收益字段是**百分比** (2.5989 = +2.6%), 本模块
原样保留百分比口径, 由 formatter 决定展示形式。
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from src.screening.confidence_calibration import SCORE_BUCKETS, _find_bucket

# 展示层常量 — 与 P9-1 / BUY-gate 的既有纪律对齐:
#   backing_sample >= 20 才可信; <5 不给点估计; IC t>=2 才谈"显著"。
WINDOW_DATES: int = 60
MIN_MATURE_DATES: int = 10
TOP_SLICE: int = 10
GRADIENT_HEAD: int = 3
IC_T_THRESHOLD: float = 2.0
POINT_ESTIMATE_MIN_MATURE: int = 5
TRUSTED_MIN_MATURE: int = 20
HORIZON_KEY: str = "next_5day_return"

__all__ = [
    "BucketStats",
    "ScorecardReport",
    "compute_bucket_stats",
    "compute_scorecard",
    "empty_bucket_stats",
    "format_bucket_header",
    "format_scorecard_lines",
]


@dataclass(frozen=True)
class BucketStats:
    """同评分桶近窗口 T+5 实证 — 桶头一行钱的口径。"""

    label: str
    window_start: str | None
    window_end: str | None
    n_records: int
    n_mature: int
    win_rate: float | None
    mean_return: float | None
    avg_win: float | None
    avg_loss: float | None
    payoff: float | None


@dataclass(frozen=True)
class ScorecardReport:
    """Top10 切片记分牌 — 表格 header 的常驻诚实行。"""

    available: bool
    reason: str | None
    window_start: str | None
    window_end: str | None
    n_dates: int
    n_mature: int
    slice_win_rate: float | None
    slice_mean_return: float | None
    head_win_rate: float | None
    rest_win_rate: float | None
    mean_daily_ic: float | None
    ic_t_stat: float | None
    ic_dates: int

    @property
    def verdict(self) -> str:
        if not self.available:
            return "insufficient"
        if self.ic_t_stat is not None and self.ic_t_stat <= -IC_T_THRESHOLD:
            return "negative"
        if (
            self.ic_t_stat is not None
            and self.ic_t_stat >= IC_T_THRESHOLD
            and (self.mean_daily_ic or 0.0) > 0
            and (self.slice_mean_return or 0.0) > 0
        ):
            return "positive"
        return "no_positive_evidence"


def empty_bucket_stats(label: str) -> BucketStats:
    """无任何追踪数据时的桶统计 (确定性空态)。"""
    return BucketStats(
        label=label,
        window_start=None,
        window_end=None,
        n_records=0,
        n_mature=0,
        win_rate=None,
        mean_return=None,
        avg_win=None,
        avg_loss=None,
        payoff=None,
    )


def _as_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _spearman(a: Sequence[float], b: Sequence[float]) -> float:
    """带并列秩的 Spearman 秩相关; 任一侧零方差 → 0.0 (无信息, 不崩溃)。"""

    def _ranks(values: Sequence[float]) -> list[float]:
        n = len(values)
        order = sorted(range(n), key=lambda i: values[i])
        ranks = [0.0] * n
        i = 0
        while i < n:
            j = i
            while j + 1 < n and values[order[j + 1]] == values[order[i]]:
                j += 1
            avg = (i + j) / 2 + 1
            for k in range(i, j + 1):
                ranks[order[k]] = avg
            i = j + 1
        return ranks

    ra, rb = _ranks(a), _ranks(b)
    mean_a = statistics.fmean(ra)
    mean_b = statistics.fmean(rb)
    num = sum((x - mean_a) * (y - mean_b) for x, y in zip(ra, rb))
    den_a = math.sqrt(sum((x - mean_a) ** 2 for x in ra))
    den_b = math.sqrt(sum((y - mean_b) ** 2 for y in rb))
    if den_a == 0 or den_b == 0 or num == 0:
        return 0.0
    return num / (den_a * den_b)


def _matured_days(
    records: Sequence[Mapping[str, Any]],
    horizon_key: str,
    top_slice: int,
) -> list[tuple[str, list[Mapping[str, Any]]]]:
    """按推荐日分组, 每日按分数取前 top_slice, 只保留 horizon 已成熟的记录。

    2024 时代 tracking 每日记录全池 (最多 300 只), 按分数截取前 10 使口径
    与"Top10 切片"一致; 近期每日恰好 10 只时是恒等操作。
    """
    by_date: dict[str, list[Mapping[str, Any]]] = {}
    for rec in records:
        date = str(rec.get("recommended_date") or "")
        if not date:
            continue
        score = _as_float(rec.get("recommendation_score"))
        if score is None:
            continue
        by_date.setdefault(date, []).append(rec)

    days: list[tuple[str, list[Mapping[str, Any]]]] = []
    for date in sorted(by_date):
        ranked = sorted(
            by_date[date],
            key=lambda r: -float(r["recommendation_score"]),
        )[:top_slice]
        matured = [
            r for r in ranked if _as_float(r.get(horizon_key)) is not None
        ]
        if matured:
            days.append((date, matured))
    return days


def compute_scorecard(
    records: Sequence[Mapping[str, Any]],
    *,
    window_dates: int = WINDOW_DATES,
    horizon_key: str = HORIZON_KEY,
    min_mature_dates: int = MIN_MATURE_DATES,
    top_slice: int = TOP_SLICE,
    gradient_head: int = GRADIENT_HEAD,
) -> ScorecardReport:
    """计算 Top10 切片记分牌。"""
    days = _matured_days(records, horizon_key, top_slice)
    window = days[-window_dates:] if window_dates > 0 else days

    if not records:
        return ScorecardReport(
            available=False, reason="no_records", window_start=None,
            window_end=None, n_dates=0, n_mature=0, slice_win_rate=None,
            slice_mean_return=None, head_win_rate=None, rest_win_rate=None,
            mean_daily_ic=None, ic_t_stat=None, ic_dates=0,
        )
    if len(window) < min_mature_dates:
        return ScorecardReport(
            available=False, reason="insufficient_mature_dates",
            window_start=window[0][0] if window else None,
            window_end=window[-1][0] if window else None,
            n_dates=len(window), n_mature=0, slice_win_rate=None,
            slice_mean_return=None, head_win_rate=None, rest_win_rate=None,
            mean_daily_ic=None, ic_t_stat=None, ic_dates=0,
        )

    returns: list[float] = []
    head_wins = head_total = rest_wins = rest_total = 0
    daily_ics: list[float] = []
    for _, day in window:
        for i, rec in enumerate(day):
            ret = float(rec[horizon_key])
            returns.append(ret)
            win = 1 if ret > 0 else 0
            if i < gradient_head:
                head_wins += win
                head_total += 1
            else:
                rest_wins += win
                rest_total += 1
        if len(day) >= 2:
            daily_ics.append(
                _spearman(
                    [float(r["recommendation_score"]) for r in day],
                    [float(r[horizon_key]) for r in day],
                )
            )

    mean_ic = statistics.fmean(daily_ics) if daily_ics else None
    if mean_ic is None or len(daily_ics) < 2:
        # IC 日数 <2 → 无标准误可言 (单样本点不宣称显著方向, 未知不编造)。
        ic_t: float | None = None
    elif statistics.stdev(daily_ics) > 0:
        ic_t = mean_ic / (statistics.stdev(daily_ics) / math.sqrt(len(daily_ics)))
    elif mean_ic == 0.0:
        ic_t = 0.0
    else:
        # 全窗口 IC 恒同号 (方差 0, >=2 个独立日确认方向) → t 取有符号无穷。
        ic_t = math.copysign(math.inf, mean_ic)

    return ScorecardReport(
        available=True,
        reason=None,
        window_start=window[0][0],
        window_end=window[-1][0],
        n_dates=len(window),
        n_mature=len(returns),
        slice_win_rate=(
            sum(1 for r in returns if r > 0) / len(returns) if returns else None
        ),
        slice_mean_return=statistics.fmean(returns) if returns else None,
        head_win_rate=(head_wins / head_total) if head_total else None,
        rest_win_rate=(rest_wins / rest_total) if rest_total else None,
        mean_daily_ic=mean_ic,
        ic_t_stat=ic_t,
        ic_dates=len(daily_ics),
    )


def compute_bucket_stats(
    records: Sequence[Mapping[str, Any]],
    *,
    window_dates: int = WINDOW_DATES,
    horizon_key: str = HORIZON_KEY,
) -> dict[str, BucketStats]:
    """按 SCORE_BUCKETS 分桶的 T+5 实证 — 桶头一行 (胜率/均值/盈亏笔均/赔率)。

    窗口 = 最近 N 个**有记录**的推荐日 (与 scorecard 的"有成熟样本的推荐日"
    略有差别: 未成熟记录计入 n_records 分母但不进统计 — 桶头「n笔（成熟m）」
    的口径要求两者都可见)。只返回有记录的桶。
    """
    by_date: dict[str, list[Mapping[str, Any]]] = {}
    for rec in records:
        date = str(rec.get("recommended_date") or "")
        score = _as_float(rec.get("recommendation_score"))
        if not date or score is None:
            continue
        by_date.setdefault(date, []).append(rec)

    window = sorted(by_date)[-window_dates:] if window_dates > 0 else sorted(by_date)
    window_start = window[0] if window else None
    window_end = window[-1] if window else None

    buckets: dict[str, list[Mapping[str, Any]]] = {}
    for date in window:
        for rec in by_date[date]:
            found = _find_bucket(float(rec["recommendation_score"]))
            if found is None:
                continue
            buckets.setdefault(found[0], []).append(rec)

    stats: dict[str, BucketStats] = {}
    for label, recs in buckets.items():
        rets = [
            r
            for r in (_as_float(rec.get(horizon_key)) for rec in recs)
            if r is not None
        ]
        wins = [r for r in rets if r > 0]
        losses = [r for r in rets if r <= 0]
        avg_win = statistics.fmean(wins) if wins else None
        avg_loss = statistics.fmean(losses) if losses else None
        payoff = (
            avg_win / abs(avg_loss)
            if avg_win is not None and avg_loss is not None and avg_loss < 0
            else None
        )
        stats[label] = BucketStats(
            label=label,
            window_start=window_start,
            window_end=window_end,
            n_records=len(recs),
            n_mature=len(rets),
            win_rate=(len(wins) / len(rets)) if rets else None,
            mean_return=statistics.fmean(rets) if rets else None,
            avg_win=avg_win,
            avg_loss=avg_loss,
            payoff=payoff,
        )
    return stats


def _fmt_pct(value: float | None, *, signed: bool = False) -> str:
    if value is None:
        return "—"
    return f"{value:+.1f}%" if signed else f"{value:.0%}"


def _fmt_ic_t(t: float | None) -> str:
    if t is None:
        return "样本不足"
    if math.isinf(t):
        return "∞" if t > 0 else "-∞"
    return f"{t:+.1f}"


def format_scorecard_lines(report: ScorecardReport) -> list[str]:
    """记分牌文案 (纯文本, 无 ANSI — briefing 卡/push/CLI 共用)。"""
    if not report.available:
        if report.reason == "no_records":
            return ["排序记分牌: 无追踪数据，排序有效性不可用 — 本表按观察清单使用"]
        n = report.n_dates
        return [
            f"排序记分牌: 成熟样本不足（{n} 个推荐日 < {MIN_MATURE_DATES}），"
            "无法评估排序有效性 — 本表按观察清单使用"
        ]

    ic_seg = (
        f"排序IC {report.mean_daily_ic:+.2f}(t={_fmt_ic_t(report.ic_t_stat)})"
        if report.mean_daily_ic is not None
        else "排序IC 样本不足"
    )
    line1 = (
        f"排序记分牌 近{report.n_dates}个推荐日（{report.window_start}→{report.window_end}）: "
        f"Top10 切片 T+5 胜率 {_fmt_pct(report.slice_win_rate)} · "
        f"均值 {_fmt_pct(report.slice_mean_return, signed=True)}（未扣费） · "
        f"{ic_seg} · "
        f"前3 {_fmt_pct(report.head_win_rate)} vs 后7 {_fmt_pct(report.rest_win_rate)}"
    )
    if report.verdict == "positive":
        line2 = "→ 排序近期有正向证据；本表仍为候选清单，实际 BUY 见 --daily-action"
    elif report.verdict == "negative":
        line2 = "→ ⚠ 排序近期实测反向（排越前越差），本表仅作反向参考；实际 BUY 见 --daily-action"
    else:
        line2 = "→ 排序近期无正向证据，本表按观察清单使用；实际 BUY 见 --daily-action"
    return [line1, line2]


def format_bucket_header(stats: BucketStats) -> str:
    """桶头一行 (纯文本, 无 ANSI)。空态矩阵: 无窗口 / 无成熟 / 少样本 / 可信。"""
    window_seg = (
        f"（{stats.window_start}→{stats.window_end}）"
        if stats.window_start and stats.window_end
        else ""
    )
    if stats.n_records == 0:
        return f"── 桶 {stats.label} · 无追踪数据，不提供估计"
    if stats.n_mature < POINT_ESTIMATE_MIN_MATURE:
        return (
            f"── 桶 {stats.label} · 近窗口{window_seg} "
            f"成熟样本不足（{stats.n_mature}<{POINT_ESTIMATE_MIN_MATURE}），不提供点估计"
        )
    payoff_seg = f"赔率 {stats.payoff:.1f}" if stats.payoff is not None else "赔率 —"
    low_sample = " ⚠少样本" if stats.n_mature < TRUSTED_MIN_MATURE else ""
    return (
        f"── 桶 {stats.label} · 近窗口{window_seg} {stats.n_records}笔（成熟{stats.n_mature}）· "
        f"T+5 胜率 {_fmt_pct(stats.win_rate)} · 均值 {_fmt_pct(stats.mean_return, signed=True)}（未扣费） · "
        f"盈笔均 {_fmt_pct(stats.avg_win, signed=True)} 亏笔均 {_fmt_pct(stats.avg_loss, signed=True)} · "
        f"{payoff_seg}{low_sample}"
    )
