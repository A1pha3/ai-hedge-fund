from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd

from src.tools.api import get_price_data

DEFAULT_COMMAND_BOARD_PATH = Path("data/reports/btst_candidate_pool_corridor_window_command_board_latest.json")
DEFAULT_OUTPUT_JSON = Path("data/reports/btst_candidate_pool_corridor_proof_gate_outcomes_latest.json")
DEFAULT_OUTPUT_MD = Path("data/reports/btst_candidate_pool_corridor_proof_gate_outcomes_latest.md")


def _load_json(path: str | Path) -> dict[str, Any]:
    resolved = Path(path).expanduser().resolve()
    return json.loads(resolved.read_text(encoding="utf-8"))


def _resolve_output_path(path: str | Path) -> Path:
    return Path(path).expanduser().resolve()


def _round_or_none(value: float | None) -> float | None:
    return None if value is None else round(float(value), 4)


def _mean_or_none(values: list[float]) -> float | None:
    return None if not values else round(sum(values) / len(values), 4)


def _positive_rate_or_none(values: list[float]) -> float | None:
    return None if not values else round(sum(1 for value in values if value > 0.0) / len(values), 4)


def _normalize_price_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame
    normalized = frame.copy()
    if "Date" in normalized.columns:
        normalized["Date"] = pd.to_datetime(normalized["Date"])
        normalized = normalized.set_index("Date")
    elif not isinstance(normalized.index, pd.DatetimeIndex):
        normalized.index = pd.to_datetime(normalized.index)
    normalized.sort_index(inplace=True)
    return normalized


def _load_price_frame_for_dates(ticker: str, trade_dates: list[str]) -> pd.DataFrame:
    if not trade_dates:
        return pd.DataFrame()
    start_date = min(trade_dates)
    end_date = (pd.Timestamp(max(trade_dates)) + pd.Timedelta(days=10)).strftime("%Y-%m-%d")
    return _normalize_price_frame(get_price_data(ticker, start_date, end_date))


def _extract_outcome_row(frame: pd.DataFrame, trade_date: str) -> dict[str, Any]:
    if frame.empty:
        return {"data_status": "missing_price_frame"}

    trade_ts = pd.Timestamp(trade_date)
    same_day = frame.loc[frame.index.normalize() == trade_ts.normalize()]
    next_day = frame.loc[frame.index.normalize() > trade_ts.normalize()]
    if same_day.empty:
        next_trade_date = None if next_day.empty else next_day.index[0].strftime("%Y-%m-%d")
        return {
            "data_status": "missing_trade_day_bar",
            "next_trade_date": next_trade_date,
        }
    if next_day.empty:
        return {"data_status": "missing_next_trade_day_bar"}

    trade_row = same_day.iloc[0]
    next_row = next_day.iloc[0]
    trade_close = float(trade_row.get("close") or 0.0)
    next_open = float(next_row.get("open") or 0.0)
    next_high = float(next_row.get("high") or 0.0)
    next_close = float(next_row.get("close") or 0.0)
    if trade_close <= 0 or next_open <= 0 or next_high <= 0 or next_close <= 0:
        return {"data_status": "incomplete_price_bar"}

    outcome = {
        "data_status": "ok",
        "next_trade_date": next_day.index[0].strftime("%Y-%m-%d"),
        "trade_close": round(trade_close, 4),
        "next_open_return": round((next_open / trade_close) - 1.0, 4),
        "next_high_return": round((next_high / trade_close) - 1.0, 4),
        "next_close_return": round((next_close / trade_close) - 1.0, 4),
        "next_open_to_close_return": round((next_close / next_open) - 1.0, 4),
    }

    second_next_day = next_day.iloc[1:2]
    if not second_next_day.empty:
        t_plus_2_close = float(second_next_day.iloc[0].get("close") or 0.0)
        if t_plus_2_close > 0:
            outcome["t_plus_2_trade_date"] = second_next_day.index[0].strftime("%Y-%m-%d")
            outcome["t_plus_2_close_return"] = round((t_plus_2_close / trade_close) - 1.0, 4)
    return outcome


