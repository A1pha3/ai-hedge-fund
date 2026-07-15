"""Canonical point-in-time fingerprints for Daily Action cache evidence."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

import pandas as pd

_PRICE_FIELDS = ("date", "open", "high", "low", "close", "pct_change", "volume")
_FLOW_FIELDS = ("date", "close", "pct_change", "main_net_inflow", "main_net_pct")


def _canonical_date(value: object) -> str:
    if isinstance(value, (date, datetime, pd.Timestamp)):
        return pd.Timestamp(value).strftime("%Y-%m-%d")
    text = str(value).strip()
    if len(text) == 8 and text.isdigit():
        return datetime.strptime(text, "%Y%m%d").strftime("%Y-%m-%d")
    return pd.Timestamp(text).strftime("%Y-%m-%d")


def _canonical_decimal(value: object) -> str | None:
    if value is None or value is pd.NA:
        return None
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    try:
        decimal_value = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return str(value)
    if not decimal_value.is_finite():
        return None
    if decimal_value == 0:
        return "0"
    return format(decimal_value.normalize(), "f")


def _canonical_row(
    row: Mapping[str, object], fields: Sequence[str]
) -> dict[str, object]:
    normalized: dict[str, object] = {}
    for field in fields:
        if field not in row:
            continue
        value = row[field]
        normalized[field] = (
            _canonical_date(value) if field == "date" else _canonical_decimal(value)
        )
    return normalized


def canonical_fingerprint(
    kind: str,
    ticker: str,
    rows: Sequence[Mapping[str, object]],
) -> str:
    """Hash already normalized PIT rows using stable canonical JSON."""

    canonical_rows = [dict(sorted(row.items())) for row in rows]
    canonical_rows.sort(
        key=lambda row: json.dumps(
            row,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    payload = {"kind": kind, "ticker": ticker, "rows": canonical_rows}
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def canonical_price_fingerprint(
    frame: pd.DataFrame | None,
    ticker: str,
    signal_date: object,
) -> str:
    """Fingerprint price rows visible at or before ``signal_date``."""

    cutoff = _canonical_date(signal_date)
    rows: list[dict[str, object]] = []
    if frame is not None and not frame.empty:
        for record in frame.to_dict(orient="records"):
            if "date" not in record:
                continue
            normalized = _canonical_row(record, _PRICE_FIELDS)
            if str(normalized["date"]) <= cutoff:
                rows.append(normalized)
    return canonical_fingerprint("price", ticker, rows)


def canonical_flow_fingerprint(
    records: Sequence[Mapping[str, object]] | pd.DataFrame | None,
    ticker: str,
    signal_date: object,
) -> str:
    """Fingerprint fund-flow rows visible at or before ``signal_date``."""

    cutoff = _canonical_date(signal_date)
    if isinstance(records, pd.DataFrame):
        source_rows: Sequence[Mapping[str, object]] = records.to_dict(orient="records")
    else:
        source_rows = records or ()
    rows: list[dict[str, object]] = []
    for record in source_rows:
        if "date" not in record:
            continue
        normalized = _canonical_row(record, _FLOW_FIELDS)
        if str(normalized["date"]) <= cutoff:
            rows.append(normalized)
    return canonical_fingerprint("fund_flow", ticker, rows)
