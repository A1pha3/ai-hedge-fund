from __future__ import annotations

import json
from pathlib import Path

from scripts.fill_btst_decision_review_ledger import fill_review_ledger


def test_fill_review_ledger_updates_realized_fields_and_review_label(tmp_path: Path) -> None:
    ledger_path = tmp_path / "ledger.json"
    price_path = tmp_path / "prices.json"
    ledger_path.write_text(
        json.dumps(
            {
                "signal_date": "2026-05-28",
                "next_trade_date": "2026-05-29",
                "rows": [
                    {
                        "ticker": "002222",
                        "role": "formal_selected",
                        "evidence_grade": "B",
                        "trade_bias": "confirmation_only",
                        "execution_state": "confirmable",
                        "release_authority": "market_gate",
                        "realized_next_open": None,
                        "realized_next_high": None,
                        "realized_next_close": None,
                        "review_label": None,
                    }
                ],
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    price_path.write_text(
        json.dumps(
            {
                "002222": {
                    "next_open_return": -0.008,
                    "next_high_return": 0.034,
                    "next_close_return": 0.021,
                }
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    result = fill_review_ledger(
        ledger_path=ledger_path,
        realized_prices_path=price_path,
        output_path=tmp_path / "filled.json",
    )

    row = result["rows"][0]
    assert row["realized_next_open"] == -0.008
    assert row["realized_next_high"] == 0.034
    assert row["realized_next_close"] == 0.021
    assert row["review_label"] == "close_positive"
    assert row["post_close_review_state"] == "close_positive"
    assert row["post_close_review_transition"] == "confirmable->close_positive"
    assert (tmp_path / "filled.json").exists()


def test_fill_review_ledger_marks_missing_realized_price(tmp_path: Path) -> None:
    ledger_path = tmp_path / "ledger.json"
    price_path = tmp_path / "prices.json"
    ledger_path.write_text(
        json.dumps(
            {
                "signal_date": "2026-05-28",
                "next_trade_date": "2026-05-29",
                "rows": [{"ticker": "002222", "execution_state": "watching", "review_label": None}],
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    price_path.write_text("{}\n", encoding="utf-8")

    result = fill_review_ledger(ledger_path=ledger_path, realized_prices_path=price_path)

    assert result["rows"][0]["review_label"] == "missing_realized_price"
    assert result["rows"][0]["post_close_review_state"] == "missing_realized_price"
    assert result["rows"][0]["post_close_review_transition"] == "watching->missing_realized_price"
