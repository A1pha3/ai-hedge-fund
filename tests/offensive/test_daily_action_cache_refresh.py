from __future__ import annotations

import json

import pandas as pd


def _daily_prices(rows: list[dict]) -> pd.DataFrame:
    defaults = {
        "ts_code": "000001.SZ",
        "trade_date": "20260708",
        "open": 10.0,
        "high": 10.5,
        "low": 9.8,
        "close": 10.2,
        "pct_chg": 2.0,
        "vol": 12345.0,
    }
    return pd.DataFrame([{**defaults, **row} for row in rows])


def _history_rows(start: str = "2026-05-20", periods: int = 35) -> pd.DataFrame:
    dates = pd.bdate_range(start, periods=periods)
    return pd.DataFrame(
        {
            "date": [date.strftime("%Y-%m-%d") for date in dates],
            "close": [10.0 + index * 0.1 for index in range(periods)],
            "open": [9.9 + index * 0.1 for index in range(periods)],
            "high": [10.2 + index * 0.1 for index in range(periods)],
            "low": [9.8 + index * 0.1 for index in range(periods)],
            "pct_change": [1.0 for _ in range(periods)],
            "volume": [1000.0 + index for index in range(periods)],
        }
    )


def test_resolve_daily_action_refresh_tickers_includes_candidate_pool(tmp_path):
    from src.screening.offensive.cache_refresh import resolve_daily_action_refresh_tickers

    price_cache = tmp_path / "price_cache"
    price_cache.mkdir()
    (price_cache / "000001.csv").write_text("date,close\n2026-07-08,10\n", encoding="utf-8")

    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()
    (snapshot_dir / "candidate_pool_20260708.json").write_text(
        json.dumps(
            [
                {"ticker": "000002"},
                {"ticker": "bad"},
                {"ts_code": "000003.SZ"},
            ]
        ),
        encoding="utf-8",
    )

    tickers = resolve_daily_action_refresh_tickers(
        "20260708",
        price_cache_dir=price_cache,
        snapshot_dir=snapshot_dir,
    )

    assert tickers == ["000001", "000002", "000003"]


def test_refresh_price_cache_updates_existing_tickers_only(tmp_path):
    from src.screening.offensive.cache_refresh import refresh_price_cache_from_daily_batch

    price_cache = tmp_path / "price_cache"
    price_cache.mkdir()
    (price_cache / "000001.csv").write_text(
        "date,close,open,high,low,pct_change,volume\n" "2026-07-06,9.8,9.7,9.9,9.6,1.1,1000\n",
        encoding="utf-8",
    )

    stats = refresh_price_cache_from_daily_batch(
        "20260708",
        price_cache_dir=price_cache,
        daily_prices_df=_daily_prices(
            [
                {
                    "ts_code": "000001.SZ",
                    "close": 10.2,
                    "open": 10.0,
                    "high": 10.5,
                    "low": 9.9,
                    "pct_chg": 4.08,
                    "vol": 2345.0,
                },
                {"ts_code": "000002.SZ", "close": 20.0},
            ]
        ),
    )

    updated = pd.read_csv(price_cache / "000001.csv", dtype={"date": str})
    assert list(updated["date"]) == ["2026-07-06", "2026-07-08"]
    latest = updated.iloc[-1]
    assert latest["close"] == 10.2
    assert latest["open"] == 10.0
    assert latest["high"] == 10.5
    assert latest["low"] == 9.9
    assert latest["pct_change"] == 4.08
    assert latest["volume"] == 2345.0
    assert not (price_cache / "000002.csv").exists()
    assert stats.price_total == 1
    assert stats.price_updated == 1
    assert stats.price_missing == 0


def test_refresh_price_cache_rejects_stale_daily_batch_rows(tmp_path):
    from src.screening.offensive.cache_refresh import refresh_price_cache_from_daily_batch

    price_cache = tmp_path / "price_cache"
    price_cache.mkdir()
    (price_cache / "000001.csv").write_text(
        "date,close,open,high,low,pct_change,volume\n" "2026-07-06,9.8,9.7,9.9,9.6,1.1,1000\n",
        encoding="utf-8",
    )

    stats = refresh_price_cache_from_daily_batch(
        "20260708",
        price_cache_dir=price_cache,
        daily_prices_df=_daily_prices(
            [
                {
                    "ts_code": "000001.SZ",
                    "trade_date": "20260706",
                    "close": 10.6,
                    "pct_chg": 8.16,
                    "vol": 3000.0,
                }
            ]
        ),
    )

    updated = pd.read_csv(price_cache / "000001.csv", dtype={"date": str})
    assert list(updated["date"]) == ["2026-07-06"]
    assert updated.iloc[0]["close"] == 9.8
    assert stats.price_updated == 0
    assert stats.price_missing == 1


