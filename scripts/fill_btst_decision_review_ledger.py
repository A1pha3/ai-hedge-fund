from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _read_json(path: str | Path) -> dict[str, Any]:
    return dict(json.loads(Path(path).read_text(encoding="utf-8")))


def _review_label(close_return: Any) -> str:
    if close_return is None:
        return "missing_realized_price"
    try:
        return "close_positive" if float(close_return) > 0 else "close_non_positive"
    except (TypeError, ValueError):
        return "missing_realized_price"


def _post_close_review_transition(execution_state: Any, review_state: str) -> str:
    normalized_execution_state = str(execution_state or "unknown").strip() or "unknown"
    return f"{normalized_execution_state}->{review_state}"


def fill_review_ledger(
    *,
    ledger_path: str | Path,
    realized_prices_path: str | Path,
    output_path: str | Path | None = None,
) -> dict[str, Any]:
    payload = _read_json(ledger_path)
    prices = _read_json(realized_prices_path)
    rows = []
    for row in list(payload.get("rows") or []):
        updated = dict(row)
        ticker = str(updated.get("ticker") or "")
        price = dict(prices.get(ticker) or {})
        if price:
            updated["realized_next_open"] = price.get("next_open_return")
            updated["realized_next_high"] = price.get("next_high_return")
            updated["realized_next_close"] = price.get("next_close_return")
            updated["review_label"] = _review_label(price.get("next_close_return"))
        else:
            updated["review_label"] = "missing_realized_price"
        updated["post_close_review_state"] = updated["review_label"]
        updated["post_close_review_transition"] = _post_close_review_transition(
            updated.get("execution_state"),
            str(updated["review_label"]),
        )
        rows.append(updated)
    result = dict(payload)
    result["rows"] = rows
    if output_path:
        target_path = Path(output_path)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return result


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fill BTST decision review ledger outcomes.")
    parser.add_argument("--ledger-path", required=True)
    parser.add_argument("--realized-prices-path", required=True)
    parser.add_argument("--output-path")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    result = fill_review_ledger(
        ledger_path=args.ledger_path,
        realized_prices_path=args.realized_prices_path,
        output_path=args.output_path,
    )
    print(
        json.dumps(
            {"status": "filled", "row_count": len(result.get("rows") or [])},
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
