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
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from src.screening.consecutive_recommendation import resolve_report_dir
from src.screening.custom_weights import STRATEGY_KEYS
from colorama import Fore, Style
from src.utils.numeric import safe_float as _safe_float

logger = logging.getLogger(__name__)

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
    """定位 ``report_dir`` 下最新的 ``auto_screening_YYYYMMDD.json``。

    文件名日期校验对齐 R54 的 ``_load_auto_screening_reports``：纯字母排序会把
    非数字开头的 malformed 文件名（如 ``auto_screening_garbage.json``，字母在
    ASCII 数字之后）排到合法日期之前，误选为"最新"。校验 stem 能解析为
    ``%Y%m%d`` 后再排序，确保只从合法日期文件里选最新。

    R89 cross-surface: 优选出落于开市 A 股交易日的报告。pre-fix legacy 或未来
    regression 可能留下周六/周日日期的报告（文件名更新，排序更靠前），但
    ``--daily-action`` 把信号日归一到最近开市日；本 finder 被 top_picks /
    run_top / daily-action fallback / DQ block 共用，须跳过周末伪交易日报告
    以保持跨 surface 一致（2026-07-12 实跑：daily-brief 展示 07-11 周六 vs
    daily-action 07-10 周五）。全部报告都非开市日时，降级返回最新（让上层
    stale 披露处理）。
    """
    from src.utils.date_utils import latest_open_trade_date_on_or_before

    search_dir = report_dir or resolve_report_dir()
    candidates = [path for path in search_dir.glob("auto_screening_*.json") if _parses_as_report_date(path.stem.replace("auto_screening_", ""))]
    candidates.sort(reverse=True)
    # R89: 从新到旧返回第一个落于开市交易日的报告（== 自身即开市日）。
    for path in candidates:
        date_str = path.stem.replace("auto_screening_", "")
        if latest_open_trade_date_on_or_before(date_str) == date_str:
            return path
    return candidates[0] if candidates else None


def _parses_as_report_date(date_str: str) -> bool:
    """R54 同族：文件名 stem 必须能解析为 ``%Y%m%d`` 才算合法报告日期。"""
    try:
        datetime.strptime(date_str, "%Y%m%d")
        return True
    except ValueError:
        return False


def load_latest_recommendations(report_dir: Path | None = None) -> tuple[str, list[dict[str, Any]]]:
    """加载最新报告的日期 + recommendations 列表。

    返回 ``(date_str, recs)``; 无报告或报告损坏时 ``(date_str, [])``。

    R88 drain (BH-017 family): 最新报告可能因部分写入 / 磁盘错误而损坏。此前裸
    ``json.load`` 抛 JSONDecodeError 中断整个数据质量审计 CLI。现在 catch 解析错误,
    发 warning 诊断, 返回空 recs 让审计继续 (与 sibling ``daily_brief._load_report``
    的 graceful contract 一致)。
    """
    path = _find_latest_report(report_dir)
    if path is None:
        return ("", [])
    try:
        with path.open(encoding="utf-8") as f:
            payload = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning(
            "data_quality_audit: 最新报告 %s 损坏 (部分写入/磁盘错误?): %s; 返回空 recs",
            path,
            exc,
        )
        return ("", [])
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
    weighted = sum(_strategy_completeness(strategy_signals, s) * weights.get(s, 0.0) for s in STRATEGY_ORDER)
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
        # NS-13 family drain: NaN score_b 经 `float(x or 0.0)` 仍 truthy 不兜底,
        # 写入 audit 记录为 NaN, 污染下游消费 (conviction_ranking 等虽已 guard,
        # 但 audit 记录本身应不含 NaN). 用 safe_float 源头拒绝.
        "score_b": _safe_float(rec.get("score_b"), 0.0),
        "per_strategy_completeness": per_strategy,
        "composite_completeness": composite,
        "weak_strategies": weak,
        "is_low_quality": composite < threshold,
    }


def audit_recommendations(recs: list[dict[str, Any]], threshold: float = DEFAULT_QUALITY_THRESHOLD, top_n: int | None = None) -> list[dict[str, Any]]:
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


def render_audit_report(audits: list[dict[str, Any]], date_str: str, threshold: float = DEFAULT_QUALITY_THRESHOLD) -> str:
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
        line = f"{a['ticker']:<8} {name:<14} " f"{bar} {comp:.0%}    " f"{strategy_bars[0]}   {strategy_bars[1]}   {strategy_bars[2]}   {strategy_bars[3]}   " f"{status}"
        lines.append(line)

    # 摘要
    total = len(audits)
    low_count = sum(1 for a in audits if a["is_low_quality"])
    avg_comp = sum(a["composite_completeness"] for a in audits) / total if total else 0.0
    lines.append("─" * 110)
    summary_color = Fore.RED if low_count > total / 2 else (Fore.YELLOW if low_count > 0 else Fore.GREEN)
    lines.append(f"{summary_color}摘要: {total} 只推荐 | 平均完整性 {avg_comp:.0%} | " f"低质量 {low_count} 只 ({low_count / total:.0%}){Style.RESET_ALL}")

    if low_count > 0:
        lines.append(f"\n{Fore.YELLOW}提示: 以下推荐基于不完整数据, 建议结合 --why-not 复查:{Style.RESET_ALL}")
        for a in audits:
            if a["is_low_quality"]:
                weak = ", ".join(STRATEGY_LABEL[s] for s in a["weak_strategies"]) or "—"
                lines.append(f"  • {a['ticker']} {a['name']}: 弱策略 [{weak}] completeness={a['composite_completeness']:.0%}")

    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# R-2 数据完整度门控 — run-level data-quality summary on the front door