def test_refresh_price_cache_backfills_new_target_ticker_before_daily_row(tmp_path):
    from src.screening.offensive.cache_refresh import refresh_price_cache_from_daily_batch

    price_cache = tmp_path / "price_cache"
    price_cache.mkdir()
    (price_cache / "000001.csv").write_text(
        "date,close,open,high,low,pct_change,volume\n" "2026-07-06,9.8,9.7,9.9,9.6,1.1,1000\n",
        encoding="utf-8",
    )

    backfilled: list[tuple[str, str, str]] = []

    def backfill_price_history(ticker: str, start_date: str, end_date: str) -> pd.DataFrame:
        backfilled.append((ticker, start_date, end_date))
        assert ticker == "000002"
        assert end_date == "20260708"
        return _history_rows()

    stats = refresh_price_cache_from_daily_batch(
        "20260708",
        price_cache_dir=price_cache,
        target_tickers=["000001", "000002"],
        daily_prices_df=_daily_prices(
            [
                {"ts_code": "000001.SZ", "close": 10.2, "pct_chg": 4.08, "vol": 2345.0},
                {"ts_code": "000002.SZ", "close": 20.0, "pct_chg": 5.0, "vol": 3456.0},
            ]
        ),
        backfill_price_history_fn=backfill_price_history,
    )

    created = pd.read_csv(price_cache / "000002.csv", dtype={"date": str})
    assert backfilled == [("000002", "20250604", "20260708")]  # 400-day lookback from 20260708
    assert len(created) == 36
    assert created.iloc[-1]["date"] == "2026-07-08"
    assert created.iloc[-1]["close"] == 20.0
    assert stats.price_total == 2
    assert stats.price_backfilled == 1
    assert stats.price_updated == 2
    assert stats.price_missing == 0


def test_refresh_price_cache_rejects_new_target_with_insufficient_history(tmp_path):
    from src.screening.offensive.cache_refresh import refresh_price_cache_from_daily_batch

    price_cache = tmp_path / "price_cache"
    price_cache.mkdir()

    stats = refresh_price_cache_from_daily_batch(
        "20260708",
        price_cache_dir=price_cache,
        target_tickers=["000002"],
        daily_prices_df=_daily_prices([{"ts_code": "000002.SZ", "close": 20.0}]),
        backfill_price_history_fn=lambda *_args: _history_rows(periods=5),
    )

    assert not (price_cache / "000002.csv").exists()
    assert stats.price_total == 1
    assert stats.price_backfilled == 0
    assert stats.price_insufficient_history == 1
    assert stats.price_updated == 0


def test_refresh_daily_action_caches_uses_candidate_pool_for_price_and_fund_flow(tmp_path):
    from src.screening.offensive.cache_refresh import refresh_daily_action_caches

    price_cache = tmp_path / "price_cache"
    price_cache.mkdir()
    (price_cache / "000001.csv").write_text(
        "date,close,open,high,low,pct_change,volume\n" "2026-07-06,9.8,9.7,9.9,9.6,1.1,1000\n",
        encoding="utf-8",
    )

    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()
    (snapshot_dir / "candidate_pool_20260708.json").write_text(
        json.dumps([{"ticker": "000002"}]),
        encoding="utf-8",
    )

    fund_flow_tickers: list[str] = []

    def fund_flow_fetch(ticker: str, start_date: str, end_date: str) -> pd.DataFrame:
        fund_flow_tickers.append(ticker)
        return pd.DataFrame(
            [
                {
                    "date": pd.Timestamp("2026-07-08"),
                    "close": 10.2,
                    "pct_change": 2.0,
                    "main_net_inflow": 1000000.0,
                    "main_net_pct": 3.5,
                }
            ]
        )

    stats = refresh_daily_action_caches(
        "20260708",
        price_cache_dir=price_cache,
        fund_flow_cache_dir=tmp_path / "fund_flow_cache",
        snapshot_dir=snapshot_dir,
        daily_prices_df=_daily_prices(
            [
                {"ts_code": "000001.SZ", "close": 10.2},
                {"ts_code": "000002.SZ", "close": 20.0},
            ]
        ),
        backfill_price_history_fn=lambda *_args: _history_rows(),
        fund_flow_fetch_fn=fund_flow_fetch,
        refresh_industry_index=False,
        fund_flow_rate_limit_sec=0,
    )

    assert (price_cache / "000002.csv").exists()
    assert stats.price_total == 2
    assert stats.price_backfilled == 1
    assert stats.fund_flow_total == 2
    assert set(fund_flow_tickers) == {"000001", "000002"}


