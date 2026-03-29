from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from src.tools.tushare_api import _cached_tushare_dataframe_call, _get_pro


def _load_json(path: str | Path) -> dict[str, Any]:
    resolved = Path(path).expanduser().resolve()
    return json.loads(resolved.read_text(encoding="utf-8"))


def _write_json(path: str | Path, payload: dict[str, Any]) -> None:
    resolved = Path(path).expanduser().resolve()
    resolved.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _resolve_followup_trade_dates(
    trade_date: str | None,
    next_trade_date: str | None,
    brief_json_path: str | Path,
    card_json_path: str | Path,
) -> tuple[str | None, str | None]:
    normalized_trade_date = _normalize_trade_date(trade_date)
    normalized_next_trade_date = _normalize_trade_date(next_trade_date)
    if normalized_trade_date and normalized_next_trade_date:
        return normalized_trade_date, normalized_next_trade_date

    brief_payload = _load_json(brief_json_path)
    card_payload = _load_json(card_json_path)
    return (
        normalized_trade_date or _normalize_trade_date(brief_payload.get("trade_date") or card_payload.get("trade_date")),
        normalized_next_trade_date or _normalize_trade_date(brief_payload.get("next_trade_date") or card_payload.get("next_trade_date")),
    )


def _format_float(value: Any, digits: int = 4) -> str:
    if isinstance(value, (int, float)):
        return f"{value:.{digits}f}"
    return "n/a"


def _normalize_trade_date(value: str | None) -> str | None:
    if not value:
        return None
    if "-" in value:
        return value
    if len(value) == 8:
        return f"{value[:4]}-{value[4:6]}-{value[6:8]}"
    return value


def _compact_trade_date(value: str | None) -> str | None:
    normalized = _normalize_trade_date(value)
    return normalized.replace("-", "") if normalized else None


def _fallback_next_weekday(trade_date: str | None) -> str | None:
    normalized = _normalize_trade_date(trade_date)
    if not normalized:
        return None
    cursor = datetime.strptime(normalized, "%Y-%m-%d") + timedelta(days=1)
    while cursor.weekday() >= 5:
        cursor += timedelta(days=1)
    return cursor.strftime("%Y-%m-%d")


