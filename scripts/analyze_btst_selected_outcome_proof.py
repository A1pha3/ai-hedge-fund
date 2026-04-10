from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from scripts.btst_analysis_utils import fetch_price_frame, normalize_trade_date, round_or_none, safe_float, summarize_distribution


REPORTS_DIR = Path("data/reports")
DEFAULT_OUTPUT_JSON = REPORTS_DIR / "btst_selected_outcome_proof_latest.json"
DEFAULT_OUTPUT_MD = REPORTS_DIR / "btst_selected_outcome_proof_latest.md"


def _load_json(path: str | Path) -> dict[str, Any]:
    resolved = Path(path).expanduser().resolve()
    return json.loads(resolved.read_text(encoding="utf-8"))


def _resolve_snapshot(input_path: str | Path | dict[str, Any]) -> tuple[dict[str, Any], str | None, str | None]:
    if isinstance(input_path, dict):
        return dict(input_path), None, None

    resolved = Path(input_path).expanduser().resolve()
    if resolved.is_file():
        snapshot_path = resolved
        report_dir = snapshot_path.parent.parent.parent
    else:
        snapshot_candidates = sorted(resolved.glob("selection_artifacts/*/selection_snapshot.json"))
        if not snapshot_candidates:
            raise FileNotFoundError(f"No selection_snapshot.json found under {resolved}")
        snapshot_path = snapshot_candidates[-1]
        report_dir = resolved

    return _load_json(snapshot_path), str(snapshot_path), str(report_dir)


def _resolve_selected_entry(snapshot: dict[str, Any], ticker: str | None = None) -> tuple[str, dict[str, Any]]:
    selection_targets = dict(snapshot.get("selection_targets") or {})
    if ticker:
        entry = dict(selection_targets.get(ticker) or {})
        short_trade = dict(entry.get("short_trade") or {})
        if not short_trade:
            raise KeyError(f"Ticker {ticker} not found in selection_targets")
        return ticker, short_trade

    selected_rows: list[tuple[str, dict[str, Any]]] = []
    for row_ticker, payload in selection_targets.items():
        short_trade = dict((payload or {}).get("short_trade") or {})
        if str(short_trade.get("decision") or "") != "selected":
            continue
        selected_rows.append((str(row_ticker), short_trade))

    if not selected_rows:
        raise ValueError("No selected short_trade entry found in snapshot")

    selected_rows.sort(
        key=lambda item: (
            int(item[1].get("rank_hint") or 999999),
            -float(item[1].get("score_target") or 0.0),
            item[0],
        )
    )
    return selected_rows[0]


def _resolve_historical_prior(short_trade: dict[str, Any]) -> dict[str, Any]:
    explainability = dict(short_trade.get("explainability_payload") or {})
    replay_context = dict(explainability.get("replay_context") or {})
    return dict(explainability.get("historical_prior") or replay_context.get("historical_prior") or {})


def _resolve_relief_context(short_trade: dict[str, Any]) -> dict[str, Any]:
    explainability = dict(short_trade.get("explainability_payload") or {})
    replay_context = dict(explainability.get("replay_context") or {})
    upstream_relief = dict(explainability.get("upstream_shadow_catalyst_relief") or {})
    replay_relief = dict(replay_context.get("short_trade_catalyst_relief") or {})
    top_reasons = [str(token) for token in list(short_trade.get("top_reasons") or [])]
    relief_reason = str(upstream_relief.get("reason") or replay_relief.get("reason") or "")
    relief_applied = bool(upstream_relief.get("applied"))
    if not relief_reason and "catalyst_theme_short_trade_carryover" in top_reasons:
        relief_reason = "catalyst_theme_short_trade_carryover"
    if not relief_applied and relief_reason == "catalyst_theme_short_trade_carryover":
        relief_applied = True
    return {
        "relief_reason": relief_reason,
        "relief_applied": relief_applied,
    }


