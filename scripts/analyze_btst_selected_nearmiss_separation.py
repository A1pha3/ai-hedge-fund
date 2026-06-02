"""Analyze BTST selected-vs-near_miss separation from selection artifacts."""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path
from typing import Any

from scripts.generate_btst_realized_prices import generate_realized_prices

_DEFAULT_REPORT_DIR = Path("data/p4_prior_shrinkage_eval_sample")
_OUTPUT_DIR = Path("data/reports")


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _iter_selection_snapshot_paths(input_path: Path) -> list[Path]:
    resolved = input_path.resolve()
    if resolved.is_file():
        return [resolved]
    artifacts_root = resolved / "selection_artifacts" if (resolved / "selection_artifacts").is_dir() else resolved
    return sorted(artifacts_root.glob("*/selection_snapshot.json"))


def _recommendation(*, selected_count: int, near_miss_count: int, gate_counts: dict[str, int]) -> str:
    weak_gate_count = int(gate_counts.get("halt") or 0) + int(gate_counts.get("shadow_only") or 0)
    if selected_count > near_miss_count and weak_gate_count == 0:
        return "go"
    if selected_count > 0:
        return "shadow_only"
    return "rollback"


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _outcome_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    ok = [row for row in rows if row.get("data_status") == "ok"]
    close_returns = [float(row["next_close_return"]) for row in ok if _as_float(row.get("next_close_return")) is not None]
    open_returns = [float(row["next_open_return"]) for row in ok if _as_float(row.get("next_open_return")) is not None]
    max_high = [
        float(row["max_high_t1_t5_from_open"]) for row in ok if _as_float(row.get("max_high_t1_t5_from_open")) is not None
    ]

    win_rate_close = None
    if close_returns:
        win_rate_close = float(sum(1.0 for r in close_returns if r > 0) / len(close_returns))

    hit_rate_5d_15 = None
    if max_high:
        hit_rate_5d_15 = float(sum(1.0 for r in max_high if r >= 0.15) / len(max_high))

    mean_next_close_return = float(sum(close_returns) / len(close_returns)) if close_returns else None
    mean_next_open_return = float(sum(open_returns) / len(open_returns)) if open_returns else None

    return {
        "count": int(len(rows)),
        "ok_count": int(len(ok)),
        "missing_count": int(len(rows) - len(ok)),
        "win_rate_next_close": win_rate_close,
        "mean_next_open_return": mean_next_open_return,
        "mean_next_close_return": mean_next_close_return,
        "hit_rate_5d_15": hit_rate_5d_15,
    }


def _compact_date(value: str) -> str:
    token = str(value or "").strip()
    if len(token) == 10 and token[4] == "-" and token[7] == "-":
        return token.replace("-", "")
    return token


