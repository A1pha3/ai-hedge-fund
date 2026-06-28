"""NS-6 因子归因 × state_type — 哪个因子在哪个市场帮倒忙.

§三·6 backlog (NS-6, P2): 各因子(T/MR/F/E)正/负贡献 × state_type 的 T+5/T+10
胜率, 告诉 owner 哪个因子在哪个市场帮倒忙 (服务 owner 因子调优, 最大 P&L 杠杆).

**用户方法论 (2026-06-29): 历史回测先行** — 不等 score_decomposition 持久化成熟.
数据来源: tracking_history (realized T+5/T+10 return) JOIN 历史报告 recommendations
(score_decomposition.base_contributions + market_state.state_type) on (ticker, date).
~7500 条 join 样本 (93% 历史报告有 score_decomposition).

镜像 factor_attribution (overall 归因) + state_type_calibration (state_type 维度) +
rank_monotonicity (footer-block) 结构. **纯诊断, 不改因子/gate/仓位** (越界=过拟合).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.screening.state_type_calibration import _score_bucket
from src.utils.display import Fore, Style

#: state_type 内每因子高/低组最低样本数 (镜像 rank_monotonicity _MIN_N)
_MIN_N_DEFAULT = 15

#: 倒挂阈值 (low_winrate - high_winrate > 此值 = 倒挂, 镜像 factor_attribution 0.05)
_INVERSION_THRESHOLD = 0.05


@dataclass
class FactorStateInversion:
    """单个 (state_type, factor) 的贡献→胜率倒挂."""

    state_type: str
    factor: str
    high_contrib_winrate: float
    low_contrib_winrate: float
    inversion: float  # low - high (正 = 倒挂: 贡献高反而胜率低)
    high_n: int
    low_n: int


@dataclass
class FactorAttributionByStateReport:
    """因子 × state_type 倒挂诊断报告."""

    inversions: list[FactorStateInversion] = field(default_factory=list)
    sample_count: int = 0
    state_types: list[str] = field(default_factory=list)
    horizon_label: str = "T+5"
    verdict: str = "insufficient"  # ok | insufficient


def _finite_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if result != result:  # NaN
        return None
    return result


def _horizon_label(horizon_field: str) -> str:
    m = re.search(r"(\d+)", horizon_field)
    return f"T+{m.group(1)}" if m else horizon_field


def compute_factor_attribution_by_state_from_loaded(
    records: list[dict[str, Any]],
    *,
    min_n: int = _MIN_N_DEFAULT,
    horizon_field: str = "next_5day_return",
) -> FactorAttributionByStateReport:
    """纯函数: 按 state_type × per-factor 贡献高/低算 T+horizon 胜率倒挂.

    Args:
        records: 每条含 ``state_type`` + ``score_decomposition.base_contributions``
            (dict[str, float]) + ``horizon_field`` (realized return). 缺任一字段跳过.
        min_n: 每 state×factor 高/低组最低样本数 (默认 15).
        horizon_field: 收益字段 (默认 next_5day_return, BUY gate 决策 horizon).

    Returns:
        :class:`FactorAttributionByStateReport` — 倒挂的 (state, factor) 列表.
        倒挂 = 该因子贡献高组胜率 < 低组 (inversion > threshold) → 该因子在该市场帮倒忙.
    """
    # 收集有效 records (有 base_contributions + state_type + horizon return)
    valid: list[tuple[str, dict[str, float], float]] = []
    for rec in records:
        decomp = rec.get("score_decomposition")
        if not isinstance(decomp, dict):
            continue
        bc = decomp.get("base_contributions")
        if not isinstance(bc, dict) or not bc:
            continue
        state = str(rec.get("state_type") or "").strip()
        if not state:
            continue
        ret = _finite_float(rec.get(horizon_field))
        if ret is None:
            continue
        # 规范化贡献为 float
        contribs = {k: (_finite_float(v) or 0.0) for k, v in bc.items()}
        valid.append((state, contribs, ret))

    if not valid:
        return FactorAttributionByStateReport(verdict="insufficient", horizon_label=_horizon_label(horizon_field))

    # 收集所有因子 keys (并集)
    all_factors: set[str] = set()
    for _, contribs, _ in valid:
        all_factors.update(contribs.keys())

    # 按 state_type 分组
    by_state: dict[str, list[tuple[dict[str, float], float]]] = {}
    for state, contribs, ret in valid:
        by_state.setdefault(state, []).append((contribs, ret))

    inversions: list[FactorStateInversion] = []
    for state in sorted(by_state.keys()):
        state_recs = by_state[state]
        for factor in sorted(all_factors):
            # 按该 factor 贡献排序
            sorted_recs = sorted(state_recs, key=lambda cr: cr[0].get(factor, 0.0))
            third = len(sorted_recs) // 3
            if third < min_n:
                continue  # 样本不足
            low_recs = sorted_recs[:third]
            high_recs = sorted_recs[-third:]
            low_returns = [r for _, r in low_recs]
            high_returns = [r for _, r in high_recs]
            if len(low_returns) < min_n or len(high_returns) < min_n:
                continue
            low_wr = sum(1 for x in low_returns if x > 0) / len(low_returns)
            high_wr = sum(1 for x in high_returns if x > 0) / len(high_returns)
            inversion = low_wr - high_wr  # 正 = 倒挂
            if inversion > _INVERSION_THRESHOLD:
                inversions.append(FactorStateInversion(
                    state_type=state, factor=factor,
                    high_contrib_winrate=high_wr, low_contrib_winrate=low_wr,
                    inversion=inversion, high_n=len(high_returns), low_n=len(low_returns),
                ))

    return FactorAttributionByStateReport(
        inversions=inversions,
        sample_count=len(valid),
        state_types=sorted(by_state.keys()),
        horizon_label=_horizon_label(horizon_field),
        verdict="ok" if inversions else "insufficient",
    )


# ---------------------------------------------------------------------------
# loader: join tracking_history (return) + 历史报告 recommendations
# (score_decomposition + state_type) — 用户方法论: 历史回测先行
# ---------------------------------------------------------------------------


def load_factor_attribution_by_state_records(
    reports_dir: Path,
) -> list[dict[str, Any]]:
    """JOIN tracking_history (realized return) + 历史报告 (score_decomposition + state_type).

    NS-6 数据源 (用户方法论: 不等 score_decomposition 持久化成熟):
      - tracking_history.records: (ticker, recommended_date, next_5day/10day return)
      - auto_screening_*.json recommendations: (ticker, date → score_decomposition
        + market_state.state_type)
      - join on (ticker, date) → records with (state_type, score_decomposition, returns)

    Returns:
        list of records, 每条含 state_type + score_decomposition + next_5day_return
        + next_10day_return. 缺字段的不含该字段 (消费侧 _finite_float 跳过).
    """
    import json

    reports_dir = Path(reports_dir)
    # 1. tracking_history → {(ticker, date): returns}
    th_path = reports_dir / "tracking_history.json"
    return_map: dict[tuple[str, str], dict[str, Any]] = {}
    try:
        th_payload = json.loads(th_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        th_payload = {"records": []}
    th_records = th_payload.get("records", th_payload) if isinstance(th_payload, dict) else th_payload
    for rec in th_records:
        if not isinstance(rec, dict):
            continue
        tk = str(rec.get("ticker", "") or "").strip()
        dt = str(rec.get("recommended_date", "") or "").strip()
        if not tk or not dt:
            continue
        return_map[(tk, dt)] = {
            "next_5day_return": rec.get("next_5day_return"),
            "next_10day_return": rec.get("next_10day_return"),
        }

    # 2. 历史报告 recommendations → join
    out: list[dict[str, Any]] = []
    for report_path in sorted(reports_dir.glob("auto_screening_*.json")):
        try:
            payload = json.loads(report_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if not isinstance(payload, dict):
            continue
        date = str(payload.get("date", "") or "").strip()
        if not date:
            continue
        market_state = payload.get("market_state") or {}
        state_type = str(market_state.get("state_type") or market_state.get("regime_gate_level") or "").strip()
        for rec in (payload.get("recommendations") or []):
            if not isinstance(rec, dict):
                continue
            tk = str(rec.get("ticker", "") or "").strip()
            if not tk:
                continue
            returns = return_map.get((tk, date))
            if returns is None:
                continue  # 无 realized return, 无法归因
            decomp = rec.get("score_decomposition")
            if not isinstance(decomp, dict):
                continue  # 无因子贡献
            out.append({
                "ticker": tk,
                "recommended_date": date,
                "state_type": state_type,
                "score_decomposition": decomp,
                "next_5day_return": returns.get("next_5day_return"),
                "next_10day_return": returns.get("next_10day_return"),
            })
    return out


def compute_factor_attribution_by_state(
    *, reports_dir: Path | None = None, min_n: int = _MIN_N_DEFAULT,
    horizon_field: str = "next_5day_return",
) -> FactorAttributionByStateReport:
    """IO 包装: load + compute (镜像 rank_monotonicity 模式)."""
    from src.screening.consecutive_recommendation import resolve_report_dir
    search_dir = reports_dir or resolve_report_dir()
    records = load_factor_attribution_by_state_records(search_dir)
    return compute_factor_attribution_by_state_from_loaded(records, min_n=min_n, horizon_field=horizon_field)


def compute_factor_attribution_score_controlled(
    *, reports_dir: Path | None = None, min_n: int = _MIN_N_DEFAULT,
    horizon_field: str = "next_5day_return",
) -> ScoreControlledFactorReport:
    """IO 包装: load + compute score-controlled (镜像 compute_factor_attribution_by_state)."""
    from src.screening.consecutive_recommendation import resolve_report_dir
    search_dir = reports_dir or resolve_report_dir()
    records = load_factor_attribution_by_state_records(search_dir)
    return compute_factor_attribution_score_controlled_from_loaded(records, min_n=min_n, horizon_field=horizon_field)


def render_factor_attribution_by_state_line(report: FactorAttributionByStateReport) -> str:
    """渲染因子 × state_type 倒挂 (insufficient/无倒挂 → 空串).

    展示形如:
      ``  ⚠ 因子归因(T+5): MIXED 市场 MR 倒挂 (高22% 低58%, 帮倒忙) | TREND 无倒挂``
    """
    if report.verdict != "ok" or not report.inversions:
        return ""
    parts = [
        f"{inv.state_type} {inv.factor} 倒挂 (高{inv.high_contrib_winrate:.0%} 低{inv.low_contrib_winrate:.0%}, 帮倒忙)"
        for inv in report.inversions[:4]  # 最多展示 4 个倒挂
    ]
    no_inversion_states = [st for st in report.state_types if st not in {inv.state_type for inv in report.inversions}]
    if no_inversion_states:
        parts.append(f"{'/'.join(no_inversion_states[:2])} 无倒挂")
    body = " | ".join(parts)
    return (
        f"  {Fore.RED}⚠ 因子归因({report.horizon_label}): {body}{Style.RESET_ALL}"
        f" {Fore.RED}(某因子高贡献反而低胜率 = 该市场帮倒忙, 供 owner 调优){Style.RESET_ALL}"
    )


# ---------------------------------------------------------------------------
# NS-6 score-controlled: 隔离因子真实效应 (排除 score-level confound)
# c239 uncontrolled NS-6 把 fundamental 标为倒挂 (+9%), 但 score-controlled 后
# 只剩 +5% (borderline) — 多数是 NS-4 score-level inversion 的 confound.
# event_sentiment 经 control 仍 +15% (真实倒挂). owner 据 score-controlled 决策.
# ---------------------------------------------------------------------------


@dataclass
class ScoreControlledFactorInversion:
    """单因子经 score 控制后的真实倒挂 (stratified within score bucket)."""

    factor: str
    stratified_inversion: float  # size-weighted avg of within-bucket inversions
    high_winrate: float
    low_winrate: float
    n: int
    survives: bool  # stratified_inversion > threshold (真实倒挂, 非 score confound)


@dataclass
class ScoreControlledFactorReport:
    """score-controlled 因子倒挂诊断报告 (confound-free)."""

    inversions: list[ScoreControlledFactorInversion] = field(default_factory=list)
    sample_count: int = 0
    horizon_label: str = "T+5"
    verdict: str = "insufficient"  # ok | insufficient


def compute_factor_attribution_score_controlled_from_loaded(
    records: list[dict[str, Any]],
    *,
    min_n: int = _MIN_N_DEFAULT,
    horizon_field: str = "next_5day_return",
) -> ScoreControlledFactorReport:
    """纯函数: score-controlled 因子倒挂 (stratified within score bucket).

    隔离因子真实效应, 排除 score-level inversion (NS-4) 的 confound:
      - 按 score bucket 分组 (low/mid_low/mid_high/high)
      - 每 bucket 内按 factor 贡献高/低 1/3 算胜率倒挂 (within-bucket, 已控制 score)
      - stratified_inversion = 各 bucket 倒挂的 size-weighted 平均
      - > threshold = 真实倒挂 (survives score control); 否则是 score confound

    Args:
        records: 每条含 score_decomposition.base_contributions + .total + horizon return.
        min_n: 每 score bucket 内 factor 高/低组最低样本数.

    Returns:
        :class:`ScoreControlledFactorReport` — survives=True 的因子是真实倒挂.
    """
    # 收集有效 records (base_contributions + total score + horizon return)
    valid: list[tuple[str, dict[str, float], float]] = []
    for rec in records:
        decomp = rec.get("score_decomposition")
        if not isinstance(decomp, dict):
            continue
        bc = decomp.get("base_contributions")
        if not isinstance(bc, dict) or not bc:
            continue
        score = _finite_float(decomp.get("total"))
        if score is None:
            continue
        ret = _finite_float(rec.get(horizon_field))
        if ret is None:
            continue
        contribs = {k: (_finite_float(v) or 0.0) for k, v in bc.items()}
        valid.append((_score_bucket(score), contribs, ret))

    if not valid:
        return ScoreControlledFactorReport(verdict="insufficient", horizon_label=_horizon_label(horizon_field))

    all_factors: set[str] = set()
    for _, contribs, _ in valid:
        all_factors.update(contribs.keys())

    # 按 score bucket 分组
    by_bucket: dict[str, list[tuple[dict[str, float], float]]] = {}
    for bucket, contribs, ret in valid:
        by_bucket.setdefault(bucket, []).append((contribs, ret))

    inversions: list[ScoreControlledFactorInversion] = []
    for factor in sorted(all_factors):
        # 每 bucket 内 within-bucket 倒挂 (已控制 score)
        total_weight = 0
        weighted_inversion = 0.0
        pooled_high_returns: list[float] = []
        pooled_low_returns: list[float] = []
        for bucket, bucket_recs in by_bucket.items():
            sorted_recs = sorted(bucket_recs, key=lambda cr: cr[0].get(factor, 0.0))
            third = len(sorted_recs) // 3
            if third < min_n:
                continue
            low_recs = sorted_recs[:third]
            high_recs = sorted_recs[-third:]
            low_returns = [r for _, r in low_recs]
            high_returns = [r for _, r in high_recs]
            if len(low_returns) < min_n or len(high_returns) < min_n:
                continue
            low_wr = sum(1 for x in low_returns if x > 0) / len(low_returns)
            high_wr = sum(1 for x in high_returns if x > 0) / len(high_returns)
            w = len(low_returns) + len(high_returns)
            weighted_inversion += (low_wr - high_wr) * w
            total_weight += w
            pooled_high_returns.extend(high_returns)
            pooled_low_returns.extend(low_returns)
        if total_weight == 0:
            continue
        stratified = weighted_inversion / total_weight
        if stratified > _INVERSION_THRESHOLD:
            inversions.append(ScoreControlledFactorInversion(
                factor=factor, stratified_inversion=stratified,
                high_winrate=sum(1 for x in pooled_high_returns if x > 0) / len(pooled_high_returns) if pooled_high_returns else 0.0,
                low_winrate=sum(1 for x in pooled_low_returns if x > 0) / len(pooled_low_returns) if pooled_low_returns else 0.0,
                n=len(pooled_high_returns) + len(pooled_low_returns),
                survives=True,
            ))

    return ScoreControlledFactorReport(
        inversions=inversions, sample_count=len(valid),
        horizon_label=_horizon_label(horizon_field),
        verdict="ok" if inversions else "insufficient",
    )


def render_score_controlled_factor_line(report: ScoreControlledFactorReport) -> str:
    """渲染 score-controlled 因子倒挂 (insufficient → 空串).

    展示形如:
      ``  ⚠ 因子真实倒挂(T+5, score-controlled): event_sentiment +15% (survives control) | fundamental borderline (filtered)``
    """
    if report.verdict != "ok" or not report.inversions:
        return ""
    parts = [
        f"{inv.factor} 倒挂 +{inv.stratified_inversion:.0%} (高{inv.high_winrate:.0%} 低{inv.low_winrate:.0%}, n={inv.n}, 经 score 控制仍真实)"
        for inv in report.inversions
    ]
    body = " | ".join(parts)
    return (
        f"  {Fore.RED}⚠ 因子真实倒挂({report.horizon_label}, score-controlled): {body}{Style.RESET_ALL}"
        f" {Fore.RED}(排除 score-level confound 后的真实因子效应, 供 owner 调优){Style.RESET_ALL}"
    )


__all__ = [
    "FactorStateInversion",
    "FactorAttributionByStateReport",
    "compute_factor_attribution_by_state_from_loaded",
    "compute_factor_attribution_by_state",
    "load_factor_attribution_by_state_records",
    "render_factor_attribution_by_state_line",
    "ScoreControlledFactorInversion",
    "ScoreControlledFactorReport",
    "compute_factor_attribution_score_controlled_from_loaded",
    "render_score_controlled_factor_line",
]
