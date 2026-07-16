"""Canonical point-in-time fingerprints for Daily Action cache evidence."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal

import numpy as np
import pandas as pd

_PRICE_FIELDS = ("date", "open", "high", "low", "close", "pct_change", "volume")
_FLOW_FIELDS = ("date", "close", "pct_change", "main_net_inflow", "main_net_pct")


class PITEvidenceError(ValueError):
    """Raised when point-in-time evidence cannot be canonicalized exactly."""


def _is_missing(value: object) -> bool:
    if value is None or value is pd.NA or value is pd.NaT:
        return True
    try:
        missing = pd.isna(value)
    except (TypeError, ValueError):
        return False
    return bool(missing) if isinstance(missing, bool) else False


def _canonical_date(value: object) -> str:
    if (
        isinstance(value, bool)
        or not isinstance(value, (str, date, datetime, pd.Timestamp))
        or _is_missing(value)
    ):
        raise PITEvidenceError(f"invalid PIT date: {value!r}")
    try:
        if isinstance(value, (date, datetime, pd.Timestamp)):
            parsed = pd.Timestamp(value)
        else:
            text = str(value).strip()
            if not text:
                raise ValueError("empty date")
            parsed = (
                pd.Timestamp(datetime.strptime(text, "%Y%m%d"))
                if len(text) == 8 and text.isdigit()
                else pd.Timestamp(text)
            )
        if pd.isna(parsed):
            raise ValueError("missing date")
        return parsed.strftime("%Y-%m-%d")
    except (TypeError, ValueError, OverflowError) as exc:
        raise PITEvidenceError(f"invalid PIT date: {value!r}") from exc


def _canonical_decimal(value: object) -> str:
    if isinstance(value, (bool, np.bool_)) or _is_missing(value):
        raise PITEvidenceError(f"invalid PIT numeric: {value!r}")
    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise PITEvidenceError("invalid PIT numeric string")
    elif type(value) in (int, float, Decimal):
        text = str(value)
    elif isinstance(value, np.integer):
        text = str(int(value))
    elif isinstance(value, np.floating):
        text = str(value)
    else:
        raise PITEvidenceError(
            f"unsupported PIT numeric scalar: {type(value).__name__}"
        )
    try:
        decimal_value = Decimal(text)
    except Exception as exc:  # noqa: BLE001 - invalid provider scalars fail closed
        raise PITEvidenceError("invalid PIT numeric") from exc
    if not decimal_value.is_finite():
        raise PITEvidenceError(f"non-finite PIT numeric: {value!r}")
    if decimal_value == 0:
        return "0"
    return format(decimal_value.normalize(), "f")


def _canonical_row(
    row: Mapping[str, object], fields: Sequence[str]
) -> dict[str, object]:
    missing = [field for field in fields if field not in row]
    if missing:
        raise PITEvidenceError(
            "missing required PIT fields: " + ", ".join(sorted(missing))
        )
    normalized: dict[str, object] = {}
    for field in fields:
        value = row[field]
        normalized[field] = (
            _canonical_date(value) if field == "date" else _canonical_decimal(value)
        )
    return normalized


def _validate_ticker(ticker: object, *, kind: str) -> str:
    if not isinstance(ticker, str) or len(ticker) != 6 or not ticker.isdigit():
        raise PITEvidenceError(f"{kind} evidence ticker must be exactly six digits")
    return ticker


def validate_price_artifact(frame: pd.DataFrame, ticker: object) -> None:
    """Validate every row in a complete price artifact before persistence."""

    _validate_ticker(ticker, kind="price")
    if not isinstance(frame, pd.DataFrame):
        raise PITEvidenceError("price evidence must be a DataFrame")
    missing_columns = set(_PRICE_FIELDS) - set(frame.columns)
    if missing_columns:
        raise PITEvidenceError(
            "missing required price columns: " + ", ".join(sorted(missing_columns))
        )
    for record in frame.to_dict(orient="records"):
        _canonical_row(record, _PRICE_FIELDS)


def validate_flow_artifact(frame: pd.DataFrame, ticker: object) -> None:
    """Validate every row and identity in a complete flow artifact before persistence."""

    if not isinstance(ticker, str) or not ticker:
        raise PITEvidenceError("fund-flow artifact ticker must be a non-empty string")
    expected_ticker = ticker
    if not isinstance(frame, pd.DataFrame):
        raise PITEvidenceError("fund-flow evidence must be a DataFrame")
    missing_columns = set(_FLOW_FIELDS) - set(frame.columns)
    if missing_columns:
        raise PITEvidenceError(
            "missing required flow columns: " + ", ".join(sorted(missing_columns))
        )
    for record in frame.to_dict(orient="records"):
        _canonical_row(record, _FLOW_FIELDS)
        if "ticker" in record and record["ticker"] != expected_ticker:
            raise PITEvidenceError("fund-flow artifact ticker identity mismatch")


def canonical_fingerprint(
    kind: str,
    ticker: str,
    rows: Sequence[Mapping[str, object]],
) -> str:
    """Hash already normalized PIT rows using stable canonical JSON."""

    if not isinstance(kind, str) or not kind:
        raise PITEvidenceError("fingerprint kind must be a non-empty string")
    if not isinstance(ticker, str) or not ticker:
        raise PITEvidenceError("fingerprint ticker must be a non-empty string")
    if any(not isinstance(row, Mapping) for row in rows):
        raise PITEvidenceError("fingerprint rows must be mappings")
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

    _validate_ticker(ticker, kind="price")
    if not isinstance(frame, pd.DataFrame):
        raise PITEvidenceError("price evidence must be a DataFrame")
    missing_columns = set(_PRICE_FIELDS) - set(frame.columns)
    if missing_columns:
        raise PITEvidenceError(
            "missing required price columns: " + ", ".join(sorted(missing_columns))
        )
    cutoff = _canonical_date(signal_date)
    rows: list[dict[str, object]] = []
    if not frame.empty:
        for record in frame.to_dict(orient="records"):
            row_date = _canonical_date(record["date"])
            if row_date > cutoff:
                continue
            rows.append(_canonical_row(record, _PRICE_FIELDS))
    return canonical_fingerprint("price", ticker, rows)


def canonical_flow_fingerprint(
    records: Sequence[Mapping[str, object]] | pd.DataFrame | None,
    ticker: str,
    signal_date: object,
) -> str:
    """Fingerprint fund-flow rows visible at or before ``signal_date``."""

    _validate_ticker(ticker, kind="fund-flow")
    cutoff = _canonical_date(signal_date)
    if records is None:
        raise PITEvidenceError("fund-flow evidence must not be None")
    if isinstance(records, pd.DataFrame):
        missing_columns = set(_FLOW_FIELDS) - set(records.columns)
        if missing_columns:
            raise PITEvidenceError(
                "missing required flow columns: "
                + ", ".join(sorted(missing_columns))
            )
        source_rows: Sequence[Mapping[str, object]] = records.to_dict(orient="records")
    else:
        source_rows = records
    rows: list[dict[str, object]] = []
    for record in source_rows:
        if not isinstance(record, Mapping):
            raise PITEvidenceError("fund-flow evidence rows must be mappings")
        if "date" not in record:
            raise PITEvidenceError("missing required PIT fields: date")
        row_date = _canonical_date(record["date"])
        if row_date > cutoff:
            continue
        rows.append(_canonical_row(record, _FLOW_FIELDS))
    return canonical_fingerprint("fund_flow", ticker, rows)
