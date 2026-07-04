"""R42 survivorship-bias audit: point-in-time stock universe filtering.

Backtest equity-curve credibility depends on the candidate pool reflecting the
stocks that were *actually tradeable* on each simulated trade date. The current
``_fetch_tushare_all_stock_basic`` requests ``list_status="L"`` (currently
listed), which silently excludes every stock that delisted before today — so a
backtest run for, say, 2024-01-15 can never pick a name that delisted in
2024-06, even though that name was alive and tradeable on the simulated date.
That is survivorship bias: it systematically beautifies backtest returns
because the losers that got delisted can never be selected.

This module tests ``filter_stock_basic_as_of``, the pure filtering primitive
that closes that hole. It takes a ``stock_basic``-shaped DataFrame (including
``list_date`` and, when available, ``delist_date``) plus an ``as_of`` trade
date, and returns the subset that was actually listed and not-yet-delisted on
that date. The primitive is fixture-driven (no live API); the backtest engine
can later wire it in so historical candidate pools exclude future-only
survivors and include since-delisted names."""

from __future__ import annotations

import pandas as pd
import pytest

from src.tools.tushare_api import filter_stock_basic_as_of


def _stock_basic_rows() -> list[dict]:
    """Synthetic universe covering every PIT boundary case.

    - ALIVE_NOW: listed long before as_of, no delist_date → in any PIT window.
    - LISTED_AFTER: IPO after as_of → must be excluded (did not exist yet).
    - LISTED_ON_AS_OF: IPO exactly on as_of → included (list_date == as_of is
      the first tradeable day).
    - DELISTED_BEFORE: delisted before as_of → excluded (no longer tradeable).
    - DELISTED_AFTER: delisted after as_of → included (was alive on as_of;
      this is the survivorship-bias case the current list_status="L" pool
      silently drops because the stock is delisted *today*).
    - DELISTED_ON_AS_OF: delisted exactly on as_of → excluded (last trade day
      is the day before; on the delist date the stock is no longer tradeable).
    - MISSING_LIST_DATE: malformed row with no list_date → excluded (cannot
      establish PIT legality; conservative exclusion, never silently kept).
    """
    return [
        {"ts_code": "000001.SZ", "name": "ALIVE_NOW", "list_date": "20100101", "delist_date": ""},
        {"ts_code": "000002.SZ", "name": "LISTED_AFTER", "list_date": "20240601", "delist_date": ""},
        {"ts_code": "000003.SZ", "name": "LISTED_ON_AS_OF", "list_date": "20240115", "delist_date": ""},
        {"ts_code": "000004.SZ", "name": "DELISTED_BEFORE", "list_date": "20100101", "delist_date": "20231231"},
        {"ts_code": "000005.SZ", "name": "DELISTED_AFTER", "list_date": "20100101", "delist_date": "20240601"},
        {"ts_code": "000006.SZ", "name": "DELISTED_ON_AS_OF", "list_date": "20100101", "delist_date": "20240115"},
        {"ts_code": "000007.SZ", "name": "MISSING_LIST_DATE", "list_date": "", "delist_date": ""},
    ]


_AS_OF = "20240115"


def test_filter_stock_basic_as_of_keeps_alive_and_listed_on_or_before() -> None:
    """A stock listed on or before as_of with no delist is always PIT-legitimate."""
    df = pd.DataFrame(_stock_basic_rows())
    kept = filter_stock_basic_as_of(df, as_of=_AS_OF)
    kept_codes = set(kept["ts_code"])
    assert "000001.SZ" in kept_codes  # ALIVE_NOW
    assert "000003.SZ" in kept_codes  # LISTED_ON_AS_OF (list_date == as_of)


def test_filter_stock_basic_as_of_excludes_listed_after() -> None:
    """A stock whose IPO is after as_of did not exist yet → must be excluded."""
    df = pd.DataFrame(_stock_basic_rows())
    kept = filter_stock_basic_as_of(df, as_of=_AS_OF)
    assert "000002.SZ" not in set(kept["ts_code"])  # LISTED_AFTER (20240601 > 20240115)


def test_filter_stock_basic_as_of_excludes_delisted_before() -> None:
    """A stock delisted before as_of is no longer tradeable → excluded."""
    df = pd.DataFrame(_stock_basic_rows())
    kept = filter_stock_basic_as_of(df, as_of=_AS_OF)
    assert "000004.SZ" not in set(kept["ts_code"])  # DELISTED_BEFORE (20231231 < 20240115)


def test_filter_stock_basic_as_of_keeps_delisted_after_survivorship_case() -> None:
    """The core survivorship-bias fix: a stock delisted *after* as_of was alive
    and tradeable on as_of, so it MUST be kept for a historical backtest even
    though it is delisted today (and thus absent from list_status="L")."""
    df = pd.DataFrame(_stock_basic_rows())
    kept = filter_stock_basic_as_of(df, as_of=_AS_OF)
    assert "000005.SZ" in set(kept["ts_code"])  # DELISTED_AFTER (20240601 > 20240115)


def test_filter_stock_basic_as_of_excludes_delisted_on_as_of() -> None:
    """Delisting on as_of means the stock's last tradeable day was as_of - 1;
    on as_of itself it is no longer tradeable → excluded (boundary symmetric
    with list_date == as_of being the first tradeable day)."""
    df = pd.DataFrame(_stock_basic_rows())
    kept = filter_stock_basic_as_of(df, as_of=_AS_OF)
    assert "000006.SZ" not in set(kept["ts_code"])  # DELISTED_ON_AS_OF (20240115 == as_of)


