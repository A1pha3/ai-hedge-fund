"""相关性聚类合并。"""

from __future__ import annotations

import pandas as pd
from src.portfolio.correlation_cluster_helpers import build_cluster_groups, build_union_find_parent, merge_correlated_pairs



def correlation_threshold_for_market(market_median_correlation: float) -> float:
    return 0.7 if market_median_correlation > 0.6 else 0.8


def build_correlation_clusters(correlation_matrix: pd.DataFrame, threshold: float) -> list[set[str]]:
    if correlation_matrix.empty:
        return []
    tickers = list(correlation_matrix.index)
    parent = build_union_find_parent(tickers)
    merge_correlated_pairs(correlation_matrix=correlation_matrix, tickers=tickers, threshold=threshold, parent=parent)
    return build_cluster_groups(tickers=tickers, parent=parent)


def market_median_correlation(correlation_matrix: pd.DataFrame) -> float:
    if correlation_matrix.empty:
        return 0.0
    values = []
    for row in correlation_matrix.index:
        for col in correlation_matrix.columns:
            if row >= col:
                continue
            value = correlation_matrix.loc[row, col]
            if pd.notna(value):
                values.append(float(value))
    if not values:
        return 0.0
    values.sort()
    mid = len(values) // 2
    if len(values) % 2 == 1:
        return values[mid]
    return (values[mid - 1] + values[mid]) / 2
