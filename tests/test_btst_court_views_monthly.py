"""btst_court_views 月度×regime 聚合视图测试 (固化临时聚合, 口径显式).

口径契约 (与 views.main 的 traded band 一致):
- band = eligible (非 degraded/industry_missing/st_name/excluded_ticker, price_ge_3)
        ∩ fillable ∩ trigger_strength>=0.5;
- gate_on = band 剔除 gate_blocked; gate_off = band 全量;
- 收益 = gross_ret_t10 - (2*30bps + 5bps)/1e4 (净口径, 同 net_ret);
- 分组键 = signal_date 前 6 位 (YYYYMM); 缺失/非有限收益行排除且 n 如实;
- regime 拆层: total/normal/crisis/risk_off, 空层输出 n=0。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from btst_court_views import monthly_by_regime  # noqa: E402

NET_COST = (2 * 30.0 + 5.0) / 1e4


def _row(signal_date: str, regime: str = "normal", **overrides) -> dict:
    base = {
        "symbol": "600000",
        "signal_date": signal_date,
        "regime": regime,
        "trigger_strength": 0.7,
        "fillable": True,
        "t1_unbuyable": False,
        "t1_missing_bar": False,
        "degraded": False,
        "industry_missing": False,
        "st_name": False,
        "excluded_ticker": False,
        "price_ge_3": True,
        "gate_blocked": False,
        "gross_ret_t10": 0.10,
    }
    base.update(overrides)
    return base


def test_monthly_buckets_gate_split_and_regime_layers():
    table = pd.DataFrame(
        [
            _row("20260310", regime="normal", gross_ret_t10=0.10),
            _row("20260320", regime="crisis", gross_ret_t10=-0.05),
            _row("20260405", regime="normal", gross_ret_t10=0.02, gate_blocked=True),  # gate 拦下
            _row("20260406", regime="risk_off", gross_ret_t10=-0.04),
        ]
    )
    out = monthly_by_regime(table)

    assert set(out.keys()) == {"202603", "202604"}
    mar = out["202603"]
    assert mar["gate_on"]["total"]["n"] == 2
    assert mar["gate_on"]["total"]["mean"] == pytest.approx(((0.10 - NET_COST) + (-0.05 - NET_COST)) / 2)
    assert mar["gate_on"]["total"]["winrate"] == pytest.approx(0.5)
    assert mar["gate_on"]["crisis"]["n"] == 1
    assert mar["gate_on"]["crisis"]["mean"] == pytest.approx(-0.05 - NET_COST)
    assert mar["gate_on"]["risk_off"]["n"] == 0  # 空层显式 n=0, 不静默缺键
    apr = out["202604"]
    assert apr["gate_on"]["total"]["n"] == 1  # gate 拦掉 normal 那笔
    assert apr["gate_on"]["total"]["mean"] == pytest.approx(-0.04 - NET_COST)
    assert apr["gate_off"]["total"]["n"] == 2  # 对照列保留被拦事件
    assert apr["gate_off"]["normal"]["mean"] == pytest.approx(0.02 - NET_COST)


def test_missing_return_rows_excluded_and_n_honest():
    table = pd.DataFrame(
        [
            _row("20260310", gross_ret_t10=0.10),
            _row("20260311", gross_ret_t10=float("nan")),
        ]
    )
    out = monthly_by_regime(table)
    total = out["202603"]["gate_on"]["total"]
    assert total["n"] == 1
    assert total["mean"] == pytest.approx(0.10 - NET_COST)


def test_month_boundary_signal_dates_split():
    table = pd.DataFrame(
        [
            _row("20250731"),
            _row("20250801"),
        ]
    )
    out = monthly_by_regime(table)
    assert out["202507"]["gate_on"]["total"]["n"] == 1
    assert out["202508"]["gate_on"]["total"]["n"] == 1


def test_traded_band_filters_apply():
    table = pd.DataFrame(
        [
            _row("20260310", degraded=True, gross_ret_t10=0.99),
            _row("20260311", st_name=True, gross_ret_t10=0.99),
            _row("20260312", industry_missing=True, gross_ret_t10=0.99),
            _row("20260313", excluded_ticker=True, gross_ret_t10=0.99),
            _row("20260314", price_ge_3=False, gross_ret_t10=0.99),
            _row("20260315", fillable=False, gross_ret_t10=0.99),
            _row("20260316", trigger_strength=0.30, gross_ret_t10=0.99),
            _row("20260317", gross_ret_t10=0.10),  # 唯一入带
        ]
    )
    out = monthly_by_regime(table)
    total = out["202603"]["gate_on"]["total"]
    assert total["n"] == 1
    assert total["mean"] == pytest.approx(0.10 - NET_COST)


def test_months_without_data_absent_and_empty_table_safe():
    assert monthly_by_regime(pd.DataFrame([_row("20260310")])).keys() == {"202603"}
    empty = pd.DataFrame([_row("20260310", gross_ret_t10=float("nan"))])
    # 全部收益缺失 → 无任何月输出, 不崩
    assert monthly_by_regime(empty) == {}


# ---- Round C: 消费侧新鲜度守卫 ----

from datetime import date  # noqa: E402

from btst_court_views import freshness_line, freshness_problems  # noqa: E402
from review_btst_prior_court import table_freshness  # noqa: E402


def _fresh(built_at: str, manifest_sha: str, cur_sha: str, today: date) -> dict:
    return table_freshness(
        {"built_at": built_at, "formula_fingerprint": {"btst_breakout_sha256": manifest_sha}},
        cur_sha,
        today,
    )


def test_freshness_line_match_vs_drift():
    today = date(2026, 8, 18)
    ok = _fresh("2026-08-15", "a" * 64, "a" * 64, today)
    line = freshness_line(ok)
    assert "表龄 3 天" in line and "公式指纹一致" in line and "⚠" not in line
    drift = _fresh("2026-08-15", "a" * 64, "b" * 64, today)
    dline = freshness_line(drift)
    assert "⚠" in dline and "公式漂移" in dline and "btst_court_build" in dline


def test_freshness_problems_boundaries():
    today = date(2026, 10, 1)  # 2026-08-17 → 45 天; 2026-08-16 → 46 天
    ok45 = _fresh("2026-08-17", "a" * 64, "a" * 64, today)
    assert freshness_problems(ok45) == []
    stale46 = _fresh("2026-08-16", "a" * 64, "a" * 64, today)
    assert any("表龄" in p for p in freshness_problems(stale46))
    drift = _fresh("2026-08-17", "a" * 64, "b" * 64, today)
    assert any("公式漂移" in p for p in freshness_problems(drift))


def test_freshness_problems_missing_manifest():
    none = table_freshness(None, "a" * 64, date(2026, 8, 18))
    assert any("manifest" in p for p in freshness_problems(none))


class TestRngDeterminism:
    """R14 同族审查: btst_court_views 模块级 RNG 两个消费点 (CI + cliff
    permutation) 的 per-call 确定性 — 镜像 winrate 工具 R13 修复纪律。"""

    def _ev(self, n=200, seed=3):
        import numpy as np
        rng = np.random.default_rng(seed)
        return pd.DataFrame({
            "signal_date": [f"2026-03-{(i % 20) + 1:02d}" for i in range(n)],
            "regime": ["normal" if i % 5 else "crisis" for i in range(n)],
            "gross_ret_t5": list(rng.normal(0.004, 0.05, n)),
            "gross_ret_t10": list(rng.normal(0.006, 0.10, n)),
            "gap_t1_open": list(rng.normal(0.01, 0.03, n)),
        })

    def test_cluster_boot_ci_repeatable(self):
        import numpy as np
        from btst_court_views import cluster_boot_ci_low
        ev = self._ev()
        diffs = ev["gross_ret_t10"] - ev["gross_ret_t5"]
        ci1 = cluster_boot_ci_low(diffs, ev["signal_date"])
        junk = cluster_boot_ci_low(
            pd.Series(np.random.default_rng(9).normal(0, 0.01, 60)),
            pd.Series([f"j{i%6}" for i in range(60)]),
        )  # 预消耗 (若仍依赖全局态, 此后漂移)
        ci2 = cluster_boot_ci_low(diffs, ev["signal_date"])
        assert ci1 == ci2

    def test_q3_gap_repeatable(self):
        from btst_court_views import q3_gap
        ev = self._ev()
        a = q3_gap(ev)
        b = q3_gap(ev)
        assert a == b  # 含 cliff permutation p 值, 与调用历史无关