# ---------------------------------------------------------------------------


@dataclass
class DataQualitySummary:
    """聚合数据完整度摘要 (供前门单行展示)。

    基于 :func:`audit_recommendations` 的逐 pick 审计结果聚合:
    平均综合完整度、低质量 pick 数、各策略平均是否就绪。
    """

    has_data: bool = False
    pick_count: int = 0
    avg_completeness: float = 0.0
    low_quality_count: int = 0
    strategy_ready_count: int = 0
    #: 各策略平均完整度 ≥ 阈值即视为该策略「就绪」, 对应前门 "N/M 策略就绪"
    strategy_total: int = field(default_factory=lambda: len(STRATEGY_ORDER))
    #: loop 83 (asymmetric-staleness drain): YYYYMMDD, 最新报告日期 (None → 不 stamp)
    latest_report_date: str | None = None


def summarize_data_quality(audits: list[dict[str, Any]], threshold: float = DEFAULT_QUALITY_THRESHOLD) -> DataQualitySummary:
    """聚合逐 pick 审计结果为 run-level 数据完整度摘要。

    Args:
        audits: :func:`audit_recommendations` 返回的逐 pick 审计列表
        threshold: composite completeness 低于此值计为低质量; 同阈值用于策略就绪判定

    Returns:
        :class:`DataQualitySummary` (空 audits → ``has_data=False``)
    """
    if not audits:
        return DataQualitySummary()

    pick_count = len(audits)
    avg_completeness = sum(a["composite_completeness"] for a in audits) / pick_count
    low_quality_count = sum(1 for a in audits if a["is_low_quality"])

    # Per-strategy readiness: a strategy is "ready" when its average completeness
    # across picks is at least the threshold (uses the same line as the audit).
    strategy_ready_count = 0
    for s in STRATEGY_ORDER:
        per_values = [a["per_strategy_completeness"].get(s, 0.0) for a in audits]
        if per_values and (sum(per_values) / len(per_values)) >= threshold:
            strategy_ready_count += 1

    return DataQualitySummary(
        has_data=True,
        pick_count=pick_count,
        avg_completeness=avg_completeness,
        low_quality_count=low_quality_count,
        strategy_ready_count=strategy_ready_count,
    )


def render_data_quality_summary(summary: DataQualitySummary) -> str:
    """渲染单行数据完整度摘要 (无数据 → 空串)。

    展示形如: ``  📊 数据完整度: 75%  (3/4 策略就绪)  ⚠ 1 只推荐基于部分数据``

    loop 83 (asymmetric-staleness drain): 末尾追加 ``| 数据时点 YYYY-MM-DD``
    mirroring the 10 sibling footer blocks. 完整度读自最新 auto_screening_*.json
    (stale-prone); 无 stamp 时一个 stale 的 "100% complete" 绿标会虚假地让
    operator 相信今日推荐基于完整数据。
    """
    if not summary.has_data:
        return ""

    total = summary.strategy_total
    ready = summary.strategy_ready_count
    avg = summary.avg_completeness

    # 颜色随平均完整度: ≥0.8 绿 / ≥0.6 黄 / 其余红 (与 _completeness_bar 一致)
    if avg >= 0.8:
        color = Fore.GREEN
    elif avg >= 0.6:
        color = Fore.YELLOW
    else:
        color = Fore.RED

    parts = [f"  📊 数据完整度: {color}{avg:.0%}{Style.RESET_ALL}  ({ready}/{total} 策略就绪)"]
    if summary.low_quality_count > 0:
        parts.append(f"  {Fore.YELLOW}⚠ {summary.low_quality_count} 只推荐基于部分数据{Style.RESET_ALL}")
    body = " ".join(parts)
    return body + _format_as_of_stamp(summary.latest_report_date)


def _format_as_of_stamp(latest_report_date: str | None) -> str:
    """Render `` | 数据时点 YYYY-MM-DD`` from a YYYYMMDD string (None → "")."""
    if not latest_report_date:
        return ""
    try:
        iso = datetime.strptime(str(latest_report_date), "%Y%m%d").date().isoformat()
        return f" {Fore.WHITE}| 数据时点 {iso}{Style.RESET_ALL}"
    except ValueError:
        return ""


# ---------------------------------------------------------------------------
# CLI entry
# ---------------------------------------------------------------------------


def run_data_quality_audit(top_n: int = 10, threshold: float = DEFAULT_QUALITY_THRESHOLD, report_dir: Path | None = None) -> int:
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
    "DataQualitySummary",
    "summarize_data_quality",
    "render_data_quality_summary",
]
