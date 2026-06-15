"""数据质量审计 (`--data-quality-audit`) — P0-10.

读取最新的 ``auto_screening_*.json`` 推荐报告, 对 Top N 推荐标的的数据完整性
进行审计, 让用户在依赖推荐前能识别"推荐基于不完整数据"的情况。

R20.17 的直接动机: 修复了 ``completeness or 1.0`` 静默覆盖 bug 后, 用户需要
一个显式入口看到每个推荐的真实数据质量, 而不是依赖隐式假设。

输出三层数据:
1. 每个策略 (trend/mean_reversion/fundamental/event_sentiment) 的 completeness
2. 推荐标的的综合 completeness (四策略加权平均)
3. 低质量告警 (completeness < 0.6 的策略会标注 ⚠️)

CLI:
    python src/main.py --data-quality-audit [--top-n=10] [--threshold=0.6]
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.screening.consecutive_recommendation import resolve_report_dir
# Canonical 4-strategy key order — single source of truth (see custom_weights).
from src.screening.custom_weights import STRATEGY_KEYS
from src.utils.display import Fore, Style

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Backwards-compatible alias for the public name; STRATEGY_KEYS is canonical.
STRATEGY_ORDER: tuple[str, ...] = STRATEGY_KEYS
STRATEGY_LABEL: dict[str, str] = {
    "trend": "趋势",
    "mean_reversion": "均值回归",
    "fundamental": "基本面",
    "event_sentiment": "事件情绪",
}
DEFAULT_QUALITY_THRESHOLD: float = 0.6
DEFAULT_WEIGHTS: dict[str, float] = {
    "trend": 0.30,
    "mean_reversion": 0.20,
    "fundamental": 0.30,
    "event_sentiment": 0.20,
}


# ---------------------------------------------------------------------------
# Report loading
# ---------------------------------------------------------------------------


def _find_latest_report(report_dir: Path | None = None) -> Path | None:
    """定位 ``report_dir`` 下最新的 ``auto_screening_YYYYMMDD.json``。"""
    search_dir = report_dir or resolve_report_dir()
    candidates = sorted(search_dir.glob("auto_screening_*.json"), reverse=True)
    return candidates[0] if candidates else None


def load_latest_recommendations(report_dir: Path | None = None) -> tuple[str, list[dict[str, Any]]]:
    """加载最新报告的日期 + recommendations 列表。

    返回 ``(date_str, recs)``; 无报告时 ``(date_str, [])``。
    """
    path = _find_latest_report(report_dir)
    if path is None:
        return ("", [])
    with path.open(encoding="utf-8") as f:
        payload = json.load(f)
    recs = list(payload.get("recommendations") or [])
    date_str = str(payload.get("date") or "")
    return (date_str, recs)


# ---------------------------------------------------------------------------
# Audit logic
# ---------------------------------------------------------------------------


def _strategy_completeness(strategy_signals: dict[str, Any], strategy: str) -> float:
    """安全读取某策略的 completeness, 缺失返回 0.0。

    NOTE: 0.0 是合法"无数据"语义, 这里直接采用 — 不做 ``or 1.0`` 静默覆盖
    (那是 R20.17 修复的 bug 模式)。
    """
    block = strategy_signals.get(strategy) or {}
    value = block.get("completeness")
    return float(value) if value is not None else 0.0


def compute_composite_completeness(strategy_signals: dict[str, Any], weights: dict[str, float] | None = None) -> float:
    """按权重加权四策略 completeness 得到综合分 (0.0-1.0)。

    缺失策略视为 completeness=0.0; 权重归一化后计算。
    """
    weights = weights or DEFAULT_WEIGHTS
    total_weight = sum(weights.get(s, 0.0) for s in STRATEGY_ORDER)
    if total_weight <= 0.0:
        return 0.0
    weighted = sum(
        _strategy_completeness(strategy_signals, s) * weights.get(s, 0.0)
        for s in STRATEGY_ORDER
    )
    return round(weighted / total_weight, 4)


def audit_recommendation(rec: dict[str, Any], threshold: float = DEFAULT_QUALITY_THRESHOLD) -> dict[str, Any]:
    """计算单个推荐的审计结果。

    返回 dict 含:
    - ticker / name
    - per_strategy_completeness: {策略: completeness}
    - composite_completeness: 加权综合
    - weak_strategies: completeness < threshold 的策略列表
    - is_low_quality: composite < threshold
    """
    strategy_signals = dict(rec.get("strategy_signals") or {})
    per_strategy = {s: _strategy_completeness(strategy_signals, s) for s in STRATEGY_ORDER}
    composite = compute_composite_completeness(strategy_signals)
    weak = [s for s in STRATEGY_ORDER if per_strategy[s] < threshold]
    return {
        "ticker": str(rec.get("ticker") or ""),
        "name": str(rec.get("name") or ""),
        "industry_sw": str(rec.get("industry_sw") or ""),
        "score_b": float(rec.get("score_b") or 0.0),
        "per_strategy_completeness": per_strategy,
        "composite_completeness": composite,
        "weak_strategies": weak,
        "is_low_quality": composite < threshold,
    }


def audit_recommendations(
    recs: list[dict[str, Any]], threshold: float = DEFAULT_QUALITY_THRESHOLD, top_n: int | None = None
) -> list[dict[str, Any]]:
    """审计 Top N 推荐, 返回审计结果列表 (按 composite_completeness 升序)。"""
    if top_n is not None and top_n > 0:
        recs = recs[:top_n]
    results = [audit_recommendation(rec, threshold=threshold) for rec in recs]
    results.sort(key=lambda r: r["composite_completeness"])
    return results


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _completeness_bar(value: float, width: int = 10) -> str:
    """0.0-1.0 → 10 格 ASCII 进度条 (满/中/空 三态着色)。"""
    filled = max(0, min(width, int(round(value * width))))
    bar = "█" * filled + "░" * (width - filled)
    if value >= 0.8:
        color = Fore.GREEN
    elif value >= 0.6:
        color = Fore.YELLOW
    else:
        color = Fore.RED
    return f"{color}{bar}{Style.RESET_ALL}"


def render_audit_report(
    audits: list[dict[str, Any]], date_str: str, threshold: float = DEFAULT_QUALITY_THRESHOLD
) -> str:
    """渲染审计结果为 markdown + ANSI 着色字符串。"""
    if not audits:
        return f"{Fore.YELLOW}未找到推荐数据 — 请先运行 `--auto` 生成报告。{Style.RESET_ALL}\n"

    lines: list[str] = []
    lines.append(f"\n{Fore.CYAN}{Style.BRIGHT}═══ 数据质量审计 (date={date_str or '未知'}) ═══{Style.RESET_ALL}")
    lines.append(f"{Fore.CYAN}质量阈值: completeness < {threshold:.2f} 标记为 ⚠️ 低质量{Style.RESET_ALL}\n")

    # 表头
    header = f"{Fore.CYAN}{'Ticker':<8} {'名称':<14} {'综合完整性':<14} {'趋势':<10} {'均值回归':<10} {'基本面':<10} {'事件情绪':<10} 状态{Style.RESET_ALL}"
    lines.append(header)
    lines.append("─" * 110)

    for a in audits:
        comp = a["composite_completeness"]
        bar = _completeness_bar(comp)
        per = a["per_strategy_completeness"]

        # 各策略的 mini bar (5 格)
        strategy_bars = []
        for s in STRATEGY_ORDER:
            v = per.get(s, 0.0)
            mini = _completeness_bar(v, width=5)
            strategy_bars.append(mini)

        status = f"{Fore.RED}⚠️ 低质量{Style.RESET_ALL}" if a["is_low_quality"] else f"{Fore.GREEN}✓ 良好{Style.RESET_ALL}"
        name = a["name"][:12] if a["name"] else "—"
        line = (
            f"{a['ticker']:<8} {name:<14} "
            f"{bar} {comp:.0%}    "
            f"{strategy_bars[0]}   {strategy_bars[1]}   {strategy_bars[2]}   {strategy_bars[3]}   "
            f"{status}"
        )
        lines.append(line)

    # 摘要
    total = len(audits)
    low_count = sum(1 for a in audits if a["is_low_quality"])
    avg_comp = sum(a["composite_completeness"] for a in audits) / total if total else 0.0
    lines.append("─" * 110)
    summary_color = Fore.RED if low_count > total / 2 else (Fore.YELLOW if low_count > 0 else Fore.GREEN)
    lines.append(
        f"{summary_color}摘要: {total} 只推荐 | 平均完整性 {avg_comp:.0%} | "
        f"低质量 {low_count} 只 ({low_count / total:.0%}){Style.RESET_ALL}"
    )

    if low_count > 0:
        lines.append(f"\n{Fore.YELLOW}提示: 以下推荐基于不完整数据, 建议结合 --why-not 复查:{Style.RESET_ALL}")
        for a in audits:
            if a["is_low_quality"]:
                weak = ", ".join(STRATEGY_LABEL[s] for s in a["weak_strategies"]) or "—"
                lines.append(f"  • {a['ticker']} {a['name']}: 弱策略 [{weak}] completeness={a['composite_completeness']:.0%}")

    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI entry
# ---------------------------------------------------------------------------


def run_data_quality_audit(
    top_n: int = 10, threshold: float = DEFAULT_QUALITY_THRESHOLD, report_dir: Path | None = None
) -> int:
    """CLI 入口: 加载最新报告 → 审计 Top N → 渲染 → 打印。"""
    date_str, recs = load_latest_recommendations(report_dir=report_dir)
    audits = audit_recommendations(recs, threshold=threshold, top_n=top_n)
    print(render_audit_report(audits, date_str=date_str, threshold=threshold))
    return 0


__all__ = [
    "STRATEGY_ORDER",
    "DEFAULT_QUALITY_THRESHOLD",
    "load_latest_recommendations",
    "compute_composite_completeness",
    "audit_recommendation",
    "audit_recommendations",
    "render_audit_report",
    "run_data_quality_audit",
]
