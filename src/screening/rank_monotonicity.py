"""NS-4 排序单调性健康度: score rank → T+horizon 胜率是否单调.

R-5.F Phase 0 (state_type_calibration) 与真实数据 (493 条 tracking_history) 共同
发现: **模型整体排序倒挂** — low-score bucket T+30 胜率 50.5%, high-score bucket
反而 39.5% (高分票胜率最低). 这意味着 must-win 前门按 score 取的"最值得买"代表票,
真实赢面反而最差.

C222 (2026-06-28 horizon 一致性): 所有计算函数已参数化 ``horizon_field``
(默认 ``next_30day_return`` 保留 — NS-4 是长期质量诊断, T+30 短期波动小, 更适合
评估 score 区分度; C219 证明 low bucket T+5/T+10 winrate=60% 而 T+30 winrate=45%
是反弹特性, 不是 score 系统失效). 未来可在调用点传 ``horizon_field="next_5day_return"``
或 ``next_10day_return`` 并列诊断, 让 owner 看到"score 系统在短期 horizon 下是否仍
倒挂". 当前 ``top_picks._print_monotonicity_block`` 仍用默认 T+30 (footer 文案需
明确标注 horizon, 防止误读为 BUY 决策 horizon).

本模块把"高分是否 → 高胜率"量化成可复现的健康信号, 在 ``--top-picks`` footer 展示:

  - **inverted** (⚠): 低分→高分胜率单调递减 (模型把输家排前面, 最危险)
  - **monotonic** (✓): 低分→高分胜率递增 (理想)
  - **non_monotonic**: 既非单调也非倒挂 (部分倒挂)
  - **insufficient**: 任一 bucket 样本 < min_n (诚实, 不下结论, 静默)

**纯诊断, 不改 gate / 不改 factor / 不改仓位** (越界 = 过拟合, Phase 0 STOP 裁决).
复用 state_type_calibration 的 ``_score_bucket`` / ``_build_date_state_type_map``
与 consecutive_recommendation 的数据加载, 镜像 regime_winrate / portfolio_concentration
的 footer-block 模式 (best-effort, 数据不足静默, 永不破坏前门).

数据流: load_tracking_history → records (recommendation_score + next_Nday_return);
load_auto_screening_history → {date → state_type} (per-state_type 细分).
"""
from __future__ import annotations

import math
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
    """单个 score-bucket 的胜率 (horizon 由 RankMonotonicityReport.horizon_label 标)."""

    bucket: str
    win_rate: float | None = None
    sample_count: int = 0


@dataclass
class RankMonotonicityReport:
    """score rank → 胜率单调性诊断报告 (horizon 默认 T+5, BUY gate 决策 horizon; 2026-06-28 C229 缩短自 T+30)."""

    overall_buckets: list[BucketWinRate] = field(default_factory=list)
    overall_verdict: str = "insufficient"  # monotonic | inverted | non_monotonic | insufficient
    overall_inverted: bool = False
    per_state_type: dict[str, list[BucketWinRate]] = field(default_factory=dict)
    per_state_type_verdict: dict[str, str] = field(default_factory=dict)
    horizon_label: str = "T+5"  # 决策 horizon (C229: 默认 T+5; 可传 next_10day_return / next_30day_return)


