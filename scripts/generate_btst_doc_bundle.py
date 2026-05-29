from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from scripts.analyze_btst_early_runner_v1 import analyze_btst_early_runner_v1
from scripts.btst_strategy_thresholds import (
    DEFAULT_STRATEGY_THRESHOLDS_PROFILE,
    resolve_strategy_thresholds,
    resolve_strategy_thresholds_config_path,
)
from scripts.generate_btst_early_runner_daily_tables import generate_btst_early_runner_daily_tables

REPORTS_DIR = Path("data/reports")
OUTPUTS_DIR = Path("outputs")


def _normalize_signal_date(value: str) -> tuple[str, str]:
    """Normalize a signal date into compact and ISO formats."""
    raw = str(value or "").strip()
    if len(raw) == 8 and raw.isdigit():
        return raw, f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}"
    if len(raw) == 10 and raw[4] == "-" and raw[7] == "-":
        compact = raw.replace("-", "")
        if compact.isdigit():
            return compact, raw
    raise ValueError(f"unsupported signal date: {value!r}")


def _read_json(path: Path) -> dict[str, Any]:
    """Read one JSON file into a dict."""
    return dict(json.loads(path.read_text(encoding="utf-8")))


def _write_text(path: Path, content: str) -> None:
    """Write UTF-8 text and create parent directories when needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _safe_rows(value: Any) -> list[dict[str, Any]]:
    """Convert mixed JSON payloads into a list of row dicts."""
    return [dict(item or {}) for item in list(value or [])]


def _tag_rows(rows: list[dict[str, Any]], table_key: str) -> list[dict[str, Any]]:
    """Attach one stable table key to rows so downstream docs can keep four-layer semantics."""
    tagged_rows = []
    for row in rows:
        tagged = dict(row)
        tagged.setdefault("table_key", table_key)
        tagged_rows.append(tagged)
    return tagged_rows


def _fmt_pct(value: Any, digits: int = 2) -> str:
    """Render mixed numeric values into percentage text."""
    try:
        if value is None or value == "":
            return "n/a"
        return f"{float(value) * 100:.{digits}f}%"
    except (TypeError, ValueError):
        return "n/a"


def _fmt_num(value: Any, digits: int = 4) -> str:
    """Render mixed numeric values into decimal text."""
    try:
        if value is None or value == "":
            return "n/a"
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return "n/a"


def _resolve_thresholds_config_path(
    config_path: str | Path | None = None,
    *,
    profile: str | None = None,
) -> str:
    """Return the visible BTST strategy-threshold config path for generated docs."""
    return resolve_strategy_thresholds_config_path(config_path, profile=profile).as_posix()


def _stock_label(entry: dict[str, Any]) -> str:
    """Format one stock as code plus name when the name is available."""
    ticker = str(entry.get("ticker") or "").strip()
    name = str(entry.get("name") or "").strip()
    return f"{ticker} {name}".strip()


def _row_historical_metric(row: dict[str, Any], key: str) -> Any:
    """Return one historical metric from nested prior first, then from the row itself."""
    prior = dict(row.get("historical_prior") or {})
    value = prior.get(key)
    if value not in (None, "", [], {}, ()):
        return value
    return row.get(key)


def _historical_reading_note(row: dict[str, Any]) -> str:
    """Explain how to read historical win-rate and payoff numbers for one stock."""
    rate = _row_historical_metric(row, "next_close_positive_rate")
    payoff = _row_historical_metric(row, "next_close_payoff_ratio")
    evaluable = _row_historical_metric(row, "evaluable_count")
    try:
        rate_value = None if rate in (None, "") else float(rate)
    except (TypeError, ValueError):
        rate_value = None
    try:
        payoff_value = None if payoff in (None, "") else float(payoff)
    except (TypeError, ValueError):
        payoff_value = None
    note_parts: list[str] = []
    if rate_value is None and payoff_value is None:
        note = "胜率和盈亏比暂缺，只能先把它当成轻量历史先验。"
    else:
        if rate_value is None:
            note_parts.append("胜率暂缺")
        elif rate_value >= 0.70:
            note_parts.append("胜率高")
        elif rate_value >= 0.55:
            note_parts.append("胜率中性偏强")
        elif rate_value >= 0.45:
            note_parts.append("胜率中性")
        else:
            note_parts.append("胜率偏弱")
        if payoff_value is None:
            note_parts.append("盈亏比暂缺，通常表示历史正负样本拆分不足")
        elif payoff_value >= 2.0:
            note_parts.append("盈亏比优秀，赚钱时通常能明显覆盖亏损")
        elif payoff_value >= 1.0:
            note_parts.append("盈亏比站上 1.00，赚钱时大体能覆盖亏损")
        else:
            note_parts.append("盈亏比低于 1.00，更像靠命中率吃小胜")
        note = "，".join(note_parts) + "。"
    try:
        evaluable_count = None if evaluable in (None, "") else int(evaluable)
    except (TypeError, ValueError):
        evaluable_count = None
    if evaluable_count is not None and evaluable_count < 5:
        note = note[:-1] + "；样本偏少，只能作弱参考。"
    elif evaluable_count is not None and evaluable_count < 10:
        note = note[:-1] + "；样本不大，宜配合盘中确认。"
    return note


def _render_historical_metric_guide() -> list[str]:
    """Render one shared guide that explains historical win-rate and payoff metrics."""
    return [
        "## 指标怎么读",
        "",
        "- `收盘胜率` 看的是历史上次日收盘为正的比例，越高代表历史命中率越好。",
        "- `盈亏比` 大于 `1.00` 才说明平均赚幅大体能覆盖平均亏幅；低于 `1.00` 往往更依赖命中率。",
        "- 如果文档写 `n/a`，通常表示历史正负样本拆分不足，先验只能轻量参考，不能把空字段误读成强信号。",
    ]


def _stock_bullets(rows: list[dict[str, Any]], *, limit: int, include_payoff: bool = False) -> list[str]:
    """Render compact stock bullets for document sections."""
    lines: list[str] = []
    for row in rows[:limit]:
        rate = _row_historical_metric(row, "next_close_positive_rate")
        payoff = _row_historical_metric(row, "next_close_payoff_ratio")
        base = f"- `{_stock_label(row)}`：层级 `{row.get('action_tier') or row.get('lane') or row.get('table_key') or row.get('entry_status') or 'n/a'}`，模式 `{row.get('preferred_entry_mode') or 'n/a'}`，分数 `{_fmt_num(row.get('score_target', row.get('pre_score')), 4)}`"
        if include_payoff:
            base += f"，收盘胜率 `{_fmt_pct(rate)}`，盈亏比 `{_fmt_num(payoff, 2)}`，说明：{_historical_reading_note(row)}"
            lines.append(base)
            continue
        lines.append(base + "。")
    return lines or ["- 无。"]


def _rule_stock_bullets(rows: list[dict[str, Any]], *, limit: int) -> list[str]:
    """Render rule-report high-confidence rows from their native score fields."""
    lines: list[str] = []
    for row in rows[:limit]:
        details = [
            f"规则分数 `{_fmt_num(_first_non_empty(row.get('score'), row.get('score_target')), 4)}`",
        ]
        if row.get("pct_chg") not in (None, ""):
            details.append(f"当日涨幅 `{_fmt_num(row.get('pct_chg'), 2)}%`")
        if row.get("close_strength") not in (None, ""):
            details.append(f"close_strength `{_fmt_num(row.get('close_strength'), 4)}`")
        if row.get("catalyst_freshness") not in (None, ""):
            details.append(f"catalyst_freshness `{_fmt_num(row.get('catalyst_freshness'), 4)}`")
        if row.get("candidate_source") not in (None, ""):
            details.append(f"来源 `{row.get('candidate_source')}`")
        lines.append(f"- `{_stock_label(row)}`：" + "，".join(details) + "。")
    return lines or ["- 无。"]


def _first_non_empty(*values: Any) -> Any:
    """Return the first non-empty value from a list of candidates."""
    for value in values:
        if value not in (None, "", [], {}, ()):
            return value
    return None


def _discover_report_dir(reports_root: Path, signal_date_iso: str, explicit_report_dir: str | Path | None) -> Path:
    """Discover the short-trade report directory for the requested signal date."""
    if explicit_report_dir:
        return Path(explicit_report_dir).expanduser().resolve()
    signal_date_compact = signal_date_iso.replace("-", "")
    candidates: list[Path] = []
    for child in reports_root.iterdir():
        if not child.is_dir():
            continue
        session_summary_path = child / "session_summary.json"
        if not session_summary_path.exists():
            continue
        try:
            session_summary = _read_json(session_summary_path)
        except Exception:
            continue
        btst_followup = dict(session_summary.get("btst_followup") or {})
        trade_date = str(
            _first_non_empty(
                session_summary.get("trade_date"),
                btst_followup.get("trade_date"),
                session_summary.get("start_date"),
                session_summary.get("end_date"),
            )
            or ""
        )
        selection_target = str(_first_non_empty(session_summary.get("selection_target"), dict(session_summary.get("plan_generation") or {}).get("selection_target")) or "")
        normalized_trade_date = trade_date.replace("-", "")
        if normalized_trade_date == signal_date_compact and selection_target == "short_trade_only":
            candidates.append(child)
    if not candidates:
        raise FileNotFoundError(f"unable to find short_trade_only report dir for {signal_date_iso}")
    return sorted(candidates, key=lambda item: item.stat().st_mtime, reverse=True)[0]


def _refresh_early_runner_artifacts(reports_root: Path) -> dict[str, Any]:
    """Refresh early-runner analysis and daily tables before document generation."""
    analysis = analyze_btst_early_runner_v1(reports_root)
    tables = generate_btst_early_runner_daily_tables(reports_root)
    return {
        "analysis": analysis,
        "tables": tables,
    }


def _load_early_runner_context(reports_root: Path, signal_date_iso: str, *, refresh: bool) -> dict[str, Any]:
    """Load the exact-date early-runner board or the latest available fallback board."""
    if refresh:
        refreshed = _refresh_early_runner_artifacts(reports_root)
        analysis = dict(refreshed["analysis"])
        tables_refresh = dict(refreshed["tables"])
    else:
        analysis = _read_json(reports_root / "btst_early_runner_v1_latest.json")
        tables_refresh = {}
    boards = _safe_rows(analysis.get("daily_boards"))
    exact_board = next((row for row in boards if str(row.get("trade_date") or "") == signal_date_iso), {})
    latest_board = max(boards, key=lambda row: str(row.get("trade_date") or ""), default={})
    selected_board = dict(exact_board or latest_board or {})
    status = "exact"
    if not selected_board:
        status = "unavailable"
    elif not exact_board:
        status = "stale_fallback"
    return {
        "analysis": analysis,
        "tables_refresh": tables_refresh,
        "status": status,
        "requested_trade_date": signal_date_iso,
        "board": selected_board,
        "latest_trade_date": str(latest_board.get("trade_date") or "") or None,
        "watchlist": _tag_rows(_safe_rows(selected_board.get("early_runner_watchlist")), "early_runner_watchlist"),
        "priority": _tag_rows(_safe_rows(selected_board.get("early_runner_priority")), "early_runner_priority"),
        "second_entry": _tag_rows(_safe_rows(selected_board.get("second_entry_reentry")), "second_entry_reentry"),
        "research_confirmation": _tag_rows(_safe_rows(selected_board.get("full_report_confirmation")), "full_report_confirmation"),
    }


def _overlap_tickers(formal_rows: list[dict[str, Any]], early_runner_rows: list[dict[str, Any]]) -> list[str]:
    """Compute de-duplicated ticker overlaps between formal BTST rows and early-runner rows."""
    formal_tickers = {str(row.get("ticker") or "").strip() for row in formal_rows if str(row.get("ticker") or "").strip()}
    overlap = []
    for row in early_runner_rows:
        ticker = str(row.get("ticker") or "").strip()
        if ticker and ticker in formal_tickers and ticker not in overlap:
            overlap.append(ticker)
    return overlap


def _find_row_by_ticker(rows: list[dict[str, Any]], ticker: str) -> dict[str, Any]:
    """Find one row by ticker and return an empty dict when it is missing."""
    normalized = str(ticker or "").strip()
    for row in rows:
        if str(row.get("ticker") or "").strip() == normalized:
            return row
    return {}


def _build_intersection_summary(context: dict[str, Any], formal_rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Build four-layer early-runner groups without mixing second-entry into first-entry overlap logic."""
    watchlist = _safe_rows(context.get("watchlist"))
    priority = _safe_rows(context.get("priority"))
    second_entry = _safe_rows(context.get("second_entry"))
    first_entry_rows = [*priority, *watchlist]
    overlap_tickers = _overlap_tickers(formal_rows, first_entry_rows)
    formal_tickers = {str(row.get("ticker") or "").strip() for row in formal_rows}
    overlap_rows = []
    for ticker in overlap_tickers:
        formal_row = _find_row_by_ticker(formal_rows, ticker)
        early_row = _first_non_empty(_find_row_by_ticker(priority, ticker), _find_row_by_ticker(watchlist, ticker), {}) or {}
        overlap_rows.append(
            {
                "ticker": ticker,
                "formal_row": dict(formal_row or {}),
                "early_row": dict(early_row or {}),
                "highlight_state": "intersection_priority" if str(context.get("status") or "") == "exact" else "reference_only_intersection",
            }
        )
    only_early_runner_rows = []
    seen_only = set()
    for row in first_entry_rows:
        ticker = str(row.get("ticker") or "").strip()
        if ticker and ticker not in formal_tickers and ticker not in seen_only:
            seen_only.add(ticker)
            only_early_runner_rows.append(dict(row))
    return {
        "status": str(context.get("status") or "unavailable"),
        "priority_rows": priority,
        "watchlist_rows": watchlist,
        "second_entry_rows": second_entry,
        "overlap_tickers": overlap_tickers,
        "overlap_rows": overlap_rows,
        "only_early_runner_rows": only_early_runner_rows,
    }


