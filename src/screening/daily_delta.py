"""推荐日间变动摘要 (Daily Recommendation Delta) — P6-2.

对比相邻两个交易日的推荐列表, 生成变动摘要:
- 新增标的 (today only)
- 移除标的 (yesterday only)
- 分数变动 (score_b 差异)
- 排名变动 (rank 变化)

CLI:
    python src/main.py --daily-delta
    python src/main.py --daily-delta --delta-lookback=5

集成到 ``--auto``:
    运行结束后自动附加 ``daily_delta`` 到报告顶层。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.screening.consecutive_recommendation import resolve_report_dir
from src.utils.display import Fore, Style

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_TOP_N = 20
_DELTA_KEY_FIELDS: tuple[str, ...] = ("score_b", "score_final", "confidence")


# ---------------------------------------------------------------------------
# Core delta computation
# ---------------------------------------------------------------------------


def compute_daily_delta(
    reports_dir: Path | None = None,
    *,
    top_n: int = _DEFAULT_TOP_N,
    lookback_days: int = 5,
) -> dict[str, Any]:
    """计算推荐日间变动。

    Args:
        reports_dir: 报告目录
        top_n: 比较的 Top N 标的数量
        lookback_days: 向前搜索最近报告的天数

    Returns:
        变动摘要 dict, 含 ``today_date``, ``yesterday_date``,
        ``added``, ``removed``, ``changed``, ``unchanged_count``
    """
    search_dir = reports_dir or resolve_report_dir()
    reports = _load_sorted_reports(search_dir)

    if len(reports) < 2:
        return _empty_delta("需要至少 2 天的推荐报告才能计算变动")

    # Find today's and yesterday's reports within lookback window
    today_report, yesterday_report = _find_adjacent_reports(reports, lookback_days)

    if today_report is None or yesterday_report is None:
        return _empty_delta(f"最近 {lookback_days} 天内未找到相邻两天的报告")

    today_recs = _extract_top_n(today_report["data"], top_n)
    yesterday_recs = _extract_top_n(yesterday_report["data"], top_n)

    today_tickers = {r["ticker"]: r for r in today_recs}
    yesterday_tickers = {r["ticker"]: r for r in yesterday_recs}

    today_set = set(today_tickers.keys())
    yesterday_set = set(yesterday_tickers.keys())

    added = []
    for ticker in sorted(today_set - yesterday_set):
        rec = today_tickers[ticker]
        added.append(_format_delta_entry(rec, rank=today_recs.index(rec) + 1))

    removed = []
    for ticker in sorted(yesterday_set - today_set):
        rec = yesterday_tickers[ticker]
        removed.append(_format_delta_entry(rec, rank=yesterday_recs.index(rec) + 1))

    changed = []
    for ticker in sorted(today_set & yesterday_set):
        today_rec = today_tickers[ticker]
        yesterday_rec = yesterday_tickers[ticker]
        delta = _compute_field_deltas(today_rec, yesterday_rec)
        if delta:
            today_rank = today_recs.index(today_rec) + 1
            yesterday_rank = yesterday_recs.index(yesterday_rec) + 1
            delta["rank_change"] = yesterday_rank - today_rank  # positive = moved up
            changed.append(delta)

    unchanged_count = len(today_set & yesterday_set) - len(changed)

    return {
        "today_date": today_report["date"],
        "yesterday_date": yesterday_report["date"],
        "added_count": len(added),
        "removed_count": len(removed),
        "changed_count": len(changed),
        "unchanged_count": max(0, unchanged_count),
        "added": added,
        "removed": removed,
        "changed": changed,
        "today_total": len(today_recs),
        "yesterday_total": len(yesterday_recs),
    }


def render_daily_delta(delta: dict[str, Any]) -> str:
    """渲染推荐变动摘要为可读文本。

    Args:
        delta: ``compute_daily_delta()`` 的输出

    Returns:
        格式化的 Markdown 字符串
    """
    if delta.get("error"):
        return f"{Fore.YELLOW}⚠ {delta['error']}{Style.RESET_ALL}"

    lines = [
        f"\n{Fore.CYAN}📊 推荐日间变动摘要{Style.RESET_ALL}",
        f"  对比: {delta['yesterday_date']} → {delta['today_date']}",
        "",
    ]

    # Summary stats
    lines.append(f"  {Fore.GREEN}+ 新增: {delta['added_count']}{Style.RESET_ALL}  "
                 f"{Fore.RED}- 移除: {delta['removed_count']}{Style.RESET_ALL}  "
                 f"{Fore.YELLOW}↔ 变动: {delta['changed_count']}{Style.RESET_ALL}  "
                 f"○ 不变: {delta['unchanged_count']}")

    # Added
    if delta.get("added"):
        lines.append(f"\n  {Fore.GREEN}新增标的:{Style.RESET_ALL}")
        for entry in delta["added"][:10]:
            lines.append(f"    {Fore.GREEN}+{Style.RESET_ALL} {entry['name']} ({entry['ticker']}) "
                         f"score={entry.get('score_b', '—')}  排名 #{entry.get('rank', '?')}")

    # Removed
    if delta.get("removed"):
        lines.append(f"\n  {Fore.RED}移除标的:{Style.RESET_ALL}")
        for entry in delta["removed"][:10]:
            lines.append(f"    {Fore.RED}-{Style.RESET_ALL} {entry['name']} ({entry['ticker']}) "
                         f"score={entry.get('score_b', '—')}")

    # Changed
    if delta.get("changed"):
        lines.append(f"\n  {Fore.YELLOW}分数变动:{Style.RESET_ALL}")
        for entry in delta["changed"]:
            score_delta = entry.get("score_b_delta", 0)
            rank_delta = entry.get("rank_change", 0)
            score_arrow = f"{Fore.GREEN}↑{score_delta:+.4f}{Style.RESET_ALL}" if score_delta > 0 else f"{Fore.RED}↓{score_delta:+.4f}{Style.RESET_ALL}" if score_delta < 0 else "→0.0000"
            rank_arrow = ""
            if rank_delta > 0:
                rank_arrow = f" {Fore.GREEN}(排名↑{rank_delta}){Style.RESET_ALL}"
            elif rank_delta < 0:
                rank_arrow = f" {Fore.RED}(排名↓{abs(rank_delta)}){Style.RESET_ALL}"
            lines.append(f"    {entry['name']} ({entry['ticker']}) {score_arrow}{rank_arrow}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _load_sorted_reports(reports_dir: Path) -> list[dict[str, Any]]:
    """Load all auto_screening reports sorted by date (newest first)."""
    reports: list[dict[str, Any]] = []
    if not reports_dir.exists():
        return reports
    for path in sorted(reports_dir.glob("auto_screening_*.json"), reverse=True):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            date_str = path.stem.replace("auto_screening_", "")[:8]
            reports.append({"date": _format_date(date_str), "path": str(path), "data": data})
        except (json.JSONDecodeError, OSError):
            continue
    return reports


def _find_adjacent_reports(
    reports: list[dict[str, Any]],
    lookback_days: int,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Find the most recent pair of adjacent reports."""
    if len(reports) < 2:
        return None, None
    today = reports[0]
    # Find the first report that's different from today
    for candidate in reports[1:]:
        if candidate["date"] != today["date"]:
            return today, candidate
    return today, None