def test_refresh_daily_action_caches_refreshes_industry_index_for_trade_date(tmp_path):
    from src.screening.offensive.cache_refresh import refresh_daily_action_caches

    calls: list[str] = []

    stats = refresh_daily_action_caches(
        "20260708",
        price_cache_dir=tmp_path / "price_cache",
        fund_flow_cache_dir=tmp_path / "fund_flow_cache",
        snapshot_dir=tmp_path / "snapshots",
        daily_prices_df=pd.DataFrame(),
        refresh_fund_flow=False,
        industry_index_backfill_fn=lambda *, end_date: calls.append(end_date) or {"农林牧渔": 1502},
    )

    assert calls == ["20260708"]
    assert stats.industry_index_total == 1502
    assert stats.industry_index_failed == 0


def test_refresh_price_cache_is_idempotent_for_same_trade_date(tmp_path):
    from src.screening.offensive.cache_refresh import refresh_price_cache_from_daily_batch

    price_cache = tmp_path / "price_cache"
    price_cache.mkdir()
    (price_cache / "000001.csv").write_text(
        "date,close,open,high,low,pct_change,volume\n" "2026-07-08,9.8,9.7,9.9,9.6,1.1,1000\n",
        encoding="utf-8",
    )

    stats = refresh_price_cache_from_daily_batch(
        "20260708",
        price_cache_dir=price_cache,
        daily_prices_df=_daily_prices(
            [
                {
                    "ts_code": "000001.SZ",
                    "close": 10.6,
                    "pct_chg": 8.16,
                    "vol": 3000.0,
                }
            ]
        ),
    )

    updated = pd.read_csv(price_cache / "000001.csv", dtype={"date": str})
    assert list(updated["date"]) == ["2026-07-08"]
    assert updated.iloc[0]["close"] == 10.6
    assert updated.iloc[0]["pct_change"] == 8.16
    assert updated.iloc[0]["volume"] == 3000.0
    assert stats.price_updated == 1


def test_refresh_fund_flow_cache_saves_each_existing_ticker(tmp_path):
    from src.screening.offensive.cache_refresh import refresh_fund_flow_cache

    def fake_fetch(ticker: str, start_date: str, end_date: str) -> pd.DataFrame:
        if ticker == "000002":
            return pd.DataFrame()
        return pd.DataFrame(
            [
                {
                    "date": pd.Timestamp("2026-07-08"),
                    "close": 10.2,
                    "pct_change": 2.0,
                    "main_net_inflow": 1000000.0,
                    "main_net_pct": 3.5,
                }
            ]
        )

    fund_flow_cache = tmp_path / "fund_flow_cache"
    stats = refresh_fund_flow_cache(
        ["000001", "000002"],
        "20260708",
        fund_flow_cache_dir=fund_flow_cache,
        fetch_fn=fake_fetch,
        rate_limit_sec=0,
    )

    saved = pd.read_csv(fund_flow_cache / "000001.csv", dtype={"date": str, "ticker": str})
    assert saved.iloc[0]["date"] == "20260708"
    assert saved.iloc[0]["ticker"] == "000001"
    assert saved.iloc[0]["main_net_inflow"] == 1000000.0
    assert not (fund_flow_cache / "000002.csv").exists()
    assert stats.fund_flow_total == 2
    assert stats.fund_flow_saved == 1
    assert stats.fund_flow_empty == 1
    assert stats.fund_flow_failed == 0


def test_fund_flow_store_preserves_zero_padded_ticker(tmp_path):
    from src.screening.offensive.data.fund_flow_store import FundFlowStore

    store = FundFlowStore(cache_dir=tmp_path / "fund_flow_cache")
    store.save(
        "000001",
        pd.DataFrame(
            [
                {
                    "date": pd.Timestamp("2026-07-08"),
                    "close": 10.2,
                    "pct_change": 2.0,
                    "main_net_inflow": 1000000.0,
                    "main_net_pct": 3.5,
                }
            ]
        ),
    )

    records = store.get_range("000001", "20260708", "20260708")

    assert len(records) == 1
    assert records[0].ticker == "000001"


