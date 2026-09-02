"""btst_strength_stability_census — 预注册判定规则的 fixture 驱动测试."""

from __future__ import annotations

import pandas as pd
import pytest

from scripts.btst_strength_stability_census import (
    MIN_CELL_N,
    census_axis,
    cross_window_verdict,
    split_halves,
    verdict_for,
)


def _events(rows: list[dict]) -> pd.DataFrame:
    base = {"ts_code": [], "signal_date": [], "regime": [], "trigger_strength": [], "gross_ret_t10": []}
    for r in rows:
        base["ts_code"].append(r["ts"])
        base["signal_date"].append(r["date"])
        base["regime"].append(r.get("regime", "normal"))
        base["trigger_strength"].append(r["strength"])
        base["gross_ret_t10"].append(r["ret"])
    return pd.DataFrame(base)


def _many(n: int, ret: float, dates: list[str], strength: float = 0.65, regime: str = "normal") -> list[dict]:
    out = []
    for i in range(n):
        out.append({"ts": f"T{i}", "date": dates[i % len(dates)], "strength": strength, "ret": ret, "regime": regime})
    return out


class TestSplitHalves:
    def test_time_ordered_median_split(self):
        h1, h2 = split_halves(["20260105", "20260101", "20260103"])
        assert h1 == ["20260101", "20260103"]  # 3 日 → 前半 2 (含中位)
        assert h2 == ["20260105"]

    def test_empty(self):
        assert split_halves([]) == ([], [])


class TestVerdict:
    def _row(self, es: dict[str, float | None], ns: dict[str, int] | None = None):
        cells = {}
        for name, e in es.items():
            cell = {"n": (ns or {}).get(name, MIN_CELL_N)}
            if e is not None:
                cell["mean_net_e_pct"] = e
            cells[name] = cell
        return {"cells": cells}

    def test_all_positive(self):
        row = self._row({"full": 1.0, "h1": 0.5, "h2": 1.5})
        assert verdict_for(row) == "stable_positive"

    def test_all_negative(self):
        row = self._row({"full": -1.0, "h1": -0.5, "h2": -1.5})
        assert verdict_for(row) == "stable_negative"

    def test_sign_flip_is_unstable(self):
        row = self._row({"full": 1.0, "h1": 0.5, "h2": -1.5})
        assert verdict_for(row) == "sign_unstable"

    def test_small_n_insufficient(self):
        row = self._row({"full": 1.0, "h1": 1.0, "h2": 1.0}, ns={"full": MIN_CELL_N, "h1": 10, "h2": MIN_CELL_N})
        assert verdict_for(row) == "insufficient"

    def test_missing_cells_insufficient(self):
        assert verdict_for({"cells": {"full": {"n": 50, "mean_net_e_pct": 1.0}}}) == "insufficient"


class TestCrossWindowVerdict:
    def test_conjunction_required(self):
        rows = [
            {"group": ">=0.70", "window": "production", "cells": {"full": {"n": 50, "mean_net_e_pct": 1.0}, "h1": {"n": 50, "mean_net_e_pct": 1.0}, "h2": {"n": 50, "mean_net_e_pct": 1.0}}},
            {"group": ">=0.70", "window": "early", "cells": {"full": {"n": 50, "mean_net_e_pct": -0.5}, "h1": {"n": 50, "mean_net_e_pct": -0.5}, "h2": {"n": 50, "mean_net_e_pct": -0.5}}},
        ]
        merged = cross_window_verdict(rows, ">=0.70")
        assert merged["verdict"] == "sign_unstable"  # 生产 stable_positive + early stable_negative → 翻转
        assert merged["per_window"] == {"production": "stable_positive", "early": "stable_negative"}


class TestCensusAxis:
    def test_regime_axis_groups(self):
        dates = [f"2026010{i}" for i in range(1, 6)]
        events = _events(
            _many(100, ret=-0.10, dates=dates, regime="crisis")
            + _many(100, ret=0.05, dates=dates, regime="normal")
        )
        rows = census_axis(events, window="test", axis="regime", groups=[(r, None, None) for r in ("crisis", "risk_off", "normal")])
        by_group = {r["group"]: r for r in rows}
        assert verdict_for(by_group["crisis"]) == "stable_negative"
        assert verdict_for(by_group["normal"]) == "stable_positive"
        assert by_group["risk_off"]["cells"] == {} or all("mean_net_e_pct" not in c for c in by_group["risk_off"]["cells"].values())

    def test_strength_axis_bands_partition(self):
        dates = [f"2026010{i}" for i in range(1, 6)]
        events = _events(
            _many(100, ret=0.05, dates=dates, strength=0.55)
            + _many(100, ret=-0.05, dates=dates, strength=0.75)
        )
        rows = census_axis(events, window="test", axis="strength", groups=(("<0.50", 0.0, 0.50), ("0.50-0.60", 0.50, 0.60), (">=0.70", 0.70, 9.0)))
        by_group = {r["group"]: r for r in rows}
        assert by_group["0.50-0.60"]["cells"]["full"]["n"] == 100
        assert by_group[">=0.70"]["cells"]["full"]["n"] == 100
        assert by_group["<0.50"]["cells"] == {}
