"""R-5.A 按 regime 展示真实历史胜率 / regime-aware win-rate disclosure.

v2 扩样本回测 (2026-06-24, 32 日期 ~189 只真实推荐, tushare 真实 T+30) 结论:
三 regime 胜率接近 (crisis 47% / normal 43% / risk_off 30%), 典型票 (median) 都微亏
到平 — **没有哪个 regime 明显赚钱** (推翻了早期小样本 "crisis 73% 赚钱" 的偏差结论)。
regime 差异主要体现在 risk_off 略差 (30% vs 43-47%)。

R-5.A 是**零行为改变**的诚实披露: 不碰 gate / 不碰仓位, 只在 --top-picks footer
按当前 regime 展示真实历史胜率, 让用户看到当前期望自己决定。这是赚钱工具的
诚实基础, 也是持续累积真实数据验证假设的基础设施。

数据源: ``REGIME_HISTORICAL_WINRATES`` 内嵌真实回测结果 (v2 扩充版, 32 日期 ~189 只;
随 daily scheduling 累积应定期重算; 后续可从 tracking_history 动态算, 当前硬编码
避免每跑一次就拉 tushare 或依赖本地 tracking_history 存在)。

NS-5 (C234, 2026-06-28): 加 ``as_of`` 数据时点标注 + staleness 检测.
C220 BUY gate horizon T+30→T+5/T+10 后, 当前 T+30 硬编码数据已 stale (距 owner
改因子已 ≥4 天, 距 C220 release 已 0 天). 重算需新模型累积 ≥10 交易日 mature 数据
(post-push observation trigger 2026-07-12); 当前只做诚实披露 (as_of + ⚠ staleness
warning), 不假装重算. daily scheduling 重算脚本待数据 mature 后再加 (避免 dead code).

Staleness 阈值 ``REGIME_STALENESS_THRESHOLD_DAYS=14``: regime winrate 是中频更新数据
(不像 ticker price 高频), 14 天兼顾 (a) 不频繁误报 (daily 调度噪声) + (b) 不放过
真正过时 (owner 改因子后 ≥2 周还没重算就是问题).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from src.utils.display import Fore, Style


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
    """

    regime: str
    has_data: bool = False
    winrate: float = 0.0  # 0-1, T+30 正收益比例
    avg_return: float = 0.0  # 百分点
    median_return: float = 0.0  # 百分点 (典型票, 免异常值)
    sample_count: int = 0
    as_of: date | None = None  # NS-5: 数据时点 (None = 未知 regime / 无数据)


# 真实回测结果 (2026-06-24, 扩充至 32 日期 ~189 只真实推荐, tushare 真实 T+30)。
# 扩样本后结论: 三 regime 胜率接近 (normal 43% / crisis 47% / risk_off 30%),
# 典型票 (median) 都微亏到平 — 没有哪个 regime 明显赚钱 (推翻了早期小样本
# "crisis 73% 赚钱" 的偏差结论)。regime 差异主要体现在 risk_off 略差。
# 随 daily scheduling 累积应定期重算 (v2 扩充版, 替代 v1 91 只小样本)。
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


# regime 的产品语义提示 (基于扩充后真实回测: 三 regime 胜率都 30-47%, 典型票微亏)
_REGIME_ADVICE: dict[str, str] = {
    "crisis": "广度弱结构性行情, 历史胜率 ~47%, 典型票微亏 (扩样本后无显著 alpha)",
    "normal": "广度强常态市, 历史胜率 ~43%, 典型票微亏, 建议谨慎",
    "risk_off": "避险/弱势市, 历史胜率仅 ~30%, 典型票 -5%, 建议空仓/轻仓",
}


def compute_regime_winrate_summary(regime: str) -> RegimeWinrateSummary:
    """查 regime 的真实历史 T+30 表现.

    NS-5 (C234): 返回的 :class:`RegimeWinrateSummary` 含 ``as_of`` 数据时点
    (未知 regime → ``as_of=None``).

    Args:
        regime: ``regime_gate_level`` 值 (normal / crisis / risk_off)

    Returns:
        :class:`RegimeWinrateSummary` (无样本/未知 regime → ``has_data=False``,
        ``as_of=None``)
    """
    key = (regime or "").strip().lower()
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


def render_regime_winrate_line(regime: str, *, today: date | None = None) -> str:
    """渲染单行 regime 真实胜率提示 (无数据 → 空串).

    NS-5 (C234): 末尾追加 ``| 数据时点 YYYY-MM-DD`` + (若 stale) ``| ⚠ ...`` 提示.

    展示形如:
      ``  📊 当前市场 (crisis): 历史真实胜率 47% | 典型 -0.9% | 样本 n=119 | 数据时点 2026-06-25 | ⚠ 数据可能过时 (距今 21 天, 阈值 14 天)``
    颜色随胜率: ≥50% 绿 / 30-50% 黄 / <30% 红.

    Args:
        regime: ``regime_gate_level`` 值.
        today: NS-5 测试注入用. ``None`` → ``date.today()`` (生产路径).
    """
    s = compute_regime_winrate_summary(regime)
    if not s.has_data:
        return ""

    if s.winrate >= 0.5:
        color = Fore.GREEN
    elif s.winrate >= 0.3:
        color = Fore.YELLOW
    else:
        color = Fore.RED

    advice = _REGIME_ADVICE.get(s.regime, "")
    parts = [
        f"  📊 当前市场 ({s.regime}): {color}历史真实胜率 {s.winrate:.0%}{Style.RESET_ALL}",
        f"| 典型 {s.median_return:+.1f}%",
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


def render_regime_multihorizon_line(regime: str, *, today: date | None = None) -> str:
    """渲染一行当前 regime 的多周期 median 速览 (无数据 → 空串).

    NS-5 (C234): 末尾追加 ``| 数据时点 YYYY-MM-DD`` + (若 stale) ``| ⚠ ...`` 提示.

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
    """
    key = (regime or "").strip().lower()
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

    # NS-5: 数据时点 + staleness 警告
    as_of = REGIME_HISTORICAL_DATA_AS_OF
    out += f" | 数据时点 {as_of.isoformat()}"
    warning = _format_staleness_warning(as_of, today=today)
    if warning:
        out += f" | {Fore.YELLOW}{warning}{Style.RESET_ALL}"
    return out


__all__ = [
    "RegimeWinrateSummary",
    "REGIME_HISTORICAL_WINRATES",
    "REGIME_MULTIHORIZON_MEDIANS",
    "REGIME_HISTORICAL_DATA_AS_OF",
    "REGIME_STALENESS_THRESHOLD_DAYS",
    "compute_regime_winrate_summary",
    "is_regime_data_stale",
    "render_regime_winrate_line",
    "render_regime_multihorizon_line",
]
