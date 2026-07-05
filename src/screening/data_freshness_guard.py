"""数据新鲜度守门员 (Data Freshness Guard) — P6-1.

在 ``--auto`` 运行时自动检测关键数据源的时效性:
- 行情数据 (daily prices)
- 财务数据 (financial metrics)
- 行业分类 (industry classification)

如果数据过期, 在报告中生成新鲜度警告并降低受影响标的的置信度。

CLI:
    python src/main.py --auto --check-freshness

集成到 ``--auto`` 流程:
    ``run_auto_screening()`` 自动调用 ``check_data_freshness()``,
    结果附加到报告顶层 ``data_freshness`` 字段。
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from src.utils.display import Fore, Style

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_FRESHNESS_CONFIG: dict[str, dict[str, Any]] = {
    "daily_prices": {
        "label": "行情数据",
        "max_stale_days": 1,
        "severity": "HIGH",
    },
    "financial_metrics": {
        "label": "财务数据",
        "max_stale_days": 5,
        "severity": "MEDIUM",
    },
    "industry_classification": {
        "label": "行业分类",
        "max_stale_days": 30,
        "severity": "LOW",
    },
}


# ---------------------------------------------------------------------------
# Core freshness check
# ---------------------------------------------------------------------------


def check_data_freshness(
    *,
    trade_date: str,
    reports_dir: Path | None = None,
    cache_path: Path | None = None,
) -> dict[str, Any]:
    """检查关键数据源的新鲜度。

    Args:
        trade_date: 交易日 (YYYYMMDD 或 YYYY-MM-DD)
        reports_dir: 报告目录 (用于检查快照时间戳)
        cache_path: 缓存数据库路径 (用于检查缓存最新日期)

    Returns:
        新鲜度报告 dict, 含 ``fresh`` (bool), ``warnings`` (list), ``summary`` (str)
    """
    normalized_date = _normalize_date(trade_date)
    warnings: list[dict[str, Any]] = []
    all_fresh = True

    # Check cache freshness
    cache_freshness = _check_cache_freshness(normalized_date, cache_path)
    if cache_freshness:
        for source_name, details in cache_freshness.items():
            config = _FRESHNESS_CONFIG.get(source_name, {})
            # R118 / 新鲜度门正确性: 单源查询失败 (schema drift / locked DB) 时
            # _check_cache_freshness 标记 ``{"unknown": True}``。历史代码缺失源
            # 不进 result → check_data_freshness 只迭代存在的源 → all_fresh 保持
            # True → 误报 fresh=True 跳过 apply_freshness_confidence_penalty 的
            # 过期数据置信度惩罚, 数据安全门被绕过。改为: unknown 源保守判 not-fresh。
            if details.get("unknown"):
                all_fresh = False
                warnings.append(
                    {
                        "source": source_name,
                        "label": config.get("label", source_name),
                        "latest_date": "unknown",
                        "stale_days": None,
                        "max_stale_days": config.get("max_stale_days", 1),
                        "severity": "UNKNOWN",
                        "message": "freshness query failed (schema drift / locked DB); cannot verify freshness",
                    }
                )
                continue
            max_stale = int(config.get("max_stale_days", 1))
            if details.get("stale_days", 0) > max_stale:
                all_fresh = False
                warnings.append(
                    {
                        "source": source_name,
                        "label": config.get("label", source_name),
                        "latest_date": details.get("latest_date", "unknown"),
                        "stale_days": details.get("stale_days", 0),
                        "max_stale_days": max_stale,
                        "severity": config.get("severity", "MEDIUM"),
                    }
                )

    # Check report timestamp freshness
    if reports_dir is not None:
        report_freshness = _check_report_freshness(normalized_date, reports_dir)
        if not report_freshness.get("fresh", True):
            all_fresh = False
            warnings.append(report_freshness.get("warning", {}))

    summary = _render_freshness_summary(all_fresh, warnings)

    return {
        "fresh": all_fresh,
        "trade_date": normalized_date,
        "warnings": warnings,
        "warning_count": len(warnings),
        "summary": summary,
    }


def apply_freshness_confidence_penalty(
    recommendations: list[dict[str, Any]],
    freshness_report: dict[str, Any],
) -> list[dict[str, Any]]:
    """对基于过期数据的推荐施加置信度惩罚。

    HIGH severity 警告 → confidence *= 0.7
    MEDIUM severity 警告 → confidence *= 0.85
    LOW severity 警告 → confidence *= 0.95

    Args:
        recommendations: 推荐列表
        freshness_report: ``check_data_freshness()`` 的输出

    Returns:
        修改后的推荐列表 (原地修改并返回)
    """
    if freshness_report.get("fresh", True):
        return recommendations

    warnings = freshness_report.get("warnings", [])
    # Use the worst severity to determine penalty
    penalty = 1.0
    for warning in warnings:
        severity = str(warning.get("severity", "MEDIUM")).upper()
        if severity == "HIGH":
            penalty = min(penalty, 0.7)
        elif severity == "MEDIUM":
            penalty = min(penalty, 0.85)
        elif severity == "LOW":
            penalty = min(penalty, 0.95)

    for rec in recommendations:
        # R96 (R68/R69 falsy-zero 同族): 用显式 presence-check, 不用 ``or``。
        # confidence=0.0 是合法值 (agent error/fallback 明确输出 0.0 = "完全无信心"),
        # ``rec.get("confidence", 100) or 100`` 会把 0.0 静默覆盖为 100 (满信心),
        # 让"完全无信心"的 agent 输出变成"高信心推荐", 破坏"更高确信"目标。
        # 与 R68 (_resolve_trade_pnl) / R69 (_apply_explicit_metric_overrides) 同型。
        raw_confidence = rec.get("confidence")
        current_confidence = float(raw_confidence) if raw_confidence is not None else 100.0
        rec["confidence"] = round(current_confidence * penalty, 1)
        rec["confidence_penalty"] = round(1.0 - penalty, 2)
        rec["confidence_penalty_reason"] = "data_freshness_warning"

    return recommendations


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _normalize_date(date_str: str) -> str:
    """Normalize date to YYYY-MM-DD format."""
    cleaned = str(date_str or "").strip().replace("-", "")
    if len(cleaned) == 8 and cleaned.isdigit():
        return f"{cleaned[:4]}-{cleaned[4:6]}-{cleaned[6:8]}"
    return str(date_str or "")


def _check_cache_freshness(
    trade_date: str,
    cache_path: Path | None,
) -> dict[str, dict[str, Any]]:
    """Check cache database for latest data dates."""
    result: dict[str, dict[str, Any]] = {}

    if cache_path is None:
        # Try default cache path
        default_cache = Path.home() / ".cache" / "ai-hedge-fund" / "cache.sqlite"
        if default_cache.exists():
            cache_path = default_cache
        else:
            return result

    if not cache_path.exists():
        return result

    try:
        import sqlite3

        conn = sqlite3.connect(f"file:{cache_path}?mode=ro", uri=True)
        try:
            # Check daily prices freshness
            try:
                row = conn.execute("SELECT MAX(date) FROM cache WHERE key LIKE '%daily_prices%' OR key LIKE '%daily_%price%'").fetchone()
                if row and row[0]:
                    latest = str(row[0])[:10]
                    stale_days = _days_between(latest, trade_date)
                    result["daily_prices"] = {"latest_date": latest, "stale_days": stale_days}
            except Exception as exc:
                # R118 / 新鲜度门正确性: 标记 unknown 而非静默跳过。历史 skip 让该源
                # 缺失 → check_data_freshness 误报 all-fresh, 绕过数据安全门。
                # BH-017 drain: 同时保留 debug 日志以便 schema drift / locked DB 可诊断。
                logger.debug("[DataFreshness] daily_prices freshness query failed: %s", exc)
                result["daily_prices"] = {"unknown": True}

            # Check financial metrics freshness
            try:
                row = conn.execute("SELECT MAX(date) FROM cache WHERE key LIKE '%financial%' OR key LIKE '%fina_%'").fetchone()
                if row and row[0]:
                    latest = str(row[0])[:10]
                    stale_days = _days_between(latest, trade_date)
                    result["financial_metrics"] = {"latest_date": latest, "stale_days": stale_days}
            except Exception as exc:
                logger.debug("[DataFreshness] financial_metrics freshness query failed: %s", exc)
                result["financial_metrics"] = {"unknown": True}

            # Check industry classification freshness
            try:
                row = conn.execute("SELECT MAX(date) FROM cache WHERE key LIKE '%industry%' OR key LIKE '%sw_class%'").fetchone()
                if row and row[0]:
                    latest = str(row[0])[:10]
                    stale_days = _days_between(latest, trade_date)
                    result["industry_classification"] = {"latest_date": latest, "stale_days": stale_days}
            except Exception as exc:
                logger.debug("[DataFreshness] industry_classification freshness query failed: %s", exc)
                result["industry_classification"] = {"unknown": True}
        finally:
            conn.close()
    except Exception as exc:
        # BH-017 drain: whole-DB failure (locked / corrupt / permission) makes
        # the cache freshness audit silently return empty → false "all fresh".
        # Warn so the operator can diagnose a cache that is actually stale.
        logger.warning("[DataFreshness] cache freshness audit unavailable for %s: %s", cache_path, exc)

    return result


def _check_report_freshness(trade_date: str, reports_dir: Path) -> dict[str, Any]:
    """Check if a report exists for the trade date."""
    date_compact = trade_date.replace("-", "")
    candidates = list(reports_dir.glob(f"auto_screening_{date_compact}*.json"))
    if candidates:
        return {"fresh": True}
    # Check for any recent report
    recent = sorted(reports_dir.glob("auto_screening_*.json"), reverse=True)
    if not recent:
        return {
            "fresh": False,
            "warning": {
                "source": "report_file",
                "label": "选股报告",
                "latest_date": "none",
                "stale_days": 999,
                "max_stale_days": 1,
                "severity": "HIGH",
            },
        }
    latest_name = recent[0].stem
    latest_date = latest_name.replace("auto_screening_", "")[:8]
    if len(latest_date) == 8 and latest_date.isdigit():
        latest_formatted = f"{latest_date[:4]}-{latest_date[4:6]}-{latest_date[6:8]}"
        stale_days = _days_between(latest_formatted, trade_date)
        return {
            "fresh": stale_days <= 1,
            "warning": {
                "source": "report_file",
                "label": "选股报告",
                "latest_date": latest_formatted,
                "stale_days": stale_days,
                "max_stale_days": 1,
                "severity": "HIGH" if stale_days > 3 else "MEDIUM",
            },
        }
    return {"fresh": True}


def _days_between(date_earlier: str, date_later: str) -> int:
    """Calculate calendar days between two YYYY-MM-DD dates."""
    try:
        earlier = datetime.strptime(str(date_earlier)[:10], "%Y-%m-%d")
        later = datetime.strptime(str(date_later)[:10], "%Y-%m-%d")
        return max(0, (later - earlier).days)
    except (ValueError, TypeError):
        return 0


def _render_freshness_summary(fresh: bool, warnings: list[dict[str, Any]]) -> str:
    """Render a human-readable freshness summary."""
    if fresh:
        return f"{Fore.GREEN}✓ 数据新鲜度检查通过 — 所有关键数据源均在使用期内{Style.RESET_ALL}"

    lines = [f"{Fore.YELLOW}⚠ 数据新鲜度警告:{Style.RESET_ALL}"]
    for warning in warnings:
        severity_color = Fore.RED if warning["severity"] == "HIGH" else Fore.YELLOW if warning["severity"] == "MEDIUM" else Fore.WHITE
        lines.append(f"  {severity_color}[{warning['severity']}]{Style.RESET_ALL} " f"{warning['label']}: 最新数据 {warning['latest_date']} " f"(过期 {warning['stale_days']} 天, 阈值 {warning['max_stale_days']} 天)")
    # autodev-6 / disease F (silent-display honesty): the penalty acts on
    # rec.confidence, which composite_score (the actual ranking / BUY-gate key,
    # see composite_score.py: composite = score_b + adjustments) does NOT read.
    # apply_freshness_confidence_penalty is called only in decision_flow on
    # in-memory recs; compute_composite_scores re-reads the report from disk.
    # So the penalty is cosmetic w.r.t. the decision basis. Disclose this scope
    # limit so the operator is not misled into thinking stale data lowers the
    # recommendation's standing — it does not change ordering or BUY verdict.
    lines.append(
        "  → 已对 rec.confidence 字段按最严重等级施加惩罚 (最高 30%); "
        "注意: composite_score / 排序 / BUY 门控不读此字段, 故不影响最终决策依据"
    )
    return "\n".join(lines)