def _render_intersection_highlights(intersection_summary: dict[str, Any]) -> list[str]:
    """Render middle-stage overlap highlights with exact-vs-fallback wording."""
    status = str(intersection_summary.get("status") or "unavailable")
    overlap_rows = _safe_rows(intersection_summary.get("overlap_rows"))
    only_early_runner_rows = _safe_rows(intersection_summary.get("only_early_runner_rows"))
    lines = ["## 交集票高亮", ""]
    if overlap_rows:
        if status == "exact":
            lines.append("- 当日 early-runner 与正式 BTST 同时命中的票如下，这些票进入“交集优先复审”层。")
        else:
            lines.append("- 当前交集来自回退板或非当日板，只能作为参考高亮，不能直接当成当日交集优先。")
        for row in overlap_rows:
            formal_row = dict(row.get("formal_row") or {})
            early_row = dict(row.get("early_row") or {})
            lines.append(
                f"- `{_stock_label(formal_row or early_row)}`：正式层级 `{formal_row.get('action_tier') or formal_row.get('lane') or 'n/a'}`，"
                f"early-runner 层级 `{early_row.get('entry_status') or early_row.get('table_key') or 'priority/watchlist'}`，"
                f"正式模式 `{formal_row.get('preferred_entry_mode') or 'n/a'}`，"
                f"early-runner pre/confirm `{_fmt_num(early_row.get('pre_score'), 4)}` / `{_fmt_num(early_row.get('confirm_score'), 4)}`。"
            )
    else:
        lines.append("- 当前没有可高亮的交集票。")
    lines.extend(["", "## Only Early Runner", ""])
    if only_early_runner_rows:
        lines.append("- 以下股票只出现在 early-runner，不进入正式执行清单，只进入盘中补充复审。")
        lines.extend(_stock_bullets(only_early_runner_rows, limit=8, include_payoff=True))
    else:
        lines.append("- 当前没有 only early-runner 补充票。")
    return lines