def test_extract_limit_up_tickers_filters_by_pct_and_date():
    """涨停股提取: 只取 pct>=9.5 且 trade_date 匹配的行."""
    from src.screening.offensive.cache_refresh import _extract_limit_up_tickers

    df = _daily_prices(
        [
            {"ts_code": "000001.SZ", "pct_chg": 2.0},   # 非涨停
            {"ts_code": "000002.SZ", "pct_chg": 9.5},   # 涨停 (边界)
            {"ts_code": "000003.SZ", "pct_chg": 10.0},  # 涨停
            {"ts_code": "000004.SZ", "pct_chg": 20.0, "trade_date": "20260706"},  # 涨停但日期不匹配
            {"ts_code": "000005.SZ", "pct_chg": -3.0},  # 跌
        ]
    )
    tickers = _extract_limit_up_tickers(df, "20260708")
    assert tickers == ["000002", "000003"]


def test_extract_limit_up_tickers_handles_empty_and_missing_columns():
    """容错: None / 空 df / 缺列 都返回空列表, 绝不抛异常."""
    from src.screening.offensive.cache_refresh import _extract_limit_up_tickers

    assert _extract_limit_up_tickers(None, "20260708") == []
    assert _extract_limit_up_tickers(pd.DataFrame(), "20260708") == []
    assert _extract_limit_up_tickers(pd.DataFrame({"ts_code": ["000001.SZ"]}), "20260708") == []
    assert _extract_limit_up_tickers(pd.DataFrame({"pct_chg": [10.0]}), "20260708") == []


def test_extract_limit_up_tickers_excludes_beijing_exchange():
    """北交所涨停股 (920xxx/8xxxxx/4xxxxx) 应被过滤: tushare moneyflow 不覆盖北交所,
    注入会导致 refresh_fund_flow_cache 对每只双源均失败。"""
    from src.screening.offensive.cache_refresh import _extract_limit_up_tickers

    df = _daily_prices(
        [
            {"ts_code": "688368.SH", "pct_chg": 10.0},   # 科创板涨停 → 保留
            {"ts_code": "000003.SZ", "pct_chg": 10.0},   # 深市涨停 → 保留
            {"ts_code": "920088.BJ", "pct_chg": 15.0},   # 北交所涨停 → 过滤
            {"ts_code": "920090.BJ", "pct_chg": 12.0},   # 北交所涨停 → 过滤
            {"ts_code": "830879.BJ", "pct_chg": 20.0},   # 北交所涨停 → 过滤
        ]
    )
    tickers = _extract_limit_up_tickers(df, "20260708")
    assert "688368" in tickers
    assert "000003" in tickers
    assert "920088" not in tickers
    assert "920090" not in tickers
    assert "830879" not in tickers


def test_refresh_daily_action_caches_injects_limit_up_tickers(tmp_path):
    """P0 修复核心: 涨停股 (不在候选池/缓存内) 应被注入 price_cache + fund_flow."""
    from src.screening.offensive.cache_refresh import refresh_daily_action_caches

    price_cache = tmp_path / "price_cache"
    price_cache.mkdir()
    (price_cache / "000001.csv").write_text(
        "date,close,open,high,low,pct_change,volume\n2026-07-06,9.8,9.7,9.9,9.6,1.1,1000\n",
        encoding="utf-8",
    )
    # candidate_pool 只含 000001 (已在缓存), 不含 000002/000003 (待注入的涨停股)
    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()
    (snapshot_dir / "candidate_pool_20260708.json").write_text(
        json.dumps([{"ticker": "000001"}]),
        encoding="utf-8",
    )

    fund_flow_tickers: list[str] = []

    def fund_flow_fetch(ticker: str, start_date: str, end_date: str) -> pd.DataFrame:
        fund_flow_tickers.append(ticker)
        return pd.DataFrame(
            [
                {
                    "date": pd.Timestamp("2026-07-08"),
                    "close": 10.2,
                    "pct_change": 2.0,
                    "main_net_inflow": 1000000.0,
                    "main_net_pct": 3.5,
                }
            ]
        )

    # batch df: 000001 非涨停, 000002/000003 涨停 (模拟不在候选池的涨停小盘股)
    daily_df = _daily_prices(
        [
            {"ts_code": "000001.SZ", "pct_chg": 2.0, "close": 10.2},
            {"ts_code": "000002.SZ", "pct_chg": 9.5, "close": 20.0},
            {"ts_code": "000003.SZ", "pct_chg": 10.0, "close": 30.0},
        ]
    )

    stats = refresh_daily_action_caches(
        "20260708",
        price_cache_dir=price_cache,
        fund_flow_cache_dir=tmp_path / "fund_flow_cache",
        snapshot_dir=snapshot_dir,
        daily_prices_df=daily_df,
        backfill_price_history_fn=lambda *_args: _history_rows(),
        fund_flow_fetch_fn=fund_flow_fetch,
        refresh_industry_index=False,
        fund_flow_rate_limit_sec=0,
    )

    # 涨停股被注入并创建缓存文件
    assert (price_cache / "000002.csv").exists()
    assert (price_cache / "000003.csv").exists()
    assert stats.limit_up_injected == 2
    # price_total 包含原候选 (000001) + 注入涨停 (000002, 000003)
    assert stats.price_total == 3
    assert stats.price_backfilled == 2  # 000002/000003 是新票需 backfill
    # fund_flow 也覆盖了注入的涨停股
    assert set(fund_flow_tickers) == {"000001", "000002", "000003"}


