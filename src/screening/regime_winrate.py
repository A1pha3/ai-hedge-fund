"""R-5.A 按 regime 展示真实历史胜率 / regime-aware win-rate disclosure.

胜率随数据累积而变 (非固定值). 数据源由 NS-5 wiring 决定: 优先读 daily
scheduling 写的 ``regime_winrates_recomputed_*.json`` artifact (从
tracking_history 重算), fallback 到 hardcoded ``REGIME_HISTORICAL_WINRATES``.
早期 v1 (91 只) 误判 "crisis 73% 赚钱", v2 扩样本 (189 只) 修正为 "三 regime
都 30-47%"; 随 daily scheduling 累积至 8000+ records (2026-07), crisis 已回到
53% — **结论会随数据变, 勿在此 docstring 写死具体胜率** (loop 55 教训:
_REGIME_ADVICE 写死 ~47% 与 headline 53% 矛盾). 当前实际值见 JSON artifact
或 ``compute_regime_winrate_summary()`` 返回.

R-5.A 是**零行为改变**的诚实披露: 不碰 gate / 不碰仓位, 只在 --top-picks footer
按当前 regime 展示真实历史胜率, 让用户看到当前期望自己决定。这是赚钱工具的
诚实基础, 也是持续累积真实数据验证假设的基础设施。

loop 52-53: winrate 点估计附 bootstrap 95% CI (recompute 写, render 读+展示),
让 owner 区分 "53% ± 2pp" vs "34% ± 4pp" 的不确定性差异.

NS-5 (C234, 2026-06-28): 加 ``as_of`` 数据时点标注 + staleness 检测.
C220 BUY gate horizon T+30→T+5/T+10 后, 当前 T+30 硬编码数据已 stale (距 owner
改因子已 ≥4 天, 距 C220 release 已 0 天). 重算需新模型累积 ≥10 交易日 mature 数据
(post-push observation trigger 2026-07-12); 当前只做诚实披露 (as_of + ⚠ staleness
warning), 不假装重算. daily scheduling 重算脚本待数据 mature 后再加 (避免 dead code).

Staleness 阈值 ``REGIME_STALENESS_THRESHOLD_DAYS=14``: regime winrate 是中频更新数据
(不像 ticker price 高频), 14 天兼顾 (a) 不频繁误报 (daily 调度噪声) + (b) 不放过
真正过时 (owner 改因子后 ≥2 周还没重算就是问题).

NS-5 wiring (2026-06-30): daily scheduling 重算脚本已上线 (c256 ``run_daily_regime_refresh``
写 ``regime_winrates_recomputed_<date>.json`` artifact), 但生产代码仍读 hardcoded
constants — JSON artifact 写了但从不消费, 重算半环断裂. 本模块补 wiring:
- :func:`load_latest_regime_recompute` 找最新 artifact 并解析 (无 → ``None``).
- :func:`compute_regime_winrate_summary` / :func:`render_regime_multihorizon_line`
  优先读 JSON, fallback 到 hardcoded (JSON 缺失 / 损坏 / 字段不全).
- :class:`RegimeWinrateSummary`.``source`` 标注数据来源 (``recomputed_json`` |
  ``hardcoded_fallback``), 让 owner 一眼看出数据是否 fresh.
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from src.utils.display import Fore, Style

logger = logging.getLogger(__name__)


# NS-5 (C234): v2 扩样本 + 多周期扩展的统一数据时点.
# - T+30 winrate 来自 2026-06-24 v2 扩样本回测 (32 日期 ~189 只)
# - 多周期 median 来自 2026-06-25 Phase 1 扩展 (293 条 × 32 报告)
# 同一数据源切片, 取较晚日期 (2026-06-25) 作为统一时点.
REGIME_HISTORICAL_DATA_AS_OF: date = date(2026, 6, 25)

# NS-5 (C234): staleness 阈值 — as_of 距今 >14 天 → 数据可能过时 (⚠ 提示).
REGIME_STALENESS_THRESHOLD_DAYS: int = 14


@dataclass(frozen=True)
class RegimeWinrateSummary:
    """单个 regime 的真实历史 T+30 表现摘要.

    NS-5 (C234): ``as_of`` 字段标注数据时点, 配合 :func:`is_regime_data_stale`
    做 staleness 检测. ``None`` 表示未知 regime 或无数据 (视为 stale).

    NS-5 wiring (2026-06-30): ``source`` 字段标注数据来源 —
    ``recomputed_json`` (daily scheduling 写的 fresh JSON artifact) 或
    ``hardcoded_fallback`` (无 JSON / JSON 损坏 → fallback 到硬编码 constants).
    让 owner 一眼看出数据是否 fresh (渲染时不展示, 但调试 / log 可用).
    """

    regime: str
    has_data: bool = False
    winrate: float = 0.0  # 0-1, T+30 正收益比例
    winrate_ci_low: float | None = None  # bootstrap CI 下限 (loop 52)
    winrate_ci_high: float | None = None  # bootstrap CI 上限
    ci_level: float = 0.95  # bootstrap 置信水平
    avg_return: float = 0.0  # 百分点
    median_return: float = 0.0  # 百分点 (典型票, 免异常值)
    sample_count: int = 0
    as_of: date | None = None  # NS-5: 数据时点 (None = 未知 regime / 无数据)
    source: str = "hardcoded_fallback"  # NS-5 wiring: recomputed_json | hardcoded_fallback


# FALLBACK 常量 — 仅当 daily scheduling JSON artifact 缺失/损坏时使用 (NS-5 wiring).
# 数据来自 2026-06-24 v2 扩样本回测 (32 日期 ~189 只). 注: 此为 fallback 快照,
# 非当前真实值 — daily scheduling 重算后 crisis 已升至 53% (8000+ records, 2026-07).
# 见 ``compute_regime_winrate_summary()`` source 字段区分 recomputed_json vs fallback.
# 勿据这些 fallback 数字下结论 (loop 55 教训: _REGIME_ADVICE 写死 ~47% 与实际矛盾).
REGIME_HISTORICAL_WINRATES: dict[str, dict] = {
    "crisis": {"winrate": 0.468, "avg_return": 0.58, "median_return": -0.93, "sample_count": 119},
    "normal": {"winrate": 0.434, "avg_return": 1.31, "median_return": -4.37, "sample_count": 60},
    "risk_off": {"winrate": 0.30, "avg_return": -1.89, "median_return": -5.12, "sample_count": 10},
}


# R-5.A 多周期扩展 (2026-06-25): per-regime × per-horizon (T+5/10/15/20/25/30) 真实 median return.
# 数据源: Phase 1 commit f7965bd2 扩展 DEFAULT_HORIZONS 到 8 周期后, 从 293 条 tracking_history
# 记录 × 32 个 auto_screening 报告 (regime_gate_level) 聚合. 全 score 桶合并.
# 关键发现 (来自一次性 54 格诊断):
#   - crisis T+20/T+25 median 转正 (+0.8%/+1.5%, n>120) — 唯一跨样本稳定的正信号
#   - normal 所有 horizon median < 0 — 难以赚钱
#   - risk_off 样本小 (n=20) + T+15-T+30 显著负 — 应空仓/轻仓
# 诚实约束: 单次回测样本, 未来 daily scheduling 累积应重算; 当前硬编码避免每次拉 tushare.
REGIME_MULTIHORIZON_MEDIANS: dict[str, dict[str, dict]] = {
    "crisis": {
        "t5":  {"median": -0.3, "winrate": 0.457, "n": 173},
        "t10": {"median": -0.7, "winrate": 0.494, "n": 168},
        "t15": {"median": -0.0, "winrate": 0.500, "n": 178},
        "t20": {"median": +0.8, "winrate": 0.536, "n": 166},
        "t25": {"median": +1.5, "winrate": 0.531, "n": 177},
        "t30": {"median": -1.6, "winrate": 0.466, "n": 163},
    },
    "normal": {
        "t5":  {"median": -1.7, "winrate": 0.378, "n": 90},
        "t10": {"median": -2.6, "winrate": 0.371, "n": 89},
        "t15": {"median": -5.7, "winrate": 0.303, "n": 89},
        "t20": {"median": -5.5, "winrate": 0.382, "n": 89},
        "t25": {"median": -6.8, "winrate": 0.330, "n": 88},
        "t30": {"median": -6.0, "winrate": 0.391, "n": 87},
    },
    "risk_off": {
        "t5":  {"median": +1.6, "winrate": 0.55, "n": 20},
        "t10": {"median": -3.1, "winrate": 0.35, "n": 20},
        "t15": {"median": -8.2, "winrate": 0.20, "n": 20},
        "t20": {"median": -6.5, "winrate": 0.15, "n": 20},
        "t25": {"median": -4.9, "winrate": 0.25, "n": 20},
        "t30": {"median": -9.7, "winrate": 0.15, "n": 20},
    },
}


# regime 的产品语义提示 (loop 55: 纯定性市场特征 + 操作姿态, 不硬编码胜率/alpha 判断 —
# headline 已展示实际 winrate + CI + median, advice 里重复具体数字会随 daily
# scheduling 重算变 stale, 与 headline 矛盾. 仅保留 regime 的市场性格定性 + 操作倾向,
# 这些不随数据重算变 stale: risk_off 本质就是防御, normal 常态市本就需精选.)
_REGIME_ADVICE: dict[str, str] = {
    "crisis": "广度弱结构性行情, 少数权重股拉动指数, 选股难度高",
    "normal": "广度强常态市, 个股分化明显, 建议谨慎精选",
    "risk_off": "避险/弱势市, 系统性压力大, 建议空仓/轻仓",
}


def compute_regime_winrate_summary(
    regime: str,
    *,
    reports_dir: Path | None = None,
) -> RegimeWinrateSummary:
    """查 regime 的真实历史 T+30 表现.

    NS-5 (C234): 返回的 :class:`RegimeWinrateSummary` 含 ``as_of`` 数据时点
    (未知 regime → ``as_of=None``).

    NS-5 wiring (2026-06-30): 优先读 daily scheduling 写的
    ``regime_winrates_recomputed_*.json`` artifact, fallback 到 hardcoded
    :data:`REGIME_HISTORICAL_WINRATES` (JSON 缺失 / 损坏 / 缺该 regime).
    ``source`` 字段标注实际数据来源.

    Args:
        regime: ``regime_gate_level`` 值 (normal / crisis / risk_off)
        reports_dir: 报告目录 (含 ``regime_winrates_recomputed_*.json``).
            ``None`` → 通过 :func:`resolve_report_dir` 解析 (生产路径).
            测试可注入 ``tmp_path`` 或显式 ``Path("/nonexistent")`` 强制 fallback.

    Returns:
        :class:`RegimeWinrateSummary` (无样本/未知 regime → ``has_data=False``,
        ``as_of=None``, ``source="hardcoded_fallback"``)
    """
    key = (regime or "").strip().lower()
    if not key:
        return RegimeWinrateSummary(regime=regime or "")

    # NS-5 wiring: 优先读 fresh JSON, fallback 到 hardcoded
    payload = load_latest_regime_recompute(reports_dir=reports_dir)
    if payload is not None:
        json_winrates = payload.get("regime_winrates") or {}
        stats = json_winrates.get(key)
        if stats:
            as_of = _parse_as_of(payload.get("as_of"))
            if as_of is not None:
                return RegimeWinrateSummary(
                    regime=key,
                    has_data=True,
                    winrate=float(stats.get("winrate", 0.0)),
                    winrate_ci_low=_optional_float(stats.get("winrate_ci_low")),
                    winrate_ci_high=_optional_float(stats.get("winrate_ci_high")),
                    ci_level=float(stats.get("ci_level", 0.95)),
                    avg_return=float(stats.get("avg_return", 0.0)),
                    median_return=float(stats.get("median_return", 0.0)),
                    sample_count=int(stats.get("sample_count", 0)),
                    as_of=as_of,
                    source="recomputed_json",
                )
        # JSON 缺该 regime 或 as_of 损坏 → fall through 到 hardcoded

    # Fallback: hardcoded constants
    stats = REGIME_HISTORICAL_WINRATES.get(key)
    if not stats:
        return RegimeWinrateSummary(regime=regime or "")
    return RegimeWinrateSummary(
        regime=key,
        has_data=True,
        winrate=stats["winrate"],
        avg_return=stats["avg_return"],
        median_return=stats["median_return"],
        sample_count=stats["sample_count"],
        as_of=REGIME_HISTORICAL_DATA_AS_OF,  # NS-5: 数据时点
        source="hardcoded_fallback",
    )


# ---------------------------------------------------------------------------
# NS-5 (C234): staleness 检测 — as_of 距今 >14 天 → 数据可能过时
# ---------------------------------------------------------------------------


def is_regime_data_stale(
    as_of: date | None,
    *,
    today: date | None = None,
    threshold_days: int | None = None,
) -> bool:
    """NS-5: 判断 regime 数据是否 stale (as_of 距今 > threshold_days).

    保守语义: ``as_of=None`` (未知时点 / 无数据) → ``True`` (视为 stale).
    这避免老代码路径 (无 as_of) 静默展示过时数据.

    Args:
        as_of: 数据时点. ``None`` → 视为 stale (保守).
        today: 当前日期. ``None`` → ``date.today()`` (生产路径).
            测试可注入固定日期以避免时间漂移.
        threshold_days: staleness 阈值天数. ``None`` →
            :data:`REGIME_STALENESS_THRESHOLD_DAYS` (默认 14).

    Returns:
        ``True`` = stale (数据过时, 应重算); ``False`` = fresh.
    """
    if as_of is None:
        return True
    today = today or date.today()
    threshold = threshold_days if threshold_days is not None else REGIME_STALENESS_THRESHOLD_DAYS
    return (today - as_of).days > threshold


def _format_staleness_warning(
    as_of: date | None,
    *,
    today: date | None = None,
) -> str:
    """NS-5: 格式化 staleness 警告 (fresh → 空串, stale → ``⚠ 数据可能过时 (距今 N 天)``).

    Args:
        as_of: 数据时点. ``None`` → ``⚠ 数据无时点, 可能过时``.
        today: 当前日期. ``None`` → ``date.today()``.

    Returns:
        fresh (距今 ≤ threshold_days) → ``""``; stale → ``⚠ ...`` 字符串.
    """
    today = today or date.today()
    if as_of is None:
        return "⚠ 数据无时点, 可能过时"
    if not is_regime_data_stale(as_of, today=today):
        return ""
    days_old = (today - as_of).days
    return f"⚠ 数据可能过时 (距今 {days_old} 天, 阈值 {REGIME_STALENESS_THRESHOLD_DAYS} 天)"


def _optional_float(value: Any) -> float | None:
    """安全转 float; None/NaN/Inf → None."""
    if value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(result) or math.isinf(result):
        return None
    return result


def _format_ci_label(
    ci_low: float | None,
    ci_high: float | None,
    /,
    ci_level: float = 0.95,
) -> str:
    """Format bootstrap CI as human label, e.g. '(95% CI 38‑56%)'.

    Returns empty string when CI is unavailable.
    The *ci_level* param (default 0.95) is rendered as its integer‑percent
    form (e.g. 0.90 → '90%', 0.995 → '99.5%'). Using the exact level
    avoids the "written‑but‑never‑read" disease where a build‑time
    constant is hard‑coded in a render helper and silently diverges.
    """
    if ci_low is None or ci_high is None:
        return ""
    pct = ci_level * 100.0
    # Strip trailing ".0" so 0.95 → "95%", not "95.0%"
    if pct == int(pct):
        level_str = str(int(pct))
    else:
        # Preserve fractional part (e.g. 99.5 → "99.5")
        level_str = f"{pct:.1f}".rstrip("0").rstrip(".")
    return f" ({level_str}% CI {ci_low:.0%}-{ci_high:.0%})"


def render_regime_winrate_line(
    regime: str,
    *,
    today: date | None = None,
    reports_dir: Path | None = None,
) -> str:
    """渲染单行 regime 真实胜率提示 (无数据 → 空串).

    NS-5 (C234): 末尾追加 ``| 数据时点 YYYY-MM-DD`` + (若 stale) ``| ⚠ ...`` 提示.

    展示形如 (具体胜率/median 随数据变, 此处仅示意格式):
      ``  📊 当前市场 (crisis): 历史真实胜率 T+30: 53% (95% CI 51%-55%) | 典型 +1.7% | 样本 n=1763 | 数据时点 2026-07-02 | 广度弱结构性行情...``
    颜色随胜率: ≥50% 绿 / 30-50% 黄 / <30% 红.

    loop 57 (empirical dogfood): headline winrate 显式标注 ``T+30`` horizon.
    BUY 决策 horizon 是 T+5/T+10 (contract §北极星), headline 是 T+30 口径
    (``_compute_stats`` on next_30day_return); 不标注会让 operator 把 T+30
    胜率误读成 BUY-horizon 胜率。BUY-horizon (T+5/T+10) 胜率在
    :func:`render_regime_multihorizon_line` 单独披露。

    Args:
        regime: ``regime_gate_level`` 值.
        today: NS-5 测试注入用. ``None`` → ``date.today()`` (生产路径).
    """
    s = compute_regime_winrate_summary(regime, reports_dir=reports_dir)
    if not s.has_data:
        return ""

    if s.winrate >= 0.5:
        color = Fore.GREEN
    elif s.winrate >= 0.3:
        color = Fore.YELLOW
    else:
        color = Fore.RED

    advice = _REGIME_ADVICE.get(s.regime, "")
    ci_label = _format_ci_label(s.winrate_ci_low, s.winrate_ci_high, ci_level=s.ci_level)
    parts = [
        f"  📊 当前市场 ({s.regime}): {color}历史真实胜率 T+30: {s.winrate:.0%}{ci_label}{Style.RESET_ALL}",
        f"| 典型 {s.median_return:+.1f}%",
        f"| 平均 {s.avg_return:+.1f}%",
        f"| 样本 n={s.sample_count}",
    ]
    # NS-5: 数据时点标注
    if s.as_of is not None:
        parts.append(f"| 数据时点 {s.as_of.isoformat()}")
    if advice:
        parts.append(f"| {color}{advice}{Style.RESET_ALL}")
    # NS-5: staleness 警告
    warning = _format_staleness_warning(s.as_of, today=today)
    if warning:
        parts.append(f"| {Fore.YELLOW}{warning}{Style.RESET_ALL}")
    return " ".join(parts)


# ---------------------------------------------------------------------------
# R-5.A 多周期扩展: 按 regime 展示各 horizon 真实 median
# ---------------------------------------------------------------------------


def render_regime_multihorizon_line(
    regime: str,
    *,
    today: date | None = None,
    reports_dir: Path | None = None,
) -> str:
    """渲染一行当前 regime 的多周期 median 速览 (无数据 → 空串).

    NS-5 (C234): 末尾追加 ``| 数据时点 YYYY-MM-DD`` + (若 stale) ``| ⚠ ...`` 提示.

    NS-5 wiring (2026-06-30): 优先读 daily scheduling 写的 JSON artifact 的
    ``regime_multihorizon_medians``, fallback 到 hardcoded
    :data:`REGIME_MULTIHORIZON_MEDIANS`. as_of 跟随数据源 (JSON as_of 或
    hardcoded :data:`REGIME_HISTORICAL_DATA_AS_OF`).

    展示形如:
      ``  📊 多周期期望 (crisis): T+15 0.0% | T+20 +0.8% | T+25 +1.5% | T+30 -1.6% (n=163+) | 数据时点 2026-06-25 | ⚠ ...``

    颜色逻辑:
      - 有 horizon median > 0 → 绿色 (展示甜区)
      - 所有 median < 0 → 黄色 (谨慎, 所有周期都亏)
      - 未知 / 无数据 → 空串

    仅展示 T+15/T+20/T+25/T+30 (中长周期), T+5/T+10 噪声大略过.

    Args:
        regime: ``regime_gate_level`` 值.
        today: NS-5 测试注入用. ``None`` → ``date.today()`` (生产路径).
        reports_dir: 报告目录. ``None`` → ``resolve_report_dir`` (生产路径).
            测试可注入 ``tmp_path`` 或显式 ``Path("/nonexistent")`` 强制 fallback.
    """
    key = (regime or "").strip().lower()
    if not key:
        return ""

    # NS-5 wiring: 优先读 fresh JSON, fallback 到 hardcoded
    as_of = REGIME_HISTORICAL_DATA_AS_OF
    data: dict[str, dict[str, Any]] | None = None

    payload = load_latest_regime_recompute(reports_dir=reports_dir)
    if payload is not None:
        json_medians = payload.get("regime_multihorizon_medians") or {}
        candidate = json_medians.get(key)
        if candidate:
            json_as_of = _parse_as_of(payload.get("as_of"))
            if json_as_of is not None:
                data = candidate
                as_of = json_as_of

    if data is None:
        data = REGIME_MULTIHORIZON_MEDIANS.get(key)

    if not data:
        return ""

    # 仅展示 T+15-T+30 (中长周期), T+5/T+10 短期噪声大
    display_horizons = [
        ("t15", "T+15"), ("t20", "T+20"), ("t25", "T+25"), ("t30", "T+30"),
    ]

    parts: list[str] = []
    has_positive = False
    max_n = 0
    for h, label in display_horizons:
        h_data = data.get(h)
        if h_data is None:
            continue
        med = h_data["median"]
        n = h_data["n"]
        if n > max_n:
            max_n = n
        sign = "+" if med >= 0 else ""
        parts.append(f"{label} {sign}{med:.1f}%")
        if med > 0:
            has_positive = True

    if not parts:
        return ""

    if has_positive:
        color = Fore.GREEN
    else:
        color = Fore.YELLOW

    # 用最小 n (T+30) 作为样本提示，诚实披露
    min_n = min(data[h]["n"] for h, _ in display_horizons if h in data)
    horizon_parts = " | ".join(parts)
    out = f"  📊 多周期期望 ({key}): {color}{horizon_parts}{Style.RESET_ALL} (n={min_n}+)"

    # loop 57 (empirical dogfood): 披露 BUY-horizon (T+5/T+10) 胜率 + CI.
    # 这些字段由 ``_compute_multihorizon_stats`` 写入 JSON, 但此前 render 不读
    # (loop-53 'written but never read' disease). contract §北极星 BUY 决策
    # horizon = T+5/T+10, 但 headline 胜率是 T+30 口径 — 必须单独让 BUY-horizon
    # 胜率可见, 否则 owner 的 F2 north-star (T+5/T+10 winrate > 50%) 是盲的.
    buy_horizons = [("t5", "T+5"), ("t10", "T+10")]
    buy_parts: list[str] = []
    for h, label in buy_horizons:
        h_data = data.get(h)
        if not isinstance(h_data, dict):
            continue
        wr = _optional_float(h_data.get("winrate"))
        if wr is None:
            continue
        ci_lo = _optional_float(h_data.get("winrate_ci_low"))
        ci_hi = _optional_float(h_data.get("winrate_ci_high"))
        h_ci_level = _optional_float(h_data.get("ci_level")) or 0.95
        ci = _format_ci_label(ci_lo, ci_hi, ci_level=h_ci_level)
        buy_parts.append(f"{label} 胜率 {wr:.0%}{ci}")
    if buy_parts:
        out += f" | BUY 周期胜率: {color}{' / '.join(buy_parts)}{Style.RESET_ALL}"

    # NS-5: 数据时点 + staleness 警告
    out += f" | 数据时点 {as_of.isoformat()}"
    warning = _format_staleness_warning(as_of, today=today)
    if warning:
        out += f" | {Fore.YELLOW}{warning}{Style.RESET_ALL}"
    return out


# ---------------------------------------------------------------------------
# NS-5 wiring (2026-06-30): loader — 找最新 regime_winrates_recomputed_*.json
# ---------------------------------------------------------------------------


def _parse_as_of(value: Any) -> date | None:
    """安全解析 ISO 日期字符串 (``YYYY-MM-DD`` → :class:`date`).

    ``None`` / 空串 / 非法格式 → ``None`` (让 caller fallback).
    """
    if not value:
        return None
    try:
        return date.fromisoformat(str(value))
    except (ValueError, TypeError):
        return None


def load_latest_regime_recompute(
    reports_dir: Path | None = None,
) -> dict[str, Any] | None:
    """NS-5 wiring: 找最新 ``regime_winrates_recomputed_*.json`` 并解析.

    daily scheduling (``run_daily_regime_refresh``) 每天写一个带日期后缀的
    JSON artifact, 本函数按文件名日期后缀排序选最新.

    Args:
        reports_dir: 报告目录. ``None`` → 通过
            :func:`consecutive_recommendation.resolve_report_dir` 解析 (生产路径).
            测试可注入 ``tmp_path`` 或 ``Path("/nonexistent")`` 强制 None.

    Returns:
        解析后的 dict (含 ``regime_winrates`` / ``regime_multihorizon_medians`` /
        ``as_of`` 等字段), 或 ``None``:

            - 目录不存在 → ``None``
            - 无匹配 artifact → ``None``
            - JSON 损坏 → ``None`` (并 log warning)
    """
    if reports_dir is None:
        # 延迟导入避免循环依赖
        from src.screening.consecutive_recommendation import resolve_report_dir

        reports_dir = resolve_report_dir()

    if not reports_dir.exists():
        return None

    # glob + 按文件名排序 (文件名含 YYYYMMDD 后缀, 字典序 = 日期序)
    candidates = sorted(reports_dir.glob("regime_winrates_recomputed_*.json"))
    if not candidates:
        return None

    latest = candidates[-1]
    try:
        payload = json.loads(latest.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning(
            "regime_winrate.load_latest_regime_recompute: 损坏 artifact %s: %s",
            latest.name,
            exc,
        )
        return None

    if not isinstance(payload, dict):
        logger.warning(
            "regime_winrate.load_latest_regime_recompute: artifact %s 顶层非 dict",
            latest.name,
        )
        return None

    return payload


__all__ = [
    "RegimeWinrateSummary",
    "REGIME_HISTORICAL_WINRATES",
    "REGIME_MULTIHORIZON_MEDIANS",
    "REGIME_HISTORICAL_DATA_AS_OF",
    "REGIME_STALENESS_THRESHOLD_DAYS",
    "compute_regime_winrate_summary",
    "is_regime_data_stale",
    "load_latest_regime_recompute",
    "render_regime_winrate_line",
    "render_regime_multihorizon_line",
]