def _resolve_selected_rows(brief: dict[str, Any], priority_board: dict[str, Any]) -> list[dict[str, Any]]:
    """Resolve formal selected rows from the brief first, then from the priority board."""
    selected_rows = _safe_rows(_first_non_empty(brief.get("selected_actions"), brief.get("selected_entries")))
    if selected_rows:
        return selected_rows
    rows = []
    for row in _safe_rows(priority_board.get("priority_rows")):
        lane = str(row.get("lane") or "")
        if lane in {"primary_entry", "selected_backup"}:
            rows.append(row)
    return rows


def _resolve_watch_rows(brief: dict[str, Any], priority_board: dict[str, Any]) -> list[dict[str, Any]]:
    """Resolve watch-only rows from the brief first, then from the priority board."""
    watch_rows = _safe_rows(brief.get("watch_actions"))
    if watch_rows:
        return watch_rows
    rows = []
    for row in _safe_rows(priority_board.get("priority_rows")):
        lane = str(row.get("lane") or "")
        actionability = str(row.get("actionability") or "")
        if actionability == "watch_only" or "near_miss" in lane:
            rows.append(row)
    return rows


def _resolve_opportunity_rows(brief: dict[str, Any], priority_board: dict[str, Any]) -> list[dict[str, Any]]:
    """Resolve opportunity rows from the brief first, then from the priority board."""
    opportunity_rows = _safe_rows(brief.get("opportunity_actions"))
    if opportunity_rows:
        return opportunity_rows
    rows = []
    for row in _safe_rows(priority_board.get("priority_rows")):
        lane = str(row.get("lane") or "")
        if lane == "opportunity_pool":
            rows.append(row)
    return rows


def _resolve_primary_action(brief: dict[str, Any], priority_board: dict[str, Any]) -> dict[str, Any]:
    """Resolve the primary trade idea from multiple artifact variants."""
    selected_rows = _resolve_selected_rows(brief, priority_board)
    return dict(_first_non_empty(brief.get("primary_action"), brief.get("primary_entry"), selected_rows[0] if selected_rows else {}) or {})


def _render_early_runner_status(context: dict[str, Any]) -> list[str]:
    """Render human-readable early-runner availability lines."""
    board = dict(context.get("board") or {})
    research_confirmation = _safe_rows(context.get("research_confirmation"))
    status = str(context.get("status") or "unavailable")
    requested = str(context.get("requested_trade_date") or "")
    latest = str(context.get("latest_trade_date") or "")
    lines = [f"- 请求 trade_date：`{requested}`。"]
    if status == "exact":
        lines.append(f"- early-runner 命中当日板：`{requested}`，`deployment_mode={board.get('deployment_mode')}`，`gate_action={board.get('gate_action')}`。")
    elif status == "stale_fallback":
        lines.append(f"- 当日 early-runner 板缺失，回退到最近可用板：`{latest}`，`deployment_mode={board.get('deployment_mode')}`，`gate_action={board.get('gate_action')}`。")
    else:
        lines.append("- 当前没有可用 early-runner 板，本轮文档只记录缺失状态，不编造观察票。")
    if research_confirmation:
        lines.append(
            f"- 当前板保留 `full_report_confirmation={len(research_confirmation)}` 条研究确认票；它们只用于研究确认，不自动进入 priority/watchlist/second-entry。"
        )
        lines.append(
            f"- 研究确认前排：`{[str(row.get('ticker') or '').strip() for row in research_confirmation[:5]]}`。"
        )
    return lines


def _render_early_runner_overlay(context: dict[str, Any], formal_rows: list[dict[str, Any]]) -> list[str]:
    """Render the overlay section that compares early-runner with formal BTST rows."""
    watchlist = _safe_rows(context.get("watchlist"))
    priority = _safe_rows(context.get("priority"))
    second_entry = _safe_rows(context.get("second_entry"))
    research_confirmation = _safe_rows(context.get("research_confirmation"))
    intersection_summary = _build_intersection_summary(context, formal_rows)
    lines = []
    lines.extend(_render_early_runner_status(context))
    lines.append(f"- watchlist 数量：`{len(watchlist)}`；priority 数量：`{len(priority)}`；second_entry 数量：`{len(second_entry)}`。")
    if research_confirmation:
        lines.append(f"- research-only 确认池数量：`{len(research_confirmation)}`。")
    lines.append(f"- 与正式 BTST 的重合票：`{intersection_summary.get('overlap_tickers')}`。")
    lines.append(
        f"- 仅 early-runner 命中的补充票：`{[str(row.get('ticker') or '').strip() for row in _safe_rows(intersection_summary.get('only_early_runner_rows'))]}`。"
    )
    lines.append(
        f"- 回补机会层：`{[str(row.get('ticker') or '').strip() for row in _safe_rows(intersection_summary.get('second_entry_rows'))]}`。"
    )
    return lines


def _render_strategy_threshold_lines(
    strategy_thresholds: dict[str, Any],
    strategy_thresholds_config_path: str,
    strategy_thresholds_profile: str,
) -> list[str]:
    """Render the shared BTST strategy-threshold baseline into generated documents."""
    return [
        "## 当前策略阈值基线",
        "",
        f"- profile：`{strategy_thresholds_profile}`；配置文件：`{strategy_thresholds_config_path}`。",
        f"- exact 连续门槛：`{strategy_thresholds.get('min_recent_exact_streak')}`；交集出现天数门槛：`{strategy_thresholds.get('min_intersection_positive_days')}`。",
        f"- 交集层 uplift 门槛：胜率差 `+{_fmt_pct(strategy_thresholds.get('intersection_uplift_rate_threshold'))}`；均值差 `+{_fmt_num(strategy_thresholds.get('intersection_uplift_mean_return_threshold'), 2)}`。",
        f"- 补充层最大容忍正收益率：`{_fmt_pct(strategy_thresholds.get('only_early_runner_max_positive_rate'))}`；回补层 T+2 优势门槛：`+{_fmt_num(strategy_thresholds.get('second_entry_t2_advantage_threshold'), 3)}`。",
    ]


