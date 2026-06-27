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

import re
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


# ---------------------------------------------------------------------------
# M5: 时段分段单调性 (period breakdown)
# 区分 H1 因子方向 bug (全期倒挂) vs H2 regime 分化 (前/后半 verdict 不同).
# design packet (docs/cn/product/research/model-scoring-investigation-packet.md)
# 推荐的最快证伪路径, 复用现有总分数据, 无需 payload 扩展.
# ---------------------------------------------------------------------------

_PERIOD_LABELS_2 = ("前半", "后半")


@dataclass
class PeriodBreakdown:
    """单个时段的单调性分解."""

    label: str
    verdict: str  # monotonic | inverted | non_monotonic | insufficient
    winrates: list[float]  # ordered low→high (空若 insufficient)
    sample_count: int


def _period_label(index: int, n_periods: int) -> str:
    if n_periods == 2:
        return _PERIOD_LABELS_2[index]
    return f"段{index + 1}"


def compute_period_breakdown_from_loaded(
    records: list[dict[str, Any]],
    *,
    n_periods: int = 2,
    min_n: int = 15,
) -> list[PeriodBreakdown]:
    """按 recommended_date 排序分 n_periods 段, 每段算 score→T+30 winrate 单调性.

    回答 design packet H1 vs H2: 两段都倒挂 → H1 因子方向 bug; verdict 分化 → H2 regime.
    分段后样本变薄, min_n 默认 15 (比 overall 的 20 宽松, 诚实标注可靠性).
    """
    # 按 recommended_date 分组, 仅成熟 T+30
    by_date: dict[str, list[dict[str, Any]]] = {}
    for rec in records:
        t30 = _finite_float(rec.get("next_30day_return"))
        if t30 is None:
            continue
        date_raw = str(rec.get("recommended_date", "") or "").replace("-", "")
        if not date_raw:
            continue
        by_date.setdefault(date_raw, []).append(rec)

    dates = sorted(by_date)
    if not dates or n_periods < 1:
        return []

    # 日期均分 n_periods 段
    n = len(dates)
    out: list[PeriodBreakdown] = []
    for i in range(n_periods):
        start = i * n // n_periods
        end = (i + 1) * n // n_periods
        seg_dates = set(dates[start:end])
        seg_records = [r for d in seg_dates for r in by_date[d]]
        returns_by_bucket = _bucket_returns_by_state(seg_records)
        verdict, wrs = _verdict(returns_by_bucket, min_n)
        sample = sum(len(v) for v in returns_by_bucket.values())
        out.append(
            PeriodBreakdown(
                label=_period_label(i, n_periods),
                verdict=verdict,
                winrates=[w for w in wrs if w is not None],
                sample_count=sample,
            )
        )
    return out


def render_period_breakdown_line(periods: list[PeriodBreakdown]) -> str:
    """渲染时段分段单调性对比 (全 insufficient → 空串).

    展示形如:
      ``  📊 时段单调性: 前半 倒挂⚠ (46→38) | 后半 倒挂⚠ (59→41) — 两段均倒挂, 倾向因子方向 (H1)``
    """
    if not periods or all(p.verdict == "insufficient" for p in periods):
        return ""

    def _seg(p: PeriodBreakdown) -> str:
        if p.verdict == "insufficient" or len(p.winrates) < 2:
            return f"{p.label} 样本不足"
        shape = "→".join(f"{w:.0%}" for w in p.winrates)
        tag = {"inverted": "倒挂⚠", "monotonic": "单调✓", "non_monotonic": "非单调⚠"}.get(
            p.verdict, p.verdict
        )
        return f"{p.label} {tag} ({shape})"

    parts = [_seg(p) for p in periods]
    # 裁决: 多段都倒挂 → H1 因子方向; 分化 → H2 regime
    non_insufficient = [p for p in periods if p.verdict != "insufficient"]
    all_inverted = bool(non_insufficient) and all(p.verdict == "inverted" for p in non_insufficient)
    verdicts_diverge = len({p.verdict for p in non_insufficient}) > 1
    if all_inverted:
        suffix = f"{Fore.RED}— 多段均倒挂, 倾向因子方向问题 (H1, 跨 regime){Style.RESET_ALL}"
    elif verdicts_diverge:
        suffix = f"{Fore.YELLOW}— verdict 分化, 倾向 regime 驱动 (H2){Style.RESET_ALL}"
    else:
        suffix = ""
    body = " | ".join(parts)
    return f"  📊 时段单调性: {body} {suffix}".rstrip()