def _load_selection_target_row(report_dir: str | Path, trade_date: str, ticker: str) -> dict[str, Any]:
    replay_path = Path(report_dir) / "selection_artifacts" / trade_date / "selection_target_replay_input.json"
    if not replay_path.exists():
        return {}
    payload = _load_json(replay_path)
    selection_targets = dict(payload.get("selection_targets") or payload)
    entry = dict(selection_targets.get(ticker) or {})
    short_trade = dict(entry.get("short_trade") or {})
    metrics_payload = dict(short_trade.get("metrics_payload") or {})
    proof = dict(metrics_payload.get("selected_historical_proof_deficiency") or {})
    return {
        "decision": short_trade.get("decision"),
        "score_target": _round_or_none(short_trade.get("score_target")),
        "candidate_source": short_trade.get("candidate_source"),
        "negative_tags": list(short_trade.get("negative_tags") or []),
        "top_reasons": list(short_trade.get("top_reasons") or []),
        "effective_select_threshold": _round_or_none(short_trade.get("effective_select_threshold")),
        "effective_near_miss_threshold": _round_or_none(short_trade.get("effective_near_miss_threshold")),
        "selected_historical_proof_deficiency": {
            "enabled": bool(proof.get("enabled")),
            "proof_missing": bool(proof.get("proof_missing")),
            "evaluable_count": proof.get("evaluable_count"),
        },
    }


def _summarize_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    ok_rows = [row for row in rows if str((row.get("outcome") or {}).get("data_status") or "") == "ok"]
    next_close_values = [float(row["outcome"]["next_close_return"]) for row in ok_rows if row.get("outcome", {}).get("next_close_return") is not None]
    t_plus_2_close_values = [float(row["outcome"]["t_plus_2_close_return"]) for row in ok_rows if row.get("outcome", {}).get("t_plus_2_close_return") is not None]
    return {
        "window_count": len(rows),
        "evaluable_count": len(ok_rows),
        "missing_trade_day_count": sum(1 for row in rows if str((row.get("outcome") or {}).get("data_status") or "") == "missing_trade_day_bar"),
        "missing_next_trade_day_count": sum(1 for row in rows if str((row.get("outcome") or {}).get("data_status") or "") == "missing_next_trade_day_bar"),
        "next_close_positive_rate": _positive_rate_or_none(next_close_values),
        "next_close_return_mean": _mean_or_none(next_close_values),
        "t_plus_2_close_positive_rate": _positive_rate_or_none(t_plus_2_close_values),
        "t_plus_2_close_return_mean": _mean_or_none(t_plus_2_close_values),
        "best_next_close_case": max(ok_rows, key=lambda row: float(row.get("outcome", {}).get("next_close_return") or -999.0), default=None),
        "worst_next_close_case": min(ok_rows, key=lambda row: float(row.get("outcome", {}).get("next_close_return") or 999.0), default=None),
    }


