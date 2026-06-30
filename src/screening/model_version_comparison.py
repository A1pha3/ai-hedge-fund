"""NS-7 新模型效果监测 — 按 ``model_version`` 分组对比新旧模型表现.

§三·6 backlog (NS-7, P2): owner 改因子后 (commits ab96aae0..e5406887) 累积 T+5/T+10
实现收益后, 按 NS-2 ``model_version`` (git short sha) 分组对比新旧模型的 winrate +
median return, 告诉 owner 每次调参是否真的改善 (服务 owner 因子调优, P&L 最大杠杆).

**缺口 (本模块补)**: NS-2 ``model_version`` 标注已存在于 ``TrackingRecord``, 但
:mod:`rank_monotonicity` / :mod:`north_star_pnl` / :mod:`factor_attribution_by_state`
均在**全部**记录上聚合, 不分版本 → owner 看不到单次调参的效果方向. 本模块按 version
分组, 取两个最近活跃版本 (按 ``recommended_date`` 排序) 做 candidate-vs-baseline 对比.

镜像 :mod:`north_star_pnl` 的 footer-block 模式: best-effort, 数据不足诚实标
``insufficient`` (新模型累积 < ``min_samples`` 个 mature 记录), 永不破坏前门.

**纯诊断, 不改 gate/factor/仓位/score** (越界=过拟合). 完整运行需新模型累积
≥ ``min_samples`` 个 mature T+5/T+10 记录; 数据成熟前 verdict=``insufficient``.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from typing import Any

from src.utils.display import Fore, Style

#: 每个版本最少 mature 记录数 (NS-7 backlog: ≥10 交易日; 镜像 north_star_pnl min_n)
_MIN_SAMPLES_DEFAULT = 10

#: 候选版本 winrate 优于基线多少 pp 算 "improved" (避免噪声抖动; 低于此 = unchanged)
_IMPROVEMENT_THRESHOLD_PP = 0.0


def _finite_float(value: Any) -> float | None:
    """Coerce to finite float; None/NaN/Inf/non-numeric → None (镜像 north_star_pnl)."""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(f):
        return None
    return f


@dataclass
class ModelVersionMetrics:
    """单个 model_version 的实现表现摘要."""

    model_version: str
    n_samples: int  # mature (finite-return) record count
    winrate: float | None  # fraction with positive horizon return (0..1); None if no samples
    median_return: float | None  # median realized horizon return; None if no samples
    latest_date: str  # most recent recommended_date for this version (activity ordering)
    sufficient: bool  # n_samples >= min_samples
    # NS-7 extension: per-version rank monotonicity (does higher score → higher winrate WITHIN
    # this version? directly measures whether owner factor tuning reduces the NS-4 score→winrate
    # inversion). verdict: monotonic|inverted|flat|insufficient.
    rank_monotonicity_verdict: str = "insufficient"
    low_score_winrate: float | None = None  # winrate of the low-score half (0..1)
    high_score_winrate: float | None = None  # winrate of the high-score half (0..1)


@dataclass
class ModelVersionComparison:
    """两个最近活跃 model_version 的对比."""

    baseline: ModelVersionMetrics | None  # second-most-recently-active
    candidate: ModelVersionMetrics | None  # most-recently-active (newest tuning)
    delta_winrate: float | None  # candidate - baseline (pp as fraction); None if not comparable
    delta_median_return: float | None  # candidate - baseline
    verdict: str  # improved|degraded|unchanged|insufficient|inconclusive|single_version|no_data
    all_versions: list[ModelVersionMetrics] = field(default_factory=list)
    # NS-7 disclosure: pre-NS-2 (commit d61f5dba 2026-06-26 之前) tracking_history 记录
    # 无 model_version 字段, 无法分配到任何 version bucket, 不参与 per-version
    # rank_monotonicity 验证. 这里统计被排除数, 供 render 显式披露 (避免 owner 误以为
    # 数据缺失或传播 bug). no_data 时仍可通过此字段程序化访问, 但 render 保持静默.
    excluded_pre_versioning_count: int = 0


def _horizon_return(rec: dict[str, Any], horizon_field: str) -> float | None:
    return _finite_float(rec.get(horizon_field))


def _version_key(rec: dict[str, Any]) -> str:
    return str(rec.get("model_version", "") or "")


def _date_key(rec: dict[str, Any]) -> str:
    # 容忍 recommended_date / trade_date / date (tracking_history 用 recommended_date)
    for key in ("recommended_date", "trade_date", "date"):
        val = rec.get(key)
        if val:
            return str(val)
    return ""


def _score_rank_monotonicity(recs: list[dict[str, Any]], horizon_field: str, rank_min_per_half: int) -> tuple[str, float | None, float | None]:
    """Per-version rank monotonicity: split records by score median into low/high halves,
    compute winrate of each. verdict: monotonic (high ≥ low) / inverted (high < low, the NS-4
    signal) / flat / insufficient (too few records or no scores).

    Returns ``(verdict, low_score_winrate, high_score_winrate)``. Self-contained (no external
    history map); quick per-version signal — owner can cross-reference the full NS-4
    rank_monotonicity footer for the 3-bucket + per-state-type breakdown.
    """
    scored = []
    for rec in recs:
        s = _finite_float(rec.get("recommendation_score"))
        if s is None:
            s = _finite_float(rec.get("score_b"))  # fallback (mirror north_star_pnl)
        r = _horizon_return(rec, horizon_field)
        if s is not None and r is not None:
            scored.append((s, r))
    if len(scored) < rank_min_per_half * 2:
        return ("insufficient", None, None)
    scored.sort(key=lambda x: x[0])  # ascending by score
    mid = len(scored) // 2
    low = scored[:mid]
    high = scored[mid:]
    low_wr = sum(1 for _, r in low if r > 0) / len(low)
    high_wr = sum(1 for _, r in high if r > 0) / len(high)
    if high_wr > low_wr:
        verdict = "monotonic"
    elif high_wr < low_wr:
        verdict = "inverted"
    else:
        verdict = "flat"
    return (verdict, low_wr, high_wr)


def compute_model_version_metrics(
    records: list[dict[str, Any]],
    *,
    horizon_field: str = "next_5day_return",
    min_samples: int = _MIN_SAMPLES_DEFAULT,
    rank_min_per_half: int = 5,
) -> list[ModelVersionMetrics]:
    """按 model_version 分组, 算每组的 n_samples / winrate / median_return / rank_monotonicity.

    跳过无 model_version 标注 (pre-NS-2 旧报告) 或 horizon return 非有限值的记录.
    返回按 ``latest_date`` 降序排列 (最近活跃在前), 供 caller 取 candidate/baseline.

    ``rank_min_per_half``: per-version rank monotonicity 需每半 (low/high score) 至少
    这么多记录 (default 5 → 版本需 ≥10 有分记录). 不足 → verdict=insufficient.

    纯函数 (无 I/O), 可用合成 records 注入测试.
    """
    by_version: dict[str, list[dict[str, Any]]] = {}
    for rec in records:
        version = _version_key(rec)
        if not version:
            continue  # 无版本标注 (pre-NS-2) → 无法对比, 跳过
        by_version.setdefault(version, []).append(rec)

    result: list[ModelVersionMetrics] = []
    for version, recs in by_version.items():
        returns = [r for r in (_horizon_return(rec, horizon_field) for rec in recs) if r is not None]
        dates = [_date_key(rec) for rec in recs]
        n = len(returns)
        winrate = (sum(1 for r in returns if r > 0) / n) if n else None
        median_return = statistics.median(returns) if returns else None
        latest_date = max((d for d in dates if d), default="")
        rm_verdict, low_wr, high_wr = _score_rank_monotonicity(recs, horizon_field, rank_min_per_half)
        result.append(
            ModelVersionMetrics(
                model_version=version,
                n_samples=n,
                winrate=winrate,
                median_return=median_return,
                latest_date=latest_date,
                sufficient=(n >= min_samples),
                rank_monotonicity_verdict=rm_verdict,
                low_score_winrate=low_wr,
                high_score_winrate=high_wr,
            )
        )

    result.sort(key=lambda m: m.latest_date, reverse=True)
    return result


def compare_model_versions(
    records: list[dict[str, Any]],
    *,
    horizon_field: str = "next_5day_return",
    min_samples: int = _MIN_SAMPLES_DEFAULT,
    rank_min_per_half: int = 5,
) -> ModelVersionComparison:
    """对比两个最近活跃 model_version, 给出 verdict + delta.

    verdict 语义:
      - ``improved``: candidate winrate > baseline winrate (新调参胜率提升)
      - ``degraded``: candidate winrate < baseline winrate
      - ``unchanged``: 二者相等
      - ``insufficient``: candidate n < min_samples (新模型数据未成熟, 不能下结论)
      - ``inconclusive``: candidate 足够但 baseline 不足 (无可靠基线)
      - ``single_version``: 仅一个版本 (待累积第二个版本)
      - ``no_data``: 无有效记录

    NS-7 disclosure: 统计 pre-NS-2 (commit d61f5dba 之前) 无 model_version 的记录数,
    填入 ``excluded_pre_versioning_count`` 供 render 显式披露. 这些记录无法分配到任何
    version bucket, 不参与 per-version rank_monotonicity 验证 (NS-4 per-version 验证).
    """
    # NS-7 disclosure: 统计 pre-versioning 记录 (空 / None model_version)
    excluded_count = sum(1 for rec in records if not _version_key(rec))

    versions = compute_model_version_metrics(records, horizon_field=horizon_field, min_samples=min_samples, rank_min_per_half=rank_min_per_half)
    if not versions:
        return ModelVersionComparison(
            baseline=None,
            candidate=None,
            delta_winrate=None,
            delta_median_return=None,
            verdict="no_data",
            all_versions=[],
            excluded_pre_versioning_count=excluded_count,
        )
    if len(versions) == 1:
        return ModelVersionComparison(
            baseline=None,
            candidate=versions[0],
            delta_winrate=None,
            delta_median_return=None,
            verdict="single_version",
            all_versions=versions,
            excluded_pre_versioning_count=excluded_count,
        )

    candidate = versions[0]  # 最近活跃 = 最新调参
    baseline = versions[1]  # 次近活跃 = 前一版本

    if not candidate.sufficient:
        verdict = "insufficient"
    elif not baseline.sufficient:
        verdict = "inconclusive"
    elif candidate.winrate is None or baseline.winrate is None:
        verdict = "inconclusive"
    else:
        delta_pp = candidate.winrate - baseline.winrate
        if delta_pp > _IMPROVEMENT_THRESHOLD_PP / 100.0:
            verdict = "improved"
        elif delta_pp < -_IMPROVEMENT_THRESHOLD_PP / 100.0:
            verdict = "degraded"
        else:
            verdict = "unchanged"

    delta_winrate = None
    if candidate.winrate is not None and baseline.winrate is not None:
        delta_winrate = candidate.winrate - baseline.winrate
    delta_median = None
    if candidate.median_return is not None and baseline.median_return is not None:
        delta_median = candidate.median_return - baseline.median_return

    return ModelVersionComparison(
        baseline=baseline,
        candidate=candidate,
        delta_winrate=delta_winrate,
        delta_median_return=delta_median,
        verdict=verdict,
        all_versions=versions,
        excluded_pre_versioning_count=excluded_count,
    )


def _pct(x: float | None, *, signed: bool = False) -> str:
    """winrate (stored as fraction 0..1) → percent display."""
    if x is None:
        return "—"
    if signed:
        return f"{x * 100:+.1f}%"
    return f"{x * 100:.0f}%"


def _ret(x: float | None) -> str:
    """realized return (already stored in PERCENT, e.g. 1.8 = 1.8%; 镜像 north_star_pnl).

    ``next_5day_return`` 在 tracking_history 中以**百分比**存储 (非 fraction),
    故此处不再 ×100 (否则双重缩放, +1.8% 误显 +180%).
    """
    if x is None:
        return "—"
    return f"{x:+.1f}%"


def _short(version: str) -> str:
    return version[:7]


def _rank_mono_tag(m: ModelVersionMetrics) -> str:
    """Per-version rank-monotonicity short tag for the footer line.

    Shows whether higher score → higher winrate WITHIN this version (monotonic✓) or the
    inverse (倒挂⚠ = the NS-4 score→winrate inversion, the owner's tuning target).
    """
    v = m.rank_monotonicity_verdict
    if v == "monotonic":
        return "单调✓"
    if v == "inverted":
        return "倒挂⚠"
    if v == "flat":
        return "持平"
    return "rank不足"


_VERDICT_MARKER = {
    "improved": ("✓", Fore.GREEN),
    "degraded": ("⚠", Fore.RED),
    "unchanged": ("→", Fore.YELLOW),
    "insufficient": ("·", Fore.YELLOW),
    "inconclusive": ("?", Fore.YELLOW),
    "single_version": ("·", Fore.YELLOW),
    "no_data": ("", ""),
}


def _excluded_suffix(comparison: ModelVersionComparison) -> str:
    """NS-7 disclosure: 构造 pre-NS-2 未版本化记录排除标注 (空串若无不渲染).

    展示形如: `` (排除 N 条 pre-NS-2 未版本化记录)``. owner 可据此判断为何部分
    tracking_history 记录未进入 per-version bucket (pre-versioning 历史数据, 非传播 bug).
    """
    n = comparison.excluded_pre_versioning_count
    if n <= 0:
        return ""
    return f" (排除{n}条 pre-NS-2 未版本化记录)"


def render_model_version_comparison_line(comparison: ModelVersionComparison) -> str:
    """渲染单行 footer (镜像 north_star_pnl/regime_winrate footer-block 风格).

    ``no_data`` → 空串 (静默, 不污染前门). 其余 → "模型版本监测: ..." 单行.
    NS-7 disclosure: 非 no_data 且存在 pre-NS-2 未版本化记录时, 末尾追加排除标注.
    """
    if comparison.verdict == "no_data":
        return ""

    marker, color = _VERDICT_MARKER.get(comparison.verdict, ("?", ""))
    verdict_label = {
        "improved": "改善",
        "degraded": "退化",
        "unchanged": "持平",
        "insufficient": "新版本样本不足",
        "inconclusive": "基线样本不足",
        "single_version": "仅单版本",
    }.get(comparison.verdict, comparison.verdict)

    excluded_suffix = _excluded_suffix(comparison)

    if comparison.verdict == "single_version" or comparison.baseline is None:
        c = comparison.candidate
        assert c is not None
        line = f"模型版本监测{marker}: 仅 {_short(c.model_version)} " f"(n={c.n_samples}, 胜率{_pct(c.winrate)}, 中位{_ret(c.median_return)}, {_rank_mono_tag(c)}) " f"[{verdict_label}, 待累积第二版本对比]{excluded_suffix}"
        return f"{color}{line}{Style.RESET_ALL}"

    b = comparison.baseline
    cand = comparison.candidate
    assert b is not None and cand is not None
    base_str = f"{_short(b.model_version)}(n={b.n_samples},胜率{_pct(b.winrate)},{_rank_mono_tag(b)})"
    cand_str = f"{_short(cand.model_version)}(n={cand.n_samples},胜率{_pct(cand.winrate)},{_rank_mono_tag(cand)})"

    if comparison.verdict in ("insufficient", "inconclusive"):
        line = f"模型版本监测{marker}: {base_str} → {cand_str} " f"[{verdict_label}, n_new={cand.n_samples}]{excluded_suffix}"
        return f"{color}{line}{Style.RESET_ALL}"

    dw = comparison.delta_winrate
    dw_str = f", 胜率Δ{dw * 100:+.0f}pp" if dw is not None else ""
    line = f"模型版本监测{marker}: {base_str} → {cand_str}{dw_str} [{verdict_label}]{excluded_suffix}"
    return f"{color}{line}{Style.RESET_ALL}"
