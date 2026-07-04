"""R-5.F Phase 0: 按 state_type 分组的 T+30 条件胜率诊断.

镜像 src/screening/regime_calibration.py, 但把分组轴从 regime_gate_level
换成 market_state.state_type (TREND/RANGE/MIXED/CRISIS). R-5.D 多时段诊断
表明胜率由'上涨 vs 震荡'驱动; state_type (TREND=全面上涨) 是比 regime_gate_level
更 discriminative 的轴. 本模块为 R-5.F gate 提供诊断证据, **不改 gate 代码**
(gate 改动是 Phase 1, 另起计划; 诊断纪律: 结论出来前不动 build_front_door_verdict).

三问:
  Q1 state_type 总体区分度 (TREND vs RANGE/MIXED 的 T+30 胜率差异)
  Q2 震荡市(RANGE/MIXED)内 score-bucket 细分, 是否有高胜率子集 (结构性机会)
  Q3 该子集留一时段样本外是否稳健 (防 in-sample 过拟合, v1/v2 教训)

数据流: load_auto_screening_history → {date → state_type} (state_type 已存于报告
payload.market_state, 无需重算 detect_market_state); load_tracking_history → 记录
(recommended_date + score_b + next_30day_return); 两者按 date join.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_VALID_STATE_TYPES: tuple[str, ...] = ("TREND", "RANGE", "MIXED", "CRISIS")


def _normalize_state_type(raw: Any) -> str:
    """大小写不敏感归一到 {TREND,RANGE,MIXED,CRISIS}, 其余 OTHER."""
    s = str(raw or "").strip().upper()
    return s if s in _VALID_STATE_TYPES else "OTHER"


def _build_date_state_type_map(history: list[dict[str, Any]]) -> dict[str, str]:
    """从 auto_screening 历史构建 {date_compact → state_type} 映射."""
    mapping: dict[str, str] = {}
    for item in history:
        date_raw = str(item.get("date", "") or "").replace("-", "")
        payload = item.get("payload", {}) or {}
        market_state = payload.get("market_state") if isinstance(payload, dict) else {}
        market_state = market_state or {}
        if date_raw:
            mapping[date_raw] = _normalize_state_type(market_state.get("state_type"))
    return mapping


# ---------------------------------------------------------------------------
# Q1: state_type 总体区分度
# ---------------------------------------------------------------------------


@dataclass
class StateTypeWinRate:
    """单个 state_type 的 T+30 条件胜率。"""

    state_type: str
    t30_win_rate: float | None = None  # None when 无成熟 T+30
    t30_avg_return: float | None = None
    t30_median_return: float | None = None  # R-6/R-7: median 防 异常值污染
    sample_count: int = 0  # 该 state_type 下全部记录数
    mature_t30_count: int = 0  # 其中已有 T+30 收益的成熟记录


@dataclass
class StateTypeCalibrationReport:
    """按 state_type 分组的条件胜率汇总。"""

    rows: list[StateTypeWinRate] = field(default_factory=list)
    unknown_state_type_count: int = 0  # recommended_date 无对应报告的记录数


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if result != result:  # NaN
        return None
    return result


def _record_score(rec: dict[str, Any]) -> Any:
    """读 tracking_history 记录的推荐分. 真实字段是 recommendation_score
    (consecutive_recommendation.load_tracking_history), 保留 score_b 兜底."""
    score = rec.get("recommendation_score")
    if score is None:
        score = rec.get("score_b")
    return score


def _win_rate_or_none(returns: list[float]) -> float | None:
    return (sum(1 for x in returns if x > 0) / len(returns)) if returns else None


def _mean_or_none(returns: list[float]) -> float | None:
    return (sum(returns) / len(returns)) if returns else None


def _median_or_none(returns: list[float]) -> float | None:
    if not returns:
        return None
    s = sorted(returns)
    n = len(s)
    mid = n // 2
    return s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2


def compute_state_type_calibration_from_loaded(
    history: list[dict[str, Any]],
    records: list[dict[str, Any]],
) -> StateTypeCalibrationReport:
    """纯函数: 用已加载的 history + tracking records 算问1报告 (可注入测试)."""
    date_st = _build_date_state_type_map(history)
    by_st_returns: dict[str, list[float]] = {}
    by_st_count: dict[str, int] = {}
    unknown = 0
    for rec in records:
        date_raw = str(rec.get("recommended_date", "") or "").replace("-", "")
        st = date_st.get(date_raw)
        if st is None:
            unknown += 1
            continue
        by_st_count[st] = by_st_count.get(st, 0) + 1
        t30 = _optional_float(rec.get("next_30day_return"))
        if t30 is not None:
            by_st_returns.setdefault(st, []).append(t30)
    ordered = list(_VALID_STATE_TYPES) + sorted(set(by_st_count) - set(_VALID_STATE_TYPES))
    rows: list[StateTypeWinRate] = []
    for st in ordered:
        if st not in by_st_count:
            continue
        rets = by_st_returns.get(st, [])
        rows.append(
            StateTypeWinRate(
                state_type=st,
                t30_win_rate=_win_rate_or_none(rets),
                t30_avg_return=_mean_or_none(rets),
                t30_median_return=_median_or_none(rets),
                sample_count=by_st_count[st],
                mature_t30_count=len(rets),
            )
        )
    return StateTypeCalibrationReport(rows=rows, unknown_state_type_count=unknown)


def compute_state_type_calibration(
    *,
    reports_dir: Path | None = None,
    lookback_days: int = 30,
) -> StateTypeCalibrationReport:
    """从报告目录加载数据算问1 (镜像 compute_regime_calibration 的 IO 包装)."""
    from src.screening.consecutive_recommendation import (
        load_auto_screening_history,
        load_tracking_history,
        resolve_report_dir,
    )

    search_dir = reports_dir or resolve_report_dir()
    history = load_auto_screening_history(lookback_days=lookback_days, report_dir=search_dir)
    records = load_tracking_history(search_dir)
    return compute_state_type_calibration_from_loaded(history, records)


# ---------------------------------------------------------------------------
# Q2: 震荡市内 score-bucket 细分 (找结构性赢面子集)
# ---------------------------------------------------------------------------


@dataclass
class StateTypeBucketWinRate:
    """state_type × score-bucket 单元的 T+30 胜率。"""

    state_type: str
    bucket: str
    t30_win_rate: float | None = None
    t30_avg_return: float | None = None
    t30_median_return: float | None = None
    sample_count: int = 0
    mature_t30_count: int = 0


def _score_bucket(score_b: Any) -> str:
    """score_b → bucket 标签. 边界对齐 dynamic_threshold 与 BUY 门控 (composite>=0.5)."""
    s = _optional_float(score_b)
    if s is None:
        return "unknown"
    if s < 0.30:
        return "low"
    if s < 0.40:
        return "mid_low"
    if s < 0.50:
        return "mid_high"
    return "high"


def compute_state_type_bucket_subdivision(
    history: list[dict[str, Any]],
    records: list[dict[str, Any]],
    *,
    target_state_types: tuple[str, ...] = ("RANGE", "MIXED"),
) -> list[StateTypeBucketWinRate]:
    """问2: 在 target_state_types 子集内按 score bucket 细分算 T+30 胜率.

    找'震荡市里仍有高胜率'的 bucket (结构性机会). 调用方按 mature_t30_count<20
    判定证据不足 (诚实, 不在此硬编码以免掩盖样本量).
    """
    date_st = _build_date_state_type_map(history)
    target = {s.upper() for s in target_state_types}
    by_cell_returns: dict[tuple[str, str], list[float]] = {}
    by_cell_count: dict[tuple[str, str], int] = {}
    for rec in records:
        date_raw = str(rec.get("recommended_date", "") or "").replace("-", "")
        st = date_st.get(date_raw)
        if st is None or st not in target:
            continue
        bucket = _score_bucket(_record_score(rec))
        key = (st, bucket)
        by_cell_count[key] = by_cell_count.get(key, 0) + 1
        t30 = _optional_float(rec.get("next_30day_return"))
        if t30 is not None:
            by_cell_returns.setdefault(key, []).append(t30)
    rows: list[StateTypeBucketWinRate] = []
    for (st, bucket), count in sorted(by_cell_count.items()):
        rets = by_cell_returns.get((st, bucket), [])
        rows.append(
            StateTypeBucketWinRate(
                state_type=st,
                bucket=bucket,
                t30_win_rate=_win_rate_or_none(rets),
                t30_avg_return=_mean_or_none(rets),
                t30_median_return=_median_or_none(rets),
                sample_count=count,
                mature_t30_count=len(rets),
            )
        )
    return rows


# ---------------------------------------------------------------------------
# Q3: 留一时段样本外验证 (防 in-sample 过拟合核心)
# ---------------------------------------------------------------------------


@dataclass
class LopoHeldoutResult:
    """单次留出日的验证结果。"""

    heldout_date: str
    rediscovered_winner_bucket: str | None  # 用非留出日数据发现的赢家 bucket
    heldout_winner_winrate: float | None  # 该赢家 bucket 在留出日的胜率
    heldout_n: int


@dataclass
class LopoReport:
    """留一时段验证汇总。"""

    target_state_types: tuple[str, ...]
    heldout_periods: int = 0
    rediscovered_winner_rate: float = 0.0  # 留出日赢家仍维持高胜率(>=floor)的比例
    robust: bool = False
    heldout_results: list[LopoHeldoutResult] = field(default_factory=list)


def _bucket_returns_by_date(records: list[dict[str, Any]], date_st: dict[str, str], target: set[str]) -> dict[str, dict[str, list[float]]]:
    """→ {date: {bucket: [returns]}} 仅 target state_type, 仅成熟 T+30 记录."""
    out: dict[str, dict[str, list[float]]] = {}
    for rec in records:
        date_raw = str(rec.get("recommended_date", "") or "").replace("-", "")
        st = date_st.get(date_raw)
        if st is None or st not in target:
            continue
        bucket = _score_bucket(_record_score(rec))
        t30 = _optional_float(rec.get("next_30day_return"))
        if t30 is None:
            continue
        out.setdefault(date_raw, {}).setdefault(bucket, []).append(t30)
    return out


def leave_one_period_out_validation(
    history: list[dict[str, Any]],
    records: list[dict[str, Any]],
    *,
    target_state_types: tuple[str, ...] = ("RANGE", "MIXED"),
    min_n: int = 20,
    winner_winrate_floor: float = 0.5,
) -> LopoReport:
    """问3: 留一时段样本外验证问2发现的赢家 bucket 是否稳健.

    每次留出一个日期 d: 用其余日期数据找 (胜率最高 且 n>=min_n 的 bucket) 作'赢家',
    再在留出日 d 上测该赢家 bucket 胜率. 若留出日胜率 >= winner_winrate_floor 计'维持'.
    robust = 维持率 >= 0.6 (多数留出日仍维持才算样本外稳健, 非 in-sample 假象).
    """
    date_st = _build_date_state_type_map(history)
    target = {s.upper() for s in target_state_types}
    by_date = _bucket_returns_by_date(records, date_st, target)
    dates = sorted(by_date.keys())
    heldout: list[LopoHeldoutResult] = []
    maintained = 0
    for d in dates:
        # 训练 = 所有非 d 日期的 bucket 汇总
        train: dict[str, list[float]] = {}
        for other, buckets in by_date.items():
            if other == d:
                continue
            for bucket, rets in buckets.items():
                train.setdefault(bucket, []).extend(rets)
        # 发现赢家: 胜率最高 且 样本 >= min_n
        winner: str | None = None
        winner_wr: float | None = None
        for bucket, rets in train.items():
            if len(rets) < min_n:
                continue
            wr = _win_rate_or_none(rets)
            if wr is not None and (winner_wr is None or wr > winner_wr):
                winner, winner_wr = bucket, wr
        # 在留出日测赢家
        heldout_rets = by_date[d].get(winner, []) if winner else []
        held_wr = _win_rate_or_none(heldout_rets)
        heldout.append(
            LopoHeldoutResult(
                heldout_date=d,
                rediscovered_winner_bucket=winner,
                heldout_winner_winrate=held_wr,
                heldout_n=len(heldout_rets),
            )
        )
        if held_wr is not None and held_wr >= winner_winrate_floor:
            maintained += 1
    rate = (maintained / len(dates)) if dates else 0.0
    return LopoReport(
        target_state_types=target_state_types,
        heldout_periods=len(dates),
        rediscovered_winner_rate=rate,
        robust=bool(dates) and rate >= 0.6,
        heldout_results=heldout,
    )


# ---------------------------------------------------------------------------
# Q4: verdict 聚合 (spec §九 映射表 → 1A / 1B / STOP)
# ---------------------------------------------------------------------------


@dataclass
class DiagnosisVerdict:
    """Phase 0 诊断裁决: 决定 Phase 1 走哪条路。"""

    phase1_branch: str  # "1A" | "1B" | "STOP"
    reason: str
    q1_trend_winrate: float | None = None
    q1_choppy_winrate: float | None = None
    q1_discriminative: bool = False
    q2_best_bucket: str | None = None
    q2_best_bucket_winrate: float | None = None
    q3_robust: bool = False


_Q1_MIN_GAP = 0.10  # TREND vs RANGE/MIXED 胜率差 >= 10pp 才算 discriminative
_Q1_MIN_N = 20
_Q2_WINNER_FLOOR = 0.50  # 震荡市赢家 bucket 胜率门槛


def _q1_is_discriminative(
    q1: StateTypeCalibrationReport,
) -> tuple[bool, float | None, float | None]:
    """判定问1: TREND 胜率 vs 震荡(RANGE/MIXED)最低胜率, 差 >= 10pp 且样本足."""
    by_st = {r.state_type: r for r in q1.rows}
    trend = by_st.get("TREND")
    choppy_rows = [r for r in q1.rows if r.state_type in ("RANGE", "MIXED") and r.mature_t30_count >= _Q1_MIN_N]
    if not trend or trend.mature_t30_count < _Q1_MIN_N or not choppy_rows:
        return False, (trend.t30_win_rate if trend else None), None
    choppy_wr = min(r.t30_win_rate or 0.0 for r in choppy_rows)
    discriminative = (trend.t30_win_rate or 0.0) - choppy_wr >= _Q1_MIN_GAP
    return discriminative, trend.t30_win_rate, choppy_wr


def aggregate_verdict(
    *,
    q1: StateTypeCalibrationReport,
    q2_best_bucket_winrate: float | None,
    q3: LopoReport,
) -> DiagnosisVerdict:
    """按 spec §九 映射表聚合三问结论 → 1A / 1B / STOP."""
    discriminative, trend_wr, choppy_wr = _q1_is_discriminative(q1)
    if not discriminative:
        return DiagnosisVerdict(
            phase1_branch="STOP",
            reason="state_type not discriminative (TREND vs RANGE/MIXED 胜率差 < 10pp 或样本不足)",
            q1_trend_winrate=trend_wr,
            q1_choppy_winrate=choppy_wr,
            q1_discriminative=False,
        )
    q2_yes = q2_best_bucket_winrate is not None and q2_best_bucket_winrate >= _Q2_WINNER_FLOOR
    if q2_yes and q3.robust:
        return DiagnosisVerdict(
            phase1_branch="1A",
            reason="震荡市存在样本外稳健的赢面 bucket → regime-conditional 精选",
            q1_trend_winrate=trend_wr,
            q1_choppy_winrate=choppy_wr,
            q1_discriminative=True,
            q2_best_bucket_winrate=q2_best_bucket_winrate,
            q3_robust=True,
        )
    return DiagnosisVerdict(
        phase1_branch="1B",
        reason="震荡市无样本外稳健赢面子集 → 保守版 (禁 BUY + 砍 top-3)",
        q1_trend_winrate=trend_wr,
        q1_choppy_winrate=choppy_wr,
        q1_discriminative=True,
        q2_best_bucket_winrate=q2_best_bucket_winrate,
        q3_robust=q3.robust,
    )


def run_state_type_diagnosis(
    *,
    reports_dir: Path | None = None,
    lookback_days: int = 30,
    target_state_types: tuple[str, ...] = ("RANGE", "MIXED"),
) -> tuple[
    StateTypeCalibrationReport,
    list[StateTypeBucketWinRate],
    LopoReport,
    DiagnosisVerdict,
]:
    """跑完三问 + 聚合 verdict. 返回 (q1, q2_rows, q3, verdict)."""
    from src.screening.consecutive_recommendation import (
        load_auto_screening_history,
        load_tracking_history,
        resolve_report_dir,
    )

    search_dir = reports_dir or resolve_report_dir()
    history = load_auto_screening_history(lookback_days=lookback_days, report_dir=search_dir)
    records = load_tracking_history(search_dir)
    q1 = compute_state_type_calibration_from_loaded(history, records)
    q2_rows = compute_state_type_bucket_subdivision(history, records, target_state_types=target_state_types)
    # 问2赢家: target 内胜率最高 且 mature n>=20 的 bucket
    qualified = [r for r in q2_rows if r.mature_t30_count >= _Q1_MIN_N and r.t30_win_rate is not None]
    q2_best = max(qualified, key=lambda r: r.t30_win_rate) if qualified else None
    # 留一时段 min_n: 真实每个日期的成熟样本可能很少, 用 2 (至少 2 只才算该日有信号)
    q3 = leave_one_period_out_validation(history, records, target_state_types=target_state_types, min_n=2)
    verdict = aggregate_verdict(
        q1=q1,
        q2_best_bucket_winrate=(q2_best.t30_win_rate if q2_best else None),
        q3=q3,
    )
    if q2_best is not None:
        verdict.q2_best_bucket = q2_best.bucket
    return q1, q2_rows, q3, verdict


__all__ = [
    "StateTypeWinRate",
    "StateTypeCalibrationReport",
    "StateTypeBucketWinRate",
    "LopoHeldoutResult",
    "LopoReport",
    "DiagnosisVerdict",
    "_build_date_state_type_map",
    "_score_bucket",
    "compute_state_type_calibration",
    "compute_state_type_calibration_from_loaded",
    "compute_state_type_bucket_subdivision",
    "leave_one_period_out_validation",
    "aggregate_verdict",
    "run_state_type_diagnosis",
]
