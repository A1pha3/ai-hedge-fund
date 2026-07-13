import json
from pathlib import Path

import pandas as pd
import pytest

from src.utils.atomic_files import atomic_write_csv, atomic_write_json


def test_json_failure_preserves_previous_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "report.json"
    target.write_text('{"version": 1}', encoding="utf-8")
    monkeypatch.setattr(json, "dump", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(OSError, match="disk full"):
        atomic_write_json(target, {"version": 2})
    assert json.loads(target.read_text(encoding="utf-8")) == {"version": 1}
    assert list(tmp_path.glob(".*.tmp")) == []


def test_csv_round_trip_replaces_complete_file(tmp_path: Path) -> None:
    target = tmp_path / "prices.csv"
    atomic_write_csv(target, pd.DataFrame([{"date": "20260710", "close": 10.0}]))
    assert pd.read_csv(target, dtype={"date": str}).to_dict("records") == [
        {"date": "20260710", "close": 10.0}
    ]
