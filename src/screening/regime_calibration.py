"""P-5 市场状态条件胜率 — 按交易时 regime 分组的 T+30 命中率.

产品研究问题: ``market_state=cautious`` 时, T+30 胜率是否系统性更低? 用户该
不该在 cautious 时降仓位? 此前 calibration 只给全样本桶胜率, 不区分交易时的
市场状态, 用户无法校准"当前 regime 下这套推荐的可信度"。

本模块把每条 tracking_history 记录按其 recommended_date 对应报告的
``market_state.regime_gate_level`` 分组, 计算每个 regime 的 T+30 胜率/均收,
供 ``--confidence-calibration`` / ``--decision-flow`` 展示。

设计原则:
  - **data join by date** — recommended_date → 该日报告的 regime; 无报告日 → unknown
  - **per-regime (非 ×bucket)** — 桶×regime 单元过稀; per-regime 单元样本充足
  - **None when 无成熟 T+30** — 诚实, 非 fake 0
  - **研究性质** — 展示条件胜率让用户校准, 不自动改 BUY 门控 (门控变更需 owner 决策)

CLI: ``--confidence-calibration`` footer 调用
``render_regime_calibration_line(compute_regime_calibration(reports_dir))``。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from colorama import Fore, Style

#: regime_gate_level 的合法值排序 (展示顺序); 其余归 "其他"
_REGIME_ORDER: tuple[str, ...] = ("normal", "cautious", "risk_off", "crisis", "halt")


@dataclass
class RegimeWinRate:
    """单个 regime 的 T+30 条件胜率。"""

    regime: str
    t30_win_rate: float | None = None  # None when 无成熟 T+30
    t30_avg_return: float | None = None
    sample_count: int = 0  # 该 regime 下全部记录数
    mature_t30_count: int = 0  # 其中已有 T+30 收益的成熟记录


@dataclass
class RegimeCalibrationReport:
    """按 regime 分组的条件胜率汇总。"""

    rows: list[RegimeWinRate] = field(default_factory=list)
    unknown_regime_count: int = 0  # recommended_date 无对应报告的记录数


def _build_date_regime_map(history: list[dict[str, Any]]) -> dict[str, str]:
    """从 auto_screening 历史构建 {date_compact → regime_gate_level} 映射。"""
    mapping: dict[str, str] = {}
    for item in history:
        date_raw = str(item.get("date", "") or "").replace("-", "")
        payload = item.get("payload", {}) or {}
        market_state = (payload.get("market_state") or {}) if isinstance(payload, dict) else {}
        regime = str(market_state.get("regime_gate_level", "") or "normal").strip().lower() or "normal"
        if date_raw:
            mapping[date_raw] = regime
    return mapping


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
    if not returns:
        return None
    return sum(1 for x in returns if x > 0) / len(returns)


def _mean_or_none(returns: list[float]) -> float | None:
    return (sum(returns) / len(returns)) if returns else None


def compute_regime_calibration(
    *,
    reports_dir: Path | None = None,
    lookback_days: int = 30,
) -> RegimeCalibrationReport:
    """按交易时 regime 分组计算 T+30 条件胜率。

    Args:
        reports_dir: 报告目录 (None 时用 ``resolve_report_dir()``)
        lookback_days: 历史报告回溯天数

    Returns:
        :class:`RegimeCalibrationReport` (无数据时 rows 空)
    """
    from src.screening.consecutive_recommendation import (
        load_auto_screening_history,
        load_tracking_history,
        resolve_report_dir,
    )

    search_dir = reports_dir or resolve_report_dir()
    history = load_auto_screening_history(lookback_days=lookback_days, report_dir=search_dir)
    date_regime = _build_date_regime_map(history)

    records = load_tracking_history(search_dir)

    # Group T+30 returns by regime
    by_regime_returns: dict[str, list[float]] = {}
    by_regime_count: dict[str, int] = {}
    unknown = 0
    for rec in records:
        date_raw = str(rec.get("recommended_date", "") or "").replace("-", "")
        regime = date_regime.get(date_raw)
        if regime is None:
            unknown += 1
            continue
        by_regime_count[regime] = by_regime_count.get(regime, 0) + 1
        t30 = _optional_float(rec.get("next_30day_return"))
        if t30 is not None:
            by_regime_returns.setdefault(regime, []).append(t30)

    # Build rows in canonical regime order, then any extras
    seen = set()
    rows: list[RegimeWinRate] = []
    ordered = list(_REGIME_ORDER) + sorted(set(by_regime_count) - set(_REGIME_ORDER))
    for regime in ordered:
        if regime not in by_regime_count:
            continue
        seen.add(regime)
        t30_returns = by_regime_returns.get(regime, [])
        rows.append(
            RegimeWinRate(
                regime=regime,
                t30_win_rate=_win_rate_or_none(t30_returns),
                t30_avg_return=_mean_or_none(t30_returns),
                sample_count=by_regime_count[regime],
                mature_t30_count=len(t30_returns),
            )
        )

    return RegimeCalibrationReport(rows=rows, unknown_regime_count=unknown)


def render_regime_calibration_line(report: RegimeCalibrationReport) -> str:
    """渲染一行 regime 条件胜率摘要 (无数据 → 空串)。"""
    if not report.rows:
        return ""
    parts: list[str] = []
    for row in report.rows:
        wr = f"{row.t30_win_rate * 100:.0f}%" if row.t30_win_rate is not None else "—"
        color = Fore.GREEN if row.t30_win_rate is not None and row.t30_win_rate >= 0.5 else Fore.RED if row.t30_win_rate is not None and row.t30_win_rate < 0.5 else Fore.YELLOW
        parts.append(f"{row.regime} {color}{wr}{Style.RESET_ALL} (n={row.mature_t30_count})")
    header = f"  {Fore.CYAN}🌡 市场状态条件胜率 (T+30):{Style.RESET_ALL} "
    suffix = ""
    if report.unknown_regime_count:
        suffix = f"  {Fore.WHITE}({report.unknown_regime_count} 条无 regime){Style.RESET_ALL}"
    return header + " | ".join(parts) + suffix


__all__ = [
    "RegimeWinRate",
    "RegimeCalibrationReport",
    "compute_regime_calibration",
    "render_regime_calibration_line",
]
