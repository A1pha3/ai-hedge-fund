"""相关性聚类合并。"""

from __future__ import annotations

from collections import defaultdict

import pandas as pd


def compute_correlation_matrix(price_frames: dict[str, pd.DataFrame], window: int = 60) -> pd.DataFrame:
    returns = {}
    for ticker, frame in price_frames.items():
        if frame is None or frame.empty or "close" not in frame.columns:
            continue
        returns[ticker] = pd.to_numeric(frame["close"], errors="coerce").pct_change().dropna().tail(window)
    if not returns:
        return pd.DataFrame()
    return pd.DataFrame(returns).corr(method="pearson")


def correlation_threshold_for_market(market_median_correlation: float) -> float:
    return 0.7 if market_median_correlation > 0.6 else 0.8


def build_correlation_clusters(correlation_matrix: pd.DataFrame, threshold: float) -> list[set[str]]:
    if correlation_matrix.empty:
        return []
    tickers = list(correlation_matrix.index)
    parent = {ticker: ticker for ticker in tickers}

    def find(node: str) -> str:
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    def union(left: str, right: str) -> None:
        root_left = find(left)
        root_right = find(right)
        if root_left != root_right:
            parent[root_right] = root_left

    for row_ticker in tickers:
        for col_ticker in tickers:
            if row_ticker >= col_ticker:
                continue
            value = correlation_matrix.loc[row_ticker, col_ticker]
            if pd.notna(value) and value > threshold:
                union(row_ticker, col_ticker)

    groups: dict[str, set[str]] = defaultdict(set)
    for ticker in tickers:
        groups[find(ticker)].add(ticker)
    return list(groups.values())


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
