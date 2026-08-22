"""early_window_feasibility — 纯函数 + fixture 端到端 (第二十二轮)."""

from __future__ import annotations

import json

import pandas as pd
import pytest

from scripts.early_window_feasibility import (
    intersection_universe,
    limit_up_days,
    limit_up_pct_for,
    year_coverage,
)


def _write_csv(path, rows, date_col="trade_date", extra=None):
    df = pd.DataFrame(rows)
    if extra:
        for k, v in extra.items():
            df[k] = v
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)


class TestYearCoverage:
    def test_coverage_and_bad_file_tolerance(self, tmp_path):
        _write_csv(tmp_path / "a.csv", [{"trade_date": f"2022-01-{d:02d}"} for d in range(1, 4)])
        _write_csv(tmp_path / "b.csv", [{"trade_date": f"2023-02-{d:02d}"} for d in range(1, 3)])
        (tmp_path / "bad.csv").write_text("not,a,csv")
        cov = year_coverage([tmp_path / "a.csv", tmp_path / "b.csv", tmp_path / "bad.csv"])
        assert cov["2022"] == {"a"} and cov["2023"] == {"b"}

    def test_intersection_requires_all_years(self):
        cov = {"2022": {"a", "b"}, "2023": {"a"}, "2024": {"a", "c"}}
        assert intersection_universe(cov) == {"a"}
        assert intersection_universe({"2022": {"a"}}) == set()  # 缺年 = 空


class TestLimitUp:
    def test_board_adaptive_thresholds(self):
        assert limit_up_pct_for("600000") == 9.5
        assert limit_up_pct_for("300001") == 19.5
        assert limit_up_pct_for("688001") == 19.5
        assert limit_up_pct_for("830001") == 29.0

    def test_limit_up_days_counts(self, tmp_path):
        rows = [
            {"trade_date": "2022-01-03", "pct_chg": 10.0},
            {"trade_date": "2022-01-04", "pct_chg": 2.0},
            {"trade_date": "2022-01-05", "pct_chg": 9.6},
            {"trade_date": "2023-03-01", "pct_chg": 11.0},
            {"trade_date": "2025-01-01", "pct_chg": 12.0},  # 窗口外
        ]
        _write_csv(tmp_path / "600001.csv", rows)
        out = limit_up_days(tmp_path, ["600001"])
        assert out == {"2022": 2, "2023": 1, "2024": 0}


class TestEndToEnd:
    def test_main_generates_report(self, tmp_path):
        from scripts import early_window_feasibility as mod
        price = tmp_path / "price"
        flow = tmp_path / "flow"
        for y in ("2022", "2023", "2024"):
            _write_csv(price / "600001.csv" if y == "2022" else price / "noop.csv",
                       [{"trade_date": f"{y}-01-03", "pct_chg": 10.0}])
        # 造 3 年全覆盖的单票
        rows = [{"trade_date": f"{y}-06-01", "pct_chg": 1.0} for y in ("2022", "2023", "2024")]
        rows[0]["pct_chg"] = 10.0
        _write_csv(price / "600001.csv", rows)
        _write_csv(flow / "600001.csv", [{"day": f"{y}-06-01"} for y in ("2022", "2023", "2024")])
        rc = mod.main(["--price-dir", str(price), "--flow-dir", str(flow),
                       "--report-dir", str(tmp_path / "rep")])
        assert rc == 0
        from datetime import date as d
        stamp = d.today().strftime("%Y%m%d")
        payload = json.loads(
            (tmp_path / "rep" / f"early_window_feasibility_{stamp}.json").read_text()
        )
        assert payload["intersection_universe_2022_2024"] == 1
        assert "幸存者偏差" in payload["verdict"] or "幸存者偏差" in payload["caveats"][0]