# ---------------------------------------------------------------------------
# M6: 多 horizon 单调性 (horizon breakdown)
# 回答 design packet H5/D1: 倒挂是 T+30 特定还是全 horizon?
# 排除 MR 短期反转假说 (H5) — 若短 horizon 就倒挂则非"短期反转长期才对".
# ---------------------------------------------------------------------------


@dataclass
class HorizonMonotonicity:
    """单个 horizon 的 score→winrate 单调性."""

    horizon: str  # 字段名 e.g. next_5day_return
    verdict: str  # monotonic | inverted | non_monotonic | insufficient
    winrates: list[float]  # ordered low→high (空若 insufficient)
    sample_count: int


def _horizon_label(horizon_field: str) -> str:
    """next_5day_return → T+5; next_day_return → T+1."""
    m = re.search(r"(\d+)", horizon_field)
    return f"T+{m.group(1)}" if m else horizon_field


def _bucket_returns_for_field(records: list[dict[str, Any]], field: str) -> dict[str, list[float]]:
    """{bucket: [returns]} for a given return field (复用 _score_bucket)."""
    out: dict[str, list[float]] = {}
    for rec in records:
        bucket = _score_bucket(_record_score(rec))
        val = _finite_float(rec.get(field))
        if val is None:
            continue
        out.setdefault(bucket, []).append(val)
    return out


def compute_horizon_monotonicity_from_loaded(
    records: list[dict[str, Any]],
    horizons: list[str],
    *,
    min_n: int = 15,
) -> list[HorizonMonotonicity]:
    """对每个 horizon 字段算 score→winrate 单调性.

    回答 design packet H5/D1: 若全 horizon 倒挂 → 非短期反转 (排除 H5 MR 假说).
    record 缺该 horizon 字段 → insufficient (诚实).
    """
    out: list[HorizonMonotonicity] = []
    for horizon in horizons:
        returns_by_bucket = _bucket_returns_for_field(records, horizon)
        verdict, wrs = _verdict(returns_by_bucket, min_n)
        sample = sum(len(v) for v in returns_by_bucket.values())
        out.append(
            HorizonMonotonicity(
                horizon=horizon,
                verdict=verdict,
                winrates=[w for w in wrs if w is not None],
                sample_count=sample,
            )
        )
    return out


def render_horizon_breakdown_line(horizons: list[HorizonMonotonicity]) -> str:
    """渲染多 horizon 单调性对比 (全 insufficient → 空串).

    展示形如:
      ``  📊 多周期单调性: T+5 倒挂⚠ (57→39) | T+10 非单调⚠ | T+30 倒挂⚠ (50→39) — 全 horizon 倒挂, 非短期反转``
    """
    if not horizons or all(h.verdict == "insufficient" for h in horizons):
        return ""

    def _seg(h: HorizonMonotonicity) -> str:
        label = _horizon_label(h.horizon)
        if h.verdict == "insufficient" or len(h.winrates) < 2:
            return f"{label} 样本不足"
        shape = "→".join(f"{w:.0%}" for w in h.winrates)
        tag = {"inverted": "倒挂⚠", "monotonic": "单调✓", "non_monotonic": "非单调⚠"}.get(h.verdict, h.verdict)
        return f"{label} {tag} ({shape})"

    parts = [_seg(h) for h in horizons]
    non_insufficient = [h for h in horizons if h.verdict != "insufficient"]
    all_inverted = bool(non_insufficient) and all(h.verdict == "inverted" for h in non_insufficient)
    # H5 判定: 全 horizon 倒挂 → 非短期反转 (排除 MR 短期反转假说)
    if all_inverted and len(non_insufficient) >= 2:
        suffix = f"{Fore.RED}— 多 horizon 均倒挂, 排除短期反转假说 (非 H5 MR){Style.RESET_ALL}"
    else:
        suffix = ""
    body = " | ".join(parts)
    return f"  📊 多周期单调性: {body} {suffix}".rstrip()


__all__ = [
    "BucketWinRate",
    "RankMonotonicityReport",
    "PeriodBreakdown",
    "HorizonMonotonicity",
    "compute_rank_monotonicity",
    "compute_rank_monotonicity_from_loaded",
    "compute_period_breakdown_from_loaded",
    "compute_horizon_monotonicity_from_loaded",
    "render_monotonicity_line",
    "render_period_breakdown_line",
    "render_horizon_breakdown_line",
]
