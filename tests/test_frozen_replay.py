from __future__ import annotations

import json
from pathlib import Path

from src.paper_trading.frozen_replay import (
    _build_recent_generated_buy_blocks,
    load_frozen_post_market_plans,
    replay_frozen_post_market_sequence,
)


def test_load_frozen_post_market_plans_backfills_missing_plan_date_from_trade_date(tmp_path) -> None:
    source_path = tmp_path / "daily_events.jsonl"
    source_path.write_text(
        json.dumps(
            {
                "event": "paper_trading_day",
                "trade_date": "20260421",
                "current_plan": {
                    "market_state": {
                        "breadth_ratio": 0.66,
                        "daily_return": -0.004,
                        "style_dispersion": 0.18,
                        "regime_flip_risk": 0.08,
                        "regime_gate_level": "normal",
                    }
                },
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    plans = load_frozen_post_market_plans(source_path)

    assert plans["20260421"].date == "20260421"
    assert plans["20260421"].market_state.regime_gate_level == "normal"


def test_replay_frozen_post_market_sequence_carries_recent_formal_buy_block(tmp_path) -> None:
    source_path = tmp_path / "daily_events.jsonl"
    source_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "event": "paper_trading_day",
                        "trade_date": "20260421",
                        "current_plan": {
                            "date": "20260421",
                            "buy_orders": [
                                {
                                    "ticker": "300724",
                                    "shares": 100,
                                    "amount": 12000.0,
                                    "score_final": 0.52,
                                    "execution_ratio": 0.3,
                                }
                            ],
                            "watchlist": [
                                {
                                    "ticker": "300724",
                                    "score_c": -0.05,
                                    "score_final": 0.52,
                                    "score_b": 0.43,
                                    "decision": "watch",
                                }
                            ],
                            "portfolio_snapshot": {"cash": 500000.0, "positions": {}},
                            "risk_metrics": {
                                "counts": {"watchlist_count": 1, "buy_order_count": 1},
                                "funnel_diagnostics": {"filters": {"buy_orders": {"filtered_count": 0, "reason_counts": {}, "tickers": [], "selected_tickers": ["300724"]}}},
                            },
                        },
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "event": "paper_trading_day",
                        "trade_date": "20260422",
                        "current_plan": {
                            "date": "20260422",
                            "buy_orders": [
                                {
                                    "ticker": "300724",
                                    "shares": 100,
                                    "amount": 12000.0,
                                    "score_final": 0.54,
                                    "execution_ratio": 0.3,
                                }
                            ],
                            "watchlist": [
                                {
                                    "ticker": "300724",
                                    "score_c": -0.04,
                                    "score_final": 0.54,
                                    "score_b": 0.45,
                                    "decision": "watch",
                                }
                            ],
                            "portfolio_snapshot": {"cash": 500000.0, "positions": {}},
                            "risk_metrics": {
                                "counts": {"watchlist_count": 1, "buy_order_count": 1},
                                "funnel_diagnostics": {"filters": {"buy_orders": {"filtered_count": 0, "reason_counts": {}, "tickers": [], "selected_tickers": ["300724"]}}},
                            },
                        },
                    },
                    ensure_ascii=False,
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    plans = replay_frozen_post_market_sequence(
        source_path,
        target_mode="short_trade_only",
        base_model_name="gpt-4.1",
        base_model_provider="OpenAI",
    )

    assert [order.ticker for order in plans["20260421"].buy_orders] == ["300724"]
    assert plans["20260422"].buy_orders == []
    assert plans["20260422"].risk_metrics["funnel_diagnostics"]["filters"]["buy_orders"]["reason_counts"] == {"blocked_by_exit_cooldown": 1}
    assert plans["20260422"].risk_metrics["funnel_diagnostics"]["filters"]["buy_orders"]["tickers"][0]["trigger_reason"] == "recent_formal_buy_cooldown"


def test_replay_frozen_post_market_sequence_strips_stale_buy_order_filter_summary(tmp_path) -> None:
    source_path = tmp_path / "daily_events.jsonl"
    source_path.write_text(
        json.dumps(
            {
                "event": "paper_trading_day",
                "trade_date": "20260421",
                "current_plan": {
                    "date": "20260421",
                    "buy_orders": [],
                    "watchlist": [],
                    "portfolio_snapshot": {"cash": 500000.0, "positions": {}},
                    "risk_metrics": {
                        "counts": {"watchlist_count": 0, "buy_order_count": 0},
                        "funnel_diagnostics": {
                            "filters": {
                                "buy_orders": {
                                    "filtered_count": 1,
                                    "reason_counts": {"blocked_by_exit_cooldown": 1},
                                    "tickers": [{"ticker": "300724", "reason": "blocked_by_exit_cooldown", "trigger_reason": "recent_formal_buy_cooldown"}],
                                    "selected_tickers": [],
                                }
                            }
                        },
                    },
                },
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    plans = replay_frozen_post_market_sequence(
        source_path,
        target_mode="short_trade_only",
        base_model_name="gpt-4.1",
        base_model_provider="OpenAI",
    )

    assert plans["20260421"].risk_metrics["funnel_diagnostics"]["filters"]["buy_orders"] == {
        "filtered_count": 0,
        "reason_counts": {},
        "tickers": [],
        "selected_tickers": [],
    }


def test_load_frozen_post_market_plans_hydrates_sparse_replay_watchlist_signals_from_selection_snapshot(tmp_path) -> None:
    source_path = tmp_path / "daily_events.jsonl"
    selection_dir = tmp_path / "selection_artifacts" / "2026-04-21"
    selection_dir.mkdir(parents=True)
    source_path.write_text(
        json.dumps(
            {
                "event": "paper_trading_day",
                "trade_date": "20260421",
                "current_plan": {
                    "date": "20260421",
                    "watchlist": [],
                    "portfolio_snapshot": {"cash": 500000.0, "positions": {}},
                    "risk_metrics": {},
                },
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    (selection_dir / "selection_target_replay_input.json").write_text(
        json.dumps(
            {
                "watchlist": [
                    {
                        "ticker": "300054",
                        "score_b": 0.51,
                        "score_c": 0.42,
                        "score_final": 0.58,
                        "quality_score": 0.71,
                        "decision": "watch",
                        "candidate_source": "layer_c_watchlist",
                        "strategy_signals": {},
                        "agent_contribution_summary": {},
                        "metrics": {"canonical_btst_evaluation_bundle": {}},
                    }
                ],
                "rejected_entries": [],
                "supplemental_short_trade_entries": [],
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    (selection_dir / "selection_snapshot.json").write_text(
        json.dumps(
            {
                "funnel_diagnostics": {
                    "filters": {
                        "watchlist": {
                            "tickers": [
                                {
                                    "ticker": "300054",
                                    "strategy_signals": {
                                        "trend": {
                                            "direction": 1,
                                            "confidence": 68.0,
                                            "completeness": 1.0,
                                            "sub_factors": {
                                                "ema_alignment": {"direction": 1, "confidence": 84.0, "completeness": 1.0}
                                            },
                                        }
                                    },
                                    "agent_contribution_summary": {"cohort_contributions": {"analyst": 0.44}},
                                }
                            ]
                        }
                    }
                }
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    plans = load_frozen_post_market_plans(source_path)

    replay_input = plans["20260421"].risk_metrics["frozen_selection_target_replay_input"]
    watchlist_row = replay_input["watchlist"][0]
    assert watchlist_row["ticker"] == "300054"
    assert watchlist_row["strategy_signals"]["trend"]["direction"] == 1


def test_replay_frozen_post_market_sequence_preserves_execution_eligibility_for_original_buy_orders() -> None:
    source_path = (
        Path(__file__).resolve().parents[1]
        / "data/reports/paper_trading_20260522_20260522_live_m2_7_short_trade_only_20260525_plan/daily_events.jsonl"
    )

    plans = replay_frozen_post_market_sequence(
        source_path,
        target_mode="short_trade_only",
        base_model_name="gpt-4.1",
        base_model_provider="OpenAI",
        short_trade_target_profile_name="momentum_optimized",
        short_trade_target_profile_overrides={"select_threshold": 0.5},
        clear_existing_buy_orders=True,
    )

    replayed_plan = plans["20260522"]
    # After layer_c_watchlist shadow profile rollout (commit 0f07447c), tickers sourced
    # from layer_c_watchlist have rank_cap=0 in short_trade_only routing, so they get
    # `selected_rank_cap_exceeded` rejection at the short_trade layer even when the
    # research layer selects them. The outer execution_eligible follows short_trade
    # for target_mode=short_trade_only.
    for ticker in ("300054", "002222"):
        ev = replayed_plan.selection_targets[ticker]
        assert ev.research.decision == "selected", f"{ticker}: research should still select"
        assert ev.research.execution_eligible is True, f"{ticker}: research should be execution_eligible"
        assert ev.short_trade.decision == "rejected", f"{ticker}: short_trade rejects due to layer_c_watchlist rank_cap"
        assert ev.short_trade.execution_eligible is False, f"{ticker}: short_trade is not execution_eligible"
        assert ev.execution_eligible is False, f"{ticker}: outer follows short_trade in short_trade_only mode"
        assert ev.delta_classification == "research_pass_short_reject"
        assert "selected_rank_cap_exceeded" in (ev.short_trade.blockers or []), (
            f"{ticker}: rejection reason must be the documented rank_cap blocker"
        )


def test_build_recent_generated_buy_blocks_skips_malformed_dates() -> None:
    """Malformed current_trade_date or buy_trade_date entries must not
    crash the replay — they should be silently skipped so a single bad
    row can't take down the entire frozen replay session.
    """
    # Malformed current_trade_date -> empty dict (no crash).
    assert _build_recent_generated_buy_blocks(
        latest_buy_trade_by_ticker={"300724": "20260420"},
        current_trade_date="not-a-date",
    ) == {}

    # Malformed buy_trade_date rows are skipped while well-formed rows
    # in the cooldown window still produce blocks.
    blocks = _build_recent_generated_buy_blocks(
        latest_buy_trade_by_ticker={
            "300724": "20260420",          # valid, within cooldown
            "600519": "garbage",            # invalid -> skipped
            "000001": "",                   # invalid -> skipped
            "999999": "20260301",           # out of cooldown -> skipped
        },
        current_trade_date="20260421",
        cooldown_calendar_days=2,
    )

    assert list(blocks.keys()) == ["300724"]
    assert blocks["300724"]["trigger_reason"] == "recent_formal_buy_cooldown"
    assert blocks["300724"]["exit_trade_date"] == "20260420"


def _write_minimal_plan_line(path: Path, trade_date: str = "20260421") -> None:
    """Helper: append one minimal valid plan record to daily_events.jsonl."""
    with path.open("a", encoding="utf-8") as fh:
        fh.write(
            json.dumps(
                {
                    "event": "paper_trading_day",
                    "trade_date": trade_date,
                    "current_plan": {
                        "date": trade_date,
                        "market_state": {
                            "breadth_ratio": 0.5,
                            "daily_return": 0.0,
                            "style_dispersion": 0.1,
                            "regime_flip_risk": 0.05,
                            "regime_gate_level": "normal",
                        },
                    },
                },
                ensure_ascii=False,
            )
            + "\n"
        )


def test_load_frozen_post_market_plans_skips_corrupt_line(tmp_path, caplog) -> None:
    """R88/BH-017 family drain: a single corrupt line in daily_events.jsonl
    (partial write / interrupted process / disk error) must not crash the
    entire frozen replay load. Well-formed lines around it must still load.

    bug 复现: load_frozen_post_market_plans 用裸 json.loads(line) 解析每行;
    任一行损坏 JSONDecodeError 中断整个 replay 加载 (paper_trading 主入口
    runtime.py:359 调用), 用户回填多日 events 时一个坏行 poison 全部。
    """
    source_path = tmp_path / "daily_events.jsonl"
    _write_minimal_plan_line(source_path, "20260420")
    # corrupt line (interrupted write / disk error / hand edit)
    with source_path.open("a", encoding="utf-8") as fh:
        fh.write("{truncated:not valid json\n")
    _write_minimal_plan_line(source_path, "20260421")

    import logging

    with caplog.at_level(logging.WARNING, logger="src.paper_trading.frozen_replay"):
        plans = load_frozen_post_market_plans(source_path)

    # Both well-formed lines loaded; corrupt line skipped, not crashed.
    assert set(plans.keys()) == {"20260420", "20260421"}
    # Diagnostic warning emitted so operators can distinguish "no record"
    # from "corrupt record silently dropped".
    assert any(
        "corrupt" in rec.message.lower() or "损坏" in rec.message or "skip" in rec.message.lower()
        for rec in caplog.records
    ), [r.message for r in caplog.records]


def test_load_sidecar_replay_input_payload_tolerates_corrupt_json(tmp_path, caplog) -> None:
    """R88/BH-017 family drain: a corrupt selection_target_replay_input.json
    sidecar must degrade to {} (no replay input) instead of crashing the
    frozen replay plan loader. Paper trading writes these sidecars during
    daily runs; a partial write mid-process must not poison the next replay.

    bug 复现: _load_sidecar_replay_input_payload 用裸 json.loads(candidate_path
    .read_text()) (line 130) + json.loads(selection_snapshot_path.read_text())
    (line 133); 任一损坏 JSONDecodeError 由 caller load_frozen_post_market_plans
    传播中断整个 frozen replay。
    """
    from src.paper_trading.frozen_replay import _load_sidecar_replay_input_payload

    source_path = tmp_path / "daily_events.jsonl"
    source_path.write_text("{}", encoding="utf-8")  # placeholder source

    sel_root = tmp_path / "selection_artifacts" / "2026-04-21"
    sel_root.mkdir(parents=True)
    # corrupt replay input (partial write)
    (sel_root / "selection_target_replay_input.json").write_text(
        "{corrupt:not json", encoding="utf-8"
    )

    import logging

    with caplog.at_level(logging.WARNING, logger="src.paper_trading.frozen_replay"):
        result = _load_sidecar_replay_input_payload(source_path, "20260421")

    # Degrade to empty dict, do not crash.
    assert result == {}
    assert any(
        "corrupt" in rec.message.lower() or "损坏" in rec.message
        for rec in caplog.records
    ), [r.message for r in caplog.records]


def test_load_sidecar_prior_by_ticker_tolerates_corrupt_json(tmp_path, caplog) -> None:
    """R88/BH-017 family drain: a corrupt selection_snapshot.json sidecar
    must degrade to {} (no prior) instead of crashing the replay loader.

    bug 复现: _load_sidecar_prior_by_ticker 用裸 json.loads(candidate_path
    .read_text()) (line 56); 损坏 JSONDecodeError 由 caller 传播中断整个 replay。
    """
    from src.paper_trading.frozen_replay import _load_sidecar_prior_by_ticker

    source_path = tmp_path / "daily_events.jsonl"
    source_path.write_text("{}", encoding="utf-8")

    sel_root = tmp_path / "selection_artifacts" / "2026-04-21"
    sel_root.mkdir(parents=True)
    # corrupt snapshot (partial write)
    (sel_root / "selection_snapshot.json").write_text(
        "{corrupt:not json", encoding="utf-8"
    )

    import logging

    with caplog.at_level(logging.WARNING, logger="src.paper_trading.frozen_replay"):
        result = _load_sidecar_prior_by_ticker(source_path, "20260421")

    assert result == {}
    assert any(
        "corrupt" in rec.message.lower() or "损坏" in rec.message
        for rec in caplog.records
    ), [r.message for r in caplog.records]


def test_load_frozen_post_market_plans_partial_degradation_warns_with_counts(tmp_path, caplog) -> None:
    """R92/R88 trust-calibration family: when SOME lines are corrupt but
    valid plans still load, emit a warning naming both counts so the user
    can calibrate trust on a partially-degraded replay (vs believing the
    replay is complete). Mirrors R92 position_health degraded banner.
    """
    source_path = tmp_path / "daily_events.jsonl"
    _write_minimal_plan_line(source_path, "20260420")
    with source_path.open("a", encoding="utf-8") as fh:
        fh.write("{corrupt1:not json\n")
        fh.write("{corrupt2:not json\n")
    _write_minimal_plan_line(source_path, "20260421")

    import logging

    with caplog.at_level(logging.WARNING, logger="src.paper_trading.frozen_replay"):
        plans = load_frozen_post_market_plans(source_path)

    assert set(plans.keys()) == {"20260420", "20260421"}
    # Partial-degradation warning names both counts so user can calibrate.
    degradation_msgs = [
        r.message for r in caplog.records
        if "完整性已降级" in r.message or "degraded" in r.message.lower()
    ]
    assert degradation_msgs, [r.message for r in caplog.records]
    msg = degradation_msgs[0]
    assert "2" in msg  # 2 corrupt lines skipped
    assert "2" in msg  # 2 plans loaded


def test_load_frozen_post_market_plans_all_corrupt_raises_distinguishing_error(tmp_path) -> None:
    """R92/R88 trust-calibration family: when ALL lines are corrupt, the
    ValueError must distinguish "all corrupt (data integrity signal)" from
    "no current_plan records (file genuinely empty)" so the user knows to
    repair the file rather than re-run with the same source.
    """
    import pytest

    source_path = tmp_path / "daily_events.jsonl"
    with source_path.open("w", encoding="utf-8") as fh:
        fh.write("{corrupt1:not json\n")
        fh.write("{corrupt2:not json\n")

    with pytest.raises(ValueError) as exc_info:
        load_frozen_post_market_plans(source_path)

    msg = str(exc_info.value)
    # Distinguishing signal: mentions corruption + count + repair hint,
    # NOT the generic "No current_plan records" message.
    assert "corrupt" in msg.lower() or "损坏" in msg
    assert "2" in msg
    assert "完整性" in msg or "integrity" in msg.lower() or "重新生成" in msg or "检查" in msg
