from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from scripts.btst_data_utils import round_or_none, safe_float


REPORTS_DIR = Path("data/reports")
DEFAULT_OPPORTUNITY_POOL_REPORT_PATH = REPORTS_DIR / "btst_tradeable_opportunity_pool_march.json"
DEFAULT_OUTPUT_JSON = REPORTS_DIR / "btst_no_candidate_entry_action_board_latest.json"
DEFAULT_OUTPUT_MD = REPORTS_DIR / "btst_no_candidate_entry_action_board_latest.md"
DEFAULT_PRESERVE_TICKERS: tuple[str, ...] = ("300394",)
PRIORITY_QUEUE_LIMIT = 8
WINDOW_HOTSPOT_LIMIT = 6
NEXT_TASK_LIMIT = 3
GLOBAL_SCAN_FOCUS_LIMIT = 5


def _load_json(path: str | Path) -> dict[str, Any]:
    resolved = Path(path).expanduser().resolve()
    return json.loads(resolved.read_text(encoding="utf-8"))


def _slug_token(value: Any) -> str:
    slug = "".join(ch if str(ch).isalnum() else "_" for ch in str(value or "").strip())
    return slug.strip("_") or "unknown"


def _rate(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round(numerator / denominator, 4)


def _row_priority_key(row: dict[str, Any]) -> tuple[float, float, float, str, str]:
    return (
        1.0 if row.get("strict_btst_goal_case") else 0.0,
        float(row.get("t_plus_2_close_return") if row.get("t_plus_2_close_return") is not None else -999.0),
        float(row.get("next_high_return") if row.get("next_high_return") is not None else -999.0),
        str(row.get("trade_date") or ""),
        str(row.get("ticker") or ""),
    )


def _mean_metric(rows: list[dict[str, Any]], key: str) -> float | None:
    values = [
        float(value)
        for value in (safe_float(row.get(key)) for row in rows)
        if value is not None
    ]
    if not values:
        return None
    return round(sum(values) / len(values), 4)


def _primary_report_dir(rows: list[dict[str, Any]]) -> str | None:
    report_dir_counts = Counter(str(row.get("report_dir") or "") for row in rows if str(row.get("report_dir") or "").strip())
    if not report_dir_counts:
        return None
    return report_dir_counts.most_common(1)[0][0]


def _classify_action_tier(*, occurrence_count: int, strict_goal_case_count: int, distinct_report_count: int) -> str:
    if distinct_report_count >= 2 and strict_goal_case_count >= 2:
        return "cross_window_semantic_replay"
    if strict_goal_case_count >= 1:
        return "strict_goal_recall_probe"
    if occurrence_count >= 2:
        return "watchlist_recall_probe"
    return "single_case_monitor"


def _classify_window_action_tier(*, trade_date_count: int, strict_goal_case_count: int) -> str:
    if trade_date_count >= 2 and strict_goal_case_count >= 2:
        return "cross_window_frontier_batch"
    return "single_window_frontier_probe"


def _build_frontier_command(
    report_dir: str | None,
    *,
    focus_tickers: list[str],
    preserve_tickers: list[str],
    output_suffix: str,
) -> str | None:
    if not report_dir or not focus_tickers:
        return None

    command_parts = [
        "python scripts/analyze_btst_candidate_entry_frontier.py",
        f"data/reports/{report_dir}",
    ]
    for ticker in focus_tickers:
        command_parts.append(f"--focus-ticker {ticker}")
    for ticker in preserve_tickers:
        command_parts.append(f"--preserve-ticker {ticker}")
    command_parts.append(f"--output-json data/reports/btst_candidate_entry_frontier_no_entry_{output_suffix}.json")
    command_parts.append(f"--output-md data/reports/btst_candidate_entry_frontier_no_entry_{output_suffix}.md")
    return " ".join(command_parts)


def _build_window_scan_command(*, focus_tickers: list[str], preserve_tickers: list[str]) -> str | None:
    if not focus_tickers:
        return None
    command_parts = [
        "python scripts/analyze_btst_candidate_entry_window_scan.py",
        "--report-root-dirs data/reports",
        "--report-name-contains paper_trading_window",
        f"--focus-tickers {','.join(focus_tickers)}",
    ]
    if preserve_tickers:
        command_parts.append(f"--preserve-tickers {','.join(preserve_tickers)}")
    command_parts.append("--output-json data/reports/btst_candidate_entry_window_scan_no_entry_priority_latest.json")
    command_parts.append("--output-md data/reports/btst_candidate_entry_window_scan_no_entry_priority_latest.md")
    return " ".join(command_parts)


def _build_minimal_rows_from_summary(analysis: dict[str, Any]) -> list[dict[str, Any]]:
    no_candidate_entry_summary = dict(analysis.get("no_candidate_entry_summary") or {})
    trade_date_contexts = dict(analysis.get("trade_date_contexts") or {})
    top_ticker_rows = {
        str(row.get("ticker") or ""): dict(row)
        for row in list(no_candidate_entry_summary.get("top_ticker_rows") or [])
        if str(row.get("ticker") or "").strip()
    }
    strict_goal_threshold = safe_float(dict(analysis.get("thresholds") or {}).get("strict_btst_goal_threshold"))
    strict_goal_threshold = float(strict_goal_threshold) if strict_goal_threshold is not None else 0.05

    rows: list[dict[str, Any]] = []
    for row in list(no_candidate_entry_summary.get("top_priority_rows") or []):
        ticker = str(row.get("ticker") or "")
        trade_date = str(row.get("trade_date") or "")
        context = dict(trade_date_contexts.get(trade_date) or {})
        ticker_summary = dict(top_ticker_rows.get(ticker) or {})
        t_plus_2_close_return = safe_float(row.get("t_plus_2_close_return"))
        rows.append(
            {
                **dict(row),
                "industry": ticker_summary.get("industry"),
                "report_dir": context.get("report_dir"),
                "report_mode": context.get("mode"),
                "report_selection_target": context.get("selection_target"),
                "pool_b_tradeable": True,
                "strict_btst_goal_case": bool(t_plus_2_close_return is not None and t_plus_2_close_return >= strict_goal_threshold),
            }
        )
    return rows


def _collect_no_candidate_rows(analysis: dict[str, Any]) -> list[dict[str, Any]]:
    rows = [
        dict(row)
        for row in list(analysis.get("rows") or [])
        if str(row.get("first_kill_switch") or "") == "no_candidate_entry"
    ]
    if rows:
        return rows
    return _build_minimal_rows_from_summary(analysis)


def _build_priority_queue(no_candidate_rows: list[dict[str, Any]], *, preserve_tickers: list[str]) -> list[dict[str, Any]]:
    ticker_buckets: dict[str, list[dict[str, Any]]] = {}
    for row in no_candidate_rows:
        ticker = str(row.get("ticker") or "").strip()
        if ticker:
            ticker_buckets.setdefault(ticker, []).append(row)

    priority_queue: list[dict[str, Any]] = []
    for ticker, ticker_rows in ticker_buckets.items():
        ticker_rows_sorted = sorted(ticker_rows, key=_row_priority_key, reverse=True)
        lead_row = ticker_rows_sorted[0]
        report_dir_counts = Counter(str(row.get("report_dir") or "") for row in ticker_rows if str(row.get("report_dir") or "").strip())
        trade_dates = sorted({str(row.get("trade_date") or "") for row in ticker_rows if str(row.get("trade_date") or "")})
        distinct_report_count = len(report_dir_counts)
        strict_goal_case_count = sum(1 for row in ticker_rows if row.get("strict_btst_goal_case"))
        action_tier = _classify_action_tier(
            occurrence_count=len(ticker_rows),
            strict_goal_case_count=strict_goal_case_count,
            distinct_report_count=distinct_report_count,
        )
        primary_report_dir = _primary_report_dir(ticker_rows)
        frontier_command = _build_frontier_command(
            primary_report_dir,
            focus_tickers=[ticker],
            preserve_tickers=preserve_tickers,
            output_suffix=f"{_slug_token(ticker)}_{_slug_token(lead_row.get('trade_date'))}",
        )
        why_now = (
            f"{ticker} 在 no_candidate_entry 队列中重复出现 {len(ticker_rows)} 次，"
            f"其中 strict_goal_case={strict_goal_case_count}，且已覆盖 {distinct_report_count} 个 report_dir。"
        )
        if action_tier == "cross_window_semantic_replay":
            why_now += "它已经具备跨窗口语义回放优先级，适合作为 candidate entry selective recall 的焦点票。"
        elif action_tier == "strict_goal_recall_probe":
            why_now += "它至少包含一批严格 BTST 目标命中样本，应优先回看 watchlist recall 漏点。"
        elif action_tier == "watchlist_recall_probe":
            why_now += "它虽未形成严格目标样本簇，但重复出现，仍值得做入口召回探针。"
        else:
            why_now += "它目前更像单案监控样本，不应先放到默认规则升级讨论。"

        priority_queue.append(
            {
                "ticker": ticker,
                "action_tier": action_tier,
                "occurrence_count": len(ticker_rows),
                "strict_goal_case_count": strict_goal_case_count,
                "strict_goal_case_share": _rate(strict_goal_case_count, len(ticker_rows)),
                "distinct_report_count": distinct_report_count,
                "report_dir_counts": {key: int(value) for key, value in report_dir_counts.most_common(3)},
                "primary_report_dir": primary_report_dir,
                "industry": lead_row.get("industry"),
                "latest_trade_date": max(trade_dates) if trade_dates else None,
                "trade_dates": trade_dates,
                "mean_next_high_return": _mean_metric(ticker_rows, "next_high_return"),
                "mean_next_close_return": _mean_metric(ticker_rows, "next_close_return"),
                "mean_t_plus_2_close_return": _mean_metric(ticker_rows, "t_plus_2_close_return"),
                "why_now": why_now,
                "next_step": (
                    f"先用 {ticker} 作为 focus_ticker 重跑 {primary_report_dir or '对应 report_dir'} 的 candidate-entry frontier，"
                    f"验证它是否能在不误伤 {preserve_tickers} 的前提下形成 selective recall 语义。"
                ),
                "frontier_command": frontier_command,
            }
        )

    priority_queue.sort(
        key=lambda row: (
            int(row.get("strict_goal_case_count") or 0),
            int(row.get("distinct_report_count") or 0),
            int(row.get("occurrence_count") or 0),
            float(row.get("mean_t_plus_2_close_return") if row.get("mean_t_plus_2_close_return") is not None else -999.0),
            float(row.get("mean_next_high_return") if row.get("mean_next_high_return") is not None else -999.0),
            str(row.get("ticker") or ""),
        ),
        reverse=True,
    )
    for index, row in enumerate(priority_queue, start=1):
        row["priority_rank"] = index
    return priority_queue[:PRIORITY_QUEUE_LIMIT]


def _build_window_hotspot_rows(no_candidate_rows: list[dict[str, Any]], *, preserve_tickers: list[str]) -> list[dict[str, Any]]:
    report_buckets: dict[str, list[dict[str, Any]]] = {}
    for row in no_candidate_rows:
        report_dir = str(row.get("report_dir") or "").strip()
        if report_dir:
            report_buckets.setdefault(report_dir, []).append(row)

    hotspot_rows: list[dict[str, Any]] = []
    for report_dir, report_rows in report_buckets.items():
        trade_dates = sorted({str(row.get("trade_date") or "") for row in report_rows if str(row.get("trade_date") or "")})
        strict_goal_case_count = sum(1 for row in report_rows if row.get("strict_btst_goal_case"))
        action_tier = _classify_window_action_tier(
            trade_date_count=len(trade_dates),
            strict_goal_case_count=strict_goal_case_count,
        )
        ticker_counts = Counter(str(row.get("ticker") or "") for row in report_rows if str(row.get("ticker") or "").strip())
        industry_counts = Counter(str(row.get("industry") or "unknown") for row in report_rows)
        focus_tickers = [ticker for ticker, _ in ticker_counts.most_common(3)]
        frontier_command = _build_frontier_command(
            report_dir,
            focus_tickers=focus_tickers,
            preserve_tickers=preserve_tickers,
            output_suffix=f"{_slug_token(report_dir)}_batch",
        )
        hotspot_rows.append(
            {
                "report_dir": report_dir,
                "action_tier": action_tier,
                "no_candidate_entry_count": len(report_rows),
                "strict_goal_case_count": strict_goal_case_count,
                "trade_date_count": len(trade_dates),
                "trade_dates": trade_dates,
                "top_focus_tickers": focus_tickers,
                "top_industries": [label for label, _ in industry_counts.most_common(3)],
                "mean_t_plus_2_close_return": _mean_metric(report_rows, "t_plus_2_close_return"),
                "report_modes": {key: int(value) for key, value in Counter(str(row.get("report_mode") or "unknown") for row in report_rows).most_common(3)},
                "selection_targets": {key: int(value) for key, value in Counter(str(row.get("report_selection_target") or "unknown") for row in report_rows).most_common(3)},
                "why_now": (
                    f"{report_dir} 在 {len(trade_dates)} 个 trade_date 上累计出现 {len(report_rows)} 个 no_candidate_entry 样本，"
                    f"其中 strict_goal_case={strict_goal_case_count}。"
                ),
                "next_step": (
                    f"优先回放 {report_dir}，围绕 {focus_tickers} 验证 candidate entry selective semantics，"
                    f"先确认能否在不误伤 {preserve_tickers} 的前提下形成可复用入口语义。"
                ),
                "frontier_command": frontier_command,
            }
        )

    hotspot_rows.sort(
        key=lambda row: (
            int(row.get("strict_goal_case_count") or 0),
            int(row.get("no_candidate_entry_count") or 0),
            int(row.get("trade_date_count") or 0),
            float(row.get("mean_t_plus_2_close_return") if row.get("mean_t_plus_2_close_return") is not None else -999.0),
            str(row.get("report_dir") or ""),
        ),
        reverse=True,
    )
    for index, row in enumerate(hotspot_rows, start=1):
        row["priority_rank"] = index
    return hotspot_rows[:WINDOW_HOTSPOT_LIMIT]


def _build_ticker_task(row: dict[str, Any]) -> dict[str, Any]:
    ticker = str(row.get("ticker") or "")
    return {
        "task_id": f"{ticker}_no_candidate_entry_replay",
        "title": f"回放 {ticker} 的 no-entry 入口语义",
        "action_tier": row.get("action_tier"),
        "why_now": row.get("why_now"),
        "next_step": row.get("next_step"),
        "command": row.get("frontier_command"),
        "acceptance_criteria": [
            "focus_ticker 能在 candidate-entry frontier 中被 selective 过滤或解释性命中",
            "preserve_ticker 不出现误伤",
            "若仅单窗有效，结论只进入 shadow backlog，不升级默认入口",
        ],
    }


def _build_window_task(row: dict[str, Any], *, window_scan_command: str | None) -> dict[str, Any]:
    report_dir = str(row.get("report_dir") or "")
    return {
        "task_id": f"{_slug_token(report_dir)}_no_candidate_entry_window_batch",
        "title": f"批量回放 {report_dir} 的 no-entry 热点窗口",
        "action_tier": row.get("action_tier"),
        "why_now": row.get("why_now"),
        "next_step": row.get("next_step"),
        "command": row.get("frontier_command") or window_scan_command,
        "acceptance_criteria": [
            "热点窗口至少形成一个可解释的 focus_ticker 过滤命中",
            "窗口批量回放不误伤 preserve_ticker",
            "若形成跨窗口重复命中，再接回 candidate-entry governance 做 shadow-only 审查",
        ],
    }


def _build_next_3_tasks(
    priority_queue: list[dict[str, Any]],
    window_hotspot_rows: list[dict[str, Any]],
    *,
    window_scan_command: str | None,
) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    for row in priority_queue[:2]:
        tasks.append(_build_ticker_task(row))
    if window_hotspot_rows:
        tasks.append(_build_window_task(window_hotspot_rows[0], window_scan_command=window_scan_command))
    elif len(priority_queue) >= 3:
        tasks.append(_build_ticker_task(priority_queue[2]))
    return tasks[:NEXT_TASK_LIMIT]


def analyze_btst_no_candidate_entry_action_board(
    opportunity_pool_report_path: str | Path,
    *,
    preserve_tickers: list[str] | None = None,
) -> dict[str, Any]:
    analysis = _load_json(opportunity_pool_report_path)
    resolved_report_path = Path(opportunity_pool_report_path).expanduser().resolve()
    resolved_reports_root = Path(analysis.get("reports_root") or resolved_report_path.parent).expanduser().resolve()
    preserve_ticker_list = [ticker for ticker in list(preserve_tickers or DEFAULT_PRESERVE_TICKERS) if str(ticker or "").strip()]

    no_candidate_rows = _collect_no_candidate_rows(analysis)
    priority_queue = _build_priority_queue(no_candidate_rows, preserve_tickers=preserve_ticker_list)
    window_hotspot_rows = _build_window_hotspot_rows(no_candidate_rows, preserve_tickers=preserve_ticker_list)
    top_priority_tickers = [str(row.get("ticker") or "") for row in priority_queue[:3] if row.get("ticker")]
    top_hotspot_report_dirs = [str(row.get("report_dir") or "") for row in window_hotspot_rows[:3] if row.get("report_dir")]
    window_scan_command = _build_window_scan_command(
        focus_tickers=[ticker for ticker in top_priority_tickers[:GLOBAL_SCAN_FOCUS_LIMIT] if ticker],
        preserve_tickers=preserve_ticker_list,
    )
    next_3_tasks = _build_next_3_tasks(priority_queue, window_hotspot_rows, window_scan_command=window_scan_command)

    no_candidate_entry_count = int(dict(analysis.get("no_candidate_entry_summary") or {}).get("count") or len(no_candidate_rows))
    tradeable_opportunity_pool_count = int(analysis.get("tradeable_opportunity_pool_count") or 0)
    no_candidate_entry_share = round_or_none(safe_float(dict(analysis.get("no_candidate_entry_summary") or {}).get("share_of_tradeable_pool")))
    recommendation = (
        f"当前 no_candidate_entry backlog 占 tradeable pool 的 {no_candidate_entry_share}，"
        f"应优先围绕 {top_priority_tickers or ['无']} 和 {top_hotspot_report_dirs or ['无']} 做 candidate entry replay / window scan，"
        "先补 watchlist recall 与 selective semantics，再决定是否需要继续推进其他入口治理动作。"
    )
    if not priority_queue:
        recommendation = "当前没有可执行的 no_candidate_entry backlog，候选入口行动板为空。"

    rerun_commands = [
        command
        for command in [
            *(row.get("frontier_command") for row in priority_queue[:2]),
            *(row.get("frontier_command") for row in window_hotspot_rows[:1]),
            window_scan_command,
        ]
        if command
    ]

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "opportunity_pool_report": resolved_report_path.as_posix(),
        "reports_root": resolved_reports_root.as_posix(),
        "tradeable_opportunity_pool_count": tradeable_opportunity_pool_count,
        "no_candidate_entry_count": no_candidate_entry_count,
        "no_candidate_entry_share_of_tradeable_pool": no_candidate_entry_share,
        "preserve_tickers": preserve_ticker_list,
        "priority_queue_count": len(priority_queue),
        "window_hotspot_count": len(window_hotspot_rows),
        "top_priority_tickers": top_priority_tickers,
        "top_hotspot_report_dirs": top_hotspot_report_dirs,
        "priority_queue": priority_queue,
        "window_hotspot_rows": window_hotspot_rows,
        "next_3_tasks": next_3_tasks,
        "window_scan_command": window_scan_command,
        "rerun_commands": rerun_commands,
        "keep_guardrails": [
            "先补 candidate entry recall，不要因为 no_candidate_entry backlog 大就直接放松 score frontier。",
            f"preserve_tickers={preserve_ticker_list} 仍必须保持 0 误伤。",
            "跨窗口重复票优先进入回放与 shadow-only 审查，单窗个案不得直接升级默认入口。",
        ],
        "recommendation": recommendation,
    }


