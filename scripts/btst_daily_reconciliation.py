from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from scripts.backfill_btst_review_ledgers import backfill_review_ledgers
from scripts.generate_btst_realized_prices import generate_realized_prices


def _load_json(path: str | Path) -> dict[str, Any]:
    resolved = Path(path).expanduser().resolve()
    return json.loads(resolved.read_text(encoding="utf-8"))


def _write_text(path: str | Path, text: str) -> None:
    target = Path(path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


def _compact_date(value: str) -> str:
    token = str(value or "").strip()
    if len(token) == 10 and token[4] == "-" and token[7] == "-":
        return token.replace("-", "")
    return token


def _iso_date(value: str) -> str:
    token = str(value or "").strip()
    if len(token) == 8 and token.isdigit():
        return f"{token[:4]}-{token[4:6]}-{token[6:8]}"
    return token


def _today_iso() -> str:
    return pd.Timestamp("today").strftime("%Y-%m-%d")


@dataclass
class DailyReconcileResult:
    signal_date: str
    outputs_scope: str
    ledger_count: int
    backfill_stats: dict[str, Any]
    report_path: str
    top_n: int
    table_rows: list[dict[str, Any]]
    output_md_path: str


def _find_ledgers(outputs_scope: Path, signal_date_compact: str) -> list[Path]:
    pattern = f"**/{signal_date_compact}-btst-decision-review-ledger.json"
    return [path for path in sorted(outputs_scope.glob(pattern)) if path.is_file()]


def _render_markdown(result: DailyReconcileResult) -> str:
    def pct(value: Any) -> str:
        if value is None:
            return "n/a"
        return f"{float(value) * 100:.2f}%"

    lines: list[str] = []
    lines.append(f"# BTST Daily Reconciliation {result.signal_date}")
    lines.append("")
    lines.append("## Backfill")
    lines.append(f"- outputs_scope: {result.outputs_scope}")
    lines.append(f"- ledgers_found: {result.ledger_count}")
    lines.append(f"- backfill_stats: `{json.dumps(result.backfill_stats, ensure_ascii=False)}`")
    lines.append("")
    lines.append("## Rule report")
    lines.append(f"- {result.report_path}")
    lines.append(f"- high_confidence top_n={result.top_n}")
    lines.append("")

    lines.append("## Realized outcomes (vs T close)")
    lines.append("| ticker | name | status | next_open | next_close | max_high_t1_t5_from_open |")
    lines.append("|---:|---|---|---:|---:|---:|")
    for row in result.table_rows:
        lines.append(
            "| "
            + " | ".join(
                [
                    str(row.get("ticker") or ""),
                    str(row.get("name") or ""),
                    str(row.get("data_status") or ""),
                    pct(row.get("next_open_return")),
                    pct(row.get("next_close_return")),
                    pct(row.get("max_high_t1_t5_from_open")),
                ]
            )
            + " |"
        )
    lines.append("")

    ok = [r for r in result.table_rows if r.get("data_status") == "ok" and r.get("next_open_return") is not None]
    neg_gap = [r for r in ok if float(r["next_open_return"]) < 0]
    nonneg_gap = [r for r in ok if float(r["next_open_return"]) >= 0]
    if ok:
        lines.append("## Gap diagnostic")
        lines.append(f"- gap<0 count={len(neg_gap)}/{len(ok)}")
        lines.append(f"- gap>=0 count={len(nonneg_gap)}/{len(ok)}")
        lines.append("")

    return "\n".join(lines) + "\n"


def run_btst_daily_reconciliation(
    *,
    signal_date: str,
    outputs_root: str | Path = "outputs",
    reports_dir: str | Path = "data/reports",
    top_n: int = 5,
    today: str | None = None,
    output_md: str | Path | None = None,
) -> DailyReconcileResult:
    signal_compact = _compact_date(signal_date)
    if len(signal_compact) != 8 or not signal_compact.isdigit():
        raise SystemExit(f"Invalid signal_date: {signal_date}")

    month = signal_compact[:6]
    outputs_scope = Path(outputs_root).expanduser().resolve() / month
    reports_root = Path(reports_dir).expanduser().resolve()

    ledgers = _find_ledgers(outputs_scope, signal_compact)

    stats = backfill_review_ledgers(
        outputs_root=outputs_scope,
        pattern=f"**/{signal_compact}-btst-decision-review-ledger.json",
        today=str(today or _today_iso()),
    )

    report_path = reports_root / f"btst_full_report_{signal_compact}.json"
    report = _load_json(report_path)
    picks = list(report.get("high_confidence") or [])[: int(top_n)]

    tickers: list[str] = []
    names: dict[str, str] = {}
    for entry in picks:
        ticker = str(entry.get("ticker") or "").strip()
        if not ticker:
            continue
        tickers.append(ticker)
        names[ticker] = str(entry.get("name") or "").strip()

    realized = generate_realized_prices(signal_date=_iso_date(signal_compact), tickers=tickers) if tickers else {}
    table_rows: list[dict[str, Any]] = []
    for ticker in tickers:
        row = dict(realized.get(ticker) or {})
        row["ticker"] = ticker
        row["name"] = names.get(ticker) or ""
        table_rows.append(row)

    resolved_output = None
    if output_md is not None:
        resolved_output = Path(output_md).expanduser().resolve()
    elif len(ledgers) == 1:
        resolved_output = ledgers[0].parent / f"{signal_compact}-btst-daily-reconciliation.md"
    else:
        resolved_output = outputs_scope / f"{signal_compact}-btst-daily-reconciliation.md"

    result = DailyReconcileResult(
        signal_date=signal_compact,
        outputs_scope=str(outputs_scope),
        ledger_count=len(ledgers),
        backfill_stats=stats.__dict__,
        report_path=str(report_path),
        top_n=int(top_n),
        table_rows=table_rows,
        output_md_path=str(resolved_output),
    )

    _write_text(resolved_output, _render_markdown(result))
    return result


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill BTST ledger and generate a daily realized reconciliation summary.")
    parser.add_argument("--signal-date", required=True, help="YYYYMMDD")
    parser.add_argument("--outputs-root", default="outputs")
    parser.add_argument("--reports-dir", default="data/reports")
    parser.add_argument("--top-n", type=int, default=5)
    parser.add_argument("--today", default="")
    parser.add_argument("--output-md", default="")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    result = run_btst_daily_reconciliation(
        signal_date=str(args.signal_date),
        outputs_root=args.outputs_root,
        reports_dir=args.reports_dir,
        top_n=int(args.top_n),
        today=str(args.today).strip() or None,
        output_md=str(args.output_md).strip() or None,
    )
    print(json.dumps({"status": "ok", "output_md": result.output_md_path}, ensure_ascii=False))


if __name__ == "__main__":
    main()
