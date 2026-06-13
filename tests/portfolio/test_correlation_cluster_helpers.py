"""Unit tests for src/portfolio/correlation_cluster_helpers.py

Union-find based correlation clustering: parent init, find with path
compression, union, pair merging above threshold, and group assembly.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.portfolio.correlation_cluster_helpers import (
    build_cluster_groups,
    build_union_find_parent,
    find_parent,
    merge_correlated_pairs,
    union_parent,
)


def _corr_matrix(tickers: list[str], values: dict[tuple[str, str], float]) -> pd.DataFrame:
    mat = pd.DataFrame(np.eye(len(tickers)), index=tickers, columns=tickers)
    for (r, c), v in values.items():
        mat.loc[r, c] = v
        mat.loc[c, r] = v
    return mat


# ---------------------------------------------------------------------------
# build_union_find_parent
# ---------------------------------------------------------------------------


def test_build_union_find_parent_self_mapping() -> None:
    parent = build_union_find_parent(["000001", "000002", "000003"])
    assert parent == {"000001": "000001", "000002": "000002", "000003": "000003"}


def test_build_union_find_parent_empty() -> None:
    assert build_union_find_parent([]) == {}


# ---------------------------------------------------------------------------
# find_parent / union_parent
# ---------------------------------------------------------------------------


def test_find_parent_self() -> None:
    parent = build_union_find_parent(["A", "B"])
    assert find_parent(parent, "A") == "A"


def test_union_merges_two_nodes() -> None:
    parent = build_union_find_parent(["A", "B"])
    union_parent(parent, "A", "B")
    assert find_parent(parent, "A") == find_parent(parent, "B")


def test_union_transitive_grouping() -> None:
    parent = build_union_find_parent(["A", "B", "C"])
    union_parent(parent, "A", "B")
    union_parent(parent, "B", "C")
    root_a = find_parent(parent, "A")
    assert find_parent(parent, "B") == root_a
    assert find_parent(parent, "C") == root_a


def test_union_already_same_root_no_change() -> None:
    parent = build_union_find_parent(["A", "B"])
    union_parent(parent, "A", "B")
    snapshot = dict(parent)
    union_parent(parent, "A", "B")  # idempotent
    assert parent == snapshot


def test_find_parent_path_compression() -> None:
    """After find, intermediate nodes point closer to root."""
    parent = build_union_find_parent(["A", "B", "C", "D"])
    # Chain: D → C → B → A
    parent["D"] = "C"
    parent["C"] = "B"
    parent["B"] = "A"
    root = find_parent(parent, "D")
    assert root == "A"
    # Path compression: D's parent should now skip toward root
    assert parent["D"] != "C" or parent["D"] == "A" or parent["D"] == root


# ---------------------------------------------------------------------------
# merge_correlated_pairs
# ---------------------------------------------------------------------------


def test_merge_correlated_pairs_groups_high_correlation() -> None:
    tickers = ["000001", "000002", "000003"]
    corr = _corr_matrix(tickers, {("000001", "000002"): 0.95, ("000001", "000003"): 0.10, ("000002", "000003"): 0.20})
    parent = build_union_find_parent(tickers)
    merge_correlated_pairs(correlation_matrix=corr, tickers=tickers, threshold=0.8, parent=parent)
    groups = build_cluster_groups(tickers=tickers, parent=parent)
    # 000001 + 000002 grouped (0.95 > 0.8); 000003 separate
    assert len(groups) == 2
    big = max(groups, key=len)
    assert big == {"000001", "000002"}


def test_merge_correlated_pairs_threshold_is_strictly_greater() -> None:
    """corr == threshold → NOT merged (strictly >)."""
    tickers = ["A", "B"]
    corr = _corr_matrix(tickers, {("A", "B"): 0.8})
    parent = build_union_find_parent(tickers)
    merge_correlated_pairs(correlation_matrix=corr, tickers=tickers, threshold=0.8, parent=parent)
    assert find_parent(parent, "A") != find_parent(parent, "B")


def test_merge_correlated_pairs_nan_not_merged() -> None:
    tickers = ["A", "B"]
    corr = _corr_matrix(tickers, {("A", "B"): float("nan")})
    parent = build_union_find_parent(tickers)
    merge_correlated_pairs(correlation_matrix=corr, tickers=tickers, threshold=0.5, parent=parent)
    assert find_parent(parent, "A") != find_parent(parent, "B")


def test_merge_correlated_pairs_transitive_chain() -> None:
    tickers = ["A", "B", "C"]
    corr = _corr_matrix(tickers, {("A", "B"): 0.9, ("B", "C"): 0.9, ("A", "C"): 0.1})
    parent = build_union_find_parent(tickers)
    merge_correlated_pairs(correlation_matrix=corr, tickers=tickers, threshold=0.8, parent=parent)
    groups = build_cluster_groups(tickers=tickers, parent=parent)
    assert len(groups) == 1
    assert groups[0] == {"A", "B", "C"}


def test_merge_correlated_pairs_all_below_threshold() -> None:
    tickers = ["A", "B", "C"]
    corr = _corr_matrix(tickers, {("A", "B"): 0.3, ("B", "C"): 0.4, ("A", "C"): 0.2})
    parent = build_union_find_parent(tickers)
    merge_correlated_pairs(correlation_matrix=corr, tickers=tickers, threshold=0.8, parent=parent)
    groups = build_cluster_groups(tickers=tickers, parent=parent)
    assert len(groups) == 3  # all singletons


# ---------------------------------------------------------------------------
# build_cluster_groups
# ---------------------------------------------------------------------------


def test_build_cluster_groups_returns_list_of_sets() -> None:
    tickers = ["A", "B", "C", "D"]
    parent = build_union_find_parent(tickers)
    union_parent(parent, "A", "B")
    groups = build_cluster_groups(tickers=tickers, parent=parent)
    assert len(groups) == 3
    # find the {A,B} group
    ab_group = [g for g in groups if len(g) == 2][0]
    assert ab_group == {"A", "B"}


def test_build_cluster_groups_all_singletons() -> None:
    tickers = ["A", "B"]
    parent = build_union_find_parent(tickers)
    groups = build_cluster_groups(tickers=tickers, parent=parent)
    assert len(groups) == 2
    assert all(len(g) == 1 for g in groups)