def _bucket_returns_by_state(
    records: list[dict[str, Any]],
    date_st: dict[str, str] | None = None,
    target_state: str | None = None,
    *,
    horizon_field: str = "next_5day_return",
) -> dict[str, list[float]]:
    """→ {bucket: [horizon returns]} 仅成熟该 horizon; target_state 过滤 (None=全部).

    C229 (2026-06-28 产品方向): must-win 周期 T+30 → T+5/T+10 (owner 决策; C219
    backfill T+5/T+10 winrate≈60% >> T+30≈45%). 默认改 ``next_5day_return`` 对齐 BUY
    gate 决策 horizon. 调用方仍可传 ``next_10day_return`` / ``next_30day_return``
    (T+30 保留为长期质量诊断 — 短期波动小, 评估 score 区分度更稳).
    """
    out: dict[str, list[float]] = {}
    for rec in records:
        if target_state is not None and date_st is not None:
            date_raw = str(rec.get("recommended_date", "") or "").replace("-", "")
            if date_st.get(date_raw) != target_state:
                continue
        bucket = _score_bucket(_record_score(rec))
        t = _finite_float(rec.get(horizon_field))
        if t is None:
            continue
        out.setdefault(bucket, []).append(t)
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
                win_rate=_win_rate(rets),
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
    horizon_field: str = "next_5day_return",
) -> RankMonotonicityReport:
    """纯函数: 用已加载 history + tracking records 算单调性报告 (可注入测试).

    C229: ``horizon_field`` 默认 ``next_5day_return`` (BUY gate 决策 horizon;
    2026-06-28 must-win 周期 T+30 → T+5/T+10). 透传给 :func:`_bucket_returns_by_state`.
    调用方可传 ``next_10day_return`` / ``next_30day_return`` (T+30 长期质量诊断).
    """
    date_st = _build_date_state_type_map(history)

    overall_returns = _bucket_returns_by_state(records, horizon_field=horizon_field)
    overall_verdict, _ = _verdict(overall_returns, min_n)
    report = RankMonotonicityReport(
        overall_buckets=_bucket_rows(overall_returns),
        overall_verdict=overall_verdict,
        overall_inverted=(overall_verdict == "inverted"),
        horizon_label=_horizon_label(horizon_field),
    )

    # per-state_type 细分 (仅出现过的 state_type)
    seen_states: set[str] = set()
    for rec in records:
        date_raw = str(rec.get("recommended_date", "") or "").replace("-", "")
        st = date_st.get(date_raw)
        if st:
            seen_states.add(st)
    for st in sorted(seen_states):
        st_returns = _bucket_returns_by_state(records, date_st, st, horizon_field=horizon_field)
        st_verdict, _ = _verdict(st_returns, min_n)
        report.per_state_type[st] = _bucket_rows(st_returns)
        report.per_state_type_verdict[st] = st_verdict

    return report


def compute_rank_monotonicity(
    *,
    reports_dir: Path | None = None,
    lookback_days: int = 30,
    min_n: int = _MIN_N_PER_BUCKET_DEFAULT,
    horizon_field: str = "next_5day_return",
) -> RankMonotonicityReport:
    """从报告目录加载数据算单调性 (镜像 state_type_calibration 的 IO 包装).

    C229: ``horizon_field`` 默认 ``next_5day_return`` (BUY gate 决策 horizon).
    """
    from src.screening.consecutive_recommendation import (
        load_auto_screening_history,
        load_tracking_history,
        resolve_report_dir,
    )

    search_dir = reports_dir or resolve_report_dir()
    history = load_auto_screening_history(lookback_days=lookback_days, report_dir=search_dir)
    records = load_tracking_history(search_dir)
    return compute_rank_monotonicity_from_loaded(
        history, records, min_n=min_n, horizon_field=horizon_field
    )


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
        f"{_BUCKET_LABEL.get(b.bucket, b.bucket)}{b.win_rate:.0%}"
        for b in report.overall_buckets
        if b.win_rate is not None
    ]
    if len(parts) < 2:
        return ""
    shape = " → ".join(parts)
    hlabel = f"({report.horizon_label})" if report.horizon_label else ""

    if report.overall_verdict == "inverted":
        return (
            f"  {Fore.RED}⚠ 排序单调性 {hlabel}: {shape} 倒挂{Style.RESET_ALL}"
            f" {Fore.RED}(高分票胜率反而更低 — 模型打分质量待改进){Style.RESET_ALL}"
        )
    if report.overall_verdict == "monotonic":
        return (
            f"  {Fore.GREEN}✓ 排序单调性 {hlabel}: {shape}{Style.RESET_ALL}"
            f" {Fore.GREEN}(高分→高胜率){Style.RESET_ALL}"
        )
    # non_monotonic
    return (
        f"  {Fore.YELLOW}⚠ 排序单调性 {hlabel}: {shape} 非单调{Style.RESET_ALL}"
        f" {Fore.YELLOW}(部分 bucket 倒挂 — 模型打分质量不稳定){Style.RESET_ALL}"
    )


