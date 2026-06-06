from __future__ import annotations

import json
from pathlib import Path

import scripts.analyze_btst_monthly_zero_pick_promotion_counterfactual as cf


def test_analyze_btst_monthly_zero_pick_promotion_counterfactual_promotes_when_zero_pick(tmp_path: Path, monkeypatch) -> None:
    reports_dir = tmp_path / "data" / "reports"
    reports_dir.mkdir(parents=True)

    plan_dir = reports_dir / "paper_trading_20260506_20260506_live_test_short_trade_only_20260506_plan"
    plan_dir.mkdir(parents=True)

    (plan_dir / "btst_next_day_trade_brief_latest.json").write_text(
        json.dumps(
            {
                "trade_date": "2026-05-06",
                "selected_entries": [],
                "near_miss_entries": [
                    {
                        "ticker": "000001",
                        "score_target": 0.49,
                        "gate_status": {"committee": "pass", "execution": "proxy_only"},
                        "historical_prior": {"prior_evidence_count": 30, "effective_next_close_positive_rate": 0.9},
                    },
                    {
                        "ticker": "000002",
                        "score_target": 0.6,
                        "gate_status": {"committee": "shadow_only", "execution": "proxy_only"},
                        "historical_prior": {"prior_evidence_count": 99, "effective_next_close_positive_rate": 0.99},
                    },
                ],
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    def _fake_realized_prices(*, signal_date: str, tickers: list[str]):  # noqa: ANN001
        assert signal_date == "2026-05-06"
        assert tickers == ["000001"]
        return {
            "000001": {
                "data_status": "ok",
                "next_close_return": 0.01,
                "next_open_to_close_return": 0.02,
                "max_high_t1_t5_from_open": 0.2,
            }
        }

    monkeypatch.setattr(cf, "generate_realized_prices", _fake_realized_prices)

    analysis = cf.analyze_btst_monthly_zero_pick_promotion_counterfactual(month="202605", reports_dir=reports_dir)
    overall = analysis["overall"]

    assert overall["zero_pick_day_count"] == 1
    assert overall["promoted_day_count"] == 1
    assert overall["promoted_only"]["pick_count"] == 1
    assert overall["promoted_only"]["win_rate_next_close_gt_0"] == 1.0
    assert overall["combined"]["pick_count"] == 1

    md = cf.render_btst_monthly_zero_pick_promotion_counterfactual_markdown(analysis)
    assert "BTST Zero-pick Promotion Counterfactual 202605" in md
    assert "promotion filter" in md