def render_btst_no_candidate_entry_action_board_markdown(analysis: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# BTST No Candidate Entry Action Board")
    lines.append("")
    lines.append("## Overview")
    lines.append(f"- no_candidate_entry_count: {analysis.get('no_candidate_entry_count')}")
    lines.append(f"- tradeable_opportunity_pool_count: {analysis.get('tradeable_opportunity_pool_count')}")
    lines.append(f"- no_candidate_entry_share_of_tradeable_pool: {analysis.get('no_candidate_entry_share_of_tradeable_pool')}")
    lines.append(f"- top_priority_tickers: {analysis.get('top_priority_tickers')}")
    lines.append(f"- top_hotspot_report_dirs: {analysis.get('top_hotspot_report_dirs')}")
    lines.append(f"- recommendation: {analysis.get('recommendation')}")
    lines.append("")
    lines.append("## Priority Queue")
    for row in list(analysis.get("priority_queue") or []):
        lines.append(
            f"- rank={row.get('priority_rank')} ticker={row.get('ticker')} action_tier={row.get('action_tier')} strict_goal_case_count={row.get('strict_goal_case_count')} occurrence_count={row.get('occurrence_count')} distinct_report_count={row.get('distinct_report_count')} latest_trade_date={row.get('latest_trade_date')}"
        )
        lines.append(f"  why_now: {row.get('why_now')}")
        lines.append(f"  next_step: {row.get('next_step')}")
    if not list(analysis.get("priority_queue") or []):
        lines.append("- none")
    lines.append("")
    lines.append("## Window Hotspots")
    for row in list(analysis.get("window_hotspot_rows") or []):
        lines.append(
            f"- rank={row.get('priority_rank')} report_dir={row.get('report_dir')} action_tier={row.get('action_tier')} no_candidate_entry_count={row.get('no_candidate_entry_count')} strict_goal_case_count={row.get('strict_goal_case_count')} trade_date_count={row.get('trade_date_count')} top_focus_tickers={row.get('top_focus_tickers')}"
        )
        lines.append(f"  why_now: {row.get('why_now')}")
        lines.append(f"  next_step: {row.get('next_step')}")
    if not list(analysis.get("window_hotspot_rows") or []):
        lines.append("- none")
    lines.append("")
    lines.append("## Immediate Next 3")
    for task in list(analysis.get("next_3_tasks") or []):
        lines.append(f"- {task.get('task_id')}: {task.get('title')}")
        lines.append(f"  why_now: {task.get('why_now')}")
        lines.append(f"  next_step: {task.get('next_step')}")
    if not list(analysis.get("next_3_tasks") or []):
        lines.append("- none")
    lines.append("")
    lines.append("## Guardrails")
    for item in list(analysis.get("keep_guardrails") or []):
        lines.append(f"- {item}")
    lines.append("")
    lines.append("## Rerun Commands")
    for item in list(analysis.get("rerun_commands") or []):
        lines.append(f"- {item}")
    if not list(analysis.get("rerun_commands") or []):
        lines.append("- none")
    lines.append("")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a no-candidate-entry action board from the BTST tradeable opportunity pool report.")
    parser.add_argument("--opportunity-pool-report", default=str(DEFAULT_OPPORTUNITY_POOL_REPORT_PATH))
    parser.add_argument("--preserve-ticker", action="append", default=[], help="Ticker that must not be misfiltered when replaying candidate-entry recall semantics.")
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--output-md", default=str(DEFAULT_OUTPUT_MD))
    args = parser.parse_args()

    preserve_tickers = list(args.preserve_ticker) or list(DEFAULT_PRESERVE_TICKERS)
    analysis = analyze_btst_no_candidate_entry_action_board(
        args.opportunity_pool_report,
        preserve_tickers=preserve_tickers,
    )
    output_json = Path(args.output_json).expanduser().resolve()
    output_md = Path(args.output_md).expanduser().resolve()
    output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_md.write_text(render_btst_no_candidate_entry_action_board_markdown(analysis), encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()