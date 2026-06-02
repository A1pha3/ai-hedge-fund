from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from scripts.analyze_btst_monthly_scorecard import analyze_btst_monthly_scorecard, render_btst_monthly_scorecard_markdown


def test_analyze_btst_monthly_scorecard_aggregates_high_confidence(monkeypatch, tmp_path: Path) -> None:
    reports_dir = tmp_path / "data" / "reports"
    reports_dir.mkdir(parents=True)

    # Two daily rule reports in the same month
    (reports_dir / "btst_full_report_20260528.json").write_text(
        json.dumps(
            {
                "trade_date": "20260528",
                "next_date": "20260529",
                "high_confidence": [
                    {
                        "ticker": "002222",
                        "name": "TESTA",
                        "score": 0.8,
                        "pct_chg": 12.0,
                        "close_strength": 1.0,
                        "catalyst_freshness": 1.0,
                    }
                ],
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    (reports_dir / "btst_full_report_20260529.json").write_text(
        json.dumps(
            {
                "trade_date": "20260529",
                "next_date": "20260530",
                "high_confidence": [
                    {
                        "ticker": "300054",
                        "name": "TESTB",
                        "score": 0.7,
                        "pct_chg": 3.0,
                        "close_strength": 1.0,
                        "catalyst_freshness": 1.0,
                    }
                ],
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    # Patch market data fetch: return deterministic frames per signal date
    idx1 = pd.to_datetime(["2026-05-28", "2026-05-29", "2026-06-02", "2026-06-03", "2026-06-04", "2026-06-05"])
    frame1 = pd.DataFrame(
        {
            "open": [10.0, 10.2, 10.3, 10.4, 10.5, 10.6],
            "high": [10.1, 12.0, 10.4, 10.6, 10.7, 10.8],
            "low": [9.8, 10.0, 10.1, 10.2, 10.3, 10.4],
            "close": [10.0, 10.4, 10.2, 10.1, 10.6, 10.5],
        },
        index=idx1,
    )

    idx2 = pd.to_datetime(["2026-05-29", "2026-06-02"])
    frame2 = pd.DataFrame(
        {"open": [20.0, 19.5], "high": [20.2, 19.8], "low": [19.8, 19.0], "close": [20.0, 19.2]},
        index=idx2,
    )

    def fake_get_price_data(ticker: str, start: str, end: str) -> pd.DataFrame:  # noqa: ARG001
        if start == "2026-05-28":
            return frame1
        if start == "2026-05-29":
            return frame2
        raise AssertionError(f"unexpected start date: {start}")

    def fake_get_prices_robust(*args: Any, **kwargs: Any):  # noqa: ANN401
        raise AssertionError("fallback path should not be used in this test")

    monkeypatch.setattr("scripts.generate_btst_realized_prices.get_price_data", fake_get_price_data)
    monkeypatch.setattr("scripts.generate_btst_realized_prices.get_prices_robust", fake_get_prices_robust)

    analysis = analyze_btst_monthly_scorecard(month="202605", reports_dir=reports_dir, top_n=1)

    assert analysis["month"] == "202605"
    assert analysis["overall"]["pick_count"] == 2
    assert analysis["overall"]["ok_count"] == 2

    # Day1 close return: 10.4/10.0-1 = 0.04 (win)
    # Day2 close return: 19.2/20.0-1 = -0.04 (loss)
    assert analysis["overall"]["win_rate_next_close"] == 0.5

    segments = analysis["overall"]["gap_segments"]
    assert segments["negative"]["count"] == 1
    assert segments["negative"]["win_rate_next_close"] == 0.0
    assert segments["non_negative"]["count"] == 1
    assert segments["non_negative"]["win_rate_next_close"] == 1.0

    pct_buckets = analysis["overall"]["pct_chg_buckets"]
    assert pct_buckets["pct<=5"]["count"] == 1
    assert pct_buckets["10<pct<=20"]["count"] == 1

    md = render_btst_monthly_scorecard_markdown(analysis)
    assert "BTST Monthly Scorecard 202605" in md
    assert "Daily breakdown" in md
    assert "gap<0" in md