def infer_next_trade_date(trade_date: str | None, lookahead_days: int = 14) -> str | None:
    normalized = _normalize_trade_date(trade_date)
    if not normalized:
        return None

    pro = _get_pro()
    if pro is None:
        return _fallback_next_weekday(normalized)

    start_date = (datetime.strptime(normalized, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y%m%d")
    end_date = (datetime.strptime(normalized, "%Y-%m-%d") + timedelta(days=lookahead_days)).strftime("%Y%m%d")

    try:
        df = _cached_tushare_dataframe_call(
            pro,
            "trade_cal",
            exchange="",
            start_date=start_date,
            end_date=end_date,
            is_open=1,
            fields="cal_date,is_open",
        )
    except Exception:
        df = None

    if df is not None and not df.empty:
        candidate_dates = sorted(_normalize_trade_date(str(value)) for value in df["cal_date"].tolist())
        if candidate_dates:
            return candidate_dates[0]
    return _fallback_next_weekday(normalized)


def _resolve_snapshot_path(input_path: str | Path, trade_date: str | None) -> tuple[Path, Path]:
    resolved_input = Path(input_path).expanduser().resolve()

    if resolved_input.is_file():
        if resolved_input.name != "selection_snapshot.json":
            raise ValueError("input_path must be a report directory or a selection_snapshot.json file")
        return resolved_input, resolved_input.parents[2]

    if not resolved_input.is_dir():
        raise FileNotFoundError(f"Input path does not exist: {resolved_input}")

    artifacts_dir = resolved_input / "selection_artifacts"
    if not artifacts_dir.exists():
        raise FileNotFoundError(f"selection_artifacts directory not found under: {resolved_input}")

    normalized_trade_date = _normalize_trade_date(trade_date)
    if normalized_trade_date:
        candidate = artifacts_dir / normalized_trade_date / "selection_snapshot.json"
        if not candidate.exists():
            raise FileNotFoundError(f"selection_snapshot.json not found for trade_date={normalized_trade_date}: {candidate}")
        return candidate, resolved_input

    trade_date_dirs = sorted(path for path in artifacts_dir.iterdir() if path.is_dir())
    if not trade_date_dirs:
        raise FileNotFoundError(f"No trade_date directories found under: {artifacts_dir}")
    latest_trade_dir = trade_date_dirs[-1]
    candidate = latest_trade_dir / "selection_snapshot.json"
    if not candidate.exists():
        raise FileNotFoundError(f"selection_snapshot.json not found under latest trade_date directory: {candidate}")
    return candidate, resolved_input


def _extract_short_trade_entry(selection_entry: dict[str, Any]) -> dict[str, Any] | None:
    short_trade_entry = selection_entry.get("short_trade") or {}
    decision = short_trade_entry.get("decision")
    if decision not in {"selected", "near_miss"}:
        return None

    metrics_payload = short_trade_entry.get("metrics_payload") or {}
    explainability_payload = short_trade_entry.get("explainability_payload") or {}

    return {
        "ticker": selection_entry.get("ticker"),
        "decision": decision,
        "score_target": short_trade_entry.get("score_target"),
        "confidence": short_trade_entry.get("confidence"),
        "rank_hint": short_trade_entry.get("rank_hint"),
        "preferred_entry_mode": short_trade_entry.get("preferred_entry_mode"),
        "positive_tags": list(short_trade_entry.get("positive_tags") or []),
        "top_reasons": list(short_trade_entry.get("top_reasons") or []),
        "candidate_source": explainability_payload.get("candidate_source") or selection_entry.get("candidate_source"),
        "gate_status": dict(short_trade_entry.get("gate_status") or {}),
        "metrics": {
            "breakout_freshness": metrics_payload.get("breakout_freshness"),
            "trend_acceleration": metrics_payload.get("trend_acceleration"),
            "volume_expansion_quality": metrics_payload.get("volume_expansion_quality"),
            "close_strength": metrics_payload.get("close_strength"),
            "catalyst_freshness": metrics_payload.get("catalyst_freshness"),
        },
    }


def _extract_excluded_research_entry(selection_entry: dict[str, Any]) -> dict[str, Any] | None:
    research_entry = selection_entry.get("research") or {}
    short_trade_entry = selection_entry.get("short_trade") or {}
    if research_entry.get("decision") != "selected":
        return None
    if short_trade_entry.get("decision") in {"selected", "near_miss"}:
        return None

    return {
        "ticker": selection_entry.get("ticker"),
        "research_score_target": research_entry.get("score_target"),
        "short_trade_decision": short_trade_entry.get("decision"),
        "short_trade_score_target": short_trade_entry.get("score_target"),
        "preferred_entry_mode": short_trade_entry.get("preferred_entry_mode"),
        "delta_summary": list(selection_entry.get("delta_summary") or []),
    }


def _summary_value(summary: dict[str, Any], key: str, fallback: int) -> int:
    value = summary.get(key)
    return fallback if value is None else value


def analyze_btst_next_day_trade_brief(input_path: str | Path, trade_date: str | None = None, next_trade_date: str | None = None) -> dict[str, Any]:
    snapshot_path, report_dir = _resolve_snapshot_path(input_path, trade_date)
    snapshot = _load_json(snapshot_path)

    session_summary_path = report_dir / "session_summary.json"
    session_summary = _load_json(session_summary_path) if session_summary_path.exists() else {}

    selection_targets = snapshot.get("selection_targets") or {}
    short_trade_entries = [
        candidate
        for candidate in (_extract_short_trade_entry(entry) for entry in selection_targets.values())
        if candidate is not None
    ]
    short_trade_entries.sort(key=lambda entry: (0 if entry["decision"] == "selected" else 1, -(entry.get("score_target") or 0.0), entry.get("ticker") or ""))

    selected_entries = [entry for entry in short_trade_entries if entry["decision"] == "selected"]
    near_miss_entries = [entry for entry in short_trade_entries if entry["decision"] == "near_miss"]

    excluded_research_entries = [
        candidate
        for candidate in (_extract_excluded_research_entry(entry) for entry in selection_targets.values())
        if candidate is not None
    ]
    excluded_research_entries.sort(key=lambda entry: (-(entry.get("research_score_target") or 0.0), entry.get("ticker") or ""))

    dual_target_summary = snapshot.get("dual_target_summary") or {}
    actual_trade_date = _normalize_trade_date(snapshot.get("trade_date") or trade_date)
    primary_entry = selected_entries[0] if selected_entries else None
    short_trade_decisions = [
        (entry.get("short_trade") or {}).get("decision")
        for entry in selection_targets.values()
        if entry.get("short_trade")
    ]
    blocked_count = sum(1 for decision in short_trade_decisions if decision == "blocked")
    rejected_count = sum(1 for decision in short_trade_decisions if decision == "rejected")
    research_selected_count = sum(
        1 for entry in selection_targets.values() if (entry.get("research") or {}).get("decision") == "selected"
    )

    recommendation_lines: list[str] = []
    if primary_entry:
        recommendation_lines.append(
            f"主入场票为 {primary_entry['ticker']}，应按 {primary_entry['preferred_entry_mode']} 执行，而不是把它视为无条件开盘追价。"
        )
    else:
        recommendation_lines.append("本次 short-trade 没有正式 selected 样本，不建议把 near_miss 直接当成主入场票。")
    if near_miss_entries:
        recommendation_lines.append(
            "备选观察票为 " + ", ".join(entry["ticker"] for entry in near_miss_entries) + "，仅适合作为盘中跟踪对象。"
        )
    if excluded_research_entries:
        recommendation_lines.append(
            "research 侧已选中但不属于本次 short-trade 执行名单的股票有 "
            + ", ".join(entry["ticker"] for entry in excluded_research_entries)
            + "。"
        )

    return {
        "report_dir": str(report_dir),
        "snapshot_path": str(snapshot_path),
        "session_summary_path": str(session_summary_path) if session_summary_path.exists() else None,
        "trade_date": actual_trade_date,
        "next_trade_date": _normalize_trade_date(next_trade_date),
        "target_mode": snapshot.get("target_mode"),
        "selection_target": (session_summary.get("plan_generation") or {}).get("selection_target") or snapshot.get("target_mode"),
        "summary": {
            "selection_target_count": _summary_value(dual_target_summary, "selection_target_count", len(selection_targets)),
            "short_trade_selected_count": _summary_value(dual_target_summary, "short_trade_selected_count", len(selected_entries)),
            "short_trade_near_miss_count": _summary_value(dual_target_summary, "short_trade_near_miss_count", len(near_miss_entries)),
            "short_trade_blocked_count": _summary_value(dual_target_summary, "short_trade_blocked_count", blocked_count),
            "short_trade_rejected_count": _summary_value(dual_target_summary, "short_trade_rejected_count", rejected_count),
            "research_selected_count": _summary_value(dual_target_summary, "research_selected_count", research_selected_count),
        },
        "primary_entry": primary_entry,
        "selected_entries": selected_entries,
        "near_miss_entries": near_miss_entries,
        "excluded_research_entries": excluded_research_entries,
        "recommendation": " ".join(recommendation_lines),
    }


def render_btst_next_day_trade_brief_markdown(analysis: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# BTST Next-Day Trade Brief")
    lines.append("")
    lines.append("## Overview")
    lines.append(f"- trade_date: {analysis.get('trade_date')}")
    lines.append(f"- next_trade_date: {analysis.get('next_trade_date') or 'n/a'}")
    lines.append(f"- target_mode: {analysis.get('target_mode')}")
    lines.append(f"- selection_target: {analysis.get('selection_target')}")
    lines.append(f"- short_trade_selected_count: {analysis['summary'].get('short_trade_selected_count')}")
    lines.append(f"- short_trade_near_miss_count: {analysis['summary'].get('short_trade_near_miss_count')}")
    lines.append(f"- short_trade_blocked_count: {analysis['summary'].get('short_trade_blocked_count')}")
    lines.append(f"- short_trade_rejected_count: {analysis['summary'].get('short_trade_rejected_count')}")
    lines.append(f"- excluded_research_selected_count: {len(analysis.get('excluded_research_entries') or [])}")
    lines.append("")
    lines.append("## Recommendation")
    lines.append(f"- {analysis.get('recommendation')}")
    lines.append("")

    for section_title, entries in (
        ("Selected Entries", analysis.get("selected_entries") or []),
        ("Near-Miss Watchlist", analysis.get("near_miss_entries") or []),
    ):
        lines.append(f"## {section_title}")
        if not entries:
            lines.append("- none")
            lines.append("")
            continue
        for entry in entries:
            lines.append(f"### {entry['ticker']}")
            lines.append(f"- decision: {entry['decision']}")
            lines.append(f"- score_target: {_format_float(entry.get('score_target'))}")
            lines.append(f"- confidence: {_format_float(entry.get('confidence'))}")
            lines.append(f"- preferred_entry_mode: {entry.get('preferred_entry_mode')}")
            lines.append(f"- candidate_source: {entry.get('candidate_source')}")
            lines.append(f"- top_reasons: {', '.join(entry.get('top_reasons') or []) or 'n/a'}")
            lines.append(f"- positive_tags: {', '.join(entry.get('positive_tags') or []) or 'n/a'}")
            lines.append(
                "- key_metrics: "
                + ", ".join(
                    [
                        f"breakout={_format_float((entry.get('metrics') or {}).get('breakout_freshness'))}",
                        f"trend={_format_float((entry.get('metrics') or {}).get('trend_acceleration'))}",
                        f"volume={_format_float((entry.get('metrics') or {}).get('volume_expansion_quality'))}",
                        f"close={_format_float((entry.get('metrics') or {}).get('close_strength'))}",
                        f"catalyst={_format_float((entry.get('metrics') or {}).get('catalyst_freshness'))}",
                    ]
                )
            )
            lines.append("- gate_status: " + ", ".join(f"{key}={value}" for key, value in (entry.get("gate_status") or {}).items()))
            lines.append("")

    lines.append("## Research Picks Excluded From Short-Trade Brief")
    excluded_research_entries = analysis.get("excluded_research_entries") or []
    if not excluded_research_entries:
        lines.append("- none")
        lines.append("")
    else:
        for entry in excluded_research_entries:
            lines.append(f"### {entry['ticker']}")
            lines.append(f"- research_score_target: {_format_float(entry.get('research_score_target'))}")
            lines.append(f"- short_trade_decision: {entry.get('short_trade_decision')}")
            lines.append(f"- short_trade_score_target: {_format_float(entry.get('short_trade_score_target'))}")
            lines.append(f"- preferred_entry_mode: {entry.get('preferred_entry_mode')}")
            lines.append(f"- delta_summary: {', '.join(entry.get('delta_summary') or []) or 'n/a'}")
            lines.append("")

    lines.append("## Source Paths")
    lines.append(f"- report_dir: {analysis.get('report_dir')}")
    lines.append(f"- snapshot_path: {analysis.get('snapshot_path')}")
    lines.append(f"- session_summary_path: {analysis.get('session_summary_path') or 'n/a'}")
    return "\n".join(lines) + "\n"


def _resolve_brief_analysis(input_path: str | Path | dict[str, Any], trade_date: str | None, next_trade_date: str | None) -> dict[str, Any]:
    if isinstance(input_path, dict):
        return input_path

    resolved_input = Path(input_path).expanduser().resolve()
    if resolved_input.is_file():
        payload = _load_json(resolved_input)
        if "selected_entries" in payload and "near_miss_entries" in payload:
            if next_trade_date and not payload.get("next_trade_date"):
                payload["next_trade_date"] = _normalize_trade_date(next_trade_date)
            return payload
    return analyze_btst_next_day_trade_brief(resolved_input, trade_date=trade_date, next_trade_date=next_trade_date)


def _selected_action_posture(preferred_entry_mode: str | None) -> tuple[str, list[str]]:
    if preferred_entry_mode == "next_day_breakout_confirmation":
        return (
            "confirm_then_enter",
            [
                "只在盘中出现 breakout confirmation 时考虑执行，不做无确认追价。",
                "若盘中强度无法延续或突破失败，则直接放弃当日入场。",
            ],
        )
    return (
        "manual_review",
        [
            "当前 entry mode 不是标准 breakout confirmation，开盘前应先人工复核。",
        ],
    )


def analyze_btst_premarket_execution_card(input_path: str | Path | dict[str, Any], trade_date: str | None = None, next_trade_date: str | None = None) -> dict[str, Any]:
    brief = _resolve_brief_analysis(input_path, trade_date=trade_date, next_trade_date=next_trade_date)
    primary_entry = brief.get("primary_entry")
    primary_action = None
    if primary_entry:
        posture, trigger_rules = _selected_action_posture(primary_entry.get("preferred_entry_mode"))
        primary_action = {
            "ticker": primary_entry.get("ticker"),
            "action_tier": "primary_entry",
            "execution_posture": posture,
            "preferred_entry_mode": primary_entry.get("preferred_entry_mode"),
            "trigger_rules": trigger_rules,
            "avoid_rules": [
                "不把 near-miss 或 research-only 股票并入主执行名单。",
                "不因为开盘情绪强就跳过 breakout confirmation。",
            ],
            "evidence": list(primary_entry.get("top_reasons") or []),
            "positive_tags": list(primary_entry.get("positive_tags") or []),
            "metrics": dict(primary_entry.get("metrics") or {}),
        }

    watch_actions = []
    for entry in brief.get("near_miss_entries") or []:
        watch_actions.append(
            {
                "ticker": entry.get("ticker"),
                "action_tier": "watch_only",
                "execution_posture": "observe_only",
                "preferred_entry_mode": entry.get("preferred_entry_mode"),
                "trigger_rules": [
                    "仅做盘中强度跟踪，不预设主买入动作。",
                    "若当日需要转为可执行对象，应先回看 short-trade score 与盘中确认信号。",
                ],
                "avoid_rules": [
                    "near_miss 不能与 selected 同级表达。",
                    "没有新增确认前，不把它视为默认替补主票。",
                ],
                "evidence": list(entry.get("top_reasons") or []),
                "metrics": dict(entry.get("metrics") or {}),
            }
        )

    return {
        "trade_date": brief.get("trade_date"),
        "next_trade_date": brief.get("next_trade_date"),
        "selection_target": brief.get("selection_target"),
        "summary": brief.get("summary") or {},
        "recommendation": brief.get("recommendation"),
        "primary_action": primary_action,
        "watch_actions": watch_actions,
        "excluded_research_entries": list(brief.get("excluded_research_entries") or []),
        "global_guardrails": [
            "主执行名单只认 short-trade selected，不把 research selected 自动等价成短线可交易票。",
            "near-miss 默认只做观察，不预设与主票同级的买入动作。",
            "若 selected 当日没有出现确认信号，则允许空仓而不是强行交易。",
        ],
        "source_paths": {
            "report_dir": brief.get("report_dir"),
            "snapshot_path": brief.get("snapshot_path"),
            "session_summary_path": brief.get("session_summary_path"),
        },
    }


def render_btst_premarket_execution_card_markdown(card: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# BTST Premarket Execution Card")
    lines.append("")
    lines.append("## Overview")
    lines.append(f"- trade_date: {card.get('trade_date')}")
    lines.append(f"- next_trade_date: {card.get('next_trade_date') or 'n/a'}")
    lines.append(f"- selection_target: {card.get('selection_target')}")
    lines.append(f"- recommendation: {card.get('recommendation')}")
    lines.append("")

    primary_action = card.get("primary_action")
    lines.append("## Primary Action")
    if not primary_action:
        lines.append("- none")
        lines.append("")
    else:
        lines.append(f"- ticker: {primary_action.get('ticker')}")
        lines.append(f"- action_tier: {primary_action.get('action_tier')}")
        lines.append(f"- execution_posture: {primary_action.get('execution_posture')}")
        lines.append(f"- preferred_entry_mode: {primary_action.get('preferred_entry_mode')}")
        lines.append(f"- evidence: {', '.join(primary_action.get('evidence') or []) or 'n/a'}")
        lines.append("- trigger_rules:")
        for item in primary_action.get("trigger_rules") or []:
            lines.append(f"  - {item}")
        lines.append("- avoid_rules:")
        for item in primary_action.get("avoid_rules") or []:
            lines.append(f"  - {item}")
        lines.append("")

    lines.append("## Watchlist Actions")
    watch_actions = card.get("watch_actions") or []
    if not watch_actions:
        lines.append("- none")
        lines.append("")
    else:
        for entry in watch_actions:
            lines.append(f"### {entry.get('ticker')}")
            lines.append(f"- action_tier: {entry.get('action_tier')}")
            lines.append(f"- execution_posture: {entry.get('execution_posture')}")
            lines.append(f"- preferred_entry_mode: {entry.get('preferred_entry_mode')}")
            lines.append(f"- evidence: {', '.join(entry.get('evidence') or []) or 'n/a'}")
            lines.append("- trigger_rules:")
            for item in entry.get("trigger_rules") or []:
                lines.append(f"  - {item}")
            lines.append("- avoid_rules:")
            for item in entry.get("avoid_rules") or []:
                lines.append(f"  - {item}")
            lines.append("")

    lines.append("## Explicit Non-Trades")
    excluded_entries = card.get("excluded_research_entries") or []
    if not excluded_entries:
        lines.append("- none")
        lines.append("")
    else:
        for entry in excluded_entries:
            lines.append(
                f"- {entry.get('ticker')}: research selected, but short_trade={entry.get('short_trade_decision')} so it stays outside the short-trade execution list."
            )
        lines.append("")

    lines.append("## Global Guardrails")
    for item in card.get("global_guardrails") or []:
        lines.append(f"- {item}")
    lines.append("")
    lines.append("## Source Paths")
    source_paths = card.get("source_paths") or {}
    lines.append(f"- report_dir: {source_paths.get('report_dir')}")
    lines.append(f"- snapshot_path: {source_paths.get('snapshot_path')}")
    lines.append(f"- session_summary_path: {source_paths.get('session_summary_path')}")
    return "\n".join(lines) + "\n"


def _build_output_file_stem(prefix: str, trade_date: str | None, next_trade_date: str | None) -> str:
    compact_trade_date = _compact_trade_date(trade_date) or "unknown"
    compact_next_trade_date = _compact_trade_date(next_trade_date) or "unknown"
    return f"{prefix}_{compact_trade_date}_for_{compact_next_trade_date}"


def generate_btst_next_day_trade_brief_artifacts(
    input_path: str | Path,
    output_dir: str | Path,
    trade_date: str | None = None,
    next_trade_date: str | None = None,
    file_stem: str | None = None,
) -> dict[str, Any]:
    analysis = analyze_btst_next_day_trade_brief(input_path=input_path, trade_date=trade_date, next_trade_date=next_trade_date)
    resolved_output_dir = Path(output_dir).expanduser().resolve()
    resolved_output_dir.mkdir(parents=True, exist_ok=True)
    stem = file_stem or _build_output_file_stem("btst_next_day_trade_brief", analysis.get("trade_date"), analysis.get("next_trade_date"))
    output_json = resolved_output_dir / f"{stem}.json"
    output_md = resolved_output_dir / f"{stem}.md"
    output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_md.write_text(render_btst_next_day_trade_brief_markdown(analysis), encoding="utf-8")
    return {
        "analysis": analysis,
        "json_path": str(output_json),
        "markdown_path": str(output_md),
    }


def generate_btst_premarket_execution_card_artifacts(
    input_path: str | Path | dict[str, Any],
    output_dir: str | Path,
    trade_date: str | None = None,
    next_trade_date: str | None = None,
    file_stem: str | None = None,
) -> dict[str, Any]:
    card = analyze_btst_premarket_execution_card(input_path=input_path, trade_date=trade_date, next_trade_date=next_trade_date)
    resolved_output_dir = Path(output_dir).expanduser().resolve()
    resolved_output_dir.mkdir(parents=True, exist_ok=True)
    stem = file_stem or _build_output_file_stem("btst_premarket_execution_card", card.get("trade_date"), card.get("next_trade_date"))
    output_json = resolved_output_dir / f"{stem}.json"
    output_md = resolved_output_dir / f"{stem}.md"
    output_json.write_text(json.dumps(card, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_md.write_text(render_btst_premarket_execution_card_markdown(card), encoding="utf-8")
    return {
        "analysis": card,
        "json_path": str(output_json),
        "markdown_path": str(output_md),
    }


def register_btst_followup_artifacts(
    report_dir: str | Path,
    *,
    trade_date: str | None,
    next_trade_date: str | None,
    brief_json_path: str | Path,
    brief_markdown_path: str | Path,
    card_json_path: str | Path,
    card_markdown_path: str | Path,
) -> dict[str, Any]:
    resolved_report_dir = Path(report_dir).expanduser().resolve()
    summary_path = resolved_report_dir / "session_summary.json"
    if not summary_path.exists():
        raise FileNotFoundError(f"session_summary.json not found under: {resolved_report_dir}")

    summary = _load_json(summary_path)
    resolved_trade_date, resolved_next_trade_date = _resolve_followup_trade_dates(
        trade_date=trade_date,
        next_trade_date=next_trade_date,
        brief_json_path=brief_json_path,
        card_json_path=card_json_path,
    )
    followup_manifest = {
        "trade_date": resolved_trade_date,
        "next_trade_date": resolved_next_trade_date,
        "brief_json": str(Path(brief_json_path).expanduser().resolve()),
        "brief_markdown": str(Path(brief_markdown_path).expanduser().resolve()),
        "execution_card_json": str(Path(card_json_path).expanduser().resolve()),
        "execution_card_markdown": str(Path(card_markdown_path).expanduser().resolve()),
    }
    summary["btst_followup"] = followup_manifest
    artifacts = dict(summary.get("artifacts") or {})
    artifacts.update(
        {
            "btst_next_day_trade_brief_json": followup_manifest["brief_json"],
            "btst_next_day_trade_brief_markdown": followup_manifest["brief_markdown"],
            "btst_premarket_execution_card_json": followup_manifest["execution_card_json"],
            "btst_premarket_execution_card_markdown": followup_manifest["execution_card_markdown"],
        }
    )
    summary["artifacts"] = artifacts
    _write_json(summary_path, summary)
    return followup_manifest


def generate_and_register_btst_followup_artifacts(
    report_dir: str | Path,
    trade_date: str | None,
    next_trade_date: str | None = None,
    *,
    brief_file_stem: str = "btst_next_day_trade_brief_latest",
    card_file_stem: str = "btst_premarket_execution_card_latest",
) -> dict[str, Any]:
    resolved_report_dir = Path(report_dir).expanduser().resolve()
    resolved_trade_date = _normalize_trade_date(trade_date)
    resolved_next_trade_date = _normalize_trade_date(next_trade_date) or infer_next_trade_date(resolved_trade_date)
    brief_result = generate_btst_next_day_trade_brief_artifacts(
        input_path=resolved_report_dir,
        output_dir=resolved_report_dir,
        trade_date=resolved_trade_date,
        next_trade_date=resolved_next_trade_date,
        file_stem=brief_file_stem,
    )

    if not resolved_trade_date:
        resolved_trade_date = _normalize_trade_date(brief_result["analysis"].get("trade_date"))

    if not resolved_next_trade_date:
        resolved_next_trade_date = _normalize_trade_date(brief_result["analysis"].get("next_trade_date")) or infer_next_trade_date(resolved_trade_date)
        if resolved_next_trade_date:
            brief_result = generate_btst_next_day_trade_brief_artifacts(
                input_path=resolved_report_dir,
                output_dir=resolved_report_dir,
                trade_date=resolved_trade_date,
                next_trade_date=resolved_next_trade_date,
                file_stem=brief_file_stem,
            )

    card_result = generate_btst_premarket_execution_card_artifacts(
        input_path=brief_result["analysis"],
        output_dir=resolved_report_dir,
        trade_date=resolved_trade_date,
        next_trade_date=resolved_next_trade_date,
        file_stem=card_file_stem,
    )
    followup_manifest = register_btst_followup_artifacts(
        resolved_report_dir,
        trade_date=resolved_trade_date,
        next_trade_date=resolved_next_trade_date,
        brief_json_path=brief_result["json_path"],
        brief_markdown_path=brief_result["markdown_path"],
        card_json_path=card_result["json_path"],
        card_markdown_path=card_result["markdown_path"],
    )
    return {
        "analysis": brief_result["analysis"],
        "execution_card": card_result["analysis"],
        **followup_manifest,
    }