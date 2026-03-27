from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from src.execution.daily_pipeline import FAST_AGENT_MAX_TICKERS, FAST_AGENT_SCORE_THRESHOLD
from src.screening.candidate_pool import _SNAPSHOT_DIR, build_candidate_pool
from src.screening.market_state import detect_market_state
from src.screening.signal_fusion import fuse_batch
from src.screening.strategy_scorer import score_batch


STRATEGY_ORDER = ["trend", "mean_reversion", "fundamental", "event_sentiment"]


def _resolve_trade_dates(raw_trade_dates: str) -> list[str]:
    trade_dates = [item.strip() for item in raw_trade_dates.split(",") if item.strip()]
    if not trade_dates:
        raise SystemExit("--trade-dates is required")
    missing = [trade_date for trade_date in trade_dates if not (_SNAPSHOT_DIR / f"candidate_pool_{trade_date}.json").exists()]
    if missing:
        raise SystemExit(f"Missing candidate pool snapshots for trade dates: {', '.join(missing)}")
    return trade_dates


def _format_market_cap(value: float) -> str:
    if value <= 0:
        return ""
    return f"{value:.2f}"


def _compact_json(value: object) -> str:
    if value in (None, "", [], {}):
        return ""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _strategy_summary(signal: dict) -> tuple[str, str, str]:
    return (
        str(int(signal.get("direction", 0) or 0)),
        f"{float(signal.get('confidence', 0.0) or 0.0):.4f}",
        f"{float(signal.get('completeness', 0.0) or 0.0):.4f}",
    )


def _top_factors(strategy_signals: dict[str, dict]) -> list[dict[str, object]]:
    factors: list[dict[str, object]] = []
    for strategy_name, signal in sorted(strategy_signals.items()):
        factors.append(
            {
                "name": strategy_name,
                "direction": int(signal.get("direction", 0) or 0),
                "confidence": float(signal.get("confidence", 0.0) or 0.0),
                "completeness": float(signal.get("completeness", 0.0) or 0.0),
            }
        )
    factors.sort(key=lambda item: abs(float(item["direction"])) * float(item["confidence"]), reverse=True)
    return factors[:3]


def _format_factor(factor: dict[str, object]) -> str:
    return f"{factor['name']}|d={int(factor['direction'])}|c={float(factor['confidence']):.1f}|k={float(factor['completeness']):.2f}"


def _extract_plan_from_daily_event(payload: dict) -> dict:
    current_plan = payload.get("current_plan")
    if isinstance(current_plan, dict):
        return current_plan
    if "risk_metrics" in payload and "watchlist" in payload:
        return payload
    return {}


def _load_downstream_map(report_dir: Path | None) -> dict[str, dict[str, dict[str, object]]]:
    if report_dir is None:
        return {}
    daily_events_path = report_dir / "daily_events.jsonl"
    if not daily_events_path.exists():
        return {}

    by_date: dict[str, dict[str, dict[str, object]]] = {}
    with daily_events_path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            payload = json.loads(line)
            plan = _extract_plan_from_daily_event(payload)
            trade_date = str(plan.get("date") or payload.get("trade_date") or "")
            if not trade_date:
                continue

            date_map: dict[str, dict[str, object]] = {}
            watchlist = list(plan.get("watchlist", []) or [])
            buy_orders = {str(order.get("ticker") or "") for order in list(plan.get("buy_orders", []) or []) if order.get("ticker")}
            funnel = dict(((plan.get("risk_metrics") or {}).get("funnel_diagnostics") or {}))
            watchlist_filters = dict((funnel.get("filters") or {}).get("watchlist") or {})
            rejected_entries = list(watchlist_filters.get("tickers", []) or [])

            for item in watchlist:
                ticker = str(item.get("ticker") or "")
                if not ticker:
                    continue
                date_map[ticker] = {
                    "layer_c_status": "watchlist",
                    "score_c": float(item.get("score_c", 0.0) or 0.0),
                    "score_final": float(item.get("score_final", 0.0) or 0.0),
                    "bc_conflict": str(item.get("bc_conflict") or ""),
                    "decision_c": str(item.get("decision") or ""),
                    "buy_order_entered": ticker in buy_orders,
                    "downstream_reason": "",
                }

            for entry in rejected_entries:
                ticker = str(entry.get("ticker") or "")
                if not ticker:
                    continue
                date_map[ticker] = {
                    "layer_c_status": "rejected_after_layer_c",
                    "score_c": float(entry.get("score_c", 0.0) or 0.0),
                    "score_final": float(entry.get("score_final", 0.0) or 0.0),
                    "bc_conflict": str(entry.get("bc_conflict") or ""),
                    "decision_c": str(entry.get("decision") or ""),
                    "buy_order_entered": False,
                    "downstream_reason": str(entry.get("reason") or ",".join(entry.get("reasons", []) or [])),
                }

            by_date[trade_date] = date_map
    return by_date