def render_per_state_type_monotonicity_line(report: RankMonotonicityReport) -> str:
    """渲染 per-state_type 单调性细分 (无数据/无 state_type → 空串).

    c334/autodev-36: per_state_type 之前 computed-but-unrendered. 回答关键问题:
    倒挂是全 regime 一致 (model defect) 还是 regime-specific (expected)?
    展示形如:
      ``  📊 单调性 per state_type: crisis 倒挂⚠ (低50%→高40%) | normal 倒挂⚠ (低55%→高42%) — 全 regime 倒挂, 倾向 model defect``
    """
    if not report.per_state_type_verdict:
        return ""
    parts = []
    for st, verdict in sorted(report.per_state_type_verdict.items()):
        buckets = report.per_state_type.get(st, [])
        wrs = [b.win_rate for b in buckets if b.win_rate is not None]
        if len(wrs) < 2:
            continue
        shape = "→".join(f"{w:.0%}" for w in wrs)
        tag = {"inverted": "倒挂⚠", "monotonic": "单调✓", "non_monotonic": "非单调⚠"}.get(verdict, verdict)
        parts.append(f"{st} {tag} ({shape})")
    if not parts:
        return ""
    body = " | ".join(parts)
    hlabel = f"({report.horizon_label})" if report.horizon_label else ""
    # 裁决: 全倒挂 → model defect; 分化 → regime-specific
    non_insufficient = [v for v in report.per_state_type_verdict.values() if v != "insufficient"]
    all_inverted = bool(non_insufficient) and all(v == "inverted" for v in non_insufficient)
    verdicts_diverge = len(set(non_insufficient)) > 1
    if all_inverted and len(non_insufficient) >= 2:
        suffix = f" {Fore.RED}— 全 regime 倒挂, 倾向 model defect{Style.RESET_ALL}"
    elif verdicts_diverge:
        suffix = f" {Fore.YELLOW}— verdict 分化, regime-specific{Style.RESET_ALL}"
    else:
        suffix = ""
    return f"  📊 排序单调性 {hlabel} per state_type: {body}{suffix}"


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
    horizon_field: str = "next_30day_return",
) -> list[PeriodBreakdown]:
    """按 recommended_date 排序分 n_periods 段, 每段算 score→T+horizon winrate 单调性.

    回答 design packet H1 vs H2: 两段都倒挂 → H1 因子方向 bug; verdict 分化 → H2 regime.
    分段后样本变薄, min_n 默认 15 (比 overall 的 20 宽松, 诚实标注可靠性).

    C222: ``horizon_field`` 参数化 (默认 ``next_30day_return``) — 与
    :func:`compute_rank_monotonicity_from_loaded` 对齐.
    """
    # 按 recommended_date 分组, 仅成熟该 horizon
    by_date: dict[str, list[dict[str, Any]]] = {}
    for rec in records:
        t = _finite_float(rec.get(horizon_field))
        if t is None:
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
        returns_by_bucket = _bucket_returns_by_state(seg_records, horizon_field=horizon_field)
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


# ---------------------------------------------------------------------------
# M7: 单调性统计显著性 — NS-4 倒挂是真的还是小样本噪声?
# high-vs-low two-proportion z-test (pooled) + p-value.
# 真实数据: T+30 倒挂 11pp 但 high n=38 → p=0.245 不显著 (可能噪声).
# 防 owner 据 NS-4 "倒挂" over-react 到噪声改模型.
# ---------------------------------------------------------------------------


@dataclass
class SignificanceResult:
    """high-vs-low 胜率差异的统计显著性."""

    low_winrate: float | None = None
    low_n: int = 0
    high_winrate: float | None = None
    high_n: int = 0
    z_score: float | None = None
    p_value: float | None = None
    verdict_note: str = "insufficient"  # significant | marginal | not_significant | insufficient


def _normal_cdf(z: float) -> float:
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def _two_proportion_z(k1: int, n1: int, k2: int, n2: int) -> tuple[float, float] | None:
    """two-proportion pooled z-test (low vs high). Returns (z, two-tailed p) or None."""
    if n1 == 0 or n2 == 0:
        return None
    p1, p2 = k1 / n1, k2 / n2
    pooled = (k1 + k2) / (n1 + n2)
    variance = pooled * (1 - pooled) * (1 / n1 + 1 / n2)
    if variance <= 0:
        return None
    se = math.sqrt(variance)
    z = (p1 - p2) / se
    p = 2 * (1 - _normal_cdf(abs(z)))
    return z, p