def _render_rule_doc(
    signal_date_compact: str,
    rule_report: dict[str, Any],
    brief: dict[str, Any],
    priority_board: dict[str, Any],
    early_runner: dict[str, Any],
    rule_report_path: Path,
    report_dir: Path,
    strategy_thresholds: dict[str, Any],
    strategy_thresholds_config_path: str,
    strategy_thresholds_profile: str,
) -> str:
    """Render the rule-based document and append early-runner status as an overlay section."""
    high_confidence = _safe_rows(rule_report.get("high_confidence"))
    selected_actions = _resolve_selected_rows(brief, priority_board)
    formal_rows = selected_actions + _resolve_watch_rows(brief, priority_board)
    intersection_summary = _build_intersection_summary(early_runner, formal_rows)
    lines = [
        f"# BTST 规则版详细计划（{signal_date_compact}）",
        "",
        "## 核心结论",
        "",
        f"- 信号日：`{signal_date_compact}`；目标交易日：`{rule_report.get('next_date') or brief.get('next_trade_date') or 'n/a'}`。",
        f"- 规则池：`pool_size={rule_report.get('pool_size')}`，`selected_count={rule_report.get('selected_count')}`，`near_miss_count={rule_report.get('near_miss_count')}`。",
        f"- 规则报告来源：`{rule_report_path}`。",
        f"- 多智能体运行目录：`{report_dir}`。",
        "",
    ]
    lines.extend(_render_strategy_threshold_lines(strategy_thresholds, strategy_thresholds_config_path, strategy_thresholds_profile))
    lines.extend([""])
    lines.extend(_render_historical_metric_guide())
    lines.extend(["", "## 规则前排", ""])
    lines.extend(_rule_stock_bullets(high_confidence, limit=8))
    lines.append("- 规则前排这里先看规则分数；若要看 BTST 股票的历史胜率和盈亏比，请以下面的多智能体详细计划与预警文档为准。")
    lines.extend(
        [
            "",
            "## Early Runner Overlay",
            "",
        ]
    )
    lines.extend(_render_early_runner_overlay(early_runner, formal_rows))
    lines.extend([""])
    lines.extend(_render_intersection_highlights(intersection_summary))
    if _safe_rows(intersection_summary.get("only_early_runner_rows")):
        lines.extend(["", "### 补充复审层", ""])
        lines.extend(_stock_bullets(_safe_rows(intersection_summary.get("only_early_runner_rows")), limit=5, include_payoff=True))
    if _safe_rows(intersection_summary.get("second_entry_rows")):
        lines.extend(["", "### 回补机会层", ""])
        lines.extend(_stock_bullets(_safe_rows(intersection_summary.get("second_entry_rows")), limit=5, include_payoff=True))
    return "\n".join(lines) + "\n"


def _render_llm_doc(
    signal_date_compact: str,
    brief: dict[str, Any],
    priority_board: dict[str, Any],
    session_summary: dict[str, Any],
    early_runner: dict[str, Any],
    report_dir: Path,
    strategy_thresholds: dict[str, Any],
    strategy_thresholds_config_path: str,
    strategy_thresholds_profile: str,
) -> str:
    """Render the multi-agent document and add early-runner overlaps plus watch-only context."""
    selected_actions = _resolve_selected_rows(brief, priority_board)
    watch_actions = _resolve_watch_rows(brief, priority_board)
    opportunity_actions = _resolve_opportunity_rows(brief, priority_board)
    formal_rows = [*selected_actions, *watch_actions, *opportunity_actions]
    intersection_summary = _build_intersection_summary(early_runner, formal_rows)
    profile_name = _first_non_empty(dict(session_summary.get("optimization_profile_resolution") or {}).get("profile_name"), session_summary.get("short_trade_target_profile_name"))
    lines = [
        f"# BTST 多智能体详细计划（{signal_date_compact}）",
        "",
        "## 核心结论",
        "",
        f"- 信号日：`{brief.get('trade_date')}`；目标交易日：`{brief.get('next_trade_date')}`。",
        f"- 运行目录：`{report_dir}`。",
        f"- 选股模式：`{brief.get('selection_target')}`；profile：`{profile_name or 'n/a'}`。",
        f"- selected 数量：`{len(selected_actions)}`；watch 数量：`{len(watch_actions)}`；机会池数量：`{len(opportunity_actions)}`。",
        "",
    ]
    lines.extend(_render_strategy_threshold_lines(strategy_thresholds, strategy_thresholds_config_path, strategy_thresholds_profile))
    lines.extend([""])
    lines.extend(_render_historical_metric_guide())
    lines.extend(["", "## 正式执行层", ""])
    lines.extend(_stock_bullets(selected_actions, limit=5, include_payoff=True))
    lines.extend(["", "## 观察层", ""])
    lines.extend(_stock_bullets(watch_actions, limit=8, include_payoff=True))
    if opportunity_actions:
        lines.extend(["", "## 机会池", ""])
        lines.extend(_stock_bullets(opportunity_actions, limit=5, include_payoff=True))
    lines.extend(["", "## Early Runner 章节", ""])
    lines.extend(_render_early_runner_overlay(early_runner, formal_rows))
    lines.extend([""])
    lines.extend(_render_intersection_highlights(intersection_summary))
    lines.extend(["", "### 四层使用顺序", ""])
    if str(intersection_summary.get("status") or "") == "exact":
        lines.append("- 正式执行层先决定主顺序，交集票只做优先复审，不做无条件升级。")
    else:
        lines.append("- 当前只有回退板或旧板可用，因此交集只做参考高亮，不升级为当日交集优先。")
    lines.append("- only early-runner 票只进入补充复审层，不自动升级为正式主票。")
    lines.append("- second-entry / reentry 单独归入回补机会层，不和普通补充票混用。")
    if _safe_rows(intersection_summary.get("only_early_runner_rows")):
        lines.extend(["", "### 补充复审层", ""])
        lines.extend(_stock_bullets(_safe_rows(intersection_summary.get("only_early_runner_rows")), limit=5, include_payoff=True))
    if _safe_rows(intersection_summary.get("second_entry_rows")):
        lines.extend(["", "### 回补机会层", ""])
        lines.extend(_stock_bullets(_safe_rows(intersection_summary.get("second_entry_rows")), limit=5, include_payoff=True))
    return "\n".join(lines) + "\n"