def _resolve_selected_score_tolerance(short_trade: dict[str, Any]) -> float:
    explainability = dict(short_trade.get("explainability_payload") or {})
    metrics_payload = dict(short_trade.get("metrics_payload") or {})
    thresholds = dict(metrics_payload.get("thresholds") or {})
    upstream_relief = dict(explainability.get("upstream_shadow_catalyst_relief") or {})
    value = (
        short_trade.get("selected_score_tolerance")
        or thresholds.get("selected_score_tolerance")
        or upstream_relief.get("selected_score_tolerance")
        or 0.0
    )
    resolved = safe_float(value, 0.0)
    return 0.0 if resolved is None else float(resolved)


def _deduplicate_recent_examples(recent_examples: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduplicated: list[dict[str, Any]] = []
    seen_keys: set[tuple[str, str, str]] = set()
    for row in recent_examples:
        trade_date = normalize_trade_date(row.get("trade_date"))
        ticker = str(row.get("ticker") or "").strip()
        candidate_source = str(row.get("candidate_source") or "").strip()
        if not trade_date or not ticker:
            continue
        key = (trade_date, ticker, candidate_source)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        deduplicated.append(
            {
                **dict(row),
                "trade_date": trade_date,
                "ticker": ticker,
                "candidate_source": candidate_source,
            }
        )
    return deduplicated


def _extract_holding_outcome(ticker: str, trade_date: str, price_cache: dict[tuple[str, str], Any]) -> dict[str, Any]:
    normalized_trade_date = normalize_trade_date(trade_date)
    frame = fetch_price_frame(ticker, normalized_trade_date, price_cache)
    if frame.empty:
        return {"data_status": "missing_price_frame", "cycle_status": "missing_next_day"}

    import pandas as pd

    trade_timestamp = pd.Timestamp(normalized_trade_date)
    same_day = frame.loc[frame.index.normalize() == trade_timestamp.normalize()]
    if same_day.empty:
        return {"data_status": "missing_trade_day_bar", "cycle_status": "missing_next_day"}

    future_days = frame.loc[frame.index.normalize() > trade_timestamp.normalize()]
    if future_days.empty:
        return {
            "data_status": "missing_next_trade_day_bar",
            "trade_close": round_or_none(safe_float(same_day.iloc[0].get("close"))),
            "cycle_status": "missing_next_day",
        }

    trade_row = same_day.iloc[0]
    trade_close = safe_float(trade_row.get("close"))
    if trade_close is None or trade_close <= 0:
        return {"data_status": "incomplete_trade_day_bar", "cycle_status": "missing_next_day"}

    future_rows, future_dates = _extract_holding_future_window(future_days)
    return _build_holding_outcome_payload(trade_close=trade_close, future_rows=future_rows, future_dates=future_dates)


def _extract_holding_future_window(future_days: Any) -> tuple[list[Any], list[str]]:
    window_size = min(len(future_days), 4)
    return (
        [future_days.iloc[index] for index in range(window_size)],
        [future_days.index[index].strftime("%Y-%m-%d") for index in range(window_size)],
    )


def _build_holding_outcome_payload(*, trade_close: float, future_rows: list[Any], future_dates: list[str]) -> dict[str, Any]:
    next_row = future_rows[0]
    next_open = safe_float(next_row.get("open"))
    next_high = safe_float(next_row.get("high"))
    next_close = safe_float(next_row.get("close"))
    if next_open is None or next_high is None or next_close is None:
        return {"data_status": "incomplete_next_trade_day_bar", "cycle_status": "missing_next_day"}

    outcome: dict[str, Any] = {
        "data_status": "ok",
        "trade_close": round(trade_close, 4),
        "next_trade_date": future_dates[0],
        "next_open": round(next_open, 4),
        "next_high": round(next_high, 4),
        "next_close": round(next_close, 4),
        "next_open_return": round((next_open / trade_close) - 1.0, 4),
        "next_high_return": round((next_high / trade_close) - 1.0, 4),
        "next_close_return": round((next_close / trade_close) - 1.0, 4),
        "next_open_to_close_return": round((next_close / next_open) - 1.0, 4),
        "cycle_status": "t1_only",
    }
    _append_holding_extension_window(outcome=outcome, trade_close=trade_close, future_rows=future_rows, future_dates=future_dates)
    return outcome


def _append_holding_extension_window(*, outcome: dict[str, Any], trade_close: float, future_rows: list[Any], future_dates: list[str]) -> None:
    for offset in range(1, 4):
        row = future_rows[offset] if len(future_rows) > offset else None
        date = future_dates[offset] if len(future_dates) > offset else None
        key_prefix = f"t_plus_{offset + 1}"
        close_value = None if row is None else safe_float(row.get("close"))
        outcome[f"{key_prefix}_trade_date"] = date
        outcome[f"{key_prefix}_close"] = round_or_none(close_value)
        outcome[f"{key_prefix}_close_return"] = None if close_value is None else round((close_value / trade_close) - 1.0, 4)

    if outcome.get("t_plus_4_close_return") is not None:
        outcome["cycle_status"] = "t_plus_4_closed"
    elif outcome.get("t_plus_3_close_return") is not None:
        outcome["cycle_status"] = "t_plus_3_closed"
    elif outcome.get("t_plus_2_close_return") is not None:
        outcome["cycle_status"] = "t_plus_2_closed"


def _rate(hit_count: int, total_count: int) -> float | None:
    if total_count <= 0:
        return None
    return round(hit_count / total_count, 4)


def _summarize_evidence_rows(rows: list[dict[str, Any]], *, next_high_hit_threshold: float) -> dict[str, Any]:
    next_day_rows = [row for row in rows if row.get("next_close_return") is not None]
    t_plus_2_rows = [row for row in rows if row.get("t_plus_2_close_return") is not None]
    t_plus_3_rows = [row for row in rows if row.get("t_plus_3_close_return") is not None]
    t_plus_4_rows = [row for row in rows if row.get("t_plus_4_close_return") is not None]

    next_high_returns = [float(row["next_high_return"]) for row in next_day_rows if row.get("next_high_return") is not None]
    next_close_returns = [float(row["next_close_return"]) for row in next_day_rows if row.get("next_close_return") is not None]
    next_open_to_close_returns = [float(row["next_open_to_close_return"]) for row in next_day_rows if row.get("next_open_to_close_return") is not None]
    t_plus_2_returns = [float(row["t_plus_2_close_return"]) for row in t_plus_2_rows if row.get("t_plus_2_close_return") is not None]
    t_plus_3_returns = [float(row["t_plus_3_close_return"]) for row in t_plus_3_rows if row.get("t_plus_3_close_return") is not None]
    t_plus_4_returns = [float(row["t_plus_4_close_return"]) for row in t_plus_4_rows if row.get("t_plus_4_close_return") is not None]

    return {
        "evidence_case_count": len(rows),
        "next_day_available_count": len(next_day_rows),
        "t_plus_2_available_count": len(t_plus_2_rows),
        "t_plus_3_available_count": len(t_plus_3_rows),
        "t_plus_4_available_count": len(t_plus_4_rows),
        "next_high_hit_threshold": round(next_high_hit_threshold, 4),
        "next_high_hit_rate_at_threshold": _rate(sum(1 for value in next_high_returns if value >= next_high_hit_threshold), len(next_day_rows)),
        "next_close_positive_rate": _rate(sum(1 for value in next_close_returns if value > 0), len(next_day_rows)),
        "t_plus_2_close_positive_rate": _rate(sum(1 for value in t_plus_2_returns if value > 0), len(t_plus_2_rows)),
        "t_plus_3_close_positive_rate": _rate(sum(1 for value in t_plus_3_returns if value > 0), len(t_plus_3_rows)),
        "t_plus_4_close_positive_rate": _rate(sum(1 for value in t_plus_4_returns if value > 0), len(t_plus_4_rows)),
        "next_high_return_distribution": summarize_distribution(next_high_returns),
        "next_close_return_distribution": summarize_distribution(next_close_returns),
        "next_open_to_close_return_distribution": summarize_distribution(next_open_to_close_returns),
        "t_plus_2_close_return_distribution": summarize_distribution(t_plus_2_returns),
        "t_plus_3_close_return_distribution": summarize_distribution(t_plus_3_returns),
        "t_plus_4_close_return_distribution": summarize_distribution(t_plus_4_returns),
    }


def _build_recommendation(summary: dict[str, Any]) -> str:
    evidence_case_count = int(summary.get("evidence_case_count") or 0)
    next_close_positive_rate = summary.get("next_close_positive_rate")
    t_plus_2_positive_rate = summary.get("t_plus_2_close_positive_rate")
    t_plus_3_positive_rate = summary.get("t_plus_3_close_positive_rate")
    if evidence_case_count <= 0:
        return "当前没有可复核的 historical_prior evidence cases，不能把这条 selected 路径当成已完成历史证明。"
    if next_close_positive_rate is not None and next_close_positive_rate >= 0.8 and t_plus_2_positive_rate is not None and t_plus_2_positive_rate >= 0.5:
        if t_plus_3_positive_rate is None or t_plus_3_positive_rate >= 0.5:
            return "当前 selected 路径已有足够的 historical_prior follow-through 支持，可继续保留 confirm_then_hold 语义。"
        return "当前 selected 路径的次日与 T+2 支持较强，但 T+3 延续偏弱，更适合作为次日确认后持有、而非过度拉长持仓的 BTST 方案。"
    if next_close_positive_rate is not None and next_close_positive_rate >= 0.8:
        return "当前 selected 路径至少证明了较强的次日收盘延续，但 T+2/T+3 样本还不足，后续应继续积累 closed-cycle 证据。"
    return "当前 selected 路径的 historical_prior 证据还不足以证明收益质量改善，优先任务应转向扩充 carryover cohort，而不是继续放松 selected frontier。"


def analyze_btst_selected_outcome_proof(input_path: str | Path | dict[str, Any], *, ticker: str | None = None) -> dict[str, Any]:
    snapshot, snapshot_path, report_dir = _resolve_snapshot(input_path)
    resolved_ticker, short_trade = _resolve_selected_entry(snapshot, ticker=ticker)
    historical_prior = _resolve_historical_prior(short_trade)
    relief_context = _resolve_relief_context(short_trade)
    recent_examples = _deduplicate_recent_examples(list(historical_prior.get("recent_examples") or []))
    next_high_hit_threshold = float(historical_prior.get("next_high_hit_threshold") or 0.02)
    score_target = safe_float(short_trade.get("score_target"))
    effective_select_threshold = safe_float(short_trade.get("effective_select_threshold"))
    selected_score_tolerance = _resolve_selected_score_tolerance(short_trade)
    score_gap_to_selected = None
    if score_target is not None and effective_select_threshold is not None:
        score_gap_to_selected = round(effective_select_threshold - score_target, 6)

    price_cache: dict[tuple[str, str], Any] = {}
    evidence_rows: list[dict[str, Any]] = []
    for row in recent_examples:
        outcome = _extract_holding_outcome(str(row.get("ticker") or ""), str(row.get("trade_date") or ""), price_cache)
        evidence_rows.append({**row, **outcome})

    summary = _summarize_evidence_rows(evidence_rows, next_high_hit_threshold=next_high_hit_threshold)
    recommendation = _build_recommendation(summary)

    return {
        "report_dir": report_dir,
        "snapshot_path": snapshot_path,
        "trade_date": normalize_trade_date(snapshot.get("trade_date")),
        "ticker": resolved_ticker,
        "decision": short_trade.get("decision"),
        "candidate_source": short_trade.get("candidate_source"),
        "preferred_entry_mode": short_trade.get("preferred_entry_mode"),
        "score_target": round_or_none(score_target),
        "effective_select_threshold": round_or_none(effective_select_threshold),
        "selected_score_tolerance": round(selected_score_tolerance, 4),
        "score_gap_to_selected": score_gap_to_selected,
        "selected_within_tolerance": bool(
            score_target is not None
            and effective_select_threshold is not None
            and score_target >= (effective_select_threshold - selected_score_tolerance)
        ),
        "relief_reason": relief_context["relief_reason"],
        "relief_applied": relief_context["relief_applied"],
        "historical_prior": historical_prior,
        "raw_recent_example_count": len(list(historical_prior.get("recent_examples") or [])),
        "deduplicated_recent_example_count": len(recent_examples),
        "summary": summary,
        "evidence_rows": evidence_rows,
        "recommendation": recommendation,
    }


def render_btst_selected_outcome_proof_markdown(analysis: dict[str, Any]) -> str:
    summary = dict(analysis.get("summary") or {})
    lines: list[str] = []
    lines.append("# BTST Selected Outcome Proof")
    lines.append("")
    lines.append("## Selected Path")
    lines.append(f"- trade_date: {analysis.get('trade_date')}")
    lines.append(f"- ticker: {analysis.get('ticker')}")
    lines.append(f"- decision: {analysis.get('decision')}")
    lines.append(f"- candidate_source: {analysis.get('candidate_source')}")
    lines.append(f"- preferred_entry_mode: {analysis.get('preferred_entry_mode')}")
    lines.append(f"- relief_reason: {analysis.get('relief_reason')}")
    lines.append(f"- relief_applied: {analysis.get('relief_applied')}")
    lines.append(f"- score_target: {analysis.get('score_target')}")
    lines.append(f"- effective_select_threshold: {analysis.get('effective_select_threshold')}")
    lines.append(f"- selected_score_tolerance: {analysis.get('selected_score_tolerance')}")
    lines.append(f"- score_gap_to_selected: {analysis.get('score_gap_to_selected')}")
    lines.append(f"- selected_within_tolerance: {analysis.get('selected_within_tolerance')}")
    lines.append("")
    lines.append("## Historical Prior Summary")
    historical_prior = dict(analysis.get("historical_prior") or {})
    lines.append(f"- sample_count: {historical_prior.get('sample_count')}")
    lines.append(f"- evaluable_count: {historical_prior.get('evaluable_count')}")
    lines.append(f"- execution_quality_label: {historical_prior.get('execution_quality_label')}")
    lines.append(f"- entry_timing_bias: {historical_prior.get('entry_timing_bias')}")
    lines.append(f"- next_high_hit_rate_at_threshold: {historical_prior.get('next_high_hit_rate_at_threshold')}")
    lines.append(f"- next_close_positive_rate: {historical_prior.get('next_close_positive_rate')}")
    lines.append(f"- next_close_return_mean: {historical_prior.get('next_close_return_mean')}")
    lines.append("")
    lines.append("## Evidence Summary")
    for key in (
        "evidence_case_count",
        "next_high_hit_rate_at_threshold",
        "next_close_positive_rate",
        "t_plus_2_close_positive_rate",
        "t_plus_3_close_positive_rate",
        "t_plus_4_close_positive_rate",
    ):
        lines.append(f"- {key}: {summary.get(key)}")
    lines.append(f"- next_close_return_distribution: {summary.get('next_close_return_distribution')}")
    lines.append(f"- t_plus_2_close_return_distribution: {summary.get('t_plus_2_close_return_distribution')}")
    lines.append(f"- t_plus_3_close_return_distribution: {summary.get('t_plus_3_close_return_distribution')}")
    lines.append(f"- t_plus_4_close_return_distribution: {summary.get('t_plus_4_close_return_distribution')}")
    lines.append("")
    lines.append("## Evidence Cases")
    for row in list(analysis.get("evidence_rows") or []):
        lines.append(
            f"- {row.get('trade_date')} {row.get('ticker')}: source={row.get('candidate_source')}, next_high_return={row.get('next_high_return')}, next_close_return={row.get('next_close_return')}, t_plus_2_close_return={row.get('t_plus_2_close_return')}, t_plus_3_close_return={row.get('t_plus_3_close_return')}, t_plus_4_close_return={row.get('t_plus_4_close_return')}, cycle_status={row.get('cycle_status')}"
        )
    if not list(analysis.get("evidence_rows") or []):
        lines.append("- none")
    lines.append("")
    lines.append("## Recommendation")
    lines.append(f"- {analysis.get('recommendation')}")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate the historical outcome quality behind the current BTST selected path.")
    parser.add_argument("--input-path", default=str(REPORTS_DIR))
    parser.add_argument("--ticker", default="")
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--output-md", default=str(DEFAULT_OUTPUT_MD))
    args = parser.parse_args()

    analysis = analyze_btst_selected_outcome_proof(args.input_path, ticker=args.ticker or None)
    output_json = Path(args.output_json).expanduser().resolve()
    output_md = Path(args.output_md).expanduser().resolve()
    output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_md.write_text(render_btst_selected_outcome_proof_markdown(analysis), encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