def analyze_btst_selected_nearmiss_separation(
    input_path: Path,
    *,
    month: str | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    snapshot_paths = _iter_selection_snapshot_paths(input_path)
    decision_counts: dict[str, int] = {}
    gate_counts: dict[str, int] = {}
    decision_gate_counts: dict[str, dict[str, int]] = {}

    outcomes_by_decision: dict[str, list[dict[str, Any]]] = {"selected": [], "near_miss": []}

    used_snapshots = 0
    month_token = str(month or "").strip()

    for snapshot_path in snapshot_paths:
        try:
            snapshot = _load_json(snapshot_path)
        except Exception:
            continue

        trade_date = str(snapshot.get("trade_date") or "").strip()
        if not trade_date:
            # try infer from nested targets (synthetic fixtures include it per-row)
            sample_target = next(iter(dict(snapshot.get("selection_targets") or {}).values()), {})
            trade_date = str(dict(sample_target or {}).get("trade_date") or "").strip()

        compact_trade_date = _compact_date(trade_date)
        if month_token and not compact_trade_date.startswith(month_token):
            continue

        selection_targets = dict(snapshot.get("selection_targets") or {})
        decisions: dict[str, str] = {}
        gates: dict[str, str] = {}
        for ticker, payload in selection_targets.items():
            target = dict(payload or {})
            short_trade = dict(target.get("short_trade") or {})
            decision = str(short_trade.get("decision") or "rejected")
            if decision not in {"selected", "near_miss"}:
                continue
            ticker_str = str(ticker or target.get("ticker") or "").strip()
            if not ticker_str:
                continue
            gate = str(target.get("btst_regime_gate") or short_trade.get("btst_regime_gate") or "unknown")
            decisions[ticker_str] = decision
            gates[ticker_str] = gate

            decision_counts[decision] = int(decision_counts.get(decision) or 0) + 1
            gate_counts[gate] = int(gate_counts.get(gate) or 0) + 1
            gate_counter = decision_gate_counts.setdefault(decision, {})
            gate_counter[gate] = int(gate_counter.get(gate) or 0) + 1

        if not decisions or not trade_date:
            continue

        used_snapshots += 1
        if limit is not None and used_snapshots > int(limit):
            break

        try:
            realized = generate_realized_prices(signal_date=trade_date, tickers=sorted(decisions))
        except Exception:
            realized = {}
        for ticker_str in sorted(decisions):
            decision = decisions[ticker_str]
            realized_row = dict(realized.get(ticker_str) or {"data_status": "realized_unavailable"})
            realized_row["ticker"] = ticker_str
            realized_row["trade_date"] = trade_date
            realized_row["decision"] = decision
            realized_row["btst_regime_gate"] = gates.get(ticker_str) or "unknown"
            outcomes_by_decision.setdefault(decision, []).append(realized_row)

    selected_count = int(decision_counts.get("selected") or 0)
    near_miss_count = int(decision_counts.get("near_miss") or 0)

    decision_outcome_summaries = {
        decision: _outcome_summary(rows) for decision, rows in outcomes_by_decision.items() if rows is not None
    }

    decision_gate_outcome_summaries: dict[str, dict[str, dict[str, Any]]] = {}
    for decision, rows in outcomes_by_decision.items():
        buckets: dict[str, list[dict[str, Any]]] = {}
        for row in list(rows or []):
            gate = str(row.get("btst_regime_gate") or "unknown")
            buckets.setdefault(gate, []).append(row)
        decision_gate_outcome_summaries[decision] = {
            gate: _outcome_summary(bucket_rows) for gate, bucket_rows in buckets.items()
        }

    selected_summary = dict(decision_outcome_summaries.get("selected") or {})
    near_miss_summary = dict(decision_outcome_summaries.get("near_miss") or {})

    return {
        "report_type": "p4_btst_selected_nearmiss_separation",
        "generated_on": str(date.today()),
        "snapshot_count": used_snapshots,
        "snapshot_count_total": len(snapshot_paths),
        "month_filter": month_token or None,
        "decision_counts": decision_counts,
        "gate_counts": gate_counts,
        "decision_gate_counts": decision_gate_counts,
        "selected_minus_near_miss": selected_count - near_miss_count,
        "recommendation": _recommendation(
            selected_count=selected_count,
            near_miss_count=near_miss_count,
            gate_counts=gate_counts,
        ),
        "decision_outcomes": decision_outcome_summaries,
        "decision_gate_outcomes": decision_gate_outcome_summaries,
        "selected_vs_near_miss_delta": {
            "win_rate_next_close": (
                None
                if selected_summary.get("win_rate_next_close") is None or near_miss_summary.get("win_rate_next_close") is None
                else float(selected_summary["win_rate_next_close"]) - float(near_miss_summary["win_rate_next_close"])
            ),
            "hit_rate_5d_15": (
                None
                if selected_summary.get("hit_rate_5d_15") is None or near_miss_summary.get("hit_rate_5d_15") is None
                else float(selected_summary["hit_rate_5d_15"]) - float(near_miss_summary["hit_rate_5d_15"])
            ),
        },
    }


def _render_markdown(analysis: dict[str, Any]) -> str:
    def pct(value: Any) -> str:
        if value is None:
            return "n/a"
        return f"{float(value) * 100:.1f}%"

    def ret(value: Any) -> str:
        if value is None:
            return "n/a"
        return f"{float(value) * 100:+.2f}%"

    lines = [
        "# Selected vs Near Miss Separation",
        "",
        f"**Generated on:** {analysis.get('generated_on', 'N/A')}",
        f"**Snapshots analyzed:** {analysis.get('snapshot_count', 0)}",
        f"**Recommendation:** {analysis.get('recommendation', 'unknown')}",
        "",
        "## Decision Counts",
        "",
        f"- selected: {dict(analysis.get('decision_counts') or {}).get('selected', 0)}",
        f"- near_miss: {dict(analysis.get('decision_counts') or {}).get('near_miss', 0)}",
        "",
        "## Outcome Summary (realized; vs signal-day close)",
        "",
    ]

    outcomes = dict(analysis.get("decision_outcomes") or {})
    for decision in ("selected", "near_miss"):
        summary = dict(outcomes.get(decision) or {})
        if not summary:
            lines.append(f"- {decision}: n/a")
            continue
        lines.append(
            f"- {decision}: n={summary.get('count')}, ok={summary.get('ok_count')}, "
            f"win_rate_close={pct(summary.get('win_rate_next_close'))}, "
            f"mean_gap={ret(summary.get('mean_next_open_return'))}, "
            f"mean_close={ret(summary.get('mean_next_close_return'))}, "
            f"hit_5d_15={pct(summary.get('hit_rate_5d_15'))}"
        )

    delta = dict(analysis.get("selected_vs_near_miss_delta") or {})
    if delta:
        lines.append("")
        lines.append(
            f"- delta(selected - near_miss): win_rate_close={pct(delta.get('win_rate_next_close'))}, hit_5d_15={pct(delta.get('hit_rate_5d_15'))}"
        )

    gate_outcomes = dict(analysis.get("decision_gate_outcomes") or {})
    if gate_outcomes:
        lines.append("")
        lines.append("## Outcome by Gate (realized)")
        lines.append("")
        for decision, buckets in sorted(gate_outcomes.items()):
            bucket_map = dict(buckets or {})
            if not bucket_map:
                continue
            lines.append(f"- {decision}:")
            for gate, summary in sorted(bucket_map.items()):
                summary = dict(summary or {})
                lines.append(
                    f"  - {gate}: n={summary.get('count')}, ok={summary.get('ok_count')}, "
                    f"win_rate_close={pct(summary.get('win_rate_next_close'))}, "
                    f"mean_gap={ret(summary.get('mean_next_open_return'))}, "
                    f"mean_close={ret(summary.get('mean_next_close_return'))}, "
                    f"hit_5d_15={pct(summary.get('hit_rate_5d_15'))}"
                )

    lines.extend(
        [
            "",
            "## Gate Counts",
            "",
            f"- gate_counts: {analysis.get('gate_counts', {})}",
            "",
            "## Decision by Gate",
            "",
        ]
    )
    for decision, gate_counts in dict(analysis.get("decision_gate_counts") or {}).items():
        lines.append(f"- {decision}: {gate_counts}")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "report_dir",
        nargs="?",
        default=str(_DEFAULT_REPORT_DIR),
        help="Directory containing selection_artifacts/ sub-tree (or data/reports root)",
    )
    parser.add_argument("--output-dir", default=str(_OUTPUT_DIR), help="Directory to write reports")
    parser.add_argument("--month", default="", help="Optional YYYYMM filter (e.g. 202605)")
    parser.add_argument("--limit", type=int, default=0, help="Optional max snapshots to analyze (0=unlimited)")
    args = parser.parse_args(argv)

    limit = None if int(args.limit) <= 0 else int(args.limit)
    month = str(args.month).strip() or None
    analysis = analyze_btst_selected_nearmiss_separation(Path(args.report_dir), month=month, limit=limit)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    json_path = output_dir / "p4_btst_selected_nearmiss_separation.json"
    md_path = output_dir / "p4_btst_selected_nearmiss_separation.md"
    json_path.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(_render_markdown(analysis), encoding="utf-8")

    print(f"P4 selected-vs-near_miss separation written to:\n  {json_path}\n  {md_path}")


if __name__ == "__main__":
    main()