def _build_rows(trade_dates: list[str], downstream_map: dict[str, dict[str, dict[str, object]]]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for trade_date in trade_dates:
        candidates = build_candidate_pool(trade_date, use_cache=True)
        market_state = detect_market_state(trade_date)
        scored = score_batch(candidates, trade_date)
        fused = fuse_batch(scored, market_state, trade_date)
        candidate_map = {candidate.ticker: candidate for candidate in candidates}

        sorted_fused = sorted(fused, key=lambda item: float(item.score_b), reverse=True)
        threshold_passers = [item for item in sorted_fused if float(item.score_b) >= FAST_AGENT_SCORE_THRESHOLD]
        high_pool_tickers = {item.ticker for item in threshold_passers[:FAST_AGENT_MAX_TICKERS]}
        downstream_by_ticker = downstream_map.get(trade_date, {})

        for rank, item in enumerate(threshold_passers, start=1):
            candidate = candidate_map.get(item.ticker)
            strategy_signals = {name: signal.model_dump() for name, signal in item.strategy_signals.items()}
            top_factors = _top_factors(strategy_signals)
            downstream = downstream_by_ticker.get(item.ticker, {})
            is_high_pool_selected = item.ticker in high_pool_tickers
            truncated_by_max = not is_high_pool_selected
            layer_c_status = str(downstream.get("layer_c_status") or ("not_run_truncated" if truncated_by_max else "entered_layer_c_unknown"))

            row = {
                "trade_date": trade_date,
                "ticker": item.ticker,
                "name": candidate.name if candidate else "",
                "industry_sw": candidate.industry_sw if candidate else "",
                "market_cap_billion": _format_market_cap(float(candidate.market_cap or 0.0)) if candidate else "",
                "score_b": f"{float(item.score_b):.4f}",
                "decision_b": str(item.decision),
                "rank_in_layer_b": rank,
                "pass_threshold": "yes",
                "high_pool_selected": "yes" if is_high_pool_selected else "no",
                "truncated_by_max": "yes" if truncated_by_max else "no",
                "market_state": str(getattr(market_state.state_type, "value", market_state.state_type)),
                "market_weights": _compact_json(dict(market_state.adjusted_weights or {})),
                "arbitration_applied": ";".join(list(item.arbitration_applied or [])),
                "weights_used": _compact_json(dict(item.weights_used or {})),
                "top_factor_1": _format_factor(top_factors[0]) if len(top_factors) >= 1 else "",
                "top_factor_2": _format_factor(top_factors[1]) if len(top_factors) >= 2 else "",
                "top_factor_3": _format_factor(top_factors[2]) if len(top_factors) >= 3 else "",
                "layer_c_status": layer_c_status,
                "score_c": f"{float(downstream.get('score_c', 0.0) or 0.0):.4f}" if downstream else "",
                "score_final": f"{float(downstream.get('score_final', 0.0) or 0.0):.4f}" if downstream else "",
                "decision_c": str(downstream.get("decision_c") or ""),
                "bc_conflict": str(downstream.get("bc_conflict") or ""),
                "buy_order_entered": "yes" if bool(downstream.get("buy_order_entered")) else "no",
                "downstream_reason": str(downstream.get("downstream_reason") or ""),
                "manual_verdict": "",
                "manual_notes": "",
            }

            for strategy_name in STRATEGY_ORDER:
                direction, confidence, completeness = _strategy_summary(strategy_signals.get(strategy_name, {}))
                row[f"{strategy_name}_direction"] = direction
                row[f"{strategy_name}_confidence"] = confidence
                row[f"{strategy_name}_completeness"] = completeness

            rows.append(row)
    return rows


def _markdown_summary(rows: list[dict[str, object]], trade_dates: list[str]) -> str:
    lines = [
        "# Layer B 人工审核台账",
        "",
        "这份报告列出指定窗口内所有通过 Layer B 阈值的股票，供人工审核它们是否真的优秀，以及 Layer B 是否需要继续调整。",
        "",
        "## 审核建议",
        "",
        "1. 先看边界样本，判断是否存在明显优秀却解释单薄的票。",
        "2. 再看被 Layer C 否决的样本，判断是 Layer B 放错了，还是 Layer C 过严。",
        "3. 最后看强通过组，判断是否出现明显低质量或题材噪声票。",
        "",
    ]

    total_count = len(rows)
    strong_count = sum(1 for row in rows if float(row["score_b"]) >= 0.50)
    boundary_count = sum(1 for row in rows if FAST_AGENT_SCORE_THRESHOLD <= float(row["score_b"]) < 0.42)
    rejected_after_layer_c_count = sum(1 for row in rows if row["layer_c_status"] == "rejected_after_layer_c")
    lines.extend(
        [
            "## 窗口概览",
            "",
            f"- trade_dates: {', '.join(trade_dates)}",
            f"- total_layer_b_passes: {total_count}",
            f"- strong_passes(score_b >= 0.50): {strong_count}",
            f"- boundary_passes(0.38 <= score_b < 0.42): {boundary_count}",
            f"- rejected_after_layer_c: {rejected_after_layer_c_count}",
            "",
        ]
    )

    for trade_date in trade_dates:
        date_rows = [row for row in rows if row["trade_date"] == trade_date]
        strong_rows = [row for row in date_rows if float(row["score_b"]) >= 0.50]
        boundary_rows = [row for row in date_rows if FAST_AGENT_SCORE_THRESHOLD <= float(row["score_b"]) < 0.42]
        layer_c_rejected_rows = [row for row in date_rows if row["layer_c_status"] == "rejected_after_layer_c"]

        lines.extend([f"## {trade_date}", "", f"- layer_b_pass_count: {len(date_rows)}", ""])

        sections = [
            ("强通过组", strong_rows),
            ("边界通过组", boundary_rows),
            ("通过但下游被否决", layer_c_rejected_rows),
            ("全部通过名单", date_rows),
        ]
        for title, section_rows in sections:
            lines.extend([f"### {title}", ""])
            if not section_rows:
                lines.extend(["- 无", ""])
                continue
            for row in section_rows:
                lines.append(
                    f"- {row['ticker']} {row['name']} | score_b={row['score_b']} | decision={row['decision_b']} | "
                    f"L/C={row['layer_c_status']} | top={row['top_factor_1'] or 'n/a'}"
                )
                if row["downstream_reason"]:
                    lines.append(f"  - downstream_reason: {row['downstream_reason']}")
                if row["bc_conflict"]:
                    lines.append(f"  - bc_conflict: {row['bc_conflict']}")
            lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _manual_review_template() -> str:
    return "\n".join(
        [
            "# Layer B 人工审核模板",
            "",
            "建议先逐只查看 layer_b_pass_ledger.csv，再按下面模板记录人工判断。",
            "",
            "## 推荐标签",
            "",
            "1. 优秀候选：多主腿同时支撑，逻辑完整，值得继续研究。",
            "2. 边界但可接受：有一定质量，但证据厚度一般，可继续观察。",
            "3. 可疑放行：看起来通过了 Layer B，但主观上并不优秀，需要复核规则。",
            "4. 明显不该通过：大概率是 Layer B 语义或阈值有问题。",
            "",
            "## 每只股票建议回答",
            "",
            "1. 它是靠哪些主腿过线的？",
            "2. 它的正向证据是结构性，还是短期噪声？",
            "3. 如果被 Layer C 或下游打回，是 Layer B 放错了，还是下游过严？",
            "4. 如果以后做规则调整，这只票更像支持放宽，还是支持收紧？",
            "",
            "## 建议填写列",
            "",
            "- manual_verdict: 优秀候选 / 边界但可接受 / 可疑放行 / 明显不该通过",
            "- manual_notes: 简短写明原因，优先记录是 trend、fundamental、event 还是 MR 导致你的判断",
            "",
            "## 快速判断优先级",
            "",
            "1. 先看 score_b 靠近阈值的边界票。",
            "2. 再看被 Layer C 否决的票。",
            "3. 最后看强通过但你主观觉得不够优秀的票。",
            "",
        ]
    )


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        fieldnames = [
            "trade_date",
            "ticker",
            "name",
            "industry_sw",
            "market_cap_billion",
            "score_b",
            "decision_b",
            "rank_in_layer_b",
            "pass_threshold",
            "high_pool_selected",
            "truncated_by_max",
            "market_state",
            "market_weights",
            "arbitration_applied",
            "weights_used",
            "top_factor_1",
            "top_factor_2",
            "top_factor_3",
            "layer_c_status",
            "score_c",
            "score_final",
            "decision_c",
            "bc_conflict",
            "buy_order_entered",
            "downstream_reason",
            "manual_verdict",
            "manual_notes",
        ]
    else:
        fieldnames = list(rows[0].keys())
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Export Layer B pass ledger for manual review.")
    parser.add_argument("--trade-dates", required=True, help="Comma-separated trade dates like 20260323,20260324")
    parser.add_argument("--report-dir", default="", help="Optional existing paper-trading report dir used to merge Layer C/watchlist/buy_order outcomes")
    parser.add_argument("--output-dir", default="", help="Optional output dir; defaults to <report-dir>/layer_b_review or data/reports/layer_b_review_<dates>")
    args = parser.parse_args()

    trade_dates = _resolve_trade_dates(args.trade_dates)
    report_dir = Path(args.report_dir).expanduser().resolve() if args.report_dir else None
    if report_dir is not None and not report_dir.exists():
        raise SystemExit(f"Report dir does not exist: {report_dir}")

    if args.output_dir:
        output_dir = Path(args.output_dir).expanduser().resolve()
    elif report_dir is not None:
        output_dir = report_dir / "layer_b_review"
    else:
        output_dir = Path(__file__).resolve().parents[1] / "data" / "reports" / f"layer_b_review_{trade_dates[0]}_{trade_dates[-1]}"
    output_dir.mkdir(parents=True, exist_ok=True)

    downstream_map = _load_downstream_map(report_dir)
    rows = _build_rows(trade_dates, downstream_map)

    csv_path = output_dir / "layer_b_pass_ledger.csv"
    md_path = output_dir / "layer_b_review.md"
    summary_path = output_dir / "layer_b_review_summary.json"
    template_path = output_dir / "manual_review_template.md"

    _write_csv(csv_path, rows)
    md_path.write_text(_markdown_summary(rows, trade_dates), encoding="utf-8")
    template_path.write_text(_manual_review_template(), encoding="utf-8")
    summary_payload = {
        "trade_dates": trade_dates,
        "row_count": len(rows),
        "report_dir": str(report_dir) if report_dir is not None else "",
        "threshold": FAST_AGENT_SCORE_THRESHOLD,
        "max_high_pool": FAST_AGENT_MAX_TICKERS,
        "output_files": {
            "csv": str(csv_path),
            "markdown": str(md_path),
            "manual_template": str(template_path),
        },
    }
    summary_path.write_text(json.dumps(summary_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(json.dumps(summary_payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()