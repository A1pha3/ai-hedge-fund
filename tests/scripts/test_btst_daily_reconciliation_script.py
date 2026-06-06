from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from scripts.btst_daily_reconciliation import run_btst_daily_reconciliation


def test_btst_daily_reconciliation_backfills_and_writes_md(monkeypatch, tmp_path: Path) -> None:
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

    reports_dir = tmp_path / "data" / "reports"
    reports_dir.mkdir(parents=True)
    (reports_dir / "btst_full_report_20260528.json").write_text(
        json.dumps(
            {
                "trade_date": "20260528",
                "next_date": "20260529",
                "high_confidence": [{"ticker": "002222", "name": "TESTA", "score": 0.8}],
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    idx = pd.to_datetime(["2026-05-28", "2026-05-29", "2026-06-02", "2026-06-03", "2026-06-04", "2026-06-05"])
    frame = pd.DataFrame(
        {
            "open": [10.0, 10.2, 10.3, 10.4, 10.5, 10.6],
            "high": [10.1, 12.0, 10.4, 10.6, 10.7, 10.8],
            "low": [9.8, 10.0, 10.1, 10.2, 10.3, 10.4],
            "close": [10.0, 10.4, 10.2, 10.1, 10.6, 10.5],
        },
        index=idx,
    )

    def fake_get_price_data(ticker: str, start: str, end: str) -> pd.DataFrame:  # noqa: ARG001
        assert ticker == "002222"
        assert start == "2026-05-28"
        return frame

    def fake_get_prices_robust(*args: Any, **kwargs: Any):  # noqa: ANN401
        raise AssertionError("fallback path should not be used in this test")

    monkeypatch.setattr("scripts.generate_btst_realized_prices.get_price_data", fake_get_price_data)
    monkeypatch.setattr("scripts.generate_btst_realized_prices.get_prices_robust", fake_get_prices_robust)

    result = run_btst_daily_reconciliation(
        signal_date="20260528",
        outputs_root=tmp_path / "outputs",
        reports_dir=reports_dir,
        today="2026-06-02",
    )

    assert Path(result.output_md_path).exists()
    assert "BTST Daily Reconciliation 20260528" in Path(result.output_md_path).read_text(encoding="utf-8")

    filled = json.loads(ledger_path.read_text(encoding="utf-8"))
    assert filled["rows"][0]["realized_next_close"] == 0.04