def _build_recommendation(
    ticker: str,
    all_summary: dict[str, Any],
    fresh_summary: dict[str, Any],
    fresh_rows: list[dict[str, Any]],
) -> tuple[str, str]:
    fresh_ok_rows = [row for row in fresh_rows if str((row.get("outcome") or {}).get("data_status") or "") == "ok"]
    fresh_dates = [str(row.get("trade_date") or "") for row in fresh_ok_rows]
    fresh_next_close_values = [float(row["outcome"]["next_close_return"]) for row in fresh_ok_rows if row.get("outcome", {}).get("next_close_return") is not None]
    top_probe = fresh_rows[0] if fresh_rows else None
    top_probe_status = None if not top_probe else (top_probe.get("outcome") or {}).get("data_status")

    if fresh_next_close_values and all(value <= 0.0 for value in fresh_next_close_values):
        return (
            "keep_proof_gate",
            f"{ticker} 的 corridor proof gate 暂不应放松：最新可评估窗口 {fresh_dates} 的 next_close_return 全为负值，而最高优先窗口 {top_probe.get('trade_date') if top_probe else None} 仍是 {top_probe_status}，不足以作为 selected historical proof。",
        )
    if (all_summary.get("next_close_positive_rate") or 0.0) >= 0.8 and (fresh_summary.get("next_close_positive_rate") or 0.0) >= 0.8:
        return (
            "relaxation_candidate",
            f"{ticker} 的 proof-gated corridor 窗口在全样本和最新样本里都呈现稳定的正 next_close_return，可考虑进入 profile-gated 的 proof gate 放松回放验证。",
        )
    return (
        "mixed_outcomes_collect_more_evidence",
        f"{ticker} 的 proof-gated corridor 窗口历史结果分化明显：旧窗口存在强正收益，但最新窗口未形成同向正反馈，继续保留 proof gate 并优先积累新的 selected 证据更稳妥。",
    )


def analyze_btst_candidate_pool_corridor_proof_gate_outcomes(
    command_board_path: str | Path = DEFAULT_COMMAND_BOARD_PATH,
    *,
    focus_ticker: str | None = None,
    target_trade_dates: list[str] | None = None,
) -> dict[str, Any]:
    command_board = _load_json(command_board_path)
    ticker = str(focus_ticker or command_board.get("focus_ticker") or "").strip()
    if not ticker:
        raise ValueError("Unable to resolve focus ticker from command board.")

    target_date_set = {str(item).strip() for item in list(target_trade_dates or command_board.get("exploratory_trade_dates") or []) if str(item).strip()}
    action_rows = [dict(row) for row in list(command_board.get("action_rows") or []) if not target_date_set or str(row.get("trade_date") or "") in target_date_set]
    if not action_rows:
        raise ValueError(f"No action rows found for ticker {ticker}.")

    price_frame = _load_price_frame_for_dates(ticker, [str(row.get("trade_date") or "") for row in action_rows if str(row.get("trade_date") or "").strip()])
    enriched_rows: list[dict[str, Any]] = []
    for action_row in action_rows:
        trade_date = str(action_row.get("trade_date") or "")
        replay_row = _load_selection_target_row(action_row.get("report_dir") or "", trade_date, ticker)
        outcome = _extract_outcome_row(price_frame, trade_date)
        enriched_rows.append(
            {
                "trade_date": trade_date,
                "report_dir": action_row.get("report_dir"),
                "action_tier": action_row.get("action_tier"),
                "decision": replay_row.get("decision") or action_row.get("decision"),
                "candidate_source": replay_row.get("candidate_source") or action_row.get("candidate_source"),
                "score_target": replay_row.get("score_target") if replay_row.get("score_target") is not None else _round_or_none(action_row.get("score_target")),
                "effective_select_threshold": replay_row.get("effective_select_threshold"),
                "effective_near_miss_threshold": replay_row.get("effective_near_miss_threshold"),
                "negative_tags": replay_row.get("negative_tags") or [],
                "top_reasons": replay_row.get("top_reasons") or [],
                "selected_historical_proof_deficiency": replay_row.get("selected_historical_proof_deficiency") or {},
                "outcome": outcome,
            }
        )

    next_target_dates = {str(item).strip() for item in list(command_board.get("next_target_trade_dates") or []) if str(item).strip()}
    fresh_rows = [row for row in enriched_rows if str(row.get("trade_date") or "") in next_target_dates]
    all_summary = _summarize_rows(enriched_rows)
    fresh_summary = _summarize_rows(fresh_rows)
    verdict, recommendation = _build_recommendation(ticker, all_summary, fresh_summary, fresh_rows)

    return {
        "focus_ticker": ticker,
        "verdict": verdict,
        "recommendation": recommendation,
        "summary": all_summary,
        "fresh_probe_summary": fresh_summary,
        "next_target_trade_dates": sorted(next_target_dates),
        "rows": enriched_rows,
        "source_reports": {
            "command_board": str(Path(command_board_path).expanduser().resolve()),
        },
    }


