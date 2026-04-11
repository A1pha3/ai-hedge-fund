from __future__ import annotations

from typing import Any

import pandas as pd


def build_stock_info_dict(df: pd.DataFrame) -> dict[str, Any]:
    info: dict[str, Any] = {}
    for _, row in df.iterrows():
        info[row["item"]] = row["value"]
    return info
