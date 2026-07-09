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


# C-TRACKING-PRICE-BACKFILL: 隔离 batch-fetcher 行为的 no-op cache loader.
# 旧测试验证 batch fetcher 注入语义; price_cache fallback 默认走真实文件系统,
# 若测试 ticker 恰在 price_cache 会误触发 fallback → 注入 no-op loader 锁定旧语义.
_NO_CACHE = lambda _t, _d: None  # noqa: E731


def test_injects_close_as_recommended_price_for_matching_tickers() -> None:
    """NS-1: matching ticker gets the trade-date close as recommended_price."""
    recs = [_rec("000001"), _rec("688008")]
    df = _price_frame([("000001.SZ", 12.34), ("688008.SH", 55.5)])
    out = _inject_recommended_prices(recs, "20260623", price_frame_fetcher=lambda _d: df, price_cache_loader=_NO_CACHE)
    assert out[0]["recommended_price"] == 12.34
    assert out[1]["recommended_price"] == 55.5


def test_skips_ticker_absent_from_price_frame_no_fake_price() -> None:
    """NS-1: a ticker not in the price frame must NOT get a fabricated price."""
    recs = [_rec("000001"), _rec("300999")]  # 300999 not in frame
    df = _price_frame([("000001.SZ", 12.34)])
    out = _inject_recommended_prices(recs, "20260623", price_frame_fetcher=lambda _d: df, price_cache_loader=_NO_CACHE)
    assert out[0]["recommended_price"] == 12.34
    assert "recommended_price" not in out[1], "absent ticker must not get a fake price"


def test_no_injection_when_price_frame_unavailable() -> None:
    """NS-1: data unavailable (None/empty) → recs unchanged, never fake."""
    recs = [_rec("000001")]
    out_none = _inject_recommended_prices(recs, "20260623", price_frame_fetcher=lambda _d: None, price_cache_loader=_NO_CACHE)
    assert "recommended_price" not in out_none[0]
    out_empty = _inject_recommended_prices(recs, "20260623", price_frame_fetcher=lambda _d: pd.DataFrame(), price_cache_loader=_NO_CACHE)
    assert "recommended_price" not in out_empty[0]


def test_does_not_overwrite_existing_nonzero_recommended_price() -> None:
    """NS-1: a rec that already carries a real price is not clobbered."""
    recs = [_rec("000001", recommended_price=99.9)]
    df = _price_frame([("000001.SZ", 12.34)])
    out = _inject_recommended_prices(recs, "20260623", price_frame_fetcher=lambda _d: df, price_cache_loader=_NO_CACHE)
    assert out[0]["recommended_price"] == 99.9, "pre-existing real price must win"


def test_skips_nonpositive_close_in_price_frame() -> None:
    """NS-1: a 0/NaN close row must not produce a fake/zero recommended_price."""
    recs = [_rec("000001"), _rec("000002")]
    df = _price_frame([("000001.SZ", 0.0), ("000002.SZ", float("nan"))])
    out = _inject_recommended_prices(recs, "20260623", price_frame_fetcher=lambda _d: df, price_cache_loader=_NO_CACHE)
    assert "recommended_price" not in out[0]
    assert "recommended_price" not in out[1]


def test_price_cache_fallback_when_batch_fetcher_lacks_ticker() -> None:
    """C-TRACKING-PRICE-BACKFILL: batch fetcher 缺某 ticker 时, price_cache 回退注入.

    Bug (20260710): 20260709 Top-N 10 只中 4 只 (002049/300184/300308/600392) 在
    batch df 缺失但 price_cache 有 → 旧代码直接 price=0 → tracking 永久残留 0.
    修复: batch 缺失时回退 price_cache 取当日 close.
    """
    recs = [_rec("000001"), _rec("300308")]  # 300308 不在 batch frame
    df = _price_frame([("000001.SZ", 12.34)])  # batch 只有 000001
    cache = lambda t, d: 1194.90 if t == "300308" else None  # noqa: E731
    out = _inject_recommended_prices(recs, "20260709", price_frame_fetcher=lambda _d: df, price_cache_loader=cache)
    assert out[0]["recommended_price"] == 12.34  # 000001 走 batch
    assert out[1]["recommended_price"] == 1194.90, "300308 应从 price_cache fallback 拿到价"


def test_price_cache_fallback_skips_when_cache_also_missing() -> None:
    """C-TRACKING-PRICE-BACKFILL: batch + price_cache 都缺 → 仍不伪造价格 (None)."""
    recs = [_rec("300999")]  # 既不在 batch 也不在 cache
    df = _price_frame([("000001.SZ", 12.34)])
    cache = lambda t, d: None  # noqa: E731
    out = _inject_recommended_prices(recs, "20260709", price_frame_fetcher=lambda _d: df, price_cache_loader=cache)
    assert "recommended_price" not in out[0], "双源都缺时绝不伪造价格"


def test_price_cache_fallback_when_batch_frame_entirely_unavailable() -> None:
    """C-TRACKING-PRICE-BACKFILL: batch frame 完全不可用时, 全量走 price_cache fallback.

    旧代码: batch 不可用直接 return → 全量 price=0. 修复: 仍尝试 price_cache.
    """
    recs = [_rec("000001"), _rec("688008")]
    cache = lambda t, d: {"000001": 10.0, "688008": 20.0}.get(t)  # noqa: E731
    out = _inject_recommended_prices(recs, "20260709", price_frame_fetcher=lambda _d: None, price_cache_loader=cache)
    assert out[0]["recommended_price"] == 10.0
    assert out[1]["recommended_price"] == 20.0