def _extract_top_n(report_data: dict[str, Any], top_n: int) -> list[dict[str, Any]]:
    """Extract Top N recommendations from a report."""
    recs = report_data.get("recommendations", []) or []
    return recs[:top_n]


def _format_date(date_compact: str) -> str:
    """Convert YYYYMMDD to YYYY-MM-DD."""
    if len(date_compact) == 8 and date_compact.isdigit():
        return f"{date_compact[:4]}-{date_compact[4:6]}-{date_compact[6:8]}"
    return date_compact


def _format_delta_entry(rec: dict[str, Any], *, rank: int = 0) -> dict[str, Any]:
    """Format a recommendation entry for delta output."""
    return {
        "ticker": str(rec.get("ticker", "")),
        "name": str(rec.get("name", "")),
        "score_b": round(float(rec.get("score_b", 0) or 0), 4),
        "rank": rank,
    }


def _compute_field_deltas(
    today_rec: dict[str, Any],
    yesterday_rec: dict[str, Any],
) -> dict[str, Any]:
    """Compute field-level deltas between two recommendation entries."""
    today_raw = today_rec.get("score_b")
    yesterday_raw = yesterday_rec.get("score_b")
    # Skip delta if either score is missing/None — avoid misleading 0→N deltas
    if today_raw is None or yesterday_raw is None:
        return {}
    today_score = float(today_raw or 0)
    yesterday_score = float(yesterday_raw or 0)
    score_delta = round(today_score - yesterday_score, 4)

    if abs(score_delta) < 0.0001:
        return {}

    return {
        "ticker": str(today_rec.get("ticker", "")),
        "name": str(today_rec.get("name", "")),
        "score_b_today": round(today_score, 4),
        "score_b_yesterday": round(yesterday_score, 4),
        "score_b_delta": score_delta,
    }


def _empty_delta(reason: str) -> dict[str, Any]:
    """Return an empty delta with an error message."""
    return {
        "error": reason,
        "today_date": "",
        "yesterday_date": "",
        "added_count": 0,
        "removed_count": 0,
        "changed_count": 0,
        "unchanged_count": 0,
        "added": [],
        "removed": [],
        "changed": [],
        "today_total": 0,
        "yesterday_total": 0,
    }
