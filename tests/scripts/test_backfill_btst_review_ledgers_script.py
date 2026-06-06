from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from scripts.backfill_btst_review_ledgers import backfill_review_ledgers


def test_backfill_review_ledgers_fills_in_place(monkeypatch, tmp_path: Path) -> None:
    outputs = tmp_path / "outputs" / "202605" / "20260529"
    outputs.mkdir(parents=True)

    ledger_path = outputs / "20260528-btst-decision-review-ledger.json"
    ledger_path.write_text(
        json.dumps(
            {
                "signal_date": "2026-05-28",
                "next_trade_date": "2026-05-29",
                "rows": [{"ticker": "002222", "execution_state": "watching", "realized_next_close": None}],
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    # Patch price fetch in realized price generator
    idx = pd.to_datetime(["2026-05-28", "2026-05-29"])
    frame = pd.DataFrame(
        {"open": [10.0, 10.2], "high": [10.1, 10.8], "low": [9.9, 10.0], "close": [10.0, 10.4]},
        index=idx,
    )

    def fake_get_price_data(ticker: str, start: str, end: str) -> pd.DataFrame:  # noqa: ARG001
        return frame

    monkeypatch.setattr("scripts.generate_btst_realized_prices.get_price_data", fake_get_price_data)

    stats = backfill_review_ledgers(outputs_root=tmp_path / "outputs", today="2026-06-02")
    assert stats.scanned == 1
    assert stats.filled == 1

    filled = json.loads(ledger_path.read_text(encoding="utf-8"))
    assert filled["rows"][0]["realized_next_close"] == 0.04
    assert filled["rows"][0]["review_label"] == "close_positive"

    realized_path = outputs / "20260528-btst-realized-prices.json"
    assert realized_path.exists()
