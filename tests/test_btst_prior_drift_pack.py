"""btst_prior_drift_pack — 决策包三面结构的 fixture 驱动测试 (零网络/零 gitignored)."""

from __future__ import annotations

import pandas as pd
import pytest

from scripts.btst_prior_drift_pack import (
    HORIZON_COLS,
    build_payload,
    kelly_view,
    prior_fields,
    rebuilt_stats,
    top1_view,
)


def _universe(rows: list[dict]) -> pd.DataFrame:
    base = {
        "ts_code": [],
        "signal_date": [],
        "trigger_strength": [],
        "gross_ret_t8": [],
        "gross_ret_t10": [],
    }
    for r in rows:
        base["ts_code"].append(r["ts"])
        base["signal_date"].append(r["date"])
        base["trigger_strength"].append(r["strength"])
        base["gross_ret_t8"].append(r.get("ret8"))
        base["gross_ret_t10"].append(r.get("ret10"))
    return pd.DataFrame(base)


class TestPriorFields:
    def test_prior_constant_fields_present(self):
        for horizon in (8, 10):
            fields = prior_fields(horizon)
            for key in ("n", "winrate", "avg_gain", "avg_loss", "expected_return", "provenance"):
                assert key in fields
            assert "世代" in fields["provenance"] or "owner" in fields["provenance"]


class TestRebuiltStats:
    def test_stats_and_net_cost(self):
        # net = gross − 0.65% (review 同式): +0.10 → +0.0935
        u = _universe(
            [
                {"ts": "A", "date": 20260701, "strength": 0.6, "ret10": 0.10},
                {"ts": "B", "date": 20260701, "strength": 0.7, "ret10": -0.05},
            ]
        )
        stats = rebuilt_stats(u, 10)
        assert stats["n"] == 2
        assert stats["winrate"] == 0.5
        assert stats["expected_return"] == round((0.0935 + (-0.0565)) / 2, 4)

    def test_empty_universe(self):
        u = _universe([{"ts": "A", "date": 20260701, "strength": 0.6, "ret10": None}])
        stats = rebuilt_stats(u, 10)
        assert stats["n"] == 0
        assert stats["expected_return"] is None


class TestKellyView:
    def test_cap_relation_disclosed(self):
        prior = {"winrate": 0.4645, "avg_gain": 0.1344, "avg_loss": -0.1062}
        rebuilt = {"winrate": 0.4462, "avg_gain": 0.1305, "avg_loss": -0.1049}
        view = kelly_view(prior, rebuilt)
        assert view["prior_full_kelly"] is not None
        assert view["rebuilt_full_kelly"] is not None
        assert view["per_setup_cap"] == 0.10
        assert "disclosure_impact" in view  # R98 Op3: 三态表述取代旧 cap_binding_note

    def test_missing_fields_give_none(self):
        view = kelly_view({"winrate": None}, {"winrate": 0.5, "avg_gain": 0.1, "avg_loss": -0.1})
        assert view["prior_full_kelly"] is None


class TestTop1View:
    def test_daily_max_strength_pick(self):
        u = _universe(
            [
                {"ts": "A", "date": 20260701, "strength": 0.55, "ret10": 0.02},
                {"ts": "B", "date": 20260701, "strength": 0.80, "ret10": -0.01},
                {"ts": "C", "date": 20260702, "strength": 0.60, "ret10": 0.03},
            ]
        )
        view = top1_view(u, 10)
        assert view["n_days"] == 2
        # picks = B (−1%−0.65% = −0.0165), C (+3%−0.65% = +0.0235) — k=1 日组合即单笔
        expected_mean = (-0.0165 + 0.0235) / 2
        assert view["trade_mean"] == round(expected_mean, 4)
        # daily_topk NAV = 日组合均值复合; k=1 时与逐笔复合一致
        expected_nav = (1 - 0.0165) * (1 + 0.0235)
        assert view["nav_compound"] == round(expected_nav, 4)


class TestBuildPayload:
    def test_three_faces_and_options(self):
        u = _universe(
            [{"ts": f"T{i}", "date": 20260701 + i, "strength": 0.6 + 0.01 * i, "ret10": 0.01 * ((-1) ** i), "ret8": 0.005 * ((-1) ** i)} for i in range(6)]
        )
        payload = build_payload(u)
        assert set(payload["horizons"]) == {"t10", "t8"}
        for key in ("t10", "t8"):
            h = payload["horizons"][key]
            assert {"prior", "rebuilt", "er_delta_pp", "kelly"} <= set(h)
        assert payload["selection_view"]["top_1_t10"]["n_days"] == 6
        assert len(payload["options"]) == 2
        assert any("重校准" in o for o in payload["options"])
        assert any("等待" in o for o in payload["options"])


class TestKellyThreeStateFraming:
    """R98 Op3 对抗修复: 生产 sizing 事实 (cap 制) 必须在场, 不得暗示今日仓位受影响."""

    def test_active_sizing_impact_is_none_cap_regime(self):
        prior = {"winrate": 0.4645, "avg_gain": 0.1344, "avg_loss": -0.1062}
        rebuilt = {"winrate": 0.4462, "avg_gain": 0.1305, "avg_loss": -0.1049}
        view = kelly_view(prior, rebuilt)
        assert view["active_sizing_impact"].startswith("none")
        assert "daily_action.py:2337" in view["active_sizing_impact"]
        assert "latent_impact" in view and "disclosure_impact" in view
        # 该例 f*: prior 0.389 > cap, rebuilt 0.0099 < cap → 跨边界
        assert "跨 cap 边界" in view["latent_impact"]

    def test_latent_no_cross_when_same_side(self):
        prior = {"winrate": 0.55, "avg_gain": 0.10, "avg_loss": -0.08}
        rebuilt = {"winrate": 0.54, "avg_gain": 0.10, "avg_loss": -0.08}
        view = kelly_view(prior, rebuilt)
        assert "无潜在边界跨越" in view["latent_impact"]
