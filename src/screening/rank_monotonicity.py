"""NS-4 排序单调性健康度: score rank → T+30 胜率是否单调.

R-5.F Phase 0 (state_type_calibration) 与真实数据 (493 条 tracking_history) 共同
发现: **模型整体排序倒挂** — low-score bucket T+30 胜率 50.5%, high-score bucket
反而 39.5% (高分票胜率最低). 这意味着 must-win 前门按 score 取的"最值得买"代表票,
真实赢面反而最差.

本模块把"高分是否 → 高胜率"量化成可复现的健康信号, 在 ``--top-picks`` footer 展示:

  - **inverted** (⚠): 低分→高分胜率单调递减 (模型把输家排前面, 最危险)
  - **monotonic** (✓): 低分→高分胜率递增 (理想)
  - **non_monotonic**: 既非单调也非倒挂 (部分倒挂)
  - **insufficient**: 任一 bucket 样本 < min_n (诚实, 不下结论, 静默)

**纯诊断, 不改 gate / 不改 factor / 不改仓位** (越界 = 过拟合, Phase 0 STOP 裁决).
复用 state_type_calibration 的 ``_score_bucket`` / ``_build_date_state_type_map``
与 consecutive_recommendation 的数据加载, 镜像 regime_winrate / portfolio_concentration
的 footer-block 模式 (best-effort, 数据不足静默, 永不破坏前门).

数据流: load_tracking_history → records (recommendation_score + next_30day_return);
load_auto_screening_history → {date → state_type} (per-state_type 细分).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.screening.state_type_calibration import (
    _build_date_state_type_map,
    _score_bucket,
)
from src.utils.display import Fore, Style

# 与 state_type_calibration _score_bucket 边界对齐: low < 0.30 / mid_low < 0.40 /
# mid_high < 0.50 (BUY 门控) / high >= 0.50.
_BUCKET_ORDER: tuple[str, ...] = ("low", "mid_low", "mid_high", "high")
# 与 state_type_calibration _Q1_MIN_N 对齐: 每 bucket 需 >=20 成熟 T+30 才下结论.
_MIN_N_PER_BUCKET_DEFAULT = 20


def _finite_float(value: Any) -> float | None:
    """NaN/Inf/garbage → None (镜像 state_type_calibration._optional_float)."""
    if value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if result != result:  # NaN
        return None
    return result


def _win_rate(returns: list[float]) -> float | None:
    return (sum(1 for x in returns if x > 0) / len(returns)) if returns else None


def _record_score(rec: dict[str, Any]) -> Any:
    """读推荐分 (recommendation_score 真实字段, score_b 兜底)."""
    score = rec.get("recommendation_score")
    if score is None:
        score = rec.get("score_b")
    return score


@dataclass
class BucketWinRate:
    """单个 score-bucket 的 T+30 胜率."""

    bucket: str
    t30_win_rate: float | None = None
    sample_count: int = 0


@dataclass
class RankMonotonicityReport:
    """score rank → T+30 胜率单调性诊断报告."""

    overall_buckets: list[BucketWinRate] = field(default_factory=list)
    overall_verdict: str = "insufficient"  # monotonic | inverted | non_monotonic | insufficient
    overall_inverted: bool = False
    per_state_type: dict[str, list[BucketWinRate]] = field(default_factory=dict)
    per_state_type_verdict: dict[str, str] = field(default_factory=dict)


def _bucket_returns_by_state(
    records: list[dict[str, Any]],
    date_st: dict[str, str] | None = None,
    target_state: str | None = None,
) -> dict[str, list[float]]:
    """→ {bucket: [t30 returns]} 仅成熟 T+30; target_state 过滤 (None=全部)."""
    out: dict[str, list[float]] = {}
    for rec in records:
        if target_state is not None and date_st is not None:
            date_raw = str(rec.get("recommended_date", "") or "").replace("-", "")
            if date_st.get(date_raw) != target_state:
                continue
        bucket = _score_bucket(_record_score(rec))
        t30 = _finite_float(rec.get("next_30day_return"))
        if t30 is None:
            continue
        out.setdefault(bucket, []).append(t30)
    return out


def _bucket_rows(returns_by_bucket: dict[str, list[float]]) -> list[BucketWinRate]:
    """{bucket: returns} → ordered BucketWinRate rows (仅 _BUCKET_ORDER 内, 有数据)."""
    rows: list[BucketWinRate] = []
    for bucket in _BUCKET_ORDER:
        rets = returns_by_bucket.get(bucket, [])
        if not rets:
            continue
        rows.append(
            BucketWinRate(
                bucket=bucket,
                t30_win_rate=_win_rate(rets),
                sample_count=len(rets),
            )
        )
    return rows


def _verdict(
    returns_by_bucket: dict[str, list[float]],
    min_n: int,
) -> tuple[str, list[float | None]]:
    """从 {bucket: returns} 算 verdict + per-bucket winrates (ordered).

    insufficient: 任一 bucket 缺失或 n < min_n (诚实, 不下结论).
    monotonic: 低→高胜率非递减.
    inverted: 低→高胜率非递增 且 low > high (倒挂, 最危险).
    non_monotonic: 其余.
    """
    wrs: list[float | None] = []
    for bucket in _BUCKET_ORDER:
        rets = returns_by_bucket.get(bucket, [])
        if len(rets) < min_n:
            return "insufficient", [None] * len(_BUCKET_ORDER)
        wrs.append(_win_rate(rets))
    if any(w is None for w in wrs):
        return "insufficient", wrs
    non_decreasing = all(wrs[i] <= wrs[i + 1] + 1e-9 for i in range(len(wrs) - 1))
    non_increasing = all(wrs[i] >= wrs[i + 1] - 1e-9 for i in range(len(wrs) - 1))
    if non_decreasing:
        return "monotonic", wrs
    if non_increasing and wrs[0] > wrs[-1]:
        return "inverted", wrs
    return "non_monotonic", wrs


def compute_rank_monotonicity_from_loaded(
    history: list[dict[str, Any]],
    records: list[dict[str, Any]],
    *,
    min_n: int = _MIN_N_PER_BUCKET_DEFAULT,
) -> RankMonotonicityReport:
    """纯函数: 用已加载 history + tracking records 算单调性报告 (可注入测试)."""
    date_st = _build_date_state_type_map(history)

    overall_returns = _bucket_returns_by_state(records)
    overall_verdict, _ = _verdict(overall_returns, min_n)
    report = RankMonotonicityReport(
        overall_buckets=_bucket_rows(overall_returns),
        overall_verdict=overall_verdict,
        overall_inverted=(overall_verdict == "inverted"),
    )

    # per-state_type 细分 (仅出现过的 state_type)
    seen_states: set[str] = set()
    for rec in records:
        date_raw = str(rec.get("recommended_date", "") or "").replace("-", "")
        st = date_st.get(date_raw)
        if st:
            seen_states.add(st)
    for st in sorted(seen_states):
        st_returns = _bucket_returns_by_state(records, date_st, st)
        st_verdict, _ = _verdict(st_returns, min_n)
        report.per_state_type[st] = _bucket_rows(st_returns)
        report.per_state_type_verdict[st] = st_verdict

    return report


def compute_rank_monotonicity(
    *,
    reports_dir: Path | None = None,
    lookback_days: int = 30,
    min_n: int = _MIN_N_PER_BUCKET_DEFAULT,
) -> RankMonotonicityReport:
    """从报告目录加载数据算单调性 (镜像 state_type_calibration 的 IO 包装)."""
    from src.screening.consecutive_recommendation import (
        load_auto_screening_history,
        load_tracking_history,
        resolve_report_dir,
    )

    search_dir = reports_dir or resolve_report_dir()
    history = load_auto_screening_history(lookback_days=lookback_days, report_dir=search_dir)
    records = load_tracking_history(search_dir)
    return compute_rank_monotonicity_from_loaded(history, records, min_n=min_n)


# ---------------------------------------------------------------------------
# footer 渲染
# ---------------------------------------------------------------------------

_BUCKET_LABEL = {"low": "低", "mid_low": "中低", "mid_high": "中高", "high": "高"}


def render_monotonicity_line(report: RankMonotonicityReport) -> str:
    """渲染单行排序单调性提示 (insufficient → 空串, 永不破坏前门).

    展示形如:
      ``  ⚠ 排序单调性: 低50%→中低46%→中高43%→高40% 倒挂 (高分票胜率反而更低)``
      ``  ✓ 排序单调性: 低40%→中低45%→中高50%→高55% (高分→高胜率)``
    """
    if report.overall_verdict == "insufficient" or not report.overall_buckets:
        return ""

    parts = [
        f"{_BUCKET_LABEL.get(b.bucket, b.bucket)}{b.t30_win_rate:.0%}"
        for b in report.overall_buckets
        if b.t30_win_rate is not None
    ]
    if len(parts) < 2:
        return ""
    shape = " → ".join(parts)

    if report.overall_verdict == "inverted":
        return (
            f"  {Fore.RED}⚠ 排序单调性: {shape} 倒挂{Style.RESET_ALL}"
            f" {Fore.RED}(高分票胜率反而更低 — 模型打分质量待改进){Style.RESET_ALL}"
        )
    if report.overall_verdict == "monotonic":
        return (
            f"  {Fore.GREEN}✓ 排序单调性: {shape}{Style.RESET_ALL}"
            f" {Fore.GREEN}(高分→高胜率){Style.RESET_ALL}"
        )
    # non_monotonic
    return (
        f"  {Fore.YELLOW}⚠ 排序单调性: {shape} 非单调{Style.RESET_ALL}"
        f" {Fore.YELLOW}(部分 bucket 倒挂 — 模型打分质量不稳定){Style.RESET_ALL}"
    )


__all__ = [
    "BucketWinRate",
    "RankMonotonicityReport",
    "compute_rank_monotonicity",
    "compute_rank_monotonicity_from_loaded",
    "render_monotonicity_line",
]