def test_refresh_daily_action_caches_limit_up_injection_disabled(tmp_path, monkeypatch):
    """env DAILY_ACTION_INCLUDE_LIMIT_UPS=false 时涨停股不注入."""
    from src.screening.offensive.cache_refresh import refresh_daily_action_caches

    monkeypatch.setenv("DAILY_ACTION_INCLUDE_LIMIT_UPS", "false")

    price_cache = tmp_path / "price_cache"
    price_cache.mkdir()
    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()
    (snapshot_dir / "candidate_pool_20260708.json").write_text(
        json.dumps([{"ticker": "000001"}]),
        encoding="utf-8",
    )

    daily_df = _daily_prices(
        [
            {"ts_code": "000001.SZ", "pct_chg": 2.0, "close": 10.2},
            {"ts_code": "000002.SZ", "pct_chg": 10.0, "close": 20.0},  # 涨停但应被忽略
        ]
    )

    stats = refresh_daily_action_caches(
        "20260708",
        price_cache_dir=price_cache,
        fund_flow_cache_dir=tmp_path / "fund_flow_cache",
        snapshot_dir=snapshot_dir,
        daily_prices_df=daily_df,
        backfill_price_history_fn=lambda *_args: _history_rows(),
        fund_flow_fetch_fn=lambda *_a: pd.DataFrame(),
        refresh_industry_index=False,
        fund_flow_rate_limit_sec=0,
    )

    assert stats.limit_up_injected == 0
    assert not (price_cache / "000002.csv").exists()


def test_refresh_daily_action_caches_limit_up_not_double_counted_when_in_cache(tmp_path):
    """涨停股若已在 price_cache, limit_up_injected 不重复计数."""
    from src.screening.offensive.cache_refresh import refresh_daily_action_caches

    price_cache = tmp_path / "price_cache"
    price_cache.mkdir()
    # 000001 既是候选又在缓存; 000002 涨停但已在缓存
    (price_cache / "000001.csv").write_text(
        "date,close,open,high,low,pct_change,volume\n2026-07-06,9.8,9.7,9.9,9.6,1.1,1000\n",
        encoding="utf-8",
    )
    (price_cache / "000002.csv").write_text(
        "date,close,open,high,low,pct_change,volume\n2026-07-06,19.8,19.7,19.9,19.6,1.1,1000\n",
        encoding="utf-8",
    )
    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()

    daily_df = _daily_prices(
        [
            {"ts_code": "000001.SZ", "pct_chg": 2.0},
            {"ts_code": "000002.SZ", "pct_chg": 10.0},  # 涨停但已在缓存
        ]
    )

    stats = refresh_daily_action_caches(
        "20260708",
        price_cache_dir=price_cache,
        fund_flow_cache_dir=tmp_path / "fund_flow_cache",
        snapshot_dir=snapshot_dir,
        daily_prices_df=daily_df,
        backfill_price_history_fn=lambda *_args: _history_rows(),
        fund_flow_fetch_fn=lambda *_a: pd.DataFrame(),
        refresh_industry_index=False,
        fund_flow_rate_limit_sec=0,
    )

    # 000002 涨停但已在 existing cache, 不算新注入
    assert stats.limit_up_injected == 0
    assert stats.price_total == 2
