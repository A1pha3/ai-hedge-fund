from __future__ import annotations

from typing import Any

import pandas as pd


def build_stock_search_results(df: pd.DataFrame, keyword: str, limit: int = 10) -> list[dict[str, Any]]:
    mask = df["名称"].str.contains(keyword, na=False) | df["代码"].str.contains(keyword, na=False)
    filtered = df[mask]

    results: list[dict[str, Any]] = []
    for _, row in filtered.head(limit).iterrows():
        results.append(
            {
                "symbol": row["代码"],
                "name": row["名称"],
                "price": row["最新价"],
                "change": row["涨跌幅"],
            }
        )
    return results
