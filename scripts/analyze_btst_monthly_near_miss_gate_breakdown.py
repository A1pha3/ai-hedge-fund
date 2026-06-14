from __future__ import annotations

import argparse
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def _compact_date(value: str) -> str:
    token = str(value or "").strip()
    if len(token) == 10 and token[4] == "-" and token[7] == "-":
        return token.replace("-", "")
    return token


def _load_json(path: str | Path) -> dict[str, Any]:
    resolved = Path(path).expanduser().resolve()
    return json.loads(resolved.read_text(encoding="utf-8"))


def _write_text(path: str | Path, text: str) -> None:
    target = Path(path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


def _write_json(path: str | Path, payload: Any) -> None:
    _write_text(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def _iter_plan_dirs(*, reports_dir: Path) -> list[Path]:
    return [path for path in sorted(reports_dir.glob("paper_trading_*_plan")) if path.is_dir()]


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


@dataclass
class NearMissRow:
    trade_date: str
    ticker: str
    score_target: float | None
    gate_data: str | None
    gate_execution: str | None
    gate_structural: str | None
    gate_score: str | None
    gate_committee_veto: str | None
    gate_committee: str | None
    execution_blocked: bool | None
    execution_blocked_flags: list[str]
    prior_evidence_count: int | None
    effective_close_pos_rate: float | None
    effective_high_hit_rate: float | None
    prior_regime_gate: str | None


def _extract_gate_status(entry: dict[str, Any]) -> dict[str, str | None]:
    gate = dict(entry.get("gate_status") or {})
    return {
        "data": (str(gate.get("data") or "").strip() or None),
        "execution": (str(gate.get("execution") or "").strip() or None),
        "structural": (str(gate.get("structural") or "").strip() or None),
        "score": (str(gate.get("score") or "").strip() or None),
        "committee_veto": (str(gate.get("committee_veto") or "").strip() or None),
        "committee": (str(gate.get("committee") or "").strip() or None),
    }


def _extract_prior(entry: dict[str, Any]) -> dict[str, Any]:
    prior = dict(entry.get("historical_prior") or {})
    return {
        "prior_evidence_count": _as_int(prior.get("prior_evidence_count") or prior.get("same_ticker_sample_count")),
        "effective_close_pos_rate": _as_float(prior.get("effective_next_close_positive_rate")),
        "effective_high_hit_rate": _as_float(prior.get("effective_next_high_hit_rate_at_threshold")),
        "prior_regime_gate": (str(prior.get("btst_regime_gate") or prior.get("prior_baseline_btst_regime_gate") or "").strip() or None),
    }


def analyze_btst_monthly_near_miss_gate_breakdown(
    *,
    month: str,
    reports_dir: str | Path = "data/reports",
    min_prior_evidence: int = 20,
    high_close_pos_rate: float = 0.65,
) -> dict[str, Any]:
    root = Path(reports_dir).expanduser().resolve()

    selected_runs: dict[str, dict[str, Any]] = {}

    for plan_dir in _iter_plan_dirs(reports_dir=root):
        brief_path = plan_dir / "btst_next_day_trade_brief_latest.json"
        if not brief_path.is_file():
            continue

        try:
            brief = _load_json(brief_path)
        except Exception:
            continue

        trade_date = _compact_date(str(brief.get("trade_date") or "").strip())
        if not trade_date or not trade_date.startswith(str(month).strip()):
            continue

        mtime = float(brief_path.stat().st_mtime)
        prev = selected_runs.get(trade_date)
        if prev is None or float(prev.get("mtime") or 0.0) < mtime:
            selected_runs[trade_date] = {
                "trade_date": trade_date,
                "plan_dir": str(plan_dir),
                "brief_path": str(brief_path),
                "mtime": mtime,
            }

    rows: list[NearMissRow] = []

    for trade_date in sorted(selected_runs.keys()):
        run = dict(selected_runs[trade_date] or {})
        brief = _load_json(str(run.get("brief_path") or ""))

        for entry in list(brief.get("near_miss_entries") or []):
            if not isinstance(entry, dict):
                continue
            ticker = str(entry.get("ticker") or "").strip()
            if not ticker:
                continue

            gate = _extract_gate_status(entry)
            prior = _extract_prior(entry)

            blocked_flags = list(entry.get("execution_blocked_flags") or [])
            blocked_flags = [str(x) for x in blocked_flags if str(x).strip()]

            rows.append(
                NearMissRow(
                    trade_date=trade_date,
                    ticker=ticker,
                    score_target=_as_float(entry.get("score_target")),
                    gate_data=gate.get("data"),
                    gate_execution=gate.get("execution"),
                    gate_structural=gate.get("structural"),
                    gate_score=gate.get("score"),
                    gate_committee_veto=gate.get("committee_veto"),
                    gate_committee=gate.get("committee"),
                    execution_blocked=(bool(entry.get("execution_blocked")) if entry.get("execution_blocked") is not None else None),
                    execution_blocked_flags=blocked_flags,
                    prior_evidence_count=prior.get("prior_evidence_count"),
                    effective_close_pos_rate=prior.get("effective_close_pos_rate"),
                    effective_high_hit_rate=prior.get("effective_high_hit_rate"),
                    prior_regime_gate=prior.get("prior_regime_gate"),
                )
            )

    def _counter(key: str) -> dict[str, int]:
        c = Counter(str(getattr(r, key) or "unknown").strip() or "unknown" for r in rows)
        return dict(sorted(c.items(), key=lambda kv: (-kv[1], kv[0])))

    def _flag_counter() -> dict[str, int]:
        c = Counter()
        for r in rows:
            for f in r.execution_blocked_flags:
                c[str(f)] += 1
        return dict(sorted(c.items(), key=lambda kv: (-kv[1], kv[0])))

    high_potential = [
        r
        for r in rows
        if (r.prior_evidence_count or 0) >= int(min_prior_evidence)
        and (r.effective_close_pos_rate is not None and float(r.effective_close_pos_rate) >= float(high_close_pos_rate))
    ]

    overall = {
        "month": str(month),
        "source": "paper_trading.trade_brief.near_miss_entries",
        "trade_date_count": len(selected_runs),
        "near_miss_row_count": len(rows),
        "min_prior_evidence": int(min_prior_evidence),
        "high_close_pos_rate": float(high_close_pos_rate),
        "high_potential_row_count": len(high_potential),
        "by_gate_execution": _counter("gate_execution"),
        "by_gate_committee": _counter("gate_committee"),
        "by_gate_score": _counter("gate_score"),
        "by_prior_regime_gate": _counter("prior_regime_gate"),
        "by_execution_blocked": _counter("execution_blocked"),
        "by_execution_blocked_flag": _flag_counter(),
        "high_potential_by_gate_committee": dict(
            sorted(
                Counter(str(r.gate_committee or "unknown") for r in high_potential).items(),
                key=lambda kv: (-kv[1], kv[0]),
            )
        ),
        "high_potential_by_gate_execution": dict(
            sorted(
                Counter(str(r.gate_execution or "unknown") for r in high_potential).items(),
                key=lambda kv: (-kv[1], kv[0]),
            )
        ),
    }

    return {
        "month": str(month),
        "reports_dir": str(root),
        "overall": overall,
        "rows": [r.__dict__ for r in rows],
        "selected_runs": [selected_runs[key] for key in sorted(selected_runs.keys())],
    }


def render_btst_monthly_near_miss_gate_breakdown_markdown(analysis: dict[str, Any]) -> str:
    overall = dict(analysis.get("overall") or {})
    lines: list[str] = []
    month = str(analysis.get("month") or "")

    def top_k(d: dict[str, Any], k: int = 10) -> list[tuple[str, Any]]:
        items = list((d or {}).items())
        items.sort(key=lambda kv: (-int(kv[1] or 0), str(kv[0])))
        return items[:k]

    lines.append(f"# BTST Monthly Near-miss Gate Breakdown {month}")
    lines.append("")
    lines.append("## Overall")
    lines.append(f"- source: {overall.get('source')}")
    lines.append(f"- trade_date_count: {overall.get('trade_date_count')}, near_miss_row_count: {overall.get('near_miss_row_count')}")
    lines.append(
        f"- high_potential filter: prior_evidence_count>={overall.get('min_prior_evidence')} AND effective_close_pos_rate>={overall.get('high_close_pos_rate')}"
    )
    lines.append(f"- high_potential_row_count: {overall.get('high_potential_row_count')}")

    def section(title: str, key: str) -> None:
        data = dict(overall.get(key) or {})
        if not data:
            return
        lines.append("")
        lines.append(f"## {title}")
        for name, count in top_k(data, 12):
            lines.append(f"- {name}: {count}")

    section("Gate: execution", "by_gate_execution")
    section("Gate: committee", "by_gate_committee")
    section("Gate: score", "by_gate_score")
    section("Prior baseline regime gate", "by_prior_regime_gate")
    section("Execution blocked flag", "by_execution_blocked_flag")

    lines.append("")
    lines.append("## High-potential near-miss (breakdown)")
    hp_comm = dict(overall.get("high_potential_by_gate_committee") or {})
    hp_exec = dict(overall.get("high_potential_by_gate_execution") or {})
    if hp_comm:
        lines.append("- by committee gate:")
        for name, count in top_k(hp_comm, 12):
            lines.append(f"  - {name}: {count}")
    if hp_exec:
        lines.append("- by execution gate:")
        for name, count in top_k(hp_exec, 12):
            lines.append(f"  - {name}: {count}")

    lines.append("")
    lines.append("## Notes")
    lines.append("- Use this to identify which gates keep near-miss entries from becoming formal-selected.")
    lines.append("- High-potential is based on historical_prior effective rates (still subject to overfitting; review carefully).")

    return "\n".join(lines) + "\n"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze BTST near-miss gate breakdown for a month")
    parser.add_argument("--month", required=True, help="YYYYMM, e.g. 202605")
    parser.add_argument("--reports-dir", default="data/reports")
    parser.add_argument("--min-prior-evidence", type=int, default=20)
    parser.add_argument("--high-close-pos-rate", type=float, default=0.65)
    parser.add_argument("--output-json", default=None)
    parser.add_argument("--output-md", default=None)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    analysis = analyze_btst_monthly_near_miss_gate_breakdown(
        month=args.month,
        reports_dir=args.reports_dir,
        min_prior_evidence=int(args.min_prior_evidence),
        high_close_pos_rate=float(args.high_close_pos_rate),
    )
    markdown = render_btst_monthly_near_miss_gate_breakdown_markdown(analysis)

    if args.output_json:
        _write_json(args.output_json, analysis)
    if args.output_md:
        _write_text(args.output_md, markdown)

    if not args.output_md:
        print(markdown)


if __name__ == "__main__":
    main()
