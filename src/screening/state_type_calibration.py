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
