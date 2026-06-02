from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from scripts.fill_btst_decision_review_ledger import fill_review_ledger
from scripts.generate_btst_realized_prices import generate_realized_prices


def _read_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write_json(path: str | Path, payload: Any) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _compact_date(value: Any) -> str:
    token = str(value or "").strip()
    if len(token) == 10 and token[4] == "-" and token[7] == "-":
        return token.replace("-", "")
    return token


def _today_iso() -> str:
    return pd.Timestamp("today").strftime("%Y-%m-%d")


def _extract_tickers(payload: dict[str, Any]) -> list[str]:
    rows = payload.get("rows") or []
    if not isinstance(rows, list):
        return []
    tickers: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        t = str(row.get("ticker") or "").strip()
        if t:
            tickers.append(t)
    # stable unique
    seen: set[str] = set()
    out: list[str] = []
    for t in tickers:
        if t in seen:
            continue
        seen.add(t)
        out.append(t)
    return out


def _needs_fill(payload: dict[str, Any]) -> bool:
    rows = payload.get("rows") or []
    if not isinstance(rows, list) or not rows:
        return False
    return any((isinstance(row, dict) and row.get("realized_next_close") is None) for row in rows)


@dataclass
class BackfillStats:
    scanned: int = 0
    skipped_already_filled: int = 0
    skipped_not_due: int = 0
    skipped_empty: int = 0
    filled: int = 0


def backfill_review_ledgers(
    *,
    outputs_root: str | Path = "outputs",
    pattern: str = "**/*btst-decision-review-ledger.json",
    today: str | None = None,
    dry_run: bool = False,
    write_realized_prices: bool = True,
) -> BackfillStats:
    root = Path(outputs_root)
    stats = BackfillStats()
    today_iso = str(today or _today_iso())

    for ledger_path in sorted(root.glob(pattern)):
        stats.scanned += 1
        payload = _read_json(ledger_path)

        rows = payload.get("rows") or []
        if not isinstance(rows, list) or not rows:
            stats.skipped_empty += 1
            continue

        if not _needs_fill(payload):
            stats.skipped_already_filled += 1
            continue

        next_trade_date = str(payload.get("next_trade_date") or "").strip()
        if next_trade_date and next_trade_date >= today_iso:
            # Not due yet (or same-day). Skip to avoid pulling incomplete data.
            stats.skipped_not_due += 1
            continue

        signal_date = str(payload.get("signal_date") or "").strip()
        tickers = _extract_tickers(payload)
        if not signal_date or not tickers:
            stats.skipped_empty += 1
            continue

        signal_compact = _compact_date(signal_date)
        realized_path = ledger_path.parent / f"{signal_compact}-btst-realized-prices.json"

        if dry_run:
            stats.filled += 1
            continue

        realized = generate_realized_prices(signal_date=signal_date, tickers=tickers)

        realized_prices_path = realized_path
        if write_realized_prices:
            _write_json(realized_path, realized)
        else:
            realized_prices_path = ledger_path.parent / f"{signal_compact}-btst-realized-prices.tmp.json"
            _write_json(realized_prices_path, realized)

        fill_review_ledger(
            ledger_path=ledger_path,
            realized_prices_path=realized_prices_path,
            output_path=ledger_path,
        )

        if not write_realized_prices:
            try:
                realized_prices_path.unlink()
            except FileNotFoundError:
                pass

        stats.filled += 1

    return stats


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill BTST decision-review ledgers with realized next-day outcomes.")
    parser.add_argument("--outputs-root", default="outputs")
    parser.add_argument("--pattern", default="**/*btst-decision-review-ledger.json")
    parser.add_argument("--today", help="Override today (YYYY-MM-DD) for deterministic runs")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-write-realized-prices", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    stats = backfill_review_ledgers(
        outputs_root=args.outputs_root,
        pattern=args.pattern,
        today=args.today,
        dry_run=bool(args.dry_run),
        write_realized_prices=not bool(args.no_write_realized_prices),
    )
    print(json.dumps(stats.__dict__, ensure_ascii=False))


if __name__ == "__main__":
    main()
