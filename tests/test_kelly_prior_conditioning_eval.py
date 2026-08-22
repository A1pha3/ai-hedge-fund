"""kelly_prior_conditioning_eval — 纯函数 + fixture 端到端 (第十五轮)."""

from __future__ import annotations

import json
import math

import pandas as pd
import pytest

from scripts.kelly_prior_conditioning_eval import (
    BUCKETS,
    HALF_KELLY,
    bucket_rows,
    kelly_stats,
    split_half_stability,
    strength_bucket,
)


class TestKellyStats:
    def test_matches_src_kelly_formula(self):
        from src.screening.offensive.kelly import kelly_fraction
        rets = [0.10, 0.05, -0.04, -0.06]
        s = kelly_stats(rets)
        w = 0.5
        g, b = 0.075, -0.05
        assert s["kelly_full"] == pytest.approx(kelly_fraction(w, g, b))
        assert s["kelly_half"] == pytest.approx(HALF_KELLY * s["kelly_full"])
        assert s["capped_at_10pct"] == (s["kelly_half"] > 0.10)

    def test_negative_kelly_flagged(self):
        rets = [0.01, -0.05, 0.01, -0.06]  # 低胜率小赢大亏
        s = kelly_stats(rets)
        assert s["negative_kelly"] is True

    def test_degenerate_no_win_returns_none(self):
        assert kelly_stats([-0.01, -0.02]) is None
        assert kelly_stats([]) is None

    def test_identity_expectancy(self):
        rets = [0.08, -0.03, 0.12, -0.05]
        s = kelly_stats(rets)
        implied = s["winrate"] * s["avg_gain"] + (1 - s["winrate"]) * s["avg_loss"]
        assert implied == pytest.approx(sum(rets) / len(rets), abs=1e-12)


class TestStrengthBucket:
    def test_boundaries(self):
        assert strength_bucket(0.4999) == "<0.50"
        assert strength_bucket(0.50) == "0.50-0.60"
        assert strength_bucket(0.70) == "≥0.70"
        assert strength_bucket(float("nan")) == "unknown"


def _fixture_ev(n=160, seed=5):
    import numpy as np
    rng = np.random.default_rng(seed)
    rows = []
    for i in range(n):
        s = 0.45 + (i % 5) * 0.11  # 跨四桶
        strong = s >= 0.60
        ret = rng.normal(0.06 if strong else -0.04, 0.08)
        rows.append({
            "symbol": f"s{i}",
            "signal_date": f"2026-{(i % 6) + 1:02d}-{(i % 27) + 1:02d}",
            "regime": "normal",
            "trigger_strength": s,
            "gross_ret_t10": ret + 0.0065,
            "fillable": True,
            "gate_blocked": False,
            "degraded": False,
            "st_name": False,
            "industry_missing": False,
            "excluded_ticker": False,
            "price_ge_3": True,
        })
    return pd.DataFrame(rows)


class TestBucketRows:
    def test_four_buckets_with_n(self):
        rows = bucket_rows(_fixture_ev())
        by = {r["bucket"]: r for r in rows}
        assert set(by) == set(BUCKETS)
        assert all(r["n"] > 0 for r in rows)
        # fixture 设计: 强桶正期望, 弱桶负
        assert by["≥0.70"]["kelly_full"] > 0
        assert by["<0.50"]["kelly_full"] < by["≥0.70"]["kelly_full"]


class TestSplitHalf:
    def test_stability_structure(self):
        ev = _fixture_ev(240, seed=5)
        sh = split_half_stability(ev)
        assert sh["split_date"]
        assert sh["spearman_kelly_order"] is not None
        assert isinstance(sh["kelly_sign_stable_across_halves"], bool)


class TestEndToEnd:
    def test_main_generates_report(self, tmp_path):
        from scripts import kelly_prior_conditioning_eval as mod
        table = tmp_path / "f.csv.gz"
        _fixture_ev(240).to_csv(table, index=False)
        rc = mod.main(["--court-table", str(table), "--report-dir", str(tmp_path / "r")])
        assert rc == 0
        from datetime import date as d
        stamp = d.today().strftime("%Y%m%d")
        md = (tmp_path / "r" / f"kelly_conditioning_eval_{stamp}.md").read_text()
        js = (tmp_path / "r" / f"kelly_conditioning_eval_{stamp}.json").read_text()
        assert "Kelly 先验条件化评估" in md
        assert "split-half 稳定性" in md
        payload = json.loads(js)
        assert payload["global_prior_kelly"]["kelly_full"] is not None
