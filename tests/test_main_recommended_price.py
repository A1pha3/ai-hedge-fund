"""NS-1: inject trade-date close as ``recommended_price`` into auto_screening recs.

Root cause (owner 2026-06-25 deep-audit, §三·6 NS-1): ``_build_auto_screening_payload``
emitted ``recommendations`` without any price field, so
``recommendation_tracker._coerce_recommended_price`` walked
``recommended_price`` → ``entry_price`` → ``close``, found none, and fell through
to ``return 0.0`` — polluting every ``tracking_history`` record's
``recommended_price`` with 0.0, which then corrupts downstream diagnostics /
calibration / attribution.

Fix: a pure helper reads the batch daily-price frame for the trade date, maps
``ts_code`` ("000001.SZ") → 6-digit ticker, and injects the close as
``recommended_price`` on each recommendation that lacks one. The fetcher is
injectable so the unit test needs no network.
"""

from __future__ import annotations

import pandas as pd

from src.main import _inject_recommended_prices


def _rec(ticker: str, **overrides) -> dict:
    rec = {"ticker": ticker, "name": "测试", "score_b": 0.45}
    rec.update(overrides)
    return rec


def _price_frame(rows: list[tuple[str, float]]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["ts_code", "close"])


def test_injects_close_as_recommended_price_for_matching_tickers() -> None:
    """NS-1: matching ticker gets the trade-date close as recommended_price."""
    recs = [_rec("000001"), _rec("688008")]
    df = _price_frame([("000001.SZ", 12.34), ("688008.SH", 55.5)])
    out = _inject_recommended_prices(recs, "20260623", price_frame_fetcher=lambda _d: df)
    assert out[0]["recommended_price"] == 12.34
    assert out[1]["recommended_price"] == 55.5


def test_skips_ticker_absent_from_price_frame_no_fake_price() -> None:
    """NS-1: a ticker not in the price frame must NOT get a fabricated price."""
    recs = [_rec("000001"), _rec("300999")]  # 300999 not in frame
    df = _price_frame([("000001.SZ", 12.34)])
    out = _inject_recommended_prices(recs, "20260623", price_frame_fetcher=lambda _d: df)
    assert out[0]["recommended_price"] == 12.34
    assert "recommended_price" not in out[1], "absent ticker must not get a fake price"


def test_no_injection_when_price_frame_unavailable() -> None:
    """NS-1: data unavailable (None/empty) → recs unchanged, never fake."""
    recs = [_rec("000001")]
    out_none = _inject_recommended_prices(recs, "20260623", price_frame_fetcher=lambda _d: None)
    assert "recommended_price" not in out_none[0]
    out_empty = _inject_recommended_prices(recs, "20260623", price_frame_fetcher=lambda _d: pd.DataFrame())
    assert "recommended_price" not in out_empty[0]


def test_does_not_overwrite_existing_nonzero_recommended_price() -> None:
    """NS-1: a rec that already carries a real price is not clobbered."""
    recs = [_rec("000001", recommended_price=99.9)]
    df = _price_frame([("000001.SZ", 12.34)])
    out = _inject_recommended_prices(recs, "20260623", price_frame_fetcher=lambda _d: df)
    assert out[0]["recommended_price"] == 99.9, "pre-existing real price must win"


def test_skips_nonpositive_close_in_price_frame() -> None:
    """NS-1: a 0/NaN close row must not produce a fake/zero recommended_price."""
    recs = [_rec("000001"), _rec("000002")]
    df = _price_frame([("000001.SZ", 0.0), ("000002.SZ", float("nan"))])
    out = _inject_recommended_prices(recs, "20260623", price_frame_fetcher=lambda _d: df)
    assert "recommended_price" not in out[0]
    assert "recommended_price" not in out[1]