def _render_plain_language_doc(signal_date_compact: str, brief: dict[str, Any], priority_board: dict[str, Any], early_runner: dict[str, Any]) -> str:
    """Render the plain-language explanation and explain why early-runner is watch-only now."""
    primary_action = _resolve_primary_action(brief, priority_board)
    selected_actions = _resolve_selected_rows(brief, priority_board)
    watch_actions = _resolve_watch_rows(brief, priority_board)
    intersection_summary = _build_intersection_summary(early_runner, [*selected_actions, *watch_actions])
    early_status = str(early_runner.get("status") or "unavailable")
    board = dict(early_runner.get("board") or {})
    status_note = {
        "exact": (
            "这次文档里已经拿到了当日 early-runner 板，但它当前仍是 `research_only`，只保留研究确认池，不生成可执行观察票。"
            if str(board.get("gate_action") or "") == "research_only"
            else "这次文档里已经拿到了当日 early-runner 板，所以它可以作为正式 BTST 旁边的第二观察层使用。"
        ),
        "stale_fallback": "这次文档没有拿到当日 early-runner 板，只能回退到最近可用板，所以它只能作为参考线索，不能当成当天正式观察单。",
        "unavailable": "这次文档没有拿到可用 early-runner 板，所以只能显式记录缺失状态，不能拿它补出不存在的观察票。",
    }.get(early_status, "当前 early-runner 状态不明确，只能保守处理。")
    lines = [
        f"# {signal_date_compact}-两套交易计划通俗说明",
        "",
        f"信号日：`{brief.get('trade_date')}`；目标交易日：`{brief.get('next_trade_date')}`。",
        "",
        "## 先说结论",
        "",
        f"正式 BTST 仍以 `{_stock_label(primary_action)}` 这条主线为准，early-runner 不是替代品，而是补充观察层。{status_note}",
        "",
        "## 这次为什么要把 Early Runner 写进来",
        "",
        "- 正式 BTST 更适合做最终执行排序。",
        "- early-runner 更适合做更早的补充观察和盘中复审。",
        "- 两边都同时命中的票，比只出现在单边的票更值得优先盯。",
        "",
        "## 正式 BTST 在看什么",
        "",
        f"- 主票是 `{_stock_label(primary_action)}`，执行模式是 `{primary_action.get('preferred_entry_mode') or 'n/a'}`。",
        f"- 正式 selected 数量是 `{len(selected_actions)}`，watch 数量是 `{len(watch_actions)}`。",
        "",
        "## Early Runner 在看什么",
        "",
    ]
    lines.extend(_render_early_runner_overlay(early_runner, [*selected_actions, *watch_actions]))
    lines.extend(
        [
            "",
            "## 交集票怎么处理",
            "",
        ]
    )
    if _safe_rows(intersection_summary.get("overlap_rows")):
        if early_status == "exact":
            lines.append("- 当日交集票会被高亮成“交集优先复审”，意思是先看这些票，再看普通观察票。")
        else:
            lines.append("- 当前看到的交集来自回退板，只能帮助你理解历史重合关系，不能当成明天一早的强优先级。")
        for row in _safe_rows(intersection_summary.get("overlap_rows"))[:5]:
            lines.append(f"- 交集票：`{_stock_label(dict(row.get('formal_row') or row.get('early_row') or {}))}`。")
    else:
        lines.append("- 这次没有交集票，所以仍按正式 BTST 主线和普通观察层执行。")
    lines.extend(
        [
            "",
            "## 怎么使用这两条线",
            "",
            "- 正式 BTST 决定主执行顺序。",
            "- early-runner 负责提示更早的观察票和 second-entry 线索。",
            "- 只出现在 early-runner 的票默认不进正式执行清单，只放入盘中复审。",
        ]
    )
    return "\n".join(lines) + "\n"


def _render_forum_doc(signal_date_compact: str, brief: dict[str, Any], priority_board: dict[str, Any], early_runner: dict[str, Any]) -> str:
    """Render the short forum-ready version with a compact early-runner status note."""
    primary_action = _resolve_primary_action(brief, priority_board)
    selected_actions = _resolve_selected_rows(brief, priority_board)
    watch_actions = _resolve_watch_rows(brief, priority_board)
    intersection_summary = _build_intersection_summary(early_runner, [*selected_actions, *watch_actions])
    priority = _safe_rows(early_runner.get("priority"))
    watchlist = _safe_rows(early_runner.get("watchlist"))
    research_confirmation = _safe_rows(early_runner.get("research_confirmation"))
    extra_rows = priority[:2] or watchlist[:2]
    extra_label = "补充观察票优先看"
    if not extra_rows and research_confirmation:
        extra_rows = research_confirmation[:2]
        extra_label = "research-only 确认前排"
    extra = [str(row.get("ticker") or "").strip() for row in extra_rows]
    overlap = [str(row.get("ticker") or "").strip() for row in _safe_rows(intersection_summary.get("overlap_rows"))[:3]]
    lines = [
        f"# {signal_date_compact}-两套交易计划论坛短版",
        "",
        f"明日 BTST 主线还是 `{_stock_label(primary_action)}`，执行模式 `{primary_action.get('preferred_entry_mode') or 'n/a'}`，先确认再决定，不做开盘无脑追价。",
        "",
        f"这次 early-runner 状态：`{early_runner.get('status')}`；交集高亮 `{overlap}`；{extra_label} `{extra}`。",
        "",
        "使用顺序：正式 BTST 决定主票，early-runner 只做交集优先和补充复审，不替代正式执行单。",
    ]
    return "\n".join(lines) + "\n"


def _render_checklist_doc(
    signal_date_compact: str,
    brief: dict[str, Any],
    priority_board: dict[str, Any],
    early_runner: dict[str, Any],
    strategy_thresholds: dict[str, Any],
    strategy_thresholds_config_path: str,
    strategy_thresholds_profile: str,
) -> str:
    """Render the next-morning checklist and append early-runner watch-only checkpoints."""
    selected_actions = _resolve_selected_rows(brief, priority_board)
    watch_actions = _resolve_watch_rows(brief, priority_board)
    intersection_summary = _build_intersection_summary(early_runner, [*selected_actions, *watch_actions])
    lines = [
        f"# BTST-{signal_date_compact}-EXEC-CHECKLIST",
        "",
        f"信号日：`{brief.get('trade_date')}`；目标交易日：`{brief.get('next_trade_date')}`。",
        "",
    ]
    lines.extend(_render_strategy_threshold_lines(strategy_thresholds, strategy_thresholds_config_path, strategy_thresholds_profile))
    lines.extend([""])
    lines.extend(_render_historical_metric_guide())
    lines.extend(["", "## 正式执行顺序", ""])
    for row in selected_actions[:3]:
        lines.append(
            f"- [ ] 正式执行：`{_stock_label(row)}`，模式 `{row.get('preferred_entry_mode') or 'n/a'}`，"
            f"收盘胜率 `{_fmt_pct(_row_historical_metric(row, 'next_close_positive_rate'))}`，"
            f"盈亏比 `{_fmt_num(_row_historical_metric(row, 'next_close_payoff_ratio'), 2)}`，"
            f"说明：{_historical_reading_note(row)}"
        )
    lines.extend(["", "## 正式观察顺序", ""])
    for row in watch_actions[:6]:
        lines.append(f"- [ ] 正式观察：`{_stock_label(row)}`，层级 `{row.get('action_tier') or 'watch_only'}`，必要时盘中再确认。")
    lines.extend(["", "## 交集优先复审", ""])
    if _safe_rows(intersection_summary.get("overlap_rows")):
        for row in _safe_rows(intersection_summary.get("overlap_rows"))[:5]:
            merged = dict(row.get("formal_row") or row.get("early_row") or {})
            if str(intersection_summary.get("status") or "") == "exact":
                lines.append(f"- [ ] 交集优先：`{_stock_label(merged)}`，先于普通观察票复审。")
            else:
                lines.append(f"- [ ] 历史交集参考：`{_stock_label(merged)}`，仅做参考，不当作当日优先升级。")
    else:
        lines.append("- [ ] 当前没有交集票。")
    lines.extend(["", "## Early Runner 补充观察", ""])
    lines.extend(_render_early_runner_status(early_runner))
    only_early_runner_rows = _safe_rows(intersection_summary.get("only_early_runner_rows"))
    if only_early_runner_rows:
        for row in only_early_runner_rows[:5]:
            lines.append(f"- [ ] Early Runner 补充复审：`{_stock_label(row)}`，来源 `{row.get('table_key') or 'early_runner'}`，`pre_score={_fmt_num(row.get('pre_score'), 4)}`，`confirm_score={_fmt_num(row.get('confirm_score'), 4)}`，仅做补充复审。")
    else:
        lines.append("- [ ] 当前没有可直接使用的 only early-runner 补充票。")
    lines.extend(["", "## 回补机会层", ""])
    second_entry_rows = _safe_rows(intersection_summary.get("second_entry_rows"))
    if second_entry_rows:
        for row in second_entry_rows[:5]:
            lines.append(f"- [ ] Second Entry / Reentry：`{_stock_label(row)}`，`pre_score={_fmt_num(row.get('pre_score'), 4)}`，`confirm_score={_fmt_num(row.get('confirm_score'), 4)}`，等二次确认后再决定是否跟进。")
    else:
        lines.append("- [ ] 当前没有 second-entry / reentry 回补机会票。")
    return "\n".join(lines) + "\n"