def compute_high_vs_low_significance_from_loaded(
    records: list[dict[str, Any]],
    *,
    horizon_field: str = "next_30day_return",
    min_n: int = 20,
) -> SignificanceResult:
    """high-vs-low T+horizon 胜率差异的统计显著性 (z-test).

    verdict_note:
      - insufficient: low/high n < min_n (诚实, 不下结论)
      - significant: p < 0.05
      - marginal: 0.05 ≤ p < 0.10
      - not_significant: p ≥ 0.10 (NS-4 倒挂可能属此, 高分桶小样本噪声)
    """
    low_returns: list[float] = []
    high_returns: list[float] = []
    for rec in records:
        bucket = _score_bucket(_record_score(rec))
        val = _finite_float(rec.get(horizon_field))
        if val is None:
            continue
        if bucket == "low":
            low_returns.append(val)
        elif bucket == "high":
            high_returns.append(val)

    nl, nh = len(low_returns), len(high_returns)
    if nl < min_n or nh < min_n:
        return SignificanceResult(low_n=nl, high_n=nh, verdict_note="insufficient")

    kl = sum(1 for x in low_returns if x > 0)
    kh = sum(1 for x in high_returns if x > 0)
    result = _two_proportion_z(kl, nl, kh, nh)
    if result is None:
        return SignificanceResult(
            low_winrate=kl / nl, low_n=nl, high_winrate=kh / nh, high_n=nh, verdict_note="insufficient"
        )
    z, p = result
    if p < 0.05:
        note = "significant"
    elif p < 0.10:
        note = "marginal"
    else:
        note = "not_significant"
    return SignificanceResult(
        low_winrate=kl / nl,
        low_n=nl,
        high_winrate=kh / nh,
        high_n=nh,
        z_score=z,
        p_value=p,
        verdict_note=note,
    )


def render_significance_line(result: SignificanceResult) -> str:
    """渲染 high-vs-low 显著性提示 (insufficient → 空串).

    展示形如:
      ``  📊 high vs low 显著性: z=+1.16 p=0.245 不显著 (倒挂可能噪声, 勿 over-react)``
      ``  📊 high vs low 显著性: z=+3.2 p=0.001 显著 (倒挂真实)``
    """
    if result.verdict_note == "insufficient":
        return ""
    if result.z_score is None or result.p_value is None:
        return ""
    z = result.z_score
    p = result.p_value
    wr_low = f"{result.low_winrate:.0%}" if result.low_winrate is not None else "?"
    wr_high = f"{result.high_winrate:.0%}" if result.high_winrate is not None else "?"
    base = f"  📊 high vs low 显著性: low {wr_low} (n={result.low_n}) vs high {wr_high} (n={result.high_n}) | z={z:+.2f} p={p:.3f}"
    if result.verdict_note == "significant":
        return f"{base} {Fore.RED}显著 (差异真实){Style.RESET_ALL}"
    if result.verdict_note == "marginal":
        return f"{base} {Fore.YELLOW}边缘显著 (需更多样本确认){Style.RESET_ALL}"
    return f"{base} {Fore.YELLOW}不显著 (差异可能噪声, 勿 over-react){Style.RESET_ALL}"


# ---------------------------------------------------------------------------
# M8: 样本量充足性 (power analysis)
# M7 T+30 不显著因 high n=38 太小. 告诉 owner 需累积多少样本才能可靠检测倒挂.
# 防 owner 据 38 样本噪声下结论改模型. two-proportion sample size (pooled).
# ---------------------------------------------------------------------------


def _required_sample_size(
    p1: float, p2: float, *, z_alpha: float = 1.96, z_power: float = 0.84
) -> int | None:
    """检测 p1 vs p2 差异 (two-proportion, 80% power, alpha=0.05) 每组需 n.

    z_alpha=1.96 (two-tailed 0.05), z_power=0.84 (80% power) 默认.
    返回 None 当 p1==p2 (零差异, 无需检测).
    """
    gap = p1 - p2
    if abs(gap) < 1e-9:
        return None
    variance_sum = p1 * (1 - p1) + p2 * (1 - p2)
    n = (z_alpha + z_power) ** 2 * variance_sum / (gap * gap)
    return math.ceil(n)