def render_btst_candidate_pool_corridor_proof_gate_outcomes_markdown(analysis: dict[str, Any]) -> str:
    summary = dict(analysis.get("summary") or {})
    fresh_summary = dict(analysis.get("fresh_probe_summary") or {})
    lines: list[str] = []
    lines.append(f"# BTST Candidate Pool Corridor Proof Gate Outcomes: {analysis['focus_ticker']}")
    lines.append("")
    lines.append("## Overview")
    lines.append(f"- verdict: {analysis.get('verdict')}")
    lines.append(f"- source_command_board: {analysis.get('source_reports', {}).get('command_board')}")
    lines.append(f"- next_target_trade_dates: {analysis.get('next_target_trade_dates')}")
    lines.append("")
    lines.append("## All Window Summary")
    lines.append(f"- window_count: {summary.get('window_count')}")
    lines.append(f"- evaluable_count: {summary.get('evaluable_count')}")
    lines.append(f"- missing_trade_day_count: {summary.get('missing_trade_day_count')}")
    lines.append(f"- next_close_positive_rate: {summary.get('next_close_positive_rate')}")
    lines.append(f"- next_close_return_mean: {summary.get('next_close_return_mean')}")
    lines.append(f"- t_plus_2_close_positive_rate: {summary.get('t_plus_2_close_positive_rate')}")
    lines.append(f"- t_plus_2_close_return_mean: {summary.get('t_plus_2_close_return_mean')}")
    lines.append("")
    lines.append("## Fresh Probe Summary")
    lines.append(f"- evaluable_count: {fresh_summary.get('evaluable_count')}")
    lines.append(f"- missing_trade_day_count: {fresh_summary.get('missing_trade_day_count')}")
    lines.append(f"- next_close_positive_rate: {fresh_summary.get('next_close_positive_rate')}")
    lines.append(f"- next_close_return_mean: {fresh_summary.get('next_close_return_mean')}")
    lines.append(f"- t_plus_2_close_positive_rate: {fresh_summary.get('t_plus_2_close_positive_rate')}")
    lines.append(f"- t_plus_2_close_return_mean: {fresh_summary.get('t_plus_2_close_return_mean')}")
    lines.append("")
    lines.append("## Per-Window Outcomes")
    for row in list(analysis.get("rows") or []):
        outcome = dict(row.get("outcome") or {})
        proof = dict(row.get("selected_historical_proof_deficiency") or {})
        lines.append(f"- {row.get('trade_date')} decision={row.get('decision')} score_target={row.get('score_target')} proof_missing={proof.get('proof_missing')} outcome_status={outcome.get('data_status')} next_trade_date={outcome.get('next_trade_date')} next_close_return={outcome.get('next_close_return')} t_plus_2_close_return={outcome.get('t_plus_2_close_return')}")
    lines.append("")
    lines.append("## Recommendation")
    lines.append(f"- {analysis.get('recommendation')}")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarize realized outcomes for corridor proof-gated BTST windows.")
    parser.add_argument("--command-board", default=str(DEFAULT_COMMAND_BOARD_PATH))
    parser.add_argument("--focus-ticker", default="")
    parser.add_argument("--trade-date", action="append", default=[])
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--output-md", default=str(DEFAULT_OUTPUT_MD))
    args = parser.parse_args()

    analysis = analyze_btst_candidate_pool_corridor_proof_gate_outcomes(
        args.command_board,
        focus_ticker=args.focus_ticker or None,
        target_trade_dates=args.trade_date or None,
    )

    output_json = _resolve_output_path(args.output_json)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    output_md = _resolve_output_path(args.output_md)
    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_md.write_text(render_btst_candidate_pool_corridor_proof_gate_outcomes_markdown(analysis), encoding="utf-8")

    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