def _render_early_warning_doc(
    signal_date_compact: str,
    early_runner: dict[str, Any],
    formal_rows: list[dict[str, Any]],
    strategy_thresholds: dict[str, Any],
    strategy_thresholds_config_path: str,
    strategy_thresholds_profile: str,
) -> str:
    """Render the dedicated early-warning document from early-runner watchlists and second-entry rows."""
    intersection_summary = _build_intersection_summary(early_runner, formal_rows)
    research_confirmation = _safe_rows(early_runner.get("research_confirmation"))
    lines = [
        f"# BTST 提前预警池（{signal_date_compact}）",
        "",
        "## 定位",
        "",
        "这份文档专门承接方案 A 的 early-runner 观察层，不替代正式 BTST 主计划。",
        "",
    ]
    lines.extend(_render_strategy_threshold_lines(strategy_thresholds, strategy_thresholds_config_path, strategy_thresholds_profile))
    lines.extend([""])
    lines.extend(_render_historical_metric_guide())
    lines.extend(
        [
            "",
            "## 状态",
            "",
        ]
    )
    lines.extend(_render_early_runner_status(early_runner))
    lines.extend(
        [
            "",
        ]
    )
    lines.extend(_render_intersection_highlights(intersection_summary))
    lines.extend(["", "## Priority", ""])
    lines.extend(_stock_bullets(_safe_rows(early_runner.get("priority")), limit=6, include_payoff=True))
    lines.extend(["", "## Watchlist", ""])
    lines.extend(_stock_bullets(_safe_rows(early_runner.get("watchlist")), limit=8, include_payoff=True))
    lines.extend(["", "## Second Entry / Reentry", ""])
    lines.extend(_stock_bullets(_safe_rows(early_runner.get("second_entry")), limit=8, include_payoff=True))
    if research_confirmation:
        lines.extend(["", "## Research Only 确认池", ""])
        lines.append("- 当前是 research_only 板，以下确认票只保留为研究确认，不自动升级为可执行 early-runner 观察票。")
        lines.extend(_stock_bullets(research_confirmation, limit=8, include_payoff=True))
    lines.extend(["", "## 使用原则", ""])
    lines.extend(
        [
            "- 只把它当作补充观察，不把它自动升级成正式交易单。",
            "- 交集票优先看，only early-runner 票只做盘中复审。",
            "- second-entry / reentry 单独管理，不能和普通补充票混成一层。",
            "- 如果 early-runner 板不是当日板，只能参考，不做强结论。",
        ]
    )
    return "\n".join(lines) + "\n"


def _render_early_warning_card_doc(signal_date_compact: str, early_runner: dict[str, Any], formal_rows: list[dict[str, Any]]) -> str:
    """Render the compact early-warning card for quick reading."""
    intersection_summary = _build_intersection_summary(early_runner, formal_rows)
    priority = _safe_rows(early_runner.get("priority"))
    watchlist = _safe_rows(early_runner.get("watchlist"))
    second_entry = _safe_rows(early_runner.get("second_entry"))
    research_confirmation = _safe_rows(early_runner.get("research_confirmation"))
    lines = [
        f"# BTST 提前预警卡（{signal_date_compact}）",
        "",
        f"- early-runner 状态：`{early_runner.get('status')}`。",
        f"- 交集高亮：`{[str(row.get('ticker') or '').strip() for row in _safe_rows(intersection_summary.get('overlap_rows'))[:5]]}`。",
        f"- priority：`{[str(row.get('ticker') or '').strip() for row in priority[:5]]}`。",
        f"- watchlist：`{[str(row.get('ticker') or '').strip() for row in watchlist[:5]]}`。",
        f"- second_entry：`{[str(row.get('ticker') or '').strip() for row in second_entry[:5]]}`。",
        "- 使用顺序：先看正式 BTST，再看交集优先复审，only early-runner 做补充复审，second-entry 单独看回补机会。",
    ]
    if research_confirmation:
        lines.insert(
            6,
            f"- research_only 确认池：`{[str(row.get('ticker') or '').strip() for row in research_confirmation[:5]]}`。",
        )
    return "\n".join(lines) + "\n"


def generate_btst_doc_bundle(
    signal_date: str,
    *,
    reports_root: str | Path = REPORTS_DIR,
    output_dir: str | Path | None = None,
    report_dir: str | Path | None = None,
    refresh_early_runner: bool = True,
    include_extra_warning_docs: bool = True,
    strategy_thresholds_config_path: str | Path | None = None,
    strategy_thresholds_profile: str = DEFAULT_STRATEGY_THRESHOLDS_PROFILE,
) -> dict[str, Any]:
    """Generate the final BTST reading bundle and append scheme-A early-runner sections."""
    signal_date_compact, signal_date_iso = _normalize_signal_date(signal_date)
    resolved_reports_root = Path(reports_root).expanduser().resolve()
    resolved_report_dir = _discover_report_dir(resolved_reports_root, signal_date_iso, report_dir)
    session_summary = _read_json(resolved_report_dir / "session_summary.json")
    followup_paths = dict(session_summary.get("btst_followup") or {})
    brief = _read_json(Path(followup_paths["brief_json"]))
    priority_board = _read_json(Path(followup_paths["priority_board_json"])) if followup_paths.get("priority_board_json") else {}
    rule_report_path = resolved_reports_root / f"btst_full_report_{signal_date_compact}.json"
    rule_report = _read_json(rule_report_path)
    early_runner = _load_early_runner_context(resolved_reports_root, signal_date_iso, refresh=refresh_early_runner)
    resolved_strategy_thresholds = resolve_strategy_thresholds(
        config_path=strategy_thresholds_config_path,
        profile=strategy_thresholds_profile,
    )
    resolved_strategy_thresholds_config_path = _resolve_thresholds_config_path(
        strategy_thresholds_config_path,
        profile=strategy_thresholds_profile,
    )
    selected_rows = _resolve_selected_rows(brief, priority_board)
    watch_rows = _resolve_watch_rows(brief, priority_board)
    opportunity_rows = _resolve_opportunity_rows(brief, priority_board)
    formal_rows = [*selected_rows, *watch_rows, *opportunity_rows]
    intersection_summary = _build_intersection_summary(early_runner, formal_rows)
    target_output_dir = Path(output_dir).expanduser().resolve() if output_dir else (OUTPUTS_DIR / signal_date_compact[:6] / brief.get("next_trade_date", signal_date_iso).replace("-", "")).resolve()
    docs = {
        f"BTST-{signal_date_compact}.md": _render_rule_doc(signal_date_compact, rule_report, brief, priority_board, early_runner, rule_report_path, resolved_report_dir, resolved_strategy_thresholds, resolved_strategy_thresholds_config_path, strategy_thresholds_profile),
        f"BTST-LLM-{signal_date_compact}.md": _render_llm_doc(signal_date_compact, brief, priority_board, session_summary, early_runner, resolved_report_dir, resolved_strategy_thresholds, resolved_strategy_thresholds_config_path, strategy_thresholds_profile),
        f"{signal_date_compact}-两套交易计划通俗说明.md": _render_plain_language_doc(signal_date_compact, brief, priority_board, early_runner),
        f"{signal_date_compact}-两套交易计划论坛短版.md": _render_forum_doc(signal_date_compact, brief, priority_board, early_runner),
        f"BTST-{signal_date_compact}-EXEC-CHECKLIST.md": _render_checklist_doc(signal_date_compact, brief, priority_board, early_runner, resolved_strategy_thresholds, resolved_strategy_thresholds_config_path, strategy_thresholds_profile),
    }
    if include_extra_warning_docs:
        docs[f"BTST-{signal_date_compact}-EARLY-WARNING.md"] = _render_early_warning_doc(signal_date_compact, early_runner, formal_rows, resolved_strategy_thresholds, resolved_strategy_thresholds_config_path, strategy_thresholds_profile)
        docs[f"BTST-{signal_date_compact}-EARLY-WARNING-CARD.md"] = _render_early_warning_card_doc(signal_date_compact, early_runner, formal_rows)
    written_files = []
    for name, content in docs.items():
        target_path = target_output_dir / name
        _write_text(target_path, content)
        written_files.append(target_path.as_posix())
    return {
        "status": "generated",
        "signal_date": signal_date_compact,
        "signal_date_iso": signal_date_iso,
        "report_dir": resolved_report_dir.as_posix(),
        "output_dir": target_output_dir.as_posix(),
        "written_files": written_files,
        "early_runner_status": early_runner.get("status"),
        "early_runner_latest_trade_date": early_runner.get("latest_trade_date"),
        "early_runner_intersection_count": len(_safe_rows(intersection_summary.get("overlap_rows"))),
        "early_runner_only_count": len(_safe_rows(intersection_summary.get("only_early_runner_rows"))),
        "early_runner_second_entry_count": len(_safe_rows(intersection_summary.get("second_entry_rows"))),
        "strategy_thresholds_config_path": resolved_strategy_thresholds_config_path,
        "strategy_thresholds_profile": strategy_thresholds_profile,
        "strategy_thresholds": resolved_strategy_thresholds,
    }


