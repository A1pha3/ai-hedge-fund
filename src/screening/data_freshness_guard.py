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

    Loop 92 (autodev): fail-closed on invalid trade_date. Previously, None / "" /
    "invalid" / malformed dates silently returned fresh=True because the glob
    pattern ``auto_screening_{date_compact}*.json`` degenerated to a wildcard
    matching any report — same disease class as loop 7 (G) permanent false
    fresh-positive. Upstream guards exist but are not comprehensive
    (report.get("date") can return ""; --trade-date "" can be passed).
    """
    normalized_date = _normalize_date(trade_date)
    warnings: list[dict[str, Any]] = []
    all_fresh = True

    # Loop 92: fail-closed on invalid trade_date — defense-in-depth even when
    # upstream guards exist. An invalid trade_date makes every downstream
    # comparison meaningless (cache stale_days, report freshness), so the
    # honest answer is "cannot verify freshness" (conservative not-fresh),
    # NOT silent fresh=True.
    if not _is_valid_normalized_date(normalized_date):
        all_fresh = False
        warnings.append(
            {
                "source": "trade_date",
                "label": "交易日期",
                "latest_date": "invalid",
                "stale_days": None,
                "max_stale_days": 0,
                "severity": "HIGH",
                "message": (
                    f"trade_date={trade_date!r} is not a valid YYYYMMDD / YYYY-MM-DD date; "
                    "freshness gate cannot verify — fail-closed (conservative not-fresh). "
                    "Pass a valid trade_date to evaluate cache/report freshness."
                ),
            }
        )
        summary = _render_freshness_summary(all_fresh, warnings)
        return {
            "fresh": all_fresh,
            "trade_date": normalized_date,
            "warnings": warnings,
            "warning_count": len(warnings),
            "summary": summary,
        }

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
            # autodev-7 / disease G: 'unavailable' means the source's date cannot
            # be checked from the cache schema (e.g. tushare hash keys with the
            # date only inside the pickled value). This is a TOOL LIMITATION, not
            # evidence of staleness. Honestly disclose it as an informational
            # note without the conservative not-fresh penalty (which would be a
            # permanent false stale-positive on every run). Distinct from
            # 'unknown' (query FAILED → conservative stale).
            if details.get("unavailable"):
                warnings.append(
                    {
                        "source": source_name,
                        "label": config.get("label", source_name),
                        "latest_date": "不可查",
                        "stale_days": None,
                        "max_stale_days": config.get("max_stale_days", 1),
                        "severity": "UNAVAILABLE",
                        "message": "cache schema does not expose this source's date (key is hash-based); freshness unverifiable, not assumed stale",
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


def _is_valid_normalized_date(normalized_date: str) -> bool:
    """Loop 92: validate that a normalized date is a real calendar date.

    Returns True only for non-empty YYYY-MM-DD strings that parse to a valid
    calendar date. Used by check_data_freshness to fail-closed on invalid
    trade_date input (None / "" / "invalid" / "20261301" month 13 etc.).
    """
    if not normalized_date:
        return False
    try:
        datetime.strptime(normalized_date, "%Y-%m-%d")
        return True
    except ValueError:
        return False


def _extract_latest_date_from_keys(
    conn: Any,
    key_pattern: str,
    date_regex: str,
) -> str | None:
    """autodev-7 / disease G: parse the latest embedded date from cache keys.

    The cache schema is ``(key, value, expires_at)`` with NO ``date`` column.
    The old ``SELECT MAX(date)`` queries always failed. Many cache keys embed
    the data's date range, e.g. ``prices:akshare::ashare_000001_20260601_20260610_daily``
    contains ``20260610`` as the end date. This helper scans keys matching
    ``key_pattern`` and extracts dates via ``date_regex`` (a regex with one
    capture group), returning the max (latest) date in ``YYYYMMDD`` form, or
    None when no key yields a date.

    Args:
        conn: open sqlite3 connection (read-only).
        key_pattern: SQL LIKE pattern to filter keys (e.g. ``%akshare::%daily``).
        date_regex: regex with one capture group yielding a YYYYMMDD date.

    Returns:
        Latest YYYYMMDD date found, or None when no key yields a date.

    Raises:
        Exception: re-raises any sqlite query error so the caller can mark the
        source ``unknown`` (conservative stale) — distinct from ``unavailable``
        (query succeeded but no parseable key, a schema limit).
    """
    import re

    rows = conn.execute("SELECT key FROM cache WHERE key LIKE ?", (key_pattern,)).fetchall()

    pattern = re.compile(date_regex)
    latest_yyyymmdd: str | None = None
    for (key,) in rows:
        m = pattern.search(str(key))
        if m:
            d = m.group(1)
            if len(d) == 8 and d.isdigit() and (latest_yyyymmdd is None or d > latest_yyyymmdd):
                latest_yyyymmdd = d
    return latest_yyyymmdd


def _check_cache_freshness(
    trade_date: str,
    cache_path: Path | None,
) -> dict[str, dict[str, Any]]:
    """Check cache database for latest data dates.

    autodev-7 / disease G: the cache schema is ``(key, value, expires_at)`` with
    NO ``date`` column. The prior implementation queried ``SELECT MAX(date)``,
    which always raised 'no such column: date' for all 3 sources, permanently
    marking every source UNKNOWN (false stale-positive on every run). R118
    caught the missing column but only fixed the fallback label, not the query.
    Now we parse dates embedded in keys (akshare price keys carry ``_YYYYMMDD_``)
    and honestly label sources whose dates cannot be checked from keys as
    ``unavailable`` (schema limit, not stale), distinct from a real stale hit.

    Loop 93 (autodev): defense-in-depth on invalid trade_date, mirroring loop
    92's ``_check_report_freshness`` boundary guard. Empirical dogfood proved
    that ``_check_cache_freshness(trade_date=None|""|"invalid"|"20261301")``
    silently returned ``stale_days=0`` (false fresh-positive) because
    ``_days_between`` try/except returns 0 on parse error. The function also
    used the raw ``trade_date`` parameter (YYYYMMDD) directly in
    ``_days_between`` without normalizing, so even valid YYYYMMDD inputs
    silently returned ``stale_days=0``. Now: normalize + validate at the
    boundary; if invalid, mark every source ``{"unknown": True}`` (conservative
    stale) so ``check_data_freshness`` treats the result as not-fresh.
    """
    # Loop 93: normalize + validate trade_date at the function boundary.
    # check_data_freshness already fail-closes on invalid trade_date (loop 92),
    # but this private helper can be called directly (tests, future code paths).
    # Without this guard, _days_between(latest, None|"") returns 0 via try/except
    # → silent false fresh-positive (same disease class as loop 92 (H)).
    normalized = _normalize_date(trade_date)
    if not _is_valid_normalized_date(normalized):
        # Conservative stale for ALL sources — check_data_freshness line 125-138
        # treats {"unknown": True} as not-fresh, aligning direct-call path with
        # the production path that fail-closed at check_data_freshness level.
        return {
            "daily_prices": {"unknown": True},
            "financial_metrics": {"unknown": True},
            "industry_classification": {"unknown": True},
        }

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
            # daily_prices: akshare price keys embed the end date
            # (prices:akshare::ashare_{ticker}_{start}_{end}_daily). tushare keys
            # are hash-based with no date in the key (date lives in the pickled
            # value), so they are not queryable without unpickling every row.
            try:
                latest = _extract_latest_date_from_keys(
                    conn,
                    key_pattern="%akshare::%daily",
                    date_regex=r"_(\d{8})_daily$",
                )
            except Exception as exc:
                # R118 conservative safety preserved: a real query failure
                # (locked DB / schema drift on the key column itself) → unknown
                # → check_data_freshness treats as not-fresh. Distinct from
                # 'unavailable' (query OK, no parseable key — schema limit).
                logger.debug("[DataFreshness] daily_prices key-scan failed: %s", exc)
                result["daily_prices"] = {"unknown": True}
            else:
                if latest is not None:
                    latest_formatted = f"{latest[:4]}-{latest[4:6]}-{latest[6:8]}"
                    # Loop 93: use normalized (YYYY-MM-DD), not raw trade_date.
                    # Previously passed raw `trade_date` (could be YYYYMMDD) to
                    # _days_between which expects YYYY-MM-DD → strptime failed →
                    # returned 0 → false fresh-positive even on valid inputs.
                    stale_days = _days_between(latest_formatted, normalized)
                    result["daily_prices"] = {"latest_date": latest_formatted, "stale_days": stale_days}
                else:
                    # No akshare keys with parseable dates. Honest 'unavailable'
                    # (cannot check from keys), NOT 'unknown' (which check_data_freshness
                    # treats as conservative stale). tushare hash keys cannot be checked
                    # without unpickling every value — out of scope for a freshness guard.
                    result["daily_prices"] = {"unavailable": True}

            # financial_metrics / industry_classification: tushare keys are
            # hash-based (tushare_df:fina_indicator:hash) with no date in the key.
            # The date lives in the pickled DataFrame value, which we cannot read
            # without unpickling every row (107k+ rows) — prohibitive for a
            # freshness guard. Honestly label as 'unavailable' (schema limit)
            # rather than the old permanent false-positive 'unknown'.
            result["financial_metrics"] = {"unavailable": True}
            result["industry_classification"] = {"unavailable": True}
        finally:
            conn.close()
    except Exception as exc:
        # BH-017 drain: whole-DB failure (locked / corrupt / permission) makes
        # the cache freshness audit silently return empty → false "all fresh".
        # Warn so the operator can diagnose a cache that is actually stale.
        logger.warning("[DataFreshness] cache freshness audit unavailable for %s: %s", cache_path, exc)

    return result


def _check_report_freshness(trade_date: str, reports_dir: Path) -> dict[str, Any]:
    """Check if a report exists for the trade date.

    Loop 92 (autodev): defense-in-depth — validate trade_date at the function
    boundary. Even though check_data_freshness now fail-closes on invalid
    trade_date, this function is also called directly in tests and could be
    called by future code paths. An invalid trade_date previously caused the
    glob pattern ``auto_screening_{date_compact}*.json`` to degenerate to a
    wildcard matching ANY report, producing false fresh=True.
    """
    normalized = _normalize_date(trade_date)
    if not _is_valid_normalized_date(normalized):
        return {
            "fresh": False,
            "warning": {
                "source": "report_file",
                "label": "选股报告",
                "latest_date": "invalid",
                "stale_days": None,
                "max_stale_days": 1,
                "severity": "HIGH",
                "message": (
                    f"trade_date={trade_date!r} is not a valid date; "
                    "cannot verify report freshness — fail-closed."
                ),
            },
        }
    date_compact = normalized.replace("-", "")
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
        stale_days = _days_between(latest_formatted, normalized)
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
    # autodev-7 / disease G: 'UNAVAILABLE' severity is an informational note
    # (cache schema does not expose a source's date — tool limit, not staleness).
    # When fresh=True but UNAVAILABLE notes exist, still render them so the
    # operator knows which sources could not be checked, instead of a bare
    # "all fresh" that hides the coverage gap.
    unavailable_notes = [w for w in warnings if w.get("severity") == "UNAVAILABLE"]
    if fresh and not unavailable_notes:
        return f"{Fore.GREEN}✓ 数据新鲜度检查通过 — 所有关键数据源均在使用期内{Style.RESET_ALL}"
    if fresh and unavailable_notes:
        # No real stale source, but some sources were unverifiable. Disclose
        # honestly without the stale-warning framing.
        lines = [f"{Fore.GREEN}✓ 数据新鲜度检查通过 (可查源均在使用期内){Style.RESET_ALL}"]
        lines.append(f"  {Fore.WHITE}ℹ 以下源因 cache schema 限制无法核查新鲜度 (非过期):{Style.RESET_ALL}")
        for w in unavailable_notes:
            lines.append(f"  {Fore.WHITE}[不可查]{Style.RESET_ALL} {w['label']}: {w['message']}")
        return "\n".join(lines)

    lines = [f"{Fore.YELLOW}⚠ 数据新鲜度警告:{Style.RESET_ALL}"]
    for warning in warnings:
        if warning["severity"] == "UNAVAILABLE":
            # Informational, not a stale warning — render distinctly.
            lines.append(f"  {Fore.WHITE}[不可查]{Style.RESET_ALL} {warning['label']}: {warning.get('message', 'cache schema 不暴露该源日期')}")
            continue
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