@dataclass
class PowerAnalysisResult:
    """high-vs-low 倒挂检测的样本量充足性."""

    low_p: float | None = None
    high_p: float | None = None
    gap_pp: float | None = None  # 百分点
    required_n_per_group: int | None = None
    current_high_n: int = 0
    sufficiency_pct: float | None = None  # current_high_n / required * 100
    verdict: str = "no_data"  # no_data | insufficient_samples | sufficient


def compute_power_analysis_from_loaded(
    records: list[dict[str, Any]],
    *,
    horizon_field: str = "next_30day_return",
    min_n: int = 20,
) -> PowerAnalysisResult:
    """算当前 high-vs-low 倒挂检测的样本充足性.

    verdict:
      - no_data: low/high bucket 缺
      - insufficient_samples: current_high_n < required (NS-4 T+30 属此, n=38 << 317)
      - sufficient: current_high_n >= required
    """
    low_returns: list[float] = []
    high_returns: list[float] = []
    for rec in records:
        bucket = _score_bucket(_record_score(rec))
        val = _finite_float(rec.get(horizon_field))
        if val is None:
            continue
        if bucket == "low":
            low_returns.append(val)
        elif bucket == "high":
            high_returns.append(val)

    nl, nh = len(low_returns), len(high_returns)
    if nl == 0 or nh == 0:
        return PowerAnalysisResult(current_high_n=nh, verdict="no_data")

    low_p = sum(1 for x in low_returns if x > 0) / nl
    high_p = sum(1 for x in high_returns if x > 0) / nh
    required = _required_sample_size(low_p, high_p)
    if required is None:
        return PowerAnalysisResult(
            low_p=low_p, high_p=high_p, gap_pp=0.0, current_high_n=nh, verdict="no_data"
        )
    sufficiency = nh / required * 100.0
    verdict = "sufficient" if nh >= required else "insufficient_samples"
    return PowerAnalysisResult(
        low_p=low_p,
        high_p=high_p,
        gap_pp=round((low_p - high_p) * 100, 1),
        required_n_per_group=required,
        current_high_n=nh,
        sufficiency_pct=round(sufficiency, 1),
        verdict=verdict,
    )


def render_power_line(result: PowerAnalysisResult) -> str:
    """渲染样本充足性提示 (no_data → 空串).

    展示形如:
      ``  📊 样本充足性: 检测当前 11pp 差异需 ~317/组 (80% power, p<.05), 当前 high n=38 (12%, ⚠ 严重不足, 勿据噪声下结论)``
    """
    if result.verdict == "no_data" or result.required_n_per_group is None:
        return ""
    req = result.required_n_per_group
    cur = result.current_high_n
    pct = f"{result.sufficiency_pct:.0f}%" if result.sufficiency_pct is not None else "?"
    gap = f"{result.gap_pp:.0f}pp" if result.gap_pp is not None else "?"
    base = f"  📊 样本充足性: 检测当前 {gap} 差异需 ~{req}/组 (80% power, p<.05), 当前 high n={cur} ({pct})"
    if result.verdict == "sufficient":
        return f"{base} {Fore.GREEN}✓ 足够下结论{Style.RESET_ALL}"
    return f"{base} {Fore.RED}⚠ 不足, 勿据噪声下结论 (累积 high bucket){Style.RESET_ALL}"


__all__ = [
    "BucketWinRate",
    "RankMonotonicityReport",
    "PeriodBreakdown",
    "HorizonMonotonicity",
    "SignificanceResult",
    "PowerAnalysisResult",
    "compute_rank_monotonicity",
    "compute_rank_monotonicity_from_loaded",
    "compute_period_breakdown_from_loaded",
    "compute_horizon_monotonicity_from_loaded",
    "compute_high_vs_low_significance_from_loaded",
    "compute_power_analysis_from_loaded",
    "render_monotonicity_line",
    "render_per_state_type_monotonicity_line",
    "render_period_breakdown_line",
    "render_horizon_breakdown_line",
    "render_significance_line",
    "render_power_line",
]
