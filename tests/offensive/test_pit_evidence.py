from __future__ import annotations

from decimal import Decimal
from importlib import import_module

import pandas as pd


def _pit_evidence():
    return import_module("src.screening.offensive.pit_evidence")


def test_price_fingerprint_ignores_rows_after_signal_date():
    frame = pd.DataFrame(
        [
            {"date": "2026-07-10", "open": 10, "high": 11, "low": 9, "close": 10.5, "pct_change": 5, "volume": 1000},
            {"date": "2026-07-13", "open": 11, "high": 12, "low": 10, "close": 11.5, "pct_change": 9.5, "volume": 2000},
        ]
    )
    with_future = pd.concat(
        [
            frame,
            pd.DataFrame(
                [{"date": "2026-07-14", "open": 99, "high": 100, "low": 1, "close": 2, "pct_change": -90, "volume": 999999}]
            ),
        ],
        ignore_index=True,
    )

    fingerprint = _pit_evidence().canonical_price_fingerprint
    assert fingerprint(frame, "000001", "20260713") == fingerprint(
        with_future,
        "000001",
        "20260713",
    )


def test_price_fingerprint_normalizes_dates_decimals_columns_and_row_order():
    left = pd.DataFrame(
        [
            {"date": "2026-07-10", "close": 10.0, "open": 9.5, "high": 10.5, "low": 9, "pct_change": 5.0, "volume": 1000},
            {"date": "20260713", "close": 11, "open": 10, "high": 12, "low": 9.8, "pct_change": 10, "volume": 2000},
        ]
    )
    right = pd.DataFrame(
        [
            {"volume": Decimal("2000.0"), "pct_change": Decimal("10.00"), "low": Decimal("9.800"), "high": 12.0, "open": Decimal("10.0"), "close": Decimal("11.00"), "date": pd.Timestamp("2026-07-13")},
            {"volume": Decimal("1000"), "pct_change": 5, "low": Decimal("9.0"), "high": Decimal("10.50"), "open": 9.5, "close": Decimal("10.000"), "date": "20260710"},
        ]
    )

    fingerprint = _pit_evidence().canonical_price_fingerprint
    assert fingerprint(left, "000001", "2026-07-13") == fingerprint(
        right,
        "000001",
        "20260713",
    )


def test_flow_fingerprint_ignores_future_rows_and_normalizes_records():
    records = [
        {"date": "20260710", "close": 10, "pct_change": 1.5, "main_net_inflow": 1000, "main_net_pct": 2},
        {"date": pd.Timestamp("2026-07-13"), "close": Decimal("11.0"), "pct_change": Decimal("2.50"), "main_net_inflow": Decimal("2000.00"), "main_net_pct": Decimal("3.0")},
    ]
    reordered = [
        {"main_net_pct": 3, "main_net_inflow": 2000, "pct_change": 2.5, "close": 11, "date": "2026-07-13"},
        {"main_net_pct": Decimal("2.00"), "main_net_inflow": Decimal("1000.0"), "pct_change": Decimal("1.500"), "close": Decimal("10.0"), "date": "2026-07-10"},
        {"date": "20260714", "close": 1, "pct_change": -99, "main_net_inflow": -1, "main_net_pct": -99},
    ]

    fingerprint = _pit_evidence().canonical_flow_fingerprint
    assert fingerprint(records, "000001", "20260713") == fingerprint(
        reordered,
        "000001",
        "2026-07-13",
    )
