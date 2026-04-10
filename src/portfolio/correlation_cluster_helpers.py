from __future__ import annotations

from collections import defaultdict

import pandas as pd


def build_union_find_parent(tickers: list[str]) -> dict[str, str]:
    return {ticker: ticker for ticker in tickers}


def find_parent(parent: dict[str, str], node: str) -> str:
    while parent[node] != node:
        parent[node] = parent[parent[node]]
        node = parent[node]
    return node


def union_parent(parent: dict[str, str], left: str, right: str) -> None:
    root_left = find_parent(parent, left)
    root_right = find_parent(parent, right)
    if root_left != root_right:
        parent[root_right] = root_left


def merge_correlated_pairs(*, correlation_matrix: pd.DataFrame, tickers: list[str], threshold: float, parent: dict[str, str]) -> None:
    for row_ticker in tickers:
        for col_ticker in tickers:
            if row_ticker >= col_ticker:
                continue
            value = correlation_matrix.loc[row_ticker, col_ticker]
            if pd.notna(value) and value > threshold:
                union_parent(parent, row_ticker, col_ticker)


def build_cluster_groups(*, tickers: list[str], parent: dict[str, str]) -> list[set[str]]:
    groups: dict[str, set[str]] = defaultdict(set)
    for ticker in tickers:
        groups[find_parent(parent, ticker)].add(ticker)
    return list(groups.values())