def _build_profile_doc_bundle_comparison(profile_results: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Compare daily BTST bundle outputs across multiple threshold profiles."""
    profiles = [
        {
            "profile": profile,
            "output_dir": result.get("output_dir"),
            "written_file_count": len(list(result.get("written_files") or [])),
            "early_runner_status": result.get("early_runner_status"),
            "intersection_count": int(result.get("early_runner_intersection_count") or 0),
            "only_early_runner_count": int(result.get("early_runner_only_count") or 0),
            "second_entry_count": int(result.get("early_runner_second_entry_count") or 0),
        }
        for profile, result in profile_results.items()
    ]
    ranked_profiles = sorted(
        profiles,
        key=lambda item: (
            int(item.get("intersection_count") or 0),
            -int(item.get("only_early_runner_count") or 0),
            -int(item.get("second_entry_count") or 0),
        ),
        reverse=True,
    )
    recommended_profile = ranked_profiles[0]["profile"] if ranked_profiles else None
    reasons: list[str] = []
    if len(ranked_profiles) >= 2:
        top = ranked_profiles[0]
        runner_up = ranked_profiles[1]
        reasons.append(
            f"`{top['profile']}` 的交集票更多：`{top['intersection_count']}` vs `{runner_up['intersection_count']}`。"
        )
        reasons.append(
            f"`{top['profile']}` 的 only early-runner 更少：`{top['only_early_runner_count']}` vs `{runner_up['only_early_runner_count']}`。"
        )
    return {
        "profiles": sorted(profiles, key=lambda item: str(item["profile"])),
        "recommended_profile": recommended_profile,
        "recommendation_reasons": reasons,
    }


def _render_profile_doc_bundle_comparison_markdown(signal_date_compact: str, comparison: dict[str, Any]) -> str:
    """Render one markdown summary for daily BTST bundle profile comparison."""
    lines = [
        f"# BTST {signal_date_compact} Profile 文档包对照",
        "",
        f"- 推荐 profile：`{comparison.get('recommended_profile') or 'n/a'}`",
        "",
        "## 总览",
        "",
        "| profile | early_runner_status | intersection_count | only_early_runner_count | second_entry_count | written_file_count | output_dir |",
        "| --- | --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for item in list(comparison.get("profiles") or []):
        lines.append(
            f"| {item['profile']} | {item.get('early_runner_status')} | {item.get('intersection_count')} | {item.get('only_early_runner_count')} | {item.get('second_entry_count')} | {item.get('written_file_count')} | {item.get('output_dir')} |"
        )
    lines.extend(["", "## 推荐理由", ""])
    if list(comparison.get("recommendation_reasons") or []):
        for reason in list(comparison.get("recommendation_reasons") or []):
            lines.append(f"- {reason}")
    else:
        lines.append("- 当前样本不足，尚未形成明显 profile 差异。")
    return "\n".join(lines) + "\n"


def _build_profile_doc_bundle_decision_card(comparison: dict[str, Any]) -> dict[str, Any]:
    """Build one compact pre-trade decision card from the daily profile comparison."""
    profiles = list(comparison.get("profiles") or [])
    recommended_profile = comparison.get("recommended_profile")
    recommended = next(
        (item for item in profiles if item.get("profile") == recommended_profile),
        None,
    )
    alternatives = [item for item in profiles if item.get("profile") != recommended_profile]
    challenger = alternatives[0] if alternatives else None
    action_bias = "偏保守执行" if recommended_profile == "conservative" else "偏激进执行"
    return {
        "recommended_profile": recommended_profile,
        "action_bias": action_bias,
        "early_runner_status": recommended.get("early_runner_status") if recommended else None,
        "intersection_count": int(recommended.get("intersection_count") or 0) if recommended else 0,
        "only_early_runner_count": int(recommended.get("only_early_runner_count") or 0) if recommended else 0,
        "second_entry_count": int(recommended.get("second_entry_count") or 0) if recommended else 0,
        "intersection_delta_vs_runner_up": (
            int(recommended.get("intersection_count") or 0) - int(challenger.get("intersection_count") or 0)
            if recommended and challenger
            else 0
        ),
        "only_early_runner_delta_vs_runner_up": (
            int(recommended.get("only_early_runner_count") or 0) - int(challenger.get("only_early_runner_count") or 0)
            if recommended and challenger
            else 0
        ),
        "second_entry_delta_vs_runner_up": (
            int(recommended.get("second_entry_count") or 0) - int(challenger.get("second_entry_count") or 0)
            if recommended and challenger
            else 0
        ),
        "recommendation_reasons": list(comparison.get("recommendation_reasons") or []),
    }


def _render_profile_doc_bundle_decision_card_markdown(signal_date_compact: str, decision_card: dict[str, Any]) -> str:
    """Render one compact pre-trade decision card for fast profile selection."""
    lines = [
        f"# BTST {signal_date_compact} 交易前决策卡",
        "",
        f"- 推荐 profile：`{decision_card.get('recommended_profile') or 'n/a'}`",
        f"- 执行倾向：`{decision_card.get('action_bias') or 'n/a'}`",
        f"- early-runner 状态：`{decision_card.get('early_runner_status') or 'n/a'}`",
        f"- 交集票：`{decision_card.get('intersection_count')}`；相对次优差值：`{decision_card.get('intersection_delta_vs_runner_up'):+d}`",
        f"- only early-runner：`{decision_card.get('only_early_runner_count')}`；相对次优差值：`{decision_card.get('only_early_runner_delta_vs_runner_up'):+d}`",
        f"- second-entry：`{decision_card.get('second_entry_count')}`；相对次优差值：`{decision_card.get('second_entry_delta_vs_runner_up'):+d}`",
        "",
        "## 快速判断",
        "",
    ]
    if list(decision_card.get("recommendation_reasons") or []):
        for reason in list(decision_card.get("recommendation_reasons") or []):
            lines.append(f"- {reason}")
    else:
        lines.append("- 当前样本不足，暂不偏向单一 profile。")
    return "\n".join(lines) + "\n"


def _render_profile_decision_bridge_lines(decision_card: dict[str, Any]) -> list[str]:
    """Render one shared conclusion block that can be injected into final BTST docs."""
    return [
        "## 今日执行倾向",
        "",
        f"- 今日更偏：`{decision_card.get('recommended_profile') or 'n/a'}`，执行倾向：`{decision_card.get('action_bias') or 'n/a'}`。",
        f"- 交集票：`{decision_card.get('intersection_count')}`；相对次优差值：`{int(decision_card.get('intersection_delta_vs_runner_up') or 0):+d}`。",
        f"- only early-runner：`{decision_card.get('only_early_runner_count')}`；相对次优差值：`{int(decision_card.get('only_early_runner_delta_vs_runner_up') or 0):+d}`。",
        f"- second-entry：`{decision_card.get('second_entry_count')}`；相对次优差值：`{int(decision_card.get('second_entry_delta_vs_runner_up') or 0):+d}`。",
    ] + [
        f"- {reason}" for reason in list(decision_card.get("recommendation_reasons") or [])
    ]


def _append_profile_decision_bridge(
    output_dir: Path,
    signal_date_compact: str,
    decision_card: dict[str, Any],
) -> list[str]:
    """Append one shared profile-decision bridge section into the main BTST docs."""
    bridge = "\n" + "\n".join(_render_profile_decision_bridge_lines(decision_card)) + "\n"
    updated_files: list[str] = []
    for file_name in (
        f"BTST-{signal_date_compact}.md",
        f"BTST-LLM-{signal_date_compact}.md",
    ):
        target_path = output_dir / file_name
        if not target_path.exists():
            continue
        original = target_path.read_text(encoding="utf-8")
        if "## 今日执行倾向" in original:
            continue
        target_path.write_text(original.rstrip() + bridge, encoding="utf-8")
        updated_files.append(target_path.as_posix())
    return updated_files


def compare_btst_doc_bundle_profiles(
    signal_date: str,
    *,
    profiles: list[str] | tuple[str, ...],
    reports_root: str | Path = REPORTS_DIR,
    output_dir: str | Path | None = None,
    report_dir: str | Path | None = None,
    refresh_early_runner: bool = True,
    include_extra_warning_docs: bool = True,
) -> dict[str, Any]:
    """Generate daily BTST bundles for multiple profiles and write one comparison report."""
    signal_date_compact, _ = _normalize_signal_date(signal_date)
    resolved_output_dir = Path(output_dir).expanduser().resolve() if output_dir else (OUTPUTS_DIR / signal_date_compact[:6] / f"{signal_date_compact}_profile_compare").resolve()
    resolved_output_dir.mkdir(parents=True, exist_ok=True)
    profile_results: dict[str, dict[str, Any]] = {}
    for profile in profiles:
        profile_output_dir = resolved_output_dir / str(profile)
        profile_results[str(profile)] = generate_btst_doc_bundle(
            signal_date_compact,
            reports_root=reports_root,
            output_dir=profile_output_dir,
            report_dir=report_dir,
            refresh_early_runner=refresh_early_runner,
            include_extra_warning_docs=include_extra_warning_docs,
            strategy_thresholds_profile=str(profile),
        )
    comparison = _build_profile_doc_bundle_comparison(profile_results)
    decision_card = _build_profile_doc_bundle_decision_card(comparison)
    bridge_updated_files: list[str] = []
    for profile, result in profile_results.items():
        bridge_updated_files.extend(
            _append_profile_decision_bridge(
                Path(result["output_dir"]),
                signal_date_compact,
                decision_card,
            )
        )
    json_path = resolved_output_dir / f"{signal_date_compact}-btst-doc-bundle-profile-comparison.json"
    md_path = resolved_output_dir / f"{signal_date_compact}-btst-doc-bundle-profile-comparison.md"
    card_json_path = resolved_output_dir / f"{signal_date_compact}-btst-pretrade-decision-card.json"
    card_md_path = resolved_output_dir / f"{signal_date_compact}-btst-pretrade-decision-card.md"
    payload = {
        "signal_date": signal_date_compact,
        "profiles": list(profiles),
        "comparison": comparison,
        "decision_card": decision_card,
        "bridge_updated_files": bridge_updated_files,
        "profile_results": profile_results,
    }
    _write_text(json_path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    _write_text(md_path, _render_profile_doc_bundle_comparison_markdown(signal_date_compact, comparison))
    _write_text(card_json_path, json.dumps(decision_card, ensure_ascii=False, indent=2) + "\n")
    _write_text(card_md_path, _render_profile_doc_bundle_decision_card_markdown(signal_date_compact, decision_card))
    return {
        "status": "compared",
        "signal_date": signal_date_compact,
        "output_dir": resolved_output_dir.as_posix(),
        "json_path": json_path.as_posix(),
        "md_path": md_path.as_posix(),
        "decision_card_json_path": card_json_path.as_posix(),
        "decision_card_md_path": card_md_path.as_posix(),
        "comparison": comparison,
        "decision_card": decision_card,
        "bridge_updated_files": bridge_updated_files,
        "profile_results": profile_results,
    }


def main() -> None:
    """CLI entrypoint for generating the BTST reading bundle."""
    parser = argparse.ArgumentParser(description="Generate BTST reading docs with scheme-A early-runner sections.")
    parser.add_argument("--signal-date", required=True, help="Signal date in YYYYMMDD or YYYY-MM-DD format.")
    parser.add_argument("--reports-root", default=str(REPORTS_DIR))
    parser.add_argument("--output-dir", default="")
    parser.add_argument("--report-dir", default="")
    parser.add_argument("--no-refresh-early-runner", action="store_true")
    parser.add_argument("--core-only", action="store_true", help="Generate only the 5 canonical BTST docs.")
    parser.add_argument("--strategy-thresholds-config", default="")
    parser.add_argument("--strategy-thresholds-profile", default=DEFAULT_STRATEGY_THRESHOLDS_PROFILE)
    parser.add_argument("--compare-profiles", nargs="*", default=[])
    args = parser.parse_args()
    if list(args.compare_profiles):
        result = compare_btst_doc_bundle_profiles(
            args.signal_date,
            profiles=list(args.compare_profiles),
            reports_root=args.reports_root,
            output_dir=args.output_dir or None,
            report_dir=args.report_dir or None,
            refresh_early_runner=not args.no_refresh_early_runner,
            include_extra_warning_docs=not args.core_only,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    result = generate_btst_doc_bundle(
        args.signal_date,
        reports_root=args.reports_root,
        output_dir=args.output_dir or None,
        report_dir=args.report_dir or None,
        refresh_early_runner=not args.no_refresh_early_runner,
        include_extra_warning_docs=not args.core_only,
        strategy_thresholds_config_path=args.strategy_thresholds_config or None,
        strategy_thresholds_profile=args.strategy_thresholds_profile,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
