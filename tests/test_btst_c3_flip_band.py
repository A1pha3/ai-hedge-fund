"""btst_c3_flip_band — 预注册带宽分类与两面量化的 fixture 测试."""

from __future__ import annotations

import pandas as pd

from scripts.btst_c3_flip_band import (
    C3_THRESHOLD,
    classify_pct,
    event_side,
    prescreen_side,
)


class TestClassifyPct:
    """带宽预注册语义: 2.00 边际通过, 1.99 边际拦截, 半量子归属."""

    def test_firm_pass(self):
        assert classify_pct(2.01) == "firm_pass"
        assert classify_pct(4.77) == "firm_pass"

    def test_flip_pass_exactly_200(self):
        assert classify_pct(2.00) == "flip_pass"

    def test_flip_fail_exactly_199(self):
        assert classify_pct(1.99) == "flip_fail"

    def test_firm_fail(self):
        assert classify_pct(1.98) == "firm_fail"
        assert classify_pct(1.13) == "firm_fail"
        assert classify_pct(-2.51) == "firm_fail"

    def test_unknown(self):
        assert classify_pct(None) == "unknown"

    def test_threshold_constant_frozen(self):
        assert C3_THRESHOLD == 2.0


def _events(rows):
    base = {"ts_code": [], "signal_date": [], "gross_ret_t10": []}
    for r in rows:
        base["ts_code"].append(r["ts"])
        base["signal_date"].append(r["date"])
        base["gross_ret_t10"].append(r.get("ret"))
    return pd.DataFrame(base)


class TestEventSide:
    def test_band_distribution_and_net(self):
        pct_map = {
            ("A", "20260807"): 2.00,   # flip_pass
            ("B", "20260807"): 4.77,   # firm_pass
            ("C", "20260807"): 3.00,   # firm_pass
        }
        events = _events([
            {"ts": "A.SH", "date": 20260807, "ret": 0.10},
            {"ts": "B.SZ", "date": 20260807, "ret": -0.05},
            {"ts": "C.SH", "date": 20260807, "ret": 0.20},
        ])
        out = event_side(events, lambda s, d: pct_map.get((s, d)))
        assert out["flip_pass"]["n"] == 1
        assert out["firm_pass"]["n"] == 2
        assert out["flip_pass_share_pct"] == round(100 / 3, 2)
        # flip_pass 净 E = 10 − 0.65 = 9.35
        assert out["flip_pass"]["mean_net_e_pct"] == 9.35

    def test_missing_industry_goes_other(self):
        events = _events([{"ts": "X.SH", "date": 20260807, "ret": 0.1}])
        out = event_side(events, lambda s, d: None)
        assert out["other"]["n"] == 1
        assert out["firm_pass"]["n"] == 0


class TestPrescreenSide:
    def test_limitup_band_counts(self):
        panel = pd.DataFrame(
            {
                "ts_code": ["600001.SH", "600002.SH", "600003.SH", "600004.SH", "830001.BJ", "600005.SH"],
                "trade_date": ["20260807"] * 6,
                "pct_chg": [10.0, 10.0, 10.0, 10.0, 29.0, 3.0],
            }
        )
        pct_map = {"600001": 2.00, "600002": 1.99, "600003": 3.0, "600004": 1.5}
        out = prescreen_side(panel, lambda s, d: pct_map.get(s))
        # 北交所 830001 剔除; 600005 (pct 3.0 < 9.5) 不入预筛
        assert out["n_limitup_rows"] == 4
        assert out["bands"]["flip_pass"] == 1
        assert out["bands"]["flip_fail"] == 1
        assert out["bands"]["firm_pass"] == 1
        assert out["bands"]["firm_fail"] == 1
        assert out["flip_share_of_decided_pct"] == 50.0
        assert "+1 / −1" in out["sensitivity_note"]
