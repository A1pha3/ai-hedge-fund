"""R213 Op1 — trial_capacity_fit_diagnostic hermetic 测试 (零宿主 data/ 读取).

fit 谓词的 oracle 一致性直接以 kernel size_portfolio 独立构造对照 (不调用
fits_trial), 包络默认值对 scripts/v3_trial_session.py 官方 SizingConfig
字面量与封存 policy fraction 钉死漂移。
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pandas as pd
import pytest

from scripts import trial_capacity_fit_diagnostic as mod
from scripts.winrate_payoff_decomposition import ROUNDTRIP_COST
from src.screening.offensive.v3.kernel.models import RawCandidate
from src.screening.offensive.v3.kernel.sizing import size_portfolio

REPO_ROOT = Path(__file__).resolve().parents[1]


def genesis_envelope(**overrides) -> mod.TrialEnvelope:
    kwargs = dict(
        nav_cents=10_000_000,
        portfolio_cap_fraction=0.02,
        per_ticker_gross_cap_cents=200_000,
        per_industry_gross_cap_cents=300_000,
        per_day_gross_cap_cents=500_000,
        worst_case_fee_ppm=3_000,
        lot_units=100,
    )
    kwargs.update(overrides)
    return mod.TrialEnvelope(**kwargs)


def _oracle_fit(price_cny: float, envelope: mod.TrialEnvelope) -> tuple[bool, str | None]:
    """测试内独立构造的 size_portfolio 调用 (与 fits_trial 同语义), 作 oracle。"""
    cap = envelope.portfolio_cap_cents
    probe = mod._probe_candidate("oracle-probe", cap)
    lines = size_portfolio(
        ranked_candidates=(probe,),
        adjusted_target_gross_by_lineage={mod.PROBE_LINEAGE_ID: cap},
        price_micros_by_candidate={"oracle-probe": round(price_cny * 1_000_000)},
        industry_by_candidate={"oracle-probe": "oracle"},
        available_cash_cents=envelope.nav_cents,
        config=envelope._sizing_config(),
        adjusted_portfolio_gross_cap_cents=cap,
        existing_portfolio_gross_cents=0,
    )
    line = lines[0]
    if line.status == "ENTRY_PLANNED":
        return True, None
    reason = line.block_reason
    return False, str(getattr(reason, "value", reason))


def test_fit_matches_independent_oracle_on_price_grid():
    envelope = genesis_envelope()
    grid = [1.0, 5.0, 10.0, 15.0, 19.99, 20.0, 20.01, 50.0, 123.45, 1000.0]
    for price in grid:
        assert mod.fits_trial(price, envelope) == _oracle_fit(price, envelope)


def test_lot_boundary_at_genesis_cap():
    envelope = genesis_envelope()
    fit_hi, reason_hi = mod.fits_trial(20.00, envelope)
    assert fit_hi is True and reason_hi is None
    fit_over, reason_over = mod.fits_trial(20.01, envelope)
    assert fit_over is False
    assert reason_over == "LOT_FLOOR_ZERO"


def test_per_ticker_cap_binds_when_below_portfolio_cap():
    envelope = genesis_envelope(per_ticker_gross_cap_cents=150_000)
    assert mod.fits_trial(15.00, envelope)[0] is True
    fit, reason = mod.fits_trial(15.01, envelope)
    assert fit is False and reason == "LOT_FLOOR_ZERO"


def test_scaled_envelope_raises_threshold():
    envelope = genesis_envelope()
    assert mod.fits_trial(21.0, envelope)[0] is False
    scaled = envelope.scaled(2.0)
    assert scaled.portfolio_cap_cents == 400_000
    assert mod.fits_trial(21.0, scaled)[0] is True


def test_invalid_envelope_and_scale_fail_closed():
    with pytest.raises(SystemExit):
        genesis_envelope(nav_cents=0)
    with pytest.raises(SystemExit):
        genesis_envelope(portfolio_cap_fraction=0.0)
    with pytest.raises(SystemExit):
        genesis_envelope(per_ticker_gross_cap_cents=-1)
    with pytest.raises(SystemExit):
        genesis_envelope().scaled(0.0)
    with pytest.raises(SystemExit):
        mod.fits_trial(0.0, genesis_envelope())


def _synthetic_universe() -> pd.DataFrame:
    """4 候选 2 日: p10 fit/p30 不 fit × {normal, crisis}; 畸形价 1 行。"""
    return pd.DataFrame(
        {
            "symbol": ["A", "B", "C", "D", "E"],
            "signal_date": ["2026-09-01", "2026-09-01", "2026-09-02", "2026-09-02", "2026-09-02"],
            "regime": ["normal", "crisis", "normal", "crisis", "crisis"],
            "signal_close": [10.0, 30.0, 12.0, 25.0, float("nan")],
            "gross_ret_t10": [0.10, -0.05, 0.20, -0.02, 0.30],
        }
    )


def test_analyze_counts_and_net_conversion():
    payload = mod.analyze(_synthetic_universe(), genesis_envelope())
    # 畸形价排除 1 行 → 4 有效候选, fit = {A, C} → 2/4
    assert payload["n_candidates"] == 4
    assert payload["n_price_invalid_excluded"] == 1
    assert payload["candidate_fit_rate"] == 0.5
    # 两个信号日各含 ≥1 fit → 日 fit 率 1.0
    assert payload["n_days"] == 2
    assert payload["day_fit_rate"] == 1.0
    # regime 分拆: blocked = {B, D} 全不 fit; normal = {A, C} 全 fit
    assert payload["regime_split"]["blocked"]["n_candidates"] == 2
    assert payload["regime_split"]["blocked"]["n_fit"] == 0
    assert payload["regime_split"]["normal"]["candidate_fit_rate"] == 1.0
    # 净收益换算: fitted gross {0.10, 0.20} → net {0.10-c, 0.20-c}
    expected = (0.10 - ROUNDTRIP_COST + 0.20 - ROUNDTRIP_COST) / 2
    got = payload["fitted_stats"]["expectancy"]
    assert got is not None and math.isclose(got, expected, rel_tol=1e-9)
    assert payload["not_fitted_stats"]["n"] == 2
    # 单手可成交价上界 = 组合上限/整手/100
    assert payload["envelope"]["single_lot_max_price_cny"] == 20.0


def test_small_n_clusters_disclosed_not_judged():
    payload = mod.analyze(_synthetic_universe(), genesis_envelope())
    assert payload["n_candidates"] < mod.MIN_CELL_N
    assert payload["fitted_stats"]["cluster_ci_low_90"] is None
    assert payload["not_fitted_stats"]["cluster_ci_low_90"] is None


def test_what_if_scale_monotone_and_formula():
    prices = [10.0, 30.0, 50.0, 70.0, 90.0]
    frame = pd.DataFrame(
        {
            "symbol": [f"T{i}" for i in range(len(prices))],
            "signal_date": ["2026-09-01"] * len(prices),
            "regime": ["normal"] * len(prices),
            "signal_close": prices,
            "gross_ret_t10": [0.0] * len(prices),
        }
    )
    scales = (1.0, 5.0, 20.0)
    payload = mod.analyze(frame, genesis_envelope(), scales)
    rates = [w["candidate_fit_rate"] for w in payload["what_if"]]
    assert rates == sorted(rates)
    assert payload["what_if"][-1]["candidate_fit_rate"] == 1.0  # ¥400 上界
    for w, s in zip(payload["what_if"], scales):
        assert w["scale"] == s
        assert w["portfolio_cap_cents"] == int(10_000_000 * s * 0.02)
        assert w["single_lot_max_price_cny"] == round(
            w["portfolio_cap_cents"] / 100 / 100.0, 2
        )


def test_single_implementation_imports_pinned():
    from src.screening.offensive.v3.kernel import sizing
    from src.screening.offensive.v3.kernel import models as kernel_models
    from scripts import winrate_payoff_decomposition as wr

    assert mod.size_portfolio is sizing.size_portfolio
    assert mod.SizingConfig is sizing.SizingConfig
    assert mod.RawCandidate is kernel_models.RawCandidate
    assert mod.production_aligned is wr.production_aligned
    assert mod.net_returns is wr.net_returns
    assert mod.win_loss_stats is wr.win_loss_stats
    assert mod.MIN_CELL_N is wr.MIN_CELL_N


def test_envelope_defaults_pinned_to_official_trial_cli():
    source = (REPO_ROOT / "scripts" / "v3_trial_session.py").read_text(
        encoding="utf-8"
    )
    for literal in (
        "per_ticker_gross_cap_cents=200_000",
        "per_industry_gross_cap_cents=300_000",
        "per_day_gross_cap_cents=500_000",
        "worst_case_fee_ppm=3_000",
    ):
        assert literal in source, f"official sizing literal drifted: {literal}"
    assert mod.DEFAULT_PER_TICKER_GROSS_CAP_CENTS == 200_000
    assert mod.DEFAULT_PER_INDUSTRY_GROSS_CAP_CENTS == 300_000
    assert mod.DEFAULT_PER_DAY_GROSS_CAP_CENTS == 500_000
    assert mod.DEFAULT_WORST_CASE_FEE_PPM == 3_000
    assert mod.DEFAULT_LOT_UNITS == 100
    trial_params = json.loads(
        (
            REPO_ROOT / "config" / "trials" / "trial-btst-regime-r1-params.json"
        ).read_text(encoding="utf-8")
    )

    def _collect_fractions(node) -> list[float]:
        found: list[float] = []
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "portfolio_gross_cap":
                    found.append(float(value))
                else:
                    found.extend(_collect_fractions(value))
        elif isinstance(node, list):
            for item in node:
                found.extend(_collect_fractions(item))
        return found

    fractions = _collect_fractions(trial_params)
    assert fractions and set(fractions) == {mod.DEFAULT_PORTFOLIO_CAP_FRACTION}


def test_render_md_disclosures_and_empty_subset_guard():
    payload = mod.analyze(_synthetic_universe(), genesis_envelope())
    md = mod.render_md(payload)
    assert "上界" in md
    assert "signal_close" in md
    assert "只披露" in md
    assert "owner" in md
    assert "| scale |" in md
    assert "候选级" in md  # SELECTED 集解读线
    # 混合 regime 合成帧含 crisis 行 → 退化披露不出现 (条件渲染)
    assert "post-regime-gate" not in md
    # 全 normal 帧 (镜像 production_aligned 的 post-gate 性质) → 退化披露出现
    all_normal = _synthetic_universe()
    all_normal["regime"] = "normal"
    assert "post-regime-gate" in mod.render_md(mod.analyze(all_normal, genesis_envelope()))
    # 全 fit 反事实: not-fitted 子集为空 → 中位价渲染为 — 而非 None
    tiny = pd.DataFrame(
        {
            "symbol": ["A"],
            "signal_date": ["2026-09-01"],
            "regime": ["normal"],
            "signal_close": [10.0],
            "gross_ret_t10": [0.05],
        }
    )
    all_fit = mod.analyze(tiny, genesis_envelope())
    assert all_fit["not_fitted_median_price_cny"] is None
    assert "¥None" not in mod.render_md(all_fit)


def test_missing_columns_fail_closed():
    frame = _synthetic_universe().drop(columns=["gross_ret_t10"])
    with pytest.raises(SystemExit) as excinfo:
        mod.analyze(frame, genesis_envelope())
    assert "missing_columns" in str(excinfo.value)


def test_empty_universe_fail_closed():
    frame = _synthetic_universe()
    frame["signal_close"] = float("nan")
    with pytest.raises(SystemExit) as excinfo:
        mod.analyze(frame, genesis_envelope())
    assert "empty_universe" in str(excinfo.value)


def test_cli_help_exits_zero():
    with pytest.raises(SystemExit) as excinfo:
        mod.main(["--help"])
    assert excinfo.value.code == 0


def test_probe_candidate_is_kernel_raw_candidate_shape():
    probe = mod._probe_candidate("p1", 123)
    assert isinstance(probe, RawCandidate)
    assert probe.unscaled_target_gross_cents == 123
    assert probe.candidate_id == "p1"
