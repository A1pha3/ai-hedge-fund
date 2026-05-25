from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any


def analyze_upstream_shadow_repeat_saturation(dossier_path: str | Path) -> dict[str, Any]:
    """Build the repeat-saturation board from an upstream-shadow FN/FP dossier.

    A ticker is blocked when it has repeated misses first: at least two false-negative
    rows before the first false-positive, with total events ≥ 3. That narrows the board
    to genuine repeat-saturation flips instead of a single miss followed by weakness.
    """
    resolved_path = Path(dossier_path).expanduser().resolve()
    payload = json.loads(resolved_path.read_text(encoding="utf-8"))

    per_ticker: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in list(payload.get("false_negative_rows") or []):
        per_ticker[str(row.get("ticker") or "")].append({**dict(row), "classification": "false_negative"})
    for row in list(payload.get("false_positive_rows") or []):
        per_ticker[str(row.get("ticker") or "")].append({**dict(row), "classification": "false_positive"})

    blocked_rows: list[dict[str, Any]] = []
    for ticker, rows in per_ticker.items():
        if not ticker or len(rows) < 3:
            continue
        rows.sort(key=lambda r: str(r.get("trade_date") or ""))
        classifications = [str(r.get("classification") or "") for r in rows]
        if "false_negative" not in classifications or "false_positive" not in classifications:
            continue
        first_fp_index = classifications.index("false_positive")
        fn_before_first_fp = sum(1 for label in classifications[:first_fp_index] if label == "false_negative")
        if first_fp_index == 0 or fn_before_first_fp < 2:
            continue
        blocked_rows.append(
            {
                "ticker": ticker,
                "block_reason": "fn_to_fp_flip_after_repeat_shadow_hits",
                "event_count": len(rows),
                "false_negative_count_before_first_false_positive": fn_before_first_fp,
                "first_false_positive_trade_date": rows[first_fp_index].get("trade_date"),
                "rows": rows,
            }
        )

    blocked_rows.sort(key=lambda r: (-int(r.get("event_count") or 0), str(r.get("ticker") or "")))
    return {
        "dossier_path": str(resolved_path),
        "blocked_rows": blocked_rows,
        "focus_blocked_tickers": [str(r.get("ticker") or "") for r in blocked_rows],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build upstream-shadow repeat-saturation board from FN/FP dossier.")
    parser.add_argument("--dossier-json", required=True, help="Path to the FN/FP dossier JSON file.")
    parser.add_argument("--output-json", required=True, help="Path to write the saturation board JSON artifact.")
    args = parser.parse_args()

    analysis = analyze_upstream_shadow_repeat_saturation(args.dossier_json)
    output_path = Path(args.output_json).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(analysis, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
