from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from scripts.btst_data_utils import load_json, normalize_price_frame, round_or_none, safe_float


def test_btst_data_utils_json_and_numeric_helpers(tmp_path: Path) -> None:
    payload_path = tmp_path / "payload.json"
    payload_path.write_text(json.dumps({"value": 1}), encoding="utf-8")

    assert load_json(payload_path) == {"value": 1}
    assert safe_float("1.25") == 1.25
    assert safe_float(None) is None
    assert safe_float("bad", default=3.5) == 3.5
    assert round_or_none(1.23456) == 1.2346
    assert round_or_none(None) is None


def test_btst_data_utils_normalize_price_frame_supports_date_columns_and_index() -> None:
    with_date_column = pd.DataFrame(
        [
            {"date": "2026-03-23 09:30:00", "Open": 10.0, "HIGH": 10.3},
            {"date": "2026-03-22 09:30:00", "Open": 9.8, "HIGH": 10.1},
        ]
    )
    normalized = normalize_price_frame(with_date_column)

    assert list(normalized.index.strftime("%Y-%m-%d")) == ["2026-03-22", "2026-03-23"]
    assert list(normalized.columns) == ["open", "high"]

    with_index = pd.DataFrame(
        [{"Close": 10.1}, {"Close": 10.4}],
        index=["2026-03-24 10:00:00", "2026-03-25 10:00:00"],
    )
    indexed = normalize_price_frame(with_index)

    assert isinstance(indexed.index, pd.DatetimeIndex)
    assert list(indexed.index.strftime("%Y-%m-%d")) == ["2026-03-24", "2026-03-25"]
    assert list(indexed.columns) == ["close"]


def test_btst_data_utils_normalize_price_frame_handles_none_and_empty() -> None:
    assert normalize_price_frame(None).empty
    assert normalize_price_frame(pd.DataFrame()).empty