def test_filter_stock_basic_as_of_excludes_missing_list_date() -> None:
    """A row with no list_date cannot be PIT-validated → conservative exclusion
    (never silently keep a row whose listing status is unknown)."""
    df = pd.DataFrame(_stock_basic_rows())
    kept = filter_stock_basic_as_of(df, as_of=_AS_OF)
    assert "000007.SZ" not in set(kept["ts_code"])  # MISSING_LIST_DATE


def test_filter_stock_basic_as_of_accepts_dashed_dates() -> None:
    """Callers may pass dashed (YYYY-MM-DD) or compact (YYYYMMDD) dates in
    either argument; both must normalize and compare correctly (parity with
    R41 ann_date normalization)."""
    df = pd.DataFrame(
        [
            {"ts_code": "000001.SZ", "name": "ALIVE", "list_date": "2010-01-01", "delist_date": ""},
            {"ts_code": "000002.SZ", "name": "DELISTED_AFTER", "list_date": "20100101", "delist_date": "2024-06-01"},
        ]
    )
    kept = filter_stock_basic_as_of(df, as_of="2024-01-15")
    assert set(kept["ts_code"]) == {"000001.SZ", "000002.SZ"}


def test_filter_stock_basic_as_of_treats_missing_delist_column_as_never_delisted() -> None:
    """When the source DataFrame has no delist_date column at all (the current
    list_status="L" shape), every row with a valid list_date on or before as_of
    is kept — the function must not crash on the missing column, and must not
    over-filter. This keeps the backtest path robust when delist metadata is
    unavailable."""
    df = pd.DataFrame(
        [
            {"ts_code": "000001.SZ", "name": "ALIVE", "list_date": "20100101"},
            {"ts_code": "000002.SZ", "name": "TOO_NEW", "list_date": "20240601"},
        ]
    )
    kept = filter_stock_basic_as_of(df, as_of=_AS_OF)
    assert set(kept["ts_code"]) == {"000001.SZ"}


def test_filter_stock_basic_as_of_preserves_other_columns() -> None:
    """The returned DataFrame must carry through all non-filter columns
    (name, industry, market, ...) so downstream candidate-pool code works
    unchanged."""
    df = pd.DataFrame(
        [
            {"ts_code": "000001.SZ", "name": "ALIVE", "list_date": "20100101", "delist_date": "", "industry": "银行", "market": "主板"},
        ]
    )
    kept = filter_stock_basic_as_of(df, as_of=_AS_OF)
    row = kept.iloc[0]
    assert row["name"] == "ALIVE"
    assert row["industry"] == "银行"
    assert row["market"] == "主板"


def test_filter_stock_basic_as_of_as_of_none_is_noop() -> None:
    """When as_of is None (live mode), the function must return the input
    unchanged — PIT filtering is a backtest-only concern, and live runs keep
    using whatever the caller already filtered (parity with R40/R41
    as_of=None live-mode preservation)."""
    df = pd.DataFrame(_stock_basic_rows())
    kept = filter_stock_basic_as_of(df, as_of=None)
    assert len(kept) == len(df)
    assert set(kept["ts_code"]) == set(df["ts_code"])


def test_filter_stock_basic_as_of_empty_input_returns_empty() -> None:
    """An empty universe filters to an empty universe (no crash)."""
    df = pd.DataFrame(columns=["ts_code", "name", "list_date", "delist_date"])
    kept = filter_stock_basic_as_of(df, as_of=_AS_OF)
    assert kept.empty


def test_filter_stock_basic_as_of_malformed_dates_fall_back_conservatively() -> None:
    """A malformed list_date/delist_date must not crash the filter; the row is
    kept only if its list_date is unambiguously on-or-before as_of (parity with
    R41 malformed-date fallback — never let one bad row poison the batch)."""
    df = pd.DataFrame(
        [
            # valid list_date, malformed delist_date → treat delist as unknown
            # (i.e. not yet delisted), keep the row.
            {"ts_code": "000001.SZ", "name": "OK_LIST_BAD_DELIST", "list_date": "20100101", "delist_date": "not-a-date"},
            # malformed list_date → cannot establish PIT legality, exclude.
            {"ts_code": "000002.SZ", "name": "BAD_LIST", "list_date": "garbage", "delist_date": ""},
        ]
    )
    kept = filter_stock_basic_as_of(df, as_of=_AS_OF)
    assert "000001.SZ" in set(kept["ts_code"])
    assert "000002.SZ" not in set(kept["ts_code"])


def test_filter_stock_basic_as_of_audit_summary_quantifies_bias() -> None:
    """R42 audit deliverable: alongside the filtered frame, the function can
    report a compact survivorship-bias audit summary so a campaign can quantify
    how many names the current list_status="L" pool silently drops for a given
    as_of date. The summary must distinguish dropped-because-delisted (the
    survivorship-bias signal) from other exclusions."""
    df = pd.DataFrame(_stock_basic_rows())
    kept, summary = filter_stock_basic_as_of(df, as_of=_AS_OF, return_audit=True)
    # 7 input rows; kept = ALIVE_NOW, LISTED_ON_AS_OF, DELISTED_AFTER = 3.
    assert len(kept) == 3
    assert summary["input_count"] == 7
    assert summary["kept_count"] == 3
    # DELISTED_BEFORE + DELISTED_ON_AS_OF = 2 names dropped because they were
    # already delisted — these are NOT survivorship bias (correctly excluded).
    assert summary["dropped_already_delisted"] == 2
    # LISTED_AFTER + MISSING_LIST_DATE + BAD_LIST-style = excluded for other
    # reasons (not yet listed / unparseable).
    assert summary["dropped_not_yet_listed"] == 1  # LISTED_AFTER
    assert summary["dropped_unparseable"] == 1  # MISSING_LIST_DATE
