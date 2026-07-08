from __future__ import annotations

import json


def _write_journal(path, records):
    path.write_text(
        "\n".join(json.dumps(rec, ensure_ascii=False) for rec in records) + "\n",
        encoding="utf-8",
    )


def test_summarize_setup_performance_from_closed_trades(tmp_path):
    """Evaluator must use EXIT realized P&L, not BUY counts or hardcoded priors."""
    from src.screening.offensive.setup_performance import summarize_setup_performance

    journal = tmp_path / "journal.jsonl"
    _write_journal(
        journal,
        [
            {"date": "20260701", "ticker": "000001", "setup": "btst_breakout", "action": "BUY"},
            {
                "date": "20260701",
                "ticker": "000001",
                "setup": "btst_breakout",
                "action": "EXIT",
                "reasoning": "T+10 到期平仓; realized=+10.00%; stop_would_trigger=False",
            },
            {
                "date": "20260702",
                "ticker": "000002",
                "setup": "btst_breakout",
                "action": "EXIT",
                "reasoning": "T+10 到期平仓; realized=-4.00%; stop_would_trigger=False",
            },
            {
                "date": "20260703",
                "ticker": "000003",
                "setup": "oversold_bounce",
                "action": "EXIT",
                "reasoning": "T+5 到期平仓; realized=+1.00%; stop_would_trigger=False",
            },
            {"date": "20260704", "ticker": "000004", "setup": "btst_breakout", "action": "EXIT"},
        ],
    )

    result = summarize_setup_performance(journal)

    btst = result.by_setup["btst_breakout"]
    assert btst.n == 2
    assert btst.winrate == 0.5
    assert abs(btst.expected_return - 0.03) < 1e-12
    assert abs(btst.avg_gain - 0.10) < 1e-12
    assert abs(btst.avg_loss - (-0.04)) < 1e-12

    oversold = result.by_setup["oversold_bounce"]
    assert oversold.n == 1
    assert oversold.winrate == 1.0
    assert abs(oversold.expected_return - 0.01) < 1e-12


def test_summarize_setup_performance_splits_by_regime(tmp_path):
    """Regime sizing decisions need actual setup performance by market regime."""
    from src.screening.offensive.setup_performance import summarize_setup_performance

    journal = tmp_path / "journal.jsonl"
    _write_journal(
        journal,
        [
            {
                "date": "20260701",
                "ticker": "000001",
                "setup": "btst_breakout",
                "action": "EXIT",
                "reasoning": "T+10 到期平仓; realized=+12.00%; stop_would_trigger=False",
            },
            {
                "date": "20260702",
                "ticker": "000002",
                "setup": "btst_breakout",
                "action": "EXIT",
                "reasoning": "T+10 到期平仓; realized=-6.00%; stop_would_trigger=False",
            },
            {
                "date": "20260703",
                "ticker": "000003",
                "setup": "btst_breakout",
                "action": "EXIT",
                "reasoning": "T+10 到期平仓; realized=+3.00%; stop_would_trigger=False",
            },
        ],
    )

    result = summarize_setup_performance(
        journal,
        regimes_by_date={"20260701": "crisis", "20260702": "crisis", "20260703": "normal"},
    )

    by_regime = result.by_setup["btst_breakout"].by_regime
    assert by_regime["crisis"].n == 2
    assert by_regime["crisis"].winrate == 0.5
    assert abs(by_regime["crisis"].expected_return - 0.03) < 1e-12
    assert by_regime["normal"].n == 1
    assert by_regime["normal"].winrate == 1.0
