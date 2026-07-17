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
    if isinstance(value, str):
        text = value.strip()
        # 快速路径: 零填充 ISO 日期 (YYYY-MM-DD) 占输入的绝大多数。
        # datetime(y, m, d) 构造与 pd.Timestamp 一样拒绝 13 月/45 日等非法值;
        # year>=1000 时 strftime("%Y-%m-%d") 的输出必然逐位等于零填充输入 — 等价
        # (year<1000 时 strftime %Y 在部分平台不零填充, 落慢路径保持原行为)。
        # isascii 必须: 全角数字 isdigit()=True 且 int() 可解析, 但慢路
        # pd.Timestamp 会把它们规范化成 ASCII — 快路必须拒绝以保逐位一致。
        if (
            len(text) == 10
            and text.isascii()
            and text[4] == "-"
            and text[7] == "-"
            and text[0] != "0"
            and text[:4].isdigit()
            and text[5:7].isdigit()
            and text[8:10].isdigit()
        ):
            try:
                datetime(int(text[:4]), int(text[5:7]), int(text[8:10]))
            except ValueError as exc:
                raise PITEvidenceError(f"invalid PIT date: {value!r}") from exc
            return text
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


def _canonical_row_values(
    values: Sequence[object], fields: Sequence[str]
) -> dict[str, object]:
    """``_canonical_row`` 的位置参数版: 与 itertuples 行迭代配套, 语义逐位等价。"""

    normalized: dict[str, object] = {}
    for field, value in zip(fields, values):
        normalized[field] = (
            _canonical_date(value) if field == "date" else _canonical_decimal(value)
        )
    return normalized


def _iter_field_rows(frame: pd.DataFrame, fields: Sequence[str]):
    """按 fields 列序逐行迭代 (位置 tuple)。

    替代 frame.to_dict(orient="records"): 逐列 box 语义一致 (float64→float,
    int64→int, datetime64→Timestamp, object 原样), 但 1580 行帧上快 ~3-5 倍。
    调用方须先确认 fields 全部存在 (missing 检查), 值顺序与 fields 一致。
    重复列名两 API 取值不同 (to_dict 后者覆盖, itertuples zip 截断取前者)
    — 无法静默对齐, 显式拒绝 (fail-closed)。
    """

    if not frame.columns.is_unique:
        raise PITEvidenceError("PIT evidence frame must not have duplicate columns")
    return frame.loc[:, list(fields)].itertuples(index=False, name=None)


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
    for values in _iter_field_rows(frame, _PRICE_FIELDS):
        _canonical_row_values(values, _PRICE_FIELDS)


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
    # 逐行 identity 检查的向量化等价: 任何行与期望 ticker 不同 → unique 中必出现
    if "ticker" in frame.columns and any(
        value != expected_ticker for value in frame["ticker"].unique()
    ):
        raise PITEvidenceError("fund-flow artifact ticker identity mismatch")
    for values in _iter_field_rows(frame, _FLOW_FIELDS):
        _canonical_row_values(values, _FLOW_FIELDS)


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
        for values in _iter_field_rows(frame, _PRICE_FIELDS):
            row_date = _canonical_date(values[0])  # "date" 是 _PRICE_FIELDS 首列
            if row_date > cutoff:
                continue
            rows.append(_canonical_row_values(values, _PRICE_FIELDS))
    return canonical_fingerprint("price", ticker, rows)


def canonical_price_row_fingerprint(
    row: Mapping[str, object],
    ticker: str,
    signal_date: object,
) -> str:
    """单行价格证据指纹 — 与 ``canonical_price_fingerprint(单行帧, ...)`` 逐位等价。

    供全市场 daily batch 这类逐行校验/取证场景免去每行一次 DataFrame 构造
    (~5000 行 x ~150us)。返回值可丢弃 (纯校验用法) 或参与聚合 (证据指纹用法)。
    """

    _validate_ticker(ticker, kind="price")
    cutoff = _canonical_date(signal_date)
    rows: list[dict[str, object]] = []
    if "date" not in row:
        raise PITEvidenceError("missing required PIT fields: date")
    if _canonical_date(row["date"]) <= cutoff:
        rows.append(_canonical_row(row, _PRICE_FIELDS))
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
    rows: list[dict[str, object]] = []
    if isinstance(records, pd.DataFrame):
        missing_columns = set(_FLOW_FIELDS) - set(records.columns)
        if missing_columns:
            raise PITEvidenceError(
                "missing required flow columns: "
                + ", ".join(sorted(missing_columns))
            )
        for values in _iter_field_rows(records, _FLOW_FIELDS):
            row_date = _canonical_date(values[0])  # "date" 是 _FLOW_FIELDS 首列
            if row_date > cutoff:
                continue
            rows.append(_canonical_row_values(values, _FLOW_FIELDS))
        return canonical_fingerprint("fund_flow", ticker, rows)
    for record in records:
        if not isinstance(record, Mapping):
            raise PITEvidenceError("fund-flow evidence rows must be mappings")
        if "date" not in record:
            raise PITEvidenceError("missing required PIT fields: date")
        row_date = _canonical_date(record["date"])
        if row_date > cutoff:
            continue
        rows.append(_canonical_row(record, _FLOW_FIELDS))
    return canonical_fingerprint("fund_flow", ticker, rows)
