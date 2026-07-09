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

    # skipped_exits: 1 EXIT record without realized marker
    assert result.skipped_exits == 1, f"expected 1 skipped, got {result.skipped_exits}"


def test_summarize_setup_performance_counts_skipped_exits(tmp_path):
    """EXIT records without parseable realized markers are counted in skipped_exits."""
    from src.screening.offensive.setup_performance import summarize_setup_performance

    journal = tmp_path / "journal.jsonl"
    _write_journal(
        journal,
        [
            {"date": "20260701", "ticker": "000001", "setup": "btst", "action": "BUY"},
            {"date": "20260701", "ticker": "000001", "setup": "btst", "action": "EXIT", "reasoning": "T+10 到期平仓; realized=+5.00%; stop_would_trigger=False"},
            {"date": "20260702", "ticker": "000002", "setup": "btst", "action": "EXIT", "reasoning": "old format, no realized marker"},
            {"date": "20260703", "ticker": "000003", "setup": "oversold", "action": "EXIT", "reasoning": "T+5 到期平仓; realized=-2.00%; stop_would_trigger=False"},
            {"date": "20260704", "ticker": "000004", "setup": "btst", "action": "EXIT"},  # no reasoning at all
        ],
    )

    result = summarize_setup_performance(journal)
    assert result.skipped_exits == 2, f"expected 2 skipped, got {result.skipped_exits}"
    assert result.by_setup["btst"].n == 1  # only the first btst EXIT has realized marker
    assert result.by_setup["oversold"].n == 1


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


# ---------------------------------------------------------------------------
# autodev-32 /loop session 6: low_confidence small-sample flag
# ---------------------------------------------------------------------------


def test_low_confidence_flag_true_below_threshold():
    """SetupPerformance with n < LOW_CONFIDENCE_N is low_confidence=True."""
    from src.screening.offensive.setup_performance import SetupPerformance

    small = SetupPerformance(n=3, winrate=1.0, expected_return=0.13, avg_gain=0.15, avg_loss=0.0)
    assert small.low_confidence is True, "n=3 < 10 should be low_confidence"


def test_low_confidence_flag_false_at_threshold():
    """SetupPerformance with n >= LOW_CONFIDENCE_N is low_confidence=False."""
    from src.screening.offensive.setup_performance import SetupPerformance

    robust = SetupPerformance(n=10, winrate=0.6, expected_return=0.05, avg_gain=0.10, avg_loss=-0.05)
    assert robust.low_confidence is False, "n=10 should NOT be low_confidence"


def test_low_confidence_flag_false_when_empty():
    """n=0 (no data) is not 'low_confidence' — it's 'no data' (different concept)."""
    from src.screening.offensive.setup_performance import SetupPerformance

    empty = SetupPerformance(n=0, winrate=0.0, expected_return=0.0, avg_gain=0.0, avg_loss=0.0)
    assert empty.low_confidence is False, "n=0 is no-data, not low-confidence noise"


def test_summarize_flags_low_confidence_regimes(tmp_path):
    """Real-data scenario: a regime with n=3 winrate=100% must be flagged low_confidence.

    Dogfood (2026-07-09 real backtest): oversold_bounce risk_off n=3 100%
    looks great but is noise. The evaluator must flag it so operators don't
    re-enable the setup based on small-sample luck.
    """
    from src.screening.offensive.setup_performance import summarize_setup_performance

    journal = tmp_path / "journal.jsonl"
    # 3 EXITs in risk_off (all wins), 12 in normal (mix)
    records = []
    for i in range(3):
        records.append({
            "date": f"2026070{i+1}", "ticker": f"00000{i}", "setup": "oversold_bounce",
            "action": "EXIT", "reasoning": f"T+5 到期平仓; realized=+{10+i}.00%",
        })
    for i in range(12):
        ret = "+5.00" if i % 2 == 0 else "-3.00"
        records.append({
            "date": f"202608{i:02d}", "ticker": f"30000{i}", "setup": "oversold_bounce",
            "action": "EXIT", "reasoning": f"T+5 到期平仓; realized={ret}%",
        })
    _write_journal(journal, records)

    result = summarize_setup_performance(
        journal,
        regimes_by_date={
            "20260701": "risk_off", "20260702": "risk_off", "20260703": "risk_off",
            **{f"202608{i:02d}": "normal" for i in range(12)},
        },
    )
    oversold = result.by_setup["oversold_bounce"]
    assert oversold.n == 15
    assert oversold.low_confidence is False  # top-level n=15 is robust
    risk_off = oversold.by_regime["risk_off"]
    assert risk_off.n == 3
    assert risk_off.winrate == 1.0
    assert risk_off.low_confidence is True, "risk_off n=3 must be flagged low_confidence"
